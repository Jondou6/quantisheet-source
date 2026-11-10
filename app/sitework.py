"""Site, earthwork and landscape takeoff from scaled site sheets (r34
stage 3). Quantities only - no prices.

  plant_schedule(page)            the plant schedule's keys and QTY column
                                  (trees / shrubs EA; seed / sod areas SF)
  site_areas(page, ppu, unit)     paving / sidewalk / sod-seed areas: the
                                  smallest closed shape a material label
                                  sits in
  curb_lengths(page, ppu, unit)   curb LF: the connected run of the pen a
                                  CURB label lies along
  earthwork(page, ppu, unit)      cut / fill from existing (dashed) and
                                  proposed (solid) labelled contours, or
                                  proposed spot elevations; otherwise an RFI
  strip_depth_in(text)            topsoil strip depth from the notes

Everything here is a measurement of what is drawn; a line that cannot be
read with confidence is returned with a reason so the caller can list it
for review (or as an RFI) instead of taking it off.
"""
import math
import re
from collections import Counter, defaultdict

import fitz

from . import tradetakeoff as tt
from .dmoney import half_up as _hu

_FT_PER = {"ft": 1.0, "m": 3.28084}


def _words(page):
    """Words in displayed (rotated) coordinates: [(Rect, text)]."""
    M = page.rotation_matrix
    out = []
    for w in page.get_text("words"):
        r = fitz.Rect(w[:4]) * M
        out.append((fitz.Rect(min(r.x0, r.x1), min(r.y0, r.y1),
                              max(r.x0, r.x1), max(r.y0, r.y1)), w[4]))
    return out


# ------------------------------------------------------------ plant schedule
_KEY_HDR = {"CODE", "KEY", "SYM", "SYMBOL", "ABBR", "ABBREV", "ABBREVIATION",
            "MARK", "ID"}
_QTY_HDR = {"QTY", "QTY.", "QUANTITY", "QUAN", "QUAN.", "NO.", "COUNT"}
_KEY_TOK = re.compile(r"^[A-Za-z][A-Za-z0-9\-]{0,9}$")
_NUM = re.compile(r"^\d{1,3}(?:,\d{3})*(?:\.\d+)?$|^\d+(?:\.\d+)?$")
_AREA_UNIT = {"SF": ("SF", 1.0), "S.F.": ("SF", 1.0), "SQ.FT.": ("SF", 1.0),
              "SY": ("SF", 9.0), "S.Y.": ("SF", 9.0), "SQ.YD.": ("SF", 9.0),
              "AC": ("SF", 43560.0), "ACRES": ("SF", 43560.0)}


def plant_schedule(page):
    """[{key, qty, unit, desc}] from a plant schedule on the page: a header
    row holding a key column (CODE / SYMBOL / KEY) and a QTY column, keys
    listed under it. Seed / sod rows carry an area (SF; SY and acres
    converted). [] when no such table (at least two keyed rows with a
    quantity) is found."""
    ws = _words(page)
    out = []
    for qr, qt in ws:
        if qt.upper() not in _QTY_HDR:
            continue
        h = qr.height
        cy = (qr.y0 + qr.y1) / 2
        heads = [(r, t) for r, t in ws if t.upper() in _KEY_HDR and
                 abs((r.y0 + r.y1) / 2 - cy) < 0.6 * h and r.x1 < qr.x0]
        best = None
        for kr, _kt in heads:
            col = sorted([(r, t) for r, t in ws if r.y0 > kr.y1 and
                          abs(r.x0 - kr.x0) < 1.0 * h and _KEY_TOK.match(t)],
                         key=lambda x: x[0].y0)
            rows, last = [], kr.y1
            for r, t in col:
                if r.y0 - last > 6 * h:
                    break
                last = r.y1
                ry = (r.y0 + r.y1) / 2
                cells = sorted([(r2, t2) for r2, t2 in ws
                                if abs((r2.y0 + r2.y1) / 2 - ry) < 0.6 * h
                                and r2.x0 >= qr.x0 - 2 * h and
                                r2.x0 <= qr.x1 + 4 * h],
                               key=lambda x: x[0].x0)
                num = next(((i, t2) for i, (r2, t2) in enumerate(cells)
                            if _NUM.match(t2)), None)
                if num is None:
                    continue
                q = float(num[1].replace(",", ""))
                unit, k = "EA", 1.0
                if num[0] + 1 < len(cells):
                    u = cells[num[0] + 1][1].upper()
                    if u in _AREA_UNIT:
                        unit, k = _AREA_UNIT[u]
                desc = " ".join(t2 for r2, t2 in sorted(
                    [(r2, t2) for r2, t2 in ws
                     if abs((r2.y0 + r2.y1) / 2 - ry) < 0.6 * h and
                     r.x1 < r2.x0 < qr.x0 - 2 * h], key=lambda x: x[0].x0))
                qq = q * k
                rows.append({"key": t, "qty": int(qq) if qq == int(qq)
                             else _hu(qq, 1), "unit": unit,
                             "desc": desc[:80]})
            if len(rows) >= 2 and (best is None or len(rows) > len(best)):
                best = rows
        if best:
            keys = {r["key"] for r in out}
            out += [r for r in best if r["key"] not in keys]
    return out


