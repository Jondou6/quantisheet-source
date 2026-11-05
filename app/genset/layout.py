"""Footprint, rooms, walls, doors and windows - the geometry of the plan,
by rule, with no randomness (the same brief gives the same plan)."""
import copy
import math
import re
from collections import deque

from . import DISCLAIMER, model, program as prog

EXT_T = 0.5           # exterior wall thickness, ft
INT_T = 0.375         # interior partitions (4 1/2")
MIN_SF, MAX_SF = 400, 8000
MAX_W, MAX_D = 120.0, 80.0
DOOR = {"A": (3.0, 6.667), "B": (2.667, 6.667)}
WINDOW = {"A": (3.0, 4.0, 3.0), "B": (2.0, 3.0, 4.0)}      # w, h, sill
WINDOW_EVERY = 12.0   # one per 12 ft of exterior wall in a habitable room
# rooms a door may lead into but never through (no walking through a
# bedroom to reach the kitchen)
PRIVATE = {"bed", "bath", "restroom", "mech", "storage", "office"}


def _r2(x):
    return 2 * round(x / 2)


def footprint(gross_sf, building_type, ratio=None, min_ratio=1.0):
    """(width, depth) from the gross area and an aspect ratio (1.6 for a
    house, 2.0 for commercial; a sketch's own ratio when there is one),
    rounded to 2 ft. The limits are the building type's (types/*.py:
    400 - 8,000 SF and 120 x 80 ft for houses and small commercial)."""
    from . import types
    lim = types.limits(building_type)
    lo, hi = lim["sf"]
    max_w, max_d = lim["max_w"], lim["max_d"]
    if not gross_sf:
        raise model.PlanError("Enter the gross SF (a sketch gives the "
                              "shape only).")
    if gross_sf < lo:
        raise model.PlanError(f"v1 starts at {lo:,.0f} SF.")
    if gross_sf > hi:
        raise model.PlanError("v1 covers one-story buildings up to "
                              f"{hi:,.0f} SF.")
    ratio = ratio or (1.6 if building_type == "single_family" else 2.0)
    ratio = max(min_ratio, min(3.0, ratio))
    w = _r2(math.sqrt(gross_sf * ratio))
    # keep inside 120 x 80 ft by changing the proportions, not refusing
    # (Venice M-3: 8,000 SF commercial at 2:1 needs 126 ft)
    if w > max_w:
        w = max_w
    d = _r2(gross_sf / w)
    if d > max_d:
        d = max_d
        w = min(max_w, _r2(gross_sf / d))
    if w > max_w or d > max_d:
        raise model.PlanError("v1 covers one-story buildings up to "
                              f"{max_w:g} x {max_d:g} ft.")
    return float(w), float(d)


# ---- squarified treemap ---------------------------------------------------------
def _worst(row, side):
    s = sum(row)
    return max(max(side * side * r / (s * s), s * s / (side * side * r))
               for r in row)


def squarify(values, rect):
    """Rectangles (x0, y0, x1, y1) for `values` (areas, adding up to the
    rect's area) in order. The first row always runs along the south edge,
    so the first room (the hub) faces the street."""
    x0, y0, x1, y1 = rect
    out, vals, first = [], list(values), True
    while vals:
        w, h = x1 - x0, y1 - y0
        along_bottom = first or w < h
        side = w if along_bottom else h
        row, i = [vals[0]], 1
        while i < len(vals) and _worst(row + [vals[i]], side) <= \
                _worst(row, side):
            row.append(vals[i])
            i += 1
        if i == len(vals) - 0 and len(vals) == len(row):
            pass
        s = sum(row)
        if along_bottom:
            rh = s / w if w else 0
            xx = x0
            for k, v in enumerate(row):
                cw = v / rh if rh else 0
                x_end = x1 if k == len(row) - 1 else xx + cw
                out.append((xx, y0, x_end, y0 + rh if vals[i:] else y1))
                xx = x_end
            y0 = y0 + rh
        else:
            cw = s / h if h else 0
            yy = y0
            for k, v in enumerate(row):
                rh = v / cw if cw else 0
                y_end = y1 if k == len(row) - 1 else yy + rh
                out.append((x0, yy, x0 + cw if vals[i:] else x1, y_end))
                yy = y_end
            x0 = x0 + cw
        vals = vals[i:]
        first = False
    return out


# ---- zoned plan (Grok review M1/M2) -------------------------------------
# The main room and the other shared rooms fill one end; the private rooms
# sit in rows along a hall in the other end, so every bedroom has an
# outside wall (a window) and every private room opens onto the hall -
# nobody walks through a bedroom, bath, laundry or mech room.
PUBLIC = {"living", "kitchen", "dining", "open_office", "conference",
          "break", "sales"}
MIN_W = {"bed": 8.0, "office": 8.0, "bath": 5.0,
         "restroom": 5.75,              # 60 in. turning circle clear
         "laundry": 5.0, "mech": 4.0, "storage": 5.0}
HALL_W = 4.0
HALL_W_COMMERCIAL = 5.0
COMMERCIAL = {"open_office", "conference", "break", "sales", "restroom"}
MIN_PUBLIC_W = 12.0


