"""The AI Takeoff's CHECK items, decided by a person (the review screen):
what the AI found but wasn't sure enough to take off - an inferred CMU
back-up, a brick height, a fitting count - one at a time, each accepted
as it is, fixed (a quantity typed in) and accepted, or deleted.

    queue(res) -> [item]        the CHECK items, most worth a look first
    accept(res, item, qty=None) the item becomes a taken-off quantity
    delete(res, item)           the item is dropped from the takeoff
    decisions(res) -> [record]  what was decided, for the record
    score(item) -> 0-100        how sure the AI is (least sure first:
                                queue(res, order="least_sure"))
    missed(res, name, ...)      a person logs something the AI missed
    removed_and_missed(res)     what review took out or added as missed

A deletion or a fix can carry a reason - "not there", "wrong shape",
"misidentified" - and a logged miss has "missed". Each is also written,
without the reviewer's name, to a feedback file on this PC
(ai_feedback.jsonl in the settings folder) to tune the takeoff later.
Nothing is sent anywhere.

An accepted item moves from res["review"] to res["quantities"] with its
basis saying who decided it, so the totals and the estimate workbook
follow. Nothing is decided without a person."""
import json
import os
import re
import time
from .dmoney import c2 as _c2

REASONS = ("missed", "not there", "wrong shape", "misidentified")
FEEDBACK_FILE = "ai_feedback.jsonl"
_CONF = re.compile(r"confidence\s*(?:of\s*)?(0?\.\d+|1(?:\.0+)?)", re.I)
# what a reason line says about how sure the finding is (no score given)
_DOUBT = (
    (re.compile(r"no size tag|not joined|untagged|no wall-type tag|"
                r"measure it by hand|give it a type by hand", re.I), 0.35),
    (re.compile(r"not inside the trace|overlaps|holds another|"
                r"columns don't line up|no header|the same key twice|"
                r"doesn't look like", re.I), 0.3),
    (re.compile(r"size check only|not sure|leader points", re.I), 0.6),
)

# review lines that repeat something already taken off: accepting one
# would count it twice, so the screen offers Delete first
_ALREADY = re.compile(r"counted once|not counted twice|counted again|"
                      r"already (?:counted|in)|isn't added again|"
                      r"same key on|also tagged on|drawn again", re.I)


def is_repeat(item):
    return bool(_ALREADY.search(item.get("why") or ""))


def _weight(item):
    """Sort key: items with a quantity first (they change the estimate),
    then the larger quantities; repeats and notes last."""
    q = item.get("qty")
    has = isinstance(q, (int, float)) and q > 0
    return (is_repeat(item), not has, -(q or 0) if has else 0,
            item.get("sheet") or "", item.get("name") or "")


def score(item):
    """How sure the AI is of this item, 0-100: the engine's own
    confidence when it gave one (a room trace, a symbol match), else one
    written in its reason ("confidence 0.55"), else a cautious figure from
    what the reason says. Items read from a scanned sheet count as less
    sure. A ranking for the review order - not a measured accuracy."""
    c = item.get("confidence")
    if not isinstance(c, (int, float)):
        m = _CONF.search(item.get("why") or "")
        c = float(m.group(1)) if m else None
    if not isinstance(c, (int, float)):
        c = 0.5
        why = item.get("why") or ""
        for rx, v in _DOUBT:
            if rx.search(why):
                c = min(c, v) if c != 0.5 else v
    c = float(c)
    if c > 1.0:
        c = c / 100.0
    if not isinstance(item.get("qty"), (int, float)):
        c = min(c, 0.2)
    if item.get("source") == "scan":
        c *= 0.6
    return int(round(max(0.0, min(1.0, c)) * 100))


def queue(res, order="worth"):
    """The undecided CHECK items: most worth a look first (the larger
    quantities), or with order="least_sure" the least sure first (score);
    repeats of something already counted always last."""
    items = [x for x in (res.get("review") or ()) if not x.get("decided")]
    if order == "least_sure":
        return sorted(items, key=lambda x: (is_repeat(x), score(x),
                                            _weight(x)))
    return sorted(items, key=_weight)


