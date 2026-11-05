"""Stand-alone restaurant: assembly (A-2), one story, 2,000 - 12,000 SF.

Rules (Claude, Oct 21 - for Jon to confirm; every default below is an
assumption and the set says so):
  * Footprint about 1.4:1 (wide to deep), 2 ft increments, the street and
    the parking to the south; made deeper when the kitchen and the
    restrooms need it. Up to 160 x 110 ft.
  * Front of house along the street, about 58% of the depth: the DINING
    room (storefront glass and the entrance on the south, a second exit
    and windows on the west) and, at the east end, a column with a
    WAITING area (the entrance moves there when the column has room), the
    MEN and WOMEN restrooms off the dining room and a JAN / ELEC room
    (the service sink) at the back of it.
  * Restrooms: separate men's and women's rooms, each sized for the water
    closets and lavatories IPC Table 2902.1 asks for the A-2 occupant
    load (codecheck.fixtures via codes.py - never numbers of its own);
    one WC and one lav a single-user room 8 x 9 ft, more a multi-user
    room (urinals may stand in for some men's WCs - by the design
    professional).
  * Back of house, the rest of the depth, west to east: OFFICE and DRY
    STORAGE (with DISH at the front when there is a drive-thru), the
    KITCHEN (the hub: the dining room's service door, every back-of-house
    room off it, and the 3'-6" service / receiving door on the north
    wall), then DISH (or the DRIVE-THRU pick-up room with its window on
    the east wall), PREP and the WALK-IN COOLER and WALK-IN FREEZER (the
    freezer off the prep room).
  * A drive-thru only when the brief says so: the window on the east
    wall, a 12 ft lane past it (stacking by the civil engineer). A brief
    that names the west side ("drive-thru window on the west side") gets
    the plan mirrored east to west: the window on the west wall, not
    marked assumed.
  * Type I hood over the cook line and a grease interceptor - noted and
    counted as assumed (sizes by the mechanical / plumbing engineers and
    the local FOG program); never drawn as designed.
  * 14 ft to the roof bearing, a low-slope roof inside a 3 ft parapet;
    fully sprinklered (NFPA 13).
  * Parking in front: the brief's count, else 10 spaces per 1,000 SF
    (assumed - zoning decides).
  * Dining at 15 SF a seat (the A-2 unconcentrated factor, assumed for
    the seat count); a brief's "120 seats" sizes the dining room.
"""
import math
import re

from .base import BuildingType

RATIO = 1.4
FRONT_SHARE = 0.58             # of the inside depth: the dining band
BACK_SHARE = 0.42
COL_A, COL_A_RANGE = 0.22, (10.0, 28.0)     # office / dry storage column
COL_C, COL_C_RANGE = 0.28, (14.0, 32.0)     # dish / prep / walk-ins
KITCHEN_MIN_W = 12.0
DINING_MIN_W, DINING_MIN_D = 20.0, 14.0
SEAT_SF = 15.0                 # dining SF a seat (assumed)
PLATE = 14.0
PARAPET = 3.0
PARKING_PER_1000 = 10.0        # assumed (zoning decides)
LANE_W = 12.0                  # drive-thru lane (assumed)
STACK = 8                      # cars stacked behind the window (assumed)
RR_SINGLE = (8.0, 9.0)         # single-user restroom, ft (x, y)
JAN_D = 7.0
WAIT_MIN = 8.0
MIN_D = {"office": 8.0, "dry_storage": 6.0, "dish": 7.0, "drive_thru": 7.0,
         "prep": 8.0}
SF_DOOR_H = 7.0
SF_GLASS_H, SF_SILL, SF_PANE = 7.0, 1.5, 8.0
WIN_A = (3.0, 4.0, 3.0)        # w, h, sill
DT_WIN = (4.0, 4.0, 3.5)
RECEIVING = (3.5, 7.0)
WINDOW_EVERY = 12.0

PATTERNS = (r"\brestaurants?\b", r"\bcaf[eé]s?\b", r"\bdiners?\b",
            r"\bbistro\b", r"\beatery\b", r"\bcoffee\s+(?:shop|house)\b",
            r"\bfast[- ]food\b", r"\bquick[- ]service\b", r"\bpizzeria\b",
            r"\bbrew\s*pub\b")
_DRIVE = re.compile(r"\bdrive[- ]?(?:thru|through|thr?u)\b", re.I)
# a drive-thru bank or pharmacy is not a restaurant
_NOT_FOOD = re.compile(r"\b(?:bank|pharmacy|credit union|car wash|"
                       r"dry clean\w*)\b", re.I)
# the side the brief puts the pick-up window on ("drive-thru window on the
# west side", "west-side drive-thru"); within the phrase, no comma between
_SIDE_WORD = r"(east|west|north|south)(?:ern)?"
_DT_SIDE = [re.compile(r"\bdrive[- ]?(?:thru|through|thr?u)\b[^.;,\n]{0,30}?"
                       r"\b" + _SIDE_WORD + r"\b", re.I),
            re.compile(r"\b" + _SIDE_WORD + r"(?:[- ](?:side|facing|wall))?"
                       r"\s+(?:side\s+)?drive[- ]?(?:thru|through|thr?u)\b",
                       re.I)]
SIDES = {"east": "E", "west": "W", "north": "N", "south": "S"}
_SEATS = [re.compile(r"\b(\d{2,4})\s*(?:-\s*)?seats?\b", re.I),
          re.compile(r"\bseat(?:s|ing)?\s*(?:for|of|:|-)?\s*(\d{2,4})\b",
                     re.I)]

USES = {"dining": "assembly_unconcentrated",
        "lobby": "assembly_unconcentrated",
        "kitchen_comm": "kitchen", "prep": "kitchen", "dish": "kitchen",
        "drive_thru": "kitchen", "walkin": "storage_mech",
        "dry_storage": "storage_mech", "mech": "storage_mech",
        "office": "business", "restroom": "support"}
CEILING = {"dining": 10.0, "lobby": 10.0, "kitchen_comm": 10.0,
           "prep": 10.0, "dish": 10.0, "drive_thru": 10.0, "walkin": 8.0,
           "dry_storage": 10.0, "mech": 9.0, "office": 9.0, "restroom": 9.0}


# ---- the brief ------------------------------------------------------------
def detect(text):
    """"drive-thru" - unless it's a bank's or a pharmacy's."""
    t = text or ""
    if _NOT_FOOD.search(t):
        return None
    return [m.group(0).lower() for m in _DRIVE.finditer(t)] or None


