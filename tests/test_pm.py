"""Project Center: the shared project database (local store + hub),
workflows, printouts, and the window itself."""
import asyncio
import filecmp
import json
import os
import socket
import threading
import urllib.request

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import mail, settings                               # noqa: E402
from app.collab import hub as hubmod                         # noqa: E402
from app.collab import hubclient                             # noqa: E402
from app.pm import actions, report, schema                   # noqa: E402
from app.pm.store import ProjectStore, spec_number           # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Pat Morgan"})
    monkeypatch.setattr(mail, "OUTBOX", [])
    H = hubmod.Hub(str(tmp_path / "hub"))

    class Session:
        authed = True

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def call(self, op, **args):
            try:
                return H.call(op, json.loads(json.dumps(args)),
                              {"ip": "10.0.0.5"}, self.authed)
            except hubmod.HubError as e:
                raise hubclient.HubClientError(str(e))

    class Client:
        def __init__(self, url=None, token=None, timeout=60):
            self.url, self.token = url or "ws://hub", token

        def session(self):
            return Session()

        def call(self, op, **a):
            return Session().call(op, **a)

    monkeypatch.setattr(hubclient, "HubClient", Client)
    return tmp_path, H


def _team(store):
    store.save_record("member", {"name": "Pat Morgan", "email":
                                 "pat@builder.example",
                                 "company": "Example Builders"})
    store.save_record("member", {"name": "Ann Arch", "email":
                                 "ann@arch.example", "role": "Architect"})
    store.save_record("member", {"name": "Lee Brooks", "email":
                                 "lee@builder.example"})
    store.save_record("member", {"name": "Sam Sub", "email":
                                 "sam@sub.example", "role": "Subcontractor"})


def test_hub_copy_is_identical():
    assert filecmp.cmp(os.path.join(ROOT, "app", "collab", "hub.py"),
                       os.path.join(ROOT, "server", "hub.py"), shallow=False)


def test_store_sync_merge_and_numbers(env):
    tmp, H = env
    a = ProjectStore(str(tmp / "a"))
    r = a.save_record("rfi", {"subject": "Footing depth", "question": "?",
                              "to": "Ann Arch"})
    assert r["_no"] == "RFI-001"                     # local project
    a.connect("ws://hub", "Aiken Clinic", "pw123456")
    b = ProjectStore(str(tmp / "b"))
    b.connect("ws://hub", "Aiken Clinic", "pw123456")
    assert [x["subject"] for x in b.list("rfi")] == ["Footing depth"]
    # two people change different fields of the same RFI
    ra, rb = a.list("rfi")[0], b.list("rfi")[0]
    ra["status"] = "Closed"
    a.save_record("rfi", ra)
    rb["answer"] = "24 in below grade"
    b.save_record("rfi", rb)
    b.sync()
    res = a.sync()
    b.sync()
    assert res["conflicts"] == 1
    for s in (a, b):
        x = s.list("rfi")[0]
        assert (x["status"], x["answer"]) == ("Closed", "24 in below grade")
        assert s.pending_count() == 0
    # both add offline: the hub numbers them, no duplicates
    a.save_record("rfi", {"subject": "A"})
    b.save_record("rfi", {"subject": "B"})
    assert b.list("rfi")[-1]["_no"].startswith("RFI-new")
    a.sync(), b.sync(), a.sync()
    assert sorted(x["_no"] for x in a.list("rfi")) == \
        ["RFI-001", "RFI-002", "RFI-003"]
    assert sorted(x["_no"] for x in a.list("rfi")) == \
        sorted(x["_no"] for x in b.list("rfi"))
    # deletes travel too; the record is kept as deleted
    gone = b.find("rfi", subject="B")[0]
    b.delete("rfi", gone["_id"])
    b.sync(), a.sync()
    assert not a.find("rfi", subject="B")
    assert len(a.list("rfi", deleted=True)) == 3
    # submittals are numbered within their spec section
    a.save_record("submittal", {"title": "Rebar shop drawings",
                                "spec": "03 20 00 Concrete Reinforcing"})
    a.save_record("submittal", {"title": "Mix design",
                                "spec": "03 30 00"})
    a.save_record("submittal", {"title": "Rebar mill certs",
                                "spec": "032000"})
    a.sync()
    nos = sorted(x["_no"] for x in a.list("submittal"))
    assert nos == ["03 20 00-001", "03 20 00-002", "03 30 00-001"]
    assert spec_number("033000 Cast-in-place") == "03 30 00"
    # reopened from disk, the folder remembers everything
    a2 = ProjectStore(str(tmp / "a"))
    assert a2.connected and len(a2.list("rfi")) == 2


