"""Dispatch board. open_window(parent) shows it.

Unassigned tickets are on the left. Each technician is a list for the
day shown. Dropping a ticket on a list assigns it; dropping it on
Unassigned clears the technician and the day. Print writes the day sheet.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QDateEdit, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QVBoxLayout,
                               QWidget)

from . import dispatch, uiutil, workorder


class _Lane(QListWidget):
    """A drop target. The ticket id travels in the drag text."""

    def __init__(self, board, tech):
        super().__init__()
        self.board = board
        self.tech = tech
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setMinimumWidth(180)
        self.setMinimumHeight(220)

    def mimeData(self, items):
        mime = super().mimeData(items)
        if items:
            mime.setText(items[0].data(Qt.UserRole) or "")
        return mime

    def dropEvent(self, event):
        wo_id = ""
        if event.mimeData() is not None:
            wo_id = event.mimeData().text()
        if not wo_id and event.source() is not None:
            item = event.source().currentItem()
            wo_id = item.data(Qt.UserRole) if item else ""
        event.accept()
        if wo_id:
            # Reload after this drop finishes so the lane is not deleted
            # while Qt is still inside it.
            from PySide6.QtCore import QTimer
            tech = self.tech
            QTimer.singleShot(0, lambda: self.board.assign_to(wo_id, tech))


def _hh2_note():
    return ("hh2 has no published time import format: this is a CSV with "
            "the columns set in service_hh2_time_columns - set them up "
            "once with your hh2 administrator.")


class DispatchWindow(uiutil.Desk):
    def __init__(self, parent=None):
        super().__init__("Dispatch Board", parent)
        self.path = workorder.default_path()
        top = QHBoxLayout()
        self.day = QDateEdit()
        self.day.setCalendarPopup(True)
        self.day.setDisplayFormat("yyyy-MM-dd")
        from PySide6.QtCore import QDate
        self.day.setDate(QDate.currentDate())
        self.day.dateChanged.connect(lambda *_: self.reload())
        self.tech_name = QLineEdit()
        self.tech_name.setPlaceholderText("Technician")
        top.addWidget(QLabel("Day"))
        top.addWidget(self.day)
        top.addWidget(self.tech_name)
        self.root.addLayout(top)
        self.buttons(("Add technician", self.add_tech_clicked),
                     ("Print day sheet", self.print_clicked),
                     ("Send week's hours…", self.hours_clicked))
        self.columns = QHBoxLayout()
        self.root.addLayout(self.columns, 1)
        self.lanes = {}
        self.finish()
        self.reload()

    def _day(self):
        return self.day.date().toString("yyyy-MM-dd")

    def reload(self):
        self.store = workorder.load(self.path)
        while self.columns.count():
            item = self.columns.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.lanes = {}
        info = dispatch.board(self.store, self._day())
        self._add_lane("Unassigned", "", info["unassigned"])
        for tech, rows in info["by_tech"].items():
            self._add_lane(tech, tech, rows)

    def _add_lane(self, title, tech, rows):
        wrap = QWidget()
        lay = QVBoxLayout(wrap)
        lay.addWidget(QLabel(title))
        lane = _Lane(self, tech)
        for wo in rows:
            lane.addItem(f"{wo['number']}  {wo['customer']}")
            lane.item(lane.count() - 1).setData(Qt.UserRole, wo["id"])
        lay.addWidget(lane)
        self.columns.addWidget(wrap)
        self.lanes[tech] = lane

    def add_tech_clicked(self):
        if self.guard(lambda: dispatch.add_tech(self.store, self.tech_name.text())):
            workorder.save(self.store, self.path)
            self.reload()

    def assign_to(self, wo_id, tech):
        """Used by the drop handler and by tests."""
        def go():
            return dispatch.assign(self.store, wo_id, tech,
                                   self._day() if tech else "")
        if self.guard(go):
            workorder.save(self.store, self.path)
            self.msg.setText("Assigned." if tech else "Back to unassigned.")
            self.reload()

    def print_to(self, path, tech=None):
        out = self.guard(lambda: dispatch.day_sheet(
            self.store, self._day(), path, tech=tech))
        if out:
            self.msg.setText(f"Saved {out}")
        return out

    def print_clicked(self):
        from PySide6.QtWidgets import QFileDialog
        from . import files
        path, _ = QFileDialog.getSaveFileName(
            self, "Day sheet", files.path_for("Day sheet.pdf"), "PDF (*.pdf)")
        if path:
            self.print_to(path)


    def week(self):
        """Monday to Sunday around the board's day (ISO dates)."""
        import datetime as _dt
        d = _dt.date.fromisoformat(self._day())
        start = d - _dt.timedelta(days=d.weekday())
        return start.isoformat(), (start + _dt.timedelta(days=6)).isoformat()

    def hours_clicked(self, _checked=False, ask=None, start=None, path=None):
        """The week's work-order hours as Back Office time cards (each
        entry goes in once; timecards.py) - or, when the time route
        setting is hh2, a mapped CSV for hh2 plus its reverse file."""
        from PySide6.QtWidgets import QMessageBox
        from . import timecards
        since, until = self.week()
        if timecards.time_route() == "hh2":
            return self._hours_hh2(since, until, path)
        snap = timecards.snapshot(workorder.load(self.path), since, until)
        sm = timecards.summary(snap)
        if not sm["cards"]:
            self.msg.setText(f"No hours logged on work orders {since} to "
                             f"{until}.")
            return None
        text = (f"{sm['cards']} time entr(ies), {since} to {until}: " +
                ", ".join(f"{k} {v} h" for k, v in sm["hours"].items()))
        if ask is None:
            ask = lambda t: QMessageBox.question(          # noqa: E731
                self, "Send hours", t + "\n\nOpen Back Office with these "
                "hours for the service job? Hours already brought in are "
                "skipped there.") == QMessageBox.Yes
        if not ask(text):
            return None
        try:
            from .. import backoffice_hook
            (start or backoffice_hook.launch_snapshot)(snap)
        except Exception as e:                            # noqa: BLE001
            self.msg.setText(f"Back Office didn't start: {e}")
            return None
        self.msg.setText("Sent to Back Office: " + text)
        return snap



    def _hours_hh2(self, since, until, path=None):
        from PySide6.QtWidgets import QFileDialog
        from . import files, timecards
        orders = workorder.load(self.path)
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Hours for hh2",
                files.path_for(f"Service hours {since} to {until} for hh2.csv"),
                "CSV (*.csv)")
        if not path:
            return None
        try:
            out = timecards.hh2_csv(orders, path, since, until)
        except ValueError as e:
            self.msg.setText(str(e))
            return None
        workorder.save(orders, self.path)
        self.msg.setText(f"{out['entries']} entr(ies) written to {out['file']} "
                         f"(reverse file: {out['reverse']}). " + _hh2_note())
        return out


def open_window(parent=None):
    return uiutil.show(DispatchWindow(parent))