def read(text):
    """seats, drive_thru, parking from the brief."""
    from .warehouse import _PARKING
    t = text or ""
    out = {}
    for rx in _SEATS:
        m = rx.search(t)
        if m and 10 <= int(m.group(1)) <= 800:
            out["seats"] = int(m.group(1))
            break
    if _DRIVE.search(t) and not _NOT_FOOD.search(t):
        out["drive_thru"] = True
        side = drive_thru_side(t)
        if side:
            out["drive_thru_side"] = side
    m = _PARKING.search(t)
    if m and 0 < int(m.group(1)) <= 2000:
        out["parking"] = int(m.group(1))
    return out


def drive_thru_side(text):
    """"E" / "W" / "N" / "S": the side the brief puts the drive-thru
    window on, else None (review 0.12.39 #5)."""
    for rx in _DT_SIDE:
        m = rx.search(text or "")
        if m:
            return SIDES[m.group(1).lower()]
    return None


def _mirror_x(plan):
    """The plan mirrored east to west (x -> W - x): the rooms, the interior
    walls and the openings (the exterior walls stay W1 S, W2 E, W3 N, W4 W;
    an opening on W2 goes to W4 and back, along = D - along). Each wall
    keeps its direction (horizontal walls still run west to east), so an
    opening on a horizontal wall is at L - along. `along` is the centre."""
    W, D = plan["footprint"]["width"], plan["footprint"]["depth"]
    flip = {}
    for w in plan["walls"]:
        if w["kind"] == "exterior":
            continue
        (ax, ay), (bx, by) = w["a"], w["b"]
        if abs(ay - by) < 1e-9:                     # horizontal
            w["a"], w["b"] = [W - bx, ay], [W - ax, by]
            flip[w["id"]] = abs(bx - ax)
        else:
            w["a"], w["b"] = [W - ax, ay], [W - bx, by]
    for r in plan["rooms"]:
        x0, y0, x1, y1 = r["rect"]
        r["rect"] = [W - x1, y0, W - x0, y1]
    swap = {"W2": "W4", "W4": "W2"}
    for o in plan["openings"]:
        wid = o["wall"]
        if wid in ("W1", "W3"):
            o["along"] = W - o["along"]
        elif wid in swap:
            o["wall"], o["along"] = swap[wid], D - o["along"]
        elif wid in flip:
            o["along"] = flip[wid] - o["along"]
    rs = plan.get("restaurant") or {}
    if rs.get("kitchen_rect"):
        x0, y0, x1, y1 = rs["kitchen_rect"]
        rs["kitchen_rect"] = [W - x1, y0, W - x0, y1]
    return plan


# ---- sizes ------------------------------------------------------------------
def restroom_size(wc_each, lav_each):
    """(x, y) ft of one restroom for its WCs and lavs: 8 x 9 ft for one
    of each (single-user); a multi-user room about 72 SF plus 30 SF a WC
    and 10 SF a lav more (assumed - the stall layout by the design
    professional)."""
    wc_each, lav_each = max(1, int(wc_each)), max(1, int(lav_each))
    if wc_each == 1 and lav_each == 1:
        return RR_SINGLE
    a = 72.0 + 30.0 * (wc_each - 1) + 10.0 * (lav_each - 1)
    x = max(RR_SINGLE[0], float(math.ceil(math.sqrt(a * 1.3))))
    y = max(RR_SINGLE[1], float(math.ceil(a / x)))
    return x, y


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _walkin_d(gross):
    return 8.0 if gross < 4000 else 10.0 if gross < 8000 else 12.0


def _targets(gross):
    """Target SF of the back-of-house rooms that aren't the rest of a
    column (assumed shares of the gross)."""
    return {"office": _clamp(0.015 * gross, 80.0, 200.0),
            "dish": _clamp(0.035 * gross, 70.0, 300.0),
            "drive_thru": _clamp(0.03 * gross, 80.0, 250.0)}


def _back_min(gross, wa, wc, dt):
    """The least back-of-house depth: each column's rooms at their
    minimum depths."""
    tg = _targets(gross)
    a = [max(MIN_D["office"], tg["office"] / wa), MIN_D["dry_storage"]]
    if dt:
        a.insert(0, max(MIN_D["dish"], tg["dish"] / wa))
    south = "drive_thru" if dt else "dish"
    c = [max(MIN_D[south], tg[south] / wc), MIN_D["prep"],
         _walkin_d(gross)]
    return float(math.ceil(max(sum(a), sum(c))))


def footprint(gross, ratio, rr, dt):
    """(W, D) centrelines in whole 2 ft: about `ratio` wide to deep, made
    deeper (and narrower) when the dining band with its restrooms and
    the back of house don't fit."""
    from .. import model
    from ..layout import _r2
    lo, hi = TYPE.sf_range
    if not gross:
        raise model.PlanError("Enter the gross SF or the number of seats.")
    if gross < lo:
        raise model.PlanError(f"Restaurants start at {lo:,.0f} SF.")
    if gross > hi:
        raise model.PlanError(f"v1 covers restaurants up to {hi:,.0f} SF "
                              "(one story).")
    ratio = _clamp(float(ratio or RATIO), 0.8, 2.5)
    W = float(_r2(math.sqrt(gross * ratio)))
    D = float(_r2(gross / W))
    for _ in range(4):
        Wi = W - 0.5
        wa = _clamp(round(COL_A * Wi), *COL_A_RANGE)
        wc = _clamp(round(COL_C * Wi), *COL_C_RANGE)
        need = max(2 * rr[1], DINING_MIN_D) + _back_min(gross, wa, wc, dt)
        if D - 0.5 >= need - 1e-6:
            break
        D = float(_r2(need + 0.5 + 1))
        W = float(_r2(gross / (D + 0.5) - 0.5))
    W, D = min(W, TYPE.max_w), min(D, TYPE.max_d)
    if W - 0.5 < (COL_A_RANGE[0] + KITCHEN_MIN_W + COL_C_RANGE[0]):
        raise model.PlanError("The kitchen doesn't fit at this size; add "
                              "SF.")
    return W, D


