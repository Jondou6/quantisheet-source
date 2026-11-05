"""Building envelope takeoff (r34 stage 3). Quantities only - no prices.

  roof_takeoff(page, ppu, unit)   roof area by pitch from a SCALED roof
                                  plan (never from aerial reports or
                                  photos): plan SF and sloped SF per pitch,
                                  eave/rake edge LF, ridge / hip / valley
                                  / flashing LF where labelled
  wall_envelope(ext_lf, height, openings, notes, system)
                                  exterior wall area by system, door and
                                  window openings deducted, with insulation
                                  and air/vapor barrier lines when the
                                  notes call for them
  wall_height_from_levels(pages)  wall height from the level marks on the
                                  elevations/sections (finish floor to top
                                  of plate / wall / parapet)
"""
import math
import re
from collections import Counter

from . import tradetakeoff as tt
from .room_finishes import parse_feet

_FT_PER = {"ft": 1.0, "m": 3.28084}


def _pen_faces(segs, max_area):
    from shapely.geometry import LineString
    from shapely.ops import polygonize, unary_union
    lines = [LineString([(s[0], s[1]), (s[2], s[3])]) for s in segs
             if math.hypot(s[2] - s[0], s[3] - s[1]) >= 0.2]
    if len(lines) < 3:
        return []
    return [p for p in polygonize(unary_union(lines))
            if 0 < p.area <= max_area]


_LINE_LABELS = [("ridge_lf", re.compile(r"\bRIDGE\b", re.I)),
                ("hip_lf", re.compile(r"\bHIPS?\b", re.I)),
                ("valley_lf", re.compile(r"\bVALLEYS?\b", re.I)),
                ("flashing_lf", re.compile(r"\bFLASH(ING)?\b", re.I))]


_DS = re.compile(r"^D\.?S\.?$", re.I)


def _downspout_tags(page):
    """Downspout tags on a roof plan: text lines that are just 'DS' / 'D.S.'
    (a note or legend line that merely mentions DS is not a tag)."""
    lines = {}
    for w in page.get_text("words"):
        lines.setdefault((w[5], w[6]), []).append(w[4])
    return sum(1 for ws in lines.values() if len(ws) == 1 and
               _DS.match(ws[0]))


def _eaves_rakes(roof, planes, per_ft):
    """(eave LF, rake LF) of the roof outline (plan lengths). A straight
    outline edge is a rake (a gable end) when a line between two planes (a
    ridge) meets it square, away from its corners; every other outline edge
    is an eave - the gutter line."""
    geoms = [roof] if hasattr(roof, "exterior") else list(roof.geoms)
    tol = 0.02 * per_ft + 0.5
    inner = []
    for f, _v in planes:
        cs = list(f.exterior.coords)
        for a, b in zip(cs, cs[1:]):
            mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            if all(g.exterior.distance(_pt(mid)) > tol for g in geoms):
                inner.append((a, b))
    eave = rake = 0.0
    for g in geoms:
        ring = g.exterior.simplify(tol)
        cs = list(ring.coords)
        for a, b in zip(cs, cs[1:]):
            L = math.dist(a, b)
            if L <= 0:
                continue
            ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
            is_rake = False
            for p, q in inner:
                for e, o in ((p, q), (q, p)):
                    t = (e[0] - a[0]) * ux + (e[1] - a[1]) * uy
                    off = abs((e[0] - a[0]) * uy - (e[1] - a[1]) * ux)
                    if off > tol or not (per_ft < t < L - per_ft):
                        continue
                    li = math.dist(e, o)
                    if li and abs(((o[0] - e[0]) * ux + (o[1] - e[1]) * uy)
                                  / li) < 0.17:
                        is_rake = True
                        break
                if is_rake:
                    break
            if is_rake:
                rake += L
            else:
                eave += L
    return eave / per_ft, rake / per_ft


def _pt(c):
    from shapely.geometry import Point
    return Point(c)


