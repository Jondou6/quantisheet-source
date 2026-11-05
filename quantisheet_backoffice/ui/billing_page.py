"""Billing > Contract (P1-10): contract summary, read-only schedule of
values and change orders from the QuantiSheet snapshot."""
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from .. import billing, cents
from .common import heading, table


class ContractPage(QWidget):
    def __init__(self, office, job_id, parent=None):
        super().__init__(parent)
        self.office, self.job_id = office, job_id
        lay = QVBoxLayout(self)
        s = billing.contract_summary(office, job_id)
        lay.addWidget(heading("Contract"))
        lay.addWidget(QLabel(
            f"Original {cents.fmt(s['original'])}   Executed changes "
            f"{cents.fmt(s['executed_changes'])}   Contract to date "
            f"{cents.fmt(s['contract_sum_to_date'])}   Pending "
            f"{cents.fmt(s['pending_changes'])}   Billed to date "
            f"{cents.fmt(s['billed_to_date'])}   Retainage held "
            f"{cents.fmt(s['retainage_held'])}"))
        self.note = QLabel("The schedule of values and change orders come "
                           "from QuantiSheet; to change them, "
                           f"{billing.EDIT_IN_QS}, then re-import.")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        self.sov_table = table(
            ["Item", "Cost code", "Description", "Scheduled", "Status"],
            [(r["item"], r["cost_code"], r["description"], r["scheduled"],
              r["status"]) for r in billing.sov_view(office, job_id)],
            money_cols=(3,))
        lay.addWidget(self.sov_table)
        ch = billing.changes_view(office, job_id)
        rows = [(c.get("co") or c.get("id"), c.get("title", ""),
                 c.get("stage", "").upper(),
                 billing.change_amount(c))
                for c in ch["executed"] + ch["pending"]]
        self.co_table = table(["No.", "Title", "Stage", "Amount"], rows,
                              money_cols=(3,))
        lay.addWidget(self.co_table)
