"""An attached garage beside the house (0.12.19).

Rules (Claude, Oct 19 - for Jon to confirm, see docs/GENSET_NOTES.md):
  * Houses only. "garage" in the brief gives a 2-car garage; "1-car",
    "2 car", "three-car" set the size: 12, 22 or 32 ft wide (wall
    centrelines) by 22 ft deep, flush with the front of the house.
  * It goes on the side whose house room is best to walk into from it:
    laundry, kitchen, mech, a hall, dining, living - never a bedroom or a
    bath. One door into the house (type C: fire-rated, self-closing -
    verify), overhead doors on the street side (9 ft for one car, 16 ft
    for two, 16 + 9 for three), 7 ft high.
  * House windows on the wall the garage covers are taken out.
  * The garage is not in the heated gross area; the cover and the
    schedules show it separately.

Plan coordinates as the house: feet, x east, y north, (0, 0) at the
house's south-west wall centreline - so a garage on the west has x < 0.
"""
import re

from . import model

SIZES = {1: 12.0, 2: 22.0, 3: 32.0}
DEPTH = 22.0
MIN_DEPTH = 20.0          # a car needs about 20 ft
ROOF_CLEAR = 0.5          # ft between the garage roof and a window sill
WALL_T = 0.5
OH_H = 7.0
STAIR_CLEAR = 3.5          # ft clear of the stair for the garage door
PREF = {"laundry": 0, "kitchen": 1, "mech": 2, "stair": 3, "hall": 3,
        "dining": 4, "living": 5}

_WORDS = {"one": 1, "single": 1, "two": 2, "double": 2, "three": 3,
          "triple": 3, "1": 1, "2": 2, "3": 3}
_GAR = re.compile(r"\b(?:(one|single|two|double|three|triple|[123])"
                  r"[\s-]*(?:car|bay|stall)s?\b[\s-]*)?(?:attached\s+)?"
                  r"garage\b", re.I)
# "no garage", "detached garage", "existing garage", "garage later" - none
# is a garage to attach (Fable review N7)
_NO = re.compile(r"\b(?:no|without)\s+(?:an?\s+)?(?:attached\s+)?garage\b|"
                 r"\b(?:detached|separate|existing|future|freestanding)\s+"
                 r"(?:(?:one|two|three|[123])[\s-]*car\s+)?garage\b|"
                 r"\bgarage\s+(?:later|in\s+the\s+future|not\s+needed|"
                 r"by\s+others)\b", re.I)


def read(text):
    """Cars (1-3) for a garage named in the brief, or None."""
    t = text or ""
    if _NO.search(t):
        return None
    m = _GAR.search(t)
    if not m:
        return None
    return _WORDS.get((m.group(1) or "two").lower(), 2)


def _overhead(cars, x0, x1):
    """[(x0, x1)] of the overhead doors on the south wall."""
    mid = (x0 + x1) / 2
    if cars == 1:
        return [(mid - 4.5, mid + 4.5)]
    if cars == 2:
        return [(mid - 8.0, mid + 8.0)]
    # three: a double and a single with 2 ft of wall between
    a = x0 + (x1 - x0 - 27.0) / 2
    return [(a, a + 16.0), (a + 18.0, a + 27.0)]


def add(plan, cars, warnings):
    """Put the garage on the plan (plan["garage"], a door into the house).
    The side whose room is best to walk into, unless covering that wall
    would leave a room with no window - then the other side. Returns True
    when it was added."""
    import copy
    if plan["project"]["building_type"] != "single_family":
        warnings.append("Garages are drawn for houses only; left out.")
        return False
    if depth(plan) < MIN_DEPTH:
        warnings.append(f"The house is only {plan['footprint']['depth']:g} "
                        f"ft deep - an attached garage needs {MIN_DEPTH:g} "
                        "ft; garage left out.")
        return False
    last = None
    # first a side that leaves every habitable room a window (0.12.22
    # review M3), then one where only a kitchen, dining or living room
    # goes without (a warning); a bedroom must always keep a window (the
    # self-check fails it)
    for strict in (True, False):
        for side in _sides(plan, cars):
            trial, w_ = copy.deepcopy(plan), []
            if _add(trial, cars, w_, side) and not _dark(
                    trial, beds=not strict, all_levels=True):
                plan.clear()
                plan.update(trial)
                warnings += w_
                return True
            last = (trial, w_) if last is None else last
    w_ = last[1] if last else ["No room to enter a garage from (only "
                               "bedrooms or baths on the side walls); "
                               "garage left out."]
    if last and last[0].get("garage"):
        w_ = ["The garage would cover the only window of a room on either "
              "side; garage left out."]
    warnings += w_
    return False


