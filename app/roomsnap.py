"""A traced room outline put back on the drawing's own lines.

Auto takeoff finds a room in a picture of the sheet (24 pixels to the
foot at most), so each side of its outline is good to about a pixel: half
an inch at 1/4" scale, an inch at 1/8". On a 3' x 4' closet that inch all
round is 4% of the floor. The walls are drawn as lines with exact
coordinates; where a side of the traced outline runs along one of them,
the side is moved onto it and the corners are worked out again from the
moved sides. The area is then the drawing's, not the picture's.

Only sides that run square to the sheet are moved (angled walls keep the
traced position, corrected for the pen as before), each onto the nearest
drawn line within a pixel or two of where the wall face has to be, and
only when that line runs alongside at least half of the side.
"""
import math

try:
    import numpy as np
except ImportError:                  # pragma: no cover
    np = None
try:
    import cv2
except ImportError:                  # pragma: no cover
    cv2 = None

TOL_PX = 1.75          # a face line is this close to where the trace says
COVER_NEAR = 0.15      # ...or this, within NEAR_PX of where the face must be
NEAR_PX = 1.2
COVER = 0.35           # ...and runs along this share of the side
STEP_PX = 4            # a side's levels are within this of its middle
JOIN_PX = 0.45         # pieces of one face line are within this of each other
LEVEL = 0.3            # a row holding this share of a side is one of its
                       # levels (a side steps in where a door was shut)
MIN_SIDE_PX = 4.0      # shorter sides are left where they are
STRAIGHT = 0.8         # share of a side's run that is square to the sheet
MAX_MOVE_PX = 4.0      # no corner moves further than this (plus the inset)


def face_lines(points, offs, keep, min_len):
    """{'h': (y, x0, x1), 'v': (x, y0, y1)} arrays, sorted by the first
    column: the straight pieces of the drawing's outlines that run square
    to the picture. `points` (n, 2) pixels (not rounded), `offs` where
    each outline starts (len = outlines + 1), `keep` which outlines
    count, `min_len` pixels."""
    n = len(points)
    if n < 2:
        z = np.zeros((0, 3))
        return {"h": z, "v": z}
    ok = np.ones(n - 1, bool)
    starts = np.asarray(offs[1:-1], int)
    ok[starts[(starts > 0) & (starts < n)] - 1] = False   # not across two
    owner = np.repeat(np.arange(len(offs) - 1), np.diff(offs))
    ok &= np.asarray(keep, bool)[owner[:-1]]
    a, b = points[:-1][ok], points[1:][ok]
    d = np.abs(b - a)
    out = {}
    for key, along, across in (("h", 0, 1), ("v", 1, 0)):
        sel = (d[:, across] <= 0.3) & (d[:, along] >= min_len)
        c = (a[sel, across] + b[sel, across]) / 2
        lo = np.minimum(a[sel, along], b[sel, along])
        hi = np.maximum(a[sel, along], b[sel, along])
        order = np.argsort(c, kind="stable")
        out[key] = np.column_stack([c[order], lo[order], hi[order]])
    return out


def _nearest(lines, want, lo, hi, tol, out=0.0, reach=0.0, edge=None):
    """The wall face for a side traced along `edge` (its row or column of
    pixels): the drawn line nearest `want` (where the face should be) -
    outward of the trace, no further than `tol` from `want` (or `reach`
    past it) - that runs alongside [lo, hi] for at least COVER of it.
    None when there is none."""
    if not len(lines):
        return None
    far = max(tol, reach)
    if edge is None:
        a, b = want - tol, want + tol
    elif out > 0:
        a, b = edge + 0.4, want + far
    else:
        a, b = want - far, edge - 0.4
    i0 = np.searchsorted(lines[:, 0], a, "left")
    i1 = np.searchsorted(lines[:, 0], b, "right")
    if i1 <= i0:
        return None
    cand = lines[i0:i1]
    ov = np.minimum(cand[:, 2], hi) - np.maximum(cand[:, 1], lo)
    cand, ov = cand[ov > 0], ov[ov > 0]
    if not len(cand):
        return None
    # pieces of one line (a face broken by openings) count together -
    # also when they are a hair apart (CAD float noise, a third of a
    # pixel): every piece within JOIN_PX of a position counts for it
    best, best_d = None, None
    for pos0 in np.unique(np.round(cand[:, 0] * 8) / 8):
        m = np.abs(cand[:, 0] - pos0) <= JOIN_PX
        pos = float(np.average(cand[m, 0], weights=ov[m]))
        dd = abs(pos - want)
        # a line right where the face has to be needs less of the side
        # beside it: a closet's door takes most of the wall it is in
        need = (COVER_NEAR if dd <= NEAR_PX else COVER) * (hi - lo)
        if _covered(cand[m, 1], cand[m, 2], lo, hi) < need:
            continue
        if best is None or dd < best_d - 1e-9:
            best, best_d = pos, dd
    return best


def _covered(a, b, lo, hi):
    """Length of [lo, hi] covered by the intervals (a, b) (overlaps
    counted once)."""
    tot, end = 0.0, lo
    for s0, s1 in sorted(zip(np.maximum(a, lo), np.minimum(b, hi))):
        if s1 > end:
            tot += s1 - max(s0, end)
            end = s1
    return tot


def _face(lines, pos, levels, out, inset, lo, hi, tol, reach=0.0):
    """The face line for a side traced at `pos`: looked for from the
    side's outermost level first (a door shut across an opening is drawn
    3" wide, so the trace steps in there - the wall face is where the
    rest of the side is)."""
    for v in sorted(set(levels) | {pos}, reverse=out > 0):
        if (v - pos) * out < 0:
            continue                         # inside the middle: not a face
        got = _nearest(lines, v + out * inset, lo, hi, tol, out, reach,
                       edge=v)
        if got is not None:
            return got
    return None


