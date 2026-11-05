"""Project Calendar (app/pm/project_calendar.py + calendarui): activities
and milestones from the CPM, inspections, meetings and expected
deliveries on the month / week grid; moving the movable ones; new items
from a dragged range; the page in Project Center. Made-up data only."""
import datetime as dt
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest                                                # noqa: E402

from app.pm import project_calendar as pc, schedule          # noqa: E402
from test_pm import qapp_pm                                  # noqa: E402,F401
from test_schedule import _store                             # noqa: E402


def _job(tmp_path, monkeypatch):
    s = _store(tmp_path, monkeypatch)
    s.save_record("inspection", {"title": "Footing inspection",
                                 "date": "2026-11-12", "status": "Scheduled"})
    s.save_record("meeting", {"title": "OAC #4", "date": "2026-11-10",
                              "time": "9:00", "type": "OAC"})
    s.save_record("expedite", {"item": "Rebar", "expected": "2026-11-09"})
    s.save_record("expedite", {"item": "Anchor bolts",
                               "expected": "2026-11-05",
                               "delivered": "2026-11-04"})
    return s


def test_items_cover_every_kind_in_range(tmp_path, monkeypatch):
    s = _job(tmp_path, monkeypatch)
    its = pc.items(s, "2026-11-01", "2026-11-30")
    kinds = {i["kind"] for i in its}
    assert kinds == {"activity", "milestone", "inspection", "meeting",
                     "delivery"}
    cpm = schedule.compute(s, schedule.data_date(s))
    mob = next(r for r in cpm["rows"] if r["name"] == "Mobilize")
    got = next(i for i in its if i["title"].endswith("Mobilize"))
    assert (got["start"], got["end"]) == (mob["es"].isoformat(),
                                          mob["ef"].isoformat())
    assert got["critical"] and got["title"].startswith("● ")
    assert not got["movable"]
    titles = [i["title"] for i in its]
    assert "9:00 OAC #4" in titles
    assert "Delivery: Rebar" in titles
    assert not any("Anchor bolts" in t for t in titles)     # delivered
    only = pc.items(s, "2026-11-01", "2026-11-30", kinds=["meeting"])
    assert [i["title"] for i in only] == ["9:00 OAC #4"]
    assert pc.items(s, "2027-01-01", "2027-01-31") == []


def test_move_meeting_but_never_an_activity(tmp_path, monkeypatch):
    s = _job(tmp_path, monkeypatch)
    its = pc.items(s, "2026-11-01", "2026-11-30")
    meet = next(i for i in its if i["kind"] == "meeting")
    pc.move(s, meet, 2)
    assert s.get("meeting", meet["id"])["date"] == "2026-11-12"
    dlv = next(i for i in its if i["kind"] == "delivery")
    pc.move(s, dlv, -1)
    assert s.get("expedite", dlv["id"])["expected"] == "2026-11-08"
    act = next(i for i in its if i["kind"] == "activity")
    before = s.get("activity", act["id"])
    with pytest.raises(pc.MoveError, match="Gantt"):
        pc.move(s, act, 3)
    assert s.get("activity", act["id"]) == before


def test_new_preset_from_a_dragged_day():
    assert pc.new_preset("meeting", dt.date(2026, 11, 18)) == \
        ("meeting", {"date": "2026-11-18"})
    with pytest.raises(pc.MoveError):
        pc.new_preset("activity", dt.date(2026, 11, 18))


def test_page_in_project_center(tmp_path, monkeypatch, qapp_pm):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from app.pm import center
    from app.pm.calendarui import ProjectCalendarPage
    s = _job(tmp_path, monkeypatch)
    w = center.ProjectCenter(s)
    p = w.show_tool("calendar")
    assert isinstance(p, ProjectCalendarPage)
    p.cal.today = dt.date(2026, 11, 4)
    p.cal.go_today()
    p.resize(1200, 800)
    p.show()
    qapp_pm.processEvents()
    assert p.cal.title.text() == "November 2026"
    assert "item(s) shown" in p.note.text()
    # filters
    p.show_kind["activity"].setChecked(False)
    p.show_kind["milestone"].setChecked(False)
    assert {i["kind"] for i in p.cal.items} == {"inspection", "meeting",
                                                "delivery"}
    # drag the meeting two days later
    g = p.cal.grid
    g.resize(1100, 700)
    g.grab()                      # paints offscreen even inside a hidden window
    rect, it = next((r, i) for r, i in g.hits if i["kind"] == "meeting")
    rows = g.rows()
    r = next(k for k, wk in enumerate(rows) if dt.date(2026, 11, 12) in wk)
    to = g.cell(r, rows[r].index(dt.date(2026, 11, 12)), len(rows)).center()

    def ev(kind, pos, buttons):
        return QMouseEvent(kind, QPointF(pos), QPointF(pos),
                           Qt.MouseButton.LeftButton, buttons,
                           Qt.KeyboardModifier.NoModifier)
    left = Qt.MouseButton.LeftButton
    g.mousePressEvent(ev(QMouseEvent.Type.MouseButtonPress, rect.center(),
                         left))
    g.mouseMoveEvent(ev(QMouseEvent.Type.MouseMove, to, left))
    g.mouseReleaseEvent(ev(QMouseEvent.Type.MouseButtonRelease, to,
                           Qt.MouseButton.NoButton))
    assert s.get("meeting", it["id"])["date"] == "2026-11-12"
    # a new inspection from a dragged range opens the create dialog
    seen = {}
    from app.pm import center as c
    monkeypatch.setattr(c.ToolPage, "new",
                        lambda self, preset=None: seen.update(
                            key=self.key, preset=preset))
    p.new_item(dt.date(2026, 11, 18), dt.date(2026, 11, 19),
               kind="inspection")
    assert seen == {"key": "inspection", "preset": {"date": "2026-11-18"}}
    w.close()
