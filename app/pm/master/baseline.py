"""Lockable baseline (design 2.4 / 4.12).

The authoritative baseline is a hash-chained schedule_record snapshot of
kind "baseline"; the activities' baseline_start/finish fields are a
display copy. While locked, schedule.set_baseline() refuses (the Set
Baseline buttons say so); a deliberate re-baseline needs a reason and
confirmation, writes a NEW baseline entry and moves the lock to it - the
old entry stays in the chain forever."""
import copy
import datetime as _dt

from .. import schedule, schedule_record

LOCK = "master_baseline"
FIELDS = ("baseline_start", "baseline_finish")


def status(store):
    st = store.setting(LOCK)
    return copy.deepcopy(st) if isinstance(st, dict) and st.get("locked") \
        else None


def _now(now):
    return (now or _dt.datetime.now()).replace(microsecond=0).isoformat()


def _copy_dates(store):
    """Fill the display copy from today's computed dates (what
    set_baseline does, without its lock check)."""
    cpm = schedule.compute(store, schedule.data_date(store))
    n = 0
    for r in cpm["rows"]:
        a = store.get("activity", r["_id"])
        bs, bf = r["es"].isoformat(), r["ef"].isoformat()
        if a.get("baseline_start") != bs or a.get("baseline_finish") != bf:
            a["baseline_start"], a["baseline_finish"] = bs, bf
            store.save_record("activity", a)
            n += 1
    return n


def lock(store, reason, by=None, now=None):
    """Lock the baseline. Activities with no baseline dates get today's
    computed dates first; then a baseline snapshot is recorded and the
    lock points at it."""
    if status(store):
        raise ValueError("The baseline is already locked; use Re-baseline.")
    reason = str(reason or "").strip()
    if not reason:
        raise ValueError("Give a reason for locking the baseline.")
    acts = store.list("activity")
    if not acts:
        raise ValueError("There are no activities to baseline.")
    if any(not a.get("baseline_start") or not a.get("baseline_finish")
           for a in acts):
        _copy_dates(store)
    e = schedule_record.snapshot(store, "baseline",
                                 f"Locked baseline: {reason}", who=by,
                                 now=now)
    store.set_setting(LOCK, {
        "locked": True, "snapshot_n": e["n"], "hash": e["hash"],
        "at": _now(now), "by": by if by is not None else store.me,
        "reason": reason,
        "history": [{"snapshot_n": e["n"], "hash": e["hash"],
                     "at": _now(now), "reason": reason}]})
    return e


def locked_entry(store):
    """The locked baseline entry; ValueError when it is missing or was
    changed after it was recorded."""
    st = status(store)
    if not st:
        return None
    for e in schedule_record.updates(store):
        if e.get("n") == st["snapshot_n"]:
            if e.get("hash") != st["hash"] or \
                    schedule_record._hash(e) != e.get("hash"):
                raise ValueError(f"Locked baseline (update {e.get('n')}) "
                                 "was changed after it was recorded.")
            return e
    raise ValueError("The locked baseline entry is missing from the "
                     "schedule history.")


def problems(store):
    out = []
    try:
        locked_entry(store)
    except ValueError as ex:
        out.append(str(ex))
    return out + schedule_record.verify(store)


def drift(store):
    """Activities whose displayed baseline dates differ from the locked
    entry (typed in the grid, or brought in by an import)."""
    e = locked_entry(store)
    if e is None:
        return []
    want = {a["_id"]: a for a in e.get("activities") or []}
    out = []
    for a in store.list("activity"):
        w = want.get(a["_id"])
        if w is None:
            continue                    # added after the baseline
        for f in FIELDS:
            if (a.get(f) or "") != (w.get(f) or ""):
                out.append({"_id": a["_id"], "_no": a.get("_no"),
                            "name": a.get("name"), "field": f,
                            "shown": a.get(f) or "",
                            "locked": w.get(f) or ""})
    return out


def restore(store):
    """Put the locked baseline back into the display fields."""
    e = locked_entry(store)
    if e is None:
        return 0
    want = {a["_id"]: a for a in e.get("activities") or []}
    n = 0
    for d in {x["_id"] for x in drift(store)}:
        a = store.get("activity", d)
        for f in FIELDS:
            a[f] = want[d].get(f) or ""
        store.save_record("activity", a)
        n += 1
    return n


def rebaseline(store, reason, confirm=False, by=None, now=None):
    """A deliberate new baseline: new snapshot, lock moved, the old entry
    kept, compare(old, new) recorded in the lock history."""
    if not confirm:
        raise PermissionError("Re-baselining needs Jon's confirmation.")
    reason = str(reason or "").strip()
    if not reason:
        raise ValueError("Give a reason for the re-baseline.")
    old = locked_entry(store)
    st = status(store)
    if old is None:
        return lock(store, reason, by=by, now=now)
    _copy_dates(store)
    e = schedule_record.snapshot(store, "baseline",
                                 f"Re-baseline: {reason}", who=by, now=now)
    hist = list(st.get("history") or [])
    hist.append({"snapshot_n": e["n"], "hash": e["hash"], "at": _now(now),
                 "reason": reason, "replaces": old["n"],
                 "compare": schedule_record.compare(old, e)})
    st.update(snapshot_n=e["n"], hash=e["hash"], at=_now(now),
              by=by if by is not None else store.me, reason=reason,
              history=hist)
    store.set_setting(LOCK, st)
    return e
