"""Running AI Takeoff again without counting anything twice (AI Takeoff
v3, Oct 31 2026).

    split(doc, marks) -> {"new": [mark], "previous": [record], "other":
                          [mark]}
    carry_decisions(prev_res, new_res) -> {"locked": [record]}
    drawing_totals(doc) -> {(group, type, unit): (total, pending)}

Inputs: the new run's measurements (page, kind, payload) and the takeoff
measurements already on the drawing - the AI's from an earlier run,
accepted or not, and a person's own.

Steps (split):
1. Read every takeoff measurement on the pages the run touched: areas as
   outlines (polygons, rectangles), lengths as lines, counts as the
   centre of their number.
2. Match each new measurement to one already there of the same type, by
   place and shape - never by name, so a renamed (reassigned) or accepted
   item is still recognised:
   - areas: the outlines overlap by AREA_IOU (80%) or more (area of the
     intersection over area of the union);
   - lengths: every point of each line is within LINE_TOL_PT (6 pt, 2 in
     at 1/4" = 1'-0") of the other line, and the lengths agree within
     LINE_LEN_TOL (10%);
   - counts: within COUNT_TOL_PT (6 pt) of a count of the same item, or of
     any count the AI made (it may have been reassigned since).
   Each one already there matches at most one new measurement.
3. A match is 'previously detected' and locked: it is never added again,
   whatever its state (pending, accepted, a person's own). The rest are
   'new matches' for the person to pick from.

carry_decisions(): CHECK items decided on the earlier run (accepted,
fixed, deleted, a scale confirmed) that come back with the same name,
sheet, page and quantity (within 1%) are not asked again: they keep the
earlier decision (an accepted one keeps its quantity line) and are listed
as locked.

Failure points: a room traced very differently on the second run (under
80% overlap) comes back as new - the person sees it in the new list and
can leave it out; two different items drawn exactly on top of each other
with the same type are taken as one.
"""
AREA_IOU = 0.80
LINE_TOL_PT = 6.0
LINE_LEN_TOL = 0.10
COUNT_TOL_PT = 6.0
QTY_TOL = 0.01

_KINDS = {"add_polygon": "area", "add_polyline": "length",
          "add_line": "length", "add_count": "count"}


def _status(doc, a):
    from . import annotate
    o = annotate.origin(doc, a)
    # an AI item a person reshaped is checked work: kept like an accepted
    return {"ai-accepted": "accepted", "ai-edited": "accepted",
            "ai-pending": "pending"}.get(o, "manual")


def existing(doc, pages):
    """{page: [{type, group, status, geom, tag, method}]} for the takeoff
    measurements on `pages`."""
    import fitz
    from shapely.geometry import LineString, Point, Polygon
    from . import annotate
    out = {}
    for p in pages:
        if not (isinstance(p, int) and 0 <= p < doc.page_count):
            continue
        page = doc[p]
        got = []
        for a in annotate.iter_annots(page):
            subj = str((a.info or {}).get("subject", ""))
            if not subj.startswith(annotate.TAKEOFF + ":"):
                continue
            parts = (subj.split(":", 5) + [""] * 6)[:6]
            mtype, group = parts[1], parts[4]
            t = a.type[0]
            geom = None
            try:
                if mtype == "count":
                    r = a.rect
                    geom = Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
                elif mtype == "area":
                    if t == fitz.PDF_ANNOT_POLYGON and a.vertices and \
                            len(a.vertices) >= 3:
                        geom = Polygon([tuple(v) for v in a.vertices])
                    elif t in (fitz.PDF_ANNOT_SQUARE, fitz.PDF_ANNOT_CIRCLE):
                        r = annotate.inner_rect(doc, a)
                        geom = Polygon([(r.x0, r.y0), (r.x1, r.y0),
                                        (r.x1, r.y1), (r.x0, r.y1)])
                    if geom is not None and not geom.is_valid:
                        geom = geom.buffer(0)
                elif mtype == "length" and a.vertices and \
                        len(a.vertices) >= 2:
                    geom = LineString([tuple(v) for v in a.vertices])
            except Exception:                            # noqa: BLE001
                geom = None
            if geom is None or geom.is_empty:
                continue
            got.append({"type": mtype, "group": group,
                        "status": _status(doc, a), "geom": geom,
                        "tag": annotate.tag_of(a),
                        "method": str(annotate.audit_of(doc, a).get(
                            "method") or ""),
                        "used": False})
        out[p] = got
    return out


def _geom(kind, pl):
    from shapely.geometry import LineString, Point, Polygon
    try:
        if kind == "add_count":
            pt = pl.get("pt")
            return Point(float(pt[0]), float(pt[1])) if pt else None
        pts = [(float(q[0]), float(q[1])) for q in pl.get("pts") or ()]
        if kind == "add_polygon" and len(pts) >= 3:
            g = Polygon(pts)
            return g if g.is_valid else g.buffer(0)
        if kind in ("add_line", "add_polyline") and len(pts) >= 2:
            return LineString(pts)
    except Exception:                                    # noqa: BLE001
        return None
    return None


