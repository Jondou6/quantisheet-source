"""Claim-ready schedule records (AACE 29R-03 practice).

A delay claim or an insurer's review asks three things of a schedule:
what did it say at each update (and can that be trusted), what changed
between updates, and what did each delay event do to the finish.

1. snapshot(): an append-only log of schedule updates (setting
   "schedule_updates"). Each entry keeps the activities with their computed
   dates and is chained to the one before by a SHA-256 hash, so an edit to
   an old update shows in verify(). compare() lists what changed between
   two updates - finish, activities added or removed, durations, logic,
   critical path, and actual dates changed after the fact (a red flag in
   any forensic review).
2. tia(): a prospective time impact analysis of a "delay" record - the
   last update before the event, the event's fragnet tied in and the
   affected activities lengthened, recomputed on a what-if copy (nothing
   is saved). tia_all() runs every event. Impacts below 0 are refused
   (check_inputs): an event only adds time.
3. concurrency(): owner and contractor delays whose windows overlap.
   notice_late(): notice given later than the contract allows.
4. windows(): a windows analysis - per pair of consecutive updates, how
   far the finish moved and which delay events started in that window.
"""
import copy
import datetime as _dt
import hashlib
import json

from . import schedule
from .recovery import NOTICE_DEFAULT, NOTICE_SETTING, WhatIf

SETTING = "schedule_updates"
# kept outside the chain: {"count", "head", "at"} of the last update
# snapshot() wrote, so a rewrite of every entry (with fresh hashes) or a
# dropped last update shows in verify(). Printed in the Claim Package too
# - a copy held elsewhere is the real check.
ANCHOR = "schedule_updates_anchor"
KINDS = ("baseline", "update", "recovery", "claim")
SNAP_FIELDS = ("_id", "_no", "name", "duration", "preds", "start", "status",
               "percent", "actual_start", "actual_finish", "baseline_start",
               "baseline_finish", "responsible", "parent")
CONTRACTOR = "Contractor"
OWNER = "Owner"
NOTICE_DAYS = NOTICE_DEFAULT


def _d(v):
    if isinstance(v, _dt.datetime):
        return v.date()
    if isinstance(v, _dt.date):
        return v
    try:
        return _dt.date.fromisoformat(str(v or "")[:10])
    except ValueError:
        return None


def _iso(v):
    return v.isoformat() if isinstance(v, (_dt.date, _dt.datetime)) else v


