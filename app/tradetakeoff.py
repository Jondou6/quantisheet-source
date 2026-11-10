"""Trade takeoff: automatic quantities for the trades Beam AI and similar
services do by hand-checked AI - read from the sheet's own linework and
text, in seconds, as ordinary editable measurements.

* Pipe, conduit and other runs (mep_runs): MEP drawings draw each system
  in its own line style (colour, weight, dash). Lines are grouped by style,
  joined into runs, and each run is named from the size label printed along
  it ("4\\" CW", "3/4\\"C", "2\\" G"). You tick which systems to take off.
* Ductwork (ducts): a duct is two parallel lines its width apart; pairs
  4" to 72" apart in one style become duct centerlines, sized from the tag
  beside them ("24x12", "14\\"Ø") with sheet-metal area and weight (SMACNA
  gauge by the larger side).
* Fixtures and devices from the legend (legend_counts): each symbol in the
  sheet's legend is cut out and counted on every sheet, named by its
  description ("DUPLEX RECEPTACLE", "WATER CLOSET").
* Roofing (roof_areas): plan areas become sloped areas from the pitch
  printed on the roof plan ("6:12"), with squares, waste and perimeter.
* Rebar (rebar_schedule): bars, laps, counts and weight from footing and
  slab takeoff, by bar size and spacing.
* Earthwork (cut_fill): existing and proposed contours, each named by its
  elevation label, interpolated on a grid inside the site boundary; cut,
  fill and net in cubic yards.

Everything returns plain data; marks() helpers turn it into viewer marks
(page, kind, payload) with the method recorded for the audit trail.
"""
import math
import re

import fitz

from . import autowalls
from .dmoney import half_up as _hu
from .dmoney import c2 as _c2

# ------------------------------------------------------------- styles
def _rgb(c):
    if not c:
        return None
    return tuple(round(float(v) * 20) / 20 for v in c[:3])


def _dash(d):
    if not d:
        return ""
    d = str(d).strip()
    if d.startswith("[]") or d in ("[ ] 0", "[] 0"):
        return ""
    nums = re.findall(r"[\d.]+", d.split("]")[0])
    return " ".join(f"{float(n):g}" for n in nums)


def _bez(p0, p1, p2, p3, n=8):
    out = []
    for i in range(n + 1):
        t = i / n
        m = 1 - t
        out.append((m ** 3 * p0.x + 3 * m * m * t * p1.x +
                    3 * m * t * t * p2.x + t ** 3 * p3.x,
                    m ** 3 * p0.y + 3 * m * m * t * p1.y +
                    3 * m * t * t * p2.y + t ** 3 * p3.y))
    return out


def styled_segments(page):
    """{style: [(x0, y0, x1, y1)]}; style = (rgb, width, dashes)."""
    out = {}
    try:
        paths = page.get_drawings()
    except Exception:
        return out
    for p in paths:
        if p.get("type") == "f":                    # fill only, no stroke
            continue
        key = (_rgb(p.get("color")), round(float(p.get("width") or 0) * 4)
               / 4, _dash(p.get("dashes")))
        segs = out.setdefault(key, [])
        for it in p.get("items", ()):
            k = it[0]
            if k == "l":
                a, b = it[1], it[2]
                segs.append((a.x, a.y, b.x, b.y))
            elif k == "c":
                pts = _bez(*it[1:5])
                segs += [(pts[i][0], pts[i][1], pts[i + 1][0],
                          pts[i + 1][1]) for i in range(len(pts) - 1)]
            elif k == "re":
                r = fitz.Rect(it[1])
                q = [r.tl, r.tr, r.br, r.bl]
                segs += [(q[i].x, q[i].y, q[(i + 1) % 4].x, q[(i + 1) % 4].y)
                         for i in range(4)]
            elif k == "qu":
                q = it[1]
                pts = [q.ul, q.ur, q.lr, q.ll]
                segs += [(pts[i].x, pts[i].y, pts[(i + 1) % 4].x,
                          pts[(i + 1) % 4].y) for i in range(4)]
    return {k: _dedupe(v) for k, v in out.items() if v}


def _dedupe(segs, q=0.5):
    """Drop repeats: the same segment drawn twice, or back the other
    way (MuPDF reports some strokes both ways)."""
    seen, out = set(), []
    for s in segs:
        a = (round(s[0] / q), round(s[1] / q))
        b = (round(s[2] / q), round(s[3] / q))
        k = (a, b) if a <= b else (b, a)
        if k in seen or a == b:
            continue
        seen.add(k)
        out.append(s)
    return out


def style_name(style):
    rgb, w, dash = style
    if rgb is None:
        col = "no colour"
    else:
        r, g, b = rgb
        if max(rgb) - min(rgb) < 0.1:
            col = "black" if r < 0.25 else "dark grey" if r < 0.55 else \
                "grey" if r < 0.85 else "light grey"
        else:
            names = {"red": (1, 0, 0), "green": (0, .6, 0), "blue": (0, 0, 1),
                     "cyan": (0, .7, .9), "magenta": (.9, 0, .9),
                     "yellow": (.9, .8, 0), "orange": (1, .5, 0),
                     "purple": (.5, 0, .7), "brown": (.55, .3, .1)}
            col = min(names, key=lambda n: sum((a - b) ** 2 for a, b in
                                               zip(rgb, names[n])))
    return f"{col}, {w:g} pt" + (", dashed" if dash else "")


# ------------------------------------------------------------- runs
def _key(x, y, tol):
    return (round(x / tol), round(y / tol))


def runs(segs, tol=1.5):
    """Join segments that meet end to end into runs (polylines); a tee
    or cross starts new runs. [[(x, y), ...]]."""
    nodes, adj = {}, {}
    edges = []
    for x0, y0, x1, y1 in segs:
        if math.hypot(x1 - x0, y1 - y0) < 0.2:
            continue
        a, b = _key(x0, y0, tol), _key(x1, y1, tol)
        if a == b:
            continue
        nodes.setdefault(a, (x0, y0))
        nodes.setdefault(b, (x1, y1))
        e = len(edges)
        edges.append((a, b))
        adj.setdefault(a, []).append(e)
        adj.setdefault(b, []).append(e)
    used = [False] * len(edges)
    out = []

    def walk(start, e):
        pts = [nodes[start]]
        cur = start
        while True:
            used[e] = True
            a, b = edges[e]
            nxt = b if a == cur else a
            pts.append(nodes[nxt])
            cur = nxt
            nexts = [f for f in adj[cur] if not used[f]]
            if len(adj[cur]) != 2 or not nexts:
                return pts
            e = nexts[0]
    for n, es in adj.items():                 # ends and branch points first
        if len(es) != 2:
            for e in es:
                if not used[e]:
                    out.append(walk(n, e))
    for e in range(len(edges)):               # closed loops left over
        if not used[e]:
            out.append(walk(edges[e][0], e))
    return out


def poly_len(pts):
    return sum(math.hypot(b[0] - a[0], b[1] - a[1])
               for a, b in zip(pts, pts[1:]))


def _seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - ax) * dx +
                                              (py - ay) * dy) / L))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def dist_to_poly(pt, pts):
    return min((_seg_dist(pt[0], pt[1], a[0], a[1], b[0], b[1])
                for a, b in zip(pts, pts[1:])), default=1e18)


# ------------------------------------------------------------- labels
_SZ = r"(\d+\s*-\s*\d/\d|\d+\s+\d/\d|\d/\d|\d+(?:\.\d+)?)"
PIPE_RE = re.compile(
    rf"^{_SZ}\s*(?:\"|''|IN\.?|Ø|DIA\.?)?\s*-?\s*"
    r"(CW|DCW|HW|DHW|HWR|HWC|TW|TMV|SAN|SS|W|V|VTR|ST|STM|SD|RD|ORD|OD|G|"
    r"GAS|NG|LP|FP|FS|SP|F|CHW|CHWS|CHWR|HHW|HHWS|HHWR|HWS|CWS|CWR|CD|COND|"
    r"CA|MA|A|AW|FOS|FOR|RL|RS|HG|IW|PW|DI|RO|VAC|O2|N2O)$", re.I)
COND_RE = re.compile(
    rf"^{_SZ}\s*(?:\"|'')?\s*-?\s*(C|EMT|RGS|GRC|PVC|IMC|FMC|MC|CONDUIT|CO)$",
    re.I)
DUCT_RE = re.compile(r"^(\d{1,3})\s*(?:\"|'')?\s*[xX×/]\s*(\d{1,3})"
                     r"\s*(?:\"|'')?$")
ROUND_RE = re.compile(r"^(\d{1,3})\s*(?:\"|'')?\s*(?:Ø|DIA\.?|RD|ROUND|"
                      r"⌀)$", re.I)
# roof pitch: 6:12, 6/12, 6 IN 12, 6 ON 12, and rise per foot as the
# architects write it on roof plans: 5"/1'-0", 2"/1'-0", 1/4"/1'-0",
# 1/4" PER FT, with an optional SLOPE / PITCH word before or after
_RISE = r"(\d{1,2}\s*-\s*\d/\d{1,2}|\d{1,2}\s+\d/\d{1,2}|\d/\d{1,2}|" \
        r"\d{1,2}(?:\.\d+)?)"
PITCH_RE = re.compile(
    rf"^(?:(?:ROOF\s+)?(?:PITCH|SLOPE)\s*[:=]?\s*)?{_RISE}\s*(?:\"|'')?\s*"
    r"(?::|/|\s+IN\s+|\s+ON\s+|\s*PER\s+|\s+TO\s+)\s*"
    r"(?:12\s*(?:\"|'')?|1\s*'\s*-?\s*0\s*(?:\"|'')?|FT\.?|FOOT)"
    r"(?:\s+(?:PITCH|SLOPE|TYP\.?|MIN\.?))?$", re.I)
_QUOTES = str.maketrans({"″": '"', "”": '"', "“": '"',
                         "′": "'", "’": "'", "‘": "'",
                         "‐": "-", "‑": "-", "–": "-"})


def _rise(text):
    """'5' -> 5.0, '1/4' -> 0.25, '1-1/2' or '1 1/2' -> 1.5."""
    t = re.sub(r"\s+", " ", text.strip())
    m = re.match(r"^(\d+)\s*[- ]\s*(\d+)/(\d+)$", t)
    if m:
        return int(m.group(1)) + int(m.group(2)) / max(1, int(m.group(3)))
    m = re.match(r"^(\d+)/(\d+)$", t)
    if m:
        return int(m.group(1)) / max(1, int(m.group(2)))
    return float(t)


def _pitch_rise(text):
    """The rise per 12 a pitch label states, or None (not a pitch label)."""
    t = (text or "").translate(_QUOTES).strip()
    m = PITCH_RE.match(t)
    if not m:
        return None
    try:
        v = _rise(m.group(1))
    except ValueError:
        return None
    return v if v > 0 else None


def pitch_value(text):
    """The rise in inches per 12 for a pitch label, or None: '6:12' -> 6,
    '5"/1\\'-0"' -> 5, '1/4" PER FT' -> 0.25. Pitch is capped at 12:12
    (calculators.MAX_PITCH): a steeper label is None here and is listed by
    steep_pitch_labels() as out of range."""
    from .calculators import MAX_PITCH
    v = _pitch_rise(text)
    return v if v is not None and v <= MAX_PITCH else None


def steep_pitch_labels(page):
    """[(label text, rise)] for pitch labels steeper than 12:12 - out of
    range, never used."""
    from .calculators import MAX_PITCH
    out = []
    for text, _r in phrases(page, 5):
        v = _pitch_rise(text)
        if v is not None and v > MAX_PITCH and \
                not any(t in text or text in t for t, _v in out):
            out.append((text, v))
    return out


ELEV_RE = re.compile(r"^(?:EL\.?\s*|ELEV\.?\s*)?(\d{1,4}(?:\.\d{1,2})?)'?$")


def phrases(page, max_words=3):
    """Words and short runs of words on one line: [(text, rect)]. Labels
    like '4" CW' are often two words."""
    words = page.get_text("words")
    rows = {}
    for w in words:
        rows.setdefault((w[5], w[6]), []).append(w)
    out = []
    for ws in rows.values():
        ws.sort(key=lambda w: w[0])
        for i in range(len(ws)):
            r = fitz.Rect(ws[i][:4])
            text = ws[i][4]
            out.append((text, fitz.Rect(r)))
            for j in range(i + 1, min(len(ws), i + max_words)):
                gap = ws[j][0] - ws[j - 1][2]
                if gap > (ws[j][3] - ws[j][1]) * 1.2:
                    break
                text += " " + ws[j][4]
                r |= fitz.Rect(ws[j][:4])
                out.append((text, fitz.Rect(r)))
    return out


# a tag for existing work: "EX. 4" W", "EXIST 2" CW", "2" W (E)",
# "(E) 3" SAN", "6" W EXISTING"
_EX_WORD = re.compile(r"^\(?(?:EX|EXIST|EXISTING|E)\)?\.?[,:;]?$", re.I)
_EX_TAIL = re.compile(r"\s*\((?:EXISTING|EXIST|EX|E)\.?\)\s*$", re.I)
_EX_HEAD = re.compile(r"^\s*(?:\((?:EXISTING|EXIST|EX|E)\.?\)|"
                      r"EXISTING\b|EXIST\.|EXIST\b|EX\.)\s*", re.I)


def _is_ex_word(w, after=False):
    w = (w or "").strip()
    if not _EX_WORD.match(w):
        return False
    bare = w.upper().strip(".,:;")
    if w.startswith("("):
        return True
    # a bare E is a compass point or a grid line; after a size tag a bare
    # EX is more likely exhaust ("10\" EX") - only EXIST / EXISTING there
    if bare == "E":
        return False
    return not (after and bare == "EX")


def phrases_ctx(page, max_words=3):
    """Like phrases(), with the word just before and just after each
    phrase on its line: [(text, rect, prev, next)] ('' when none)."""
    words = page.get_text("words")
    rows = {}
    for w in words:
        rows.setdefault((w[5], w[6]), []).append(w)
    out = []
    for ws in rows.values():
        ws.sort(key=lambda w: w[0])

        def near(a, b):
            return ws[b][0] - ws[a][2] <= (ws[b][3] - ws[b][1]) * 1.2
        for i in range(len(ws)):
            prev = ws[i - 1][4] if i > 0 and near(i - 1, i) else ""
            r = fitz.Rect(ws[i][:4])
            text = ws[i][4]
            nxt = ws[i + 1][4] if i + 1 < len(ws) and near(i, i + 1) else ""
            out.append((text, fitz.Rect(r), prev, nxt))
            for j in range(i + 1, min(len(ws), i + max_words)):
                if not near(j - 1, j):
                    break
                text += " " + ws[j][4]
                r |= fitz.Rect(ws[j][:4])
                nxt = ws[j + 1][4] if j + 1 < len(ws) and near(j, j + 1) \
                    else ""
                out.append((text, fitz.Rect(r), prev, nxt))
    return out


def _norm_size(s):
    s = re.sub(r"\s+", " ", s.strip())
    s = re.sub(r"(\d)\s*-\s*(\d/\d)", r"\1-\2", s)
    s = re.sub(r"(\d) (\d/\d)", r"\1-\2", s)
    return s


_FRAC_FIRST = re.compile(r"^(\d/\d{1,2})(.*)$")


def _bubbles(page):
    """Small closed outlines (circles, hexagons, diamonds, boxes) drawn on
    the sheet - where keynote and detail bubbles are."""
    out = []
    try:
        drawings = page.get_drawings()
    except Exception:                                     # noqa: BLE001
        return out
    for d in drawings:
        rc = fitz.Rect(d.get("rect") or (0, 0, 0, 0))
        if rc.is_empty or max(rc.width, rc.height) > 60 or \
                min(rc.width, rc.height) < 2:
            continue
        if max(rc.width, rc.height) > 2.0 * min(rc.width, rc.height):
            continue
        items = d.get("items") or []
        curves = any(it[0] == "c" for it in items)
        closed = d.get("closePath") or curves or len(items) >= 3 or \
            any(it[0] in ("re", "qu") for it in items)
        if closed:
            out.append(rc)
    return out


