"""Spec Book Sections window (Document > Spec Book Sections)."""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QDialog,
                               QDialogButtonBox, QFileDialog, QHeaderView,
                               QLabel, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from . import specs


class SpecSectionsDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.win = window
        self.view = window._view
        self.setWindowTitle("Spec Book Sections")
        self.resize(760, 560)
        v = QVBoxLayout(self)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.sections = specs.find_sections(self.view.doc)
        finally:
            QApplication.restoreOverrideCursor()
        divs = len({s["division"] for s in self.sections})
        self.head = QLabel(f"{len(self.sections)} section(s) in {divs} "
                           "division(s). Double-click to go to a section."
                           if self.sections else
                           "No CSI sections found (pages starting with "
                           "\"SECTION 03 30 00\" or similar).")
        v.addWidget(self.head)
        t = self.table = QTableWidget(len(self.sections), 4)
        t.setHorizontalHeaderLabels(["Section", "Title", "Division",
                                     "Pages"])
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        t.verticalHeader().hide()
        for r, s in enumerate(self.sections):
            for c, val in enumerate((s["number"], s["title"],
                                     f"{s['division']} {s['division_title']}",
                                     f"{s['start'] + 1}–{s['end'] + 1}")):
                it = QTableWidgetItem(val)
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                t.setItem(r, c, it)
        t.cellDoubleClicked.connect(
            lambda r, _c: self.win._go_page(self.sections[r]["start"]))
        v.addWidget(t, 1)
        self.replace = QCheckBox("Replace the existing bookmarks")
        v.addWidget(self.replace)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        self.b_mark = bb.addButton("Add Bookmarks", QDialogButtonBox.ActionRole)
        self.b_split = bb.addButton("Split Into Section Files…",
                                    QDialogButtonBox.ActionRole)
        for b in (self.b_mark, self.b_split):
            b.setEnabled(bool(self.sections))
        self.b_mark.clicked.connect(lambda: self.add_bookmarks())
        self.b_split.clicked.connect(lambda: self.split())
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def add_bookmarks(self):
        n = self.win._page_change(
            lambda: specs.bookmark(self.view.doc, self.sections,
                                   self.replace.isChecked()),
            "Bookmarked the spec sections")
        self.win.bookmarks.set_doc(self.view.doc)
        return n

    def split(self, folder=None):
        if folder is None:
            base = os.path.dirname(self.win._path or "")
            folder = QFileDialog.getExistingDirectory(
                self, "Folder for the Section Files", base)
        if not folder:
            return None
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            paths = specs.split(self.view.doc, self.sections, folder)
        finally:
            QApplication.restoreOverrideCursor()
        self.win._flash(f"Saved {len(paths)} section file(s)")
        return paths
