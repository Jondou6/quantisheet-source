"""Daily pre-task plan (JHA). Copy the previous plan forward and
collect crew signatures. The sheet is a PDF on this PC.
"""
from __future__ import annotations

import json

from .. import clock, jobs
from . import pdfutil, schema
from .safety import _strokes


class JhaError(ValueError):
    pass


def add_plan(office, plan_date, job_id, task, hazards, controls) -> int:
    schema.need(office, "time.edit", record_type="jha", record_id=plan_date)
    if not str(task).strip():
        raise JhaError("Name the task.")
    schema.ensure(office.db)
    with office.db.tx():
        pid = office.db.insert(
            "jha_plans", plan_date=str(plan_date), job_id=job_id,
            task=str(task).strip(), hazards=hazards or "",
            controls=controls or "", copied_from=None)
        office.audit("create", "jha", pid, None,
                     {"date": str(plan_date), "task": task})
    return pid


def get_plan(office, pid) -> dict:
    schema.ensure(office.db)
    row = office.db.get("jha_plans", pid)
    if not row or row.get("deleted"):
        raise JhaError("That pre-task plan is not on file.")
    return row


def for_job(office, job_id, plan_date=None) -> list[dict]:
    schema.ensure(office.db)
    if plan_date:
        return office.db.rows(
            "SELECT * FROM jha_plans WHERE job_id = ? AND plan_date = ? AND "
            "deleted = 0 ORDER BY id", (job_id, str(plan_date)))
    return office.db.rows("SELECT * FROM jha_plans WHERE job_id = ? AND "
                          "deleted = 0 ORDER BY plan_date, id", (job_id,))


def update_plan(office, plan_id, task, hazards, controls) -> None:
    """Change a plan's task, hazards and controls (signatures stay)."""
    schema.need(office, "time.edit", record_type="jha", record_id=plan_id)
    before = get_plan(office, plan_id)
    if not str(task).strip():
        raise JhaError("Name the task.")
    with office.db.tx():
        office.db.update("jha_plans", plan_id, task=str(task).strip(),
                         hazards=hazards or "", controls=controls or "")
        office.audit("update", "jha", plan_id,
                     {"task": before.get("task")}, {"task": str(task).strip()})


def copy_yesterday(office, job_id, onto_date) -> int:
    """Copy the latest plan for this job from before `onto_date`
    (yesterday when the crew files every day). Signatures are not copied."""
    schema.need(office, "time.edit", record_type="jha", record_id=onto_date)
    schema.ensure(office.db)
    prev = office.db.one(
        "SELECT * FROM jha_plans WHERE job_id = ? AND plan_date < ? AND "
        "deleted = 0 ORDER BY plan_date DESC, id DESC LIMIT 1",
        (job_id, str(onto_date)))
    if not prev:
        raise JhaError("No earlier pre-task plan to copy.")
    with office.db.tx():
        pid = office.db.insert(
            "jha_plans", plan_date=str(onto_date), job_id=job_id,
            task=prev["task"], hazards=prev["hazards"],
            controls=prev["controls"], copied_from=prev["id"])
        office.audit("copy", "jha", pid, None,
                     {"from": prev["plan_date"], "onto": str(onto_date)})
    return pid


def sign(office, plan_id, name, strokes) -> int:
    schema.need(office, "time.edit", record_type="jha", record_id=plan_id)
    get_plan(office, plan_id)
    if not str(name).strip():
        raise JhaError("The signer needs a name.")
    drawn = _strokes(strokes)
    with office.db.tx():
        sid = office.db.insert("jha_signatures", plan_id=plan_id,
                               name=str(name).strip(), signature=drawn,
                               signed_at=clock.iso_now())
        office.audit("sign", "jha", plan_id, None, {"name": name})
    return sid


def signatures(office, plan_id) -> list[dict]:
    get_plan(office, plan_id)
    rows = office.db.rows("SELECT * FROM jha_signatures WHERE plan_id = ? AND "
                          "deleted = 0 ORDER BY id", (plan_id,))
    for r in rows:
        raw = r.get("signature")
        if isinstance(raw, str) and raw:
            try:
                r["signature"] = json.loads(raw)
            except ValueError:
                r["signature"] = []
    return rows


def pdf(office, plan_id, path=None) -> str:
    schema.need(office, "time.edit", record_type="jha", record_id=plan_id)
    import fitz
    plan = get_plan(office, plan_id)
    path = path or pdfutil.out_path(office, f"jha-{plan['plan_date']}.pdf")
    from .. import fileguard
    path = fileguard.write_target(path)
    j = jobs.job(office, plan["job_id"]) if plan["job_id"] else None
    doc = fitz.open()
    try:
        page = doc.new_page(width=612, height=792)
        y = pdfutil.draw_header(office, page, "Daily pre-task plan")
        pdfutil.text(page, 54, y, "Date", 9, True)
        pdfutil.text(page, 140, y, plan["plan_date"], 9)
        y += 14
        if j:
            pdfutil.text(page, 54, y, "Job", 9, True)
            pdfutil.text(page, 140, y, f"{j['number']} {j['name']}", 9)
            y += 14
        pdfutil.text(page, 54, y, "Task", 9, True)
        pdfutil.text(page, 140, y, plan["task"], 9)
        y += 18
        pdfutil.text(page, 54, y, "Hazards", 9, True)
        y += 12
        pdfutil.text(page, 54, y, (plan["hazards"] or "")[:500], 9)
        y += 28
        pdfutil.text(page, 54, y, "Controls", 9, True)
        y += 12
        pdfutil.text(page, 54, y, (plan["controls"] or "")[:500], 9)
        y += 28
        pdfutil.text(page, 54, y, "Crew signatures", 9, True)
        y += 16
        for sig in signatures(office, plan_id):
            pdfutil.text(page, 54, y + 12, sig["name"], 9)
            box = fitz.Rect(200, y, 420, y + 28)
            page.draw_rect(box, color=(0.6, 0.6, 0.6), width=0.4)
            pdfutil.strokes(page, box, sig["signature"])
            y += 36
        doc.save(path)
    finally:
        doc.close()
    return path
