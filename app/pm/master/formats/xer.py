"""Primavera P6 .xer export -> neutral rows (design 3.3-3.4).

A NEW read-only path: never calls the Scheduler's import_xer / _merge.
Master ID: the activity code named by setting "xer_code" (default
"QuantiSheet ID"), then the task code as an activity number (a name
mismatch is warned), then an activity made by an earlier Scheduler
import (_ext "p6:<task_id>"). Unmatched rows map once by "p6:<task
code>"."""
import os
import re

from .. import model
from . import common


def _num(v):
    try:
        return float(str(v).strip()) if str(v or "").strip() else None
    except ValueError:
        return None


_EXC = re.compile(r"\(d\|(\d{5})\)\s*\(\s*\)")


def calendar_days_off(clndr_data):
    """The non-work exception days of a P6 calendar (clndr_data): each
    is '(d|<Excel serial day>)()' with no work periods under it."""
    import datetime as dt
    out = set()
    text = clndr_data or ""
    i = text.find("Exceptions")
    for m in _EXC.finditer(text[i:] if i >= 0 else ""):
        try:
            out.add((dt.date(1899, 12, 30) +
                     dt.timedelta(days=int(m.group(1)))).isoformat())
        except (OverflowError, ValueError):
            continue
    return out


def _compare_holidays(store, tables, dd, out):
    """The sub's default calendar's days off against the master's
    holidays (warned, never changed) - as the MS Project reader does."""
    from ... import schedule
    cals = tables.get("CALENDAR") or []
    cal = next((c for c in cals if c.get("default_flag") == "Y"),
               cals[0] if cals else None)
    if not cal:
        return
    file_hol = calendar_days_off(cal.get("clndr_data"))
    if not file_hol:
        return
    lo = dd.replace(day=1).isoformat()
    hi = dd.replace(year=dd.year + 1).isoformat()
    master = {d.isoformat() for d in
              schedule.Calendar(dd, store.setting("holidays") or ()).hol}
    extra = sorted(d for d in file_hol - master if lo <= d <= hi)
    missing = sorted(d for d in master - file_hol if lo <= d <= hi)
    if extra or missing:
        out["warnings"].append(common.err(
            "calendar", "The sub's P6 calendar differs from the master's "
            "(the master calendar is used; nothing is changed)." +
            (" Sub's days off not in the master: " + ", ".join(extra) +
             "." if extra else "") +
            (" Master days off the sub works: " + ", ".join(missing) + "."
             if missing else "")))


def read(store, path, company, now=None):
    out = common.new_out("xer")
    name = os.path.basename(path)
    data = common.load(path, out)
    if data is None:
        return out
    lines = data.decode("cp1252", errors="replace").splitlines()
    if not lines or not lines[0].startswith("ERMHDR"):
        out["errors"].append(common.err(name, "This isn't a Primavera P6 "
                                        "XER export (no ERMHDR line)."))
        return out
    tables, cur, fields = {}, None, []
    for ln in lines[1:]:
        parts = ln.split("\t")
        if parts[0] == "%T" and len(parts) > 1:
            cur = parts[1]
            tables.setdefault(cur, [])
        elif parts[0] == "%F":
            fields = parts[1:]
        elif parts[0] == "%R" and cur:
            tables[cur].append(dict(zip(fields, parts[1:])))
    if not tables.get("TASK"):
        out["errors"].append(common.err(name, "No activities (TASK table) "
                                        "in this XER file."))
        return out
    projs = tables.get("PROJECT") or []
    if len(projs) > 1:
        out["errors"].append(common.err(name, "The XER holds more than one "
                                        "project - export only yours."))
        return out
    if len(tables["TASK"]) > common.MAX_ROWS:
        out["errors"].append(common.err(name, f"More than {common.MAX_ROWS} "
                                        "activities."))
        return out
    status = (projs[0].get("last_recalc_date") or "")[:10] if projs else ""
    dd = common.data_date(store, status, out, now)
    per_day = 8.0
    for c in tables.get("CALENDAR") or []:
        if c.get("default_flag") == "Y" and _num(c.get("day_hr_cnt")):
            per_day = _num(c.get("day_hr_cnt"))
    _compare_holidays(store, tables, dd, out)
    want = model.config(store).get("xer_code") or "QuantiSheet ID"
    tid = {r.get("actv_code_type_id") for r in tables.get("ACTVTYPE") or []
           if (r.get("actv_code_type") or "").strip() == want}
    vals_by = {r.get("actv_code_id"): r.get("short_name")
               for r in tables.get("ACTVCODE") or []
               if r.get("actv_code_type_id") in tid}
    code_of = {r.get("task_id"): vals_by.get(r.get("actv_code_id"))
               for r in tables.get("TASKACTV") or []
               if r.get("actv_code_id") in vals_by}
    preds = {}
    for p in tables.get("TASKPRED") or []:
        preds.setdefault(p.get("task_id"), []).append(
            f"p6id:{p.get('pred_task_id')}")
    items = []
    for k, tk in enumerate(tables["TASK"], 1):
        code = (tk.get("task_code") or "").strip()
        nm = tk.get("task_name") or code
        where = f"Activity {code} '{nm}'"
        if (tk.get("task_type") or "") == "TT_WBS":
            continue
        hrs = _num(tk.get("target_drtn_hr_cnt"))
        pc = _num(tk.get("phys_complete_pct"))
        if pc is not None and pc == int(pc):
            pc = int(pc)
        v = {"duration": common.duration(hrs, per_day), "percent": pc}
        for f, col in (("actual_start", "act_start_date"),
                       ("actual_finish", "act_end_date")):
            d = (tk.get(col) or "").strip()[:10]
            if d and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d):
                out["errors"].append(common.err(where, f"{col} '{d}' isn't "
                                                "a date."))
                d = ""
            v[f] = d or None
        if v["actual_finish"] and v["actual_start"]:
            v["percent"] = 100
        ids = []
        if code_of.get(tk.get("task_id")):
            ids.append(("activity code", code_of[tk.get("task_id")]))
        ids.append(("task code", code))
        items.append({"ref": f"p6:{code}", "ids": ids,
                      "ext": f"p6:{tk.get('task_id')}", "name": nm,
                      "where": where, "values": v, "row": k,
                      "link_key": f"p6id:{tk.get('task_id')}",
                      "links": preds.get(tk.get("task_id"), [])})
    # (no project id here: reading must not create one - it writes)
    out["meta"] = {"company": company, "cycle": dd.isoformat(),
                   "rev": "unknown"}
    return common.build(store, company, items, out, want)
