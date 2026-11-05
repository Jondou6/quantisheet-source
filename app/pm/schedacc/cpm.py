"""Critical-path pass for a compiled schedule.

``app.pm.schedule.compute`` remains the Gantt's pass. It has one
Monday-to-Friday calendar, so it cannot place a 7-day cure or a weather
calendar. This pass reuses ``schedule.Calendar`` (through
``calendar.WorkCalendar``) and implements the rest: four relationship
types, a lag calendar, the ten constraint types, retained logic / progress
override / actual dates, start and finish float, the longest path, and
several float paths.

Algorithm (the reference engine's order, steps 1-10):

1. Validate and break loops.
2. Topological order.
3. Forward pass.
4. Backward pass from the early finish, or from the must-finish date.
5. Float (start, finish, or the smaller of the two).
6. Critical flag (total float at or under the threshold, or the longest path).
7. Longest path: activities whose early finish is the project's early
   finish, then every driving predecessor back to the start.
8. Several float paths.
9. Level of effort and WBS summary dates (they never push other work).
10. As-late-as-possible: early dates slide by free float only.

Durations are hours. A workday is the calendar's hours-per-day.
"""
import datetime as _dt
from collections import defaultdict

from . import calendar as calmod
from .model import (
    ACTIVE, ALAP, COMPLETE, DERIVED, FINISH_MS, MAND_FIN, MAND_START,
    MEO, MEOA, MEOB, MSO, MSOA, MSOB, NOT_STARTED, START_MS, as_date, iso,
)

DAY = _dt.timedelta(days=1)


def schedule(doc):
    """Run the pass. Fills dates, float and the log on ``doc``."""
    log = []
    doc["log"] = log
    cals = calmod.build_all(doc)
    acts = [a for a in doc.get("activities") or ()]
    by = {}
    for a in acts:
        if a.get("code") in by:
            log.append(f"Duplicate activity id {a.get('code')} ignored.")
            continue
        by[a["code"]] = a
        _prepare(a, cals, doc, log)
    rels = [r for r in doc.get("relationships") or ()
            if _rel_ok(r, by, doc, log)]
    doc["relationships"] = rels
    graph_rels = [r for r in rels if not _derived(by[r["pred"]])
                  and not _derived(by[r["succ"]])]
    order, broken = _topo(list(by), graph_rels)
    for msg in broken:
        log.append(msg)
    fwd = [a for a in order if not _derived(by[a])]
    _forward(doc, by, fwd, graph_rels, cals, log)
    _backward(doc, by, list(reversed(fwd)), graph_rels, cals, log)
    _float(doc, by, fwd, graph_rels, cals)
    _longest(doc, by, graph_rels)
    _float_paths(doc, by, graph_rels)
    _derive(doc, by, rels, cals, log)
    _alap(doc, by, cals)
    _explain(doc, by, graph_rels)
    _statistics(doc, by, rels, log)
    for a in acts:
        a.pop("_cal", None)
    return doc


# ------------------------------------------------------------- prepare
def _prepare(act, cals, doc, log):
    key = act.get("calendar") or doc["project"].get("calendar") or "5day"
    if key not in cals:
        log.append(f"{act.get('code')}: calendar '{key}' is missing; "
                   "the 5-day workweek is used.")
        key = "5day" if "5day" in cals else next(iter(cals))
        act["calendar"] = key
    cal = cals[key]
    # Resource-dependent work uses the intersection of its calendar and
    # the calendars of its roles' resources, when those calendars exist.
    if act.get("type") == "resource":
        parts = [cal]
        for role in act.get("roles") or ():
            rc = cals.get(_resource_calendar(doc, role))
            if rc is not None:
                parts.append(rc)
        if len(parts) > 1:
            cal = calmod.IntersectCalendar(
                cal.base, parts, name="Resource calendar", key=key)
    if act.get("suspend") and act.get("resume"):
        cal = _with_gap(cal, act["suspend"], act["resume"])
    act["_cal"] = cal
    act["_hpd"] = cal.hours_per_day
    hpd = cal.hours_per_day
    if act.get("type") in (START_MS, FINISH_MS):
        act["orig_hours"] = 0.0
        act["remain_hours"] = 0.0
    else:
        act["orig_hours"] = float(act.get("orig_hours") or 0)
        if act.get("remain_hours") is None:
            act["remain_hours"] = act["orig_hours"]
        act["remain_hours"] = float(act.get("remain_hours") or 0)
    if act.get("status") == COMPLETE or act.get("actual_finish"):
        act["status"] = COMPLETE
        act["remain_hours"] = 0.0
        act["percent"] = 100.0
    elif act.get("actual_start") or float(act.get("percent") or 0) > 0:
        act["status"] = ACTIVE
        if act.get("pct_type", "duration") == "duration":
            pct = min(100.0, max(0.0, float(act.get("percent") or 0)))
            act["remain_hours"] = act["orig_hours"] * (1.0 - pct / 100.0)
    else:
        act.setdefault("status", NOT_STARTED)
    act["dur_days"] = 0 if act.get("type") in (START_MS, FINISH_MS) \
        else (act["remain_hours"] / hpd if hpd else 0)
    _blank_dates(act)


def _with_gap(cal, suspend, resume):
    """Days from suspend through the day before resume are not work."""
    extra = []
    d = as_date(suspend)
    end = as_date(resume)
    while d and end and d < end:
        extra.append(d.isoformat())
        d += DAY
    return calmod.WorkCalendar(
        cal.base, holidays=list(cal.hol) + extra, weekdays=cal.weekdays,
        months_off=cal.months_off, hours_per_day=cal.hours_per_day,
        name=cal.name, key=cal.key)


