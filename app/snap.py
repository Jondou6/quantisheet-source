"""Snap to content, like Bluebeam: while drawing or measuring, the cursor
jumps to line ends, corners, intersections, midpoints and onto lines in the
drawing (and to the points of existing markups).

All coordinates are "screen" page coordinates (the page as displayed,
rotation applied, before zoom), the same as PdfView._sp().
"""
import logging
import math

import fitz

from . import annotate

log = logging.getLogger(__name__)

CELL = 24.0                  # grid cell size, PDF points
MAX_SEGMENTS = 250_000       # stop indexing absurdly dense pages

# kinds, best first
ENDPOINT, INTERSECTION, MIDPOINT, ONLINE = (
    "Endpoint", "Intersection", "Midpoint", "On line")
_RANK = {ENDPOINT: 0, INTERSECTION: 0, MIDPOINT: 1, ONLINE: 2}


def _xy(p):
    return (p[0], p[1]) if isinstance(p, (tuple, list)) else (p.x, p.y)


def page_segments(page):
    """Line segments of the page's vector drawing (display coordinates).
    Curves contribute their chord, so their ends still snap."""
    segs = []
    try:
        drawings = page.get_cdrawings()
    except Exception:
        drawings = page.get_drawings()
    for d in drawings:
        for it in d.get("items", ()):
            try:
                segs += _item_segments(it)
            except Exception:
                continue                     # skip one odd item, not the page
        if len(segs) > MAX_SEGMENTS:
            break
    # drawings come back unrotated; the index works on the page as shown
    if page.rotation:
        m = page.rotation_matrix
        segs = [(_xy(fitz.Point(a) * m), _xy(fitz.Point(b) * m))
                for a, b in segs]
    return segs


def _item_segments(it):
    op = it[0]
    if op == "l":
        return [(_xy(it[1]), _xy(it[2]))]
    if op == "c":
        return [(_xy(it[1]), _xy(it[4]))]
    if op == "re":
        r = fitz.Rect(it[1])
        c = [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)]
    elif op == "qu":
        q = fitz.Quad(it[1])
        c = [_xy(q.ul), _xy(q.ur), _xy(q.lr), _xy(q.ll)]
    else:
        return []
    return [(c[i], c[(i + 1) % 4]) for i in range(4)]


MAX_CELLS = 2_000_000         # grid entries in all: a cap, never a freeze


def clip_segment(a, b, rect):
    """The part of segment a-b inside rect (x0, y0, x1, y1), or None
    (Liang-Barsky). A drawing with one coordinate at x = 1e8 used to make
    the grid step across 4 million cells (11 s, 1.2 GB; Grok r5 #3)."""
    x0, y0, x1, y1 = rect
    dx, dy = b[0] - a[0], b[1] - a[1]
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, a[0] - x0), (dx, x1 - a[0]),
                 (-dy, a[1] - y0), (dy, y1 - a[1])):
        if p == 0:
            if q < 0:
                return None
            continue
        r = q / p
        if p < 0:
            if r > t1:
                return None
            t0 = max(t0, r)
        else:
            if r < t0:
                return None
            t1 = min(t1, r)
    return ((a[0] + t0 * dx, a[1] + t0 * dy),
            (a[0] + t1 * dx, a[1] + t1 * dy))


def page_clip(page):
    """The page's area with one page-size of margin all round, covering
    both rotated and unrotated coordinates - linework beyond that is never
    something to snap to."""
    try:
        boxes = [page.rect, page.mediabox, page.cropbox]
    except Exception:
        return None
    x0 = min(b.x0 for b in boxes)
    y0 = min(b.y0 for b in boxes)
    x1 = max(b.x1 for b in boxes)
    y1 = max(b.y1 for b in boxes)
    m = max(x1 - x0, y1 - y0)
    return (x0 - m, y0 - m, x1 + m, y1 + m)


