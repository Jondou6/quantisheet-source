"""Billing > Change Order From Revision: the window (logic: co_delta.py)."""
import os
import tempfile

import fitz
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton)

from . import co_delta
from .dmoney import c2 as _c2


class CODialog(QDialog):
    def __init__(self, view, parent=None, open_result=None):
        super().__init__(parent)
        self.view = view
        self.open_result = open_result
        self.old = None
        self.setWindowTitle("Change Order From Revision")
        f = QFormLayout(self)
        f.addRow(QLabel(f"Revised sheet: <b>page {view.page + 1}</b> of the "
                        "open drawing (go to another page to change it)."))
        row = QHBoxLayout()
        self.old_path = QLineEdit()
        self.old_path.setPlaceholderText("The earlier revision (PDF with "
                                         "takeoff)")
        b = QPushButton("Browse…")
        b.clicked.connect(lambda: self.pick())
        row.addWidget(self.old_path, 1)
        row.addWidget(b)
        f.addRow("Earlier set:", row)
        self.old_page = QComboBox()
        f.addRow("Sheet it replaces:", self.old_page)
        self.markup = QDoubleSpinBox()
        self.markup.setRange(0, 100)
        self.markup.setSuffix(" %")
        self.markup.setValue(10)
        f.addRow("Markup:", self.markup)
        self.result = QLabel("")
        self.result.setWordWrap(True)
        f.addRow(self.result)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        go = bb.addButton("Make Change Order", QDialogButtonBox.ActionRole)
        go.clicked.connect(lambda: self.make())
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def pick(self, path=None):
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "Earlier Revision",
                                                  "", "PDF (*.pdf)")
            if not path:
                return None
        self.old_path.setText(path)
        self.old = fitz.open(path)
        self.old_page.clear()
        self.old_page.addItems([f"Page {i + 1}" for i in
                                range(self.old.page_count)])
        self.old_page.setCurrentIndex(min(self.view.page,
                                          self.old.page_count - 1))
        return self.old

    def make(self, out=None):
        if self.old is None:
            QMessageBox.information(self, self.windowTitle(),
                                    "Pick the earlier revision first.")
            return None
        v = self.view
        res = co_delta.delta(self.old, self.old_page.currentIndex(), v.doc,
                             v.page, self.markup.value())
        if not res["lines"]:
            self.result.setText("No takeoff changed between the two "
                                "sheets.")
            return res
        out = out or os.path.join(tempfile.mkdtemp(prefix="qs_co_"),
                                  "Change Order Proposal.pdf")
        co_delta.make_pdf(v.doc, v.page, res, out, sheet=f"page {v.page + 1}")
        self.result.setText(f"{len(res['lines'])} item(s) changed, total "
                            f"<b>${_c2(res['total']):,.2f}</b>" +
                            (f"; not priced: {', '.join(res['unpriced'])}"
                             if res["unpriced"] else ""))
        if self.open_result:
            self.open_result(out)
        res["path"] = out
        return res