def roof_takeoff(page, ppu, unit="ft"):
    """{plan_sf, sloped_sf, by_pitch: [{pitch, plan_sf, sloped_sf}],
    edge_lf, ridge_lf, hip_lf, valley_lf, flashing_lf, unlabelled_sf,
    pitch_labels}.

    The roof is the set of faces of one pen's linework that hold a pitch
    label (planes split by that pen's ridge / hip / valley lines), plus
    unlabelled faces of the same pen sharing an edge with them (they take
    the pitch of the labelled face they share the longest edge with).
    The pen chosen is the one whose labelled faces cover the most area.
    A scale is required: ValueError without one."""
    if not ppu:
        raise ValueError("roof takeoff needs a scaled roof plan")
    from shapely.geometry import Point
    from shapely.ops import unary_union
    k = _FT_PER.get(unit, 1.0)
    per_ft = ppu / k
    W, H = page.mediabox.width, page.mediabox.height
    labels = tt.pitch_labels(page)
    res = {"plan_sf": 0.0, "sloped_sf": 0.0, "by_pitch": [], "edge_lf": 0.0,
           "eave_lf": 0.0, "rake_lf": 0.0, "downspouts": 0,
           "ridge_lf": 0.0, "hip_lf": 0.0, "valley_lf": 0.0,
           "flashing_lf": 0.0, "unlabelled_sf": 0.0,
           "pitch_labels": len(labels)}
    if not labels:
        return res
    styles = tt.styled_segments(page)
    best = None
    for st, segs in styles.items():
        if st[2]:                                    # dashed: overhead/hidden
            continue
        faces = _pen_faces(segs, 0.5 * W * H)
        lab = []
        for f in faces:
            ins = [v for v, c in labels if f.contains(Point(c))]
            if ins:
                lab.append((f, Counter(ins).most_common(1)[0][0]))
        if not lab:
            continue
        a = sum(f.area for f, _v in lab)
        if best is None or a > best[0]:
            best = (a, st, faces, lab)
    if best is None:
        return res
    _a, st, faces, lab = best
    planes = list(lab)
    labelled = [f for f, _v in lab]
    for f in faces:
        if any(f.equals(g) for g in labelled):
            continue
        shared = [(f.boundary.intersection(g.boundary).length, v)
                  for g, v in lab]
        L, v = max(shared, key=lambda x: x[0])
        if L > 1.0 * per_ft and f.area < sum(g.area for g in labelled):
            planes.append((f, v))
            res["unlabelled_sf"] += f.area / per_ft ** 2
    by = {}
    for f, v in planes:
        sf = f.area / per_ft ** 2
        b = by.setdefault(float(v), [0.0, 0.0])
        b[0] += sf
        b[1] += sf * tt.slope_factor(v)
    res["by_pitch"] = [{"pitch": v, "plan_sf": a, "sloped_sf": s}
                       for v, (a, s) in sorted(by.items())]
    res["plan_sf"] = sum(a for a, _s in by.values())
    res["sloped_sf"] = sum(s for _a, s in by.values())
    roof = unary_union([f for f, _v in planes])
    res["edge_lf"] = roof.exterior.length / per_ft if hasattr(
        roof, "exterior") else sum(g.exterior.length for g in roof.geoms) \
        / per_ft
    res["eave_lf"], res["rake_lf"] = _eaves_rakes(roof, planes, per_ft)
    res["downspouts"] = _downspout_tags(page)
    # ridge / hip / valley / flashing: the nearest solid run (any pen -
    # caps and flashings are often drawn thin) to each label; runs
    # parallel to a taken one within a foot (a cap band) are the same line
    rs = []
    for st2, segs in styles.items():
        if st2[2]:
            continue
        rs += [r for r in tt.runs(segs) if tt.poly_len(r) >= 2 * per_ft]
    words = page.get_text("words")
    used = set()

    def same_line(i, j):
        a, b = rs[i], rs[j]
        return abs(tt.poly_len(a) - tt.poly_len(b)) < 0.1 * tt.poly_len(a) \
            and all(tt.dist_to_poly(q, a) < 1.0 * per_ft for q in (b[0],
                                                                 b[-1]))
    for key, rx in _LINE_LABELS:
        for w in words:
            if not rx.search(w[4]):
                continue
            c = ((w[0] + w[2]) / 2, (w[1] + w[3]) / 2)
            h = max(min(w[3] - w[1], w[2] - w[0]), 4.0)
            cand = [(tt.dist_to_poly(c, r), i) for i, r in enumerate(rs)
                    if i not in used]
            cand = [x for x in cand if x[0] <= 3 * h]
            if not cand:
                continue
            _d, i = min(cand)
            used |= {i} | {j for j in range(len(rs)) if j not in used and
                           same_line(i, j)}
            res[key] += tt.poly_len(rs[i]) / per_ft
    return res


