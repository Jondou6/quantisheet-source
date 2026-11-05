"""Whole-file validation (design 3.3 / 4.1 / 4.3 / 4.4 / 4.11).

check() collects EVERY problem before deciding: any error rejects the
whole file with all of its reasons; nothing from it reaches the store.
Warnings ride along into review (and stop auto-accept)."""
import datetime as _dt
import math

from . import model

FIELDS = ("duration", "percent", "actual_start", "actual_finish")


def _e(where, text):
    return {"where": where, "text": text}


def identity(store, meta, company):
    out = []
    if not model.same_company(meta.get("company"), company):
        out.append(_e("file", f"This update is {meta.get('company')}'s "
                      f"template, but it came in as {company}'s. It was "
                      "not used."))
    return out


def check(store, parsed, company):
    """{"errors", "warnings", "own", "ignored", "not_reported", "new"}.
    own: [{"key", "no", "name", "values", "base", "where"}] with values
    normalized (durations whole workdays)."""
    errors = list(parsed.get("errors") or [])
    warnings = list(parsed.get("warnings") or [])
    out = {"errors": errors, "warnings": warnings, "own": [],
           "ignored": [], "not_reported": [], "new": []}
    meta = parsed.get("meta") or {}
    if not meta:                  # unreadable / not our template: stop
        return out
    # cell-level problems found while reading don't stop the checks:
    # every reason is collected before the whole file is rejected
    errors += identity(store, meta, company)
    try:
        dd = _dt.date.fromisoformat(str(meta.get("cycle"))[:10])
    except ValueError:
        errors.append(_e("file", "The update has no cycle date."))
        return out
    acts = {a["_id"]: a for a in store.list("activity")}
    mine = set(model.slice_ids(store, company))
    reported = set()
    for r in parsed.get("rows") or []:
        a = acts.get(r["key"])
        if r["ctx"]:
            moved = sorted(f for f in r["values"]
                           if r["values"].get(f) != r["base"].get(f))
            if moved:
                out["ignored"].append({"_id": r["key"], "_no": r["no"],
                                       "name": r.get("name"),
                                       "fields": moved,
                                       "why": "another trade's activity"})
                warnings.append(_e(r["where"][moved[0]],
                                   f"{r['no']} isn't {company}'s - the "
                                   "edit was ignored (flagged for you)."))
            continue
        if a is None:
            warnings.append(_e(f"Update!A{r['row']}", f"{r['no']} is no "
                               "longer in the master schedule - ignored."))
            continue
        if r["key"] not in mine:
            out["ignored"].append({"_id": r["key"], "_no": r["no"],
                                   "name": r.get("name"),
                                   "fields": list(FIELDS),
                                   "why": "no longer this sub's"})
            warnings.append(_e(f"Update!A{r['row']}", f"{r['no']} is no "
                               f"longer {company}'s - ignored."))
            continue
        reported.add(r["key"])
        out["own"].append(_row(r, a, dd, errors, warnings))
    out["not_reported"] = sorted(acts[i].get("_no") for i in mine
                                 if i not in reported)
    own_dur = {r["no"]: (r["values"].get("duration") or 0)
               for r in out["own"]}
    nos = {acts[i].get("_no"): i for i in mine}
    totals = {}
    for n in parsed.get("new") or []:
        w = n["where"]
        if not n["name"]:
            errors.append(_e(w, "A new activity needs a name."))
        d = n.get("duration")
        if d is None and not any(x["where"].startswith("New activities!B"
                                                       + str(n["row"]))
                                 for x in errors):
            errors.append(_e(w, f"New activity '{n['name']}': give a "
                          "duration in workdays."))
        elif d is not None and d < 0:
            errors.append(_e(w, f"New activity '{n['name']}': a duration "
                          "can't be below 0."))
        if n["parent_no"] not in nos:
            errors.append(_e(w, f"New activity '{n['name']}': master "
                          f"activity '{n['parent_no']}' isn't yours - "
                          "pick one of your activities."))
        else:
            totals[n["parent_no"]] = totals.get(n["parent_no"], 0) + \
                (d or 0)
        out["new"].append({k: n.get(k) for k in ("name", "duration",
                                                 "parent_no", "note",
                                                 "where")})
    for no, tot in sorted(totals.items()):
        dur = own_dur.get(no) or 0
        if tot > dur:
            warnings.append(_e("New activities", f"The new internal "
                               f"activities under {no} total {tot:g} "
                               f"workdays, longer than {no} itself "
                               f"({dur:g} workdays)."))
    return out


def _row(r, a, dd, errors, warnings):
    v = dict(r["values"])
    b = r["base"]
    no, W = r["no"], r["where"]
    d = v.get("duration")
    if d is None and b.get("duration") is not None:
        errors.append(_e(W["duration"], f"{no}: the duration is blank."))
    elif d is not None:
        if d < 0:
            errors.append(_e(W["duration"], f"{no}: a duration can't be "
                          "below 0."))
        elif d == 0 and (b.get("duration") or 0) != 0:
            errors.append(_e(W["duration"], f"{no}: 0 workdays would make "
                          "it a milestone - milestones are the GC's."))
        elif d != int(d):
            up = int(math.ceil(d))
            warnings.append(_e(W["duration"], f"{no}: {d:g} workdays "
                               f"rounded up to {up}."))
            v["duration"] = up
    pc = v.get("percent")
    if pc is not None and not 0 <= pc <= 100:
        errors.append(_e(W["percent"], f"{no}: % complete must be 0 to "
                      f"100 (it says {pc:g})."))
    st, fi = v.get("actual_start"), v.get("actual_finish")
    if fi and not st:
        errors.append(_e(W["actual_finish"], f"{no}: an actual finish "
                      "without an actual start."))
    if st and fi and fi < st:
        errors.append(_e(W["actual_finish"], f"{no}: actual finish {fi} "
                      f"is before the actual start {st}."))
    for f in ("actual_start", "actual_finish"):
        if v.get(f) and v[f] > dd.isoformat():
            errors.append(_e(W[f], f"{no}: {f.replace('_', ' ')} {v[f]} "
                          f"is after the data date {dd.isoformat()}."))
    if pc is not None and 0 <= pc <= 100:
        if pc == 100 and not fi:
            errors.append(_e(W["percent"], f"{no}: 100 % complete needs "
                          "an actual finish."))
        if fi and pc < 100:
            errors.append(_e(W["percent"], f"{no}: an actual finish needs "
                          "100 % complete."))
    ef = v.get("expected_finish")
    if ef:
        if d is not None and d != b.get("duration"):
            errors.append(_e(W["expected_finish"], f"{no}: Duration and "
                          "Expected finish disagree - fill in one of "
                          "them."))
        if ef < dd.isoformat() and not fi:
            errors.append(_e(W["expected_finish"], f"{no}: expected "
                          f"finish {ef} is before the data date - give an "
                          "actual finish instead."))
        if fi:
            errors.append(_e(W["expected_finish"], f"{no}: it has an "
                          "actual finish, so no expected finish."))
    return {"key": r["key"], "no": no, "name": a.get("name"), "values": v,
            "base": dict(b), "where": W,
            "matched_by": r.get("matched_by", "template id")}