class SnapIndex:
    """Grid of segments for fast lookup near the cursor.

    `clip`: the page rectangle (x0, y0, x1, y1), with a margin; segments
    are cut to it, so a stray far-off coordinate can't blow the grid up."""

    def __init__(self, segments, clip=None):
        self.segs = []
        self.grid = {}
        seen = set()
        total = 0
        for a, b in segments:
            if not all(map(math.isfinite, (a[0], a[1], b[0], b[1]))):
                continue                               # NaN / inf
            if clip is not None:
                cut = clip_segment(a, b, clip)
                if cut is None:
                    continue                           # off the page
                a, b = cut
            if abs(a[0] - b[0]) + abs(a[1] - b[1]) < 0.5:
                continue                               # dots
            key = tuple(sorted(((round(a[0], 2), round(a[1], 2)),
                                (round(b[0], 2), round(b[1], 2)))))
            if key in seen:
                continue                 # drawn twice (fill + outline)
            seen.add(key)
            i = len(self.segs)
            self.segs.append((a, b))
            n = int(math.hypot(b[0] - a[0], b[1] - a[1]) / CELL) + 1
            if total + n > MAX_CELLS:
                log.warning("snap: page has too much linework; snapping "
                            "covers the first %d segments", len(self.segs))
                self.segs.pop()
                break
            total += n
            cells = set()
            for k in range(n + 1):
                t = k / n
                cells.add((int((a[0] + (b[0] - a[0]) * t) // CELL),
                           int((a[1] + (b[1] - a[1]) * t) // CELL)))
            for c in cells:
                self.grid.setdefault(c, []).append(i)
        self.points = []                               # markup vertices
        self.arrows = {}             # grid cell -> [(bbox, tip)]
        self._find_arrowheads()

    def _find_arrowheads(self, small=20.0, long=30.0):
        """Dimension arrowheads are tiny closed triangles with one corner
        on the end of a long line (the tip). Clicking anywhere on one
        should snap to the tip, never to the back of the arrow."""
        def key(p):
            return (round(p[0], 2), round(p[1], 2))
        adj, deg, longs = {}, {}, set()
        for a, b in self.segs:
            ka, kb = key(a), key(b)
            deg[ka] = deg.get(ka, 0) + 1
            deg[kb] = deg.get(kb, 0) + 1
            L = math.hypot(b[0] - a[0], b[1] - a[1])
            if L <= small:
                adj.setdefault(ka, set()).add(kb)
                adj.setdefault(kb, set()).add(ka)
            elif L >= long:
                longs.add(ka)
                longs.add(kb)
        done = set()
        for p, nbrs in adj.items():
            for q in nbrs:
                for r in adj.get(q, ()):
                    if r == p or r not in nbrs:
                        continue
                    tri = tuple(sorted((p, q, r)))
                    if tri in done:
                        continue
                    done.add(tri)
                    tips = [v for v in tri if v in longs and deg[v] >= 3]
                    if len(tips) != 1:
                        continue
                    tip = tips[0]
                    xs = [v[0] for v in tri]
                    ys = [v[1] for v in tri]
                    box = (min(xs) - 0.6, min(ys) - 0.6,
                           max(xs) + 0.6, max(ys) + 0.6)
                    cell = (int(tip[0] // CELL), int(tip[1] // CELL))
                    self.arrows.setdefault(cell, []).append((box, tip))

    def _arrow_tip(self, x, y):
        cx, cy = int(x // CELL), int(y // CELL)
        for i in (-1, 0, 1):
            for j in (-1, 0, 1):
                for box, tip in self.arrows.get((cx + i, cy + j), ()):
                    if box[0] <= x <= box[2] and box[1] <= y <= box[3]:
                        return tip
        return None

    def near(self, x, y, r):
        """Indexes of segments in the cells around (x, y)."""
        out = set()
        c0, c1 = int((x - r) // CELL) - 1, int((x + r) // CELL) + 1
        r0, r1 = int((y - r) // CELL) - 1, int((y + r) // CELL) + 1
        for cx in range(c0, c1 + 1):
            for cy in range(r0, r1 + 1):
                out.update(self.grid.get((cx, cy), ()))
        return out

    def snap(self, pt, radius, kinds=None):
        """Best snap point within `radius` of `pt`, as (fitz.Point, kind),
        or None.

        Points where several lines meet win over lone line ends close by:
        the tip of a dimension arrow (dimension line, extension line and
        both arrow edges) beats the arrow's back corners a few points away,
        which is where a measurement should start and end."""
        x, y = pt.x, pt.y
        cands = []

        def offer(px, py, kind):
            if kinds is not None and kind not in kinds:
                return
            d = math.hypot(px - x, py - y)
            if d <= radius:
                cands.append((px, py, kind, d))

        for px, py in self.points:
            offer(px, py, ENDPOINT)
        idx = list(self.near(x, y, radius))[:600]
        segs = [self.segs[i] for i in idx]
        close = [s for s in segs if _dist_seg(s[0], s[1], x, y) <= radius]
        for a, b in close:
            offer(a[0], a[1], ENDPOINT)
            offer(b[0], b[1], ENDPOINT)
            offer((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, MIDPOINT)
            q = _closest(a, b, x, y)
            offer(q[0], q[1], ONLINE)
        # intersections only between segments that pass close by
        for i in range(len(close)):
            for j in range(i + 1, min(len(close), i + 80)):
                q = _intersect(close[i], close[j])
                if q:
                    offer(q[0], q[1], INTERSECTION)
        if not cands:
            return None

        def score(c):
            px, py, kind, d = c
            if kind in (ENDPOINT, INTERSECTION):
                deg = sum(1 for s in close
                          if _dist_seg(s[0], s[1], px, py) < 0.35)
                d = d / (1 + 1.5 * (min(max(deg, 1), 5) - 1))
            return (_RANK[kind], d)

        best = min(cands, key=score)
        tip = self._arrow_tip(best[0], best[1])
        if tip is not None:
            return fitz.Point(tip[0], tip[1]), ENDPOINT
        return fitz.Point(best[0], best[1]), best[2]


def _closest(a, b, x, y):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((x - a[0]) * dx +
                                               (y - a[1]) * dy) / L))
    return a[0] + t * dx, a[1] + t * dy


def _dist_seg(a, b, x, y):
    q = _closest(a, b, x, y)
    return math.hypot(q[0] - x, q[1] - y)


def _intersect(s, t):
    (x1, y1), (x2, y2) = s
    (x3, y3), (x4, y4) = t
    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
    if abs(den) < 1e-9:
        return None
    u = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
    v = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / den
    if -1e-6 <= u <= 1 + 1e-6 and -1e-6 <= v <= 1 + 1e-6:
        return x1 + u * (x2 - x1), y1 + u * (y2 - y1)
    return None


def markup_points(page):
    """Vertices of existing markups (display coordinates), so a new
    measurement can start where another one ends."""
    pts = []
    m = page.rotation_matrix
    for a in annotate.iter_annots(page):
        try:
            t = a.type[0]
            if t in (fitz.PDF_ANNOT_LINE, fitz.PDF_ANNOT_POLY_LINE,
                     fitz.PDF_ANNOT_POLYGON):
                for v in a.vertices or []:
                    q = fitz.Point(v) * m
                    pts.append((q.x, q.y))
            elif t in (fitz.PDF_ANNOT_SQUARE, fitz.PDF_ANNOT_CIRCLE):
                r = a.rect
                for c in (r.tl, r.tr, r.br, r.bl):
                    q = c * m
                    pts.append((q.x, q.y))
        except Exception:
            continue
    return pts


def ortho(anchor, pt):
    """Constrain the line anchor->pt to 0/45/90 degrees (hold Shift)."""
    dx, dy = pt.x - anchor.x, pt.y - anchor.y
    d = math.hypot(dx, dy)
    if d == 0:
        return pt
    ang = round(math.atan2(dy, dx) / (math.pi / 4)) * (math.pi / 4)
    return fitz.Point(anchor.x + d * math.cos(ang),
                      anchor.y + d * math.sin(ang))
