"""Recovery schedule (Oct 21): when a job is behind, a plan to win the
time back - kept apart from the live schedule until it's approved.

1. Where the job stands: the forecast finish (the Substantial Completion
   milestone, else the last activity) against the target (the date typed
   in the plan, else completion_date(): the contract completion date in
   Project settings, else the milestone's baseline finish), in workdays.
2. Why: the cause of the slip - the contractor's (labor, subs, material,
   equipment) or external (weather, design / RFIs, owner changes,
   permits, site conditions) - and a note.
3. The plan: steps on the activities still to do that drive the target
   milestone (zero float toward it - driving()) -
     crash        a shorter duration (more crew, longer shifts, more
                  equipment), with how and what it costs;
     fast-track   overlap the activity with a predecessor (that link
                  becomes start-to-start, plus finish-to-finish 0 so it
                  can't finish first; the overlap must be shorter than
                  the predecessor);
     resequence   drop a predecessor link so the work runs at the same
                  time.
   Each step records whether the sub has agreed.
4. evaluate(): the schedule recomputed with the plan (a what-if copy -
   the live schedule is untouched), the revised finish and the days won.
5. apply(): writes the plan into the schedule (durations and links; the
   baseline stays, so the recovery shows as variance), and keeps a record
   with every changed activity's old values; revert_last() puts them
   back.
6. export_pdf(): the recovery plan for the owner.

suggest() drafts steps: the longest critical activities are crashed by
about a fifth, then finish-to-start links between critical activities are
overlapped, until the target is met. Every suggestion is a starting point
to check with the subs.
"""
import copy
import datetime as _dt
import math

from . import schedule

CAUSES = [
    ("labor", "Labor / crew shortage", "contractor"),
    ("sub", "Subcontractor performance", "contractor"),
    ("materials", "Material delivery", "contractor"),
    ("equipment", "Equipment", "contractor"),
    ("weather", "Weather beyond normal", "external"),
    ("design", "Design, RFIs or submittal review", "external"),
    ("owner", "Owner change or decision", "external"),
    ("permit", "Permit or inspection", "external"),
    ("site", "Unforeseen site conditions", "external"),
    ("other", "Other", ""),
]
CAUSE_LABEL = {k: v for k, v, _s in CAUSES}
CAUSE_SIDE = {k: s for k, _v, s in CAUSES}
TECHNIQUES = {"crash": "Crash", "fast_track": "Fast-track",
              "resequence": "Resequence"}
SETTING = "recovery_plan"
HISTORY = "recovery_history"
MILESTONE = "SUBSTANTIAL COMPLETION"
# Project settings (Project Center > Project settings): the contract
# completion date (yyyy-mm-dd, blank = none) and the notice period in
# calendar days (blank = NOTICE_DEFAULT). The Claim Package, the DCMA
# check and standing() all measure against completion_date().
CONTRACT_SETTING = "contract_completion"
NOTICE_SETTING = "notice_days"
NOTICE_DEFAULT = 7
SOURCE_LABEL = {"contract": "contract completion date",
                "baseline": "baseline finish of the finish milestone",
                "recovery target": "recovery plan target",
                "given": "target date given"}


def _d(v):
    if isinstance(v, _dt.date):
        return v
    try:
        return _dt.date.fromisoformat(str(v or "")[:10])
    except ValueError:
        return None


def new_plan(target=None):
    return {"target": target.isoformat() if isinstance(target, _dt.date)
            else (target or ""), "cause": "", "cause_note": "", "steps": [],
            "created": _dt.date.today().isoformat(), "status": "Draft"}


def load(store):
    """The saved plan (a copy), or a new one."""
    p = store.setting(SETTING)
    return copy.deepcopy(p) if p else new_plan(default_target(store))


def save(store, plan):
    store.set_setting(SETTING, copy.deepcopy(plan))


# ------------------------------------------------------------- what-if
class WhatIf:
    """Looks like a ProjectStore to schedule.compute(): the store's
    activities with the plan's changes, everything else the store's own.
    Nothing is saved."""

    def __init__(self, store, acts):
        self._store, self._acts = store, acts
        self.name = getattr(store, "name", "")
        self.version = None

    def list(self, coll, deleted=False):
        if coll == "activity":
            return copy.deepcopy(self._acts)
        return self._store.list(coll, deleted)

    def setting(self, key, default=None):
        return self._store.setting(key, default)

    def get(self, coll, rid):
        if coll == "activity":
            return next((copy.deepcopy(a) for a in self._acts
                         if a["_id"] == rid), None)
        return self._store.get(coll, rid)


