"""Project > Allowances…: a small table of the contract's allowances."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout,
                               QLabel, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from . import allowances as al


class AllowancesDialog(QDialog):
    COLS = ("Allowance", "Amount", "Spent", "Left")

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Allowances")
        self.resize(560, 360)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("The owner contract's allowances. The owner "
                             "report shows each one with what's left."))
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(list(self.COLS))
        lay.addWidget(self.table, 1)
        self.table.itemChanged.connect(
            lambda it: self._left(it.row()) if it.column() in (1, 2)
            else None)
        row = QHBoxLayout()
        for text, fn in (("Add", self.add_row), ("Remove", self.remove_row)):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, f=fn: f())
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        lay.addWidget(self.msg)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        for a in al.read(store):
            self.add_row(a["name"], f"{a['amount']:,.2f}",
                         f"{a['spent']:,.2f}")

    def add_row(self, name="", amount="", spent=""):
        r = self.table.rowCount()
        self.table.insertRow(r)
        for c, v in enumerate((name, amount, spent)):
            self.table.setItem(r, c, QTableWidgetItem(v))
        left = QTableWidgetItem("")
        left.setFlags(left.flags() & ~Qt.ItemIsEditable)
        self.table.setItem(r, 3, left)
        self._left(r)
        return r

    def _left(self, r):
        if any(self.table.item(r, c) is None for c in range(4)):
            return
        try:
            a = al._money(self.table.item(r, 1).text())
            s = al._money(self.table.item(r, 2).text())
            self.table.item(r, 3).setText(f"{a - s:,.2f}")
        except al.AllowanceError:
            self.table.item(r, 3).setText("?")

    def remove_row(self):
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r)

    def rows(self):
        return [{"name": self.table.item(r, 0).text(),
                 "amount": self.table.item(r, 1).text(),
                 "spent": self.table.item(r, 2).text()}
                for r in range(self.table.rowCount())]

    def save(self):
        try:
            al.save(self.store, self.rows())
        except al.AllowanceError as e:
            self.msg.setText(str(e))
            return False
        self.accept()
        return True
