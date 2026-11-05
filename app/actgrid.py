"""Acoustical ceiling area off the reflected ceiling plan (accuracy round
6): a lay-in ceiling is drawn as its grid - one thin pen, lines every 2'
(or 2' and 4') both ways. Grid lines are the thin lines with a parallel
partner exactly one tile away; the area they cover is measured by
widening every grid line three-quarters of a tile across itself (EDGE),
which fills the tiles and runs on past the last line for the cut tiles
at the walls.

    grid_area(page, per_ft) -> {"sf", "spacing_ft", "style", "lines",
                                "why"} or None (no grid drawn)

Used to split rooms the finish schedule gives two ceilings ("ACT-1 /
PT-4"): the grid is the lay-in part, the rest is the other ceiling.
"""
import math

PX_PER_FT = 4                    # raster for the area
# each grid line is widened this many tiles across itself: inside the grid
# the tiles fill; at the walls the cut tiles - laid out to be at least half
# a tile - are taken at three-quarters of one
EDGE = 0.75


def _axis_segs(segs, per_ft):
    hs, vs = [], []
    for x0, y0, x1, y1 in segs:
        if abs(y1 - y0) <= 0.3 and abs(x1 - x0) >= 0.5 * per_ft:
            hs.append((min(x0, x1), max(x0, x1), (y0 + y1) / 2))
        elif abs(x1 - x0) <= 0.3 and abs(y1 - y0) >= 0.5 * per_ft:
            vs.append((min(y0, y1), max(y0, y1), (x0 + x1) / 2))
    return hs, vs


def _spaced(lines, per_ft):
    """(share of distinct line positions with a neighbour 2' or 4' away,
    the spacing most found in feet, number of positions)."""
    pos = sorted({round(c, 1) for _a, _b, c in lines})
    if len(pos) < 6:
        return 0.0, None, len(pos)
    hits = {2: 0, 4: 0}
    good = 0
    s = set(pos)
    for p in pos:
        found = False
        for ft in (2, 4):
            d = ft * per_ft
            tol = max(0.4, 0.02 * d)
            if any(abs(q - (p + d)) <= tol or abs(q - (p - d)) <= tol
                   for q in _near(s, p, d + tol)):
                hits[ft] += 1
                found = True
        good += found
    sp = max(hits, key=hits.get)
    return good / len(pos), sp, len(pos)


def _near(s, p, r):
    return [q for q in s if abs(q - p) <= r + 0.5]


