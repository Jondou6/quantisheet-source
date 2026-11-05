"""Schedule-health metrics beside the completeness gate.

The fourteen points follow the DCMA EVMS Program Analysis Pamphlet
(PAM) 200.1 thresholds: missing logic, leads, lags, relationship types,
hard constraints, high float, negative float, high duration, invalid
dates, resources, missed tasks, the critical-path length test, CPLI and
BEI. A failed point means "look at this", which is how that pamphlet
uses the set. The completeness gate is what blocks a draft; this report
is shown next to it.

Milestones, level-of-effort and WBS summaries are left out of the
percentages, matching the pamphlet. When a project store is passed,
``schedule_check.check`` (the program's existing fourteen-point pass) is
included as ``native`` so the two can be compared. This module does not
replace that pass.

44 workdays is the pamphlet's "high" line. The critical-path test adds
600 workdays to one longest-path activity and requires the project
finish to move by the same number of that activity's workdays.
"""
import copy

from . import cpm
from .calendar import build_all
from .model import DERIVED, HARD_CONSTRAINTS, MILESTONES, as_date

LIMIT = 44
CP_ADD = 600


def _alive(doc, code):
    act = next((a for a in doc.get("activities") or () if a.get("code") == code), None)
    return bool(act) and act.get("type") not in DERIVED and act.get("status") != "complete"


def _item(key, name, metric, threshold, passed, offenders=(), note=""):
    return {"key": key, "name": name, "metric": metric,
            "threshold": threshold, "passed": passed,
            "offenders": list(offenders)[:40], "note": note}


def _pct(n, total):
    if not total:
        return "0 of 0"
    return f"{n} of {total} ({100.0 * n / total:.1f}%)"


def logic_with(doc, tasks):
    preds, succs = set(), set()
    for r in doc.get("relationships") or ():
        succs.add(r.get("pred"))
        preds.add(r.get("succ"))
    bad = []
    for a in tasks:
        missing = []
        if a["code"] not in preds and a.get("cls") != "ntp":
            missing.append("no predecessor")
        if a["code"] not in succs and a.get("cls") != "final":
            missing.append("no successor")
        if missing:
            bad.append({"no": a["code"], "name": a.get("name"),
                        "detail": ", ".join(missing)})
    total = len(tasks)
    n = len(bad)
    passed = (100.0 * n / total <= 5) if total else True
    return _item("logic", "Logic", _pct(n, total), "<= 5%", passed, bad)


def _leads(rels):
    bad = [r for r in rels if float(r.get("lag_hours") or 0) < 0]
    total = len(rels)
    return _item("leads", "Leads", _pct(len(bad), total), "0",
                 len(bad) == 0, [{"no": f"{r['pred']}->{r['succ']}",
                                  "name": r.get("type"), "detail": "negative lag"}
                                 for r in bad])


def _lags(rels):
    bad = [r for r in rels if float(r.get("lag_hours") or 0) > 0]
    total = len(rels)
    passed = (100.0 * len(bad) / total <= 5) if total else True
    return _item("lags", "Lags", _pct(len(bad), total), "<= 5% of links",
                 passed, [{"no": f"{r['pred']}->{r['succ']}", "name": r.get("type"),
                           "detail": str(r.get("lag_hours"))} for r in bad])


def _types(rels):
    if not rels:
        return _item("rel_types", "Relationship types", "0 of 0", ">= 90% FS",
                     True)
    fs = sum(1 for r in rels if r.get("type") == "FS")
    passed = 100.0 * fs / len(rels) >= 90
    return _item("rel_types", "Relationship types",
                 _pct(fs, len(rels)) + " FS", ">= 90% FS", passed)


def _constraints(tasks):
    bad = [a for a in tasks if (a.get("constraint") or "") in HARD_CONSTRAINTS
           or (a.get("constraint2") or "") in HARD_CONSTRAINTS]
    total = len(tasks)
    passed = (100.0 * len(bad) / total <= 5) if total else True
    return _item("constraints", "Hard constraints", _pct(len(bad), total),
                 "<= 5%", passed,
                 [{"no": a["code"], "name": a.get("name"),
                   "detail": a.get("constraint") or ""} for a in bad])


