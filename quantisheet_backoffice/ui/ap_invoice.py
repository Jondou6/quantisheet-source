"""AP Invoice screen (P1-08/09): header fields, coding lines, approval
path and warnings. Read-only for anyone without ap.edit (brief 3.1); the
engine refuses (and audits) edits regardless of what the screen shows."""
from PySide6.QtWidgets import (QDialog, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QVBoxLayout)

from .. import ap, approvals, cents
from .common import error, table


class APInvoiceDialog(QDialog):
    def __init__(self, office, iid, parent=None):
        super().__init__(parent)
        self.office, self.iid = office, iid
        inv = ap.invoice(office, iid)
        v = ap.vendor(office, inv["vendor_id"])
        self.setWindowTitle(f"AP Invoice {inv['number']}")
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self._fields = {}
        for key, label, val in (
                ("vendor", "Vendor", v["name"]),
                ("invoice_no", "Vendor invoice no.", inv["invoice_no"]),
                ("invoice_date", "Invoice date", inv["invoice_date"]),
                ("due_date", "Due date", inv["due_date"]),
                ("gl_date", "Posting date", inv["gl_date"]),
                ("total", "Total", cents.text(inv["total"])),
                ("retainage", "Retainage", cents.text(inv["retainage"] or 0)),
                ("commitment_no", "Commitment", inv["commitment_no"] or "")):
            e = QLineEdit(str(val or ""))
            self._fields[key] = e
            form.addRow(label, e)
        lay.addLayout(form)
        lay.addWidget(QLabel(f"Status: {inv['status']}"))
        req = approvals.request(office, "ap_invoice", iid)
        if req:
            lay.addWidget(QLabel(approvals.waiting_on(office, req) or
                                 req["status"]))
        for w in ap.warnings(office, iid):
            lay.addWidget(QLabel("Warning: " + w))
        self.lines = table(["Line", "Job", "Cost code", "Category",
                            "Amount", "Description"],
                           [(ln["line_no"], ln["job_id"] or "",
                             ln["cost_code"], ln["category"], ln["amount"],
                             ln["description"]) for ln in
                            ap.lines(office, iid)], money_cols=(4,))
        lay.addWidget(self.lines)
        row = QHBoxLayout()
        self.save_btn = QPushButton("Save")
        self.submit_btn = QPushButton("Submit for approval")
        self.approve_btn = QPushButton("Approve")
        self.reject_btn = QPushButton("Reject")
        for b in (self.save_btn, self.submit_btn, self.approve_btn,
                  self.reject_btn):
            row.addWidget(b)
        lay.addLayout(row)
        self.save_btn.clicked.connect(self._save)
        self.submit_btn.clicked.connect(self._submit)
        self.approve_btn.clicked.connect(self._approve)
        can_edit = office.can("ap.edit") and inv["status"] in ("Draft",
                                                              "Rejected")
        for e in self._fields.values():
            e.setReadOnly(not can_edit)
        self._fields["vendor"].setReadOnly(True)
        self.save_btn.setEnabled(can_edit)
        self.submit_btn.setEnabled(can_edit)
        can_ok = bool(req) and office.user is not None and \
            approvals.can_act(office, req, office.user["id"])
        self.approve_btn.setEnabled(can_ok)
        self.reject_btn.setEnabled(can_ok)

    def edit_buttons(self):
        return [self.save_btn, self.submit_btn, self.approve_btn,
                self.reject_btn]

    def fields(self):
        return list(self._fields.values())

    def _save(self):
        try:
            ap.save(self.office, self.iid,
                    invoice_no=self._fields["invoice_no"].text(),
                    due_date=self._fields["due_date"].text())
        except Exception as e:                            # noqa: BLE001
            error(self, e)

    def _submit(self):
        try:
            ap.submit(self.office, self.iid)
            self.accept()
        except Exception as e:                            # noqa: BLE001
            error(self, e)

    def _approve(self):
        try:
            ap.approve(self.office, self.iid)
            self.accept()
        except Exception as e:                            # noqa: BLE001
            error(self, e)
