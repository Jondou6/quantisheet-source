"""Dialogs for the Acrobat-style tools."""
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGridLayout,
    QLabel, QLineEdit, QSpinBox, QVBoxLayout
)

from . import acrobat


class HeaderFooterDialog(QDialog):
    """Header/footer text in six positions, with page-number tokens."""

    def __init__(self, parent=None, page_numbers_only=False):
        super().__init__(parent)
        self.setWindowTitle("Page Numbers" if page_numbers_only
                            else "Header & Footer")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(
            "Use {page}, {pages}, {date} and {file} in the text. "
            "Leave a box empty to skip it."))
        grid = QGridLayout()
        self.edits = {}
        for col, h in enumerate(("Left", "Center", "Right")):
            grid.addWidget(QLabel(f"<b>{h}</b>"), 0, col + 1)
        for row, v in enumerate(("Header", "Footer"), 1):
            grid.addWidget(QLabel(f"<b>{v}</b>"), row, 0)
            for col, h in enumerate(("left", "center", "right")):
                pos = f"{'top' if v == 'Header' else 'bottom'}_{h}"
                e = QLineEdit()
                self.edits[pos] = e
                grid.addWidget(e, row, col + 1)
        lay.addLayout(grid)
        if page_numbers_only:
            self.edits["bottom_center"].setText("Page {page} of {pages}")
        form = QFormLayout()
        self.size = QSpinBox()
        self.size.setRange(5, 48)
        self.size.setValue(9)
        self.start = QSpinBox()
        self.start.setRange(0, 100000)
        self.start.setValue(1)
        self.margin = QSpinBox()
        self.margin.setRange(4, 144)
        self.margin.setValue(24)
        form.addRow("Font size", self.size)
        form.addRow("First page number", self.start)
        form.addRow("Margin (points)", self.margin)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def values(self):
        return {"texts": {p: e.text() for p, e in self.edits.items()
                          if e.text().strip()},
                "size": self.size.value(), "start": self.start.value(),
                "margin": self.margin.value()}


class ProtectDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Password Protect")
        form = QFormLayout(self)
        self.open_pw = QLineEdit()
        self.open_pw.setEchoMode(QLineEdit.Password)
        self.open_pw2 = QLineEdit()
        self.open_pw2.setEchoMode(QLineEdit.Password)
        self.owner_pw = QLineEdit()
        self.owner_pw.setEchoMode(QLineEdit.Password)
        self.print_ = QCheckBox("Allow printing")
        self.print_.setChecked(True)
        self.copy = QCheckBox("Allow copying text and images")
        self.copy.setChecked(True)
        self.edit = QCheckBox("Allow editing and comments")
        self.edit.setChecked(False)
        self.msg = QLabel("")
        form.addRow("Password to open", self.open_pw)
        form.addRow("Confirm", self.open_pw2)
        # L3: without its own password, anyone who can open the file
        # can also change the permissions
        self.owner_pw.setToolTip(
            "Optional. Without a separate permissions password, anyone "
            "with the open password can lift the print / copy / edit "
            "limits.")
        form.addRow("Permissions password", self.owner_pw)
        form.addRow(self.print_)
        form.addRow(self.copy)
        form.addRow(self.edit)
        form.addRow(QLabel("<small>Saved as a new AES-256 encrypted copy. "
                           "Keep the passwords safe: they can't be "
                           "recovered.</small>"))
        form.addRow(self.msg)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _ok(self):
        if self.open_pw.text() != self.open_pw2.text():
            self.msg.setText("<font color=red>The passwords don't match."
                             "</font>")
            return
        if not self.open_pw.text() and not self.owner_pw.text():
            self.msg.setText("<font color=red>Enter at least one password."
                             "</font>")
            return
        self.accept()

    def values(self):
        return {"open_password": self.open_pw.text(),
                "owner_password": self.owner_pw.text(),
                "allow_print": self.print_.isChecked(),
                "allow_copy": self.copy.isChecked(),
                "allow_edit": self.edit.isChecked()}


