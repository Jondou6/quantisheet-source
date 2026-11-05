"""PreconSuite round 2: company directory (favorites, certifications,
compliance, bid history), prequalification forms, sealed bids, leveling
plugs, award letters, bidding reports - and per-user logins with roles
(review item R8)."""
import datetime as dt
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import mail, prequal, settings, subdir                # noqa: E402
from app.collab import hub as hubmod                           # noqa: E402
from app.pm import actions, bidreports                         # noqa: E402
from app.pm.store import ProjectStore                          # noqa: E402
from test_pm import env, qapp_pm, _team                        # noqa: E402,F401

FORM = [{"item": "1", "description": "Mobilization", "type": "Lump sum"},
        {"item": "2", "description": "8 in PVC sewer", "type": "Unit price",
         "qty": 100, "unit": "LF"}]


# ------------------------------------------------------------ directory
def test_directory_edit_favorites_certs_alerts_history(env):
    a = subdir.upsert({"company": "Dig Co", "email": "est@dig.example",
                       "division": "33", "certs": "MBE, DBE",
                       "insurance_exp": "2020-01-01"})
    b = subdir.upsert({"company": "Pipe Pros", "email": "bid@pipe.example",
                       "division": "33", "state": "South Carolina"})
    assert a["id"] and b["state"] == "SC"
    subdir.upsert(dict(a, phone="555-1212"))
    assert len(subdir.load()) == 2 and subdir.get(a["id"])["phone"] == \
        "555-1212"
    assert subdir.toggle_favorite(b["id"]) is True
    assert [c["company"] for c in subdir.search()][0] == "Pipe Pros"
    assert [c["company"] for c in subdir.search(favorites=True)] == \
        ["Pipe Pros"]
    assert [c["company"] for c in subdir.search(cert="dbe")] == ["Dig Co"]
    al = subdir.alerts(today=dt.date(2026, 10, 1))
    assert al[0][0]["company"] == "Dig Co" and al[0][3] is True
    # prequalified, and only up to a limit
    subdir.upsert(dict(subdir.get(b["id"]), prequal="Approved",
                       prequal_exp="2099-01-01", prequal_limit="500000"))
    pp = subdir.get(b["id"])
    assert subdir.prequal_ok(pp) and not subdir.prequal_ok(pp, 900000)
    assert subdir.prequal_status(subdir.get(a["id"])) == "Not prequalified"
    assert [c["company"] for c in subdir.search(prequalified=True)] == \
        ["Pipe Pros"]
    # bid history survives contact edits
    subdir.record_bid("Dig Co", "Aiken Clinic", "Sewer", 100000, "Awarded")
    subdir.record_bid("DIG CO.", "Aiken Clinic", "Water", 50000,
                      "Not awarded")
    subdir.upsert(dict(subdir.get(a["id"]), notes="good"))
    st = subdir.stats("Dig Co")
    assert st["bids"] == 2 and st["wins"] == 1 and st["win_rate"] == 0.5
    assert subdir.remove(a["id"]) == 1 and len(subdir.load()) == 1


def test_directory_window_buttons(env, qapp_pm, tmp_path):
    from app.subdir_ui import DirectoryWidget
    w = DirectoryWidget()
    w.add({"company": "Volt Electric", "email": "bids@volt.example",
           "certs": "WBE", "division": "26"})
    assert w.table.rowCount() == 1
    w.table.selectRow(0)
    assert w.favorite() is True
    w.table.selectRow(0)
    w.edit(dict(subdir.load()[0], contact="Vic"))
    assert subdir.load()[0]["contact"] == "Vic"
    w.cert.setCurrentText("MBE")
    assert w.table.rowCount() == 0
    w.cert.setCurrentText("WBE")
    assert w.table.rowCount() == 1
    # prequal: send the form, read it back filled in
    w.table.selectRow(0)
    n = len(mail.OUTBOX)
    assert w.send_prequal(gc="Example Builders")
    assert len(mail.OUTBOX) == n + 1 and subdir.load()[0]["prequal"] == "Sent"
    pdf = mail.OUTBOX[-1]["attachments"][0]
    filled = tmp_path / "back.pdf"
    _fill(pdf, filled, {"legal_name": "Volt Electric", "years": "12",
                        "emr": "0.82, 0.85, 0.79", "safety_program": "Yes",
                        "osha_citations": "No", "litigation": "No",
                        "default": "No", "bond_single": "$2.5M",
                        "ins_carrier": "Acme", "ins_exp": "06/30/2027",
                        "references": "x", "signer": "Vic, Pres",
                        "certs": "WBE, SBE", "license": "SC 12345"})
    w.table.selectRow(0)
    got = []
    out = w.read_prequal(str(filled), decide=lambda *a: (got.append(a) or
                                                        ("Approved", a[3])))
    assert got[0][0] >= 90 and got[0][2] == "Approved"
    assert out["prequal"] == "Approved" and out["prequal_limit"] == \
        "2500000" and out["insurance_exp"] == "2027-06-30"
    assert out["certs"] == "WBE, SBE" and out["license"] == "SC 12345"
    assert subdir.prequal_ok(out)


