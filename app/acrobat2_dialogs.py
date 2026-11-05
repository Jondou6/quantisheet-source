"""Dialogs for Create PDF, properties and the Action Wizard."""
import os

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QProgressDialog,
    QPushButton, QVBoxLayout, QApplication, QDoubleSpinBox
)

from . import acrobat2


class PropertiesDialog(QDialog):
    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Document Properties")
        form = QFormLayout(self)
        meta = doc.metadata or {}
        self.edits = {}
        for k in acrobat2.PROPERTY_KEYS:
            e = QLineEdit(meta.get(k) or "")
            self.edits[k] = e
            form.addRow(k.title(), e)
        info = (f"Pages: {doc.page_count}    Size of page 1: "
                f"{doc[0].rect.width / 72:.2f} × {doc[0].rect.height / 72:.2f}"
                f" in    Encrypted: {'yes' if meta.get('encryption') else 'no'}"
                f"    Format: {meta.get('format', '')}")
        form.addRow(QLabel(f"<small>{info}</small>"))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def values(self):
        return {k: e.text() for k, e in self.edits.items()}


class BatchDialog(QDialog):
    """Action Wizard: run several actions over many files."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Action Wizard — Batch Process Files")
        self.resize(560, 520)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("<b>1. Files</b> (PDFs, Office files, images)"))
        self.files = QListWidget()
        lay.addWidget(self.files)
        row = QHBoxLayout()
        add = QPushButton("Add Files…")
        add.clicked.connect(self._add_files)
        folder = QPushButton("Add Folder…")
        folder.clicked.connect(self._add_folder)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.files.clear)
        for b in (add, folder, clear):
            row.addWidget(b)
        lay.addLayout(row)
        lay.addWidget(QLabel("<b>2. Actions</b> (run in this order)"))
        self.checks = {}
        for key, label in acrobat2.BATCH_ACTIONS:
            c = QCheckBox(label)
            self.checks[key] = c
            lay.addWidget(c)
        form = QFormLayout()
        self.watermark = QLineEdit("DRAFT")
        self.page_format = QLineEdit("Page {page} of {pages}")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        form.addRow("Watermark text", self.watermark)
        form.addRow("Page number format", self.page_format)
        form.addRow("Password", self.password)
        lay.addLayout(form)
        lay.addWidget(QLabel("<b>3. Save results to</b>"))
        row2 = QHBoxLayout()
        self.out = QLineEdit()
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._out_dir)
        row2.addWidget(self.out, 1)
        row2.addWidget(browse)
        lay.addLayout(row2)
        bb = QDialogButtonBox()
        self.run_btn = bb.addButton("Run", QDialogButtonBox.AcceptRole)
        bb.addButton(QDialogButtonBox.Cancel)
        bb.accepted.connect(self._check)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.msg = QLabel("")
        lay.addWidget(self.msg)

    def _add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Add Files", "",
                                                acrobat2.CREATE_FILTER)
        self.add_paths(paths)

    def _add_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Add Folder")
        if d:
            self.add_paths(sorted(
                os.path.join(d, f) for f in os.listdir(d)
                if f.lower().endswith(".pdf")))
            if not self.out.text():
                self.out.setText(os.path.join(d, "processed"))

    def add_paths(self, paths):
        have = {self.files.item(i).text() for i in range(self.files.count())}
        for p in paths:
            if p not in have:
                self.files.addItem(p)

    def _out_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Save Results To")
        if d:
            self.out.setText(d)

    def _check(self):
        if not self.files.count():
            self.msg.setText("<font color=red>Add some files.</font>")
        elif not any(c.isChecked() for c in self.checks.values()):
            self.msg.setText("<font color=red>Pick at least one action.</font>")
        elif not self.out.text().strip():
            self.msg.setText("<font color=red>Choose where to save results."
                             "</font>")
        elif self.checks["protect"].isChecked() and not self.password.text():
            self.msg.setText("<font color=red>Enter a password.</font>")
        else:
            self.accept()

    def job(self):
        return ([self.files.item(i).text() for i in range(self.files.count())],
                [k for k, c in self.checks.items() if c.isChecked()],
                self.out.text().strip(),
                {"watermark": self.watermark.text(),
                 "page_format": self.page_format.text(),
                 "password": self.password.text()})


def run_with_progress(parent, paths, actions, out_dir, options):
    prog = QProgressDialog("Processing…", "Stop", 0, len(paths), parent)
    prog.setWindowTitle("Action Wizard")
    prog.setMinimumDuration(0)

    def step(n, total, src):
        prog.setValue(n)
        prog.setLabelText(f"{n + 1} of {total}: {os.path.basename(src)}")
        QApplication.processEvents()
        return not prog.wasCanceled()

    try:
        return acrobat2.run_batch(paths, actions, out_dir, options, step)
    finally:
        prog.close()
