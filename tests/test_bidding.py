"""Bid management (PreconSuite-style): bid packages from trades, bid forms
priced online, addenda with acknowledgment, invitations, leveling from the
forms, and the bid calendar."""
import base64
import csv
import datetime as dt
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import annotate, mail                                # noqa: E402
from app.collab import hub as hubmod                          # noqa: E402
from app.pm import actions, bidforms                          # noqa: E402
from app.pm.store import ProjectStore                         # noqa: E402
from test_pm import env, _team, _pdf                          # noqa: E402,F401

FORM = [
    {"item": "1", "description": "Mobilization", "type": "Lump sum"},
    {"item": "2", "description": "8 in PVC sewer", "type": "Unit price",
     "qty": 1200, "unit": "LF"},
    {"item": "3", "description": "Manholes", "type": "Unit price",
     "qty": 6, "unit": "EA"},
    {"item": "4", "description": "Rock (allowance)", "type": "Allowance",
     "qty": 15000},
    {"item": "5", "description": "Alt 1: DIP in lieu of PVC",
     "type": "Alternate"},
    {"item": "6", "description": "Bid bond included?", "type": "Yes / No"},
]


def test_totals_and_leveling_rows():
    vals = {"0": "25,000", "1": "$42.50", "2": "5200", "4": "18000",
            "5": "Yes"}
    t = bidforms.totals(FORM, vals)
    assert t["base"] == pytest.approx(25000 + 1200 * 42.5 + 6 * 5200 + 15000)
    assert t["alternates"] == {"5": 18000.0} and t["missing"] == []
    t2 = bidforms.totals(FORM, {"0": "25000"})
    assert t2["missing"] == ["2", "3"]
    # hub (runs alone on a server) adds up the same way
    assert hubmod.bid_totals(FORM, vals) == t
    rec = {"title": "Sewer", "form": FORM, "bidders": [
        {"company": "A Co", "form_values": vals},
        {"company": "B Co", "form_values": {"0": "30000", "1": "40",
                                            "2": "4900"}},
        {"company": "C Co", "amount": 190000}]}
    lv = bidforms.to_leveling(rec)
    assert set(lv) == {"A Co", "B Co", "C Co"}
    a = {r["item_no"]: r for r in lv["A Co"]}
    assert a["2"]["qty"] == 1200 and a["2"]["price"] == 42.5
    assert a["4"]["price"] == 15000 and "5" not in a      # alternate out
    from app import leveling
    res = leveling.run(lv, use_vocab=False)
    assert len(res["results"]) == 3


