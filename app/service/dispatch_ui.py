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
                     ("Print day sheet", self.print_clicked))
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


def open_window(parent=None):
    return uiutil.show(DispatchWindow(parent))
