"""Auto Walls & Doors: take off a floor plan's walls and doors from its
linework in one click (what Beam AI and Togal sell as AI takeoff, done
here exactly, from the CAD vectors).

Walls
  A wall is drawn as two parallel lines a wall's thickness apart (3" to
  16" at the sheet's scale). Lines are grouped by direction and sorted by
  their offset, so each line only meets the lines near it. A pair that
  runs side by side for at least 1'-6" is a piece of wall; its centerline
  is measured. Pieces that line up (the stud and finish lines of the same
  wall) are merged. Hatching is rejected: a hatch line has four or more
  parallel neighbours within a wall's thickness, a wall face at most two
  or three (its own layers). A line paired both ways (a counter edge
  beside a wall's face) is dropped when its "wall" has a thickness the
  sheet has nowhere else. Walls are grouped by thickness ("Wall 5in",
  "Wall 8in"), so each type gets its own total.

Thickness classes
  Every wall's face-to-face thickness is kept ("measured"); walls are
  grouped where the thicknesses bunch up (length weighted), each group's
  median is snapped to a standard assembly (3-5/8" stud + 5/8" GB ea side
  = 4-7/8", 8" CMU = 7-5/8" ...) - thickness_classes() - so two sheets of
  one building give the same classes.

Wall types
  wall_types() reads the wall-type tags (a code in a hexagon / diamond /
  circle) and the wall-type legend and gives LF per type, which is what
  an estimator prices; untagged walls take their class's type only when
  that is unambiguous, and say so.

Doors
  A door is drawn as a swing: a quarter-circle arc (one or more Bezier
  curves) of the door's width. Arcs with a 2'-0" to 4'-0" radius sweeping
  about 90 degrees are counted at the hinge, grouped by width
  ("Door 3'-0\"").

Works best on vector PDFs (exported from CAD/Revit). On a scan the walls
are found in the picture instead (raster_segments): solid wall shapes
are traced and their outlines paired the same way.
"""
import math
import re

import fitz

MIN_T_IN, MAX_T_IN = 3.0, 16.0          # wall thickness range, inches
MIN_RUN_FT = 1.5                        # side-by-side run to be a wall
MIN_SEG_FT = 1.0                        # shorter lines are ignored
ANGLE_TOL = math.radians(1.0)


class AutoWallsError(Exception):
    pass


# ------------------------------------------------------------- segments
def segments(page, min_len=0.0):
    """Straight segments of the page's linework: [(x0, y0, x1, y1)]."""
    out = []
    try:
        paths = page.get_drawings()
    except Exception:
        return out

    def add(a, b):
        if math.hypot(b.x - a.x, b.y - a.y) >= min_len:
            out.append((a.x, a.y, b.x, b.y))
    for p in paths:
        for it in p.get("items", ()):
            k = it[0]
            if k == "l":
                add(it[1], it[2])
            elif k == "re":
                r = fitz.Rect(it[1])
                q = [r.tl, r.tr, r.br, r.bl]
                for i in range(4):
                    add(q[i], q[(i + 1) % 4])
            elif k == "qu":
                q = it[1]
                pts = [q.ul, q.ur, q.lr, q.ll]
                for i in range(4):
                    add(pts[i], pts[(i + 1) % 4])
    return out


def _frame(seg):
    """(angle in [0, pi), offset, t0, t1): the segment in the frame of its
    own direction - offset across it, t0..t1 along it."""
    x0, y0, x1, y1 = seg
    a = math.atan2(y1 - y0, x1 - x0) % math.pi
    if a > math.pi - ANGLE_TOL / 2:
        a -= math.pi
    ux, uy = math.cos(a), math.sin(a)
    t0, t1 = x0 * ux + y0 * uy, x1 * ux + y1 * uy
    off = -x0 * uy + y0 * ux
    if t1 < t0:
        t0, t1 = t1, t0
    return a, off, t0, t1


def _point(a, off, t):
    ux, uy = math.cos(a), math.sin(a)
    return (t * ux - off * uy, t * uy + off * ux)


# ------------------------------------------------------------- walls
RASTER_PPF = 48.0                   # pixels per foot for scans (1/4")


def raster_segments(page, ppu, unit="ft"):
    """Wall faces of a scanned plan: the page is rendered, thin lines
    (dimensions, hatching, text) are dropped so only solid walls are left
    (autotakeoff.wall_mask), and the outlines of what's left are
    straightened into segments - the two faces of each wall - in page
    points."""
    from . import autotakeoff
    if not autotakeoff.available():
        raise AutoWallsError("Reading walls from a scan needs numpy and "
                             "OpenCV.")
    import numpy as np
    per_ft = ppu / autotakeoff.FT_PER_UNIT.get(unit, 1.0)
    r = page.rect
    zoom = RASTER_PPF / per_ft
    zoom = min(zoom, math.sqrt(autotakeoff.MAX_PIXELS /
                               max(1.0, r.width * r.height)))
    ppf = zoom * per_ft
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom),
                          colorspace=fitz.csGRAY, annots=False, alpha=False)
    gray = np.frombuffer(pix.samples, np.uint8).reshape(
        pix.height, pix.stride)[:, :pix.width]
    m = page.rotation_matrix
    boxes = [(fitz.Rect(w[:4]) * m).normalize() * zoom
             for w in page.get_text("words")]
    mask = autotakeoff.wall_mask(gray, ppf, boxes)
    return mask_segments(mask, zoom, ppf)


class RasterSegs(list):
    """Segments traced from a picture; `px_in` is one pixel in inches at
    the plan's scale - thicknesses measured from them are only good to
    about that."""

    def __init__(self, segs, px_in):
        super().__init__(segs)
        self.px_in = px_in