def _resource_calendar(doc, role):
    for res in doc.get("resources") or ():
        if res.get("role") == role or res.get("name") == role:
            return res.get("calendar") or ""
    return ""


def _derived(act):
    return act.get("type") in DERIVED


def _blank_dates(act):
    for k in ("es", "ef", "ls", "lf", "why", "driving_pred", "driving_succ"):
        act.setdefault(k, "")
    act.setdefault("total_float_days", 0)
    act.setdefault("free_float_days", 0)
    act.setdefault("critical", False)
    act.setdefault("longest_path", False)
    act.setdefault("near_critical", False)
    act.setdefault("float_path", 0)
    act.setdefault("float_path_order", 0)


def _rel_ok(rel, by, doc, log):
    pred, succ = rel.get("pred"), rel.get("succ")
    if pred not in by or succ not in by:
        if doc["options"].get("ignore_external", True):
            owner = succ if succ in by else pred
            if owner in by:
                by[owner]["external_early_start"] = \
                    by[owner].get("external_early_start") or ""
            log.append(f"Relationship {pred} -> {succ} points outside the "
                       "schedule and was skipped.")
            return False
        log.append(f"Relationship {pred} -> {succ} is incomplete.")
        return False
    if str(rel.get("type") or "FS").upper() not in ("FS", "SS", "FF", "SF"):
        log.append(f"Relationship {pred} -> {succ} has an unknown type "
                   "and was skipped.")
        return False
    rel["type"] = str(rel.get("type") or "FS").upper()
    rel["lag_hours"] = float(rel.get("lag_hours") or 0)
    rel["driving"] = False
    rel["free_float_days"] = 0
    return True


def _topo(codes, rels):
    preds = defaultdict(set)
    succs = defaultdict(set)
    for r in rels:
        preds[r["succ"]].add(r["pred"])
        succs[r["pred"]].add(r["succ"])
    indeg = {c: len(preds.get(c, ())) for c in codes}
    order = [c for c in codes if indeg[c] == 0]
    k = 0
    while k < len(order):
        for s in succs.get(order[k], ()):
            indeg[s] -= 1
            if indeg[s] == 0:
                order.append(s)
        k += 1
    broken = []
    if len(order) < len(codes):
        left = [c for c in codes if c not in set(order)]
        broken.append(
            "These activities depend on each other in a loop and were "
            "scheduled without those links: " + ", ".join(left))
        drop = set(left)
        rels[:] = [r for r in rels if r["pred"] not in drop
                   or r["succ"] not in drop]
        return _topo(codes, rels)[0], broken
    return order, broken


# ------------------------------------------------------------- lag calendar
def _lag_cal(doc, rel, pred, succ, cals):
    choice = (rel.get("lag_calendar")
              or doc["options"].get("lag_calendar") or "successor")
    if choice == "predecessor":
        return pred["_cal"]
    if choice == "24hour":
        return cals.get("24hour") or succ["_cal"]
    if choice == "project":
        key = doc["project"].get("calendar") or "5day"
        return cals.get(key) or pred["_cal"]
    return succ["_cal"]


def _lag_days(rel, lag_cal):
    hpd = lag_cal.hours_per_day or 8
    return rel.get("lag_hours", 0) / hpd


def _dur_days(act):
    if act.get("type") in (START_MS, FINISH_MS):
        return 0
    return float(act.get("dur_days") or 0)


# ------------------------------------------------------------- forward
def _forward(doc, by, order, rels, cals, log):
    proj_start = as_date(doc["project"].get("start"))
    data = as_date(doc["project"].get("data_date")) or proj_start
    incoming = defaultdict(list)
    for r in rels:
        incoming[r["succ"]].append(r)
    for code in order:
        act = by[code]
        cal = act["_cal"]
        status = act.get("status") or NOT_STARTED
        if status == COMPLETE and act.get("actual_start") and \
                act.get("actual_finish"):
            es = calmod.snap_forward(cal, act["actual_start"])
            ef = calmod.snap_back(cal, act["actual_finish"])
            if cal.index(ef) < cal.index(es):
                ef = es
            act["es"], act["ef"] = es.isoformat(), ef.isoformat()
            act["dur_days"] = 0
            continue
        dur = _dur_days(act)
        if status == ACTIVE and doc["options"].get("use_expected_finish") \
                and act.get("expected_finish"):
            exp = as_date(act["expected_finish"])
            base = calmod.snap_forward(cal, data)
            span = max(0, cal.index(exp) - cal.index(base) + 1)
            act["dur_days"] = span
            act["remain_hours"] = span * cal.hours_per_day
            dur = span
        es_min, driver = _early_start(
            doc, act, incoming[code], by, cals, data, proj_start, log)
        ef_min = None
        for rel in incoming[code]:
            pred = by[rel["pred"]]
            if not pred.get("ef"):
                continue
            bound = _min_finish(rel, pred, act, doc, cals)
            if bound is not None and (ef_min is None or bound > ef_min):
                ef_min = bound
                if act.get("type") == FINISH_MS:
                    driver = pred["code"]
        es, ef = _place(act, es_min, ef_min, dur, cal)
        es, ef = _forward_constraints(act, es, ef, dur, cal, data, log)
        # Out of sequence: an in-progress activity.
        if status == ACTIVE:
            es, ef = _out_of_sequence(
                doc, act, es, ef, dur, cal, data, incoming[code], by, log)
        act["es"], act["ef"] = es.isoformat(), ef.isoformat()
        act["driving_pred"] = driver or ""
        _mark_driving(act, incoming[code], by, doc, cals)


