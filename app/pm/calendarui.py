"""Project Calendar page: the job's month / week at a glance - schedule
activities and milestones, inspections, meetings and expected deliveries.
Drag a day range to add a meeting or inspection; drag a meeting,
inspection or delivery to move it; click anything to open it. Activities
are read from the schedule and changed only in the Gantt chart."""
from __future__ import annotations

from datetime import date

from PySide6.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel,
                               QMenu, QVBoxLayout, QWidget)

from . import project_calendar as pc
from .calendar_view import CalendarView


class ProjectCalendarPage(QWidget):
    def __init__(self, center, today=None):
        super().__init__()
        self.center = center
        self.store = center.store
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        head = QFrame()
        head.setObjectName("pcPageHead")
        h = QHBoxLayout(head)
        h.setContentsMargins(18, 14, 18, 12)
        t = QLabel("Calendar")
        t.setObjectName("pcH1")
        h.addWidget(t)
        self.note = QLabel()
        self.note.setObjectName("muted")
        h.addWidget(self.note)
        h.addStretch()
        self.show_kind = {}
        for k in pc.KINDS:
            cb = QCheckBox(pc.LABELS[k])
            cb.setChecked(True)
            cb.toggled.connect(lambda _on: self.cal.reload())
            self.show_kind[k] = cb
            h.addWidget(cb)
        v.addWidget(head)
        body = QWidget()
        bv = QVBoxLayout(body)
        bv.setContentsMargins(18, 8, 18, 18)
        self.cal = CalendarView(self._source, today=today or date.today())
        self.cal.itemActivated.connect(self.open_item)
        self.cal.itemMoved.connect(self.move_item)
        self.cal.rangeSelected.connect(self.new_item)
        bv.addWidget(self.cal, 1)
        v.addWidget(body, 1)

    def _source(self, a, b):
        kinds = [k for k, cb in getattr(self, "show_kind", {}).items()
                 if cb.isChecked()] or None
        if hasattr(self, "show_kind") and not kinds:
            return [], {}
        its = pc.items(self.store, a, b, kinds)
        if hasattr(self, "note"):
            crit = sum(1 for i in its if i["critical"])
            self.note.setText(f"{len(its)} item(s) shown" +
                              (f", {crit} on the critical path (●)"
                               if crit else ""))
        return its, {}

    def refresh(self):
        self.cal.reload()

    def open_item(self, it):
        try:
            if it["coll"] == "activity":
                self.center.show_tool("gantt") if hasattr(
                    self.center, "show_tool") else None
            else:
                self.center.open_record(it["coll"], it["id"])
        except Exception:                                 # noqa: BLE001
            pass

    def move_item(self, it, days):
        try:
            pc.move(self.store, it, days)
            self._toast(f"Moved {it['title']} by {days:+d} day(s).")
        except pc.MoveError as e:
            self._toast(str(e))
        self.cal.reload()

    def new_item(self, a, _b, kind=None):
        """A dragged range (or a double-clicked day): a new meeting or
        inspection on its first day. `kind` skips the menu (tests)."""
        if kind is None:
            m = QMenu(self)
            acts = {m.addAction(f"New meeting on {a:%b %d}"): "meeting",
                    m.addAction(f"New inspection on {a:%b %d}"): "inspection"}
            from PySide6.QtGui import QCursor
            chosen = m.exec(QCursor.pos())
            kind = acts.get(chosen)
            if not kind:
                return None
        coll, preset = pc.new_preset(kind, a)
        page = self.center.show_tool(coll)
        if hasattr(page, "new"):
            try:
                return page.new(preset)
            except TypeError:
                return page.new()
        return None

    def _toast(self, text):
        if hasattr(self.center, "toast"):
            self.center.toast(text)
