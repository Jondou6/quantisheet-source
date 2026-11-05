"""Two-story houses (0.12.17): a center stair hall on both floors.

Decisions (Claude, Oct 19 - Jon to confirm; see docs/GENSET_NOTES.md):
  * Up to two stories, houses only. Two-story office or retail needs a
    second exit stair and usually an elevator - drawn as one story, with
    a warning.
  * The gross SF in the brief is the whole house; each floor gets half.
  * A center stair hall 7 ft wide runs front to back on both floors: a
    straight stair 3'-6" wide on one side, a 3'-6" walk beside it. Every
    room on both floors opens onto it - nobody walks through a room.
  * Level 1: living, kitchen, dining, a laundry / mechanical room, and a
    powder room when there are two or more baths. Level 2: the bedrooms and the other
    baths. The front door opens into the stair hall.
  * A floor too narrow for a good wing on each side (under 10'-6" each)
    gets a side hall instead: the stair hall along the west wall, the
    stair against that wall, every room in one wide wing east of it - a
    row house (0.12.23, narrow lots).
  * Floor to floor 10'-0" (9 ft plate + 1 ft floor framing): 16 risers of
    7 1/2", 15 treads of 10" - a 12'-6" run, with 4 ft clear at the
    bottom and 3 ft at the top.
"""
import itertools
import math

from . import model, program as prog

SH_W = 7.0               # stair hall width
STAIR_W = 3.5
FLOOR_TO_FLOOR = 10.0
RISER_MAX_IN = 7.75
TREAD_IN = 10.0
BOTTOM_CLEAR = 4.0
TOP_CLEAR = 3.0
MIN_D = {"living": 11.0, "kitchen": 9.0, "dining": 9.0, "bed": 9.0,
         "bath": 5.0, "laundry": 5.0, "mech": 4.0}
MIN_WING = 8.0
GRID_SLACK = 0.5


def stair_numbers(f2f=FLOOR_TO_FLOOR):
    risers = math.ceil(f2f * 12 / RISER_MAX_IN - 1e-9)
    rise_in = f2f * 12 / risers
    run = (risers - 1) * TREAD_IN / 12.0
    return risers, rise_in, run


def programs(beds, baths):
    """(level 1 rooms, level 2 rooms): [{name, type, share}], hub first.
    Rooms with "band" share a strip of the wing: the "inner" one against
    the stair hall, the "outer" one on the outside wall with its door from
    the room named in "door_from" (laundry off the kitchen; the primary
    bath off the primary bedroom)."""
    beds = max(1, min(6, int(beds or 3)))
    baths = max(1, min(4, int(baths or 2)))
    hall = {"name": "STAIR HALL", "type": "stair", "share": 0.0}
    l1 = [dict(hall), {"name": "LIVING", "type": "living", "share": 0.30},
          {"name": "KITCHEN", "type": "kitchen", "share": 0.18},
          {"name": "DINING", "type": "dining", "share": 0.14}]
    up_baths = baths
    if baths >= 2:
        l1 += [{"name": "POWDER", "type": "bath", "share": 0.03,
                "band": "svc", "pos": "inner"},
               {"name": "LAUNDRY / MECH", "type": "laundry", "share": 0.07,
                "band": "svc", "pos": "outer", "door_from": "KITCHEN"}]
        up_baths = baths - 1
    else:
        l1.append({"name": "LAUNDRY / MECH", "type": "laundry",
                   "share": 0.07})
    l2 = [dict(hall), {"name": "PRIMARY BEDROOM", "type": "bed",
                       "share": 0.26}]
    for i in range(2, beds + 1):
        l2.append({"name": f"BEDROOM {i}", "type": "bed", "share": 0.17})
    if up_baths >= 2:
        l2 += [{"name": "BATH", "type": "bath", "share": 0.07,
                "band": "suite", "pos": "inner"},
               {"name": "PRIMARY BATH", "type": "bath", "share": 0.08,
                "band": "suite", "pos": "outer",
                "door_from": "PRIMARY BEDROOM"}]
        for i in range(3, up_baths + 1):
            l2.append({"name": f"BATH {i - 1}", "type": "bath",
                       "share": 0.06})
    else:
        l2.append({"name": "BATH", "type": "bath", "share": 0.08})
    return l1, l2


def _bands(rooms):
    """Rooms grouped into strips: [{"rooms": [inner(, outer)], "target",
    "min", "anchor"}]."""
    out, by = [], {}
    for r in rooms:
        key = r.get("band")
        if key and key in by:
            by[key]["rooms"].append(r)
            continue
        b = {"rooms": [r]}
        out.append(b)
        if key:
            by[key] = b
    for b in out:
        b["rooms"].sort(key=lambda r: r.get("pos") != "inner")
        b["target"] = sum(r["target_sf"] for r in b["rooms"])
        b["min"] = max(MIN_D.get(r["type"], 4.0) for r in b["rooms"])
        b["anchor"] = next((r.get("door_from") for r in b["rooms"]
                            if r.get("door_from")), None)
        b["name"] = b["rooms"][0]["name"]
    return out


