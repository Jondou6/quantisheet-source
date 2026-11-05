"""Trace Outline: an area tool that follows the drawing's own linework.

Irregular slabs, foundations and paving edges are drawn as long vector
paths with many corners (and curves). Tracing one by hand means a click on
every corner. With Trace Outline:

- every click lands on the nearest vertex of a drawn path (or, failing
  that, the nearest point on one of its edges) within a few pixels;
- "follow edge": when the next click is on the same drawn path as the
  previous one, the path's own vertices between the two clicks are put in
  as well - the shorter way round on a closed path, so three or four
  clicks trace a slab with dozens of corners. Paths drawn as separate,
  end-to-end pieces (common in CAD exports) are followed too, through the
  points where their ends meet;
- the outline does not have to close on the drawing (paving that runs off
  the sheet, a match line, a messy outline with gaps): the area is the
  polygon of the clicked and followed points, closed from the last point
  back to the first.

Coordinates are the page as displayed (rotation applied, before zoom), as
in snap.py. The index of a page's paths is built once and cached by the
viewer (PdfView.trace_index).
"""
import heapq
import math

CELL = 24.0                  # grid cell, points
MAX_SEGMENTS = 300_000       # dense sheets: index the first this many
CURVE_STEPS = 8              # a Bezier is followed as this many pieces
JOIN = 0.6                   # path ends this close (points) are joined
VERTEX, EDGE = "vertex", "edge"


def _xy(p):
    if isinstance(p, (tuple, list)):
        return (float(p[0]), float(p[1]))
    return (float(p.x), float(p.y))


def _bez(p0, p1, p2, p3, t):
    m = 1 - t
    return (m ** 3 * p0[0] + 3 * m * m * t * p1[0] + 3 * m * t * t * p2[0] +
            t ** 3 * p3[0],
            m ** 3 * p0[1] + 3 * m * m * t * p1[1] + 3 * m * t * t * p2[1] +
            t ** 3 * p3[1])


def _d(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])


class Chain:
    """One drawn run of connected pieces: `pts` [(x, y)], `real` [bool]
    (False for points put in along a curve), `closed`."""
    __slots__ = ("pts", "real", "closed")

    def __init__(self, pts, real=None, closed=False):
        real = list(real) if real is not None else [True] * len(pts)
        self.pts, self.real = [], []
        for p, r in zip(pts, real):
            p = tuple(p)
            if self.pts and _d(self.pts[-1], p) <= 1e-6:
                self.real[-1] = self.real[-1] or r      # drawn twice
                continue
            self.pts.append(p)
            self.real.append(r)
        self.closed = bool(closed)
        if len(self.pts) >= 3 and _d(self.pts[0], self.pts[-1]) <= JOIN:
            self.pts.pop()                 # drawn back to its start
            self.real.pop()
            self.closed = True

    def nseg(self):
        n = len(self.pts)
        return n if self.closed else n - 1

    def seg(self, i):
        n = len(self.pts)
        return self.pts[i % n], self.pts[(i + 1) % n]


def chains_from_drawings(drawings, matrix=None):
    """Chains of a page's drawings (page.get_drawings() or
    get_cdrawings() output). `matrix`: a callable (x, y) -> (x, y) for the
    page's rotation, or None."""
    out = []

    def tr(p):
        p = _xy(p)
        return matrix(p) if matrix else p
    for d in drawings:
        cur, real = [], []

        def flush(closed=False):
            if len(cur) >= 2:
                out.append(Chain(cur, real, closed))
        for it in d.get("items", ()):
            try:
                op = it[0]
                if op == "l":
                    a, b = tr(it[1]), tr(it[2])
                    if cur and _d(cur[-1], a) <= 0.01:
                        cur.append(b)
                        real.append(True)
                    else:
                        flush()
                        cur, real = [a, b], [True, True]
                elif op == "c":
                    raw = [_xy(q) for q in it[1:5]]
                    a = tr(raw[0])
                    if not (cur and _d(cur[-1], a) <= 0.01):
                        flush()
                        cur, real = [a], [True]
                    for k in range(1, CURVE_STEPS + 1):
                        cur.append(tr(_bez(*raw, k / CURVE_STEPS)))
                        real.append(k == CURVE_STEPS)
                elif op in ("re", "qu"):
                    flush()
                    cur, real = [], []
                    r = it[1]
                    if op == "re":
                        if isinstance(r, (tuple, list)) and len(r) == 4 and \
                                not isinstance(r[0], (tuple, list)):
                            x0, y0, x1, y1 = (float(v) for v in r)
                        else:
                            x0, y0, x1, y1 = r.x0, r.y0, r.x1, r.y1
                        c = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
                    else:
                        if hasattr(r, "ul"):
                            c = [_xy(r.ul), _xy(r.ur), _xy(r.lr), _xy(r.ll)]
                        else:                       # cdrawings: 4 points
                            c = [_xy(q) for q in r][:4]
                    out.append(Chain([tr(q) for q in c], closed=True))
            except Exception:
                continue                    # one odd item, not the page
        flush(bool(d.get("closePath")))
    return out


