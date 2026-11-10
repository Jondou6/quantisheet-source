"""Written-scale guard (Nov 2, scope list item 1).

A scale written on a sheet ("1/4\" = 1'-0\"") is only right on a print of
the size it was drawn for. Applying a written scale to a reduced print
(a 24x36 sheet printed 11x17) halves every quantity, so before a written
scale is used this says when the page doesn't look like a full-size
sheet - and which other pages share this page's size, for applying the
same scale to more of the set.

Nothing here changes the drawing; the caller shows the warning."""
import re
from .dmoney import c2 as _c2

# sheet sizes in inches (short side, long side)
SHEETS = {
    "ANSI A (8.5x11)": (8.5, 11), "ANSI B (11x17)": (11, 17),
    "ANSI C (17x22)": (17, 22), "ANSI D (22x34)": (22, 34),
    "ANSI E (34x44)": (34, 44),
    "ARCH A (9x12)": (9, 12), "ARCH B (12x18)": (12, 18),
    "ARCH C (18x24)": (18, 24), "ARCH D (24x36)": (24, 36),
    "ARCH E1 (30x42)": (30, 42), "ARCH E (36x48)": (36, 48),
}
SMALL = {"ANSI A (8.5x11)", "ANSI B (11x17)", "ARCH A (9x12)",
         "ARCH B (12x18)"}
TOL = 0.35                   # inches

_REDUCED = re.compile(
    r"\b(half[\s-]*size|1/2\s*size|reduced\s+(?:print|size|copy|set)|"
    r"(?:scale|scales)\s+(?:shown\s+)?(?:is|are|valid)\s+(?:only\s+)?"
    r"(?:for|on|at)\s+(?:a\s+)?(?:full[\s-]*size|\d{2}\s*[\"x×]\s*\d{2}))",
    re.I)
_ARCH = re.compile(r"\d+(?:/\d+)?\s*\"\s*=\s*1\s*'", re.I)


def size_in(page):
    """(short, long) side of the page in inches."""
    r = page.rect
    a, b = sorted((r.width / 72.0, r.height / 72.0))
    return _c2(a), _c2(b)


def sheet_name(page):
    """The standard sheet size the page is, or None."""
    a, b = size_in(page)
    for name, (x, y) in SHEETS.items():
        if abs(a - x) <= TOL and abs(b - y) <= TOL:
            return name
    return None


def _same(s1, s2):
    return abs(s1[0] - s2[0]) <= TOL and abs(s1[1] - s2[1]) <= TOL


def common_size(doc, limit=400):
    """The page size most of the set is, as (short, long), or None."""
    seen = []
    for i in range(min(doc.page_count, limit)):
        s = size_in(doc[i])
        for row in seen:
            if _same(row[0], s):
                row[1] += 1
                break
        else:
            seen.append([s, 1])
    if not seen:
        return None
    seen.sort(key=lambda r: -r[1])
    return seen[0][0]


def check(doc, pno, scale_name=""):
    """Reasons a written scale may be wrong on page `pno` ([] if none):
    the sheet says it's a reduced/half-size print, it is a small sheet
    while the scale is an architectural one meant for a full-size
    drawing, or it is a different size from most of the set."""
    page = doc[pno]
    out = []
    try:
        text = page.get_text("text")
    except Exception:
        text = ""
    m = _REDUCED.search(text or "")
    if m:
        out.append(f'The sheet says "{m.group(0).strip()}": a written scale '
                   "is for the full-size print, so it is off on this one.")
    name = sheet_name(page)
    a, b = size_in(page)
    if name in SMALL and _ARCH.search(scale_name or ""):
        out.append(f"This page is {name}. Plans at {scale_name} are "
                   "usually drawn on a larger sheet, so if this is a "
                   "reduced print the written scale makes every quantity "
                   "too small.")
    common = common_size(doc)
    if common and doc.page_count > 2 and not _same(common, (a, b)):
        out.append(f"This page is {a:g}x{b:g} in, but most of the set is "
                   f"{common[0]:g}x{common[1]:g} in.")
    if out:
        out.append("Check it: Takeoff > Calibrate on a dimension you know.")
    return out


def pages_like(doc, pno):
    """0-based pages the same size as page `pno` (it included)."""
    s = size_in(doc[pno])
    return [i for i in range(doc.page_count) if _same(size_in(doc[i]), s)]


def parse_pages(text, count):
    """'1-3, 5, 8-' -> [0, 1, 2, 4, 7, ...]: 1-based page numbers and
    ranges, within 1..count; None if unreadable."""
    out = []
    for part in re.split(r"[,;\s]+", (text or "").strip()):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)?\s*-\s*(\d+)?|(\d+)", part)
        if not m:
            return None
        if m.group(3):
            lo = hi = int(m.group(3))
        else:
            lo = int(m.group(1) or 1)
            hi = int(m.group(2) or count)
        if lo < 1 or hi < lo:
            return None
        out.extend(i - 1 for i in range(lo, min(hi, count) + 1))
    return sorted(set(out)) or None
