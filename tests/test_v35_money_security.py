"""Review round 3 (v35a): blockers, money and security fixes."""
import asyncio
import base64
import json
import os
import time
import types

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import assemblies, bls_core, estimate, money, settings  # noqa: E402
from app.collab import hub as hubmod                             # noqa: E402
from app.collab import relaycore as rc                           # noqa: E402
from app.pm import actions, bidforms, cashflow, cost, schedule   # noqa: E402
from app.pm import store as storemod                             # noqa: E402
from app.pm.store import ProjectStore                            # noqa: E402
from app.pm.usersui import temp_password                         # noqa: E402


@pytest.fixture(autouse=True)
def _cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Pat Morgan"})
    for k in ("TLS_PROXY", "BEHIND_PROXY"):
        monkeypatch.delenv(k, raising=False)


# ------------------------------------------------------------ blockers
def test_hub_get_ignores_stale_op(tmp_path):
    H = hubmod.Hub(str(tmp_path / "hub"))
    r = H.call("proj.open", {"project": "Job", "password": "pw123456",
                             "user": "Jon"}, {"ip": "10.0.0.5"}, True)
    key = r["key"]
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 20
    att = H.call("att.put", {"project": "Job", "key": key, "name": "a.png",
                             "data": base64.b64encode(png).decode()},
                 {}, True)
    H._op = "user.add"                      # left over from another call
    st, _ct, body = H.get(f"/hub/att/Job/{att['sha256']}",
                          {"Authorization": f"Bearer {key}"})
    assert (st, body) == (200, png)
    assert H._op == "att.get"


def test_project_password_needs_8(tmp_path):
    H = hubmod.Hub(str(tmp_path / "hub"))
    with pytest.raises(hubmod.HubError, match="8 or more"):
        H.call("proj.open", {"project": "J", "password": "1234567"}, {},
               True)


def test_store_save_is_debounced_and_flushed(tmp_path):
    s = ProjectStore(str(tmp_path / "p"))
    s.save()                                   # the first save is direct
    assert os.path.isfile(s.path)
    writes = []
    real = s._write
    s._write = lambda: (writes.append(1), real())
    for i in range(50):
        s.save_record("rfi", {"subject": f"q{i}"})
    assert len(writes) == 0                    # nothing yet: coalesced
    # another store opening the same file sees every record
    t = ProjectStore(str(tmp_path / "p"))
    assert len(t.list("rfi")) == 50 and len(writes) == 1
    s.set_setting("x", 1)
    time.sleep(storemod.SAVE_DELAY + 0.4)      # timer writes on its own
    assert len(writes) == 2
    with open(s.path, encoding="utf-8") as f:
        assert json.load(f)["settings"]["x"] == 1


def test_store_non_dict_json_is_set_aside(tmp_path):
    p = tmp_path / "p" / ".quantisheet"
    p.mkdir(parents=True)
    (p / "project.json").write_text("[1, 2]", encoding="utf-8")
    s = ProjectStore(str(tmp_path / "p"))
    assert s.damaged.endswith(".damaged") and s.list("rfi") == []


def test_attachment_path_is_atomic(tmp_path, monkeypatch):
    s = ProjectStore(str(tmp_path / "p"))
    s.data["hub"] = {"project": "J", "key": "k", "url": "ws://x"}

    class C:
        def call(self, op, **a):
            return {"data": base64.b64encode(b"hello").decode()}
    monkeypatch.setattr(s, "client", lambda: C())
    p = s.attachment_path({"sha256": "ab" * 32, "ext": ".txt"})
    assert open(p, "rb").read() == b"hello"
    assert not os.path.exists(p + ".tmp")


