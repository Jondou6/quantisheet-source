"""Change-set, impact on a what-if copy, and classification
(design 3.5 / 4.8)."""
import copy
import datetime as _dt
import json

from .. import schedule, schedule_record
from ..recovery import WhatIf
from . import model
from .values import base_of

PROGRESS = ("percent", "actual_start", "actual_finish", "notes", "status")
SUB_FIELDS = ("duration", "percent", "actual_start", "actual_finish")


def _status(a):
    """update_dates()'s rule, for one activity."""
    st = a.get("status") or "Not Started"
    try:
        pc = float(a.get("percent") or 0)
    except (TypeError, ValueError):
        pc = 0.0
    if a.get("actual_finish") or pc >= 100:
        return "Complete"
    if a.get("actual_start") or pc > 0:
        return "In Progress"
    return st


def _store_val(field, v):
    if field in ("actual_start", "actual_finish"):
        return v or ""
    return "" if v is None else v


def build(store, company, checked, meta):
    """{"changes", "conflicts", "proposed", "errors"} - three-way against
    the values in the template as issued (base), the master now
    (current) and the sub's file."""
    acts = store.list("activity")
    by = {a["_id"]: a for a in acts}
    proposed = copy.deepcopy(acts)
    pby = {a["_id"]: a for a in proposed}
    changes, conflicts, errors = [], [], []
    ef_rows = []
    for r in checked["own"]:
        a = by[r["key"]]
        cur = base_of(a)
        for f in SUB_FIELDS:
            base, sub, now = r["base"].get(f), r["values"].get(f), cur[f]
            if sub == base or sub == now:
                continue                 # unchanged by the sub, or agreed
            if now != base:
                conflicts.append({"_id": a["_id"], "_no": a.get("_no"),
                                  "name": a.get("name"), "field": f,
                                  "base": base, "current": now, "sub": sub})
            pby[a["_id"]][f] = _store_val(f, sub)
        note = r["values"].get("note")
        if note:
            pby[a["_id"]]["notes"] = ((a.get("notes") or "").rstrip() +
                                      ("\n" if a.get("notes") else "") +
                                      f"{company} {meta.get('cycle')}: "
                                      f"{note}")
        if r["values"].get("expected_finish"):
            ef_rows.append(r)
    dd = _dt.date.fromisoformat(str(meta["cycle"])[:10])
    for r in ef_rows:
        n = _duration_for(store, proposed, r["key"],
                          r["values"]["expected_finish"], dd)
        if n is None:
            errors.append({"where": r["where"]["expected_finish"],
                           "text": f"{r['no']}: the expected finish "
                           f"{r['values']['expected_finish']} can't be "
                           "reached by changing the duration."})
        else:
            pby[r["key"]]["duration"] = n
    for a in proposed:
        old = by[a["_id"]]
        touched = any(a.get(k) != old.get(k) for k in a if
                      not k.startswith("_"))
        if touched:
            a["status"] = _status(a)
        if a.get("status") == "Not Started" and not old.get("status"):
            # blank already means Not Started: not a change the sub made
            # (review r41 F06)
            a["status"] = old.get("status")
        for k in sorted(set(a) | set(old)):
            if k.startswith("_") or a.get(k) == old.get(k):
                continue
            changes.append({"_id": a["_id"], "_no": a.get("_no"),
                            "name": a.get("name"), "field": k,
                            "before": old.get(k), "after": a.get(k)})
    return {"changes": changes, "conflicts": conflicts,
            "proposed": proposed, "errors": errors}


def _duration_for(store, proposed, rid, expected, dd):
    want = _dt.date.fromisoformat(expected)

    def ef(n):
        trial = copy.deepcopy(proposed)
        for a in trial:
            if a["_id"] == rid:
                a["duration"] = n
        cpm = schedule.compute(WhatIf(store, trial), dd)
        return next(r["ef"] for r in cpm["rows"] if r["_id"] == rid)
    lo, hi = 1, 4000
    if ef(hi) < want:
        return None
    while lo < hi:
        mid = (lo + hi) // 2
        if ef(mid) >= want:
            hi = mid
        else:
            lo = mid + 1
    return lo if ef(lo) == want else None


def _entry(cpm, acts, dd, n):
    rows = {r["_id"]: r for r in cpm["rows"]}
    out = []
    for a in acts:
        r = rows.get(a["_id"], {})
        e = {k: copy.deepcopy(a.get(k)) for k in schedule_record.SNAP_FIELDS}
        e.update(es=r.get("es"), ef=r.get("ef"), float=r.get("float"),
                 critical=bool(r.get("critical")))
        out.append(e)
    return {"n": n, "data_date": dd, "finish": cpm.get("finish"),
            "critical": sorted(str(rows[i].get("_no"))
                               for i in cpm["critical"] if i in rows),
            "activities": out}


