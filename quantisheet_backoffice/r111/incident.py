"""Incident reports and a recordable-case log in the OSHA 300 column
style (our own sheet, not a copy of the government form).

Photos are copied into the company documents folder. Nothing is filed
or sent anywhere.
"""
from __future__ import annotations

import csv
import os

from .. import clock, jobs, store
from . import pdfutil, schema

KINDS = ("injury", "near miss", "property damage", "environmental", "other")
CLASSES = ("death", "days away", "job transfer", "other recordable")
ROLES = ("injured", "witness", "other")


class IncidentError(ValueError):
    pass


def add(office, kind, occurred_on, description, job_id=None, occurred_time="",
        weather="", location="") -> int:
    schema.need(office, "time.edit", record_type="incident",
                record_id=occurred_on)
    if kind not in KINDS:
        raise IncidentError(f"Type must be one of: {', '.join(KINDS)}.")
    if not str(description).strip():
        raise IncidentError("Describe what happened.")
    schema.ensure(office.db)
    with office.db.tx():
        number = office.db.next_number("INC", "INC-{n:04d}")
        iid = office.db.insert(
            "incidents", number=number, job_id=job_id, kind=kind,
            occurred_on=str(occurred_on), occurred_time=occurred_time or "",
            weather=weather or "", location=location or "",
            description=str(description).strip(), status="open",
            supervisor="", reviewed_at="", review_note="")
        office.audit("create", "incident", iid, None,
                     {"number": number, "kind": kind})
    return iid


def get(office, iid) -> dict:
    schema.ensure(office.db)
    row = office.db.get("incidents", iid)
    if not row or row.get("deleted"):
        raise IncidentError("That incident is not on file.")
    return row


def add_person(office, iid, name, role="witness", statement="", company="",
               job_title="") -> int:
    schema.need(office, "time.edit", record_type="incident", record_id=iid)
    get(office, iid)
    if role not in ROLES:
        raise IncidentError(f"Role must be one of: {', '.join(ROLES)}.")
    if not str(name).strip():
        raise IncidentError("The person needs a name.")
    with office.db.tx():
        pid = office.db.insert(
            "incident_people", incident_id=iid, role=role,
            name=str(name).strip(), company=company or "",
            job_title=job_title or "", statement=statement or "",
            recordable=0, classification="", days_away=0,
            days_restricted=0, privacy=0)
        office.audit("create", "incident_person", pid, None,
                     {"name": name, "role": role})
    return pid


def people(office, iid) -> list[dict]:
    get(office, iid)
    return office.db.rows("SELECT * FROM incident_people WHERE incident_id = ? "
                          "AND deleted = 0 ORDER BY id", (iid,))


def add_photo(office, iid, path, caption="") -> int:
    schema.need(office, "time.edit", record_type="incident", record_id=iid)
    get(office, iid)
    from .. import fileguard
    fileguard.refuse_company_file(path)
    if not os.path.isfile(path):
        raise IncidentError("That photo was not found.")
    kept = store.copy_into(office.documents_folder(), path)
    with office.db.tx():
        pid = office.db.insert("incident_photos", incident_id=iid,
                               file_path=kept, caption=caption or "")
        office.audit("create", "incident_photo", pid, None,
                     {"file": os.path.basename(kept)})
    return pid


def photos(office, iid) -> list[dict]:
    get(office, iid)
    return office.db.rows("SELECT * FROM incident_photos WHERE incident_id = ? "
                          "AND deleted = 0 ORDER BY id", (iid,))


def mark_recordable(office, person_id, classification, days_away=0,
                    days_restricted=0, privacy=False) -> None:
    schema.need(office, "time.edit", record_type="incident_person",
                record_id=person_id)
    if classification not in CLASSES:
        raise IncidentError("Classification must be one of: "
                            + ", ".join(CLASSES) + ".")
    who = office.db.get("incident_people", person_id)
    if not who or who.get("deleted"):
        raise IncidentError("That person is not on the incident.")
    with office.db.tx():
        office.db.update("incident_people", person_id, recordable=1,
                         classification=classification,
                         days_away=int(days_away),
                         days_restricted=int(days_restricted),
                         privacy=1 if privacy else 0)
        office.audit("change", "incident_person", person_id, None,
                     {"classification": classification})


def review(office, iid, note, accept=True) -> None:
    """Supervisor review. Stays in the file; nothing is sent."""
    schema.need(office, "time.approve", "hr.edit", record_type="incident",
                record_id=iid)
    if not str(note).strip():
        raise IncidentError("A review note is required.")
    row = get(office, iid)
    status = "reviewed" if accept else "returned"
    with office.db.tx():
        office.db.update("incidents", iid, status=status, supervisor=office.who,
                         reviewed_at=clock.iso_now(), review_note=str(note).strip())
        office.audit("review", "incident", iid, {"status": row["status"]},
                     {"status": status, "note": note})


