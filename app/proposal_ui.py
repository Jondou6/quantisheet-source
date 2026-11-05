"""Create Proposal dialog."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPlainTextEdit, QPushButton,
                               QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from . import proposal


def _text(value="", height=70):
    t = QPlainTextEdit(value)
    t.setFixedHeight(height)
    return t


class ProposalDialog(QDialog):
    def __init__(self, doc, parent=None, page=None, warning=None):
        super().__init__(parent)
        self.setWindowTitle("Create Proposal")
        self.resize(700, 600)
        self.doc = doc
        self.page = page
        data = proposal.read(doc)
        comp = proposal.company()
        lay = QVBoxLayout(self)
        # a warning shown in the dialog, not as a second modal box before
        # it (review 0.12.35 #20: a stacked modal could hang a sweep)
        self.warning_label = None
        if warning:
            self.warning_label = QLabel(warning)
            self.warning_label.setWordWrap(True)
            self.warning_label.setStyleSheet(
                "QLabel { background: #fff4ce; color: #5c4400; "
                "border: 1px solid #e0c060; padding: 6px; }")
            lay.addWidget(self.warning_label)
        tabs = QTabWidget()
        lay.addWidget(tabs)

        # --- your company (saved once, used on every proposal) ---
        w = QWidget()
        f = QFormLayout(w)
        self.c = {}
        for key, label in (("name", "Company"), ("phone", "Phone"),
                           ("email", "Email"), ("website", "Website"),
                           ("license", "License no."),
                           ("signer", "Signed by"), ("title", "Title")):
            self.c[key] = QLineEdit(comp.get(key, ""))
            f.addRow(label + ":", self.c[key])
        self.c["address"] = _text(comp.get("address", ""), 54)
        f.insertRow(1, "Address:", self.c["address"])
        row = QHBoxLayout()
        self.c["logo"] = QLineEdit(comp.get("logo", ""))
        self.c["logo"].setPlaceholderText("PNG or JPG file (optional)")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._logo)
        row.addWidget(self.c["logo"])
        row.addWidget(browse)
        f.addRow("Logo:", row)
        f.addRow(QLabel("<small>Saved for all your proposals.</small>"))
        tabs.addTab(w, "Your Company")

        # --- client and project ---
        w = QWidget()
        f = QFormLayout(w)
        self.d = {}
        for key, label in (("client", "Client"), ("attention", "Attention"),
                           ("project", "Project"), ("number", "Proposal no.")):
            self.d[key] = QLineEdit(str(data.get(key, "")))
            f.addRow(label + ":", self.d[key])
        self.d["client_address"] = _text(data.get("client_address", ""), 54)
        f.insertRow(2, "Client address:", self.d["client_address"])
        self.d["project_address"] = _text(data.get("project_address", ""), 54)
        f.insertRow(4, "Project address:", self.d["project_address"])
        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        from PySide6.QtCore import QDate
        d = QDate.fromString(str(data.get("date", "")), "yyyy-MM-dd")
        self.date.setDate(d if d.isValid() else QDate.currentDate())
        f.addRow("Date:", self.date)
        self.valid = QSpinBox()
        self.valid.setRange(1, 365)
        self.valid.setValue(int(proposal._num(data.get("valid_days"), 30)))
        self.valid.setSuffix(" days")
        f.addRow("Valid for:", self.valid)
        tabs.addTab(w, "Client && Project")
        self._job_info_tab(tabs, data)

        # --- pricing ---
        w = QWidget()
        f = QFormLayout(w)
        self.detail = QComboBox()
        for k, label in proposal.DETAIL.items():
            self.detail.addItem(label, k)
        self.detail.setCurrentIndex(
            max(0, list(proposal.DETAIL).index(data.get("detail", "trade"))
                if data.get("detail") in proposal.DETAIL else 0))
        f.addRow("Show prices:", self.detail)
        self.pct = {}
        for key, label in (("tax", "Sales tax on materials"),
                           ("overhead", "Overhead"), ("profit", "Profit")):
            s = QDoubleSpinBox()
            s.setRange(0, 100)
            s.setDecimals(2)
            s.setSuffix(" %")
            s.setValue(proposal._num(data.get(key)))
            s.valueChanged.connect(self._update_total)
            self.pct[key] = s
            f.addRow(label + ":", s)
        more = QPushButton("Bid Build-up…")
        more.setToolTip("General conditions, insurance, contingency, "
                        "escalation, bond, trade margins and front-loading")
        more.clicked.connect(lambda: self.build_up())
        f.addRow("More markups:", more)
        self.extra = {}
        self.breakdown = QCheckBox("Show material, labor and every markup "
                                   "on the proposal")
        self.breakdown.setChecked(bool(data.get("show_breakdown")))
        f.addRow(self.breakdown)
        self.summary = QLabel("")
        self.summary.setTextFormat(Qt.RichText)
        f.addRow(self.summary)
        tabs.addTab(w, "Pricing")

        # --- wording ---
        w = QWidget()
        f = QFormLayout(w)
        self.t = {}
        for key, label, h in (("scope", "Scope of work", 70),
                              ("qualifications",
                               "Qualifications (one per line)", 60),
                              ("inclusions", "Inclusions (one per line)", 70),
                              ("exclusions", "Exclusions (one per line)", 90),
                              ("terms", "Terms", 70)):
            self.t[key] = _text(data.get(key, ""), h)
            f.addRow(label + ":", self.t[key])
        self.notes = QCheckBox("Add what the takeoff assumed to the "
                               "qualifications")
        self.notes.setChecked(bool(data.get("takeoff_notes", True)))
        found = proposal.takeoff_notes(self.doc)
        self.notes.setToolTip("\n".join(found) if found else
                              "Nothing to add for this takeoff yet.")
        f.addRow(self.notes)
        self.sched = QCheckBox("Show a rough schedule from the estimate's "
                               "labor hours, crew of")
        self.sched.setChecked(bool(data.get("show_schedule")))
        self.crew = QSpinBox()
        self.crew.setRange(1, 200)
        self.crew.setValue(int(proposal._num(data.get("crew_size"), 4)))
        row = QHBoxLayout()
        row.addWidget(self.sched)
        row.addWidget(self.crew)
        row.addStretch(1)
        f.addRow(row)
        tabs.addTab(w, "Scope && Terms")

        bb = QDialogButtonBox(QDialogButtonBox.Cancel)
        make = bb.addButton("Create Proposal", QDialogButtonBox.AcceptRole)
        make.setDefault(True)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._update_total()

    def _logo(self):
        path, _ = QFileDialog.getOpenFileName(self, "Company Logo", "",
                                              "Images (*.png *.jpg *.jpeg)")
        if path:
            self.c["logo"].setText(path)

    def values(self):
        data = proposal.read(self.doc)
        for k, w in self.d.items():
            data[k] = w.toPlainText() if isinstance(w, QPlainTextEdit) \
                else w.text()
        data["date"] = self.date.date().toString("yyyy-MM-dd")
        data["valid_days"] = self.valid.value()
        data["detail"] = self.detail.currentData()
        for k, s in self.pct.items():
            data[k] = s.value()
        data.update(self.extra)
        data["show_breakdown"] = self.breakdown.isChecked()
        for k, w in self.t.items():
            data[k] = w.toPlainText()
        data["takeoff_notes"] = self.notes.isChecked()
        data["show_schedule"] = self.sched.isChecked()
        data["crew_size"] = self.crew.value()
        if getattr(self, "job_info", None) is not None:
            data.update(self.job_info.values())
        return data

    def _job_info_tab(self, tabs, data):
        """Job Info: description, website / contact, job ZIP (picks the
        location region), project image (jobinfo_ui.py)."""
        from .jobinfo_ui import JobInfoWidget
        self.job_info = JobInfoWidget(self.doc, data)
        tabs.addTab(self.job_info, "Job Info")

    def company_values(self):
        return {k: (w.toPlainText() if isinstance(w, QPlainTextEdit)
                    else w.text()) for k, w in self.c.items()}

    def _update_total(self):
        p = proposal.price(self.doc, self.values(), self.page)
        if not p["lines"]:
            self.summary.setText("<b>No assembly takeoff yet.</b> Take off "
                                 "with assemblies first (Takeoff > Assembly "
                                 "Library).")
            return
        rows = "".join(f"<br>+ {st['label'].lower()} "
                       f"{proposal._money(st['amount'])}"
                       for st in p["steps"] if st["key"] != "tax")
        self.summary.setText(
            f"Cost {proposal._money(p['cost'])} (material "
            f"{proposal._money(p['material'])} + tax "
            f"{proposal._money(p['tax'])} + labor "
            f"{proposal._money(p['labor'])}){rows}<br><b>Proposal total "
            f"{proposal._money(p['total'])}</b>")

    def build_up(self, dlg=None):
        """Open the Bid Build-up with what's on this dialog; OK brings the
        markups back here (saved with the job when the proposal is made)."""
        from .bidbuild_ui import BidBuildDialog
        given = dlg is not None
        dlg = dlg or BidBuildDialog(self.doc, self, self.values(), self.page)
        if given or dlg.exec():
            vals = dlg.values()
            for k in ("tax", "overhead", "profit"):
                self.pct[k].setValue(vals.pop(k))
            self.extra.update(vals)
            self._update_total()
        return dlg

    def accept(self):
        data = self.values()
        if not proposal.price(self.doc, data, self.page)["lines"]:
            QMessageBox.information(
                self, "Proposal", "There's nothing to price yet. Take off "
                "with assemblies first (Takeoff > Assembly Library).")
            return
        if getattr(self, "job_info", None) is not None:
            if not self.job_info.commit():      # image refused: say so
                return
            data = self.values()                # with the image's name
        self.result_data = data
        super().accept()
