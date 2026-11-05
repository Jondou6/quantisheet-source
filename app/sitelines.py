"""Site line types on civil plans (accuracy round 6): the limits of
disturbance and silt fence, measured from their own linework.

    lod(page, per_ft) -> {"style", "length_ft", "closed", "area_sf",
                          "loops": [[pts]], "labels"}
        the dashed pen the 'LOD' labels sit on, its dash and label gaps
        closed; the area inside its closed loop(s) is the disturbed area
        (seeding, mulch, erosion control are carried over it).
    marked_lines(page, per_ft) -> [{"style", "marker_in", "length_ft",
                                    "markers", "runs"}]
        thin lines carrying small circles at intervals (silt fence on
        SCDHEC / most state erosion plans: a line with dots).
"""
import math
import re

import fitz

from . import tradetakeoff as tt


def _shoelace(pts):
    a = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        a += x0 * y1 - x1 * y0
    return abs(a) / 2.0


def lod(page, per_ft):
    return labelled(page, per_ft, r"L\.?O\.?D\.?")


def labelled(page, per_ft, label_rx):
    """The line a short label is written along at intervals ('LOD',
    'SF' for silt fence: '--SF--SF--'): the pen whose linework runs
    through most of the labels, its dash gaps and the gaps left for the
    labels closed. {"style", "length_ft", "closed", "area_sf", "loops",
    "labels"}."""
    out = {"style": None, "length_ft": 0.0, "closed": False,
           "area_sf": 0.0, "loops": [], "labels": 0}
    words = [w for w in page.get_text("words")
             if re.fullmatch(label_rx, w[4].strip().upper())]
    if len(words) < 3:
        return out
    out["labels"] = len(words)
    styles = tt.styled_segments(page)
    # the pen whose segments run closest to the labels
    best = None
    for st, segs in styles.items():
        hit = 0
        for w in words:
            cx, cy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
            h = max(w[3] - w[1], w[2] - w[0])
            if any(tt._seg_dist(cx, cy, s[0], s[1], s[2], s[3]) <= 1.5 * h
                   for s in segs):
                hit += 1
        if hit >= 0.6 * len(words) and (best is None or hit > best[0]):
            best = (hit, st)
    if best is None:
        return out
    st = best[1]
    out["style"] = tt.style_name(st)
    rs = tt.runs(styles[st])
    # close the dash gaps and the gaps left for the 'LOD' labels
    closed, _linked = tt.close_dash_gaps(rs, max_gap=8 * max(
        (w[3] - w[1]) for w in words), max_turn=12.0)
    chains = _chain(closed, tol=6.0)
    L = sum(tt.poly_len(c) for c in chains)
    out["length_ft"] = round(L / per_ft, 1)
    loops = [c for c in chains if len(c) > 3 and
             math.hypot(c[0][0] - c[-1][0], c[0][1] - c[-1][1]) <= 12.0]
    if loops:
        out["closed"] = True
        out["loops"] = loops
        out["area_sf"] = round(sum(_shoelace(c) for c in loops) /
                               per_ft / per_ft, 0)
    return out


def _chain(rs, tol):
    """Join runs end to end (nearest ends within tol) into polylines."""
    rs = [list(r) for r in rs if len(r) >= 2]
    out = []
    used = [False] * len(rs)
    for i in range(len(rs)):
        if used[i]:
            continue
        used[i] = True
        cur = list(rs[i])
        grown = True
        while grown:
            grown = False
            for j in range(len(rs)):
                if used[j]:
                    continue
                r = rs[j]
                for a_end in (0, -1):
                    for b_end in (0, -1):
                        p = cur[a_end]
                        q = r[b_end]
                        if math.hypot(p[0] - q[0], p[1] - q[1]) <= tol:
                            seg = r if b_end == 0 else r[::-1]
                            if a_end == -1:
                                cur = cur + seg[1:]
                            else:
                                cur = seg[::-1][:-1] + cur
                            used[j] = True
                            grown = True
                            break
                    if grown:
                        break
                if grown:
                    break
        out.append(cur)
    return out


