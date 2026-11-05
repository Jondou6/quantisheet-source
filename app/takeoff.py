import math
import re
import fitz


class Calibration:
    """Scale between PDF points and real-world units, from a known length."""

    def __init__(self, pt_a, pt_b, real_distance, unit="ft"):
        d = ((pt_b.x - pt_a.x) ** 2 + (pt_b.y - pt_a.y) ** 2) ** 0.5
        if d <= 0:
            raise ValueError("zero-length calibration")
        if (not real_distance or not math.isfinite(real_distance)
                or real_distance <= 0):
            raise ValueError("calibration distance must be positive")
        self.points_per_unit = d / real_distance
        self.unit = unit

    def convert(self, points):
        return points / self.points_per_unit


def distance(cal, a, b):
    d = ((b.x - a.x) ** 2 + (b.y - a.y) ** 2) ** 0.5
    return cal.convert(d)


def area(cal, pts):
    if len(pts) < 3:
        return 0.0
    s = 0.0
    n = len(pts)
    for i in range(n):
        j = (i + 1) % n
        s += pts[i].x * pts[j].y - pts[j].x * pts[i].y
    return (abs(s) / 2.0) / (cal.points_per_unit ** 2)


def annotate_distance(page, cal, a, b, unit=None):
    unit = unit or cal.unit
    val = distance(cal, a, b)
    page.draw_line(a, b, color=(0, 0, 0), width=1)
    mid = fitz.Point((a.x + b.x) / 2, (a.y + b.y) / 2)
    page.insert_text((mid.x, mid.y - 3), f"{val:.2f} {unit}", fontsize=8)
    return val


def annotate_area(page, cal, pts, unit=None):
    unit = unit or f"sq {cal.unit}"
    if len(pts) < 3:
        return 0.0
    for a, b in zip(pts, pts[1:]):
        page.draw_line(a, b, color=(0, 0, 0), width=1)
    page.draw_line(pts[-1], pts[0], color=(0, 0, 0), width=1)
    cx = sum(p.x for p in pts) / len(pts)
    cy = sum(p.y for p in pts) / len(pts)
    val = area(cal, pts)
    page.insert_text((cx, cy), f"{val:.2f} {unit}", fontsize=8)
    return val


# ---- helpers used by the desktop takeoff tools --------------------------------

UNITS = ["ft", "in", "yd", "m", "cm", "mm"]


def _dist(a, b):
    return ((b.x - a.x) ** 2 + (b.y - a.y) ** 2) ** 0.5


def path_length(pts):
    return sum(_dist(a, b) for a, b in zip(pts, pts[1:]))


def polygon_area(pts):
    n = len(pts)
    if n < 3:
        return 0.0
    s = sum(pts[i].x * pts[(i + 1) % n].y - pts[(i + 1) % n].x * pts[i].y
            for i in range(n))
    return abs(s) / 2.0


def fmt(value, unit):
    """12.5 ft -> "12' 6\"" for feet, otherwise "12.50 m"."""
    if not math.isfinite(value):
        return f"{value} {unit}"
    if unit == "ft":
        sign = "-" if value < 0 else ""
        value = abs(value)
        feet = int(value)
        inches = round((value - feet) * 12, 1)
        if inches >= 12:
            feet, inches = feet + 1, 0
        if sign and not feet and not inches:
            sign = ""
        return f"{sign}{feet}' {inches:g}\""
    return f"{value:,.2f} {unit}"


_QUOTES = str.maketrans({"\u2019": "'", "\u2032": "'", "\u201d": '"',
                         "\u2033": '"', "\u201c": '"', "\u2018": "'"})
_NUM = r"(\d+(?:\.\d+)?)"
_FT_IN = re.compile(
    r"^\s*(?:" + _NUM + r"\s*(?:'|ft\b|feet\b|foot\b))?\s*-?\s*"
    r"(?:" + _NUM + r"(?:\s+(\d+)\s*/\s*(\d+))?\s*(?:\"|in\b|inch(?:es)?\b))?\s*$",
    re.I)
_PLAIN = re.compile(r"^\s*" + _NUM + r"\s*(ft|in|yd|m|cm|mm)?\s*$", re.I)


def parse_length(text):
    """Read a length typed the way it's written on drawings.

    "4'-6\"", "4' 6 1/2\"", "4ft 6in", "4'" -> (feet, "ft");
    "54\"" -> (54, "in"); "1.2 m" -> (1.2, "m"); "12.5" -> (12.5, None).
    Returns None if the text isn't a length.
    """
    t = (text or "").translate(_QUOTES).strip()
    if not t:
        return None
    m = _PLAIN.match(t)
    if m:
        unit = m.group(2).lower() if m.group(2) else None
        return float(m.group(1)), unit
    m = _FT_IN.match(t)
    if m and (m.group(1) or m.group(2)):
        feet = float(m.group(1) or 0)
        inches = float(m.group(2) or 0)
        if m.group(3) and m.group(4) and float(m.group(4)):
            inches += float(m.group(3)) / float(m.group(4))
        if m.group(1):
            return feet + inches / 12, "ft"
        return inches, "in"
    return None


