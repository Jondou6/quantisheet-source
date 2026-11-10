"""Refrigerant recovery & cylinders window (from the Refrigerant Log).
open_window(parent) shows it."""
import datetime as dt

from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel,
                               QLineEdit)

from . import files, recovery, uiutil


def _edit(hint, text=""):
    e = QLineEdit(text)
    e.setPlaceholderText(hint)
    e.setAccessibleName(hint)
    return e


class RecoveryWindow(uiutil.Desk):
    def __init__(self, parent=None):
        super().__init__("Refrigerant Recovery & Cylinders", parent)
        self.path = recovery.default_path()
        self.root.addWidget(QLabel(
            "Disposal records for appliances of 5 to 50 lb (40 CFR "
            "82.156(a)(3)), monthly totals by type, transfers to a "
            "reclaimer, cylinders on each truck and the disposable-cylinder "
            "statement (40 CFR 84.116). Not legal advice."))
        r1 = QHBoxLayout()
        self.d_when = _edit("Date")
        self.d_loc = _edit("Location")
        self.d_gas = _edit("Refrigerant")
        self.d_lbs = _edit("Pounds recovered")
        self.d_charge = _edit("Full charge, lb")
        self.d_app = _edit("Appliance")
        for w in (self.d_when, self.d_loc, self.d_gas, self.d_lbs,
                  self.d_charge, self.d_app):
            r1.addWidget(w)
        self.root.addLayout(r1)
        self.buttons(("Record disposal", self.disposal_clicked))
        r2 = QHBoxLayout()
        self.t_when = _edit("Date")
        self.t_who = _edit("Reclaimer")
        self.t_gas = _edit("Refrigerant")
        self.t_lbs = _edit("Pounds")
        self.t_cyl = _edit("Cylinder #")
        for w in (self.t_when, self.t_who, self.t_gas, self.t_lbs, self.t_cyl):
            r2.addWidget(w)
        self.root.addLayout(r2)
        self.buttons(("Record transfer to reclaimer", self.transfer_clicked))
        r3 = QHBoxLayout()
        self.c_no = _edit("Cylinder #")
        self.c_gas = _edit("Refrigerant")
        self.c_kind = QComboBox()
        self.c_kind.setAccessibleName("Cylinder kind")
        for k in recovery.CYL_KINDS:
            self.c_kind.addItem(k.capitalize(), k)
        self.c_truck = _edit("Truck")
        for w in (self.c_no, self.c_gas, self.c_kind, self.c_truck):
            r3.addWidget(w)
        self.root.addLayout(r3)
        self.buttons(("Add cylinder", self.cylinder_clicked))
        r4 = QHBoxLayout()
        self.s_method = QComboBox()
        self.s_method.setAccessibleName("How it was emptied")
        self.s_method.addItem("Heel removed", "heel")
        self.s_method.addItem("Evacuated to vacuum", "vacuum")
        self.s_tech = _edit("Technician")
        self.s_cert = _edit("608 cert #")
        for w in (self.s_method, self.s_tech, self.s_cert):
            r4.addWidget(w)
        self.root.addLayout(r4)
        self.buttons(("Disposable cylinder statement for selected…",
                      self.statement_clicked),
                     ("Print this month's log", self.month_clicked))
        self.table = uiutil.table(["Cylinder", "Refrigerant", "Kind",
                                   "Truck", "Status"])
        self.table.setAccessibleName("Cylinders")
        self.root.addWidget(self.table, 1)
        self.totals = QLabel("")
        self.root.addWidget(self.totals)
        self.finish()
        self.reload()

    def reload(self):
        self.store = recovery.load(self.path)
        rows = [[c["number"], c["refrigerant"], c["kind"], c["truck"],
                 c["status"]] for c in self.store["cylinders"]]
        uiutil.fill(self.table, rows, [c["id"]
                                       for c in self.store["cylinders"]])
        t = dt.date.today()
        tot = recovery.monthly_totals(self.store, t.year, t.month)
        self.totals.setText("Recovered this month: " + (", ".join(
            f"{k} {v} lb" for k, v in tot.items()) or "none"))

    def _save(self, text):
        recovery.save(self.store, self.path)
        self.reload()
        self.msg.setText(text)

    def disposal_clicked(self):
        if self.guard(lambda: recovery.add_disposal(
                self.store, self.d_when.text(), self.d_loc.text(),
                self.d_gas.text(), self.d_lbs.text(),
                full_charge=self.d_charge.text(),
                appliance=self.d_app.text())):
            self._save("Disposal recorded.")

    def transfer_clicked(self):
        if self.guard(lambda: recovery.add_transfer(
                self.store, self.t_when.text(), self.t_who.text(),
                self.t_gas.text(), self.t_lbs.text(), self.t_cyl.text())):
            self._save("Transfer recorded.")

    def cylinder_clicked(self):
        if self.guard(lambda: recovery.add_cylinder(
                self.store, self.c_no.text(), self.c_gas.text(),
                self.c_kind.currentData(), self.c_truck.text())):
            self._save("Cylinder added.")

    def statement_clicked(self, _checked=False, path=None):
        from PySide6.QtCore import Qt
        r = self.table.currentRow()
        it = self.table.item(r, 0) if r >= 0 else None
        if it is None:
            self.msg.setText("Pick a disposable cylinder in the list.")
            return None
        sid = self.guard(lambda: recovery.empty_statement(
            self.store, it.data(Qt.UserRole), dt.date.today().isoformat(),
            self.s_method.currentData(), self.s_tech.text(),
            self.s_cert.text()))
        if not sid:
            return None
        recovery.save(self.store, self.path)
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Cylinder statement",
                files.path_for("Disposable cylinder statement.pdf"),
                "PDF (*.pdf)")
        out = self.guard(lambda: recovery.statement_pdf(self.store, sid,
                                                        path)) if path else None
        self.reload()
        if out:
            self.msg.setText(f"Saved {out} - the tech signs it.")
        return out

    def month_clicked(self, _checked=False, path=None):
        t = dt.date.today()
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Recovery log",
                files.path_for(f"Recovery log {t:%Y-%m}.pdf"), "PDF (*.pdf)")
        if not path:
            return None
        out = self.guard(lambda: recovery.disposal_log_pdf(
            self.store, t.year, t.month, path))
        if out:
            self.msg.setText(f"Saved {out}")
        return out


def open_window(parent=None):
    return uiutil.show(RecoveryWindow(parent))
