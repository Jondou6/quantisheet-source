"""Warehouse / industrial building: S-1 (storage, distribution) or F-1
(manufacturing), one story, 3,000 - 200,000 SF.

Rules (Claude, Oct 20 - for Jon to confirm; every default below is an
assumption and the set says so):
  * Footprint about 2:1 (the dock wall the long side, to the north; the
    street and the office front to the south), 2 ft increments, up to
    900 x 600 ft.
  * Structural grid about 50 x 50 ft with a 60 ft speed bay at the dock
    wall (grid.py), lines on the exterior wall centrelines.
  * Office front in the south-west corner, about 7% of the gross (at
    least 900 SF, at most a quarter): lobby (the entrance), open office,
    two offices, break room, two restrooms, IT / electrical and the fire
    riser room, zoned like the small-commercial plan (a 5 ft hall). The
    rest is one warehouse (S-1) or manufacturing (F-1) space - two
    rectangles around the office with an open wall between them.
  * Dock doors 9 x 10 ft at 12 ft on centre on the north (truck court)
    wall, about one per 7,500 SF unless the brief gives a count; one
    12 x 14 ft drive-in door at the east end (two from 50,000 SF, the
    second at the west end), in the speed bay. Man doors (exits) about
    every 100 ft along the walls of the warehouse.
  * Tilt-up concrete: 32 ft clear, 4 ft of roof structure, a low-slope
    roof (1/4:12) inside a 4 ft parapet. Pre-engineered metal building
    (PEMB): 24 ft clear, 3 ft of structure, a 1:12 gable roof, ridge
    east-west.
  * Truck court 130 ft deep behind the dock wall; dock-high floor (the
    truck court 4 ft below the floor).
"""
import math
import re

from .base import BuildingType

BAY, SPEED_BAY = 50.0, 60.0
OFFICE_SHARE, OFFICE_MIN, OFFICE_MAX_SHARE = 0.07, 900.0, 0.25
SF_PER_DOCK = 7500.0
DOCK = (9.0, 10.0)              # w, h ft
DRIVE_IN = (12.0, 14.0)
DOCK_OC = 12.0
END_CLEAR = 20.0                # ft of dock wall kept clear at each end
MAN_DOOR_EVERY = 100.0
CLEAR = {"tilt-up": 32.0, "pemb": 24.0}
STRUCTURE = {"tilt-up": 4.0, "pemb": 3.0}
PARAPET = 4.0
PEMB_PITCH = 1.0
TRUCK_COURT = 130.0
DOCK_HEIGHT = 4.0
SLAB_FT = 7.0 / 12               # 7 in. slab on grade
CONSTRUCTION = {"tilt-up": "Tilt-up concrete wall panels",
                "pemb": "Pre-engineered metal building (PEMB)"}

PATTERNS = (r"\bwarehous\w*", r"\bdistribution\b", r"\bindustrial\b",
            r"\bmanufactur\w*", r"\bfulfil+ment\b", r"\blogistics\b",
            r"\bcross[- ]?dock\w*", r"\bflex[- ]space\b",
            r"\btilt[- ]?up\b", r"\bpemb\b", r"\bmetal building\b",
            r"\b\d+\s*dock(?:[- ]high)?\s*doors?\b",
            r"\b\d+\s*drive[- ]?ins?\b",
            r"\b\d{2}\s*(?:'|ft\.?|feet|foot)?\s*clear\b",
            r"\bmachine shop\b")
# construction words alone: a warehouse unless another type's words are
# in the brief too (a "tilt-up strip center", a "PEMB restaurant")
WEAK = (r"\btilt[- ]?up\b", r"\bpemb\b", r"\bmetal building\b",
        r"\b\d{2}\s*(?:'|ft\.?|feet|foot)?\s*clear\b")
OCC_RULES = ((r"\bmanufactur\w*|\bmachine shop\b|\bfabricat\w*|"
              r"\bproduction\b", "F-1"),
             (r"\bwarehous\w*|\bdistribution\b|\bstorage\b|\bfulfil+ment\b|"
              r"\blogistics\b|\bcross[- ]?dock", "S-1"),
             (r"\bindustrial\b", "F-1"))

# (name, type, share of the office, fixed SF or None). The first is the
# band along the front: it is laid out as one room and then split into
# the LOBBY (the entrance, west) and the OPEN OFFICE (east)
OFFICE_PROGRAM = [("LOBBY", "lobby", 0.48, None),
                  ("BREAK ROOM", "break", 0.13, None),
                  ("OFFICE 1", "office", 0.09, None),
                  ("OFFICE 2", "office", 0.09, None),
                  ("RESTROOM 1", "restroom", 0.06, None),
                  ("RESTROOM 2", "restroom", 0.06, None),
                  ("IT / ELEC", "mech", 0.05, None),
                  ("FIRE RISER", "riser", 0.0, 120.0)]
LOBBY_SHARE = 0.14              # of the office; the open office the rest
DROP_ORDER = ("OFFICE 2", "BREAK ROOM", "OFFICE 1", "IT / ELEC")
MIN_ROOM_SF = {"office": 80.0, "break": 80.0, "lobby": 150.0,
               "restroom": 48.0, "mech": 40.0, "riser": 60.0}


