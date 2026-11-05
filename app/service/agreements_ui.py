"""Service agreements window. open_window(parent) shows it."""
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QLineEdit

from .. import dmoney
from ..estimating import service as records_api
from . import agreements, files, uiutil, workorder


class AgreementsWindow(uiutil.Desk):
    def __init__(self, parent=None):
        super().__init__("Service Agreements", parent)
        self.path = agreements.default_path()
        self.orders_path = workorder.default_path()
        row = QHBoxLayout()
        self.customer = QLineEdit()
        self.customer.setPlaceholderText("Customer")
        self.site = QLineEdit()
        self.site.setPlaceholderText("Site")
        self.price = QLineEdit()
        self.price.setPlaceholderText("Price")
        self.visits = QLineEdit("2")
        self.renewal = QLineEdit()
        self.renewal.setPlaceholderText("Renewal YYYY-MM-DD")
        for w in (self.customer, self.site, self.price, self.visits,
                  self.renewal):
            row.addWidget(w)
        self.root.addLayout(row)
        self.buttons(("Add agreement", self.add_clicked),
                     ("Create due visits", self.due_clicked),
                     ("Print summary", self.print_clicked))
        self.table = uiutil.table(
            ["Number", "Customer", "Site", "Price", "Visits / year",
             "Renewal", "Warning", "Profit"])
        self.root.addWidget(self.table, 1)
        self.warn = QLabel("")
        self.warn.setWordWrap(True)
        self.root.addWidget(self.warn)
        self.finish()
        self.reload()

    def reload(self):
        self.store = agreements.load(self.path)
        self.orders = workorder.load(self.orders_path)
        today_warnings = {w["id"]: w for w in agreements.renewal_warnings(
            self.store)}
        rows, ids = [], []
        for agr in self.store["agreements"]:
            got = agreements.profit(agr, self.orders)
            warn = today_warnings.get(agr["id"])
            band = ""
            if warn:
                band = ("Overdue" if warn["band"] == "overdue"
                        else f"{warn['band']} days")
            rows.append([agr["number"], agr["customer"], agr["site"],
                         dmoney.fmt(agr["price"]), agr["visits_per_year"],
                         agr["renewal"], band, dmoney.fmt(got["profit"])])
            ids.append(agr["id"])
        uiutil.fill(self.table, rows, ids)
        lines = []
        for w in agreements.renewal_warnings(self.store):
            if w["band"] == "overdue":
                lines.append(f"{w['number']} {w['customer']} renewal is overdue")
            else:
                lines.append(f"{w['number']} {w['customer']} renews in "
                             f"{w['days_left']} days ({w['band']}-day warning)")
        self.warn.setText("\n".join(lines) or "No renewal inside 90 days.")

    def add_clicked(self):
        def go():
            return agreements.add(
                self.store, self.customer.text(), self.price.text(),
                self.visits.text(), self.renewal.text(),
                site=self.site.text(), records=records_api.load())
        if self.guard(go):
            agreements.save(self.store, self.path)
            self.reload()
            self.msg.setText("Agreement saved.")

    def due_clicked(self):
        def go():
            return agreements.create_due_work_orders(
                self.store, self.orders, records_api.load())
        ids = self.guard(go)
        if ids is None:
            return
        workorder.save(self.orders, self.orders_path)
        self.reload()
        self.msg.setText(f"{len(ids)} planned visit(s) opened.")

    def print_to(self, path):
        out = self.guard(lambda: agreements.summary_pdf(
            self.store, self.orders, path))
        if out:
            self.msg.setText(f"Saved {out}")
        return out

    def print_clicked(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Agreements", files.path_for("Service agreements.pdf"),
            "PDF (*.pdf)")
        if path:
            self.print_to(path)


def open_window(parent=None):
    return uiutil.show(AgreementsWindow(parent))