_INSUL = re.compile(r"INSUL", re.I)
_BARRIER = re.compile(r"AIR\s*(?:/\s*VAPOR\s*)?BARRIER|VAPOR\s+(BARRIER|"
                      r"RETARDER)|WEATHER\s*(RESISTIVE\s*)?BARRIER|\bWRB\b|"
                      r"HOUSE\s*WRAP|BUILDING\s+WRAP", re.I)


def wall_envelope(ext_lf, height, openings, notes="", system="Exterior wall"):
    """{gross_sf, openings_sf, net_sf, lines: [{name, qty, unit}],
    confidence}. openings = [(width_ft, height_ft)] of the doors/windows in
    the wall. Insulation / air-vapor barrier lines follow the net wall
    area and are only made when the notes name them. With no openings
    known the confidence is low (the net area is the gross area)."""
    gross = float(ext_lf) * float(height)
    op = sum(float(w) * float(h) for w, h in (openings or []))
    net = max(0.0, gross - op)
    lines = [{"name": f"{system} - net wall area", "qty": net, "unit": "SF"}]
    t = str(notes or "")
    if _INSUL.search(t):
        lines.append({"name": f"{system} - insulation", "qty": net,
                      "unit": "SF"})
    if _BARRIER.search(t):
        lines.append({"name": f"{system} - air/vapor barrier", "qty": net,
                      "unit": "SF"})
    return {"gross_sf": gross, "openings_sf": op, "net_sf": net,
            "lines": lines, "confidence": 0.75 if openings else 0.5}


_TOP = re.compile(r"T\.?\s*O\.?\s*(PLATE|WALL|PARAPET|MASONRY|BEARING|STEEL|"
                  r"STRUCT)|TOP\s+OF\s+(PLATE|WALL|PARAPET|MASONRY|BEARING)|"
                  r"\bROOF\s+(BEARING|BRG\.?)\b|\bBEARING\s+(EL\.?|ELEV)",
                  re.I)
_FLOOR = re.compile(r"FIN(ISH(ED)?|\.)?\s*FL(OO)?R|\bF\.?F\.?E?\b|FIRST\s+FLOOR|"
                    r"LEVEL\s+1\b|GROUND\s+FLOOR", re.I)
_ELEV = re.compile(r"(\d+'\s*-?\s*\d+(?:\s+\d/\d)?\"?|\d+'-\d+\")")


def _marks(page, rx):
    """[elev_ft] for each level-mark label: the dimension on the label's
    line or just under it (within two lines)."""
    lines = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            t = "".join(s["text"] for s in ln["spans"]).strip()
            if t:
                lines.append((t, ln["bbox"]))
    out = []
    for t, bb in lines:
        if not rx.search(t):
            continue
        m = _ELEV.search(t[rx.search(t).end():])
        v = parse_feet(m.group(1)) if m else None
        if v is None:
            h = bb[3] - bb[1]
            nb = sorted((b2[1] - bb[3], t2) for t2, b2 in lines
                        if 0 <= b2[1] - bb[1] <= 2.5 * h and
                        abs(b2[0] - bb[0]) < 4 * h and (t2, b2) != (t, bb))
            for _d, t2 in nb:
                m = _ELEV.search(t2)
                if m and (v := parse_feet(m.group(1))) is not None:
                    break
        if v is not None:
            out.append(v)
    return out