def _early_start(doc, act, rels, by, cals, data, proj_start, log):
    cal = act["_cal"]
    cands = []
    driver = ""
    if not rels:
        cands.append(calmod.snap_forward(cal, proj_start))
    mode = doc["options"].get("out_of_sequence") or "retained"
    started = act.get("status") == ACTIVE
    ignore_logic = started and mode == "override"
    if not ignore_logic:
        for rel in rels:
            pred = by[rel["pred"]]
            if not pred.get("es"):
                continue
            if rel["type"] in ("FF", "SF") and act.get("type") != FINISH_MS:
                continue
            when = _rel_early(doc, rel, pred, act, cals, data)
            if when is None:
                continue
            cands.append(when)
    if act.get("status") != COMPLETE:
        cands.append(calmod.snap_forward(cal, data))
    if not cands:
        cands.append(calmod.snap_forward(cal, proj_start))
    es = max(cands, key=lambda d: cal.index(d))
    # Which predecessor produced it.
    for rel in rels:
        pred = by[rel["pred"]]
        if not pred.get("es"):
            continue
        when = _rel_early(doc, rel, pred, act, cals, data)
        if when is not None and cal.index(when) == cal.index(es):
            driver = pred["code"]
            break
    return es, driver


def _rel_early(doc, rel, pred, succ, cals, data):
    """The successor date this relationship requires (start, or finish for
    a finish milestone)."""
    lag_cal = _lag_cal(doc, rel, pred, succ, cals)
    lag = _lag_days(rel, lag_cal)
    pred_es = as_date(pred["es"])
    pred_ef = as_date(pred["ef"])
    kind = rel["type"]
    # Started predecessor, start-to-start lag counted from the data date
    # or from the early start, depending on the option.
    if kind == "SS" and pred.get("actual_start") and \
            pred.get("status") in (ACTIVE, COMPLETE):
        return _ss_started(doc, pred, succ, lag_cal, lag, data)
    if succ.get("type") == FINISH_MS and kind in ("FS", "FF"):
        base = pred_ef if kind == "FS" else pred_ef
        if kind == "SS":
            base = pred_es
        d = calmod.shift(lag_cal, base, lag)
        return calmod.snap_forward(succ["_cal"], d)
    if kind == "FS":
        if pred.get("type") == START_MS:
            d = calmod.shift(lag_cal, pred_es, lag)
        else:
            d = calmod.shift(lag_cal, pred_ef + DAY, lag)
        return calmod.snap_forward(succ["_cal"], d)
    if kind == "SS":
        d = calmod.shift(lag_cal, pred_es, lag)
        return calmod.snap_forward(succ["_cal"], d)
    return None


def _ss_started(doc, pred, succ, lag_cal, lag, data):
    """Remaining start-to-start lag after the predecessor has started.

    Early-start option: lag already used up between the actual start and
    the data date comes off the lag. Actual-start option: the remainder is
    counted forward from the data date.
    """
    actual = as_date(pred["actual_start"])
    expired = max(0, lag_cal.index(data) - lag_cal.index(actual))
    remain = lag - expired
    if (doc["options"].get("ss_lag_from") or "early") == "actual":
        d = calmod.shift(lag_cal, data, max(0, remain) if remain > 0 else remain)
    else:
        base = as_date(pred["es"]) or data
        d = calmod.shift(lag_cal, base, remain)
    return calmod.snap_forward(succ["_cal"], d)


def _min_finish(rel, pred, succ, doc, cals):
    if rel["type"] not in ("FF", "SF"):
        return None
    lag_cal = _lag_cal(doc, rel, pred, succ, cals)
    lag = _lag_days(rel, lag_cal)
    base = as_date(pred["ef"] if rel["type"] == "FF" else pred["es"])
    d = calmod.shift(lag_cal, base, lag)
    return calmod.snap_forward(succ["_cal"], d)


def _place(act, es, ef_min, dur, cal):
    es = calmod.snap_forward(cal, es)
    if act.get("type") == FINISH_MS or dur <= 0 and act.get("type") in (
            START_MS, FINISH_MS):
        ef = es
        if ef_min is not None and cal.index(ef_min) > cal.index(ef):
            ef = calmod.snap_forward(cal, ef_min)
            es = ef
        return es, ef
    ef = calmod.add_workdays(cal, es, dur)
    if ef_min is not None and cal.index(ef_min) > cal.index(ef):
        ef = calmod.snap_forward(cal, ef_min)
        es2 = calmod.sub_workdays(cal, ef, dur)
        # Never pull the start earlier than the start constraints.
        if cal.index(es2) > cal.index(es):
            es = es2
        ef = calmod.add_workdays(cal, es, dur)
    return es, ef


def _forward_constraints(act, es, ef, dur, cal, data, log):
    """Constraints that move early dates. Mandatory dates override logic
    and are reported when they disagree with it."""
    es, ef = _one_constraint(
        act, es, ef, dur, cal, act.get("constraint"),
        act.get("constraint_date"), data, log, "primary")
    es, ef = _one_constraint(
        act, es, ef, dur, cal, act.get("constraint2"),
        act.get("constraint2_date"), data, log, "secondary")
    if act.get("status") != COMPLETE:
        floor = calmod.snap_forward(cal, data)
        if cal.index(es) < cal.index(floor):
            es = floor
            ef = es if dur <= 0 else calmod.add_workdays(cal, es, dur)
    return es, ef