def _keynote_between(wr, r, h, bubbles):
    """True when the number at `wr` sits in a bubble (one that doesn't
    hold the tag `r` too), or a bubble is drawn in the gap between the
    number and the tag."""
    c = fitz.Point((wr.x0 + wr.x1) / 2, (wr.y0 + wr.y1) / 2)
    tc = fitz.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
    gap = fitz.Rect(min(wr.x1, r.x0), min(wr.y0, r.y0),
                    max(wr.x1, r.x0), max(wr.y1, r.y1)) \
        if wr.x1 <= r.x0 else fitz.Rect(min(r.x1, wr.x0), min(wr.y0, r.y0),
                                         max(r.x1, wr.x0), max(wr.y1, r.y1))
    for b in bubbles:
        if b.contains(tc) or max(b.width, b.height) > 4 * h:
            continue
        if b.contains(c):
            return True
        bc = fitz.Point((b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2)
        if gap.width > 0 and gap.x0 <= bc.x <= gap.x1 and \
                gap.y0 - h <= bc.y <= gap.y1 + h:
            return True               # the bubble sits between them
    return False


_WHOLE_FRAC = re.compile(r"^\d{1,2}-\d/\d")


def _drop_keynote_joins(page, tags):
    """H4: a phrase read as '3 1/2"CW' whose '3' is a keynote number (in
    its own bubble, or a bubble drawn between it and the tag) is not a
    3-1/2" pipe: the phrase is dropped (the tag on its own, '1/2"CW', is
    read from the next word). Changes `tags` in place."""
    joined = [t for t in tags if t["kind"] in ("pipe", "conduit") and
              _WHOLE_FRAC.match(t["name"])]
    if not joined:
        return
    words = page.get_text("words")
    bubbles = _bubbles(page)
    if not bubbles:
        return
    drop = []
    for t in joined:
        r = t["rect"]
        h = max(1.0, min(r.width, r.height))
        whole = t["name"].split("-")[0]
        for w in words:
            wr = fitz.Rect(w[:4])
            if w[4] != whole or not r.contains(wr) or wr.width >= r.width:
                continue
            if wr.x0 - r.x0 < 0.5 * h:            # the phrase's first word
                rest = fitz.Rect(wr.x1 + 0.5, r.y0, r.x1, r.y1)
                if _keynote_between(wr, rest, h, bubbles):
                    drop.append(t)
                break
    for t in drop:
        tags.remove(t)


def _whole_fractions(page, tags):
    """'1' and '1/2"V' set as two text pieces (often in separate text
    blocks, so not one phrase) are 1-1/2" V, not 1/2" V: a pipe or
    conduit tag whose size is a bare fraction takes a whole number printed
    right next to it in line with it (before it in reading order - which
    on text turned to run up, down or upside down can be any side).""" 
    fr = [t for t in tags if t["kind"] in ("pipe", "conduit") and
          _FRAC_FIRST.match(t["name"])]
    if not fr:
        return
    words = page.get_text("words")
    bubbles = None
    # a sheet turned a quarter on the page: text level in the page's own
    # coordinates runs up or down the sheet as displayed (P-101), so the
    # whole number can be either side
    turned = page.rotation % 180 == 90
    for t in fr:
        r = t["rect"]
        # the text's height: the short side for a one-word tag (it may run
        # up the sheet, rotated)
        h = max(1.0, min(r.width, r.height))
        best = None
        for w in words:
            if not re.fullmatch(r"\d{1,2}", w[4]):
                continue
            wr = fitz.Rect(w[:4])
            if wr.intersects(r) and (wr & r).get_area() > 0.5 * \
                    wr.get_area():
                continue                         # part of the tag itself
            if bubbles is None:
                bubbles = _bubbles(page)
            if _keynote_between(wr, r, h, bubbles):
                continue          # a keynote number, not the size (H4)
            dx = max(0.0, max(r.x0 - wr.x1, wr.x0 - r.x1))
            dy = max(0.0, max(r.y0 - wr.y1, wr.y0 - r.y1))
            gap = math.hypot(dx, dy)
            if gap > 1.2 * h:
                continue
            cx, cy = (wr.x0 + wr.x1) / 2, (wr.y0 + wr.y1) / 2
            in_row = r.y0 - 0.2 * h <= cy <= r.y1 + 0.2 * h
            in_col = r.x0 - 0.2 * h <= cx <= r.x1 + 0.2 * h
            # along the text's own line only: a "1" in the next column of
            # a row of tags set up the sheet belongs to that tag
            upright = r.height > 1.5 * r.width
            if not (in_col if upright else in_row):
                continue
            if r.width > 1.5 * r.height and cx > r.x0 and not turned:
                continue                 # level text reads left to right
                # (text set at an angle has a squarish box: any side)
            if best is None or gap < best[0]:
                best = (gap, w[4], wr)
        if best:
            _g, whole, wr = best
            m = _FRAC_FIRST.match(t["name"])
            t["name"] = f"{whole}-{m.group(1)}{m.group(2)}"
            t["rect"] = fitz.Rect(r) | wr
            t["center"] = ((t["rect"].x0 + t["rect"].x1) / 2,
                           (t["rect"].y0 + t["rect"].y1) / 2)


def labels(page):
    """Size tags on the sheet: [{kind: pipe|conduit|duct|round, name,
    w, h (inches, ducts), center, rect, existing}]. `existing` is set for
    tags marked as existing work (EX., EXIST., (E), EXISTING) - those are
    not new work."""
    out = []
    seen = set()
    for text, r, prev, nxt in phrases_ctx(page):
        t = text.strip().translate(_QUOTES)
        existing = False
        if _EX_TAIL.search(t):
            t, existing = _EX_TAIL.sub("", t), True
        if _EX_HEAD.match(t):
            t, existing = _EX_HEAD.sub("", t), True
        t = t.strip().strip(",;()")
        if _is_ex_word(prev) or _is_ex_word(nxt, after=True):
            existing = True
        kind = name = None
        w = h = None
        m = PIPE_RE.match(t)
        if m:
            kind, name = "pipe", f"{_norm_size(m.group(1))}\" " \
                f"{m.group(2).upper()}"
        else:
            m = COND_RE.match(t)
            if m:
                kind, name = "conduit", f"{_norm_size(m.group(1))}\" " \
                    f"{m.group(2).upper().replace('CONDUIT', 'C')}"
            else:
                m = DUCT_RE.match(t)
                if m and 4 <= int(m.group(1)) <= 120 and \
                        3 <= int(m.group(2)) <= 120:
                    kind, w, h = "duct", int(m.group(1)), int(m.group(2))
                    name = f"{w}x{h}"
                else:
                    m = ROUND_RE.match(t)
                    if m and 3 <= int(m.group(1)) <= 60:
                        kind, w = "round", int(m.group(1))
                        name = f"{w}\" round"
        if not kind:
            continue
        key = (kind, name, round(r.x0), round(r.y0))
        if key in seen:
            continue
        seen.add(key)
        out.append({"kind": kind, "name": name, "w": w, "h": h,
                    "center": ((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2),
                    "rect": r, "existing": existing})
    _drop_keynote_joins(page, out)
    _whole_fractions(page, out)
    # a phrase and the words inside it both matching: keep the longest
    # (and existing if either says so: "EX. 4\" W" holds "4\" W")
    out.sort(key=lambda l: -l["rect"].width)
    kept = []
    for l in out:
        inside = [k for k in kept if k["rect"].contains(l["rect"]) and
                  k["kind"] == l["kind"]]
        if inside:
            if l["existing"]:
                for k in inside:
                    k["existing"] = True
            continue
        kept.append(l)
    return kept


def _per_ft(ppu, unit):
    return ppu * {"ft": 1.0, "in": 12.0, "m": 0.3048,
                  "yd": 1 / 3.0}.get(unit, 1.0)


# ------------------------------------------------------------- pipe runs
def _bbox(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return (min(xs), min(ys), max(xs), max(ys))


def _rect_seg_dist(rc, a, b):
    """Distance from rectangle (x0, y0, x1, y1) to segment a-b (0 when
    they touch or cross)."""
    x0, y0, x1, y1 = rc

    def inside(p):
        return x0 <= p[0] <= x1 and y0 <= p[1] <= y1
    if inside(a) or inside(b):
        return 0.0
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    for i in range(4):                       # crossing an edge
        c, d = corners[i], corners[(i + 1) % 4]
        if _cross(a, b, c, d):
            return 0.0
    d = min(_seg_dist(c[0], c[1], a[0], a[1], b[0], b[1]) for c in corners)
    for p in (a, b):
        dx = max(x0 - p[0], 0, p[0] - x1)
        dy = max(y0 - p[1], 0, p[1] - y1)
        d = min(d, math.hypot(dx, dy))
    return d


def _cross(a, b, c, d):
    def o(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    d1, d2 = o(c, d, a), o(c, d, b)
    d3, d4 = o(a, b, c), o(a, b, d)
    return (d1 * d2 < 0) and (d3 * d4 < 0)


def _unit(dx, dy):
    L = math.hypot(dx, dy)
    return (dx / L, dy / L) if L else (0.0, 0.0)


class _Grid:
    """A coarse spatial hash of boxes, for 'what is near here' lookups."""

    def __init__(self, cell):
        self.cell = max(1.0, cell)
        self.cells = {}

    def _span(self, x0, y0, x1, y1):
        c = self.cell
        for gx in range(int(math.floor(x0 / c)), int(math.floor(x1 / c)) + 1):
            for gy in range(int(math.floor(y0 / c)),
                            int(math.floor(y1 / c)) + 1):
                yield gx, gy

    def add(self, box, item):
        for k in self._span(*box):
            self.cells.setdefault(k, []).append(item)

    def near(self, box, pad=0.0):
        x0, y0, x1, y1 = box
        seen = set()
        for k in self._span(x0 - pad, y0 - pad, x1 + pad, y1 + pad):
            for it in self.cells.get(k, ()):
                if it not in seen:
                    seen.add(it)
                    yield it


def _size_in(name):
    """Nominal size in inches of a pipe tag name ('1-1/2" CW' -> 1.5)."""
    m = re.match(r"^\s*(\d+)-(\d+)/(\d+)\"|^\s*(\d+)/(\d+)\"|"
                 r"^\s*(\d+(?:\.\d+)?)\"", name or "")
    if not m:
        return None
    if m.group(1):
        return int(m.group(1)) + int(m.group(2)) / int(m.group(3))
    if m.group(4):
        return int(m.group(4)) / int(m.group(5))
    return float(m.group(6))


# standard outside diameters (in) of pipe by nominal size (NPS / DWV)
PIPE_OD_IN = {0.5: 0.84, 0.75: 1.05, 1.0: 1.315, 1.25: 1.66, 1.5: 1.9,
              2.0: 2.375, 2.5: 2.875, 3.0: 3.5, 4.0: 4.5, 5.0: 5.563,
              6.0: 6.625, 8.0: 8.625, 10.0: 10.75, 12.0: 12.75}


def od_window(d):
    """The spacing (in) of a double-line pipe drawn at nominal size d: from
    its nominal size (or half-way to the next smaller size's outside
    diameter, if lower) to half-way to the next larger size's OD (at least
    +/-8% of its OD for drawing tolerance) - so a pair drawn at the next
    size's diameter is not this size."""
    sizes = sorted(PIPE_OD_IN)
    if d not in PIPE_OD_IN:
        od = d + 0.4
        return 0.9 * od, 1.15 * od
    i = sizes.index(d)
    od = PIPE_OD_IN[d]
    lo = (od + PIPE_OD_IN[sizes[i - 1]]) / 2 if i else 0.75 * od
    hi = (od + PIPE_OD_IN[sizes[i + 1]]) / 2 if i + 1 < len(sizes) \
        else 1.15 * od
    # some sets draw the pipe at its nominal size, not its OD
    return min(lo, 0.92 * od, 0.95 * d), max(hi, 1.08 * od)


def close_dash_gaps(rs, max_gap=12.0, tol=1.5, max_turn=3.0, min_chain=3):
    """A dashed line's pieces, closed up: where two runs of one style face
    each other straight on (same direction, no side step over `tol`)
    across a gap of up to `max_gap` points - a dash pattern's gap, about
    1/6" on paper whatever the scale - each end is moved to the middle of
    the gap, so the line measures its whole length, gaps included. The
    pieces stay separate runs (a size can still change from one to the
    next). Returns (runs, linked): `linked` holds the pieces closed up
    with a neighbour - dashes, kept however short they are. Bigger gaps
    (a door in a wall, a break for a tag) and lines that turn or sit side
    by side are left alone."""
    rs = [list(r) for r in rs if len(r) >= 2]
    if len(rs) < 2:
        return rs, set()
    cos_turn = math.cos(math.radians(max_turn))

    def out_dir(r, which):
        if which == 0:
            return _unit(r[0][0] - r[1][0], r[0][1] - r[1][1])
        return _unit(r[-1][0] - r[-2][0], r[-1][1] - r[-2][1])
    ends = _Grid(max(4 * max_gap, 20.0))
    for i, r in enumerate(rs):
        for w in (0, -1):
            ends.add((r[w][0], r[w][1], r[w][0], r[w][1]), (i, w))
    pairs = []
    for i, r in enumerate(rs):
        for w in (0, -1):
            p, d = r[w], out_dir(r, w)
            if d == (0.0, 0.0):
                continue
            for j, wj in ends.near((p[0], p[1], p[0], p[1]), max_gap):
                if j <= i:
                    continue
                q = rs[j][wj]
                v = (q[0] - p[0], q[1] - p[1])
                along = v[0] * d[0] + v[1] * d[1]
                side = abs(v[0] * d[1] - v[1] * d[0])
                if along <= 0 or along > max_gap or side > tol:
                    continue
                dj = out_dir(rs[j], wj)
                if dj[0] * d[0] + dj[1] * d[1] > -cos_turn:
                    continue                     # not the same straight line
                pairs.append((math.hypot(*v), i, w, j, wj))
    pairs.sort()
    used, links = set(), {}
    for g, i, w, j, wj in pairs:
        if (i, w) in used or (j, wj) in used:
            continue
        used.add((i, w))
        used.add((j, wj))
        links[(i, w)] = (j, wj, g)
        links[(j, wj)] = (i, w, g)
    # a dash pattern repeats: only chains of `min_chain` or more pieces
    # whose gaps are mostly alike (three in four within half to twice the
    # chain's middle gap) are closed up - not one-off breaks at a fitting,
    # a tag or a crossing
    seen, linked = set(), set()
    for i in range(len(rs)):
        if i in seen:
            continue
        chain, gaps, todo = {i}, [], [i]
        while todo:
            k = todo.pop()
            for w in (0, -1):
                nx = links.get((k, w))
                if nx and nx[0] not in chain:
                    chain.add(nx[0])
                    gaps.append(nx[2])
                    todo.append(nx[0])
        seen |= chain
        if len(chain) < min_chain or not gaps:
            continue
        med = sorted(gaps)[len(gaps) // 2]
        alike = sum(1 for g in gaps if 0.5 * med <= g <= 2 * med)
        if alike < max(2, 0.75 * len(gaps)):
            continue
        linked |= chain
    for (i, w), (j, wj, _g) in links.items():
        if i in linked and j in linked and (i, w) < (j, wj):
            p, q = rs[i][w], rs[j][wj]
            m = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)
            rs[i][w] = m
            rs[j][wj] = m
    return rs, linked


def _run_neighbours(rs, tol, gap, max_turn=10.0):
    """For runs `rs` of one style: {i: set(j)} where run j touches run i
    (shared end, or a tee: an end on the other's line) or continues it
    in a straight line across a short gap (a line broken for a tag, a
    symbol or a crossing pipe)."""
    segs = _Grid(max(gap, 4 * tol))
    ends = _Grid(max(gap, 4 * tol))
    for i, r in enumerate(rs):
        for k, (a, b) in enumerate(zip(r, r[1:])):
            segs.add((min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]),
                      max(a[1], b[1])), (i, k))
        ends.add((r[0][0], r[0][1], r[0][0], r[0][1]), (i, 0))
        ends.add((r[-1][0], r[-1][1], r[-1][0], r[-1][1]), (i, -1))
    cos_turn = math.cos(math.radians(max_turn))

    def end_dir(r, which):
        # pointing out of the run at that end
        if which == 0:
            return _unit(r[0][0] - r[1][0], r[0][1] - r[1][1])
        return _unit(r[-1][0] - r[-2][0], r[-1][1] - r[-2][1])
    nb = {i: set() for i in range(len(rs))}
    for i, r in enumerate(rs):
        for which in (0, -1):
            p = r[which]
            # touching: this end on any other run's line
            for j, k in segs.near((p[0], p[1], p[0], p[1]), tol):
                if j == i:
                    continue
                a, b = rs[j][k], rs[j][k + 1]
                if _seg_dist(p[0], p[1], a[0], a[1], b[0], b[1]) <= tol:
                    nb[i].add(j)
                    nb[j].add(i)
            # straight on across a gap
            d = end_dir(r, which)
            for j, wj in ends.near((p[0], p[1], p[0], p[1]), gap):
                if j == i or j in nb[i]:
                    continue
                q = rs[j][wj]
                v = (q[0] - p[0], q[1] - p[1])
                L = math.hypot(*v)
                if L > gap or L <= tol:
                    continue
                u = (v[0] / L, v[1] / L)
                dj = end_dir(rs[j], wj)
                if (u[0] * d[0] + u[1] * d[1]) >= cos_turn and \
                        (dj[0] * d[0] + dj[1] * d[1]) <= -cos_turn:
                    nb[i].add(j)
                    nb[j].add(i)
    return nb


def plausible_ft(boxes, per_ft, factor=3.0, density_sf=10.0, floor_ft=60.0):
    """The most pipe of one size a drawing area can plausibly hold, in
    feet: `factor` times the perimeter of the area the system and its
    tags cover, or one foot per `density_sf` of that area (a sprinkler
    grid), whichever is more."""
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[2] for b in boxes)
    y1 = max(b[3] for b in boxes)
    w, h = (x1 - x0) / per_ft, (y1 - y0) / per_ft
    return max(floor_ft, factor * 2 * (w + h), w * h / density_sf)


def _not_pipe_shape(r, per_ft):
    """A run drawn as a closed outline (a cabinet, a fixture, a box) or
    as an arc of short pieces (a door swing) is not a pipe."""
    if len(r) < 4:
        return False
    if math.hypot(r[0][0] - r[-1][0], r[0][1] - r[-1][1]) <= 0.25 * per_ft:
        xs, ys = [p[0] for p in r], [p[1] for p in r]
        # a small closed outline: a cabinet, a fixture, a kennel (a wall
        # or a grid closes too, but is far bigger - left for the checks
        # that catch those)
        return max(max(xs) - min(xs), max(ys) - min(ys)) <= 8.0 * per_ft
    segs = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(r, r[1:])]
    if len(segs) >= 5 and max(segs) < 0.75 * per_ft:
        turn = 0.0
        sign = 0
        for a, b, c in zip(r, r[1:], r[2:]):
            a1 = math.atan2(b[1] - a[1], b[0] - a[0])
            a2 = math.atan2(c[1] - b[1], c[0] - b[0])
            d = (a2 - a1 + math.pi) % (2 * math.pi) - math.pi
            if abs(d) < 1e-6:
                continue
            s_ = 1 if d > 0 else -1
            if sign and s_ != sign:
                return False                   # wiggles: not one arc
            sign = s_
            turn += abs(d)
        # a door swing: an arc as wide as a door (a pipe's long-radius
        # bend is far tighter and must stay - it joins its pipe's runs)
        if math.degrees(turn) >= 45 and \
                poly_len(r) / turn >= 2.25 * per_ft:
            return True
    return False