def test_attach_defer_queues_and_push_uploads(tmp_path, monkeypatch):
    s = ProjectStore(str(tmp_path / "p"))
    s.data["hub"] = {"project": "J", "key": "k", "url": "ws://x"}
    sent = []

    class C:
        def call(self, op, **a):
            sent.append((op, a["name"]))
    monkeypatch.setattr(s, "client", lambda: C())
    f = tmp_path / "photo.jpg"
    f.write_bytes(b"\xff\xd8 jpeg")
    s.attach(str(f), defer=True)
    assert sent == [] and len(s.data["att_pending"]) == 1
    s.push_attachments()
    assert sent and sent[0][0] == "att.put" and s.data["att_pending"] == []
    # no hub: nothing to do, no KeyError
    s.data["hub"] = None
    s.data["att_pending"] = ["x"]
    s.push_attachments()


def test_by_code_is_memoised_per_version(tmp_path, monkeypatch):
    s = ProjectStore(str(tmp_path / "p"))
    b = s.save_record("budget", {"cost_code": "03 30 00",
                                 "description": "Concrete",
                                 "original": 1000})
    calls = []
    real = cost._by_code
    monkeypatch.setattr(cost, "_by_code",
                        lambda st: (calls.append(1), real(st))[1])
    for _ in range(200):                       # 200 painted cells
        cost.cell(s, "budget", b, "_revised")
    assert len(calls) == 1
    s.save_record("cost", {"cost_code": "03 30 00", "amount": 1500})
    assert cost.cell(s, "budget", b, "_flag") == "Over budget"
    assert len(calls) == 2


def test_scheduler_uses_cached_cpm():
    import inspect
    from app.pm import scheduler
    src = inspect.getsource(scheduler.Scheduler.refresh) if hasattr(
        scheduler, "Scheduler") else inspect.getsource(scheduler)
    assert "schedule.cached(" in src and "schedule.compute(" not in src


# ------------------------------------------------------------ money
def _rec(lines, values):
    return {"form": lines, "bidders": [{"company": "A",
                                        "form_values": values}]}


@pytest.mark.parametrize("line,val", [
    ({"type": "Allowance", "qty": "0"}, "500"),
    ({"type": "Allowance", "qty": 0}, None),
    ({"type": "Allowance", "qty": "2,500"}, "100"),
    ({"type": "Allowance"}, "750"),
    ({"type": "Unit price", "qty": "0", "unit": "LF"}, "12"),
    ({"type": "Unit price", "qty": "10", "unit": "LF"}, "12.50"),
    ({"type": "Lump sum"}, "1,234.50"),
])
def test_allowance_and_qty_agree_with_leveling(line, val):
    line = dict(line, description="x", item="1")
    total = bidforms.line_total(line, val)
    rows = bidforms.to_leveling(_rec([line], {"0": val}))["A"]
    lev = sum((r["qty"] or 0) * (r["price"] or 0) for r in rows)
    assert lev == pytest.approx(total)


def test_num_commas_only_as_thousands():
    assert bidforms.num("1,234.50") == 1234.5
    assert bidforms.num("$12,000") == 12000
    assert bidforms.num("1,2,3") is None
    assert bidforms.num("12,34") is None
    assert bidforms.num("-1,000") == -1000


def _job(tmp_path):
    s = ProjectStore(str(tmp_path / "p"))
    s.save_record("contract", {"item": "1", "description": "Base",
                               "scheduled": 100000})
    s.save_record("budget", {"cost_code": "03 30 00", "description": "Conc",
                             "original": 80000})
    return s


def _approve(s, amount, title="co"):
    e = s.save_record("event", {"title": title, "status": "Open",
                                "lines": [{"cost_code": "03 30 00",
                                           "cost": amount,
                                           "price": amount}]})
    ctx = types.SimpleNamespace(store=s)
    e = actions.ev_approve(ctx, e)
    return s.save_record("event", e)