def _one_constraint(act, es, ef, dur, cal, kind, raw, data, log, which):
    if not kind:
        return es, ef
    if kind == ALAP:
        return es, ef
    date = as_date(raw)
    if date is None and kind not in (ALAP,):
        log.append(f"{act.get('code')}: {which} constraint has no date.")
        return es, ef
    if kind in (MSOA, MSO):
        gate = calmod.snap_forward(cal, date)
        if cal.index(es) < cal.index(gate):
            es = gate
            ef = es if dur <= 0 else calmod.add_workdays(cal, es, dur)
        if kind == MAND_START:
            pass
    if kind == MAND_START:
        gate = calmod.snap_forward(cal, date)
        if cal.index(gate) != cal.index(es):
            log.append(f"{act.get('code')}: mandatory start {date} "
                       f"overrides logic ({es}).")
        es = gate
        ef = es if dur <= 0 else calmod.add_workdays(cal, es, dur)
    if kind in (MEOA, MEO, MAND_FIN):
        gate = calmod.snap_forward(cal, date)
        if kind == MAND_FIN and cal.index(ef) != cal.index(gate):
            log.append(f"{act.get('code')}: mandatory finish {date} "
                       f"overrides logic ({ef}).")
            ef = gate
            es = ef if dur <= 0 else calmod.sub_workdays(cal, ef, dur)
        elif cal.index(ef) < cal.index(gate):
            ef = gate
            es2 = ef if dur <= 0 else calmod.sub_workdays(cal, ef, dur)
            if dur <= 0 or cal.index(es2) >= cal.index(es):
                es = es2
            else:
                ef = calmod.add_workdays(cal, es, dur)
    return es, ef


def _out_of_sequence(doc, act, es, ef, dur, cal, data, rels, by, log):
    mode = doc["options"].get("out_of_sequence") or "retained"
    if mode == "actual" and act.get("actual_start"):
        es = calmod.snap_forward(cal, act["actual_start"])
        ef = es if dur <= 0 else calmod.add_workdays(cal, es, dur)
        return es, ef
    if mode == "override":
        es = calmod.snap_forward(cal, data)
        ef = es if dur <= 0 else calmod.add_workdays(cal, es, dur)
        for rel in rels:
            pred = by[rel["pred"]]
            if rel["type"] == "FS" and pred.get("status") != COMPLETE:
                log.append(
                    f"{act.get('code')} is out of sequence with "
                    f"{pred.get('code')} (progress override).")
                break
        return es, ef
    # Retained logic: remaining work waits on unfinished predecessors and
    # on the data date. ``es`` already includes both.
    if act.get("actual_start"):
        for rel in rels:
            pred = by[rel["pred"]]
            if rel["type"] == "FS" and pred.get("status") != COMPLETE:
                log.append(
                    f"{act.get('code')} is out of sequence with "
                    f"{pred.get('code')} (retained logic).")
                break
    return es, ef


def _mark_driving(act, rels, by, doc, cals):
    cal = act["_cal"]
    es = as_date(act["es"])
    for rel in rels:
        pred = by[rel["pred"]]
        if not pred.get("es"):
            rel["driving"] = False
            continue
        when = _rel_early(doc, rel, pred, act, cals,
                          as_date(doc["project"].get("data_date")))
        if when is None:
            rel["driving"] = False
            continue
        rel["driving"] = cal.index(when) == cal.index(es)
        rel["free_float_days"] = cal.index(es) - cal.index(when)


# ------------------------------------------------------------- backward
def _backward(doc, by, order, rels, cals, log):
    early = []
    for a in by.values():
        if a.get("ef") and not _derived(a):
            early.append(as_date(a["ef"]))
    if not early:
        return
    natural = max(early)
    must = as_date(doc["project"].get("must_finish"))
    end = must or natural
    doc["project"]["early_finish"] = natural.isoformat()
    outgoing = defaultdict(list)
    incoming = defaultdict(set)
    for r in rels:
        outgoing[r["pred"]].append(r)
        incoming[r["succ"]].add(r["pred"])
    open_critical = bool(doc["options"].get("open_ends_critical"))
    for code in order:
        act = by[code]
        if not act.get("ef"):
            continue
        cal = act["_cal"]
        ef = as_date(act["ef"])
        es = as_date(act["es"])
        dur = _dur_days(act)
        if act.get("status") == COMPLETE:
            act["ls"], act["lf"] = es.isoformat(), ef.isoformat()
            continue
        succs = outgoing.get(code) or []
        if not succs and open_critical:
            lf, ls = ef, es
        else:
            lf = calmod.snap_back(cal, end)
            if cal.index(lf) < cal.index(ef) and must is None:
                lf = ef
            ls = es if dur <= 0 else calmod.sub_workdays(cal, lf, dur)
            for rel in succs:
                succ = by[rel["succ"]]
                if not succ.get("ls"):
                    continue
                cap_s, cap_f = _rel_late(doc, rel, act, succ, cals)
                if cap_f is not None and cal.index(cap_f) < cal.index(lf):
                    lf = cap_f
                if cap_s is not None and cal.index(cap_s) < cal.index(ls):
                    ls = cap_s
            if dur <= 0:
                # A milestone's start and finish are the same day. A
                # tightened late start has to pull the late finish with it.
                if cal.index(ls) < cal.index(lf):
                    lf = ls
                ls = lf
            else:
                lf_from_ls = calmod.add_workdays(cal, ls, dur)
                if cal.index(lf_from_ls) < cal.index(lf):
                    lf = lf_from_ls
                ls = calmod.sub_workdays(cal, lf, dur)
        ls, lf = _backward_constraints(act, ls, lf, dur, cal, log)
        act["ls"], act["lf"] = ls.isoformat(), lf.isoformat()
        # Driving successor: the one with the tightest late cap.
        best, best_i = "", None
        for rel in succs:
            succ = by[rel["succ"]]
            if not succ.get("ls"):
                continue
            cap_s, cap_f = _rel_late(doc, rel, act, succ, cals)
            mark = cap_f or cap_s
            if mark is None:
                continue
            idx = cal.index(mark)
            if best_i is None or idx < best_i:
                best_i, best = idx, succ["code"]
        act["driving_succ"] = best


