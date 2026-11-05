"""Schedule quality check: the DCMA 14-Point Assessment.

When a schedule is used to support (or defend) a delay or insurance claim,
the reviewer's first question is whether the schedule itself can be
trusted. The common yardstick is the DCMA 14-Point Assessment; check()
runs it on the live schedule (schedule.compute at the data date) and
says, point by point, what passed, what failed and which activities are
the problem.

  1  Logic              incomplete activities missing a predecessor or a
                        successor (the start / finish milestones may
                        have an open end), or with a dangling start
                        (only FF / SF predecessors) or finish (only
                        SS / SF successors)                      <= 5%
  2  Leads              negative lags                            = 0
  3  Lags               positive lags                            <= 5% of links
  4  Relationship types finish-to-start links                    >= 90%
  5  Hard constraints   activities with a hard date constraint   <= 5%
                        (must start / finish on, start / finish
                        no later than); "start / finish no
                        earlier than" are soft and listed as
                        "Soft: n" - they don't count
  6  High float         total float over 44 workdays             <= 5%
  7  Negative float     float against the target / contract date = 0
  8  High duration      over 44 workdays (not milestones)        <= 5%
  9  Invalid dates      unstarted work the logic puts before the
                        data date, actual dates after it         = 0
  10 Resources          not tracked here                         n/a
  11 Missed tasks       due by the baseline but finished late or
                        not at all                               <= 5%
  12 Critical path test a critical activity made 600 workdays
                        longer must push the finish 600 workdays
                        (the detail names where the driving path
                        breaks when it doesn't)                  pass
  13 CPLI               (critical path length + float to target) /
                        critical path length                     >= 0.95
  14 BEI                completed / baseline due by data date    >= 0.95

Summary rows are left out everywhere; milestones are left out of the
duration checks. Counts are of incomplete activities (and the links into
them) unless the point says otherwise.
"""
import copy
import datetime as _dt

from . import schedule

LIMIT = 44            # workdays: "high" float / duration
CP_ADD = 600          # workdays added in the critical path test
CAP = 50              # offenders listed per point

POINTS = [
    ("logic", "Logic"), ("leads", "Leads"), ("lags", "Lags"),
    ("rel_types", "Relationship Types"), ("constraints", "Hard Constraints"),
    ("high_float", "High Float"), ("neg_float", "Negative Float"),
    ("high_duration", "High Duration"), ("invalid_dates", "Invalid Dates"),
    ("resources", "Resources"), ("missed", "Missed Tasks"),
    ("cp_test", "Critical Path Test"), ("cpli", "CPLI"), ("bei", "BEI"),
]
NAMES = dict(POINTS)

WHY = {
    "logic": "Without a predecessor and a successor an activity can't "
             "push or be pushed, so the schedule can't show how a delay "
             "flowed to the finish.",
    "leads": "A negative lag lets work start before the work it depends "
             "on is done - reviewers treat it as hiding a compressed "
             "or impossible sequence.",
    "lags": "Lags are unexplained waiting time; too many of them let "
            "dates be tuned by hand instead of by the work.",
    "rel_types": "Finish-to-start logic is the easiest to verify; heavy "
                 "use of other link types makes the critical path hard "
                 "to defend.",
    "constraints": "Date constraints override the logic, so delay "
                   "analysis can't show cause and effect through them.",
    "high_float": "Large float usually means missing successors - the "
                  "activity could slip months without the schedule "
                  "showing any impact.",
    "neg_float": "Negative float means the current plan finishes after "
                 "the contract date; a reviewer will ask what recovery "
                 "or time extension accounts for it.",
    "high_duration": "Long activities hide the work inside them; a delay "
                     "can't be pinned to a specific scope or period.",
    "invalid_dates": "Unrecorded progress in the past or actual dates in "
                     "the future mean the update wasn't statused "
                     "properly, which undermines every date in it.",
    "resources": "Resource loading supports claims about crew size and "
                 "productivity; without it those arguments need other "
                 "records.",
    "missed": "Work that missed its baseline finish is the first thing "
              "a claim reviewer compares against the delay narrative.",
    "cp_test": "If lengthening a critical activity doesn't move the "
               "finish, the critical path is broken and the delay "
               "analysis built on it won't hold.",
    "cpli": "CPLI shows whether the remaining critical path can still "
            "make the contract date; below 1.0 the job is behind.",
    "bei": "BEI shows whether work is being finished at the pace the "
           "baseline promised; a low BEI supports (or undercuts) a "
           "delay claim's timeline.",
}