def _match(kind, g, group, have):
    """The best unused measurement already there that is the same thing,
    and how well it matches (overlap, or distance in points)."""
    best, how = None, None
    mtype = _KINDS[kind]
    for h in have:
        if h["used"] or h["type"] != mtype:
            continue
        hg = h["geom"]
        if mtype == "area":
            if not g.envelope.intersects(hg.envelope):
                continue
            try:
                inter = g.intersection(hg).area
                union = g.union(hg).area
            except Exception:                            # noqa: BLE001
                continue
            iou = inter / union if union else 0.0
            if iou >= AREA_IOU and (how is None or iou > how):
                best, how = h, iou
        elif mtype == "length":
            if g.distance(hg) > LINE_TOL_PT:
                continue
            la, lb = g.length, hg.length
            if not la or abs(la - lb) / max(la, lb) > LINE_LEN_TOL:
                continue
            d = g.hausdorff_distance(hg)
            if d <= LINE_TOL_PT and (how is None or d < how):
                best, how = h, d
        else:
            d = g.distance(hg)
            if d > COUNT_TOL_PT:
                continue
            if h["group"] != group and not h["method"].startswith(
                    ("AI takeoff", "auto")):
                continue                  # a person's count of another item
            if how is None or d < how:
                best, how = h, d
    return best, how


def split(doc, marks):
    """New measurements vs those already on the drawing (see the module
    notes). Marks that aren't takeoff measurements (scales...) are in
    "other" and go ahead as before."""
    marks = list(marks)
    pages = {p for p, k, pl in marks if k in _KINDS}
    have = existing(doc, pages)
    new, previous, other = [], [], []
    for m in marks:
        p, kind, pl = m
        meas = pl.get("measure") if isinstance(pl, dict) else None
        if kind not in _KINDS or not isinstance(meas, dict):
            other.append(m)
            continue
        g = _geom(kind, pl)
        if g is None or g.is_empty:
            new.append(m)
            continue
        h, how = _match(kind, g, str(meas.get("group") or ""),
                        have.get(p) or [])
        if h is None:
            new.append(m)
            continue
        h["used"] = True
        previous.append({"mark": m, "page": p, "locked": True,
                         "status": h["status"], "have_group": h["group"],
                         "tag": h["tag"], "type": h["type"],
                         "group": meas.get("group"),
                         "value": meas.get("value"),
                         "unit": meas.get("unit"),
                         "how": round(how, 3) if how is not None else None})
    return {"new": new, "previous": previous, "other": other}


def drawing_totals(doc):
    """{(group, type, unit): (total, pending)} over the whole drawing, to
    the nearest 0.001."""
    from . import annotate
    out = {}
    for it in annotate.takeoff_items(doc):
        k = (it.get("group") or "", it["type"], it.get("unit") or "")
        t, pd = out.get(k, (0.0, 0.0))
        v = float(it.get("value") or 0.0) * float(it.get("multiplier") or 1)
        if it.get("pending"):
            pd += v
        else:
            t += v
        out[k] = (t, pd)
    return {k: (round(t, 3), round(pd, 3)) for k, (t, pd) in out.items()}


def _same_qty(a, b):
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        return a is None and b is None
    return abs(a - b) <= max(0.01, QTY_TOL * max(abs(a), abs(b)))


def _same_item(rec, item):
    return (rec.get("name") == item.get("name") and
            rec.get("sheet") == item.get("sheet") and
            rec.get("page") == item.get("page") and
            (rec.get("unit") or "") == (item.get("unit") or "") and
            _same_qty(rec.get("qty_found"), item.get("qty")))


def carry_decisions(prev, new):
    """Keep the earlier run's review decisions on the new result (see the
    module notes). Changes `new` in place."""
    if not prev or not new:
        return {"locked": []}
    locked = []
    review = new.setdefault("review", [])
    quantities = new.setdefault("quantities", [])
    decisions = new.setdefault("decisions", [])
    prev_lines = [q for q in prev.get("quantities") or ()
                  if q.get("reviewed")]
    for rec in prev.get("decisions") or ():
        act = rec.get("action")
        if act not in ("accepted", "fixed", "deleted", "scale confirmed",
                       "scale rejected"):
            continue
        item = next((x for x in review if not x.get("decided") and
                     _same_item(rec, x)), None)
        if item is None:
            continue
        review.remove(item)
        decisions.append(dict(rec))
        if act in ("accepted", "fixed"):
            line = next((q for q in prev_lines if q.get("name") ==
                         rec.get("name") and q.get("page") ==
                         rec.get("page") and q.get("sheet") ==
                         rec.get("sheet") and _same_qty(q.get("qty"),
                                                        rec.get("qty"))),
                        None)
            if line is not None:
                prev_lines.remove(line)
                quantities.append(dict(line))
        if act == "scale confirmed":
            _release_scale(new, item.get("page"))
        locked.append(dict(item, decision=act))
    return {"locked": locked}


def _release_scale(res, page):
    from . import aitakeoff
    aitakeoff.release_scale(res, page)
