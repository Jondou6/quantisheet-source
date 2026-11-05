"""The Booklet / N-up dialog (Pages menu). The layout itself is in
app/booklet.py."""
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QLabel, QVBoxLayout)

from . import booklet


class BookletDialog(QDialog):
    def __init__(self, parent=None, page_count=0):
        super().__init__(parent)
        self.setWindowTitle("Booklet / N-up")
        lay = QVBoxLayout(self)
        intro = QLabel("Lay the pages out for printing in a new PDF. The "
                       "open document isn't changed.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        form = QFormLayout()
        self.mode = QComboBox()
        for key in booklet.MODES:
            self.mode.addItem(booklet.MODE_NAMES[key], key)
        form.addRow("Layout:", self.mode)
        self.paper = QComboBox()
        for key in booklet.PAPER:
            self.paper.addItem(booklet.PAPER_NAMES[key], key)
        form.addRow("Sheet size:", self.paper)
        self.gutter = QDoubleSpinBox()
        self.gutter.setRange(0, 144)
        self.gutter.setSuffix(" pt")
        self.gutter.setToolTip("Space between the pages on a sheet "
                               "(72 pt = 1 inch).")
        form.addRow("Gutter:", self.gutter)
        self.creep = QDoubleSpinBox()
        self.creep.setRange(0, 10)
        self.creep.setDecimals(2)
        self.creep.setSuffix(" pt per sheet")
        self.creep.setToolTip("Booklets of thick paper: pull the outer edge "
                              "of inner pages in by this much per sheet, so "
                              "nothing is trimmed off. 0 for most jobs.")
        form.addRow("Creep:", self.creep)
        self.flip = QCheckBox("Turn the back of each sheet upside down "
                              "(printer flips on the short edge)")
        form.addRow("", self.flip)
        self.markups = QCheckBox("Include markups")
        self.markups.setChecked(True)
        form.addRow("", self.markups)
        lay.addLayout(form)
        self.note = QLabel()
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        self._n = page_count
        self.mode.currentIndexChanged.connect(
            lambda _i=0: self._update())
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._update()

    def _update(self):
        mode = self.mode.currentData()
        booklet_mode = mode == "booklet"
        self.creep.setEnabled(booklet_mode)
        self.gutter.setValue(0 if booklet_mode else 12)
        n = self._n
        if not n:
            self.note.setText("")
        elif booklet_mode:
            m = booklet.padded(n)
            extra = f" ({m - n} blank page(s) added at the end)" \
                if m > n else ""
            self.note.setText(f"{n} page(s) → {m // 4} sheet(s), printed on "
                              f"both sides{extra}.")
        else:
            per = 2 if mode == "2up" else 4
            self.note.setText(f"{n} page(s) → {-(-n // per)} sheet side(s).")

    def values(self):
        return {"mode": self.mode.currentData(),
                "paper": self.paper.currentData(),
                "gutter": self.gutter.value(),
                "creep": self.creep.value() if self.creep.isEnabled() else 0,
                "flip_back": self.flip.isChecked(),
                "markups": self.markups.isChecked()}