class RedactDialog(QDialog):
    """Find words or patterns to redact everywhere in the document."""

    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.hits = []
        self.setWindowTitle("Search & Redact")
        form = QFormLayout(self)
        self.kind = QComboBox()
        self.kind.addItems(["Words or phrases"] + list(acrobat.PATTERNS) +
                           ["Regular expression"])
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self.text = QLineEdit()
        self.text.setPlaceholderText("Text to find")
        self.text.textChanged.connect(self._search)
        self.whole = QCheckBox("Whole words only")
        self.whole.toggled.connect(self._search)
        self.case = QCheckBox("Match case")
        self.case.toggled.connect(self._search)
        self.result = QLabel("")
        self.result.setWordWrap(True)        # was cut off (Chief, Nov 7)
        form.addRow("Find", self.kind)
        form.addRow("Text", self.text)
        form.addRow(self.whole)
        form.addRow(self.case)
        form.addRow(self.result)
        self.note = QLabel("<small>Redaction permanently removes the text "
                           "and anything under it. You can undo until you "
                           "save.</small>")
        self.note.setWordWrap(True)
        form.addRow(self.note)
        self.setMinimumWidth(460)
        bb = QDialogButtonBox()
        self.go = bb.addButton("Redact All", QDialogButtonBox.AcceptRole)
        bb.addButton(QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)
        self.go.setEnabled(False)

    def _query(self):
        i = self.kind.currentIndex()
        if i == 0:
            return dict(text=self.text.text(),
                        whole_word=self.whole.isChecked(),
                        case=self.case.isChecked())
        if i <= len(acrobat.PATTERNS):
            return dict(pattern=list(acrobat.PATTERNS.values())[i - 1],
                        case=self.case.isChecked())
        return dict(pattern=self.text.text() or None,
                    case=self.case.isChecked())

    def _search_later(self):
        """Big set: wait until typing pauses, then search a copy of the
        document on a worker thread; only the newest search is shown."""
        from PySide6.QtCore import QTimer
        if not hasattr(self, "_timer"):
            self._timer = QTimer(self)
            self._timer.setSingleShot(True)
            self._timer.timeout.connect(self._search_now)
            self._seq = 0
        self.go.setEnabled(False)
        self.result.setText("Searching...")
        self._timer.start(600)

    def _search_now(self):
        import fitz
        from . import bg
        if not hasattr(self, "_data"):
            self._data = self.doc.tobytes()
        self._seq += 1
        seq, q, data = self._seq, self._query(), self._data

        def work():
            d = fitz.open("pdf", data)
            try:
                return acrobat.find_for_redaction(d, **q)
            finally:
                d.close()

        def done(hits):
            if seq != self._seq:
                return                      # a newer search is running
            self.hits = hits
            pages = len({p for p, _ in hits})
            self.result.setText(f"<b>{len(hits)}</b> matches on {pages} "
                                "page(s)" if hits else "No matches")
            self.go.setEnabled(bool(hits))

        def failed(msg):
            if seq == self._seq:
                self.hits = []
                self.result.setText(f"<font color=red>{msg}</font>")
        bg.run(work, done, failed, self)

    def _kind_changed(self, i):
        preset = 0 < i <= len(acrobat.PATTERNS)
        self.text.setEnabled(not preset)
        self.whole.setEnabled(i == 0)
        self._search()

    BIG = 60          # pages: above this, search after a pause, off-thread

    def _search(self, *_):
        if self.doc.page_count > self.BIG:
            return self._search_later()
        i = self.kind.currentIndex()
        try:
            if i == 0:
                self.hits = acrobat.find_for_redaction(
                    self.doc, text=self.text.text(),
                    whole_word=self.whole.isChecked(),
                    case=self.case.isChecked())
            elif i <= len(acrobat.PATTERNS):
                pat = list(acrobat.PATTERNS.values())[i - 1]
                self.hits = acrobat.find_for_redaction(
                    self.doc, pattern=pat, case=self.case.isChecked())
            else:
                self.hits = acrobat.find_for_redaction(
                    self.doc, pattern=self.text.text() or None,
                    case=self.case.isChecked())
        except Exception as e:                  # bad regular expression
            self.hits = []
            self.result.setText(f"<font color=red>{e}</font>")
            self.go.setEnabled(False)
            return
        pages = len({p for p, _ in self.hits})
        self.result.setText(f"<b>{len(self.hits)}</b> matches on {pages} "
                            "page(s)" if self.hits else "No matches")
        self.go.setEnabled(bool(self.hits))

    def marks(self):
        return [(p, "add_redact", {"rect": list(r)}) for p, r in self.hits]