def test_phone_access_is_limited(env):
    tmp, H = env
    a = ProjectStore(str(tmp / "a"))
    a.connect("ws://hub", "Job", "pw123456")
    key = a.data["hub"]["key"]
    # a phone has the project password but no relay token
    with pytest.raises(hubmod.HubError):
        H.call("proj.open", {"project": "New one", "password": "abcd"},
               {}, authed=False)                     # can't create
    r = H.call("proj.open", {"project": "Job", "password": "pw123456"}, {},
               authed=False)
    assert r["key"] == key
    H.call("rec.put", {"project": "Job", "key": key, "coll": "punch",
                       "record": {"title": "Ding in door 104"},
                       "prefix": "P-", "width": 4, "user": "Lee"}, {},
           authed=False)
    with pytest.raises(hubmod.HubError):
        H.call("env.create", {}, {}, authed=False)
    with pytest.raises(hubmod.HubError):
        H.call("proj.open", {"project": "Job", "password": "nope"}, {},
               authed=False)
    a.sync()
    assert a.list("punch")[0]["_no"] == "P-0001"
    # photos: stored once by content, fetched by GET with the key
    import base64
    png = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 8, 8), 0).tobytes("png")
    att = H.call("att.put", {"project": "Job", "key": key, "name": "d.png",
                             "data": base64.b64encode(png).decode()}, {},
                 authed=False)
    url = f"/hub/att/Job/{att['sha256']}"
    st, ctype, body = H.get(url, {"Authorization": f"Bearer {key}"})
    assert (st, ctype, body) == (200, "image/png", png)
    assert H.get(url, {"Authorization": "Bearer wrong"})[0] == 403
    assert H.get(f"{url}?k={key}")[0] == 401          # not in the address


