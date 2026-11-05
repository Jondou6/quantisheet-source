"""Scheduler: build a schedule in a grid + Gantt chart, no PDF needed -
typed activities, durations and predecessors, indent into summaries,
links by dragging, undo, project start, PDF."""
import datetime as dt
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QUANTISHEET_NO_OPEN"] = "1"

import pytest                                                 # noqa: E402

from app.pm import schedule, scheduler as sch                 # noqa: E402
from app.pm.store import ProjectStore                         # noqa: E402
from test_gui import win, qapp                                # noqa: E402,F401


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    from app import settings
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {})
    return tmp_path


def test_parsing():
    assert sch.parse_duration("5") == 5 and sch.parse_duration("5d") == 5
    assert sch.parse_duration("2w") == 10 and sch.parse_duration("0") == 0
    assert sch.parse_duration("1 month") == 20
    assert sch.parse_duration("soon") is None
    assert sch.parse_date("11/02/26") == dt.date(2026, 11, 2)
    assert sch.parse_date("2026-11-02") == dt.date(2026, 11, 2)
    rows = [{"_id": "a", "_no": "A0001", "name": "One"},
            {"_id": "b", "_no": "A0002", "name": "Two"},
            {"_id": "c", "_no": "A0003", "name": "Three"}]
    lines, bad = sch.parse_preds("1, 2SS+2, 9, x", rows)
    assert lines == [{"id": "A0001", "type": "FS", "lag": 0},
                     {"id": "A0002", "type": "SS", "lag": 2}]
    assert bad == ["9", "x"]
    assert sch.preds_text({"preds": lines}, rows) == "1, 2SS+2"


def test_engine_summaries_and_project_start(tmp_path):
    s = ProjectStore(str(tmp_path / "p"))
    s.set_setting("project_start", "2026-11-02")          # a Monday
    ph = s.save_record("activity", {"name": "Site work", "seq": 1})
    a = s.save_record("activity", {"name": "Clear", "duration": 5,
                                   "parent": ph["_id"], "seq": 1})
    b = s.save_record("activity", {"name": "Grade", "duration": 10,
                                   "parent": ph["_id"], "seq": 2,
                                   "preds": [{"id": a["_no"]}]})
    s.save_record("activity", {"name": "Bad link", "duration": 1, "seq": 3,
                               "preds": [{"id": ph["_no"]}]})
    cpm = schedule.compute(s)
    by = {r["name"]: r for r in cpm["rows"]}
    assert by["Clear"]["es"] == dt.date(2026, 11, 2)
    assert by["Grade"]["es"] == dt.date(2026, 11, 9)
    summ = by["Site work"]
    assert summ["summary"] and summ["es"] == dt.date(2026, 11, 2) and \
        summ["ef"] == by["Grade"]["ef"] and summ["dur"] == 15
    assert ph["_id"] not in cpm["critical"]
    assert any("summary" in p for p in cpm["problems"])
    ol = [(x["name"], lvl) for x, lvl, _s in schedule.outline(
        s.list("activity"))]
    assert ol == [("Site work", 0), ("Clear", 1), ("Grade", 1),
                  ("Bad link", 0)]
    path = schedule.gantt_pdf(s, str(tmp_path / "g.pdf"))
    assert os.path.getsize(path) > 1000