def _rel_late(doc, rel, pred, succ, cals):
    """(late-start cap, late-finish cap) this successor imposes, either
    of them None when the relationship does not limit that side."""
    lag_cal = _lag_cal(doc, rel, pred, succ, cals)
    lag = _lag_days(rel, lag_cal)
    pred_cal = pred["_cal"]
    kind = rel["type"]
    succ_ls = as_date(succ["ls"])
    succ_lf = as_date(succ["lf"])
    if kind == "FS":
        if pred.get("type") == START_MS:
            d = calmod.shift(lag_cal, succ_ls, -lag)
            return calmod.snap_back(pred_cal, d), None
        # A finish milestone falls on the predecessor's finish date, so the
        # cap is that date. A task or a start milestone starts the next
        # work period, so the predecessor finishes the day before.
        if succ.get("type") == FINISH_MS:
            d = calmod.shift(lag_cal, succ_lf or succ_ls, -lag)
            return None, calmod.snap_back(pred_cal, d)
        shifted = calmod.shift(lag_cal, succ_ls, -lag)
        finish = shifted - DAY
        return None, calmod.snap_back(pred_cal, finish)
    if kind == "SS":
        d = calmod.shift(lag_cal, succ_ls, -lag)
        return calmod.snap_back(pred_cal, d), None
    if kind == "FF":
        d = calmod.shift(lag_cal, succ_lf, -lag)
        return None, calmod.snap_back(pred_cal, d)
    if kind == "SF":
        d = calmod.shift(lag_cal, succ_lf, -lag)
        return calmod.snap_back(pred_cal, d), None
    return None, None


def _backward_constraints(act, ls, lf, dur, cal, log):
    ls, lf = _one_back(act, ls, lf, dur, cal, act.get("constraint"),
                       act.get("constraint_date"))
    ls, lf = _one_back(act, ls, lf, dur, cal, act.get("constraint2"),
                       act.get("constraint2_date"))
    return ls, lf


def _one_back(act, ls, lf, dur, cal, kind, raw):
    if not kind or kind in (MSOA, MEOA, ALAP):
        return ls, lf
    date = as_date(raw)
    if date is None:
        return ls, lf
    if kind in (MSOB, MSO, MAND_START):
        gate = calmod.snap_back(cal, date) if kind == MSOB else \
            calmod.snap_forward(cal, date)
        if kind == MAND_START:
            ls = gate
            lf = ls if dur <= 0 else calmod.add_workdays(cal, ls, dur)
        elif cal.index(ls) > cal.index(gate) or kind == MSO:
            if kind == MSO:
                ls = calmod.snap_forward(cal, date)
            else:
                ls = gate if cal.index(gate) < cal.index(ls) else ls
            lf_from = ls if dur <= 0 else calmod.add_workdays(cal, ls, dur)
            if cal.index(lf_from) < cal.index(lf) or kind == MSO:
                lf = lf_from
    if kind in (MEOB, MEO, MAND_FIN):
        gate = calmod.snap_forward(cal, date) if kind != MEOB else \
            calmod.snap_back(cal, date)
        if kind == MAND_FIN:
            lf = calmod.snap_forward(cal, date)
        elif cal.index(lf) > cal.index(gate) or kind == MEO:
            lf = gate
        ls = lf if dur <= 0 else calmod.sub_workdays(cal, lf, dur)
    return ls, lf


# ------------------------------------------------------------- float
def _float(doc, by, order, rels, cals):
    method = doc["options"].get("total_float") or "smallest"
    threshold = float(doc["project"].get("critical_hours") or 0)
    near = float(doc["options"].get("near_critical_days") or 10)
    outgoing = defaultdict(list)
    for r in rels:
        outgoing[r["pred"]].append(r)
    for code in order:
        act = by[code]
        if not act.get("es") or not act.get("ls"):
            continue
        cal = act["_cal"]
        es, ef = as_date(act["es"]), as_date(act["ef"])
        ls, lf = as_date(act["ls"]), as_date(act["lf"])
        start_f = cal.index(ls) - cal.index(es)
        finish_f = cal.index(lf) - cal.index(ef)
        if method == "start":
            total = start_f
        elif method == "finish":
            total = finish_f
        else:
            total = start_f if abs(start_f) <= abs(finish_f) else finish_f
            if start_f < 0 or finish_f < 0:
                total = min(start_f, finish_f)
        act["start_float_days"] = start_f
        act["finish_float_days"] = finish_f
        act["total_float_days"] = total
        act["total_float_hours"] = total * cal.hours_per_day
        ff = _free_float(doc, act, outgoing.get(code) or [], by, cals)
        act["free_float_days"] = ff
        act["free_float_hours"] = ff * cal.hours_per_day
        crit = act["total_float_hours"] <= threshold + 1e-6
        if doc["options"].get("critical") == "longest":
            crit = False          # set after the longest-path trace
        if act.get("status") == COMPLETE or _derived(act):
            crit = False
        act["critical"] = bool(crit)
        act["near_critical"] = (not crit) and 0 < total <= near


def _free_float(doc, act, rels, by, cals):
    """How far the early finish can slip before any successor's early date
    moves. Measured in the predecessor's calendar."""
    if act.get("status") == COMPLETE:
        return 0
    if not rels:
        return act.get("total_float_days") or 0
    cal = act["_cal"]
    ef = as_date(act["ef"])
    es = as_date(act["es"])
    vals = []
    for rel in rels:
        succ = by.get(rel["succ"])
        if not succ or not succ.get("es"):
            continue
        fake = dict(succ)
        fake["ls"], fake["lf"] = succ.get("es"), succ.get("ef")
        cap_s, cap_f = _rel_late(doc, rel, act, fake, cals)
        if cap_f is not None and ef is not None:
            vals.append(cal.index(cap_f) - cal.index(ef))
        elif cap_s is not None and es is not None:
            vals.append(cal.index(cap_s) - cal.index(es))
    if not vals:
        return act.get("total_float_days") or 0
    return min(vals)


