"""Build Schedule From Plans - contract time read from the specs (with
pages and conflicts), scope, the draft schedule, the fit check."""
import datetime as dt
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QUANTISHEET_NO_OPEN"] = "1"

import fitz                                                   # noqa: E402
import pytest                                                 # noqa: E402

from app.pm import autoschedule as au, schedule               # noqa: E402
from app.pm.store import ProjectStore                         # noqa: E402
from test_gui import qapp                                     # noqa: E402,F401


def test_contract_time_found_with_pages():
    pages = [
        (4, "Time of Completion: The time of completion is 270 calendar "
            "days, and availability of all items must be confirmed."),
        (22, "if the Surety does not commence performance thereof within "
             "five (5) days from the date of the mailing to such Surety of "
             "notice of termination, the Owner may take over the work."),
        (28, "shall fully complete all work there under within the "
             "following number of consecutive calendar days from and "
             "including that date: 270 Consecutive Calendar Days The "
             "Bidder declares that he understands"),
        (30, "the sum of Five Hundred and 00/100 Dollars ($500.00) as "
             "Liquidated Damages for each consecutive calendar day."),
        (462, "Within 90 days of completing TAB, perform additional TAB."),
        (500, "Warranty Period: Two years from date of Substantial "
              "Completion.")]
    ct = au.contract_time(pages)
    assert ct["final"] == {"days": 270, "basis": "calendar",
                           "pages": [4, 28]}
    assert ct["substantial"] is None and not ct["conflicts"]
    assert ct["ld_per_day"] == 500.0 and ct["ld_pages"] == [30]
    d = au.contract_dates(ct, dt.date(2026, 11, 2))
    assert d["final"] == d["substantial"] == dt.date(2027, 7, 29)


def test_substantial_final_dates_and_conflicts():
    ct = au.contract_time([(1, "Substantial Completion shall be achieved "
                               "within 240 calendar days after the date of "
                               "the Notice to Proceed. Final Completion "
                               "shall be achieved within 30 days after "
                               "Substantial Completion.")])
    assert ct["substantial"]["days"] == 240 and \
        ct["final_after_substantial"] == 30
    d = au.contract_dates(ct, dt.date(2026, 11, 2))
    assert d["final"] - d["substantial"] == dt.timedelta(days=30)
    ct = au.contract_time([(3, "The Work shall be substantially complete on "
                               "or before June 30, 2027 and fully complete "
                               "within 180 working days of the Notice to "
                               "Proceed.")])
    assert ct["dates"] == {"substantial": "2027-06-30"}
    assert ct["final"] == {"days": 180, "basis": "working", "pages": [3]}
    ct = au.contract_time([(2, "Contract Time: 300 calendar days to Final "
                               "Completion."),
                           (40, "Complete the Work within 330 calendar "
                                "days.")])
    assert ct["conflicts"] and "300" in ct["conflicts"][0]


def test_plan_skips_scope_and_keeps_links():
    sc = au.scope([{"number": "A-101", "title": "FLOOR PLAN"}],
                  area_sf=2000)
    acts = {a["key"]: a for a in au.plan(sc)}
    assert "utilities" not in acts and "grading" not in acts
    # footings still waits for layout (grading was left out)
    assert ("layout", "FS", 0) in acts["footings"]["preds"]
    assert acts["sc"]["duration"] == 0 and acts["ntp"]["duration"] == 0
    sc2 = au.scope([{"number": "C-301", "title": "UTILITY PLAN"},
                    {"number": "A-101", "title": "FLOOR PLAN"}],
                   area_sf=2000, takeoff=[{"type": "length", "group":
                                           "8 in sewer", "value": 2400}])
    a2 = {a["key"]: a for a in au.plan(sc2)}
    assert a2["utilities"]["duration"] == 30            # 2400 LF / 80
    # the utilities wait on their layout, which starts with the grading
    # (a real lead-in in place of the old SS+3 lag - DCMA point 3)
    assert a2["utilities"]["preds"] == [("util_layout", "FS", 0)]
    assert a2["util_layout"]["preds"] == [("grading", "SS", 0)]
    assert a2["util_layout"]["duration"] == 3


