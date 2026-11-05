"""Refrigerant log window. open_window(parent) shows it."""
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel,
                               QLineEdit)

from ..estimating import service as records_api
from . import files, refrigerant, uiutil


class RefrigerantWindow(uiutil.Desk):
    def __init__(self, parent=None):
        super().__init__("Refrigerant Log", parent)
        self.path = refrigerant.default_path()
        note = QLabel(refrigerant.RULE_NOTE)      # compliance records
        note.setWordWrap(True)
        self.root.addWidget(note)
        row = QHBoxLayout()
        self.unit = QComboBox()
        self.gas = QLineEdit()
        self.gas.setPlaceholderText("Refrigerant")
        self.charge = QLineEdit()
        self.charge.setPlaceholderText("Full charge, lb")
        self.category = QComboBox()
        for key, label in refrigerant.CATEGORY_LABELS.items():
            self.category.addItem(label, key)
        self.charge_date = QLineEdit()
        self.charge_date.setPlaceholderText("Charge date")
        for w in (self.unit, self.gas, self.charge, self.category,
                  self.charge_date):
            row.addWidget(w)
        self.root.addLayout(row)
        self.buttons(("Add unit", self.add_unit_clicked),)
        visit = QHBoxLayout()
        self.added = QLineEdit("0")
        self.recovered = QLineEdit("0")
        self.cylinder = QLineEdit()
        self.cylinder.setPlaceholderText("Cylinder #")
        self.cert = QLineEdit()
        self.cert.setPlaceholderText("608 cert #")
        self.tech = QLineEdit()
        self.tech.setPlaceholderText("Technician")
        self.when = QLineEdit()
        self.when.setPlaceholderText("Visit date")
        for w, lab in ((self.added, "Added lb"), (self.recovered, "Recovered"),
                       (self.cylinder, ""), (self.cert, ""), (self.tech, ""),
                       (self.when, "")):
            if lab:
                visit.addWidget(QLabel(lab))
            visit.addWidget(w)
        self.root.addLayout(visit)
        self.buttons(("Add visit", self.add_visit_clicked),
                     ("Print site log", self.print_clicked))
        self.table = uiutil.table(
            ["Unit", "Refrigerant", "Full charge", "Leak rate", "Limit",
             "Flag"])
        self.root.addWidget(self.table, 1)
        self.finish()
        self.reload()

    def reload(self):
        self.store = refrigerant.load(self.path)
        self.records = records_api.load()
        current = self.unit.currentData()
        self.unit.clear()
        for eq in self.records["equipment"]:
            label = " ".join(p for p in (eq.get("kind"), eq.get("model"),
                                         eq.get("serial")) if p)
            self.unit.addItem(label, eq["id"])
        if current:
            idx = self.unit.findData(current)
            if idx >= 0:
                self.unit.setCurrentIndex(idx)
        rows, ids = [], []
        for u in self.store["units"]:
            info = refrigerant.leak_rate(self.store, u["id"])
            rows.append([u["unit"], u["refrigerant"], u["full_charge"],
                         f"{info['rate']}%", f"{info['threshold']}%",
                         refrigerant.flag_text(info)])
            ids.append(u["id"])
        uiutil.fill(self.table, rows, ids)

    def _logged_id(self):
        eq = self.unit.currentData()
        for u in self.store["units"]:
            if u["equipment_id"] == eq:
                return u["id"]
        self.msg.setText("Add this unit to the log first.")
        return None

    def add_unit_clicked(self):
        def go():
            return refrigerant.add_unit(
                self.store, self.records, self.unit.currentData(),
                self.gas.text(), self.charge.text(),
                self.category.currentData(), self.charge_date.text())
        if self.guard(go):
            refrigerant.save(self.store, self.path)
            self.reload()
            self.msg.setText("Unit added to the log.")

    def add_visit_clicked(self):
        uid = self._logged_id()
        if not uid:
            return
        def go():
            return refrigerant.add_visit(
                self.store, uid, self.when.text(), self.added.text() or "0",
                self.recovered.text() or "0", self.cylinder.text(),
                self.cert.text(), self.tech.text())
        if self.guard(go):
            refrigerant.save(self.store, self.path)
            self.reload()
            self.msg.setText("Visit recorded.")

    def print_to(self, path, property_id):
        out = self.guard(lambda: refrigerant.site_log_pdf(
            self.store, self.records, property_id, path))
        if out:
            self.msg.setText(f"Saved {out}")
        return out

    def print_clicked(self):
        eq_id = self.unit.currentData()
        eq = records_api.find(self.records, eq_id) if eq_id else None
        if not eq:
            self.msg.setText("Pick a unit.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Refrigerant log", files.path_for("Refrigerant log.pdf"),
            "PDF (*.pdf)")
        if path:
            self.print_to(path, eq.get("property"))


def open_window(parent=None):
    return uiutil.show(RefrigerantWindow(parent))