# ------------------------------------------------------------- longest path
def _longest(doc, by, rels):
    """Longest path: start at activities that finish on the project early
    finish and walk driving predecessors back to the start.

    Float is in each activity's own calendar, so the lowest float is not
    always the longest chain when calendars differ. The longest path does
    not depend on that.
    """
    dated = [a for a in by.values() if a.get("ef") and not _derived(a)]
    if not dated:
        return
    end = max(as_date(a["ef"]) for a in dated)
    doc["project"]["early_finish"] = end.isoformat()
    incoming = defaultdict(list)
    for r in rels:
        incoming[r["succ"]].append(r)
    seeds = [a["code"] for a in dated if as_date(a["ef"]) == end]
    seen = set()
    stack = list(seeds)
    while stack:
        code = stack.pop()
        if code in seen:
            continue
        seen.add(code)
        by[code]["longest_path"] = True
        if doc["options"].get("critical") == "longest" and \
                by[code].get("status") != COMPLETE:
            by[code]["critical"] = True
        for rel in incoming.get(code, ()):
            if rel.get("driving"):
                stack.append(rel["pred"])
    if doc["options"].get("critical") != "longest":
        # A longest-path activity with positive float (a calendar effect)
        # stays flagged on longest_path and is not forced critical.
        pass


def _float_paths(doc, by, rels):
    n = int(doc["options"].get("float_paths") or 0)
    if n <= 0:
        return
    use_tf = bool(doc["options"].get("float_paths_use_total_float"))
    remaining = {a["code"] for a in by.values()
                 if a.get("ef") and not _derived(a)}
    incoming = defaultdict(list)
    for r in rels:
        incoming[r["succ"]].append(r)
    for path_no in range(1, n + 1):
        if not remaining:
            break
        end = max(remaining, key=lambda c: as_date(by[c]["ef"]).toordinal())
        chain = []
        cur = end
        guard = set()
        while cur and cur not in guard:
            guard.add(cur)
            chain.append(cur)
            preds = [r for r in incoming.get(cur, ())
                     if r["pred"] in remaining and r["pred"] not in guard]
            if not preds:
                break
            if use_tf:
                cur = min(preds, key=lambda r: (
                    by[r["pred"]].get("total_float_days") or 0,
                    r["pred"]))["pred"]
            else:
                driving = [r for r in preds if r.get("driving")]
                cur = (driving or preds)[0]["pred"]
        chain.reverse()
        for i, code in enumerate(chain, 1):
            by[code]["float_path"] = path_no
            by[code]["float_path_order"] = i
            remaining.discard(code)


# ------------------------------------------------------------- derived types
def _derive(doc, by, rels, cals, log):
    incoming = defaultdict(list)
    outgoing = defaultdict(list)
    for r in rels:
        incoming[r["succ"]].append(r)
        outgoing[r["pred"]].append(r)
    for act in list(by.values()):
        if act.get("type") != "loe":
            continue
        _loe(doc, act, incoming[act["code"]], outgoing[act["code"]],
             by, cals, log)
    children = defaultdict(list)
    for act in by.values():
        if act.get("wbs") and act.get("type") != "wbs_summary" and act.get("es"):
            children[act["wbs"]].append(act)
    for act in by.values():
        if act.get("type") != "wbs_summary":
            continue
        kids = children.get(act.get("wbs")) or []
        kids = [k for k in kids if k is not act and k.get("es")]
        if not kids:
            continue
        cal = act["_cal"]
        es = min(as_date(k["es"]) for k in kids)
        ef = max(as_date(k["ef"]) for k in kids)
        es = calmod.snap_forward(cal, es)
        ef = calmod.snap_back(cal, ef) if cal.index(ef) >= cal.index(es) \
            else es
        act["es"], act["ef"] = es.isoformat(), ef.isoformat()
        act["ls"], act["lf"] = act["es"], act["ef"]
        span = max(0, cal.index(ef) - cal.index(es) + 1)
        act["dur_days"] = span
        act["orig_hours"] = span * cal.hours_per_day
        act["remain_hours"] = act["orig_hours"]
        act["total_float_days"] = min(k.get("total_float_days") or 0
                                      for k in kids)
        act["critical"] = False
        act["longest_path"] = False


def _loe(doc, act, preds, succs, by, cals, log):
    cal = act["_cal"]
    starts, finishes = [], []
    data = as_date(doc["project"].get("data_date"))
    for rel in preds:
        pred = by[rel["pred"]]
        if not pred.get("ef"):
            continue
        when = _rel_early(doc, rel, pred, act, cals, data)
        if when is not None:
            starts.append(when)
    for rel in succs:
        succ = by[rel["succ"]]
        if not succ.get("es"):
            continue
        # The level of effort ends the day before a finish-to-start
        # successor starts, or on a finish-to-finish successor's finish.
        if rel["type"] == "FF":
            finishes.append(as_date(succ["ef"]))
        else:
            finishes.append(as_date(succ["es"]) - DAY)
    if not starts:
        starts.append(calmod.snap_forward(
            cal, doc["project"].get("start")))
    es = calmod.snap_forward(cal, max(starts, key=lambda d: cal.index(
        calmod.snap_forward(cal, d))))
    if finishes:
        ef = min(finishes)
        ef = calmod.snap_back(cal, ef)
    else:
        ef = as_date(doc["project"].get("early_finish")) or es
        ef = calmod.snap_back(cal, ef)
    if cal.index(ef) < cal.index(es):
        log.append(f"{act.get('code')}: level of effort has no span "
                   "between its links.")
        ef = es
    span = max(0, cal.index(ef) - cal.index(es) + 1)
    act["es"], act["ef"] = es.isoformat(), ef.isoformat()
    act["ls"], act["lf"] = act["es"], act["ef"]
    act["dur_days"] = span if span else 0
    act["orig_hours"] = span * cal.hours_per_day
    act["remain_hours"] = act["orig_hours"]
    act["total_float_days"] = 0
    act["free_float_days"] = 0
    act["critical"] = False
    act["longest_path"] = False