def _reason(reason):
    if reason is None or reason == "":
        return None
    r = str(reason).strip().lower()
    if r not in REASONS:
        raise ValueError(f"unknown reason {reason!r}; one of "
                         + ", ".join(REASONS))
    return r


def feedback_path():
    from . import settings
    return os.path.join(settings.DIR, FEEDBACK_FILE)


def _log(rec, item, log_path):
    """One line in the feedback file - what and why, never who."""
    if log_path is None:
        return
    path = feedback_path() if log_path == "default" else str(log_path)
    row = {"when": rec["when"], "action": rec["action"],
           "reason": rec.get("reason"), "engine": item.get("engine"),
           "name": rec.get("name"), "sheet": rec.get("sheet"),
           "page": rec.get("page"), "qty_found": rec.get("qty_found"),
           "qty": rec.get("qty"), "unit": rec.get("unit"),
           "score": score(item) if item.get("why") is not None or
           item.get("confidence") is not None else None,
           "source": item.get("source"), "why": item.get("why")}
    try:
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except OSError:
        pass                     # the decision itself is already recorded


def _record(res, item, action, qty, who, reason=None,
            log_path="default"):
    rec = {"name": item.get("name"), "sheet": item.get("sheet"),
           "page": item.get("page"), "action": action,
           "qty_found": item.get("qty"), "qty": qty,
           "unit": item.get("unit"), "why": item.get("why"),
           "who": who, "when": time.strftime("%Y-%m-%d %H:%M")}
    if reason:
        rec["reason"] = reason
    res.setdefault("decisions", []).append(rec)
    if reason:
        _log(rec, item, log_path)
    return rec


def accept(res, item, qty=None, who="reviewer", reason=None,
           log_path="default"):
    """Take the item off: as found, or with the quantity the person typed.
    Returns the new quantity line, or None when there is no quantity."""
    reason = _reason(reason)
    q = item.get("qty") if qty is None else qty
    if not isinstance(q, (int, float)):
        return None
    try:
        res["review"].remove(item)
    except (KeyError, ValueError):
        pass
    fixed = qty is not None and qty != item.get("qty")
    line = {"engine": item.get("engine") or "review",
            "name": item.get("name"), "qty": _c2(float(q)),
            "unit": item.get("unit") or "EA", "status": "taken off",
            "page": item.get("page"), "sheet": item.get("sheet"),
            "csi": item.get("csi") or "", "reviewed": True,
            "basis": ("quantity entered" if fixed else "accepted as found")
            + f" by {who} in review"
            + (f" (AI found {item.get('qty'):g})"
               if fixed and isinstance(item.get("qty"), (int, float))
               else "")}
    res.setdefault("quantities", []).append(line)
    _record(res, item, "fixed" if fixed else "accepted", q, who,
            reason if fixed else None, log_path)
    return line


def delete(res, item, who="reviewer", reason=None, log_path="default"):
    """Drop the item: it is not in the takeoff or the workbook. `reason`:
    "not there", "wrong shape" or "misidentified"."""
    reason = _reason(reason)
    try:
        res["review"].remove(item)
    except (KeyError, ValueError):
        pass
    _record(res, item, "deleted", None, who, reason, log_path)
    return True


def missed(res, name, sheet=None, page=None, qty=None, unit=None,
           who="reviewer", log_path="default"):
    """A person logs something the AI didn't find. It is recorded (and
    in the feedback file); it is not added to the takeoff - measure it
    with the normal tools."""
    item = {"name": name, "sheet": sheet, "page": page, "qty": None,
            "unit": unit, "why": None, "engine": None}
    rec = _record(res, item, "missed", qty, who, "missed", log_path)
    return rec


def removed_and_missed(res):
    """What review took out (deleted, with its reason) and what was
    logged as missed - the 'what changed' view, in the order decided."""
    return [d for d in decisions(res) if d["action"] in ("deleted",
                                                          "missed")]


def decisions(res):
    return list(res.get("decisions") or ())


def counts(res):
    d = decisions(res)
    return {"left": len(queue(res)),
            "accepted": sum(1 for x in d if x["action"] == "accepted"),
            "fixed": sum(1 for x in d if x["action"] == "fixed"),
            "deleted": sum(1 for x in d if x["action"] == "deleted")}
