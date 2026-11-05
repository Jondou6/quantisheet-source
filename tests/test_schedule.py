"""Project schedule: critical path, Gantt/lookahead PDFs, MS Project and
P6 exchange, and the Gantt page."""
import datetime as dt
import os

import fitz

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import settings                                     # noqa: E402
from app.pm import actions, report, schedule                 # noqa: E402
from app.pm.store import ProjectStore                        # noqa: E402
from test_pm import qapp_pm                                  # noqa: E402,F401


def _store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Pat Morgan"})
    s = ProjectStore(str(tmp_path / "job"))
    s.set_setting("holidays", ["2026-11-26"])
    s.set_setting("data_date", "2026-10-01")       # status date
    add = lambda **r: s.save_record("activity", r)       # noqa: E731
    add(name="Mobilize", duration=2, start="2026-11-02")
    add(name="Excavate", duration=5, preds=[{"id": "A0001"}])
    add(name="Footings", duration=4,
        preds=[{"id": "2", "type": "FS", "lag": 1}], responsible="ABC")
    add(name="Survey", duration=2, preds=[{"id": "Mobilize"}])
    add(name="Rebar", duration=3, preds=[{"id": "A0003", "type": "SS",
                                           "lag": 1}])
    add(name="Foundations done", duration=0,
        preds=[{"id": "A0003"}, {"id": "A0004"}])
    add(name="Slab", duration=4, preds=[{"id": "A0006"}])   # over Thanksgiving
    return s


def _row(cpm, name):
    return next(r for r in cpm["rows"] if r["name"] == name)


def test_critical_path(tmp_path, monkeypatch):
    s = _store(tmp_path, monkeypatch)
    cpm = schedule.compute(s)
    assert not cpm["problems"]
    d = dt.date.fromisoformat
    ex = _row(cpm, "Excavate")
    assert (ex["es"], ex["ef"]) == (d("2026-11-04"), d("2026-11-10"))
    ft = _row(cpm, "Footings")                    # lag 1 day
    assert (ft["es"], ft["ef"]) == (d("2026-11-12"), d("2026-11-17"))
    assert _row(cpm, "Rebar")["es"] == d("2026-11-13")       # SS + 1
    ms = _row(cpm, "Foundations done")
    assert ms["milestone"] and ms["es"] == d("2026-11-17")
    slab = _row(cpm, "Slab")                     # skips the holiday
    assert (slab["es"], slab["ef"]) == (d("2026-11-18"), d("2026-11-24")) \
        or slab["ef"] == d("2026-11-23")
    assert _row(cpm, "Survey")["float"] > 0
    assert not _row(cpm, "Survey")["critical"]
    for n in ("Mobilize", "Excavate", "Footings", "Slab"):
        assert _row(cpm, n)["critical"]
    # list columns
    rec = s.find("activity", name="Footings")[0]
    assert report.cell(s, "activity", rec, "_finish") == "2026-11-17"
    assert report.cell(s, "activity", rec, "_float") == "Critical"
    # a loop is reported, not a crash
    m = s.find("activity", name="Mobilize")[0]
    m["preds"] = [{"id": "A0007"}]
    s.save_record("activity", m)
    cpm = schedule.compute(s)
    assert cpm["problems"] and "loop" in cpm["problems"][0]