# ------------------------------------------------------------ site areas
SITE_KINDS = [
    ("asphalt paving", re.compile(r"\b(ASPHALT|BITUMINOUS|HMA)\b", re.I)),
    ("concrete sidewalk", re.compile(r"\bSIDE\s*WALKS?\b|\bCONC(?:RETE|\.)?"
                                     r"\s+WALKS?\b", re.I)),
    ("concrete paving", re.compile(r"\bCONC(?:RETE|\.)?\s+(PAVEMENT|PAVING|"
                                   r"APRON|PAD|DRIVE)\b", re.I)),
    ("gravel paving", re.compile(r"\b(GRAVEL|AGGREGATE)\s+(PAVING|SURFACE|"
                                 r"DRIVE|LOT)\b", re.I)),
    ("sod / seed", re.compile(r"\b(SOD|SODDED|SEED(?:ED|ING)?|LAWN|TURF|"
                              r"GRASS(?:ED|ING)?)\b", re.I)),
]


def _lines(page):
    """Text lines (displayed coordinates is not needed: unrotated, like the
    drawings): [(text, Rect, size)]."""
    out = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            t = "".join(s["text"] for s in ln["spans"]).strip()
            if t:
                size = min((s["size"] for s in ln["spans"]), default=6.0)
                out.append((t, fitz.Rect(ln["bbox"]), size))
    return out


HATCH_MIN = 8        # a pen of at least this many strokes ...
HATCH_SHARE = 0.7    # ... this share in one direction, mostly unjoined,
                     # is hatching (or parking stripes), not an outline


