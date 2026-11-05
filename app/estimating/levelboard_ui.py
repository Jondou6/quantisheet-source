"""Estimate > Leveling Board (logic: levelboard.py)."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QHBoxLayout,
                               QHeaderView, QInputDialog, QLabel, QMenu,
                               QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from . import bidday, levelboard as LB

COLORS = {LB.GREEN: QColor(214, 241, 222), LB.YELLOW: QColor(255, 241, 189),
          LB.RED: QColor(250, 214, 210)}
FIXED = ["Item", "Qty", "Unit", "Our plug"]


class LevelBoard(QDialog):
    def __init__(self, doc, parent=None, on_change=None):
        super().__init__(parent)
        self.doc = doc
        self.on_change = on_change
        self.setWindowTitle("Leveling Board")
        self.resize(1100, 620)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Package:"))
        self.pkg = QComboBox()
        self.pkg.setMinimumWidth(220)
        self.pkg.currentIndexChanged.connect(lambda _i: self.refresh())
        top.addWidget(self.pkg)
        for text, fn in (("New From Trade…", self.new_from_trade),
                         ("Add Sub Quote PDF…", self.add_quote),
                         ("Export Scope Sheet…", self.export_scope),
                         ("Use Low in Estimate", self.use_low)):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, f=fn: f())
            top.addWidget(b)
        top.addStretch(1)
        lay.addLayout(top)
        lay.addWidget(QLabel(
            "<span style='background:#d6f1de'>&nbsp;confirmed&nbsp;</span> "
            "<span style='background:#fff1bd'>&nbsp;unclear&nbsp;</span> "
            "<span style='background:#fad6d2'>&nbsp;gap - plugged from "
            "our takeoff&nbsp;</span>  Right-click a cell to change it."))
        self.table = QTableWidget(0, len(FIXED))
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.table, 1)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        self.data = None
        self.fill_packages()

    def fill_packages(self, pick=None):
        self.pkg.blockSignals(True)
        self.pkg.clear()
        self.pkg.addItems(bidday.packages(self.doc))
        if pick:
            self.pkg.setCurrentText(pick)
        self.pkg.blockSignals(False)
        self.refresh()

    def package(self):
        return self.pkg.currentText()

    def refresh(self):
        p = self.package()
        if not p:
            self.table.setRowCount(0)
            self.summary.setText("No package yet: New From Trade… builds "
                                 "one from the takeoff and the specs.")
            self.data = None
            return None
        self.data = d = LB.board(self.doc, p)
        names = [b["name"] for b in d["bidders"]]
        self.table.setColumnCount(len(FIXED) + len(names))
        self.table.setHorizontalHeaderLabels(FIXED + names)
        self.table.setRowCount(len(d["rows"]))
        for r, row in enumerate(d["rows"]):
            vals = [row["desc"], row["qty"], row["unit"],
                    f"${row['plug']:,.2f}" if row["plug"] is not None else ""]
            for c, v in enumerate(vals):
                self.table.setItem(r, c, QTableWidgetItem(v))
            for k, n in enumerate(names):
                cell = row["cells"][n]
                a = cell["amount"]
                t = ("" if a is None else f"${a:,.2f}") + \
                    (" (plug)" if cell["plugged"] and a is not None else
                     " NO PLUG" if cell["plugged"] else "")
                it = QTableWidgetItem(t)
                it.setBackground(COLORS[cell["status"]])
                it.setData(Qt.UserRole, (n, row["id"]))
                self.table.setItem(r, len(FIXED) + k, it)
        parts = [f"<b>{b['name']}</b>: ${b['total']:,.2f} "
                 f"({b['gaps']} gap(s), {b['unclear']} unclear)"
                 for b in d["bidders"]]
        self.summary.setText(" &nbsp; ".join(parts) + (
            f"<br>Leveled low: <b>{d['low']}</b>" if d["low"] else ""))
        return d

    def _menu(self, pos):
        it = self.table.itemAt(pos)
        if it is None or not it.data(Qt.UserRole):
            return
        bidder, rid = it.data(Qt.UserRole)
        m = QMenu(self)
        m.addAction("Confirmed", lambda: self.set_cell(bidder, rid, LB.GREEN))
        m.addAction("Unclear", lambda: self.set_cell(bidder, rid, LB.YELLOW))
        m.addAction("Gap (not included)",
                    lambda: self.set_cell(bidder, rid, LB.RED))
        m.addAction("Type Their Price…",
                    lambda: self.set_cell(bidder, rid, LB.GREEN, ask=True))
        m.exec(self.table.viewport().mapToGlobal(pos))

    def set_cell(self, bidder, rid, status, ask=False, amount=None):
        if ask:
            v, ok = QInputDialog.getDouble(self, "Price", f"{bidder}:", 0, 0,
                                           1e12, 2)
            if not ok:
                return None
            amount = f"{v:.2f}"
        LB.set_status(self.doc, self.package(), bidder, rid, status, amount)
        self._changed()
        return self.refresh()

    def _changed(self):
        if self.on_change:
            self.on_change()

    def new_from_trade(self, division=None, spec_path=None, ask=True):
        from .. import csi
        tr = LB.trades(self.doc)
        if division is None:
            labels = [f"{d} {csi.DIVISIONS.get(d, 'Uncoded')}" if d else
                      "Uncoded items" for d in sorted(tr)]
            if not labels:
                QMessageBox.information(self, self.windowTitle(),
                                        "There's no takeoff to build a scope "
                                        "from yet.")
                return None
            pick, ok = QInputDialog.getItem(self, "New From Trade", "Trade:",
                                            labels, 0, False)
            if not ok:
                return None
            division = sorted(tr)[labels.index(pick)]
        if spec_path is None and ask:
            spec_path, _ = QFileDialog.getOpenFileName(
                self, "Spec book for this trade (optional - Cancel to skip)",
                "", "PDF (*.pdf)")
        spec = None
        if spec_path:
            import fitz
            spec = fitz.open(spec_path)
        sheet = LB.scope_sheet(self.doc, division, spec)
        self.last_sheet = sheet
        p = LB.start_board(self.doc, sheet)
        self._changed()
        self.fill_packages(p)
        return sheet

    def add_quote(self, path=None):
        if not self.package():
            QMessageBox.information(self, self.windowTitle(),
                                    "Make a package first (New From Trade).")
            return None
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Sub Quote", "",
                "Quotes (*.pdf *.png *.jpg *.jpeg *.tif *.tiff);;All (*)")
            if not path:
                return None
        try:
            got = LB.import_quote(self.doc, self.package(), path)
        except Exception as e:                            # noqa: BLE001
            QMessageBox.warning(self, self.windowTitle(),
                                f"That quote couldn't be read: {e}")
            return None
        self._changed()
        self.refresh()
        if got.get("check"):
            self.summary.setText(self.summary.text() + "<br>" + got["check"])
        if got["unmatched"]:
            self.summary.setText(self.summary.text() + "<br>Not matched to a "
                                 "scope row: " + "; ".join(
                                     got["unmatched"][:6]))
        return got

    def export_scope(self, path=None):
        sheet = getattr(self, "last_sheet", None)
        if sheet is None:
            s = bidday.load(self.doc, self.package()) if self.package() \
                else None
            if s is None:
                return None
            sheet = {"trade": s["package"], "rows": [
                dict(r, source="") for r in s["scope"]]}
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Scope Sheet", f"Scope - {sheet['trade']}.csv",
                "CSV (*.csv)")
            if not path:
                return None
        return LB.scope_csv(sheet, path)

    def use_low(self, bidder=None):
        if not self.package():
            return None
        try:
            got = LB.use_low(self.doc, self.package(), bidder)
        except bidday.BidDayError as e:
            QMessageBox.warning(self, self.windowTitle(), str(e))
            return None
        self._changed()
        self.refresh()
        self.summary.setText(self.summary.text() + f"<br>In the estimate: "
                             f"<b>{got['bidder']}</b> ${got['total']:,.2f}")
        return got