THRESHOLD = {
    "logic": "<= 5%", "leads": "0", "lags": "<= 5% of links",
    "rel_types": ">= 90% FS", "constraints": "<= 5%",
    "high_float": "<= 5%", "neg_float": "0", "high_duration": "<= 5%",
    "invalid_dates": "0", "resources": "n/a", "missed": "<= 5% of due",
    "cp_test": "pass", "cpli": ">= 0.95", "bei": ">= 0.95",
}

_d = schedule._d
_num = schedule._num


# ------------------------------------------------------------- helpers
def _pct(n, total):
    return f"{n} of {total} ({100.0 * n / total:.1f}%)" if total else \
        f"{n} of 0"


def _done(r):
    return r.get("status") == "Complete" or bool(r.get("actual_finish")) \
        or _num(r.get("percent")) >= 100


def _started(r):
    return bool(r.get("actual_start")) or _num(r.get("percent")) > 0 or \
        r.get("status") in ("In Progress", "Complete")


def _off(r, detail):
    return {"no": str(r.get("_no") or ""), "name": str(r.get("name") or ""),
            "detail": detail}


def _item(key, metric, passed, offenders=(), note=""):
    offenders = list(offenders)
    return {"key": key, "name": NAMES[key], "metric": metric,
            "threshold": THRESHOLD[key], "passed": passed,
            "offenders": offenders[:CAP], "count": len(offenders),
            "why": WHY[key], "note": note}


def _ratio(key, offenders, total, limit_pct, note=""):
    """A "<= limit% of total" point; n/a when there's nothing to count."""
    n = len(offenders)
    if not total:
        return _item(key, "0 of 0", None, (), note or "Nothing to check.")
    return _item(key, _pct(n, total), 100.0 * n / total <= limit_pct + 1e-9,
                 offenders, note)


def _when(d):
    return f"{d:%b} {d.day}, {d.year}" if d else "-"


def target_date(store, cpm=None):
    """(target date, where it came from) for the float / CPLI points -
    recovery.completion_date(), the same date the Claim Package and
    recovery.standing() use: the contract completion date when set
    ("contract completion date"), else the finish milestone's baseline
    finish ("baseline finish ..."), else a recovery plan's target."""
    from . import recovery
    t, src = recovery.completion_date(store, cpm)
    return (t, recovery.SOURCE_LABEL.get(src, src)) if t else (None, "")


HARD = {"MSO": "Must start on", "MFO": "Must finish on",
        "SNLT": "Start no later than", "FNLT": "Finish no later than"}
SOFT = {"SNET": "Start no earlier than", "FNET": "Finish no earlier than"}
# typed names, P6 cstr_type codes and Microsoft Project ConstraintType
# numbers -> the four-letter code
_ALIAS = {"MUST START ON": "MSO", "MUST FINISH ON": "MFO",
          "MANDATORY START": "MSO", "MANDATORY FINISH": "MFO",
          "START ON": "MSO", "FINISH ON": "MFO",
          "START NO LATER THAN": "SNLT", "FINISH NO LATER THAN": "FNLT",
          "START NO EARLIER THAN": "SNET", "FINISH NO EARLIER THAN": "FNET",
          "START ON OR AFTER": "SNET", "FINISH ON OR AFTER": "FNET",
          "START ON OR BEFORE": "SNLT", "FINISH ON OR BEFORE": "FNLT",
          "CS MSO": "MSO", "CS MEO": "MFO", "CS MANDSTART": "MSO",
          "CS MANDFIN": "MFO", "CS MSOA": "SNET", "CS MEOA": "FNET",
          "CS MSOB": "SNLT", "CS MEOB": "FNLT",
          "2": "MSO", "3": "MFO", "4": "SNET", "5": "SNLT", "6": "FNET",
          "7": "FNLT"}


