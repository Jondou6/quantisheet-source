"""Submittal look-ahead: the open submittals due in the next few weeks,
plus the ones already late, soonest first. What the PM brings to the
weekly sub meeting.

An item is "due" on its submit-by date while the sub still has it, and
on the due date of each review step not yet returned once it is in
review. The earliest of those is the date that counts.
"""
from datetime import date, timedelta

from . import schema

KEY = "submittal"
# the sub still has it: the submit-by date is what counts
_WITH_SUB = ("Draft", "Not Submitted", "Revise and Resubmit")
HEADERS = ["Spec", "No.", "Title", "Type", "Responsible", "Ball in court",
           "Due for", "Due", "Submit by", "Needed on site", "Days left",
           "Status"]


def _day(v):
    """ISO text or a date -> date, or None."""
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v or "")[:10])
    except ValueError:
        return None


def _name(v):
    if isinstance(v, dict):
        return str(v.get("name") or v.get("email") or "")
    if isinstance(v, (list, tuple)):
        return "; ".join(_name(x) for x in v if x)
    return str(v or "")


def _due(rec):
    """(date, what is due) for an open submittal, or (None, "")."""
    got = []
    sub_by = _day(rec.get("submit_by") or schema.submit_by(rec))
    if rec.get("status") in _WITH_SUB and sub_by:
        got.append((sub_by, "Submit"))
    for step in rec.get("workflow") or []:
        d = _day(step.get("due"))
        if d and not step.get("returned"):
            who = _name(step.get("reviewer"))
            got.append((d, f"Review by {who}" if who else "Review"))
    return min(got, key=lambda g: g[0]) if got else (None, "")


def lookahead(store, weeks=4, today=None):
    """Open submittals due from today to today + weeks, and every late
    one, soonest first."""
    today = _day(today) or date.today()
    end = today + timedelta(weeks=int(weeks))
    rows = []
    for rec in store.list(KEY):
        if schema.is_closed(KEY, rec):
            continue
        due, what = _due(rec)
        if due is None or due > end:
            continue
        sub_by = rec.get("submit_by") or schema.submit_by(rec)
        rows.append({
            "id": rec.get("_id"), "spec": rec.get("spec") or "",
            "no": rec.get("_no") or "", "title": rec.get("title") or "",
            "type": rec.get("type") or "",
            "responsible": _name(rec.get("responsible")),
            "ball": schema.ball_in_court(KEY, rec), "for": what,
            "due": due.isoformat(), "submit_by": sub_by or "",
            "on_site": rec.get("required_on_site") or "",
            "days_left": (due - today).days,
            "status": rec.get("status") or ""})
    rows.sort(key=lambda r: (r["due"], r["spec"], r["no"]))
    return rows


def table(rows):
    """Rows as lists under HEADERS (dates left as ISO text)."""
    return [[r["spec"], r["no"], r["title"], r["type"], r["responsible"],
             r["ball"], r["for"], r["due"], r["submit_by"], r["on_site"],
             r["days_left"], r["status"]] for r in rows]


def _title(weeks):
    return f"Submittal look-ahead - {int(weeks)} weeks"


def export_pdf(store, path, weeks=4, today=None):
    from . import report
    from .widgets import show_date
    rows = lookahead(store, weeks, today)
    late = sum(1 for r in rows if r["days_left"] < 0)
    d = report._Doc(_title(weeks), store.name,
                    f"{len(rows)} open submittal(s), {late} late")
    body = []
    for r in table(rows):
        r = list(r)
        for i in (7, 8, 9):
            r[i] = show_date(r[i])
        n = r[10]
        r[10] = f"{-n} late" if n < 0 else str(n)
        body.append(r)
    d.table(HEADERS, body,
            [1.1, 1.0, 2.6, 1.2, 1.5, 1.5, 1.4, 1.1, 1.1, 1.1, 0.8, 1.2])
    return d.finish(path)


def export_xlsx(store, path, weeks=4, today=None):
    import openpyxl
    from openpyxl.styles import Font
    from .. import safecell
    rows = lookahead(store, weeks, today)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Look-ahead"
    safecell.append_row(ws, HEADERS)
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in table(rows):
        for i in (7, 8, 9):
            r[i] = _day(r[i]) or r[i]
        safecell.append_row(ws, r)      # user text stays text
    for row in ws.iter_rows(min_row=2):
        for c in row[7:10]:
            if isinstance(c.value, date):
                c.number_format = "mmm d, yyyy"
    for col, w in zip("ABCDEFGHIJKL",
                      (11, 11, 40, 15, 22, 22, 22, 13, 13, 13, 9, 16)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A2"
    wb.save(path)
    return path


def export(store, path, weeks=4, today=None):
    """PDF or Excel by the file's extension."""
    if path.lower().endswith(".xlsx"):
        return export_xlsx(store, path, weeks, today)
    return export_pdf(store, path, weeks, today)