def test_money_chain_invariants(tmp_path):
    s = _job(tmp_path)
    s.save_record("commitment", {"vendor": "Sub", "status": "Executed",
                                 "lines": [{"cost_code": "03 30 00",
                                            "amount": 60000}]})
    _approve(s, 5000)
    _approve(s, -1200)
    s.save_record("cost", {"cost_code": "03 30 00", "amount": 20000})
    rows = cost.by_code(s)
    for r in rows.values():
        assert r["revised"] == pytest.approx(r["original"] + r["approved"])
        assert r["fac"] == pytest.approx(r["actual"] + r["etc"])
        assert r["variance"] == pytest.approx(r["revised"] - r["fac"])
    summ = cost.summary(s)
    assert summ["totals"]["revised"] == pytest.approx(
        sum(r["revised"] for r in rows.values()))
    con = cost.contract_numbers(s)
    assert con["revised"] == pytest.approx(con["original"] +
                                           con["approved"])
    # G702: line 3 = 1 + 2; 6 = 4 - 5; 8 = 6 - 7; 9 = 3 - 6
    # filled, then certified (a certified app is final - NW-07)
    pa1 = s.save_record("payapp", {"period_to": "2026-01-31"})
    pa1["lines"] = [dict(l, this_period=l["scheduled"] * 0.3)
                    for l in cost.fill_payapp(s, pa1)]
    pa1 = s.save_record("payapp", pa1)
    pa1 = s.save_record("payapp", dict(pa1, status="Certified"))
    pa2 = s.save_record("payapp", {"period_to": "2026-02-28"})
    pa2["lines"] = [dict(l, this_period=l["scheduled"] * 0.2)
                    for l in cost.fill_payapp(s, pa2)]
    pa2 = s.save_record("payapp", pa2)
    for pa in (pa1, pa2):
        g = cost.payapp_values(s, pa)["g702"]
        assert g["3"] == pytest.approx(g["1"] + g["2"])
        assert g["6"] == pytest.approx(g["4"] - g["5"])
        assert g["8"] == pytest.approx(g["6"] - g["7"])
        assert g["9"] == pytest.approx(g["3"] - g["6"])
    assert cost.payapp_values(s, pa2)["g702"]["7"] == pytest.approx(
        cost.payapp_values(s, pa1)["g702"]["6"])


def test_uncertified_app_is_not_previous_work(tmp_path):
    s = _job(tmp_path)
    a1 = s.save_record("payapp", {"period_to": "2026-01-31",
                                  "status": "Draft",
                                  "lines": [{"item": "1",
                                             "this_period": 10000}]})
    a2 = s.save_record("payapp", {"period_to": "2026-02-28"})
    v = cost.payapp_values(s, a2)
    assert v["totals"]["previous"] == 0 and v["g702"]["7"] == 0
    assert any("aren't certified" in w for w in v["warnings"])
    assert all(l["previous"] == 0 for l in cost.fill_payapp(s, a2))
    a1["status"] = "Certified"
    s.save_record("payapp", a1)
    assert cost.payapp_values(s, a2)["totals"]["previous"] == 10000


def test_thousand_change_orders(tmp_path):
    s = _job(tmp_path)
    ctx = types.SimpleNamespace(store=s)
    for i in range(1000):
        e = s.save_record("event", {"title": f"c{i}", "status": "Open",
                                    "approved": "2026-03-01",
                                    "lines": [{"cost_code": "03 30 00",
                                               "cost": 10, "price": 10}]})
        s.save_record("event", actions.ev_approve(ctx, e))
    nos = [e["co_no"] for e in s.list("event")]
    assert len(set(nos)) == 1000 and "CO-1000" in nos and "CO-001" in nos
    sov = [l["item"] for l in cost.sov_lines(s) if l.get("co")]
    assert sov[:3] == ["CO-001", "CO-002", "CO-003"]
    assert sov[-2:] == ["CO-999", "CO-1000"]
    pa = s.save_record("payapp", {"period_to": "2026-03-31"})
    g = cost.payapp_values(s, pa)["g702"]
    assert g["2"] == pytest.approx(10000) and g["3"] == pytest.approx(110000)
    # deleting one never re-issues a number
    s.delete("event", next(e["_id"] for e in s.list("event")
                           if e["co_no"] == "CO-500"))
    e = s.save_record("event", {"title": "late", "status": "Open"})
    assert actions.ev_approve(ctx, e)["co_no"] == "CO-1001"


