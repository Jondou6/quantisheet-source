"""Trace the lines a PDF already contains.

Most plan sheets are vector: a wall line is already drawn exactly, so
clicking it once can measure its whole run instead of clicking every
corner. trace() starts from the drawn segment under the click and follows
connected segments both ways, through corners, until the line ends or
reaches a junction where it can't tell which way to go (it carries
straight on through a T). (Built on the Venice AI draft.)

Coordinates are the page as displayed (rotation applied, before zoom), as
in snap.py.
"""
import math

from . import snap


def _key(p, join):
    return (round(p[0] / join), round(p[1] / join))


def _ends(idx, join):
    """{quantized point: [(segment index, which end 0/1)]}, cached on the
    snap index."""
    cache = getattr(idx, "_trace_ends", None)
    if cache and cache[0] == join:
        return cache[1]
    ends = {}
    for i, (a, b) in enumerate(idx.segs):
        for which, p in ((0, a), (1, b)):
            k = _key(p, join)
            # also file it in neighbouring cells so near misses join
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    ends.setdefault((k[0] + dx, k[1] + dy), []).append(
                        (i, which))
    idx._trace_ends = (join, ends)
    return ends


def nearest(idx, pt, tol=6.0):
    """Index of the drawn segment nearest `pt`, within `tol`, or None."""
    x, y = pt
    best, bd = None, tol
    cx, cy = int(x // snap.CELL), int(y // snap.CELL)
    seen = set()
    for gx in (cx - 1, cx, cx + 1):
        for gy in (cy - 1, cy, cy + 1):
            for i in idx.grid.get((gx, gy), ()):
                if i in seen:
                    continue
                seen.add(i)
                a, b = idx.segs[i]
                d = snap._dist_seg(a, b, x, y)
                if d < bd:
                    best, bd = i, d
    return best


def _dir(a, b):
    L = math.hypot(b[0] - a[0], b[1] - a[1])
    return ((b[0] - a[0]) / L, (b[1] - a[1]) / L) if L else (0.0, 0.0)


def _turn(d1, d2):
    """Angle in degrees between two directions."""
    c = max(-1.0, min(1.0, d1[0] * d2[0] + d1[1] * d2[1]))
    return math.degrees(math.acos(c))


def _walk(idx, ends, start_seg, from_end, join, max_turn, used, limit,
          stop=None):
    """Points beyond end `from_end` of `start_seg`, following the line."""
    a, b = idx.segs[start_seg]
    p, q = (a, b) if from_end == 1 else (b, a)
    d = _dir(p, q)
    pts = []
    cur = q
    for _ in range(limit):
        cands = []
        for j, which in ends.get(_key(cur, join), ()):
            if j in used:
                continue
            s0, s1 = idx.segs[j]
            near, far = (s0, s1) if which == 0 else (s1, s0)
            if math.hypot(near[0] - cur[0], near[1] - cur[1]) > join * 1.5:
                continue
            nd = _dir(near, far)
            t = _turn(d, nd)
            if t <= max_turn:
                cands.append((t, j, far, nd))
        if not cands:
            break
        cands.sort()
        if len(cands) > 1:
            straight = [c for c in cands if c[0] < 10]
            if len(straight) != 1:
                break                         # a junction: stop here
            cands = straight
        t, j, far, nd = cands[0]
        used.add(j)
        pts.append(far)
        cur, d = far, nd
        if stop is not None and math.hypot(far[0] - stop[0],
                                           far[1] - stop[1]) <= join * 1.5:
            break                             # back where it started
    return pts


def _simplify(pts, tol_deg=1.0):
    out = [pts[0]]
    for i in range(1, len(pts) - 1):
        d1 = _dir(out[-1], pts[i])
        d2 = _dir(pts[i], pts[i + 1])
        if d1 == (0.0, 0.0) or _turn(d1, d2) > tol_deg:
            out.append(pts[i])
    out.append(pts[-1])
    return out


def trace(idx, pt, tol=6.0, join=1.0, max_turn=95.0, limit=2000):
    """The connected run of drawn line under `pt`: (points, closed), or
    (None, False) when there's no line within `tol`."""
    seed = nearest(idx, pt, tol)
    if seed is None:
        return None, False
    ends = _ends(idx, join)
    used = {seed}
    a, b = idx.segs[seed]
    fwd = _walk(idx, ends, seed, 1, join, max_turn, used, limit, stop=a)
    closed = bool(fwd) and math.hypot(fwd[-1][0] - a[0],
                                      fwd[-1][1] - a[1]) <= join * 1.5
    back = [] if closed else _walk(idx, ends, seed, 0, join, max_turn, used,
                                   limit)
    pts = list(reversed(back)) + [a, b] + fwd
    if closed:
        pts[-1] = pts[0]
    pts = [tuple(p) for p in pts]
    return _simplify(pts), closed


def length(pts):
    return sum(math.hypot(pts[i + 1][0] - pts[i][0],
                          pts[i + 1][1] - pts[i][1])
               for i in range(len(pts) - 1))