def test_workflows_send_mail(env):
    tmp, H = env
    s = ProjectStore(str(tmp / "p"))
    _team(s)
    ctx = actions.Ctx(s)
    rfi = s.save_record("rfi", dict(schema.defaults("rfi", s.me),
                                    subject="Door hardware",
                                    question="Which lockset at 104?",
                                    to="Ann Arch", cc=["Lee Brooks"],
                                    status="Draft"))
    assert schema.ball_in_court("rfi", rfi) == "Pat Morgan"
    rfi = actions.run(ctx, "rfi", rfi, "Send RFI")
    assert rfi["status"] == "Open"
    assert schema.ball_in_court("rfi", rfi) == "Ann Arch"
    m = mail.OUTBOX[-1]
    assert m["to"] == ["ann@arch.example"]
    assert m["cc"] == ["lee@builder.example"]
    assert "RFI-001" in m["subject"] and m["attachments"][0].endswith(".pdf")
    assert "Which lockset" in fitz.open(m["attachments"][0])[0].get_text()
    assert not [a for a in actions.available("rfi", rfi)
                if a[0] == "Close with Response"]
    rfi["answer"] = "Mortise, Grade 1"
    rfi = actions.run(ctx, "rfi", rfi, "Close with Response")
    assert rfi["status"] == "Closed" and rfi["answered_by"] == "Ann Arch"
    # submittal through two reviewers, returned once
    sub = s.save_record("submittal", {
        "title": "Hollow metal frames", "spec": "08 11 13",
        "responsible": "Sam Sub", "required_on_site": "2026-12-01",
        "lead_days": 30, "review_days": 10,
        "workflow": [{"reviewer": "Pat Morgan", "days": 3},
                     {"reviewer": "Ann Arch", "days": 10}]})
    assert schema.submit_by(sub) == "2026-10-22"
    sub = actions.run(ctx, "submittal", sub, "Send for Review")
    assert schema.ball_in_court("submittal", sub) == "Pat Morgan"
    answers = iter(["Approved", "Revise and Resubmit"])
    ctx.ask = lambda title, opts: next(answers)
    sub = actions.run(ctx, "submittal", sub, "Record Response")
    assert sub["status"] == "In Review"
    assert schema.ball_in_court("submittal", sub) == "Ann Arch"
    sub = actions.run(ctx, "submittal", sub, "Record Response")
    assert sub["status"] == "Revise and Resubmit"
    assert schema.ball_in_court("submittal", sub) == "Sam Sub"
    sub = actions.run(ctx, "submittal", sub, "Resubmit as Next Revision")
    assert sub["revision"] == 1 and sub["status"] == "Not Submitted"
    # punch: assignee fixes it, manager accepts
    p = s.save_record("punch", dict(schema.defaults("punch", s.me),
                                    title="Touch up paint",
                                    assignee="Sam Sub", status="Initiated"))
    p = actions.run(ctx, "punch", p, "Send to Assignee")
    assert mail.OUTBOX[-1]["to"] == ["sam@sub.example"]
    p = actions.run(ctx, "punch", p, "Ready for Review")
    assert schema.ball_in_court("punch", p) == "Pat Morgan"
    p = actions.run(ctx, "punch", p, "Accept")
    assert p["status"] == "Closed"
    # meeting: open topics carry to the next meeting and become issues
    mt = s.save_record("meeting", {
        "title": "OAC #1", "date": "2026-10-15",
        "attendees": [{"name": "Ann Arch"}],
        "topics": [{"no": "1.1", "topic": "Roof drains", "owner":
                    "Sam Sub", "status": "Open"},
                   {"no": "1.2", "topic": "Site fence", "status":
                    "Closed"}]})
    mt = actions.run(ctx, "meeting", mt, "Topics to Issues")
    assert s.list("issue")[0]["assignee"] == "Sam Sub"
    out = actions.run(ctx, "meeting", mt, "Create Next Meeting")
    nxt = s.get(*out["_open"])
    assert nxt["date"] == "2026-10-22" and len(nxt["topics"]) == 1
    # daily log copies yesterday's crews
    s.save_record("daily", {"date": "2026-10-14", "manpower": [
        {"company": "ABC Concrete", "workers": 6, "hours": 8}]})
    d = s.save_record("daily", {"date": "2026-10-15"})
    d = actions.run(ctx, "daily", d, "Copy Yesterday's Crews")
    assert d["manpower"][0]["company"] == "ABC Concrete"
    # inspection: failed items become observations
    from app.pm.templates import items_for
    ins = s.save_record("inspection", {"title": "Slab on grade",
                                       "template": "Pre-pour concrete",
                                       "items": items_for(
                                           "Pre-pour concrete")})
    ins["items"][0]["result"] = "No"
    for i in ins["items"][1:]:
        i["result"] = "Yes"
    ins = actions.run(ctx, "inspection", ins, "Finish Inspection")
    assert ins["status"] == "Failed"
    assert s.list("observation")[0]["title"].startswith("Forms set")
    # nobody to send to: saved, not sent, and the user is told
    told = []
    ctx.notify = told.append
    iss = s.save_record("issue", {"title": "Loose", "assignee": "Nobody"})
    actions.run(ctx, "issue", iss, "Email Responsible")
    assert told and "Directory" in told[-1]