def mep_runs(page, ppu, unit="ft", min_ft=1.0, reach_ft=4.0, gap_ft=3.0,
             extent_factor=3.0, debug=None):
    """Line-style systems on the sheet: [{style, style_name, name,
    length (unit), runs: [{pts, length, label}], labelled (runs named
    from a tag), suggested (bool), existing (bool), flag (why it needs a
    person, or '')}], longest first.

    Each size tag belongs to the one run that carries it - the nearest
    line to the tag's text, in any style, within `reach_ft` (a short
    leader is followed to the line it points at). From there the size
    spreads only along that style's linework that is connected to the
    tagged run (a shared end or a tee) or continues it straight across a
    gap of up to `gap_ft` - never to other lines just because they are
    near, so walls, casework and dimensions drawn in the same style stay
    out. A system longer than the drawing area can plausibly hold
    (plausible_ft) is flagged and not suggested. Tags marked existing
    (EX., EXIST., (E)) make an existing system, never suggested."""
    per_ft = _per_ft(ppu, unit)
    if per_ft <= 0:
        return []
    tags = [l for l in labels(page) if l["kind"] in ("pipe", "conduit")]
    styles = []
    kinds = []        # per style: run -> "d" dashed, "s" solid, "" short
    for style, segs in styled_segments(page).items():
        closed, dashes = close_dash_gaps(runs(segs))
        keep = [k for k, r in enumerate(closed)
                if (k in dashes or poly_len(r) >= min_ft * per_ft) and
                not _not_pipe_shape(r, per_ft)]
        rs = [closed[k] for k in keep]
        if rs:
            styles.append((style, rs))
            kinds.append(["d" if k in dashes else
                          "s" if poly_len(closed[k]) >= 2.0 * per_ft else ""
                          for k in keep])
    reach = reach_ft * per_ft
    tol = 1.5
    # every run, indexed by its box, to find what a tag sits on
    grid = _Grid(max(reach, 20.0))
    for si, (_st, rs) in enumerate(styles):
        for ri, r in enumerate(rs):
            grid.add(_bbox(r), (si, ri))

    def tag_dist(t, si, ri):
        r = styles[si][1][ri]
        rc = (t["rect"].x0, t["rect"].y0, t["rect"].x1, t["rect"].y1)
        horiz = t["rect"].width >= t["rect"].height
        best = 1e18
        for a, b in zip(r, r[1:]):
            d = _rect_seg_dist(rc, a, b)
            # text runs along its pipe: a line across the text's
            # direction is a worse fit than one along it
            ux, uy = _unit(b[0] - a[0], b[1] - a[1])
            along = abs(ux) if horiz else abs(uy)
            if along < 0.94:
                d += 0.5 * reach
            best = min(best, d)
        return best
    seg_grids = {}
    dbl_cache = {}

    def doubled(si, ri):
        if (si, ri) not in dbl_cache:
            dbl_cache[(si, ri)] = _doubled(si, ri)
        return dbl_cache[(si, ri)]

    def _doubled(si, ri, lo_in=2.0, hi_in=16.0):
        """Share of run ri's length that has a parallel line of the same
        style 2" to 16" off it: a wall's two faces (or a duct), not a
        pipe - pipe is drawn as a single line."""
        rs = styles[si][1]
        if si not in seg_grids:
            g = _Grid(max(hi_in / 12 * per_ft, 20.0))
            for j, q in enumerate(rs):
                for a, b in zip(q, q[1:]):
                    g.add((min(a[0], b[0]), min(a[1], b[1]),
                           max(a[0], b[0]), max(a[1], b[1])), (j, a, b))
            seg_grids[si] = g
        g = seg_grids[si]
        lo, hi = lo_in / 12 * per_ft, hi_in / 12 * per_ft
        r = rs[ri]
        tot = dbl = 0.0
        offs, twins = [], {}
        for a, b in zip(r, r[1:]):
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            if L <= 0:
                continue
            tot += L
            u = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
            best = 0.0
            box = (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]),
                   max(a[1], b[1]))
            for j, c, d in g.near(box, hi):
                if j == ri:
                    continue
                M = math.hypot(d[0] - c[0], d[1] - c[1])
                if M <= 0:
                    continue
                v = ((d[0] - c[0]) / M, (d[1] - c[1]) / M)
                if abs(u[0] * v[1] - u[1] * v[0]) > 0.087:     # 5 degrees
                    continue
                off = abs((c[0] - a[0]) * u[1] - (c[1] - a[1]) * u[0])
                if not lo <= off <= hi:
                    continue
                t1 = (c[0] - a[0]) * u[0] + (c[1] - a[1]) * u[1]
                t2 = (d[0] - a[0]) * u[0] + (d[1] - a[1]) * u[1]
                ov = min(L, max(t1, t2)) - max(0.0, min(t1, t2))
                if ov > best:
                    best, b_off, b_j = ov, off, j
            if best > 0:
                offs.append((min(L, best), b_off))
                twins[b_j] = twins.get(b_j, 0.0) + min(L, best)
            dbl += min(L, max(0.0, best))
        if offs:
            offs.sort(key=lambda o: o[1])
            half, acc = sum(w for w, _o in offs) / 2, 0.0
            for w, o in offs:
                acc += w
                if acc >= half:
                    pair_info[(si, ri)] = (o / per_ft * 12.0,
                                           max(twins, key=twins.get))
                    break
        return dbl / tot if tot else 0.0

    pair_info = {}                       # (si, ri) -> (offset in, twin run)

    def pair_fits(t, si, ri):
        """A doubled run whose two lines sit the tag's pipe size apart (its
        outside diameter drawn to scale) is a double-line pipe, not a wall
        or a duct face."""
        doubled(si, ri)
        info = pair_info.get((si, ri))
        d = _size_in(t["name"])
        if not info or not d:
            return False
        lo, hi = od_window(d)
        return lo <= info[0] <= hi

    def follow_leader(t, d, si, ri):
        r = styles[si][1][ri]
        rc = (t["rect"].x0, t["rect"].y0, t["rect"].x1, t["rect"].y1)
        cx, cy = (rc[0] + rc[2]) / 2, (rc[1] + rc[3]) / 2
        horiz = t["rect"].width >= t["rect"].height
        ux, uy = _unit(r[-1][0] - r[0][0], r[-1][1] - r[0][1])
        across = (abs(ux) if horiz else abs(uy)) < 0.94
        if poly_len(r) >= 6 * per_ft or not across:
            return si, ri
        # a short line leaving the text at an angle is a leader: the tag
        # belongs to the line at its far end
        far = max((r[0], r[-1]), key=lambda p: math.hypot(p[0] - cx,
                                                            p[1] - cy))
        hit = None
        for sj, rj in grid.near((far[0], far[1], far[0], far[1]), tol):
            if sj == si:
                continue
            q = styles[sj][1][rj]
            dd = dist_to_poly(far, q)
            if dd <= tol and poly_len(q) > poly_len(r) and \
                    (hit is None or dd < hit[0]):
                hit = (dd, sj, rj)
        return (hit[1], hit[2]) if hit is not None else (si, ri)
    # each tag's candidate runs, best first, one per style
    cands = []
    for t in tags:
        rc = (t["rect"].x0, t["rect"].y0, t["rect"].x1, t["rect"].y1)
        best = {}
        for si, ri in grid.near(rc, reach):
            d = tag_dist(t, si, ri)
            if d <= reach and (si not in best or d < best[si][0]):
                best[si] = (d, si, ri)
        cs = []
        for d, si, ri in sorted(best.values()):
            sj, rj = follow_leader(t, d, si, ri)
            if doubled(sj, rj) > 0.6 and not pair_fits(t, sj, rj):
                continue                   # a wall or duct face
            cs.append((d, sj, rj))
            if len(cs) == 3:
                break
        # a double-line pipe drawn at this tag's size is the pipe the tag
        # names, even when a thin background line runs a little nearer
        cs.sort(key=lambda c: (not (doubled(c[1], c[2]) > 0.6 and
                                    pair_fits(t, c[1], c[2])), c[0]))
        cands.append(cs)

    def build(choice):
        seeds = {}                           # (si, ri) -> [(dist, tag)]
        for t, cs, k in zip(tags, cands, choice):
            if k < len(cs):
                d, si, ri = cs[k]
                seeds.setdefault((si, ri), []).append((d, t))
        out, bad = [], set()
        for si, (style, rs) in enumerate(styles):
            mine = {ri: sorted(v, key=lambda dv: dv[0])[0][1]
                    for (s, ri), v in seeds.items() if s == si}
            if not mine:
                out.append({"style": style, "style_name": style_name(style),
                            "name": style_name(style),
                            "length": sum(poly_len(r) for r in rs) / ppu,
                            "runs": [{"pts": r, "length": poly_len(r) / ppu,
                                      "label": ""} for r in rs],
                            "labelled": False, "existing": False,
                            "flag": "", "suggested": False})
                continue
            label = {}                         # run -> tag
            nb = _run_neighbours(rs, tol, gap_ft * per_ft)
            # a double-line pipe: its outlines are broken at every coupling
            # and bend (the bend drawn apart, or not at all) - an outline
            # piece links to the next piece of a pipe drawn the same width
            # whose end is within 9", whatever the angle
            dl = [ri for ri in range(len(rs)) if doubled(si, ri) > 0.6 and
                  pair_info.get((si, ri))]
            if dl:
                eg = _Grid(max(0.75 * per_ft, 8.0))
                for ri in dl:
                    for w in (0, -1):
                        p_ = rs[ri][w]
                        eg.add((p_[0], p_[1], p_[0], p_[1]), (ri, w))
                reach_dl = 0.75 * per_ft
                for ri in dl:
                    oi, twin = pair_info[(si, ri)]
                    for w in (0, -1):
                        p_ = rs[ri][w]
                        for rj, wj in eg.near((p_[0], p_[1], p_[0], p_[1]),
                                              reach_dl):
                            if rj == ri or rj == twin or rj in nb[ri]:
                                continue
                            oj, twj = pair_info[(si, rj)]
                            if twj == ri or abs(oi - oj) > 0.6:
                                continue
                            q = rs[rj][wj]
                            if math.hypot(q[0] - p_[0], q[1] - p_[1]) <= \
                                    reach_dl:
                                nb[ri].add(rj)
                                nb[rj].add(ri)
            # outward from every tag at once, nearest along the pipe first
            # (a size holds until the next tag: where a 2" branch meets a
            # 4" main, each run takes the tag closest along the network,
            # not the one fewest hops away); never through a wall's or a
            # duct's double line drawn in the same style
            import heapq
            lens = [poly_len(r) for r in rs]
            heap = []
            # a dashed line (a vent) and a solid one (the waste it rises
            # from) drawn in one pen are two systems: a size never passes
            # from one to the other (short corner pieces go either way)
            # dashes only mean a vent on a single-line pipe: a double-line
            # pipe's outline is broken by its couplings, not dashed
            kd = ["" if k and doubled(si, i) > 0.6 else k
                  for i, k in enumerate(kinds[si])]
            for k, (ri, t) in enumerate(mine.items()):
                heapq.heappush(heap, (0.0, k, ri, t, kd[ri]))
            done = set()
            while heap:
                d, k, ri, t, cls = heapq.heappop(heap)
                if ri in done:
                    continue
                done.add(ri)
                label[ri] = t
                for rj in sorted(nb[ri]):
                    if rj in done or (doubled(si, rj) > 0.6 and
                                      not pair_fits(t, si, rj)):
                        continue
                    if cls and kd[rj] and kd[rj] != cls:
                        continue
                    heapq.heappush(heap, (d + 0.5 * (lens[ri] + lens[rj]),
                                          k, rj, t, kd[rj] or cls))
            if debug is not None:
                for ri, r in enumerate(rs):
                    bx = _bbox(r)
                    if bx[2] < debug[0] or bx[0] > debug[2] or \
                            bx[3] < debug[1] or bx[1] > debug[3]:
                        continue
                    t = label.get(ri)
                    print(f"  [{style_name(style)}] run {ri} "
                          f"{_c2(lens[ri] / per_ft):5.2f} ft kind={kd[ri]!r} "
                          f"dbl={_c2(doubled(si, ri)):.2f} "
                          f"pair={pair_info.get((si, ri))} "
                          f"label={t['name'] if t else None} "
                          f"nb={sorted(nb[ri])[:8]} "
                          f"ends=({r[0][0]:.0f},{r[0][1]:.0f})-"
                          f"({r[-1][0]:.0f},{r[-1][1]:.0f})")
            by = {}
            for ri, r in enumerate(rs):
                t = label.get(ri)
                tw = pair_info.get((si, ri))
                # a double-line pipe has two outlines, each broken at its
                # own couplings: each outline piece counts half when its
                # partner is sized too (pieces pair up unevenly, so
                # halving every piece measures the pipe once)
                w = 0.5 if (t is not None and tw is not None and
                            doubled(si, ri) > 0.6 and
                            label.get(tw[1]) is not None) else 1.0
                key = (t["name"], bool(t.get("existing"))) if t else \
                    ("", False)
                by.setdefault(key, []).append(
                    {"pts": r, "length": w * poly_len(r) / ppu,
                     "label": t["name"] if t else "", "kind": kd[ri]})
            for (lab, ex), its in by.items():
                length = sum(i["length"] for i in its)
                flag = ""
                if lab:
                    bx = [_bbox(i["pts"]) for i in its]
                    bx += [(t["rect"].x0, t["rect"].y0, t["rect"].x1,
                            t["rect"].y1) for t in tags if t["name"] == lab]
                    cap = plausible_ft(bx, per_ft, extent_factor)
                    L_ft = length * ppu / per_ft
                    if L_ft > cap:
                        flag = (f"{L_ft:,.0f} ft is more than the drawing "
                                "area can plausibly hold for one size "
                                f"({cap:,.0f} ft) - lines other than this "
                                "pipe were picked up; measure it by hand")
                        bad.add((si, lab, ex))
                out.append({"style": style, "style_name": style_name(style),
                            "name": (lab + (" (existing)" if ex else ""))
                            if lab else style_name(style),
                            "length": length, "runs": its,
                            "labelled": bool(lab), "existing": ex,
                            "flag": flag,
                            "suggested": bool(lab) and not ex and not flag})
        return out, bad
    choice = [0] * len(tags)
    out, bad = build(choice)
    if bad:
        # a tag whose line spread over far too much (it sat on a wall or
        # a grid line): try its next-best line in another style, once
        moved = False
        for i, (t, cs) in enumerate(zip(tags, cands)):
            if cs and (cs[0][1], t["name"], bool(t.get("existing"))) in bad \
                    and len(cs) > 1:
                choice[i] = 1
                moved = True
        if moved:
            out2, bad2 = build(choice)
            if len(bad2) < len(bad):
                out = out2
    # size tags no single line carries (in a schedule, a riser diagram,
    # beside a wall): listed for a person, never guessed
    orphans = {}
    for t, cs in zip(tags, cands):
        if not cs:
            key = (t["name"], bool(t.get("existing")))
            orphans[key] = orphans.get(key, 0) + 1
    for (lab, ex), n in orphans.items():
        if any(g["labelled"] and g["name"] == lab + (" (existing)" if ex
                                                     else "") for g in out):
            continue                  # the size was found elsewhere
        out.append({"style": None, "style_name": "",
                    "name": lab + (" (existing)" if ex else ""),
                    "length": 0.0, "runs": [], "labelled": True,
                    "existing": ex, "orphan": n,
                    "flag": f"{n} size tag(s) with no single pipe line at "
                            "them - find this pipe by hand",
                    "suggested": False})
    out.sort(key=lambda g: (-g["labelled"], -g["length"]))
    return out