def _run_kind(run):
    """('h'|'v', position) when the contour run lies along one row or
    column of pixels, else ('g', None)."""
    a, b = run[:-1], run[1:]
    d = b - a
    ext = np.abs(run[-1] - run[0]).astype(float)
    for key, along, across in (("h", 0, 1), ("v", 1, 0)):
        if ext[along] < MIN_SIDE_PX or ext[across] > 0.35 * ext[along] + 3:
            continue
        flat = d[:, across] == 0
        length = np.abs(d[flat, along]).astype(float)
        if length.sum() < STRAIGHT * ext[along]:
            continue
        pos = a[flat, across].astype(float)
        order = np.argsort(pos)
        cum = np.cumsum(length[order])
        med = pos[order][np.searchsorted(cum, cum[-1] / 2)]
        # most of it on that row, or stepped in a few pixels from it
        # (a shut door's line is 3" wide)
        if length[np.abs(pos - med) <= STEP_PX].sum() < \
                STRAIGHT * ext[along]:
            continue
        levels = {}
        for v, ln in zip(pos, length):
            levels[float(v)] = levels.get(float(v), 0.0) + float(ln)
        need = LEVEL * ext[along]
        # rows a pixel apart are one level (the two ends of a wall face
        # can land on neighbouring rows)
        out, grp = [], []
        for v in sorted(levels):
            if grp and v - grp[-1] > 1:
                out.append(grp)
                grp = []
            grp.append(v)
        if grp:
            out.append(grp)
        return key, float(med), [
            sum(v * levels[v] for v in g) / sum(levels[v] for v in g)
            for g in out if sum(levels[v] for v in g) >= need]
    return "g", None, []


def snap(contour, eps, faces, inset, tol=TOL_PX, reach=0.0):
    """(corners (m, 2) float pixels, share of the outline's length moved
    onto drawn lines) for the traced `contour` (cv2, closed), or None
    when the outline can't be rebuilt. `reach` (pixels): how far outside
    the trace a face may be (a side with a door shut in it is traced
    along the door's line, 3" wide, not along the wall face). `eps`: the simplification
    (pixels), `faces` from face_lines, `inset`: how far inside the wall
    face the trace runs (pixels)."""
    c = np.asarray(contour).reshape(-1, 2).astype(np.int64)
    n = len(c)
    if n < 4:
        return None
    poly = cv2.approxPolyDP(c.reshape(-1, 1, 2).astype(np.int32), eps,
                            True).reshape(-1, 2).astype(np.int64)
    m = len(poly)
    if m < 3:
        return None
    # where each corner sits in the contour
    idx, j = [], 0
    for p in poly:
        k = None
        for s in range(n):
            q = (j + s) % n
            if c[q, 0] == p[0] and c[q, 1] == p[1]:
                k = q
                break
        if k is None:
            return None
        idx.append(k)
        j = k
    x, y = c[:, 0].astype(float), c[:, 1].astype(float)
    signed = 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))
    if signed == 0:
        return None
    sgn = 1.0 if signed > 0 else -1.0
    lines = []                       # each side as (nx, ny, d): n.p = d
    moved = total = 0.0
    for i in range(m):
        k0, k1 = idx[i], idx[(i + 1) % m]
        run = c[k0:k1 + 1] if k1 > k0 else np.vstack([c[k0:], c[:k1 + 1]])
        p, q = poly[i].astype(float), poly[(i + 1) % m].astype(float)
        dx, dy = q - p
        L = math.hypot(dx, dy)
        if L == 0:
            return None
        nx, ny = sgn * dy / L, -sgn * dx / L          # outward
        total += L
        kind, pos, levels = _run_kind(run) if len(run) >= 2 else \
            ("g", None, [])
        if kind == "h":
            out = 1.0 if ny > 0 else -1.0
            lo, hi = sorted((p[0], q[0]))
            got = _face(faces["h"], pos, levels, out, inset, lo, hi, tol,
                        reach)
            if got is not None:
                moved += L
            lines.append((0.0, out, out * (got if got is not None
                                           else pos + out * inset)))
        elif kind == "v":
            out = 1.0 if nx > 0 else -1.0
            lo, hi = sorted((p[1], q[1]))
            got = _face(faces["v"], pos, levels, out, inset, lo, hi, tol,
                        reach)
            if got is not None:
                moved += L
            lines.append((out, 0.0, out * (got if got is not None
                                           else pos + out * inset)))
        else:
            lines.append((nx, ny, nx * p[0] + ny * p[1] + inset))
    pts = []
    limit = MAX_MOVE_PX + inset + eps
    for i in range(m):
        a1, b1, d1 = lines[i - 1]
        a2, b2, d2 = lines[i]
        det = a1 * b2 - a2 * b1
        v = poly[i].astype(float)
        if abs(det) < 0.2:           # the two sides run on (or nearly)
            t = d2 - (a2 * v[0] + b2 * v[1])
            px, py = v[0] + a2 * t, v[1] + b2 * t
        else:
            px = (d1 * b2 - d2 * b1) / det
            py = (a1 * d2 - a2 * d1) / det
        if math.hypot(px - v[0], py - v[1]) > limit:
            return None
        pts.append((px, py))
    return np.array(pts, float), (moved / total if total else 0.0)


def area(pts):
    x, y = pts[:, 0], pts[:, 1]
    return 0.5 * abs(float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)))


def perimeter(pts):
    d = np.roll(pts, -1, axis=0) - pts
    return float(np.hypot(d[:, 0], d[:, 1]).sum())