def constraint_code(text):
    """'MSO', 'SNET' ... for a constraint type as typed or imported
    ("Must Start On", "snlt", "CS_MSO", 2 ...), or "" when it isn't a
    date constraint (ASAP / ALAP / blank)."""
    t = " ".join(str(text if text is not None else "").upper()
                 .replace("_", " ").replace("-", " ").split())
    if t in HARD or t in SOFT:
        return t
    return _ALIAS.get(t, "")


def constraints_of(r):
    """[(kind "hard" / "soft", label, date)] on an activity: the
    "Start no earlier than" date (field "start" - soft) and a typed or
    imported constraint ("constraint" + "constraint_date")."""
    out = []
    if _d(r.get("start")):
        out.append(("soft", SOFT["SNET"], str(r.get("start"))[:10]))
    code = constraint_code(r.get("constraint"))
    if code:
        when = str(r.get("constraint_date") or "")[:10]
        if code == "SNET" and out and when in ("", out[0][2]):
            return out                       # the same SNET, once
        out.append(("hard" if code in HARD else "soft",
                    HARD.get(code) or SOFT[code], when))
    return out


def _link_name(by, pid):
    p = by.get(pid) or {}
    return str(p.get("_no") or p.get("name") or pid)


# ------------------------------------------------------------- the CP test
def cp_test(store, cpm=None, dd=None, act_id=None):
    """Add CP_ADD workdays to one critical activity (act_id, else the
    first unstarted critical one) in a what-if copy. {"passed",
    "activity" (row), "act_shift", "finish_shift", "detail"}; passed is
    None when there is no critical activity to test."""
    from . import recovery
    dd = dd or schedule.data_date(store)
    cpm = cpm or schedule.compute(store, dd)
    rows = [r for r in cpm["rows"] if not r.get("summary")]
    if act_id:
        cands = [r for r in rows if r["_id"] == act_id]
    else:
        cands = [r for r in rows if r["critical"] and not _done(r)]
        cands.sort(key=lambda r: (bool(r.get("milestone")), _started(r),
                                  r["es_i"], r.get("_n") or 0))
    if not cands:
        return {"passed": None, "activity": None, "act_shift": 0,
                "finish_shift": 0,
                "detail": "No unfinished critical activity to test."}
    row = cands[0]
    acts = copy.deepcopy(store.list("activity"))
    for a in acts:
        if a["_id"] == row["_id"]:
            a["duration"] = _num(a.get("duration")) + CP_ADD
    new = schedule.compute(recovery.WhatIf(store, acts), dd)
    nrow = next(r for r in new["rows"] if r["_id"] == row["_id"])
    old_f = max(r["ef_i"] for r in rows)
    new_f = max(r["ef_i"] for r in new["rows"] if not r.get("summary"))
    act_shift = nrow["ef_i"] - row["ef_i"]
    fin_shift = new_f - old_f
    # the whole driving path from the delayed activity to the finish has
    # to move by the delay, not just the activity itself
    path, breaks = _driving_path(rows, new["rows"], row["_id"]), []
    for r, shift in path:
        if shift < act_shift:
            breaks.append(f"{r.get('_no')} {r.get('name')} moves {shift}")
    passed = act_shift > 0 and fin_shift == act_shift
    detail = (f"{row.get('_no')} {row.get('name')} made {CP_ADD} workdays "
              f"longer: it finishes {act_shift} workdays later, the "
              f"project finish moves {fin_shift} workdays")
    if path:
        detail += (f"; {len(path)} activit"
                   f"{'y' if len(path) == 1 else 'ies'} on its driving path")
    if not passed and breaks:
        detail += " - the path breaks at " + ", ".join(breaks[:3])
    return {"passed": passed, "activity": row, "act_shift": act_shift,
            "finish_shift": fin_shift, "detail": detail + ".",
            "path": [{"no": str(r.get("_no") or ""), "name": r.get("name"),
                      "shift": sh} for r, sh in path]}