def _alap(doc, by, cals):
    """As late as possible uses free float only, so successors stay put."""
    for act in by.values():
        if act.get("constraint") != ALAP and act.get("constraint2") != ALAP:
            continue
        if _derived(act) or act.get("status") == COMPLETE:
            continue
        ff = int(round(act.get("free_float_days") or 0))
        if ff <= 0:
            continue
        cal = cals.get(act.get("calendar")) or act.get("_cal")
        if cal is None:
            continue
        es = calmod.shift(cal, act["es"], ff)
        dur = _dur_days(act)
        ef = es if dur <= 0 else calmod.add_workdays(cal, es, dur)
        act["es"], act["ef"] = es.isoformat(), ef.isoformat()
        act["free_float_days"] = 0
        act["total_float_days"] = (act.get("total_float_days") or 0) - ff
        act["start_float_days"] = act["total_float_days"]


# ------------------------------------------------------------- words
def _explain(doc, by, rels):
    incoming = defaultdict(list)
    for r in rels:
        incoming[r["succ"]].append(r)
    for act in by.values():
        if not act.get("es"):
            continue
        pred = by.get(act.get("driving_pred") or "")
        succ = by.get(act.get("driving_succ") or "")
        rel = next((r for r in incoming[act["code"]]
                    if r["pred"] == act.get("driving_pred")), None)
        kind = act.get("duration_kind") or "estimated"
        days = act.get("dur_days") or 0
        if act.get("type") in (START_MS, FINISH_MS):
            how_long = "It is a milestone (no duration)."
        else:
            unit = "workday" if abs(days - 1) < 1e-6 else "workdays"
            how_long = (f"It is {days:.0f} {unit} on the "
                        f"{_cal_name(doc, act)} calendar, marked {kind}. "
                        f"{act.get('basis') or ''}".strip())
        if pred and rel:
            why_here = (f"It is here because {pred['name']} "
                        f"({rel['type']}) drives it.")
        elif not incoming[act["code"]]:
            why_here = "It has no predecessor; it starts at the project start."
        else:
            why_here = "Its start is set by the calendar and the data date."
        if act.get("longest_path"):
            drives = "It is on the longest path."
        elif succ:
            drives = f"It drives {succ['name']}."
        else:
            drives = "Nothing is scheduled after it."
        tf = act.get("total_float_days")
        ff = act.get("free_float_days")
        float_s = (f"Total float {tf:.0f} workdays, free float {ff:.0f}."
                   if tf is not None else "")
        if (tf or 0) < 0:
            float_s += " Negative float is a conflict with a constraint or the finish date."
        act["why"] = " ".join(p for p in (why_here, how_long, drives, float_s)
                              if p)


def _cal_name(doc, act):
    spec = (doc.get("calendars") or {}).get(act.get("calendar") or "") or {}
    return spec.get("name") or act.get("calendar") or "project"


def _statistics(doc, by, rels, log):
    acts = list(by.values())
    n = len(acts)
    ns = sum(1 for a in acts if a.get("status") == NOT_STARTED)
    ip = sum(1 for a in acts if a.get("status") == ACTIVE)
    dn = sum(1 for a in acts if a.get("status") == COMPLETE)
    crit = sum(1 for a in acts if a.get("critical"))
    neg = [a for a in acts if (a.get("total_float_days") or 0) < 0
           and not _derived(a)]
    doc["project"]["finish"] = doc["project"].get("early_finish") or ""
    if doc["project"].get("must_finish"):
        # The backward pass may have pulled late dates in; the early
        # finish is still when the work ends.
        pass
    lines = [
        f"Data date {doc['project'].get('data_date')}.",
        f"Out of sequence: {doc['options'].get('out_of_sequence')}.",
        f"Total float method: {doc['options'].get('total_float')}.",
        f"Lag calendar: {doc['options'].get('lag_calendar')}.",
        f"Critical definition: {doc['options'].get('critical')} "
        f"(threshold {doc['project'].get('critical_hours')} hours).",
        f"Activities {n}: not started {ns}, in progress {ip}, "
        f"completed {dn}. Relationships {len(rels)}.",
        f"Early finish {doc['project'].get('early_finish') or 'none'}. "
        f"Critical activities {crit}.",
    ]
    if neg:
        lines.append("Negative float: " + ", ".join(
            a.get("code") or "" for a in neg[:12]))
    doc["log"] = lines + list(log)


# ------------------------------------------------------------- baselines / EV
def take_baseline(doc, name="project"):
    """Copy today's early dates into a named snapshot and onto each
    activity. ``name`` of ``project`` is the one variances and the
    completeness ratio use. Primary, secondary and tertiary are the same
    kind of snapshot with a different pointer.
    """
    snap = {"name": name, "activities": {}}
    for a in doc.get("activities") or ():
        row = {"es": a.get("es") or "", "ef": a.get("ef") or "",
               "hours": a.get("orig_hours") or 0}
        snap["activities"][a["code"]] = row
        if name == "project":
            a["bl_start"], a["bl_finish"] = row["es"], row["ef"]
            a["bl_hours"] = row["hours"]
    doc.setdefault("baselines", []).append(snap)
    if name in ("project", "primary", "secondary", "tertiary"):
        doc["project"][name + "_baseline" if name != "project"
                       else "baseline"] = name
        if name == "project":
            doc["project"]["baseline"] = name
    return snap


