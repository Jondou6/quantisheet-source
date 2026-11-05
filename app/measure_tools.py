"""Measurement tools added from the Nov 2 scope list, working on the open
viewer (PdfView): rise/drop and wall height on a run, the unit a volume is
shown in, converting a measurement to another type without redrawing it,
copying a markup several times at a set spacing (with a preview), adding
more marks to an existing count, and side lengths on screen.

Each change is one undo step (viewer.apply_marks)."""
import math

import fitz

from . import annotate, measure_extra, takeoff

RUN = (fitz.PDF_ANNOT_POLY_LINE, fitz.PDF_ANNOT_LINE)


# ---- what is selected -----------------------------------------------------------

def selected_measure(v):
    """The selected measurement's shape: {"annot", "type", "value", "unit",
    "group", "extra", "run", "tag"} - or None."""
    if not v.selected or v.multi:
        return None
    for a in annotate.find_annots(v.pg, v.selected["ref"]):
        subj = (a.info or {}).get("subject", "")
        if not subj.startswith(annotate.TAKEOFF + ":"):
            continue
        if annotate.is_label(v.doc, a) or annotate.is_hatch(v.doc, a) or \
                annotate.is_badge(v.doc, a) or annotate.is_legend(v.doc, a):
            continue
        parts = (subj.split(":", 5) + [""] * 6)[:6]
        try:
            value = float(parts[2])
        except ValueError:
            continue
        return {"annot": a, "type": parts[1], "value": value,
                "unit": parts[3], "group": parts[4], "parent": parts[5],
                "extra": measure_extra.read(v.doc, a),
                "run": a.type[0] in RUN, "tag": annotate.tag_of(a),
                "polygon": a.type[0] == fitz.PDF_ANNOT_POLYGON}
    return None


def _set(v, m, **changes):
    target = {"target": m["tag"]} if m["tag"] else {"xref": m["annot"].xref}
    return v.apply_marks([(v.page, "set_measure", {**target, **changes})])


# ---- rise / drop, wall height, volume unit ----------------------------------------

def set_rise(v, rise):
    """Vertical length (sheet units) added to the selected run; 0 removes
    it."""
    m = selected_measure(v)
    if not m or not m["run"]:
        return 0
    return _set(v, m, rise=float(rise or 0))


def set_wall(v, height, openings=0.0):
    """Make the selected run a wall area (height 0: back to a length)."""
    m = selected_measure(v)
    if not m or not m["run"]:
        return 0
    return _set(v, m, height=float(height or 0),
                openings=float(openings or 0))


def show_volume_in(v, unit):
    m = selected_measure(v)
    if not m or m["type"] != "volume":
        return 0
    return _set(v, m, show=unit)


# ---- convert a measurement to another type -----------------------------------------

CONVERT = {"length": "Length", "area": "Area", "volume": "Volume",
           "wall": "Wall Area"}


def convert_choices(m):
    """What the selected measurement can become."""
    if not m or m["type"] not in ("length", "area", "volume"):
        return []
    n = len(m["annot"].vertices or [])
    now = "wall" if m["type"] == "area" and \
        measure_extra.is_wall(m["extra"]) else m["type"]
    out = [k for k in ("length", "wall", "area", "volume") if k != now]
    if n < 3:
        out = [k for k in out if k in ("length", "wall")]
    return out


