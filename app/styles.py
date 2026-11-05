"""Line styles and hatch patterns (built in plus your own), and the
geometry that fills a shape with hatch lines.

Custom styles are kept in the settings file, so they're available in every
drawing. A hatch is drawn as one ink annotation clipped to the shape; it
carries the shape's op tag, so it moves, recolors and deletes with it.
"""
import math

from . import settings

# name -> dash pattern in points (None = solid)
LINE_STYLES = {
    "Solid": None,
    "Dashed": [6, 3],
    "Dotted": [1, 2],
    "Dash Dot": [6, 2, 1, 2],
    "Long Dash": [12, 4],
    "Hidden": [3, 3],
    "Center": [12, 3, 3, 3],
}

# name -> [(angle in degrees, spacing in points), ...]
HATCHES = {
    "None": None,
    "Diagonal": [(45, 6)],
    "Back Diagonal": [(135, 6)],
    "Cross Hatch": [(45, 6), (135, 6)],
    "Horizontal": [(0, 6)],
    "Vertical": [(90, 6)],
    "Grid": [(0, 6), (90, 6)],
    "Dense Diagonal": [(45, 3)],
    "Wide Diagonal": [(45, 12)],
    "Insulation": [(60, 4), (120, 4)],
}


def _clean_dashes(seq):
    try:
        out = [float(x) for x in seq]
    except (TypeError, ValueError):
        return None
    out = [x for x in out if 0 < x <= 100][:8]
    return out or None


def _clean_hatch(seq):
    out = []
    try:
        for ang, sp in seq:
            ang, sp = float(ang) % 180, float(sp)
            if 1 <= sp <= 200:
                out.append((ang, sp))
    except (TypeError, ValueError):
        return None
    return out[:4] or None


def line_styles():
    out = dict(LINE_STYLES)
    for name, d in (settings.get("line_styles") or {}).items():
        d = _clean_dashes(d)
        if d:
            out[str(name)] = d
    return out


def hatches():
    out = dict(HATCHES)
    for name, h in (settings.get("hatches") or {}).items():
        h = _clean_hatch(h)
        if h:
            out[str(name)] = h
    return out


def save_line_style(name, dashes):
    d = _clean_dashes(dashes)
    if not name or not d:
        raise ValueError("Give a name and a dash pattern like 6 3 1 3")
    cur = dict(settings.get("line_styles") or {})
    cur[name] = d
    settings.set("line_styles", cur)


def delete_line_style(name):
    cur = dict(settings.get("line_styles") or {})
    cur.pop(name, None)
    settings.set("line_styles", cur)


def save_hatch(name, families):
    h = _clean_hatch(families)
    if not name or not h:
        raise ValueError("Give a name and at least one angle and spacing")
    cur = dict(settings.get("hatches") or {})
    cur[name] = [list(f) for f in h]
    settings.set("hatches", cur)


def delete_hatch(name):
    cur = dict(settings.get("hatches") or {})
    cur.pop(name, None)
    settings.set("hatches", cur)


def parse_dashes(text):
    """'6 3 1 3' or '6,3' -> [6, 3, 1, 3]"""
    parts = str(text or "").replace(",", " ").split()
    return _clean_dashes(parts)


def parse_hatch(text):
    """'45/6, 135/6' (angle/spacing pairs) -> [(45, 6), (135, 6)]"""
    fams = []
    for chunk in str(text or "").replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        bits = chunk.replace("@", "/").split("/")
        if len(bits) != 2:
            return None
        fams.append((bits[0], bits[1]))
    return _clean_hatch(fams)


# ---- statuses (Markups List) --------------------------------------------------

def statuses(defaults):
    out = list(defaults)
    for s in settings.get("statuses") or []:
        s = str(s).strip()[:40]
        if s and s not in out:
            out.append(s)
    return out


def set_custom_statuses(names):
    settings.set("statuses", [str(n).strip()[:40] for n in names
                              if str(n).strip()])


# ---- hatch geometry -----------------------------------------------------------

def hatch_segments(poly, families, limit=4000):
    """Hatch lines clipped to polygon `poly` ([(x, y)]): a list of
    ((x0, y0), (x1, y1)) segments."""
    pts = [(float(x), float(y)) for x, y in poly]
    if len(pts) < 3 or not families:
        return []
    segs = []
    for ang, spacing in families:
        a = math.radians(ang)
        ca, sa = math.cos(a), math.sin(a)
        # rotate so hatch lines are horizontal: v = -x sin + y cos
        rot = [(x * ca + y * sa, -x * sa + y * ca) for x, y in pts]
        vs = [p[1] for p in rot]
        v = (math.floor(min(vs) / spacing) + 0.5) * spacing
        n = len(rot)
        while v < max(vs) and len(segs) < limit:
            xs = []
            for i in range(n):
                (u0, v0), (u1, v1) = rot[i], rot[(i + 1) % n]
                if (v0 <= v < v1) or (v1 <= v < v0):
                    xs.append(u0 + (v - v0) * (u1 - u0) / (v1 - v0))
            xs.sort()
            for k in range(0, len(xs) - 1, 2):
                if xs[k + 1] - xs[k] < 0.5:
                    continue
                p0 = (xs[k] * ca - v * sa, xs[k] * sa + v * ca)
                p1 = (xs[k + 1] * ca - v * sa, xs[k + 1] * sa + v * ca)
                segs.append((p0, p1))
            v += spacing
    return segs


def ellipse_points(rect, n=48):
    x0, y0, x1, y1 = rect
    cx, cy, rx, ry = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2
    return [(cx + rx * math.cos(2 * math.pi * i / n),
             cy + ry * math.sin(2 * math.pi * i / n)) for i in range(n)]


def rect_points(rect):
    x0, y0, x1, y1 = rect
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
