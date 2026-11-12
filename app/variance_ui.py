"""The Variance window: each bidder line by line against our own
estimate (see variance.py)."""
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from . import variance as V

BG = {V.HIGH: QColor("#ffcdcd"), V.LOW: QColor("#c8e6ff"),
      V.MISSING: QColor("#ffe1aa"), "none": QColor("#eeeeee")}
INK = QColor("#111111")


class VarianceDialog(QDialog):
    """`source()` gives (rows, bidders) for variance.compare; it is asked
    again whenever the percent changes."""

    def __init__(self, source, title="", parent=None, company=""):
        super().__init__(parent)
        self.source, self.title, self.company = source, title, company
        self.res = None
        self.setWindowTitle("Variance Against Our Estimate" +
                            (f" - {title}" if title else ""))
        self.resize(1100, 620)
        v = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Mark a row HIGH or LOW at"))
        self.pct = QDoubleSpinBox()
        self.pct.setRange(0.5, 1000.0)
        self.pct.setDecimals(1)
        self.pct.setSuffix(" %")
        self.pct.setValue(V.threshold())
        self.pct.valueChanged.connect(self._pct_changed)
        top.addWidget(self.pct)
        top.addWidget(QLabel("above or below our number (kept as your "
                             "setting)."))
        top.addStretch(1)
        v.addLayout(top)
        self.table = QTableWidget(0, 0)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        v.addWidget(self.table, 1)
        self.missing = QLabel("")
        self.missing.setWordWrap(True)
        v.addWidget(self.missing)
        v.addWidget(QLabel(
            "<span style='background:#ffcdcd;color:#111'>&nbsp;HIGH&nbsp;"
            "</span> <span style='background:#c8e6ff;color:#111'>&nbsp;LOW"
            "&nbsp;</span> <span style='background:#ffe1aa;color:#111'>"
            "&nbsp;MISSING SCOPE - plugged at our number&nbsp;</span> "
            "<span style='background:#eeeeee;color:#111'>&nbsp;no estimate"
            "&nbsp;</span>  A blank is not $0.00. The last row adds up to "
            "the totals to the cent."))
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        b = bb.addButton("Export to Excel…", QDialogButtonBox.ActionRole)
        b.clicked.connect(lambda: self.export_xlsx())
        b = bb.addButton("Export to PDF…", QDialogButtonBox.ActionRole)
        b.clicked.connect(lambda: self.export_pdf())
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.fill()

    def _pct_changed(self, val):
        try:
            V.set_threshold(val)
        except ValueError:
            return
        self.fill()

    def fill(self):
        rows, names = self.source()
        self.res = res = V.compare(rows, names, self.pct.value())
        t = self.table
        heads = ["Scope row", "Our number"]
        for n in names:
            heads += [n, "Difference", "Note"]
        t.setColumnCount(len(heads))
        t.setHorizontalHeaderLabels(heads)
        t.setRowCount(len(res["rows"]) + 1)
        for r, row in enumerate(res["rows"]):
            t.setItem(r, 0, QTableWidgetItem(row["desc"]))
            ours = QTableWidgetItem(V.money(row["ours"]) if row["ours"]
                                    is not None else "no estimate")
            if row["ours"] is None:
                ours.setBackground(BG["none"])
                ours.setForeground(INK)
            t.setItem(r, 1, ours)
            for k, n in enumerate(names):
                c = row["cells"][n]
                texts = V.cell_text(row, c)
                key = c["flag"] or (V.MISSING if c["state"] == V.MISSING
                                    else "none" if "no estimate" in texts[2]
                                    else "")
                for j, text in enumerate(texts):
                    it = QTableWidgetItem(text)
                    if key:
                        it.setBackground(BG[key])
                        it.setForeground(INK)
                    t.setItem(r, 2 + 3 * k + j, it)
        last = len(res["rows"])
        t.setItem(last, 0, QTableWidgetItem("LEVELED TOTAL"))
        t.setItem(last, 1, QTableWidgetItem(V.money(res["ours"])))
        for k, b in enumerate(res["bidders"]):
            if not b["breakdown"]:
                vals = ("", "", "no breakdown")
            else:
                vals = (V.money(b["leveled"]),
                        f"{V.signed(b['var_total'])} "
                        f"({V.pct_text(b['pct_total']) or 'n/a'})", "")
            for j, text in enumerate(vals):
                t.setItem(last, 2 + 3 * k + j, QTableWidgetItem(text))
        h = t.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeToContents)
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        bits = []
        for b in res["bidders"]:
            if b["missing_rows"] or b["unplugged"]:
                bits.append(
                    f"<b>{b['name']}</b>: missing scope "
                    f"{V.money(b['missing'])} (" + "; ".join(
                        f"{d} {V.money(v)}" for d, v in b["missing_rows"])
                    + ("; " if b["missing_rows"] and b["unplugged"] else "")
                    + "; ".join(f"{d} - no estimate" for d in b["unplugged"])
                    + ")")
        self.missing.setText("<br>".join(bits) if bits else
                             "No missing scope: every bidder priced every "
                             "row we carry.")
        return res

    def export_xlsx(self, path=None):
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Variance Report", f"Variance - {self.title}.xlsx",
                "Excel (*.xlsx)")
        return V.export_xlsx(self.res, path, self.title) if path else None

    def export_pdf(self, path=None):
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Variance Report", f"Variance - {self.title}.pdf",
                "PDF (*.pdf)")
        return V.export_pdf(self.res, path, self.title, self.company) \
            if path else None