def test_printouts(env):
    tmp, H = env
    s = ProjectStore(str(tmp / "p"))
    _team(s)
    s.save_record("daily", {
        "date": "2026-10-15", "work": "Poured footings grid A-C",
        "weather": {"high": "78", "low": "60", "sky": "Clear"},
        "manpower": [{"company": "ABC Concrete", "trade": "Concrete",
                      "workers": 6, "hours": 8}]})
    for i in range(30):
        s.save_record("punch", {"title": f"Item {i} needs paint",
                                "location": f"Room {100 + i}",
                                "assignee": "Sam Sub",
                                "status": "Work Required"})
    d = s.list("daily")[0]
    path = report.record_pdf(s, "daily", d, str(tmp / "dl.pdf"))
    text = fitz.open(path)[0].get_text()
    for want in ("Daily log DL-0001", "78/60°F, Clear", "ABC Concrete",
                 "Poured footings"):
        assert want in text, want
    path = report.list_pdf(s, "punch", s.list("punch"), str(tmp / "p.pdf"))
    doc = fitz.open(path)
    assert doc.page_count >= 2 and "Room 129" in "".join(
        p.get_text() for p in doc)
    xl = report.list_xlsx(s, "punch", s.list("punch"), str(tmp / "p.xlsx"))
    import zipfile
    assert "Item 29 needs paint" in zipfile.ZipFile(xl).read(
        "xl/worksheets/sheet1.xml").decode()


def test_project_center_window(env, qapp_pm):
    tmp, H = env
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from app.pm import center
    s = ProjectStore(str(tmp / "job"))
    _team(s)
    for i in range(5):
        s.save_record("rfi", {"subject": f"Question {i}", "to": "Pat "
                              "Morgan", "status": "Open",
                              "question": "Which detail applies?",
                              "due": "2020-01-01" if i == 0 else "2099-01-01"})
    _pdf(tmp / "job" / "A-101.pdf")
    w = center.ProjectCenter(s)
    w.show()
    QApplication.processEvents()
    w.home.refresh()
    text = " ".join(lbl.text() for lbl in w.home.findChildren(
        type(w.toast_lbl)))
    assert "Waiting on you" in text and "Overdue" in text
    page = w.show_tool("rfi", "Open")
    assert page.proxy.rowCount() == 5
    page.chips.button(2).setChecked(True)              # Overdue
    page.refresh()
    assert page.proxy.rowCount() == 1
    page.search.setText("rfi-003")
    page.chips.button(4).setChecked(True)              # All
    page.refresh()
    assert page.proxy.rowCount() == 1
    page.search.clear()
    rid = s.find("rfi", subject="Question 2")[0]["_id"]
    w.open_record("rfi", rid)
    f = page.form
    assert f.current["_id"] == rid
    f.title.setText("Question 2 - revised")
    f.title.editingFinished.emit()
    assert s.get("rfi", rid)["subject"] == "Question 2 - revised"
    f.editors["answer"].set_value("Use detail 5/A-501")
    f.editors["answer"].changed.emit()
    assert s.get("rfi", rid)["answer"] == "Use detail 5/A-501"
    f._run("Close with Response")
    assert s.get("rfi", rid)["status"] == "Closed"
    assert mail.OUTBOX
    # jump box finds items by number
    j = center.JumpDialog(w)
    j.q.setText("rfi 3")
    assert "RFI-003" in j.list.item(0).text()
    j.close()
    # every tool page opens, and the cost and document pages
    for key in list(schema.TOOLS) + list(center.SPECIAL):
        w.show_tool(key)
        QApplication.processEvents()
    docs = w.pages["documents"]
    assert docs.table.rowCount() >= 1          # the project folder's files
    from app import theme
    theme.apply(QApplication.instance(), "dark")
    theme.apply(QApplication.instance(), "light")
    w.close()


