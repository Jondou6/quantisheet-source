"""Code Check window."""
import logging
import os

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSpinBox, QSplitter, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget)

from . import theme as _theme
from . import codecheck

HOW = ("Name your measurements so the check can find them: areas are "
       "spaces (named by room); lengths in groups with \"Door\", \"Exit "
       "Door\", \"Corridor\" or \"Stair\" are clear widths, and \"Travel\", "
       "\"Common Path\" or \"Dead End\" are distances; counts named \"Exit\", "
       "\"WC\", \"Lavatory\" or \"Drinking Fountain\" are counted. Each page "
       "is one floor.")
SEV = {"error": ("Error", QColor(255, 220, 220)),
       "warn": ("Check", QColor(255, 244, 214)),
       "info": ("Note", None)}


def _item(text, data=None):
    it = QTableWidgetItem("" if text is None else str(text))
    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
    if data is not None:
        it.setData(Qt.UserRole, data)
    return it


class CodeCheckDialog(QDialog):
    edited = Signal()
    go_to = Signal(int, object)

    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle("Code Check")
        self.resize(1150, 720)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        form = QFormLayout()
        self.group = QComboBox()
        self.group.addItems(codecheck.GROUPS)
        form.addRow("Occupancy group:", self.group)
        self.spr = QCheckBox("Sprinklered throughout (NFPA 13)")
        form.addRow(self.spr)
        self.voice = QCheckBox("Emergency voice/alarm communication")
        form.addRow(self.voice)
        top.addLayout(form)
        pk = QFormLayout()
        self.pk = {}
        for k, label in (("total", "Parking spaces:"),
                         ("accessible", "Accessible spaces:"),
                         ("van", "Van-accessible:")):
            e = QLineEdit()
            e.setPlaceholderText("not checked")
            e.setMaximumWidth(110)
            pk.addRow(label, e)
            self.pk[k] = e
        top.addLayout(pk)
        how = QLabel(HOW)
        how.setWordWrap(True)
        how.setStyleSheet("color: #555;")
        top.addWidget(how, 1)
        lay.addLayout(top)

        split = QSplitter(Qt.Vertical)
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(QLabel("<b>Spaces</b> (function of space sets the "
                           "occupant load factor; exits only matter where "
                           "the load needs two)"))
        self.spaces = QTableWidget(0, 6)
        self.spaces.setHorizontalHeaderLabels(
            ["Page", "Space", "Area (sf)", "Function of space", "Exits",
             "Occupants"])
        self.spaces.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.Stretch)
        self.spaces.itemDoubleClicked.connect(self._space_go)
        v.addWidget(self.spaces)
        split.addWidget(w)
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        self.summary = QLabel("")
        v.addWidget(self.summary)
        self.found = QTableWidget(0, 6)
        self.found.setHorizontalHeaderLabels(
            ["", "Section", "Where", "Finding", "Shown", "Required"])
        self.found.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.Stretch)
        self.found.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.found.itemDoubleClicked.connect(self._finding_go)
        v.addWidget(self.found)
        split.addWidget(w)
        lay.addWidget(split, 1)
        row = QHBoxLayout()
        for label, fn in (("Run Check", self.run),
                          ("Mark Up Findings on Drawings", self.mark_up),
                          ("Print Report…", self.report)):
            b = QPushButton(label)
            b.clicked.connect(lambda _c=False, _f=fn: _f())
            row.addWidget(b)
        row.addStretch()
        note = QLabel(f"{codecheck.EDITION}. Screening only - verify "
                      "against the adopted code and local amendments.")
        note.setStyleSheet("color: #777;")
        row.addWidget(note)
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.close)
        lay.addWidget(bb)
        self.findings = []
        self.refresh()

    # ---- settings <-> widgets ----------------------------------------------
    def refresh(self):
        data = codecheck.read(self.doc)
        self.group.setCurrentText(data["group"])
        self.spr.setChecked(bool(data["sprinklered"]))
        self.voice.setChecked(bool(data["voice_alarm"]))
        for k, e in self.pk.items():
            v = data["parking"].get(k)
            e.setText("" if v is None else str(v))
        self.run(save=False)

    def settings(self):
        uses, exits = {}, {}
        for r in range(self.spaces.rowCount()):
            name = self.spaces.item(r, 1).data(Qt.UserRole)
            uses[name] = self.spaces.cellWidget(r, 3).currentData()
            sp = self.spaces.cellWidget(r, 4)
            if sp.value() > 0:
                exits[name] = sp.value()
            else:
                exits[name] = None
        pk = {}
        for k, e in self.pk.items():
            t = e.text().strip()
            pk[k] = int(t) if t.isdigit() else None
        return {"group": self.group.currentText(),
                "sprinklered": self.spr.isChecked(),
                "voice_alarm": self.voice.isChecked(), "uses": uses,
                "exits": {k: v for k, v in exits.items() if v},
                "parking": pk}

    def save(self):
        data = codecheck.read(self.doc)
        new = self.settings()
        data.update({k: new[k] for k in ("group", "sprinklered",
                                         "voice_alarm", "parking")})
        data["uses"].update(new["uses"])
        for name in new["uses"]:
            data["exits"].pop(name, None)
        data["exits"].update(new["exits"])
        codecheck.write(self.doc, data)
        self.edited.emit()

    # ---- run -------------------------------------------------------------------
    def run(self, save=True):
        if save and self.spaces.rowCount():
            self.save()
        findings, s = codecheck.check(self.doc)
        self.findings = findings
        self._fill_spaces(s["spaces"])
        self.found.setRowCount(len(findings))
        for r, f in enumerate(findings):
            label, color = SEV[f["severity"]]
            vals = [label, f["section"], f["where"], f["message"],
                    "" if f["actual"] is None else f"{f['actual']} {f['unit']}",
                    "" if f["required"] is None else
                    f"{f['required']} {f['unit']}"]
            for c, val in enumerate(vals):
                it = _item(val, r)
                if color:
                    _theme.tint(it, color)
                self.found.setItem(r, c, it)
        self.summary.setText(
            f"<b>{s['occupants']} occupants</b> on {len(s['floors'])} "
            f"floor(s) - <b>{s['errors']}</b> error(s), "
            f"<b>{s['warnings']}</b> to check. Double-click a row to go "
            "to it.")
        return findings

    def _fill_spaces(self, spaces):
        self.spaces.setRowCount(len(spaces))
        for r, sp in enumerate(spaces):
            self.spaces.setItem(r, 0, _item(sp["page"] + 1))
            self.spaces.setItem(r, 1, _item(sp["name"], sp["name"]))
            self.spaces.item(r, 1).setData(Qt.UserRole + 1,
                                           (sp["page"], sp["ref"]))
            self.spaces.setItem(r, 2, _item(f"{sp['area']:,.0f}"))
            cb = QComboBox()
            for k, u in codecheck.USES.items():
                cb.addItem(f"{u[0]}" + (f"  ({u[1]} {u[2]})" if u[1] else
                                        ""), k)
            cb.setCurrentIndex(max(0, cb.findData(sp["use"])))
            cb.currentIndexChanged.connect(self._later)
            self.spaces.setCellWidget(r, 3, cb)
            spin = QSpinBox()
            spin.setRange(0, 20)
            spin.setSpecialValueText("?")
            spin.setValue(int(sp.get("exits") or 0))
            spin.valueChanged.connect(self._later)
            self.spaces.setCellWidget(r, 4, spin)
            self.spaces.setItem(r, 5, _item(sp["load"]))

    def _later(self, *_):
        # rebuild after the signal returns (the sender is replaced)
        QTimer.singleShot(0, self.run)

    def _space_go(self, it):
        page, ref = self.spaces.item(it.row(), 1).data(Qt.UserRole + 1)
        self.go_to.emit(page, ref)

    def _finding_go(self, it):
        f = self.findings[it.data(Qt.UserRole)]
        if f.get("page") is not None:
            self.go_to.emit(f["page"], f.get("ref"))

    def mark_up(self):
        self.run()
        from . import settings
        n = codecheck.markup(self.doc, self.findings, settings.author())
        self.edited.emit()
        QMessageBox.information(self, "Code Check",
                                f"Added {n} cloud(s) around findings on the "
                                "drawings." if n else
                                "No findings point at a measurement.")
        return n

    def report(self, path=None):
        self.run()
        project = ""
        try:
            from . import money
            project = money.read(self.doc)["info"].get("project", "")
        except Exception:
            logging.getLogger(__name__).debug("ignored error", exc_info=True)
        if path is None:
            from .reportname import report_file_name
            base = os.path.dirname(self.doc.name or "") or \
                os.path.expanduser("~")
            path, _ = QFileDialog.getSaveFileName(
                self, "Code Check Report",
                os.path.join(base, report_file_name("Code Check Report",
                                                    project)),
                "PDF (*.pdf)")
        if not path:
            return None
        codecheck.report_pdf(self.doc, path, project)
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        return path
