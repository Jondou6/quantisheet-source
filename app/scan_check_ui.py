"""Check Scan Quality window (Document menu). open_dialog(win)."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox,
                               QLabel, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from . import scan_check


class ScanQualityDialog(QDialog):
    def __init__(self, doc, parent=None, languages=None, on_page=None):
        super().__init__(parent)
        self.setWindowTitle("Check Scan Quality")
        self.resize(760, 460)
        self.on_page = on_page
        lay = QVBoxLayout(self)
        self.result = scan_check.check(doc, languages=languages)
        self.head = QLabel("\n".join(scan_check.summary(self.result)))
        self.head.setWordWrap(True)
        lay.addWidget(self.head)
        rows = [r for r in self.result["pages"] if r["scan"]]
        self.table = QTableWidget(len(rows), 4)
        self.table.setAccessibleName("Scanned pages")
        self.table.setHorizontalHeaderLabels(["Page", "DPI", "Tilt",
                                              "What to fix"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        for i, r in enumerate(rows):
            vals = [str(r["page"]), "" if r["dpi"] is None else f"{r['dpi']:g}",
                    "" if r["skew"] is None else f"{r['skew']:.1f}°",
                    " ".join(r["reasons"]) or "OK"]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c == 0:
                    it.setData(Qt.UserRole, r["page"] - 1)
                self.table.setItem(i, c, it)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.resizeColumnsToContents()
        self.table.cellDoubleClicked.connect(self.go)
        self.table.setVisible(bool(rows))
        lay.addWidget(self.table, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.close)
        lay.addWidget(bb)

    def go(self, row, _col=0):
        it = self.table.item(row, 0)
        if it is not None and self.on_page is not None:
            self.on_page(it.data(Qt.UserRole))


def open_dialog(win, show=True, languages=None):
    v = getattr(win, "_view", None)
    if v is None:
        return None
    go = getattr(v, "go_to", None)
    dlg = ScanQualityDialog(v.doc, win, languages=languages, on_page=go)
    win._scan_quality = dlg
    if show:
        dlg.show()
    return dlg
