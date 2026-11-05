"""Preflight window: check a PDF for print and export PDF/X."""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QMessageBox, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from . import preflight, theme


class PreflightDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.win = window
        self.setWindowTitle("Preflight")
        self.resize(860, 520)
        v = QVBoxLayout(self)
        h = QHBoxLayout()
        h.addWidget(QLabel("Check for"))
        self.profile = QComboBox()
        self.profile.addItems(list(preflight.PROFILES))
        self.profile.currentIndexChanged.connect(lambda _i: self.refresh())
        h.addWidget(self.profile)
        self.head = QLabel()
        h.addWidget(self.head, 1)
        v.addLayout(h)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["", "Problem", "Pages"])
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self.table.verticalHeader().hide()
        v.addWidget(self.table, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        b = bb.addButton("Export PDF/X…", QDialogButtonBox.ActionRole)
        b.clicked.connect(self.export)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.refresh()

    def refresh(self):
        doc = self.win._view.doc
        self.issues = preflight.preflight(doc, self.profile.currentText())
        t = self.table
        t.setRowCount(len(self.issues))
        for r, i in enumerate(self.issues):
            sev = QTableWidgetItem({"error": "Error", "warning": "Warning",
                                    "info": "Info"}[i["severity"]])
            theme.tint(sev, {"error": "#ffd9d9", "warning": "#fff1c2",
                             "info": "#e3ecff"}[i["severity"]])
            pages = ", ".join(map(str, i["pages"][:12])) + \
                ("…" if len(i["pages"]) > 12 else "")
            for c, it in enumerate((sev, QTableWidgetItem(
                    i["text"] + ("  (fixed on export)" if i["fix"] else "")),
                    QTableWidgetItem(pages))):
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                t.setItem(r, c, it)
        self.head.setText("   " + preflight.summary(self.issues))

    def export(self):
        base = os.path.splitext(self.win._path or "document")[0]
        prof = self.profile.currentText()
        if prof.startswith("Plan"):
            prof = "PDF/X-4"
        path, _ = QFileDialog.getSaveFileName(
            self, f"Export {prof}", f"{base} ({prof.replace('/', '-')}).pdf",
            "PDF (*.pdf)")
        if not path:
            return
        res = preflight.export_pdfx(self.win._view.doc, path, prof)
        msg = "Done: " + "; ".join(res["done"])
        if res["remaining"]:
            msg += "\n\nStill to fix (needs the authoring program or " \
                   "Ghostscript):\n" + "\n".join(
                       "• " + i["text"] for i in res["remaining"][:8])
        QMessageBox.information(self, f"Export {prof}", msg)