# ---- the plan --------------------------------------------------------------
def _rects(W, D, gross, rr, dt, seats, warnings, assumed):
    """[(name, type, (x0, y0, x1, y1), extra)] tiling the inside of the
    building (whole-foot partitions on their centrelines)."""
    t = 0.25
    Wi, Di = W - 0.5, D - 0.5
    rx, ry = rr
    xr = float(round(W - t - rx))             # the restroom column's west
    wa = _clamp(round(COL_A * Wi), *COL_A_RANGE)
    wc = _clamp(round(COL_C * Wi), *COL_C_RANGE)
    xa = float(round(t + wa))
    xb = float(round(W - t - wc))
    if xb > xr - 4.0:                          # the kitchen meets the dining
        xb = xr - 4.0
    if xb - xa < KITCHEN_MIN_W:
        xa = max(t + COL_A_RANGE[0], xb - KITCHEN_MIN_W)
        xa = float(round(xa))
    back = _back_min(gross, xa - t, W - t - xb, dt)
    front_min = max(2 * ry, DINING_MIN_D)
    if seats:
        want = seats * SEAT_SF / max(1.0, xr - t)
    else:
        want = Di * FRONT_SHARE
    if Di - back < front_min - 1e-6:
        from .. import model
        raise model.PlanError("The dining room, restrooms and kitchen don't "
                              "fit at this size; add SF.")
    F = _clamp(want, front_min, Di - back)
    if seats and abs(F - want) > 0.05 * want:
        warnings.append(f"{seats} seats at {SEAT_SF:g} SF each "
                        f"{'need more' if F < want else 'leave room to spare'}"
                        " at this size; the dining room is drawn "
                        f"{(xr - t) * F:,.0f} SF.")
    yf = float(round(t + F))
    yb = D - t
    out = []
    # front of house: dining, and the column at the east end
    out.append(("DINING", "dining", (t, t, xr, yf)))
    # the column, north to south: JAN / ELEC (when there's room), WOMEN,
    # MEN, and WAITING at the front when there's room for it too
    left = (yf - t) - 2 * ry
    jan = wait = 0.0
    if left >= WAIT_MIN + JAN_D:
        jan, wait = JAN_D, left - JAN_D
    elif left >= 6.0:
        jan = float(math.floor(left))
    yj = yf - jan
    y_mw = yj - ry                             # women / men
    ym = float(math.floor(y_mw - ry)) if wait else t   # men / waiting
    if wait:
        out.append(("WAITING", "lobby", (xr, t, W - t, ym)))
    out.append(("MEN", "restroom", (xr, ym, W - t, y_mw)))
    out.append(("WOMEN", "restroom", (xr, y_mw, W - t, yj)))
    if jan:
        out.append(("JAN / ELEC", "mech", (xr, yj, W - t, yf)))
    # back of house, west to east
    tg = _targets(gross)
    ya = yf
    col_a = []
    if dt:
        col_a.append(("DISH", "dish", tg["dish"]))
    col_a += [("OFFICE", "office", tg["office"])]
    for name, kind, sf in col_a:
        d = float(round(max(MIN_D[kind], sf / (xa - t))))
        out.append((name, kind, (t, ya, xa, ya + d)))
        ya += d
    out.append(("DRY STORAGE", "dry_storage", (t, ya, xa, yb)))
    out.append(("KITCHEN", "kitchen_comm", (xa, yf, xb, yb)))
    wcw = W - t - xb
    south = ("DRIVE-THRU", "drive_thru") if dt else ("DISH", "dish")
    ds = float(round(max(MIN_D[south[1]], tg[south[1]] / wcw)))
    dw = _walkin_d(gross)
    yw = float(round(yb - dw))
    if yw - (yf + ds) < MIN_D["prep"]:
        ds = max(MIN_D[south[1]], float(math.floor(yw - yf -
                                                   MIN_D["prep"])))
    out.append((south[0], south[1], (xb, yf, W - t, yf + ds)))
    out.append(("PREP", "prep", (xb, yf + ds, W - t, yw)))
    xc = float(round(xb + _clamp(round(0.6 * wcw), 8.0, 20.0)))
    if W - t - xc < 6.0:
        xc = float(math.floor(W - t - 6.0))
    out.append(("WALK-IN COOLER", "walkin", (xb, yw, xc, yb)))
    out.append(("WALK-IN FREEZER", "walkin", (xc, yw, W - t, yb)))
    assumed.append(f"walk-in cooler and freezer {dw:g} ft deep (sizes by "
                   "the walk-in supplier)")
    return out, {"xr": xr, "xa": xa, "xb": xb, "xc": xc, "yf": yf,
                 "yw": yw}


def _rooms(rects, yf):
    from . import parts
    from .. import program as prog
    rooms = []
    for i, (name, kind, rc) in enumerate(rects, 1):
        r = parts.room(f"R{100 + i}", 100 + i, name, kind, rc)
        r["ceiling_ht"] = CEILING[kind]
        r["use"] = USES[kind]
        r["zone"] = "front" if rc[3] <= yf + 1e-6 else "back"
        if kind == "dining":
            fin = prog.FINISHES["sales"]          # LVT, RB, GWB-PT, ACT
            r["finishes"] = {"floor": fin[0], "base": fin[1],
                             "walls": fin[2], "ceiling": fin[3]}
        rooms.append(r)
    return rooms


def load_and_fixtures(rooms):
    """(occupant load, codecheck.fixtures for A-2) from the room areas -
    the same tables codes.py uses."""
    from ... import codecheck
    main = codecheck.MAIN_USE["A"]
    load = sum(codecheck.occupant_load(r["area"], r["use"], main)
               for r in rooms)
    return load, codecheck.fixtures(load, "A-2")


def _by(rooms, name):
    return next((r for r in rooms if r["name"] == name), None)


def _storefront(ops, room, wall_id, lo, hi, door_at=None, door_w=0.0):
    """Storefront glass along [lo, hi] of wall W1 (along = x), panes up to
    8 ft, clear of the door."""
    spans = [(lo, hi)] if door_at is None else \
        [(lo, door_at - door_w / 2 - 0.75), (door_at + door_w / 2 + 0.75,
                                             hi)]
    for a0, a1 in spans:
        L = a1 - a0
        if L < 2.0:
            continue
        k = max(1, int(math.ceil(L / SF_PANE)))
        pw = (L - 0.25 * (k - 1)) / k
        for j in range(k):
            a = a0 + j * (pw + 0.25) + pw / 2
            ops.append({"id": "", "kind": "window", "mark": "SF",
                        "type": "SF", "wall": wall_id, "along": round(a, 3),
                        "width": round(pw, 3), "height": SF_GLASS_H,
                        "sill": SF_SILL, "room": room["id"]})