def _zoned_any(order, W, D, t):
    """_zoned, or for a deep, narrow building (0.12.21) the same zoning
    turned a quarter: the shared rooms across the front, the hall running
    back from them with the private rooms on its sides. Laid out with
    width and depth swapped, then mirrored about the diagonal - the front
    (south) stays the front."""
    if D <= W * 1.1:
        return _zoned(order, W, D, t)
    placed = _zoned(order, D, W, t)
    if placed is None:
        return None
    return [(r, (y0, x0, y1, x1)) for r, (x0, y0, x1, y1) in placed]


def _zoned(order, W, D, t):
    """[(room dict, (x0, y0, x1, y1))] with a HALL entry added, or None
    when the private rooms can't fit along the hall at their smallest."""
    sn = lambda v, lo, hi: _snap(v, lo, hi)                # noqa: E731
    x0i, y0i, x1i, y1i = t, t, W - t, D - t
    Wi, Di = x1i - x0i, y1i - y0i
    hub = order[0]
    # office / retail: a 5 ft hall, so a door off it has the 48 in. push
    # side clearance (ADA 404.2.4.1) - a house keeps 4 ft
    hall_w = HALL_W_COMMERCIAL if any(r["type"] in COMMERCIAL
                                      for r in order) else HALL_W
    pub = [r for r in order[1:] if r["type"] in PUBLIC]
    priv = [r for r in order[1:] if r["type"] not in PUBLIC]
    out = []
    if not priv:
        xp = x1i
    else:
        # the first arrangement that fits: rooms on one side of the hall
        # (shallow buildings) or both sides (deep ones), then the same with
        # a narrower shared end - before anything is left out (Venice M1).
        # Two rows only when both get rooms (Venice M3: no empty row).
        tries = []
        for pub_w in (MIN_PUBLIC_W, 10.0):
            for single in ((True, False) if Di < 24.0 else (False, True)):
                if not single and (len(priv) < 2 or (Di - hall_w) / 2 < 6):
                    continue
                tries.append((single, pub_w))
        for single, pub_w in tries:
            depth = (Di - hall_w) if single else (Di - hall_w) / 2
            rows = 1 if single else 2
            widths = {id(r): max(MIN_W.get(r["type"], 4.0),
                                 r["target_sf"] / depth) for r in priv}
            # balance the rows by length, biggest rooms first
            lanes = [[] for _ in range(rows)]
            for r in sorted(priv, key=lambda r: (-widths[id(r)], r["name"])):
                min(lanes, key=lambda ln: sum(widths[id(x)] for x in ln)
                    ).append(r)
            if any(not ln for ln in lanes):
                continue
            need = max(sum(widths[id(r)] for r in ln) for ln in lanes)
            mins = max(sum(MIN_W.get(r["type"], 4.0) for r in ln)
                       for ln in lanes)
            if mins <= Wi - pub_w:
                break
        else:
            return None
        wing = min(need, Wi - pub_w)
        xp = sn(x1i - wing, x0i, x1i)
        wing = x1i - xp
        if single:
            hy0, hy1 = y0i, sn(y0i + hall_w, y0i, y1i)
            bands = [(hy1, y1i)]
        else:
            mid = (y0i + y1i) / 2
            hy0 = sn(mid - hall_w / 2, y0i, y1i)
            hy1 = sn(mid + hall_w / 2, y0i, y1i)
            bands = [(y0i, hy0), (hy1, y1i)]
        if hall_w > HALL_W and hy1 - hy0 < hall_w - 1e-6 and hy1 + 1 < y1i:
            hy1 += 1.0                  # the 1 ft grid rounded it down
            bands[-1] = (hy1, y1i)
        out.append(({"name": "HALL", "type": "hall", "share": 0,
                     "target_sf": round(wing * (hy1 - hy0), 1)},
                    (xp, hy0, x1i, hy1)))
        for lane, (by0, by1) in zip(lanes, bands):
            # the smaller rooms nearest the main room, the biggest (the
            # primary bedroom) at the far end with two outside walls
            lane.sort(key=lambda r: (widths[id(r)], r["name"]))
            tot = sum(widths[id(r)] for r in lane) or 1
            x = xp
            for i, r in enumerate(lane):
                x2 = x1i if i == len(lane) - 1 else \
                    sn(x + wing * widths[id(r)] / tot, x0i, x1i)
                out.append((r, (x, by0, x2, by1)))
                x = x2
        hall_top = hy1
    # the shared end: the main room along the front (south), the other
    # shared rooms in a row behind it
    if pub:
        pa = sum(r["target_sf"] for r in pub)
        ha = hub["target_sf"]
        yh = sn(y0i + Di * ha / (ha + pa), y0i, y1i)
        if priv:
            yh = max(yh, sn(hall_top + 2, y0i, y1i))
        yh = min(yh, sn(y1i - 7, y0i, y1i))
        out.insert(0, (hub, (x0i, y0i, xp, yh)))
        tot = pa or 1
        x = x0i
        for i, r in enumerate(pub):
            x2 = xp if i == len(pub) - 1 else \
                sn(x + (xp - x0i) * r["target_sf"] / tot, x0i, x1i)
            out.insert(1 + i, (r, (x, yh, x2, y1i)))
            x = x2
    else:
        out.insert(0, (hub, (x0i, y0i, xp, y1i)))
    return out


def _snap(v, lo, hi):
    """To the 1 ft grid, except the outside faces of the rooms."""
    if abs(v - lo) < 1e-6 or abs(v - hi) < 1e-6:
        return v
    return float(round(v))


