"""Flat-rate pricebook window. open_window(parent) shows it."""
from PySide6.QtWidgets import QComboBox, QFileDialog, QHBoxLayout, QLineEdit

from .. import dmoney
from . import files, pricebook, uiutil


class PricebookWindow(uiutil.Desk):
    def __init__(self, parent=None):
        super().__init__("Flat-Rate Pricebook", parent)
        self.path = pricebook.default_path()
        row = QHBoxLayout()
        self.code = QLineEdit()
        self.code.setPlaceholderText("Code")
        self.name = QLineEdit()
        self.name.setPlaceholderText("Task")
        self.customer = QLineEdit()
        self.customer.setPlaceholderText("Customer price")
        self.member = QLineEdit()
        self.member.setPlaceholderText("Member price")
        self.hours = QLineEdit("0")
        self.labor = QLineEdit("0")
        self.tier = QComboBox()
        self.tier.addItems(list(pricebook.TIERS))
        self.tier.setCurrentText("option")
        for w in (self.code, self.name, self.customer, self.member,
                  self.hours, self.labor, self.tier):
            row.addWidget(w)
        self.root.addLayout(row)
        self.part = QLineEdit()
        self.part.setPlaceholderText("Built-in part, qty x cost  e.g. capacitor, 1, 12.50")
        self.root.addWidget(self.part)
        self.buttons(("Add task", self.add_clicked),
                     ("Option quote", self.quote_clicked))
        self.table = uiutil.table(
            ["Code", "Task", "Customer", "Member", "Hours", "Built-in cost",
             "Tier"])
        self.root.addWidget(self.table, 1)
        self.finish()
        self.reload()

    def reload(self):
        self.store = pricebook.load(self.path)
        rows, ids = [], []
        for t in self.store["tasks"]:
            rows.append([t["code"], t["name"], dmoney.fmt(t["customer_price"]),
                         dmoney.fmt(t["member_price"]), t["hours"],
                         dmoney.fmt(pricebook.task_cost(t)), t["tier"]])
            ids.append(t["id"])
        uiutil.fill(self.table, rows, ids)

    def _parts(self):
        text = self.part.text().strip()
        if not text:
            return []
        bits = [b.strip() for b in text.split(",")]
        desc = bits[0] if bits else "Part"
        qty = bits[1] if len(bits) > 1 and bits[1] else "1"
        cost = bits[2] if len(bits) > 2 and bits[2] else "0"
        return [{"desc": desc, "qty": qty, "cost": cost}]

    def add_clicked(self):
        def go():
            return pricebook.add_task(
                self.store, self.name.text(), self.customer.text(),
                self.member.text(), code=self.code.text(),
                hours=self.hours.text() or "0",
                labor_cost=self.labor.text() or "0", parts=self._parts(),
                tier=self.tier.currentText())
        if self.guard(go):
            pricebook.save(self.store, self.path)
            self.reload()
            self.msg.setText("Task saved.")

    def quote_to(self, path, member=False):
        ids = [t["id"] for t in self.store["tasks"]]
        def go():
            quote = pricebook.option_quote(self.store, ids, member=member)
            return pricebook.save_quote(path, quote)
        out = self.guard(go)
        if out:
            self.msg.setText(f"Saved {out}")
        return out

    def quote_clicked(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Option quote", files.path_for("Service options.pdf"),
            "PDF (*.pdf)")
        if path:
            self.quote_to(path)


def open_window(parent=None):
    return uiutil.show(PricebookWindow(parent))