def _dark(plan, beds=False, all_levels=None):
    """Habitable rooms (or only bedrooms) with no window - on every floor
    when beds=True (an upstairs bedroom can lose its window to the garage
    roof too)."""
    from .model import HABITABLE, levels
    out = []
    lvls = levels(plan) if (beds if all_levels is None else all_levels) \
        else [plan]
    for lp in lvls:
        lit = {o.get("room") for o in lp["openings"]
               if o["kind"] == "window"}
        out += [r["name"] for r in lp["rooms"]
                if (r["type"] == "bed" if beds else r["type"] in HABITABLE)
                and r["id"] not in lit]
    return out


def depth(plan):
    """22 ft, or the house's depth when it is 20-22 ft (the garage never
    runs past the back of the house - Fable review M6)."""
    return min(DEPTH, float(plan["footprint"]["depth"]))


def _sides(plan, cars):
    """The sides to try, best door room first."""
    W = plan["footprint"]["width"]
    t, GD = 0.25, depth(plan)
    best = {}
    for side in ("E", "W"):
        edge = W - t if side == "E" else t
        for r in plan["rooms"]:
            x0, y0, x1, y1 = r["rect"]
            if r["type"] not in PREF:
                continue
            if abs((x1 if side == "E" else x0) - edge) > 1e-6:
                continue
            if min(y1, GD - t) - max(y0, t) < 4.0:
                continue
            k = (PREF[r["type"]], side != "E")
            best[side] = min(best.get(side, k), k)
    return sorted(best, key=lambda s_: best[s_])