def convert(v, to, depth=None, wall=None):
    """Turn the selected measurement into a `to` measurement (length,
    area, volume or wall) on the same points: an area's outline becomes
    its perimeter, a run of 3+ points closes into an area. Name, color,
    layer and status are kept. Returns 1 when converted."""
    m = selected_measure(v)
    if not m or to not in convert_choices(m):
        return 0
    a = m["annot"]
    if m["polygon"] and m["type"] == "area" and any(
            it.get("parent") == m["tag"] for it in annotate.takeoff_items(
                v.doc, include_cutouts=True) if it["page"] == v.page):
        return -1                      # its cutouts would lose their area
    pts = [fitz.Point(q) for q in (a.vertices or [])]
    sc = v.scale(at=pts)
    if not sc or len(pts) < 2:
        return 0
    if m["polygon"] and to in ("length", "wall"):
        pts = pts + [pts[0]]                       # the perimeter
    elif not m["polygon"] and to in ("area", "volume") and \
            abs(pts[0].x - pts[-1].x) + abs(pts[0].y - pts[-1].y) < 1:
        pts = pts[:-1]                             # already closed
    if to in ("area", "volume") and len(pts) < 3:
        return 0
    extra = {k: x for k, x in m["extra"].items() if k == "to"}
    if to == "wall":
        if wall is None:
            wall = v.ask_wall()
            if wall is None:
                return 0
        extra.update(wall)
    if to == "volume" and depth is None:
        depth = v.ask_depth(sc["unit"])
        if depth is None:
            return 0
    keep = dict(v.style)
    try:
        v.style["subject"] = m["group"]
        for k in ("rise", "height", "openings", "unit"):
            v.style.pop(k, None)
        payload = v._measure_payload("length" if to == "wall" else to, pts,
                                     sc, extra, depth=depth)
    finally:
        v.style = keep
    if payload is None:
        return 0
    kind = payload.pop("_kind")
    stroke = (a.colors or {}).get("stroke")
    if stroke:
        payload["color"] = list(stroke)
        if kind == "add_polygon":
            payload["fill"] = list((a.colors or {}).get("fill") or stroke)
    if (a.border or {}).get("width", -1) > 0:
        payload["width"] = a.border["width"]
    layer = (v.selected_props() or {}).get("layer")
    if layer:
        payload["layer"] = layer
    status = annotate.status_of(v.doc, a)
    target = {"target": m["tag"]} if m["tag"] else {"xref": a.xref}
    marks = [(v.page, "delete_annot", target),
             (v.page, kind, v._styled(kind, payload))]
    n = v.apply_marks(marks)
    if n and status:
        new = [x for x in annotate.iter_annots(v.pg)
               if (x.info or {}).get("content") == payload["label"]]
        if new and annotate.tag_of(new[-1]):
            v.apply_marks([(v.page, "set_annot",
                            {"target": annotate.tag_of(new[-1]),
                             "status": status})])
    v.select(None)
    return 1 if n else 0


# ---- copy several times (multiply) ---------------------------------------------------

DIRECTIONS = {"Right": 0.0, "Down": 90.0, "Left": 180.0, "Up": 270.0}


def offset(v, spacing_pts, direction):
    """Page (unrotated) offset of `spacing_pts` toward `direction` as seen
    on screen ("Right", "Down", ... or an angle in degrees, clockwise from
    right)."""
    deg = DIRECTIONS.get(direction)
    if deg is None:
        deg = float(direction)
    rad = math.radians(deg)
    a = annotate.to_page(v.pg, fitz.Point(0, 0))
    b = annotate.to_page(v.pg, fitz.Point(spacing_pts * math.cos(rad),
                                          spacing_pts * math.sin(rad)))
    return b.x - a.x, b.y - a.y


