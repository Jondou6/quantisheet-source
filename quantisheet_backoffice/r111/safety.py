"""Safety meetings: a topic library, attendees with signatures, and a
one-page sign-in sheet PDF. Signatures stay in the company file.
"""
from __future__ import annotations

import json

from .. import clock, jobs
from . import pdfutil, schema

DEFAULT_TOPICS = (
    ("Ladder setup",
     "Set the ladder on firm, level ground. Three points of contact. "
     "Do not stand on the top cap."),
    ("Housekeeping",
     "Keep walkways clear of scrap, cords and standing water before "
     "the crew starts."),
    ("Heat",
     "Water nearby, shade on hot days, and stop if someone is dizzy, "
     "confused or stops sweating."),
    ("Eye and hand protection",
     "Glasses and gloves for cutting, grinding and chemicals."),
    ("Silica dust",
     "Wet cutting or a vacuum when concrete or masonry is cut. Do not "
     "dry-sweep that dust."),
)


class SafetyError(ValueError):
    pass


def _seed(office) -> None:
    if office.db.scalar("SELECT COUNT(*) FROM safety_topics"):
        return
    for title, body in DEFAULT_TOPICS:
        office.db.insert("safety_topics", title=title, body=body, active=1)


def topics(office) -> list[dict]:
    schema.ensure(office.db)
    _seed(office)
    return office.db.rows("SELECT * FROM safety_topics WHERE deleted = 0 AND "
                          "active = 1 ORDER BY title")


def add_topic(office, title, body) -> int:
    schema.need(office, "time.edit", record_type="safety_topic",
                record_id=title)
    if not str(title).strip():
        raise SafetyError("Name the topic.")
    schema.ensure(office.db)
    _seed(office)
    with office.db.tx():
        tid = office.db.insert("safety_topics", title=str(title).strip(),
                               body=str(body or "").strip(), active=1)
        office.audit("create", "safety_topic", tid, None, {"title": title})
    return tid


def add_meeting(office, meeting_date, title="", topic_id=None, job_id=None,
                presenter="", notes="") -> int:
    schema.need(office, "time.edit", record_type="safety_meeting",
                record_id=meeting_date)
    schema.ensure(office.db)
    _seed(office)
    if topic_id and not title:
        topic = office.db.get("safety_topics", topic_id)
        title = topic["title"] if topic else ""
    if not str(title).strip():
        raise SafetyError("Name the meeting topic.")
    with office.db.tx():
        number = office.db.next_number("SM", "SM-{n:04d}")
        mid = office.db.insert(
            "safety_meetings", number=number,
            meeting_date=str(meeting_date), job_id=job_id, topic_id=topic_id,
            title=str(title).strip(), notes=notes or "",
            presenter=presenter or office.who)
        office.audit("create", "safety_meeting", mid, None,
                     {"number": number, "title": title})
    return mid


def add_attendee(office, meeting_id, name, company="") -> int:
    schema.need(office, "time.edit", record_type="safety_meeting",
                record_id=meeting_id)
    if not str(name).strip():
        raise SafetyError("The attendee needs a name.")
    schema.ensure(office.db)
    with office.db.tx():
        aid = office.db.insert("safety_attendees", meeting_id=meeting_id,
                               name=str(name).strip(), company=company or "",
                               signed=0, signature=None, signed_at="")
        office.audit("create", "safety_attendee", aid, None, {"name": name})
    return aid


def _strokes(data) -> list:
    if not isinstance(data, list) or not data:
        raise SafetyError("A signature is required.")
    out = []
    for stroke in data:
        pts = []
        for p in stroke:
            if not isinstance(p, (list, tuple)) or len(p) < 2:
                continue
            if isinstance(p[0], bool) or isinstance(p[1], bool):
                continue
            pts.append([int(p[0]), int(p[1])])
        if len(pts) >= 2:
            out.append(pts)
    if not out:
        raise SafetyError("A signature is required.")
    return out


def sign(office, attendee_id, strokes) -> None:
    schema.need(office, "time.edit", record_type="safety_attendee",
                record_id=attendee_id)
    schema.ensure(office.db)
    drawn = _strokes(strokes)
    who = office.db.get("safety_attendees", attendee_id)
    if not who or who.get("deleted"):
        raise SafetyError("That attendee is not on the sheet.")
    with office.db.tx():
        office.db.update("safety_attendees", attendee_id, signed=1,
                         signature=drawn, signed_at=clock.iso_now())
        office.audit("sign", "safety_attendee", attendee_id, None,
                     {"name": who["name"]})


def attendees(office, meeting_id) -> list[dict]:
    schema.ensure(office.db)
    rows = office.db.rows("SELECT * FROM safety_attendees WHERE meeting_id = ? "
                          "AND deleted = 0 ORDER BY id", (meeting_id,))
    for r in rows:
        raw = r.get("signature")
        if isinstance(raw, str) and raw:
            try:
                r["signature"] = json.loads(raw)
            except ValueError:
                r["signature"] = []
        elif not raw:
            r["signature"] = []
    return rows


def meeting(office, meeting_id) -> dict:
    schema.ensure(office.db)
    row = office.db.get("safety_meetings", meeting_id)
    if not row or row.get("deleted"):
        raise SafetyError("That meeting is not on file.")
    return row


def signin_pdf(office, meeting_id, path=None) -> str:
    """One-click sign-in sheet."""
    schema.need(office, "time.edit", record_type="safety_meeting",
                record_id=meeting_id)
    import fitz
    m = meeting(office, meeting_id)
    people = attendees(office, meeting_id)
    path = path or pdfutil.out_path(office, f"{m['number']}-signin.pdf")
    from .. import fileguard
    path = fileguard.write_target(path) if path else path
    doc = fitz.open()
    try:
        page = doc.new_page(width=612, height=792)
        y = pdfutil.draw_header(office, page, "Safety meeting sign-in")
        job = ""
        if m["job_id"]:
            j = jobs.job(office, m["job_id"])
            if j:
                job = f"{j['number']} {j['name']}".strip()
        for label, value in (("Meeting", m["number"]), ("Date", m["meeting_date"]),
                             ("Topic", m["title"]), ("Presenter", m["presenter"]),
                             ("Job", job)):
            if not value:
                continue
            pdfutil.text(page, 54, y, label, 9, True)
            pdfutil.text(page, 140, y, value, 9)
            y += 14
        if m["notes"]:
            pdfutil.text(page, 54, y, m["notes"][:240], 8)
            y += 16
        y += 8
        pdfutil.text(page, 54, y, "Name", 9, True)
        pdfutil.text(page, 220, y, "Company", 9, True)
        pdfutil.text(page, 380, y, "Signature", 9, True)
        y += 8
        page.draw_line((54, y), (558, y), width=0.4)
        y += 16
        for person in people:
            pdfutil.text(page, 54, y + 10, person["name"], 9)
            pdfutil.text(page, 220, y + 10, person["company"] or "", 9)
            box = fitz.Rect(380, y - 4, 558, y + 22)
            page.draw_rect(box, color=(0.6, 0.6, 0.6), width=0.4)
            if person["signed"] and person["signature"]:
                pdfutil.strokes(page, box, person["signature"])
            else:
                pdfutil.text(page, 386, y + 12, "not signed", 8)
            y += 32
            if y > 740:
                break
        doc.save(path)
    finally:
        doc.close()
    office.audit("export", "safety_meeting", meeting_id, None,
                 {"file": path})
    return path
