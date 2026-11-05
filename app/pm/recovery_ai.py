"""AI helper for the recovery schedule (Oct 21).

A small agent loop around the local model (Ollama - the schedule never
leaves the computer):

  1. brief(): the job's standing - target, forecast, workdays behind, the
     cause - the critical activities still to do (and the near-critical
     ones, float <= 5) with their links, the steps already in the plan,
     and the limits the person typed ("no second crew on footings").
  2. The model answers in JSON: steps, each {activity (number),
     technique crash | fast_track | resequence, new_duration, predecessor,
     overlap, how, why, risk}.
  3. check(): every step is checked against the schedule - the activity
     exists, isn't finished and isn't a milestone (nor is the
     predecessor), a crash is at least 1 day and cuts no more than half,
     a predecessor really is one, an overlap is at most half the
     predecessor, one step per link and one crash per activity - and the
     rejected ones say why. A resequence (dropping a logic link) is only
     proposed as "needs PM OK" (unticked) unless the contractor's limits
     allow resequencing.
  4. The accepted steps are added to a copy of the plan and the schedule
     is recomputed (recovery.evaluate). Still late, and rounds left: the
     result and the rejections go back to the model for another try.

Nothing here changes the schedule or the saved plan: help() returns
proposals; the person ticks the ones to add.
"""
import json
import re

from . import recovery, schedule

ROUNDS = 3
MAX_CUT = 0.5                         # a crash cuts at most half
NEAR = 5                              # near-critical: float <= 5 workdays

SYSTEM = """You are a construction scheduler helping a general contractor \
build a RECOVERY SCHEDULE for a job that is behind. Use only these \
techniques on the activities listed:
- crash: shorten an activity (more workers, a second crew, longer shifts, \
more equipment). Give new_duration in workdays.
- fast_track: overlap an activity with one of its predecessors (start it \
before the predecessor finishes). Give predecessor (activity number) and \
overlap (workdays).
- resequence: remove the wait on one predecessor so the work runs at the \
same time. Give predecessor.
Only critical or near-critical activities shorten the job. Respect every \
limit the contractor gives. Be realistic: say how (crew, shifts, \
equipment) and the risk (cost, quality, safety, trade stacking). Prefer \
the fewest, cheapest steps that meet the target.
Answer with JSON only: {"steps": [{"activity": "A0012", "technique": \
"crash", "new_duration": 8, "predecessor": "", "overlap": 0, "how": "...", \
"why": "...", "risk": "..."}], "summary": "one or two sentences"}"""


def _no(a):
    return str(a.get("_no") or "")


def brief(store, plan, limits="", feedback=""):
    """The prompt: standing, critical work, the plan so far, limits."""
    ev = recovery.evaluate(store, plan)
    acts = recovery.changed_acts(store, plan)
    by = {a["_id"]: a for a in acts}
    # float toward the target milestone (work that doesn't lead to it
    # can't win time back, however long it is)
    fl = recovery.driving(ev["cpm"])
    rows = [r for r in ev["cpm"]["rows"] if not r.get("summary") and
            r.get("status") != "Complete" and not r.get("actual_finish")
            and r["_id"] in fl and fl[r["_id"]] <= NEAR]
    rows.sort(key=lambda r: r["es"])
    lines = []
    for r in rows[:60]:
        a = by.get(r["_id"]) or {}
        f = fl[r["_id"]]
        preds = ", ".join(f"{_no(by[pid])} {typ}"
                          + (f"{lag:+g}" if lag else "")
                          for _i, pid, _n, typ, lag in
                          recovery.preds_of(acts, a) if pid in by)
        lines.append(
            f"{_no(a)} | {a.get('name', '')} | {int(r.get('dur') or 0)} "
            f"workdays | {r['es']:%b %d}-{r['ef']:%b %d} | "
            f"{'CRITICAL' if f <= 0 else f'float {f}'}"
            f" | {recovery_name(a.get('responsible'))} | after: "
            f"{preds or '-'} | {int(float(a.get('percent') or 0))}% done")
    have = [f"- {recovery.TECHNIQUES.get(s.get('technique'))} "
            f"{_no(by.get(s.get('id'), {}))}: "
            f"{recovery.describe(store, s)}"
            for s in plan.get("steps") or []]
    cause = recovery.CAUSE_LABEL.get(plan.get("cause"), "not given")
    parts = [
        SYSTEM, "",
        f"Project: {store.name}",
        f"Target completion: {ev['target']}",
        f"Forecast completion: {ev['forecast']}",
        f"Behind: {ev['behind']} workdays" if ev["behind"] is not None
        else "Behind: unknown (no target date)",
        f"Cause of the delay: {cause}. {plan.get('cause_note') or ''}",
        "",
        "Activities still to do (number | name | duration | dates | "
        "critical/float | responsible | predecessors | % done):",
        *lines, "",
        "Steps already in the plan:", *(have or ["- none"]), "",
        f"Contractor's limits: {limits.strip() or 'none given'}"]
    if feedback:
        parts += ["", "Result of your last answer:", feedback]
    return "\n".join(parts)