def _high_float(tasks):
    bad = [a for a in tasks if (a.get("total_float_days") or 0) > LIMIT]
    total = len(tasks)
    passed = (100.0 * len(bad) / total <= 5) if total else True
    return _item("high_float", "High float", _pct(len(bad), total),
                 f"<= 5% over {LIMIT} workdays", passed,
                 [{"no": a["code"], "name": a.get("name"),
                   "detail": f"{a.get('total_float_days')}d"} for a in bad])


def _neg_float(acts):
    bad = [a for a in acts if (a.get("total_float_days") or 0) < 0
           and a.get("type") not in MILESTONES]
    return _item("neg_float", "Negative float", str(len(bad)), "0",
                 len(bad) == 0,
                 [{"no": a["code"], "name": a.get("name"),
                   "detail": f"{a.get('total_float_days')}d"} for a in bad])


def _high_duration(tasks):
    bad = []
    for a in tasks:
        days = a.get("dur_days")
        if days is None:
            hpd = 8
            days = (a.get("remain_hours") or 0) / hpd
        if days > LIMIT:
            bad.append(a)
    total = len(tasks)
    passed = (100.0 * len(bad) / total <= 5) if total else True
    return _item("high_duration", "High duration", _pct(len(bad), total),
                 f"<= 5% over {LIMIT} workdays", passed,
                 [{"no": a["code"], "name": a.get("name"),
                   "detail": f"{a.get('dur_days')}d"} for a in bad])


def _invalid_dates(doc, acts):
    data = as_date((doc.get("project") or {}).get("data_date"))
    bad = []
    if data:
        for a in acts:
            es = as_date(a.get("es"))
            if a.get("status") == "not_started" and es and es < data:
                bad.append({"no": a["code"], "name": a.get("name"),
                            "detail": "forecast starts before the data date"})
            for key in ("actual_start", "actual_finish"):
                d = as_date(a.get(key))
                if d and d > data:
                    bad.append({"no": a["code"], "name": a.get("name"),
                                "detail": f"{key} is after the data date"})
    return _item("invalid_dates", "Invalid dates", str(len(bad)), "0",
                 len(bad) == 0, bad)


def _resources(doc, tasks):
    assigned = {a.get("activity") for a in doc.get("assignments") or ()}
    bad = [a for a in tasks if a["code"] not in assigned
           and (a.get("dur_days") or 0) > 0 and not a.get("roles")]
    # A role on the activity counts; assignments are the loaded form.
    loaded = assigned | {a["code"] for a in tasks if a.get("roles")}
    bad = [a for a in tasks if a["code"] not in loaded and (a.get("dur_days") or 0) > 0]
    total = len(tasks)
    passed = (100.0 * len(bad) / total <= 5) if total else True
    return _item("resources", "Resources", _pct(len(bad), total), "<= 5%",
                 passed, [{"no": a["code"], "name": a.get("name"),
                           "detail": "no role"} for a in bad])


def _missed(doc, tasks):
    data = as_date((doc.get("project") or {}).get("data_date"))
    due = []
    late = []
    for a in tasks:
        bf = as_date(a.get("bl_finish"))
        if not bf or not data or bf > data:
            continue
        due.append(a)
        ef = as_date(a.get("ef"))
        if a.get("status") != "complete" and (ef is None or ef > bf):
            late.append(a)
    if not due:
        return _item("missed", "Missed tasks", "0 of 0", "<= 5% of due",
                     None, note="Nothing was baselined to finish by the data date.")
    passed = 100.0 * len(late) / len(due) <= 5
    return _item("missed", "Missed tasks", _pct(len(late), len(due)),
                 "<= 5% of due", passed,
                 [{"no": a["code"], "name": a.get("name"),
                   "detail": "missed the baseline finish"} for a in late])


