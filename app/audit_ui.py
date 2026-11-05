"""Measurement Audit window: who took off what, when, how and at what
scale - and takeoff search across every job in the shared database."""
import logging
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFileDialog, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QTabWidget, QVBoxLayout, QWidget)

from . import annotate, audit, settings, theme
from .reportname import report_file_name


def _it(v, right=False):
    it = QTableWidgetItem("" if v is None else str(v))
    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
    if right:
        it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return it


class AuditDialog(QDialog):
    COLS = ["Sheet", "Group", "Quantity", "Taken by", "Taken", "How",
            "Confidence", "Scale", "Revision", "Status"]

    def __init__(self, window, tab=0):
        super().__init__(window)
        self.win = window
        self.doc = window._view.doc if window._view else None
        self.setWindowTitle("Measurement Audit")
        self.resize(1180, 680)
        v = QVBoxLayout(self)
        self.tabs = QTabWidget()
        v.addWidget(self.tabs, 1)

        # --- this document ---
        w = QWidget()
        lay = QVBoxLayout(w)
        self.head = QLabel("")
        self.head.setWordWrap(True)
        self.head.setTextFormat(Qt.RichText)
        lay.addWidget(self.head)
        row = QHBoxLayout()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter by group, author, sheet…")
        self.filter.textChanged.connect(lambda: self.fill())
        row.addWidget(self.filter, 1)
        self.how = QComboBox()
        self.how.addItem("Every method", "")
        for k, label in audit.METHODS.items():
            self.how.addItem(label, k)
        self.how.currentIndexChanged.connect(lambda: self.fill())
        row.addWidget(self.how)
        self.only_check = QCheckBox("Only to check")
        self.only_check.toggled.connect(lambda: self.fill())
        row.addWidget(self.only_check)
        lay.addLayout(row)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self.table.verticalHeader().hide()
        self.table.setSortingEnabled(True)
        self.table.cellDoubleClicked.connect(self._go)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.auto_sync = QCheckBox("Update the shared takeoff table every "
                                   "time I save")
        self.auto_sync.setChecked(bool(settings.get("mirror_on_save")))
        self.auto_sync.toggled.connect(
            lambda on: settings.set("mirror_on_save", bool(on)))
        row.addWidget(self.auto_sync)
        row.addStretch(1)
        b = QPushButton("Send to Shared Database")
        b.setToolTip("Copy this file's takeoff into the shared price "
                     "database so it can be searched with every other job")
        b.clicked.connect(lambda: self.sync())
        row.addWidget(b)
        b = QPushButton("Export to Excel…")
        b.clicked.connect(lambda: self.export())
        row.addWidget(b)
        lay.addLayout(row)
        self.tabs.addTab(w, "This Document")

        # --- across jobs ---
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        self.q = QLineEdit()
        self.q.setPlaceholderText("Search takeoff in every job, e.g. "
                                  "\"storm 18\" or \"interior wall\"")
        self.q.returnPressed.connect(lambda: self.search())
        row.addWidget(self.q, 1)
        b = QPushButton("Search")
        b.setDefault(False)
        b.clicked.connect(lambda: self.search())
        row.addWidget(b)
        lay.addLayout(row)
        self.totals = QLabel("")
        self.totals.setWordWrap(True)
        lay.addWidget(self.totals)
        self.results = QTableWidget(0, 8)
        self.results.setHorizontalHeaderLabels(
            ["Job", "Sheet", "Group", "Quantity", "Taken by", "Taken",
             "How", "File"])
        self.results.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch)
        self.results.verticalHeader().hide()
        self.results.cellDoubleClicked.connect(self._open_result)
        lay.addWidget(self.results, 1)
        self.tabs.addTab(w, "Search All Jobs")
        self.tabs.setCurrentIndex(tab)

        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.rows = audit.trail(self.doc) if self.doc is not None else []
        self.found = []
        self.fill()

    def fill(self):
        q = self.filter.text().strip().lower()
        how = self.how.currentData()
        rows = [r for r in self.rows
                if (not q or q in " ".join(str(r[k]) for k in (
                    "group", "author", "sheet", "revision")).lower())
                and (not how or r["method"] == how)
                and (not self.only_check.isChecked()
                     or r["status"] == annotate.REVISED)]
        self.shown = rows
        t = self.table
        t.setSortingEnabled(False)
        t.setRowCount(len(rows))
        for i, r in enumerate(rows):
            conf = "" if r["confidence"] is None else \
                f"{r['confidence'] * 100:.0f}%"
            vals = (r["sheet"] or f"p. {r['page'] + 1}", r["group"],
                    f"{r['value']:,.2f} {r['unit']}", r["author"],
                    r["taken"].replace("T", " ")[:16],
                    audit.METHODS.get(r["method"], r["method"]), conf,
                    r["scale"], r["revision"], r["status"])
            for c, val in enumerate(vals):
                it = _it(val, c in (2, 6))
                if c == 0:
                    it.setData(Qt.UserRole, i)
                if c == 6 and r["confidence"] is not None and \
                        r["confidence"] < 0.85:
                    theme.tint(it, "#fff1c2")
                if c == 9 and r["status"] == annotate.REVISED:
                    theme.tint(it, "#ffd9d9")
                t.setItem(i, c, it)
        t.setSortingEnabled(True)
        s = audit.summary(self.rows)
        methods = ", ".join(f"{audit.METHODS.get(k, k)} {n}"
                            for k, n in sorted(s["methods"].items(),
                                               key=lambda x: -x[1]))
        self.head.setText(
            f"<b>{len(self.rows)} measurement(s)</b> — {methods or 'none'}. "
            f"By {len(s['authors'])} person(s). "
            + (f"<span style='color:#b54708'>{s['to_check']} to re-measure "
               "after a revision.</span> " if s["to_check"] else "")
            + (f"{s['low_confidence']} automatic count(s) below 85% "
               "confidence. " if s["low_confidence"] else ""))
        return len(rows)

    def _go(self, row, _col):
        it = self.table.item(row, 0)
        if it is None:
            return
        r = self.shown[it.data(Qt.UserRole)]
        self.win._go_page(r["page"])
        try:
            self.win._go_annot(r["page"], r["ref"])
        except Exception:
            logging.getLogger(__name__).debug("ignored error", exc_info=True)

    def sync(self):
        if self.doc is None:
            return 0
        try:
            n = audit.mirror(self.doc, file=self.win._path or "")
        except Exception as e:
            QMessageBox.warning(self, "Measurement Audit", str(e))
            return None
        self.win._flash(f"Sent {n} measurement(s) to the shared database")
        return n

    def export(self, path=None):
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Export Measurement Audit", report_file_name(
                    "Measurement Audit", os.path.splitext(os.path.basename(
                        self.win._path or getattr(self.doc, "name", "")
                        or ""))[0], ext=".xlsx"),
                "Excel (*.xlsx)")
        if not path:
            return None
        return audit.export_xlsx(self.shown, path)

    def search(self, text=None):
        text = self.q.text() if text is None else text
        try:
            self.found = audit.search(text)
        except Exception as e:
            QMessageBox.warning(self, "Search All Jobs", str(e))
            return []
        t = self.results
        t.setRowCount(len(self.found))
        for i, r in enumerate(self.found):
            for c, val in enumerate((r["job"], r["sheet"], r["group"],
                                     f"{r['value']:,.2f} {r['unit']}",
                                     r["author"],
                                     (r["taken"] or "")[:10],
                                     audit.METHODS.get(r["method"],
                                                       r["method"]),
                                     os.path.basename(r["file"] or ""))):
                t.setItem(i, c, _it(val, c == 3))
        tot = audit.totals(self.found)
        self.totals.setText("  ·  ".join(
            f"<b>{g}</b>: {q:,.1f} {u} in {n} file(s)"
            for (g, u), (q, n) in sorted(tot.items())[:12])
            or "No takeoff found. Files appear here after Send to Shared "
               "Database (or with automatic updates on save).")
        self.totals.setTextFormat(Qt.RichText)
        return self.found

    def _open_result(self, row, _col):
        r = self.found[row]
        if r.get("file") and os.path.exists(r["file"]):
            self.win.open_sheet(r["file"], int(r.get("page") or 0))
