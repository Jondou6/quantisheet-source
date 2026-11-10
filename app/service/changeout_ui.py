"""Changeout proposal window (1.2 phase 6, #11).

Pick the site and the unit being replaced and the outside designer's
load report (warns when there isn't one), fill in the equipment for
Good / Better / Best and pick the pricebook tasks that price each one;
the permit fee and duct changes go on every option. Print the proposal; when the customer signs,
the choice becomes a work order with the permit on it; when it's in,
Installed adds the unit to the records and starts the warranty
registration countdown. open_window(parent).
"""
import datetime as dt

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox,
                               QFileDialog,
                               QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QVBoxLayout)

from .. import dmoney
from ..estimating import service as records_api
from . import (agreements, changeout, files, gbb, loadcalc, pricebook,
               uiutil, warranty, workorder)


class ChangeoutWindow(uiutil.Desk):
    def __init__(self, parent=None, today=None):
        super().__init__("Changeout Proposal", parent)
        self.today = today or dt.date.today()
        self.path = gbb.default_path()
        top = QFormLayout()
        self.site = QComboBox()
        self.site.setAccessibleName("Site")
        self.unit = QComboBox()
        self.unit.setAccessibleName("Unit being replaced")
        self.calc = QComboBox()
        self.calc.setAccessibleName("Load report")
        self.permit_req = QCheckBox("Permit required")
        self.permit_req.setChecked(True)
        self.permit_fee = QLineEdit()
        self.permit_fee.setPlaceholderText("Permit fee")
        self.permit_fee.setAccessibleName("Permit fee")
        prow = QHBoxLayout()
        prow.addWidget(self.permit_req)
        prow.addWidget(self.permit_fee)
        self.duct = QLineEdit()
        self.duct.setPlaceholderText("Duct changes (what)")
        self.duct.setAccessibleName("Duct changes")
        self.duct_price = QLineEdit()
        self.duct_price.setPlaceholderText("Price")
        self.duct_price.setAccessibleName("Duct changes price")
        drow = QHBoxLayout()
        drow.addWidget(self.duct, 3)
        drow.addWidget(self.duct_price, 1)
        self.notes = QLineEdit()
        self.notes.setAccessibleName("Proposal notes")
        top.addRow("Site", self.site)
        top.addRow("Replacing", self.unit)
        top.addRow("Load report", self.calc)
        top.addRow("Permit", prow)
        top.addRow("Duct changes", drow)
        top.addRow("Notes", self.notes)
        self.root.addLayout(top)
        self.size_lbl = QLabel("")
        self.size_lbl.setWordWrap(True)
        self.root.addWidget(self.size_lbl)
        cols = QHBoxLayout()
        self.eq, self.lists = {}, {}
        for name in gbb.CHOICES:
            box = QVBoxLayout()
            box.addWidget(QLabel(name))
            fields = {}
            for key, ph in (("brand", "Brand"), ("model", "Model"),
                            ("tons", "Tons"),
                            ("efficiency", "Efficiency (e.g. 16 SEER2)"),
                            ("warranty", "Warranty"), ("line", "Model line")):
                ed = QLineEdit()
                ed.setPlaceholderText(ph)
                ed.setAccessibleName(f"{name} {ph}")
                box.addWidget(ed)
                fields[key] = ed
            lw = QListWidget()
            lw.setSelectionMode(QAbstractItemView.MultiSelection)
            lw.setAccessibleName(f"{name} pricebook tasks")
            box.addWidget(lw)
            cols.addLayout(box)
            self.eq[name], self.lists[name] = fields, lw
        self.root.addLayout(cols, 2)
        self.buttons(("Save proposal", self.save_clicked),
                     ("Print proposal…", self.print_clicked))
        self.table = uiutil.table(["Proposal", "Date", "Customer", "Site",
                                   "Options", "Status", "Work order"])
        self.table.setAccessibleName("Changeout proposals")
        self.root.addWidget(self.table, 1)
        act = QHBoxLayout()
        self.pick = QComboBox()
        self.pick.setAccessibleName("Signed choice")
        for name in gbb.CHOICES:
            self.pick.addItem(name, name)
        self.signer = QLineEdit()
        self.signer.setPlaceholderText("Signed by")
        self.signer.setAccessibleName("Signed by")
        self.serial = QLineEdit()
        self.serial.setPlaceholderText("New serial #")
        self.serial.setAccessibleName("New serial number")
        self.installed = QLineEdit(self.today.isoformat())
        self.installed.setAccessibleName("Install date")
        for lbl, w in (("Customer chose", self.pick), ("", self.signer),
                       ("Installed", self.installed), ("", self.serial)):
            if lbl:
                act.addWidget(QLabel(lbl))
            act.addWidget(w)
        self.root.addLayout(act)
        self.buttons(("Signed - make work order", self.accept_clicked),
                     ("Declined", self.decline_clicked),
                     ("Installed - add to records", self.install_clicked))
        self.finish()
        self.site.currentIndexChanged.connect(self._fill_units)
        self.calc.currentIndexChanged.connect(self._show_size)
        self.reload()

    # ---- data -------------------------------------------------------------
    def reload(self):
        self.store = gbb.load(self.path)
        self.records = records_api.load()
        self.book = pricebook.load()
        self.calcs = loadcalc.load()
        keep = self.site.currentData()
        self.site.blockSignals(True)
        self.site.clear()
        self.site.addItem("", "")
        for p in self.records.get("properties", []):
            self.site.addItem(f"{p.get('customer') or ''} - "
                              f"{p.get('name') or ''}", p["id"])
        i = self.site.findData(keep)
        self.site.setCurrentIndex(max(i, 0))
        self.site.blockSignals(False)
        self._fill_units()
        self.calc.clear()
        self.calc.addItem("(none)", "")
        for j in self.calcs["jobs"]:
            self.calc.addItem(loadcalc.summary(j), j["id"])
        for name, lw in self.lists.items():
            sel = {i.data(Qt.UserRole) for i in lw.selectedItems()}
            lw.clear()
            for t in sorted(self.book["tasks"], key=lambda t: (
                    t.get("tier") != name, t["name"].lower())):
                it = QListWidgetItem(
                    f"{t['name']}  {dmoney.fmt(t['customer_price'])}")
                it.setData(Qt.UserRole, t["id"])
                lw.addItem(it)
                it.setSelected(t["id"] in sel)
        rows, ids = [], []
        for q in self.store["quotes"]:
            if q.get("kind") != "changeout":
                continue
            rows.append([q["number"], q["date"], q["customer"], q["site"],
                         ", ".join(f"{c['name']} {dmoney.fmt(c['total'])}"
                                   for c in q["choices"]),
                         q["status"] + (" - installed" if q["changeout"].get(
                             "installed") else ""), q["work_order"]])
            ids.append(q["id"])
        uiutil.fill(self.table, rows, ids)

    def _prop(self):
        pid = self.site.currentData()
        return next((p for p in self.records.get("properties", [])
                     if p["id"] == pid), None)

    def _fill_units(self):
        pid = self.site.currentData()
        self.unit.clear()
        self.unit.addItem("", "")
        for eq in self.records.get("equipment", []):
            if pid and eq.get("property") == pid and not eq.get("replaced"):
                self.unit.addItem(" ".join(p for p in (
                    eq.get("kind"), eq.get("make"), eq.get("model"),
                    eq.get("serial")) if p), eq["id"])

    def _calc(self):
        cid = self.calc.currentData()
        return loadcalc.get(self.calcs, cid) if cid else None

    def _show_size(self):
        self.size_lbl.setText(loadcalc.status(self._calc()))

    def choices(self):
        return {n: [i.data(Qt.UserRole) for i in lw.selectedItems()]
                for n, lw in self.lists.items()}

    def equipment(self):
        return {n: {k: ed.text() for k, ed in f.items()}
                for n, f in self.eq.items()}

    # ---- actions ----------------------------------------------------------
    def save_clicked(self):
        prop = self._prop()
        if prop is None:
            self.msg.setText("Pick the site (add it to the service records "
                             "first).")
            return None
        qid = self.guard(lambda: changeout.create(
            self.store, self.book, prop.get("customer") or prop.get("name"),
            prop.get("name") or "", self.choices(), self.equipment(),
            records=self.records, equipment_id=self.unit.currentData() or "",
            existing="" if self.unit.currentData() else
            "Existing unit (not on the records)",
            agreements=agreements.load(), property_id=prop["id"],
            notes=self.notes.text(), when=self.today,
            load_job=self._calc(), permit_fee=self.permit_fee.text(),
            permit_required=self.permit_req.isChecked(),
            duct_changes=self.duct.text(),
            duct_price=self.duct_price.text()))
        if not qid:
            return None
        gbb.save(self.store, self.path)
        q = gbb.get(self.store, qid)
        self.reload()
        warn = changeout.load_warning(q)
        self.msg.setText(changeout.summary(q) + (f"  {warn}" if warn
                                                 else ""))
        return qid

    def _picked(self):
        qid = uiutil.selected_id(self.table)
        if not qid:
            self.msg.setText("Pick a proposal in the list.")
        return qid

    def print_clicked(self, _checked=False, path=None):
        qid = self._picked()
        if not qid:
            return None
        q = gbb.get(self.store, qid)
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Changeout proposal", files.path_for(
                    f"{q['number']} replacement proposal.pdf"),
                "PDF (*.pdf)")
        if not path:
            return None
        got = self.guard(lambda: changeout.proposal_pdf(q, path))
        if got is not None:
            self.msg.setText(f"Saved {path}")
        return got

    def accept_clicked(self):
        qid = self._picked()
        if not qid:
            return None
        orders = workorder.load()
        wo_id = self.guard(lambda: changeout.accept(
            self.store, qid, self.pick.currentData(), orders, self.records,
            signed_by=self.signer.text(), when=self.today))
        if not wo_id:
            return None
        workorder.save(orders)
        gbb.save(self.store, self.path)
        self.reload()
        wo = workorder.get(orders, wo_id)
        self.msg.setText(f"{wo['number']} opened with the permit on it - "
                         "pick the permit office on the work order.")
        return wo_id

    def decline_clicked(self):
        qid = self._picked()
        if not qid:
            return None
        got = self.guard(lambda: gbb.decline(self.store, qid, when=self.today))
        if got is None:
            return None
        gbb.save(self.store, self.path)
        self.reload()
        return got

    def install_clicked(self):
        qid = self._picked()
        if not qid:
            return None
        wst = warranty.load()
        eid = self.guard(lambda: changeout.install(
            self.store, qid, self.records, wst, self.installed.text(),
            serial=self.serial.text()))
        if not eid:
            return None
        records_api.save(self.records)
        warranty.save(wst)
        gbb.save(self.store, self.path)
        u = warranty.entry(wst, eid)
        self.reload()
        self.msg.setText("Added to the service records. Register with "
                         f"{u['brand']} by {u['register_by']}"
                         + ("" if u.get("verified") else
                            " (window UNVERIFIED)") + ".")
        return eid


def open_window(parent=None):
    return uiutil.show(ChangeoutWindow(parent))