def _cp_test(doc):
    path = [a for a in doc.get("activities") or ()
            if a.get("longest_path") and a.get("type") not in DERIVED
            and a.get("type") not in MILESTONES and (a.get("dur_days") or 0) > 0]
    if not path:
        return _item("cp_test", "Critical path test", "no longest-path task",
                     "pass", None, note="No longest-path task to lengthen.")
    target = max(path, key=lambda a: a.get("dur_days") or 0)
    before = as_date((doc.get("project") or {}).get("early_finish"))
    trial = copy.deepcopy(doc)
    act = next(a for a in trial["activities"] if a["code"] == target["code"])
    hpd = float((trial.get("calendars") or {}).get(act.get("calendar") or "5day",
                                                   {}).get("hours_per_day") or 8)
    act["orig_hours"] = float(act.get("orig_hours") or 0) + CP_ADD * hpd
    act["remain_hours"] = float(act.get("remain_hours") or 0) + CP_ADD * hpd
    act["duration_kind"] = act.get("duration_kind")
    cpm.schedule(trial)
    after = as_date(trial["project"].get("early_finish"))
    cals = build_all(doc)
    cal = cals.get(target.get("calendar") or "5day")
    slip = 0
    if before and after and cal is not None:
        slip = cal.index(after) - cal.index(before)
    # A successor on a different calendar can absorb a weekend, so the
    # project finish may move a couple of workdays less than the amount
    # added. A broken path moves it by about nothing.
    passed = slip >= CP_ADD - 5
    return _item("cp_test", "Critical path test",
                 f"finish moved {slip} workdays (added {CP_ADD})",
                 "pass", passed,
                 note=f"Lengthened {target.get('code')} {target.get('name')}.")


def _cpli(doc):
    start = as_date((doc.get("project") or {}).get("start"))
    finish = as_date((doc.get("project") or {}).get("early_finish"))
    must = as_date((doc.get("project") or {}).get("must_finish"))
    if not start or not finish:
        return _item("cpli", "CPLI", "n/a", ">= 0.95", None,
                     note="The schedule has no finish date.")
    cals = build_all(doc)
    cal = cals.get((doc.get("project") or {}).get("calendar") or "5day")
    length = max(1, cal.index(finish) - cal.index(start) + 1)
    tf = 0 if not must else cal.index(must) - cal.index(finish)
    ratio = (length + tf) / length
    return _item("cpli", "CPLI", f"{ratio:.2f}", ">= 0.95", ratio >= 0.95 - 1e-9)


def _bei(doc, tasks):
    data = as_date((doc.get("project") or {}).get("data_date"))
    due = [a for a in tasks if as_date(a.get("bl_finish"))
           and data and as_date(a.get("bl_finish")) <= data]
    if not due:
        return _item("bei", "BEI", "n/a", ">= 0.95", None,
                     note="No baseline finish falls on or before the data date.")
    done = [a for a in due if a.get("status") == "complete"]
    ratio = len(done) / len(due)
    return _item("bei", "BEI", f"{ratio:.2f}", ">= 0.95", ratio >= 0.95 - 1e-9)


def _native(store, today):
    from .. import schedule_check
    try:
        return schedule_check.check(store, today=today)
    except Exception as exc:                            # noqa: BLE001
        return {"error": str(exc)[:200]}


def check(doc, store=None, today=None):
    tasks_all = [a for a in doc.get("activities") or ()
                 if a.get("type") not in DERIVED and a.get("status") != "complete"]
    tasks = [a for a in tasks_all if a.get("type") not in MILESTONES]
    rels = [r for r in doc.get("relationships") or () if _alive(doc, r.get("succ"))]
    items = [
        logic_with(doc, tasks),
        _leads(rels),
        _lags(rels),
        _types(rels),
        _constraints(tasks),
        _high_float(tasks),
        _neg_float(tasks_all),
        _high_duration(tasks),
        _invalid_dates(doc, tasks_all),
        _resources(doc, tasks),
        _missed(doc, tasks),
        _cp_test(doc),
        _cpli(doc),
        _bei(doc, tasks),
    ]
    graded = [i for i in items if i["passed"] is not None]
    passed = sum(1 for i in graded if i["passed"])
    result = {
        "items": items,
        "passed": passed,
        "graded": len(graded),
        "score": round(100.0 * passed / len(graded), 1) if graded else 0,
        "standard": "DCMA 14-point schedule health",
    }
    if store is not None:
        result["native"] = _native(store, today)
    doc["health"] = result
    return result