# ---- the brief ------------------------------------------------------------
_N = r"(\d[\d,]*)"
_DOCKS = re.compile(r"\b(\d+)\s*(?:truck\s+|loading\s+)?dock(?:[- ]high)?"
                    r"\s*(?:doors?|positions?|bays?)?\b", re.I)
_DRIVE = re.compile(r"\b(\d+)\s*(?:drive[- ]?ins?|grade[- ]level)\b", re.I)
_CLEAR = re.compile(r"\b(\d{2})\s*(?:'|ft\.?|feet|foot)?\s*clear\b", re.I)
_OFFICE = [re.compile(_N + r"\s*(?:sf|s\.f\.|sq\.?\s*ft|square\s*feet)\s+"
                      r"(?:of\s+)?(?:office|offices)\b", re.I),
           re.compile(r"\boffices?\s*(?:of|:|-|=|area)?\s*" + _N +
                      r"\s*(?:sf|s\.f\.|sq\.?\s*ft|square\s*feet)", re.I)]
_OFFICE_PCT = re.compile(r"\b(\d{1,2})\s*%\s*office", re.I)
_PARKING = re.compile(r"\b(\d+)\s*(?:car\s+)?(?:parking\s+(?:spaces|stalls)|"
                      r"parking)\b", re.I)


def read(text):
    """The warehouse fields a brief may give: docks, drive_ins, clear_ht,
    construction, office_sf / office_pct, parking."""
    t = text or ""
    out = {}
    m = _DOCKS.search(t)
    if m and 0 < int(m.group(1)) <= 200:
        out["docks"] = int(m.group(1))
    m = _DRIVE.search(t)
    if m and 0 < int(m.group(1)) <= 20:
        out["drive_ins"] = int(m.group(1))
    m = _CLEAR.search(t)
    if m and 14 <= int(m.group(1)) <= 60:
        out["clear_ht"] = float(m.group(1))
    if re.search(r"\bpemb\b|pre[- ]?engineered|metal building|steel "
                 r"building|butler", t, re.I):
        out["construction"] = "pemb"
    elif re.search(r"\btilt[- ]?(?:up|wall)\b|concrete tilt", t, re.I):
        out["construction"] = "tilt-up"
    for rx in _OFFICE:
        m = rx.search(t)
        if m:
            v = float(m.group(1).replace(",", ""))
            if v >= 100:
                out["office_sf"] = v
                break
    m = _OFFICE_PCT.search(t)
    if m and "office_sf" not in out and 1 <= int(m.group(1)) <= 50:
        out["office_pct"] = int(m.group(1)) / 100.0
    m = _PARKING.search(t)
    if m and 0 < int(m.group(1)) <= 5000:
        out["parking"] = int(m.group(1))
    return out


# ---- the plan --------------------------------------------------------------
def footprint(gross, ratio=None):
    """(W, D) in whole 2 ft, about `ratio` (2:1) wide to deep."""
    from .. import model
    from ..layout import _r2
    lo, hi = TYPE.sf_range
    if not gross:
        raise model.PlanError("Enter the gross SF (a sketch gives the "
                              "shape only).")
    if gross < lo:
        raise model.PlanError(f"Warehouses start at {lo:,.0f} SF.")
    if gross > hi:
        raise model.PlanError(f"v1 covers warehouses up to {hi:,.0f} SF "
                              "(one story).")
    ratio = max(1.0, min(3.0, float(ratio or TYPE.ratio)))
    w = _r2(math.sqrt(gross * ratio))
    d = _r2(gross / w)
    if w > TYPE.max_w:
        w = TYPE.max_w
        d = _r2(gross / w)
    if d > TYPE.max_d:
        d = TYPE.max_d
    return _on_grid(float(w), float(d))


def _on_grid(w, d):
    """Nudge the footprint so the bays come out in whole feet: the width
    a whole number of equal bays near BAY, the depth a speed bay plus
    equal bays (each at most half a foot per bay off)."""
    nx = max(1, int(round(w / BAY)))
    w = nx * float(round(w / nx))
    if d - SPEED_BAY >= 0.8 * BAY:
        ny = max(1, int(round((d - SPEED_BAY) / BAY)))
        d = SPEED_BAY + ny * float(round((d - SPEED_BAY) / ny))
    else:
        ny = max(1, int(round(d / BAY)))
        d = ny * float(round(d / ny))
    return float(min(w, TYPE.max_w)), float(min(d, TYPE.max_d))


def _office_sf(fields, gross):
    if fields.get("office_sf"):
        sf = float(fields["office_sf"])
    elif fields.get("office_pct"):
        sf = gross * float(fields["office_pct"])
    else:
        sf = max(OFFICE_MIN, gross * OFFICE_SHARE)
    return max(400.0, min(sf, gross * OFFICE_MAX_SHARE))


def _office_rooms(gross):
    """The office program: [{name, type, share, fixed}]."""
    rooms = []
    for name, kind, share, sf in OFFICE_PROGRAM:
        if kind == "mech":
            sf = max(100.0, min(400.0, 0.002 * gross))
        rooms.append({"name": name, "type": kind, "share": share,
                      "fixed": sf})
    return rooms


