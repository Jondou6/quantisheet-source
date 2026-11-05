"""Activity look-ahead for the weekly superintendent meeting: the
schedule's work in the next 1-4 weeks, Monday to Friday, day by day, with
the late items first; PDF and Excel; the Schedule page button."""
import datetime as dt
import os

import fitz

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.pm import actions, activity_lookahead as la           # noqa: E402
from test_pm import qapp_pm                                   # noqa: E402,F401
from test_schedule import _store                              # noqa: E402

D = dt.date
WED = D(2026, 11, 4)                  # the meeting day in these tests


def names(rows):
    return [r["name"] for r in rows]


def test_window_is_monday_to_friday():
    assert la.window(2, WED) == (D(2026, 11, 2), D(2026, 11, 13))
    assert la.window(1, D(2026, 11, 2)) == (D(2026, 11, 2), D(2026, 11, 6))
    # from Saturday on it's next week's meeting
    assert la.window(2, D(2026, 11, 7)) == (D(2026, 11, 9), D(2026, 11, 20))
    assert la.window(3, WED)[1] == D(2026, 11, 20)


def test_rows_for_the_meeting(tmp_path, monkeypatch):
    s = _store(tmp_path, monkeypatch)
    rs = la.rows(s, 2, WED)
    by = {r["name"]: r for r in rs}
    # Mobilize (Nov 2-3) should be done by Wednesday: first, flagged
    assert rs[0]["name"] == "Mobilize" and rs[0]["late"]
    assert rs[0]["flag"] == "Past finish - update status"
    assert set(names(rs)) == {"Mobilize", "Excavate", "Survey", "Footings",
                              "Rebar"}             # Slab is after Nov 13
    assert by["Excavate"]["period"] == "Starts & finishes"
    assert by["Footings"]["period"] == "Starts"       # runs to Nov 17
    assert by["Survey"]["days"] == [D(2026, 11, 4), D(2026, 11, 5)]
    assert by["Footings"]["days"] == [D(2026, 11, 12), D(2026, 11, 13)]
    assert by["Footings"]["critical"] and by["Footings"]["responsible"] \
        == "ABC"
    assert not by["Survey"]["critical"] and by["Survey"]["float"] > 0
    # finished work drops off
    sv = s.find("activity", name="Survey")[0]
    sv["status"], sv["percent"] = "Complete", 100
    s.save_record("activity", sv)
    assert "Survey" not in names(la.rows(s, 2, WED))
    # a week later: the foundations milestone and the slab
    nxt = names(la.rows(s, 2, D(2026, 11, 16)))
    assert "Foundations done" in nxt and "Slab" in nxt


def test_behind_baseline_is_flagged(tmp_path, monkeypatch):
    s = _store(tmp_path, monkeypatch)
    ex = s.find("activity", name="Excavate")[0]
    ex["baseline_start"], ex["baseline_finish"] = "2026-11-02", "2026-11-06"
    s.save_record("activity", ex)
    by = {r["name"]: r for r in la.rows(s, 2, D(2026, 11, 2))}
    assert by["Excavate"]["flag"] == "2 day(s) behind baseline"
    assert by["Excavate"]["late"]


def test_holidays_are_not_workdays(tmp_path, monkeypatch):
    s = _store(tmp_path, monkeypatch)
    start, end = la.window(1, D(2026, 11, 23))
    days = la.workdays(s, start, end)
    assert D(2026, 11, 26) not in days and len(days) == 4