def _is_hatch(v):
    if len(v) < HATCH_MIN:
        return False
    bins = Counter(int(math.degrees(math.atan2(s[3] - s[1], s[2] - s[0]))
                       % 180 // 10) for s in v)
    if bins.most_common(1)[0][1] < HATCH_SHARE * len(v):
        return False
    ends = Counter((round(x), round(y)) for s in v
                   for x, y in ((s[0], s[1]), (s[2], s[3])))
    joined = sum(1 for s in v if ends[(round(s[0]), round(s[1]))] > 1 or
                 ends[(round(s[2]), round(s[3]))] > 1)
    return joined < 0.5 * len(v)


def _outline_segments(page, ppu):
    """Segments that can bound an area: hatch pens (many parallel strokes
    that do not join up) and sheet-long lines (borders) are left out."""
    W, H = page.mediabox.width, page.mediabox.height
    segs = []
    for st, v in tt.styled_segments(page).items():
        if _is_hatch(v):
            continue
        for s in v:
            L = math.hypot(s[2] - s[0], s[3] - s[1])
            if L < 0.2 or L > 0.85 * max(W, H):
                continue
            segs.append(s)
    return segs


SITE_REACH_FT = (30, 80, 150)  # linework looked at around a label, widening
MIN_AREA_SF = 25     # a smaller shape is a symbol, not a paved / seeded area
GAP_MAX_SEGS = 1500  # hairline-gap closing only on lighter linework
GAP_PT = 1.0          # hairline gaps in an outline closed up to this


def _label_blocks(page):
    """Text blocks (a multi-line note is one label): [(text, Rect, size)]."""
    out = []
    for b in page.get_text("dict")["blocks"]:
        ls = b.get("lines", [])
        t = " ".join("".join(s["text"] for s in ln["spans"]).strip()
                     for ln in ls).strip()
        if t:
            size = min((s["size"] for ln in ls for s in ln["spans"]),
                       default=6.0)
            out.append((t, fitz.Rect(b["bbox"]), size))
    return out


def _containing_polygon(pt, segs, max_area, reach):
    """The smallest closed shape the linework makes around pt (shapely
    polygonize of the noded lines within reach); when the outline has
    hairline gaps, the hole around pt in the lines thickened by GAP_PT
    (grown back by GAP_PT). None when pt is in no closed shape."""
    from shapely.geometry import LineString, Point, Polygon
    from shapely.ops import polygonize, unary_union
    x, y = pt
    near = [s for s in segs if min(s[0], s[2]) <= x + reach and
            max(s[0], s[2]) >= x - reach and min(s[1], s[3]) <= y + reach and
            max(s[1], s[3]) >= y - reach]
    if not near:
        return None
    lines = unary_union([LineString([(s[0], s[1]), (s[2], s[3])])
                         for s in near])
    p = Point(x, y)
    best = None
    for poly in polygonize(lines):
        if poly.area <= 0 or poly.area > max_area or not poly.contains(p):
            continue
        if best is None or poly.area < best.area:
            best = poly
    if best is not None or len(near) > GAP_MAX_SEGS:
        return best
    fat = lines.buffer(GAP_PT / 2, cap_style=3, join_style=2)
    for g in getattr(fat, "geoms", [fat]):
        for ring in g.interiors:
            hole = Polygon(ring)
            if hole.contains(p):
                grown = hole.buffer(GAP_PT / 2, join_style=2)
                if 0 < grown.area <= max_area and (best is None or
                                                    grown.area < best.area):
                    best = grown
    return best


def _bezier(p0, p1, p2, p3, n=8):
    return [((1 - t) ** 3 * p0.x + 3 * (1 - t) ** 2 * t * p1.x +
             3 * (1 - t) * t * t * p2.x + t ** 3 * p3.x,
             (1 - t) ** 3 * p0.y + 3 * (1 - t) ** 2 * t * p1.y +
             3 * (1 - t) * t * t * p2.y + t ** 3 * p3.y)
            for t in (i / n for i in range(1, n + 1))]


FILL_JOIN_PT = 0.3    # abutting fill pieces of one colour join up


def shaded_regions(page, max_area, min_area=0.0):
    """Filled (non-white) regions as shapely polygons: each filled path's
    closed sub-paths combined even-odd (holes stay holes), then the pieces
    of one fill colour that touch joined into one region (CAD exports a
    solid fill as many strips)."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    by_fill = {}
    out = []
    try:
        paths = page.get_drawings()
    except Exception:                                    # noqa: BLE001
        return out
    for p in paths:
        f = p.get("fill")
        if not f or p.get("type") not in ("f", "fs") or min(f) > 0.95:
            continue
        rings, cur = [], []
        for it in p.get("items", ()):
            op = it[0]
            if op == "re":
                r = it[1]
                rings.append([(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1),
                              (r.x0, r.y1)])
                cur = []
                continue
            if op == "qu":
                q = it[1]
                rings.append([(q.ul.x, q.ul.y), (q.ur.x, q.ur.y),
                              (q.lr.x, q.lr.y), (q.ll.x, q.ll.y)])
                cur = []
                continue
            a = it[1]
            if cur and math.dist(cur[-1], (a.x, a.y)) > 0.5:
                rings.append(cur)
                cur = []
            if not cur:
                cur = [(a.x, a.y)]
            if op == "l":
                cur.append((it[2].x, it[2].y))
            elif op == "c":
                cur += _bezier(it[1], it[2], it[3], it[4])
        if cur:
            rings.append(cur)
        geom = None
        for ring in rings:
            if len(ring) < 3:
                continue
            g = Polygon(ring).buffer(0)
            if g.is_empty:
                continue
            geom = g if geom is None else geom.symmetric_difference(g)
        if geom is not None and geom.area > 0:
            by_fill.setdefault(tuple(_hu(v, 2) for v in f), []).append(geom)
    for gs in by_fill.values():
        u = unary_union([g.buffer(FILL_JOIN_PT, join_style=2) for g in gs])
        u = u.buffer(-FILL_JOIN_PT, join_style=2)
        for g in getattr(u, "geoms", [u]):
            if min_area < g.area <= max_area:
                out.append(g)
    return out


def _seeds(page, items):
    """[(seed point, leader pts or None)] for label blocks: a label with a
    leader is seeded just inside its tip, else at its centre."""
    from .civiltakeoff import _leaders
    labs = [{"rect": tuple(r), "size_pt": size,
             "center": ((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)}
            for _t, r, size in items]
    _leaders(page, labs)
    return [(lab["center"], lab.get("leader")) for lab in labs]


def site_areas(page, ppu, unit="ft", kinds=None, report_unclosed=False):
    """[{kind, area (SF), label, pts}] - each material label's closed
    shape (the shape its leader points into, when it has one), each shape
    once. With report_unclosed, labels with no closed shape come back as
    {kind, area: None, unclosed: True}."""
    if not ppu:
        raise ValueError("site areas need a scale")
    k = _FT_PER.get(unit, 1.0)
    per_ft = ppu / k
    segs = _outline_segments(page, per_ft)
    W, H = page.mediabox.width, page.mediabox.height
    items = []
    for text, r, size in _label_blocks(page):
        kind = next((kn for kn, rx in SITE_KINDS
                     if rx.search(text) and (kinds is None or kn in kinds)),
                    None)
        if kind is not None and len(text) <= 90:
            items.append((kind, text, r, size))
    seeds = _seeds(page, [(t, r, s) for _k, t, r, s in items])
    shaded = shaded_regions(page, 0.35 * W * H, (2 * per_ft) ** 2) \
        if items else []
    out, seen = [], []
    for (kind, text, r, size), (c, leader) in zip(items, seeds):
        use = segs
        if leader:
            lp = [tuple(q) for q in leader]
            use = [s for s in segs if not (
                tt.dist_to_poly((s[0], s[1]), lp) < 0.3 and
                tt.dist_to_poly((s[2], s[3]), lp) < 0.3)]
            # a tip on the outline: step back along the leader
            pts_ = [tuple(q) for q in leader]
            if math.dist(pts_[0], c) < math.dist(pts_[-1], c):
                pts_ = pts_[::-1]                 # tip last
            a, b = pts_[-2], pts_[-1]
            L = math.hypot(b[0] - a[0], b[1] - a[1]) or 1.0
            cands = [(b[0] + (a[0] - b[0]) / L * dd,
                      b[1] + (a[1] - b[1]) / L * dd) for dd in (0, 2, 4)]
        else:
            cands = [c]
        poly = None
        from shapely.geometry import Point
        for q in cands:
            # a shaded region under the seed is the area itself
            inside = [g for g in shaded if g.contains(Point(q))]
            if inside:
                g = min(inside, key=lambda g: g.area)
                poly = max(getattr(g, "geoms", [g]),
                           key=lambda x: x.area)
                if g.area > poly.area:
                    poly = g
                break
            poly = None
            for reach in SITE_REACH_FT:
                try:
                    poly = _containing_polygon(q, use, 0.35 * W * H,
                                               reach * per_ft)
                except Exception:                        # noqa: BLE001
                    poly = None
                if poly is not None and (
                        poly.bounds[2] - poly.bounds[0] < 1.6 * reach *
                        per_ft and poly.bounds[3] - poly.bounds[1] < 1.6 *
                        reach * per_ft):
                    break               # well inside the window: final
                if poly is not None and reach == SITE_REACH_FT[-1]:
                    break
            if poly is not None:
                break
        small = poly is not None and (
            poly.area < MIN_AREA_SF * per_ft ** 2 or
            (not leader and poly.area < 4 * r.width * r.height))
        if poly is None or small:
            if report_unclosed:
                out.append({"kind": kind, "area": None, "unclosed": True,
                            "label": text})
            continue
        key = tuple(round(v) for v in poly.bounds)
        if key in seen:
            continue
        seen.append(key)
        out.append({"kind": kind, "area": poly.area / per_ft ** 2,
                    "label": text,
                    "pts": [list(q) for q in max(
                        getattr(poly, "geoms", [poly]),
                        key=lambda x: x.area).exterior.coords]})
    return out


_CURB = re.compile(r"\bCURB\b|\bC\s*&\s*G\b", re.I)


def curb_lengths(page, ppu, unit="ft"):
    """[{length (LF), label, pts}] - for each CURB label, the run of the
    pen it lies along (the nearest run within three text heights) and the
    runs of that pen joined to it end to end; each run once."""
    if not ppu:
        raise ValueError("curb lengths need a scale")
    k = _FT_PER.get(unit, 1.0)
    per_ft = ppu / k
    by_style = {}
    for st, v in tt.styled_segments(page).items():
        rs = [r for r in tt.runs(v) if tt.poly_len(r) >= 3 * per_ft]
        if rs:
            by_style[st] = rs
    out, used = [], set()
    for text, r, size in _lines(page):
        if not _CURB.search(text) or len(text) > 50:
            continue
        c = ((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
        best = None
        for st, rs in by_style.items():
            for i, run in enumerate(rs):
                d = tt.dist_to_poly(c, run)
                if d <= 3 * max(size, r.height) and (best is None or
                                                     d < best[0]):
                    best = (d, st, i)
        if best is None:
            continue
        _d, st, i = best
        rs = by_style[st]
        comp, todo = {i}, [i]
        while todo:
            j = todo.pop()
            ends = (rs[j][0], rs[j][-1])
            for m, run in enumerate(rs):
                if m in comp:
                    continue
                if any(math.dist(a, b) <= 1.0 * per_ft for a in ends
                       for b in (run[0], run[-1])):
                    comp.add(m)
                    todo.append(m)
        comp = {m for m in comp if (st, m) not in used}
        if not comp:
            continue
        used |= {(st, m) for m in comp}
        out.append({"length": sum(tt.poly_len(rs[m]) for m in comp) / per_ft,
                    "label": text, "pts": [rs[m] for m in comp]})
    return out


# ------------------------------------------------------------ earthwork
_CONTOUR_NO = re.compile(r"^\d{2,4}(?:\.0{1,2})?$")
_SPOT = re.compile(r"^(?:(?:FFE|FF|TC|BC|TW|BW|FG|EG|TP|INV)[\s=:]*)?"
                   r"(\d{2,4}\.\d{1,2})$", re.I)


def _contour_sets(page, per_ft):
    """{style: [(elev, run)]} - runs carrying a contour number on or right
    beside them."""
    labs = []
    for text, r, size in _lines(page):
        if _CONTOUR_NO.match(text):
            labs.append((float(text), ((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2),
                         max(size, min(r.width, r.height))))
    if not labs:
        return {}
    out = defaultdict(list)
    styles = tt.styled_segments(page)
    cand = []
    for st, v in styles.items():
        for run in tt.runs(v):
            if tt.poly_len(run) >= 10 * per_ft:
                cand.append((st, run))
    for z, c, h in labs:
        best = None
        for st, run in cand:
            d = tt.dist_to_poly(c, run)
            if d <= 2.0 * h and (best is None or d < best[0]):
                best = (d, st, run)
        if best:
            out[best[1]].append((z, best[2]))
    return out


def _interp(pt, levels):
    """Ground elevation at pt from contour levels {z: [runs]}: linear
    between the two nearest contours of different elevation."""
    ds = sorted((min(tt.dist_to_poly(pt, r) for r in rs), z)
                for z, rs in levels.items())
    if len(ds) < 2:
        return None
    (d1, z1), (d2, z2) = ds[0], ds[1]
    if d1 + d2 <= 0:
        return z1
    return z1 + (z2 - z1) * d1 / (d1 + d2)


def _idw(pt, pts):
    num = den = 0.0
    for (x, y), z in pts:
        d = math.hypot(pt[0] - x, pt[1] - y)
        if d < 1e-6:
            return z
        w = 1.0 / d ** 2
        num += w * z
        den += w
    return num / den if den else None


def earthwork(page, ppu, unit="ft", cell_ft=None):
    """{cut_cy, fill_cy, area_sf, existing, proposed, rfi, confidence}:
    the grid-cell volume between existing ground (dashed contours) and
    the proposed surface (solid contours, or proposed spot elevations)
    over the area both cover. rfi is a reason (and the volumes None) when
    the sheet does not give both surfaces."""
    res = {"cut_cy": None, "fill_cy": None, "area_sf": None,
           "existing": 0, "proposed": 0, "rfi": None, "confidence": 0.0}
    if not ppu:
        res["rfi"] = "no scale - cut/fill not measured"
        return res
    k = _FT_PER.get(unit, 1.0)
    per_ft = ppu / k
    sets = _contour_sets(page, per_ft)
    sets = {st: v for st, v in sets.items()
            if len({z for z, _ in v}) >= 2}
    dashed = [st for st in sets if st[2]]
    solid = [st for st in sets if not st[2]]
    if not dashed and len(solid) >= 2:
        # both drawn solid: the lighter (screened) pen is the existing
        solid.sort(key=lambda st: -(sum(st[0]) if st[0] else 0))
        dashed, solid = [solid[0]], solid[1:]
    ex = defaultdict(list)
    for st in dashed:
        for z, run in sets[st]:
            ex[z].append(run)
    pr = defaultdict(list)
    for st in solid:
        for z, run in sets[st]:
            pr[z].append(run)
    spots = []
    if len(pr) < 2:
        for text, r, size in _lines(page):
            m = _SPOT.match(text)
            if m:
                spots.append((((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2),
                              float(m.group(1))))
    res["existing"], res["proposed"] = len(ex), len(pr) or len(spots)
    if len(ex) < 2 or (len(pr) < 2 and len(spots) < 3):
        res["rfi"] = ("existing and proposed grades not both shown as "
                      "labelled contours / spot elevations - cut and fill "
                      "need the grading surfaces (RFI)")
        return res
    from shapely.geometry import MultiPoint, Point
    ex_pts = [q for rs in ex.values() for r in rs for q in r]
    pr_pts = [q for rs in pr.values() for r in rs for q in r] or \
        [p for p, _z in spots]
    area = MultiPoint(ex_pts).convex_hull.intersection(
        MultiPoint(pr_pts).convex_hull)
    if area.is_empty or area.area <= 0:
        res["rfi"] = "existing and proposed grades do not overlap (RFI)"
        return res
    total_sf = area.area / per_ft ** 2
    cell_ft = cell_ft or max(2.0, math.sqrt(total_sf / 6000.0))
    step = cell_ft * per_ft
    x0, y0, x1, y1 = area.bounds
    cut = fill = 0.0
    n = 0
    y = y0 + step / 2
    while y < y1:
        x = x0 + step / 2
        while x < x1:
            if area.contains(Point(x, y)):
                ze = _interp((x, y), ex)
                zp = _interp((x, y), pr) if len(pr) >= 2 else \
                    _idw((x, y), spots)
                if ze is not None and zp is not None:
                    dz = ze - zp
                    if dz > 0:
                        cut += dz
                    else:
                        fill -= dz
                    n += 1
            x += step
        y += step
    a = cell_ft * cell_ft
    res.update(cut_cy=cut * a / 27.0, fill_cy=fill * a / 27.0,
               area_sf=n * a)
    lv = min(len(ex), len(pr) or len(spots))
    res["confidence"] = 0.65 if lv >= 3 and len(pr) >= 2 else 0.45
    return res


_STRIP = re.compile(r"(\d{1,2}(?:\.\d)?)\s*(?:\"|''|IN\b|IN\.|INCH(?:ES)?)",
                    re.I)


def strip_depth_in(text):
    """Topsoil strip depth (in) written in the notes ('STRIP 6\" OF
    TOPSOIL', 'TOPSOIL (4 INCHES)'), or None."""
    t = " ".join(str(text or "").split())
    for m in re.finditer(r"TOPSOIL", t, re.I):
        win = t[max(0, m.start() - 60):m.end() + 40]
        if not re.search(r"STRIP|REMOVE|STOCKPILE", win, re.I):
            continue
        d = _STRIP.search(win)
        if d:
            v = float(d.group(1))
            return int(v) if v == int(v) else v
    return None


# ------------------------------------------------------------ pavement section
# The layers an estimator takes off under a paved area, read from the
# pavement section detail's callouts (C-601 "TACK COATING / 1 1/2" 9.5 MM
# SUPERPAVE / 2" 12.5 MM SUPERPAVE (HOT PLANT MIX) BINDER / ... AGGREGATE
# BASE / SUBGRADE COMPACTED TO 100%"). Only what the detail says is listed:
# a layer the drawing doesn't call out (a prime coat, a geotextile) is not
# added.
_LAYER_RX = [
    ("tack coat", re.compile(r"\bTACK\s+COAT(?:ING)?\b", re.I)),
    ("prime coat", re.compile(r"\bPRIME\s+COAT(?:ING)?\b", re.I)),
    ("asphalt course", re.compile(
        r"(\d+(?:\s*[- ]\s*\d/\d)?|\d/\d)\s*(?:\"|''|IN\.?)?\s*(?:[\d.]+\s*MM\s*)?"
        r"(?:SUPER\s*PAVE|ASPHALT(?:IC)?\s+CONCRETE|HMA|HOT\s+MIX)", re.I)),
    ("binder", re.compile(r"\bBINDER\b", re.I)),
    ("aggregate base", re.compile(
        r"\b(?:GRADED\s+)?AGGREGATE\s+BASE\b|\bGAB\b|\bABC\b", re.I)),
    ("subgrade", re.compile(r"\bSUBGRADE\s+COMPACTED\b|\bCOMPACTED\s+SUBGRADE\b",
                            re.I)),
    ("geotextile", re.compile(r"\bGEOTEX(?:TILE)?\b", re.I)),
]
_EXCLUDE_LAYER = re.compile(r"\bTACKIFIER\b|\bTOPSOIL\b|\bSEED", re.I)
_LAYER_IN = re.compile(r"(\d+(?:\.\d+)?)\s*(?:\"|''|IN\b)", re.I)


def pavement_layers(page, reach_pt=400.0):
    """The layers of an asphalt pavement section detail on `page`:
    [{"layer": "tack coat" | "asphalt course" | "binder course" |
    "aggregate base" | "compacted subgrade" | "prime coat" | "geotextile",
    "thickness_in": float or None, "text": the callout}] top down, or []
    when the page has no such detail (at least three different layers
    called out close together, one of them an asphalt course)."""
    lines = [(t, r) for t, r, _s in _lines(page)
             if not _EXCLUDE_LAYER.search(t)]
    hits = []
    for t, r in lines:
        for kind, rx in _LAYER_RX:
            if rx.search(t):
                hits.append((kind, t, r))
                break
    if not hits:
        return []
    # the densest cluster of callouts (a detail is one small area)
    best = []
    for _k, _t, r in hits:
        c = ((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
        near = [h for h in hits
                if abs((h[2].x0 + h[2].x1) / 2 - c[0]) <= reach_pt and
                abs((h[2].y0 + h[2].y1) / 2 - c[1]) <= reach_pt]
        if len({h[0] for h in near}) > len({h[0] for h in best}):
            best = near
    kinds = {h[0] for h in best}
    if len(kinds) < 3 or "asphalt course" not in kinds:
        return []
    best.sort(key=lambda h: (h[2].y0, h[2].x0))
    # "(HOT PLANT MIX) BINDER" finishes the asphalt course callout nearest
    # to it: that course is the binder course; the other is the surface
    binder_of = set()
    for kind, t, r in best:
        if kind != "binder":
            continue
        cs = [(abs(h[2].y0 - r.y0) + 0.25 * abs(h[2].x0 - r.x0), id(h))
              for h in best if h[0] == "asphalt course"]
        if cs:
            binder_of.add(min(cs)[1])
    out = []
    courses = 0
    for h in best:
        kind, t, r = h
        if kind == "binder":
            continue
        m = _LAYER_IN.search(t)
        th = None
        if m:
            th = float(m.group(1))
        mf = re.match(r"\s*(\d+)\s*[- ]\s*(\d)/(\d)", t)
        if mf:
            th = int(mf.group(1)) + int(mf.group(2)) / int(mf.group(3))
        layer = kind
        if kind == "asphalt course":
            courses += 1
            layer = "binder course" if id(h) in binder_of else \
                "surface course" if not any(
                    o["layer"] == "surface course" for o in out) else \
                "asphalt course"
        if kind == "subgrade":
            layer = "compacted subgrade"
        if any(o["layer"] == layer and o["text"] == t for o in out):
            continue
        out.append({"layer": layer, "thickness_in": th, "text": t})
    return out