def test_build_a_schedule_in_the_grid(qapp, cfg):
    st = sch.create_schedule("Shelter Cove Site", folder=str(cfg / "job"),
                             start=dt.date(2026, 11, 2))
    # status date pinned to the start: unstarted work can't be scheduled
    # before the status date, which is today's date when not set - so the
    # dates below only held on Nov 2 (failed Nov 3, nothing else changed)
    st.set_setting("data_date", "2026-11-02")
    assert ProjectStore.exists(str(cfg / "job"))
    w = sch.Scheduler(st)
    t = w.table
    # type three activities in the blank row, one after another
    for name in ("Site work", "Clear and grub", "Mass grading"):
        t.item(t.rowCount() - 1, sch.C_NAME).setText(name)
    assert [a["name"] for a in w.order] == ["Site work", "Clear and grub",
                                            "Mass grading"]
    clear, grade = w.order[1], w.order[2]
    # durations and a predecessor typed as text
    t.item(1, sch.C_DUR).setText("2w")
    t.item(2, sch.C_DUR).setText("15")
    t.item(2, sch.C_PRED).setText("2")
    assert st.get("activity", clear["_id"])["duration"] == 10
    assert st.get("activity", grade["_id"])["preds"][0]["id"] == clear["_no"]
    # indent both under "Site work": it becomes a summary over them
    t.selectRow(1)
    from PySide6.QtCore import QItemSelectionModel as M
    t.selectionModel().select(t.model().index(2, 0), M.Select | M.Rows)
    assert w.indent() == 2
    by = {r["name"]: r for r in w.cpm["rows"]}
    assert by["Site work"]["summary"]
    assert by["Mass grading"]["es"] == dt.date(2026, 11, 16)
    assert by["Site work"]["ef"] == by["Mass grading"]["ef"]
    assert w.levels[grade["_id"]] == 1
    assert t.item(0, sch.C_DUR).text() == ""         # summaries: computed
    # undo puts them back at the top level, redo indents again
    assert w.undo() and not st.get("activity", grade["_id"]).get("parent")
    assert w.redo() and st.get("activity", grade["_id"]).get("parent")
    # a milestone linked by "dragging" bar to bar
    t.item(t.rowCount() - 1, sch.C_NAME).setText("Grading done")
    done = w.order[-1]
    t.item(w.order.index(done), sch.C_DUR).setText("0")
    assert w.link(grade["_id"], done["_id"])
    by = {r["name"]: r for r in w.cpm["rows"]}
    assert by["Grading done"]["milestone"] and \
        by["Grading done"]["es"] == by["Mass grading"]["ef"]
    # bad text is refused with a message, nothing changes
    rec = st.get("activity", done["_id"])
    assert "duration" in w.apply_edit(rec, sch.C_DUR, "soon")
    assert "row numbers" in w.apply_edit(rec, sch.C_PRED, "99")
    # finish typed: the duration follows
    rec = st.get("activity", clear["_id"])
    w.apply_edit(rec, sch.C_FIN, "11/20/26")
    assert st.get("activity", clear["_id"])["duration"] == 15
    # % done sets the status
    w.apply_edit(st.get("activity", clear["_id"]), sch.C_PCT, "100")
    assert st.get("activity", clear["_id"])["status"] == "Complete"
    # PDF in outline order
    p = w.pdf(path=str(cfg / "sched.pdf"))
    assert os.path.getsize(p) > 1000
    w.close()


def test_insert_move_delete_and_project_start(qapp, cfg):
    st = sch.create_schedule("Job", folder=str(cfg / "j2"))
    w = sch.Scheduler(st)
    for n in ("A", "B", "C"):
        w.add_activity(n, 3)
    w.refresh()
    w.table.selectRow(1)
    w.insert_row("A2")
    assert [a["name"] for a in w.order] == ["A", "A2", "B", "C"]
    w.table.selectRow(3)
    assert w.move_row(-1)
    assert [a["name"] for a in w.order] == ["A", "A2", "C", "B"]
    w.table.selectRow(0)
    assert w.delete_rows(ask=False) == 1
    assert [a["name"] for a in w.order] == ["A2", "C", "B"]
    w.project_start(dt.date(2026, 12, 7))
    assert all(r["es"] >= dt.date(2026, 12, 7) for r in w.cpm["rows"])
    w.close()


def test_scheduler_from_the_main_window(win, cfg):
    a = win.command("Scheduler (Gantt)")
    assert a is not None and a.isEnabled()
    st = sch.create_schedule("From window", folder=str(cfg / "j3"))
    w = win.scheduler(store=st)
    assert isinstance(w, sch.Scheduler) and w.store is st
    w.close()


def test_part_done_activity_planned_ahead_keeps_its_length(tmp_path):
    s = ProjectStore(str(tmp_path / "p"))
    s.set_setting("project_start", "2026-11-18")
    s.save_record("activity", {"name": "Sewer", "duration": 12,
                               "percent": 40, "status": "In Progress",
                               "actual_start": "2026-11-18"})
    r = schedule.compute(s, dt.date(2026, 10, 16))["rows"][0]
    assert (r["es"], r["ef"]) == (dt.date(2026, 11, 18), dt.date(2026, 12, 3))
    # status date 5 workdays in: the 60% left runs on from it
    r = schedule.compute(s, dt.date(2026, 11, 25))["rows"][0]
    assert r["ef"] == dt.date(2026, 12, 4)