def _split_front(placed, office_sf):
    """The front band (placed[0]) split into LOBBY and OPEN OFFICE when
    both come out a fair size; else it stays one LOBBY."""
    hub, (x0, y0, x1, y1) = placed[0]
    d = y1 - y0
    want = LOBBY_SHARE * office_sf
    xs = float(round(x0 + max(10.0, want / d)))
    if x1 - xs < 12.0 or d < 8.0:
        return placed
    lobby = dict(hub, target_sf=round((xs - x0) * d, 1))
    oo = {"name": "OPEN OFFICE", "type": "open_office", "share": 0,
          "target_sf": round((x1 - xs) * d, 1)}
    return [(lobby, (x0, y0, xs, y1)), (oo, (xs, y0, x1, y1))] + placed[1:]


def _place_office(office, gross, warnings):
    """[(room, rect)] for the office block (inner rect `office`), the
    lobby first; rooms that can't fit at a useful size are left out, the
    least needed first."""
    from ..layout import MIN_W, _zoned_any
    x0, y0, x1, y1 = office
    t = x0
    net = (x1 - x0) * (y1 - y0)
    rooms = _office_rooms(gross)
    dropped = []
    while True:
        fixed = sum(r["fixed"] or 0.0 for r in rooms)
        shares = sum(r["share"] for r in rooms if not r["fixed"]) or 1.0
        rest = max(net * 0.5, net - fixed)
        order = []
        for r in rooms:
            sf = r["fixed"] or rest * r["share"] / shares
            order.append({"name": r["name"], "type": r["type"],
                          "share": r["share"], "target_sf": round(sf, 1)})
        # the block as a building of its own: its inner rect is `office`
        placed = _zoned_any(order, x1 + t, y1 + t, t)
        if placed is not None:
            placed = _split_front(placed, net)
            small = [r for r, rc in placed
                     if min(rc[2] - rc[0], rc[3] - rc[1]) <
                     MIN_W.get(r["type"], 3.0) - 1e-6 or
                     (rc[2] - rc[0]) * (rc[3] - rc[1]) <
                     MIN_ROOM_SF.get(r["type"], 0.0)]
            if not small:
                break
        gone = next((n for n in DROP_ORDER
                     if any(r["name"] == n for r in rooms)), None)
        if gone is None:
            if placed is not None:
                break                         # small, but everything fits
            from .. import model
            raise model.PlanError("The office front doesn't fit at this "
                                  "size; add SF.")
        rooms = [r for r in rooms if r["name"] != gone]
        dropped.append(gone)
    if dropped:
        warnings.append("Office front too small for all its rooms, left "
                        "out: " + ", ".join(dropped))
    for r, rc in placed:
        r["zone"] = "office"
    return placed, dropped


def _bay_names(occ):
    return ("MANUFACTURING", "industrial") if occ == "F-1" else \
        ("WAREHOUSE", "warehouse")


def _room_use(r, occ):
    """The IBC Table 1004.5 function (app/codecheck.py USES key)."""
    from ... import codecheck
    fixed = {"warehouse": "warehouse", "industrial": "industrial",
             "riser": "storage_mech", "mech": "storage_mech",
             "restroom": "support", "hall": "support", "lobby": "business",
             "open_office": "business", "office": "business"}
    if r["type"] in fixed:
        return fixed[r["type"]]
    return codecheck.guess_use(r["name"], "B" if r.get("zone") == "office"
                               else occ)


def _wall_point(w, along):
    (ax, ay), (bx, by) = w["a"], w["b"]
    L = math.hypot(bx - ax, by - ay) or 1
    return ax + (bx - ax) * along / L, ay + (by - ay) * along / L


def _room_at(rooms, x, y, zone=None):
    t = 0.26
    for r in rooms:
        x0, y0, x1, y1 = r["rect"]
        if zone and r.get("zone") != zone:
            continue
        if x0 - t <= x <= x1 + t and y0 - t <= y <= y1 + t:
            return r
    return None


