"""Shared pieces for the service windows. Qt lives here and in the
window modules, not in the record-keeping modules."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QHBoxLayout,
                               QLabel, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)


class Desk(QDialog):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(980, 700)
        self.root = QVBoxLayout(self)
        self.msg = QLabel("")
        self.msg.setWordWrap(True)

    def finish(self):
        self.root.addWidget(self.msg)

    def buttons(self, *pairs):
        row = QHBoxLayout()
        for label, fn in pairs:
            b = QPushButton(label)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch(1)
        self.root.addLayout(row)

    def guard(self, fn):
        try:
            result = fn()
        except ValueError as e:
            self.msg.setText(str(e))
            return None
        return result


def table(headers):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(list(headers))
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.verticalHeader().setVisible(False)
    t.setAlternatingRowColors(True)
    return t


def fill(widget, rows, ids=None):
    widget.setRowCount(len(rows))
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            item = QTableWidgetItem("" if val is None else str(val))
            if c == 0 and ids is not None:
                item.setData(Qt.UserRole, ids[r])
            widget.setItem(r, c, item)
    widget.resizeColumnsToContents()


def selected_id(widget):
    row = widget.currentRow()
    if row < 0:
        return None
    item = widget.item(row, 0)
    return None if item is None else item.data(Qt.UserRole)


def show(win):
    win.show()
    win.raise_()
    win.activateWindow()
    return win