# ---- walls and openings ----------------------------------------------------------
def _exterior_walls(W, D):
    return [
        {"id": "W1", "a": [0.0, 0.0], "b": [W, 0.0], "thickness": EXT_T,
         "kind": "exterior", "face": "S"},
        {"id": "W2", "a": [W, 0.0], "b": [W, D], "thickness": EXT_T,
         "kind": "exterior", "face": "E"},
        {"id": "W3", "a": [W, D], "b": [0.0, D], "thickness": EXT_T,
         "kind": "exterior", "face": "N"},
        {"id": "W4", "a": [0.0, D], "b": [0.0, 0.0], "thickness": EXT_T,
         "kind": "exterior", "face": "W"},
    ]


def _shared(a, b, tol=1e-6):
    """The edge rooms a and b share: (orientation, fixed, lo, hi) or None."""
    ax0, ay0, ax1, ay1 = a["rect"]
    bx0, by0, bx1, by1 = b["rect"]
    for x in ((ax1, bx0), (bx1, ax0)):
        if abs(x[0] - x[1]) < tol:
            lo, hi = max(ay0, by0), min(ay1, by1)
            if hi - lo > tol:
                return ("v", x[0], lo, hi)
    for y in ((ay1, by0), (by1, ay0)):
        if abs(y[0] - y[1]) < tol:
            lo, hi = max(ax0, bx0), min(ax1, bx1)
            if hi - lo > tol:
                return ("h", y[0], lo, hi)
    return None


def _ext_frontage(r, W, D):
    """[(wall id, along_lo, along_hi, length)] of a room on the outside."""
    x0, y0, x1, y1 = r["rect"]
    t = EXT_T / 2
    out = []
    if abs(y0 - t) < 1e-6:
        out.append(("W1", x0, x1))
    if abs(x1 - (W - t)) < 1e-6:
        out.append(("W2", y0, y1))
    if abs(y1 - (D - t)) < 1e-6:
        out.append(("W3", W - x1, W - x0))
    if abs(x0 - t) < 1e-6:
        out.append(("W4", D - y1, D - y0))
    return [(w, lo, hi, hi - lo) for w, lo, hi in out]


def _fits(occupied, wall, lo, hi, margin=0.5):
    for w, a, b in occupied:
        if w == wall and lo < b + margin and hi > a - margin:
            return False
    return True


_KINDS = [("sales", "sales"), ("conference", "conference"),
          ("suite", "bed"), ("bed", "bed"), ("bath", "bath"), ("restroom", "restroom"),
          ("toilet", "restroom"), ("kitchen", "kitchen"),
          ("living", "living"), ("family", "living"), ("great", "living"),
          ("dining", "dining"), ("laundry", "laundry"), ("mech", "mech"),
          ("conference", "conference"), ("break", "break"),
          ("open office", "open_office"), ("office", "office"),
          ("storage", "storage"), ("stock", "storage"), ("sales", "sales")]


def _kind_of(name):
    low = name.lower()
    return next((k for word, k in _KINDS if word in low), None)


MIN_DOOR = 2.0            # ft: the narrowest door v1 will draw


def _door_spot(occupied, wall, L, width, latch=0.75):
    """(along, width) for a door on a wall L long: toward one end when
    there is room, both ends clear by 0.5 ft (Venice S-1), never on top of
    another opening. None when it can't fit. `latch`: the wall wanted
    beside the door at the near end (office / retail: 18 in. past the
    latch plus the partition, ADA 404.2.4.1)."""
    width = min(width, L - 1.0)
    if width < MIN_DOOR:
        return None
    lo_c, hi_c = 0.5 + width / 2, L - 0.5 - width / 2
    roomy = L >= width + latch + 1.25
    pref = latch + width / 2 if roomy else L / 2
    for along in (pref, L - pref if roomy else hi_c - 0.25, L / 2, lo_c,
                  hi_c):
        along = max(lo_c, min(hi_c, along))
        if _fits(occupied, wall, along - width / 2, along + width / 2,
                 margin=0.25):
            return along, width
    return None


