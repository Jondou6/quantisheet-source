"""New sheets or addenda in the watched plan folder (Nov 19)."""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from . import planwatch

HINT = {"Addenda": "log in the Addenda Gate, then compare",
        "Drawings": "compare with this set, then Slip Sheet",
        "Specs": "open to read",
        "Other": "open to look"}


class NewPlansDialog(QDialog):
    def __init__(self, win, doc, items):
        super().__init__(win)
        self.win, self.doc, self.items = win, doc, list(items)
        self.done_rels = set()
        self.setWindowTitle("New in the Plan Folder")
        self.resize(760, 360)
        v = QVBoxLayout(self)
        folder = planwatch.folder_of(doc)
        lab = QLabel(f"{len(self.items)} new or changed PDF(s) in "
                     f"{os.path.basename(folder) or folder}. Tick the ones "
                     "to act on.")
        lab.setWordWrap(True)
        v.addWidget(lab)
        t = QTableWidget(len(self.items), 3)
        t.setHorizontalHeaderLabels(["File", "Looks like", "Next step"])
        for i, it in enumerate(self.items):
            a = QTableWidgetItem(it["rel"])
            a.setFlags(a.flags() | Qt.ItemIsUserCheckable)
            a.setCheckState(Qt.Checked)
            t.setItem(i, 0, a)
            t.setItem(i, 1, QTableWidgetItem(it["kind"]))
            t.setItem(i, 2, QTableWidgetItem(HINT.get(it["kind"], "")))
        t.resizeColumnsToContents()
        t.horizontalHeader().setStretchLastSection(True)
        self.table = t
        v.addWidget(t, 1)
        self.status = QLabel("")
        v.addWidget(self.status)
        bb = QDialogButtonBox()
        b = bb.addButton("Log Addenda", QDialogButtonBox.ActionRole)
        b.setToolTip("Each ticked addendum goes in the Addenda Gate, not "
                     "priced: the bid form and proposal wait until it is")
        b.clicked.connect(lambda: self.log_addenda())
        b = bb.addButton("Compare With This Set", QDialogButtonBox.ActionRole)
        b.setToolTip("Compare Revisions with the first ticked file; from "
                     "there Slip Sheet brings it under this set's takeoff")
        b.clicked.connect(lambda: self.compare())
        b = bb.addButton("Open", QDialogButtonBox.ActionRole)
        b.clicked.connect(lambda: self.open_files())
        b = bb.addButton("Mark as Seen", QDialogButtonBox.ActionRole)
        b.clicked.connect(lambda: self.mark_seen())
        bb.addButton("Later", QDialogButtonBox.RejectRole)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def ticked(self):
        return [it for i, it in enumerate(self.items)
                if self.table.item(i, 0).checkState() == Qt.Checked]

    def _seen(self, items):
        planwatch.mark_seen(self.doc, items)
        self.done_rels |= {it["rel"] for it in items}
        self.win._doc_edited()

    def log_addenda(self):
        adds = [it for it in self.ticked() if it["kind"] == "Addenda"]
        if not adds:
            self.status.setText("None of the ticked files looks like an "
                                "addendum.")
            return []
        ids = planwatch.log_addenda(self.doc, adds)
        self._seen(adds)
        self.status.setText(f"{len(ids)} addendum(s) logged in the Addenda "
                            "Gate - price each (even at $0) before the bid "
                            "goes out.")
        return ids

    def compare(self):
        pick = self.ticked()
        if not pick:
            self.status.setText("Tick a file to compare.")
            return None
        it = pick[0]
        dlg = self.win.compare_revisions(it["path"])
        self._seen([it])
        self.status.setText(f"Comparing {it['rel']} with this set.")
        return dlg

    def open_files(self):
        pick = self.ticked()
        for it in pick:
            self.win.open_path(it["path"])
        self._seen(pick)
        return len(pick)

    def mark_seen(self):
        pick = self.ticked()
        self._seen(pick)
        self.status.setText(f"{len(pick)} file(s) marked as seen.")
        return len(pick)
