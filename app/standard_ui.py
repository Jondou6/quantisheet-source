"""Takeoff > Takeoff Standard: the office's takeoff workflow as a
checklist for this drawing (app/standard.py)."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout,
                               QInputDialog, QLabel, QPushButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from . import standard


class StandardDialog(QDialog):
    """Each step with a tick: done ones the drawing shows are ticked for
    you; tick the others when they're done. Ticks are saved in the PDF."""

    def __init__(self, doc, parent=None, changed=None):
        super().__init__(parent)
        self.doc = doc
        self.changed = changed or (lambda: None)
        self.setWindowTitle("Takeoff Standard")
        self.resize(640, 440)
        lay = QVBoxLayout(self)
        intro = QLabel("The office's takeoff workflow, step by step. Steps "
                       "the drawing shows are ticked for you; tick the "
                       "others as they're done.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Step", "What the drawing shows"])
        self.tree.setColumnWidth(0, 300)
        self.tree.itemChanged.connect(self._ticked)
        lay.addWidget(self.tree)
        row = QHBoxLayout()
        edit = QPushButton("Your Office's Steps…")
        edit.setToolTip("Add your own steps, offered on every job")
        edit.clicked.connect(lambda: self.edit_steps())
        row.addWidget(edit)
        row.addStretch(1)
        self.summary = QLabel("")
        row.addWidget(self.summary)
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.fill()

    def fill(self):
        self._loading = True
        self.tree.clear()
        rows = standard.status(self.doc)
        for i, r in enumerate(rows, 1):
            it = QTreeWidgetItem([f"{i}. {r['title']}", r["note"]])
            it.setToolTip(0, r["what"])
            it.setToolTip(1, r["what"])
            it.setData(0, Qt.UserRole, r["key"])
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(0, Qt.Checked if r["done"] else Qt.Unchecked)
            self.tree.addTopLevelItem(it)
        done = sum(1 for r in rows if r["done"])
        self.summary.setText(f"{done} of {len(rows)} done")
        self._loading = False

    def _ticked(self, item, col):
        if self._loading or col != 0:
            return
        key = item.data(0, Qt.UserRole)
        standard.tick(self.doc, key, item.checkState(0) == Qt.Checked)
        self.changed()
        self.fill()

    def edit_steps(self, text=None):
        if text is None:
            cur = "\n".join(f"{t}: {w}" if w else t
                            for _k, t, w in standard.own_steps())
            text, ok = QInputDialog.getMultiLineText(
                self, "Your Office's Steps", "One step per line, as "
                "Title: what it means (e.g. Waste: add 10% to flooring):",
                cur)
            if not ok:
                return False
        standard.set_own_steps(text.splitlines())
        self.fill()
        return True
