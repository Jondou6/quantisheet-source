"""Takeoff > Item Names Learned: the AI names you renamed, and what AI
Takeoff calls them now (name_memory.py). Remove a pair, or turn the
renaming off."""
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog,
                               QDialogButtonBox, QHBoxLayout, QLabel,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from . import name_memory, settings

TITLE = "Item Names Learned"


class NameMemoryDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(TITLE)
        lay = QVBoxLayout(self)
        info = QLabel(
            "When you rename an item AI Takeoff made, or move its "
            "measurements to one of your items, the next AI Takeoff uses "
            "your name. Rooms are matched without their number; {n} is "
            "the room's own number.\nKept in: " + name_memory.path())
        info.setWordWrap(True)
        lay.addWidget(info)
        self.use = QCheckBox("Use these names in AI Takeoff")
        self.use.setChecked(name_memory.on())
        self.use.toggled.connect(
            lambda on: settings.set("remember_item_names", bool(on)))
        lay.addWidget(self.use)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["AI name", "Your name", "Kind",
                                              "Learned"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.table)
        row = QHBoxLayout()
        self.remove_btn = QPushButton("Forget Selected")
        self.remove_btn.clicked.connect(lambda: self.forget_selected())
        row.addWidget(self.remove_btn)
        row.addStretch(1)
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.resize(620, 420)
        self.fill()

    def fill(self):
        self.pairs = name_memory.pairs()
        self.table.setRowCount(len(self.pairs))
        for i, p in enumerate(self.pairs):
            kind = "room (any number)" if p.get("room") else \
                (p.get("type") or "item")
            for j, v in enumerate((p.get("from", ""), p.get("to", ""), kind,
                                   p.get("learned", ""))):
                self.table.setItem(i, j, QTableWidgetItem(str(v)))
        self.table.resizeColumnsToContents()
        self.remove_btn.setEnabled(bool(self.pairs))

    def forget_selected(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        n = 0
        for r in rows:
            if 0 <= r < len(self.pairs):
                n += name_memory.forget(self.pairs[r]["key"])
        self.fill()
        return n


def open_dialog(win, show=True):
    dlg = NameMemoryDialog(win)
    if show:
        dlg.exec()
    return dlg