def _fill(src, dst, values):
    d = fitz.open(src)
    for page in d:
        for wd in page.widgets():
            if wd.field_name in values:
                wd.field_value = values[wd.field_name]
                wd.update()
    d.save(str(dst))


def test_prequal_score_flags_problems(tmp_path):
    p = prequal.make_form(str(tmp_path / "f.pdf"), "Bad Co", "GC")
    ans = prequal.read_form(p)
    assert ans["legal_name"] == "Bad Co"
    pts, notes, st, lim = prequal.score({"emr": "1.45", "years": "1",
                                         "default": "Yes"})
    assert pts < 40 and st == "Pending" and lim is None
    assert any("EMR" in n for n in notes)
    with pytest.raises(ValueError):
        q = fitz.open()
        q.new_page()
        q.save(str(tmp_path / "plain.pdf"))
        prequal.read_form(str(tmp_path / "plain.pdf"))


def test_company_bidders_prequal_choice(env):
    tmp, H = env
    subdir.upsert({"company": "Dig Co", "email": "est@dig.example",
                   "division": "33", "prequal": "Approved",
                   "prequal_exp": "2099-01-01"})
    subdir.upsert({"company": "New Guy", "email": "n@new.example",
                   "division": "33"})
    s = ProjectStore(str(tmp / "p"))
    pkg = s.save_record("bidpkg", {"title": "Sewer", "trades": "33 30 00"})
    ctx = actions.Ctx(s)
    ctx.ask = lambda t, opts: next(o for o in opts if "prequalified" in o)
    pkg = actions.run(ctx, "bidpkg", pkg, "Add Bidders from Company "
                                          "Directory")
    assert [b["company"] for b in pkg["bidders"]] == ["Dig Co"]
    ctx.ask = lambda t, opts: opts[0]
    pkg = actions.run(ctx, "bidpkg", pkg, "Add Bidders from Company "
                                          "Directory")
    guy = next(b for b in pkg["bidders"] if b["company"] == "New Guy")
    assert "prequal" in guy["note"]


# ------------------------------------------------------------ sealed bids
def _now(monkeypatch, when):
    monkeypatch.setattr(hubmod, "_now_local", lambda: when)