def _milestone(cpm):
    rows = [r for r in cpm["rows"] if not r.get("summary")]
    for r in rows:
        if str(r.get("name") or "").strip().upper() == MILESTONE:
            return r
    return max(rows, key=lambda r: r["ef"]) if rows else None


def driving(cpm, target=None):
    """{activity id: workdays of float toward the target milestone} for
    every activity that leads to it (target: a cpm row, default the
    Substantial Completion milestone or the latest finish). 0 = it drives
    the milestone; activities that don't lead to it aren't in the dict.
    The CPM "critical" flag is float to the project's last finish - an
    unlinked long activity is "critical" there without moving the
    milestone at all."""
    rows = {r["_id"]: r for r in cpm["rows"] if not r.get("summary")}
    m = target or _milestone(cpm)
    if not m or m["_id"] not in rows:
        return {}
    mid = m["_id"]
    reach, stack = {mid}, [mid]
    while stack:
        for p, _t, _l in rows[stack.pop()].get("links") or ():
            if p in rows and p not in reach:
                reach.add(p)
                stack.append(p)
    succs = {i: [] for i in reach}
    for i in reach:
        for p, t, lag in rows[i].get("links") or ():
            if p in reach:
                succs[p].append((i, t, lag))
    # backward pass toward the milestone, in reverse topological order
    left = {i: len(succs[i]) for i in reach}
    queue = [i for i in reach if not left[i]]
    lf = {}
    while queue:
        i = queue.pop()
        n = int(rows[i].get("dur") or 0)
        cand = []
        for sx, t, lag in succs[i]:
            ls_s = lf[sx] - int(rows[sx].get("dur") or 0)
            if t == "FS":
                cand.append(ls_s - lag)
            elif t == "SS":
                cand.append(ls_s - lag + n)
            elif t == "FF":
                cand.append(lf[sx] - lag)
            else:                                    # SF
                cand.append(lf[sx] - lag + n)
        lf[i] = min(cand) if cand else rows[i]["ef_i"]
        for p, _t, _l in rows[i].get("links") or ():
            if p in left:
                left[p] -= 1
                if not left[p]:
                    queue.append(p)
    return {i: lf[i] - rows[i]["ef_i"] for i in lf}


def _critical(cpm, target=None):
    """The rows still to do that drive the target milestone."""
    fl = driving(cpm, target)
    return [r for r in cpm["rows"] if r["_id"] in fl and fl[r["_id"]] <= 0
            and not r.get("summary") and r.get("status") != "Complete"
            and not r.get("actual_finish") and r.get("dur")]


def completion_date(store, cpm=None):
    """(date, source): the date the job is measured against - the
    contract completion date (setting CONTRACT_SETTING) when set
    (source "contract"), else the finish milestone's baseline finish
    ("baseline"), else a saved recovery plan's target ("recovery
    target"), else (None, "")."""
    cc = _d(store.setting(CONTRACT_SETTING))
    if cc:
        return cc, "contract"
    cpm = cpm or schedule.compute(store, schedule.data_date(store))
    m = _milestone(cpm)
    bf = _d(m.get("baseline_finish")) if m else None
    if bf:
        return bf, "baseline"
    t = _d((store.setting(SETTING) or {}).get("target"))
    if t:
        return t, "recovery target"
    return None, ""


def default_target(store, cpm=None):
    """The date to recover to: the plan's target typed earlier, else the
    contract completion date, else the finish milestone's baseline
    finish, else None."""
    t = _d((store.setting(SETTING) or {}).get("target"))
    if t:
        return t
    return completion_date(store, cpm)[0]


def _late(cal, forecast, target):
    """Workdays the forecast is past the target (negative = early)."""
    if not (forecast and target):
        return None
    return cal.index(forecast) - cal.index(target)


def standing(store, target=None, cpm=None):
    """{forecast, target, target_source ("given" when target is passed,
    else completion_date()'s "contract" / "baseline" / "recovery
    target"), behind (workdays), calendar_days, milestone (name),
    critical: [rows still to do that drive the milestone]}."""
    cpm = cpm or schedule.compute(store, schedule.data_date(store))
    if _d(target):
        target, source = _d(target), "given"
    else:
        target, source = completion_date(store, cpm)
    m = _milestone(cpm)
    forecast = m["ef"] if m else None
    crit = _critical(cpm, m)
    return {"forecast": forecast, "target": target,
            "target_source": source,
            "behind": _late(cpm["cal"], forecast, target),
            "calendar_days": (forecast - target).days
            if forecast and target else None,
            "milestone": m.get("name") if m else "", "critical": crit,
            "cpm": cpm}