def test_holiday_and_actuals(tmp_path, monkeypatch):
    s = _store(tmp_path, monkeypatch)
    slab = _row(schedule.compute(s), "Slab")
    # Nov 18,19,20,23 are 4 workdays: no holiday inside yet
    assert slab["ef"] == dt.date(2026, 11, 23)
    s.set_setting("holidays", ["2026-11-19"])
    slab = _row(schedule.compute(s), "Slab")
    assert slab["ef"] == dt.date(2026, 11, 24)
    # actual dates pin an activity; status follows
    ex = s.find("activity", name="Excavate")[0]
    ex["actual_start"] = "2026-11-09"
    s.save_record("activity", ex)
    assert schedule.update_dates(s) == 1
    assert s.get("activity", ex["_id"])["status"] == "In Progress"
    assert _row(schedule.compute(s), "Excavate")["es"] == dt.date(2026, 11, 9)
    # in progress at a later status date: what's left runs from it
    ex = s.get("activity", ex["_id"])
    ex["percent"] = 40                              # 3 of 5 days left
    s.save_record("activity", ex)
    row = _row(schedule.compute(s, dt.date(2026, 11, 16)), "Excavate")
    assert row["ef"] == dt.date(2026, 11, 18)
    assert _row(schedule.compute(s, dt.date(2026, 11, 16)),
                "Survey")["es"] >= dt.date(2026, 11, 16)


def test_baseline_pdfs_and_exchange(tmp_path, monkeypatch):
    s = _store(tmp_path, monkeypatch)
    assert schedule.set_baseline(s) == 7
    ft = s.find("activity", name="Footings")[0]
    ft["duration"] = 6
    s.save_record("activity", ft)
    cpm = schedule.compute(s)
    assert schedule.variance(_row(cpm, "Slab")) == 2
    p = schedule.gantt_pdf(s, str(tmp_path / "g.pdf"))
    d = fitz.open(p)
    text = d[0].get_text()
    assert "Footings" in text and "Foundations done" in text
    rows, a, b = schedule.lookahead(s, 3, dt.date(2026, 11, 16))
    assert {r["name"] for r in rows} >= {"Footings", "Rebar"}
    assert "Mobilize" not in {r["name"] for r in rows}
    schedule.lookahead_pdf(s, str(tmp_path / "la.pdf"),
                           start=dt.date(2026, 11, 16))
    assert "Lookahead" in fitz.open(str(tmp_path / "la.pdf"))[0].get_text()
    # MS Project round trip
    xml = schedule.export_msproject(s, str(tmp_path / "s.xml"))
    s2 = ProjectStore(str(tmp_path / "job2"))
    assert schedule.import_msproject(s2, xml) == 7
    c2 = schedule.compute(s2)
    assert [(r["name"], r["es"], r["ef"]) for r in c2["rows"]
            if r["name"] != "Slab"] == \
        [(r["name"], r["es"], r["ef"]) for r in cpm["rows"]
         if r["name"] != "Slab"]
    assert schedule.import_msproject(s2, xml) == 7      # updates in place
    assert len(s2.list("activity")) == 7
    # every task has its outline level; one calendar, the holidays as its
    # exceptions - and the importer reads them back (review 0.12.35 T14)
    import xml.etree.ElementTree as ET
    ns = "{http://schemas.microsoft.com/project}"
    root = ET.parse(xml).getroot()
    tasks = root.find(ns + "Tasks").findall(ns + "Task")
    assert tasks and all(t.find(ns + "OutlineLevel") is not None
                         for t in tasks)
    cals = root.find(ns + "Calendars").findall(ns + "Calendar")
    assert len(cals) == 1
    assert root.find(ns + "CalendarUID").text == cals[0].find(
        ns + "UID").text
    ex = cals[0].find(ns + "Exceptions").findall(ns + "Exception")
    assert [e.find(ns + "TimePeriod").find(ns + "FromDate").text[:10]
            for e in ex] == ["2026-11-26"]
    assert s2.setting("holidays") == ["2026-11-26"]
    # Primavera P6
    xer = tmp_path / "p6.xer"
    xer.write_text("ERMHDR\t19.12\n%T\tPROJWBS\n%F\twbs_id\twbs_name\n"
                   "%R\t1\tSitework\n%T\tTASK\n%F\ttask_id\ttask_code\t"
                   "task_name\twbs_id\ttarget_drtn_hr_cnt\t"
                   "target_start_date\ttask_type\tphys_complete_pct\n"
                   "%R\t10\tA1000\tClear site\t1\t24\t2026-11-02 08:00\t"
                   "TT_Task\t0\n%R\t11\tA1010\tGrade\t1\t40\t"
                   "2026-11-05 08:00\tTT_Task\t0\n%T\tTASKPRED\n%F\t"
                   "task_pred_id\ttask_id\tpred_task_id\tpred_type\t"
                   "lag_hr_cnt\n%R\t1\t11\t10\tPR_FS\t0\n%E\n",
                   encoding="cp1252")
    s3 = ProjectStore(str(tmp_path / "job3"))
    assert schedule.import_xer(s3, str(xer)) == 2
    c3 = schedule.compute(s3)
    g = _row(c3, "Grade")
    assert g["area"] == "Sitework" and g["es"] == dt.date(2026, 11, 5)


