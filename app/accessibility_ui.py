"""Accessibility Check window and the PDF/A export command."""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog,
                               QHeaderView, QLabel, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from . import accessibility, pdfa, theme


class AccessibilityDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.win = window
        self.view = window._view
        self.setWindowTitle("Accessibility Check")
        self.resize(820, 520)
        v = QVBoxLayout(self)
        self.head = QLabel("")
        self.head.setWordWrap(True)
        v.addWidget(self.head)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Check", "Result", "Details"])
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch)
        self.table.verticalHeader().hide()
        v.addWidget(self.table, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        self.b_fix = bb.addButton("Fix Automatically",
                                  QDialogButtonBox.ActionRole)
        self.b_fix.clicked.connect(lambda: self.fix())
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.refresh()

    def refresh(self):
        self.results = accessibility.check(self.view.doc)
        t = self.table
        t.setRowCount(len(self.results))
        for r, x in enumerate(self.results):
            ok = QTableWidgetItem("Passed" if x["ok"] else
                                  ("Can fix" if x["fix"] else "Needs you"))
            theme.tint(ok, "#d9f5e3" if x["ok"] else
                       "#fff1c2" if x["fix"] else "#ffd9d9")
            for c, it in enumerate((QTableWidgetItem(x["name"]), ok,
                                    QTableWidgetItem(x["detail"]))):
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                t.setItem(r, c, it)
        bad = [x for x in self.results if not x["ok"]]
        fixable = [x for x in bad if x["fix"]]
        self.head.setText(
            f"{len(self.results) - len(bad)} of {len(self.results)} checks "
            f"passed. {len(fixable)} can be fixed automatically"
            + (f"; {len(bad) - len(fixable)} need the authoring program or "
               "a person." if len(bad) > len(fixable) else "."))
        self.b_fix.setEnabled(bool(fixable))
        return self.results

    def fix(self):
        done = self.win._page_change(
            lambda: accessibility.fix(self.view.doc),
            "Fixed accessibility settings")
        self.refresh()
        return done


def export_pdfa(window, path=None):
    v = window._view
    if not v:
        return None
    if path is None:
        base = os.path.splitext(window._path or "document")[0]
        path, _ = QFileDialog.getSaveFileName(
            window, "Export PDF/A (archival)", f"{base} (PDF-A).pdf",
            "PDF (*.pdf)")
    if not path:
        return None
    try:
        res = pdfa.export(v.doc, path)
    except Exception as e:
        QMessageBox.warning(window, "PDF/A", str(e))
        return None
    msg = (f"Saved as PDF/A-3b ({'Ghostscript' if res['method'] == 'ghostscript' else 'built in'}): "
           + "; ".join(res["done"]) + ".")
    if res["remaining"]:
        msg += ("\n\nStill to fix: " + "; ".join(res["remaining"]) +
                ("\nInstall Ghostscript to embed fonts." if res["method"]
                 != "ghostscript" else ""))
    QMessageBox.information(window, "PDF/A", msg)
    return res
