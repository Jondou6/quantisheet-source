"""Master ID matching for MS Project / P6 files (design 3.4).

Order: the per-sub mapping table Jon saved ("msp:<UID>" / "p6:<task
code>" -> activity _id, or "ignore") -> the master ID carried in the file
(MSP Text30, a P6 activity code, the P6 task code), as an activity _id or
activity number -> an activity created by an earlier Scheduler import of
the same file (its _ext). Matching uses _id, never only _no, so hub
renumbering can't break a saved mapping (4.9)."""
from . import model

IGNORE = "ignore"


def _norm(v):
    return str(v or "").strip().casefold()


def mappings(store, company):
    m = model.config(store).get("mappings") or {}
    for k, v in m.items():
        if model.same_company(k, company):
            return dict(v or {})
    return {}


def find(store, company, cand):
    """cand: {"ref", "ids": [value or (label, value)], "ext", "name"}.
    -> (activity, how) | (None, "ignore") | (None, None)."""
    acts = store.list("activity")
    by_id = {a["_id"]: a for a in acts}
    t = mappings(store, company).get(cand.get("ref"))
    if t == IGNORE:
        return None, IGNORE
    if t and t in by_id:
        return by_id[t], "mapping"
    by_no = {_norm(a.get("_no")): a for a in acts if a.get("_no")}
    for x in cand.get("ids") or ():
        label, val = x if isinstance(x, tuple) else ("master id", x)
        if not str(val or "").strip():
            continue
        a = by_id.get(str(val).strip()) or by_no.get(_norm(val))
        if a is not None:
            return a, label
    ext = cand.get("ext")
    if ext:
        for a in acts:
            if a.get("_ext") == ext:
                return a, "earlier import"
    return None, None


def save(store, company, pairs):
    """pairs {ref: activity _id | "ignore"}: each target must be one of
    this sub's own activities. All checked before anything is saved."""
    mine = set(model.slice_ids(store, company))
    bad = [f"{r} -> {t}" for r, t in pairs.items()
           if not (str(r).startswith(("msp:", "p6:")) and
                   (t == IGNORE or t in mine))]
    if bad:
        raise ValueError("Each row maps to one of " + str(company) +
                         "'s own activities (or Ignore): " + ", ".join(bad))
    allm = dict(model.config(store).get("mappings") or {})
    key = next((k for k in allm if model.same_company(k, company)), company)
    cur = dict(allm.get(key) or {})
    cur.update(pairs)
    allm[key] = cur
    model.set_config(store, mappings=allm)
    return cur