def variance_days(doc, act, which="finish"):
    """Baseline minus current, in the activity calendar's workdays.

    Positive means the current date is earlier than the baseline.
    """
    key = "bl_start" if which == "start" else "bl_finish"
    cur_key = "es" if which == "start" else "ef"
    b, c = as_date(act.get(key)), as_date(act.get(cur_key))
    if not b or not c:
        return None
    cals = calmod.build_all(doc)
    cal = cals.get(act.get("calendar") or "5day") or next(iter(cals.values()))
    return cal.index(b) - cal.index(c)


def earned_value(doc):
    """Project earned value from budget cost, percent complete and the
    project baseline. Technique is activity percent (duration percent when
    that is what the activity uses). Performance factor defaults to 1.

    BCWS spreads the baseline budget uniformly from baseline start to
    baseline finish and sums the share that falls on or before the data
    date. BCWP is budget times percent complete. ETC is the budget still
    unearned, times the performance factor.
    """
    data = as_date(doc["project"].get("data_date"))
    pf = float(doc["project"].get("performance_factor") or 1)
    bac = bcws = bcwp = acwp = 0.0
    cals = calmod.build_all(doc)
    for a in doc.get("activities") or ():
        if a.get("type") in DERIVED:
            continue
        cost = float(a.get("budget_cost") or 0)
        bac += cost
        acwp += float(a.get("actual_cost") or 0)
        pct = min(100.0, max(0.0, float(a.get("percent") or 0)))
        if a.get("status") == COMPLETE:
            pct = 100.0
        bcwp += cost * pct / 100.0
        b0, b1 = as_date(a.get("bl_start")), as_date(a.get("bl_finish"))
        if cost and b0 and b1 and data:
            cal = cals.get(a.get("calendar") or "5day")
            span = max(1, cal.index(b1) - cal.index(b0) + 1)
            done = cal.index(data) - cal.index(b0) + 1
            share = min(1.0, max(0.0, done / span))
            bcws += cost * share
    sv = bcwp - bcws
    cv = bcwp - acwp
    spi = (bcwp / bcws) if bcws else None
    cpi = (bcwp / acwp) if acwp else None
    etc = (bac - bcwp) * pf
    eac = acwp + etc
    out = {"bac": bac, "bcws": bcws, "bcwp": bcwp, "acwp": acwp,
           "sv": sv, "cv": cv, "spi": spi, "cpi": cpi, "etc": etc,
           "eac": eac, "performance_factor": pf}
    doc["earned_value"] = out
    return out


def level_resources(doc, max_units=None):
    """Serial leveling. An activity may slide within its free float when
    a role would otherwise exceed ``max_units`` people on one workday.
    Early dates before leveling are kept on ``unleveled_es``. Off unless
    ``options.level`` is set; ``engine`` calls it only then.

    This is a single-project, one-pass level. It does not level across
    projects or reshape resource curves.
    """
    max_units = float(max_units if max_units is not None else
                      doc["project"].get("level_max") or 1)
    cals = calmod.build_all(doc)
    tasks = [a for a in doc.get("activities") or ()
             if a.get("type") not in DERIVED and a.get("es")
             and a.get("status") != COMPLETE and (a.get("roles"))]
    rank = {"top": 0, "high": 1, "normal": 2, "low": 3, "lowest": 4}
    tasks.sort(key=lambda a: (
        rank.get(a.get("priority") or "normal", 2),
        a.get("total_float_days") or 0,
        a.get("es") or "",
        a.get("code") or ""))
    # role -> date -> headcount
    load = defaultdict(lambda: defaultdict(float))

    def paint(act, sign=1):
        cal = cals.get(act.get("calendar") or "5day")
        es, ef = as_date(act["es"]), as_date(act["ef"])
        if not es or not ef:
            return
        d = es
        people = sum(float(x.get("units") or 1) for x in
                     (act.get("role_units") or []) ) or len(act.get("roles") or ())
        # one headcount per named role when units were not given
        people = people or 1.0
        guard = 0
        while d <= ef and guard < 800:
            guard += 1
            if cal.is_work(d):
                for role in act.get("roles") or ("crew",):
                    load[role][d.isoformat()] += sign * (
                        people / max(1, len(act.get("roles") or ())))
            d += DAY

    for a in tasks:
        a["unleveled_es"] = a.get("es")
        a["unleveled_ef"] = a.get("ef")
        cal = cals.get(a.get("calendar") or "5day")
        ff = int(round(a.get("free_float_days") or 0))
        for _ in range(max(0, ff) + 1):
            paint(a, 1)
            over = False
            es, ef = as_date(a["es"]), as_date(a["ef"])
            d = es
            while d <= ef:
                if cal.is_work(d):
                    for role in a.get("roles") or ():
                        if load[role][d.isoformat()] > max_units + 1e-6:
                            over = True
                d += DAY
            if not over:
                break
            paint(a, -1)
            a["es"] = calmod.shift(cal, a["es"], 1).isoformat()
            dur = _dur_days(a)
            a["ef"] = (a["es"] if dur <= 0 else
                       calmod.add_workdays(cal, a["es"], dur).isoformat())
            ff -= 1
            if ff < 0:
                paint(a, 1)
                break
    doc["project"]["leveled"] = True
    return doc
