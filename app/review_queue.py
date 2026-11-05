"""One review queue for everything AI Takeoff found (v3, Oct 31 2026).

    build(doc, res) -> [entry]      least sure first, repeats last
    Session(doc, res, win=None)     .accept(entry, qty=None)
                                    .deny(entry, reason=None)
                                    .undo() -> bool

Inputs: the drawing (AI measurements not accepted yet - outlines, lines,
count dots, from audit.trail) and the run's result (res["review"]: CHECK
items - schedule rows, rooms, duct runs, a doubtful scale, cross-checks).

Steps:
1. Every AI measurement on the drawing that isn't accepted is an entry
   (kind "area", "length" or "count"); every undecided CHECK item is one
   too ("schedule row", "scale", or by its unit). A CHECK item and an
   outline for the same room (engine rooms, same page, same name) are ONE
   entry: deciding it decides both.
2. Each entry's score (0-100): the CHECK item's score (review.score) when
   there is one; else the measurement's own confidence; else 60 for an AI
   measurement flagged for review and 85 for one the AI took off (80 or
   more is needed to take off). Sorted least sure first, repeats of
   something already counted last.
3. Accept: the measurement turns solid, loses its AI badge and is
   "Accepted" (so a pending one joins the totals); the CHECK item becomes
   a taken-off quantity (a scale is confirmed: its sheet's held totals
   count again). Deny: the measurement is deleted; the CHECK item is
   dropped (with its reason in the feedback file). Undo puts the last
   decision back on the drawing and in the result.

Pending (flagged for review) items are in no total until accepted - the
same rule as room 109 in v2.

Failure points: a room whose CHECK item and outline have different names
shows as two entries; with the window open, Undo goes through the
window's Edit > Undo and is refused if something else was edited since.
"""
import copy

from . import annotate, review

TAKEN_SCORE = 85        # an AI measurement taken off (80+ to take off)
FLAGGED_SCORE = 60      # an AI measurement flagged for review
_AREA_UNITS = ("sf", "sq ft", "sq. ft", "sqft", "sy", "m2")
_LEN_UNITS = ("ft", "lf", "m")


def _item_kind(x):
    if x.get("kind") == "scale" or x.get("engine") == "scale":
        return "scale"
    if x.get("engine") == "schedules":
        return "schedule row"
    u = str(x.get("unit") or "").lower()
    if u in _AREA_UNITS:
        return "area"
    if u in _LEN_UNITS:
        return "length"
    if u in ("ea", "each"):
        return "count"
    return "item"


def _mark_score(r):
    c = r.get("confidence")
    if isinstance(c, (int, float)):
        return review.score({"confidence": c, "qty": r.get("value"),
                             "source": r.get("source")})
    if str(r.get("method") or "").endswith(annotate.REVIEW_SUFFIX):
        return FLAGGED_SCORE
    return TAKEN_SCORE


def build(doc, res):
    """The queue (see the module notes)."""
    from . import audit
    marks = []
    if doc is not None:
        for r in audit.trail(doc):
            m = str(r.get("method") or "")
            if r.get("status") == "Accepted" or not m.startswith(
                    ("AI takeoff", "auto")) or "(reviewed)" in m:
                continue
            marks.append(r)
    items = [x for x in (res or {}).get("review") or ()
             if not x.get("decided")]
    used = set()
    out = []
    for r in marks:
        item = None
        if str(r.get("method") or "").startswith("AI takeoff: rooms"):
            item = next((x for x in items if id(x) not in used and
                         x.get("engine") == "rooms" and
                         x.get("page") == r["page"] and
                         x.get("name") == r["group"]), None)
            if item is not None:
                used.add(id(item))
        sc = review.score(item) if item is not None else _mark_score(r)
        out.append({"kind": r["type"] if r["type"] in (
                        "area", "length", "count") else "item",
                    "name": r["group"] or r["type"].title(),
                    "qty": r["value"], "unit": r["unit"],
                    "page": r["page"], "sheet": r.get("sheet"),
                    "score": sc, "why": (item or {}).get("why") or
                    r.get("method"), "source": (item or {}).get("source"),
                    "pending": str(r.get("method") or "").endswith(
                        annotate.REVIEW_SUFFIX),
                    "repeat": bool(item and review.is_repeat(item)),
                    "mark": r, "item": item, "rect": None})
    for x in items:
        if id(x) in used:
            continue
        k = _item_kind(x)
        # a scale's score is the scale check's own (scale_evidence)
        sc = round(100 * float(x.get("confidence") or 0)) if k == "scale" \
            else review.score(x)
        out.append({"kind": k, "name": x.get("name") or "Item",
                    "qty": x.get("qty"), "unit": x.get("unit") or "",
                    "page": x.get("page"), "sheet": x.get("sheet"),
                    "score": sc, "why": x.get("why") or "",
                    "source": x.get("source"), "pending": True,
                    "repeat": review.is_repeat(x), "mark": None, "item": x,
                    "rect": x.get("rect")})
    out.sort(key=lambda e: (e["repeat"], e["score"],
                            -(e["qty"] or 0) if isinstance(
                                e["qty"], (int, float)) else 0,
                            str(e.get("sheet") or ""), e["name"]))
    return out