def marked_lines(page, per_ft, max_marker_pt=7.0):
    """Lines that carry small circles at intervals (silt fence)."""
    try:
        paths = page.get_drawings()
    except Exception:                                    # noqa: BLE001
        return []
    marks = []
    for p in paths:
        r = p.get("rect")
        if r is None:
            continue
        w, h = abs(r.x1 - r.x0), abs(r.y1 - r.y0)
        if not (1.0 <= w <= max_marker_pt and 1.0 <= h <= max_marker_pt and
                abs(w - h) <= 0.25 * max(w, h)):
            continue
        kinds = [it[0] for it in p.get("items", ())]
        # a small circle, square or diamond: a fence post / marker
        if not ("c" in kinds or "re" in kinds or "qu" in kinds or
                (kinds.count("l") >= 3 and p.get("closePath", False)) or
                kinds.count("l") == 4):
            continue
        marks.append(((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2, w,
                      tt._rgb(p.get("color") or p.get("fill"))))
    if len(marks) < 6:
        return []
    styles = tt.styled_segments(page)
    out = []
    for st, segs in styles.items():
        if st[1] > 1.0:
            continue
        rs = tt.runs(segs)
        keep, n_on = [], 0
        for r in rs:
            n = 0
            xs, ys = [q[0] for q in r], [q[1] for q in r]
            x0, x1, y0, y1 = min(xs) - 8, max(xs) + 8, min(ys) - 8, max(ys) + 8
            for mx, my, mw, _c in marks:
                if not (x0 <= mx <= x1 and y0 <= my <= y1):
                    continue
                if tt.dist_to_poly((mx, my), r) <= 0.75 * mw:
                    n += 1
            L = tt.poly_len(r)
            # at least two markers, and about one every 2-20 ft
            if n >= 2 and L / max(n, 1) <= 20 * per_ft:
                keep.append(r)
                n_on += n
        if keep:
            out.append({"style": tt.style_name(st), "markers": n_on,
                        "marker_in": round(sum(m[2] for m in marks) /
                                           len(marks) / per_ft * 12, 1),
                        "length_ft": round(sum(tt.poly_len(r) for r in keep)
                                           / per_ft, 1), "runs": keep})
    out.sort(key=lambda g: -g["markers"])
    return out


def marker_chains(page, per_ft, max_marker_pt=7.0, min_markers=5):
    """Lines drawn as a row of small circles (silt fence, the posts):
    the circles of one size and colour linked to their neighbours, each
    connected row measured along its links plus half a spacing at each
    end. [{"size_pt", "color", "markers", "spacing_ft", "length_ft",
    "chains": [[(x, y)]]}], longest first."""
    try:
        paths = page.get_drawings()
    except Exception:                                    # noqa: BLE001
        return []
    groups, drawn = {}, {}
    for p in paths:
        col = tt._rgb(p.get("color") or p.get("fill"))
        # the circles in a path: runs of joined bezier arcs that close on
        # themselves (a linetype's circles are many in one path)
        run = []

        def flush():
            if len(run) >= 2:
                xs = [q.x for it in run for q in it[1:] if hasattr(q, "x")]
                ys = [q.y for it in run for q in it[1:] if hasattr(q, "y")]
                w, h = max(xs) - min(xs), max(ys) - min(ys)
                a0, b1 = run[0][1], run[-1][-1]
                if 0.8 <= w <= max_marker_pt and \
                        abs(w - h) <= 0.25 * max(w, h) and \
                        math.hypot(a0.x - b1.x, a0.y - b1.y) <= 0.2 * w:
                    key = (round(w * 2) / 2, col)
                    groups.setdefault(key, []).append(
                        ((max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2))
            run.clear()
        # small closed boxes drawn inside a line's own path (a line with
        # squares at intervals): a run of 3-6 straight pieces that comes
        # back to where it started
        its = p.get("items", ())
        pts_ = [it[2] for it in its if it[0] == "l"]
        starts = [it[1] for it in its if it[0] == "l"]
        i = 0
        plain, pkeys = 0.0, []
        while i < len(pts_):
            hit = False
            for k in range(3, 7):
                if i + k > len(pts_):
                    break
                a0 = starts[i]
                e = pts_[i + k - 1]
                if math.hypot(a0.x - e.x, a0.y - e.y) > 0.1:
                    continue
                loop = [starts[i]] + pts_[i:i + k]
                xs = [q.x for q in loop]
                ys = [q.y for q in loop]
                w, h = max(xs) - min(xs), max(ys) - min(ys)
                # its side from the perimeter: a square turned along a
                # sloping line has a bigger box than side
                side = sum(math.hypot(q1.x - q0.x, q1.y - q0.y)
                           for q0, q1 in zip(loop, loop[1:])) / 4.0
                if 0.8 <= side <= max_marker_pt and \
                        abs(w - h) <= 0.45 * max(w, h):
                    key = (round(side * 2) / 2, col)
                    groups.setdefault(key, []).append(
                        ((max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2))
                    pkeys.append(key)
                    i += k
                    hit = True
                    break
            if not hit:
                plain += math.hypot(pts_[i].x - starts[i].x,
                                    pts_[i].y - starts[i].y)
                i += 1
        if pkeys:
            # the line itself, drawn in the same path as its squares
            k0 = max(set(pkeys), key=pkeys.count)
            drawn[k0] = drawn.get(k0, 0.0) + plain
        for it in its:
            if it[0] != "c":
                flush()
                continue
            if run:
                e = run[-1][-1]
                if math.hypot(e.x - it[1].x, e.y - it[1].y) > 0.05:
                    flush()
            run.append(it)
            a0, e = run[0][1], run[-1][-1]
            if len(run) >= 2 and math.hypot(a0.x - e.x, a0.y - e.y) <= 0.05:
                flush()
        flush()
    out = []
    for (size, col), pts in groups.items():
        # one circle drawn twice (fill and stroke) is one marker
        uniq = []
        for q in pts:
            if all(math.hypot(q[0] - u[0], q[1] - u[1]) > 0.5 * size
                   for u in uniq[-50:]):
                uniq.append(q)
        pts = uniq
        if len(pts) < min_markers or len(pts) > 1500:
            continue                  # too few; or a stipple / hatch
        nn = []
        for i, a in enumerate(pts):
            d = min((math.hypot(a[0] - b[0], a[1] - b[1])
                     for j, b in enumerate(pts) if j != i), default=0)
            nn.append(d)
        sp = sorted(nn)[len(nn) // 2]
        if sp <= 0 or sp > 40 * per_ft:
            continue
        link = 2.2 * sp
        # minimum spanning forest with edges up to `link` (Prim per part)
        n = len(pts)
        seen = [False] * n
        chains = []
        total = 0.0
        for s0 in range(n):
            if seen[s0]:
                continue
            seen[s0] = True
            comp, L = [pts[s0]], 0.0
            dist = {}

            def relax(i):
                for j in range(n):
                    if not seen[j]:
                        d = math.hypot(pts[i][0] - pts[j][0],
                                       pts[i][1] - pts[j][1])
                        if d <= link and d < dist.get(j, 1e18):
                            dist[j] = d
            relax(s0)
            while dist:
                j = min(dist, key=dist.get)
                L += dist.pop(j)
                seen[j] = True
                comp.append(pts[j])
                relax(j)
            if len(comp) >= min_markers:
                chains.append(comp)
                total += L + sp                  # half a spacing each end
        if not chains:
            continue
        out.append({"size_pt": size, "color": col,
                    "markers": sum(len(c) for c in chains),
                    "spacing_ft": round(sp / per_ft, 2),
                    "length_ft": round(total / per_ft, 1),
                    "drawn_ft": round(drawn.get((size, col), 0.0) / per_ft,
                                      1),
                    "chains": chains})
    out.sort(key=lambda g: -g["length_ft"])
    return out