def _partnered(lines, per_ft, ft):
    """The lines with a parallel line `ft` feet away overlapping them by
    half their length - a grid's lines; hatching, walls and text strokes
    mostly have none."""
    d = ft * per_ft
    tol = max(0.5, 0.02 * d)
    by = {}
    for ln in lines:
        by.setdefault(int(ln[2] // 2), []).append(ln)
    keep = []
    for a, b, c in lines:
        L = b - a
        hit = False
        for side in (c - d, c + d):
            for k in range(int((side - tol) // 2), int((side + tol) // 2) + 1):
                for a2, b2, c2 in by.get(k, ()):
                    if abs(c2 - side) <= tol and \
                            min(b, b2) - max(a, a2) >= 0.5 * min(L, b2 - a2):
                        hit = True
                        break
                if hit:
                    break
            if hit:
                break
        if hit:
            keep.append((a, b, c))
    return keep


def _pick(lines, per_ft):
    """(spacing ft, the grid's lines) for one direction."""
    k2 = _partnered(lines, per_ft, 2)
    k4 = _partnered(lines, per_ft, 4)
    if len(k4) > 1.25 * len(k2):
        return 4, k4
    return 2, k2


def find_grid(page, per_ft):
    """The pen the lay-in grid is drawn with and its grid lines: (style,
    h lines, v lines, (h spacing, v spacing)) or None."""
    from . import tradetakeoff as tt
    best = None
    for style, segs in tt.styled_segments(page).items():
        if style[2]:                                  # dashed: not a grid
            continue
        if style[1] > 0.6:                            # heavy: walls
            continue
        hs, vs = _axis_segs(segs, per_ft)
        if len(hs) < 6 or len(vs) < 6:
            continue
        sh, kh = _pick(hs, per_ft)
        sv, kv = _pick(vs, per_ft)
        if len(kh) < 6 or len(kv) < 6:
            continue
        # most of the grid pen's long lines are grid
        lh = sum(b - a for a, b, _c in kh)
        lv = sum(b - a for a, b, _c in kv)
        score = min(lh, lv)
        if best is None or score > best[0]:
            best = (score, style, kh, kv, (sh, sv))
    if best is None or best[0] < 40 * per_ft:
        return None
    return best[1], best[2], best[3], best[4]


def grid_area(page, per_ft, clip=None):
    """The area (SF) the lay-in grid covers on `page`; `clip` (x0, y0, x1,
    y1) limits it to the drawing area."""
    try:
        import numpy as np
    except Exception:                                     # noqa: BLE001
        return None
    if not per_ft or per_ft <= 0:
        return None
    g = find_grid(page, per_ft)
    if g is None:
        return None
    style, hs, vs, (sh, sv) = g
    sp = min(sh, sv)
    if clip:
        cx0, cy0, cx1, cy1 = clip
        hs = [h for h in hs if cy0 <= h[2] <= cy1 and h[1] >= cx0 and
              h[0] <= cx1]
        vs = [v for v in vs if cx0 <= v[2] <= cx1 and v[1] >= cy0 and
              v[0] <= cy1]
    if not hs or not vs:
        return None
    k = PX_PER_FT / per_ft                                  # px per unit
    xs = [a for a, _b, _c in hs] + [c for _a, _b, c in vs]
    xe = [b for _a, b, _c in hs] + [c for _a, _b, c in vs]
    ys = [c for _a, _b, c in hs] + [a for a, _b, _c in vs]
    ye = [c for _a, _b, c in hs] + [b for _a, b, _c in vs]
    ox, oy = min(xs) - 3 * per_ft, min(ys) - 3 * per_ft
    W = int((max(xe) - ox) * k) + 3 * PX_PER_FT + 2
    H = int((max(ye) - oy) * k) + 3 * PX_PER_FT + 2
    if W * H > 40_000_000:
        return None
    rh = int(round(EDGE * sh * PX_PER_FT))         # across the h lines
    rv = int(round(EDGE * sv * PX_PER_FT))
    # a tile is grid where it lies between grid lines both ways: each
    # line widened half a tile across itself (a lone line - a fixture
    # edge - covers nothing)
    hm = np.zeros((H, W), dtype=bool)
    vm = np.zeros((H, W), dtype=bool)
    for a, b, c in hs:
        y = int(round((c - oy) * k))
        hm[y, int((a - ox) * k):int(math.ceil((b - ox) * k)) + 1] = True
    for a, b, c in vs:
        x = int(round((c - ox) * k))
        vm[int((a - oy) * k):int(math.ceil((b - oy) * k)) + 1, x] = True
    hd = hm.copy()
    for i in range(1, rh + 1):
        hd[i:, :] |= hm[:-i, :]
        hd[:-i, :] |= hm[i:, :]
    vd = vm.copy()
    for i in range(1, rv + 1):
        vd[:, i:] |= vm[:, :-i]
        vd[:, :-i] |= vm[:, i:]
    cover = hd & vd
    sf = float(cover.sum()) / (PX_PER_FT * PX_PER_FT)
    return {"sf": round(sf, 1), "spacing_ft": (sh, sv), "style": style,
            "lines": len(hs) + len(vs), "mask": cover,
            "origin": (ox, oy, k),
            "why": f"lay-in grid on the reflected ceiling plan ({sh}' x {sv}' "
                   f"tiles, {len(hs) + len(vs)} grid lines) - the area "
                   "it covers, with the cut tiles at the walls taken at "
                   "three-quarters of a tile"}