def mask_segments(mask, zoom, ppf):
    """Outline segments (page points) of a wall mask (1 = wall)."""
    import cv2
    import numpy as np
    # trace the boundary between pixels, not through the edge pixels:
    # upsample 2x so each contour runs half a pixel outside the wall
    big = cv2.resize(mask.astype(np.uint8), None, fx=2, fy=2,
                     interpolation=cv2.INTER_NEAREST)
    big = cv2.copyMakeBorder(big, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    cnts, _ = cv2.findContours(big, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    out = []
    eps = max(1.5, 0.05 * ppf * 2)          # ~1/2" of straightening
    for c in cnts:
        if len(c) < 8:
            continue
        poly = cv2.approxPolyDP(c, eps, True).reshape(-1, 2).astype(float)
        # contour pixel centers sit inside the shape; push half a (big)
        # pixel out to the true edge
        poly = (poly - 1 + 0.5) / 2.0
        for i in range(len(poly)):
            x0, y0 = poly[i]
            x1, y1 = poly[(i + 1) % len(poly)]
            out.append((float(x0) / zoom, float(y0) / zoom,
                        float(x1) / zoom, float(y1) / zoom))
    return RasterSegs(out, 12.0 / ppf)


# A line with four or more parallel neighbours within a wall's thickness
# is hatching only when they are evenly spaced (a hatch pattern); the
# layers of a composite exterior wall (veneer, air space, insulation, CMU,
# furring, board) are not, and were wrongly thrown out as hatching.
HATCH_EVEN_ONLY = True
HATCH_GAP_TOL = 0.15


def _evenly_spaced(partners):
    """True when this line and its neighbours (partners: (j, d, ...)) form
    at least four lines at one spacing (three equal gaps in a row)."""
    offs = sorted({0.0} | {round(p[1], 3) for p in partners})
    gaps = [b - a for a, b in zip(offs, offs[1:]) if b - a > 1e-6]
    run = 1
    for g0, g1 in zip(gaps, gaps[1:]):
        if abs(g1 - g0) <= HATCH_GAP_TOL * max(g0, g1):
            run += 1
            if run >= 3:
                return True
        else:
            run = 1
    return False


def walls(page, ppu, unit="ft", min_t=MIN_T_IN, max_t=None,
          segs=None, info=None, resolution_in=None):
    """[{p0, p1, thickness (inches), length (unit)}] for the walls drawn on
    `page` at `ppu` points per `unit`. `segs` overrides the page's
    linework (raster_segments for a scan).

    Each wall also has "measured" (its own face-to-face thickness),
    "class_median", "nominal_in", "assembly", "snapped" and "class_label"
    (see _cluster); "thickness" is its class's size. `resolution_in`:
    how finely thickness is measured (inches); segments from
    raster_segments carry their pixel size, and classes are then grouped
    at no less than RASTER_JOIN_IN. `info` (a dict) gets
    "classes" (thickness_classes) and "dropped" (phantom walls left out)."""
    per_ft = ppu * {"ft": 1.0, "in": 12.0, "m": 0.3048,
                    "yd": 1 / 3.0}.get(unit, 1.0)
    if per_ft <= 0:
        raise AutoWallsError("Set the scale for this page first.")
    if max_t is None:
        max_t = MAX_T_IN
    lo, hi = min_t / 12 * per_ft, max_t / 12 * per_ft
    if resolution_in is None:            # before segs is filtered below
        resolution_in = getattr(segs, "px_in", None)
    if segs is None:
        segs = segments(page, MIN_SEG_FT * per_ft)
    else:
        segs = [q for q in segs if math.hypot(q[2] - q[0], q[3] - q[1])
                >= MIN_SEG_FT * per_ft]
    if not segs:
        raise AutoWallsError("This page has no drawn lines to read (a scan "
                             "or an image). Run OCR / use Auto Area "
                             "instead.")
    fr = sorted((_frame(s) for s in segs), key=lambda f: f[0])
    # group by direction (angles within the tolerance)
    groups, cur = [], []
    for f in fr:
        if cur and f[0] - cur[-1][0] > ANGLE_TOL:
            groups.append(cur)
            cur = []
        cur.append(f)
    if cur:
        groups.append(cur)
    if len(groups) > 1 and groups[0][0][0] + math.pi - groups[-1][-1][0] \
            <= ANGLE_TOL:
        groups[0] = groups[-1] + groups[0]       # 0 and 180 deg are one
        groups.pop()
    min_run = MIN_RUN_FT * per_ft
    pieces = []
    for g in groups:
        a = sum(f[0] for f in g) / len(g)
        lines = sorted(((f[1], f[2], f[3]) for f in g))
        # merge duplicates (the same line drawn twice, or split pieces)
        # lines a hair apart (CAD float noise) are one line: cluster by
        # offset first, then join pieces along it only where they touch -
        # sorting by offset alone let a piece that sorts late reach back
        # across a gap to an earlier one
        merged = []
        clus = []
        for ln in lines:
            if clus and ln[0] - clus[-1][-1][0] >= 0.25:
                clus.append([])
            if not clus:
                clus.append([])
            clus[-1].append(ln)
        for cl in clus:
            off = cl[0][0]
            for _o, t0, t1 in sorted(cl, key=lambda q: q[1]):
                m = merged[-1] if merged and merged[-1][3] is cl else None
                if m and t0 <= m[2] + 0.5:
                    m[2] = max(m[2], t1)
                else:
                    merged.append([off, t0, t1, cl])
        merged = [m[:3] for m in merged]
        n = len(merged)
        # partners: lines lo..hi across, overlapping along the run
        partners = [[] for _ in range(n)]
        j0 = 0
        for i in range(n):
            oi, ai, bi = merged[i]
            while j0 < n and merged[j0][0] < oi - hi:
                j0 += 1
            j = j0
            while j < n and merged[j][0] <= oi + hi:
                if j != i:
                    oj, aj, bj = merged[j]
                    d = oj - oi
                    ov = min(bi, bj) - max(ai, aj)
                    if lo <= abs(d) and ov >= min_run:
                        partners[i].append((j, d, max(ai, aj), min(bi, bj)))
                j += 1
        # hatching: evenly spaced lines - neighbours at the same spacing on
        # both sides, or four or more within a wall's thickness. A wall face
        # has its other face on one side only (layered walls: very
        # different distances).
        hatch = [False] * n
        for i in range(n):
            if len(partners[i]) >= 4 and (not HATCH_EVEN_ONLY or
                                          _evenly_spaced(partners[i])):
                hatch[i] = True
                continue
            ab = [p[1] for p in partners[i] if p[1] > 0]
            be = [-p[1] for p in partners[i] if p[1] < 0]
            if ab and be:
                da, db = min(ab), min(be)
                if abs(da - db) <= 0.15 * max(da, db):
                    hatch[i] = True
        for i in range(n):
            above = [p for p in partners[i] if p[1] > 0 and not hatch[p[0]]]
            if hatch[i]:
                continue
            if not above:
                continue
            # pair with the farthest face within a wall's thickness (the
            # finish face across) wherever it runs alongside, so layered
            # walls get their full width; a face split by a tee pairs with
            # each part
            oi = merged[i][0]
            for j, d, t0, t1 in above:
                if hatch[j]:
                    continue
                if any(q[1] > d + 0.25 * per_ft / 12 and
                       min(q[3], t1) - max(q[2], t0) >= (t1 - t0) * 0.5
                       for q in above):
                    continue               # a farther face covers this run
                pieces.append((a, oi + d / 2, t0, t1, oi, oi + d))
    # merge pieces of the same wall (stud lines inside finish lines)
    pieces.sort(key=lambda p: (round(p[0], 2), p[1], p[2]))
    walls_out = []
    for a, off, t0, t1, f0, f1 in pieces:
        hit = None
        for w in walls_out[-40:]:
            if abs(w["a"] - a) <= ANGLE_TOL and f0 < w["f1"] - 0.25 and \
                    f1 > w["f0"] + 0.25 and \
                    t0 <= w["t1"] + 0.5 and t1 >= w["t0"] - 0.5:
                hit = w
                break
        if hit:
            hit["t0"], hit["t1"] = min(hit["t0"], t0), max(hit["t1"], t1)
            hit["f0"], hit["f1"] = min(hit["f0"], f0), max(hit["f1"], f1)
        else:
            walls_out.append({"a": a, "t0": t0, "t1": t1, "f0": f0,
                              "f1": f1})
    for w in walls_out:
        w["off"] = (w["f0"] + w["f1"]) / 2
        w["th"] = w["f1"] - w["f0"]
    dropped = _drop_shared_face(walls_out, per_ft)
    _join_corners(walls_out)
    out = []
    for w in walls_out:
        p0 = _point(w["a"], w["off"], w["t0"])
        p1 = _point(w["a"], w["off"], w["t1"])
        out.append({"p0": p0, "p1": p1,
                    "thickness": w["th"] / per_ft * 12,
                    "length": (w["t1"] - w["t0"]) / ppu})
    if resolution_in is None:
        resolution_in = getattr(segs, "px_in", None)
    _cluster(out, resolution_in)
    out.sort(key=lambda w: -w["length"])
    if info is not None:
        info["dropped"] = [{"p0": _point(w["a"], w["off"], w["t0"]),
                            "p1": _point(w["a"], w["off"], w["t1"]),
                            "thickness": w["th"] / per_ft * 12,
                            "length": (w["t1"] - w["t0"]) / ppu,
                            "why": w["why"]} for w in dropped]
        info["classes"] = thickness_classes(out)
    return out


# ------------------------------------------------------------- thickness
# Standard wall assemblies by overall thickness (inches), for naming the
# thickness classes. Drafted CAD walls measure exactly; the classes snap
# to these when within SNAP_IN.
NOMINALS = (
    (3.5, '2-1/2" stud + 1/2" GB ea side'),
    (3.625, '4" CMU (3-5/8")'),
    (3.75, '2-1/2" stud + 5/8" GB ea side'),
    (4.0, '4" CMU (drawn nominal)'),
    (4.25, '3-5/8" stud + 5/8" GB one side'),
    (4.5, '2x4 wood stud + 1/2" GB ea side'),
    (4.625, '3-5/8" stud + 1/2" GB ea side'),
    (4.75, '2x4 wood stud + 5/8" GB ea side'),
    (4.875, '3-5/8" stud + 5/8" GB ea side'),
    (5.625, '6" CMU (5-5/8")'),
    (6.0, '6" CMU (drawn nominal)'),
    (6.125, '3-5/8" stud + 2 layers 5/8" GB ea side'),
    (6.5, '2x6 wood stud + 1/2" GB ea side'),
    (6.625, '6" stud + 5/8" GB one side'),
    (6.75, '2x6 wood stud + 5/8" GB ea side'),
    (7.0, '6" stud + 1/2" GB ea side'),
    (7.25, '6" stud + 5/8" GB ea side'),
    (7.625, '8" CMU (7-5/8")'),
    (8.0, '8" CMU (drawn nominal)'),
    (8.5, '6" stud + 2 layers 5/8" GB ea side'),
    (9.625, '10" CMU (9-5/8")'),
    (10.0, '10" CMU (drawn nominal)'),
    (11.625, '12" CMU (11-5/8")'),
    (12.0, '12" CMU (drawn nominal)'),
)
SNAP_IN = 0.25            # a class this close to a standard size takes it
CLASS_BW_IN = 0.08        # thickness peaks: kernel width (inches)
CLASS_JOIN_IN = 0.3       # a wall this close to a peak is in its class
RASTER_JOIN_IN = 1.25     # the same for walls traced from a scan
WEAK_LF, WEAK_SHARE = 10.0, 0.05   # less LF than this: an unconfirmed class


def fraction_in(x, den=16):
    """4.875 -> '4-7/8"', 8.0 -> '8"', 0.625 -> '5/8"'."""
    n = int(round(x * den))
    whole, rest = divmod(n, den)
    if not rest:
        return f'{whole}"'
    g = math.gcd(rest, den)
    frac = f"{rest // g}/{den // g}"
    return f'{whole}-{frac}"' if whole else f'{frac}"'


def snap_thickness(t_in, tol=SNAP_IN):
    """(nominal inches, assembly, snapped) for a measured wall thickness:
    the nearest standard assembly when within `tol` (4.95 -> 4.875, '3-5/8"
    stud + 5/8" GB ea side', True), else the measurement to the nearest
    1/8" with no assembly (13.1 -> 13.125, '', False)."""
    best = min(NOMINALS, key=lambda nv: abs(nv[0] - t_in))
    if abs(best[0] - t_in) <= tol:
        return best[0], best[1], True
    return round(t_in * 8) / 8, "", False


def _weighted_median(vals, wts):
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    tot = sum(wts) or 1.0
    acc = 0.0
    for i in order:
        acc += wts[i]
        if acc >= tot / 2:
            return vals[i]
    return vals[order[-1]] if order else 0.0


def _class_peaks(vals, wts):
    """Thicknesses where walls bunch up (length-weighted kernel density
    peaks), heaviest first."""
    if not vals:
        return []
    lo, hi = min(vals) - 1.0, max(vals) + 1.0
    step = 1 / 64
    n = int((hi - lo) / step) + 1
    grid = [lo + k * step for k in range(n)]
    try:
        import numpy as np
        g = np.array(grid)
        v = np.array(vals)[:, None]
        w = np.array(wts)[:, None]
        dens = (w * np.exp(-((g[None, :] - v) ** 2) /
                           (2 * CLASS_BW_IN ** 2))).sum(axis=0).tolist()
    except ImportError:                       # pragma: no cover
        dens = [sum(wt * math.exp(-((x - t) ** 2) / (2 * CLASS_BW_IN ** 2))
                    for t, wt in zip(vals, wts)) for x in grid]
    peaks = [(dens[k], grid[k]) for k in range(1, n - 1)
             if dens[k] >= dens[k - 1] and dens[k] > dens[k + 1]]
    peaks.sort(reverse=True)
    return [x for _d, x in peaks]


def _cluster(ws, resolution_in=None):
    """Walls of one type measure a little differently (a scan's pixels,
    drafting slop, a face picked up a hair off): every wall's measured
    thickness is kept ("measured"), the walls are grouped around the
    thicknesses they bunch up at (length weighted, within CLASS_JOIN_IN),
    each group takes its weighted median and is snapped to a standard
    assembly (snap_thickness). Groups that snap to the same size are one
    class. Sets on each wall "measured", "thickness" (the class size),
    "class_median", "nominal_in", "assembly", "snapped", "class_label"."""
    if not ws:
        return
    for w in ws:
        w.setdefault("measured", w["thickness"])
    vals = [w["measured"] for w in ws]
    wts = [max(w["length"], 1e-6) for w in ws]
    peaks = _class_peaks(vals, wts)
    join = CLASS_JOIN_IN
    snap_tol = SNAP_IN
    if resolution_in:
        # traced from a picture: each face lands a pixel either way, so
        # one wall type measures over two pixels - group at that (no
        # tighter than RASTER_JOIN_IN), heaviest thickness first, and
        # snap as loosely
        join = max(RASTER_JOIN_IN, 2 * resolution_in)
        snap_tol = max(SNAP_IN, resolution_in)
        kept = []
        for p in peaks:                          # heaviest first
            if all(abs(p - q) >= join for q in kept):
                kept.append(p)
        peaks = kept
    groups = {}
    for k, w in enumerate(ws):
        near = [p for p in peaks if abs(p - vals[k]) <= join]
        key = min(near, key=lambda p: abs(p - vals[k])) if near \
            else round(vals[k] * 16) / 16
        groups.setdefault(key, []).append(k)
    by_nominal = {}
    for key, idx in groups.items():
        med = _weighted_median([vals[k] for k in idx], [wts[k] for k in idx])
        nom, asm, snapped = snap_thickness(med, snap_tol)
        by_nominal.setdefault(nom, []).extend(
            (k, asm, snapped) for k in idx)
    for nom, rows in by_nominal.items():
        idx = [k for k, _a, _s in rows]
        med = _weighted_median([vals[k] for k in idx], [wts[k] for k in idx])
        asm = next((a for _k, a, _s in rows if a), "")
        snapped = any(s for _k, _a, s in rows)
        label = f"Wall {fraction_in(nom)}" + (f" ({asm})" if asm else "")
        for k in idx:
            w = ws[k]
            w["class_median"] = med
            w["nominal_in"] = nom
            w["assembly"] = asm
            w["snapped"] = snapped
            w["class_label"] = label
            w["thickness"] = nom if snapped else med


def thickness_classes(ws):
    """The wall thickness classes of walls() output: [{"label",
    "nominal_in", "median_in" (measured, length-weighted), "spread_in"
    (middle half of the measurements), "assembly", "snapped", "lf",
    "count", "confident", "flags"}], most LF first. A class with little LF
    (under WEAK_LF ft or WEAK_SHARE of all) or that matches no standard
    assembly is not confident and says why."""
    rows = {}
    for w in ws:
        if "nominal_in" not in w:
            _cluster(ws)
            break
    for w in ws:
        rows.setdefault(w["nominal_in"], []).append(w)
    total = sum(w["length"] for w in ws) or 1.0
    out = []
    for nom, mem in rows.items():
        vals = sorted(w["measured"] for w in mem)
        lf = sum(w["length"] for w in mem)
        med = _weighted_median([w["measured"] for w in mem],
                               [max(w["length"], 1e-6) for w in mem])
        q1 = vals[len(vals) // 4]
        q3 = vals[(3 * len(vals)) // 4] if len(vals) > 1 else vals[0]
        flags = []
        if not mem[0]["snapped"]:
            flags.append("matches no standard assembly - check the wall "
                         "types")
        if lf < WEAK_LF or lf < WEAK_SHARE * total:
            flags.append(f"only {lf:,.0f} LF at this thickness - may be "
                         "casework or furniture lines, not a wall")
        if q3 - q1 > 0.25:
            flags.append(f"measurements spread {fraction_in(q1)} to "
                         f"{fraction_in(q3)}")
        out.append({"label": mem[0]["class_label"], "nominal_in": nom,
                    "median_in": round(med, 4),
                    "spread_in": round(q3 - q1, 4),
                    "assembly": mem[0]["assembly"],
                    "snapped": mem[0]["snapped"], "lf": lf,
                    "count": len(mem), "confident": not flags,
                    "flags": flags})
    out.sort(key=lambda c: -c["lf"])
    return out


def _drop_shared_face(walls_out, per_ft):
    """A line paired both ways - one face of a wall, and again with a
    parallel line on its other side (a counter edge or casework 11" off an
    exterior wall's inside face) - makes a second "wall" that shares the
    real wall's face. Where two pairs share a face along the same run,
    the one with less run (the phantom) is dropped when its thickness is
    not one the sheet has elsewhere. Returns the dropped walls (removed
    from `walls_out`), each with "why"."""
    if len(walls_out) < 2:
        return []
    q = 0.5                                       # points
    faces = {}
    for k, w in enumerate(walls_out):
        for side in ("f0", "f1"):
            faces.setdefault((round(w["a"], 2), round(w[side] / q)),
                             []).append((k, side))

    def th_in(w):
        return w["th"] / per_ft * 12
    # how much wall the sheet has at each thickness (to the nearest 1/4")
    lf = {}
    for w in walls_out:
        key = round(th_in(w) * 4)
        lf[key] = lf.get(key, 0.0) + (w["t1"] - w["t0"]) / per_ft
    total = sum(lf.values()) or 1.0

    def common(w):
        key = round(th_in(w) * 4)
        got = sum(lf.get(key + d, 0.0) for d in (-1, 0, 1))
        return got - (w["t1"] - w["t0"]) / per_ft >= max(WEAK_LF,
                                                         WEAK_SHARE * total)
    drop = set()
    for k, w in enumerate(walls_out):
        if k in drop:
            continue
        for side, other in (("f1", "f0"), ("f0", "f1")):
            key = (round(w["a"], 2), round(w[side] / q))
            for dk in (-1, 0, 1):
                for j, s2 in faces.get((key[0], key[1] + dk), ()):
                    if j == k or j in drop or s2 != other:
                        continue
                    o = walls_out[j]
                    if abs(o[other] - w[side]) > q:
                        continue
                    ov = min(w["t1"], o["t1"]) - max(w["t0"], o["t0"])
                    rw, ro = w["t1"] - w["t0"], o["t1"] - o["t0"]
                    if ov < 0.5 * min(rw, ro):
                        continue
                    short = j if ro <= rw else k
                    if not common(walls_out[short]):
                        drop.add(short)
    out = []
    for k in sorted(drop, reverse=True):
        w = walls_out.pop(k)
        w["why"] = ("shares a face with a longer wall and its thickness "
                    "is found nowhere else - a counter or casework line")
        out.append(w)
    return out


def _join_corners(ws):
    """Run each wall's centerline on to where it meets the centerline of
    a wall it butts into (corners and tees), as takeoff convention has it:
    face-to-face pieces would be short by half a wall at every end."""
    ends = []
    for w in ws:
        ends.append((w, "t0"))
        ends.append((w, "t1"))
    # walls bucketed on a grid by their extent (plus the farthest an end
    # can reach to meet them), so each end only looks at the walls near
    # it - not at every wall on the sheet (quadratic on dense plans)
    if not ws:
        return
    # an end meets a wall within 0.75 x both thicknesses of its line, and
    # walls get longer as their ends are joined: pad by 3 thicknesses
    reach_max = 3.0 * max(w["th"] for w in ws) + 1.0
    G = max(24.0, 2 * reach_max)
    grid = {}
    for k, o in enumerate(ws):
        p0 = _point(o["a"], o["off"], o["t0"] - o["th"])
        p1 = _point(o["a"], o["off"], o["t1"] + o["th"])
        x0, x1 = sorted((p0[0], p1[0]))
        y0, y1 = sorted((p0[1], p1[1]))
        for gx in range(int((x0 - reach_max) // G),
                        int((x1 + reach_max) // G) + 1):
            for gy in range(int((y0 - reach_max) // G),
                            int((y1 + reach_max) // G) + 1):
                grid.setdefault((gx, gy), []).append(k)
    for w, key in ends:
        a, off = w["a"], w["off"]
        ux, uy = math.cos(a), math.sin(a)
        ex, ey = _point(a, off, w[key])
        best = None
        near = sorted(set(grid.get((int(ex // G), int(ey // G)), ())))
        for o in (ws[k] for k in near):
            if o is w or abs(math.sin(o["a"] - a)) < 0.5:
                continue                 # parallel-ish: not a corner
            vx, vy = math.cos(o["a"]), math.sin(o["a"])
            # intersection of the two centerlines
            den = ux * vy - uy * vx
            ox_, oy_ = _point(o["a"], o["off"], o["t0"])
            t = ((ox_ - ex) * vy - (oy_ - ey) * vx) / den
            ix, iy = ex + t * ux, ey + t * uy
            reach = (o["th"] + w["th"]) * 0.75
            if abs(t) > reach:
                continue
            to = ix * vx + iy * vy           # along the other wall
            if not (o["t0"] - o["th"] <= to <= o["t1"] + o["th"]):
                continue
            if best is None or abs(t) < abs(best):
                best = t
        if best is not None:
            nt = w[key] + best
            if key == "t0" and nt < w["t1"]:
                w["t0"] = nt
            elif key == "t1" and nt > w["t0"]:
                w["t1"] = nt


def wall_type(thickness_in):
    """Nominal label: 4.875" -> 'Wall 5in'."""
    return f"Wall {max(1, round(thickness_in))}in"


# ------------------------------------------------------------- doors
def _circle(p, q, r):
    """Circle through three points: (cx, cy, radius) or None."""
    ax, ay = p
    bx, by = q
    cx, cy = r
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-9:
        return None
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) +
          (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) +
          (cx * cx + cy * cy) * (bx - ax)) / d
    return ux, uy, math.hypot(ax - ux, ay - uy)


def _bez(p0, p1, p2, p3, t):
    m = 1 - t
    return (m ** 3 * p0[0] + 3 * m * m * t * p1[0] + 3 * m * t * t * p2[0] +
            t ** 3 * p3[0],
            m ** 3 * p0[1] + 3 * m * m * t * p1[1] + 3 * m * t * t * p2[1] +
            t ** 3 * p3[1])


def _ang_mean(angles, weights=None):
    weights = weights or [1.0] * len(angles)
    x = sum(w * math.cos(a) for a, w in zip(angles, weights))
    y = sum(w * math.sin(a) for a, w in zip(angles, weights))
    return math.atan2(y, x)


NARROW_FT = 2.5          # under 2'-6": toilet partition / shower doors


def doors(page, ppu, unit="ft", min_w_ft=2.0, max_w_ft=4.0,
          include_narrow=False):
    """[{hinge (x, y), width (ft), sweep (deg), leaves}] for the door
    swings. A swing drawn twice counts once and a pair of leaves meeting
    in the middle is one door ("leaves": 2, width = both) - PM review
    NW-17: A-102 found 43 against the schedule's 31. Single swings under
    NARROW_FT (toilet partition and shower doors, not in a door schedule)
    are left out, or with include_narrow kept and marked "narrow": True
    for review."""
    per_ft = ppu * {"ft": 1.0, "in": 12.0, "m": 0.3048,
                    "yd": 1 / 3.0}.get(unit, 1.0)
    arcs = []                        # [cx, cy, r, sweep, mid angle]
    try:
        paths = page.get_drawings()
    except Exception:
        paths = []
    for p in paths:
        for it in p.get("items", ()):
            if it[0] != "c":
                continue
            pts = [(q.x, q.y) for q in it[1:5]]
            chord = math.hypot(pts[3][0] - pts[0][0], pts[3][1] - pts[0][1])
            if chord < min_w_ft * per_ft * 0.3 or \
                    chord > max_w_ft * per_ft * 1.6:
                continue                 # quick reject before any maths
            mid = _bez(*pts, 0.5)
            c = _circle(pts[0], mid, pts[3])
            if c is None:
                continue
            cx, cy, r = c
            if not (min_w_ft * 0.9 <= r / per_ft <= max_w_ft * 1.1):
                continue             # not door-sized (cloud scallops etc.)
            # really circular? check the quarter points too
            ok = all(abs(math.hypot(x - cx, y - cy) - r) < r * 0.03
                     for x, y in (_bez(*pts, 0.25), _bez(*pts, 0.75)))
            if not ok:
                continue
            a0 = math.atan2(pts[0][1] - cy, pts[0][0] - cx)
            a1 = math.atan2(pts[3][1] - cy, pts[3][0] - cx)
            sweep = abs((a1 - a0 + math.pi) % (2 * math.pi) - math.pi)
            arcs.append([cx, cy, r, sweep,
                         math.atan2(mid[1] - cy, mid[0] - cx)])
        # Revit and many CAD exports draw a swing as a run of short straight
        # lines, not a curve (Aiken A-101/A-102: no door found at all)
        try:
            from .autotakeoff import _arc_fit, _bends, _line_chains
            for chain in _line_chains(p.get("items", ())):
                for run in _bends(chain):
                    got = _arc_fit(run, min_w_ft * 0.9 * per_ft,
                                   max_w_ft * 1.1 * per_ft)
                    if got:
                        ctr, r, ends, sweep = got
                        m = _ang_mean([math.atan2(e.y - ctr.y, e.x - ctr.x)
                                       for e in ends])
                        arcs.append([ctr.x, ctr.y, r, sweep, m])
        except ImportError:                     # pragma: no cover
            pass
    # join the curves of one arc (same center and radius); two quarter
    # arcs on one centre make a half circle, which is no door swing
    joined = []
    for cx, cy, r, sw, ma in arcs:
        for j in joined:
            if math.hypot(j[0] - cx, j[1] - cy) < r * 0.1 and \
                    abs(j[2] - r) < r * 0.05:
                off = abs((ma - j[4] + math.pi) % (2 * math.pi) - math.pi)
                if off < min(sw, j[3]) / 2:
                    break                # the same curve drawn again
                j[4] = _ang_mean([j[4], ma], [j[3], sw])
                j[3] += sw
                break
        else:
            joined.append([cx, cy, r, sw, ma])
    segs = _segments(paths)
    found = []
    for cx, cy, r, sw, ma in joined:
        w = r / per_ft
        deg = math.degrees(sw)
        # a door swing has its leaf: a straight line from the hinge out to
        # about the arc (toilet bowls and fixtures are arcs too - NW-17)
        if min_w_ft <= w <= max_w_ft and 75 <= deg <= 105 and \
                _has_leaf(segs, cx, cy, r):
            found.append({"hinge": (cx, cy), "width": w, "sweep": deg,
                          "leaves": 1,
                          "_mid": (cx + r * math.cos(ma),
                                   cy + r * math.sin(ma))})
    out = _merge_swings(found, per_ft)
    for d in out:
        d["narrow"] = d["leaves"] == 1 and d["width"] < NARROW_FT
    return out if include_narrow else [d for d in out if not d["narrow"]]


def _segments(paths):
    """Every straight piece on the page as (x0, y0, x1, y1)."""
    out = []
    for p in paths:
        for it in p.get("items", ()):
            if it[0] == "l":
                out.append((it[1].x, it[1].y, it[2].x, it[2].y))
            elif it[0] == "re":
                r = it[1]
                c = [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)]
                out += [c[i] + c[(i + 1) % 4] for i in range(4)]
            elif it[0] == "qu":
                q = it[1]
                c = [(q.ul.x, q.ul.y), (q.ur.x, q.ur.y), (q.lr.x, q.lr.y),
                     (q.ll.x, q.ll.y)]
                out += [c[i] + c[(i + 1) % 4] for i in range(4)]
    return out


def _has_leaf(segs, cx, cy, r):
    near, lo, hi = 0.2 * r, 0.6 * r, 1.15 * r
    for x0, y0, x1, y1 in segs:
        for (ax, ay), (bx, by) in (((x0, y0), (x1, y1)),
                                   ((x1, y1), (x0, y0))):
            if abs(ax - cx) > near or abs(ay - cy) > near:
                continue
            if math.hypot(ax - cx, ay - cy) <= near and \
                    lo <= math.hypot(bx - cx, by - cy) <= hi:
                return True
    return False


def _merge_swings(found, per_ft):
    """One door per opening: the same swing drawn twice (hinges and arc
    midpoints both close) is kept once; two like leaves whose hinges are
    two leaf widths apart and whose arcs meet are one pair."""
    def dist(a, b):
        return math.hypot(a[0] - b[0], a[1] - b[1]) / per_ft
    keep = []
    for d in found:
        if any(abs(d["width"] - k["width"]) < 0.25 and
               dist(d["hinge"], k["hinge"]) < 0.6 * d["width"] and
               dist(d["_mid"], k["_mid"]) < 0.6 * d["width"] for k in keep):
            continue
        keep.append(d)
    out, used = [], set()
    for i, d in enumerate(keep):
        if i in used:
            continue
        for j in range(i + 1, len(keep)):
            e = keep[j]
            if j in used or abs(d["width"] - e["width"]) >= 0.25:
                continue
            h = dist(d["hinge"], e["hinge"])
            span = d["width"] + e["width"]
            if 0.85 * span <= h <= 1.15 * span and \
                    dist(d["_mid"], e["_mid"]) < 0.6 * h:
                used.add(j)
                d = dict(d, width=span, leaves=2,
                         hinge=((d["hinge"][0] + e["hinge"][0]) / 2,
                                (d["hinge"][1] + e["hinge"][1]) / 2))
                break
        d = dict(d)
        d.pop("_mid", None)
        out.append(d)
    return out


def door_type(width_ft):
    """3.02 ft -> "Door 3'-0\"" (to the nearest 2 inches)."""
    inches = int(round(width_ft * 12 / 2) * 2)
    return f"Door {inches // 12}'-{inches % 12}\""


# ------------------------------------------------------------- marks
WALL_COLORS = [(0.85, 0.2, 0.2), (0.15, 0.45, 0.85), (0.1, 0.6, 0.3),
               (0.8, 0.45, 0.0), (0.55, 0.25, 0.75), (0.0, 0.55, 0.6)]


def marks(page_no, ws, ds, scale):
    """Viewer marks [(page, kind, payload)] for walls and doors."""
    unit = scale.get("unit", "ft")
    types = sorted({wall_type(w["thickness"]) for w in ws})
    color = {t: WALL_COLORS[i % len(WALL_COLORS)]
             for i, t in enumerate(types)}
    out = []
    for w in ws:
        t = wall_type(w["thickness"])
        out.append((page_no, "add_line", {
            "pts": [list(w["p0"]), list(w["p1"])],
            "color": list(color[t]), "width": 3, "opacity": 0.55,
            "measure": {"type": "length", "value": round(w["length"], 4),
                        "unit": unit, "group": t}}))
    for i, d in enumerate(ds):
        t = door_type(d["width"])
        out.append((page_no, "add_count", {
            "pt": list(d["hinge"]), "n": i + 1, "color": [0.9, 0.5, 0.0],
            "measure": {"type": "count", "value": 1, "unit": "ea",
                        "group": t}}))
    return out


def summary(ws, ds):
    """{"walls": {type: length}, "doors": {type: count}}"""
    wt, dt = {}, {}
    for w in ws:
        t = wall_type(w["thickness"])
        wt[t] = wt.get(t, 0) + w["length"]
    for d in ds:
        t = door_type(d["width"])
        dt[t] = dt.get(t, 0) + 1
    return {"walls": wt, "doors": dt}


# ------------------------------------------------------------- wall types
# Wall-type tags: a short code ("1A", "W3", "6") in a small hexagon,
# diamond or circle set on or beside a wall, keyed to the wall-type legend
# ("WALL TYPES" / "PARTITION TYPES"). LF per wall type is what an
# estimator prices from, not LF per thickness.
TAG_MIN_PT, TAG_MAX_PT = 7.0, 54.0       # symbol size on paper (0.1"-0.75")
TAG_REACH_FT = 2.5                       # a tag this close names a wall
RUN_GAP_FT = 8.0                         # a tagged run continues through
                                         # openings this wide
INFER_SHARE = 0.8                        # a thickness class whose tagged LF
                                         # is this much one type: the type
_CODE = re.compile(r"^(?:[A-Z]{1,3}-?\d{1,3}[A-Z]{0,2}|\d{1,2}[A-Z]{0,2}|"
                   r"[A-Z]{1,2})$")
_WALL_LEGEND = re.compile(r"\b(?:WALL|PARTITION)S?\s+(?:TYPES?|LEGEND|"
                          r"SCHEDULE|ASSEMBL(?:Y|IES))\b|\bTYPICAL\s+WALL\s+"
                          r"TYPES\b")
LEGEND_W_PT, LEGEND_H_PT = 9 * 72.0, 12 * 72.0   # a legend's extent


def _shape(p):
    """'hexagon', 'diamond', 'circle', 'rect', 'octagon' or None for a
    small closed path."""
    items = p.get("items") or ()
    kinds = {it[0] for it in items}
    if kinds == {"c"} and 2 <= len(items) <= 8:
        return "circle"
    if kinds == {"re"} and len(items) == 1:
        return "rect"
    if kinds == {"qu"} and len(items) == 1:
        q = items[0][1]
        pts = [q.ul, q.ur, q.lr, q.ll]
    elif kinds == {"l"}:
        pts = [items[0][1]] + [it[2] for it in items]
        if math.hypot(pts[0].x - pts[-1].x, pts[0].y - pts[-1].y) > 1.0 and \
                not p.get("closePath"):
            return None
        if math.hypot(pts[0].x - pts[-1].x, pts[0].y - pts[-1].y) <= 1.0:
            pts = pts[:-1]
    else:
        return None
    n = len(pts)
    if n == 6:
        return "hexagon"
    if n == 8:
        return "octagon"
    if n == 4:
        diag = all(abs(abs(b.x - a.x) - abs(b.y - a.y)) <=
                   0.35 * max(abs(b.x - a.x), abs(b.y - a.y), 1e-6)
                   for a, b in zip(pts, pts[1:] + pts[:1]))
        return "diamond" if diag else "rect"
    if n == 3:
        return "triangle"
    return None


def _lines_of(words):
    """Text lines [(rect (x0, y0, x1, y1), text)] from get_text("words")."""
    groups = {}
    for w in words:
        groups.setdefault((w[5], w[6]), []).append(w)
    out = []
    for ws in groups.values():
        ws.sort(key=lambda w: w[0])
        out.append(((min(w[0] for w in ws), min(w[1] for w in ws),
                     max(w[2] for w in ws), max(w[3] for w in ws)),
                    " ".join(str(w[4]) for w in ws)))
    return out


# the words of a graphics / symbols key entry (section, elevation, detail
# and grid markers) - a code described like this is not a wall type
_SYMBOL_KEY = re.compile(r"\b(?:SHEET\s+IDENTIFIER|DETAIL\s+LOCATION|"
                         r"DRAWING\s+LOCATION|DIRECTION\s+OF\s+(?:ELEVATION|"
                         r"SECTION)|ELEVATION\s+KEY|LOCATION\s+OF\s+"
                         r"(?:DETAIL|ELEVATION|SECTION)|GRID\s+REFERENCE|"
                         r"DETAIL\s+INDICATOR)\b")


def find_type_tags(page):
    """Wall-type tag symbols on the page: [{"code", "pt" (x, y), "r"
    (half its size), "shape"}] in unrotated page points - a small closed
    hexagon / diamond / circle / octagon / rectangle with a short code
    inside."""
    try:
        paths = page.get_drawings()
        words = page.get_text("words")
    except Exception:
        return []
    G = 36.0
    grid = {}
    for w in words:
        cx, cy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
        grid.setdefault((int(cx // G), int(cy // G)), []).append(
            (cx, cy, str(w[4]).strip()))
    out = []
    seen = set()
    for p in paths:
        r = p.get("rect")
        if r is None:
            continue
        w, h = abs(r.x1 - r.x0), abs(r.y1 - r.y0)
        if not (TAG_MIN_PT <= max(w, h) <= TAG_MAX_PT) or \
                min(w, h) < 0.5 * max(w, h):
            continue
        shape = _shape(p)
        if shape is None or shape == "triangle":
            continue
        x0, y0 = min(r.x0, r.x1), min(r.y0, r.y1)
        x1, y1 = max(r.x0, r.x1), max(r.y0, r.y1)
        inside = []
        for gx in range(int(x0 // G), int(x1 // G) + 1):
            for gy in range(int(y0 // G), int(y1 // G) + 1):
                for cx, cy, t in grid.get((gx, gy), ()):
                    if x0 < cx < x1 and y0 < cy < y1:
                        inside.append((cx, t))
        if not inside:
            continue
        code = "".join(t for _cx, t in sorted(inside)).upper().strip(".")
        if not _CODE.match(code) or (code.isdigit() and len(code) > 2):
            continue                 # 101 / 101A are door and room numbers
        key = (round((x0 + x1) / 2), round((y0 + y1) / 2), code)
        if key in seen:
            continue
        seen.add(key)
        out.append({"code": code, "pt": ((x0 + x1) / 2, (y0 + y1) / 2),
                    "r": max(w, h) / 2, "shape": shape})
    out += _stroked_tags(paths, words, out)
    return out


def _end_ids(segs, tol=0.8):
    """[(id of end a, id of end b)] per segment: ends within `tol` pt of
    each other share an id."""
    pts, ids = [], []
    for a, b in segs:
        pair = []
        for q in (a, b):
            for k, r in enumerate(pts):
                if abs(r[0] - q[0]) <= tol and abs(r[1] - q[1]) <= tol:
                    pair.append(k)
                    break
            else:
                pts.append(q)
                pair.append(len(pts) - 1)
        ids.append(tuple(pair))
    return ids


def _loop_shape(segs):
    """A closed loop of straight segments [((x0, y0), (x1, y1))] (each
    end met by exactly one other): (shape, (x0, y0, x1, y1)) or None."""
    deg = {}
    for pair in _end_ids(segs):
        for k in pair:
            deg[k] = deg.get(k, 0) + 1
    if not deg or any(v != 2 for v in deg.values()):
        return None
    n = len(deg)
    if n not in (4, 6, 8) or len(segs) != n:
        return None
    xs = [q[0] for sg in segs for q in sg]
    ys = [q[1] for sg in segs for q in sg]
    box = (min(xs), min(ys), max(xs), max(ys))
    if n == 6:
        return "hexagon", box
    if n == 8:
        return "octagon", box
    diag = all(abs(abs(b[0] - a[0]) - abs(b[1] - a[1])) <=
               0.35 * max(abs(b[0] - a[0]), abs(b[1] - a[1]), 1e-6)
               for a, b in segs)
    return ("diamond" if diag else "rect"), box


def _stroked_tags(paths, words, found):
    """Tag symbols drawn as loose strokes - a diamond of four separate
    lines - around a short code: the strokes near each code word that
    join end to end into one closed 4/6/8-sided loop around it."""
    G = 36.0
    grid = {}
    for p in paths:
        r = p.get("rect")
        items = p.get("items") or ()
        if r is None or not items or len(items) > 8 or \
                max(abs(r.x1 - r.x0), abs(r.y1 - r.y0)) > TAG_MAX_PT or \
                any(it[0] != "l" for it in items):
            continue
        for it in items:
            a, b = (it[1].x, it[1].y), (it[2].x, it[2].y)
            if math.hypot(b[0] - a[0], b[1] - a[1]) < 1.0:
                continue
            mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            grid.setdefault((int(mx // G), int(my // G)), []).append((a, b))
    if not grid:
        return []
    out = []
    taken = [(t["pt"], t["r"]) for t in found]
    for w in words:
        code = str(w[4]).strip().upper().strip(".")
        if not _CODE.match(code) or (code.isdigit() and len(code) > 2):
            continue
        cx, cy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
        if any(math.hypot(cx - q[0], cy - q[1]) <= r for q, r in taken):
            continue
        reach = TAG_MAX_PT / 2 + 2
        near = []
        for gx in range(int((cx - reach) // G), int((cx + reach) // G) + 1):
            for gy in range(int((cy - reach) // G),
                            int((cy + reach) // G) + 1):
                for a, b in grid.get((gx, gy), ()):
                    if max(abs(a[0] - cx), abs(b[0] - cx), abs(a[1] - cy),
                           abs(b[1] - cy)) <= reach:
                        near.append((a, b))
        if not 4 <= len(near) <= 24:
            continue
        # the loop: segments joined end to end with the word inside
        comps = _components(near)
        for comp in comps:
            got = _loop_shape(comp)
            if not got:
                continue
            shape, (x0, y0, x1, y1) = got
            sw, sh = x1 - x0, y1 - y0
            if not (TAG_MIN_PT <= max(sw, sh) <= TAG_MAX_PT) or \
                    min(sw, sh) < 0.5 * max(sw, sh) or \
                    not (x0 < cx < x1 and y0 < cy < y1):
                continue
            pt = ((x0 + x1) / 2, (y0 + y1) / 2)
            out.append({"code": code, "pt": pt, "r": max(sw, sh) / 2,
                        "shape": shape})
            taken.append((pt, max(sw, sh) / 2))
            break
    return out


def _components(segs):
    """Segments grouped by shared ends (within 0.8 pt)."""
    parent = list(range(len(segs)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    ends = {}
    for i, pair in enumerate(_end_ids(segs)):
        for k in pair:
            if k in ends:
                parent[find(i)] = find(ends[k])
            else:
                ends[k] = i
    groups = {}
    for i in range(len(segs)):
        groups.setdefault(find(i), []).append(segs[i])
    return list(groups.values())


def type_legend(page, tags=None):
    """The wall-type legend on this page: ({code: description}, [zones
    (x0, y0, x1, y1)]). A legend starts at a heading ("WALL TYPES",
    "PARTITION TYPES", "WALL LEGEND"); each tag symbol under it names a
    type, described by the text to its right."""
    try:
        words = page.get_text("words")
    except Exception:
        return {}, []
    lines = _lines_of(words)
    zones = []
    for (x0, y0, x1, y1), text in lines:
        if len(text.split()) <= 6 and _WALL_LEGEND.search(text.upper()):
            zones.append((x0 - 24, y0 - 4, x0 + LEGEND_W_PT,
                          y1 + LEGEND_H_PT))
    legend = {}
    if not zones:
        return legend, zones
    tags = find_type_tags(page) if tags is None else tags
    for t in tags:
        x, y = t["pt"]
        if not any(z[0] <= x <= z[2] and z[1] <= y <= z[3] for z in zones):
            continue
        r = t["r"]
        desc = []
        for (lx0, ly0, lx1, ly1), text in sorted(lines,
                                                 key=lambda ln: ln[0][0]):
            ly = (ly0 + ly1) / 2
            if lx0 >= x + r * 0.8 and lx0 <= x + 4 * 72 and \
                    abs(ly - y) <= max(r, (ly1 - ly0)) and \
                    text.strip().upper() != t["code"]:
                desc.append(text.strip())
        d = " ".join(desc).strip()
        if _SYMBOL_KEY.search(d.upper()):
            continue                # a graphics key's marker, not a type
        legend.setdefault(t["code"], d)
    return legend, zones


def _thin_lines(page):
    """Straight thin lines (leaders, dimension lines) on the page."""
    segs = []
    try:
        for p in page.get_drawings():
            if (p.get("width") or 0) > 1.0:
                continue
            for it in p.get("items", ()):
                if it[0] == "l":
                    a, b = it[1], it[2]
                    segs.append(((a.x, a.y), (b.x, b.y)))
    except Exception:                                    # noqa: BLE001
        return []
    return segs


def _leader_walls(segs, t, ws, per_ft, max_ft=20.0):
    """Walls a tag points at with leader lines: thin straight lines that
    start on the tag's outline and end at a wall (within 9" of its face).
    Returns wall indexes, nearest leader first."""
    px, py = t["pt"]
    r = t.get("r") or 6.0
    out = []
    for a, b in segs:
        da = math.hypot(a[0] - px, a[1] - py)
        db = math.hypot(b[0] - px, b[1] - py)
        near, far = (a, b) if da < db else (b, a)
        dn = min(da, db)
        L = math.hypot(far[0] - near[0], far[1] - near[1])
        if not (0.6 * r <= dn <= 1.6 * r) or L < 1.0 * per_ft or \
                L > max_ft * per_ft:
            continue
        best = None
        for k, w in enumerate(ws):
            d = _seg_dist(far[0], far[1], w["p0"], w["p1"])
            lim = 0.75 * per_ft + w["thickness"] / 24 * per_ft
            if d <= lim and (best is None or d < best[0]):
                best = (d, k)
        if best and best[1] not in out:
            out.append(best[1])
    return out


def _seg_dist(px, py, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx +
                                               (py - ay) * dy) / L2))
    return math.hypot(ax + t * dx - px, ay + t * dy - py)


def _runs(ws, per_ft):
    """Union-find over walls: walls of one class on one line, end to end
    or across an opening up to RUN_GAP_FT, are one run. [run id]."""
    n = len(ws)
    parent = list(range(n))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    geo = []
    for w in ws:
        (x0, y0), (x1, y1) = w["p0"], w["p1"]
        L = math.hypot(x1 - x0, y1 - y0) or 1e-9
        a = math.atan2(y1 - y0, x1 - x0) % math.pi
        ux, uy = math.cos(a), math.sin(a)
        off = -x0 * uy + y0 * ux
        t0, t1 = sorted((x0 * ux + y0 * uy, x1 * ux + y1 * uy))
        geo.append((a, off, t0, t1))
    gap = RUN_GAP_FT * per_ft
    order = sorted(range(n), key=lambda i: (round(geo[i][0], 2),
                                            geo[i][1]))
    for ii, i in enumerate(order):
        a, off, t0, t1 = geo[i]
        for j in order[ii + 1:]:
            b, offj, s0, s1 = geo[j]
            if abs(math.sin(b - a)) > math.sin(ANGLE_TOL * 2):
                break
            tol = max(1.0, ws[i]["thickness"] / 24 * per_ft)
            if offj - off > tol:
                break
            if ws[i].get("nominal_in") != ws[j].get("nominal_in"):
                continue
            if s0 - t1 > gap or t0 - s1 > gap:
                continue
            parent[find(j)] = find(i)
    return [find(i) for i in range(n)]


def drop_opening_tags(tags, not_codes, legend):
    """(tags kept, sorted codes dropped): tags whose code is a key of the
    set's door or window schedule (not_codes) are door / window tags, not
    wall types - unless the wall-type legend lists that code."""
    leg = {str(k).upper() for k in (legend or {})}
    bad = {str(c).upper() for c in (not_codes or ())} - leg

    def shape(c):
        # 'D04' -> ('D', 2): a row the schedule reader lost (columns run
        # together) still has a tag shaped like its neighbours' keys
        m = re.match(r"^([A-Z]+)(\d+)$", c)
        return (m.group(1), len(m.group(2))) if m else None
    shapes = {shape(c) for c in bad} - {None}

    def opening(code):
        c = str(code).upper()
        return c not in leg and (c in bad or shape(c) in shapes)
    kept = [t for t in tags if not opening(t["code"])]
    gone = sorted({t["code"] for t in tags if opening(t["code"])})
    return kept, gone


def wall_types(page, ppu, unit="ft", ws=None, legend=None, not_codes=None):
    """LF per wall type from the wall-type tags on a plan.

    ws: walls() output (read from the page when None). legend: {code:
    description} from the wall-type legend when it is on another sheet
    (G-004); the page's own legend is read too. Each tag names the wall
    it sits on or beside (within TAG_REACH_FT); the type runs on along
    that wall line - through door openings - to the next tag. A wall no
    tag reaches takes the type of its thickness class when every tagged
    wall of that class (INFER_SHARE of its LF) is one type - flagged as
    inferred - and is otherwise left "untagged" for review.

    Returns {"by_type": {code: {"lf", "lf_inferred", "walls", "tags",
    "description", "nominal_in", "thickness_in"}}, "untagged": {class
    label: lf}, "walls": ws (each with "type" and "type_source": "tag",
    "run", "thickness" or None), "tags": [{"code", "pt", "shape",
    "wall"}], "legend": {code: description}, "flags": [text]}. Lengths
    are in `unit`, like walls(). not_codes: keys of the set's door and
    window schedules - their tags are never wall types (drop_opening_tags).
    """
    per_ft = ppu * {"ft": 1.0, "in": 12.0, "m": 0.3048,
                    "yd": 1 / 3.0}.get(unit, 1.0)
    if ws is None:
        ws = walls(page, ppu, unit)
    if ws and "nominal_in" not in ws[0]:
        _cluster(ws)
    flags = []
    tags = find_type_tags(page)
    page_legend, zones = type_legend(page, tags)
    if legend and page_legend and not (
            set(page_legend) & {str(k).upper() for k in legend}):
        # the set's legend is on another sheet and this page's "legend"
        # names none of its types: a graphics / symbols key with a wall
        # type entry ("WALL TYPE - SEE A-103"), not a wall-type legend
        page_legend = {}
    leg = dict(page_legend)
    for k, v in (legend or {}).items():
        leg[str(k).upper()] = v or leg.get(str(k).upper(), "")
    plan_tags = [t for t in tags if not any(
        z[0] <= t["pt"][0] <= z[2] and z[1] <= t["pt"][1] <= z[3]
        for z in zones)]
    plan_tags, gone = drop_opening_tags(plan_tags, not_codes, leg)
    if gone:
        flags.append("door / window schedule tags left out of the wall "
                     "types: " + ", ".join(gone[:10]))
    if not leg:
        flags.append("no wall-type legend found - tags grouped by their "
                     "code, not checked against a legend")
    else:
        other = sorted({t["code"] for t in plan_tags if t["code"] not in leg})
        if other:
            flags.append("tags not in the wall-type legend left out "
                         "(window, door or keynote tags?): " +
                         ", ".join(other[:10]))
        plan_tags = [t for t in plan_tags if t["code"] in leg]
    for w in ws:
        w["type"], w["type_source"] = None, None
    # each tag to the wall it is on or beside
    reach = TAG_REACH_FT * per_ft
    thin = None
    for t in plan_tags:
        px, py = t["pt"]
        best = None
        for k, w in enumerate(ws):
            d = _seg_dist(px, py, w["p0"], w["p1"])
            lim = reach + t["r"] + w["thickness"] / 24 * per_ft
            if d <= lim and (best is None or d < best[0]):
                best = (d, k)
        t["wall"] = best[1] if best else None
        if best is None:
            # a tag set away from its walls with leader lines to them
            # (one diamond, two leaders: both walls are that type)
            if thin is None:
                thin = _thin_lines(page)
            hit = _leader_walls(thin, t, ws, per_ft)
            for k in hit:
                w = ws[k]
                if not w["type"]:
                    w["type"], w["type_source"] = t["code"], "tag"
            if hit:
                t["wall"] = hit[0]
                continue
            flags.append(f"tag {t['code']} at ({px:.0f}, {py:.0f}) is near "
                         "no wall found - not counted")
            continue
        w = ws[best[1]]
        if w["type"] and w["type"] != t["code"]:
            flags.append(f"one wall tagged both {w['type']} and "
                         f"{t['code']} - kept {w['type']}")
            continue
        w["type"], w["type_source"] = t["code"], "tag"
    # a tagged wall's type runs on along its line, through openings
    run = _runs(ws, per_ft) if ws else []
    codes = {}
    for k, w in enumerate(ws):
        if w["type"]:
            codes.setdefault(run[k], set()).add(w["type"])
    for k, w in enumerate(ws):
        if w["type"]:
            continue
        got = codes.get(run[k], set())
        if len(got) == 1:
            w["type"], w["type_source"] = next(iter(got)), "run"
        elif len(got) > 1:
            # several types on one line: the nearest tagged wall's
            (x0, y0), (x1, y1) = w["p0"], w["p1"]
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            near = min((math.hypot((o["p0"][0] + o["p1"][0]) / 2 - cx,
                                   (o["p0"][1] + o["p1"][1]) / 2 - cy), o)
                       for j, o in enumerate(ws)
                       if run[j] == run[k] and o["type_source"] == "tag")
            w["type"], w["type_source"] = near[1]["type"], "run"
    # untagged: by thickness class, when the class is all one type
    by_class = {}
    for w in ws:
        if w["type"]:
            c = by_class.setdefault(w.get("nominal_in"), {})
            c[w["type"]] = c.get(w["type"], 0.0) + w["length"]
    inferred = 0.0
    for w in ws:
        if w["type"]:
            continue
        c = by_class.get(w.get("nominal_in"))
        if not c:
            continue
        code, lf = max(c.items(), key=lambda kv: kv[1])
        if lf >= INFER_SHARE * sum(c.values()):
            w["type"], w["type_source"] = code, "thickness"
            inferred += w["length"]
    # untagged and still unknown: a wall as thick as one type's legend
    # build-up (3-5/8" studs + 5/8" board each side = 4-7/8") and no
    # other's takes that type, flagged as inferred
    from . import wall_assembly
    built = {}
    tagged_here = {t["code"] for t in plan_tags if t.get("wall") is not None}
    for code, d in leg.items():
        if code not in tagged_here:
            continue             # only a type this sheet actually tags
            # (a mezzanine plan draws the floor below's walls faintly)
        try:
            t = wall_assembly.thickness_in(d)
        except Exception:                                # noqa: BLE001
            t = None
        if t:
            built[code] = t
    by_build = 0.0
    if built:
        for w in ws:
            if w["type"]:
                continue
            m = w.get("measured", w["thickness"])
            hit = [c for c, t in built.items() if abs(m - t) <= 0.3]
            if len(hit) == 1:
                w["type"], w["type_source"] = hit[0], "thickness"
                inferred += w["length"]
                by_build += w["length"]
    if by_build:
        flags.append(f"{by_build:,.1f} {unit} of untagged wall typed by "
                     "matching its thickness to a legend build-up - check")
    if inferred:
        flags.append(f"{inferred:,.1f} {unit} of untagged wall given a type "
                     "inferred from its thickness - check")
    by_type, untagged = {}, {}
    for w in ws:
        if not w["type"]:
            lab = w.get("class_label") or wall_type(w["thickness"])
            untagged[lab] = untagged.get(lab, 0.0) + w["length"]
            continue
        b = by_type.setdefault(w["type"], {
            "lf": 0.0, "lf_inferred": 0.0, "walls": 0, "tags": 0,
            "description": leg.get(w["type"], ""), "_t": []})
        if w["type_source"] == "thickness":
            b["lf_inferred"] += w["length"]
        else:
            b["lf"] += w["length"]
        b["walls"] += 1
        b["_t"].append((w.get("measured", w["thickness"]), w["length"],
                        w.get("nominal_in")))
    for t in plan_tags:
        if t.get("wall") is not None and t["code"] in by_type:
            by_type[t["code"]]["tags"] += 1
    for code, b in by_type.items():
        ts = b.pop("_t")
        b["thickness_in"] = _weighted_median([x[0] for x in ts],
                                             [max(x[1], 1e-6) for x in ts])
        noms = {x[2] for x in ts}
        b["nominal_in"] = noms.pop() if len(noms) == 1 else None
        if b["nominal_in"] is None:
            flags.append(f"type {code} is tagged on walls of different "
                         "thicknesses - check the tags")
    if untagged:
        flags.append("walls with no type: " + ", ".join(
            f"{k} {v:,.1f} {unit}" for k, v in sorted(untagged.items())))
    return {"by_type": by_type, "untagged": untagged, "walls": ws,
            "tags": plan_tags, "legend": leg, "flags": flags}


def type_marks(page_no, ws, scale):
    """Viewer marks [(page, "add_line", payload)] for wall_types() output
    walls: grouped "Wall Type <code>" (untagged walls "<class label> -
    untagged", for review), so each type gets its own LF total."""
    unit = scale.get("unit", "ft")
    groups = []
    for w in ws:
        g = f"Wall Type {w['type']}" if w.get("type") else \
            f"{w.get('class_label') or wall_type(w['thickness'])} - untagged"
        if g not in groups:
            groups.append(g)
    color = {g: WALL_COLORS[i % len(WALL_COLORS)]
             for i, g in enumerate(groups)}
    out = []
    for w in ws:
        g = f"Wall Type {w['type']}" if w.get("type") else \
            f"{w.get('class_label') or wall_type(w['thickness'])} - untagged"
        m = {"type": "length", "value": round(w["length"], 4), "unit": unit,
             "group": g, "method": "wall types"}
        if w.get("type_source") == "thickness":
            m["method"] = "wall types (inferred from thickness)"
        out.append((page_no, "add_line", {
            "pts": [list(w["p0"]), list(w["p1"])],
            "color": list(color[g]), "width": 3, "opacity": 0.55,
            "measure": m}))
    return out