def test_money_find_by_number():
    data = {"changes": [{"id": "c1", "co_no": "CO-007", "cor_no": "COR-3"}]}
    assert money._find(data, "CO-7")["id"] == "c1"
    assert money._find(data, 7)["id"] == "c1"
    assert money._find(data, "COR-003")["id"] == "c1"
    with pytest.raises(KeyError):
        money._find(data, "CO-8")


def test_unassigned_and_flags(tmp_path):
    s = _job(tmp_path)
    _approve(s, 3000)                        # no vendor on the line
    r = cost.by_code(s)["03 30 00"]
    assert r["unassigned"] == 3000 and r["etc_default"] and r["flag"] == ""


def test_escalation_round_trip_and_capped_annual():
    pts = {f"{y}-{m:02d}": 100 * 1.05 ** ((y - 2020) + (m - 1) / 12)
           for y in range(2020, 2025) for m in range(1, 13)}
    e = bls_core.escalation(pts, "2021-01", "2023-01")
    back = bls_core.escalation(pts, "2023-01", "2021-01")
    assert e["factor"] * back["factor"] == pytest.approx(1.0)
    assert e["annual_pct"] == pytest.approx(5.0, abs=0.01)
    far = bls_core.escalation(pts, "2024-12", "2035-12")
    assert far["capped"]
    span = bls_core.months_between("2024-12", "2024-12") + far["extrapolated"]
    assert (1 + far["annual_pct"] / 100) ** (span / 12) == \
        pytest.approx(far["factor"])
    assert far["annual_pct"] == pytest.approx(5.0, abs=0.2)


def test_cashflow_overdue_remaining_spreads_over_a_month(tmp_path):
    s = _job(tmp_path)
    s.save_record("activity", {"name": "Pour", "cost_code": "03 30 00",
                               "start": "2026-01-05", "duration": 5})
    import datetime as dt
    out = cashflow.months(s, today=dt.date(2026, 3, 30))
    f = {r["month"]: r["forecast"] for r in out["rows"]}
    assert f.get("2026-03", 0) > 0 and f.get("2026-04", 0) > 0


def test_variance_skips_holidays():
    import datetime as dt
    cal = schedule.Calendar(dt.date(2026, 1, 1), ["2026-07-03"])
    row = {"baseline_finish": "2026-07-02", "ef": dt.date(2026, 7, 6)}
    assert schedule.variance(row) == 2
    assert schedule.variance(row, cal) == 1


def test_estimate_keys_and_cents():
    assert estimate.key_of("Wall", "length", "ft") == "Wall|length|ft"
    a = estimate.key_of("2x4 | 2x6", "length", "ft")
    b = estimate.key_of("2x4 ", " 2x6|length", "ft")
    assert a != b and json.loads(a)[0] == "2x4 | 2x6"


def test_zero_divisor_formula():
    with pytest.raises(assemblies.FormulaError, match="division by zero"):
        assemblies.evaluate("area / spacing", {"area": 10, "spacing": 0})
    with pytest.raises(assemblies.FormulaError):
        assemblies.evaluate("len % 0", {"len": 3})
    with pytest.raises(assemblies.FormulaError):
        assemblies.evaluate("len // w", {"len": 3, "w": 0})
    assert assemblies.evaluate("area / spacing if spacing else 0",
                               {"area": 10, "spacing": 0}) == 0
    assert assemblies.evaluate("area / spacing",
                               {"area": 10, "spacing": 4}) == 2.5


# ------------------------------------------------------------ security
class _WS:
    def __init__(self, ip, headers=None):
        self.remote_address = (ip, 1)
        self.request_headers = headers or {}
        self.sent = []

    async def send(self, data):
        self.sent.append(json.loads(data))

    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