# ------------------------------------------------------------- steel
STEEL_RE = re.compile(
    r"^(W|M|S|HP|C|MC|WT)\s*(\d{1,2}(?:\.\d)?)\s*[xX×]\s*(\d{1,3}(?:\.\d+)?)$"
    r"|^(HSS)\s*(\d{1,2}(?:\.\d+)?)\s*[xX×]\s*(\d{1,2}(?:\.\d+)?)\s*[xX×]"
    r"\s*(\d/\d{1,2}|\.\d+|0?\.\d+)$"
    r"|^(L)\s*(\d{1,2}(?:\.\d+)?)\s*[xX×]\s*(\d{1,2}(?:\.\d+)?)\s*[xX×]"
    r"\s*(\d/\d{1,2}|\d+/\d+|0?\.\d+)$", re.I)


def _frac(t):
    t = t.strip()
    if "/" in t:
        a, b = t.split("/")
        return float(a) / float(b)
    return float(t)


def steel_weight(name):
    """Pounds per foot for a steel shape tag: W12X26 -> 26; HSS and
    angles from their dimensions (steel 3.40 lb per sq in per ft)."""
    m = STEEL_RE.match(name.replace(" ", "").upper())
    if not m:
        return None
    if m.group(1):
        return float(m.group(3))
    if m.group(4):                          # HSS a x b x t
        a, b, t = float(m.group(5)), float(m.group(6)), _frac(m.group(7))
        # nominal wall, less the rounded corners (matches AISC within 2%)
        return _hu((2 * t * (a + b) - 4 * t * t) * 3.40 * 0.973, 2)
    a, b, t = float(m.group(9)), float(m.group(10)), _frac(m.group(11))
    return _hu(t * (a + b - t) * 3.40, 2)