def build_level(placed, W, D, bt, warnings, level_no=1, entry=True,
                all_to_hub=False, blocked=None):
    """Rooms, walls, doors and windows for one floor from the placed room
    rectangles [(room, rect)] - the first room is the hub. Level 2 rooms
    are numbered 201..., its doors 201...; `entry` adds the front (and a
    house's rear) door; `all_to_hub` opens every room onto the hub (the
    stair hall of a two-story house); `blocked` [(x0, y0, x1, y1)] are
    stair runs no door may open into."""
    t = EXT_T / 2
    base = 100 * level_no
    order = [r for r, _rc in placed]
    rects = [rc for _r, rc in placed]
    rooms = []
    for i, (r, rc) in enumerate(zip(order, rects)):
        x0, y0, x1, y1 = (_snap(rc[0], t, W - t), _snap(rc[1], t, D - t),
                          _snap(rc[2], t, W - t), _snap(rc[3], t, D - t))
        if x1 - x0 < 3 or y1 - y0 < 3:
            warnings.append(f"{r['name']} came out under 3 ft wide; "
                            "check the program")
        if x1 <= x0 or y1 <= y0:
            raise model.PlanError(f"{r['name']} came out with no area")
        area = round((x1 - x0) * (y1 - y0), 2)
        fin = prog.FINISHES.get(r["type"], ("TBD",) * 4)
        rooms.append({
            "id": f"R{base + 1 + i}", "number": str(base + 1 + i), "name": r["name"],
            "type": r["type"], "rect": [x0, y0, x1, y1], "area": area,
            "target_sf": r["target_sf"],
            "finishes": {"floor": fin[0], "base": fin[1], "walls": fin[2],
                         "ceiling": fin[3]},
            "ceiling_ht": 9.0 if bt == "single_family" else 10.0,
            **({"door_from": r["door_from"]} if r.get("door_from")
               else {})})
    walls = _exterior_walls(W, D)
    pair_wall = {}
    for i, a in enumerate(rooms):
        for b in rooms[i + 1:]:
            sh = _shared(a, b)
            if sh is None or sh[3] - sh[2] < 1.0:
                continue
            o, f, lo, hi = sh
            wid = f"W{len(walls) + 1}"
            pa, pb = ([f, lo], [f, hi]) if o == "v" else ([lo, f], [hi, f])
            walls.append({"id": wid, "a": pa, "b": pb, "thickness": INT_T,
                          "kind": "interior", "face": None})
            pair_wall[(a["id"], b["id"])] = pair_wall[(b["id"], a["id"])] = \
                (wid, hi - lo)
    openings, occupied = [], []
    hub_room = rooms[0]
    # a stair run: no door opens into its side (on either floor)
    for bx0, by0, bx1, by1 in blocked or ():
        for w in walls:
            if w["kind"] != "interior":
                continue
            (ax, ay), (cx, cy) = w["a"], w["b"]
            if abs(ax - cx) < 1e-6 and bx0 - 1e-6 <= ax <= bx1 + 1e-6:
                lo, hi = max(ay, by0), min(cy, by1)
                if hi > lo:
                    occupied.append((w["id"], lo - ay, hi - ay))
            elif abs(ay - cy) < 1e-6 and by0 - 1e-6 <= ay <= by1 + 1e-6:
                lo, hi = max(ax, bx0), min(cx, bx1)
                if hi > lo:
                    occupied.append((w["id"], lo - ax, hi - ax))

    def add(o):
        openings.append(o)
        occupied.append((o["wall"], o["along"] - o["width"] / 2,
                         o["along"] + o["width"] / 2))

    # front door: centred on the hub's south wall
    dw, dh = DOOR["A"]
    front = [f for f in _ext_frontage(hub_room, W, D) if f[0] == "W1"] \
        if entry else []
    if not entry:
        pass
    elif front:
        _, lo, hi, L = front[0]
        add({"id": "D1", "kind": "door", "mark": str(base + 1), "type": "A",
             "wall": "W1", "along": round((lo + hi) / 2, 3), "width": dw,
             "height": dh, "swing": "in-left", "from_room": "EXT",
             "to_room": hub_room["id"]})
    else:
        warnings.append("The main room doesn't reach the south wall; "
                        "front door left out")
    # rear door (house): the kitchen, dining or living room on the north
    if bt == "single_family" and entry:
        # north wall first, then the side walls
        # (a deep house's hall reaches the back wall: a back door there
        # before a side door near the front - it's what a deck needs)
        cand = [(r, f) for wall, kinds in (
                    ("W3", ("kitchen", "dining", "laundry", "living",
                            "hall")),
                    ("W2", ("kitchen", "dining", "laundry", "living")),
                    ("W4", ("kitchen", "dining", "laundry", "living")))
                for kind in kinds
                for r in rooms if r["type"] == kind
                for f in _ext_frontage(r, W, D) if f[0] == wall
                and f[3] >= dw + (0.4 if kind == "hall" else 1.5)]
        for _once in (1,):
            if cand:
                r, (rear_wall, lo, hi, L) = cand[0]
                # toward one end, leaving the rest of the wall for a window
                along = lo + 0.75 + dw / 2 if L >= dw + 6 else (lo + hi) / 2
                add({"id": f"D{len(openings) + 1}", "kind": "door",
                     "mark": str(base + len(openings) + 1), "type": "A",
                     "wall": rear_wall, "along": round(along, 3),
                     "width": dw, "height": dh, "swing": "in-right",
                     "from_room": "EXT", "to_room": r["id"]})
            else:
                warnings.append("No room on an outside wall for a rear "
                                "door")
    # interior doors: a tree from the hub (no corridors in v1)
    # office and retail: 3'-0" doors everywhere - a 2'-8" leaf is under
    # the 32 in. clear the ADA Standards need (404.2.3)
    bw, bh = DOOR["B"] if bt == "single_family" else DOOR["A"]
    adj = {r["id"]: [] for r in rooms}
    for (a, b), (wid, L) in pair_wall.items():
        if L >= bw + 1.0:
            adj[a].append(b)
    for k_ in adj:
        adj[k_].sort()
    by_id = {r["id"]: r for r in rooms}
    private = {r["id"] for r in rooms if r["type"] in PRIVATE}
    parent, seen = {}, {hub_room["id"]}
    # the zoned plan's own doors first: shared rooms open to the main
    # room, the hall opens to it, private rooms open onto the hall
    hall_id = next((r["id"] for r in rooms if r["type"] == "hall"), None)

    def touches(a, b, need=MIN_DOOR + 1.0):
        return (a, b) in pair_wall and pair_wall[(a, b)][1] >= need
    if hall_id and touches(hall_id, hub_room["id"]):
        parent[hall_id] = hub_room["id"]
    if all_to_hub:                  # a center hall: every room opens on it
        for r in rooms[1:]:
            if touches(r["id"], hub_room["id"]):
                parent[r["id"]] = hub_room["id"]
    for r in rooms:                 # a laundry off the kitchen, an en-suite
        via = r.get("door_from")
        pid = next((x["id"] for x in rooms if x["name"] == via), None) \
            if via else None
        if pid and touches(r["id"], pid):
            parent[r["id"]] = pid
    for r in rooms[1:]:
        if r["id"] == hall_id:
            continue
        if r["type"] in PUBLIC and touches(r["id"], hub_room["id"]):
            parent[r["id"]] = hub_room["id"]
        elif r["type"] not in PUBLIC and hall_id and \
                touches(r["id"], hall_id):
            parent[r["id"]] = hall_id
    seen |= set(parent)
    q = deque([hub_room["id"]])
    while q:                    # 1: shared rooms, through shared rooms
        cur = q.popleft()
        for nb in adj[cur]:
            if nb not in seen and nb not in private:
                seen.add(nb)
                parent[nb] = cur
                q.append(nb)
    for r in rooms:             # 2: private rooms open off a shared one
        if r["id"] in private and r["id"] not in seen:
            pubs = [nb for nb in adj[r["id"]] if nb in seen and
                    nb not in private]
            if pubs:
                pubs.sort(key=lambda nb: (nb != hub_room["id"], nb))
                parent[r["id"]] = pubs[0]
                seen.add(r["id"])
    q = deque(sorted(seen))
    while q:                    # 3: anything left, any way it can
        cur = q.popleft()
        for nb in adj[cur]:
            if nb not in seen:
                seen.add(nb)
                parent[nb] = cur
                q.append(nb)
    # 4: still cut off - through any shared wall a narrow door fits in
    # (Venice M-1: two rooms that only touch each other used to get two
    # doors on the same spot and stay unreachable)
    narrow = {r["id"]: sorted(b for (a, b), (_w, L) in pair_wall.items()
                              if a == r["id"] and L >= MIN_DOOR + 1.0)
              for r in rooms}
    q = deque(sorted(seen))
    while q:
        cur = q.popleft()
        for nb in narrow[cur]:
            if nb not in seen:
                seen.add(nb)
                parent[nb] = cur
                q.append(nb)
    for r in rooms[1:]:
        p = parent.get(r["id"])
        if p is None:
            warnings.append(f"{r['name']} can't be reached from "
                            f"{hub_room['name']} - no shared wall is long "
                            "enough for a door")
            continue
        wid, L = pair_wall[(r["id"], p)]
        spot = _door_spot(occupied, wid, L, bw,
                          0.75 if bt == "single_family" else 1.75)
        if spot is None:
            warnings.append(f"No room for a door between {r['name']} and "
                            f"{by_id[p]['name']}")
            continue
        along, width = spot
        add({"id": f"D{len(openings) + 1}", "kind": "door",
             "mark": str(base + len([o for o in openings
                                    if o["kind"] == "door"]) + 1),
             "type": "B", "wall": wid, "along": round(along, 3),
             "width": round(width, 3), "height": bh, "swing": "in",
             "from_room": p, "to_room": r["id"]})
    # windows: one per 12 ft of exterior wall in each habitable room
    for r in rooms:
        hab = r["type"] in model.HABITABLE
        bath = r["type"] in ("bath",)
        if not (hab or bath):
            continue
        sides = sorted(_ext_frontage(r, W, D), key=lambda f: -f[3])
        if not sides:
            continue
        typ = "B" if bath else "A"
        ww, wh, sill = WINDOW[typ]
        placed = 0
        for wall, lo, hi, L in sides:
            n = 1 if bath else int(L // WINDOW_EVERY)
            if bath and placed:
                break
            for j in range(n):
                c = lo + L * (j + 0.5) / n
                a_, b_ = c - ww / 2, c + ww / 2
                wl = model.wall_length(next(x for x in walls
                                            if x["id"] == wall))
                if a_ < 0.5 or b_ > wl - 0.5 or not _fits(occupied, wall,
                                                            a_, b_):
                    continue
                add({"id": f"N{len([o for o in openings if o['kind'] == 'window']) + 1}",
                     "kind": "window", "mark": typ, "type": typ,
                     "wall": wall, "along": round(c, 3), "width": ww,
                     "height": wh, "sill": sill, "room": r["id"]})
                placed += 1
        # enough glass for daylight: at least one window, and windows
        # until the glass is 8% of the floor (the self-check's light rule)
        need = 0 if not hab else max(1, math.ceil(
            0.08 * (r["rect"][2] - r["rect"][0]) *
            (r["rect"][3] - r["rect"][1]) / (ww * wh)))
        if hab and placed < need:
            # slide along each outside wall until a window fits beside
            # the doors and the other windows
            for wall, lo, hi, L in sides:
                c = lo + ww / 2 + 0.5
                while c + ww / 2 <= hi - 0.5 + 1e-9 and placed < need:
                    if _fits(occupied, wall, c - ww / 2, c + ww / 2):
                        add({"id": f"N{len([o for o in openings if o['kind'] == 'window']) + 1}",
                             "kind": "window", "mark": typ, "type": typ,
                             "wall": wall, "along": round(c, 3),
                             "width": ww, "height": wh, "sill": sill,
                             "room": r["id"]})
                        placed += 1
                        c += ww + 1.0
                        continue
                    c += 0.5
                if placed >= need:
                    break
    return rooms, walls, openings


FIT_RATIOS = (2.4, 2.0, 1.8, 1.6, 1.4, 1.2, 1.0, 0.9, 0.8, 0.7, 0.6, 0.5)


def _left_out(plan):
    """How many rooms were left out (plan["dropped"]; older plans: the
    warning that lists them)."""
    if "dropped" in plan:
        return len(plan["dropped"])
    for w in plan.get("warnings") or []:
        if "left out:" in w:
            return len(w.split("left out:", 1)[1].split(","))
    return 0


_LANKY_OK = {"hall", "bath", "mech", "laundry", "storage", "restroom",
             "stair"}


def _lanky(plan):
    """Rooms people live in that came out more than 2.5 times as long as
    they are wide (a 10 x 40 ft living room)."""
    n = 0
    for lp in model.levels(plan):
        for r in lp["rooms"]:
            x0, y0, x1, y1 = r["rect"]
            a, b = sorted((x1 - x0, y1 - y0))
            if r["type"] not in _LANKY_OK and a > 0 and b / a > 2.5:
                n += 1
    return n


_SERIOUS = ("window", "door", "reached", "7 ft", "walking")


def _quality(plan):
    """(rooms left out, serious problems, other self-check items not
    passed) - lower is better; the lot and setback items don't count.
    Serious: a room without a window or a door, rooms not reached or
    walked through, rooms under 7 ft, long skinny rooms, and a house left
    with one outside door (0.12.22 review: a garage took the back door)."""
    from . import audit
    serious = minor = 0
    for r in audit.audit(plan):
        name = r[1].lower()
        if r[0] == "PASS" or "lot" in name or "setback" in name:
            continue
        if any(k in name for k in _SERIOUS):
            serious += 1
        else:
            minor += 1
    serious += _lanky(plan)
    if plan["project"]["building_type"] == "single_family" and sum(
            1 for o in plan["openings"] if o.get("from_room") == "EXT") < 2:
        serious += 1
    return (_left_out(plan), serious, minor)


def make_plan(fields):
    """The plan JSON from the brief's fields (see brief.parse).

    When the brief gives the lot and the building doesn't fit its
    setbacks, other proportions are tried (0.12.21: narrow lots) - deeper
    and narrower for a tight width, wider for a shallow lot - and the
    first that fits without leaving out more rooms is used. A sketch's
    proportions are never changed.

    A building type with its own layout hook (types/warehouse.py) makes
    its plan there; houses and small commercial are laid out here."""
    from . import types
    tp = types.get(fields.get("building_type") or "single_family")
    if tp.layout is not None:
        return tp.layout(copy.deepcopy(fields))
    plan = _make_once(copy.deepcopy(fields))
    lot = fields.get("lot") or {}
    s = plan.get("site") or {}
    if fields.get("ratio") or not (lot.get("w") or lot.get("area")) or \
            (s.get("on_lot") and not s.get("binding")):
        return plan
    W0, D0 = plan["footprint"]["width"], plan["footprint"]["depth"]
    r0 = W0 / D0
    base = _quality(plan)
    for r in sorted(FIT_RATIOS, key=lambda r: abs(math.log(r / r0))):
        if abs(math.log(r / r0)) < 0.05:
            continue
        f = copy.deepcopy(fields)
        f["fit_ratio"] = r
        try:
            p = _make_once(f)
        except model.PlanError:
            continue
        ps = p["site"]
        q = _quality(p)
        if ps["on_lot"] and not ps["binding"] and q[:2] <= base[:2] and \
                (q[:2] < base[:2] or q[2] <= base[2] + 1):
            W, D = p["footprint"]["width"], p["footprint"]["depth"]
            p["warnings"].append(
                f"Proportions changed to fit the lot and its setbacks: "
                f"{W:g}' wide x {D:g}' deep (was {W0:g}' x {D0:g}').")
            return p
    return plan


def _make_once(fields):
    """One try at the plan, at the proportions the fields give."""
    bt = fields.get("building_type") or "single_family"
    occ = fields.get("occupancy") or ("R-3" if bt == "single_family"
                                      else "B")
    gross = float(fields.get("gross_sf") or 0)
    warnings = list(fields.get("warnings") or [])
    stories = int(fields.get("stories") or 1)
    if stories > 1 and bt != "single_family":
        warnings.append("Two-story office and retail are a later phase "
                        "(a second exit stair and usually an elevator); "
                        "drawn as one story.")
        stories = 1
    if stories > 1:
        return _two_story(fields, bt, occ, gross, warnings)
    W, D = footprint(gross, bt, fields.get("ratio") or
                     fields.get("fit_ratio"),
                     0.5 if fields.get("fit_ratio") else 1.0)
    t = EXT_T / 2
    inner = (t, t, W - t, D - t)
    net = (W - EXT_T) * (D - EXT_T)
    program = prog.default_program(bt, occ, fields.get("beds"),
                                   fields.get("baths"))
    if bt == "single_family":
        b_, ba_ = fields.get("beds"), fields.get("baths")
        if (b_ and int(b_) > 6) or (ba_ and int(ba_) > 4):
            warnings.append("v1 draws at most 6 bedrooms and 4 baths; "
                            "the rest were left out")
    # room sizes written in the brief (Grok S2)
    sizes = fields.get("room_sizes") or []
    asked = sum(sf * c for _k, sf, c in sizes)
    if asked and asked > 1.3 * gross:
        raise model.PlanError(
            f"The room sizes in the brief add up to {asked:,.0f} SF, more "
            f"than the {gross:,.0f} SF building can hold.")
    for kind, sf, count in sizes:
        free = [r for r in program if r["type"] == kind and
                not r.get("target_sf")]
        if len(free) < count and kind not in ("bed", "bath"):
            warnings.append(f"The brief sizes {count} {kind} room(s); the "
                            f"program has {len(free)}.")
        for r in free[:count]:
            r["target_sf"] = float(sf)
    # names read off a sketch go to the room of the same kind (Venice N:
    # they used to be handed out in order, one room off)
    unused = []
    for n in [n for n in (fields.get("room_names") or []) if n]:
        n = re.sub(r"\s*\b[A-Z]?\d{2,4}[A-Z]?\s*$", "", n.strip())
        if not n:
            continue
        if re.search(r"garage", n, re.I):
            fields.setdefault("garage", 2)      # drawn beside the house
            continue
        if re.search(r"carport|porch|deck|patio", n, re.I):
            warnings.append(f"{n.upper()} on the sketch isn't drawn in v1 "
                            "(porches and decks come later)")
            continue
        kind = _kind_of(n)
        r = next((r for r in program if r["type"] == kind and
                  not r.get("_named")), None) if kind else None
        if r is not None:
            r["name"], r["_named"] = n.upper()[:24], True
        else:
            unused.append(n.upper())
    if unused:
        warnings.append("Sketch room names not used: " + ", ".join(unused))
    for r in program:
        r.pop("_named", None)
    # rooms that can't fit at their smallest are left out (service rooms
    # first, never the main room) rather than drawn as slivers
    dropped = []
    hall_est = 0.0
    while True:
        for _pass in range(2):         # the hall takes some of the net area
            prog_now, w2 = prog.reconcile([dict(r) for r in program],
                                          max(net - hall_est, net * 0.5))
            order = prog_now
            placed = _zoned_any(order, W, D, t)
            if placed is None:
                break
            hall = [rc for r, rc in placed if r["type"] == "hall"]
            hall_est = (hall[0][2] - hall[0][0]) * (hall[0][3] - hall[0][1]) \
                if hall else 0.0
        if placed is not None:
            thin = [r for r, rc in placed
                    if min(rc[2] - rc[0], rc[3] - rc[1]) < 3]
            if not thin:
                break
        if len(program) <= 2:
            if placed is None:
                raise model.PlanError("The program doesn't fit at this "
                                      "size; add SF or fewer rooms.")
            break
        drop_order = {"mech": 0, "storage": 1, "laundry": 2, "office": 3,
                      "restroom": 4, "bath": 5, "bed": 6}

        def last_of_kind(r):
            # a house keeps one bedroom and one bath (Venice M1)
            return r["type"] in ("bed", "bath") and sum(
                x["type"] == r["type"] for x in program) == 1
        cand = [r for r in program[1:] if r["type"] not in PUBLIC and
                not last_of_kind(r)]
        if not cand:
            raise model.PlanError(
                "Too small for a bedroom and a bath at this size and shape; "
                "add SF or use a less square footprint.")
        gone = min(cand, key=lambda r: (drop_order.get(r["type"], 9),
                                        r.get("share", 0), r["name"]))
        program = [r for r in program if r["name"] != gone["name"]]
        dropped.append(gone["name"])
    warnings += w2
    if dropped:
        warnings.append("Too small to fit at this size, left out: "
                        + ", ".join(dropped))
    rooms, walls, openings = build_level(placed, W, D, bt, warnings)
    plan = _assemble(fields, bt, occ, gross, W, D, walls, rooms, openings,
                     warnings)
    plan["dropped"] = list(dropped)        # Venice review M13: not prose
    return plan


def _assemble(fields, bt, occ, gross, W, D, walls, rooms, openings,
              warnings, upper=None):
    """The plan JSON around the level-1 geometry (and level 2's)."""
    house = bt == "single_family"
    plan = {
        "schema": model.SCHEMA, "units": "ft", "disclaimer": DISCLAIMER,
        "project": {
            "name": fields.get("name") or "Untitled Project",
            "address": fields.get("address") or None,
            "firm": fields.get("firm") or "[FIRM NAME]",
            "date": fields.get("date"),
            "building_type": bt, "work": fields.get("work") or "new",
            "occupancy": occ, "gross_sf_target": gross},
        "source": {"brief": fields.get("brief") or "",
                   "sketch": fields.get("sketch"),
                   "ai_used": bool(fields.get("ai_used")),
                   "ai_model": fields.get("ai_model"),
                   "kernel": "modulor", "modulor_version": None},
        "footprint": {"width": W, "depth": D,
                      "from": "sketch" if fields.get("ratio") else
                      ("fit to the lot" if fields.get("fit_ratio")
                       else "brief")},
        "level": {"name": "L1", "floor_elev": 0.0,
                  "plate_height": 9.0 if house else 12.0, "slab": 0.33},
        # the ridge runs the long way: east-west, or north-south on a
        # deep, narrow house (0.12.22) - a front gable to the street. Not
        # with a garage: its gable roof meets the house's east or west
        # wall, which must then be a gable wall too (review M4)
        "roof": ({"type": "gable", "pitch": 6,
                  "ridge_dir": "y" if D > W and not fields.get("garage")
                  else "x",
                  "overhang": 1.5, "parapet": 0} if house else
                 {"type": "flat", "pitch": 0.25, "ridge_dir": None,
                  "overhang": 0, "parapet": 3.0}),
        "walls": walls, "rooms": rooms, "openings": openings,
        "door_types": {"A": "Exterior, insulated",
                       "B": "Interior, hollow core" if house else
                            "Interior, solid core, 3'-0\" (ADA 32 in. "
                            "clear)"},
        "window_types": {"A": "3'-0\" x 4'-0\" single hung",
                         "B": "2'-0\" x 3'-0\" (bath, obscure)"},
        "notes": {"general": [], "project": [], "from_ai": False},
        "warnings": warnings,
    }
    if upper:
        plan["stories"] = 2
        plan["upper"] = upper
    if fields.get("garage"):
        from . import garage as garage_mod
        garage_mod.add(plan, fields["garage"], plan["warnings"])
    from . import site as site_mod
    plan["site"], sw = site_mod.site_for(plan, fields.get("lot"))
    plan["warnings"].extend(w for w in sw if w not in plan["warnings"])
    if fields.get("porch") or fields.get("deck"):
        from . import outdoor
        outdoor.add(plan, {"porch": fields.get("porch"),
                           "deck": fields.get("deck")}, plan["warnings"])
    model.validate(plan)
    return plan


def _side_hall_windows(W, D, stair, levels_):
    """A side hall has a whole outside wall of its own: a window on each
    floor, past the top of the stair (Venice review N10: it was a blind
    wall)."""
    t = EXT_T / 2
    for rooms, openings in levels_:
        hall = rooms[0]
        x0, y0, x1, y1 = hall["rect"]
        if x0 > t + 1e-6:
            continue                       # a centre hall: no outside wall
        lo = max(stair["rect"][3] + 1.0, y0 + 1.0)
        if y1 - lo < 4.0:
            lo = y0 + 1.0
            if stair["rect"][1] - lo < 4.0:
                continue
            y = (lo + stair["rect"][1]) / 2
        else:
            y = (lo + y1) / 2
        n = sum(o["kind"] == "window" for o in openings)
        openings.append({"id": f"N{n + 1}h", "kind": "window", "mark": "A",
                         "type": "A", "wall": "W4", "along": round(D - y, 3),
                         "width": 3.0, "height": 4.0, "sill": 3.0,
                         "room": hall["id"]})


def _two_story(fields, bt, occ, gross, warnings):
    """A two-story house: see twostory.py for the rules."""
    from . import twostory
    if not gross:
        raise model.PlanError("Enter the gross SF (a sketch gives the "
                              "shape only).")
    if gross > MAX_SF:
        raise model.PlanError("v1 covers houses up to 8,000 SF.")
    if fields.get("room_sizes"):
        warnings.append("Room sizes in the brief aren't used for two-story "
                        "houses yet; rooms are sized by the default "
                        "program.")
    W, D = twostory.footprint(gross, fields.get("ratio") or
                              fields.get("fit_ratio"),
                              0.5 if fields.get("fit_ratio") else 1.0)
    if fields.get("beds") and int(fields["beds"]) > 6 or \
            fields.get("baths") and int(fields["baths"]) > 4:
        warnings.append("v1 draws at most 6 bedrooms and 4 baths; "
                        "the rest were left out")
    (l1, l2), stair = twostory.make_levels(fields, W, D, warnings)
    rooms, walls, openings, w1 = l1
    rooms2, walls2, openings2, w2 = l2
    for w_ in w1 + w2:
        if w_ not in warnings:
            warnings.append(w_)
    for rs, word in ((rooms, "UP"), (rooms2, "DN")):
        rs[0]["stair"] = dict(stair, label=word)
    _side_hall_windows(W, D, stair, ((rooms, openings), (rooms2, openings2)))
    ftf = twostory.FLOOR_TO_FLOOR
    upper = {"level": {"name": "L2", "floor_elev": ftf, "plate_height": 9.0,
                       "slab": 0.0},
             "walls": walls2, "rooms": rooms2, "openings": openings2}
    plan = _assemble(fields, bt, occ, gross, W, D, walls, rooms, openings,
                     warnings, upper=upper)
    plan["dropped"] = list(fields.get("_dropped") or [])
    return plan


def reachable(plan):
    """Room ids reachable from the front door through doors (BFS) - and
    across open walls (one space in two rectangles)."""
    g = {}
    for o in plan["openings"]:
        if o["kind"] == "door":
            a, b = o.get("from_room"), o.get("to_room")
            g.setdefault(a, set()).add(b)
            g.setdefault(b, set()).add(a)
    for w in plan.get("walls", []):
        if w.get("kind") == "open" and len(w.get("rooms") or ()) == 2:
            a, b = w["rooms"]
            g.setdefault(a, set()).add(b)
            g.setdefault(b, set()).add(a)
    seen, q = {"EXT"}, deque(["EXT"])
    while q:
        for nb in g.get(q.popleft(), ()):
            if nb not in seen:
                seen.add(nb)
                q.append(nb)
    return seen - {"EXT"}
