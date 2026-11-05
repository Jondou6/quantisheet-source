"""Service work order window.

open_window(parent) shows it and returns it. Wire that from the Service
ribbon. The record keeping is workorder.py.
"""
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout,
                               QLabel, QLineEdit, QPlainTextEdit)

from .. import dmoney
from ..estimating import service as records_api
from . import files, pricebook, truckstock, uiutil, workorder


class WorkOrderWindow(uiutil.Desk):
    def __init__(self, parent=None):
        super().__init__("Service Work Order", parent)
        self.path = workorder.default_path()
        self.store = workorder.load(self.path)
        self.records = records_api.load()
        self.book = pricebook.load()
        self.trucks = truckstock.load()
        row = QHBoxLayout()
        self.customer = QLineEdit()
        self.customer.setPlaceholderText("Customer")
        self.site = QComboBox()
        self.site.setEditable(True)
        self.unit = QComboBox()
        self.complaint = QLineEdit()
        self.complaint.setPlaceholderText("Complaint")
        self.tech = QLineEdit()
        self.tech.setPlaceholderText("Technician")
        for w in (self.customer, self.site, self.unit, self.complaint,
                  self.tech):
            row.addWidget(w)
        self.root.addLayout(row)
        self.site.currentIndexChanged.connect(self._fill_units)
        self.buttons(("Add ticket", self.add_clicked),)
        self.table = uiutil.table(
            ["Number", "Customer", "Site", "Unit", "Complaint", "Tech",
             "Status", "Price", "Profit", "Invoice"])
        self.table.itemSelectionChanged.connect(self._on_select)
        self.root.addWidget(self.table, 1)
        rates = QHBoxLayout()
        self.bill = QLineEdit(self.store["settings"]["labor_bill"])
        self.cost_rate = QLineEdit(self.store["settings"]["labor_cost"])
        self.hours = QLineEdit()
        self.hours.setPlaceholderText("Hours")
        rates.addWidget(QLabel("Labor price"))
        rates.addWidget(self.bill)
        rates.addWidget(QLabel("Labor cost"))
        rates.addWidget(self.cost_rate)
        rates.addWidget(self.hours)
        self.root.addLayout(rates)
        parts = QHBoxLayout()
        self.part = QLineEdit()
        self.part.setPlaceholderText("Part")
        self.part_qty = QLineEdit("1")
        self.part_cost = QLineEdit("0")
        self.part_price = QLineEdit("0")
        self.part_sku = QLineEdit()
        self.part_sku.setPlaceholderText("Item # on the truck")
        self.truck = QComboBox()
        for w in (self.part, self.part_qty, self.part_cost, self.part_price,
                  self.part_sku, self.truck):
            parts.addWidget(w)
        self.root.addLayout(parts)
        task_row = QHBoxLayout()
        self.task = QComboBox()
        self.member = QComboBox()
        self.member.addItems(["Customer price", "Agreement member price"])
        task_row.addWidget(self.task, 1)
        task_row.addWidget(self.member)
        self.root.addLayout(task_row)
        self.notes = QPlainTextEdit()
        self.notes.setPlaceholderText("Notes (required to close)")
        self.notes.setFixedHeight(70)
        self.root.addWidget(self.notes)
        self.profit = QLabel("")
        self.profit.setWordWrap(True)
        self.root.addWidget(self.profit)
        self.buttons(("Add time", self.add_time_clicked),
                     ("Add part", self.add_part_clicked),
                     ("No parts used", self.no_parts_clicked),
                     ("Use flat-rate task", self.task_clicked),
                     ("Use book time and parts", self.book_clicked),
                     ("Print work order", self.print_clicked),
                     ("Close and invoice", self.close_clicked))
        self.finish()
        self.reload()

    def reload(self):
        self.store = workorder.load(self.path)
        self.records = records_api.load()
        self.book = pricebook.load()
        self.trucks = truckstock.load()
        self._fill_sites()
        self._fill_tasks()
        self._fill_trucks()
        rows, ids = [], []
        for wo in self.store["orders"]:
            got = workorder.ticket_profit(self.store, wo)
            inv = next((i["number"] for i in self.store["invoices"]
                        if i["id"] == wo.get("invoice_id")), "")
            rows.append([wo["number"], wo["customer"], wo["site"], wo["unit"],
                         wo["complaint"], wo["tech"], wo["status"],
                         dmoney.fmt(got["price"]), dmoney.fmt(got["profit"]),
                         inv])
            ids.append(wo["id"])
        uiutil.fill(self.table, rows, ids)
        self._on_select()

    def _fill_sites(self):
        current = self.site.currentText()
        self.site.blockSignals(True)
        self.site.clear()
        self.site.addItem("", "")
        for p in self.records["properties"]:
            self.site.addItem(p["name"], p["id"])
        self.site.setCurrentText(current)
        self.site.blockSignals(False)
        self._fill_units()

    def _property_id(self):
        text = self.site.currentText().strip()
        if self.site.findText(text) < 0:
            return ""
        return self.site.currentData() or ""

    def _fill_units(self):
        pid = self._property_id()
        self.unit.clear()
        self.unit.addItem("", "")
        for eq in self.records["equipment"]:
            if pid and eq.get("property") != pid:
                continue
            label = " ".join(p for p in (eq.get("kind"), eq.get("model"),
                                         eq.get("serial")) if p)
            self.unit.addItem(label, eq["id"])

    def _fill_tasks(self):
        self.task.clear()
        self.task.addItem("", "")
        for t in self.book["tasks"]:
            self.task.addItem(f"{t['code']} {t['name']}".strip(), t["id"])

    def _fill_trucks(self):
        self.truck.clear()
        self.truck.addItem("", "")
        for t in self.trucks["trucks"]:
            self.truck.addItem(t["name"], t["id"])

    def _id(self):
        wo_id = uiutil.selected_id(self.table)
        if not wo_id:
            self.msg.setText("Select a ticket.")
        return wo_id

    def _save_rates(self):
        workorder.set_rates(self.store, self.bill.text(), self.cost_rate.text())

    def add_clicked(self):
        def go():
            return workorder.add(
                self.store, self.records, customer=self.customer.text(),
                site=self.site.currentText(), property_id=self._property_id(),
                equipment_id=self.unit.currentData() or "",
                complaint=self.complaint.text(), tech=self.tech.text())
        wo_id = self.guard(go)
        if not wo_id:
            return
        workorder.save(self.store, self.path)
        self.reload()
        self._select(wo_id)
        self.msg.setText("Ticket opened.")

    def _select(self, wo_id):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(uiutil.Qt.UserRole) == wo_id:
                self.table.selectRow(row)
                return

    def add_time_clicked(self):
        wo_id = self._id()
        if not wo_id:
            return
        def go():
            self._save_rates()
            return workorder.add_time(self.store, wo_id, self.tech.text(),
                                      self.hours.text() or "0")
        if self.guard(go):
            workorder.save(self.store, self.path)
            self.reload()
            self._select(wo_id)

    def add_part_clicked(self):
        wo_id = self._id()
        if not wo_id:
            return
        def go():
            return workorder.add_part(
                self.store, wo_id, self.part.text(), self.part_qty.text() or "1",
                cost=self.part_cost.text() or "0",
                price=self.part_price.text() or "0", sku=self.part_sku.text(),
                truck_store=self.trucks if self.truck.currentData() else None,
                truck_id=self.truck.currentData() or "")
        if self.guard(go):
            if self.truck.currentData():
                truckstock.save(self.trucks)
            workorder.save(self.store, self.path)
            self.reload()
            self._select(wo_id)

    def no_parts_clicked(self):
        wo_id = self._id()
        if not wo_id:
            return
        if self.guard(lambda: workorder.no_parts(self.store, wo_id)):
            workorder.save(self.store, self.path)
            self.reload()
            self._select(wo_id)

    def task_clicked(self):
        wo_id = self._id()
        tid = self.task.currentData()
        if not wo_id or not tid:
            self.msg.setText("Select a ticket and a task.")
            return
        member = self.member.currentIndex() == 1
        def go():
            return workorder.apply_task(self.store, wo_id,
                                        pricebook.get(self.book, tid), member)
        if self.guard(go):
            workorder.save(self.store, self.path)
            self.reload()
            self._select(wo_id)
            self.msg.setText("Flat-rate task applied.")

    def book_clicked(self):
        wo_id = self._id()
        if not wo_id:
            return
        def go():
            self._save_rates()
            return workorder.use_book(
                self.store, wo_id, tech=self.tech.text(),
                truck_store=self.trucks if self.truck.currentData() else None,
                truck_id=self.truck.currentData() or "")
        if self.guard(go):
            if self.truck.currentData():
                truckstock.save(self.trucks)
            workorder.save(self.store, self.path)
            self.reload()
            self._select(wo_id)

    def print_to(self, path):
        wo_id = self._id()
        if not wo_id:
            return None
        out = self.guard(lambda: workorder.print_work_order(
            self.store, wo_id, path))
        if out:
            self.msg.setText(f"Saved {out}")
        return out

    def print_clicked(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Work order", files.path_for("Work order.pdf"),
            "PDF (*.pdf)")
        if path:
            self.print_to(path)

    def close_clicked(self):
        wo_id = self._id()
        if not wo_id:
            return
        def go():
            self._save_rates()
            return workorder.close_and_invoice(
                self.store, wo_id, notes=self.notes.toPlainText())
        inv = self.guard(go)
        if not inv:
            return
        workorder.save(self.store, self.path)
        self.reload()
        self._select(wo_id)
        self.msg.setText(f"Invoice {inv['number']}  {dmoney.fmt(inv['total'])}")

    def _on_select(self):
        wo_id = uiutil.selected_id(self.table)
        if not wo_id:
            self.profit.setText("")
            return
        wo = workorder.get(self.store, wo_id)
        got = workorder.ticket_profit(self.store, wo)
        self.profit.setText(
            f"{wo['number']}    price {dmoney.fmt(got['price'])}    "
            f"cost {dmoney.fmt(got['cost'])}    "
            f"profit {dmoney.fmt(got['profit'])}")
        self.notes.setPlainText(wo.get("notes") or "")


def open_window(parent=None):
    return uiutil.show(WorkOrderWindow(parent))
