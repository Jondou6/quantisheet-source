"""A sheet's scale checked against its own printed dimensions (accuracy
round 6): a wrong scale throws off every quantity on the sheet, so before
a sheet is taken off its dimension strings ("12'-6\"") are measured at
the scale it was given and compared with what they say.

    grade(page, per_ft) -> {"grade": "A" | "B" | "F" | None, "ratio",
                            "n", "spread", "samples": [(text, printed ft,
                            measured ft)], "why"}

For each dimension string, the dimension line is the straight line just
beside it, running the same way; the dimension runs between the nearest
extension lines or ticks crossing that line on either side of the text.
The median of measured / printed over the sheet grades it:

    A   within 2% (the scale is right),
    B   within 5% (probably right - drawing tolerance, check one),
    F   further off (the scale is wrong: the sheet is not taken off),
    None fewer than MIN_SAMPLES dimensions read - no grade either way.
"""
import math
import re
from .dmoney import c2 as _c2

MIN_SAMPLES = 4
_DIM = re.compile(r"^(\d{1,3})'\s*-?\s*(\d{1,2})(?:\s*(\d)/(\d{1,2}))?\"$")


def _ft(text):
    m = _DIM.match(text.strip().replace("′", "'")
                   .replace("″", '"'))
    if not m:
        return None
    v = int(m.group(1)) + int(m.group(2)) / 12.0
    if m.group(3):
        v += int(m.group(3)) / int(m.group(4)) / 12.0
    return v


def _segments(page):
    segs = []
    try:
        for p in page.get_drawings():
            if (p.get("width") or 0) > 1.2:
                continue                   # walls and heavy lines
            for it in p.get("items", ()):
                if it[0] == "l":
                    a, b = it[1], it[2]
                    segs.append((a.x, a.y, b.x, b.y))
    except Exception:                                    # noqa: BLE001
        return []
    return segs


def _words(page):
    """Dimension strings as whole words or two words ("12'-" "6\"")."""
    try:
        ws = page.get_text("words")
    except Exception:                                    # noqa: BLE001
        return []
    out = []
    for w in ws:
        v = _ft(w[4])
        if v:
            out.append((w[0], w[1], w[2], w[3], w[4], v))
    return out


def _measure(word, segs):
    """The measured length (drawing units) of the dimension a string
    labels, or None."""
    x0, y0, x1, y1 = word[:4]
    horiz = (x1 - x0) >= (y1 - y0)
    h = min(x1 - x0, y1 - y0) or 1.0
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    # work in the dimension's own axis: u along it, v across
    if horiz:
        def uv(x, y):
            return x, y
        cu, cv = cx, cy
    else:
        def uv(x, y):
            return y, x
        cu, cv = cy, cx
    # the dimension line: along the axis, within 2 text heights across,
    # passing the text
    line_v = None
    for a0, b0, a1, b1 in segs:
        u0, v0 = uv(a0, b0)
        u1, v1 = uv(a1, b1)
        if abs(v1 - v0) > 0.3 or abs(u1 - u0) < 2 * h:
            continue
        lo, hi = min(u0, u1), max(u0, u1)
        if not lo - 4 * h <= cu <= hi + 4 * h:
            continue
        d = abs(v0 - cv)
        if d <= 2.0 * h and (line_v is None or d < line_v[0]):
            line_v = (d, v0)
    if line_v is None:
        return None
    lv = line_v[1]
    # crossings of that line by extension lines / ticks, each side
    left = right = None
    for a0, b0, a1, b1 in segs:
        u0, v0 = uv(a0, b0)
        u1, v1 = uv(a1, b1)
        if abs(v1 - v0) <= 0.3:
            continue                                 # along the line
        if not min(v0, v1) - 0.5 <= lv <= max(v0, v1) + 0.5:
            continue
        t = (lv - v0) / (v1 - v0)
        u = u0 + t * (u1 - u0)
        if u < cu - 0.5 * (x1 - x0 if horiz else y1 - y0):
            if left is None or u > left:
                left = u
        elif u > cu + 0.5 * (x1 - x0 if horiz else y1 - y0):
            if right is None or u < right:
                right = u
    if left is None or right is None:
        return None
    return right - left


