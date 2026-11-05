"""Warranty and service calls on a job that has been closed out.

The caller, the issue, photos, who it is assigned to, and the close
are kept here. A PDF is the report. Nothing is dispatched off this PC.
"""
from __future__ import annotations

import os

from .. import clock, jobs, store
from . import pdfutil, schema


class WarrantyError(ValueError):
    pass


def close_job(office, job_id, closed_on=None, note="") -> int:
    schema.need(office, "time.edit", record_type="job_closeout",
                record_id=job_id)
    if not jobs.job(office, job_id):
        raise WarrantyError("That job is not on file.")
    schema.ensure(office.db)
    day = str(closed_on or clock.today().isoformat())
    have = office.db.one("SELECT * FROM job_closeouts WHERE job_id = ? AND "
                         "deleted = 0", (job_id,))
    with office.db.tx():
        if have:
            office.db.update("job_closeouts", have["id"], closed_on=day,
                             note=note or have["note"] or "")
            cid = have["id"]
        else:
            cid = office.db.insert("job_closeouts", job_id=job_id,
                                   closed_on=day, note=note or "")
        office.audit("change", "job_closeout", cid, None,
                     {"job_id": job_id, "closed_on": day})
    return cid


def is_closed(office, job_id) -> bool:
    schema.ensure(office.db)
    return office.db.one("SELECT id FROM job_closeouts WHERE job_id = ? AND "
                         "deleted = 0", (job_id,)) is not None


def add_call(office, job_id, caller, issue, assigned="", phone="") -> int:
    schema.need(office, "time.edit", record_type="warranty_call",
                record_id=job_id)
    if not is_closed(office, job_id):
        raise WarrantyError("Close the job out before logging a warranty "
                            "or service call.")
    if not str(caller).strip() or not str(issue).strip():
        raise WarrantyError("A call needs a caller and the issue.")
    with office.db.tx():
        number = office.db.next_number("WR", "WR-{n:04d}")
        cid = office.db.insert(
            "warranty_calls", number=number, job_id=job_id,
            caller=str(caller).strip(), phone=phone or "",
            issue=str(issue).strip(), assigned=assigned or "",
            status="open", opened_on=clock.today().isoformat(),
            closed_on="", note="")
        office.audit("create", "warranty_call", cid, None,
                     {"number": number, "caller": caller})
    return cid


def add_photo(office, call_id, path, caption="") -> int:
    schema.need(office, "time.edit", record_type="warranty_call",
                record_id=call_id)
    from .. import fileguard
    fileguard.refuse_company_file(path)
    if not os.path.isfile(path):
        raise WarrantyError("That photo was not found.")
    kept = store.copy_into(office.documents_folder(), path)
    with office.db.tx():
        pid = office.db.insert("warranty_photos", call_id=call_id,
                               file_path=kept, caption=caption or "")
        office.audit("create", "warranty_photo", pid, None,
                     {"file": os.path.basename(kept)})
    return pid


def close_call(office, call_id, note="") -> None:
    schema.need(office, "time.edit", record_type="warranty_call",
                record_id=call_id)
    row = office.db.get("warranty_calls", call_id)
    if not row or row.get("deleted"):
        raise WarrantyError("That call is not on file.")
    with office.db.tx():
        office.db.update("warranty_calls", call_id, status="closed",
                         closed_on=clock.today().isoformat(),
                         note=note or row["note"] or "")
        office.audit("close", "warranty_call", call_id,
                     {"status": row["status"]}, {"status": "closed"})


def calls(office, job_id) -> list[dict]:
    schema.ensure(office.db)
    return office.db.rows("SELECT * FROM warranty_calls WHERE job_id = ? AND "
                          "deleted = 0 ORDER BY id", (job_id,))


def report_pdf(office, job_id, path=None) -> str:
    schema.need(office, "time.edit", record_type="warranty_call",
                record_id=job_id)
    import fitz
    j = jobs.job(office, job_id)
    if not j:
        raise WarrantyError("That job is not on file.")
    path = path or pdfutil.out_path(office, f"warranty-{j['number']}.pdf")
    from .. import fileguard
    path = fileguard.write_target(path)
    doc = fitz.open()
    try:
        page = doc.new_page(width=612, height=792)
        y = pdfutil.draw_header(office, page,
                                f"Warranty and service calls - {j['number']}")
        pdfutil.text(page, 54, y, j["name"] or "", 11, True)
        y += 20
        for call in calls(office, job_id):
            pdfutil.text(page, 54, y, f"{call['number']}  {call['status']}",
                         10, True)
            y += 13
            pdfutil.text(page, 54, y, f"Caller: {call['caller']}", 9)
            y += 12
            pdfutil.text(page, 54, y, f"Issue: {call['issue'][:200]}", 9)
            y += 12
            if call["assigned"]:
                pdfutil.text(page, 54, y, f"Assigned: {call['assigned']}", 9)
                y += 12
            if call["closed_on"]:
                pdfutil.text(page, 54, y, f"Closed: {call['closed_on']}", 9)
                y += 12
            for photo in office.db.rows(
                    "SELECT * FROM warranty_photos WHERE call_id = ? AND "
                    "deleted = 0", (call["id"],)):
                pdfutil.text(page, 70, y, photo["caption"] or
                             os.path.basename(photo["file_path"]), 8)
                y += 11
                if photo["file_path"] and os.path.isfile(photo["file_path"]) \
                        and y < 680:
                    try:
                        page.insert_image(fitz.Rect(70, y, 250, y + 80),
                                          filename=photo["file_path"],
                                          keep_proportion=True)
                        y += 88
                    except Exception:                     # noqa: BLE001
                        pass
            y += 8
        if not calls(office, job_id):
            pdfutil.text(page, 54, y, "No calls on this job.", 9)
        doc.save(path)
    finally:
        doc.close()
    return path
