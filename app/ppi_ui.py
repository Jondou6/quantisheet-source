"""Escalation window: real BLS Producer Price Index series as escalation
rates for bid tabs and cost books."""
import logging
import datetime as _dt

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout)

from . import ppi, settings

COLS = ["Series", "What it measures", "Used for", "Latest", "Month",
        "Factor", "% per year", ""]


class EscalationDialog(QDialog):
    def __init__(self, parent=None, book=None):
        super().__init__(parent)
        self.setWindowTitle("Escalation from BLS Producer Prices")
        self.resize(1150, 640)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(
            "Real price changes by trade from the U.S. Bureau of Labor "
            "Statistics Producer Price Index (series checked against the AGC "
            "monthly PPI tables). Fetch updates them for everyone using this "
            "price database."))
        row = QHBoxLayout()
        row.addWidget(QLabel("From:"))
        self.start = QLineEdit("2024-01")
        self.start.setMaximumWidth(80)
        row.addWidget(self.start)
        row.addWidget(QLabel("To:"))
        self.end = QLineEdit(_dt.date.today().strftime("%Y-%m"))
        self.end.setMaximumWidth(80)
        row.addWidget(self.end)
        for w in (self.start, self.end):
            w.editingFinished.connect(self.fill)
        row.addWidget(QLabel("BLS key (optional):"))
        self.key = QLineEdit(settings.get("bls_key") or "")
        self.key.setEchoMode(QLineEdit.Password)
        self.key.setPlaceholderText("free from data.bls.gov/registrationEngine")
        row.addWidget(self.key, 1)
        b = QPushButton("Fetch from BLS")
        b.clicked.connect(lambda: self.fetch())
        row.addWidget(b)
        lay.addLayout(row)
        self.when = QLabel("")
        lay.addWidget(self.when)
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        lay.addWidget(self.table, 1)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        row = QHBoxLayout()
        b = QPushButton("Use for Bid Tabs")
        b.setToolTip("Each bid escalates at its trade's PPI rate")
        b.clicked.connect(lambda: self.use_bidtabs())
        row.addWidget(b)
        self.book = QComboBox()
        from . import costbook
        try:
            for n in costbook.list_books():   # shown name, stored name
                self.book.addItem(costbook.display_name(n), n)
        except Exception:
            logging.getLogger(__name__).debug("ignored error", exc_info=True)
        if book:
            i = self.book.findData(book)
            if i >= 0:
                self.book.setCurrentIndex(i)
            else:
                self.book.setCurrentText(book)
        row.addWidget(QLabel("Cost book:"))
        row.addWidget(self.book)
        b = QPushButton("Use for This Cost Book")
        b.setToolTip("Items escalate at their CSI division's PPI rate; the "
                     "general rate becomes new nonresidential construction")
        b.clicked.connect(lambda: self.use_book())
        row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.fill()

    def months(self):
        return self.start.text().strip(), self.end.text().strip()

    def fetch(self, fetcher=None):
        key = self.key.text().strip()
        settings.set("bls_key", key or None)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            got = ppi.fetch(key=key or None, fetcher=fetcher)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "BLS", f"Couldn't reach BLS ({e}). "
                                "The saved figures are still used.")
            return None
        QApplication.restoreOverrideCursor()
        missing = [s for s in ppi.series() if not got.get(s)]
        if missing:
            QMessageBox.information(self, "BLS", "No data came back for: " +
                                    ", ".join(missing))
        self.fill()
        return got

    def fill(self):
        start, end = self.months()
        f = ppi.fetched()
        self.when.setText(f"Last fetched {f[:16].replace('T', ' ')}" if f else
                          "Not fetched yet - click Fetch from BLS.")
        try:
            rows = ppi.table(start, end)
        except Exception as e:
            self.summary.setText(f"<span style='color:#b00'>{e}</span>")
            return []
        self.table.setRowCount(len(rows))
        for r, x in enumerate(rows):
            vals = [x["id"], x["title"], ", ".join(x["trades"]),
                    "" if x["last"] is None else f"{x['last']:.1f}",
                    x["last_month"],
                    "" if x["factor"] is None else f"{x['factor']:.3f}",
                    "" if x["annual_pct"] is None else
                    f"{x['annual_pct']:+.2f}",
                    "; ".join(([f"extends {x['extrapolated']} mo past the "
                                "data"] if x["extrapolated"] else [])
                              + list(x.get("warnings") or []))]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                if c in (3, 5, 6):
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, c, it)
        tr = ppi.trade_rates(start, end)
        self.summary.setText(
            ("By trade, % per year " + f"{start} to {end}: " + ", ".join(
                f"{t} {v:+.1f}" for t, v in sorted(tr.items())))
            if tr else "")
        return rows

    def use_bidtabs(self):
        start, end = self.months()
        new = ppi.apply_to_bidtabs(start, end)
        QMessageBox.information(self, "Bid Tabs", f"Bid tabs now escalate "
                                f"{len(new)} trades at their PPI rates.")
        return new

    def use_book(self):
        name = self.book.currentData() or self.book.currentText()
        if not name:
            return None
        start, end = self.months()
        try:
            divs = ppi.apply_to_book(name, start, end)
        except Exception as e:
            QMessageBox.warning(self, "Cost Book", str(e))
            return None
        QMessageBox.information(
            self, "Cost Book", f"{_shown(name)} now escalates {len(divs)} CSI "
            "divisions at their PPI rates (logged in its History).")
        return divs


def _shown(name):
    """A cost book's name as people see it (costbook.display_name)."""
    from . import costbook
    return costbook.display_name(name)