def _driving_path(rows, new_rows, start_id):
    """[(row, ef shift)] for the critical activities the start activity
    drives (link with no slack, followed on) in the original schedule,
    with how far each one's finish moved in the what-if."""
    by = {r["_id"]: r for r in rows}
    moved = {r["_id"]: r["ef_i"] for r in new_rows}
    succs = {}
    for r in rows:
        for p, t, lag in r.get("links") or ():
            succs.setdefault(p, []).append((r["_id"], t, lag))

    def drives(p, sx, t, lag):
        a, b = by[p], by[sx]
        need = {"FS": a["ef_i"] + lag, "SS": a["es_i"] + lag,
                "FF": a["ef_i"] + lag - b["dur"]}.get(
                    t, a["es_i"] + lag - b["dur"])
        return need == b["es_i"]
    out, seen, stack = [], {start_id}, [start_id]
    while stack:
        i = stack.pop(0)
        for sx, t, lag in succs.get(i, ()):
            if sx in seen or sx not in by or not by[sx]["critical"]:
                continue
            if not drives(i, sx, t, lag):
                continue
            seen.add(sx)
            stack.append(sx)
            out.append((by[sx], moved.get(sx, by[sx]["ef_i"]) -
                        by[sx]["ef_i"]))
    return out


# ------------------------------------------------------------- check
def check(store, today=None):
    """Run the 14 points. {"items": [14 dicts: key, name, metric,
    threshold, passed (True / False / None = n/a), offenders [{no, name,
    detail}] (first CAP), count, why, note], "score", "summary",
    "data_date", "target", "finish"}."""
    today = _d(today) or _dt.date.today()
    dd = _d(store.setting("data_date")) or today
    cpm = schedule.compute(store, dd)
    cal = cpm["cal"]
    rows = [r for r in cpm["rows"] if not r.get("summary")]
    by = {r["_id"]: r for r in rows}
    todo = [r for r in rows if not _done(r)]
    succs = {r["_id"]: [] for r in rows}
    for r in rows:
        for p, t, lag in r.get("links") or ():
            if p in succs:
                succs[p].append((r["_id"], t, lag))
    items = []

    # 1 logic -----------------------------------------------------------
    ms = [r for r in rows if r.get("milestone")]
    first_ms = min((r for r in ms if not r.get("links")),
                   key=lambda r: (r["es_i"], r.get("_n") or 0), default=None)
    last_ms = max((r for r in ms if not succs[r["_id"]]),
                  key=lambda r: (r["ef_i"], r.get("_n") or 0), default=None)
    off = []
    for r in todo:
        miss = []
        if not r.get("links") and r is not first_ms:
            miss.append("predecessor")
        if not succs[r["_id"]] and r is not last_ms:
            miss.append("successor")
        bits = ["No " + " or ".join(miss)] if miss else []
        # dangling ends: linked, but nothing ties the start (only FF / SF
        # predecessors) or the finish (only SS / SF successors)
        pt = {t for _p, t, _l in r.get("links") or ()}
        if pt and not pt & {"FS", "SS"}:
            bits.append("Dangling start (only finish-to-finish "
                        "predecessors - nothing drives the start)")
        st = {t for _s, t, _l in succs[r["_id"]]}
        if st and not st & {"FS", "FF"}:
            bits.append("Dangling finish (only start-to-start successors "
                        "- nothing follows the finish)")
        if bits:
            off.append(_off(r, "; ".join(bits)))
    items.append(_ratio("logic", off, len(todo), 5))

    # 2-4 links into unfinished activities -------------------------------
    links = [(r, p, t, lag) for r in todo for p, t, lag in r.get("links")
             or ()]
    nl = len(links)

    def ldesc(p, t, lag):
        return f"{t} {'+' if lag > 0 else ''}{lag}d from {_link_name(by, p)}"
    leads = [_off(r, "Lead: " + ldesc(p, t, lag))
             for r, p, t, lag in links if lag < 0]
    items.append(_item("leads", f"{len(leads)} of {nl} links", len(leads)
                       == 0 if nl else None, leads,
                       "" if nl else "No links to check."))
    lags = [_off(r, "Lag: " + ldesc(p, t, lag))
            for r, p, t, lag in links if lag > 0]
    items.append(_ratio("lags", lags, nl, 5))
    nfs = [_off(r, ldesc(p, t, lag)) for r, p, t, lag in links if t != "FS"]
    if nl:
        fs = nl - len(nfs)
        items.append(_item("rel_types",
                           f"{fs} of {nl} FS ({100.0 * fs / nl:.1f}%)",
                           100.0 * fs / nl >= 90 - 1e-9, nfs))
    else:
        items.append(_item("rel_types", "0 of 0", None, (),
                           "No links to check."))

    # 5 constraints ------------------------------------------------------
    hard, soft = [], []
    for r in todo:
        for kind, label, when in constraints_of(r):
            (hard if kind == "hard" else soft).append(
                _off(r, f"{label} {when}".strip()))
    it5 = _ratio("constraints", hard, len(todo), 5,
                 "Only hard constraints count here (must start / finish "
                 "on, start / finish no later than). \"Start no earlier "
                 "than\" and \"finish no earlier than\" are soft - the "
                 "logic can still push the activity later - and are listed "
                 "separately; keep them to real-world dates (permits, "
                 "deliveries, owner access).")
    if todo:
        it5["metric"] += f"; Soft: {len(soft)}"
    it5["soft"] = soft[:CAP]
    it5["soft_count"] = len(soft)
    items.append(it5)

    # 6 high float -------------------------------------------------------
    hf = [_off(r, f"{r['float']} workdays of float")
          for r in todo if r["float"] > LIMIT]
    items.append(_ratio("high_float", hf, len(todo), 5))

    # 7 negative float against the target ---------------------------------
    from . import recovery
    target, kind = recovery.completion_date(store, cpm)
    src = recovery.SOURCE_LABEL.get(kind, kind) if target else ""
    finish = cpm["finish"]
    if target and finish and todo:
        shift = cal.index(target) - cal.index(finish)
        nf = [_off(r, f"{r['float'] + shift} workdays of float to "
                      f"{target.isoformat()}")
              for r in todo if r["float"] + shift < 0]
        items.append(_item("neg_float", f"{len(nf)} of {len(todo)}",
                           not nf, nf, f"Against the {src} "
                           f"({_when(target)})."))
    else:
        items.append(_item("neg_float", "n/a", None, (),
                           "No target date: set the contract completion "
                           "date (or a baseline on the finish milestone) "
                           "to measure float against it." if todo else
                           "No unfinished activities."))

    # 8 high duration ----------------------------------------------------
    work = [r for r in todo if not r.get("milestone")]
    hd = [_off(r, f"{r['dur']} workdays") for r in work if r["dur"] > LIMIT]
    items.append(_ratio("high_duration", hd, len(work), 5))

    # 9 invalid dates ----------------------------------------------------
    ddi = cal.index(dd)
    ps = _d(store.setting("project_start"))
    inv = []
    for r in rows:
        a_s, a_f = _d(r.get("actual_start")), _d(r.get("actual_finish"))
        if a_s and a_s > dd:
            inv.append(_off(r, f"Actual start {a_s} is after the data "
                               f"date {dd}"))
        if a_f and a_f > dd:
            inv.append(_off(r, f"Actual finish {a_f} is after the data "
                               f"date {dd}"))
        if a_s and a_f and a_f < a_s:
            inv.append(_off(r, f"Actual finish {a_f} is before the actual "
                               f"start {a_s}"))
        if _started(r):
            continue
        # where the logic alone puts this unstarted activity (compute
        # holds it at the data date, which hides the problem)
        cand = [0]
        if ps:
            cand.append(cal.index(ps))
        if _d(r.get("start")):
            cand.append(cal.index(_d(r["start"])))
        n = r["dur"]
        for p, t, lag in r.get("links") or ():
            pr = by.get(p)
            if not pr:
                continue
            cand.append({"FS": pr["ef_i"] + lag, "SS": pr["es_i"] + lag,
                         "FF": pr["ef_i"] + lag - n}.get(
                             t, pr["es_i"] + lag - n))
        if max(cand) < ddi:
            inv.append(_off(r, f"Not started, but the logic has it "
                               f"starting {cal.date(max(cand))} - before "
                               f"the data date {dd}"))
    items.append(_item("invalid_dates", f"{len(inv)} found", not inv
                       if rows else None, inv,
                       "Unstarted work is held at the data date when the "
                       "schedule is calculated, so this checks where the "
                       "logic would have put it."))

    # 10 resources -------------------------------------------------------
    items.append(_item("resources", "n/a", None, (),
                       "QuantiSheet schedules don't carry resource or cost "
                       "loading; use crew logs, daily reports and cost "
                       "records to support resource arguments."))

    # 11 missed tasks / 14 BEI ------------------------------------------
    due = [r for r in rows if _d(r.get("baseline_finish")) and
           _d(r["baseline_finish"]) <= dd]
    missed = []
    for r in due:
        bf = _d(r["baseline_finish"])
        fin = _d(r.get("actual_finish")) or (r["ef"] if _done(r) else None)
        if fin is None:
            missed.append(_off(r, f"Baseline finish {bf}, not finished"))
        elif fin > bf:
            missed.append(_off(r, f"Baseline finish {bf}, finished {fin}"))
    items.append(_ratio("missed", missed, len(due), 5,
                        "" if due else "Nothing was due by the data date "
                        "(set a baseline to measure this)."))

    # 12 critical path test ----------------------------------------------
    cp = cp_test(store, cpm, dd)
    cp_off = [_off(cp["activity"], cp["detail"])] if cp["passed"] is False \
        else []
    items.append(_item("cp_test", "Pass" if cp["passed"] else
                       ("Fail" if cp["passed"] is False else "n/a"),
                       cp["passed"], cp_off, cp["detail"]))

    # 13 CPLI ------------------------------------------------------------
    if target and finish and finish >= dd:
        cpl = cal.index(finish) - ddi + 1
        tf = cal.index(target) - cal.index(finish)
        cpli = (cpl + tf) / cpl if cpl > 0 else None
    else:
        cpli = None
    if cpli is None:
        items.append(_item("cpli", "n/a", None, (),
                           "Needs a target date and remaining work." if
                           target else "No target date: set the contract "
                           "completion date to measure CPLI."))
    else:
        items.append(_item("cpli", f"{cpli:.2f}", cpli >= 0.95 - 1e-9, (),
                           f"Critical path {cpl} workdays from the data "
                           f"date, {tf:+d} workdays of float to the {src} "
                           f"({_when(target)})."))

    # 14 BEI -------------------------------------------------------------
    completed = [r for r in rows if _done(r)]
    if due:
        bei = len(completed) / len(due)
        items.append(_item("bei", f"{bei:.2f} ({len(completed)} done / "
                           f"{len(due)} due)", bei >= 0.95 - 1e-9,
                           [o for o in missed if "not finished" in
                            o["detail"]]))
    else:
        bei = None
        items.append(_item("bei", "n/a", None, (),
                           "Nothing was due by the data date in the "
                           "baseline."))
    order = {k: i for i, (k, _n) in enumerate(POINTS)}
    items.sort(key=lambda it: order[it["key"]])

    ok = sum(1 for it in items if it["passed"] is True)
    bad = sum(1 for it in items if it["passed"] is False)
    na = sum(1 for it in items if it["passed"] is None)
    score = f"{ok} of {ok + bad}"
    summary = (f"{ok} of {ok + bad} applicable points pass"
               + (f" ({na} n/a)" if na else "")
               + (". Failed: " + ", ".join(it["name"] for it in items
                                           if it["passed"] is False)
                  if bad else "."))
    return {"items": items, "score": score, "summary": summary,
            "passed": ok, "failed": bad, "na": na, "data_date": dd,
            "target": target, "target_source": src,
            "target_kind": kind,
            "finish": finish,
            "cpli": cpli, "bei": bei, "problems": cpm["problems"]}