_SOUTH_FIRST = ["living", "bed", "dining", "bath", "laundry", "kitchen"]


def _wing_order(bands, level_no):
    """South to north, the order tried first. Level 1: living at the
    front, kitchen at the back (for the rear door). Level 2: the biggest
    bedroom on the front corner, then the baths, the other bedrooms
    behind."""
    def kind(b):
        return b["rooms"][0]["type"]
    if level_no == 1:
        return sorted(bands, key=lambda b: (_SOUTH_FIRST.index(kind(b)) if
                                            kind(b) in _SOUTH_FIRST else 9,
                                            b["name"]))
    beds = sorted([b for b in bands if kind(b) == "bed"],
                  key=lambda b: (-b["target"], b["name"]))
    rest = [b for b in bands if kind(b) != "bed"]
    return beds[:1] + rest + beds[1:]


DOOR_FREE = 3.5          # ft of wall a door needs clear of the stair


def center_hall(order, W, D, t, level_no, stair=None, mirror=False):
    """[(room, rect)] with the stair hall (order[0]) down the middle, the
    other rooms in strips across the two wings, or None when they can't
    fit at their smallest. stair (side, (y0, y1)): the strips on that side
    are ordered so each room against the hall keeps DOOR_FREE ft of wall
    that isn't the side of the stair."""
    x0i, y0i, x1i, y1i = t, t, W - t, D - t
    Wi, Di = x1i - x0i, y1i - y0i
    xs0, xs1, sides = hall_span(W, t)
    width = {"W": xs0 - x0i, "E": x1i - xs1}
    if min(width[s_] for s_ in sides) < MIN_WING:
        return None
    if mirror and len(sides) == 1:
        return None
    bands = _bands(order[1:])
    wings = {"W": [], "E": []}
    used = {"W": 0.0, "E": 0.0}
    home = {}
    fixed = {"living": "W", "kitchen": "E"} if level_no == 1 and \
        len(sides) == 2 else {}
    for b in sorted(bands, key=lambda b: (b["anchor"] is not None,
                                          -b["target"], b["name"])):
        k = b["rooms"][0]["type"]
        if b["anchor"] in home:
            side = home[b["anchor"]]               # beside its door room
        elif k in fixed:
            side = fixed[k]
        else:
            side = min(sides, key=lambda s: (used[s] + b["target"] /
                                             width[s], s))
        wings[side].append(b)
        used[side] += b["target"] / width[side]
        for r in b["rooms"]:
            home[r["name"]] = side
    if mirror:                         # the same wings, swapped
        if max(used.values()) > Di * 1.5:
            return None
        wings = {"W": wings["E"], "E": wings["W"]}
    out = [(order[0], (xs0, y0i, xs1, y1i))]
    for side in sides:
        pref = _wing_order(wings[side], level_no)
        if not pref:
            return None
        x0, x1 = (x0i, xs0) if side == "W" else (xs1, x1i)
        hall_x = xs0 if side == "W" else xs1
        need_search = (stair and stair[0] == side) or any(
            b["anchor"] for b in pref)
        # the preferred order first; when it can't be stacked (or doors
        # need searching) the other orders, rather than dropping a room
        tries = itertools.chain([tuple(pref)], itertools.permutations(pref))
        for bs in itertools.islice(tries, 5040):
            bs = list(bs)
            if not _anchored(bs):
                continue
            col = _stack(bs, x0, x1, y0i, y1i, hall_x)
            if col is None:          # this order doesn't fit: try the next
                continue             # (Venice review S2: it gave up here)
            if stair and stair[0] == side:
                sy0, sy1 = stair[1]
                if any(max(min(y2, sy0) - y, y2 - max(y, sy1)) < DOOR_FREE
                       for r, (_a, y, _b, y2) in col
                       if r.get("pos") != "outer"):
                    continue
            out += col
            break
        else:
            return None
    return out


def _anchored(bands):
    """A strip whose outer room opens off another room sits next to it."""
    idx = {r["name"]: i for i, b in enumerate(bands) for r in b["rooms"]}
    return all(abs(idx.get(b["anchor"], -9) - i) == 1
               for i, b in enumerate(bands) if b["anchor"])