@pytest.fixture
def qapp_pm(monkeypatch):
    """No modal dialog may wait for a click in a test."""
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import (QApplication, QDialog, QInputDialog,
                                   QMessageBox)
    for n in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, n,
                            staticmethod(lambda *a, **k: 0))
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    monkeypatch.setattr(QInputDialog, "getText",
                        staticmethod(lambda *a, **k: ("", False)))
    monkeypatch.setattr(QInputDialog, "getItem",
                        staticmethod(lambda *a, **k: ("", False)))
    monkeypatch.setattr(QDialog, "exec", lambda self, *a: 0)
    return QApplication.instance() or QApplication([])


def _port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def test_hub_over_the_hosted_relay(tmp_path, monkeypatch):
    """The real thing: hosted relay, WebSocket API, HTTP GET."""
    pytest.importorskip("websockets")
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "relay_server", os.path.join(ROOT, "server", "relay_server.py"))
    rs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rs)
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Jon"})
    port = _port()
    relay = rs.Relay(token="t0k", data_dir=str(tmp_path / "data"))
    ready = threading.Event()
    stop = {}

    def serve():
        async def main():
            async with rs.serve(relay.handler, "127.0.0.1", port,
                                process_request=rs.process_request,
                                max_size=rs.MAX_MESSAGE):
                stop["loop"] = asyncio.get_running_loop()
                stop["fut"] = stop["loop"].create_future()
                ready.set()
                await stop["fut"]
        asyncio.run(main())
    t = threading.Thread(target=serve, daemon=True)
    t.start()
    assert ready.wait(10)
    try:
        url = f"ws://127.0.0.1:{port}/"
        s = ProjectStore(str(tmp_path / "job"))
        s.save_record("rfi", {"subject": "Over the wire"})
        with pytest.raises(Exception, match="No such project"):
            s.connect(url, "Wire Job", "pw123456", token="bad")
        s.connect(url, "Wire Job", "pw123456", token="t0k")
        assert s.list("rfi")[0]["_no"] == "RFI-001"
        # a bigger project file goes up and down in chunks
        big = tmp_path / "set.pdf"
        big.write_bytes(os.urandom(9 * 1024 * 1024))
        c = hubclient.HubClient(url, "t0k")
        h = s.data["hub"]
        r = c.upload(h["key"], h["project"], str(big), note="IFC set")
        assert r["version"] == 1
        back = tmp_path / "back.pdf"
        c.download(h["key"], h["project"], "set.pdf", str(back))
        assert back.read_bytes() == big.read_bytes()
        files = c.call("proj.files", project=h["project"], key=h["key"])
        assert files["files"][0]["versions"][0]["note"] == "IFC set"
        # a photo from a phone, then fetched over plain HTTP
        img = tmp_path / "ph.png"
        img.write_bytes(fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 4, 4),
                                    0).tobytes("png"))
        ref = s.attach(str(img))
        body = urllib.request.urlopen(urllib.request.Request(
            f"http://127.0.0.1:{port}/hub/att/Wire%20Job/{ref['sha256']}",
            headers={"Authorization": f"Bearer {h['key']}"})).read()
        assert body == img.read_bytes()
    finally:
        stop["loop"].call_soon_threadsafe(stop["fut"].set_result, None)
        t.join(5)


def test_payapp_fill_leaves_out_later_change_orders(env):
    """Nov 1: a change order executed after the pay period was offered as a
    line on that pay app, and what was typed on it was dropped from the
    G702/G703 without a word. It is left off now; a later app gets it."""
    tmp, H = env
    from app.pm import cost
    s = ProjectStore(str(tmp / "p2"))
    s.save_record("contract", {"item": "1", "description": "Example work",
                               "scheduled": 1000})
    s.save_record("event", {"title": "Example change", "status": "Approved",
                            "approved": "2026-11-05", "co_no": "CO-001",
                            "lines": [{"cost_code": "03 30 00",
                                       "cost": 100}]})
    early = s.save_record("payapp", {"period_to": "2026-10-31"})
    assert [l["item"] for l in cost.fill_payapp(s, early)] == ["1"]
    late = s.save_record("payapp", {"period_to": "2026-11-30"})
    assert [l["item"] for l in cost.fill_payapp(s, late)] == ["1", "CO-001"]