def _add(plan, cars, warnings, only_side):
    from .layout import DOOR, _door_spot
    cars = max(1, min(3, int(cars)))
    W, D = plan["footprint"]["width"], plan["footprint"]["depth"]
    GW, GD = SIZES[cars], depth(plan)
    t = 0.25
    best = None
    for side in (only_side,):
        edge = W - t if side == "E" else t
        for r in plan["rooms"]:
            x0, y0, x1, y1 = r["rect"]
            if r["type"] not in PREF:
                continue
            if abs((x1 if side == "E" else x0) - edge) > 1e-6:
                continue
            lo, hi = max(y0, t), min(y1, GD - t)
            if hi - lo < 4.0:
                continue
            key = (PREF[r["type"]], side != "E", r["number"])
            if best is None or key < best[0]:
                best = (key, side, r, lo, hi)
    if best is None:
        warnings.append("No room to enter a garage from (only bedrooms or "
                        "baths on the side walls); garage left out.")
        return False
    _k, side, room, lo, hi = best
    wall = "W2" if side == "E" else "W4"
    L = model.wall_length(next(w for w in plan["walls"] if w["id"] == wall))

    def along(y):                       # W2 runs north, W4 runs south
        return y if side == "E" else D - y
    span = sorted((along(0.0), along(GD)))
    # no windows into the garage; an outside door there opens into it
    kept, moved, lost = [], None, set()
    for o in plan["openings"]:
        if o["wall"] == wall and o["along"] + o["width"] / 2 > span[0] \
                and o["along"] - o["width"] / 2 < span[1]:
            if o["kind"] == "window":
                lost.add(o.get("room"))
                continue
            if o.get("from_room") == "EXT" and moved is None:
                moved = o
        kept.append(o)
    plan["openings"] = kept
    _relight(plan, wall, span, lost)
    if moved is not None:
        moved.update(type="C", from_room="GAR", width=DOOR["A"][0])
        door = moved
        # the cover and schedules name the room this door really opens
        # into (0.12.22 review M1: it said LAUNDRY for a kitchen door)
        room = next((r for r in plan["rooms"]
                     if r["id"] == moved.get("to_room")), room)
        if not any(o.get("from_room") == "EXT" and o["kind"] == "door"
                   and o is not moved for o in kept
                   if o["wall"] != "W1"):
            # say so plainly (Venice review M9: the deck warning blamed
            # the deck)
            warnings.append("The garage covers the back door's wall: that "
                            "door now opens into the garage, so the house "
                            "has no other back door (and no deck).")
    else:
        occ = [(o["wall"], o["along"] - o["width"] / 2,
                o["along"] + o["width"] / 2) for o in kept]
        # never into the side of the stair (Venice review S6: a side-hall
        # house has its stair against this very wall)
        st = (plan["rooms"][0].get("stair") or {}).get("rect")
        if st and ((side == "W" and st[0] <= t + 0.01) or
                   (side == "E" and st[2] >= W - t - 0.01)):
            a_, b_ = sorted((along(st[1]), along(st[3])))
            occ.append((wall, a_ - STAIR_CLEAR, b_ + STAIR_CLEAR))
        a, b = sorted((along(lo), along(hi)))
        # a door spot inside the room's stretch of the wall
        spot = None
        for c in (a + 0.75 + 1.5, (a + b) / 2, b - 0.75 - 1.5):
            if a + 0.5 + 1.5 <= c <= b - 0.5 - 1.5 and \
                    all(not (w_ == wall and c - 1.5 < q + 0.25 and
                             c + 1.5 > p - 0.25) for w_, p, q in occ):
                spot = c
                break
        if spot is None:
            got = _door_spot(occ, wall, L, DOOR["A"][0])
            spot = got[0] if got and a <= got[0] <= b else None
        if spot is None:
            warnings.append("No room for a door from the garage into the "
                            "house; garage left out.")
            return False
        n = sum(o["kind"] == "door" for o in kept)
        door = {"id": f"D{len(kept) + 1}", "kind": "door",
                "mark": str(100 + n + 1), "type": "C", "wall": wall,
                "along": round(spot, 3), "width": DOOR["A"][0],
                "height": DOOR["A"][1], "swing": "in",
                "from_room": "GAR", "to_room": room["id"]}
        plan["openings"].append(door)
    gx0, gx1 = (W, W + GW) if side == "E" else (-GW, 0.0)
    plan["garage"] = {
        "cars": cars, "side": side, "rect": [gx0, 0.0, gx1, GD],
        "width": GW, "depth": GD, "wall_t": WALL_T,
        "plate_height": 9.0, "pitch": 6, "overhang": 1.0,
        "area": round((GW - WALL_T) * (GD - WALL_T), 1),
        "overhead": [list(x) for x in _overhead(cars, gx0, gx1)],
        "overhead_h": OH_H, "door": door["id"], "into": room["name"],
        "number": "G01", "name": f"GARAGE ({cars}-CAR)"}
    _clear_upper(plan, wall, span)
    plan["door_types"]["C"] = ("Garage to house: fire-rated, self-closing "
                               "(verify locally)")
    plan["door_types"]["OH"] = "Overhead sectional garage door, insulated"
    return True


def walls(g):
    """The garage's own walls as rectangles (x0, y0, x1, y1), the overhead
    door openings cut out of the south wall. The house wall it shares is
    the house's."""
    gx0, gy0, gx1, gy1 = g["rect"]
    h = g["wall_t"] / 2
    out_x = gx1 if g["side"] == "E" else gx0
    rects = [(gx0 - (h if g["side"] == "W" else 0), gy1 - h,
              gx1 + (h if g["side"] == "E" else 0), gy1 + h),       # north
             (out_x - h, gy0 - h, out_x + h, gy1 + h)]             # side
    x = gx0 if g["side"] == "E" else gx0 - h
    for a, b in sorted(g["overhead"]):
        if a > x:
            rects.append((x, gy0 - h, a, gy0 + h))
        x = b
    end = gx1 + h if g["side"] == "E" else gx1
    if end > x:
        rects.append((x, gy0 - h, end, gy0 + h))
    return rects


