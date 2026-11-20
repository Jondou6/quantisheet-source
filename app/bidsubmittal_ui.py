"""The bid-submittal checklist shown before Export Bid Package (Nov 19)."""
import os

from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox,
                               QFileDialog, QGridLayout, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QSpinBox,
                               QVBoxLayout)

from . import bidsubmittal as bs


class SubmittalDialog(QDialog):
    """Tick what's ready, attach the files, type the bid reference number.
    `ask_anyway(text)` (tests) answers "export with items not checked?"."""

    def __init__(self, doc, parent=None, ask_anyway=None):
        super().__init__(parent)
        self.doc = doc
        self.ask_anyway = ask_anyway
        self.state = bs.read(doc)
        self.setWindowTitle("Bid Submittal Checklist")
        v = QVBoxLayout(self)
        intro = QLabel("Before the bid package is made: tick what is "
                       "ready to go in with the bid. Attached files are "
                       "copied into the package.")
        intro.setWordWrap(True)
        v.addWidget(intro)
        g = QGridLayout()
        self.boxes, self.files = {}, {}
        row = 0
        for key, label in bs.ITEMS:
            if key == "ref_no":
                continue
            cb = QCheckBox(label)
            cb.setChecked(self.state["items"][key]["done"])
            self.boxes[key] = cb
            g.addWidget(cb, row, 0)
            f = QLabel(os.path.basename(self.state["items"][key]["file"])
                       or "no file attached")
            self.files[key] = f
            g.addWidget(f, row, 1)
            b = QPushButton("Attach…")
            b.clicked.connect(lambda _=False, k=key: self.attach(k))
            g.addWidget(b, row, 2)
            row += 1
        g.addWidget(QLabel(bs.LABEL["ref_no"]), row, 0)
        self.ref = QLineEdit(self.state["ref_no"])
        self.ref.setPlaceholderText("from the invitation or solicitation")
        g.addWidget(self.ref, row, 1, 1, 2)
        row += 1
        # Nov 19: bid day and how long the bid must hold its price - the
        # Estimate Error Check warns about quotes that run out sooner
        g.addWidget(QLabel("Bid day (YYYY-MM-DD)"), row, 0)
        self.bid_date = QLineEdit(self.state["bid_date"])
        self.bid_date.setPlaceholderText("e.g. 2026-12-08")
        g.addWidget(self.bid_date, row, 1, 1, 2)
        row += 1
        g.addWidget(QLabel("Bid must hold for (days)"), row, 0)
        self.hold = QSpinBox()
        self.hold.setRange(0, 730)
        self.hold.setSpecialValueText("not set")
        self.hold.setValue(self.state["hold_days"])
        g.addWidget(self.hold, row, 1, 1, 2)
        v.addLayout(g)
        bb = QDialogButtonBox(QDialogButtonBox.Cancel)
        go = bb.addButton("Make Bid Package", QDialogButtonBox.AcceptRole)
        go.clicked.connect(self.go)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def attach(self, key, path=None):
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, bs.LABEL[key], "",
                "Documents (*.pdf *.png *.jpg *.jpeg *.docx *.xlsx);;"
                "All files (*)")
            if not path:
                return None
        self.state["items"][key]["file"] = path
        self.files[key].setText(os.path.basename(path))
        self.boxes[key].setChecked(True)
        return path

    def values(self):
        for key, cb in self.boxes.items():
            self.state["items"][key]["done"] = cb.isChecked()
        self.state["ref_no"] = self.ref.text().strip()
        self.state["bid_date"] = self.bid_date.text().strip()
        self.state["hold_days"] = self.hold.value()
        return self.state

    def go(self):
        st = bs.write(self.doc, self.values())
        gaps = bs.missing(st)
        if gaps:
            text = ("Not checked off yet:\n- " + "\n- ".join(gaps) +
                    "\n\nMake the bid package anyway? The contents list "
                    "will say what is missing.")
            ok = self.ask_anyway(text) if self.ask_anyway else \
                QMessageBox.question(self, "Bid Submittal Checklist",
                                     text) == QMessageBox.Yes
            if not ok:
                return False
        self.accept()
        return True