class Session:
    """Decisions on the queue, with Undo. `win`: the main window, when the
    drawing is open in it (its Undo history is used); else the decisions
    are made straight on `doc` and Undo restores the page."""

    def __init__(self, doc, res, win=None, who="reviewer",
                 log_path="default"):
        self.doc = doc
        self.res = res if res is not None else {}
        self.win = win
        self.who = who
        self.log_path = log_path
        self.done = []          # undo records, last first out

    # ---- the drawing --------------------------------------------------
    def _view(self):
        return getattr(self.win, "_view", None) if self.win else None

    def _apply(self, page, kind, payload):
        v = self._view()
        if v is not None:
            n = v.apply_marks([(page, kind, payload)])
            return {"how": "window", "pos": v.history.pos} if n else None
        from . import history
        st = history.page_state(self.doc, page)
        annotate.apply_op(self.doc, {"kind": kind, "page": page,
                                     "id": f"rq{len(self.done)}",
                                     "payload": payload}, fresh=True)
        return {"how": "page", "page": page, "state": st}

    def _snap(self):
        r = self.res
        return {k: copy.copy(r.get(k)) for k in ("review", "quantities",
                                                 "decisions")} | {
            "sheets": {p: dict(sh) for p, sh in (r.get("sheets") or
                                                 {}).items()},
            "q_status": [(q, q.get("status"), q.get("scale_hold"))
                         for q in r.get("quantities") or ()]}

    # ---- decisions ----------------------------------------------------
    def accept(self, e, qty=None, reason=None):
        snap = self._snap()
        drawn = None
        m = e.get("mark")
        if m is not None:
            payload = dict(m["ref"], status="Accepted", dashes=[],
                           badge=False)
            drawn = self._apply(m["page"], "set_annot", payload)
        line = None
        it = e.get("item")
        if it is not None:
            if e["kind"] == "scale":
                review._record(self.res, it, "scale confirmed", None,
                               self.who, None, self.log_path)
                try:
                    self.res["review"].remove(it)
                except (KeyError, ValueError):
                    pass
                from . import aitakeoff
                aitakeoff.release_scale(self.res, it.get("page"))
            else:
                q = qty if qty is not None else e.get("qty")
                line = review.accept(self.res, it,
                                     None if q == it.get("qty") else q,
                                     self.who, reason=reason,
                                     log_path=self.log_path)
                if line is None and m is None:
                    return None          # no quantity: type one first
        self.done.append({"entry": e, "snap": snap, "drawn": drawn,
                          "action": "accept"})
        return line if line is not None else True

    def deny(self, e, reason=None):
        snap = self._snap()
        drawn = None
        m = e.get("mark")
        if m is not None:
            drawn = self._apply(m["page"], "delete_annot", dict(m["ref"]))
        it = e.get("item")
        if it is not None:
            if e["kind"] == "scale":
                review._record(self.res, it, "scale rejected", None,
                               self.who, None, self.log_path)
                try:
                    self.res["review"].remove(it)
                except (KeyError, ValueError):
                    pass
            else:
                review.delete(self.res, it, self.who, reason=reason,
                              log_path=self.log_path)
        self.done.append({"entry": e, "snap": snap, "drawn": drawn,
                          "action": "deny"})
        return True

    def undo(self):
        """Put the last decision back. False when there is none, or when
        the drawing was edited in the window since."""
        if not self.done:
            return False
        rec = self.done[-1]
        d = rec["drawn"]
        if d is not None and d["how"] == "window":
            v = self._view()
            if v is None or v.history.pos != d["pos"]:
                return False
            self.win.undo()
        elif d is not None:
            from . import history
            history.restore_page(self.doc, d["state"])
        self.done.pop()
        s = rec["snap"]
        for k in ("review", "quantities", "decisions"):
            if s[k] is None:
                self.res.pop(k, None)
            else:
                self.res[k] = s[k]
        for p, sh in s["sheets"].items():
            self.res["sheets"][p].clear()
            self.res["sheets"][p].update(sh)
        for q, st, hold in s["q_status"]:
            q["status"] = st
            if hold is None:
                q.pop("scale_hold", None)
            else:
                q["scale_hold"] = hold
        return True