def wall_heights_from_levels(pages):
    """The distinct (top mark - finish floor) heights in ft over the pages,
    lowest first. Floor = the lowest floor mark on each page."""
    hs = {}
    for pg in pages:
        tops = _marks(pg, _TOP)
        floors = _marks(pg, _FLOOR)
        if not tops or not floors:
            continue
        f = min(floors)
        for t in tops:
            if t > f:
                hs.setdefault(round(t - f, 3), t - f)
    return [hs[k] for k in sorted(hs)]


def wall_height_from_levels(pages):
    """The perimeter wall height in ft: the lowest top-of-wall / roof
    bearing mark above finish floor (higher marks are dormers, clerestories
    or parapets over part of the walls), or None."""
    hs = wall_heights_from_levels(pages)
    return hs[0] if hs else None


# ------------------------------------------------------------ roof assembly
# The layers under the roofing, read from the roof / wall section callouts
# near the roofing material (A-302: "STANDING SEAM ... UNDERLAYMENT ... 2"
# RIGID INSULATION"). Only layers the section calls out are listed.
_ROOFING = re.compile(r"\bSTANDING\s+SEAM\b|\bMETAL\s+ROOF(?:ING)?\b|"
                      r"\bASPHALT\s+SHINGLES?\b|\bTPO\b|\bEPDM\b|"
                      r"\bMODIFIED\s+BITUMEN\b", re.I)
_ROOF_LAYERS = [
    ("rigid insulation", re.compile(
        r"(\d+(?:\s*[- ]\s*\d/\d)?)\s*(?:\"|'')\s*(?:POLYISO\w*|RIGID)\s+"
        r"(?:ROOF\s+)?INSUL", re.I)),
    ("underlayment", re.compile(r"\bUNDERLAYMENT\b|\bSYNTHETIC\s+FELT\b",
                                re.I)),
    ("ice & water shield", re.compile(r"\bICE\s*(?:&|AND)\s*WATER\b", re.I)),
    ("vapor barrier", re.compile(r"\bVAPOU?R\s+(?:BARRIER|RETARDER)\b", re.I)),
    ("cover board", re.compile(r"\bCOVER\s*BOARD\b", re.I)),
]


def _lines_of(page):
    out = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            t = " ".join(s["text"] for s in ln["spans"]).strip()
            if t:
                out.append((t, fitz_rect(ln["bbox"])))
    return out


def fitz_rect(b):
    import fitz
    return fitz.Rect(b)


def roof_layers(page, reach_pt=150.0):
    """[{"layer", "thickness_in", "text"}] called out within `reach_pt` of
    a roofing material callout on `page` (a roof or wall section), or []."""
    lines = _lines_of(page)
    roofs = [r for t, r in lines if _ROOFING.search(t)]
    if not roofs:
        return []
    out, seen = [], set()
    for t, r in lines:
        c = ((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
        if not any(abs(c[0] - (q.x0 + q.x1) / 2) <= reach_pt and
                   abs(c[1] - (q.y0 + q.y1) / 2) <= reach_pt for q in roofs):
            continue
        for layer, rx in _ROOF_LAYERS:
            m = rx.search(t)
            if not m or layer in seen:
                continue
            th = None
            if layer == "rigid insulation":
                g = re.sub(r"\s+", " ", m.group(1))
                mf = re.match(r"(\d+)\s*[- ]\s*(\d)/(\d)", g)
                th = int(mf.group(1)) + int(mf.group(2)) / int(mf.group(3)) \
                    if mf else float(g)
            seen.add(layer)
            out.append({"layer": layer, "thickness_in": th, "text": t})
    return out