def grade(page, per_ft, others=()):
    """Grade the scale `per_ft` (drawing units per foot) of `page`.
    others: the per-foot of the other scales printed on the sheet (detail
    titles); a dimension that measures right at one of those belongs to
    that view, not to this scale, and is left out."""
    out = {"grade": None, "ratio": None, "n": 0, "spread": None,
           "samples": [], "why": ""}
    if not per_ft or per_ft <= 0:
        out["why"] = "no scale"
        return out
    words = _words(page)
    if not words:
        out["why"] = "no dimension strings on the sheet"
        return out
    segs = _segments(page)
    alt = [o / per_ft for o in others or ()
           if o and o > 0 and abs(o / per_ft - 1) > 0.1]
    pts = []
    other_view = 0
    for w in words[:120]:
        L = _measure(w, segs)
        if not L:
            continue
        meas = L / per_ft
        if any(abs(meas / w[5] / a - 1) <= 0.05 for a in alt):
            other_view += 1                 # drawn at another view's scale
            continue
        if 0.25 <= meas / w[5] <= 4.0:        # a chain total, a stray
            pts.append((w[5], meas))
            out["samples"].append((w[4], round(w[5], 3), round(meas, 3)))
    out["n"] = len(pts)
    out["other_view"] = other_view
    if len(pts) < MIN_SAMPLES:
        out["why"] = (f"only {len(pts)} dimension(s) could be measured "
                      "- the scale is not graded")
        return out
    # measured = slope x printed + offset: the slope is the scale's error;
    # a constant offset is how the ticks are drawn, not the scale
    # (Theil-Sen: the median of the pairwise slopes, robust to strays)
    sl = []
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            dx = pts[j][0] - pts[i][0]
            if abs(dx) >= 0.5:
                sl.append((pts[j][1] - pts[i][1]) / dx)
    if len(sl) < 3:
        out["why"] = "the dimensions measured are all about one length - " \
                     "the scale is not graded"
        return out
    sl.sort()
    med = sl[len(sl) // 2]
    offs = sorted(m - med * v for v, m in pts)
    b = offs[len(offs) // 2]
    agree = sum(1 for v, m in pts
                if abs(m - (med * v + b)) <= 0.03 * v + 0.1) / len(pts)
    out["ratio"] = round(med, 4)
    out["spread"] = _c2(agree)
    med_v = sorted(v for v, _m in pts)[len(pts) // 2]
    if med <= 0.05 or abs(b) > max(1.5, 0.25 * med_v):
        out["ratio"] = None
        out["why"] = (f"the {len(pts)} dimensions measured don't follow "
                      "their printed values (the wrong lines were read) - "
                      "the scale is not graded")
        return out
    if agree < 0.5:
        out["why"] = (f"the {len(pts)} dimensions measured disagree with "
                      "each other (more than one scale on the sheet?) - "
                      "the scale is not graded")
        return out
    off = abs(med - 1.0)
    out["grade"] = "A" if off <= 0.02 else "B" if off <= 0.05 else "F"
    if out["grade"] == "F" and any(abs(med / a - 1) <= 0.03 for a in alt):
        out["grade"] = None              # they are another view's dimensions
        out["why"] = (f"{len(pts)} printed dimensions measure {med:.3f}x "
                      "their values - the scale of another view printed on "
                      "the sheet, so they belong to that view; the sheet's "
                      "scale is not graded - check one dimension by hand")
        return out
    if out["grade"] == "F" and (len(pts) < 8 or agree < 0.7 or
                                not 0.4 <= med <= 2.5):
        out["grade"] = None              # too few or too loose to stop on
        out["why"] = (f"{len(pts)} printed dimensions measure {med:.3f}x "
                      "their values, but too few agree to be sure - the "
                      "scale is not graded; check one dimension by hand")
        return out
    out["why"] = (f"{len(pts)} printed dimensions measure {med:.3f}x their "
                  "values at this scale"
                  + ("" if out["grade"] == "A" else
                     " - check one by hand" if out["grade"] == "B" else
                     f" - the scale looks wrong (true scale about "
                     f"{_c2(per_ft * med):.2f} units per foot)"))
    return out
    ratios.sort()
    med = ratios[len(ratios) // 2]
    # agreement: the share of dimensions within 3% of the median
    agree = sum(1 for r in ratios if abs(r / med - 1) <= 0.03) / len(ratios)
    out["ratio"] = round(med, 4)
    out["spread"] = _c2(agree)
    off = abs(med - 1.0)
    med_v = sorted(v for v, _m in pts)[len(pts) // 2]
    if med <= 0.05 or abs(b) > max(1.5, 0.25 * med_v):
        out["ratio"] = None
        out["why"] = (f"the {len(pts)} dimensions measured don't follow "
                      "their printed values (the wrong lines were read) - "
                      "the scale is not graded")
        return out
    if agree < 0.5:
        out["why"] = (f"the {len(ratios)} dimensions measured disagree with "
                      "each other - the scale is not graded")
        return out
    out["grade"] = "A" if off <= 0.02 else "B" if off <= 0.05 else "F"
    if out["grade"] == "F" and (len(pts) < 8 or agree < 0.7 or
                                not 0.4 <= med <= 2.5):
        out["grade"] = None              # too few or too loose to stop on
        out["why"] = (f"{len(pts)} printed dimensions measure {med:.3f}x "
                      "their values, but too few agree to be sure - the "
                      "scale is not graded; check one dimension by hand")
        return out
    out["why"] = (f"{len(ratios)} printed dimensions measure "
                  f"{med:.3f}x their values at this scale"
                  + ("" if out["grade"] == "A" else
                     " - check one by hand" if out["grade"] == "B" else
                     f" - the scale looks wrong (true scale about "
                     f"{_c2(per_ft * med):.2f} units per foot)"))
    return out
