"""Fill From the Job and Sign: the review window (see fillsign.py).
Every value is shown with where it comes from before anything is
written; the signature goes on only when Sign is pressed for a box."""
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from . import fillsign as F, settings

BG = {F.READY: "#cdf0cd", F.UNSURE: "#fff1bd", F.NEVER: "#ffcdcd",
      F.SIGN: "#c8e6ff", F.BLANK: "#eeeeee", F.HAS: "#eeeeee"}
C_TICK, C_FIELD, C_VALUE, C_SRC, C_STATUS, C_PAGE = range(6)
OURS = "Our company"


class FillSignDialog(QDialog):
    """`path`: the form (a saved PDF). `job_doc`: the job's drawing for
    its billing info, or None. `on_open(path)`: show a file made here."""

    def __init__(self, path, parent=None, job_doc=None, contacts=None,
                 on_open=None):
        super().__init__(parent)
        self.src = self.path = path
        self.job_doc, self.on_open = job_doc, on_open
        self.contacts = list(contacts or [])
        self.rows, self.filled, self.signed = [], None, []
        self.setWindowTitle("Fill From the Job and Sign - " +
                            os.path.basename(path))
        self.resize(1080, 620)
        v = QVBoxLayout(self)
        v.addWidget(QLabel(
            "Each field below shows the value it would get and <b>where "
            "that value comes from</b>. Nothing is written until you press "
            "Fill Ticked, and it goes into a new file - your form is not "
            "changed. Nothing is sent. The signature goes on only when you "
            "press Sign for a box."))
        top = QHBoxLayout()
        top.addWidget(QLabel("The company on this form is"))
        self.who = QComboBox()
        self.who.addItem(OURS)
        for c in self.contacts:
            if c.get("company"):
                self.who.addItem(c["company"])
        self.who.setToolTip("Our company, or a subcontractor from the "
                            "Company Directory when the form is theirs")
        self.who.currentIndexChanged.connect(lambda _i: self.propose())
        top.addWidget(self.who)
        top.addWidget(QLabel("Signer"))
        self.signer = QLineEdit(settings.get("author", "") or "")
        self.signer.setPlaceholderText("Name of the person signing")
        self.signer.editingFinished.connect(self.propose)
        top.addWidget(self.signer)
        self.title = QLineEdit(settings.get("signer_title", "") or "")
        self.title.setPlaceholderText("Title")
        self.title.editingFinished.connect(self.propose)
        top.addWidget(self.title)
        v.addLayout(top)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Fill", "Field", "Value (you can change it)",
             "Where it comes from", "Status", "Page"])
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.ResizeToContents)
        h.setSectionResizeMode(C_VALUE, QHeaderView.Stretch)
        h.setSectionResizeMode(C_SRC, QHeaderView.Stretch)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        v.addWidget(self.table, 1)
        self.note = QLabel("")
        self.note.setWordWrap(True)
        v.addWidget(self.note)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        self.fill_btn = bb.addButton("Fill Ticked",
                                     QDialogButtonBox.ActionRole)
        self.fill_btn.clicked.connect(lambda: self.fill())
        self.sign_btn = bb.addButton("Sign Selected Box",
                                     QDialogButtonBox.ActionRole)
        self.sign_btn.setToolTip("Puts your saved signature in the "
                                 "selected signature box, in a new file, "
                                 "and records who signed and when")
        self.sign_btn.clicked.connect(lambda: self.sign())
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.propose()

    # ------------------------------------------------------------ propose
    def data(self):
        who = self.who.currentText()
        contact = next((c for c in self.contacts
                        if c.get("company") == who), None) \
            if who != OURS else None
        return F.known(self.job_doc, contact,
                       {"name": self.signer.text().strip(),
                        "title": self.title.text().strip()})

    def propose(self):
        import fitz
        doc = fitz.open(self.path)
        try:
            self.rows = F.propose(doc, self.data())
        finally:
            doc.close()
        t = self.table
        t.setRowCount(len(self.rows))
        for r, row in enumerate(self.rows):
            tick = QTableWidgetItem("")
            can = row["status"] in (F.READY, F.UNSURE)
            tick.setFlags((Qt.ItemIsUserCheckable | Qt.ItemIsEnabled |
                           Qt.ItemIsSelectable) if can else
                          Qt.ItemIsSelectable)
            if can:
                tick.setCheckState(Qt.Checked if row["tick"]
                                   else Qt.Unchecked)
            t.setItem(r, C_TICK, tick)
            name = row["name"] or "(no name)"
            if row["label"] and row["label"].lower() not in name.lower():
                name += f"  [{row['label']}]"
            cells = [(C_FIELD, name, False),
                     (C_VALUE, row["value"], can),
                     (C_SRC, row["source"], False),
                     (C_STATUS, row["status"].upper() + (
                         " - " + row["why"] if row["why"] else ""), False),
                     (C_PAGE, str(row["page"] + 1), False)]
            for c, text, edit in cells:
                it = QTableWidgetItem(text)
                if not edit:
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                if c == C_STATUS:
                    it.setBackground(QColor(BG[row["status"]]))
                    it.setForeground(QColor("#111111"))
                t.setItem(r, c, it)
        self.note.setText(
            (F.summary(self.rows) if self.rows else
             "This PDF has no fillable fields. Use Fill & Sign > Fill Text "
             "to type on it, and Signature to sign it.") + (
                f"  Working on: {os.path.basename(self.path)}"
                if self.path != self.src else ""))
        self.fill_btn.setEnabled(any(r["status"] in (F.READY, F.UNSURE)
                                     for r in self.rows))
        self.sign_btn.setEnabled(any(r["status"] == F.SIGN
                                     for r in self.rows))
        return self.rows

    def _sync(self):
        """The ticks and typed values, back into the rows."""
        values = {}
        for r, row in enumerate(self.rows):
            if row["status"] in (F.READY, F.UNSURE):
                row["tick"] = self.table.item(r, C_TICK).checkState() == \
                    Qt.Checked
                values[row["id"]] = self.table.item(r, C_VALUE).text()
        return values

    # --------------------------------------------------------------- fill
    def fill(self):
        values = self._sync()
        if not any(r["tick"] for r in self.rows
                   if r["status"] in (F.READY, F.UNSURE)):
            self.note.setText("Tick the fields to fill first.")
            return None
        out, done = F.fill(self.path, self.rows, values=values)
        self.filled = self.path = out
        self.propose()
        self.note.setText(f"Filled {len(done)} field(s) into "
                          f"{os.path.basename(out)} (your form was not "
                          "changed). " + self.note.text())
        if self.on_open:
            self.on_open(out)
        return out

    # --------------------------------------------------------------- sign
    def sign(self, row=None, strokes=None):
        """Sign one box: the selected one. Needs the signer's name and a
        saved signature."""
        from . import signature
        if row is None:
            r = self.table.currentRow()
            row = self.rows[r] if 0 <= r < len(self.rows) else None
        if row is None or row["status"] != F.SIGN:
            QMessageBox.information(
                self, self.windowTitle(), "Select a signature box in the "
                "list first (its status says SIGNATURE).")
            return None
        if not self.signer.text().strip():
            QMessageBox.information(
                self, self.windowTitle(), "Enter the signer's name first. "
                "It is kept with the signature.")
            return None
        if strokes is None:
            strokes = signature.saved("signature")
            if strokes is None:
                if not signature.SignaturePad("signature", self).exec():
                    return None
                strokes = signature.saved("signature")
        try:
            got = F.sign(self.path, row, strokes, self.signer.text(),
                         date_rows=F.date_rows_for(self.rows, row))
        except ValueError as e:
            QMessageBox.information(self, self.windowTitle(), str(e))
            return None
        if self.title.text().strip():
            settings.set("signer_title", self.title.text().strip())
        self.signed.append(got)
        self.path = got["path"]
        self.propose()
        self.note.setText(
            f"Signed by {got['by']} into {os.path.basename(got['path'])}. "
            f"Recorded in {F.LOG_NAME} beside it and in the file's own "
            "audit trail. This is a drawn signature, not a certificate "
            "signature. Nothing was sent.")
        if self.on_open:
            self.on_open(got["path"])
        return got
