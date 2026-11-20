"""Estimate > Find Bid Terms (Nov 19)."""
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHeaderView, QLabel,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from . import bidsubmittal as bs, bidterms


class BidTermsDialog(QDialog):
    """What the bid documents say about bond, hold time, wages, damages,
    pre-bid, goals, retainage, contract time and alternates - each with
    its page (double-click to go there)."""

    def __init__(self, win, found=None):
        super().__init__(win)
        self.win = win
        self.doc = win._view.doc
        self.found = bidterms.find(self.doc) if found is None else found
        self.setWindowTitle("Bid Terms")
        self.resize(820, 420)
        v = QVBoxLayout(self)
        intro = QLabel(
            "Read from this document's text by pattern - check each one "
            "on its page (double-click a row). Nothing is sent anywhere."
            if self.found else
            "No bid terms were found in this document's text. Open the "
            "specifications or instructions to bidders (scanned pages need "
            "Make Searchable first).")
        intro.setWordWrap(True)
        v.addWidget(intro)
        t = self.table = QTableWidget(len(self.found), 4)
        t.setHorizontalHeaderLabels(["Term", "Found", "Page", "Where"])
        for r, f in enumerate(self.found):
            for c, val in enumerate((f["label"], f["value"],
                                     str(f["page"] + 1), f["text"])):
                t.setItem(r, c, QTableWidgetItem(val))
        t.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        t.cellDoubleClicked.connect(lambda r, _c: self.go(r))
        v.addWidget(t)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        self.use_btn = bb.addButton("Put Hold Days in the Bid Checklist",
                                    QDialogButtonBox.ActionRole)
        self.use_btn.setEnabled(bidterms.hold_days(self.found) is not None)
        self.use_btn.clicked.connect(lambda: self.use_hold())
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def go(self, row):
        self.win._go_page(self.found[row]["page"])

    def use_hold(self):
        """The hold days into the Bid Submittal Checklist (Estimate Error
        Check then warns about quotes that run out sooner)."""
        n = bidterms.hold_days(self.found)
        if n is None:
            return None
        st = bs.read(self.doc)
        st["hold_days"] = n
        bs.write(self.doc, st)
        self.win._doc_edited()
        self.use_btn.setText(f"Bid Checklist: holds {n} days")
        return n