def copy_payloads(v, dx, dy, n):
    """(kind, payload) for `n` copies of the selected markup, each a
    further (dx, dy) page points along - or None when it can't be copied
    (only measurements, counts and plain shapes can)."""
    if not v.selected or v.multi:
        return None
    found = [a for a in annotate.find_annots(v.pg, v.selected["ref"])
             if not annotate.is_label(v.doc, a) and
             not annotate.is_hatch(v.doc, a) and
             not annotate.is_badge(v.doc, a)]
    if not found:
        return None
    a = found[0]
    m = selected_measure(v)
    color = list(annotate.markup_color(v.doc, a) or (1, 0, 0))
    width = (a.border or {}).get("width", -1)
    out = []
    for i in range(1, int(n) + 1):
        ox, oy = dx * i, dy * i
        if m and m["type"] == "count":
            r = fitz.Rect(a.rect)
            p = {"pt": [(r.x0 + r.x1) / 2 + ox, (r.y0 + r.y1) / 2 + oy],
                 "color": color,
                 "measure": {"type": "count", "value": 1, "unit": "ea",
                             "group": m["group"]}}
            out.append(("add_count", p))
            continue
        if m and m["type"] in ("length", "area", "volume") and \
                a.vertices:
            pts = [fitz.Point(q) + (ox, oy) for q in a.vertices]
            sc = v.scale(at=pts)
            if not sc:
                return None
            depth = None
            if m["type"] == "volume":
                area = takeoff.polygon_area(
                    [fitz.Point(q) for q in a.vertices]) / sc["ppu"] ** 2
                depth = measure_extra.volume_in(
                    m["value"], m["unit"],
                    measure_extra.unit_for("volume", sc["unit"])) \
                    if m["unit"] != f"cu {sc['unit']}" else m["value"]
                depth = (depth or 0) / area if area else None
                if not depth:
                    return None
            keep = dict(v.style)
            try:
                v.style["subject"] = m["group"]
                for k in ("rise", "height", "openings", "unit"):
                    v.style.pop(k, None)
                mt = "length" if m["run"] else m["type"]
                payload = v._measure_payload(mt, pts, sc, dict(m["extra"]),
                                             depth=depth)
            finally:
                v.style = keep
            if payload is None:
                return None
            kind = payload.pop("_kind")
            show = m["extra"].get("show")
            if m["type"] == "volume" and show:
                _show_in(payload, show)
            payload["color"] = color
            if kind == "add_polygon":
                payload["fill"] = list((a.colors or {}).get("fill") or color)
            if width > 0:
                payload["width"] = width
            out.append((kind, payload))
            continue
        t = a.type[0]
        if m:
            return None                        # other measurements
        if t in (fitz.PDF_ANNOT_SQUARE, fitz.PDF_ANNOT_CIRCLE):
            r = annotate.inner_rect(v.doc, a)
            kind = "add_rect" if t == fitz.PDF_ANNOT_SQUARE \
                else "add_ellipse"
            p = {"rect": [r.x0 + ox, r.y0 + oy, r.x1 + ox, r.y1 + oy],
                 "color": color}
            fill = (a.colors or {}).get("fill")
            if fill:
                p["fill"] = list(fill)
        elif t in (fitz.PDF_ANNOT_POLY_LINE, fitz.PDF_ANNOT_POLYGON,
                   fitz.PDF_ANNOT_LINE) and a.vertices:
            kind = {fitz.PDF_ANNOT_POLY_LINE: "add_polyline",
                    fitz.PDF_ANNOT_POLYGON: "add_polygon",
                    fitz.PDF_ANNOT_LINE: "add_line"}[t]
            p = {"pts": [[fitz.Point(q).x + ox, fitz.Point(q).y + oy]
                         for q in a.vertices], "color": color}
            fill = (a.colors or {}).get("fill")
            if fill and kind == "add_polygon":
                p["fill"] = list(fill)
        else:
            return None
        if width > 0:
            p["width"] = width
        subj = (a.info or {}).get("subject")
        if subj:
            p["subject"] = subj
        out.append((kind, p))
    return out


def _show_in(payload, unit):
    """A new volume payload kept in cubic `unit` (as its original was)."""
    mm = payload["measure"]
    got = measure_extra.volume_in(mm["value"], mm["unit"], unit)
    if got is None:
        return
    mm["value"], mm["unit"] = round(got, 4), unit
    payload["extra"] = dict(payload.get("extra") or {}, show=unit)
    payload["label"] = measure_extra.label_text(
        "volume", got, unit, mm.get("group", ""), payload["extra"])