def recovery_name(v):
    from .lookahead import _name
    return _name(v) or "-"


def parse(text):
    """The model's JSON (allowing a fenced block or text around it)."""
    t = str(text or "").strip()
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        raise ValueError("The AI didn't answer with a plan.")
    data = json.loads(m.group(0))
    steps = data.get("steps") if isinstance(data, dict) else None
    if not isinstance(steps, list):
        raise ValueError("The AI's answer had no steps.")
    return steps, str(data.get("summary") or "")


_NEG = re.compile(r"\b(no|not|never|don'?t|do not|without|avoid|can'?t|"
                  r"cannot|won'?t|isn'?t|aren'?t)\b", re.I)
_RESEQ = re.compile(r"re-?\s?sequenc", re.I)


def resequence_allowed(limits):
    """True when the contractor's limits say resequencing is OK - a
    sentence that names resequencing without a "no / not / don't"."""
    for sent in re.split(r"[.;\n!?]+", str(limits or "")):
        if _RESEQ.search(sent) and not _NEG.search(sent):
            return True
    return False


def check(store, plan, raw_steps, limits="", others=()):
    """(steps the plan can take, [why each other one was rejected]).
    `others`: steps proposed earlier but not in the plan (they count
    toward "one step per link"). A resequence comes back with
    needs_ok=True unless `limits` allows resequencing."""
    acts = recovery.changed_acts(store, plan)
    find = schedule.resolver(acts)
    by = {a["_id"]: a for a in acts}
    reseq_ok = resequence_allowed(limits)
    ok, bad = [], []

    def taken():
        return list(plan.get("steps") or []) + list(others) + ok
    for s in raw_steps:
        if not isinstance(s, dict):
            continue
        ref = str(s.get("activity") or "").strip()
        rid = find(ref) if ref else None
        a = by.get(rid)
        tech = str(s.get("technique") or "").strip().lower().replace(
            "-", "_").replace(" ", "_")
        label = f"{ref or '?'} {tech or '?'}"
        if a is None:
            bad.append(f"{label}: no activity {ref!r}")
            continue
        if a.get("status") == "Complete" or a.get("actual_finish"):
            bad.append(f"{label}: already finished")
            continue
        n = int(schedule._num(a.get("duration")))
        if n < 1:
            bad.append(f"{label}: {a.get('name') or ref} is a milestone "
                       "(0 days) - it can't be crashed or overlapped")
            continue
        step = {"id": rid, "technique": tech, "how": str(s.get("how") or
                                                         "")[:200],
                "why": str(s.get("why") or "")[:300],
                "risk": str(s.get("risk") or "")[:200], "cost": 0,
                "agreed": False, "ai": True}
        if tech == "crash":
            if any(x.get("id") == rid and x.get("technique") == "crash"
                   for x in taken()):
                bad.append(f"{label}: already crashed in the plan - one "
                           "crash per activity")
                continue
            if n < 2:
                bad.append(f"{label}: only {n} workday - nothing to cut")
                continue
            new = int(round(schedule._num(s.get("new_duration"), -1)))
            if new < 1 or new >= n:
                bad.append(f"{label}: new duration {new} must be 1 to "
                           f"{n - 1} workdays")
                continue
            if new < n * (1 - MAX_CUT):
                bad.append(f"{label}: {n} -> {new} cuts more than half - "
                           "not realistic")
                continue
            step.update(was=n, duration=new)
        elif tech in ("fast_track", "resequence"):
            pref = str(s.get("predecessor") or "").strip()
            pid = find(pref) if pref else None
            links = {}
            for p in recovery.preds_of(acts, a):
                links.setdefault(p[1], p)
            if pid not in links:
                bad.append(f"{label}: {pref or '(none)'} is not one of its "
                           "predecessors")
                continue
            pdur = int(schedule._num(by[pid].get("duration")))
            if pdur < 1:
                bad.append(f"{label}: predecessor {pref} is a milestone "
                           "(0 days) - nothing to overlap or drop")
                continue
            if any(x.get("id") == rid and x.get("pred") == pid
                   for x in taken()):
                bad.append(f"{label}: there is already a step on the link "
                           f"to {pref} - one step per link")
                continue
            step["pred"] = pid
            if tech == "fast_track":
                if links[pid][3] != "FS":
                    bad.append(f"{label}: the link to {pref} is already "
                               f"{links[pid][3]}")
                    continue
                over = int(round(schedule._num(s.get("overlap"), 0)))
                most = pdur // 2
                if most < 1:
                    bad.append(f"{label}: {pref} is only {pdur} workday - "
                               "too short to overlap")
                    continue
                if over < 1 or over > most:
                    bad.append(f"{label}: overlap {over} must be 1 to "
                               f"{most} workdays (at most half of {pref}'s "
                               f"{pdur})")
                    continue
                step["overlap"] = over
            elif not reseq_ok:
                step["needs_ok"] = True
        else:
            bad.append(f"{label}: unknown technique")
            continue
        ok.append(step)
    return ok, bad


