"""Block a second capture of the same invoice (QS-020).

Same vendor and invoice number, or the same vendor and amount within
7 days, or the same file hash. An override is stored with the person
and the reason; it is not a silent skip.
"""
from __future__ import annotations

from .. import cents, clock
from . import schema

WINDOW_DAYS = 7


def is_recurring(office, vendor_id) -> bool:
    if not vendor_id:
        return False
    schema.ensure(office.db)
    row = office.db.one("SELECT recurring FROM vendor_flags WHERE "
                        "vendor_id = ? AND deleted = 0 ORDER BY id DESC "
                        "LIMIT 1", (vendor_id,))
    return bool(row and row["recurring"])


def set_recurring(office, vendor_id, on=True) -> None:
    """Same amount is normal for this vendor: only the invoice number and
    the file are checked for it. Needs AP edit rights; logged."""
    schema.need(office, "ap.edit", record_type="vendor", record_id=vendor_id)
    with office.db.tx():
        office.db.insert("vendor_flags", vendor_id=vendor_id,
                         recurring=1 if on else 0)
        office.audit("recurring bills" if on else "not recurring bills",
                     "vendor", vendor_id, None, {"who": office.who})


def find(office, vendor_id, invoice_no, total_c, invoice_date,
         doc_hash=None, exclude_id=None) -> list[str]:
    """Reasons this invoice looks like one already on file. Empty when
    it does not. `total_c` is int cents or None."""
    out = []
    if vendor_id and (invoice_no or (total_c is not None and invoice_date)):
        rows = office.db.rows(
            "SELECT * FROM ap_invoices WHERE vendor_id = ? AND "
            "status != 'Void' AND deleted = 0", (vendor_id,))
        when = clock.d(invoice_date) if invoice_date else None
        if is_recurring(office, vendor_id):
            when = None             # same amount is normal for this vendor
        for r in rows:
            if exclude_id is not None and r["id"] == exclude_id:
                continue
            if invoice_no and (r["invoice_no"] or "").strip().lower() == \
                    str(invoice_no).strip().lower():
                out.append(f"possible duplicate of {r['number']} (same "
                           f"invoice number {invoice_no})")
            elif total_c is not None and when is not None and \
                    r["total"] == total_c and \
                    abs((clock.d(r["invoice_date"]) - when).days) <= WINDOW_DAYS:
                out.append(f"possible duplicate of {r['number']} (same "
                           f"vendor and amount {cents.fmt(total_c)} within "
                           f"{WINDOW_DAYS} days)")
    if doc_hash:
        rows = office.db.rows(
            "SELECT id, number FROM ap_invoices WHERE doc_hash = ? AND "
            "status != 'Void' AND deleted = 0", (doc_hash,))
        for r in rows:
            if exclude_id is not None and r["id"] == exclude_id:
                continue
            msg = f"possible duplicate of {r['number']} (same file)"
            if msg not in out:
                out.append(msg)
    return out


def record_override(office, invoice_id, matches, why, doc_hash="") -> int:
    """Who allowed this duplicate, and why. `why` must already be non-empty."""
    schema.ensure(office.db)
    who = office.who
    uid = office.user["id"] if office.user else None
    with office.db.tx():
        rid = office.db.insert(
            "dup_overrides", invoice_id=invoice_id, doc_hash=doc_hash or "",
            who=who, user_id=uid, why=str(why).strip(), matches=list(matches))
        office.audit("duplicate override", "ap_invoice",
                     invoice_id if invoice_id is not None else "",
                     None, {"who": who, "why": str(why).strip(),
                            "matches": list(matches)})
    return rid