def test_gantt_page_and_actions(qapp_pm, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from app.pm import center
    monkeypatch.setenv("QUANTISHEET_NO_OPEN", "1")
    s = _store(tmp_path, monkeypatch)
    w = center.ProjectCenter(s)
    w.show()
    page = w.show_tool("gantt")
    QApplication.processEvents()
    assert len(page.chart.rows) == 7
    assert "critical" in page.summary.text()
    page.chart.repaint()
    page.crit.setChecked(True)
    assert all(r["critical"] for r in page.chart.rows)
    page.crit.setChecked(False)
    for sc in ("Days", "Months", "Weeks"):
        page.scale.setCurrentText(sc)
        page.chart.repaint()
    # dragging a bar = saving a new start
    ex = next(r for r in page.chart.rows if r["name"] == "Survey")
    page.chart.changed.emit(ex["_id"], {"start": "2026-11-09"})
    assert s.get("activity", ex["_id"])["start"] == "2026-11-09"
    assert _row(schedule.compute(s), "Survey")["es"] == dt.date(2026, 11, 9)
    assert page.pdf(path=str(tmp_path / "x.pdf"))
    assert page.export(path=str(tmp_path / "x.xml"))
    assert page.baseline() == 7
    # activity actions
    rec = s.find("activity", name="Mobilize")[0]
    ctx = actions.Ctx(s, ask=lambda *a: None, notify=lambda *a: None)
    out = actions.run(ctx, "activity", rec, "Started Today")
    assert out["status"] == "In Progress" and out["actual_start"]
    out = actions.run(ctx, "activity", out, "Finished Today")
    assert out["status"] == "Complete" and out["percent"] == 100
    w.show_tool("activity")
    QApplication.processEvents()
    w.close()


def test_cached_ignores_update_log(tmp_path, monkeypatch):
    """The saved update log lives in the settings; it must not make every
    Start/Finish/Float cell re-serialise it or recompute the CPM (review
    finding 4: 900 cells took 17 s with 12 saved updates)."""
    import json
    import time
    from app.pm import schedule_record as SR
    s = _store(tmp_path, monkeypatch)
    prev = "A0007"
    for i in range(150):
        r = s.save_record("activity", {"name": f"Act {i}", "duration": 3,
                                       "preds": [{"id": prev}]})
        prev = r["_no"]
    for k in range(12):
        SR.snapshot(s, "update", f"month {k}")
    assert len(json.dumps(s.setting("schedule_updates"), default=str)) \
        > 100000
    calls = []
    real = schedule.compute
    monkeypatch.setattr(schedule, "compute",
                        lambda *a, **k: calls.append(1) or real(*a, **k))
    sizes = []
    real_dumps = json.dumps

    class _J:
        @staticmethod
        def dumps(o, *a, **k):
            out = real_dumps(o, *a, **k)
            sizes.append(len(out))
            return out
    monkeypatch.setattr(schedule, "json", _J)
    schedule.cached(s)
    assert calls == [1]
    t = time.time()
    for rec in s.list("activity"):
        for c in ("_start", "_finish", "_float"):
            assert schedule.cell(s, rec, c)
    assert calls == [1]                     # not recomputed per cell
    assert max(sizes) < 2000                # the log was never serialised
    assert time.time() - t < 5              # rough guard; was ~10 s
    # another update saved: the dates can't move, so no recompute either
    SR.snapshot(s, "update", "month 13")   # (computes once itself)
    del calls[:]
    schedule.cached(s)
    assert calls == []
    # what the CPM does read still invalidates the cache
    s.set_setting("holidays", ["2026-11-26", "2026-11-27"])
    schedule.cached(s)
    assert len(calls) == 1
    s.set_setting("project_start", "2026-11-09")
    assert schedule.cached(s)["start"] >= dt.date(2026, 11, 9)
    assert len(calls) == 2
    s.set_setting("data_date", "2026-11-20")
    schedule.cached(s)
    assert len(calls) == 3


def test_msproject_xml_element_order(tmp_path, monkeypatch):
    """Project and Task children follow the MSPDI schema's xs:sequence
    (as remembered from mspdi_pj12.xsd - not validated against the file)."""
    import xml.etree.ElementTree as ET
    s = _store(tmp_path, monkeypatch)
    a = s.find("activity", name="Survey")[0]
    a.update(notes="SOURCE: plans", actual_start="2026-11-04",
             percent=50)
    s.save_record("activity", a)
    schedule.set_baseline(s)
    xml = schedule.export_msproject(s, str(tmp_path / "o.xml"))
    ns = "{http://schemas.microsoft.com/project}"
    root = ET.parse(xml).getroot()

    def check(el, seq):
        got = [c.tag[len(ns):] for c in el]
        assert set(got) <= set(seq), set(got) - set(seq)
        idx = [seq.index(g) for g in got]
        assert idx == sorted(idx), got
        return got
    project_seq = [
        "SaveVersion", "UID", "Name", "Title", "Subject", "Category",
        "Company", "Manager", "Author", "CreationDate", "Revision",
        "LastSaved", "ScheduleFromStart", "StartDate", "FinishDate",
        "FYStartDate", "CriticalSlackLimit", "CurrencyDigits",
        "CurrencySymbol", "CurrencyCode", "CurrencySymbolPosition",
        "CalendarUID", "DefaultStartTime", "DefaultFinishTime",
        "MinutesPerDay", "MinutesPerWeek", "DaysPerMonth",
        "DefaultTaskType", "ExtendedAttributes", "Calendars", "Tasks",
        "Resources", "Assignments"]
    got = check(root, project_seq)
    assert got.index("CalendarUID") < got.index("MinutesPerDay")
    task_seq = [
        "UID", "GUID", "ID", "Name", "Active", "Manual", "Type", "IsNull",
        "CreateDate", "Contact", "WBS", "WBSLevel", "OutlineNumber",
        "OutlineLevel", "Priority", "Start", "Finish", "Duration",
        "ManualStart", "ManualFinish", "ManualDuration", "DurationFormat",
        "Work", "Stop", "Resume", "ResumeValid", "EffortDriven",
        "Recurring", "OverAllocated", "Estimated", "Milestone", "Summary",
        "DisplayAsSummary", "Critical", "IsSubproject",
        "PercentComplete", "PercentWorkComplete", "Cost", "ActualStart",
        "ActualFinish", "ActualDuration", "ConstraintType", "CalendarUID",
        "ConstraintDate", "Deadline", "Notes", "PredecessorLink",
        "ExtendedAttribute", "Baseline"]
    tasks = root.find(ns + "Tasks").findall(ns + "Task")
    seen = set()
    for t in tasks:
        seen.update(check(t, task_seq))
        for pl in t.findall(ns + "PredecessorLink"):
            check(pl, ["PredecessorUID", "Type", "CrossProject",
                       "CrossProjectName", "LinkLag", "LagFormat"])
    assert {"Notes", "PredecessorLink", "ActualStart",
            "ConstraintType", "Baseline"} <= seen
    cal = root.find(ns + "Calendars").find(ns + "Calendar")
    check(cal, ["UID", "GUID", "Name", "IsBaseCalendar",
                "IsBaselineCalendar", "BaseCalendarUID", "WeekDays",
                "Exceptions", "WorkWeeks"])
    for ex in cal.find(ns + "Exceptions"):
        check(ex, ["EnteredByOccurrences", "TimePeriod", "Occurrences",
                   "Name", "Type", "PeriodNumber", "DaysOfWeek",
                   "MonthItem", "Month", "MonthDay", "DayWorking",
                   "WorkingTimes"])


def test_msproject_baselines_and_notes_round_trip(tmp_path, monkeypatch):
    """Review 0.12.38 #7: after Set Baseline the export wrote no Baseline
    elements, and the import dropped Notes. Made-up 4-activity job, one
    holiday inside the pour (11/12) so the baseline duration counts
    workdays only."""
    import xml.etree.ElementTree as ET
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Pat Morgan"})
    s = ProjectStore(str(tmp_path / "job"))
    s.set_setting("holidays", ["2026-11-12"])
    s.set_setting("data_date", "2026-10-01")
    add = lambda **r: s.save_record("activity", r)       # noqa: E731
    add(name="Mobilize", duration=2, start="2026-11-02")
    add(name="Dig", duration=5, preds=[{"id": "Mobilize"}])
    add(name="Pour", duration=3, preds=[{"id": "Dig"}])
    add(name="Pad done", duration=0, preds=[{"id": "Pour"}])
    assert schedule.set_baseline(s) == 4
    dig = s.find("activity", name="Dig")[0]
    dig["notes"] = "Made-up note: rock at 4 ft, see RFI 3"
    s.save_record("activity", dig)
    cpm = schedule.compute(s)
    xml = schedule.export_msproject(s, str(tmp_path / "b.xml"))
    ns = "{http://schemas.microsoft.com/project}"
    root = ET.parse(xml).getroot()
    got = {}
    for t in root.find(ns + "Tasks").findall(ns + "Task"):
        bl = t.findall(ns + "Baseline")
        assert len(bl) == 1, t.find(ns + "Name").text
        tags = [c.tag[len(ns):] for c in bl[0]]
        assert tags == ["Number", "Start", "Finish", "Duration",
                        "DurationFormat"]
        kids = [c.tag[len(ns):] for c in t]
        assert kids[-1] == "Baseline"               # after PredecessorLink
        got[t.find(ns + "Name").text] = {
            c.tag[len(ns):]: c.text for c in bl[0]}
    assert set(got) == {"Mobilize", "Dig", "Pour", "Pad done"}
    assert {n: g["Duration"] for n, g in got.items()} == {
        "Mobilize": "PT16H0M0S", "Dig": "PT40H0M0S", "Pour": "PT24H0M0S",
        "Pad done": "PT0H0M0S"}
    pour = _row(cpm, "Pour")
    assert got["Pour"]["Start"] == f"{pour['es']}T08:00:00"
    assert got["Pour"]["Finish"] == f"{pour['ef']}T17:00:00"
    assert all(g["Number"] == "0" for g in got.values())
    # re-import keeps the note and the baselines
    s2 = ProjectStore(str(tmp_path / "job2"))
    assert schedule.import_msproject(s2, xml) == 4
    by = {a["name"]: a for a in s2.list("activity")}
    assert by["Dig"]["notes"] == "Made-up note: rock at 4 ft, see RFI 3"
    assert not by["Pour"].get("notes")
    for a in s.list("activity"):
        b = by[a["name"]]
        assert (b["baseline_start"], b["baseline_finish"]) == \
            (a["baseline_start"], a["baseline_finish"])
    # a second import of a file without the note doesn't wipe it here
    for t in root.find(ns + "Tasks").findall(ns + "Task"):
        for n in t.findall(ns + "Notes"):
            t.remove(n)
    ET.ElementTree(root).write(str(tmp_path / "c.xml"))
    schedule.import_msproject(s2, str(tmp_path / "c.xml"))
    assert s2.find("activity", name="Dig")[0]["notes"].startswith("Made-up")