def multiply(v, n, spacing_pts, direction="Right"):
    """Copy the selected markup `n` times, `spacing_pts` apart toward
    `direction`. One undo step; returns how many were added."""
    dx, dy = offset(v, spacing_pts, direction)
    got = copy_payloads(v, dx, dy, n)
    if not got:
        return 0
    counts = {}
    marks = []
    for kind, p in got:
        if kind == "add_count":
            g = p["measure"]["group"]
            if g not in counts:
                counts[g] = sum(1 for it in annotate.takeoff_items(v.doc)
                                if it["type"] == "count" and
                                it["page"] == v.page and it["group"] == g)
            counts[g] += 1
            p["n"] = counts[g]
        marks.append((v.page, kind, v._styled(kind, p)))
    v.ghosts = []
    return v.apply_marks(marks)


def preview(v, n, spacing_pts, direction="Right"):
    """Dashed outlines where the copies would go (screen rects), shown
    until the copy is made or cancelled."""
    if not v.selected:
        v.ghosts = []
        return []
    dx, dy = offset(v, spacing_pts, direction)
    r0 = fitz.Rect(v.selected["rect"])
    v.ghosts = [annotate.from_page(v.pg, r0 + (dx * i, dy * i,
                                               dx * i, dy * i))
                for i in range(1, int(n) + 1)]
    v.update()
    return v.ghosts


# ---- counts ----------------------------------------------------------------------

def resume_count(v, group, color=None):
    """Go on counting `group`: the Count tool, numbering after the marks
    already on the page, in the count's own color."""
    v.set_tool("count")
    v.count_group = group
    if color:
        v.style["color"] = list(color)
    return True


# ---- side lengths on screen -------------------------------------------------------

def side_lengths(v, a):
    """[(screen midpoint, text)] for each side of measurement shape `a`."""
    pts = [fitz.Point(q) for q in (a.vertices or [])]
    if len(pts) < 2:
        return []
    sc = v.scale(at=pts)
    if not sc:
        return []
    loop = pts + ([pts[0]] if a.type[0] == fitz.PDF_ANNOT_POLYGON else [])
    out = []
    for p, q in zip(loop, loop[1:]):
        d = math.hypot(q.x - p.x, q.y - p.y) / sc["ppu"]
        if d <= 0:
            continue
        mid = annotate.from_page(v.pg, fitz.Point((p.x + q.x) / 2,
                                                  (p.y + q.y) / 2))
        out.append((mid, takeoff.fmt(d, sc["unit"])))
    return out


def shapes_for_sides(v, mode):
    """Measurement shapes whose sides are labeled on screen: "selected"
    (the selected one), "all" (every one on the page), else none."""
    if mode == "selected":
        m = selected_measure(v)
        return [m["annot"]] if m and m["annot"].vertices else []
    if mode != "all":
        return []
    out = []
    for a in annotate.iter_annots(v.pg):
        subj = (a.info or {}).get("subject", "")
        if subj.startswith(annotate.TAKEOFF + ":") and a.vertices and \
                a.type[0] in RUN + (fitz.PDF_ANNOT_POLYGON,) and \
                not annotate.is_hatch(v.doc, a):
            out.append(a)
        if len(out) >= 300:
            break
    return out


# ---- bulk edit (Nov 4 takeoff list #9) -------------------------------------------------

def bulk_targets(v):
    """[(target, measure)] for every selected measurement."""
    keep_sel, keep_multi = v.selected, v.multi
    out = []
    try:
        for ref in list(v.selected_refs()):
            found = annotate.find_annots(v.pg, ref)
            if not found:
                continue
            v.multi = None
            v.select(found[0])
            m = selected_measure(v)
            if m:
                t = {"target": m["tag"]} if m["tag"] else \
                    {"xref": m["annot"].xref}
                out.append((t, m))
    finally:
        v.selected, v.multi = keep_sel, keep_multi
    return out