def _stack(bands, x0, x1, y0i, y1i, hall_x):
    """The strips of one wing, south to north, filling it; a two-room
    strip has its inner room against the stair hall."""
    Di, wid = y1i - y0i, x1 - x0
    depths = _depths([b["target"] / wid for b in bands],
                     [b["min"] for b in bands], Di)
    if depths is None:
        return None
    col, y = [], y0i
    for i, (b, dpt) in enumerate(zip(bands, depths)):
        # the minimums allow for the 1 ft grid starting at the wall's
        # inside face (up to 6" less)
        rest = sum(x["min"] - GRID_SLACK for x in bands[i + 1:])
        if i == len(bands) - 1:
            y2 = y1i
        else:      # on the 1 ft grid, never squeezing the strips after it
            y2 = float(round(y + dpt))
            y2 = max(y2, float(math.ceil(y + b["min"] - GRID_SLACK - 1e-9)))
            y2 = min(y2, float(math.floor(y1i - rest + 1e-9)))
        if y2 - y < b["min"] - GRID_SLACK - 1e-6:
            return None
        if len(b["rooms"]) == 1:
            col.append((b["rooms"][0], (x0, y, x1, y2)))
        else:
            inner, outer = b["rooms"]
            wi = float(round(min(max(inner["target_sf"] / (y2 - y), 5.0),
                                 wid - 5.0)))
            if wi < 5.0 - 1e-6 or wid - wi < 5.0 - 1e-6:
                return None
            if hall_x == x1:                      # west wing: hall east
                col += [(inner, (x1 - wi, y, x1, y2)),
                        (outer, (x0, y, x1 - wi, y2))]
            else:
                col += [(inner, (x0, y, x0 + wi, y2)),
                        (outer, (x0 + wi, y, x1, y2))]
        y = y2
    return col


def _depths(want, mins, total):
    """Depths adding up to `total`: each at least its minimum, the rest
    shared in proportion to what the program asked for (water-filling).
    None when the minimums alone don't fit."""
    if sum(mins) > total + GRID_SLACK * len(mins) + 1e-6:
        return None
    lo, hi = 0.0, total / max(min(want), 1e-6) + 1
    for _ in range(60):
        k = (lo + hi) / 2
        if sum(max(m, k * w) for w, m in zip(want, mins)) > total:
            hi = k
        else:
            lo = k
    return [max(m, lo * w) for w, m in zip(want, mins)]


SIDE_HALL_WING = 10.5    # wings narrower than this: a side hall instead


def hall_span(W, t):
    """(x0, x1, wing sides) of the stair hall: down the middle with a
    wing each side, or - on a floor too narrow for two good wings
    (0.12.23: narrow lots) - along the west wall with one wide wing east
    of it, like a side-hall row house."""
    x0i, x1i = t, W - t
    Wi = x1i - x0i
    if (Wi - SH_W) / 2 < SIDE_HALL_WING and Wi - SH_W >= 2 * MIN_WING:
        return x0i, x0i + SH_W, ("E",)
    xs0 = float(round(x0i + (Wi - SH_W) / 2))
    return xs0, xs0 + SH_W, ("W", "E")


def stair_options(W, D, t):
    """Where the stair can go in the hall: [(side, dir, run rect)]. With
    a side hall the stair runs along the outside wall, the walk beside the
    rooms."""
    x0i, y0i, x1i, y1i = t, t, W - t, D - t
    xs0, xs1, sides = hall_span(W, t)
    _r, _ri, run = stair_numbers()
    out = []
    for side in (("E", "W") if len(sides) == 2 else ("W",)):
        sx0, sx1 = (xs1 - STAIR_W, xs1) if side == "E" else \
            (xs0, xs0 + STAIR_W)
        for d in ("N", "S"):
            if d == "N":
                sy0 = y0i + BOTTOM_CLEAR
            else:
                sy0 = y1i - BOTTOM_CLEAR - run
            out.append((side, d, (sx0, sy0, sx1, sy0 + run)))
    return out


def min_depth():
    return BOTTOM_CLEAR + stair_numbers()[2] + TOP_CLEAR + 0.5


def reached(rooms, openings):
    hub = rooms[0]["id"]
    adj = {}
    for o in openings:
        if o["kind"] == "door":
            a, b = o.get("from_room"), o.get("to_room")
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)
    seen, todo = {hub}, [hub]
    while todo:
        for nb in adj.get(todo.pop(), ()):
            if nb not in seen:
                seen.add(nb)
                todo.append(nb)
    return {r["id"] for r in rooms} <= seen


