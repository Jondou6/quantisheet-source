"""Review > Spec Book Risk Scanner: the window (logic: specrisk.py)."""
import os
import tempfile

import fitz
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox,
                               QFileDialog, QHeaderView, QLabel, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from . import specrisk


class SpecRiskDialog(QDialog):
    def __init__(self, parent=None, doc=None, open_result=None, title="",
                 src_path=None):
        super().__init__(parent)
        self.open_result = open_result
        self.title = title
        self.src_path = src_path
        self.review_path = None
        self.review_items = []
        self.setWindowTitle("Spec Book Risk Scanner")
        self.resize(900, 520)
        lay = QVBoxLayout(self)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Risk", "Term", "Section",
                                              "Page", "Words"])
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        lay.addWidget(self.table, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        o = bb.addButton("Scan Another Spec Book…", QDialogButtonBox.ActionRole)
        o.clicked.connect(lambda: self.pick())
        sv = bb.addButton("Summary PDF", QDialogButtonBox.ActionRole)
        sv.clicked.connect(lambda: self.summary())
        rv = bb.addButton("Open Bid Form && Insurance Review",
                          QDialogButtonBox.ActionRole)
        rv.clicked.connect(lambda: self.open_review())
        br = bb.addButton("Builder's Risk Quote Request…",
                          QDialogButtonBox.ActionRole)
        br.clicked.connect(lambda: self.builders_risk())
        bf = bb.addButton("Bid Form Workbook…", QDialogButtonBox.ActionRole)
        bf.clicked.connect(lambda: self.bid_form())
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.found = []
        if doc is not None:
            self.load(doc)
        else:
            self.note.setText("Pick a spec book (project manual) to scan.")

    def pick(self, path=None):
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "Spec Book", "",
                                                  "PDF (*.pdf)")
            if not path:
                return None
        self.title = os.path.splitext(os.path.basename(path))[0]
        self.src_path = path
        return self.load(fitz.open(path))

    def load(self, doc):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.found = specrisk.scan(doc)
        finally:
            QApplication.restoreOverrideCursor()
        self.table.setRowCount(len(self.found))
        for i, r in enumerate(self.found):
            for c, v in enumerate((r["label"], r["value"], r["section"],
                                   str(r["page"] + 1), r["quote"])):
                self.table.setItem(i, c, QTableWidgetItem(v))
        note = (
            f"{len(self.found)} costly term(s) found in {doc.page_count} "
            "page(s). Check each in the book - this reads the words, it "
            "doesn't judge them." if self.found else
            "No bonds, liquidated damages, prevailing wage, insurance limits, "
            "long warranties or contractor-paid testing found.")
        try:                 # Nov 4: the review PDF, made every scan
            self.make_review(doc)
            got = [i for i in self.review_items if not i.get("missing")]
            miss = [i["label"] for i in self.review_items if i.get("missing")]
            note += (f"<br>Bid Form & Insurance Review: {len(got)} part(s) "
                     f"pulled out, saved as "
                     f"<b>{os.path.basename(self.review_path)}</b>")
            if miss:
                note += " - not found: " + ", ".join(miss)
        except Exception as e:                            # noqa: BLE001
            note += f"<br>The review PDF couldn't be made ({e})."
        self.note.setText(note)
        return self.found

    def review_name(self):
        return f"{self.title or 'Spec Book'} - Bid Form & Insurance " \
               "Review.pdf"

    def make_review(self, doc, path=None):
        """Insurance and builder's risk pages in their own PDF: beside the
        spec book when it has a folder that can be written, else a temp
        folder."""
        if path is None:
            folder = os.path.dirname(self.src_path) if self.src_path else ""
            if not folder or not os.access(folder, os.W_OK):
                folder = tempfile.mkdtemp(prefix="qs_review_")
            path = os.path.join(folder, self.review_name())
        self.review_items = specrisk.review_for(doc, path, self.title)
        self.review_path = path
        return path

    def builders_risk(self):
        """The quote request with this spec book's builder's risk pages."""
        w = self.parent()
        if w is None or not hasattr(w, "builders_risk"):
            return None
        doc = fitz.open(self.src_path) if self.src_path else None
        return w.builders_risk(doc, self.review_items)

    def bid_form(self):
        w = self.parent()
        if w is None or not hasattr(w, "bid_form_workbook"):
            return None
        return w.bid_form_workbook(self.src_path)

    def open_review(self):
        if self.review_path and self.open_result:
            self.open_result(self.review_path)
        return self.review_path

    def summary(self, path=None):
        path = path or os.path.join(tempfile.mkdtemp(prefix="qs_risk_"),
                                    "Spec Risk Summary.pdf")
        specrisk.summary_pdf(self.found, path, self.title)
        if self.open_result:
            self.open_result(path)
        return path