def test_build_fit_and_holidays(tmp_path):
    s = ProjectStore(str(tmp_path / "p"))
    sc = au.scope([{"number": n, "title": t} for n, t in
                   [("C-201", "GRADING AND DRAINAGE PLAN"),
                    ("A-101", "FLOOR PLAN"), ("M-101", "HVAC PLAN"),
                    ("P-101", "PLUMBING PLAN"), ("E-101", "POWER PLAN")]],
                  area_sf=3400)
    ct = au.contract_time([(4, "The time of completion is 270 calendar "
                               "days.")])
    ntp = dt.date(2026, 11, 2)
    res = au.build(s, sc, ntp, ct)
    assert res["activities"] > 30
    assert "2026-12-25" in s.setting("holidays")
    f = res["fit"]
    assert f["required_substantial"] == dt.date(2027, 7, 29)
    assert f["predicted_substantial"] < f["required_substantial"]
    cpm = schedule.compute(s, au.ntp_or_today(s))
    assert not cpm["problems"]
    names = [a["name"] for a, _l, _s in schedule.outline(s.list("activity"))]
    assert names[0] == "Preconstruction" and "Final Completion" in names
    with pytest.raises(ValueError):
        au.build(s, sc, ntp, ct)                     # already has one
    # squeeze it to a much earlier date
    target = f["predicted_substantial"] - dt.timedelta(days=40)
    got = au.fit(s, target, ntp)
    assert got <= target
    assert len(au.summary_text(ct, sc, res)) >= 4


def test_dialog_reads_spec_and_builds(qapp, tmp_path, monkeypatch):
    from app import settings
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {})
    from app.pm import scheduler as sch
    spec = fitz.open()
    pg = spec.new_page()
    pg.insert_text((72, 72), "SECTION 00 41 00 - BID FORM", fontsize=10)
    pg.insert_text((72, 100), "The Contractor shall fully complete all "
                   "Work within 200 calendar days.", fontsize=9)
    for div, title in (("03 30 00", "CAST-IN-PLACE CONCRETE"),
                       ("09 91 00", "PAINTING"), ("22 10 00", "PLUMBING"),
                       ("26 05 00", "ELECTRICAL")):
        p = spec.new_page()
        p.insert_text((72, 72), f"SECTION {div} - {title}", fontsize=10)
    sp = str(tmp_path / "spec.pdf")
    spec.save(sp)
    st = sch.create_schedule("Clinic", folder=str(tmp_path / "job"))
    w = sch.Scheduler(st)
    w._quiet = True
    dlg = w.build_from_plans(spec=sp, show=False)
    dlg.ntp.setText("11/02/26")
    info = dlg.read()
    assert info["ct"]["final"]["days"] == 200
    assert {"22", "26"} <= set(info["divisions"])
    assert dlg.days.text() == "200"
    dlg.area.setText("4000")
    res = dlg.build()
    assert res and res["activities"] > 20
    assert any(a["name"] == "Substantial Completion" for a in w.order)
    assert res["fit"]["required_substantial"] == dt.date(2027, 5, 20)
    assert w.undo() and not st.list("activity")        # undo the build
    w.close()


def test_review13_final_completion_read_and_on_its_milestone(tmp_path):
    for text in ("Substantial Completion within 180 calendar days after the "
                 "Notice to Proceed and Final Completion within 210 "
                 "calendar days after the Notice to Proceed.",
                 "The Work will be substantially completed within 180 days "
                 "after the date when the Contract Times commence to run, "
                 "and completed and ready for final payment within 210 days "
                 "after the date when the Contract Times commence to run."):
        ct = au.contract_time([(7, text)])
        assert ct["substantial"] == {"days": 180, "basis": "calendar",
                                     "pages": [7]}, text
        assert ct["final"] == {"days": 210, "basis": "calendar",
                               "pages": [7]}, text
    ntp = dt.date(2026, 11, 2)
    d = au.contract_dates(ct, ntp)
    assert d["final"] - d["substantial"] == dt.timedelta(days=30)
    s = ProjectStore(str(tmp_path / "p"))
    sc = au.scope([{"number": "A-101", "title": "FLOOR PLAN"}],
                  area_sf=3000)
    res = au.build(s, sc, ntp, ct)
    fc = s.find("activity", name="Final Completion")[0]
    assert fc["contract_date"] == d["final"].isoformat()
    assert "CONTRACT: Final Completion 210 calendar days" in fc["notes"]
    assert res["fit"]["required_final"] == d["final"]
    assert any(ln.startswith("Contract Final Completion")
               for ln in au.summary_text(ct, sc, res))


