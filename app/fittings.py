"""Pipe fittings counted from the drawn pipe layout (accuracy round 6): an
estimator counts the elbows and tees on each system, size by size, as
well as the pipe. Quantities only - no prices.

    count(groups, per_ft) -> {(system, size_in, kind, branch_in): n}
    names(counts) -> [(name, n)]

`groups` are Trade Takeoff pipe systems ({name: '2" V', runs: [{pts}]}).
Within one system (waste, vent, water), every drawn run is put on one
network: run ends and corners closer than a few inches are one point,
and a run that ends on the side of another makes a tee there. Then:

- a corner turning 20-67 degrees is a 45 elbow, 67-120 degrees a 90
  elbow (a curved elbow drawn as short pieces is simplified first, so it
  is one corner); a straight joint is no fitting;
- three pipes meeting are a tee - a wye on waste / sanitary when the
  branch comes in at an angle - named main x branch when the branch is
  smaller;
- a pipe end is a fixture, a riser or a cap: not a fitting.

What it can't see - drops and risers drawn as circles, fittings hidden
under text - isn't counted, so the lines are offered for a person to
check."""
import math
import re

_SYS = {"V": "vent", "VTR": "vent", "W": "waste", "S": "waste",
        "SAN": "waste", "SS": "waste", "CW": "water", "DCW": "water",
        "HW": "water", "DHW": "water", "HWR": "water", "HWC": "water",
        "TW": "water"}


def _size(name):
    m = re.match(r"^\s*(\d+)-(\d+)/(\d+)\"|^\s*(\d+)/(\d+)\"|"
                 r"^\s*(\d+(?:\.\d+)?)\"", name or "")
    if not m:
        return None
    if m.group(1):
        return int(m.group(1)) + int(m.group(2)) / int(m.group(3))
    if m.group(4):
        return int(m.group(4)) / int(m.group(5))
    return float(m.group(6))


def system_of(name):
    """'2" V' -> 'vent', '1/2" CW' -> 'water', '3" W' -> 'waste'."""
    m = re.search(r"\"\s*([A-Z]+)\b", name or "")
    return _SYS.get(m.group(1)) if m else None


def _simplify(pts, eps):
    """Douglas-Peucker: a curve drawn as short pieces becomes its corner."""
    if len(pts) < 3:
        return list(pts)
    a, b = pts[0], pts[-1]
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(dx, dy)
    best, k = -1.0, 0
    for i in range(1, len(pts) - 1):
        p = pts[i]
        if L == 0:
            d = math.hypot(p[0] - a[0], p[1] - a[1])
        else:
            d = abs(dy * p[0] - dx * p[1] + b[0] * a[1] - b[1] * a[0]) / L
        if d > best:
            best, k = d, i
    if best <= eps:
        return [a, b]
    left = _simplify(pts[:k + 1], eps)
    return left[:-1] + _simplify(pts[k:], eps)


def _turn(a, b, c):
    """Signed turn at b in degrees (left positive)."""
    a1 = math.atan2(b[1] - a[1], b[0] - a[0])
    a2 = math.atan2(c[1] - b[1], c[0] - b[0])
    d = math.degrees(a2 - a1)
    while d > 180:
        d -= 360
    while d < -180:
        d += 360
    return d


def _join_bends(pts, short):
    """A bend drawn as two or three short turns the same way (a long
    radius elbow) is one corner: consecutive same-way turns closer than
    `short` are merged into one vertex at their middle."""
    pts = list(pts)
    changed = True
    while changed and len(pts) >= 4:
        changed = False
        for i in range(1, len(pts) - 2):
            t1 = _turn(pts[i - 1], pts[i], pts[i + 1])
            t2 = _turn(pts[i], pts[i + 1], pts[i + 2])
            seg = math.hypot(pts[i + 1][0] - pts[i][0],
                             pts[i + 1][1] - pts[i][1])
            if seg < short and abs(t1) > 5 and abs(t2) > 5 and \
                    (t1 > 0) == (t2 > 0) and abs(t1 + t2) <= 135:
                mid = ((pts[i][0] + pts[i + 1][0]) / 2,
                       (pts[i][1] + pts[i + 1][1]) / 2)
                pts[i:i + 2] = [mid]
                changed = True
                break
    return pts


