"""Exports screen (P1-17): type, format and dates, preview with problems,
Export, batch history. Shows the trademark notice; a dropped QuickBooks
company file is refused (addendum 17.6)."""
from PySide6.QtWidgets import (QComboBox, QDateEdit, QHBoxLayout, QLabel,
                               QListWidget, QPushButton, QVBoxLayout, QWidget)
from PySide6.QtCore import QDate

from .. import exports, fileguard
from .common import error, fill, heading, table


class DropGuard:
    """Mix-in for any screen that accepts dropped files: company files are
    refused with the standard message before anything opens them."""

    def drop_file(self, path) -> str:
        if fileguard.is_company_file(path):
            self.last_message = fileguard.MESSAGE
            return fileguard.MESSAGE
        self.last_message = ""
        return self.accept_file(path)

    def accept_file(self, path) -> str:                 # noqa: D401
        return ""

    def dragEnterEvent(self, ev):                         # noqa: N802
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):                              # noqa: N802
        for url in ev.mimeData().urls():
            msg = self.drop_file(url.toLocalFile())
            if msg:
                error(self, msg)


class ExportsPage(DropGuard, QWidget):
    def __init__(self, office, parent=None):
        super().__init__(parent)
        self.office = office
        self.setAcceptDrops(True)
        lay = QVBoxLayout(self)
        lay.addWidget(heading("Exports"))
        self.notice = QLabel(fileguard.TRADEMARK_NOTICE)
        self.notice.setWordWrap(True)
        lay.addWidget(self.notice)
        row = QHBoxLayout()
        self.kind = QComboBox()
        for k, v in exports.TYPES.items():
            self.kind.addItem(v, k)
        self.fmt = QComboBox()
        for k, v in exports.FORMATS.items():
            self.fmt.addItem(v, k)
        today = QDate.currentDate()
        self.d_from = QDateEdit(today.addDays(-today.day() + 1))
        self.d_to = QDateEdit(today)
        for w in (self.kind, self.fmt, self.d_from, self.d_to):
            w.setParent(self)
            row.addWidget(w)
        self.preview_btn = QPushButton("Preview")
        self.export_btn = QPushButton("Export")
        row.addWidget(self.preview_btn)
        row.addWidget(self.export_btn)
        lay.addLayout(row)
        self.problems = QListWidget()
        lay.addWidget(QLabel("Problems (not exported):"))
        lay.addWidget(self.problems)
        self.history = table(["Batch", "Type", "Format", "Records", "Total",
                              "Status", "File"])
        lay.addWidget(QLabel("Batch history"))
        lay.addWidget(self.history)
        self.preview_btn.clicked.connect(self.preview)
        self.export_btn.clicked.connect(self.export)
        self.export_btn.setEnabled(office.can("export.run"))
        self.refresh()

    def _args(self):
        return (self.kind.currentData(),
                self.d_from.date().toString("yyyy-MM-dd"),
                self.d_to.date().toString("yyyy-MM-dd"))

    def preview(self):
        k, a, b = self._args()
        try:
            pv = exports.preview(self.office, k, a, b, self.fmt.currentData())
        except Exception as e:                            # noqa: BLE001
            error(self, e)
            return None
        self.problems.clear()
        self.problems.addItems(pv["problems"])
        return pv

    def export(self):
        k, a, b = self._args()
        try:
            r = exports.export(self.office, k, a, b, self.fmt.currentData())
        except Exception as e:                            # noqa: BLE001
            error(self, e)
            return None
        self.problems.clear()
        self.problems.addItems(r["problems"])
        self.refresh()
        return r

    def refresh(self):
        fill(self.history, [(b["number"], b["type"], b["format"],
                             b["record_count"], b["total"], b["status"],
                             b["file_path"]) for b in
                            exports.batches(self.office)], money_cols=(4,))
