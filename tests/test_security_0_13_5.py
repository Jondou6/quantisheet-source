"""0.13.5 security fixes: sealed-bid invitation tokens stay out of the
shared bid package record, a sealed number is never read back, the
X-Forwarded-For header is believed only from trusted proxies, spreadsheet
exports can't carry live formulas from user text, PDF links open only web
and email addresses, a full save keeps a document's encryption, and the
dashboard's set_result writes the project first. Made-up companies,
people and numbers only (example.com, 555 numbers)."""
import datetime as dt
import json
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import safecell                                     # noqa: E402
from app.collab import hub as hubmod                         # noqa: E402
from app.collab import relaycore as rc                       # noqa: E402

PW = "example-pass-1"


# ============================================================ helpers
class _WS:
    """A WebSocket stand-in: peer address and handshake headers."""

    def __init__(self, peer, headers=None):
        self.remote_address = (peer, 50000)
        self.request_headers = headers or {}


@pytest.fixture
def no_proxy_env(monkeypatch):
    monkeypatch.delenv("TRUSTED_PROXIES", raising=False)
    rc.set_trusted_proxies(None)
    yield
    rc.set_trusted_proxies(None)


@pytest.fixture
def clean_lockout():
    hubmod._FAILS.clear()
    hubmod._LOCKED.clear()
    yield
    hubmod._FAILS.clear()
    hubmod._LOCKED.clear()


def _hub(tmp_path):
    H = hubmod.Hub(str(tmp_path / "hub"))
    r = H.call("proj.open", {"project": "Example Sewer", "password": PW,
                             "user": "Example GC"}, {}, True)
    key = r["key"]
    a = H.call("user.add", {"project": "Example Sewer", "key": key,
                            "email": "gc@example.com", "role": "admin",
                            "name": "Example GC", "password": PW}, {}, True)
    keys = {"admin": a["key"]}
    for role in ("sub", "viewer", "estimator"):
        H.call("user.add", {"project": "Example Sewer", "key": keys["admin"],
                            "email": f"{role}@example.com", "role": role,
                            "name": f"Example {role}", "password": PW},
               {}, True)
        keys[role] = H.call("proj.open", {
            "project": "Example Sewer", "email": f"{role}@example.com",
            "password": PW}, {}, True)["key"]
    return H, keys


BIDDERS = [{"company": "Example Dig Co", "email": "est@dig.example.com",
            "phone": "555-0101"},
           {"company": "Example Pipe LLC", "email": "bid@pipe.example.com",
            "phone": "555-0102"}]


def _package(H, keys, sealed=True):
    rec = {"title": "Example sanitary sewer", "due": "2026-11-20",
           "due_time": "2:00 PM", "sealed": "Yes" if sealed else "No",
           "bidders": [dict(b) for b in BIDDERS]}
    r = H.call("rec.put", {"project": "Example Sewer", "key": keys["admin"],
                           "coll": "bidpkg", "record": rec, "prefix": "BP-"},
               {}, True)
    rid = r["record"]["_id"]
    inv = H.call("bid.invite", {"project": "Example Sewer",
                                "key": keys["admin"], "record_id": rid,
                                "bidders": BIDDERS}, {}, True)["invites"]
    toks = [i["token"] for i in inv]
    # the GC's desktop writes the tokens on its own rows and syncs them
    rows = [dict(b, token=t) for b, t in zip(BIDDERS, toks)]
    H.call("rec.put", {"project": "Example Sewer", "key": keys["admin"],
                       "coll": "bidpkg", "record": {"_id": rid,
                                                    "bidders": rows}},
           {}, True)
    return rid, toks


def _changes(H, key, authed=True):
    return H.call("rec.changes", {"project": "Example Sewer", "key": key,
                                  "since": 0}, {}, authed)


def _pkg(res, rid):
    return next(r for r in res["records"] if r["_id"] == rid)