def impact(store, proposed, dd):
    """Before / after CPM on what-if copies (nothing saved)."""
    acts = store.list("activity")
    hol = store.setting("holidays") or ()
    before = schedule.compute(WhatIf(store, acts), dd)
    after = schedule.compute(WhatIf(store, proposed), dd)
    rb = {r["_id"]: r for r in before["rows"] if not r.get("summary")}
    later = []
    for r in after["rows"]:
        b = rb.get(r["_id"])
        if b is None or r.get("summary") or r["ef"] <= b["ef"]:
            continue
        later.append({"_id": r["_id"], "_no": r.get("_no"),
                      "name": r.get("name"),
                      "owner": model.owner_of(r) or "GC",
                      "before": b["ef"].isoformat(),
                      "after": r["ef"].isoformat(),
                      "workdays": schedule_record._workdays(b["ef"], r["ef"],
                                                            hol)})
    log = schedule_record.updates(store)
    prev_dd = log[-1].get("data_date") if log else None
    cmp = schedule_record.compare(_entry(before, acts, prev_dd, "master"),
                                  _entry(after, proposed, dd.isoformat(),
                                         "proposed"), holidays=hol)
    from ..recovery import _milestone
    mb, ma = _milestone(before), _milestone(after)
    ms = None
    if mb and ma and mb["_id"] == ma["_id"]:
        ms = {"_no": ma.get("_no"), "name": ma.get("name"),
              "before": mb["ef"].isoformat(), "after": ma["ef"].isoformat(),
              "workdays": schedule_record._workdays(mb["ef"], ma["ef"],
                                                    hol)}
    out = {"data_date": dd.isoformat(),
           "finish_before": before["finish"], "finish_after":
           after["finish"],
           "finish_workdays": schedule_record._workdays(
               before["finish"], after["finish"], hol)
           if before["finish"] and after["finish"] else 0,
           "milestone": ms, "later": later,
           "red_flags": cmp["red_flags"], "compare": cmp,
           "new_problems": [p for p in after["problems"]
                            if p not in before["problems"]]}
    return json.loads(json.dumps(out, default=str))


def classify(cfg, built, checked, imp):
    """[reason it needs Jon] - empty means it may be accepted on its own:
    the rule is on, only progress fields change, NO activity finishes
    later (zero slip, every activity), and no flag of any kind."""
    why = []
    aa = cfg.get("auto_accept") or {}
    if not aa.get("progress_only", True):
        why.append("Auto-accept is switched off.")
    other = sorted({c["field"] for c in built["changes"]
                    if c["field"] not in PROGRESS})
    if other:
        why.append("Changes more than progress: " + ", ".join(other) + ".")
    if imp["later"]:
        why.append(f"{len(imp['later'])} activit"
                   f"{'y finishes' if len(imp['later']) == 1 else 'ies finish'}"
                   " later (zero-slip rule).")
    if imp["red_flags"]:
        why.append(f"{len(imp['red_flags'])} red flag(s).")
    if checked["warnings"]:
        why.append(f"{len(checked['warnings'])} warning(s).")
    if built["conflicts"]:
        why.append(f"{len(built['conflicts'])} conflict(s) with your "
                   "changes since the template went out.")
    if checked["ignored"]:
        why.append("Edits outside the sub's activities were ignored.")
    if checked["new"]:
        why.append(f"{len(checked['new'])} new internal activit"
                   f"{'y' if len(checked['new']) == 1 else 'ies'}.")
    return why


def combined(store, cycle):
    """4.7: the impact of ALL pending submissions for one cycle taken
    together (each is still diffed and applied on its own)."""
    subs = [x for x in model.submissions(store)
            if x.get("status") == "Pending review" and
            str(x.get("cycle")) == str(cycle)]
    out = {"cycle": str(cycle), "submissions": [model.label(x)
                                                for x in subs],
           "later": [], "completion": None}
    if not subs:
        return out
    proposed = copy.deepcopy(store.list("activity"))
    by = {a["_id"]: a for a in proposed}
    for x in subs:
        for c in x.get("changes") or []:
            if c["_id"] in by:
                by[c["_id"]][c["field"]] = c["after"]
    imp = impact(store, proposed, _dt.date.fromisoformat(str(cycle)[:10]))
    out.update({k: v for k, v in imp.items() if k != "data_date"})
    return out