def _exterior_openings(plan_rooms, walls, openings, W, D, fields, gross,
                       office, warnings):
    """Dock doors, drive-ins and man doors on the warehouse's outside
    walls. Returns (docks, drive_ins) as placed."""
    from ..layout import _fits
    wall = {w["id"]: w for w in walls}
    occupied = [(o["wall"], o["along"] - o["width"] / 2,
                 o["along"] + o["width"] / 2) for o in openings]
    bay_rooms = [r for r in plan_rooms if r.get("zone") == "bay"]

    def room_for(wid, along):
        x, y = _wall_point(wall[wid], along)
        r = _room_at(bay_rooms, x, y)
        return r

    def put(o):
        openings.append(o)
        occupied.append((o["wall"], o["along"] - o["width"] / 2,
                         o["along"] + o["width"] / 2))

    # dock doors: the north wall, centred, 12 ft on centre
    want = fields.get("docks")
    n = int(want) if want else max(1, int(round(gross / SF_PER_DOCK)))
    dw, dh = DOCK
    room_len = W - 2 * END_CLEAR
    fit = max(0, int((room_len - dw) // DOCK_OC) + 1) if room_len >= dw \
        else 0
    if n > fit:
        warnings.append(f"Only {fit} dock doors fit on the {W:g} ft dock "
                        f"wall at {DOCK_OC:g} ft on centre (asked {n}).")
        n = fit
    docks = 0
    if n:
        run = (n - 1) * DOCK_OC
        start = W / 2 - run / 2                        # along W3 (from east)
        for k in range(n):
            a = round(start + k * DOCK_OC, 3)
            r = room_for("W3", a)
            if r is None or not _fits(occupied, "W3", a - dw / 2,
                                      a + dw / 2):
                continue
            docks += 1
            put({"id": f"OH{docks}", "kind": "overhead", "mark": f"OH{docks}",
                 "type": "OH-D", "wall": "W3", "along": a, "width": dw,
                 "height": dh, "room": r["id"], "dock": True})
    # drive-ins: in the speed bay, east end first, then west
    want = fields.get("drive_ins")
    nd = int(want) if want else (2 if gross >= 50000 else 1)
    iw, ih = DRIVE_IN
    y = D - min(SPEED_BAY / 2, D / 2)
    spots = [("W2", y), ("W4", D - y), ("W2", y - (iw + 6)),
             ("W4", D - y + iw + 6)]
    placed_di = 0
    for wid, a in spots:
        if placed_di >= nd:
            break
        L = math.hypot(wall[wid]["b"][0] - wall[wid]["a"][0],
                       wall[wid]["b"][1] - wall[wid]["a"][1])
        if a - iw / 2 < 1.0 or a + iw / 2 > L - 1.0:
            continue
        r = room_for(wid, a)
        if r is None or not _fits(occupied, wid, a - iw / 2, a + iw / 2,
                                  margin=1.0):
            continue
        placed_di += 1
        k = docks + placed_di
        put({"id": f"OH{k}", "kind": "overhead", "mark": f"OH{k}",
             "type": "OH-DI", "wall": wid, "along": round(a, 3),
             "width": iw, "height": ih, "room": r["id"]})
    if placed_di < nd:
        warnings.append(f"{nd - placed_di} drive-in door(s) didn't fit and "
                        "were left out.")
    # man doors (exits) along the warehouse walls, about every 100 ft
    xo = office[2]
    od = office[3]
    cand = []
    n_s = max(1, int(math.ceil((W - xo) / MAN_DOOR_EVERY)))
    for k in range(n_s):                      # south, east of the office
        x = W - 12 - k * (W - xo - 24) / max(1, n_s - 1) if n_s > 1 \
            else (xo + W) / 2
        cand.append(("W1", x))
    n_e = max(1, int(math.ceil(D / MAN_DOOR_EVERY)))
    for k in range(n_e):                      # east
        y_ = 12 + k * (D - 24) / max(1, n_e - 1) if n_e > 1 else D / 2
        cand.append(("W2", y_))
    if D - od > 30:                           # west, behind the office
        n_w = max(1, int(math.ceil((D - od) / MAN_DOOR_EVERY)))
        for k in range(n_w):
            y_ = D - 12 - k * (D - od - 24) / max(1, n_w - 1) if n_w > 1 \
                else (od + D) / 2
            cand.append(("W4", D - y_))
    cand += [("W3", 10.0), ("W3", W - 10.0)]  # each end of the dock run
    ndoor = sum(o["kind"] == "door" for o in openings)
    nid = max([int(o["id"][1:]) for o in openings
               if re.fullmatch(r"D\d+", o["id"])] + [len(openings)])
    mw, mh = 3.0, 6.667
    for wid, a in cand:
        L = math.hypot(wall[wid]["b"][0] - wall[wid]["a"][0],
                       wall[wid]["b"][1] - wall[wid]["a"][1])
        for shift in (0.0, 4.0, -4.0, 8.0, -8.0, 14.0, -14.0):
            aa = round(a + shift, 3)
            if aa - mw / 2 < 1.0 or aa + mw / 2 > L - 1.0:
                continue
            r = room_for(wid, aa)
            if r is None or not _fits(occupied, wid, aa - mw / 2,
                                      aa + mw / 2, margin=1.0):
                continue
            ndoor += 1
            nid += 1
            put({"id": f"D{nid}", "kind": "door",
                 "mark": str(100 + ndoor), "type": "A", "wall": wid,
                 "along": aa, "width": mw, "height": mh,
                 "swing": "out", "from_room": "EXT", "to_room": r["id"],
                 "exit": True})
            break
    return docks, placed_di


def make_plan(fields):
    """The warehouse plan JSON from the brief's fields."""
    from .. import DISCLAIMER, model, site as site_mod
    from .. import bays, codes, grid as grid_mod
    from ..layout import EXT_T, build_level
    occ = fields.get("occupancy")
    if occ not in TYPE.occupancies:
        occ = TYPE.default_occ
    gross = float(fields.get("gross_sf") or 0)
    warnings = list(fields.get("warnings") or [])
    assumed = []
    if int(fields.get("stories") or 1) > 1:
        warnings.append("Multi-story warehouses (and mezzanines) are a "
                        "later phase; drawn as one story.")
    if fields.get("room_sizes"):
        warnings.append("Room sizes in the brief aren't used for "
                        "warehouses; the office is sized as a whole.")
    W, D = footprint(gross, fields.get("ratio"))
    t = EXT_T / 2
    cons = fields.get("construction")
    if cons not in CONSTRUCTION:
        cons = "tilt-up"
        assumed.append("tilt-up concrete construction")
    clear = float(fields.get("clear_ht") or 0)
    if not clear:
        clear = CLEAR[cons]
        assumed.append(f"{clear:g} ft clear height")
    eave = clear + STRUCTURE[cons]
    grid = grid_mod.make_grid(W, D, BAY, SPEED_BAY)
    assumed.append(grid_mod.describe(grid).replace("'-0\"", " ft"))
    office_sf = _office_sf(fields, gross)
    if not (fields.get("office_sf") or fields.get("office_pct")):
        assumed.append(f"office about {office_sf / gross:.0%} of the gross")
    office, bay, annex = bays.office_and_bay(W, D, office_sf, "W")
    placed, _dropped = _place_office(office, gross, warnings)
    name, kind = _bay_names(occ)
    main = {"name": name, "type": kind, "share": 0,
            "target_sf": round((bay[2] - bay[0]) * (bay[3] - bay[1]), 1),
            "zone": "bay"}
    placed.append((main, bay))
    if annex:
        placed.append(({"name": name + " (CONT.)", "type": kind, "share": 0,
                        "target_sf": round((annex[2] - annex[0]) *
                                           (annex[3] - annex[1]), 1),
                        "zone": "bay"}, annex))
    zones = [r.get("zone") for r, _rc in placed]
    rooms, walls, openings = build_level(placed, W, D, "warehouse", warnings)
    for r, z in zip(rooms, zones):
        r["zone"] = z
        if z == "bay":
            r["ceiling_ht"] = clear
            r["target_sf"] = r["area"]
        r["use"] = _room_use(r, occ)
    # the two warehouse rectangles are one space: no partition between
    if annex:
        a_id, b_id = rooms[-2]["id"], rooms[-1]["id"]
        for w in walls:
            if w["kind"] != "interior":
                continue
            ra = _room_at([rooms[-2]], *w["a"]) and \
                _room_at([rooms[-2]], *w["b"])
            rb = _room_at([rooms[-1]], *w["a"]) and \
                _room_at([rooms[-1]], *w["b"])
            if ra and rb:
                w.update(kind="open", thickness=0.0, rooms=[a_id, b_id])
                openings[:] = [o for o in openings if o["wall"] != w["id"]]
    _renumber_doors(openings)
    docks, drive_ins = _exterior_openings(rooms, walls, openings, W, D,
                                          fields, gross, office, warnings)
    if not fields.get("docks"):
        assumed.append(f"{docks} dock doors (about one per "
                       f"{SF_PER_DOCK:,.0f} SF)")
    if not fields.get("drive_ins"):
        assumed.append(f"{drive_ins} drive-in door(s)")
    assumed += ["9 x 10 ft dock doors at 12 ft on centre, 12 x 14 ft "
                "drive-ins", f"{TRUCK_COURT:g} ft truck court, dock-high "
                f"floor {DOCK_HEIGHT:g} ft above it",
                "fully sprinklered (NFPA 13)"]
    if cons == "tilt-up":
        roof = {"type": "flat", "pitch": 0.25, "ridge_dir": None,
                "overhang": 0, "parapet": PARAPET}
    else:
        roof = {"type": "gable", "pitch": PEMB_PITCH, "ridge_dir": "x",
                "overhang": 1.0, "parapet": 0}
    plan = {
        "schema": model.SCHEMA, "units": "ft", "disclaimer": DISCLAIMER,
        "project": {
            "name": fields.get("name") or "Untitled Project",
            "address": fields.get("address") or None,
            "firm": fields.get("firm") or "[FIRM NAME]",
            "date": fields.get("date"), "building_type": TYPE.key,
            "work": fields.get("work") or "new", "occupancy": occ,
            "gross_sf_target": gross, "construction": cons},
        "source": {"brief": fields.get("brief") or "",
                   "sketch": fields.get("sketch"),
                   "ai_used": bool(fields.get("ai_used")),
                   "ai_model": fields.get("ai_model"),
                   "kernel": "modulor", "modulor_version": None},
        "footprint": {"width": W, "depth": D,
                      "from": "sketch" if fields.get("ratio") else "brief"},
        "level": {"name": "L1", "floor_elev": 0.0, "plate_height": eave,
                  "slab": round(SLAB_FT, 3)},
        "roof": roof, "walls": walls, "rooms": rooms, "openings": openings,
        "door_types": {
            "A": "Exterior, insulated hollow metal",
            "B": "Interior, solid core, 3'-0\" (ADA 32 in. clear)",
            "OH-D": "Dock door, insulated sectional, with dock leveler, "
                    "bumpers and seal (assumed)",
            "OH-DI": "Drive-in door, insulated sectional (assumed)"},
        "window_types": {"A": "3'-0\" x 4'-0\" storefront / punched "
                              "window",
                         "B": "2'-0\" x 3'-0\" (bath, obscure)"},
        "notes": {"general": [], "project": [], "from_ai": False},
        "warnings": warnings,
        "grid": grid,
        "truck_court": {"side": "N", "depth": TRUCK_COURT, "assumed": True},
        "warehouse": {
            "construction": cons, "clear_ht": clear, "eave": eave,
            "structure": STRUCTURE[cons], "docks": docks,
            "drive_ins": drive_ins, "office_sf": round(office_sf),
            "office_rect": [office[0], office[1], office[2], office[3]],
            "dock_wall": "N", "dock_height": DOCK_HEIGHT,
            "parking": fields.get("parking"), "sprinklered": True,
            "assumed": assumed,
            "elev_note": {"N": f"Truck court and dock aprons "
                               f"{DOCK_HEIGHT:g} ft below the floor "
                               "(assumed) - grades by the civil engineer."}},
    }
    plan["dropped"] = list(_dropped)
    plan["site"], sw = site_mod.site_for(plan, fields.get("lot"))
    plan["warnings"].extend(w for w in sw if w not in plan["warnings"])
    plan["code"] = codes.analyze(plan)
    model.validate(plan)
    return plan


def _renumber_doors(openings):
    """Door marks 101, 102... again after doors came out of the open
    wall."""
    n = 0
    for o in openings:
        if o["kind"] == "door":
            n += 1
            o["mark"] = str(100 + n)


# ---- hooks ------------------------------------------------------------------
def checks(plan):
    """Self-check lines for a warehouse (audit.py adds them)."""
    from .. import codes
    from ..audit import FAIL, PASS, WARN
    out = []
    walls = {w["id"]: w for w in plan["walls"]}
    bad = [o["mark"] for o in plan["openings"] if o["kind"] == "overhead"
           and (walls.get(o["wall"]) or {}).get("kind") != "exterior"]
    out.append((FAIL if bad else PASS, "Overhead doors on exterior walls "
                "only", ", ".join(bad[:6])))
    g = plan.get("grid") or {}
    W, D = plan["footprint"]["width"], plan["footprint"]["depth"]
    ok = bool(g) and abs(g["x"][0]) < 1e-6 and abs(g["x"][-1] - W) < 1e-6 \
        and abs(g["y"][0]) < 1e-6 and abs(g["y"][-1] - D) < 1e-6 and \
        all(b > a for a, b in zip(g["x"], g["x"][1:])) and \
        all(b > a for a, b in zip(g["y"], g["y"][1:]))
    out.append((PASS if ok else FAIL, "Structural grid on the exterior "
                "walls", "" if ok else "grid lines off the walls"))
    c = codes.analyze(plan, store=False)
    ex = c["exits"]
    out.append((PASS if ex["have"] >= ex["need"] else WARN,
                "Exits for the occupant load (screening)",
                f"{ex['have']} exit doors, {ex['need']} needed for "
                f"{ex['load']} occupants"))
    tr = c["travel"]
    over = tr["limit"] is not None and tr["max_ft"] > tr["limit"]
    out.append((WARN if over or tr["limit"] is None else PASS,
                "Exit access travel distance (approximate)",
                f"{tr['max_ft']:.0f} ft rectilinear, limit "
                f"{tr['limit'] if tr['limit'] is not None else 'n/a'} ft"
                if over or tr["limit"] is None else ""))
    s = plan.get("site") or {}
    tc = float((plan.get("truck_court") or {}).get("depth") or 0)
    if s and tc:
        room = s["provided"]["rear"]
        out.append((PASS if room + 1e-6 >= tc else WARN,
                    "Truck court fits on the lot",
                    "" if room + 1e-6 >= tc else
                    f"{room:.0f} ft behind the dock wall, {tc:.0f} ft "
                    "court"))
    has = any(r["type"] == "riser" for r in plan["rooms"])
    out.append((PASS if has else WARN, "Fire riser room", "" if has else
                "none drawn"))
    return out


def validate(plan):
    from .. import model
    g = plan.get("grid")
    if g:
        W, D = plan["footprint"]["width"], plan["footprint"]["depth"]
        if abs(g["x"][-1] - W) > 1e-6 or abs(g["y"][-1] - D) > 1e-6:
            raise model.PlanError("the structural grid doesn't end on the "
                                  "exterior walls")
    for w in plan.get("walls", []):
        if w.get("kind") == "open" and len(w.get("rooms") or ()) != 2:
            raise model.PlanError(f"open wall {w['id']} must name its two "
                                  "rooms")
    return []


def notes(plan):
    wh = plan.get("warehouse") or {}
    cons = CONSTRUCTION.get(wh.get("construction"), "")
    occ = plan["project"].get("occupancy")
    out = [f"One-story {'manufacturing' if occ == 'F-1' else 'warehouse'} "
           f"building ({occ}) on a slab on grade: {cons.lower()}.",
           "Office front with lobby, offices, break room and restrooms; "
           "the rest of the building is open "
           f"{'production' if occ == 'F-1' else 'storage'} space.",
           "Structural grid, bay sizes and column locations are a starting "
           "point for the structural engineer.",
           "Dock doors, levelers, bumpers and seals, drive-in doors and "
           "truck court grades to be confirmed with the owner and the "
           "civil engineer.",
           "Fire sprinklers, fire riser room, fire alarm and any high-piled "
           "storage design by the fire protection engineer.",
           "Code summary on the code sheet is a screening only; code "
           "analysis by the design professional."]
    if wh.get("assumed"):
        out.append("ASSUMED (not in the brief - verify): " +
                   "; ".join(wh["assumed"]) + ".")
    return out


def cover(plan, rows):
    """The cover's project data for a warehouse: construction, clear
    height, docks, grid and truck court instead of garage and porch."""
    from ..grid import describe
    from ..model import fmt_ftin
    wh = plan.get("warehouse") or {}
    asm = " ".join(wh.get("assumed") or [])
    out = []
    for k, v in rows:
        if k in ("Garage", "Porch / deck"):
            continue
        if k == "Construction type":
            v = CONSTRUCTION.get(wh.get("construction"), v) + (
                " (assumed)" if "construction" in asm else "") + \
                " - type by design professional"
        elif k == "Code analysis":
            v = "screening on G-003 - by design professional"
        out.append([k, v])
        if k == "Stories":
            out += [["Clear height", fmt_ftin(wh.get("clear_ht", 0)) + (
                        " (assumed)" if "clear height" in asm else "")],
                    ["Dock / drive-in doors",
                     f"{wh.get('docks', 0)} dock, {wh.get('drive_ins', 0)} "
                     "drive-in"],
                    ["Structural grid", describe(plan["grid"]) +
                     " (assumed)"],
                    ["Truck court", fmt_ftin(plan["truck_court"]["depth"])
                     + " (assumed)"]]
    return out


def quantities(plan):
    """A-701 rows for a warehouse: (group, item, qty, unit, how)."""
    from .. import quantities as q
    from ..grid import interior_columns
    from ..model import fmt_ftin, wall_length
    out = []

    def add(group, item, qty, unit, how=""):
        if qty:
            out.append((group, item, qty, unit, how))
    G = q.GROUPS
    W, D = plan["footprint"]["width"], plan["footprint"]["depth"]
    t = 0.25
    wh = plan["warehouse"]
    foot = (W + 2 * t) * (D + 2 * t)
    slab_t = float(plan["level"].get("slab") or SLAB_FT)
    perim = 2 * (W + D + 4 * t)
    add(G[0], "Slab on grade (building)", q._r(foot), "SF",
        "outside face of the walls")
    add(G[0], f"Slab concrete, {slab_t * 12:.0f}\" thick (assumed)",
        q._r(foot * slab_t / 27, 1), "CY", "slab area x thickness, no waste")
    add(G[0], "Perimeter footing", q._r(perim), "LF", "outside face")
    tc = plan.get("truck_court")
    if tc:
        add(G[0], f"Truck court paving, {tc['depth']:g} ft deep (assumed)",
            q._r((W + 2 * t) * tc["depth"]), "SF",
            "the dock wall's length x the court depth")
    ops = plan["openings"]
    ext = [w for w in plan["walls"] if w["kind"] == "exterior"]
    ext_ids = {w["id"] for w in ext}
    ext_lf = sum(wall_length(w) for w in ext)
    eave = plan["level"]["plate_height"]
    par = float(plan["roof"].get("parapet") or 0)
    ext_open = sum(o["width"] * o["height"] for o in ops
                   if o["wall"] in ext_ids)
    if wh["construction"] == "tilt-up":
        h = eave + par
        add(G[1], "Tilt-up wall panels, gross", q._r(perim * h), "SF",
            f"perimeter x {h:g} ft (eave + parapet)")
        add(G[1], "Tilt-up wall panels, net", q._r(perim * h - ext_open),
            "SF", "less the door openings")
    else:
        frames = max(0, len(plan["grid"]["x"]) - 2)
        add(G[1], "PEMB rigid frames (interior grid lines)", frames, "EA",
            f"clear span {fmt_ftin(D)}; by the PEMB supplier")
        add(G[1], "PEMB endwall frames", 2, "EA", "by the PEMB supplier")
        add(G[1], "Metal wall panels, net", q._r(ext_lf * eave - ext_open),
            "SF", f"centreline x {eave:g} ft eave, less openings")
    add(G[1], "Interior columns", interior_columns(plan["grid"]), "EA",
        "at the grid intersections (assumed grid)")
    inn = [w for w in plan["walls"] if w["kind"] == "interior"]
    int_lf = sum(wall_length(w) for w in inn)
    add(G[1], "Office partitions", q._r(int_lf), "LF", "centreline, to "
        "the office ceiling")
    # openings: doors and windows by type and size, overhead doors apart
    doors, wins, ohs = {}, {}, {}
    for o in ops:
        key = (o["type"], o["width"], o["height"])
        d = ohs if o["kind"] == "overhead" else doors if \
            o["kind"] == "door" else wins
        d[key] = d.get(key, 0) + 1
    for (typ, w, h), n in sorted(doors.items()):
        add(G[2], f"Door {typ}: {plan['door_types'].get(typ, '')}", n,
            "EA", f"{fmt_ftin(w)} x {fmt_ftin(h)}")
    for (typ, w, h), n in sorted(wins.items()):
        add(G[2], f"Window {typ}: {plan['window_types'].get(typ, '')}", n,
            "EA", f"{fmt_ftin(w)} x {fmt_ftin(h)}")
    for (typ, w, h), n in sorted(ohs.items()):
        add(G[2], f"Overhead door {typ}: "
            f"{plan['door_types'].get(typ, '')}", n, "EA",
            f"{fmt_ftin(w)} x {fmt_ftin(h)}")
    docks = sum(1 for o in ops if o.get("dock"))
    add("Dock equipment", "Dock levelers (assumed at every dock door)",
        docks, "EA", "pit or edge type by the owner")
    add("Dock equipment", "Dock bumpers", 2 * docks, "EA", "two per door")
    add("Dock equipment", "Dock seals / shelters", docks, "EA")
    # finishes, room by room
    floor, ceil, base = {}, {}, {}
    for r in plan["rooms"]:
        f = r.get("finishes") or {}
        x0, y0, x1, y1 = r["rect"]
        a = (x1 - x0) * (y1 - y0)
        kf, kc, kb = (f.get(k) or "TBD" for k in ("floor", "ceiling",
                                                   "base"))
        floor[kf] = floor.get(kf, 0) + a
        ceil[kc] = ceil.get(kc, 0) + a
        if r.get("zone") == "office":
            base[kb] = base.get(kb, 0) + 2 * ((x1 - x0) + (y1 - y0))
    for code, a in sorted(floor.items()):
        add(G[3], f"Floor finish {code}", q._r(a), "SF", "room areas")
    for code, lf in sorted(base.items()):
        if code not in ("-", "TBD"):
            add(G[3], f"Base {code}", q._r(lf), "LF", "office rooms")
    for code, a in sorted(ceil.items()):
        add(G[3], f"Ceiling {code}", q._r(a), "SF", "room areas")
    roof = plan["roof"]
    ov = float(roof.get("overhang") or 0)
    plan_area = (W + 2 * t + 2 * ov) * (D + 2 * t + 2 * ov)
    if roof["type"] == "gable":
        f = math.sqrt(1 + (roof["pitch"] / 12.0) ** 2)
        add(G[4], f"Metal roof, {roof['pitch']:g}:12", q._r(plan_area * f),
            "SF", f"plan area x slope factor {f:.3f}")
        add(G[4], "Ridge", q._r(W + 2 * t + 2 * ov), "LF")
        add(G[4], "Eaves / gutters", q._r(2 * (W + 2 * t + 2 * ov)), "LF")
    else:
        add(G[4], "Low-slope roof membrane", q._r(plan_area), "SF",
            "inside the parapet, no turn-ups")
        add(G[4], "Parapet", q._r(perim), "LF", f"{par:g} ft high")
    return out


def sheets(plan):
    from .. import sheets as S
    from . import warehouse_draw as wd
    out = [S.SheetSpec("G-001", "Cover", S.cover),
           S.SheetSpec("G-002", "General Notes", S.general_notes),
           S.SheetSpec("G-003", "Code Summary", S.code_summary),
           S.SheetSpec("AS-101", "Site Plan", S.site_plan, nts=False),
           S.SheetSpec("A-101", "Floor Plan", S.level_plan(0, "Floor Plan"),
                       nts=False),
           S.SheetSpec("A-102", "Enlarged Office Plan", wd.office_plan,
                       nts=False),
           S.SheetSpec("A-103", "Roof Plan", S.roof_plan, nts=False)]
    out += S.elevation_sheets(plan)
    out += [S.SheetSpec("A-301", "Building Section", wd.section, nts=False),
            S.SheetSpec("A-601", "Room Schedule", S.room_schedule),
            S.SheetSpec("A-602", "Door & Window Schedules", S.door_window),
            S.SheetSpec("A-701", "Quantity Summary", S.quantity_sheet),
            S.SheetSpec("A-801", "Accessibility", S.accessibility)]
    return out


TYPE = BuildingType(
    key="warehouse", label="Warehouse / industrial",
    occupancies=("S-1", "F-1"), default_occ="S-1",
    sf_range=(3000, 200000), stories_range=(1, 1), ratio=2.0,
    plate_height=CLEAR["tilt-up"] + STRUCTURE["tilt-up"],
    floor_to_floor=CLEAR["tilt-up"] + STRUCTURE["tilt-up"],
    ceiling_ht=10.0, ext_wall=CONSTRUCTION["tilt-up"],
    roof_default={"type": "flat", "pitch": 0.25, "overhang": 0,
                  "parapet": PARAPET},
    setbacks={"front": 30.0, "side": 20.0, "rear": 20.0},
    ada_use="warehouse", patterns=PATTERNS, weak=WEAK, occ_rules=OCC_RULES,
    max_w=900.0, max_d=600.0, cover_label="Warehouse / industrial building",
    code_sheet=True, needs=(("restroom",), "Has a restroom"),
    layout=make_plan, checks=checks, sheets=sheets, notes=notes,
    quantities=quantities, validate=validate, cover=cover)