# ============================================================ sealed bids
def test_tokens_never_stored_on_the_shared_record(tmp_path):
    H, keys = _hub(tmp_path)
    rid, toks = _package(H, keys)
    on_disk = open(H._p("projects", "Example Sewer", "records",
                        "bidpkg.json"), encoding="utf-8").read()
    for t in toks:
        assert t not in on_disk
    rec = json.loads(on_disk)["items"][rid]
    assert all(b.get("invite_ref") and "token" not in b
               for b in rec["bidders"])
    # but the invitations still work
    info = H.call("bid.open", {"token": toks[0]}, {}, False)
    assert info["company"] == "Example Dig Co"


@pytest.mark.parametrize("who,authed", [("sub", True), ("viewer", True),
                                        ("estimator", False),
                                        ("admin", False)])
def test_other_readers_never_get_tokens(tmp_path, who, authed):
    H, keys = _hub(tmp_path)
    rid, toks = _package(H, keys)
    res = _changes(H, keys[who], authed)
    text = json.dumps(res)
    for t in toks:
        assert t not in text
    assert all("token" not in b for b in _pkg(res, rid)["bidders"])


def test_office_staff_keep_their_links(tmp_path):
    H, keys = _hub(tmp_path)
    rid, toks = _package(H, keys)
    for who in ("admin", "estimator"):
        rows = _pkg(_changes(H, keys[who]), rid)["bidders"]
        assert [b.get("token") for b in rows] == toks


def test_a_put_answer_carries_no_tokens_for_others(tmp_path):
    H, keys = _hub(tmp_path)
    rid, toks = _package(H, keys)
    r = H.call("rec.put", {"project": "Example Sewer", "key": keys["sub"],
                           "coll": "bidpkg",
                           "record": {"_id": rid, "title": "x"}}, {}, True)
    assert r.get("denied") and not any(t in json.dumps(r) for t in toks)


def test_sealed_bid_open_shows_only_status(tmp_path, monkeypatch):
    monkeypatch.setattr(hubmod, "_now_local",
                        lambda: dt.datetime(2026, 11, 19, 9, 0))
    H, keys = _hub(tmp_path)
    rid, toks = _package(H, keys)
    H.call("bid.respond", {"token": toks[0], "intent": "Will Bid",
                           "amount": "$91,234.56",
                           "inclusions": "Example trench box"}, {}, False)
    H.call("bid.respond", {"token": toks[1], "intent": "Will Bid",
                           "amount": "87,650"}, {}, False)
    for t in toks:
        info = H.call("bid.open", {"token": t}, {}, False)
        text = json.dumps(info)
        assert info["sealed"] and info["status"] == "Bid Received"
        assert info["amount"] is None and info["values"] == {}
        assert info["inclusions"] == "" and info["sealed_received"]
        assert "91234" not in text and "87650" not in text
        assert "trench" not in text
    # nobody on the project sees a number before the opening
    for who in ("admin", "sub", "viewer"):
        text = json.dumps(_pkg(_changes(H, keys[who]), rid))
        assert "91234" not in text and "87650" not in text


def test_answer_only_click_keeps_the_sealed_bid(tmp_path, monkeypatch):
    when = {"now": dt.datetime(2026, 11, 19, 9, 0)}
    monkeypatch.setattr(hubmod, "_now_local", lambda: when["now"])
    H, keys = _hub(tmp_path)
    rid, toks = _package(H, keys)
    H.call("bid.respond", {"token": toks[0], "intent": "Will Bid",
                           "amount": "50,000"}, {}, False)
    # the page can't show the number back: a later click with a blank
    # amount must not wipe it
    H.call("bid.respond", {"token": toks[0], "intent": "Will Bid",
                           "amount": "", "inclusions": "",
                           "note": "Example note"}, {}, False)
    when["now"] = dt.datetime(2026, 11, 20, 14, 5)
    r = H.call("bid.unseal", {"project": "Example Sewer",
                              "key": keys["admin"], "record_id": rid},
               {}, True)
    assert r["opened"] == 1
    rows = _pkg(_changes(H, keys["admin"]), rid)["bidders"]
    assert rows[0]["amount"] == 50000.0