def test_templates_imports_and_takeoff(tmp_path, monkeypatch):
    from app import settings
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    lib = bidforms.library()
    assert "Site utilities" in lib and "Electrical" in lib
    bidforms.save_template("My sewer", FORM)
    assert bidforms.library()["My sewer"][1]["qty"] == 1200
    p = tmp_path / "form.csv"
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Item", "Description", "Type", "Qty", "UOM"])
        w.writerow(["1", "Mobilization", "LS", "", ""])
        w.writerow(["2", "Water main", "unit", "800", "LF"])
        w.writerow(["3", "Bond?", "y/n", "", ""])
    lines = bidforms.import_lines(str(p))
    assert [x["type"] for x in lines] == ["Lump sum", "Unit price",
                                          "Yes / No"]
    assert lines[1]["qty"] == 800
    b = tmp_path / "subs.csv"
    with open(b, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Company Name", "Estimator", "E-mail", "Phone", "Trade"])
        w.writerow(["Volt Electric", "Vic", "bids@volt.example", "555",
                    "Electrical"])
        w.writerow(["No Mail Co", "", "", "", "Electrical"])
    rows = bidforms.import_rows(str(b))
    assert rows[0]["company"] == "Volt Electric" and \
        rows[0]["contact"] == "Vic" and rows[0]["email"] == \
        "bids@volt.example"
    d = fitz.open()
    d.new_page()
    annotate.apply_op(d, annotate.new_op("set_scale", 0, ppu=18,
                                         unit="ft"))
    for x in (100, 300):
        annotate.apply_op(d, annotate.new_op(
            "add_line", 0, pts=[[x, 100], [x, 280]],
            measure={"type": "length", "value": 10, "unit": "ft",
                     "group": "8 in sewer"}))
    annotate.apply_op(d, annotate.new_op(
        "add_count", 0, pt=[50, 50], n=1,
        measure={"type": "count", "value": 1, "unit": "ea",
                 "group": "Manhole"}))
    tl = {x["description"]: x for x in bidforms.from_takeoff(d)}
    assert tl["8 in sewer"]["qty"] == 20 and tl["8 in sewer"]["unit"] == "LF"
    assert tl["Manhole"]["unit"] == "EA"


def test_bid_form_online_with_addenda(env):
    tmp, H = env
    s = ProjectStore(str(tmp / "p"))
    _team(s)
    s.connect("ws://hub", "Sewer Job", "pw123456")
    doc = s.attach(str(_pdf(tmp / "C-201.pdf")))
    pkg = s.save_record("bidpkg", {
        "title": "Sanitary sewer", "trades": "33 30 00", "due":
        "2026-11-20", "documents": [doc], "rfi_due": "2026-11-12",
        "bidders": [{"company": "Dig Co", "email": "est@dig.example"},
                    {"company": "Pipe Pros", "email": "bid@pipe.example"}]})
    ctx = actions.Ctx(s)
    ctx.ask = lambda title, opts: next(o for o in opts
                                       if "Site utilities" in o)
    pkg = actions.run(ctx, "bidpkg", pkg, "Bid Form…")
    assert pkg["form"] and pkg["form"][1]["type"] == "Unit price"
    pkg["form"] = FORM
    pkg = s.save_record("bidpkg", pkg)
    pkg = actions.run(ctx, "bidpkg", pkg, "Send Invitations")
    toks = [b["token"] for b in pkg["bidders"]]
    # an addendum: numbered, and bidders are told
    ctx.ask_text = lambda title, default="": "Revised manhole detail"
    ctx.pick_file = lambda title, f="": str(_pdf(tmp / "ADD1.pdf"))
    n_mail = len(mail.OUTBOX)
    pkg = actions.run(ctx, "bidpkg", pkg, "Issue Addendum…")
    assert pkg["addenda"][0]["number"] == "1"
    assert any(d["name"].startswith("Addendum 1") for d in pkg["documents"])
    assert len(mail.OUTBOX) == n_mail + 2
    s.sync()
    info = H.call("bid.open", {"token": toks[0]}, {}, authed=False)
    assert info["form"][1]["qty"] == 1200 and info["addenda"][0]["number"] \
        == "1" and info["rfi_due"] == "2026-11-12"
    vals = {"0": "25000", "1": "42.50", "2": "5200", "4": "18000",
            "5": "Yes"}
    with pytest.raises(hubmod.HubError, match="addendum"):
        H.call("bid.respond", {"token": toks[0], "intent": "Will Bid",
                               "form": vals}, {}, authed=False)
    H.call("bid.respond", {"token": toks[0], "intent": "Will Bid",
                           "form": vals, "acks": ["1"],
                           "exclusions": "No rock over allowance"},
           {}, authed=False)
    H.call("bid.respond", {"token": toks[1], "intent": "Will Bid",
                           "form": {"0": "30000", "1": "40", "2": "4900"},
                           "acks": ["1"]}, {}, authed=False)
    s.sync()
    rec = s.list("bidpkg")[0]
    dig = rec["bidders"][0]
    assert dig["status"] == "Bid Received"
    assert dig["amount"] == pytest.approx(25000 + 51000 + 31200 + 15000)
    assert dig["alternates"] == {"5": 18000.0} and dig["acks"] == "1"
    assert dig["exclusions"] == "No rock over allowance"
    pipe = rec["bidders"][1]
    assert pipe["form_missing"] == []
    # level the bids straight from the forms
    shown = {}
    ctx.level = lambda bids, title="", **kw: shown.update(bids=bids, title=title, **kw)
    assert "Level Bids" in [a[0] for a in actions.available("bidpkg", rec)]
    actions.run(ctx, "bidpkg", rec, "Level Bids")
    assert set(shown["bids"]) == {"Dig Co", "Pipe Pros"}
    # Award takes the form total
    ctx.ask = lambda title, opts: opts[0]
    rec = actions.run(ctx, "bidpkg", rec, "Award")
    assert rec["awarded_to"] == "Dig Co"            # the low base bid


def test_import_and_directory_bidders(env, tmp_path):
    tmp, H = env
    s = ProjectStore(str(tmp / "p2"))
    _team(s)
    s.save_record("member", {"name": "Ed Wire", "company": "Wire Works",
                             "email": "ed@wire.example",
                             "role": "Subcontractor",
                             "trade": "Electrical"})
    pkg = s.save_record("bidpkg", {"title": "Electrical", "trades":
                                   "26 00 00 Electrical"})
    ctx = actions.Ctx(s)
    ctx.ask = lambda title, opts: opts[0]
    pkg = actions.run(ctx, "bidpkg", pkg, "Add Bidders from Project Team")
    assert [b["company"] for b in pkg["bidders"]] == ["Wire Works"]
    p = tmp_path / "subs.csv"
    with open(p, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Company", "Contact", "Email"])
        w.writerow(["Volt Electric", "Vic", "bids@volt.example"])
        w.writerow(["Wire Works", "Ed", "ed@wire.example"])   # duplicate
    ctx.pick_file = lambda title, f="": str(p)
    pkg = actions.run(ctx, "bidpkg", pkg, "Import Bidders…")
    assert [b["company"] for b in pkg["bidders"]] == ["Wire Works",
                                                      "Volt Electric"]


def test_packages_from_trades_and_calendar(env, tmp_path, monkeypatch):
    tmp, H = env
    from app import settings
    from app.pm import bidui
    s = ProjectStore(str(tmp / "p3"))
    made = bidui.make_packages(s, [
        {"csi": "33 30 00", "trade": "Sanitary sewer", "due": "2026-11-20",
         "form": "Site utilities"},
        {"csi": "26 00 00", "trade": "Electrical", "due": "2026-11-21",
         "form": "Electrical"}])
    assert len(made) == 2 and made[0]["form"] and \
        "Section 33 30 00" in made[0]["scope"]
    r = s.list("bidpkg")[0]
    r.update(prebid="2026-11-05 10:00 AM at the site", rfi_due="2026-11-12",
             due_time="2:00 PM")
    s.save_record("bidpkg", r)
    ev = bidforms.events(s)
    kinds = {(e["kind"], e["date"].isoformat()) for e in ev}
    assert ("Bids due", "2026-11-20") in kinds
    assert ("Pre-bid meeting", "2026-11-05") in kinds
    assert ("Questions due", "2026-11-12") in kinds
    due = next(e for e in ev if e["kind"] == "Bids due" and
               e["date"] == dt.date(2026, 11, 20))
    assert due["time"] == dt.time(14, 0)
    other = ProjectStore(str(tmp / "p4"))
    other.save_record("bidpkg", {"title": "Paving", "due": "2026-12-01"})
    settings.set("pm_recent", [str(tmp / "p4")])
    allev = bidforms.all_events([str(tmp / "p3")])
    assert {e["project"] for e in allev} == {s.name, other.name}
    ics = bidforms.to_ics(allev, str(tmp / "bids.ics"))
    text = open(ics, encoding="utf-8").read()
    assert text.count("BEGIN:VEVENT") == len(allev)
    assert "DTSTART:20261120T140000" in text and "BEGIN:VALARM" in text


def test_bid_calendar_page(env, qapp_pm):
    tmp, H = env
    from app.pm import center
    s = ProjectStore(str(tmp / "cal"))
    s.save_record("bidpkg", {"title": "Roofing",
                             "due": (dt.date.today() +
                                     dt.timedelta(days=3)).isoformat()})
    w = center.ProjectCenter(s)
    page = w.show_tool("bidcal")
    assert len(page.events) == 1 and "1 bid date" in page.note.text()
    assert page.table.rowCount() >= 1
    lst = w.show_tool("bidpkg")
    dlg_picks = [{"csi": "07 50 00", "trade": "Roofing", "form":
                  "General - lump sum", "due": "2026-12-01"}]
    assert len(lst.packages_from_trades(dlg_picks)) == 1
    p = page.export_ics(str(tmp / "x.ics"))
    assert os.path.exists(p)
    w.close()


from test_pm import qapp_pm                                  # noqa: E402,F401


def _contacts_xlsx(path):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "IMPORT"
    ws.append(["Division", "COMPANY NAME", "Company Address", "Company City",
               "Company State", "Company Zip", "CONTACT", "PHONE NUMBER",
               "E-MAIL"])
    ws.append([26, "Volt Electric", "1 Main", "Florence", "South Carolina",
               29501, "Vic Volt", "(843)555-0101", "bids@volt.example"])
    ws.append([None, "Spark Co", "", "Charlotte", "North Carolina", "00000",
               "Spark Co", "(704)555-0102", "est@spark.example"])
    ws.append([9, "Brush Painting", "", "Columbia", "SC", 29201, "Bo",
               "", "bo@brush.example"])
    t = wb.create_sheet("2024")
    t.append(["Example CONTACT LIST"])
    t.append([])
    t.append(["Division", "Type", "TRADE", "COMPANY NAME", "CONTACT"])
    t.append([26, "Sub", "Electric", "Spark Co", "Sam"])
    wb.save(path)
    return str(path)


def test_company_directory_private(env, tmp_path):
    tmp, H = env
    from app import settings, subdir
    rep = subdir.import_xlsx(_contacts_xlsx(tmp_path / "contacts.xlsx"))
    assert rep["sheet"] == "IMPORT" and rep["added"] == 3
    # kept in the user's own data folder, not the program folder
    assert os.path.dirname(subdir.path()) == settings.DIR
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert not subdir.path().startswith(root)
    cs = subdir.load()
    spark = next(c for c in cs if c["company"] == "Spark Co")
    assert spark["division"] == "26" and spark["trade"] == "Electric"
    assert spark["state"] == "NC" and spark["zip"] == "" and \
        spark["contact"] == ""
    assert subdir.import_xlsx(str(tmp_path / "contacts.xlsx"))["added"] == 0
    s = ProjectStore(str(tmp / "p5"))
    pkg = s.save_record("bidpkg", {"title": "Electrical",
                                   "trades": "26 00 00 Electrical"})
    ctx = actions.Ctx(s)
    ctx.ask = lambda title, opts: opts[0]
    pkg = actions.run(ctx, "bidpkg", pkg,
                      "Add Bidders from Company Directory")
    assert sorted(b["company"] for b in pkg["bidders"]) == ["Spark Co",
                                                            "Volt Electric"]
    assert [c["company"] for c in subdir.search(state="SC", division="9")] \
        == ["Brush Painting"]


def test_company_directory_window(env, qapp_pm, tmp_path):
    from app import subdir
    from app.subdir_ui import DirectoryDialog
    subdir.import_xlsx(_contacts_xlsx(tmp_path / "c.xlsx"))
    d = DirectoryDialog()
    assert d.w.table.rowCount() == 3
    d.w.text.setText("volt")
    assert d.w.table.rowCount() == 1
    d.close()