def scale_text(ppu, unit):
    """Human description of a scale, e.g. '1" = 8.0 ft'."""
    if ppu <= 0:
        return ""
    per_inch = 72 / ppu
    return f'1" on paper = {per_inch:,.4g} {unit}'


# ---- reading the scale off a sheet (Auto Scale) --------------------------

# A mixed number ("1 1/2", "1-1/2") must sit on one line with only spaces
# or a hyphen between its parts, and its whole part can't have a leading
# zero: "02\n1/2\"" on a title block is a sheet-number tail and a scale,
# not 2-1/2". Nothing may run into the number from the left either.
_SP = r"[ \t]"
_FRAC = (r"(?<![\d./])((?:[1-9]\d?)(?:[ \t]+|[ \t]*-[ \t]*)\d+/\d+"
         r"|\d+/\d+|\d+(?:\.\d+)?)")
_ARCH = re.compile(_FRAC + _SP + r"*(?:\"|''|in\.?)" + _SP + r"*=" + _SP +
                   r"*1" + _SP + r"*(?:'|ft\.?)" + _SP + r"*-?" + _SP +
                   r"*0?" + _SP + r"*(?:\"|'')?", re.I)
_ENG = re.compile(r"(?<![\d/.])1" + _SP + r"*(?:\"|''|in\.?)" + _SP + r"*=" +
                  _SP + r"*(\d+(?:\.\d+)?)" + _SP + r"*(?:'|ft\b|feet\b)"
                  r"(?:" + _SP + r"*-?" + _SP + r"*0" + _SP +
                  r"*(?:\"|''))?", re.I)
_METRIC = re.compile(r"scale" + _SP + r"*:?" + _SP + r"*1" + _SP + r"*:" +
                     _SP + r"*(\d+(?:\.\d+)?)", re.I)
_NTS = re.compile(r"\b(N\.?T\.?S\.?|NOT\s+TO\s+SCALE)\b", re.I)
_SCALE_WORD = re.compile(r"\bSCALE\b", re.I)


def _frac(t):
    """'1 1/2', '1-1/2', '3/4' or '2' -> inches. Never raises."""
    parts = [x for x in re.split(r"[\s-]+", (t or "").strip()) if x]
    total = 0.0
    try:
        for x in parts:
            if "/" in x:
                a, b = x.split("/", 1)
                total += float(a) / float(b) if float(b) else 0.0
            else:
                total += float(x)
    except ValueError:
        return 0.0
    return total


def _label_in(inches_text):
    t = re.sub(r"[ \t]*-[ \t]*|[ \t]+", "-", inches_text.strip())
    return f'{t}" = 1\'-0"'


# a scale whose three parts are separate text lines ('SCALE: 1/4"' / '=' /
# "1'-0\"", Oct 31 public bid MEP sheets): inches mark ending one line, a
# line that is only '=', a line starting with feet. The two line breaks
# become spaces (same length, so positions don't move); nothing else is
# joined, so a sheet-number tail can still never run into a fraction.
_SPLIT_SCALE = re.compile(r"(?<=[\d/]\")[ \t]*\n[ \t]*=[ \t]*\n(?=[ \t]*\d+(?:\.\d+)?"
                          r"[ \t]*(?:'|ft\b))", re.I)


def _join_split_scales(t):
    return _SPLIT_SCALE.sub(lambda m: m.group(0).replace("\n", " "), t)


def find_scales(text):
    """Every drawing scale written in `text`, as a list of
    (label, points per unit, unit) in the order found.
    1/4" = 1'-0" -> 18 pt per ft; 1" = 20' -> 3.6 pt per ft; 1:100 -> m."""
    return [f[:3] for f in _find(text)]


# DESIGN RULE (Oct 31 2026, patent review - enforced by
# tests/test_patent_design_rules.py): AI Takeoff takes a sheet's scale from
# its printed scale text (title block or view title) and checks it against
# printed dimension strings - never by counting raster pixels along
# something of known length.
def _find(text):
    """find_scales() plus, for each, whether it sits on or just below a
    line that says SCALE."""
    return [f[2:] for f in scale_spans(text)]