def test_unseal_after_deadline_still_opens_every_bid(tmp_path, monkeypatch):
    when = {"now": dt.datetime(2026, 11, 19, 9, 0)}
    monkeypatch.setattr(hubmod, "_now_local", lambda: when["now"])
    H, keys = _hub(tmp_path)
    rid, toks = _package(H, keys)
    for t, amt in zip(toks, ("9,000", "8,500")):
        H.call("bid.respond", {"token": t, "intent": "Will Bid",
                               "amount": amt}, {}, False)
    with pytest.raises(hubmod.HubError, match="before the"):
        H.call("bid.unseal", {"project": "Example Sewer",
                              "key": keys["admin"], "record_id": rid},
               {}, True)
    when["now"] = dt.datetime(2026, 11, 20, 14, 1)
    r = H.call("bid.unseal", {"project": "Example Sewer",
                              "key": keys["admin"], "record_id": rid},
               {}, True)
    assert r["opened"] == 2
    am = {b["company"]: b["amount"]
          for b in _pkg(_changes(H, keys["sub"]), rid)["bidders"]}
    assert am == {"Example Dig Co": 9000.0, "Example Pipe LLC": 8500.0}
    assert not any(t in json.dumps(_changes(H, keys["sub"])) for t in toks)


def test_record_from_before_the_fix_is_cleaned(tmp_path):
    """A package saved by 0.13.4 (token on the row) loses it on the next
    change and still matches its invitation."""
    H, keys = _hub(tmp_path)
    rid, toks = _package(H, keys)
    p = H._p("projects", "Example Sewer", "records", "bidpkg.json")
    data = json.load(open(p, encoding="utf-8"))
    for b, t in zip(data["items"][rid]["bidders"], toks):
        b.pop("invite_ref", None)
        b["token"] = t
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f)
    assert not any(t in json.dumps(_changes(H, keys["sub"])) for t in toks)
    H.call("bid.open", {"token": toks[1]}, {}, False)
    assert not any(t in open(p, encoding="utf-8").read() for t in toks)
    rows = _pkg(_changes(H, keys["admin"]), rid)["bidders"]
    assert [b.get("token") for b in rows] == toks


def test_open_bids_still_show_the_bidders_own_answer(tmp_path):
    H, keys = _hub(tmp_path)
    rid, toks = _package(H, keys, sealed=False)
    H.call("bid.respond", {"token": toks[0], "intent": "Will Bid",
                           "amount": "12,000"}, {}, False)
    info = H.call("bid.open", {"token": toks[0]}, {}, False)
    assert info["amount"] == 12000.0 and not info["sealed"]


# ============================================================ X-Forwarded-For
def test_lan_peer_cannot_rotate_forwarded_for(no_proxy_env, clean_lockout):
    for i in range(5):
        ctx = hubmod.ws_context(_WS("192.168.1.50", {
            "X-Forwarded-For": f"203.0.113.{i + 1}"}))
        assert ctx["ip"] == "192.168.1.50"
        assert rc.remote_ip(_WS("192.168.1.50", {
            "X-Forwarded-For": f"198.51.100.{i + 1}"})) == "192.168.1.50"
        hubmod._note_fail(ctx["ip"])
    assert hubmod._blocked("192.168.1.50")


def test_default_trusts_only_loopback(no_proxy_env):
    f = rc.forwarded_ip
    for peer in ("10.0.0.5", "172.16.4.4", "192.168.0.9", "100.64.1.1",
                 "fd00::5", "203.0.113.7"):
        assert f(peer, "198.51.100.4") == peer
    assert f("127.0.0.1", "198.51.100.4") == "198.51.100.4"
    assert f("::1", "198.51.100.4") == "198.51.100.4"
    assert f("::ffff:127.0.0.1", "198.51.100.4") == "198.51.100.4"
    assert f("127.0.0.1", "") == "127.0.0.1"


