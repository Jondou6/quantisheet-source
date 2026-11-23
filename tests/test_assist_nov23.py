"""Ask the Project, Draft Daily Log From Notes, Check Submittal Against
Spec and Project Risk Flags (Nov 23, Jon: features like our competitors',
built ourselves). Made-up project, people and text only."""
import datetime as dt
import os
import sys

import fitz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import askproject as ap, pmassist as pa  # noqa: E402
from app.pm.store import ProjectStore  # noqa: E402

try:
    from test_gui import win, qapp  # noqa: F401,E402
except Exception:                                         # noqa: BLE001
    pass

SPEC = [
    "SECTION 07 54 23 - THERMOPLASTIC POLYOLEFIN (TPO) ROOFING\n"
    "1.6 WARRANTY\nA. Manufacturer's warranty: twenty (20) years for the "
    "roofing system, including membrane and flashings.",
    "SECTION 08 71 00 - DOOR HARDWARE\nPART 1 GENERAL\n1.3 SUBMITTALS\n"
    "A. Product Data: for each type of product.\nB. Shop Drawings: "
    "hardware schedule.\nC. Samples: finish samples.\n1.4 WARRANTY\n"
    "A. Manufacturer's warranty: ten (10) years for closers.\n"
    "PART 2 PRODUCTS\n2.1 MANUFACTURERS\nA. Provide products by one of the "
    "following:\n1. Example Hardware Co.\n2. Sample Locks Inc.\n"
    "B. Comply with BHMA A156.4 and UL 10C.\nEND OF SECTION",
]


def _pdf(path, pages):
    d = fitz.open()
    for t in pages:
        d.new_page().insert_textbox(fitz.Rect(54, 54, 558, 738), t,
                                    fontsize=10)
    d.save(str(path))
    d.close()
    return str(path)


def _store(tmp_path):
    s = ProjectStore(str(tmp_path / "job"))
    s.save_record("rfi", {"subject": "Roof drain location", "status": "Open",
                          "question": "Confirm the roof drain at grid C-4.",
                          "due": "2026-11-10", "sent": "2026-11-03",
                          "cost_impact": "Yes", "to": "Pat Architect"})
    s.save_record("submittal", {"title": "Door hardware", "spec": "08 71 00",
                                "status": "Not Submitted",
                                "submit_by": "2026-11-15",
                                "required_on_site": "2026-11-30",
                                "lead_days": 30, "review_days": 10})
    s.save_record("activity", {"name": "Set roof top units", "duration": 2,
                               "status": "In Progress", "percent": 40,
                               "baseline_finish": "2026-11-12"})
    return s


TODAY = dt.date(2026, 11, 23)


def test_ask_finds_the_passage_and_keeps_citations_honest(tmp_path):
    doc = fitz.open(_pdf(tmp_path / "specs.pdf", SPEC))
    chunks = ap.sources(doc, _store(tmp_path), "specs.pdf")
    hits = ap.search("What is the roofing warranty?", chunks)
    assert hits[0]["where"] == "specs.pdf p. 1"
    hits = ap.search("roof drain grid", chunks)
    assert hits[0]["where"].startswith("RFI")
    res = ap.answer("roofing warranty", chunks,
                    ask=lambda p: "Twenty years [1] and more [9].")
    assert res["ai"] and res["answer"] == "Twenty years [1] and more ."
    both = ap.answer("roofing warranty", chunks, ask=lambda p: "Twenty "
                     "years [1]. Not found in the project documents.")
    assert both["answer"] == "Twenty years [1]."
    off = ap.answer("roofing warranty", chunks, use_ai=False)
    assert off["hits"] and not off["answer"]
    down = ap.answer("roofing warranty", chunks,
                     ask=lambda p: (_ for _ in ()).throw(OSError("no AI")))
    assert down["error"] == "no AI" and down["hits"]
    assert ap.answer("zzzz qqqq", chunks)["answer"].startswith("Nothing")


def test_daily_log_from_notes():
    rec = pa.draft_daily(
        "Example Plumbing 4 men 8 hrs rough-in at level 2\n"
        "Sample Electric - 3 electricians, pulling wire in corridor B\n"
        "Concrete delivered from Example Ready Mix 10:30, 12 CY\n"
        "Rained 2 hrs in the morning, stopped site work\n"
        "Fire inspection passed at 2 PM\nToolbox talk on ladders\n"
        "Owner on site: walkthrough with architect\n"
        "Framed walls in rooms 101-105", "2026-11-23")
    assert [(m["company"], m["workers"], m["hours"]) for m in
            rec["manpower"]] == [("Example Plumbing", 4, 8.0),
                                 ("Sample Electric", 3, 8)]
    assert rec["deliveries"][0]["supplier"] == "Example Ready Mix"
    assert rec["deliveries"][0]["time"] == "10:30"
    assert rec["delays"] == [{"cause": "Weather", "hours": 2.0,
                              "description": "Rained 2 hrs in the morning, "
                                             "stopped site work"}]
    assert rec["inspections_note"] == "Fire inspection passed at 2 PM"
    assert rec["safety"] == "Toolbox talk on ladders"
    assert "Framed walls in rooms 101-105" in rec["work"]
    assert rec["status"] == "Draft"


