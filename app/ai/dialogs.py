from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView
)
from PySide6.QtCore import Qt
from . import review
from .. import bg


def _wrap_columns(table, stretch, fixed=None):
    """Long text wraps and rows grow to fit; `stretch` takes the spare
    width, `fixed` {column: width} start at that width (drag to change),
    the rest fit their contents."""
    h = table.horizontalHeader()
    h.setSectionResizeMode(QHeaderView.ResizeToContents)
    h.setSectionResizeMode(stretch, QHeaderView.Stretch)
    for c, w in (fixed or {}).items():
        h.setSectionResizeMode(c, QHeaderView.Interactive)
        table.setColumnWidth(c, w)
    table.setWordWrap(True)
    table.verticalHeader().setVisible(False)
    h.sectionResized.connect(lambda *_: table.resizeRowsToContents())


class _AIDialog(QDialog):
    """Shared plumbing: run the model in the background, show progress."""

    def _start(self, fn, on_done):
        self.gen.setEnabled(False)
        self.apply_btn.setEnabled(False)
        self.status.setText("Asking the model… this can take a minute.")
        bg.run(fn, lambda result: self._finish(on_done, result),
               self._failed, self)

    def _run(self, fn):
        text, info = review.doc_text_info(self.doc)  # read on this thread
        self.coverage = review.coverage_note(info)
        self._start(lambda: fn(text), self._show)
        self.status.setText("Asking the model… this can take a minute.\n"
                            + self.coverage)

    def _finish(self, on_done, result):
        self.gen.setEnabled(True)
        on_done(result)
        cov = getattr(self, "coverage", "")
        if cov and cov not in self.status.text():
            self.status.setText(self.status.text() + "\n" + cov)
        self.apply_btn.setEnabled(self.table.rowCount() > 0)

    def _failed(self, msg):
        self.gen.setEnabled(True)
        self.status.setText(f"Error: {msg}")

    def _buttons(self, layout):
        self.status = QLabel("")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        btns = QHBoxLayout()
        self.gen = QPushButton("Generate")
        self.apply_btn = QPushButton("Apply")
        self.apply_btn.setEnabled(False)
        self.apply_btn.clicked.connect(self.accept)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        btns.addWidget(self.gen)
        btns.addStretch()
        btns.addWidget(self.apply_btn)
        btns.addWidget(cancel)
        layout.addLayout(btns)


class RedlineDialog(_AIDialog):
    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle("AI Redline")
        self.resize(1000, 560)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Proposed edits (check the ones to mark up):"))

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["", "Old", "New", "Reason"])
        _wrap_columns(self.table, stretch=3, fixed={1: 220, 2: 220})
        layout.addWidget(self.table)
        self._buttons(layout)
        self.gen.clicked.connect(
            lambda: self._run(review.redline_from_text))

    def _show(self, edits):
        self.table.setRowCount(0)
        for e in edits:
            row = self.table.rowCount()
            self.table.insertRow(row)
            chk = QTableWidgetItem()
            # edits that may change scope (NOT, BY OTHERS...) start unticked
            chk.setCheckState(Qt.Unchecked if review.risky(e) else Qt.Checked)
            if review.risky(e):
                chk.setToolTip("May change scope or meaning - check it "
                               "before applying")
            self.table.setItem(row, 0, chk)
            for col, key in ((1, "old"), (2, "new"), (3, "reason")):
                self.table.setItem(row, col, QTableWidgetItem(str(e.get(key, ""))))
        self.table.resizeRowsToContents()
        self.status.setText(f"{len(edits)} proposals." if edits else
                            "The model had no suggestions.")

    def selected_edits(self):
        out = []
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).checkState() == Qt.Checked:
                out.append({
                    "old": self.table.item(row, 1).text(),
                    "new": self.table.item(row, 2).text(),
                    "reason": self.table.item(row, 3).text()})
        return out


class SpecCheckDialog(_AIDialog):
    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.findings = []
        self.setWindowTitle("AI Spec-Check")
        self.resize(900, 560)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Findings (Apply adds them as sticky notes):"))

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Finding", "Page"])
        _wrap_columns(self.table, stretch=0)
        layout.addWidget(self.table)
        self._buttons(layout)
        self.gen.clicked.connect(
            lambda: self._run(review.spec_from_text))

    def _show(self, findings):
        self.findings = findings
        self.table.setRowCount(0)
        for f in findings:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(f.get("finding", ""))))
            page = f.get("page", f.get("page_hint", ""))
            self.table.setItem(row, 1, QTableWidgetItem(str(page)))
        self.table.resizeRowsToContents()
        self.status.setText(f"{len(findings)} findings." if findings else
                            "The model found nothing to report.")