def test_pdf_and_excel(tmp_path, monkeypatch):
    s = _store(tmp_path, monkeypatch)
    p = la.export(s, str(tmp_path / "la.pdf"), 2, WED)
    doc = fitz.open(p)
    t = doc[0].get_text()
    assert doc[0].rect.width > doc[0].rect.height          # landscape
    for word in ("2-Week Look-Ahead", "Excavate", "Notes / constraints",
                 "Week of Nov 2", "Week of Nov 9", "Past finish",
                 "Progress last updated Oct 1", "Page 1 of 1"):
        assert word in t, word
    assert "Slab" not in t
    x = la.export(s, str(tmp_path / "la.xlsx"), 2, WED)
    import openpyxl
    ws = openpyxl.load_workbook(x).active
    head = [c.value for c in ws[3]]
    assert head[:2] == ["No.", "Activity"] and head[-1] == \
        "Notes / constraints"
    assert head[11] == "Mon 11/2" and len(head) == 11 + 10 + 1
    rows = {ws.cell(r, 2).value: r for r in range(4, ws.max_row + 1)}
    sv = rows["Survey"]
    filled = [ws.cell(sv, 12 + i).fill.fgColor.rgb for i in range(10)]
    assert filled[2].endswith("5B8CEE") and filled[3].endswith("5B8CEE")
    assert not filled[0].endswith("5B8CEE")


def test_many_rows_run_onto_more_pages(tmp_path, monkeypatch):
    s = _store(tmp_path, monkeypatch)
    for i in range(40):
        s.save_record("activity", {"name": f"Task {i}", "duration": 3,
                                   "start": "2026-11-03"})
    doc = fitz.open(la.export_pdf(s, str(tmp_path / "big.pdf"), 2, WED))
    assert doc.page_count == 2
    assert "Notes / constraints" in doc[1].get_text()     # header repeats


def test_empty_schedule(tmp_path, monkeypatch):
    from app import settings
    from app.pm.store import ProjectStore
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    s = ProjectStore(str(tmp_path / "empty"))
    assert la.rows(s, 2, WED) == []
    t = fitz.open(la.export_pdf(s, str(tmp_path / "e.pdf"), 2, WED))[0]
    assert "Nothing scheduled" in t.get_text()


def test_schedule_page_button_and_action(qapp_pm, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from app.pm import center
    monkeypatch.setenv("QUANTISHEET_NO_OPEN", "1")
    s = _store(tmp_path, monkeypatch)
    w = center.ProjectCenter(s)
    w.show()
    page = w.show_tool("gantt")
    QApplication.processEvents()
    assert page.la_button.text() == "Look-Ahead…"
    out = page.look_ahead(2, str(tmp_path / "meet.pdf"))
    assert out and fitz.open(out).page_count >= 1
    assert page.look_ahead(3, str(tmp_path / "meet.xlsx"))
    labels = [a[0] for a in actions.ACTIONS["activity"]]
    assert "2-Week Look-Ahead" in labels and "3-Week Lookahead" in labels
    w.close()


def test_work_past_its_planned_finish_is_flagged(tmp_path, monkeypatch):
    """Review 0.12.32 #10: with the status date today and no baseline, an
    activity planned to finish Oct 5 but not complete comes first, flagged
    - even though progress moved its dates forward."""
    from app import settings
    from app.pm.store import ProjectStore
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    s = ProjectStore(str(tmp_path / "late"))
    today = D(2026, 10, 21)
    s.set_setting("data_date", today.isoformat())
    s.save_record("activity", {"name": "Set trusses", "duration": 6,
                               "start": "2026-09-28"})        # to Oct 5
    s.save_record("activity", {"name": "Hang drywall", "duration": 5,
                               "start": "2026-10-22"})
    rs = la.rows(s, 2, today)
    assert rs[0]["name"] == "Set trusses" and rs[0]["late"]
    assert rs[0]["flag"] == "Planned to finish Oct 5 - not complete"
    assert not next(r for r in rs if r["name"] == "Hang drywall")["late"]
    # no project name: the Excel title has no "None"
    import openpyxl
    p = la.export_xlsx(s, str(tmp_path / "x.xlsx"), 2, today)
    title = openpyxl.load_workbook(p).active["A1"].value
    assert "None" not in title and title.endswith("2-Week Look-Ahead")
