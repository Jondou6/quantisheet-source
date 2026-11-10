"""Revision Log window (Review > Revision Log): what each drawing revision
did to the bid."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog,
                               QHBoxLayout, QHeaderView, QInputDialog,
                               QLabel, QMessageBox, QPushButton, QSplitter,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from . import revisions, theme
from .dmoney import c2 as _c2


def _rname(win, doc):
    """Company rule, date first (app/reportname.py)."""
    import os
    from .reportname import report_file_name
    proj = os.path.splitext(os.path.basename(
        getattr(win, "_path", "") or getattr(doc, "name", "") or ""))[0]
    return report_file_name("Revision Log", proj, ext=".xlsx")


def _m(v, sign=False):
    s = f"${abs(v):,.0f}"
    if sign and v:
        return ("+" if v > 0 else "−") + s
    return s


def _it(text, right=False):
    it = QTableWidgetItem(str(text))
    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
    if right:
        it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return it


class RevisionLogDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.win = window
        self.doc = window._view.doc
        self.setWindowTitle("Revision Log")
        self.resize(1100, 640)
        lay = QVBoxLayout(self)
        self.head = QLabel("")
        self.head.setWordWrap(True)
        self.head.setTextFormat(Qt.RichText)
        lay.addWidget(self.head)
        split = QSplitter(Qt.Vertical)
        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(
            ["No", "Revision", "Date", "Sheets changed", "Takeoffs flagged",
             "Still to check", "Value at risk", "Bid before", "Bid after",
             "Change"])
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.itemSelectionChanged.connect(self.show_detail)
        split.addWidget(self.table)
        self.detail = QTableWidget(0, 7)
        self.detail.setHorizontalHeaderLabels(
            ["Assembly", "Trade", "Qty before", "Qty after", "Before",
             "After", "Change"])
        self.detail.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        self.detail.verticalHeader().hide()
        split.addWidget(self.detail)
        split.setSizes([260, 300])
        lay.addWidget(split, 1)
        row = QHBoxLayout()
        b = QPushButton("Record a Revision…")
        b.setToolTip("Save the bid as it stands now as the start of a new "
                     "revision (Slip Sheet and Carry Takeoff do this for "
                     "you)")
        b.clicked.connect(lambda: self.record())
        row.addWidget(b)
        b = QPushButton("Show Takeoffs to Check")
        b.setToolTip("Filter the Markups list to takeoffs marked "
                     "\"Check - drawing revised\"")
        b.clicked.connect(self.show_flagged)
        row.addWidget(b)
        row.addStretch(1)
        b = QPushButton("Export to Excel…")
        b.clicked.connect(lambda: self.export())
        row.addWidget(b)
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.rows = []
        self.refresh()

    def refresh(self):
        self._now = revisions.snapshot(self.doc)   # priced once (3b M10)
        self.rows = revisions.log_rows(self.doc, self._now)
        t = self.table
        t.setRowCount(len(self.rows))
        for r, x in enumerate(self.rows):
            vals = (x["no"], x["label"], x["date"][:10], len(x["sheets"]),
                    x["flagged"], x["open"], _m(x["at_risk"]),
                    _m(x["before"]), _m(x["after"]) +
                    ("  (now)" if x["latest"] else ""),
                    f"{_m(x['change'], True)}  ({x['change_pct']:+.1f}%)")
            for c, v in enumerate(vals):
                it = _it(v, c >= 3)
                if c == 3 and x["sheets"]:
                    it.setToolTip(", ".join(x["sheets"]))
                if c == 5 and x["open"]:
                    theme.tint(it, "#fff1c2")
                if c == 9 and x["change"]:
                    theme.tint(it, "#ffd9d9" if x["change"] > 0
                               else "#d9f5e3")
                t.setItem(r, c, it)
        if not self.rows:
            self.head.setText(
                "<b>No revisions recorded yet.</b> Use Compare Revisions > "
                "Slip Sheet (or Carry Takeoff) when a new set comes in, and "
                "each revision's effect on the bid is tracked here.")
        else:
            last = self.rows[-1]
            total = sum(x["change"] for x in self.rows)
            self.head.setText(
                f"<b>{len(self.rows)} revision(s).</b> Bid moved "
                f"<b>{_m(total, True)}</b> since the first one. "
                + (f"<span style='color:#b54708'><b>{last['open']}</b> "
                   "takeoff(s) from the latest revision still need "
                   "re-measuring</span> - the change isn't final until they "
                   "are." if last["open"] else
                   "Every flagged takeoff has been checked."))
            t.selectRow(len(self.rows) - 1)
        return self.rows

    def show_detail(self):
        r = self.table.currentRow()
        if r < 0 or r >= len(self.rows):
            self.detail.setRowCount(0)
            return None
        ch = revisions.revision_changes(self.doc, self.rows[r]["no"],
                                        getattr(self, "_now", None))
        d = self.detail
        d.setRowCount(len(ch["items"]))
        for i, it in enumerate(ch["items"]):
            for c, v in enumerate((it["name"], it["trade"] or "",
                                   f"{_c2(it['qty_before']):,.2f} {it['unit']}",
                                   f"{_c2(it['qty_after']):,.2f} {it['unit']}",
                                   _m(it["before"]), _m(it["after"]),
                                   _m(it["change"], True))):
                d.setItem(i, c, _it(v, c >= 2))
        return ch

    def record(self, label=None):
        if label is None:
            label, ok = QInputDialog.getText(
                self, "Record a Revision", "Revision name (e.g. Addendum 2, "
                "Rev C):")
            if not ok or not label.strip():
                return None
        e = revisions.record(self.doc, label.strip())
        self.win._doc_edited()
        self.refresh()
        return e

    def show_flagged(self):
        from . import annotate
        m = self.win.markups
        try:
            i = m.status_filter.findText(annotate.REVISED)
            if i >= 0:
                m.status_filter.setCurrentIndex(i)
        except AttributeError:
            pass
        self.win.markups_dock.show()
        self.win.markups_dock.raise_()

    def export(self, path=None):
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Export Revision Log", _rname(self.win, self.doc),
                "Excel (*.xlsx)")
        if not path:
            return None
        try:
            return revisions.export_xlsx(self.doc, path)
        except Exception as e:
            QMessageBox.warning(self, "Revision Log", str(e))
            return None