def _on_seg(p, a, b, tol):
    """Distance along a-b of p's foot when p lies on the segment's
    interior within tol, else None."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return None
    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L2
    L = math.sqrt(L2)
    if t * L <= tol or (1 - t) * L <= tol:
        return None                                    # at an end
    fx, fy = a[0] + t * dx, a[1] + t * dy
    if math.hypot(p[0] - fx, p[1] - fy) > tol:
        return None
    return t


def count(groups, per_ft, join_ft=0.5, simplify_ft=0.12, min_ft=0.25):
    """{(system, size_in, kind, branch_in or None): n} over `groups`."""
    out = {}
    if per_ft <= 0:
        return out
    tol = join_ft * per_ft
    eps = simplify_ft * per_ft
    by_sys = {}
    for g in groups or ():
        sys_ = system_of(g.get("name"))
        size = _size(g.get("name"))
        if not sys_ or not size:
            continue
        for r in g.get("runs") or ():
            pts = [tuple(p[:2]) for p in (r.get("pts") or ())]
            pts = _join_bends(_simplify(pts, eps), 1.5 * per_ft)
            for a, b in zip(pts, pts[1:]):
                if math.hypot(b[0] - a[0], b[1] - a[1]) >= min_ft * per_ft:
                    by_sys.setdefault(sys_, []).append([a, b, size])
    for sys_, segs in by_sys.items():
        # a run ending on the side of another splits it there (a tee)
        ends = [s[0] for s in segs] + [s[1] for s in segs]
        changed = True
        guard = 0
        while changed and guard < 4:
            changed, guard = False, guard + 1
            new = []
            for a, b, sz in segs:
                cuts = sorted({t for p in ends
                               for t in [_on_seg(p, a, b, tol)] if t})
                if not cuts:
                    new.append([a, b, sz])
                    continue
                changed = True
                prev = a
                for t in cuts:
                    q = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
                    new.append([prev, q, sz])
                    prev = q
                new.append([prev, b, sz])
            segs = new
        # cluster ends into nodes
        nodes = []                       # [x, y, [(dir, size)]]
        for a, b, sz in segs:
            for p, q in ((a, b), (b, a)):
                for nd in nodes:
                    if math.hypot(nd[0] - p[0], nd[1] - p[1]) <= tol:
                        break
                else:
                    nd = [p[0], p[1], []]
                    nodes.append(nd)
                L = math.hypot(q[0] - p[0], q[1] - p[1]) or 1.0
                nd[2].append(((q[0] - p[0]) / L, (q[1] - p[1]) / L, sz))
        for _x, _y, inc in nodes:
            # the same pipe drawn twice into a node is one leg
            legs = []
            for ux, uy, sz in inc:
                for lg in legs:
                    if ux * lg[0] + uy * lg[1] > math.cos(math.radians(8)):
                        lg[2] = max(lg[2], sz)
                        break
                else:
                    legs.append([ux, uy, sz])
            if len(legs) == 2:
                cos = legs[0][0] * legs[1][0] + legs[0][1] * legs[1][1]
                dev = 180.0 - math.degrees(math.acos(max(-1.0, min(1.0,
                                                                  cos))))
                size = max(legs[0][2], legs[1][2])
                if 20 <= dev < 67:
                    k = (sys_, size, "45 elbow", None)
                elif 67 <= dev <= 120:
                    k = (sys_, size, "90 elbow", None)
                else:
                    continue
                out[k] = out.get(k, 0) + 1
            elif len(legs) == 3:
                # the run: the two legs closest to straight through
                best = None
                for i in range(3):
                    for j in range(i + 1, 3):
                        c = legs[i][0] * legs[j][0] + legs[i][1] * legs[j][1]
                        if best is None or c < best[0]:
                            best = (c, i, j)
                _c, i, j = best
                br = legs[3 - i - j]
                main = max(legs[i][2], legs[j][2])
                # the branch's angle to the run
                c = abs(br[0] * legs[i][0] + br[1] * legs[i][1])
                ang = math.degrees(math.acos(max(-1.0, min(1.0, c))))
                wye = sys_ == "waste" and ang < 67
                kind = "Y-tee" if wye else "tee"
                b = br[2] if br[2] < main else None
                k = (sys_, main, kind, b)
                out[k] = out.get(k, 0) + 1
            elif len(legs) == 4:
                k = (sys_, max(lg[2] for lg in legs), "cross", None)
                out[k] = out.get(k, 0) + 1
    return out


def size_text(x):
    whole = int(x)
    rem = round((x - whole) * 8) / 8
    if rem == 0:
        return f"{whole}\""
    num, den = int(round(rem * 8)), 8
    while num % 2 == 0:
        num //= 2
        den //= 2
    return f"{whole}-{num}/{den}\"" if whole else f"{num}/{den}\""


def names(counts):
    """[(line name, n)] - '2" 90 elbow - vent', '3/4" x 1/2" tee - water'."""
    out = []
    for (sys_, size, kind, br), n in sorted(
            counts.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2],
                                            kv[0][3] or 0)):
        s = size_text(size) + (f" x {size_text(br)}" if br else "")
        out.append((f"{s} {kind} - {sys_}", n))
    return out


# ------------------------------------------------------------- ducts
def _duct_size(name):
    """'10" round' -> (10.0, None); '20x22' -> (20.0, 22.0); else None."""
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\"\s*round\b", name or "", re.I)
    if m:
        return (float(m.group(1)), None)
    m = re.match(r"^\s*(\d+)\s*[xX]\s*(\d+)\b", name or "")
    if m:
        return (float(m.group(1)), float(m.group(2)))
    return None


def duct_text(sz):
    w, h = sz
    return f'{w:g}" round' if h is None else f'{w:g}x{h:g}'


def count_ducts(groups, per_ft, flex=()):
    """{(kind, size, other): n} for duct groups (aitakeoff.duct_groups
    kept: {name, pieces: [{p0, p1, fitting}]}):

    - an elbow where a run turns 20-67 (45) or 67-120 degrees (90);
    - a transition where two sizes meet straight on;
    - a take-off where a run ends on the side of another (a branch);
    - a flex connection per flex run-out (flex = flex_runs output).

    Run ends are joined over 1.5 ft (an elbow drawn as its own arc) -
    the pieces are the duct's centre line."""
    out = {}
    if per_ft <= 0:
        return out
    segs = []
    for g in groups or ():
        sz = _duct_size(g.get("name"))
        if not sz:
            continue
        for pc in g.get("pieces") or ():
            if pc.get("fitting"):
                continue
            a, b = tuple(pc["p0"][:2]), tuple(pc["p1"][:2])
            if math.hypot(b[0] - a[0], b[1] - a[1]) >= 0.25 * per_ft:
                segs.append([a, b, sz])
    tol = 1.5 * per_ft
    # a run ending on the side of another: split there (a take-off)
    ends = [s[0] for s in segs] + [s[1] for s in segs]
    new = []
    for a, b, sz in segs:
        cuts = sorted({t for p in ends for t in [_on_seg(p, a, b, tol)] if t})
        prev = a
        for t in cuts:
            q = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
            new.append([prev, q, sz])
            prev = q
        new.append([prev, b, sz])
    segs = new
    nodes = []
    for a, b, sz in segs:
        for p, q in ((a, b), (b, a)):
            for nd in nodes:
                if math.hypot(nd[0] - p[0], nd[1] - p[1]) <= tol:
                    break
            else:
                nd = [p[0], p[1], []]
                nodes.append(nd)
            L = math.hypot(q[0] - p[0], q[1] - p[1]) or 1.0
            nd[2].append(((q[0] - p[0]) / L, (q[1] - p[1]) / L, sz))

    def bigger(x, y):
        return x if (x[0] * (x[1] or x[0])) >= (y[0] * (y[1] or y[0])) else y
    for _x, _y, inc in nodes:
        legs = []
        for ux, uy, sz in inc:
            for lg in legs:
                if ux * lg[0] + uy * lg[1] > math.cos(math.radians(8)):
                    if lg[2] != sz:
                        lg[3].add(sz)
                    break
            else:
                legs.append([ux, uy, sz, set()])
        if len(legs) == 2:
            cos = legs[0][0] * legs[1][0] + legs[0][1] * legs[1][1]
            dev = 180.0 - math.degrees(math.acos(max(-1.0, min(1.0, cos))))
            a, b = legs[0][2], legs[1][2]
            if dev < 20:
                if a != b:
                    lo, hi = sorted((a, b), key=lambda s: s[0] * (s[1] or s[0]))
                    k = ("transition", lo, hi)
                else:
                    continue
            elif dev < 67:
                k = ("45 elbow", bigger(a, b), None)
            elif dev <= 120:
                k = ("90 elbow", bigger(a, b), None)
            else:
                continue
            out[k] = out.get(k, 0) + 1
        elif len(legs) == 3:
            best = None
            for i in range(3):
                for j in range(i + 1, 3):
                    c = legs[i][0] * legs[j][0] + legs[i][1] * legs[j][1]
                    if best is None or c < best[0]:
                        best = (c, i, j)
            _c, i, j = best
            br = legs[3 - i - j][2]
            main = bigger(legs[i][2], legs[j][2])
            k = ("take-off", br, main)
            out[k] = out.get(k, 0) + 1
    for f in flex or ():
        d = f.get("size_in")
        if d:
            k = ("flex connection", (float(d), None), None)
            out[k] = out.get(k, 0) + 1
    return out


def duct_names(counts):
    """[(name, n)]: '8" round 90 elbow - duct', '6" round take-off from
    10" round - duct', '10" round to 12" round transition - duct',
    '8" round to flex connection - duct'."""
    out = []
    for (kind, a, b), n in sorted(counts.items(), key=lambda kv: (
            kv[0][0], kv[0][1], kv[0][2] or (0, 0))):
        if kind == "transition":
            nm = f"{duct_text(a)} to {duct_text(b)} transition"
        elif kind == "take-off":
            nm = f"{duct_text(a)} take-off from {duct_text(b)}"
        elif kind == "flex connection":
            nm = f"{duct_text(a)} to flex connection"
        else:
            nm = f"{duct_text(a)} {kind}"
        out.append((nm + " - duct", n))
    return out
