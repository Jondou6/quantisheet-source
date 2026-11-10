"""Warranty registrations window (1.2 phase 5, #9 / QW4).

The due list counts down each unit's register-by date; the brand rules
are editable (days per brand) and anything not confirmed on the maker's
own page says UNVERIFIED. open_window(parent).
"""
import datetime as dt

from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QSpinBox

from ..estimating import service as records_api
from . import uiutil, warranty


class WarrantyWindow(uiutil.Desk):
    def __init__(self, parent=None, today=None):
        super().__init__("Warranty Registrations", parent)
        self.today = today or dt.date.today()
        self.note = QLabel("The warranty card that ships with the unit is "
                           "what counts - these windows are starting "
                           "values.")
        self.note.setWordWrap(True)
        self.root.addWidget(self.note)
        self.buttons(("Add units from service records",
                      self.sync_clicked),)
        self.table = uiutil.table(["Register by", "Unit", "What"])
        self.table.setAccessibleName("Registrations due")
        self.root.addWidget(self.table, 2)
        reg = QHBoxLayout()
        self.confirmation = QLineEdit()
        self.confirmation.setPlaceholderText("Confirmation # (optional)")
        self.confirmation.setAccessibleName("Confirmation number")
        reg.addWidget(self.confirmation)
        self.root.addLayout(reg)
        self.buttons(("Mark registered", self.registered_clicked),)
        self.rules_table = uiutil.table(["Brand", "Days", "Checked",
                                         "Note"])
        self.rules_table.setAccessibleName("Brand rules")
        self.root.addWidget(self.rules_table, 1)
        edit = QHBoxLayout()
        self.days = QSpinBox()
        self.days.setRange(0, 3650)
        self.days.setAccessibleName("Days to register")
        edit.addWidget(QLabel("Days to register for the selected brand"))
        edit.addWidget(self.days)
        edit.addStretch(1)
        self.root.addLayout(edit)
        self.buttons(("Save brand days", self.rule_clicked),)
        self.finish()
        self.rules_table.itemSelectionChanged.connect(self._rule_picked)
        self.reload()

    def reload(self):
        self.store = warranty.load()
        rows = warranty.due(self.store, self.today)
        uiutil.fill(self.table, [[by or "-", name,
                                  ("LATE: " if late else "") + what]
                                 for by, name, what, late, _ in rows],
                    [r[4] for r in rows])
        self.rules = warranty.rules()
        uiutil.fill(self.rules_table, [
            [b, r["days"], "yes" if r.get("verified") else "UNVERIFIED",
             r.get("note", "")] for b, r in self.rules.items()],
            list(self.rules))
        late = sum(1 for r in rows if r[3])
        self.msg.setText(f"{len(rows)} unit(s) not registered yet"
                         + (f", {late} past the window" if late else "")
                         + ".")

    def sync_clicked(self):
        n = self.guard(lambda: warranty.sync_from_records(
            self.store, records_api.load()))
        if n is None:
            return None
        warranty.save(self.store)
        self.reload()
        self.msg.setText(f"{len(n)} unit(s) on the service records "
                         "checked. " + self.msg.text())
        return n

    def registered_clicked(self):
        eid = uiutil.selected_id(self.table)
        if not eid:
            self.msg.setText("Pick a unit in the list.")
            return None
        got = self.guard(lambda: warranty.mark_registered(
            self.store, eid, self.today, self.confirmation.text()))
        if got is None:
            return None
        warranty.save(self.store)
        self.confirmation.clear()
        self.reload()
        return got

    def _rule_picked(self):
        brand = uiutil.selected_id(self.rules_table)
        if brand in self.rules:
            self.days.setValue(int(self.rules[brand]["days"]))

    def rule_clicked(self):
        brand = uiutil.selected_id(self.rules_table)
        if not brand:
            self.msg.setText("Pick a brand in the rules list.")
            return None
        self.rules[brand]["days"] = self.days.value()
        if self.guard(lambda: warranty.save_rules(self.rules)) is None:
            return None
        self.reload()
        self.msg.setText(f"{brand}: {self.days.value()} days. Units already "
                         "tracked keep their window.")
        return brand


def open_window(parent=None):
    return uiutil.show(WarrantyWindow(parent))