def test_cost_management(env):
    tmp, H = env
    from app.pm import cost
    s = ProjectStore(str(tmp / "p"))
    _team(s)
    s.set_setting("owner", "Aiken County")
    s.set_setting("owner_contact", "Ann Arch")
    s.save_record("budget", {"cost_code": "03 30 00", "description":
                             "Concrete", "category": "Subcontractor",
                             "original": 100000})
    s.save_record("budget", {"cost_code": "26 00 00", "description":
                             "Electrical", "category": "Subcontractor",
                             "original": 80000})
    s.save_record("contract", {"item": "1", "description": "Sitework and "
                               "concrete", "scheduled": 120000})
    s.save_record("contract", {"item": "2", "description": "Electrical",
                               "scheduled": 100000})
    c = s.save_record("commitment", {"title": "Concrete", "vendor":
                                     "Sam Sub", "lines": [
                                         {"cost_code": "033000",
                                          "amount": 95000}]})
    ctx = actions.Ctx(s)
    c = actions.run(ctx, "commitment", c, "Send for Signature")
    assert c["status"] == "Out for Signature"
    assert mail.OUTBOX[-1]["to"] == ["sam@sub.example"]
    ev = s.save_record("event", {"title": "Kennel drains", "lines": [
        {"cost_code": "03 30 00", "vendor": "Sam Sub", "cost": 5000,
         "markup": 10}], "status": "Open"})
    ev = actions.run(ctx, "event", ev, "Send to Owner")
    assert ev["status"] == "Pending"
    assert mail.OUTBOX[-1]["to"] == ["ann@arch.example"]
    assert "$5,500" in mail.OUTBOX[-1]["body"]
    # a fixed date inside the pay period: with today's date the CO is
    # executed after 2026-10-31 and rightly left off that pay app (Nov 1)
    ev["approved"] = "2026-10-20"
    ev = actions.run(ctx, "event", ev, "Owner Approved")
    assert ev["co_no"] == "CO-001" and ev["approved"] == "2026-10-20"
    s.save_record("cost", {"date": "2026-10-01", "vendor": "Sam Sub",
                           "cost_code": "03 30 00", "amount": 40000,
                           "commitment": c["_id"], "retainage": 4000})
    rows = cost.by_code(s)
    assert rows["03 30 00"]["revised"] == 105000
    assert rows["03 30 00"]["committed"] == 100000
    assert rows["03 30 00"]["actual"] == 40000
    assert rows["03 30 00"]["fac"] == 105000
    assert rows["26 00 00"]["etc"] == 80000
    n = cost.commitment_numbers(s, c)
    assert (n["revised"], n["invoiced"], n["remaining"]) == \
        (100000, 40000, 60000)
    sm = cost.summary(s)
    assert sm["contract"]["revised"] == 225500
    assert round(sm["margin"]) == 225500 - 185000
    # owner pay app: fill from the contract, bill, print G702/G703
    pa = s.save_record("payapp", {"period_to": "2026-10-31",
                                  "retainage_work": 10,
                                  "retainage_stored": 10})
    pa = actions.run(ctx, "payapp", pa, "Fill from Contract")
    assert [l["item"] for l in pa["lines"]] == ["1", "2", "CO-001"]
    pa["lines"][0]["this_period"] = 60000
    pa["lines"][2]["this_period"] = 5500
    pa = s.save_record("payapp", pa)
    v = cost.payapp_values(s, pa)
    assert v["g702"]["1"] == 220000 and v["g702"]["2"] == 5500
    assert v["g702"]["4"] == 65500 and v["g702"]["5"] == 6550
    assert v["g702"]["8"] == 58950
    pa = actions.run(ctx, "payapp", pa, "Submit to Owner")
    assert pa["status"] == "Submitted"
    sent = mail.OUTBOX[-1]["attachments"]
    # company rule: date first
    g702 = [p for p in sent if "2026.10.31 " in p and
            "Pay Application 001.pdf" in p][0]
    text = fitz.open(g702)[0].get_text()
    assert "58,950.00" in text
    ctx.ask_text = lambda title, default="": default
    pa = actions.run(ctx, "payapp", pa, "Record Payment")
    assert pa["received"] == 58950 and pa["status"] == "Paid"
    # second app picks up what was billed before
    pa2 = s.save_record("payapp", {"period_to": "2026-11-30"})
    pa2 = actions.run(ctx, "payapp", pa2, "Fill from Contract")
    assert pa2["lines"][0]["previous"] == 60000
    sm = cost.summary(s)
    assert sm["received"] == 58950
    # reports
    from app.pm.costui import cost_summary_pdf
    p = cost_summary_pdf(s, str(tmp / "cs.pdf"))
    assert "Projected margin" in fitz.open(p)[0].get_text()
    csv = cost.sage_csv(s, str(tmp / "sage.csv"))
    body = open(csv).read()
    assert "Budget" in body and "Commitment" in body and "03 30 00" in body