class Snap:
    """Where a click landed: (x, y), VERTEX or EDGE, on chain `chain` at
    position `pos` (segment index + fraction along it)."""
    __slots__ = ("x", "y", "kind", "chain", "pos")

    def __init__(self, x, y, kind, chain, pos):
        self.x, self.y, self.kind, self.chain, self.pos = x, y, kind, chain, pos

    def __repr__(self):
        return (f"Snap({self.x:.2f}, {self.y:.2f}, {self.kind}, "
                f"chain={self.chain}, pos={self.pos:.3f})")


class TraceIndex:
    """The page's drawn paths with a grid for lookups near the cursor."""

    def __init__(self, chains):
        self.chains = []
        self.grid = {}
        total = 0
        for ch in chains:
            if len(ch.pts) < 2:
                continue
            ci = len(self.chains)
            self.chains.append(ch)
            for si in range(ch.nseg()):
                a, b = ch.seg(si)
                if not all(map(math.isfinite, a + b)):
                    continue
                total += 1
                n = int(_d(a, b) / CELL) + 1
                if n > 400:
                    continue                 # absurd: off-page junk
                cells = set()
                for k in range(n + 1):
                    t = k / n
                    cells.add((int((a[0] + (b[0] - a[0]) * t) // CELL),
                               int((a[1] + (b[1] - a[1]) * t) // CELL)))
                for c in cells:
                    self.grid.setdefault(c, []).append((ci, si))
            if total > MAX_SEGMENTS:
                break
        self._graph = None

    @classmethod
    def from_page(cls, page):
        try:
            drawings = page.get_cdrawings()
        except Exception:
            drawings = page.get_drawings()
        matrix = None
        if page.rotation:
            m = page.rotation_matrix
            matrix = (lambda p, m=m: (p[0] * m.a + p[1] * m.c + m.e,
                                      p[0] * m.b + p[1] * m.d + m.f))
        return cls(chains_from_drawings(drawings, matrix))

    def _near(self, x, y, r):
        out = set()
        for cx in range(int((x - r) // CELL), int((x + r) // CELL) + 1):
            for cy in range(int((y - r) // CELL), int((y + r) // CELL) + 1):
                out.update(self.grid.get((cx, cy), ()))
        return out

    def snap(self, pt, radius):
        """The best Snap within `radius` of pt (x, y), or None. A path
        vertex wins over a point on an edge; among vertices, the nearest."""
        x, y = _xy(pt)
        best_v = best_e = None
        for ci, si in self._near(x, y, radius):
            ch = self.chains[ci]
            a, b = ch.seg(si)
            dx, dy = b[0] - a[0], b[1] - a[1]
            L2 = dx * dx + dy * dy
            t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((x - a[0]) * dx +
                                                      (y - a[1]) * dy) / L2))
            qx, qy = a[0] + t * dx, a[1] + t * dy
            de = math.hypot(qx - x, qy - y)
            if de > radius:
                continue
            n = len(ch.pts)
            for k, p in ((si, a), (si + 1, b)):
                if not ch.real[k % n]:
                    continue
                dv = math.hypot(p[0] - x, p[1] - y)
                if dv <= radius and (best_v is None or dv < best_v[0]):
                    pos = float(k % n) if ch.closed else float(k)
                    best_v = (dv, Snap(p[0], p[1], VERTEX, ci, pos))
            if best_e is None or de < best_e[0]:
                best_e = (de, Snap(qx, qy, EDGE, ci, si + t))
        if best_v is not None:
            return best_v[1]
        return best_e[1] if best_e else None

    # ---- following the drawing between two clicks --------------------------
    def _at(self, ch, pos):
        n = len(ch.pts)
        i = int(math.floor(pos))
        t = pos - i
        if not ch.closed and i >= n - 1:
            return ch.pts[-1]
        a, b = ch.pts[i % n], ch.pts[(i + 1) % n]
        return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)

    def _run(self, ch, p0, p1, step):
        """Vertices strictly between positions p0 and p1 going `step`
        (+1 / -1) along the chain, and the length of that way."""
        n = len(ch.pts)
        eps = 1e-6
        pts = []
        if step > 0:
            k = math.floor(p0 + eps) + 1
            end = p1 if p1 > p0 + eps or not ch.closed else p1 + n
            while k < end - eps:
                pts.append(ch.pts[int(k) % n])
                k += 1
        else:
            k = math.ceil(p0 - eps) - 1
            end = p1 if p1 < p0 - eps or not ch.closed else p1 - n
            while k > end + eps:
                pts.append(ch.pts[int(k) % n])
                k -= 1
        a = self._at(ch, p0)
        b = self._at(ch, p1 % n if ch.closed else p1)
        way = [a] + pts + [b]
        return pts, sum(_d(way[i], way[i + 1]) for i in range(len(way) - 1))

    def between(self, s0, s1):
        """Drawn vertices from Snap s0 to Snap s1 along the drawing
        (neither end included), or None when they aren't on connected
        linework. [] means they are joined directly."""
        if s0 is None or s1 is None:
            return None
        if _d((s0.x, s0.y), (s1.x, s1.y)) < 1e-6:
            return []
        if s0.chain == s1.chain:
            ch = self.chains[s0.chain]
            if not ch.closed:
                step = 1 if s1.pos >= s0.pos else -1
                return self._run(ch, s0.pos, s1.pos, step)[0]
            fwd, lf = self._run(ch, s0.pos, s1.pos, 1)
            back, lb = self._run(ch, s0.pos, s1.pos, -1)
            return fwd if lf <= lb else back
        return self._graph_path(s0, s1)

    # pieces drawn as separate paths that meet end to end
    def _key(self, p):
        return (round(p[0] / JOIN), round(p[1] / JOIN))

    def _build_graph(self):
        adj = {}
        where = {}
        for ci, ch in enumerate(self.chains):
            n = len(ch.pts)
            for si in range(ch.nseg()):
                a, b = ch.pts[si % n], ch.pts[(si + 1) % n]
                ka, kb = self._key(a), self._key(b)
                if ka == kb:
                    continue
                w = _d(a, b)
                adj.setdefault(ka, {})
                adj.setdefault(kb, {})
                if w < adj[ka].get(kb, 1e18):
                    adj[ka][kb] = adj[kb][ka] = w
                where.setdefault(ka, a)
                where.setdefault(kb, b)
        self._graph = (adj, where)

    def _graph_path(self, s0, s1, max_nodes=20000):
        if self._graph is None:
            self._build_graph()
        adj, where = self._graph

        def ends(s):
            ch = self.chains[s.chain]
            n = len(ch.pts)
            p = (s.x, s.y)
            if s.kind == VERTEX:
                k = self._key(ch.pts[int(round(s.pos)) % n])
                return [(k, 0.0)]
            i = int(math.floor(s.pos))
            a, b = ch.pts[i % n], ch.pts[(i + 1) % n]
            return [(self._key(a), _d(p, a)), (self._key(b), _d(p, b))]
        start = ends(s0)
        goal = dict(ends(s1))
        direct = _d((s0.x, s0.y), (s1.x, s1.y))
        limit = 4.0 * direct + 2.0
        dist, prev, heap = {}, {}, []
        for k, w in start:
            if k in adj and w < dist.get(k, 1e18):
                dist[k] = w
                prev[k] = None
                heapq.heappush(heap, (w, k))
        best = None
        seen = 0
        while heap:
            w, k = heapq.heappop(heap)
            if w > dist.get(k, 1e18):
                continue
            if best is not None and w >= best[0]:
                break
            if w > limit:
                break
            seen += 1
            if seen > max_nodes:
                break
            if k in goal:
                tot = w + goal[k]
                if best is None or tot < best[0]:
                    best = (tot, k)
            for nk, ew in adj.get(k, {}).items():
                nw = w + ew
                if nw < dist.get(nk, 1e18):
                    dist[nk] = nw
                    prev[nk] = k
                    heapq.heappush(heap, (nw, nk))
        if best is None or best[0] > limit:
            return None
        path = []
        k = best[1]
        while k is not None:
            path.append(where[k])
            k = prev[k]
        path.reverse()
        a, b = (s0.x, s0.y), (s1.x, s1.y)
        return [p for p in path if _d(p, a) > 1e-6 and _d(p, b) > 1e-6]


# ---- the numbers while tracing ----------------------------------------------
def polygon_area(pts):
    n = len(pts)
    if n < 3:
        return 0.0
    s = 0.0
    for i in range(n):
        x0, y0 = _xy(pts[i])
        x1, y1 = _xy(pts[(i + 1) % n])
        s += x0 * y1 - x1 * y0
    return abs(s) / 2.0


def path_length(pts):
    q = [_xy(p) for p in pts]
    return sum(_d(q[i], q[i + 1]) for i in range(len(q) - 1))


def measures(pts, ppu):
    """{"area", "perimeter", "length", "points"} of the outline `pts`
    (page points) at `ppu` points per unit: area closed back to the first
    point, perimeter closed, length as clicked (open)."""
    q = [_xy(p) for p in pts]
    length = path_length(q)
    closing = _d(q[-1], q[0]) if len(q) >= 3 else 0.0
    ppu = float(ppu or 0) or 1.0
    return {"area": polygon_area(q) / ppu ** 2,
            "perimeter": (length + closing) / ppu,
            "length": length / ppu, "points": len(q)}


def readout(pts, ppu, unit, fmt=None):
    """One line for the live readout: area, perimeter, length, points."""
    m = measures(pts, ppu)
    f = fmt or (lambda v, u: f"{v:,.2f} {u}")
    return (f"Area {m['area']:,.2f} sq {unit} · Perim "
            f"{f(m['perimeter'], unit)} · Len {f(m['length'], unit)} "
            f"· {m['points']} pts")