# ------------------------------------------------------------- output
def _result_word(p):
    return "PASS" if p is True else ("FAIL" if p is False else "n/a")


def text_summary(result):
    """The check as plain text (one line per point, then offenders of the
    failed points)."""
    out = ["Schedule Quality Check (DCMA 14-Point)",
           f"Data date {result.get('data_date')}: {result['summary']}"]
    for i, it in enumerate(result["items"], 1):
        out.append(f"{i:>2}. {it['name']:<20} {_result_word(it['passed']):<5}"
                   f" {it['metric']}  (threshold {it['threshold']})")
    for it in result["items"]:
        if it["passed"] is False and it["offenders"]:
            out.append("")
            out.append(f"{it['name']} - {it['count']} offender(s):")
            for o in it["offenders"]:
                out.append(f"  {o['no']} {o['name']}: {o['detail']}")
    return "\n".join(out)


def export_pdf(store, path, today=None):
    """The check as a Letter PDF: the pass / fail table, then each failed
    point with why it matters and its offenders."""
    from . import report
    today = _d(today) or _dt.date.today()
    res = check(store, today)
    d = report._Doc("Schedule Quality Check (DCMA 14-Point)",
                    getattr(store, "name", "") or "",
                    f"Data date {_when(res['data_date'])}  |  Prepared "
                    f"{_when(today)}  |  {res['score']} applicable points "
                    "pass")
    d.heading("Summary")
    d.grid([("Result", res["summary"]),
            ("Forecast finish", _when(res["finish"])),
            ("Target / contract completion",
             f"{_when(res['target'])} ({res['target_source']})"
             if res["target"] else "Not set"),
            ("Data date", _when(res["data_date"]))], cols=2)
    for p in res["problems"]:
        d.text(p, size=8.5, color=(0.75, 0.1, 0.1))
    d.heading("The 14 points")
    d.table(["#", "Point", "Metric", "Threshold", "Result"],
            [[str(i), it["name"], it["metric"], it["threshold"],
              _result_word(it["passed"])]
             for i, it in enumerate(res["items"], 1)],
            [0.4, 2.0, 2.6, 1.4, 0.8])
    for it in res["items"]:
        if it["passed"] is not None:
            continue
        d.text(f"{it['name']}: {it['note']}", size=8.5, color=report.MUTED)
    soft = next((it for it in res["items"] if it["key"] == "constraints"),
                {}).get("soft") or []
    if soft:
        d.text("Soft constraints (listed, not counted in point 5): " +
               "; ".join(f"{o['no']} {o['name']} ({o['detail']})"
                         for o in soft[:12]) +
               (" ..." if len(soft) > 12 else ""), size=8.5,
               color=report.MUTED)
    for i, it in enumerate(res["items"], 1):
        if it["passed"] is not False:
            continue
        d.heading(f"{i}. {it['name']} - failed ({it['metric']})")
        d.text(it["why"], size=9)
        if it["note"]:
            d.text(it["note"], size=8.5, color=report.MUTED)
        if it["offenders"]:
            d.table(["No.", "Activity", "Detail"],
                    [[o["no"], o["name"], o["detail"]]
                     for o in it["offenders"]], [0.8, 2.6, 3.8])
            if it["count"] > len(it["offenders"]):
                d.text(f"... and {it['count'] - len(it['offenders'])} "
                       "more.", size=8.5, color=report.MUTED)
    d.heading("About this check")
    d.text("The DCMA 14-Point Assessment is a common test of whether a "
           "schedule is built well enough to rely on for delay analysis. "
           "Thresholds are the standard ones; a failed point is a question "
           "a reviewer will ask, not proof the schedule is wrong.",
           size=8.5, color=report.MUTED)
    return d.finish(path)