def bulk_edit(v, height=None, rise=None, status=None, group=None):
    """Set wall height / rise-drop (runs), status and item name on every
    selected measurement in one undoable step. None leaves a setting as it
    is. Returns how many measurements changed."""
    targets = bulk_targets(v)
    marks = []
    for t, m in targets:
        ch = {}
        if m["run"] and height is not None:
            ch["height"] = float(height)
            ch["openings"] = float(m["extra"].get("openings") or 0)
        if m["run"] and rise is not None:
            ch["rise"] = float(rise)
        if ch:
            marks.append((v.page, "set_measure", {**t, **ch}))
        if status is not None:
            marks.append((v.page, "set_annot", {**t, "status": status}))
    v.undo_label = (f"Bulk Edit ({len(targets)} items)" if len(targets) > 1
                    else "Bulk Edit")   # Undo says what it takes back
    n = v.apply_marks(marks) if marks else 0
    if group:
        n = max(n, v.reassign_selected(group))
    return len(targets) if (n or group) else 0


# ---- split and join runs (Nov 4 takeoff list #4) ----------------------------------------

JOIN_TOL = 6.0            # page points: ends this close are the same point


def _rebuild(v, m, pts):
    """add_* (kind, payload) for a run over `pts` like measurement m."""
    sc = v.scale(at=pts)
    if not sc:
        return None
    keep = dict(v.style)
    try:
        v.style["subject"] = m["group"]
        for k in ("rise", "height", "openings", "unit"):
            v.style.pop(k, None)
        extra = dict(m["extra"] or {})
        extra.pop("rise", None)           # a drop belongs to one end only
        p = v._measure_payload("length", pts, sc, extra)
    finally:
        v.style = keep
    if p is None:
        return None
    kind = p.pop("_kind")
    color = annotate.markup_color(v.doc, m["annot"])
    if color:
        p["color"] = list(color)
    return kind, p


def split_run(v, at=None):
    """Split the selected run at the corner nearest `at` (page point), or
    its middle corner: two runs, same item. Returns 2 or 0."""
    m = selected_measure(v)
    if not m or not m["run"]:
        return 0
    pts = [fitz.Point(q) for q in m["annot"].vertices or []]
    if len(pts) < 3:
        return 0
    inner = list(range(1, len(pts) - 1))
    if at is not None:
        k = min(inner, key=lambda i: abs(pts[i] - at))
    else:
        k = inner[len(inner) // 2]
    a = _rebuild(v, m, pts[:k + 1])
    b = _rebuild(v, m, pts[k:])
    if not a or not b:
        return 0
    target = {"target": m["tag"]} if m["tag"] else {"xref": m["annot"].xref}
    n = v.apply_marks([(v.page, "delete_annot", target),
                       (v.page, a[0], a[1]), (v.page, b[0], b[1])])
    v.select(None)
    return 2 if n else 0


def join_runs(v):
    """Join the selected runs of one item whose ends meet into one run.
    Returns 1 or 0."""
    targets = bulk_targets(v)
    runs = [(t, m) for t, m in targets if m["run"]]
    if len(runs) < 2 or len({m["group"] for _t, m in runs}) != 1:
        return 0
    chains = [[fitz.Point(q) for q in m["annot"].vertices or []]
              for _t, m in runs]
    path = chains.pop(0)
    while chains:
        hit = None
        for i, c in enumerate(chains):
            for rev_path in (False, True):
                p = list(reversed(path)) if rev_path else path
                for rev_c in (False, True):
                    q = list(reversed(c)) if rev_c else c
                    if abs(p[-1] - q[0]) <= JOIN_TOL:
                        hit = (i, p + q[1:])
                        break
                if hit:
                    break
            if hit:
                break
        if hit is None:
            return 0                       # the ends don't meet
        chains.pop(hit[0])
        path = hit[1]
    got = _rebuild(v, runs[0][1], path)
    if not got:
        return 0
    marks = [(v.page, "delete_annot", t) for t, _m in runs]
    marks.append((v.page, got[0], got[1]))
    n = v.apply_marks(marks)
    v.select(None)
    return 1 if n else 0