def _cases(office, year) -> list[dict]:
    year = str(year)
    out = []
    for inc in office.db.rows(
            "SELECT * FROM incidents WHERE deleted = 0 AND occurred_on LIKE ?",
            (year + "-%",)):
        job = ""
        if inc["job_id"]:
            j = jobs.job(office, inc["job_id"])
            if j:
                job = f"{j['number']} {j['name']}".strip()
        for person in office.db.rows(
                "SELECT * FROM incident_people WHERE incident_id = ? AND "
                "recordable = 1 AND deleted = 0", (inc["id"],)):
            name = "Privacy case" if person["privacy"] else person["name"]
            out.append({"case": inc["number"], "employee": name,
                        "job_title": person["job_title"] or "",
                        "date": inc["occurred_on"], "where": inc["location"]
                        or job, "description": inc["description"],
                        "classification": person["classification"] or "",
                        "days_away": person["days_away"] or 0,
                        "days_restricted": person["days_restricted"] or 0})
    return out


_COLUMNS = ("case", "employee", "job_title", "date", "where", "description",
            "classification", "days_away", "days_restricted")
_HEADS = ("Case", "Employee", "Job title", "Date", "Where", "Description",
          "Classification", "Days away", "Days restricted")


def export_log(office, year, path) -> str:
    """OSHA 300-style log for one calendar year. PDF or CSV from the
    file extension. Recordable people only."""
    schema.need(office, "time.edit", "hr.view", record_type="incident_log",
                record_id=year)
    from .. import fileguard
    schema.ensure(office.db)
    path = fileguard.write_target(path)
    rows = _cases(office, year)
    if str(path).lower().endswith(".csv"):
        from .. import fileguard
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(_HEADS)
            for r in rows:
                w.writerow(fileguard.safe_row([r[k] for k in _COLUMNS]))
    else:
        _pdf(office, year, rows, path)
    office.audit("export", "incident_log", year, None,
                 {"file": os.path.basename(path), "rows": len(rows)})
    return path


def _pdf(office, year, rows, path) -> None:
    import fitz
    doc = fitz.open()
    try:
        page = doc.new_page(width=792, height=612)
        y = pdfutil.draw_header(
            office, page, f"Recordable case log {year} (OSHA 300-style)")
        pdfutil.text(page, 54, y, "Local record only. Nothing in this log "
                     "is filed or sent.", 8)
        y += 18
        x = [36, 90, 180, 260, 320, 420, 560, 660, 730]
        for i, head in enumerate(_HEADS):
            pdfutil.text(page, x[i], y, head, 7, True)
        y += 6
        page.draw_line((36, y), (770, y), width=0.4)
        y += 12
        for r in rows:
            vals = [str(r[k])[:28] for k in _COLUMNS]
            for i, val in enumerate(vals):
                pdfutil.text(page, x[i], y, val, 7)
            y += 12
            if y > 560:
                break
        if not rows:
            pdfutil.text(page, 36, y, "No recordable cases in this year.", 9)
        doc.save(path)
    finally:
        doc.close()


def packet_pdf(office, iid, path=None) -> str:
    """One incident: people, statements and photo captions."""
    schema.need(office, "time.edit", record_type="incident", record_id=iid)
    import fitz
    row = get(office, iid)
    path = path or pdfutil.out_path(office, f"{row['number']}.pdf")
    from .. import fileguard
    path = fileguard.write_target(path)
    doc = fitz.open()
    try:
        page = doc.new_page(width=612, height=792)
        y = pdfutil.draw_header(office, page, f"Incident {row['number']}")
        for label, value in (
                ("Type", row["kind"]), ("Date", row["occurred_on"]),
                ("Time", row["occurred_time"]), ("Weather", row["weather"]),
                ("Where", row["location"]), ("Status", row["status"]),
                ("Supervisor", row["supervisor"]),
                ("Review", row["review_note"])):
            if not value:
                continue
            pdfutil.text(page, 54, y, label, 9, True)
            pdfutil.text(page, 140, y, str(value)[:80], 9)
            y += 14
        pdfutil.text(page, 54, y, row["description"][:400], 9)
        y += 28
        for person in people(office, iid):
            pdfutil.text(page, 54, y,
                         f"{person['role']}: {person['name']}", 9, True)
            y += 12
            if person["statement"]:
                pdfutil.text(page, 70, y, person["statement"][:300], 8)
                y += 14
        for photo in photos(office, iid):
            pdfutil.text(page, 54, y, photo["caption"] or
                         os.path.basename(photo["file_path"]), 8)
            y += 12
            if photo["file_path"] and os.path.isfile(photo["file_path"]) \
                    and y < 680:
                try:
                    page.insert_image(fitz.Rect(54, y, 254, y + 90),
                                      filename=photo["file_path"],
                                      keep_proportion=True)
                    y += 100
                except Exception:                         # noqa: BLE001
                    pass
        doc.save(path)
    finally:
        doc.close()
    return path