def test_trusted_proxies_from_the_environment(no_proxy_env, monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXIES", "10.0.0.0/8, 192.0.2.10, junk")
    f = rc.forwarded_ip
    assert f("10.1.2.3", "203.0.113.9") == "203.0.113.9"
    assert f("192.0.2.10", "198.51.100.1, 203.0.113.9") == "203.0.113.9"
    assert f("192.0.2.11", "203.0.113.9") == "192.0.2.11"
    assert f("192.168.1.50", "203.0.113.9") == "192.168.1.50"
    rc.set_trusted_proxies(["192.168.1.0/24"])    # a setting wins
    assert f("192.168.1.50", "203.0.113.9") == "203.0.113.9"
    assert f("10.1.2.3", "203.0.113.9") == "10.1.2.3"


def test_hosted_relay_configs_set_trusted_proxies():
    """Review F8: Fly.io and Render configs trust their own proxy so the
    lockout sees the client's address; the README explains it."""
    import re
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                        "server")
    try:
        import tomllib
    except ImportError:                              # Python < 3.11
        tomllib = None
    fly_text = open(os.path.join(root, "fly.toml"), encoding="utf-8").read()
    if tomllib is not None:
        fly = tomllib.loads(fly_text)["env"]["TRUSTED_PROXIES"]
    else:
        fly = re.search(r'^\s*TRUSTED_PROXIES\s*=\s*"([^"]+)"', fly_text,
                        re.M).group(1)
    assert rc._parse_proxies(fly) and "fdaa::/16" in fly
    render = open(os.path.join(root, "render.yaml"), encoding="utf-8").read()
    m = re.search(r"-\s*key:\s*TRUSTED_PROXIES\s*\n\s*value:\s*\"?([^\"\n]+)",
                  render)
    assert m and rc._parse_proxies(m.group(1)) and "10.0.0.0/8" in m.group(1)
    readme = open(os.path.join(root, "README.md"), encoding="utf-8").read()
    assert "TRUSTED_PROXIES" in readme and "lock" in readme


# ============================================================ safe cells
@pytest.mark.parametrize("v,want", [
    ('=HYPERLINK("https://example.invalid/x")',
     '\'=HYPERLINK("https://example.invalid/x")'),
    ("+1+1", "'+1+1"), ("@SUM(A1)", "'@SUM(A1)"), ("-2+3", "'-2+3"),
    ("\tx", "'\tx"), ("\rx", "'\rx"), ("=1+1", "'=1+1"),
    ("-312.47", "-312.47"), ("+5", "+5"), ("-1,234.50", "-1,234.50"),
    ("-", "-"), ("Example Co", "Example Co"), ("", ""), (12, 12),
    (-3.5, -3.5), (None, None)])
def test_safe_cell(v, want):
    assert safecell.safe_cell(v) == want


def test_safe_csv_writer(tmp_path):
    import csv
    p = tmp_path / "x.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = safecell.writer(f)
        w.writerow(["=cmd|' /C calc'!A0", 5, "-2.50", "Example"])
        w.writerows([["@x", None]])
    rows = list(csv.reader(open(p, encoding="utf-8")))
    assert rows == [["'=cmd|' /C calc'!A0", "5", "-2.50", "Example"],
                    ["'@x", ""]]


