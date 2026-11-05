"""Estimate > Placeholders & Allowances, Escalation to Buy Date and Bid
Gate Settings (logic: bidgate.py)."""
import csv

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (QDateEdit, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout,
                               QHeaderView, QLabel, QMessageBox,
                               QSpinBox, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from . import bidgate


def _table(heads):
    t = QTableWidget(0, len(heads))
    t.setHorizontalHeaderLabels(heads)
    t.verticalHeader().hide()
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    t.horizontalHeader().setStretchLastSection(True)
    t.setEditTriggers(QTableWidget.NoEditTriggers)
    return t


class PlaceholdersDialog(QDialog):
    """Every placeholder, plug and allowance still in the bid - before it
    goes out, and again at buyout."""

    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle("Placeholders & Allowances")
        self.resize(760, 420)
        lay = QVBoxLayout(self)
        self.rows = bidgate.placeholders(doc)
        total = sum((r["amount"] for r in self.rows), 0)
        lay.addWidget(QLabel(
            f"<b>{len(self.rows)}</b> placeholder(s), plug(s) and "
            f"allowance(s) still in the estimate, <b>${total:,.2f}</b>. "
            "Replace each with takeoff or a real quote, or keep it on "
            "purpose." if self.rows else
            "Nothing left to replace: no placeholders, plugs or allowances "
            "in the estimate."))
        self.table = _table(["Kind", "Item", "Amount", "From"])
        self.table.setRowCount(len(self.rows))
        for i, r in enumerate(self.rows):
            for c, v in enumerate((r["kind"].title(), r["item"],
                                   f"${r['amount']:,.2f}", r["source"])):
                self.table.setItem(i, c, QTableWidgetItem(v))
        lay.addWidget(self.table, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        exp = bb.addButton("Export CSV…", QDialogButtonBox.ActionRole)
        exp.clicked.connect(lambda: self.export())
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def export(self, path=None):
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Export Placeholders", "Placeholders.csv", "CSV (*.csv)")
            if not path:
                return None
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Kind", "Item", "Amount", "From"])
            for r in self.rows:
                w.writerow([r["kind"], r["item"], f"{r['amount']:.2f}",
                            r["source"]])
        return path


class EscalationDialog(QDialog):
    """Escalation to Buy Date: each cost type's rise (% a year) from the
    bid day to the day it is bought; Add to Estimate puts it in as a
    line."""

    def __init__(self, doc, parent=None, on_added=None):
        super().__init__(parent)
        self.doc = doc
        self.on_added = on_added
        self.setWindowTitle("Escalation to Buy Date")
        self.resize(620, 400)
        lay = QVBoxLayout(self)
        f = QFormLayout()
        self.bid = QDateEdit(QDate.currentDate())
        self.bid.setCalendarPopup(True)
        self.buy = QDateEdit(QDate.currentDate().addMonths(6))
        self.buy.setCalendarPopup(True)
        f.addRow("Bid date:", self.bid)
        f.addRow("Bought on:", self.buy)
        self.pct = {}
        for t, v in bidgate.rates().items():
            sb = QDoubleSpinBox()
            sb.setRange(-50, 100)
            sb.setDecimals(1)
            sb.setSuffix(" % a year")
            sb.setValue(v)
            sb.valueChanged.connect(lambda _v: self.refresh())
            self.pct[t] = sb
            f.addRow(f"{t}:", sb)
        self.bid.dateChanged.connect(lambda _d: self.refresh())
        self.buy.dateChanged.connect(lambda _d: self.refresh())
        lay.addLayout(f)
        self.table = _table(["Cost type", "In the estimate", "% a year",
                             "Months", "Rise"])
        lay.addWidget(self.table, 1)
        self.total = QLabel("")
        lay.addWidget(self.total)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        add = bb.addButton("Add to Estimate", QDialogButtonBox.ActionRole)
        add.clicked.connect(lambda: self.add())
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.refresh()

    def _rates(self):
        return {t: sb.value() for t, sb in self.pct.items()}

    def result(self):
        return bidgate.project(self.doc, self.buy.date().toString("yyyy-MM-dd"),
                               self.bid.date().toString("yyyy-MM-dd"),
                               pct=self._rates())

    def refresh(self):
        r = self.result()
        self.table.setRowCount(len(r["rows"]))
        for i, x in enumerate(r["rows"]):
            for c, v in enumerate((x["type"], f"${x['amount']:,.2f}",
                                   f"{x['pct_year']:g}%", f"{x['months']}",
                                   f"${x['rise']:,.2f}")):
                self.table.setItem(i, c, QTableWidgetItem(v))
        self.total.setText(f"<b>Projected rise: ${r['total']:,.2f}</b>")
        return r

    def add(self):
        from .. import estimate_lines as EL
        r = self.result()
        bidgate.save_rates(self._rates())
        if not r["total"]:
            QMessageBox.information(self, self.windowTitle(),
                                    "No rise to add.")
            return None
        ids = EL.add(self.doc, [bidgate.escalation_line(
            r, self.buy.date().toString("yyyy-MM-dd"))])
        if self.on_added:
            self.on_added()
        return ids[0]


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Bid Gate Settings")
        f = QFormLayout(self)
        self.days = QSpinBox()
        self.days.setRange(1, 3650)
        self.days.setSuffix(" days")
        self.days.setValue(bidgate.max_age())
        f.addRow("Warn when a price is older than:", self.days)
        f.addRow(QLabel("Error Check also flags expired quotes, unpriced "
                        "addenda, placeholders and double counts."))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def save(self):
        from .. import settings
        settings.set(bidgate.S_MAX_AGE, int(self.days.value()))
        self.accept()


def gate_text(doc):
    """Plain words for what blocks the bid going out ("" = nothing)."""
    b = bidgate.blockers(doc)
    if not b:
        return ""
    return ("Not priced yet: " + ", ".join(f["item"] for f in b) +
            ". Mark each addendum priced (even at $0) in Project > Addenda "
            "before the bid goes out.")