def test_sealed_bids_open_only_after_deadline(env, monkeypatch):
    tmp, H = env
    s = ProjectStore(str(tmp / "p"))
    _team(s)
    s.connect("ws://hub", "Sealed Job", "pw123456")
    pkg = s.save_record("bidpkg", {
        "title": "Sewer", "due": "2026-11-20", "due_time": "2:00 PM",
        "sealed": "Yes", "form": FORM,
        "bidders": [{"company": "Dig Co", "email": "est@dig.example"},
                    {"company": "Pipe Pros", "email": "bid@pipe.example"}]})
    ctx = actions.Ctx(s)
    pkg = actions.run(ctx, "bidpkg", pkg, "Send Invitations")
    s.sync()
    toks = [b["token"] for b in pkg["bidders"]]
    _now(monkeypatch, dt.datetime(2026, 11, 19, 9, 0))
    H.call("bid.respond", {"token": toks[0], "intent": "Will Bid",
                           "form": {"0": "5000", "1": "40"}}, {}, False)
    H.call("bid.respond", {"token": toks[1], "intent": "Will Bid",
                           "form": {"0": "4000", "1": "45"}}, {}, False)
    # a bidder sees only that their sealed bid arrived (0.13.5: a sealed
    # number is never read back, not even with the bidder's own link)
    mine = H.call("bid.open", {"token": toks[0]}, {}, False)
    assert mine["sealed"] and mine["values"] == {} and \
        mine["amount"] is None and mine["status"] == "Bid Received" and \
        mine["sealed_received"]
    s.sync()
    rec = s.list("bidpkg")[0]
    assert all(b["status"] == "Bid Received" for b in rec["bidders"])
    assert all(b.get("amount") in (None, "") and not b.get("form_values")
               for b in rec["bidders"])            # the GC can't see them
    names = [a[0] for a in actions.available("bidpkg", rec)]
    assert "Open Sealed Bids" in names and "Award" not in names \
        and "Level Bids" not in names
    msgs = []
    ctx.notify = msgs.append
    assert actions.run(ctx, "bidpkg", rec, "Open Sealed Bids") is None
    assert "before the deadline" in msgs[-1]
    # after 2 PM on the due date: no more sealed bids, and they open
    _now(monkeypatch, dt.datetime(2026, 11, 20, 14, 1))
    with pytest.raises(hubmod.HubError, match="deadline"):
        H.call("bid.respond", {"token": toks[1], "intent": "Will Bid",
                               "form": {"0": "1", "1": "1"}}, {}, False)
    rec = actions.run(ctx, "bidpkg", s.list("bidpkg")[0], "Open Sealed Bids")
    assert rec["unsealed"] and rec["unsealed_by"] == "Pat Morgan"
    am = {b["company"]: b["amount"] for b in rec["bidders"]}
    assert am == {"Dig Co": 9000.0, "Pipe Pros": 8500.0}
    ev = H.call("proj.activity", {"project": "Sealed Job",
                                  "key": s.data["hub"]["key"]}, {})
    assert any("opened 2 sealed" in e["action"] for e in ev["events"])


def test_deadline_parse():
    d = hubmod._deadline({"due": "2026-11-20", "due_time": "10:30 am"})
    assert (d.hour, d.minute) == (10, 30)
    assert hubmod._deadline({"due": "2026-11-20"}).hour == 14
    assert hubmod._deadline({"due": ""}) is None


# ------------------------------------------------------------ plugs
def test_leveling_plugs_and_adjustments():
    from app import leveling

    def row(b, no, desc, unit, qty, price):
        return {"desc": desc, "unit": unit, "qty": qty, "price": price,
                "item_no": no, "bidder": b, "note": ""}
    bids = {"A": [row("A", "1", "Mob", "LS", 1, 1000),
                  row("A", "2", "Pipe", "LF", 100, 10)],
            "B": [row("B", "1", "Mob", "LS", 1, 1200)],
            "C": [row("C", "1", "Mob", "LS", 1, 900),
                  row("C", "2", "Pipe", "LF", 100, 12)]}
    base = {r["bidder"]: r for r in leveling.run(bids, use_vocab=False)
            ["results"]}
    assert base["B"]["added"] == pytest.approx(1100)
    res = leveling.run(bids, use_vocab=False, plugs=[
        {"bidder": "B", "item": "2", "kind": "Plug", "amount": 500},
        {"bidder": "A", "item": "", "kind": "Adjustment", "amount": 300,
         "note": "no bond"},
        {"bidder": "C", "item": "Pipe", "kind": "Override", "amount": 11}])
    r = {x["bidder"]: x for x in res["results"]}
    assert r["B"]["leveled"] == pytest.approx(1700)
    assert r["A"]["leveled"] == pytest.approx(2300)
    assert r["C"]["base"] == pytest.approx(2000)
    assert res["results"][0]["bidder"] == "B"
    pipe = next(i for i in res["items"] if i.item_no == "2")
    assert leveling.cell(res, pipe, "B")[1] == "plug"
    inc = leveling.run(bids, use_vocab=False, plugs=[
        {"bidder": "B", "item": "2", "kind": "Included"}])
    assert {x["bidder"]: x for x in inc["results"]}["B"]["omissions"] == 0