def footprint(gross_total, ratio=None, min_ratio=1.0):
    """(W, D) of one floor: half the house, deep enough for the stair."""
    from .layout import _r2, MAX_W, MAX_D
    if gross_total < 1200:
        raise model.PlanError("Two-story houses start at 1,200 SF (600 SF "
                              "a floor).")
    per = gross_total / 2.0
    ratio = max(min_ratio, min(3.0, ratio or 1.6))
    w = _r2(math.sqrt(per * ratio))
    d = _r2(per / w)
    need = math.ceil(min_depth())
    if d < need:
        d = float(need + need % 2)
        w = _r2(per / d)
    if w < SH_W + 2 * MIN_WING + 0.5:
        raise model.PlanError(
            "Too small for two stories: each floor needs room for the "
            "stair hall and a room on each side - about 1,000 SF or more "
            "in all.")
    if w > MAX_W or d > MAX_D:
        raise model.PlanError("v1 covers two-story houses up to 120 x 80 "
                              "ft a floor.")
    return float(w), float(d)


_DROP = {"mech": 0, "laundry": 1, "dining": 2, "bath": 3, "bed": 4}


def _droppable(progm, level_no):
    keep = ("living", "kitchen") if level_no == 1 else ("bed", "bath")
    anchors = {r.get("door_from") for r in progm}
    cand = [r for r in progm[1:] if r["name"] not in anchors and not (
        r["type"] in keep and
        sum(x["type"] == r["type"] for x in progm) == 1)]
    # an en-suite bath goes before the hall bath the other bedrooms use
    return min(cand, key=lambda r: (_DROP.get(r["type"], 9),
                                    not r.get("door_from"), r["share"],
                                    r["name"])) if cand else None


def make_levels(fields, W, D, warnings):
    """([(rooms, walls, openings, warnings)] for levels 1 and 2, stair
    dict), or a PlanError."""
    from .layout import EXT_T, build_level
    t = EXT_T / 2
    net = (W - EXT_T) * (D - EXT_T)
    hall_sf = SH_W * (D - EXT_T)
    progs = dict(zip((1, 2), programs(fields.get("beds"),
                                      fields.get("baths"))))
    dropped = []
    risers, rise_in, run = stair_numbers()

    moved = []

    def remove(gone):
        """Leave a room out - the laundry first moves upstairs."""
        for n in (1, 2):
            progs[n] = [r for r in progs[n] if r["name"] != gone["name"]]
        if gone["type"] == "laundry" and not moved:
            progs[2].append({"name": gone["name"], "type": "laundry",
                             "share": gone["share"]})
            moved.append(gone["name"])
            return
        dropped.append(gone["name"])

    def order_for(level_no):
        """The level's rooms with their target SF, dropping rooms until
        the floor holds them (without the stair yet)."""
        while True:
            progm = progs[level_no]
            rooms, _w = prog.reconcile([dict(r) for r in progm[1:]],
                                       net - hall_sf)
            hub = dict(progm[0], target_sf=round(hall_sf, 1))
            if center_hall([hub] + rooms, W, D, t, level_no) is not None:
                return [hub] + rooms
            gone = _droppable(progm, level_no)
            if gone is None:
                raise model.PlanError(
                    f"Level {level_no} doesn't fit at this size; add SF.")
            remove(gone)

    for _attempt in range(10):
        orders = {1: order_for(1), 2: order_for(2)}
        # the first stair position where every room on both floors keeps
        # a door it can use
        for side, d, rect in stair_options(W, D, t):
            trial = []
            for level_no in (1, 2):
                for mirror in (False, True):
                    got = center_hall(orders[level_no], W, D, t, level_no,
                                      stair=(side, (rect[1], rect[3])),
                                      mirror=mirror)
                    if got is not None:
                        break
                if got is None:
                    break
                w_ = []
                rooms, walls, openings = build_level(
                    [(dict(r), rc) for r, rc in got], W, D,
                    "single_family", w_, level_no=level_no,
                    entry=level_no == 1, all_to_hub=True, blocked=[rect])
                if not reached(rooms, openings):
                    break
                trial.append((rooms, walls, openings, w_))
            if len(trial) == 2:
                if dropped:
                    warnings.append("Too small to fit at this size, left "
                                    "out: " + ", ".join(dropped))
                if moved and any(r["name"] == moved[0] for r, _rc in got):
                    warnings.append("The laundry is upstairs (no room for "
                                    "it on the first floor).")
                fields["_dropped"] = list(dropped)
                stair = {"side": side, "dir": d, "rect": list(rect),
                         "risers": risers, "rise_in": round(rise_in, 3),
                         "tread_in": TREAD_IN, "width": STAIR_W}
                return trial, stair
        # no room for the stair as it is: one room fewer on the fuller
        # floor, and try again
        lv = max((2, 1), key=lambda n: len(progs[n]))
        gone = _droppable(progs[lv], lv) or _droppable(progs[3 - lv], 3 - lv)
        if gone is None:
            break
        remove(gone)
    raise model.PlanError("No place for the stair where every room keeps a "
                          "door; try another size or shape.")
