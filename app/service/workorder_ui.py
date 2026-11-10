"""Service work order window.

open_window(parent) shows it and returns it. Wire that from the Service
ribbon. The record keeping is workorder.py.
"""
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog,
                               QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QPushButton)

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
        # every box says what it is (hands-on pass, Nov 10: two unnamed
        # lists beside Customer, and "1 / 0 / 0" beside Part)
        self.site.lineEdit().setPlaceholderText("Site")
        self.site.setMinimumWidth(130)
        self.site.setToolTip("Site: the address this call is for")
        self.site.setAccessibleName("Site")
        self.unit.setPlaceholderText("Unit")
        self.unit.setMinimumWidth(110)
        self.unit.setToolTip("Unit: the equipment at that site")
        self.unit.setAccessibleName("Unit")
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
        self.truck.setToolTip("Truck the part comes off")
        self.truck.setAccessibleName("Truck")
        for label, w in ((None, self.part), ("Qty", self.part_qty),
                         ("Cost each", self.part_cost),
                         ("Price each", self.part_price),
                         (None, self.part_sku), ("Truck", self.truck)):
            if label:
                parts.addWidget(QLabel(label))
                w.setAccessibleName(f"Part {label.lower()}"
                                    if label != "Truck" else "Truck")
            parts.addWidget(w)
        self.root.addLayout(parts)
        task_row = QHBoxLayout()
        self.task = QComboBox()
        self.member = QComboBox()
        self.member.addItems(["Customer price", "Agreement member price"])
        self.task.setAccessibleName("Flat-rate task")
        task_row.addWidget(QLabel("Flat-rate task"))
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
        # 1.2 (Nov 5): invoices go to Back Office by default; Sage or hh2
        # for clients who use them (invoice_route.py)
        from . import invoice_route
        route_row = QHBoxLayout()
        route_row.addWidget(QLabel("Invoices go to"))
        self.route = QComboBox()
        self.route.setAccessibleName("Invoices go to")
        for key, label in invoice_route.ROUTES.items():
            self.route.addItem(label, key)
        self.route.setCurrentIndex(self.route.findData(invoice_route.route()))
        self.route.currentIndexChanged.connect(
            lambda _i: invoice_route.set_route(self.route.currentData()))
        route_row.addWidget(self.route)
        # sales tax and the card fee for this ticket's invoice (Jon via
        # Chief, Nov 7); each invoice keeps the rate it was made with
        route_row.addSpacing(16)
        route_row.addWidget(QLabel("Sales tax"))
        self.tax = QComboBox()
        self.tax.setAccessibleName("Sales tax rate")
        for r in workorder.TAX_RATES:
            self.tax.addItem(workorder.tax_rate_text(r), r)
        self.tax.setCurrentIndex(self.tax.findData(
            workorder.default_tax_rate()))
        self.tax.currentIndexChanged.connect(self._payment_changed)
        route_row.addWidget(self.tax)
        self.tax_default = QPushButton("Make default")
        self.tax_default.setAutoDefault(False)
        self.tax_default.setToolTip("Use this rate for new invoices")
        self.tax_default.clicked.connect(lambda *_a:
                                         self.tax_default_clicked())
        route_row.addWidget(self.tax_default)
        self.card = QCheckBox(
            f"Paying by credit card (+{workorder.card_fee_pct()}% fee)")
        self.card.setAccessibleName("Paying by credit card")
        self.card.toggled.connect(self._payment_changed)
        route_row.addWidget(self.card)
        route_row.addStretch(1)
        self.root.addLayout(route_row)
        # 1.2 phase 3 (Nov 5): field paperwork for the selected ticket
        self.buttons(("Phone ticket (PDF)…", self.ticket_clicked),
                     ("Read back ticket…", self.readback_clicked),
                     ("Checklist…", self.checklist_clicked),
                     ("Leave-behind report…", self.leave_clicked),
                     ("Certificate…", self.cert_clicked),
                     ("Permit…", self.permit_clicked))
        self.buttons(("Send invoices…", self.send_clicked),
                     ("Reverse selected invoice in Back Office…",
                      self.reverse_clicked))
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
                         wo["complaint"], wo["tech"],
                         wo["status"] + (f" - callback ({wo['callback_of']})"
                                         if wo.get("callback_of") else ""),
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
            self._said(wo_id, f"Added {self.hours.text() or '0'} hr "
                       f"for {self.tech.text() or 'the tech'}.")

    def _said(self, wo_id, what):
        """The message line after a change: what was done and the ticket's
        price now (Chief's estimator test, Nov 7: it kept saying "Ticket
        opened." after time and parts were added)."""
        try:
            wo = workorder.get(self.store, wo_id)
            prof = workorder.ticket_profit(self.store, wo)
            self.msg.setText(f"{wo['number']}: {what} Ticket now "
                             f"{dmoney.fmt(prof['price'])}.")
        except Exception:                                 # noqa: BLE001
            self.msg.setText(what)

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
            self._said(wo_id, f"Added {self.part_qty.text() or '1'} x "
                       f"{self.part.text()}.")

    def no_parts_clicked(self):
        wo_id = self._id()
        if not wo_id:
            return
        if self.guard(lambda: workorder.no_parts(self.store, wo_id)):
            workorder.save(self.store, self.path)
            self.reload()
            self._select(wo_id)
            self._said(wo_id, "Marked no parts used.")

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
            self._said(wo_id, "Added the book's time and parts.")

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

    def close_warnings(self, wo):
        """Permit not finaled, unit under warranty (1.2 phase 5). Shown,
        never blocking: the office decides."""
        from . import permits, warranty
        return [t for t in (permits.close_warning(wo),
                            warranty.billing_warning(wo, self.records))
                if t]

    def close_clicked(self, _checked=False, ask=None):
        wo_id = self._id()
        if not wo_id:
            return
        warn = self.close_warnings(workorder.get(self.store, wo_id))
        if warn:
            if ask is None:
                from PySide6.QtWidgets import QMessageBox
                ask = lambda t: QMessageBox.question(          # noqa: E731
                    self, "Close and invoice", t + "\n\nClose anyway?",
                    QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes
            if not ask("\n\n".join(warn)):
                self.msg.setText("Not closed. " + " ".join(warn))
                return
        def go():
            self._save_rates()
            return workorder.close_and_invoice(
                self.store, wo_id, notes=self.notes.toPlainText(),
                tax_rate=self.tax.currentData(),
                card=self.card.isChecked())
        inv = self.guard(go)
        if not inv:
            return
        workorder.save(self.store, self.path)
        self.reload()
        self._select(wo_id)
        miss = workorder.missing_company()
        self.msg.setText(
            f"Invoice {inv['number']}  {dmoney.fmt(inv['total'])}" +
            (f"  - the invoice has no company {' or '.join(miss)} to pay "
             "to: fill in the Company Profile" if miss else ""))

    def permit_clicked(self, _checked=False):
        wo_id = self._picked()
        if not wo_id:
            return None
        from . import permit_ui
        self._permit = permit_ui.PermitDialog(self.store, wo_id, self)
        self._permit.saved.connect(lambda: workorder.save(self.store,
                                                          self.path))
        return uiutil.show(self._permit)

    def send_clicked(self, _checked=False, target=None, ask=None,
                     start=None):
        """Every closed ticket's invoice not yet sent, to the route picked
        above, after a preview. Held invoices are listed, never sent."""
        from PySide6.QtWidgets import QMessageBox
        from . import invoice_route
        r = self.route.currentData() or invoice_route.route()
        if r == "sage":
            return self.sage_clicked(path=target, ask=ask)
        pv = invoice_route.preview(self.store, r)
        text = (f"{pv['invoices']} invoice(s), total "
                f"{dmoney.fmt(pv['total'])}, to "
                f"{invoice_route.ROUTES[r]}.")
        if pv["held"]:
            text += "\nHeld back: " + "; ".join(f"{n}: {w}"
                                                  for n, w in pv["held"][:6])
        if not pv["invoices"]:
            self.msg.setText("Nothing new to send. " + text)
            return None
        if ask is None:
            ask = lambda t: QMessageBox.question(          # noqa: E731
                self, "Send invoices", t + "\n\nSend them?") == \
                QMessageBox.Yes
        if not ask(text):
            return None
        if r == "hh2" and target is None:
            target = QFileDialog.getExistingDirectory(
                self, "Folder for hh2 upload", files.path_for(""))
            if not target:
                return None
        try:
            out = invoice_route.send(self.store, r, target, start=start)
        except (ValueError, RuntimeError) as e:
            self.msg.setText(str(e))
            return None
        workorder.save(self.store, self.path)
        if r == "backoffice":
            self.msg.setText(f"Sent to Back Office: {', '.join(out['sent'])}."
                             " Post them there: Billing > Bring In "
                             "QuantiSheet Service Invoices.")
        else:
            self.msg.setText(f"hh2 folder: {out['folder']} - upload the "
                             "invoice PDFs in hh2 (AP > Document Flow > "
                             "Document Acceptance). Manifest and reverse "
                             "file are in the folder.")
        return out

    def reverse_clicked(self, _checked=False, why=None, start=None):
        """Back the selected ticket's invoice out of Back Office."""
        from PySide6.QtWidgets import QInputDialog
        from . import invoice_route
        wo_id = uiutil.selected_id(self.table)
        wo = workorder.get(self.store, wo_id) if wo_id else None
        if not wo or not wo.get("invoice_id"):
            self.msg.setText("Pick a ticket that has an invoice.")
            return None
        if why is None:
            why, ok = QInputDialog.getText(self, "Reverse invoice",
                                           "Why is it being reversed?")
            if not ok:
                return None
        try:
            snap = invoice_route.reverse_backoffice(
                self.store, wo["invoice_id"], why, start=start)
        except (ValueError, RuntimeError) as e:
            self.msg.setText(str(e))
            return None
        workorder.save(self.store, self.path)
        self.msg.setText("Reversal sent to Back Office - bring it in there "
                         "the same way; it voids the posted invoice.")
        return snap

    # ---- field paperwork (1.2 phase 3) -------------------------------------
    def _picked(self):
        wo_id = uiutil.selected_id(self.table)
        if not wo_id:
            self.msg.setText("Pick a ticket in the list.")
        return wo_id

    def ticket_clicked(self, _checked=False, path=None):
        from . import ticket_pdf
        wo_id = self._picked()
        if not wo_id:
            return None
        wo = workorder.get(self.store, wo_id)
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Phone ticket", files.path_for(
                    f"{wo['number']} ticket.pdf"), "PDF (*.pdf)")
        if not path:
            return None
        out = self.guard(lambda: ticket_pdf.make(self.store, wo_id, path))
        if not out:
            return None
        workorder.save(self.store, self.path)
        self.msg.setText(f"Ticket QS-{out['token']} saved: {out['path']} - "
                         "send it to the tech's phone; it fills in with no "
                         "signal.")
        return out

    def readback_clicked(self, _checked=False, path=None, ask=None):
        from PySide6.QtWidgets import QMessageBox
        from . import ticket_pdf
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Returned ticket", files.path_for(""), "PDF (*.pdf)")
        if not path:
            return None
        ret = self.guard(lambda: ticket_pdf.read(self.store, path))
        if not ret:
            return None
        if ask is None:
            def ask(t, title="Read back ticket"):
                return QMessageBox.question(self, title, t) == \
                    QMessageBox.Yes
        got = self.guard(lambda: ticket_pdf._entries(ret["values"]))
        if got is None:
            return None
        times, parts = got
        text = (f"Ticket QS-{ret['token']} for {ret['number']}: "
                f"{len(times)} time entr(ies), {len(parts)} part(s). "
                f"{ret['note']}\n\nAdd them to the work order?")
        if not ask(text):
            return None
        try:
            got = ticket_pdf.apply(self.store, ret)
        except ticket_pdf.TicketConflict as e:
            if not ask(str(e) + "\n\nReplace the first return with this "
                       "one?", "Ticket came back twice"):
                self.msg.setText("Kept the first return.")
                return None
            got = self.guard(lambda: ticket_pdf.apply(self.store, ret,
                                                      replace=True))
        except ticket_pdf.TicketError as e:
            self.msg.setText(str(e))
            return None
        if got is None:
            return None
        workorder.save(self.store, self.path)
        self.reload()
        self.msg.setText("Same entries as before - nothing added." if
                         got["same"] else
                         f"Added {len(got['added_time'])} time and "
                         f"{len(got['added_parts'])} part line(s) from the "
                         "ticket. Parts from a ticket need a price.")
        return got

    def checklist_clicked(self, _checked=False):
        from . import checklists_ui
        wo_id = self._picked()
        if not wo_id:
            return None
        self._checklist = checklists_ui.open_window(self, wo_id)
        return self._checklist

    def leave_clicked(self, _checked=False, path=None):
        from . import leave_behind
        wo_id = self._picked()
        if not wo_id:
            return None
        wo = workorder.get(self.store, wo_id)
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Leave-behind report", files.path_for(
                    f"{wo['number']} visit report.pdf"), "PDF (*.pdf)")
        if not path:
            return None
        out = self.guard(lambda: leave_behind.pdf(self.store, wo_id, path))
        if out:
            self.msg.setText(f"Saved {out} - for the customer.")
        return out

    def cert_clicked(self, _checked=False, kind=None, path=None):
        from PySide6.QtWidgets import QInputDialog
        from . import certificates
        wo_id = self._picked()
        if not wo_id:
            return None
        wo = workorder.get(self.store, wo_id)
        if kind is None:
            names = list(certificates.KINDS.values())
            name, ok = QInputDialog.getItem(self, "Certificate", "Which one?",
                                            names, 0, False)
            if not ok:
                return None
            kind = next(k for k, v in certificates.KINDS.items()
                        if v == name)
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Certificate", files.path_for(
                    f"{wo['number']} {certificates.KINDS[kind]}.pdf"),
                "PDF (*.pdf)")
        if not path:
            return None
        out = self.guard(lambda: certificates.pdf(kind, path, wo=wo))
        try:            # the blanks go in the Form Library too (once)
            certificates.install_templates()
        except Exception:                                 # noqa: BLE001
            pass
        if out:
            self.msg.setText(f"Saved {out} - fill it in (fillable PDF).")
        return out

    def sage_clicked(self, _checked=False, path=None, ask=None):
        """Every invoice not yet sent, to a CSV for Sage's AR import,
        after a preview (sage_ar.py). A reverse file is written too."""
        from PySide6.QtWidgets import QMessageBox
        from . import sage_ar
        rws, held = sage_ar.rows(self.store)
        pv = sage_ar.preview(rws, held)
        text = (f"{pv['invoices']} invoice(s), {pv['lines']} line(s), "
                f"total {dmoney.fmt(pv['total'])}.")
        if held:
            text += "\nHeld back: " + "; ".join(f"{n}: {w}"
                                                 for n, w in held[:6])
        if not rws:
            self.msg.setText("Nothing new to send to Sage. " + text)
            return None
        if ask is None:
            ask = lambda t: QMessageBox.question(          # noqa: E731
                self, "Send to Sage", t + "\n\nWrite the Sage file?") == \
                QMessageBox.Yes
        if not ask(text):
            return None
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Sage invoice file", files.path_for(
                    "Service invoices for Sage.csv"), "CSV (*.csv)")
            if not path:
                return None
        out = self.guard(lambda: sage_ar.export(self.store, path))
        if not out:
            return None
        workorder.save(self.store, self.path)
        self.msg.setText(f"Sage file: {out['file']} ({text}) - and a reverse "
                         f"file to back it out: {out['reverse']}")
        return out

    def _on_select(self):
        wo_id = uiutil.selected_id(self.table)
        if not wo_id:
            self.profit.setText("")
            return
        wo = workorder.get(self.store, wo_id)
        got = workorder.ticket_profit(self.store, wo)
        self._profit_line = (
            f"{wo['number']}    price {dmoney.fmt(got['price'])}    "
            f"cost {dmoney.fmt(got['cost'])}    "
            f"profit {dmoney.fmt(got['profit'])}")
        self.profit.setText(self._profit_line)
        self.notes.setPlainText(wo.get("notes") or "")
        self._loading = True
        try:
            r = wo.get("tax_rate")
            i = self.tax.findData(r if r not in (None, "") else
                                  workorder.default_tax_rate())
            if i >= 0:
                self.tax.setCurrentIndex(i)
            self.card.setChecked(bool(wo.get("card")))
        finally:
            self._loading = False
        self._show_amount_due(wo)

    def _payment_changed(self, *_):
        """The tax rate or card choice changed: kept on the open ticket
        (an invoiced one keeps what it was invoiced with)."""
        if getattr(self, "_loading", False):
            return
        wo_id = uiutil.selected_id(self.table) if hasattr(self, "table") \
            else None
        if not wo_id:
            return
        wo = workorder.get(self.store, wo_id)
        if wo.get("invoice_id"):
            return
        workorder.set_payment(self.store, wo_id, self.tax.currentData(),
                              self.card.isChecked())
        workorder.save(self.store, self.path)
        self._on_select()

    def _show_amount_due(self, wo):
        """The ticket line, then what the invoice would come to. Replaced
        each time, never added to (Chief's re-test, Nov 7: toggling the
        card fee piled up old totals)."""
        base = getattr(self, "_profit_line", "")
        if wo.get("invoice_id"):
            self.profit.setText(base)
            return
        try:
            m = workorder.invoice_money(self.store, wo)
        except ArithmeticError:
            self.profit.setText(base)
            return
        bits = [f"subtotal {dmoney.fmt(m['subtotal'])}"]
        if m["discount"]:
            bits.append(f"member discount -{dmoney.fmt(m['discount'])}")
        bits.append(f"tax {dmoney.fmt(m['tax'])}")
        if m["card"]:
            bits.append(f"card fee {dmoney.fmt(m['card_fee'])}")
        bits.append(f"amount due {dmoney.fmt(m['total'])}")
        self.profit.setText(base + "\n" + "    ".join(bits))

    def tax_default_clicked(self):
        from .. import settings
        settings.set("service_tax_rate", self.tax.currentData())
        self.msg.setText(f"New invoices start at "
                         f"{workorder.tax_rate_text(self.tax.currentData())}"
                         " sales tax.")


def open_window(parent=None):
    return uiutil.show(WorkOrderWindow(parent))
