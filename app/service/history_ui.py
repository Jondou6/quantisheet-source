"""Customer History window (Nov 5). Pick a customer: sites, units,
every work order, invoice and refrigerant entry, newest first, with
totals. Read only. The record keeping is history.py."""
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel

from . import history, uiutil


class CustomerHistoryWindow(uiutil.Desk):
    def __init__(self, parent=None):
        super().__init__("Customer History", parent)
        row = QHBoxLayout()
        row.addWidget(QLabel("Customer"))
        self.who = QComboBox()
        self.who.setEditable(False)
        self.who.setAccessibleName("Customer")
        row.addWidget(self.who, 1)
        self.root.addLayout(row)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self.root.addWidget(self.summary)
        self.units = uiutil.table(["Site", "Unit", "Make", "Model",
                                   "Serial", "Installed"])
        self.units.setMaximumHeight(160)
        self.root.addWidget(self.units)
        self.table = uiutil.table(["Date", "What", "Detail", "Status"])
        self.root.addWidget(self.table, 1)
        self.finish()
        self.who.currentIndexChanged.connect(lambda _i: self.show_customer())
        self.reload()

    def reload(self):
        from ..estimating import service as records_api
        from . import agreements, workorder
        self._names = [n for n, _k in history.customers(
            records_api.load(), workorder.load(), agreements.load())]
        self.who.blockSignals(True)
        self.who.clear()
        self.who.addItems(self._names)
        self.who.blockSignals(False)
        if self._names:
            self.show_customer()
        else:
            self.summary.setText("No customers yet - they appear here once "
                                 "a site or work order is entered.")

    def show_customer(self, name=None):
        name = name or self.who.currentText()
        if not name:
            return None
        h = history.history(customer=name)
        self.summary.setText("\n".join(history.summary_lines(h)))
        sites = {p["id"]: p.get("name", "") for p in h["properties"]}
        uiutil.fill(self.units, [[sites.get(e.get("property"), ""),
                                  e.get("kind", ""), e.get("make", ""),
                                  e.get("model", ""), e.get("serial", ""),
                                  e.get("installed", "")]
                                 for e in h["equipment"]])
        uiutil.fill(self.table, [list(ev) for ev in h["events"]])
        self.history = h
        return h


def open_window(parent=None, customer=""):
    w = CustomerHistoryWindow(parent)
    if customer and customer in w._names:
        w.who.setCurrentIndex(w._names.index(customer))
    return uiutil.show(w)
