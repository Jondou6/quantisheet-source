"""Write a compiled schedule into the project store's activity records.

``duration`` is the Monday-Friday span of the compiled early dates, which
is what ``schedule.compute`` can draw. The activity's own calendar and
the duration on that calendar are kept on ``sch_calendar`` and
``sch_duration_days``. Per-activity calendars are not read by
``schedule.compute`` until that function grows one; see the package
docstring.

Summary rows are the WBS. Logic is only on the activities under them.
"""
import datetime as _dt

from .. import schedule
from .calendar import build_all, workdays_between
from .model import as_date
from ...dmoney import c2 as _c2


def apply_to_store(store, doc, replace=False):
    old = store.list("activity")
    if old and not replace:
        raise ValueError("This project already has a schedule.")
    for a in old:
        store.delete("activity", a["_id"])
    start = as_date((doc.get("project") or {}).get("start")) or _dt.date.today()
    store.set_setting("project_start", start.isoformat())
    if doc["project"].get("data_date"):
        store.set_setting("data_date", doc["project"]["data_date"])
    hol = []
    for spec in (doc.get("calendars") or {}).values():
        if spec.get("key") in ("5day", "weather", None) or spec.get("key") == "5day":
            hol = list(spec.get("holidays") or [])
    if not hol:
        for spec in (doc.get("calendars") or {}).values():
            if spec.get("holidays"):
                hol = list(spec["holidays"])
                break
    store.set_setting("holidays", hol)
    cals = build_all(doc)
    project = cals.get("5day") or next(iter(cals.values()))
    summaries = {}
    seq = 1.0
    for w in doc.get("wbs") or []:
        rec = store.save_record("activity", {
            "name": w.get("name") or w.get("code"),
            "seq": seq, "status": "Not Started",
            "area": w.get("code") or "",
            "notes": "WBS " + (w.get("code") or ""),
            "auto": "schedacc",
        })
        summaries[w.get("code")] = rec
        seq += 1
    # Parent the nested WBS rows.
    for w in doc.get("wbs") or []:
        parent = summaries.get(w.get("parent") or "")
        if parent:
            rec = summaries[w["code"]]
            rec["parent"] = parent["_id"]
            store.save_record("activity", rec)
    made = {}
    n = 0
    for act in doc.get("activities") or []:
        if act.get("type") in ("wbs_summary",):
            continue
        es, ef = as_date(act.get("es")), as_date(act.get("ef"))
        milestone = act.get("type") in ("start_ms", "finish_ms") or (
            not es or not ef)
        if milestone or not es or not ef:
            dur = 0
        else:
            dur = max(0, workdays_between(project, es, ef) + 1) if \
                project.index(ef) >= project.index(es) else 0
            if act.get("type") == "loe":
                dur = max(dur, 1)
        parent = summaries.get(act.get("wbs") or "")
        notes = "\n".join(x for x in (
            "BASIS: " + (act.get("basis") or ""),
            "WHY: " + (act.get("why") or ""),
            "CALENDAR: " + (act.get("calendar") or ""),
            "DURATION: " + (act.get("duration_kind") or ""),
            "SLOT: " + (act.get("template_slot") or ""),
            "SOURCE: " + "; ".join(c.get("source") or "" for c in
                                   act.get("citations") or []
                                   if c.get("document")),
        ) if x and not x.endswith(": "))
        rec = store.save_record("activity", {
            "name": act.get("name") or act.get("code"),
            "duration": 0 if milestone else dur,
            "seq": n + 1.0,
            "parent": parent["_id"] if parent else "",
            "status": "Not Started",
            "area": act.get("wbs") or "",
            "cost_code": act.get("cost_code") or "",
            "notes": notes,
            "auto": "schedacc",
            "sch_calendar": act.get("calendar") or "",
            "sch_duration_days": act.get("dur_days") or 0,
            "sch_es": act.get("es") or "",
            "sch_ef": act.get("ef") or "",
            "sch_float": act.get("total_float_days"),
            "sch_kind": act.get("duration_kind") or "",
            "sch_code": act.get("code") or "",
        })
        if act.get("constraint") in ("start_on_or_after", "start_on",
                                     "mandatory_start") and act.get("constraint_date"):
            rec["start"] = str(act["constraint_date"])[:10]
            store.save_record("activity", rec)
        made[act["code"]] = rec
        n += 1
    for act in doc.get("activities") or []:
        rec = made.get(act["code"])
        if rec is None:
            continue
        lines = []
        for rel in doc.get("relationships") or []:
            if rel.get("succ") != act["code"]:
                continue
            pred = made.get(rel.get("pred"))
            if pred is None:
                continue
            lag_days = float(rel.get("lag_hours") or 0) / 8.0
            lines.append({"id": pred["_no"], "type": rel.get("type") or "FS",
                          "lag": _c2(lag_days)})
        if lines:
            rec = store.get("activity", rec["_id"])
            rec["preds"] = lines
            store.save_record("activity", rec)
    if doc.get("caveat"):
        store.set_setting("schedule_caveat", doc["caveat"])
    native = schedule.compute(store, as_date(doc["project"].get("data_date")))
    return {"activities": n, "native": native}