def steel_members(page, ppu, unit="ft", reach_ft=4.0, min_ft=2.0):
    """Framing members tagged with their shape (W12X26, HSS6X6X1/4,
    L4X4X1/2): each tag takes the nearest line drawn near it.
    [{name, lb_ft, count, length, lb, members: [{pts, length}]}]."""
    per_ft = _per_ft(ppu, unit)
    tags = []
    for text, r in phrases(page, 3):
        t = text.strip().strip(",;()")
        if STEEL_RE.match(t.replace(" ", "").upper()):
            tags.append((t.replace(" ", "").upper(),
                         ((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2), r))
    # a tag and the words inside it both matching: keep the longest
    tags.sort(key=lambda t: -t[2].width)
    kept = []
    for t in tags:
        if not any(k[2].contains(t[2]) for k in kept):
            kept.append(t)
    if not kept:
        return []
    cands = []
    for style, segs in styled_segments(page).items():
        for rr in runs(segs):
            L = poly_len(rr)
            if L >= min_ft * per_ft:
                cands.append(rr)
    used = set()
    groups = {}
    reach = reach_ft * per_ft
    for name, c, _r in kept:
        best, bd = None, reach
        for i, rr in enumerate(cands):
            if i in used:
                continue
            d = dist_to_poly(c, rr)
            if d < bd:
                best, bd = i, d
        if best is None:
            continue
        used.add(best)
        rr = cands[best]
        g = groups.setdefault(name, {"name": name,
                                     "lb_ft": steel_weight(name) or 0.0,
                                     "members": []})
        g["members"].append({"pts": rr, "length": poly_len(rr) / ppu})
    out = []
    for g in groups.values():
        g["count"] = len(g["members"])
        g["length"] = sum(m["length"] for m in g["members"])
        g["lb"] = g["length"] * g["lb_ft"]
        g["runs"] = g["members"]
        out.append(g)
    out.sort(key=lambda g: -g["lb"])
    return out


# ------------------------------------------------------------- ducts
GAUGES = [(12, 26, 0.906), (30, 24, 1.156), (54, 22, 1.406),
          (84, 20, 1.656), (999, 18, 2.156)]           # SMACNA, lb/sf


def gauge(larger_in):
    for limit, ga, lb in GAUGES:
        if larger_in <= limit:
            return ga, lb
    return 18, 2.156


def ducts(page, ppu, unit="ft", min_in=4.0, max_in=72.0, reach_ft=8.0):
    """Double-line ductwork: [{name, w, h, length, sf, lb, gauge, pieces:
    [{p0, p1, length, length_ft, width (measured, inches)}]}]."""
    per_ft = _per_ft(ppu, unit)
    tags = [l for l in labels(page) if l["kind"] in ("duct", "round")]
    reach = reach_ft * per_ft
    pieces = []
    for style, segs in styled_segments(page).items():
        if len(segs) < 2:
            continue
        try:
            ws = autowalls.walls(page, ppu, unit, min_t=min_in, max_t=max_in,
                                 segs=segs)
        except autowalls.AutoWallsError:
            continue
        for w in ws:
            w["style"] = style
            pieces.append(w)
    groups = {}
    for w in pieces:
        mid = ((w["p0"][0] + w["p1"][0]) / 2, (w["p0"][1] + w["p1"][1]) / 2)
        best, bd = None, reach
        for t in tags:
            d = dist_to_poly(t["center"], [w["p0"], w["p1"]])
            if d < bd:
                best, bd = t, d
        width = round(w["thickness"])
        if best and best["kind"] == "duct":
            # the tag's first number is the width seen on plan
            name, W, H = best["name"], best["w"], best["h"]
            if abs(W - width) > max(2, 0.25 * W) and \
                    abs(H - width) <= max(2, 0.25 * H):
                W, H = H, W
            per = 2 * (W + H) / 12
            big = max(W, H)
        elif best and best["kind"] == "round":
            name, W, H = best["name"], best["w"], None
            per = math.pi * W / 12
            big = W
        else:
            name, W, H = f"Duct {width}in wide", width, None
            per = 2 * (width + width) / 12        # assumed square
            big = width
        g = groups.setdefault(name, {"name": name, "w": W, "h": H,
                                     "length": 0.0, "sf": 0.0,
                                     "pieces": [], "tagged": bool(best)})
        ga, lbsf = gauge(big)
        L = w["length"]
        if unit != "ft":
            L_ft = L * {"in": 1 / 12, "m": 3.28084, "yd": 3.0}.get(unit, 1)
        else:
            L_ft = L
        g["length"] += L
        g["sf"] += per * L_ft
        g["gauge"], g["lbsf"] = ga, lbsf
        g["pieces"].append({"p0": w["p0"], "p1": w["p1"], "length": L,
                            "mid": mid, "width": w["thickness"],
                            "length_ft": L_ft, "style": w["style"]})
    out = list(groups.values())
    for g in out:
        g["lb"] = g["sf"] * g["lbsf"]
    out.sort(key=lambda g: (-g["tagged"], -g["length"]))
    return out


DUCT_TAG_REACH_FT = 8.0       # a size tag names the duct this close to it
# an untagged duct-style piece far from every tag of its width (another
# drawing on the sheet, an equipment cabinet) isn't given that size:
DUCT_FAR_REACH = 3.0          # x reach: a round size's own width
DUCT_SHARED_REACH = 1.5       # x reach: a width two sizes share
DUCT_JOIN_FT = 3.0            # a piece continues a run from this close
DUCT_BAND = 0.06              # measured width within 6% (>= 3/4") of the tag
DUCT_BAND_MIN_IN = 0.75


DUCT_STYLE_SHARE = 0.25      # a style with this share of the tags' votes


def ducts_by_tag(page, ppu, unit="ft", reach_ft=DUCT_TAG_REACH_FT,
                 join_ft=DUCT_JOIN_FT, info=None):
    """Ducts read from their size tags (AI takeoff): for each size printed
    on the sheet, only pairs of lines that size apart are looked for
    (a 12" round is two lines 12" apart), so a duct's face never pairs
    with a wall or another duct across the room. A piece is that size's
    duct when it runs within `reach_ft` of one of its tags, or continues
    such a piece end to end (within `join_ft`). Only the line styles the
    tagged pieces are drawn in are used (the ductwork's own layer: a 4"
    pair in the background walls or casework near a dryer vent's tag is
    not a duct). Returns (groups, unassigned): groups as ducts() gives
    them (all "tagged"), unassigned [{name, length, why}] - pieces the
    right width in a duct style with no tag near and no tagged piece to
    continue. `info` gets "styles" {style: tagged pieces}."""
    per_ft = _per_ft(ppu, unit)
    k_ft = {"in": 1 / 12, "m": 3.28084, "yd": 3.0}.get(unit, 1.0) \
        if unit != "ft" else 1.0
    tags = [l for l in labels(page) if l["kind"] in ("duct", "round") and
            not l.get("existing")]
    if not tags:
        return [], []
    widths = {}
    for t in tags:
        for wd in ((t["w"],) if t["kind"] == "round" else (t["w"], t["h"])):
            if wd:
                widths.setdefault(int(wd), []).append(t)
    styled = {k: v for k, v in styled_segments(page).items() if len(v) >= 2}
    reach, join = reach_ft * per_ft, join_ft * per_ft
    # every piece of every tagged width, with its style
    pieces = []                        # (wd, style, wall, seed tag)
    for wd in sorted(widths):
        band = max(DUCT_BAND_MIN_IN, DUCT_BAND * wd)
        for style, segs in styled.items():
            try:
                ws = autowalls.walls(page, ppu, unit, min_t=wd - band,
                                     max_t=wd + band, segs=segs)
            except autowalls.AutoWallsError:
                continue
            for w in ws:
                if abs(w.get("measured", w["thickness"]) - wd) > band:
                    continue
                best, bd = None, reach
                for t in widths[wd]:
                    d = dist_to_poly(t["center"], [w["p0"], w["p1"]])
                    if d < bd:
                        best, bd = t, d
                pieces.append([wd, style, w, best])
    # the ductwork's style(s): each tag votes for the style of the piece of
    # its size nearest to it (a tag sits on or right beside its duct; a
    # wall in the background is only sometimes near)
    seeds = {}
    for t in tags:
        tw = {t["w"]} if t["kind"] == "round" else {t["w"], t["h"]}
        best, bd = None, reach
        for wd, style, w, _t in pieces:
            if wd not in tw:
                continue
            d = dist_to_poly(t["center"], [w["p0"], w["p1"]])
            if d < bd:
                best, bd = style, d
        if best is not None:
            seeds[best] = seeds.get(best, 0) + 1
    if info is not None:
        info["styles"] = dict(seeds)
    if not seeds:
        return [], []
    top = max(seeds.values())
    duct_styles = {st for st, n in seeds.items()
                   if n >= max(2, DUCT_STYLE_SHARE * top)} or \
        {max(seeds, key=seeds.get)}
    pieces = [p for p in pieces if p[1] in duct_styles]
    changed = True
    while changed:                     # follow each run from its tag
        changed = False
        for p in pieces:
            if p[3] is not None:
                continue
            w = p[2]
            for q in pieces:
                if q[3] is None or q[0] != p[0]:
                    continue
                v = q[2]
                if min(math.hypot(a[0] - b[0], a[1] - b[1])
                       for a in (w["p0"], w["p1"])
                       for b in (v["p0"], v["p1"])) <= join:
                    p[3] = q[3]
                    changed = True
                    break
    # a duct-style piece no tag reaches: its width names it when only one
    # size on the sheet has that width and it is round (only "8\" round"
    # is 8" wide; a rectangular size's plan width could be either side);
    # a width shared by two sizes (10" round and 10x10) takes the nearest
    # tag within 3 x reach, else it is left for review
    for p in pieces:
        if p[3] is not None:
            continue
        wd, w = p[0], p[2]
        names = {t["name"] for t in widths[wd]}
        near = min(dist_to_poly(t["center"], [w["p0"], w["p1"]])
                   for t in widths[wd])
        if len(names) == 1 and widths[wd][0]["kind"] == "round" and \
                near <= DUCT_FAR_REACH * reach:
            p[3] = widths[wd][0]       # a round size: one width, one name
            continue
        best, bd = None, DUCT_SHARED_REACH * reach
        for t in widths[wd]:
            d = dist_to_poly(t["center"], [w["p0"], w["p1"]])
            if d < bd:
                best, bd = t, d
        p[3] = best
    groups, unassigned = {}, {}
    for wd, _style, w, t in pieces:
        L = w["length"]
        if t is None:
            u = unassigned.setdefault(wd, {"name": f"Duct {wd}in wide",
                                           "length": 0.0})
            u["length"] += L
            continue
        name = t["name"]
        if t["kind"] == "round":
            W, H, per = t["w"], None, math.pi * t["w"] / 12
        else:
            W, H = (t["w"], t["h"]) if wd == t["w"] else (t["h"], t["w"])
            per = 2 * (W + H) / 12
        g = groups.setdefault(name, {"name": name, "w": W, "h": H,
                                     "length": 0.0, "sf": 0.0,
                                     "pieces": [], "tagged": True})
        ga, lbsf = gauge(max(W, H or 0))
        g["length"] += L
        g["sf"] += per * L * k_ft
        g["gauge"], g["lbsf"] = ga, lbsf
        mid = ((w["p0"][0] + w["p1"][0]) / 2, (w["p0"][1] + w["p1"][1]) / 2)
        g["pieces"].append({"p0": w["p0"], "p1": w["p1"], "length": L,
                            "mid": mid, "width": w.get("measured",
                                                       w["thickness"]),
                            "length_ft": L * k_ft})
    out = list(groups.values())
    for g in out:
        _through_fittings(g, per_ft, k_ft)
        g["lb"] = g["sf"] * g["lbsf"]
    out.sort(key=lambda g: -g["length"])
    un = [{"name": u["name"], "length": u["length"],
           "why": "duct-width lines with no size tag near and not joined "
                  "to a tagged run - check them"}
          for u in unassigned.values() if u["length"] > 0]
    return out, un


DUCT_FIT_DIAS = 2.5     # a gap this many duct widths long is a fitting


def _dir(pc):
    dx, dy = pc["p1"][0] - pc["p0"][0], pc["p1"][1] - pc["p0"][1]
    n = math.hypot(dx, dy) or 1.0
    return dx / n, dy / n


def _run_on(pa_, pb_, ea, eb, W):
    """Two pieces whose ends ea / eb are near: one run through a fitting
    when they line up (a damper, a transition: the gap runs along them)
    or turn a corner (an elbow); two ducts side by side are not."""
    ua, ub = _dir(pa_), _dir(pb_)
    cos = abs(ua[0] * ub[0] + ua[1] * ub[1])
    gx, gy = eb[0] - ea[0], eb[1] - ea[1]
    if cos > 0.94:                       # parallel: must be in line
        off = abs(gx * ua[1] - gy * ua[0])
        return off <= 0.3 * W
    return cos < 0.34                    # a square-ish turn: an elbow


def _through_fittings(g, per_ft, k_ft):
    """Duct is measured along its centreline through its fittings: the
    straight pieces of one run stop where an elbow, a damper or a
    transition is drawn. Where two pieces of the same size end within
    DUCT_FIT_DIAS duct widths of each other, the gap between them is
    added (each end used once) as g["fittings_length"]."""
    W = max(g["w"] or 0, g.get("h") or 0) / 12.0 * per_ft   # drawing units
    if not W or len(g["pieces"]) < 2:
        g["fittings_length"] = 0.0
        return
    lim = DUCT_FIT_DIAS * W
    ends = []
    for i, pc in enumerate(g["pieces"]):
        ends.append((i, pc["p0"]))
        ends.append((i, pc["p1"]))
    pairs = []
    for a in range(len(ends)):
        for b in range(a + 1, len(ends)):
            ia, pa = ends[a]
            ib, pb = ends[b]
            if ia == ib:
                continue
            d = math.hypot(pa[0] - pb[0], pa[1] - pb[1])
            if 0.05 * W < d <= lim and _run_on(g["pieces"][ia],
                                               g["pieces"][ib], pa, pb, W):
                pairs.append((d, a, b))
    used, add = set(), 0.0
    gaps = []
    for d, a, b in sorted(pairs):
        if a in used or b in used:
            continue
        used.update((a, b))
        d_ft = d / per_ft                     # drawing units -> feet
        L = d_ft / k_ft if k_ft else d_ft      # -> the sheet's unit
        add += L
        pa, pb = ends[a][1], ends[b][1]
        gaps.append({"p0": pa, "p1": pb, "length": L,
                     "mid": ((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2),
                     "width": g["pieces"][ends[a][0]].get("width"),
                     "length_ft": d_ft, "fitting": True})
    g["pieces"] += gaps
    g["fittings_length"] = add
    if add:
        per = (math.pi * g["w"] / 12) if g.get("h") is None else \
            2 * ((g["w"] or 0) + (g["h"] or 0)) / 12
        g["length"] += add
        g["sf"] += per * add * k_ft


# ------------------------------------------------------------- legend
LEGEND_WORDS = ("LEGEND", "SYMBOLS", "SYMBOL", "SCHEDULE OF SYMBOLS")


# words that make a legend line a note, an instruction or a schedule
# entry, not the name of a symbol
_NOTE_WORDS = re.compile(
    r"\b(SEE|SHALL|MUST|REFER|VERIFY|COORDINATE|CONTRACTOR|PROVIDED?|"
    r"INSTALL(ED)?|LOCATED|REQUIRED|UNLESS|NOTED|ALL\s+RELATED|SUBMITTAL|"
    r"REVIEW|ISSUED|REVISIONS?|DRAWINGS?|SPECIFICATIONS?|CODES?|"
    r"STANDARDS?|EDITION|SCHEDULED?|NOTES?)\b", re.I)
_MODEL_NO = re.compile(r"#|\b\d+\.\d{2,}\b|\b[A-Z]{1,3}-\d{2,}\b")
_PROSE = re.compile(r"\b(THE|THAT|WHICH|THESE|THIS|IS|ARE|BE|WILL|WHEN|"
                    r"WHERE|IF)\b", re.I)
# a mounting height after the name: 80" A.F.F., @ 48" AFF
_MOUNTING = re.compile(r"\s+@?\s*\d+(?:\s*-\s*\d+)?\s*(?:\"|'')\s*"
                       r"(?:A\.?F\.?[FG]\.?|ABOVE\b.*)?\s*$", re.I)


def device_label(text, max_words=8, max_len=48):
    """The short name of a legend symbol from its legend line, or None
    when the line is a note, a schedule entry or a sentence:
    'FIRE ALARM MANUAL PULL STATION. MOUNT 48" TO TOP OF BOX' ->
    'FIRE ALARM MANUAL PULL STATION'; 'CEILING / WALL MOUNTED EXIT SIGN -
    SHADING INDICATES FACE(S)' -> 'CEILING / WALL MOUNTED EXIT SIGN';
    'SPILLWAYS THAT MUST BE LOCATED ON FILL MATERIAL.' -> None;
    'ANGLE STOPS, 3/8" SUPPLIES, AND TRAP' -> None."""
    t = re.sub(r"\s+", " ", (text or "").translate(_QUOTES)).strip(" -:")
    if not t:
        return None
    # the name ends at the first sentence break or " - " explanation
    t = re.split(r"\.\s+(?=[A-Z0-9])|\s+[-–—]\s+", t, maxsplit=1)[0]
    t = _MOUNTING.sub("", t).strip(" -:;.")
    if not t or "," in t or ";" in t:
        return None                        # a list, not a name
    if _NOTE_WORDS.search(t) or _MODEL_NO.search(t):
        return None
    words = t.split()
    if len(words) > max_words or len(t) > max_len:
        return None
    if sum(ch.isalpha() for ch in t) < 3:
        return None
    if _PROSE.search(t):
        return None                        # a sentence
    return t


def _heading_line(words, w):
    """The words on the same printed line as word `w`."""
    return [x for x in words if (x[5], x[6]) == (w[5], w[6])]


# a legend runs down its column from the heading: sub-groups (lighting,
# power, fire alarm) are set apart by a blank line or two, not ended
LEGEND_REACH_PT = 1100.0
LEGEND_GAP_PT = 70.0


def legend_rows(page, rejects=None, text_syms=None):
    """[(name, symbol rect)] from the legend(s) on the page: the lines
    below a LEGEND / SYMBOLS heading that have a symbol drawn just to the
    left of a short name (device_label). A line without its own symbol -
    a note, a schedule row, a wrapped line - is never a device. Lines
    that have a symbol but no usable name (a sentence, a list, a model
    number) are added to `rejects` as (text, reason) when it is given,
    so they can be listed for a person instead of dropped unseen.
    `text_syms` (a list, optional) gets (name, text, rect) for legend lines
    whose symbol is only a short word with no linework ("OS" for a wall
    occupancy sensor): those are counted by the word, not a picture."""
    words = page.get_text("words")
    # a sheet turned on the page (P-001 rotated 90): read the legend as it
    # is displayed - text and symbols in displayed coordinates, linework
    # looked up in the page's own
    rot = page.rotation % 360
    to_disp = page.rotation_matrix if rot else None
    to_page = page.derotation_matrix if rot else None
    if rot:
        def _d(w):
            r = fitz.Rect(w[:4]) * to_disp
            return (r.x0, r.y0, r.x1, r.y1) + tuple(w[4:])
        words = [_d(w) for w in words]
    drawings = None
    heads = []
    for w in words:
        if w[4].strip(":").upper() not in ("LEGEND", "SYMBOLS", "SYMBOL"):
            continue
        # a heading stands on its own line ("ELECTRICAL SYMBOLS:"), not
        # inside a sentence ("SEE LEGEND FOR ...")
        ln = _heading_line(words, w)
        if len(ln) > 4 or any(x[4].upper().rstrip(":") in ("SEE", "FOR",
                                                          "REFER", "PER")
                              for x in ln):
            continue
        heads.append(fitz.Rect(w[:4]))
    if not heads:
        return []
    lines = {}
    for w in words:
        lines.setdefault((w[5], w[6]), []).append(w)
    rows = []
    for (b, l), ws in lines.items():
        ws.sort(key=lambda w: w[0])
        r = fitz.Rect(ws[0][:4])
        for w in ws[1:]:
            r |= fitz.Rect(w[:4])
        rows.append((r, " ".join(w[4] for w in ws)))
    out = []
    seen = set()
    for h in heads:
        below = [(r, t) for r, t in rows
                 if h.y1 - 1 <= r.y0 <= h.y1 + LEGEND_REACH_PT and
                 h.x0 - 150 <= r.x0 <= h.x0 + 450 and
                 t.strip(":").upper() not in LEGEND_WORDS]
        below.sort(key=lambda rt: rt[0].y0)
        # stop at the first big gap: the end of the legend
        kept, last = [], h.y1
        for r, t in below:
            if r.y0 - last > max(LEGEND_GAP_PT, 4 * r.height):
                break
            kept.append((r, t))
            last = r.y1
        if not kept:
            continue
        # the description column: where most of the longer lines start
        # (short text further left - "EWC", "TB", "S" - is part of a
        # symbol; lines further right are wrapped second lines)
        cols = {}
        for r, t in kept:
            if len(t.strip()) >= 4:
                k = round(r.x0 / 10)
                cols[k] = cols.get(k, 0) + 1
        if not cols:
            continue
        x_desc = max(cols, key=lambda k: (cols[k], -k)) * 10
        prev_r = prev_sym = None
        for r, t in kept:
            if not x_desc - 15 <= r.x0 <= x_desc + 30:
                continue
            key = (round(r.x0), round(r.y0))
            if key in seen:                    # two headings, one legend
                continue
            seen.add(key)
            hgt = max(r.height, 6)
            box = fitz.Rect(r.x0 - 6 * hgt, r.y0 - 0.8 * hgt, r.x0 - 3,
                            r.y1 + 0.8 * hgt)
            if drawings is None:               # once per page, not per row
                try:
                    drawings = page.get_drawings()
                except Exception:
                    drawings = []
            # only linework wholly inside the space left of the name: a
            # table's rules and the next row's symbol aren't this symbol
            def ink(bx):
                if rot:
                    sy = _ink_box(page, bx * to_page,
                                  exclude=[rr * to_page for rr, _ in rows],
                                  paths=drawings, whole=True)
                    return sy * to_disp if sy is not None else None
                return _ink_box(page, bx, exclude=[rr for rr, _ in rows],
                                paths=drawings, whole=True)
            sym = ink(box)
            if sym is None:
                # a wide SYMBOL column (the picture 60-100 pt left of its
                # description): look twice as far, not past the text left
                wide = fitz.Rect(r.x0 - 12 * hgt, box.y0, box.x1, box.y1)
                left_txt = [rr.x1 for rr, _t in rows
                            if rr.x1 < r.x0 - 3 and rr.y1 > box.y0 and
                            rr.y0 < box.y1 and rr.x1 > wide.x0]
                if not left_txt:
                    sym = ink(wide)
            if sym is None and text_syms is not None:
                # the symbol is a short word alone ("OS") left of the name
                cy = (r.y0 + r.y1) / 2
                tw = [(rr, tt_.strip()) for rr, tt_ in rows
                      if 1 <= len(tt_.strip()) <= 3 and
                      tt_.strip().isalnum() and tt_.strip().isupper() and
                      rr.x1 < r.x0 - 3 and rr.x0 >= r.x0 - 12 * hgt and
                      rr.y0 - 0.5 * hgt <= cy <= rr.y1 + 0.5 * hgt]
                nm_ = device_label(t)
                if tw and nm_ and good_name(nm_):
                    rr, wt = max(tw, key=lambda x: x[0].x1)
                    text_syms.append((nm_, wt, rr))
                    continue
            if sym is None or sym.width < 3 or sym.height < 3 or \
                    sym.x1 > r.x0 + 1:
                continue                         # no symbol: not a device
            if prev_sym is not None and r.y0 - prev_r.y1 < 1.5 * hgt and \
                    _overlap_share(sym, prev_sym) > 0.5:
                # the second line of the entry above ('DUPLEX CONVENIENCE
                # OUTLET' / 'GROUND FAULT INTERRUPTER TYPE'): the same
                # symbol - its words finish the name, not a device of its own
                if out and out[-1][1] is prev_sym:
                    both = device_label(out[-1][0] + " " + t)
                    out[-1] = (both or (out[-1][0] + " - " +
                                        t.strip().rstrip(".")[:40]),
                               prev_sym)
                elif rejects is not None:
                    rejects.append((t.strip(), "second line of the legend "
                                               "entry above"))
                continue
            prev_r, prev_sym = r, sym
            name = device_label(t)
            if name is None:
                if rejects is not None:
                    rejects.append((t.strip(), "not a short device name"))
                continue
            out.append((name, sym))
    return out


def _overlap_share(a, b):
    """Area of a & b over the smaller of the two."""
    i = fitz.Rect(a) & fitz.Rect(b)
    if i.is_empty:
        return 0.0
    small = min(a.width * a.height, b.width * b.height) or 1.0
    return (i.width * i.height) / small


def _item_rect(it):
    k = it[0]
    if k in ("re",):
        return fitz.Rect(it[1])
    if k == "qu":
        return it[1].rect
    pts = [q for q in it[1:] if isinstance(q, fitz.Point)]
    if not pts:
        return None
    r = fitz.Rect(pts[0], pts[0])
    for q in pts[1:]:
        r |= q
    return r


def _ink_box(page, box, exclude=(), paths=None, whole=False):
    """The bounding box of the linework drawn inside `box` (no text, no
    table rules running through it). `whole`: only pieces lying wholly
    inside the box count (nothing clipped from a longer line)."""
    hit = None
    if paths is None:
        try:
            paths = page.get_drawings()
        except Exception:
            return None
    grow = box + (-0.5, -0.5, 0.5, 0.5)
    for p in paths:
        if not grow.intersects(fitz.Rect(p["rect"])):
            continue
        for it in p.get("items", ()):
            r = _item_rect(it)
            if r is None:
                continue
            if not (grow.intersects(r) or grow.contains(r.tl)):
                continue
            if whole and not (r.x0 >= grow.x0 and r.x1 <= grow.x1 and
                              r.y0 >= grow.y0 and r.y1 <= grow.y1):
                continue
            if r.width > box.width * 1.2 or r.height > box.height * 1.2:
                continue                   # a table rule or frame
            r = r & box
            if r.width <= 0 and r.height <= 0:
                continue
            hit = fitz.Rect(r) if hit is None else hit | r
    return hit


_BAD_NAME = re.compile(r"https?:|www\.|LEGEND|SCHEDULE|NOTES?\b|SHEET|"
                       r"ABBREVIATION|^\W*[\d\W]+\W*$|"
                       r"\bPIPE\s+(?:UP|DOWN|RISER?|DROP)\b|"
                       r"\b(?:DIRECTION\s+OF\s+)?FLOW\s+(?:ARROW|DIRECTION)\b|"
                       r"^NORTH\b|\bBREAK\s+LINE\b", re.I)


# Nov 1 (Aiken G-sheet code legend): lines of a life-safety / code plan
# legend that describe a note, a mounting height, a wall type or an egress
# path, not a symbol to count - each took ~17 s to search for nothing and
# together pushed real symbols (the fire extinguisher) past the time limit
_NOTE_NAME = re.compile(r"\bA\.?\s?F\.?\s?F\b|\bTOP\s+OF\b|"
                        r"\bEXIT\s+CAPACITY\b|\bEGRESS\s+(?:TRAVEL|PATH|WIDTH)|"
                        r"\bTRAVEL\s+(?:PATH|DISTANCE)\b|"
                        r"\b(?:ANTICIPATED|OCCUPANT|DESIGN)\s+LOAD\b|"
                        r"\bCONSTRUCTION\s+FOR\b|\bNON-?RATED\b|"
                        r"\bCOMMON\s+PATH\b|\bDEAD\s*-?\s*END\b", re.I)
# names that are a device to count: tried first within their discipline,
# so a time limit falls on the doubtful lines, not on these
_DEVICE_WORD = re.compile(r"EXTINGUISH|RECEPTACLE|OUTLET|DUPLEX|SIGN\b|"
                          r"DETECTOR|SENSOR|VALVE|FIXTURE|LIGHT|LUMINAIRE|"
                          r"DIFFUSER|GRILLE|REGISTER|PANEL|SWITCH|SPEAKER|"
                          r"HORN|STROBE|PULL\s+STATION|CABINET|HYDRANT|"
                          r"SPRINKLER|HEAD\b|THERMOSTAT|CAMERA|JACK|"
                          r"DEVICE|BOX\b|FAN\b|HEATER|DRAIN|HOSE\s+BIB|"
                          r"CLEANOUT|ARRESTOR|ANNUNCIATOR", re.I)
# a life-safety device drawn on the floor / life safety plans, not on the
# trade sheets (Aiken: searched on the E/M/P sheets only, never found)
_LIFE_SAFETY_DEVICE = re.compile(r"FIRE\s+EXTINGUISHER|\bF\.?E\.?C\.?\b|"
                                 r"\bKNOX\s+BOX|\bAED\b|DEFIBRILLATOR|"
                                 r"AREA\s+OF\s+REFUGE|EMERGENCY\s+EYE\s*WASH",
                                 re.I)
_LIFE_SAFETY_PLAN = re.compile(r"LIFE\s+SAFETY|CODE\s+PLAN|EGRESS\s+PLAN",
                               re.I)


def life_safety_device(name):
    """A legend symbol counted on the floor / life safety plans."""
    return bool(_LIFE_SAFETY_DEVICE.search(name or "")) and \
        not _NOTE_NAME.search(name or "")


def _life_safety_pages(plan_pages, titles):
    """The life safety plans among `plan_pages` when the set has them (the
    devices are drawn there), else the floor plans themselves."""
    own = [p for p in plan_pages
           if _LIFE_SAFETY_PLAN.search((titles or {}).get(p) or "")]
    return own or list(plan_pages)


def good_name(name):
    """A legend description worth counting ("DUPLEX RECEPTACLE"), not a
    heading, a number, a link, a note or a whole sentence."""
    n = (name or "").strip()
    if not (3 <= len(n) <= 90 and sum(ch.isalpha() for ch in n) >= 3) or \
            _BAD_NAME.search(n) or _NOTE_NAME.search(n):
        return False
    if len(n) <= 50:
        return True
    # a longer name is a device with its qualifier ('WALL MOUNTED DATA
    # OUTLET - STUBBED ABOVE LIFT-OUT CEILING', 'DUPLEX CONVENIENCE
    # OUTLET - GROUND FAULT INTERRUPTER TYPE'), not a sentence
    return len(n.split()) <= 14 and not n.endswith(".")


def plain_symbol(sym):
    """Too small or too line-like to count by picture (it would match
    every short line on the sheet)."""
    w, h = sym.width, sym.height
    return w < 4 or h < 4 or max(w, h) / max(1e-6, min(w, h)) > 5


_SHARED_DISCIPLINES = {"", "general", "cover", "index", "code", "other"}


def _symbol_word(page, sym):
    """The one short word (2-3 capital letters) drawn inside a legend
    symbol's box (displayed coordinates), or None."""
    r = fitz.Rect(sym)
    if page.rotation % 360:
        r = r * page.derotation_matrix
    r = r + (-1, -1, 1, 1)
    ws = [w for w in page.get_text("words")
          if r.contains(fitz.Rect(w[:4]))]
    ws = [w[4].strip() for w in ws]
    if len(ws) == 1 and 2 <= len(ws[0]) <= 3 and ws[0].isalpha() and \
            ws[0].isupper():
        return ws[0]
    return None


def _text_symbol_counts(doc, text_legends, found, legends_pc, pages,
                        disciplines, words=None):
    """Legend rows whose symbol is only a short word ("OS"): the word,
    standing alone, on the legend's own discipline's pages (not the legend
    sheet). A word inside a symbol already counted (the ceiling sensor's
    circle with OS in it) is that symbol, not another. `words` (a dict)
    keeps each page's words between calls (NW-18 speed)."""
    out = []
    seen = set()
    for pno, name, text in text_legends:
        if (name.upper(), text) in seen:
            continue
        seen.add((name.upper(), text))
        where = _pages_for_legend(pno, pages, disciplines)
        pool = range(doc.page_count) if where is None else where
        hits = []
        for p_ in pool:
            if p_ == pno:
                continue
            if words is not None and p_ in words:
                ws = words[p_]
            else:
                ws = doc[p_].get_text("words")
                if words is not None:
                    words[p_] = ws
            match = [w for w in ws if w[4].strip() == text]
            if not match:
                continue
            taken = [fitz.Rect(h["rect"]) + (-2, -2, 2, 2) for f in found
                     for h in f["hits"] if h["page"] == p_]
            taken += [s + (-20, -20, 20, 20) for pp, _n, s in legends_pc
                      if pp == p_]
            for w in match:
                r = fitz.Rect(w[:4])
                c = fitz.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
                if any(t.contains(c) for t in taken):
                    continue
                hits.append({"page": p_, "rect": list(r), "score": 0.8,
                             "method": "legend count (symbol word)"})
        if hits:
            out.append({"name": name[:90], "hits": hits, "page": pno,
                        "symbol": None})
    return out


def auto_disciplines(doc):
    """{page: discipline} from each sheet's number and title ({} when the
    sheets can't be read)."""
    try:
        from . import aitakeoff, sheets
        out = {}
        for i in range(doc.page_count):
            for r in sheets.scan(doc, [i], numbers=False):
                text = doc[i].get_text()[:3000]
                out[r["page"]] = aitakeoff.discipline(r.get("number"),
                                                      r.get("title"), text)
        return out
    except Exception:                                     # noqa: BLE001
        import logging
        logging.getLogger(__name__).info("sheet disciplines not read",
                                         exc_info=True)
        return {}


def _pages_for_legend(pno, pages, disc):
    """The pages a legend's symbols are counted on: with `disc` ({page:
    discipline}), only the legend's own discipline (an electrical legend's
    EMERGENCY FIXTURE is not counted on the plumbing and HVAC plans); a
    general (G-) legend applies to every page."""
    if not disc:
        return pages
    d = (disc.get(pno) or "").lower()
    if d in _SHARED_DISCIPLINES:
        return pages
    pool = range(len(disc)) if pages is None else pages
    return [p for p in pool if (disc.get(p) or "").lower() == d]


def _ring_like(p, lo=4.0, hi=30.0):
    """A stroked closed outline that is a circle (curves, or a polygon of
    8+ sides) about lo..hi pt across: the ring of a ring symbol."""
    if p.get("fill") is not None and p.get("type") == "f":
        return None
    r = fitz.Rect(p["rect"])
    if not (lo <= r.width <= hi and lo <= r.height <= hi and
            abs(r.width - r.height) <= 0.15 * max(r.width, r.height)):
        return None
    kinds = [it[0] for it in p.get("items", ())]
    if kinds.count("c") >= 4 or kinds.count("l") >= 8:
        return r
    return None


def _dark_fill(p, lo=2.0, hi=20.0):
    """(rect, fullness) of a dark filled shape lo..hi pt (a filled
    triangle or square inside a symbol), or None."""
    f = p.get("fill")
    if f is None or max(f[:3]) > 0.35:
        return None
    r = fitz.Rect(p["rect"])
    if not (lo <= r.width <= hi and lo <= r.height <= hi):
        return None
    its = p.get("items", ())
    if not 3 <= len(its) <= 8 or any(it[0] != "l" for it in its):
        return None
    # how full the shape fills its box (a triangle about half, a square
    # all of it) - steadier than counting corners, which a drawing's
    # extra closing line changes
    pts = [it[1] for it in its]
    a2 = 0.0
    for q0, q1 in zip(pts, pts[1:] + pts[:1]):
        a2 += q0.x * q1.y - q1.x * q0.y
    full = abs(a2) / 2.0 / max(r.width * r.height, 1e-6)
    return r, _hu(full, 2)


def fill_ring_signature(paths, box):
    """A symbol drawn as a dark filled shape inside a ring (SPECIAL
    OUTLET: a filled triangle in a circle): (fullness, fill w / ring, fill
    h / ring) from the legend's drawing in `box`, or None."""
    grow = box + (-1, -1, 1, 1)
    fills, rings = [], []
    for p in paths:
        r = fitz.Rect(p["rect"])
        if not grow.contains(r):
            continue
        d = _dark_fill(p)
        if d:
            fills.append(d)
        g = _ring_like(p)
        if g is not None:
            rings.append(g)
    for fr, n in fills:
        c = (fr.tl + fr.br) / 2
        for rg in rings:
            if rg.contains(c) and rg.width > fr.width:
                return (n, fr.width / rg.width, fr.height / rg.height)
    return None


def _fill_ring_parts(page, cache=None):
    """([(fill rect, n)], [ring rects]) of a page - read once per page
    when a cache dict is given (NW-18 speed: legend_counts asked for every
    symbol and re-read every sheet's drawings each time)."""
    key = page.number
    if cache is not None and key in cache:
        return cache[key]
    try:
        paths = page.get_drawings()
    except Exception:                                     # noqa: BLE001
        paths = []
    fills, rings = [], []
    for p in paths:
        d = _dark_fill(p)
        if d:
            fills.append((d[0], d[1]))
        g = _ring_like(p)
        if g is not None:
            rings.append(g)
    if cache is not None:
        cache[key] = (fills, rings)
    return fills, rings


def fill_ring_hits(page, sig, tol=0.2, cache=None):
    """Rects of the symbols on `page` drawn like `sig` - the same filled
    shape inside a ring, in the same proportion, at any size."""
    n, rw, rh = sig
    allf, rings = _fill_ring_parts(page, cache)
    fills = [r for r, dn in allf if abs(dn - n) <= 0.15]
    out = []
    for fr in fills:
        c = (fr.tl + fr.br) / 2
        for rg in rings:
            rc = (rg.tl + rg.br) / 2
            if abs(rc.x - c.x) > 0.3 * rg.width or \
                    abs(rc.y - c.y) > 0.3 * rg.height:
                continue
            if abs(fr.width / rg.width - rw) <= tol and \
                    abs(fr.height / rg.height - rh) <= tol:
                if not any(o.intersects(rg) for o in out):
                    out.append(fitz.Rect(rg))
                break
    return out


def _same_picture(tpl, seen, tol=8.0):
    """The name of an already-counted legend symbol with the same picture
    as `tpl` (PNG bytes), or None."""
    try:
        import cv2
        import numpy as np
        a = cv2.imdecode(np.frombuffer(tpl, np.uint8), cv2.IMREAD_GRAYSCALE)
    except Exception:                                     # noqa: BLE001
        return None
    if a is None:
        return None
    for t, name in seen:
        b = cv2.imdecode(np.frombuffer(t, np.uint8), cv2.IMREAD_GRAYSCALE)
        if b is None or abs(a.shape[0] - b.shape[0]) > 2 or \
                abs(a.shape[1] - b.shape[1]) > 2:
            continue
        h, w = min(a.shape[0], b.shape[0]), min(a.shape[1], b.shape[1])
        x, y = a[:h, :w], b[:h, :w]
        if float(np.mean(np.abs(x.astype(int) - y.astype(int)))) >= tol:
            continue
        # most of a symbol is white paper: the ink must match too (a data
        # outlet triangle is not a quadruplex outlet circle)
        ia, ib = (x < 160).astype(np.uint8), (y < 160).astype(np.uint8)
        na, nb = int(ia.sum()), int(ib.sum())
        if na == 0 or nb == 0:
            if na == nb:
                return name
            continue
        k = np.ones((3, 3), np.uint8)              # a pixel of slack
        da, db = cv2.dilate(ia, k), cv2.dilate(ib, k)
        if min(int((ia & db).sum()) / na, int((ib & da).sum()) / nb) >= 0.85:
            return name
    return None


def _table_boxes(page):
    """Schedule tables on a page, in the page's own coordinates."""
    try:
        from . import schedules
        return [schedules.to_page(page, t["bbox"])
                for t in schedules.read_page(page) if t.get("rows")]
    except Exception:                                     # noqa: BLE001
        return []


def _compete(found):
    """One device per spot: where two legend symbols matched the same spot
    (a duplex outlet also matches the quadruplex and the GFI symbols at a
    lower score), the spot goes to the symbol that matched it best."""
    allh = []
    for fi, f in enumerate(found):
        for hi, h in enumerate(f["hits"]):
            r = h["rect"]
            allh.append((float(h.get("score") or 0.0), fi, hi, h["page"],
                         (r[0] + r[2]) / 2, (r[1] + r[3]) / 2,
                         max(r[2] - r[0], r[3] - r[1])))
    allh.sort(key=lambda t: -t[0])
    kept, lose = [], set()
    # a small symbol found inside a bigger one (the pull station's boxed
    # 'F' inside the 'FACP' panel symbol) is part of the bigger symbol's
    # drawing, whatever the scores
    rects = [(fi, hi, h["page"], fitz.Rect(h["rect"]))
             for fi, f in enumerate(found) for hi, h in enumerate(f["hits"])]
    by_pg = {}
    for t in rects:
        by_pg.setdefault(t[2], []).append(t)
    for lst in by_pg.values():
        for fi, hi, _pg, r in lst:
            ar = r.width * r.height
            if ar <= 0:
                continue
            for fj, _hj, _p2, q in lst:
                if fj == fi or q.width * q.height < 2.0 * ar:
                    continue
                i = r & q
                if not i.is_empty and i.width * i.height >= 0.8 * ar:
                    lose.add((fi, hi))
                    break
    for sc, fi, hi, pg, cx, cy, sz in allh:
        if (fi, hi) in lose:
            continue
        # the same spot: centres within a third of the smaller symbol (a
        # data outlet drawn right beside a receptacle is its own device)
        clash = any(k[3] == pg and k[1] != fi and
                    abs(k[4] - cx) <= 0.35 * min(sz, k[6]) and
                    abs(k[5] - cy) <= 0.35 * min(sz, k[6]) for k in kept)
        if clash:
            lose.add((fi, hi))
        else:
            kept.append((sc, fi, hi, pg, cx, cy, sz))
    for fi, f in enumerate(found):
        lost = [hi for hi in range(len(f["hits"])) if (fi, hi) in lose]
        if lost:
            f["lost"] = len(lost)
            f["hits"] = [h for hi, h in enumerate(f["hits"])
                         if (fi, hi) not in lose]


LEGEND_DISC_ORDER = ("electrical", "fire alarm", "telecom", "fire protection",
                     "mechanical", "plumbing", "civil", "landscape",
                     "structural", "architectural", "interiors")


# a device's own plan, when the set splits the electrical work by plan
# (LIGHTING PLAN / POWER PLAN / FIRE ALARM PLAN): a smoke detector is
# counted on the fire alarm plan only, a light fixture on the lighting plan
_SYMBOL_PLANS = (
    (re.compile(r"FIRE\s*ALARM|SMOKE|HEAT\s+DETECT|PULL\s+STATION|HORN|"
                r"STROBE|SPEAKER|\bNAC\b|FACP|ANNUNCIATOR|DUCT\s+DETECT",
                re.I), re.compile(r"FIRE\s*ALARM", re.I)),
    (re.compile(r"FIXTURE|LIGHT|LUMINAIRE|EXIT\s+SIGN|OCCUPANCY|VACANCY|"
                r"SENSOR|PHOTO\s*CELL|DIMMER|\bSWITCH", re.I),
     re.compile(r"LIGHTING", re.I)),
    (re.compile(r"RECEPTACLE|OUTLET|DUPLEX|QUADRUPLEX|GFI|JUNCTION\s+BOX|"
                r"DISCONNECT|MOTOR|FLOOR\s+BOX|DATA|TELE|VOICE", re.I),
     re.compile(r"POWER|DATA|SIGNAL|SYSTEMS?|TELECOM", re.I)),
)


def _plans_for_symbol(name, where, titles):
    """The pages a legend symbol is counted on, narrowed to its own plan
    when the set has one (titles {page: sheet title}); unchanged when no
    page of `where` carries that plan's name."""
    if not titles or not where:
        return where
    for dev, plan in _SYMBOL_PLANS:
        if dev.search(name or ""):
            own = [p for p in where if plan.search(titles.get(p) or "")]
            return own or where
    return where


def legend_counts(doc, pages=None, threshold=0.8, progress=None,
                  max_symbols=40, time_limit=None, report=None,
                  disciplines=None, titles=None, pictures=True,
                  plan_pages=None):
    """Count every legend symbol across the set: [{name, hits}] where hits
    are find_symbols() hits (symbols inside legends themselves left out).
    progress(k, n, name) -> False stops.

    `report` (a dict, optional) gets what was not counted, so nothing is
    dropped unseen: "not_counted" [(name, why)] for symbols left over at
    the time limit, past `max_symbols`, stopped, or that failed;
    "rejected" [(page, text, why)] for legend lines with a symbol but no
    usable device name. `disciplines` ({page: discipline}, optional): a
    legend's symbols are counted on its own discipline's pages only.
    `pictures` False: no matching by picture (the 'picture_count' setting,
    a patent design-rule switch) - only the vector shape search below.
    `plan_pages` (optional): the floor plans; a life-safety device (fire
    extinguisher, AED) is counted on the life safety plans among them, or
    on them all, instead of the trade sheets."""
    from . import autocount
    if disciplines is None:
        # PM review NW-18: called without the sheet list (Trade Takeoff >
        # Legend, or a script on the E sheets), every legend in the set
        # was counted on the given pages - plumbing and civil notes came
        # back as 'electrical' symbols. Each legend now counts on its own
        # discipline's sheets, read from the sheet numbers and titles.
        disciplines = auto_disciplines(doc)
    found = []
    legends = []
    rejected = []
    text_legends = []
    for pno in range(doc.page_count):
        rej = []
        tsy = []
        rows_ = legend_rows(doc[pno], rejects=rej, text_syms=tsy)
        text_legends += [(pno, n_, w_) for n_, w_, _r in tsy]
        boxes = _table_boxes(doc[pno]) if rows_ else []
        derot = doc[pno].derotation_matrix if doc[pno].rotation % 360 \
            else None
        for name, sym in rows_:
            ps = sym * derot if derot is not None else sym   # page coords
            c = ((ps.x0 + ps.x1) / 2, (ps.y0 + ps.y1) / 2)
            if any(b[0] <= c[0] <= b[2] and b[1] <= c[1] <= b[3]
                   for b in boxes):
                rej.append((name, "a line of a schedule table, not a "
                                  "legend symbol"))
                continue
            legends.append((pno, name, sym))
        rejected += [(pno, t, why) for t, why in rej]
    if report is not None:
        report["rejected"] = rejected
        report.setdefault("not_counted", [])
    # the legends' own symbols in page coordinates (hits are in those)
    legends_pc = []
    for pno, name, sym in legends:
        pg_ = doc[pno]
        legends_pc.append((pno, name, sym * pg_.derotation_matrix
                           if pg_.rotation % 360 else sym))
    cache = {}
    ring_cache = {}
    word_cache = {}
    out = []
    todo = [lg for lg in legends if not plain_symbol(lg[2]) and
            good_name(lg[1])]
    for pno, name, sym in legends:
        if plain_symbol(sym) and good_name(name):
            rejected.append((pno, name, "symbol is a plain line - too "
                             "simple to count by its picture"))
        elif not good_name(name):
            rejected.append((pno, name, "not a device name (a heading, a "
                             "number or a sentence)"))
    seen_names = set()
    uniq = []
    for lg in todo:                      # one search per described symbol
        key = lg[1].strip().upper()
        if key in seen_names:
            continue
        seen_names.add(key)
        uniq.append(lg)
    # device legends first (power, lighting, fire alarm, HVAC, plumbing):
    # an architectural finish legend's hatches must not use up the count
    # before the electrical symbols are reached; the cap is per discipline
    disc_of = disciplines or {}
    order = {d: i for i, d in enumerate(LEGEND_DISC_ORDER)}
    uniq.sort(key=lambda lg: (order.get(disc_of.get(lg[0], ""),
                                        len(order)),
                              not _DEVICE_WORD.search(lg[1] or "")))
    per, todo, left = {}, [], []
    for lg in uniq:
        d = disc_of.get(lg[0], "")
        if per.get(d, 0) >= max_symbols:
            left.append((lg[1], f"more than {max_symbols} legend symbols "
                                f"on the {d or 'other'} sheets"))
            continue
        per[d] = per.get(d, 0) + 1
        todo.append(lg)
    import time as _time
    t0 = _time.perf_counter()
    seen_tpls = []
    for k, (pno, name, sym) in enumerate(todo):
        if progress and progress(k, len(todo), name) is False:
            left += [(lg[1], "stopped") for lg in todo[k:]]
            break
        if time_limit and _time.perf_counter() - t0 > time_limit:
            left += [(lg[1], f"time limit ({time_limit:.0f} s)")
                     for lg in todo[k:]]
            break
        pad = 1.5
        clip = (sym + (-pad, -pad, pad, pad)) & doc[pno].rect
        if clip.is_empty or clip.width < 3 or clip.height < 3:
            left.append((name, "symbol too small to match"))
            continue
        try:
            # (no picture made at all when matching by picture is off)
            tpl = autocount.symbol_template(doc[pno], clip) \
                if pictures else None
            twin = _same_picture(tpl, seen_tpls) if tpl else None
            if twin:
                # a wrapped legend line ('... FOR WATER' / 'COOLER') or a
                # second name for one picture: the symbol is counted once
                left.append((name, f"same symbol as '{twin[:40]}'"))
                continue
            if tpl:
                seen_tpls.append((tpl, name))
            if plan_pages and life_safety_device(name):
                where = _life_safety_pages(plan_pages, titles)
            else:
                where = _plans_for_symbol(
                    name, _pages_for_legend(pno, pages, disciplines),
                    titles)
            hits = autocount.find_symbols(doc, tpl, threshold, where,
                                          cache=cache) \
                if where != [] and pictures else []
        except Exception:                  # one odd symbol never stops all
            import logging
            logging.getLogger(__name__).info("legend symbol %r skipped",
                                             name, exc_info=True)
            left.append((name, "couldn't be matched"))
            continue
        keep = []
        for h in hits:
            r = fitz.Rect(h["rect"])
            if any((s + (-20, -20, 20, 20)).intersects(r)
                   for p_, _n, s in legends_pc if p_ == h["page"]):
                continue                         # the legend's own symbol
            h["method"] = "legend count"
            keep.append(h)
        if len(keep) < 3 and where != []:
            # a ring with a filled shape inside (SPECIAL OUTLET), drawn at
            # another size on the plans than in the legend: found by its
            # shape, not its picture
            try:
                lp = doc[pno]
                box = fitz.Rect(sym) * lp.derotation_matrix \
                    if lp.rotation else fitz.Rect(sym)
                sig = fill_ring_signature(lp.get_drawings(), box)
            except Exception:                             # noqa: BLE001
                sig = None
            if sig:
                more = []
                for p_ in (where if where is not None else
                           range(doc.page_count)):
                    if p_ == pno:
                        continue
                    for r in fill_ring_hits(doc[p_], sig,
                                            cache=ring_cache):
                        if any((s + (-20, -20, 20, 20)).intersects(r)
                               for pp, _n, s in legends_pc if pp == p_):
                            continue
                        more.append({"page": p_, "rect": list(r),
                                     "score": 0.85, "method":
                                     "legend count (symbol shape)"})
                if len(more) >= 3 and len(more) > len(keep):
                    keep = more
        if len(keep) < 3 and where != []:
            # a symbol whose picture is mostly its letters ('OS' in a
            # circle): matched by the word when the picture finds too few
            wd = _symbol_word(doc[pno], sym)
            if wd:
                more = _text_symbol_counts(
                    doc, [(pno, name, wd)], found, legends_pc,
                    where, None, words=word_cache)
                more = more[0]["hits"] if more else []
                if len(more) >= 3 and len(more) > len(keep):
                    for h in more:
                        h["method"] = "legend count (symbol letters)"
                    keep = more
        if not keep and not pictures and where != []:
            left.append((name, "not found by its shape or letters; "
                               "counting by picture is turned off"))
        found.append({"name": name[:90], "hits": keep, "page": pno,
                      "symbol": list(sym)})
    found += _text_symbol_counts(doc, text_legends, found, legends_pc,
                                 pages, disciplines, words=word_cache)
    _compete(found)
    for f in found:
        if f["hits"]:
            out.append(f)
    out.sort(key=lambda f: -len(f["hits"]))
    if report is not None:
        report["not_counted"] = left
    return out


# ------------------------------------------------------------- roofing
def pitch_labels(page):
    """[(rise per 12, centre)] for each pitch label on the page (6:12,
    5"/1'-0", 6 IN 12...). A label and the shorter phrases inside it
    count once."""
    out = []
    for text, r in phrases(page, 5):
        v = pitch_value(text)
        if v is None:
            continue
        if any(abs(v - o[0]) < 1e-9 and o[2].contains(r) or
               abs(v - o[0]) < 1e-9 and r.contains(o[2]) for o in out):
            continue
        out.append((v, ((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2), fitz.Rect(r)))
    return [(v, c) for v, c, _r in out]


def slope_factor(rise):
    return math.sqrt(1 + (rise / 12.0) ** 2)


def _inside(pt, poly):
    x, y = pt
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and \
                x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def roof_area(plan_sf, rise, waste=0.10):
    s = plan_sf * slope_factor(rise)
    return {"plan": plan_sf, "pitch": rise, "factor": slope_factor(rise),
            "sloped": s, "squares": s / 100 * (1 + waste)}


def steep_pitch_labels_at(page):
    """[(label text, rise, centre)] for pitch labels over 12:12 - never
    used as a pitch, but they say which roof area needs a person (H3)."""
    from .calculators import MAX_PITCH
    out = []
    for text, r in phrases(page, 5):
        v = _pitch_rise(text)
        if v is None or v <= MAX_PITCH:
            continue
        c = ((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
        if any(t in text or text in t for t, _v, _c in out):
            continue
        out.append((text.strip(), v, c))
    return out


def roof_pitch(poly, pitches, steep=(), default=None):
    """(pitch, note) for one roof area (H3). The label inside the outline
    wins, else the nearest label; if that label is over 12:12 the area
    gets no pitch (None) and a note to check it - it is never priced at
    the default. The default is used only when the page has no pitch
    label at all."""
    from .calculators import MAX_PITCH
    labs = [(p, c, None) for p, c in pitches] + \
        [(v, c, t) for t, v, c in steep]
    if not labs:
        return default, (f"no pitch printed - using {default:g}:12"
                         if default is not None else "no pitch printed")
    inside = [x for x in labs if _inside(x[1], poly)]
    good_in = [x for x in inside if x[2] is None]
    if good_in:
        pick = good_in[0]
    elif inside:
        pick = inside[0]
    else:
        cx = sum(p[0] for p in poly) / len(poly)
        cy = sum(p[1] for p in poly) / len(poly)
        pick = min(labs, key=lambda x: math.hypot(x[1][0] - cx,
                                                  x[1][1] - cy))
    if pick[2] is not None:
        return None, (f"pitch {pick[2]} is over {MAX_PITCH:g}:12 - out of "
                      "range, not taken off; check it")
    return pick[0], ""


def roof_status(n, squares, flagged, steep, any_pitch, default):
    """The Roof Areas status line: what was found, the areas sent to
    review, and the over-12:12 labels - nothing overwrites anything
    (H3)."""
    def fmt(v):
        return f"{_c2(v):,.2f}".rstrip("0").rstrip(".")
    parts = [f"{n} roof area(s), {fmt(squares)} squares with waste."
             if n else ("No area measurements on this page yet."
                        if not flagged else "No roof area taken off.")]
    if n and not any_pitch:
        parts.append(f"No pitch printed, using {default:g}:12 "
                     "(Takeoff > Roof Plan Takeoff asks for each pitch).")
    if flagged:
        parts.append(f"{len(flagged)} area(s) to review, not taken off "
                     "(pitch over 12:12): " + ", ".join(flagged[:5]) + ".")
    if steep:
        parts.append("Pitch over 12:12 is out of range and not used: " +
                     ", ".join(steep[:5]) + ".")
    return " ".join(parts)


def pitch_for(poly, pitches, default=None):
    """The pitch printed inside the roof outline, else the nearest one."""
    inside = [p for p, c in pitches if _inside(c, poly)]
    if inside:
        return inside[0]
    if pitches:
        cx = sum(p[0] for p in poly) / len(poly)
        cy = sum(p[1] for p in poly) / len(poly)
        return min(pitches, key=lambda pc: math.hypot(pc[1][0] - cx,
                                                      pc[1][1] - cy))[0]
    return default


# ------------------------------------------------------------- rebar
BARS = {3: (0.375, 0.376), 4: (0.500, 0.668), 5: (0.625, 1.043),
        6: (0.750, 1.502), 7: (0.875, 2.044), 8: (1.000, 2.670),
        9: (1.128, 3.400), 10: (1.270, 4.303), 11: (1.410, 5.313)}
STOCK_FT = 20.0


def _laps(length_ft, bar, lap_db=40):
    """Lap splices along a bar run longer than stock length."""
    if length_ft <= STOCK_FT:
        return 0, 0.0
    lap = lap_db * BARS[bar][0] / 12
    n = math.ceil((length_ft - STOCK_FT) / (STOCK_FT - lap))
    return n, n * lap


def rebar_linear(length_ft, bar=4, bars=2, width_in=24, trans_bar=None,
                 spacing_in=None, cover_in=3, lap_db=40):
    """Continuous footing or grade beam: `bars` longitudinal bars plus
    optional transverse bars at `spacing_in`."""
    rows = []
    n_laps, lap_ft = _laps(length_ft, bar, lap_db)
    lf = bars * (length_ft + lap_ft)
    rows.append({"bar": bar, "use": "Longitudinal", "count": bars,
                 "laps": n_laps * bars, "lf": lf})
    if trans_bar and spacing_in:
        n = int(math.floor(length_ft * 12 / spacing_in)) + 1
        each = max(0.5, (width_in - 2 * cover_in) / 12)
        rows.append({"bar": trans_bar, "use": "Transverse", "count": n,
                     "laps": 0, "lf": n * each})
    return _weigh(rows)


def rebar_slab(area_sf, perimeter_ft, bar=4, spacing_in=12, both_ways=True,
               layers=1, lap_db=40):
    """Slab or mat: bars each way at `spacing_in`. Uses the area and the
    perimeter of the shape (as a rectangle of the same area and
    perimeter) to size the bar runs."""
    # rectangle with this area and perimeter: sides a, b
    p2 = perimeter_ft / 2
    disc = max(0.0, p2 * p2 - 4 * area_sf)
    a = (p2 + math.sqrt(disc)) / 2
    b = area_sf / a if a else 0
    rows = []
    for use, run, across in (("Long way", a, b), ("Short way", b, a)):
        if use == "Short way" and not both_ways:
            continue
        n = int(math.floor(across * 12 / spacing_in)) + 1
        n_laps, lap_ft = _laps(run, bar, lap_db)
        rows.append({"bar": bar, "use": use, "count": n * layers,
                     "laps": n_laps * n * layers,
                     "lf": n * layers * (run + lap_ft)})
    return _weigh(rows)


def _weigh(rows):
    for r in rows:
        r["lb"] = r["lf"] * BARS[r["bar"]][1]
        r["pieces"] = math.ceil(r["lf"] / STOCK_FT)
    return rows


def rebar_totals(rows):
    by = {}
    for r in rows:
        t = by.setdefault(r["bar"], {"bar": r["bar"], "lf": 0.0, "lb": 0.0,
                                     "pieces": 0})
        t["lf"] += r["lf"]
        t["lb"] += r["lb"]
        t["pieces"] += r["pieces"]
    return [by[k] for k in sorted(by)]


# ------------------------------------------------------------- earthwork
def contour_sets(page, ppu, unit="ft", reach_ft=3.0):
    """Line styles that carry elevation labels: [{style, style_name,
    dashed, lines: [{pts, z}]}] with the most-labelled first."""
    per_ft = _per_ft(ppu, unit)
    elevs = []
    for w in page.get_text("words"):
        m = ELEV_RE.match(w[4].strip())
        if m:
            z = float(m.group(1))
            r = fitz.Rect(w[:4])
            elevs.append((z, ((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)))
    if not elevs:
        return []
    reach = max(6.0, reach_ft * per_ft)
    out = []
    for style, segs in styled_segments(page).items():
        lines = []
        for r in runs(segs):
            if poly_len(r) < 3 * per_ft:
                continue
            best, bd = None, reach
            for z, c in elevs:
                d = dist_to_poly(c, r)
                if d < bd:
                    best, bd = z, d
            if best is not None:
                lines.append({"pts": r, "z": best})
        zs = {l["z"] for l in lines}
        if len(lines) >= 2 and len(zs) >= 2:
            out.append({"style": style, "style_name": style_name(style),
                        "dashed": bool(style[2]), "lines": lines})
    out.sort(key=lambda s: -len(s["lines"]))
    return out


def _surface(lines, step):
    """Sample points (x, y, z) every `step` along the contour lines."""
    pts = []
    for l in lines:
        p = l["pts"]
        for a, b in zip(p, p[1:]):
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            n = max(1, int(L / step))
            for i in range(n):
                t = i / n
                pts.append((a[0] + (b[0] - a[0]) * t,
                            a[1] + (b[1] - a[1]) * t, l["z"]))
        pts.append((p[-1][0], p[-1][1], l["z"]))
    return pts


def _interp(samples, x, y):
    """Elevation at (x, y): between the two nearest contours of different
    elevation, by distance; (z, distance to nearest contour)."""
    best = {}
    for sx, sy, z in samples:
        d = (sx - x) ** 2 + (sy - y) ** 2
        if z not in best or d < best[z]:
            best[z] = d
    if not best:
        return None, None
    order = sorted(best.items(), key=lambda kv: kv[1])
    z1, d1 = order[0]
    if len(order) == 1:
        return z1, math.sqrt(d1)
    z2, d2 = order[1]
    d1, d2 = math.sqrt(d1), math.sqrt(d2)
    if d1 + d2 == 0:
        return z1, 0.0
    return (z1 * d2 + z2 * d1) / (d1 + d2), d1


def cut_fill(existing, proposed, boundary, ppu, unit="ft", cell_ft=5.0,
             tie_ft=30.0):
    """Volumes between two contour surfaces inside `boundary` (a polygon
    in page points), on a `cell_ft` grid. Where no proposed contour is
    within `tie_ft`, the ground isn't being changed. Returns {cut, fill,
    net (CY), area (SF), cells: [(x, y, dz ft)]}."""
    per_ft = _per_ft(ppu, unit)
    step = cell_ft * per_ft
    ex = _surface(existing, step / 2)
    pr = _surface(proposed, step / 2)
    try:
        import numpy as np
    except ImportError:
        np = None
    xs = [p[0] for p in boundary]
    ys = [p[1] for p in boundary]
    cells = []
    y = min(ys) + step / 2
    while y < max(ys):
        x = min(xs) + step / 2
        while x < max(xs):
            if _inside((x, y), boundary):
                cells.append((x, y))
            x += step
        y += step
    if np is not None and cells:
        C = np.array(cells)

        def surf(samples):
            S = np.array(samples)
            zs = np.unique(S[:, 2])
            # nearest distance from each cell to each contour elevation
            D = np.full((len(C), len(zs)), np.inf)
            for k, z in enumerate(zs):
                P = S[S[:, 2] == z][:, :2]
                for i0 in range(0, len(C), 2000):
                    blk = C[i0:i0 + 2000]
                    d = np.sqrt(((blk[:, None, :] - P[None, :, :]) ** 2)
                                .sum(-1)).min(1)
                    D[i0:i0 + 2000, k] = d
            o = np.argsort(D, axis=1)
            d1 = np.take_along_axis(D, o[:, :1], 1)[:, 0]
            z1 = zs[o[:, 0]]
            if len(zs) > 1:
                d2 = np.take_along_axis(D, o[:, 1:2], 1)[:, 0]
                z2 = zs[o[:, 1]]
                tot = d1 + d2
                z = np.where(tot > 0, (z1 * d2 + z2 * d1) /
                             np.where(tot > 0, tot, 1), z1)
            else:
                z = z1
            return z, d1
        ze, _ = surf(ex)
        zp, dp = surf(pr)
        zp = np.where(dp / per_ft <= tie_ft, zp, ze)
        dz = (zp - ze).tolist()
    else:
        dz = []
        for x, y in cells:
            ze, _d = _interp(ex, x, y)
            zp, dpp = _interp(pr, x, y)
            if zp is None or dpp / per_ft > tie_ft:
                zp = ze
            dz.append(zp - ze)
    cell_sf = cell_ft * cell_ft
    fill = sum(d for d in dz if d > 0) * cell_sf / 27
    cut = -sum(d for d in dz if d < 0) * cell_sf / 27
    return {"cut": cut, "fill": fill, "net": fill - cut,
            "area": len(cells) * cell_sf,
            "cells": [(c[0], c[1], d) for c, d in zip(cells, dz)]}


# ------------------------------------------------------------- marks
PALETTE = [(0.85, 0.2, 0.2), (0.15, 0.45, 0.85), (0.1, 0.6, 0.3),
           (0.8, 0.45, 0.0), (0.55, 0.25, 0.75), (0.0, 0.55, 0.6),
           (0.75, 0.6, 0.0), (0.4, 0.4, 0.4)]


def run_marks(page_no, systems, unit, method="auto runs"):
    out = []
    for i, g in enumerate(systems):
        col = PALETTE[i % len(PALETTE)]
        for r in g["runs"]:
            pts = [list(p) for p in r["pts"]]
            out.append((page_no, "add_polyline" if len(pts) > 2 else
                        "add_line", {
                            "pts": pts, "color": list(col), "width": 2.5,
                            "opacity": 0.6,
                            "measure": {"type": "length",
                                        "value": round(r["length"], 4),
                                        "unit": unit, "group": g["name"],
                                        "method": method}}))
    return out


def duct_marks(page_no, groups, unit):
    out = []
    for i, g in enumerate(groups):
        col = PALETTE[i % len(PALETTE)]
        for p in g["pieces"]:
            out.append((page_no, "add_line", {
                "pts": [list(p["p0"]), list(p["p1"])], "color": list(col),
                "width": 3, "opacity": 0.55,
                "measure": {"type": "length", "value": round(p["length"], 4),
                            "unit": unit, "group": f"Duct {g['name']}"
                            if not g["name"].startswith("Duct") else
                            g["name"], "method": "auto ducts"}}))
    return out


# ------------------------------------------------------------- pipe drops
# Plumbing drops (and rises) to fixtures are not drawn in plan: the plan
# shows a keynote bubble at the fixture whose note reads '1/2"CW DOWN',
# '1/2"CW & HW DOWN', '1"CW UP TO ...'. Each such bubble is one vertical
# run per system. Its length is an ASSUMPTION: the default is 7 ft, from
# piping run at a 9'-0" ceiling down to a fixture rough-in about 2'-0"
# above the floor. Every line built from it says so, and the height can be
# changed (setting 'pipe_drop_ft', or the drop_ft argument).
DROP_FT_DEFAULT = 7.0
# pressure supply piping that runs overhead and drops to the fixtures
SUPPLY_SYSTEMS = {"CW", "DCW", "HW", "DHW", "HWR", "HWC", "TW", "TMV",
                  "CWS", "HWS", "IW", "PW", "DI", "RO"}
_DROP_NOTE = re.compile(
    rf"^\s*{_SZ}\s*(?:\"|''|IN\.?)?\s*-?\s*([A-Z]{{1,4}})"
    r"((?:\s*(?:&|AND|,|/)\s*[A-Z]{1,4})*)\s+(?:DOWN|DN|UP)\b", re.I)


def _text_lines(page):
    """[(text, rect, height)] for each text line on the page."""
    out = []
    try:
        blocks = page.get_text("dict").get("blocks", [])
    except Exception:                                     # noqa: BLE001
        return out
    for b in blocks:
        for ln in b.get("lines", []):
            spans = ln.get("spans", [])
            t = "".join(s.get("text", "") for s in spans).strip()
            if not t:
                continue
            r = fitz.Rect(ln["bbox"])
            h = max(min(s.get("size", 0) for s in spans), 1.0)
            out.append((t.translate(_QUOTES), r, h))
    return out


def _loop_bubbles(page, max_pt=60.0):
    """Small closed outlines drawn as separate lines (a hexagon or a
    diamond exploded into its sides, as many CAD exports do)."""
    out = []
    for _style, segs in styled_segments(page).items():
        small = [s for s in segs if math.hypot(s[2] - s[0], s[3] - s[1])
                 <= max_pt]
        for r in runs(small):
            if len(r) < 4 or math.hypot(r[0][0] - r[-1][0],
                                         r[0][1] - r[-1][1]) > 1.5:
                continue
            x0, y0, x1, y1 = _bbox(r)
            w, h = x1 - x0, y1 - y0
            if 2 <= min(w, h) and max(w, h) <= max_pt and \
                    max(w, h) <= 2.0 * min(w, h):
                out.append(fitz.Rect(x0, y0, x1, y1))
    return out


def keynote_drops(page, drop_ft=None):
    """Drops/rises to fixtures from DOWN / UP keynotes: [{name ('1/2" CW'),
    drops, length_ft, keys, basis, assumption: True}]. A note in the
    sheet's keynote list reading '<size><system>[ & <system>] DOWN|UP' is
    found with its bubble number; every bubble with that number elsewhere
    on the sheet is one drop per system. Bubbles in the list itself (one
    column of numbered bubbles) are not counted."""
    drop_ft = DROP_FT_DEFAULT if drop_ft is None else float(drop_ft)
    lines = _text_lines(page)
    if not any(_DROP_NOTE.match(t) for t, _r, _h in lines):
        return []
    bubbles = _bubbles(page) + _loop_bubbles(page)

    def bubble_of(r, h):
        c = fitz.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
        best = None
        for b in bubbles:
            if b.contains(c) and max(b.width, b.height) <= 4.5 * h and \
                    (best is None or b.width * b.height <
                     best.width * best.height):
                best = b
        return best
    nums = []                              # (num, rect, h, bubble)
    for t, r, h in lines:
        if re.fullmatch(r"\d{1,2}", t):
            b = bubble_of(r, h)
            if b is not None:
                nums.append((t, r, h, b))
    if not nums:
        return []
    notes = []                             # (num, systems, key entry)
    for t, r, h in lines:
        m = _DROP_NOTE.match(t)
        if not m:
            continue
        size = _norm_size(m.group(1))
        systems = [m.group(2).upper()] + [
            s.upper() for s in re.findall(r"[A-Z]{1,4}", m.group(3) or "",
                                          re.I)]
        systems = [s for s in systems
                   if PIPE_RE.match(f'{size}" {s}')]
        if not systems:
            continue
        # its bubble number: the nearest numbered bubble beside the start
        # of the note line
        best = None
        for n in nums:
            nb = n[3]
            d = math.hypot(max(nb.x0 - r.x1, r.x0 - nb.x1, 0),
                           max(nb.y0 - r.y1, r.y0 - nb.y1, 0))
            if d <= 3.0 * h and (best is None or d < best[0]):
                best = (d, n)
        if best is None:
            continue
        notes.append((best[1][0], [f'{size}" {s}' for s in systems],
                      best[1]))
    if not notes:
        return []
    keys = [n[2] for n in notes]

    def in_list(n):
        # a numbered bubble in the notes column: lined up with a note's
        # own bubble and close to it
        c = n[3]
        for k in keys:
            b = k[3]
            if c == b:
                return True
            dx = abs((c.x0 + c.x1) - (b.x0 + b.x1)) / 2
            dy = abs((c.y0 + c.y1) - (b.y0 + b.y1)) / 2
            if (dx <= n[2] or dy <= n[2]) and max(dx, dy) <= 25 * n[2]:
                return True
        return False
    plan = [n for n in nums if not in_list(n)]
    out = {}
    for num, names, key in notes:
        kb = key[3]
        size = max(kb.width, kb.height)
        hits = [n for n in plan if n[0] == num and
                0.6 * size <= max(n[3].width, n[3].height) <= 1.6 * size]
        if not hits:
            continue
        for nm in names:
            g = out.setdefault(nm, {"name": nm, "drops": 0, "keys": []})
            g["drops"] += len(hits)
            g["keys"].append(num)
    res = []
    for g in out.values():
        g["assumption"] = True
        if g["name"].split()[-1] not in SUPPLY_SYSTEMS:
            # waste / vent / other rises run floor to roof or below the
            # slab - the ceiling-to-fixture default does not apply
            g["length_ft"] = None
            g["basis"] = (f"{g['drops']} vertical rise(s)/drop(s) at "
                          f"keynote(s) {', '.join(sorted(set(g['keys']), key=int))}"
                          " - height not shown in plan; review and measure "
                          "from the sections / riser diagram")
            res.append(g)
            continue
        g["length_ft"] = g["drops"] * drop_ft
        g["basis"] = (f"{g['drops']} drop(s)/rise(s) at keynote(s) "
                      f"{', '.join(sorted(set(g['keys']), key=int))} x "
                      f"{drop_ft:g} ft each - ASSUMED drop height (not drawn "
                      "in plan); change it to suit the ceiling and fixture "
                      "heights (setting 'pipe_drop_ft')")
        res.append(g)
    res.sort(key=lambda g: g["name"])
    return res


# ------------------------------------------------------------- flex duct
# Flexible run-outs to air devices are drawn as a row of short cross-ticks
# the width of the duct, laid along a (usually curved) centreline, and
# are seldom tagged. A run is a chain of ticks in one pen, near-parallel
# to each other, each square to the chain, spaced closely (spacing at most
# FLEX_SPACING x the tick length - wall hatch and treads are spaced wider
# or lie at an angle). Its length is the path through the tick centres;
# its size is the tick length at scale, rounded to a standard round size.
# The size is read from the drawing, not a tag, and is flagged as such.
FLEX_SIZES_IN = (4, 5, 6, 7, 8, 9, 10, 12, 14, 16)
FLEX_SPACING = 0.35
FLEX_MIN_TICKS = 6


def flex_runs(page, ppu, unit):
    """[{name, size_in, length, n_ticks, pts}] - flex run-outs on a page."""
    per_in = ppu / (12.0 if unit == "ft" else 1000 / 25.4)    # pt per inch
    lo, hi = 3 * per_in, (FLEX_SIZES_IN[-1] + 1) * per_in
    ticks = []
    for st, segs in styled_segments(page).items():
        for x0, y0, x1, y1 in segs:
            L = math.hypot(x1 - x0, y1 - y0)
            if lo <= L <= hi:
                ticks.append((st, (x0 + x1) / 2, (y0 + y1) / 2,
                              (x1 - x0) / L, (y1 - y0) / L, L))
    G = hi
    grid = {}
    for i, t in enumerate(ticks):
        grid.setdefault((int(t[1] // G), int(t[2] // G)), []).append(i)
    adj = {}
    for i, a in enumerate(ticks):
        gx, gy = int(a[1] // G), int(a[2] // G)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in grid.get((gx + dx, gy + dy), ()):
                    if j <= i:
                        continue
                    b = ticks[j]
                    if a[0] != b[0] or abs(a[5] - b[5]) > 0.25 * max(a[5], b[5]):
                        continue
                    mx, my = b[1] - a[1], b[2] - a[2]
                    dd = math.hypot(mx, my)
                    if dd < 0.05 * a[5] or dd > FLEX_SPACING * max(a[5], b[5]):
                        continue
                    if abs(a[3] * b[3] + a[4] * b[4]) < 0.8:
                        continue                         # not parallel
                    if abs(a[3] * mx + a[4] * my) / dd > 0.5:
                        continue                         # not square to run
                    adj.setdefault(i, set()).add(j)
                    adj.setdefault(j, set()).add(i)
    seen, out = set(), []
    for i in adj:
        if i in seen:
            continue
        comp, st = [], [i]
        seen.add(i)
        while st:
            k = st.pop()
            comp.append(k)
            for n in adj[k]:
                if n not in seen:
                    seen.add(n)
                    st.append(n)
        if len(comp) < FLEX_MIN_TICKS:
            continue
        pts = [(ticks[k][1], ticks[k][2]) for k in comp]
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        cur = max(range(len(pts)),
                  key=lambda k: (pts[k][0] - cx) ** 2 + (pts[k][1] - cy) ** 2)
        left = set(range(len(pts))) - {cur}
        path, L = [pts[cur]], 0.0
        while left:
            n = min(left, key=lambda k: math.dist(pts[k], pts[cur]))
            L += math.dist(pts[n], pts[cur])
            cur = n
            left.discard(n)
            path.append(pts[n])
        tl = sorted(ticks[k][5] for k in comp)[len(comp) // 2] / per_in
        size = min(FLEX_SIZES_IN, key=lambda s: abs(s - tl))
        if abs(size - tl) > 0.25 * size:
            continue
        L += L / max(len(pts) - 1, 1)          # half a pitch at each end
        if L / ppu < 1.0:
            continue
        out.append({"name": f'{size}" round flex', "size_in": size,
                    "length": _hu(L / ppu, 2), "n_ticks": len(comp),
                    "pts": [list(p) for p in path]})
    return out


# ------------------------------------------------------------- linetypes
def legend_linetypes(page, max_len_ratio=0.25):
    """Line types a legend defines by a sample line ('—— SILT FENCE',
    '—x—x— CHAIN LINK FENCE'): [{"name", "style", "sample" rect,
    "length" (drawing units, outside the legend), "shared"}].

    The sample's pen (colour, width, dash) is looked up over the whole
    sheet; its length elsewhere is the run of that line type. "shared"
    is True when the pen is also a common drafting pen on the sheet
    (more than `max_len_ratio` of all linework, or used by another
    legend sample) - then the length can't be trusted."""
    words = page.get_text("words")
    heads = []
    for w in words:
        if w[4].strip(":").upper() in ("LEGEND", "SYMBOLS", "SYMBOL"):
            heads.append(fitz.Rect(w[:4]))
    if not heads:
        return []
    lines = {}
    for w in words:
        lines.setdefault((w[5], w[6]), []).append(w)
    rows = []
    for ws in lines.values():
        ws.sort(key=lambda w: w[0])
        r = fitz.Rect(ws[0][:4])
        for w in ws[1:]:
            r |= fitz.Rect(w[:4])
        rows.append((r, " ".join(w[4] for w in ws)))
    styles = styled_segments(page)
    total_all = sum(math.hypot(s[2] - s[0], s[3] - s[1])
                    for segs in styles.values() for s in segs) or 1.0
    out = []
    for h in heads:
        below = [(r, t) for r, t in rows
                 if h.y1 - 1 <= r.y0 <= h.y1 + LEGEND_REACH_PT and
                 h.x0 - 150 <= r.x0 <= h.x0 + 450 and
                 len(t.strip()) >= 4 and good_name(t)]
        for r, t in below:
            hgt = max(r.height, 6)
            box = fitz.Rect(r.x0 - 12 * hgt, r.y0 - 0.6 * hgt, r.x0 - 2,
                            r.y1 + 0.6 * hgt)
            # the pen drawing most of a long horizontal sample in the box
            best = None
            for st, segs in styles.items():
                L = 0.0
                for s in segs:
                    if box.contains(fitz.Point(s[0], s[1])) and \
                            box.contains(fitz.Point(s[2], s[3])) and \
                            abs(s[3] - s[1]) <= 0.5:
                        L += abs(s[2] - s[0])
                if L >= 3 * hgt and (best is None or L > best[0]):
                    best = (L, st)
            if best is None:
                continue
            out.append({"name": re.sub(r"\s+", " ", t.strip()),
                        "style": best[1], "sample": box})
    zone = None
    for o in out:
        zone = o["sample"] if zone is None else zone | o["sample"]
    seen = {}
    for o in out:
        seen[o["style"]] = seen.get(o["style"], 0) + 1
    for o in out:
        segs = []
        for s in styles.get(o["style"], ()):
            mid = fitz.Point((s[0] + s[2]) / 2, (s[1] + s[3]) / 2)
            if zone is not None and (zone + (-20, -20, 20, 20)).contains(mid):
                continue
            segs.append(s)
        # a dashed line type (silt fence: dashes with 'SF' between them)
        # is measured along its whole run: the dash gaps and the gap for
        # the letters are closed up; the letters' own strokes (short,
        # not in line with a dash) are left out
        closed, linked = close_dash_gaps(runs(segs), max_gap=30.0)
        L = 0.0
        for k, r in enumerate(closed):
            pl = poly_len(r)
            if k in linked or pl >= 12.0:
                L += pl
        o["length"] = L
        allst = sum(math.hypot(s[2] - s[0], s[3] - s[1])
                    for s in styles.get(o["style"], ()))
        o["shared"] = seen[o["style"]] > 1 or \
            allst > max_len_ratio * total_all
    return out
