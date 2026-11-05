"""Project calendar data: what happens on which day of the job - schedule
activities and milestones (from the CPM, never edited here), inspections,
meetings and expected deliveries - for the Calendar page (calendarui).

    items(store, start, end, kinds=None) -> [{kind, start, end, title,
        coll, id, movable, critical}]
    move(store, item, days) -> the moved record (meetings, inspections,
        deliveries only; activities are changed in the Gantt)

The page's look follows the MIT-licensed Kargul calendar design prototype
(see THIRD_PARTY_NOTICES.txt); this is our own code.
"""
from __future__ import annotations

from datetime import date, timedelta

KINDS = ("activity", "milestone", "inspection", "meeting", "delivery")
LABELS = {"activity": "Activities", "milestone": "Milestones",
          "inspection": "Inspections", "meeting": "Meetings",
          "delivery": "Deliveries"}
# record kind -> (collection, date field)
MOVABLE = {"inspection": ("inspection", "date"),
           "meeting": ("meeting", "date"),
           "delivery": ("expedite", "expected")}


def _d(v) -> date | None:
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def items(store, start, end, kinds=None) -> list[dict]:
    """Everything dated from start to end (inclusive), all-day items."""
    want = set(kinds or KINDS)
    s, e = _d(start), _d(end)
    out = []
    if want & {"activity", "milestone"}:
        from . import schedule
        try:
            rows = schedule.cached(store)["rows"]
        except Exception:                                 # noqa: BLE001
            rows = []
        for r in rows:
            a, b = r.get("es"), r.get("ef")
            if not isinstance(a, date) or not isinstance(b, date):
                continue
            if b < s or a > e:
                continue
            kind = "milestone" if r.get("milestone") else "activity"
            if kind not in want:
                continue
            if r.get("summary"):
                continue                     # summary rows: their parts show
            title = r.get("name") or r.get("_no") or "Activity"
            if r.get("critical"):
                title = "● " + title
            out.append({"kind": kind, "start": a.isoformat(),
                        "end": b.isoformat(), "title": title,
                        "coll": "activity", "id": r["_id"],
                        "movable": False, "critical": bool(r.get("critical"))})
    for kind, (coll, field) in MOVABLE.items():
        if kind not in want:
            continue
        for rec in store.list(coll):
            d = _d(rec.get(field))
            if d is None or d < s or d > e:
                continue
            if kind == "delivery" and rec.get("delivered"):
                continue
            title = rec.get("title") or rec.get("item") or rec.get("_no", "")
            if kind == "meeting" and rec.get("time"):
                title = f"{rec['time']} {title}"
            if kind == "delivery":
                title = "Delivery: " + title
            out.append({"kind": kind, "start": d.isoformat(),
                        "end": d.isoformat(), "title": title, "coll": coll,
                        "id": rec["_id"], "movable": True,
                        "critical": False})
    order = {k: i for i, k in enumerate(("milestone", "inspection",
                                         "meeting", "delivery", "activity"))}
    out.sort(key=lambda x: (x["start"], order[x["kind"]], x["title"]))
    return out


class MoveError(ValueError):
    pass


def move(store, item, days) -> dict:
    """Move a meeting, inspection or delivery by whole days."""
    if not item.get("movable") or item.get("kind") not in MOVABLE:
        raise MoveError("Schedule activities move in the Gantt chart, "
                        "where their links and float are shown.")
    coll, field = MOVABLE[item["kind"]]
    rec = store.get(coll, item["id"])
    if rec is None:
        raise MoveError("That item no longer exists.")
    d = _d(rec.get(field))
    if d is None:
        raise MoveError("That item has no date.")
    rec = dict(rec)
    rec[field] = (d + timedelta(days=int(days))).isoformat()
    return store.save_record(coll, rec)


def new_preset(kind, day) -> tuple[str, dict]:
    """The collection and preset fields for a new item made by dragging
    a day range (meeting / inspection on its first day)."""
    if kind not in ("meeting", "inspection"):
        raise MoveError("New items from the calendar are meetings or "
                        "inspections.")
    return kind, {"date": _d(day).isoformat()}