def test_leveling_window_saves_plugs(qapp_pm):
    from app.leveling_ui import LevelingDialog
    bids = {b: [{"desc": "Mob", "unit": "LS", "qty": 1, "price": p,
                 "item_no": "1", "bidder": b, "note": ""}]
            for b, p in (("A", 100), ("B", 120))}
    bids["A"].append({"desc": "Pipe", "unit": "LF", "qty": 10, "price": 5,
                      "item_no": "2", "bidder": "A", "note": ""})
    bids["C"] = [dict(bids["A"][0], bidder="C", price=90),
                 dict(bids["A"][1], bidder="C", price=6)]
    saved = []
    d = LevelingDialog()
    d.bids = bids
    d.on_plugs = saved.append
    d.project.addItem("t", "files")
    d.project.setCurrentIndex(d.project.count() - 1)
    d.run()
    d.add_plug("B", "2", "Plug", 40.0, "our number")
    d.add_plug("A", "", "Adjustment", -10.0, "credit")
    assert saved[-1][0]["kind"] == "Plug" and d.plug_table.rowCount() == 2
    lev = {r["bidder"]: r["leveled"] for r in d.res["results"]}
    assert lev["B"] == pytest.approx(160) and lev["A"] == pytest.approx(140)
    d.remove_plug(1)
    assert len(saved[-1]) == 1


# ------------------------------------------------------------ award letters
def test_award_letters_history_and_reports(env, tmp_path):
    tmp, H = env
    s = ProjectStore(str(tmp / "p"))
    _team(s)
    s.save_record("budget", {"cost_code": "33 30 00", "description":
                             "Sanitary sewer", "original": 100000})
    pkg = s.save_record("bidpkg", {
        "title": "Sewer", "trades": "33 30 00 Sanitary", "status": "Open",
        "bidders": [{"company": "Dig Co", "email": "est@dig.example",
                     "amount": 95000, "status": "Bid Received"},
                    {"company": "Pipe Pros", "email": "bid@pipe.example",
                     "amount": 99000, "status": "Bid Received"},
                    {"company": "Nope Inc", "email": "x@nope.example",
                     "status": "Won't Bid"}]})
    ctx = actions.Ctx(s)
    ctx.ask = lambda title, opts: opts[0]
    rec = actions.run(ctx, "bidpkg", pkg, "Award")
    assert rec["awarded_to"] == "Dig Co" and rec["award_amount"] == 95000
    kinds = sorted((x["letter"], x["company"]) for x in rec["letters"])
    assert kinds == [("award", "Dig Co"), ("regret", "Pipe Pros")]
    award = fitz.open(s.attachment_path(next(
        x for x in rec["letters"] if x["letter"] == "award")))
    txt = award[0].get_text()
    assert "Dig Co" in txt and "$95,000.00" in txt and "Intent to Award" \
        in txt
    n = len(mail.OUTBOX)
    rec = actions.run(ctx, "bidpkg", rec, "Send Award Letters")
    assert len(mail.OUTBOX) == n + 2 and rec["letters_sent"]
    assert "Send Award Letters" not in [a[0] for a in
                                        actions.available("bidpkg", rec)]
    assert subdir.stats("Dig Co")["wins"] == 1
    assert subdir.stats("Pipe Pros")["bids"] == 1
    # reports
    rows = bidreports.package_rows(s)
    assert rows[1][-2:] == ["Dig Co", 95000]
    buy = bidreports.buyout_rows(s)
    assert buy[1][3] == 100000 and buy[1][7] == -5000
    cov = bidreports.coverage_rows(s)
    assert len(cov) == 4
    path = bidreports.export_xlsx(s, str(tmp_path / "bid.xlsx"))
    import openpyxl
    wb = openpyxl.load_workbook(path)
    assert wb.sheetnames == ["Packages", "Bidder Coverage", "Buyout",
                             "Bidder History"]


