"""Estimate > Bid Form Autopilot: the window (logic: bidform_auto.py)."""
import os

from PySide6.QtCore import QDateTime
from PySide6.QtWidgets import (QCheckBox, QDateTimeEdit, QDialog,
                               QDialogButtonBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from . import bidform_auto as BA


def _grid(heads, rows=4):
    t = QTableWidget(rows, len(heads))
    t.setHorizontalHeaderLabels(heads)
    t.verticalHeader().hide()
    t.horizontalHeader().setStretchLastSection(True)
    t.setMaximumHeight(150)
    return t


def _pairs(t):
    out = {}
    for r in range(t.rowCount()):
        n, a = t.item(r, 0), t.item(r, t.columnCount() - 1)
        try:
            out[int(n.text())] = float(str(a.text()).replace("$", "")
                                       .replace(",", ""))
        except (AttributeError, ValueError):
            continue
    return out


class BidFormDialog(QDialog):
    def __init__(self, doc, parent=None, open_result=None):
        super().__init__(parent)
        self.doc = doc
        self.open_result = open_result
        self.setWindowTitle("Bid Form Autopilot")
        self.resize(640, 640)
        lay = QVBoxLayout(self)
        try:
            v = BA.values(doc)
            head = (f"Base bid from the estimate: <b>${v['base']:,.2f}</b>"
                    f"<br><i>{v['words']}</i><br>Addenda to acknowledge: "
                    f"{', '.join(str(n) for n in sorted(v['addenda'])) or 'none'}")
        except Exception as e:                            # noqa: BLE001
            head = f"The estimate couldn't be totalled: {e}"
        lay.addWidget(QLabel(head))
        f = QFormLayout()
        row = QHBoxLayout()
        self.form = QLineEdit()
        self.form.setPlaceholderText("The owner's bid form (PDF with fields)")
        pick = QPushButton("Browse…")
        pick.clicked.connect(lambda: self._pick())
        row.addWidget(self.form, 1)
        row.addWidget(pick)
        f.addRow("Bid form:", row)
        self.deadline = QDateTimeEdit(QDateTime.currentDateTime().addDays(1))
        self.deadline.setCalendarPopup(True)
        f.addRow("Bids due:", self.deadline)
        self.bond = QCheckBox("Bid bond is ready")
        f.addRow("", self.bond)
        lay.addLayout(f)
        lay.addWidget(QLabel("Alternates (number, description, amount):"))
        self.alts = _grid(["No.", "Description", "Amount"])
        lay.addWidget(self.alts)
        lay.addWidget(QLabel("Unit prices (item number on the form, price):"))
        self.units = _grid(["No.", "Price"])
        lay.addWidget(self.units)
        self.result = QLabel("")
        self.result.setWordWrap(True)
        lay.addWidget(self.result, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        go = bb.addButton("Fill the Form", QDialogButtonBox.ActionRole)
        go.clicked.connect(lambda: self.run())
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _pick(self):
        p, _ = QFileDialog.getOpenFileName(self, "Owner's Bid Form", "",
                                           "PDF (*.pdf)")
        if p:
            self.form.setText(p)

    def run(self, out_path=None):
        src = self.form.text().strip()
        if not src or not os.path.isfile(src):
            QMessageBox.information(self, self.windowTitle(),
                                    "Pick the owner's bid form first.")
            return None
        out_path = out_path or os.path.splitext(src)[0] + " - filled.pdf"
        dl = self.deadline.dateTime().toPython()
        try:
            got = BA.run(self.doc, src, out_path, _pairs(self.alts),
                         _pairs(self.units), dl, self.bond.isChecked())
        except BA.GateError as e:
            QMessageBox.warning(self, self.windowTitle(),
                                f"{e}. Mark each addendum priced (even at $0)"
                                " in Project > Addenda first.")
            return None
        except Exception as e:                            # noqa: BLE001
            QMessageBox.warning(self, self.windowTitle(),
                                f"The form couldn't be filled: {e}")
            return None
        lines = [("✔ " if ok else "✖ ") + msg for ok, msg in got["check"]]
        self.result.setText(f"Filled {len(got['filled'])} field(s), saved "
                            f"as {os.path.basename(out_path)}.<br>" +
                            "<br>".join(lines))
        if self.open_result:
            self.open_result(out_path)
        got["path"] = out_path
        return got