def run(store, plan, limits="", ask=None, rounds=ROUNDS, progress=None,
        cancel=None):
    """Run the loop. Returns {"steps": proposals (not in the plan),
    "summary", "rejected": [...], "result": evaluate() with them,
    "rounds": n, "log": [text], "error": the model's error or "",
    "failed_round": the round it failed in (0 = none)}. `ask(prompt) ->
    text` defaults to the local model in JSON mode. A model error stops
    the loop but keeps what earlier rounds proposed. Resequence steps
    that need the PM's OK are proposed (needs_ok) but not counted in the
    result. `cancel()` -> True stops before the next round."""
    if ask is None:
        from ..ai import review
        ask = lambda p: review._ollama(p, json_mode=True)    # noqa: E731
    trial = dict(plan, steps=list(plan.get("steps") or []))
    proposals, held, rejected, log, summary = [], [], [], [], ""
    feedback, error, failed = "", "", 0
    n = 0
    for n in range(1, rounds + 1):
        if cancel is not None and cancel():
            log.append(f"AI stopped at round {n}: cancelled")
            n -= 1
            break
        if progress:
            progress(f"AI round {n} of {rounds}…")
        prompt = brief(store, trial, limits, feedback)
        try:
            raw = ask(prompt)
        except Exception as e:                     # noqa: BLE001
            # AIError (Ollama down, HTTP 500 ...) or anything else: keep
            # the steps from the rounds before
            error, failed = str(e) or e.__class__.__name__, n
            log.append(f"AI stopped at round {n}: {error}")
            break
        try:
            steps, summary = parse(raw)
        except (ValueError, json.JSONDecodeError) as e:
            log.append(f"Round {n}: {e}")
            feedback = f"Your answer could not be read ({e}). Answer with " \
                "the JSON only."
            continue
        good, bad = check(store, trial, steps, limits, others=held)
        rejected += bad
        need = [x for x in good if x.get("needs_ok")]
        good = [x for x in good if not x.get("needs_ok")]
        held += need
        trial["steps"] = trial["steps"] + good
        proposals += good + need
        ev = recovery.evaluate(store, trial)
        held_txt = (f", {len(need)} resequence step(s) need the PM's OK"
                    if need else "")
        log.append(f"Round {n}: {len(good)} step(s) kept{held_txt}, "
                   f"{len(bad)} rejected; still {ev['behind']} workday(s) "
                   "late" if ev["behind"] and ev["behind"] > 0 else
                   f"Round {n}: {len(good)} step(s) kept{held_txt}, "
                   f"{len(bad)} rejected; meets the target")
        if ev["behind"] is None or ev["behind"] <= 0:
            break
        feedback = (f"With your steps the job is still {ev['behind']} "
                    f"workday(s) late (forecast {ev['forecast']}). "
                    + ("Rejected: " + "; ".join(bad) + ". " if bad else "")
                    + ("Resequencing is not allowed without the PM's OK, "
                       "so those steps don't count. " if need else "")
                    + "Propose MORE steps (not ones already in the plan).")
    result = recovery.evaluate(store, trial)
    return {"steps": proposals, "summary": summary, "rejected": rejected,
            "result": result, "rounds": n, "log": log, "error": error,
            "failed_round": failed}