def test_xlsx_text_cells_and_own_formulas(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    safecell.append_row(ws, ["=1+1", safecell.Formula("=SUM(C1:C2)"), 4,
                             "-4", "@x", "Example"])
    p = str(tmp_path / "x.xlsx")
    wb.save(p)
    c = openpyxl.load_workbook(p).active[1]
    assert (c[0].value, c[0].data_type) == ("=1+1", "s")
    assert (c[1].value, c[1].data_type) == ("=SUM(C1:C2)", "f")
    assert c[2].value == 4 and c[3].data_type == "s"
    assert (c[4].value, c[4].data_type) == ("@x", "s")


def test_dashboard_excel_keeps_user_text_as_text(tmp_path, monkeypatch):
    openpyxl = pytest.importorskip("openpyxl")
    from app import dashboard as db, settings
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Example Estimator"})
    os.makedirs(settings.DIR, exist_ok=True)
    db._CACHE.clear()
    from app.pm import store
    monkeypatch.setattr(store, "_OPEN", {})
    from test_dashboard import _project, _sheet
    evil = '=HYPERLINK("https://example.invalid/x","Example")'
    a = _project(tmp_path, "S1", {"bid_date": "2025-02-01", "owner": "=1+1",
                                  "building_type": "Example Office",
                                  "building_sf": "1000",
                                  "bid_amount": "100000",
                                  "bid_result": "Won"},
                 sheets=[_sheet("09 29 00", "Board",
                                [(evil, "100,000"),
                                 ("Example Walls", "110,000")])])
    r = db.build(db.load([a]))
    path = db.export_xlsx(r, str(tmp_path / "out" / "dash.xlsx"))
    wb = openpyxl.load_workbook(path)
    seen = set()
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for c in row:
                if c.value in ("=1+1", evil):
                    assert c.data_type == "s", (ws.title, c.coordinate)
                    seen.add(ws.title)
    assert {"Jobs", "Hit Rate", "Sub Bids", "Sub Summary"} <= seen
    js = wb["Jobs"]
    assert js["D2"].value == "=1+1" and js["D2"].data_type == "s"
    assert js["L2"].data_type == "f" and js["L2"].value.startswith("=IF(")
    last = js.max_row
    assert js[f"M{last}"].data_type == "f" and \
        js[f"M{last}"].value.startswith("=SUM(")
    assert wb["Sub Bids"]["G2"].data_type == "f"


def test_estimate_excel_and_csv_neutralise_descriptions(tmp_path):
    pytest.importorskip("fitz")
    openpyxl = pytest.importorskip("openpyxl")
    import csv
    from app import estimate_export as EX, estimate_lines as EL
    from estimate_helpers import blank_doc
    d = blank_doc()
    EL.add(d, [EL.new_line("=1+2", 10, "sf", code="03 31 13", mat="2.50"),
               EL.new_line("@Example", 1, "ls", code="09 29 10", lab=5)])
    x = EX.save_xlsx(d, str(tmp_path / "e.xlsx"))
    wb = openpyxl.load_workbook(x)
    descs = {c.value: c.data_type for c in wb["Lines"]["C"]}
    assert descs["=1+2"] == "s" and descs["@Example"] == "s"
    assert any(c.data_type == "f" and str(c.value).startswith("=SUM(")
               for row in wb["By Division"].iter_rows() for c in row)
    p = EX.save_csv(d, str(tmp_path / "e.csv"))
    cells = [c for row in csv.reader(open(p, encoding="utf-8-sig"))
             for c in row]
    assert "'=1+2" in cells and "=1+2" not in cells


# ============================================================ dashboard N9
def test_set_result_damaged_project_changes_nothing(tmp_path, monkeypatch):
    from app import dashboard as db, pricedb, settings
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Example Estimator"})
    os.makedirs(settings.DIR, exist_ok=True)
    db._CACHE.clear()
    from app.pm import store
    monkeypatch.setattr(store, "_OPEN", {})
    from test_dashboard import _db_job, _project
    jid = _db_job("EX-9", "Example Office", 1000, 90000, 100000,
                  "2025-03-01")
    folder = _project(tmp_path, "P9", {"number": "EX-9"})
    job = db.load([folder])["index"][f"db:{jid}"]
    assert job["folder"] == os.path.abspath(folder)
    with open(os.path.join(folder, db.PROJECT_FILE), "w",
              encoding="utf-8") as f:
        f.write("{ damaged")
    with pytest.raises(db.DashboardError, match="damaged"):
        db.set_result(job, "Lost")
    with pricedb.connect() as con:
        assert (con.execute("SELECT result FROM jobs WHERE id=?",
                            (jid,)).fetchone()[0] or "") != "Lost"
    assert job["result"] != "Lost"


# ============================================================ PDF links
@pytest.mark.parametrize("uri,ok", [
    ("https://example.com/spec.pdf", True), ("HTTP://example.com", True),
    ("mailto:bids@example.com", True), ("file:///C:/Windows/calc.exe", False),
    ("javascript:alert(1)", False), ("ms-settings:", False),
    ("search-ms:query=x", False), ("\\\\server\\share\\x.exe", False),
    ("smb://server/share", False), ("www.example.com", False),
    ("java\nscript:alert(1)", False), ("https:///nohost", False)])
def test_link_schemes(uri, ok):
    pytest.importorskip("PySide6")
    from app import main_window as mw
    assert (mw.link_scheme(uri) is not None) == ok


def test_follow_link_refuses_other_schemes(monkeypatch):
    pytest.importorskip("PySide6")
    from PySide6.QtGui import QDesktopServices
    from app import main_window as mw
    opened, warned = [], []
    monkeypatch.setattr(QDesktopServices, "openUrl",
                        staticmethod(lambda u: opened.append(u.toString())))
    monkeypatch.setattr(mw.QMessageBox, "warning",
                        staticmethod(lambda *a, **k: warned.append(a[2])))
    monkeypatch.setattr(mw.QMessageBox, "question",
                        staticmethod(lambda *a, **k: mw.QMessageBox.Yes))
    me = SimpleNamespace(_view=object())
    assert mw.MainWindow.follow_link(me, {"kind": mw.fitz.LINK_URI,
                                          "uri": "file:///C:/x.exe"}) is False
    assert opened == [] and "Only web" in warned[-1]
    assert mw.MainWindow.follow_link(me, {"kind": mw.fitz.LINK_URI,
                                          "uri": "https://example.com/a"})
    assert opened == ["https://example.com/a"]


# ============================================================ S7 encryption
USER_PW, OWNER_PW = "example-open-1", "example-owner-1"

# (case, user password on the file, password typed when opening)
PROTECTED_CASES = [("opened with the user password", USER_PW, USER_PW),
                   ("opened with the owner password", USER_PW, OWNER_PW),
                   ("permissions only", "", None)]


def _locked_pdf(path, user=USER_PW, owner=OWNER_PW):
    """A made-up AES-256 print-only plan sheet (user="" : no password to
    open it, permissions only)."""
    import fitz
    d = fitz.open()
    d.new_page().insert_text((72, 72), "Example plan sheet A-101")
    perm = int(fitz.PDF_PERM_ACCESSIBILITY | fitz.PDF_PERM_PRINT)
    d.save(str(path), encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=user,
           owner_pw=owner, permissions=perm)
    d.close()
    return path


def _open_like_the_app(mw, path, pw):
    import fitz
    doc = fitz.open(str(path))
    needed = doc.needs_pass
    code = 0
    if needed or pw:
        code = doc.authenticate(pw)
        assert code
    prot = mw.protection_on_open(doc, pw, code, needed)
    return doc, prot


def _perms_as_user(path, user):
    """The permissions someone opening `path` with the user password (or
    none) gets."""
    import fitz
    d = fitz.open(str(path))
    try:
        if d.needs_pass:
            assert d.authenticate(user)
        return d.permissions
    finally:
        d.close()


def assert_same_protection(copy, original, user=USER_PW, owner=OWNER_PW):
    """`copy` opens with the original user password (or none when the
    original needed none), the original owner password authenticates,
    and the permissions match the original's."""
    import fitz
    r = fitz.open(str(copy))
    try:
        assert r.needs_pass == bool(user)
        if user:
            assert not r.authenticate("wrong password")
            assert r.authenticate(user) & 2
        # PyMuPDF reports the method only once the file is unlocked
        # (a permissions-only file needs no password)
        enc = (r.metadata or {}).get("encryption") or ""
        assert "AES" in enc and "256" in enc, enc
    finally:
        r.close()
    r = fitz.open(str(copy))
    try:
        assert r.authenticate(owner) & 4
    finally:
        r.close()
    assert _perms_as_user(copy, user) == _perms_as_user(original, user)


def test_full_save_keeps_encryption_and_permissions(tmp_path):
    fitz = pytest.importorskip("fitz")
    pytest.importorskip("PySide6")
    from app import main_window as mw
    src = _locked_pdf(tmp_path / "locked.pdf")
    doc, prot = _open_like_the_app(mw, src, USER_PW)
    orig_perms = doc.permissions
    assert prot is not None and "example" not in repr(prot)
    assert prot.owner_pw != OWNER_PW       # unknown: a random fallback one
    doc[0].insert_text((72, 144), "Example edit")
    view = SimpleNamespace(doc=doc, page=0, protection=prot)
    out = tmp_path / "saved as.pdf"
    mw.MainWindow._write(SimpleNamespace(_view=None), str(out), view)
    r = fitz.open(str(out))
    assert r.needs_pass
    assert not r.authenticate("wrong password")
    assert r.authenticate(USER_PW)
    assert r.permissions == orig_perms
    assert "Example edit" in r[0].get_text()
    r.close()
    doc.close()
    assert_same_protection(out, src)


@pytest.mark.parametrize("case,user,typed", PROTECTED_CASES)
def test_save_as_keeps_both_passwords(tmp_path, case, user, typed):
    """Review F5: Save As kept the user password but replaced the owner
    password (or made the owner password the user password)."""
    pytest.importorskip("fitz")
    pytest.importorskip("PySide6")
    from app import main_window as mw
    src = _locked_pdf(tmp_path / "locked.pdf", user=user)
    doc, prot = _open_like_the_app(mw, src, typed)
    assert prot is not None
    doc[0].insert_text((72, 144), "Example edit")
    view = SimpleNamespace(doc=doc, page=0, protection=prot)
    out = tmp_path / "copy.pdf"
    mw.MainWindow._write(SimpleNamespace(_view=None), str(out), view)
    doc.close()
    assert_same_protection(out, src, user=user)


@pytest.mark.parametrize("case,user,typed", PROTECTED_CASES)
def test_full_save_in_place_keeps_encryption(tmp_path, monkeypatch, case,
                                             user, typed):
    fitz = pytest.importorskip("fitz")
    pytest.importorskip("PySide6")
    from app import main_window as mw
    src = _locked_pdf(tmp_path / "job.pdf", user=user)
    orig = _locked_pdf(tmp_path / "orig.pdf", user=user)
    doc, prot = _open_like_the_app(mw, src, typed)
    doc[0].insert_text((72, 144), "Example edit")
    view = SimpleNamespace(doc=doc, page=0, protection=prot)
    monkeypatch.setattr(doc, "can_save_incrementally", lambda: False)
    mw.MainWindow._write(SimpleNamespace(_view=None), str(src), view)
    # reopened and unlocked (needs_pass never changes; is_encrypted turns
    # False once authenticated)
    assert not view.doc.is_encrypted
    assert "Example edit" in view.doc[0].get_text()
    view.doc.close()
    assert_same_protection(src, orig, user=user)


def test_keep_failing_falls_back_to_re_encrypting(tmp_path, monkeypatch):
    """KEEP raising (or writing an unencrypted file): the DocProtection
    re-encryption is used, so the copy is never unprotected."""
    fitz = pytest.importorskip("fitz")
    pytest.importorskip("PySide6")
    from app import main_window as mw
    src = _locked_pdf(tmp_path / "locked.pdf")
    doc, prot = _open_like_the_app(mw, src, USER_PW)
    real = doc.save

    def save(path, **kw):
        if kw.get("encryption") == fitz.PDF_ENCRYPT_KEEP:
            raise RuntimeError("example KEEP failure")
        return real(path, **kw)

    monkeypatch.setattr(doc, "save", save)
    out = tmp_path / "copy.pdf"
    assert mw.save_keeping_protection(doc, str(out), prot, garbage=1) == \
        "fallback"
    r = fitz.open(str(out))
    assert r.needs_pass and r.authenticate(USER_PW)
    assert r.permissions == _perms_as_user(src, USER_PW)
    r.close()
    doc.close()


def test_protected_copy_without_fallback_writes_nothing(tmp_path,
                                                        monkeypatch):
    fitz = pytest.importorskip("fitz")
    from app import safeio
    src = _locked_pdf(tmp_path / "locked.pdf")
    doc = fitz.open(str(src))
    assert doc.authenticate(USER_PW)
    real = doc.save
    # KEEP "works" but writes an unencrypted file
    monkeypatch.setattr(doc, "save", lambda path, **kw: real(path))
    out = tmp_path / "copy.pdf"
    with pytest.raises(safeio.UnprotectedCopyError):
        safeio.save_keeping_encryption(doc, str(out))
    assert not out.exists()
    doc.close()


# ---------------------------------------------- F6: copies of protected PDFs
@pytest.mark.parametrize("case,user,typed", PROTECTED_CASES)
def test_reduce_file_size_keeps_protection(tmp_path, case, user, typed):
    fitz = pytest.importorskip("fitz")
    from app import acrobat, safeio
    src = _locked_pdf(tmp_path / "locked.pdf", user=user)
    doc = fitz.open(str(src))
    if typed:
        assert doc.authenticate(typed)
    copy = safeio.protected_copy(doc, typed)      # what the app reduces
    out = tmp_path / "small.pdf"
    try:
        # the main window hands reduce_size its throwaway copy, in place
        before = src.read_bytes()
        acrobat.reduce_size(copy, str(out), in_place=True)
    finally:
        copy.close()
        doc.close()
    # the result is at `out`, and the original file wasn't touched
    # (Venice, Nov 9 - N6)
    assert out.exists() and out.stat().st_size > 0
    assert src.read_bytes() == before
    assert_same_protection(out, src, user=user)
    r = fitz.open(str(out))
    if user:
        r.authenticate(user)
    assert "Example plan sheet" in r[0].get_text()
    r.close()


def test_protected_copy_needs_the_password(tmp_path):
    fitz = pytest.importorskip("fitz")
    from app import safeio
    src = _locked_pdf(tmp_path / "locked.pdf")
    doc = fitz.open(str(src))
    assert doc.authenticate(USER_PW)
    with pytest.raises(safeio.UnprotectedCopyError):
        safeio.protected_copy(doc, None)
    doc.close()


@pytest.mark.parametrize("case,user,typed", PROTECTED_CASES)
def test_external_issue_keeps_protection(tmp_path, case, user, typed):
    fitz = pytest.importorskip("fitz")
    from app import acrobat2
    src = _locked_pdf(tmp_path / "locked.pdf", user=user)
    doc = fitz.open(str(src))
    if typed:
        assert doc.authenticate(typed)
    out = tmp_path / "external.pdf"
    acrobat2.external_issue(doc, str(out), typed)
    doc.close()
    assert_same_protection(out, src, user=user)


def test_check_repair_copy_of_protected_file_keeps_protection(tmp_path,
                                                              monkeypatch):
    fitz = pytest.importorskip("fitz")
    from app import acrobat2
    src = _locked_pdf(tmp_path / "locked.pdf", user="")

    def bad(doc, rep):                       # pretend a page is damaged
        rep.page_count = doc.page_count
        rep.repaired_on_open = True

    monkeypatch.setattr(acrobat2, "_check_doc", bad)
    rep = acrobat2.check_and_repair(str(src))
    if rep.out:
        assert_same_protection(rep.out, src, user="")
    else:
        assert rep.unprotected_skip and "password-protected" in rep.text()


def test_unprotected_document_saves_as_before(tmp_path):
    fitz = pytest.importorskip("fitz")
    pytest.importorskip("PySide6")
    from app import main_window as mw
    d = fitz.open()
    d.new_page().insert_text((72, 72), "Example open sheet")
    p = tmp_path / "plain.pdf"
    d.save(str(p))
    d.close()
    doc = fitz.open(str(p))
    assert mw.protection_on_open(doc) is None
    view = SimpleNamespace(doc=doc, page=0, protection=None)
    assert mw.encryption_save_args(view) == {}
    out = tmp_path / "plain2.pdf"
    mw.MainWindow._write(SimpleNamespace(_view=None), str(out), view)
    r = fitz.open(str(out))
    assert not r.needs_pass and not r.metadata.get("encryption")
    r.close()
    doc.close()