def bbox(plan):
    """(x0, y0, x1, y1) of the house and garage together (centrelines)."""
    W, D = plan["footprint"]["width"], plan["footprint"]["depth"]
    g = plan.get("garage")
    if not g:
        return 0.0, 0.0, W, D
    gx0, gy0, gx1, gy1 = g["rect"]
    return min(0.0, gx0), 0.0, max(W, gx1), max(D, gy1)


def _relight(plan, covered_wall, span, lost=()):
    """Rooms that lost windows to the garage get them back on their other
    outside walls, where they fit, until the glass is 8% of the floor
    again (the layout's daylight rule)."""
    import math
    from .layout import WINDOW, _ext_frontage, _fits
    from .model import HABITABLE
    W, D = plan["footprint"]["width"], plan["footprint"]["depth"]
    ww, wh, sill = WINDOW["A"]
    for r in plan["rooms"]:
        if r["id"] not in lost or r["type"] not in HABITABLE:
            continue
        x0, y0, x1, y1 = r["rect"]
        need = max(1, math.ceil(0.08 * (x1 - x0) * (y1 - y0) / (ww * wh)))
        have = sum(o["kind"] == "window" and o.get("room") == r["id"]
                   for o in plan["openings"])
        for wall, lo, hi, _L in sorted(_ext_frontage(r, W, D),
                                       key=lambda f: -f[3]):
            c = lo + ww / 2 + 0.75
            while c + ww / 2 <= hi - 0.75 and have < need:
                a, b = c - ww / 2, c + ww / 2
                occ = [(o["wall"], o["along"] - o["width"] / 2,
                        o["along"] + o["width"] / 2)
                       for o in plan["openings"]]
                in_garage = wall == covered_wall and b > span[0] and \
                    a < span[1]
                if not in_garage and _fits(occ, wall, a, b):
                    n = sum(o["kind"] == "window" for o in plan["openings"])
                    plan["openings"].append({
                        "id": f"N{n + 1}g", "kind": "window", "mark": "A",
                        "type": "A", "wall": wall, "along": round(c, 3),
                        "width": ww, "height": wh, "sill": sill,
                        "room": r["id"]})
                    have += 1
                    c += ww + 1.0
                    continue
                c += 0.5
            if have >= need:
                break


def _clear_upper(plan, wall, span):
    """Second-floor windows the garage roof would run into come out (and
    go back on the room's other outside walls) - Fable review M5. The
    roof slopes from the plate up to the ridge at mid-depth; a sill must
    clear it by ROOF_CLEAR."""
    up = plan.get("upper")
    g = plan.get("garage")
    if not up or not g:
        return
    from .model import levels
    D = plan["footprint"]["depth"]
    GD, p = g["depth"], g["pitch"] / 12.0
    f2 = up["level"]["floor_elev"]

    def y_of(along):
        return along if wall == "W2" else D - along
    keep, lost = [], set()
    for o in up["openings"]:
        if o["kind"] == "window" and o["wall"] == wall:
            ya, yb = sorted((y_of(o["along"] - o["width"] / 2),
                             y_of(o["along"] + o["width"] / 2)))
            if yb > 0 and ya < GD:
                y = min(max(GD / 2, ya), yb)        # the highest roof under it
                roof = g["plate_height"] + p * min(y, GD - y)
                if f2 + o["sill"] < roof + ROOF_CLEAR:
                    lost.add(o.get("room"))
                    continue
        keep.append(o)
    up["openings"] = keep
    if lost:
        _relight(levels(plan)[1], wall, span, lost)