def contract_terms(store):
    """{completion (date or None), notice_days (int)} as stored."""
    try:
        n = int(float(store.setting(NOTICE_SETTING)))
    except (TypeError, ValueError):
        n = NOTICE_DEFAULT
    return {"completion": _d(store.setting(CONTRACT_SETTING)),
            "notice_days": n}


def parse_terms(completion, notice):
    """Check what was typed in Project settings: (completion ISO date or
    "", notice days int) - raises ValueError with a message to show.
    Dates may be yyyy-mm-dd or m/d/yyyy; a blank notice period means
    NOTICE_DEFAULT."""
    c = str(completion or "").strip()
    if c:
        d = _d(c)
        if d is None:
            try:
                d = _dt.datetime.strptime(c, "%m/%d/%Y").date()
            except ValueError:
                raise ValueError(f"Contract completion date '{c}' isn't a "
                                 "date - use yyyy-mm-dd (or m/d/yyyy), or "
                                 "leave it blank.") from None
        c = d.isoformat()
    n = str(notice if notice is not None else "").strip()
    if not n:
        return c, NOTICE_DEFAULT
    try:
        days = float(n)
    except ValueError:
        days = -1
    if days < 0 or days != int(days):
        raise ValueError(f"Notice period '{n}' must be a whole number of "
                         "days (0 or more).")
    return c, int(days)


def set_terms(store, completion, notice):
    """Validate (parse_terms) and save the two settings."""
    c, n = parse_terms(completion, notice)
    store.set_setting(CONTRACT_SETTING, c)
    store.set_setting(NOTICE_SETTING, n)
    return c, n


# ------------------------------------------------------------- the plan
def preds_of(acts, act):
    """[(index in preds, predecessor id, its name, type, lag)]."""
    find = schedule.resolver(acts)
    by = {a["_id"]: a for a in acts}
    out = []
    for i, ln in enumerate(act.get("preds") or []):
        pid = find(str(ln.get("id") or ""))
        if pid and pid in by and pid != act["_id"]:
            out.append((i, pid, by[pid].get("name") or "",
                        str(ln.get("type") or "FS").upper()[:2] or "FS",
                        schedule._num(ln.get("lag"))))
    return out


def overlap_problem(pdur, overlap):
    """Why a fast-track overlap can't work, or "" if it can: the
    successor has to start after the predecessor does, so the overlap
    must be shorter than the predecessor."""
    if pdur < 1:
        return "the predecessor is a milestone (0 days) - nothing to overlap"
    if overlap >= pdur:
        return (f"an overlap of {overlap} day(s) is not shorter than the "
                f"predecessor's {pdur} day(s)")
    return ""


def changed_acts(store, plan, notes=None):
    """The activities with the plan's steps applied (copies): crashes
    first, then overlaps and dropped links. A fast-track turns the
    finish-to-start link into start-to-start (lag = predecessor duration
    + lag - overlap) plus finish-to-finish 0, so the successor still
    can't finish before its predecessor. A fast-track whose overlap is
    not shorter than the predecessor is left out (and explained in
    `notes`, a list, when given)."""
    acts = store.list("activity")
    by = {a["_id"]: a for a in acts}
    steps = [s for s in plan.get("steps") or () if s.get("id") in by]
    for s in steps:
        if s.get("technique") == "crash" and s.get("duration") is not None:
            by[s["id"]]["duration"] = max(0, int(s["duration"]))
    for s in steps:
        t = s.get("technique")
        if t not in ("fast_track", "resequence") or not s.get("pred"):
            continue
        a = by[s["id"]]
        for i, pid, _n, typ, lag in preds_of(acts, a):
            if pid != s["pred"]:
                continue
            if t == "resequence":
                a["preds"][i] = None          # every link to it goes
            elif typ == "FS":
                pdur = int(schedule._num(by[pid].get("duration")))
                over = max(0, int(s.get("overlap") or 0))
                why = overlap_problem(pdur, over)
                if why:
                    if notes is not None:
                        notes.append(f"{a.get('_no') or ''} "
                                     f"{a.get('name') or ''}: fast-track "
                                     f"ignored - {why}".strip())
                    break
                ref = a["preds"][i].get("id")
                a["preds"][i] = [
                    {"id": ref, "type": "SS",
                     "lag": max(0, pdur + int(lag) - over)},
                    {"id": ref, "type": "FF", "lag": 0}]
                break
        out = []
        for p in a.get("preds") or []:
            if isinstance(p, list):
                out += p
            elif p:
                out.append(p)
        if "preds" in a or out:
            a["preds"] = out
    return acts


