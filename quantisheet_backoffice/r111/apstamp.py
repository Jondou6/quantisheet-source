"""Burn an approval stamp onto a copy of the invoice PDF.

The stamp carries the job, cost code, amount, approver and date. The
file that was captured is left as it was; the stamped copy is the audit
backup. Drawn into the page content, not a toggle-off annotation.
"""
from __future__ import annotations

import os

from .. import cents, clock, fileguard, jobs, store
from . import schema


class StampError(ValueError):
    pass


def _lines_text(office, iid) -> tuple[str, str]:
    from .. import ap
    inv = ap.invoice(office, iid)
    codes = []
    for ln in ap.lines(office, iid):
        if ln["cost_code"] and ln["cost_code"] not in codes:
            codes.append(ln["cost_code"])
    job_text = ""
    if inv["job_id"]:
        j = jobs.job(office, inv["job_id"])
        if j:
            job_text = f"{j['number']} {j['name']}".strip()
    return job_text, ", ".join(codes)


def stamp_invoice(office, iid) -> str:
    """Write the stamped PDF and return its path. The invoice must
    already be approved. A missing source PDF still produces a one-page
    backup with the same stamp."""
    schema.need(office, "ap.approve", "ap.edit", record_type="ap_stamp",
                record_id=iid)
    from .. import ap
    schema.ensure(office.db)
    inv = ap.invoice(office, iid)
    if inv["status"] not in ("Approved", "Exported", "Partly paid", "Paid"):
        raise StampError(f"{inv['number']} is {inv['status']}. Stamp it "
                         "after it is approved.")
    job_text, codes = _lines_text(office, iid)
    prev = office.db.one("SELECT * FROM ap_stamps WHERE invoice_id = ? AND "
                         "deleted = 0 ORDER BY id DESC LIMIT 1", (iid,))
    src = (prev or {}).get("original_path") or inv.get("doc_path") or ""
    original_hash = ""
    if src and os.path.isfile(src):
        fileguard.refuse_company_file(src)
        original_hash = store.file_hash(src)
    folder = os.path.join(office.documents_folder(), "stamps")
    os.makedirs(folder, exist_ok=True)
    dest = fileguard.safe_path(
        folder, f"{inv['number']}-approved-{clock.today().isoformat()}.pdf")
    body = _body(office, inv, job_text, codes)
    _burn(src, dest, body)
    with office.db.tx():
        office.db.insert(
            "ap_stamps", invoice_id=iid, original_path=src,
            original_hash=original_hash, stamped_path=dest,
            stamped_hash=store.file_hash(dest), job_text=job_text,
            cost_code=codes, amount=inv["total"], approver=office.who,
            stamped_on=clock.today().isoformat())
        office.audit("stamp", "ap_invoice", iid, None,
                     {"file": os.path.basename(dest), "approver": office.who,
                      "amount": inv["total"], "job": job_text,
                      "cost_code": codes})
    if src and os.path.isfile(src) and original_hash:
        if store.file_hash(src) != original_hash:
            raise StampError("The captured invoice was changed while "
                             "stamping. The original was not kept.")
    return dest


def _body(office, inv, job_text, codes) -> str:
    from .. import ap
    v = ap.vendor(office, inv["vendor_id"])
    return "\n".join([
        "APPROVED",
        f"Job: {job_text or '(no job)'}",
        f"Cost code: {codes or '(none)'}",
        f"Amount: {cents.fmt(inv['total'])}",
        f"Approver: {office.who}",
        f"Date: {clock.today().isoformat()}",
        f"Invoice: {inv['invoice_no'] or inv['number']}",
        f"Vendor: {v['name']}",
    ])


def _burn(src, dest, body) -> None:
    """Draw the stamp into a new file. `src` is only read. A failed save
    removes the partial file and leaves `src` alone."""
    import fitz
    tmp = dest + ".tmp"
    for stale in (dest, tmp):
        if os.path.exists(stale):
            os.remove(stale)
    if src and os.path.isfile(src):
        doc = fitz.open(src)
    else:
        doc = fitz.open()
        doc.new_page(width=612, height=792)
    try:
        page = doc[0]
        r = page.rect
        box = fitz.Rect(36, max(24, r.height - 156),
                        min(r.width - 36, 460), r.height - 20)
        page.draw_rect(box, color=(0.15, 0.15, 0.15), fill=(1, 1, 0.86),
                       width=1.1)
        inner = fitz.Rect(box.x0 + 8, box.y0 + 6, box.x1 - 6, box.y1 - 4)
        page.insert_textbox(inner, body, fontsize=9, fontname="helv",
                            align=0)
        doc.save(tmp, garbage=4, deflate=True)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    finally:
        doc.close()
    os.replace(tmp, dest)


def stamped_path(office, iid) -> str:
    schema.ensure(office.db)
    row = office.db.one("SELECT stamped_path FROM ap_stamps WHERE "
                        "invoice_id = ? AND deleted = 0 ORDER BY id DESC "
                        "LIMIT 1", (iid,))
    return (row or {}).get("stamped_path") or ""