def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _hash(entry):
    body = {k: v for k, v in entry.items() if k != "hash"}
    text = json.dumps(body, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _workdays(a, b, holidays=()):
    """Signed workdays from date a to date b (b later = positive)."""
    a, b = _d(a), _d(b)
    if not a or not b or a == b:
        return 0
    lo, hi = sorted((a, b))
    cal = schedule.Calendar(lo, holidays)
    n = cal.index(hi) - cal.index(lo)
    return n if b > a else -n


# ------------------------------------------------------------- the log
def updates(store):
    """The schedule updates, oldest first (copies)."""
    return copy.deepcopy(store.setting(SETTING) or [])


def snapshot(store, kind="update", note="", who=None, now=None):
    """Record the schedule as it stands: appended to "schedule_updates"
    and chained to the previous entry's hash. Returns the entry."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}")
    dd = schedule.data_date(store)
    cpm = schedule.compute(store, dd)
    rows = {r["_id"]: r for r in cpm["rows"]}
    acts = []
    for a in store.list("activity"):
        r = rows.get(a["_id"], {})
        e = {k: copy.deepcopy(a.get(k)) for k in SNAP_FIELDS}
        e.update(es=_iso(r.get("es")), ef=_iso(r.get("ef")),
                 float=r.get("float"), critical=bool(r.get("critical")))
        acts.append(e)
    acts.sort(key=lambda e: str(e.get("_no") or ""))
    log = store.setting(SETTING) or []
    prev = log[-1].get("hash", "") if log else ""
    if now is None:
        now = _dt.datetime.now().replace(microsecond=0)
    entry = {
        "n": len(log) + 1, "kind": kind, "anchored": True, "taken": _iso(now),
        "by": who if who is not None else store.me,
        "data_date": dd.isoformat(),
        "finish": _iso(cpm.get("finish")),
        "critical": sorted(str(rows[i].get("_no")) for i in cpm["critical"]
                           if i in rows),
        "holidays": [str(h) for h in store.setting("holidays") or ()],
        "activities": acts, "note": note or "", "prev_hash": prev}
    # what gets stored is JSON: hash exactly what will be read back
    entry = json.loads(json.dumps(entry, default=str))
    entry["hash"] = _hash(entry)
    store.set_setting(SETTING, copy.deepcopy(log) + [entry])
    store.set_setting(ANCHOR, {"count": entry["n"], "head": entry["hash"],
                               "at": entry["taken"]})
    return copy.deepcopy(entry)


def anchor(store):
    """The recorded head {count, head, at}, or None before the first
    update saved with anchoring (jobs from before 0.12.36)."""
    a = store.setting(ANCHOR)
    if isinstance(a, dict) and a.get("head"):
        return copy.deepcopy(a)
    return None


def verify_notes(store):
    """[info text] that isn't tampering - today: an update record from
    before anchoring ("not anchored yet"; the next saved update anchors
    it)."""
    log = store.setting(SETTING) or []
    if log and anchor(store) is None and \
            not any(e.get("anchored") for e in log):
        return ["Update record not anchored yet (saved before anchoring "
                "was added) - the next saved update anchors it."]
    return []


def verify(store):
    """[problem text] - empty when every update is intact and chained and
    the chain ends at the recorded head (ANCHOR). A record with no anchor
    yet isn't a problem (see verify_notes) unless one of its updates was
    saved with anchoring - then the anchor was removed."""
    log = store.setting(SETTING) or []
    out, prev = [], ""
    for i, e in enumerate(log):
        n = e.get("n")
        if n != i + 1:
            out.append(f"Update {n}: out of sequence (expected {i + 1}) - "
                       "an update was removed or reordered")
        if e.get("prev_hash", "") != prev:
            out.append(f"Update {n}: doesn't follow the update before it - "
                       "the chain is broken")
        if _hash(e) != e.get("hash"):
            out.append(f"Update {n}: its contents changed after it was "
                       "recorded")
        prev = e.get("hash", "")
    a = anchor(store)
    if a is None:
        if any(e.get("anchored") for e in log):
            out.append("The recorded head of the update chain is missing "
                       "- it was removed after updates were anchored")
        return out
    try:
        count = int(a.get("count"))
    except (TypeError, ValueError):
        count = None
    if count is not None and len(log) != count:
        out.append(f"Chain {'shorter' if len(log) < count else 'longer'} "
                   f"than recorded ({len(log)} vs {count}) - "
                   + ("an update was removed" if len(log) < count else
                      "an update was added outside Save Schedule Update"))
    if prev != a.get("head"):
        out.append("Head hash does not match the recorded head - the "
                   "update record was rewritten or cut short")
    return out


# ------------------------------------------------------------- compare
def _links(entry):
    """{activity id: sorted [(pred no., type, lag)]} with refs resolved."""
    acts = entry.get("activities") or []
    find = schedule.resolver(acts)
    no = {a["_id"]: a.get("_no") for a in acts}
    out = {}
    for a in acts:
        ls = []
        for ref, t, lag in schedule.parse_preds(a):
            p = find(ref)
            ls.append((str(no.get(p, ref)), t, int(round(lag))))
        out[a["_id"]] = sorted(ls)
    return out


def _fmt_links(ls):
    return ", ".join(f"{p} {t}" + (f"{lag:+d}" if lag else "")
                     for p, t, lag in ls) or "none"


def compare(a, b, holidays=None):
    """What changed from update a to update b (two snapshot entries)."""
    hol = b.get("holidays") if holidays is None else holidays
    fa, fb = _d(a.get("finish")), _d(b.get("finish"))
    A = {x["_id"]: x for x in a.get("activities") or []}
    B = {x["_id"]: x for x in b.get("activities") or []}
    lab = lambda x: {"_no": x.get("_no"), "name": x.get("name")}  # noqa
    out = {"from": a.get("n"), "to": b.get("n"),
           "finish_before": _iso(fa), "finish_after": _iso(fb),
           "finish_workdays": _workdays(fa, fb, hol) if fa and fb else None,
           "finish_calendar_days": (fb - fa).days if fa and fb else None,
           "added": [lab(B[i]) for i in B if i not in A],
           "removed": [lab(A[i]) for i in A if i not in B],
           "durations": [], "logic": [], "retroactive": [],
           "critical_entered": sorted(set(b.get("critical") or []) -
                                      set(a.get("critical") or [])),
           "critical_left": sorted(set(a.get("critical") or []) -
                                   set(b.get("critical") or [])),
           "red_flags": []}
    la, lb = _links(a), _links(b)
    a_dd = _d(a.get("data_date"))
    for i in A:
        if i not in B:
            continue
        x, y = A[i], B[i]
        if _num(x.get("duration")) != _num(y.get("duration")):
            out["durations"].append(dict(lab(y), before=x.get("duration"),
                                         after=y.get("duration")))
        if la[i] != lb[i]:
            out["logic"].append(dict(lab(y), before=_fmt_links(la[i]),
                                     after=_fmt_links(lb[i])))
        for f in ("actual_start", "actual_finish"):
            old, new = x.get(f) or "", y.get(f) or ""
            if old and new != old:
                why = "changed after it was reported"
            elif not old and new and a_dd and _d(new) and _d(new) < a_dd:
                why = (f"reported now, but dated before update "
                       f"{a.get('n')}'s data date ({a_dd.isoformat()}) "
                       "when the work showed as not "
                       + ("started" if f == "actual_start" else "finished"))
            else:
                continue
            out["retroactive"].append(dict(lab(y), field=f, before=old,
                                           after=new, why=why))
            out["red_flags"].append(
                f"{y.get('_no')} {y.get('name')}: "
                f"{f.replace('_', ' ')} {old or '(blank)'} -> "
                f"{new or '(blank)'} - {why}")
    if out["removed"]:
        out["red_flags"].append(
            f"{len(out['removed'])} activit"
            f"{'y' if len(out['removed']) == 1 else 'ies'} removed - "
            "explain each in the update narrative")
    return out


# ------------------------------------------------------------- TIA
class _Frozen(WhatIf):
    """A what-if copy that also uses the snapshot's holidays."""

    def __init__(self, store, acts, holidays=None):
        super().__init__(store, acts)
        self._hol = holidays

    def setting(self, key, default=None):
        if key == "holidays" and self._hol is not None:
            return list(self._hol)
        return super().setting(key, default)


def _base_for(store, start):
    best = None
    for e in updates(store):
        dd = _d(e.get("data_date"))
        if dd and (start is None or dd <= start):
            if best is None or dd >= _d(best.get("data_date")):
                best = e
    return best


def check_inputs(rec):
    """[problem text] for what a delay event can't hold: added workdays
    or fragnet durations below 0. A delay event only adds time - work
    taken out (a negative impact) is a recovery step, not a delay, and
    would hide the event's effect behind "absorbed by float"."""
    out = []
    for ln in rec.get("affected") or []:
        ref = str(ln.get("id") or "").strip()
        days = _num(ln.get("days"))
        if ref and days < 0:
            out.append(f"Affected activity {ref}: {days:g} workdays - added "
                       "workdays can't be below 0 (0 is allowed). Time "
                       "taken out is a recovery step, not a delay.")
    for k, ln in enumerate(rec.get("fragnet") or [], 1):
        dur = _num(ln.get("duration"))
        if dur < 0:
            name = str(ln.get("name") or "").strip() or f"Fragnet {k}"
            out.append(f"Fragnet '{name}': duration {dur:g} - can't be "
                       "below 0 (0 is allowed).")
    return out


def tia(store, rec, base=None):
    """Time impact analysis of a delay event on a what-if copy. Raises
    ValueError (with the reason) for a negative impact: added workdays or
    a fragnet duration below 0 (check_inputs), or a result that moves the
    finish earlier."""
    bad = check_inputs(rec)
    if bad:
        raise ValueError("Time impact analysis refused: " + " ".join(bad))
    notes = []
    start = _d(rec.get("event_start"))
    if base is None:
        base = _base_for(store, start)
    if base:
        acts = [{k: copy.deepcopy(v) for k, v in a.items()
                 if k in SNAP_FIELDS} for a in base.get("activities") or []]
        for k, a in enumerate(acts):
            a["_n"] = k + 1
        dd = _d(base.get("data_date")) or schedule.data_date(store)
        hol = base.get("holidays")
        notes.append(f"Base: update {base.get('n')} (data date "
                     f"{dd.isoformat()}).")
    else:
        acts = store.list("activity")
        dd = schedule.data_date(store)
        hol = None
        notes.append("No update recorded before the event: the live "
                     "schedule was used as the base - record an update "
                     "first for a claim.")
    if not start:
        notes.append("No event start: the fragnet was not held to a date.")
    before = schedule.compute(_Frozen(store, acts, hol), dd)
    find = schedule.resolver(acts)
    by = {a["_id"]: a for a in acts}
    new_ids = []
    for k, ln in enumerate(rec.get("fragnet") or [], 1):
        name = str(ln.get("name") or "").strip() or f"Fragnet {k}"
        fid, fno = f"tia-frag-{k}", f"TIA-F{k}"
        act = {"_id": fid, "_no": fno, "name": name, "_n": 10 ** 6 + k,
               "duration": max(0, int(round(_num(ln.get("duration"))))),
               "preds": [], "status": "Not Started"}
        if start:
            act["start"] = start.isoformat()
        p = str(ln.get("pred") or "").strip()
        if p:
            pid = find(p)
            if pid:
                act["preds"].append({"id": by[pid]["_no"]})
            else:
                notes.append(f"Fragnet '{name}': no predecessor '{p}'.")
        s = str(ln.get("succ") or "").strip()
        if s:
            sid = find(s)
            if sid:
                by[sid]["preds"] = list(by[sid].get("preds") or []) + \
                    [{"id": fno}]
            else:
                notes.append(f"Fragnet '{name}': no successor '{s}'.")
        if not p and not s:
            notes.append(f"Fragnet '{name}' isn't tied to the schedule.")
        acts.append(act)
        new_ids.append(fid)
    for ln in rec.get("affected") or []:
        ref = str(ln.get("id") or "").strip()
        days = int(round(_num(ln.get("days"))))
        if not ref:
            continue
        aid = find(ref)
        if aid is None:
            notes.append(f"Affected: no activity '{ref}'.")
            continue
        a = by[aid]
        if a.get("actual_finish") or a.get("status") == "Complete":
            notes.append(f"{a.get('_no')} {a.get('name')} was already "
                         "finished at the base update: added days have "
                         "no effect.")
        a["duration"] = max(0, int(round(_num(a.get("duration")))) + days)
    after = schedule.compute(_Frozen(store, acts, hol), dd)
    notes += [f"Schedule: {p}" for p in after["problems"]
              if p not in before["problems"]]
    fb, fa = before["finish"], after["finish"]
    cal = after["cal"]
    impact = (cal.index(fa) - cal.index(fb)) if fa and fb else 0
    if impact < 0:
        raise ValueError(
            f"Time impact analysis refused: the event moves the finish "
            f"{-impact} workdays earlier ({fb} to {fa}). A delay event "
            "can't shorten the schedule - check its fragnet and affected "
            "activities.")
    rows = {r["_id"]: r for r in after["rows"]}
    crit = [str(rows[i].get("_no")) for i in after["critical"]]
    on_crit = any(i in after["critical"] for i in new_ids)
    if impact == 0:
        notes.append("No delay to the finish: the event was absorbed by "
                     "float.")
    return {"base_update": base.get("n") if base else None,
            "finish_before": fb, "finish_after": fa,
            "impact_workdays": impact,
            "impact_calendar_days": (fa - fb).days if fa and fb else 0,
            "critical_after": crit, "fragnet_on_critical": on_crit,
            "notes": notes}


def _events(store):
    return [r for r in store.list("delay")
            if r.get("status") != "Withdrawn"]


def tia_all(store):
    """[{_id, _no, title, ...tia()}] for every delay event not withdrawn
    (an event tia() refuses has {"error": reason, impact_workdays None})."""
    out = []
    for r in sorted(_events(store), key=lambda r: (
            str(r.get("event_start") or ""), r.get("_n") or 0)):
        try:
            res = tia(store, r)
        except ValueError as e:
            res = {"error": str(e), "impact_workdays": None}
        res.update(_id=r["_id"], _no=r.get("_no"), title=r.get("title"))
        out.append(res)
    return out


def _window(r):
    s = _d(r.get("event_start"))
    if not s:
        return None
    e = _d(r.get("event_end")) or s
    return s, max(s, e)


def concurrency(store):
    """Owner and contractor delays at the same time: [{owner, contractor,
    start, end, days}] (dates overlap, calendar days inclusive)."""
    ev = [(r, _window(r)) for r in _events(store)]
    own = [(r, w) for r, w in ev if w and r.get("responsibility") == OWNER]
    con = [(r, w) for r, w in ev if w and
           r.get("responsibility") == CONTRACTOR]
    out = []
    for o, wo in own:
        for c, wc in con:
            s, e = max(wo[0], wc[0]), min(wo[1], wc[1])
            if s <= e:
                out.append({"owner": o.get("_no"), "contractor": c.get("_no"),
                            "start": s, "end": e, "days": (e - s).days + 1})
    out.sort(key=lambda x: (x["start"], str(x["owner"])))
    return out


def notice_late(store, rec, today=None):
    """{late, days, limit, given, note}: notice later than the setting
    "notice_days" - Project settings > Notice period (days) - in calendar
    days from the event start; default 7. On the last day is on time."""
    limit = int(_num(store.setting(NOTICE_SETTING), NOTICE_DAYS))
    start = _d(rec.get("event_start"))
    given = _d(rec.get("notice_date"))
    note = (f"Notice is checked against {limit} calendar days from the "
            "event start - the contract governs.")
    if not start:
        return {"late": False, "days": None, "limit": limit,
                "given": bool(given), "note": "No event start. " + note}
    end = given or _d(today) or _dt.date.today()
    days = (end - start).days
    late = days > limit
    if late and not given:
        note = f"No notice given yet, {days} days after the event. " + note
    return {"late": late, "days": days, "limit": limit,
            "given": bool(given), "note": note}


# ------------------------------------------------------------- windows
def windows(store):
    """Per consecutive pair of updates: [{from, to, start, end,
    finish_before, finish_after, workdays, calendar_days, events}] - the
    events are the delay records whose event start falls in the window
    (after the earlier data date, up to the later one)."""
    log = updates(store)
    ev = _events(store)
    hol = store.setting("holidays") or ()
    out = []
    for a, b in zip(log, log[1:]):
        s, e = _d(a.get("data_date")), _d(b.get("data_date"))
        fa, fb = _d(a.get("finish")), _d(b.get("finish"))
        inside = [r for r in ev if _d(r.get("event_start")) and s and e and
                  s < _d(r["event_start"]) <= e]
        inside.sort(key=lambda r: str(r.get("event_start")))
        out.append({"from": a.get("n"), "to": b.get("n"),
                    "start": _iso(s), "end": _iso(e),
                    "finish_before": _iso(fa), "finish_after": _iso(fb),
                    "workdays": _workdays(fa, fb, hol) if fa and fb else None,
                    "calendar_days": (fb - fa).days if fa and fb else None,
                    "events": [r.get("_no") for r in inside]})
    return out