def evaluate(store, plan):
    """The schedule with the plan: {forecast, target, behind (after),
    before (behind now), recovered (workdays), on_time, cost, not_agreed,
    cpm}."""
    now = standing(store, plan.get("target"))
    notes = []
    wi = WhatIf(store, changed_acts(store, plan, notes))
    cpm = schedule.compute(wi, schedule.data_date(store))
    m = _milestone(cpm)
    forecast = m["ef"] if m else None
    after = _late(cpm["cal"], forecast, now["target"])
    before = now["behind"]
    steps = plan.get("steps") or []
    cost = sum(schedule._num(s.get("cost")) for s in steps)
    return {"forecast": forecast, "target": now["target"],
            "before": before, "behind": after,
            "recovered": (before - after) if before is not None and
            after is not None else None,
            "on_time": after is not None and after <= 0,
            "cost": cost,
            "not_agreed": sum(1 for s in steps if not s.get("agreed")),
            "cpm": cpm, "store": wi, "was": now["forecast"],
            "notes": notes}


def suggest(store, target=None, crash_share=0.2, overlap_share=0.3,
            most=12):
    """Draft steps until the target is met (or nothing is left to try):
    crash the longest critical activities by about `crash_share`, then
    overlap finish-to-start links between critical activities by about
    `overlap_share` of the predecessor."""
    plan = new_plan(target or default_target(store))
    if not _d(plan["target"]):
        return plan
    tried = set()
    for _round in range(most):
        ev = evaluate(store, plan)
        if ev["behind"] is None or ev["behind"] <= 0:
            break
        # only work that drives the target milestone shortens the job
        crit = _critical(ev["cpm"])
        acts = changed_acts(store, plan)
        by = {a["_id"]: a for a in acts}
        made = False
        for r in sorted(crit, key=lambda r: -int(r.get("dur") or 0)):
            n = int(schedule._num(by[r["_id"]].get("duration")))
            if ("crash", r["_id"]) in tried or n < 4:
                continue
            tried.add(("crash", r["_id"]))
            cut = max(1, min(int(math.ceil(n * crash_share)),
                             ev["behind"]))
            plan["steps"].append({
                "id": r["_id"], "technique": "crash",
                "was": n, "duration": n - cut,
                "how": "Add a crew or extend shifts", "cost": 0,
                "agreed": False, "suggested": True})
            made = True
            break
        if not made:
            crit_ids = {r["_id"] for r in crit}
            for r in crit:
                a = by[r["_id"]]
                for _i, pid, pname, typ, _lag in preds_of(acts, a):
                    key = ("fast_track", r["_id"], pid)
                    pdur = int(schedule._num(by[pid].get("duration")))
                    if key in tried or typ != "FS" or \
                            pid not in crit_ids or pdur < 3:
                        continue
                    tried.add(key)
                    plan["steps"].append({
                        "id": r["_id"], "technique": "fast_track",
                        "pred": pid, "overlap": max(1, int(round(
                            pdur * overlap_share))),
                        "how": f"Start before {pname} is finished",
                        "cost": 0, "agreed": False, "suggested": True})
                    made = True
                    break
                if made:
                    break
        if not made:
            break
    return plan


def describe(store, step, acts=None):
    """'Crash 10 -> 8 days', 'Overlap 3 days with Framing', 'Start
    without waiting for Inspection'."""
    acts = acts or store.list("activity")
    by = {a["_id"]: a for a in acts}
    t = step.get("technique")
    if t == "crash":
        was = step.get("was")
        if was is None and step.get("id") in by:
            was = int(schedule._num(by[step["id"]].get("duration")))
        return f"{was} -> {step.get('duration')} days"
    pname = (by.get(step.get("pred")) or {}).get("name") or "?"
    if t == "fast_track":
        return f"Overlap {step.get('overlap')} day(s) with {pname}"
    if t == "resequence":
        return f"Start without waiting for {pname}"
    return ""


FIELDS = ("duration", "preds", "notes")      # what apply() may change


def _same_dur(a, b):
    return schedule._num(a, 0) == schedule._num(b, 0)


