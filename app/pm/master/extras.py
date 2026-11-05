"""Master Schedule additions (0.13.12, items Chief's build left out):

    preview(store, sub)          before / after bars for the review
    approve_lines(store, sid, keep, by, now)
                                 approve only some activities' changes
    to_delay_log(store, sid, by) a draft Delay Log entry for the
                                 activities an approved update made later

Pure Python (no Qt); writes only through the ProjectStore."""
import copy
import datetime as _dt

from .. import schedule
from ..recovery import WhatIf
from . import apply, model


def _changed_ids(sub):
    return {c["_id"] for c in sub.get("changes") or []}


def preview(store, sub, limit=60):
    """[{"_no", "name", "owner", "before": (es, ef), "after": (es, ef),
    "critical"}] for every activity the update changes or moves - what
    the before / after bars show. Worked out on what-if copies of the
    current master (nothing saved). Dates as ISO strings."""
    acts = store.list("activity")
    proposed = copy.deepcopy(acts)
    by = {a["_id"]: a for a in proposed}
    for c in sub.get("changes") or []:
        a = by.get(c["_id"])
        if a is not None:
            a[c["field"]] = c["after"]
    try:
        dd = _dt.date.fromisoformat(str(sub.get("cycle"))[:10])
    except ValueError:
        dd = _dt.date.today()
    b = schedule.compute(WhatIf(store, acts), dd)
    a = schedule.compute(WhatIf(store, proposed), dd)
    rb = {r["_id"]: r for r in b["rows"] if not r.get("summary")}
    touched = _changed_ids(sub)
    out = []
    for r in a["rows"]:
        if r.get("summary") or r["_id"] not in rb:
            continue
        o = rb[r["_id"]]
        if r["_id"] not in touched and (r["es"], r["ef"]) == (o["es"],
                                                              o["ef"]):
            continue
        out.append({"_id": r["_id"], "_no": r.get("_no"),
                    "name": r.get("name"),
                    "owner": model.owner_of(r) or "GC",
                    "before": (o["es"].isoformat(), o["ef"].isoformat()),
                    "after": (r["es"].isoformat(), r["ef"].isoformat()),
                    "critical": bool(r.get("critical"))})
    out.sort(key=lambda x: (x["after"][0], str(x["_no"])))
    return out[:limit]


def approve_lines(store, sid, keep, by=None, now=None):
    """Approve only the changes of the activities numbered in `keep`
    (activity numbers); every other activity keeps the master's values,
    recorded as GC overrides (Edit and approve). The impact is worked
    out again on what is actually applied."""
    model.need_approver(store)
    sub = store.get(model.SUBS, sid)
    if sub is None or sub.get("status") != "Pending review":
        raise apply.ApplyRefused("Only a submission waiting for review can "
                                 "be approved.")
    from .values import base_of
    keep = {str(k) for k in keep}
    acts = {a["_id"]: a for a in store.list("activity")}
    rows = {str(r["no"]): r for r in sub.get("rows") or []}
    edits = {}
    for c in sub.get("changes") or []:
        no = str(c.get("_no"))
        if no in keep or no not in rows or c["_id"] not in acts or \
                c["field"] not in ("duration", "percent", "actual_start",
                                   "actual_finish"):
            continue
        cur = base_of(acts[c["_id"]])     # the master's value stays
        edits.setdefault(rows[no]["no"], {})[c["field"]] = cur[c["field"]]
    if not edits:
        return apply.approve(store, sid, by=by, now=now)
    if len(edits) == len({str(c.get("_no")) for c in
                          sub.get("changes") or []}) and not keep:
        raise apply.ApplyRefused("No lines are ticked - decline it "
                                 "instead.")
    return apply.approve(store, sid, by=by, now=now, edits=edits)


def to_delay_log(store, sid, by=None):
    """A Delay Log entry (status Open) for an approved / auto-accepted
    update that made activities finish later: one affected line per
    activity with the workdays it slipped. Cause and responsibility are
    a starting point for Jon to check. Returns the new record, or None
    when nothing slipped."""
    sub = store.get(model.SUBS, sid)
    if sub is None or sub.get("status") not in ("Approved",
                                                 "Auto-accepted"):
        raise apply.ApplyRefused("Only an applied update goes to the Delay "
                                 "Log.")
    later = (sub.get("impact") or {}).get("later") or []
    if not later:
        return None
    if sub.get("delay_id") and store.get("delay", sub["delay_id"]):
        raise apply.ApplyRefused("This update is already in the Delay Log "
                                 f"({store.get('delay', sub['delay_id'])['_no']}).")
    imp = sub["impact"]
    first = min(x["before"] for x in later)
    rec = {"title": f"{sub.get('company')} update {sub.get('cycle')}: "
                    f"{len(later)} activit{'y' if len(later) == 1 else 'ies'}"
                    " later",
           "description": (f"From Master Schedule submission "
                           f"{model.label(sub)} ({sub.get('file_name') or sub.get('channel')}), "
                           f"applied {sub.get('decided_at') or ''}. Project "
                           f"finish {imp.get('finish_before')} -> "
                           f"{imp.get('finish_after')} "
                           f"({imp.get('finish_workdays', 0):+d} workdays). "
                           "Cause and responsibility are a starting point - "
                           "check them before any notice."),
           "cause": "Subcontractor performance",
           "responsibility": "Contractor",
           "event_start": first,
           "status": "Open",
           "affected": [{"id": x["_no"], "days": x["workdays"],
                         "note": f"{x['name']}: {x['before']} -> "
                                 f"{x['after']}"} for x in later]}
    rec = store.save_record("delay", rec)
    sub["delay_id"] = rec["_id"]
    store.save_record(model.SUBS, sub)
    return rec