def _openings(rooms, walls, pair, W, D, dt, big_entry, warnings):
    from . import parts
    wall = {w["id"]: w for w in walls}
    ops = []
    dining, wait = _by(rooms, "DINING"), _by(rooms, "WAITING")
    kitchen = _by(rooms, "KITCHEN")

    def door(frm, to, typ, width=3.0, height=7.0, want=None, swing="in"):
        w = pair.get((frm["id"], to["id"]))
        if w is None:
            warnings.append(f"{to['name']} has no wall to {frm['name']} for "
                            "a door")
            return None
        L = parts.wall_len(w)
        a = parts.place(ops, w, L / 2 if want is None else want, width)
        if a is None:
            warnings.append(f"No room for a door from {frm['name']} into "
                            f"{to['name']}")
            return None
        o = {"id": "", "kind": "door", "mark": "", "type": typ,
             "wall": w["id"], "along": a, "width": width, "height": height,
             "swing": swing, "from_room": frm["id"], "to_room": to["id"]}
        ops.append(o)
        return o

    def ext_door(room, wid, want, typ, width, height=7.0, **more):
        a = parts.place(ops, wall[wid], want, width, margin=0.5)
        if a is None:
            warnings.append(f"No room for the {room['name']} door on "
                            f"{wid}")
            return None
        o = dict({"id": "", "kind": "door", "mark": "", "type": typ,
                  "wall": wid, "along": a, "width": width, "height": height,
                  "swing": "out", "from_room": "EXT", "to_room": room["id"],
                  "exit": True}, **more)
        ops.append(o)
        return o

    # the entrance: into the waiting area when there is one, else the
    # dining room; a pair of 3'-0" leaves for a big dining room
    entry_room = wait or dining
    x0, _y0, x1, _y1 = entry_room["rect"]
    # (a pair only where there's still storefront glass beside it)
    ew = 6.0 if big_entry and x1 - x0 >= 6.0 + 2 * (0.75 + 2.0) + 2.0 \
        else 3.0
    ent = ext_door(entry_room, "W1", (x0 + x1) / 2, "SF", ew, SF_DOOR_H,
                   entrance=True)
    for r in (dining, wait):
        if r is None:
            continue
        a0, a1 = r["rect"][0] + 1.0, r["rect"][2] - 1.0
        if ent and ent["to_room"] == r["id"]:
            _storefront(ops, r, "W1", a0, a1, ent["along"], ew)
        else:
            _storefront(ops, r, "W1", a0, a1)
    # the dining room's second exit, on the west wall (never through the
    # kitchen - IBC 1016.2)
    _dx0, dy0, _dx1, dy1 = dining["rect"]
    w4 = wall["W4"]
    ext_door(dining, "W4", D - (dy0 + dy1) / 2, "A", 3.0)
    # west windows in the dining room, about one per 12 ft
    n = max(1, int((dy1 - dy0) // WINDOW_EVERY))
    ww, wh, ws = WIN_A
    for k in range(n):
        y = dy0 + (dy1 - dy0) * (k + 0.5) / n
        a = parts.place(ops, w4, D - y, ww, margin=0.5, lo=D - dy1 + 0.5,
                        hi=D - dy0 - 0.5)
        if a is not None:
            ops.append({"id": "", "kind": "window", "mark": "A",
                        "type": "A", "wall": "W4", "along": a, "width": ww,
                        "height": wh, "sill": ws, "room": dining["id"]})
    if wait:
        door(dining, wait, "O", 6.0, 7.0)
    for name in ("MEN", "WOMEN"):
        door(dining, _by(rooms, name), "B")
    # the kitchen: the dining room's service door, the receiving door,
    # every back-of-house room off it
    kx0, _ky0, kx1, _ky1 = kitchen["rect"]
    sh = pair.get((dining["id"], kitchen["id"]))
    if sh is not None:
        door(dining, kitchen, "C", want=parts.wall_len(sh) / 2)
    rw, rh = RECEIVING
    ext_door(kitchen, "W3", W - (kx0 + kx1) / 2, "R", rw, rh,
             receiving=True)
    for name, typ, width in (("OFFICE", "B", 3.0), ("DRY STORAGE", "B", 3.0),
                             ("DISH", "B", 3.0), ("DRIVE-THRU", "O", 4.0),
                             ("PREP", "O", 4.0),
                             ("WALK-IN COOLER", "W", 3.0)):
        r = _by(rooms, name)
        if r is not None:
            door(kitchen, r, typ, width)
    frz, prep = _by(rooms, "WALK-IN FREEZER"), _by(rooms, "PREP")
    if (prep["id"], frz["id"]) in pair:
        door(prep, frz, "W")
    else:
        door(_by(rooms, "WALK-IN COOLER"), frz, "W")
    jan = _by(rooms, "JAN / ELEC")
    if jan is not None:
        south = _by(rooms, "DRIVE-THRU") or _by(rooms, "DISH")
        if (south["id"], jan["id"]) in pair:
            door(south, jan, "B")
        else:
            door(dining, jan, "B")
    # the office windows (west wall): glass about 8% of the floor
    off = _by(rooms, "OFFICE")
    _ox0, oy0, _ox1, oy1 = off["rect"]
    n = max(1, int(math.ceil(0.08 * off["area"] / (ww * wh) - 1e-9)))
    for k in range(n):
        y = oy0 + (oy1 - oy0) * (k + 0.5) / n
        a = parts.place(ops, w4, D - y, ww, margin=0.5, lo=D - oy1 + 0.25,
                        hi=D - oy0 - 0.25)
        if a is not None:
            ops.append({"id": "", "kind": "window", "mark": "A",
                        "type": "A", "wall": "W4", "along": a, "width": ww,
                        "height": wh, "sill": ws, "room": off["id"]})
    # the drive-thru window, east wall (along = y)
    if dt:
        r = _by(rooms, "DRIVE-THRU")
        _x0, y0, _x1, y1 = r["rect"]
        dw_, dh_, ds_ = DT_WIN
        a = parts.place(ops, wall["W2"], (y0 + y1) / 2, dw_, margin=0.5,
                        lo=y0 + 0.25, hi=y1 - 0.25)
        if a is None:
            warnings.append("No room for the drive-thru window on the east "
                            "wall")
        else:
            ops.append({"id": "", "kind": "window", "mark": "DT",
                        "type": "DT", "wall": "W2", "along": a,
                        "width": dw_, "height": dh_, "sill": ds_,
                        "room": r["id"], "drive_thru": True})
    parts.renumber(ops)
    return ops


def make_plan(fields):
    """The restaurant plan JSON from the brief's fields."""
    from .. import DISCLAIMER, model, site as site_mod
    from .. import codes
    from . import parts
    occ = "A-2"
    warnings = list(fields.get("warnings") or [])
    assumed = []
    if int(fields.get("stories") or 1) > 1:
        warnings.append("Multi-story restaurants are a later phase; drawn "
                        "as one story.")
    if fields.get("room_sizes"):
        warnings.append("Room sizes in the brief aren't used for "
                        "restaurants; the rooms are sized as a whole.")
    seats = int(fields.get("seats") or 0)
    gross = float(fields.get("gross_sf") or 0)
    if not gross and seats:
        # the dining room about half the building (assumed)
        gross = float(round(seats * SEAT_SF / 0.5, -2))
        lo, hi = TYPE.sf_range
        if not lo <= gross <= hi:
            warnings.append(f"{seats} seats make about {gross:,.0f} SF; "
                            f"drawn at {_clamp(gross, lo, hi):,.0f} SF "
                            f"(v1 draws {lo:,.0f} - {hi:,.0f} SF).")
            gross = float(_clamp(gross, lo, hi))
    dt = bool(fields.get("drive_thru"))
    # the window's side: the brief's (east or west), else east (assumed)
    side_asked = (fields.get("drive_thru_side") or drive_thru_side(
        fields.get("brief") or "") or "") if dt else ""
    side_asked = str(side_asked).strip().upper()[:1]
    dt_side = side_asked if side_asked in ("E", "W") else "E"
    # the restrooms are sized from the occupant load, and the load from
    # the rooms: start from one WC each and settle in a few passes
    rr = RR_SINGLE
    for _try in range(4):
        for _ in range(4):
            W, D = footprint(gross, fields.get("ratio"), rr, dt)
            w_, a_ = [], []
            rects, keys = _rects(W, D, gross, rr, dt, seats, w_, a_)
            rooms = _rooms(rects, keys["yf"])
            load, fx = load_and_fixtures(rooms)
            want = restroom_size(fx["wc_each"], fx["lav_each"])
            if want == rr:
                break
            rr = want
        # sized from the seats alone: grow until the seats fit (a small
        # restaurant's kitchen is more than half of it)
        short = seats * SEAT_SF - _by(rooms, "DINING")["area"]
        if not seats or fields.get("gross_sf") or \
                short <= 0.05 * seats * SEAT_SF or gross >= TYPE.sf_range[1]:
            break
        gross = float(min(TYPE.sf_range[1],
                          round(gross + 1.3 * short + 50, -2)))
    if seats and not fields.get("gross_sf"):
        assumed.append(f"gross area {gross:,.0f} SF from {seats} seats")
    warnings += w_
    assumed += a_
    walls, pair = parts.walls_for(rooms, W, D)
    dining = _by(rooms, "DINING")
    from ... import codecheck
    dload = codecheck.occupant_load(dining["area"], dining["use"])
    openings = _openings(rooms, walls, pair, W, D, dt, dload > 200,
                         warnings)
    for r in rooms:
        if r["type"] == "restroom":
            r["fixtures"] = {"wc": fx["wc_each"], "lav": fx["lav_each"]}
    seats_drawn = int(sum(r["area"] for r in rooms if r["type"] ==
                          "dining") // SEAT_SF)
    if not seats:
        assumed.append(f"about {seats_drawn} seats (dining at {SEAT_SF:g} "
                       "SF a seat)")
    spaces = fields.get("parking")
    ratio = None
    if not spaces:
        ratio = PARKING_PER_1000
        spaces = int(math.ceil(gross / 1000.0 * ratio))
        assumed.append(f"{spaces} parking spaces ({ratio:g} per 1,000 SF - "
                       "zoning decides)")
    kitchen = _by(rooms, "KITCHEN")
    kw = kitchen["rect"][2] - kitchen["rect"][0]
    hood = float(_clamp(round(0.5 * kw), 8.0, 40.0))
    assumed += [f"restrooms sized for {fx['wc_each']} WC and "
                f"{fx['lav_each']} lav each (IPC Table 2902.1, A-2, "
                f"{load} occupants)",
                f"Type I kitchen hood about {hood:g} ft long over the cook "
                "line (by the mechanical engineer)",
                "grease interceptor outside, near the kitchen (size by the "
                "plumbing engineer and the local FOG program)",
                "storefront glass and the entrance on the street side, a "
                "second exit on the " + ("east" if dt_side == "W" else
                                         "west") +
                ", a 3'-6\" service / receiving door at the kitchen",
                f"{PLATE:g} ft to the roof bearing, {PARAPET:g} ft parapet",
                "fully sprinklered (NFPA 13)"]
    if dt and side_asked in ("E", "W"):
        assumed.append(f"a {LANE_W:g} ft drive-thru lane and {STACK} cars "
                       "of stacking (by the civil engineer)")
    elif dt:
        assumed.append(f"drive-thru window on the east wall, a "
                       f"{LANE_W:g} ft lane and {STACK} cars of stacking "
                       "(by the civil engineer)")
        if side_asked in ("N", "S"):
            warnings.append("The brief puts the drive-thru window on the "
                            + {"N": "north", "S": "south"}[side_asked] +
                            " side; v1 draws it on the east or west wall - "
                            "drawn on the east (verify).")
    plan = {
        "schema": model.SCHEMA, "units": "ft", "disclaimer": DISCLAIMER,
        "project": {
            "name": fields.get("name") or "Untitled Project",
            "address": fields.get("address") or None,
            "firm": fields.get("firm") or "[FIRM NAME]",
            "date": fields.get("date"), "building_type": TYPE.key,
            "work": fields.get("work") or "new", "occupancy": occ,
            "gross_sf_target": gross},
        "source": {"brief": fields.get("brief") or "",
                   "sketch": fields.get("sketch"),
                   "ai_used": bool(fields.get("ai_used")),
                   "ai_model": fields.get("ai_model"),
                   "kernel": "modulor", "modulor_version": None},
        "footprint": {"width": W, "depth": D,
                      "from": "sketch" if fields.get("ratio") else "brief"},
        "level": {"name": "L1", "floor_elev": 0.0, "plate_height": PLATE,
                  "slab": 0.42},
        "roof": {"type": "flat", "pitch": 0.25, "ridge_dir": None,
                 "overhang": 0, "parapet": PARAPET},
        "walls": walls, "rooms": rooms, "openings": openings,
        "door_types": {
            "SF": "Storefront entrance, aluminum and glass (assumed)",
            "A": "Exterior, insulated hollow metal",
            "R": "Service / receiving door, insulated hollow metal "
                 "(assumed)",
            "B": "Interior, solid core, 3'-0\" (ADA 32 in. clear)",
            "C": "Kitchen service door, double-acting, vision panels "
                 "(assumed)",
            "O": "Cased opening, no door (assumed)",
            "W": "Walk-in door, by the walk-in supplier (assumed)"},
        "window_types": {"SF": "Aluminum storefront glazing (assumed)",
                         "A": "3'-0\" x 4'-0\" punched window",
                         "DT": "Drive-thru pass-through window, sliding "
                               "(assumed)"},
        "notes": {"general": [], "project": [], "from_ai": False},
        "warnings": warnings,
        "restaurant": {
            "seats": seats or None, "seats_drawn": seats_drawn,
            "occupant_load": load, "fixtures": fx,
            "drive_thru": dt, "hood_lf": hood,
            "grease_interceptor": {"assumed": True,
                                   "where": "outside, near the kitchen"},
            "kitchen_rect": [keys["xa"], keys["yf"], keys["xb"], D - 0.25],
            "back_y": keys["yf"], "assumed": assumed,
            "elev_note": {"S": "Storefront and entrance on the street side "
                               "- glazing and signage by the design "
                               "professional (assumed).",
                          "N": "Service / receiving door at the kitchen; "
                               "the hood exhaust and make-up air on the "
                               "roof (assumed)."}},
    }
    plan["parking"] = parts.parking(W, spaces, ratio, gross)
    if dt:
        plan["drive_thru"] = {"side": "E", "lane_w": LANE_W,
                              "stack": STACK, "window_wall": "W2",
                              "assumed": side_asked not in ("E", "W")}
        if dt_side == "W":             # the brief's west side: mirrored
            _mirror_x(plan)
            plan["drive_thru"].update(side="W", window_wall="W4")
    plan["dropped"] = []
    # the building moves back on the lot for the parking field when it
    # has to (site_for, Oct 22); the field widens when that's not enough
    plan["site"], sw = site_mod.site_for(plan, fields.get("lot"))
    wide = site_mod.widen_parking(plan, fields.get("lot"))   # review #10
    if wide is not None:
        sw = wide
    plan["warnings"].extend(w for w in sw if w not in plan["warnings"])
    plan["code"] = codes.analyze(plan)
    model.validate(plan)
    return plan


# ---- hooks ------------------------------------------------------------------
def _reached_without(plan, start_ids, avoid):
    """Rooms reached from start_ids through doors and openings, not
    passing through rooms of the types in `avoid`."""
    from collections import deque
    by = {r["id"]: r for r in plan["rooms"]}
    adj = {r: set() for r in by}
    for o in plan["openings"]:
        a, b = o.get("from_room"), o.get("to_room")
        if o["kind"] == "door" and a in by and b in by:
            adj[a].add(b)
            adj[b].add(a)
    seen, q = set(start_ids), deque(start_ids)
    while q:
        for nb in adj[q.popleft()]:
            if nb not in seen and by[nb]["type"] not in avoid:
                seen.add(nb)
                q.append(nb)
    return seen


def dining_exits(plan):
    """Exit doors the dining room reaches without going through the
    kitchen or any back-of-house room (IBC 1016.2)."""
    dining = next(r for r in plan["rooms"] if r["type"] == "dining")
    ok = _reached_without(plan, [dining["id"]],
                          {"kitchen_comm", "prep", "dish", "drive_thru",
                           "walkin", "dry_storage", "office", "mech",
                           "restroom"})
    return [o for o in plan["openings"] if o["kind"] == "door" and
            o.get("from_room") == "EXT" and o.get("to_room") in ok]


def restroom_check(plan, fx=None):
    """(status, detail): the men's and women's rooms against IPC Table
    2902.1 for the A-2 load."""
    from ..audit import FAIL, PASS
    if fx is None:
        from .. import codes
        c = codes.analyze(plan, store=False)
        fx = next((f["fx"] for f in c["fixtures"] if f["group"] == "A-2"),
                  None)
    rr = {r["name"]: r for r in plan["rooms"] if r["type"] == "restroom"}
    if fx is None:
        return FAIL, "no A-2 row in the fixture table"
    short = []
    for name in ("MEN", "WOMEN"):
        r = rr.get(name)
        have = (r or {}).get("fixtures") or {}
        if r is None:
            short.append(f"no {name} room")
        elif have.get("wc", 0) < fx["wc_each"] or \
                have.get("lav", 0) < fx["lav_each"]:
            short.append(f"{name} {have.get('wc', 0)} WC / "
                         f"{have.get('lav', 0)} lav")
    det = (f"{fx['wc_each']} WC and {fx['lav_each']} lav per sex required"
           + ("; short: " + ", ".join(short) if short else ""))
    return (FAIL if short else PASS), det


def checks(plan):
    """Self-check lines for a restaurant (audit.py adds them)."""
    from .. import codes
    from ..audit import FAIL, PASS, WARN
    out = []
    c = codes.analyze(plan, store=False)
    fx = next((f["fx"] for f in c["fixtures"] if f["group"] == "A-2"), None)
    st, det = restroom_check(plan, fx)
    out.append((st, "Restrooms per IPC Table 2902.1 (A-2, screening)", det))
    names = {r["name"] for r in plan["rooms"]}
    out.append((PASS if {"MEN", "WOMEN"} <= names else FAIL,
                "Separate men's and women's restrooms", ""))
    dining = next(r for r in plan["rooms"] if r["type"] == "dining")
    from ... import codecheck
    dload = codecheck.occupant_load(dining["area"], dining["use"])
    ex = dining_exits(plan)
    need = 2 if dload > codecheck.one_exit_max("A-2") else 1
    out.append((PASS if len(ex) >= need else FAIL,
                "Dining exits not through the kitchen (IBC 1016.2)",
                f"{len(ex)} exits, {need} needed for {dload} occupants"))
    walls = {w["id"]: w for w in plan["walls"]}
    rec = [o for o in plan["openings"] if o.get("receiving")]
    k_ok = any(walls[o["wall"]]["kind"] == "exterior" for o in rec)
    out.append((PASS if k_ok else WARN, "Service / receiving door at the "
                "kitchen", "" if k_ok else "none drawn"))
    by = {r["id"]: r for r in plan["rooms"]}
    reach = set()
    for o in plan["openings"]:
        a, b = by.get(o.get("from_room")), by.get(o.get("to_room"))
        if a and b and b["type"] == "walkin" and \
                a["type"] in ("kitchen_comm", "prep", "walkin"):
            reach.add(b["name"])
    lost = sorted({r["name"] for r in plan["rooms"]
                   if r["type"] == "walkin"} - reach)
    out.append((FAIL if lost else PASS, "Walk-ins open off the kitchen or "
                "prep", ", ".join(lost)))
    if (plan.get("restaurant") or {}).get("drive_thru"):
        dtw = [o for o in plan["openings"] if o.get("drive_thru")]
        good = dtw and all(walls[o["wall"]]["kind"] == "exterior"
                           for o in dtw)
        out.append((PASS if good else FAIL, "Drive-thru window on an "
                    "exterior wall", "" if good else "none drawn"))
    asm = " ".join((plan.get("restaurant") or {}).get("assumed") or [])
    noted = "hood" in asm and "grease interceptor" in asm
    out.append((PASS if noted else WARN, "Kitchen hood and grease "
                "interceptor noted as assumed", ""))
    e = c["exits"]
    out.append((PASS if e["have"] >= e["need"] else WARN,
                "Exits for the occupant load (screening)",
                f"{e['have']} exit doors, {e['need']} needed for "
                f"{e['load']} occupants"))
    tr = c["travel"]
    over = tr["limit"] is not None and tr["max_ft"] > tr["limit"]
    out.append((WARN if over or tr["limit"] is None else PASS,
                "Exit access travel distance (approximate)",
                f"{tr['max_ft']:.0f} ft rectilinear, limit "
                f"{tr['limit'] if tr['limit'] is not None else 'n/a'} ft"
                if over or tr["limit"] is None else ""))
    pk = plan.get("parking")
    s = plan.get("site") or {}
    if pk and s:
        room = s["provided"]["front"]
        from . import parts
        ok = parts.field_fits(plan)
        out.append((PASS if ok else WARN,
                    "Parking field fits in front",
                    "" if ok else
                    f"{room:.0f} ft in front, {pk['depth']:.0f} ft field"))
    return out


def validate(plan):
    from .. import model
    kinds = {r["type"] for r in plan["rooms"]}
    for k in ("dining", "kitchen_comm", "restroom"):
        if k not in kinds:
            raise model.PlanError(f"a restaurant plan needs a {k} room")
    return []


def _dt_side(plan):
    """'east' or 'west': the wall the pick-up window is on (east unless
    the brief named the west side or an edited plan moved it)."""
    return "west" if (plan.get("drive_thru") or {}).get("side") == "W" \
        else "east"


def notes(plan):
    rs = plan.get("restaurant") or {}
    out = ["One-story restaurant (A-2) on a slab on grade: dining room, "
           "restrooms and waiting at the front; kitchen, prep, dish, "
           "walk-ins, dry storage and office behind."
           + (f" Drive-thru window on the {_dt_side(plan)} side."
              if rs.get("drive_thru") else ""),
           "Kitchen equipment, the Type I hood, grease duct and its fire "
           "suppression by the food service consultant and the mechanical "
           "engineer; hood shown as an allowance only.",
           "Grease interceptor, floor sinks and indirect waste by the "
           "plumbing engineer; size per the local FOG program.",
           "Kitchen finishes (floors, walls and ceilings) to meet the "
           "local health department's rules; submit the plans for its "
           "review.",
           "Restroom fixture counts are a screening from IPC Table 2902.1; "
           "the design professional confirms them (urinals, drinking "
           "fountain and service sink included).",
           "Structural, MEP and fire protection design by others. Fire sprinklers "
           "and fire alarm by the fire protection engineer.",
           "Code summary on the code sheet is a screening only; code "
           "analysis by the design professional."]
    if rs.get("assumed"):
        out.append("ASSUMED (not in the brief - verify): " +
                   "; ".join(rs["assumed"]) + ".")
    return out


def cover(plan, rows):
    from ..model import fmt_ftin
    rs = plan.get("restaurant") or {}
    pk = plan.get("parking")
    fx = rs.get("fixtures") or {}
    out = []
    for k, v in rows:
        if k in ("Garage", "Porch / deck"):
            continue
        if k == "Construction type":
            v = "by design professional"
        elif k == "Code analysis":
            v = "screening on G-003 - by design professional"
        out.append([k, v])
        if k == "Stories":
            out += [["Seats", (f"{rs['seats']} (brief)" if rs.get("seats")
                               else f"about {rs.get('seats_drawn', 0)} "
                               f"(assumed, {SEAT_SF:g} SF a seat)")],
                    ["Occupant load (screening)",
                     f"{rs.get('occupant_load', 0)} - restrooms "
                     f"{fx.get('wc_each', 0)} WC / {fx.get('lav_each', 0)} "
                     "lav per sex (assumed from IPC 2902.1)"],
                    ["Drive-thru", f"yes - {_dt_side(plan)} side" + (
                        " (assumed)" if (plan.get("drive_thru") or {}).get(
                            "assumed", True) else " (brief)")
                     if rs.get("drive_thru") else "none"],
                    ["Kitchen hood", f"Type I, about "
                     f"{fmt_ftin(rs.get('hood_lf', 0))} (assumed)"],
                    ["Parking", (f"{pk['spaces']} spaces" + (
                        f" ({pk['ratio']:g} / 1,000 SF assumed)"
                        if pk.get("ratio") else "") +
                        f", {pk['accessible']} accessible") if pk else
                     "not drawn"]]
    return out


def quantities(plan):
    from . import parts
    from .. import quantities as q
    out = parts.base_quantities(plan)

    def add(group, item, qty, unit, how=""):
        if qty:
            out.append((group, item, qty, unit, how))
    G = q.GROUPS
    rs = plan["restaurant"]
    glass = sum(o["width"] * o["height"] for o in plan["openings"]
                if o["kind"] == "window" and o["type"] == "SF")
    add(G[2], "Storefront glazing", q._r(glass), "SF", "the storefront "
        "openings, frames not deducted")
    walk = [r for r in plan["rooms"] if r["type"] == "walkin"]
    for r in walk:
        add("Food service (allowances)", f"{r['name'].title()} (by the "
            "walk-in supplier, assumed)", q._r(r["area"]), "SF",
            "the room on the plan")
    add("Food service (allowances)", "Type I kitchen hood (assumed)",
        rs["hood_lf"], "LF", "about half the kitchen's width - by the "
        "mechanical engineer")
    add("Food service (allowances)", "Hood fire suppression system "
        "(assumed)", 1, "EA", "by the hood supplier")
    add("Food service (allowances)", "Grease interceptor (assumed)", 1,
        "EA", "size by the plumbing engineer / local FOG program")
    fx = rs["fixtures"]
    add("Plumbing fixtures (screening)", "Water closets (IPC 2902.1, A-2)",
        fx["wc"], "EA", f"{fx['wc_each']} per sex at {rs['occupant_load']} "
        "occupants; urinals may stand in for some men's")
    add("Plumbing fixtures (screening)", "Lavatories", fx["lav"], "EA",
        f"{fx['lav_each']} per sex")
    add("Plumbing fixtures (screening)", "Service sink", fx["service_sink"],
        "EA", "in the JAN / ELEC room (or the dish room)")
    pk = plan.get("parking")
    W = plan["footprint"]["width"]
    if pk:
        add(G[0], f"Parking stalls ({pk['spaces']})", pk["spaces"], "EA",
            f"of them {pk['accessible']} accessible, {pk['van']} van")
        add(G[0], "Parking field paving (assumed layout)",
            q._r(parts.field_width(pk, W) * (pk["depth"] - parts.WALK)),
            "SF", parts.field_words(pk, "the building's width x the parking rows"))
        add(G[0], "Front walk", q._r((W + 0.5) * parts.WALK), "SF",
            f"{parts.WALK:g} ft wide, the building's width")
    from .. import site as _site
    sq = _site.site_quantities(plan)
    dt = plan.get("drive_thru")
    if dt and sq.get("lane_sf"):
        add(G[0], "Drive-thru lane paving (assumed)", q._r(sq["lane_sf"]),
            "SF", f"{dt['lane_w']:g} ft x {sq['lane_lf']:.0f} ft of lane "
            "round the building as drawn on AS-101; final layout by the "
            "civil engineer")
    elif dt:
        D = plan["footprint"]["depth"]
        add(G[0], "Drive-thru lane paving (assumed)",
            q._r(dt["lane_w"] * (D + 0.5)), "SF",
            f"{dt['lane_w']:g} ft x the building's depth; stacking beyond "
            "by the civil engineer")
    if sq.get("walk_sf"):
        add(G[0], "Side and service walks (assumed)", q._r(sq["walk_sf"]),
            "SF", "the 5 ft walks drawn on AS-101")
    return out


def kitchen_subplan(plan):
    """A-102: the back of house (kitchen, prep, dish, walk-ins, storage,
    office) as a plan of its own (parts.part_plan)."""
    from . import parts
    W, D = plan["footprint"]["width"], plan["footprint"]["depth"]
    y = plan["restaurant"]["back_y"]
    rooms = [r for r in plan["rooms"] if r.get("zone") == "back"]
    return parts.part_plan(plan, (0.0, y, W, D), rooms)


def sheets(plan):
    from .. import sheets as S
    from . import parts
    out = [S.SheetSpec("G-001", "Cover", S.cover),
           S.SheetSpec("G-002", "General Notes", S.general_notes),
           S.SheetSpec("G-003", "Code Summary", S.code_summary),
           S.SheetSpec("AS-101", "Site Plan", S.site_plan, nts=False),
           S.SheetSpec("A-101", "Floor Plan", S.level_plan(0, "Floor Plan"),
                       nts=False),
           S.SheetSpec("A-102", "Enlarged Kitchen Plan",
                       parts.part_sheet(
                           kitchen_subplan, "Enlarged Kitchen Plan",
                           "Back of house. Dimensions to the outside face "
                           "of the exterior walls and the centreline of "
                           "the partition to the dining room. Equipment "
                           "by the food service consultant (not shown)."),
                       nts=False),
           S.SheetSpec("A-103", "Roof Plan", S.roof_plan, nts=False)]
    out += S.elevation_sheets(plan)
    out += [S.SheetSpec("A-301", "Building Section", S.section, nts=False),
            S.SheetSpec("A-601", "Room Schedule", S.room_schedule),
            S.SheetSpec("A-602", "Door & Window Schedules", S.door_window),
            S.SheetSpec("A-701", "Quantity Summary", S.quantity_sheet),
            S.SheetSpec("A-801", "Accessibility", S.accessibility)]
    return out


def scoping(plan, proj):
    """A-801: the dining seats (5% accessible, 226.1), a sales / service
    counter, the restrooms with their fixtures and the parking."""
    rs = plan["restaurant"]
    proj = dict(proj)
    proj["dining_seats"] = rs.get("seats") or rs.get("seats_drawn")
    proj["counter_types"] = 2 if rs.get("drive_thru") else 1
    proj["toilet_rooms"] = [
        {"name": r["name"],
         "water_closets": (r.get("fixtures") or {}).get("wc", 1),
         "lavatories": (r.get("fixtures") or {}).get("lav", 1)}
        for r in plan["rooms"] if r["type"] == "restroom"]
    proj["single_user_toilets_cluster"] = 0
    pk = plan.get("parking")
    if pk:
        proj["parking"] = [{"name": "Parking", "total": pk["spaces"]}]
    return proj


def code_lines(plan, c):
    fx = next((f["fx"] for f in c["fixtures"] if f["group"] == "A-2"), None)
    rr = [r for r in plan["rooms"] if r["type"] == "restroom"]
    have = ", ".join(f"{r['name']} {(r.get('fixtures') or {}).get('wc', 0)}"
                     f" WC / {(r.get('fixtures') or {}).get('lav', 0)} lav"
                     for r in rr)
    ex = dining_exits(plan)
    return [["Restrooms per sex (IPC 2902.1, A-2)",
             f"{fx['wc_each']} WC, {fx['lav_each']} lav each" if fx else
             "UNVERIFIED", have],
            ["Dining exits (IBC 1016.2, not through the kitchen)",
             "2 where the dining load > 49", f"{len(ex)} drawn"],
            ["Kitchen hood / grease interceptor",
             "UNVERIFIED - IMC 507, NFPA 96, IPC 1003",
             "assumed allowances - by the MEP engineers"]]


TYPE = BuildingType(
    key="restaurant", label="Restaurant (stand-alone)",
    occupancies=("A-2",), default_occ="A-2",
    sf_range=(2000, 12000), stories_range=(1, 1), ratio=RATIO,
    plate_height=PLATE, floor_to_floor=PLATE, ceiling_ht=10.0,
    ext_wall="By design professional",
    roof_default={"type": "flat", "pitch": 0.25, "overhang": 0,
                  "parapet": PARAPET},
    setbacks={"front": 20.0, "side": 15.0, "rear": 20.0},
    ada_use="restaurant", patterns=PATTERNS, detect=detect, read=read,
    max_w=160.0, max_d=110.0, cover_label="Restaurant (stand-alone)",
    code_sheet=True,
    needs=(("dining", "kitchen_comm", "restroom"),
           "Has dining, a kitchen and restrooms"),
    layout=make_plan, checks=checks, sheets=sheets, notes=notes,
    quantities=quantities, validate=validate, cover=cover, scoping=scoping,
    code_lines=code_lines)