def test_submittal_check(tmp_path):
    doc = fitz.open(_pdf(tmp_path / "specs.pdf", SPEC))
    text, pages = pa.section_text(doc, "08 71 00")
    assert pages == [1] and "DOOR HARDWARE" in text
    rows = pa.check_submittal(text, "Example Hardware Co. closer product "
                              "data. Certified to BHMA A156.4. Warranty: 10 "
                              "year limited.")
    got = {(r["check"], r["spec"]): r["ok"] for r in rows}
    assert got[("Standard", "BHMA A156.4")] is True
    assert got[("Standard", "UL 10C")] is False
    assert got[("Warranty", "10 years")] is True
    assert got[("Submittal item", "shop drawings")] is False
    mf = next(r for r in rows if r["check"] == "Manufacturer")
    assert mf["ok"] and "Example Hardware Co" in mf["found"]


def test_risk_flags(tmp_path):
    flags = pa.risk_flags(_store(tmp_path), TODAY)
    reasons = [f["reason"] for f in flags]
    assert "answer is 13 day(s) late" in reasons
    assert "has a cost impact but no change event" in reasons
    assert any(r.startswith("not submitted - 8 day(s)") for r in reasons)
    assert any("needed on site in 7 day(s)" in r for r in reasons)
    assert any("past its baseline finish" in r for r in reasons)
    assert flags[0]["level"] == "High"


def test_windows_menus_and_project_center(win, tmp_path):
    w = win
    s = _store(tmp_path)
    for name in ("Ask the Project…", "Draft Daily Log From Notes…",
                 "Check Submittal Against Spec…", "Project Risk Flags…"):
        assert w.command(name) is not None, name
    ai = w.ribbon.page("AI").group("Project")
    have = {b.defaultAction().text() for b in ai.buttons}
    assert {"Ask the Project…", "Draft Daily Log From Notes…",
            "Check Submittal Against Spec…", "Project Risk Flags…"} <= have
    pg = w.ribbon.page("Project Analysis").group("Project Analysis")
    assert "Ask the Project…" in {b.defaultAction().text()
                                  for b in pg.buttons}
    chk = w.ribbon.page("Project").group("Check")
    assert "Project Risk Flags…" in {b.defaultAction().text()
                                     for b in chk.buttons}
    dlg = w.ask_project(store=s, show=False)
    res = dlg.ask("roof drain", ask=lambda p: "At grid C-4 [1].", wait=True)
    assert res["answer"] == "At grid C-4 [1]."
    assert "At grid C-4" in dlg.answer.text()
    dd = w.daily_draft(store=s, show=False)
    dd.notes.setPlainText("Example Plumbing 4 men 8 hrs rough-in")
    dd.draft()
    saved = dd.save()
    assert saved["manpower"][0]["company"] == "Example Plumbing"
    assert any(r["_id"] == saved["_id"] for r in s.list("daily"))
    rf = w.risk_flags(store=s, show=False)
    assert rf.table.rowCount() == len(pa.risk_flags(s))
    sc = w.submittal_check(store=s, show=False)
    sc.pick_spec(_pdf(tmp_path / "specs.pdf", SPEC))
    sc.pick.setCurrentIndex(1)
    assert sc.code.text() == "08 71 00"
    assert sc.run() and "to look at" in sc.status.text()
    for d in (dlg, dd, rf, sc):
        d.close()


def test_project_center_buttons_and_home(qapp, tmp_path):
    from app.pm.center import ProjectCenter
    s = _store(tmp_path)
    pc = ProjectCenter(s)
    try:
        pc.home.refresh()
        assert pc.home.risk and pc.home.risk[0]["level"] == "High"
        dlg = pc.page("daily").draft_from_notes(show=False)
        assert dlg.windowTitle() == "Draft Daily Log From Notes"
        dlg.close()
        sp = pc.page("submittal")
        sp.select(s.list("submittal")[0]["_id"])
        chk = sp.check_against_spec(show=False)
        assert chk.code.text() == "08 71 00"
        chk.close()
    finally:
        pc.close()