def test_fit_keeps_notes_and_lead_times(tmp_path):
    """Fit to Contract keeps each row's Notes (BASIS, SOURCE, what the PM
    typed) and adds one FIT line; procurement / lead-time rows keep their
    durations and say so (review finding 11)."""
    s = ProjectStore(str(tmp_path / "p"))
    sc = au.scope([], area_sf=12000, project_type="pump_or_lift_station")
    ntp = dt.date(2026, 11, 2)
    res = au.build(s, sc, ntp, {"substantial": {
        "days": 300, "basis": "calendar", "pages": [3]}})
    acts = s.list("activity")
    parents = {a.get("parent") for a in acts}
    leaf = [a for a in acts if a["_id"] not in parents and
            schedule._num(a.get("duration")) > 1]
    leads = [a for a in leaf if au.is_lead_row(a)]
    work = [a for a in leaf if not au.is_lead_row(a)]
    names = {a["name"] for a in leads}
    assert any(n.startswith("Procure pumps") for n in names)
    assert "Submittal review & approval" in names
    assert "Pump control panel - fabricate" in names
    assert not any(n.startswith(("Excavat", "Install", "Start-up"))
                   for n in names)
    w = next(a for a in work if "SOURCE:" in (a.get("notes") or ""))
    w["notes"] += "\nPM: crane is booked for this week."
    s.save_record("activity", w)
    before = {a["_id"]: (a["duration"], a.get("notes") or "")
              for a in leaf}
    target = res["fit"]["predicted_substantial"] - dt.timedelta(days=20)
    au.fit(s, target, ntp)
    au.fit(s, target - dt.timedelta(days=5), ntp)     # twice: still one line
    for a in leads:
        now = s.get("activity", a["_id"])
        assert now["duration"] == before[a["_id"]][0]
        assert now["notes"].startswith(before[a["_id"]][1].rstrip())
        assert now["notes"].count("FIT:") == 1
        assert "lead time not compressed" in now["notes"]
    cut = 0
    for a in work:
        now = s.get("activity", a["_id"])
        dur, notes = before[a["_id"]]
        if now["duration"] < dur:
            cut += 1
            assert now["notes"].count("FIT:") == 1
            assert f"FIT: cut from {dur} d to {now['duration']} d" in \
                now["notes"]
        for line in notes.splitlines():               # nothing lost
            assert line in now["notes"].splitlines()
    assert cut
    w = s.get("activity", w["_id"])
    assert "PM: crane is booked for this week." in w["notes"]
    assert "SOURCE:" in w["notes"] and w["notes"].startswith("BASIS:")
    # the old whole-note form is replaced, not kept beside the new one
    assert au._fit_note("BASIS: x - cut to 3 d by Fit to Contract.\nPM",
                        "FIT: new") == "PM\nFIT: new"


def test_fit_cuts_only_the_driving_path_and_names_the_lead_row(tmp_path):
    """Review 0.12.38 #2 (made-up job): a 30 d lead-time row beside 20 d +
    10 d of work. The work beside the lead row isn't cut once the lead
    row drives Substantial Completion; the message names the lead row."""
    s = ProjectStore(str(tmp_path / "p"))
    ntp = dt.date.today() + dt.timedelta(days=14)
    s.set_setting("project_start", ntp.isoformat())
    add = lambda **r: s.save_record("activity", r)       # noqa: E731
    add(name="Notice to Proceed", duration=0)
    add(name="Fabricate & deliver widgets - lead time (6 wk)", duration=30,
        area="Procurement", preds=[{"id": "Notice to Proceed"}])
    add(name="Framing", duration=20, preds=[{"id": "Notice to Proceed"}])
    add(name="Drywall", duration=10, preds=[{"id": "Framing"}])
    add(name="Substantial Completion", duration=0, preds=[
        {"id": "Fabricate & deliver widgets - lead time (6 wk)"},
        {"id": "Drywall"}])
    cpm = schedule.compute(s, au.ntp_or_today(s))
    sc_row = next(r for r in cpm["rows"]
                  if r["name"] == "Substantial Completion")
    target = cpm["cal"].date(cpm["cal"].index(sc_row["ef"]) - 5)
    res = au.fit_result(s, target, ntp)
    by = {a["name"]: a for a in s.list("activity")}
    assert by["Framing"]["duration"] == 20
    assert by["Drywall"]["duration"] == 10
    assert by["Fabricate & deliver widgets - lead time (6 wk)"][
        "duration"] == 30
    assert res["lead_row"] == "Fabricate & deliver widgets - lead time (6 wk)"
    assert res["message"] == ("Lead time on Fabricate & deliver widgets - "
                              "lead time (6 wk) drives the finish - Fit to "
                              "Contract can't reach the target without "
                              "changing it.")
    assert res["finish"] == sc_row["ef"] > target
    assert au.fit(s, target, ntp) == sc_row["ef"]
    # work that drives is cut - and only it: a 40 d chain beside the lead
    fr = by["Framing"]
    fr["duration"] = 30
    s.save_record("activity", fr)
    add(name="Site fence", duration=3, preds=[{"id": "Notice to Proceed"}])
    res = au.fit_result(s, target, ntp)
    by = {a["name"]: a for a in s.list("activity")}
    assert by["Site fence"]["duration"] == 3
    assert by["Framing"]["duration"] + by["Drywall"]["duration"] < 40
    assert "FIT: cut from 30 d" in by["Framing"]["notes"]
    assert res["lead_row"] and "Lead time on" in res["message"]
