"""Crew board: which crew is on which job.

Assign a crew (the screen can drag a crew onto a job; both call
assign / move). Print the day. Prefill writes each job's daily-log
manpower and Draft time cards from the board. "Copy Yesterday's Crews"
copies the most recent earlier board onto the date you are looking at.
"""
from __future__ import annotations

import json

from .. import cents, jobs, timeentry
from . import pdfutil, schema


class CrewError(ValueError):
    pass


def assign(office, work_date, crew_id, job_id, cost_code="", hours="8",
           note="") -> int:
    schema.need(office, "time.edit", record_type="crew_board",
                record_id=work_date)
    schema.ensure(office.db)
    if not office.db.get("crews", crew_id):
        raise CrewError("That crew is not on file.")
    if not jobs.job(office, job_id):
        raise CrewError("That job is not on file.")
    have = office.db.one(
        "SELECT id FROM crew_assignments WHERE work_date = ? AND crew_id = ? "
        "AND job_id = ? AND deleted = 0",
        (str(work_date), crew_id, job_id))
    h = cents.hours(hours)
    with office.db.tx():
        if have:
            office.db.update("crew_assignments", have["id"],
                             cost_code=cost_code or "", hours=h,
                             note=note or "")
            aid = have["id"]
        else:
            aid = office.db.insert(
                "crew_assignments", work_date=str(work_date), crew_id=crew_id,
                job_id=job_id, cost_code=cost_code or "", hours=h,
                note=note or "")
        office.audit("change", "crew_board", aid, None,
                     {"date": str(work_date), "crew_id": crew_id,
                      "job_id": job_id})
    return aid


def move(office, assignment_id, job_id) -> None:
    """Drag a crew from one job to another on the same day."""
    schema.need(office, "time.edit", record_type="crew_board",
                record_id=assignment_id)
    row = office.db.get("crew_assignments", assignment_id)
    if not row or row.get("deleted"):
        raise CrewError("That assignment is not on the board.")
    if not jobs.job(office, job_id):
        raise CrewError("That job is not on file.")
    with office.db.tx():
        office.db.update("crew_assignments", assignment_id, job_id=job_id)
        office.audit("change", "crew_board", assignment_id,
                     {"job_id": row["job_id"]}, {"job_id": job_id})


def board(office, work_date) -> list[dict]:
    schema.ensure(office.db)
    rows = office.db.rows(
        "SELECT a.*, c.name AS crew, j.number AS job_number, j.name AS "
        "job_name FROM crew_assignments a JOIN crews c ON c.id = a.crew_id "
        "JOIN jobs j ON j.id = a.job_id WHERE a.work_date = ? AND "
        "a.deleted = 0 ORDER BY j.number, c.name", (str(work_date),))
    return rows


def copy_yesterday(office, onto_date) -> dict:
    """Copy the most recent earlier crew board onto `onto_date`.

    The button label is "Copy Yesterday's Crews". When the crew was last
    set out before yesterday, that day is the one copied, and the result
    says which date it came from.
    """
    schema.need(office, "time.edit", record_type="crew_board",
                record_id=onto_date)
    schema.ensure(office.db)
    prev = office.db.one(
        "SELECT work_date FROM crew_assignments WHERE deleted = 0 AND "
        "work_date < ? ORDER BY work_date DESC LIMIT 1", (str(onto_date),))
    if not prev:
        raise CrewError("No earlier crew board to copy.")
    src = prev["work_date"]
    copied = []
    with office.db.tx():
        for row in office.db.rows(
                "SELECT * FROM crew_assignments WHERE work_date = ? AND "
                "deleted = 0", (src,)):
            have = office.db.one(
                "SELECT id FROM crew_assignments WHERE work_date = ? AND "
                "crew_id = ? AND job_id = ? AND deleted = 0",
                (str(onto_date), row["crew_id"], row["job_id"]))
            if have:
                continue
            copied.append(office.db.insert(
                "crew_assignments", work_date=str(onto_date),
                crew_id=row["crew_id"], job_id=row["job_id"],
                cost_code=row["cost_code"] or "", hours=row["hours"],
                note=row["note"] or ""))
        office.audit("copy", "crew_board", onto_date, None,
                     {"from": src, "copied": len(copied)})
    return {"from": src, "copied": len(copied), "ids": copied}


