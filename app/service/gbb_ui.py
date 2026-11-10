"""Good / Better / Best quotes window (1.2 phase 5, #6).

Pick pricebook tasks for each choice, save the quote, print it, and when
the customer signs one choice it becomes a flat-rate work order.
open_window(parent) shows it.
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QVBoxLayout)

from .. import dmoney
from ..estimating import service as records_api
from . import agreements, files, gbb, pricebook, uiutil, workorder


class QuotesWindow(uiutil.Desk):
    def __init__(self, parent=None):
        super().__init__("Good / Better / Best Quotes", parent)
        self.path = gbb.default_path()
        top = QHBoxLayout()
        self.customer = QLineEdit()
        self.customer.setPlaceholderText("Customer")
        self.customer.setAccessibleName("Customer")
        self.site = QLineEdit()
        self.site.setPlaceholderText("Site")
        self.site.setAccessibleName("Site")
        self.title = QLineEdit()
        self.title.setPlaceholderText("Title (Your options)")
        self.title.setAccessibleName("Quote title")
        for w in (self.customer, self.site, self.title):
            top.addWidget(w)
        self.root.addLayout(top)
        cols = QHBoxLayout()
        self.lists = {}
        for name in gbb.CHOICES:
            box = QVBoxLayout()
            box.addWidget(QLabel(name))
            lw = QListWidget()
            lw.setSelectionMode(QAbstractItemView.MultiSelection)
            lw.setAccessibleName(f"{name} tasks")
            box.addWidget(lw)
            cols.addLayout(box)
            self.lists[name] = lw
        self.root.addLayout(cols, 1)
        self.buttons(("Save quote", self.save_clicked),
                     ("Print quote…", self.print_clicked))
        self.table = uiutil.table(["Quote", "Date", "Customer", "Site",
                                   "Choices", "Status", "Work order"])
        self.table.setAccessibleName("Quotes")
        self.root.addWidget(self.table, 1)
        sign = QHBoxLayout()
        self.pick = QComboBox()
        self.pick.setAccessibleName("Signed choice")
        for name in gbb.CHOICES:
            self.pick.addItem(name, name)
        self.signer = QLineEdit()
        self.signer.setPlaceholderText("Signed by")
        self.signer.setAccessibleName("Signed by")
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("Why declined (optional)")
        self.reason.setAccessibleName("Why declined")
        sign.addWidget(QLabel("Customer chose"))
        for w in (self.pick, self.signer, self.reason):
            sign.addWidget(w)
        self.root.addLayout(sign)
        self.buttons(("Signed - make work order", self.accept_clicked),
                     ("Declined", self.decline_clicked))
        self.finish()
        self.reload()

    def reload(self):
        self.store = gbb.load(self.path)
        self.book = pricebook.load()
        for name, lw in self.lists.items():
            keep = {i.data(Qt.UserRole) for i in lw.selectedItems()}
            lw.clear()
            tasks = sorted(self.book["tasks"], key=lambda t: (
                t.get("tier") != name, t["name"].lower()))
            for t in tasks:
                it = QListWidgetItem(f"{t['name']}  "
                                     f"{dmoney.fmt(t['customer_price'])}")
                it.setData(Qt.UserRole, t["id"])
                lw.addItem(it)
                it.setSelected(t["id"] in keep)
        rows, ids = [], []
        for q in self.store["quotes"]:
            rows.append([q["number"], q["date"], q["customer"], q["site"],
                         ", ".join(f"{c['name']} {dmoney.fmt(c['total'])}"
                                   for c in q["choices"]),
                         q["status"] + (" (member)" if q["member"] else ""),
                         q["work_order"]])
            ids.append(q["id"])
        uiutil.fill(self.table, rows, ids)

    def choices(self):
        return {n: [i.data(Qt.UserRole) for i in lw.selectedItems()]
                for n, lw in self.lists.items()}

    def save_clicked(self):
        qid = self.guard(lambda: gbb.create(
            self.store, self.book, self.customer.text(), self.site.text(),
            self.choices(), agreements=agreements.load(),
            title=self.title.text()))
        if not qid:
            return None
        gbb.save(self.store, self.path)
        q = gbb.get(self.store, qid)
        self.reload()
        self.msg.setText(gbb.summary(q))
        return qid

    def _picked(self):
        qid = uiutil.selected_id(self.table)
        if not qid:
            self.msg.setText("Pick a quote in the list.")
        return qid

    def print_clicked(self, _checked=False, path=None):
        qid = self._picked()
        if not qid:
            return None
        q = gbb.get(self.store, qid)
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Quote", files.path_for(f"{q['number']}.pdf"),
                "PDF (*.pdf)")
        if not path:
            return None
        got = self.guard(lambda: gbb.save_pdf(q, path))
        if got is not None:
            self.msg.setText(f"Saved {path}")
        return got

    def accept_clicked(self):
        qid = self._picked()
        if not qid:
            return None
        orders = workorder.load()
        q = gbb.get(self.store, qid)
        if q.get("kind") == "changeout":       # puts the permit on it too
            from . import changeout
            fn = changeout.accept
        else:
            fn = gbb.accept
        wo_id = self.guard(lambda: fn(
            self.store, qid, self.pick.currentData(), orders,
            records_api.load(), signed_by=self.signer.text()))
        if not wo_id:
            return None
        workorder.save(orders)
        gbb.save(self.store, self.path)
        self.reload()
        self.msg.setText(gbb.summary(gbb.get(self.store, qid)))
        return wo_id

    def decline_clicked(self):
        qid = self._picked()
        if not qid:
            return None
        got = self.guard(lambda: gbb.decline(self.store, qid,
                                             self.reason.text()))
        if got is None:
            return None
        gbb.save(self.store, self.path)
        self.reload()
        self.msg.setText(gbb.summary(got))
        return got


def open_window(parent=None):
    return uiutil.show(QuotesWindow(parent))