def test_bid_packages(env):
    tmp, H = env
    s = ProjectStore(str(tmp / "p"))
    _team(s)
    s.connect("ws://hub", "Bid Job", "pw123456")
    doc = s.attach(str(_pdf(tmp / "A-101.pdf")))
    pkg = s.save_record("bidpkg", {
        "title": "Electrical", "trades": "26 00 00", "due": "2026-11-01",
        "scope": "Complete electrical per E-series.", "documents": [doc],
        "bidders": [{"company": "Volt Electric", "email": "bids@volt.example"},
                    {"company": "Spark Co", "email": "est@spark.example"}]})
    ctx = actions.Ctx(s)
    pkg = actions.run(ctx, "bidpkg", pkg, "Send Invitations")
    assert pkg["status"] == "Open"
    assert all(b.get("token") for b in pkg["bidders"])
    assert len(mail.OUTBOX) == 2
    assert "http://hub/bid.html?t=" in mail.OUTBOX[0]["body"]
    s.sync()
    tok = s.list("bidpkg")[0]["bidders"][0]["token"]
    info = H.call("bid.open", {"token": tok}, {}, authed=False)
    assert info["title"] == "Electrical" and info["company"] == \
        "Volt Electric"
    st, ctype, body = H.get(f"/hub/bid/{tok}/{doc['sha256']}")
    assert st == 200 and body[:4] == b"%PDF"
    assert H.get(f"/hub/bid/{tok}/{'0' * 64}")[0] == 403
    import base64
    H.call("bid.respond", {"token": tok, "intent": "Will Bid",
                           "amount": "$212,400", "note": "Excl. fire alarm",
                           "file": base64.b64encode(b"%PDF-1.4 bid")
                           .decode(), "file_name": "Volt bid.pdf"},
           {}, authed=False)
    s.sync()
    rec = s.list("bidpkg")[0]
    volt = rec["bidders"][0]
    assert (volt["status"], volt["amount"]) == ("Bid Received", 212400)
    assert volt["bid_file"]["name"] == "Volt bid.pdf"
    # the desktop table keeps hidden keys (tokens, files) when edited
    from app.pm.widgets import LinesEdit
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    le = LinesEdit(schema.field("bidpkg", "bidders")["cols"], s)
    le.set_value(rec["bidders"])
    assert le.value()[0]["token"] == tok
    rec["bidders"][1]["amount"] = 219000
    rec = s.save_record("bidpkg", rec)
    ctx.ask = lambda title, opts: opts[0]
    rec = actions.run(ctx, "bidpkg", rec, "Award")
    assert rec["status"] == "Awarded" and rec["awarded_to"] == "Volt Electric"
    c = s.list("commitment")[0]
    assert c["vendor"] == "Volt Electric" and c["lines"][0]["amount"] == \
        212400


def _pdf(path):
    d = fitz.open()
    d.new_page().insert_text((72, 72), "A-101 FLOOR PLAN")
    d.save(str(path))
    return path
