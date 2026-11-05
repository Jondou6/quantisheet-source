"""Invoices waiting on the signed-in user.

Uses the approval inbox that is already there. Approve and reject go
through ap.approve and ap.reject. Approving also burns the audit stamp
and remembers the vendor's job, cost code and approval path.
"""
from __future__ import annotations

from .. import ap, approvals, cents, jobs
from . import apstamp, pdfutil, vendmem


def coding_text(office, iid) -> str:
    rows = []
    for ln in ap.lines(office, iid):
        rows.append(f"{ln['cost_code'] or '(no code)'}  "
                    f"{cents.fmt(ln['amount'])}  {ln['description'] or ''}"
                    .rstrip())
    return "\n".join(rows)


def mine(office) -> list[dict]:
    """Invoices whose current approval step is this user."""
    out = []
    for item in approvals.inbox(office, record_type="ap_invoice"):
        iid = item["record_id"]
        inv = ap.invoice(office, iid)
        if not inv or inv.get("deleted"):
            continue
        v = ap.vendor(office, inv["vendor_id"])
        job_text = ""
        if inv["job_id"]:
            j = jobs.job(office, inv["job_id"])
            if j:
                job_text = f"{j['number']} {j['name']}".strip()
        path = inv.get("doc_path") or ""
        out.append({"invoice_id": iid, "number": inv["number"],
                    "vendor": v["name"] if v else "",
                    "invoice_no": inv["invoice_no"] or "",
                    "total": inv["total"], "job_id": inv["job_id"],
                    "job": job_text, "lines": ap.lines(office, iid),
                    "doc_path": path, "waiting": item["waiting"],
                    "coding": coding_text(office, iid),
                    "pdf_text": pdfutil.page_text(path)})
    return out


def approve(office, iid, override_reason="", gl_date=None) -> dict:
    """One step: the existing approve path, then the stamp and vendor
    memory. The approval stands even if the caller only needed the
    decision; both follow-ups run before this returns."""
    from .duties import guard
    guard(office, "ap_invoice", iid, "approve")
    req = ap.approve(office, iid, override_reason=override_reason,
                     gl_date=gl_date)
    stamped = apstamp.stamp_invoice(office, iid)
    vendmem.learn_invoice(office, iid)
    return {"request": req, "stamped": stamped}


def reject(office, iid, reason) -> None:
    ap.reject(office, iid, reason)
