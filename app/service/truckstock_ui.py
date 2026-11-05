"""Truck stock window. open_window(parent) shows it."""
from PySide6.QtWidgets import QComboBox, QFileDialog, QHBoxLayout, QLineEdit

from . import files, truckstock, uiutil


class TruckWindow(uiutil.Desk):
    def __init__(self, parent=None):
        super().__init__("Truck Stock", parent)
        self.path = truckstock.default_path()
        row = QHBoxLayout()
        self.truck_name = QLineEdit()
        self.truck_name.setPlaceholderText("Truck")
        self.tech = QLineEdit()
        self.tech.setPlaceholderText("Technician")
        self.desc = QLineEdit()
        self.desc.setPlaceholderText("Part")
        self.sku = QLineEdit()
        self.sku.setPlaceholderText("Item #")
        self.cost = QLineEdit("0")
        self.price = QLineEdit("0")
        self.minimum = QLineEdit("0")
        self.supplier = QLineEdit()
        self.supplier.setPlaceholderText("Supplier")
        for w in (self.truck_name, self.tech, self.desc, self.sku, self.cost,
                  self.price, self.minimum, self.supplier):
            row.addWidget(w)
        self.root.addLayout(row)
        put = QHBoxLayout()
        self.which = QComboBox()
        self.part = QComboBox()
        self.qty = QLineEdit("1")
        put.addWidget(self.which)
        put.addWidget(self.part)
        put.addWidget(self.qty)
        self.root.addLayout(put)
        self.buttons(("Add truck", self.add_truck_clicked),
                     ("Add catalog part", self.add_part_clicked),
                     ("Put on truck", self.receive_clicked),
                     ("Export restock list", self.export_clicked))
        self.table = uiutil.table(
            ["Truck", "Item #", "Part", "On hand", "Minimum", "Supplier"])
        self.root.addWidget(self.table, 1)
        self.restock = uiutil.table(
            ["Truck", "Part", "On hand", "Order"])
        self.root.addWidget(self.restock, 1)
        self.finish()
        self.reload()

    def reload(self):
        self.store = truckstock.load(self.path)
        self.which.clear()
        self.part.clear()
        for t in self.store["trucks"]:
            self.which.addItem(t["name"], t["id"])
        for p in self.store["parts"]:
            self.part.addItem(p["sku"] or p["desc"], p["id"])
        rows = []
        for t in self.store["trucks"]:
            for p in self.store["parts"]:
                rows.append([t["name"], p["sku"], p["desc"],
                             truckstock.on_hand(self.store, t["id"], p["id"]),
                             p["min_qty"], p["supplier"]])
        uiutil.fill(self.table, rows)
        lines = truckstock.restock_lines(self.store)
        uiutil.fill(self.restock, [[r["truck"], r["desc"], r["on_hand"],
                                    r["order_qty"]] for r in lines])

    def add_truck_clicked(self):
        if self.guard(lambda: truckstock.add_truck(
                self.store, self.truck_name.text(), self.tech.text())):
            truckstock.save(self.store, self.path)
            self.reload()

    def add_part_clicked(self):
        if self.guard(lambda: truckstock.add_part(
                self.store, self.desc.text(), self.cost.text() or "0",
                self.price.text() or "0", sku=self.sku.text(),
                supplier=self.supplier.text(),
                min_qty=self.minimum.text() or "0")):
            truckstock.save(self.store, self.path)
            self.reload()

    def receive_clicked(self):
        if not self.which.currentData() or not self.part.currentData():
            self.msg.setText("Add a truck and a part first.")
            return
        if self.guard(lambda: truckstock.receive(
                self.store, self.which.currentData(),
                self.part.currentData(), self.qty.text() or "1")):
            truckstock.save(self.store, self.path)
            self.reload()
            self.msg.setText("Stock updated.")

    def export_to(self, path):
        out = self.guard(lambda: truckstock.export_restock(self.store, path))
        if out:
            self.msg.setText(f"Saved {out}")
        return out

    def export_clicked(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Restock list", files.path_for("Truck restock.csv"),
            "CSV (*.csv);;Excel (*.xlsx)")
        if path:
            self.export_to(path)


def open_window(parent=None):
    return uiutil.show(TruckWindow(parent))