def test_forwarded_for_spoof_from_internet_is_ignored():
    # live's fix (relaycore.forwarded_ip, 3:26 PM): header believed only
    # from a loopback/private proxy peer, and then its last hop
    spoof = {"X-Forwarded-For": "127.0.0.1"}
    assert rc.remote_ip(_WS("203.0.113.9", spoof)) == "203.0.113.9"
    assert hubmod.ws_context(_WS("203.0.113.9", spoof))["ip"] == \
        "203.0.113.9"
    h = {"X-Forwarded-For": "127.0.0.1, 203.0.113.7"}
    assert rc.remote_ip(_WS("127.0.0.1", h)) == "203.0.113.7"

    async def run():
        rooms = rc.Rooms(token=None)
        w = _WS("203.0.113.9", spoof)
        await rooms.serve(w, {"type": "hello", "room": "job",
                              "password": "x"})
        assert "no session" in w.sent[-1]["msg"]
    asyncio.run(run())


def test_temp_password_strength():
    pws = {temp_password() for _ in range(200)}
    assert len(pws) == 200
    tail = next(iter(pws)).split("-")[-1]
    assert len(tail) == 8


def test_service_worker_never_caches_hub():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sw = open(os.path.join(root, "app", "collab", "web", "sw.js"),
              encoding="utf-8").read()
    assert "isPrivate(e.request.url)" in sw and "MAX_ENTRIES" in sw
    assert "'logout'" in sw


# ------------------------------------------------------------ 3b: B2, C17
def test_failed_edit_is_never_broadcast(monkeypatch):
    from app import annotate, viewer
    from app.collab import oplog
    from app.collab.session import CollabSession
    sent = []
    sess = CollabSession.__new__(CollabSession)
    sess.log = oplog.OpLog("me") if hasattr(oplog, "OpLog") else None
    if sess.log is None:
        pytest.skip("no OpLog class")
    sess._applied = set()
    sess.client = types.SimpleNamespace(
        send_event=lambda kind, data: sent.append(data))
    fake = types.SimpleNamespace(session=sess, doc=None,
                                 recorder=types.SimpleNamespace(
                                     record=lambda d: None),
                                 _pf_forget=lambda: None)

    def boom(doc, op, fresh=False):
        raise ValueError("bad payload")
    monkeypatch.setattr(annotate, "apply_op", boom)
    with pytest.raises(ValueError):
        viewer.PdfView.do_op(fake, "add_text", 0, text="x")
    assert sent == [] and not sess.log.ops and not sess._applied
    monkeypatch.setattr(annotate, "apply_op", lambda d, op, fresh=False: True)
    assert viewer.PdfView.do_op(fake, "add_text", 0, text="y")
    assert len(sent) == 1 and len(sess.log.ops) == 1


def test_symbol_hits_on_rotated_page_are_normalised():
    import fitz
    pytest.importorskip("cv2")
    from app import autocount
    doc = fitz.open()
    page = doc.new_page(width=600, height=400)
    for x in (100, 300, 450):
        page.draw_rect(fitz.Rect(x, 150, x + 30, 180), color=(0, 0, 0),
                       width=2)
        page.draw_line((x, 150), (x + 30, 180), width=2)
    page.set_rotation(90)
    clip = fitz.Rect(100 - 4, 150 - 4, 134, 184) * page.rotation_matrix
    tpl = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=clip.normalize(),
                          colorspace=fitz.csGRAY).tobytes("png")
    hits = autocount.find_symbols(doc, tpl, threshold=0.7)
    assert len(hits) >= 3
    for h in hits:
        x0, y0, x1, y1 = h["rect"]
        assert x0 <= x1 and y0 <= y1
        assert 140 <= y0 <= 160                      # unrotated page space


def test_lan_peer_spoofing_loopback_cannot_open_rooms():
    async def run():
        rooms = rc.Rooms(token=None)
        w = _WS("192.168.1.50", {"X-Forwarded-For": "127.0.0.1"})
        await rooms.serve(w, {"type": "hello", "room": "job",
                              "password": "x"})
        assert "no session" in w.sent[-1]["msg"]
    asyncio.run(run())