def _fields(rec):
    """{field: copy} of the fields apply() changes - a field the record
    doesn't have is left out, so revert can remove it again."""
    return {k: copy.deepcopy(rec[k]) for k in FIELDS if k in rec}


def apply(store, plan, today=None):
    """Write the plan into the live schedule. The baseline is kept (the
    recovery shows as variance). The history entry keeps every changed
    activity's fields as they were (duration, links with type and lag,
    notes) and as written, so revert_last() can put them back. Returns
    the number of activities changed."""
    today = _d(today) or _dt.date.today()
    acts = {a["_id"]: a for a in changed_acts(store, plan)}
    live = {a["_id"]: a for a in store.list("activity")}
    stepped = {s.get("id") for s in plan.get("steps") or ()}
    before, after = [], []
    n = 0
    for rid, a in acts.items():
        old = live.get(rid)
        if old is None or rid not in stepped:
            continue
        dur_changed = not _same_dur(old.get("duration"), a.get("duration"))
        preds_changed = (old.get("preds") or []) != (a.get("preds") or [])
        if not (dur_changed or preds_changed):
            continue
        steps = [s for s in plan.get("steps") or () if s.get("id") == rid]
        note = "; ".join(f"{TECHNIQUES.get(s.get('technique'), '')}: "
                         f"{describe(store, s, list(live.values()))}"
                         for s in steps)
        was = _fields(old)
        if dur_changed:
            old["duration"] = a.get("duration")
        if preds_changed:
            old["preds"] = a.get("preds")
        old["notes"] = ((old.get("notes") or "") + "\n" if old.get("notes")
                        else "") + f"Recovery plan {today:%b %d, %Y}: {note}"
        saved = store.save_record("activity", old)
        before.append(dict(was, _id=rid, _absent=[k for k in FIELDS
                                                  if k not in was]))
        after.append(dict(_fields(saved), _id=rid))
        n += 1
    done = copy.deepcopy(plan)
    done["status"] = "Applied"
    done["applied"] = today.isoformat()
    done.pop("reverted", None)
    hist = list(store.setting(HISTORY) or [])
    hist.append(dict(copy.deepcopy(done), before=before, after=after))
    store.set_setting(HISTORY, hist)
    save(store, done)
    return n


def last_applied(store):
    """The last history entry when it's an applied plan not yet
    reverted (with its before-values), else None."""
    hist = store.setting(HISTORY) or []
    h = hist[-1] if hist else None
    if h and h.get("status") == "Applied" and not h.get("reverted") and \
            "before" in h:
        return h
    return None


def edited_since(store):
    """Names of activities changed by hand since the last apply (a
    revert puts those fields back too)."""
    h = last_applied(store)
    out = []
    for aft in (h or {}).get("after") or ():
        rec = store.get("activity", aft["_id"])
        if rec is not None and _fields(rec) != \
                {k: v for k, v in aft.items() if k != "_id"}:
            out.append(rec.get("name") or rec.get("_no") or "")
    return out


def revert_last(store, today=None):
    """Undo the last applied plan: every activity it changed gets its
    duration, links and notes back exactly as they were; the history
    entry is marked reverted and the plan is a draft again. Returns the
    number of activities restored (None when there is nothing to revert).
    """
    h = last_applied(store)
    if h is None:
        return None
    today = _d(today) or _dt.date.today()
    n = 0
    for was in h.get("before") or ():
        rec = store.get("activity", was["_id"])
        if rec is None:                      # deleted since
            continue
        for k in FIELDS:
            if k in was:
                rec[k] = copy.deepcopy(was[k])
            else:
                rec.pop(k, None)
        store.save_record("activity", rec)
        gone = [k for k in was.get("_absent") or () if k in FIELDS]
        if gone:
            # save_record keeps a dropped field as None: take it out, so
            # the record is as it was before the plan
            with store.lock:
                live = store.coll("activity").get(was["_id"])
                for k in gone:
                    if live is not None and live.get(k) is None:
                        live.pop(k, None)
                store.save()
        n += 1
    hist = list(store.setting(HISTORY) or [])
    hist[-1] = dict(hist[-1], reverted=today.isoformat())
    store.set_setting(HISTORY, hist)
    plan = copy.deepcopy(store.setting(SETTING) or {})
    if plan:
        plan["status"] = "Draft"
        plan["reverted"] = today.isoformat()
        plan.pop("applied", None)
        save(store, plan)
    return n