def print_pdf(office, work_date, path=None) -> str:
    schema.need(office, "time.edit", record_type="crew_board",
                record_id=work_date)
    import fitz
    path = path or pdfutil.out_path(office, f"crews-{work_date}.pdf")
    from .. import fileguard
    path = fileguard.write_target(path)
    rows = board(office, work_date)
    doc = fitz.open()
    try:
        page = doc.new_page(width=612, height=792)
        y = pdfutil.draw_header(office, page, f"Crew board {work_date}")
        pdfutil.text(page, 54, y, "Crew", 9, True)
        pdfutil.text(page, 200, y, "Job", 9, True)
        pdfutil.text(page, 400, y, "Cost code", 9, True)
        pdfutil.text(page, 490, y, "Hours", 9, True)
        y += 8
        page.draw_line((54, y), (558, y), width=0.4)
        y += 14
        for r in rows:
            pdfutil.text(page, 54, y, r["crew"], 9)
            pdfutil.text(page, 200, y, f"{r['job_number']} {r['job_name']}", 9)
            pdfutil.text(page, 400, y, r["cost_code"] or "", 9)
            pdfutil.text(page, 490, y, cents.hours_text(r["hours"]), 9)
            y += 14
        if not rows:
            pdfutil.text(page, 54, y, "No crews assigned.", 9)
        doc.save(path)
    finally:
        doc.close()
    return path


def prefill(office, work_date) -> dict:
    """Draft time cards for every member, and a daily-log manpower block
    on each job. Running it again does not add a second copy."""
    schema.need(office, "time.edit", record_type="crew_board",
                record_id=work_date)
    rows = board(office, work_date)
    if not rows:
        raise CrewError("Nothing is assigned that day.")
    company = (office.company().get("name") or "").strip()
    time_ids = []
    by_job = {}
    for a in rows:
        by_job.setdefault(a["job_id"], []).append(a)
        members = office.db.rows(
            "SELECT id FROM workers WHERE crew_id = ? AND active = 1 AND "
            "deleted = 0", (a["crew_id"],))
        for w in members:
            key = (f"crewboard:{work_date}:{a['crew_id']}:{w['id']}:"
                   f"{a['job_id']}")
            if office.db.one("SELECT id FROM time_lines WHERE source_key = ? "
                             "AND deleted = 0", (key,)):
                continue
            time_ids.append(timeentry.add_line(
                office, w["id"], work_date, a["job_id"],
                a["cost_code"] or "", cents.hours_text(a["hours"]),
                note=f"Crew board {a['crew']}", source="crewboard",
                source_key=key))
    for job_id, items in by_job.items():
        _daily_log(office, job_id, str(work_date), items, company)
    office.audit("prefill", "crew_board", work_date, None,
                 {"time_lines": len(time_ids), "jobs": len(by_job)})
    return {"time_lines": time_ids, "jobs": sorted(by_job)}


def _daily_log(office, job_id, work_date, items, company) -> None:
    man = []
    for a in items:
        n = office.db.scalar(
            "SELECT COUNT(*) FROM workers WHERE crew_id = ? AND active = 1 "
            "AND deleted = 0", (a["crew_id"],)) or 0
        man.append({"company": company, "trade": a["crew"],
                    "workers": str(int(n)),
                    "hours": cents.hours_text(a["hours"])})
    rec = {"id": f"crewboard-{job_id}-{work_date}", "date": work_date,
           "status": "Draft", "manpower": man}
    key = f"crewboard:{job_id}:{work_date}"
    row = office.db.one(
        "SELECT id FROM snap_records WHERE job_id = ? AND section = "
        "'daily_logs' AND key = ? AND deleted = 0", (job_id, key))
    payload = json.dumps(rec, sort_keys=True)
    if row:
        office.db.update("snap_records", row["id"], data=payload)
    else:
        office.db.insert("snap_records", job_id=job_id, section="daily_logs",
                         key=key, data=payload, first_import=0,
                         last_import=0, frozen=0)