# ------------------------------------------------------------ R8 logins
def test_logins_and_roles(env):
    tmp, H = env
    admin = ProjectStore(str(tmp / "a"))
    admin.connect("ws://hub", "Role Job", "pw123456")
    assert admin.role == "admin" and admin.can_edit
    rfi = admin.save_record("rfi", {"subject": "Footing", "question": "?",
                                    "to": "Ann Arch"})
    admin.sync()
    # turn on logins: the first is me, as admin, and my key switches
    admin.add_user("pat@builder.example", "Pat Morgan", "admin",
                   "longpassword1")
    assert admin.data["hub"]["logins"] and \
        admin.data["hub"]["key"].startswith("u.")
    admin.add_user("vera@view.example", "Vera Viewer", "viewer",
                   "viewpass123")
    admin.add_user("sam@sub.example", "Sam Sub", "sub", "subpass123")
    with pytest.raises(Exception, match="8 or more"):
        admin.add_user("x@y.example", "X", "pm", "short")
    assert {u["email"] for u in admin.users()} == {
        "pat@builder.example", "vera@view.example", "sam@sub.example"}
    # the shared project password no longer opens it
    other = ProjectStore(str(tmp / "o"))
    with pytest.raises(Exception, match="logins"):
        other.connect("ws://hub", "Role Job", "pw123456")
    # a viewer can read but not change an RFI
    v = ProjectStore(str(tmp / "v"))
    v.connect("ws://hub", "Role Job", "viewpass123",
              email="vera@view.example")
    assert v.role == "viewer" and not v.can_edit
    r = v.list("rfi")[0]
    v.save_record("rfi", dict(r, subject="Changed by viewer"))
    res = v.sync()
    assert res["denied"] == 1 and "view-only" in v.last_denied
    assert v.list("rfi")[0]["subject"] == "Footing"       # put back
    admin.sync()
    assert admin.list("rfi")[0]["subject"] == "Footing"
    # a sub may add an RFI, and change only their own
    sub = ProjectStore(str(tmp / "s"))
    sub.connect("ws://hub", "Role Job", "subpass123",
                email="sam@sub.example")
    mine = sub.save_record("rfi", {"subject": "Sleeve size", "question":
                                   "?"})
    assert sub.sync()["denied"] == 0
    sub.save_record("rfi", dict(sub.get("rfi", rfi["_id"]),
                                subject="hijack"))
    assert sub.sync()["denied"] == 1
    sub.save_record("budget", {"cost_code": "01", "description": "x",
                               "original": 1})
    assert sub.sync()["denied"] == 1 and not sub.list("budget")
    # the record and the activity log carry the real user
    admin.sync()
    got = admin.get("rfi", mine["_id"])
    assert got["_by"] == "Sam Sub" and got["_by_id"] == "sam@sub.example"
    ev = H.call("proj.activity", {"project": "Role Job",
                                  "key": admin.data["hub"]["key"]}, {})
    added = [e for e in ev["events"] if e["action"] == "added rfi"]
    assert added[-1]["uid"] == "sam@sub.example" and \
        added[-1]["role"] == "sub"
    # only an admin manages logins; the last admin stays
    with pytest.raises(Exception, match="admin"):
        sub.users()
    with pytest.raises(Exception, match="at least one admin"):
        admin.set_user("pat@builder.example", role="pm")
    # wrong password, disabled login, password change
    with pytest.raises(Exception, match="Wrong email or password"):
        ProjectStore(str(tmp / "x")).connect(
            "ws://hub", "Role Job", "nope", email="sam@sub.example")
    admin.set_user("sam@sub.example", disabled=True)
    with pytest.raises(Exception):
        sub.sync()
    assert v.change_password("viewpass123", "newviewpass1")
    v.sync()


def test_users_dialog(env, qapp_pm):
    from PySide6.QtWidgets import QMainWindow
    from app.pm.usersui import UsersDialog
    tmp, H = env
    s = ProjectStore(str(tmp / "a"))
    s.connect("ws://hub", "UI Job", "pw123456")

    class Center(QMainWindow):
        store = s
    d = UsersDialog(Center())
    assert d.add_btn.text() == "Turn On Logins…"
    d.add({"email": "pat@builder.example", "name": "Jon",
           "password": "longpassword1", "role": "viewer"})
    assert s.data["hub"]["logins"] and d.table.rowCount() == 1
    d.add({"email": "pm@x.example", "name": "Pat", "role": "pm",
           "password": "pmpassword1"})
    d.table.selectRow(1)
    d.change_role("estimator")
    assert {u["email"]: u["role"] for u in d.users}["pm@x.example"] == \
        "estimator"
    d.table.selectRow(1)
    d.remove(confirm=False)
    assert d.table.rowCount() == 1