def scale_spans(text):
    """_find() with where each scale is in `text`: [(start, end, label,
    points per unit, unit, near the word SCALE)] - the AI scale evidence
    (scale_evidence.py) maps these back to the printed words."""
    t = _join_split_scales((text or "").translate(_QUOTES))
    lines = t.split("\n")
    starts, pos = [], 0
    for ln in lines:
        starts.append(pos)
        pos += len(ln) + 1
    flag = [bool(_SCALE_WORD.search(ln)) for ln in lines]

    def near(at):
        import bisect
        i = bisect.bisect_right(starts, at) - 1
        return flag[i] or (i > 0 and flag[i - 1])
    out = []
    for m in _ARCH.finditer(t):
        inches = _frac(m.group(1))
        if 0 < inches <= 12:
            out.append((m.start(), m.end(), _label_in(m.group(1)),
                        inches * 72, "ft", near(m.start())))
    for m in _ENG.finditer(t):
        feet = float(m.group(1))
        if feet >= 1 and not (feet == 1 and "1'-0" in m.group(0)):
            out.append((m.start(), m.end(), f'1" = {m.group(1)}\'',
                        72 / feet, "ft", near(m.start())))
    for m in _METRIC.finditer(t):
        n = float(m.group(1))
        if n >= 1:
            out.append((m.start(), m.end(), f"1:{m.group(1)}",
                        1000 / n / 25.4 * 72, "m", True))
    out.sort(key=lambda f: f[0])
    return out


def main_scale(text):
    """The scale to use for a sheet, or None if there's none or the sheet
    only says NTS. Scales written next to the word SCALE win over loose
    text; among those, the smallest (the plan, not its enlarged details);
    standard scales win over odd ones."""
    found = _find(text)
    if not found:
        return None
    pool = [f for f in found if f[3]] or found
    std = [f for f in pool if is_standard(f[1], f[2])]
    pool = std or pool
    by_unit = {}
    for f in pool:
        by_unit.setdefault(f[2], []).append(f)
    group = by_unit.get("ft") or next(iter(by_unit.values()))
    return min(group, key=lambda f: f[1])[:3]


def is_standard(ppu, unit, tol=0.005):
    """True if (ppu, unit) is one of the usual drawing scales."""
    for fam in PRESETS.values():
        for _, (p, u) in fam:
            if u == unit and abs(p - ppu) <= tol * p:
                return True
    for p, u in _EXTRA_STANDARD:
        if u == unit and abs(p - ppu) <= tol * p:
            return True
    return False


# ---- standard drawing scales -----------------------------------------------------
# name -> (points on paper per real unit, unit)
def _arch(paper_in):          # paper inches per real foot
    return (paper_in * 72, "ft")


def _eng(feet_per_inch):      # 1" = N'
    return (72 / feet_per_inch, "ft")


def _metric(ratio):           # 1:N, real metres
    return (1000 / ratio / 25.4 * 72, "m")


PRESETS = {
    "Architectural": [
        ('1/16" = 1\'-0"', _arch(1 / 16)), ('3/32" = 1\'-0"', _arch(3 / 32)),
        ('1/8" = 1\'-0"', _arch(1 / 8)), ('3/16" = 1\'-0"', _arch(3 / 16)),
        ('1/4" = 1\'-0"', _arch(1 / 4)), ('3/8" = 1\'-0"', _arch(3 / 8)),
        ('1/2" = 1\'-0"', _arch(1 / 2)), ('3/4" = 1\'-0"', _arch(3 / 4)),
        ('1" = 1\'-0"', _arch(1)), ('1-1/2" = 1\'-0"', _arch(1.5)),
        ('3" = 1\'-0"', _arch(3)),
    ],
    "Engineering": [(f'1" = {n}\'', _eng(n))
                    for n in (10, 20, 30, 40, 50, 60, 100, 200)],
    "Metric": [(f"1:{n}", _metric(n))
               for n in (20, 50, 100, 200, 250, 500, 1000)],
}


# less common scales that are still real (civil, site and large details)
_EXTRA_STANDARD = [_arch(x) for x in (1 / 32, 1 / 64, 1.5, 3, 6, 12)] + \
    [_eng(n) for n in (1, 2, 4, 5, 8, 15, 25, 80, 120, 150, 250, 300, 400,
                       500, 600, 800, 1000, 2000)] + \
    [_metric(n) for n in (1, 2, 5, 10, 25, 75, 125, 1250, 2000, 2500, 5000)]


# ---- angle, circle, units --------------------------------------------------------

def angle(pts):
    """Angle in degrees at pts[1] between pts[0] and pts[2] (0-180)."""
    import math
    a, b, c = pts[:3]
    v1 = (a.x - b.x, a.y - b.y)
    v2 = (c.x - b.x, c.y - b.y)
    n1, n2 = math.hypot(*v1), math.hypot(*v2)
    if n1 == 0 or n2 == 0:
        return 0.0
    cosv = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2)))
    return math.degrees(math.acos(cosv))


FT_PER = {"ft": 1.0, "in": 1 / 12, "yd": 3.0, "m": 3.28084, "cm": 0.0328084,
          "mm": 0.00328084}


def convert(value, from_unit, to_unit):
    """Convert a length between drawing units (ft, in, yd, m, cm, mm)."""
    if not from_unit or from_unit == to_unit:
        return value
    if from_unit not in FT_PER or to_unit not in FT_PER:
        return value
    return value * FT_PER[from_unit] / FT_PER[to_unit]