# ------------------------------------------------------------- report
def _when(d):
    return f"{d:%b} {d.day}, {d.year}" if d else "-"


def export_pdf(store, path, plan, today=None):
    """The recovery plan for the owner: where the job stands, why, the
    steps, the result, and a Gantt chart of the revised schedule."""
    import os
    import tempfile

    import fitz

    from . import report
    today = _d(today) or _dt.date.today()
    ev = evaluate(store, plan)
    acts = store.list("activity")
    by = {a["_id"]: a for a in acts}
    d = report._Doc("Recovery Schedule", store.name,
                    f"Prepared {_when(today)}"
                    + ("  |  APPLIED " + _when(_d(plan.get("applied")))
                       if plan.get("status") == "Applied" else
                       "  |  DRAFT - not yet in the schedule"))
    d.heading("Where the job stands")
    behind = ev["before"]
    d.grid([("Contract / target completion", _when(ev["target"])),
            ("Forecast completion before recovery", _when(ev["was"])),
            ("Behind", f"{behind} workday(s)" if behind and behind > 0
             else ("On time" if behind is not None else "No target date")),
            ("Cause", CAUSE_LABEL.get(plan.get("cause"), "") or
             "Not given")], cols=2)
    if plan.get("cause_note"):
        d.text(plan["cause_note"])
    side = CAUSE_SIDE.get(plan.get("cause"))
    if side == "external":
        d.text("The cause is outside the contractor's control: check the "
               "contract's notice and time-extension requirements for "
               "this delay.", size=8.5, color=report.MUTED)
    d.heading("Recovery plan")
    rows = []
    for s in plan.get("steps") or []:
        a = by.get(s.get("id"))
        if not a:
            continue
        rows.append([a.get("_no") or "", a.get("name") or "",
                     TECHNIQUES.get(s.get("technique"), ""),
                     describe(store, s, acts), s.get("how") or "",
                     f"${schedule._num(s.get('cost')):,.0f}"
                     if schedule._num(s.get("cost")) else "",
                     "Yes" if s.get("agreed") else "No"])
    if rows:
        d.table(["No.", "Activity", "Technique", "Change", "How",
                 "Added cost", "Sub agreed"], rows,
                # wide enough for "Added cost" / "Sub agreed" in the
                # 7.5 pt bold header (~41 pt each), which clipped at 1.0/0.9
                [0.7, 2.5, 1.1, 2.2, 2.1, 1.1, 1.1])
    else:
        d.text("No steps yet.", color=report.MUTED)
    d.heading("Result")
    rec = ev["recovered"]
    res = [("Revised completion", _when(ev["forecast"])),
           ("Days recovered", f"{rec} workday(s)" if rec is not None
            else "-"),
           ("Against the target", "On time" if ev["on_time"] else
            (f"Still {ev['behind']} workday(s) late"
             if ev["behind"] is not None else "-")),
           ("Added cost of acceleration", f"${ev['cost']:,.0f}")]
    d.grid(res, cols=2)
    if ev["not_agreed"]:
        d.text(f"{ev['not_agreed']} step(s) not yet agreed with the "
               "subcontractor.", color=(0.75, 0.1, 0.1))
    for note in ev.get("notes") or ():
        d.text(note, size=8.5, color=report.MUTED)
    tmp = os.path.join(tempfile.mkdtemp(prefix="quantisheet-"), "g.pdf")
    rows_g = [r for r in ev["cpm"]["rows"]
              if r.get("status") != "Complete"]
    schedule.gantt_pdf(ev["store"], tmp, rows_g,
                       title="Revised schedule (recovery plan)",
                       cpm=ev["cpm"])
    # the Gantt pages (11x17) go in before the pages are numbered, so the
    # footer counts the whole document (report._Doc.finish numbers only
    # its own pages - "Page 1 of 1" on a 2-page PDF)
    out = d.doc
    g = fitz.open(tmp)
    out.insert_pdf(g)
    g.close()
    total = out.page_count
    printed = report.show_date(today.isoformat())
    for i, pg in enumerate(out):
        w, h = pg.rect.width, pg.rect.height
        pg.insert_text((report.M, h - 24), f"Printed {printed} from "
                       "QuantiSheet", fontsize=7.5, fontname="helv",
                       color=report.MUTED)
        pg.insert_text((w - report.M - 50, h - 24),
                       f"Page {i + 1} of {total}", fontsize=7.5,
                       fontname="helv", color=report.MUTED)
    out.save(path, garbage=3, deflate=True)
    out.close()
    return path
