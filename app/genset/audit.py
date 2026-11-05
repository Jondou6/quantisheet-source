"""The set checks itself: audit(plan) -> [(status, check, detail)] with
status PASS, WARN or FAIL. One checker, three users: the cover sheet's
SELF-CHECK box, the .genset.json sidecar, and the tests (Venice, Oct 19:
"the oracle that would have caught all three findings").

These are geometry and consistency checks of the generated drawings, not a
code review - code analysis stays with the design professional."""
from collections import deque

from . import DISCLAIMER
from .model import HABITABLE, rect_area, wall_length

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"
LIGHT_RATIO = 0.08         # glass at least 8% of floor area (a common rule
                           # of thumb for natural light - verify locally)
MIN_DOOR = 2.0             # ft


def _overlap(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    return max(0.0, min(ax1, bx1) - max(ax0, bx0)) * \
        max(0.0, min(ay1, by1) - max(ay0, by0))


def _reached(plan):
    rooms = {r["id"] for r in plan["rooms"]}
    adj = {r: set() for r in rooms}
    start = set()
    for o in plan["openings"]:
        if o["kind"] != "door":
            continue
        a, b = o.get("from_room"), o.get("to_room")
        if a == "EXT" and b in rooms:
            start.add(b)
        elif a in rooms and b in rooms:
            adj[a].add(b)
            adj[b].add(a)
    for a, b in _open_pairs(plan):          # one space, two rectangles
        if a in rooms and b in rooms:
            adj[a].add(b)
            adj[b].add(a)
    seen, q = set(start), deque(start)
    while q:
        for nb in adj[q.popleft()]:
            if nb not in seen:
                seen.add(nb)
                q.append(nb)
    return seen, rooms


def _open_pairs(plan):
    """(room, room) pairs joined by an open wall - no partition between
    them (schema 2)."""
    return [tuple(w["rooms"]) for w in plan.get("walls", [])
            if w.get("kind") == "open" and len(w.get("rooms") or ()) == 2]


def _needs(plan):
    """(room kinds the building must have, the check's name) - from its
    building type: a bedroom and a bath for a house, a restroom
    otherwise."""
    from . import types
    kinds, label = types.for_plan(plan).needs
    return set(kinds), label


def _type_checks(plan):
    from . import types
    return list(types.for_plan(plan).run("checks", plan, default=[]) or [])


def _chain(plan):
    """The south dimension string: the room breaks along the front add up
    to the overall size (both measured to the outside face)."""
    W = plan["footprint"]["width"]
    t = 0.25
    xs = sorted({round(x, 3) for r in plan["rooms"]
                 if abs(r["rect"][1] - t) < 1e-6
                 for x in (r["rect"][0], r["rect"][2])})
    xs = [-t] + [x for x in xs if t < x < W - t] + [W + t]
    segs = [b - a for a, b in zip(xs, xs[1:])]
    # and the front rooms really cover the front, end to end with no gap
    # (Venice review M12: the sum closed by construction)
    front = sorted((r["rect"][0], r["rect"][2]) for r in plan["rooms"]
                   if abs(r["rect"][1] - t) < 1e-6)
    x, covered = t, bool(front)
    for a, b in front:
        if a > x + 1e-6:
            covered = False
            break
        x = max(x, b)
    covered = covered and x >= W - t - 1e-6
    return covered and abs(sum(segs) - (W + 2 * t)) < 1e-6 and \
        all(s > 0 for s in segs)


def audit(plan):
    """[(status, check, detail)] for the whole set. A two-story house is
    checked floor by floor (the details say "L2:" for the upper floor);
    the entry door is on level 1, level 2 is reached by the stair, and
    the bedroom / bath and gross-area checks are for the whole house."""
    from .model import levels
    lvls = levels(plan)
    if len(lvls) == 1:
        return _audit_level(plan)
    rank = {PASS: 0, WARN: 1, FAIL: 2}
    merged, order = {}, []
    for i, lp in enumerate(lvls):
        for st, chk, det in _audit_level(dict(lp, _level_of=True)):
            if chk not in merged:
                merged[chk] = [PASS, []]
                order.append(chk)
            if i and chk in ("An entry door from outside",
                             "Building inside the setbacks",
                             "Building fits on the lot",
                             "FOR REVIEW - NOT FOR SEALING on the set"):
                continue          # the first floor's (or the whole set's)
            if i and chk == "Every room reached from an outside door":
                st, det = _stair_reach(lp)
            if rank[st] > rank[merged[chk][0]]:
                merged[chk][0] = st
            if det:
                merged[chk][1].append((f"L{i + 1}: " if i else "") + det)
    rooms = [r for lp in lvls for r in lp["rooms"]]
    W = float(plan["footprint"]["width"])
    D = float(plan["footprint"]["depth"])
    gross = (W + 0.5) * (D + 0.5) * len(lvls)
    target = float(plan["project"].get("gross_sf_target") or 0)
    if target:
        off = abs(gross - target) / target
        merged["Gross area within 10% of the brief"] = [
            PASS if off <= 0.10 else WARN,
            [f"{gross:,.0f} SF vs {target:,.0f} SF"] if off > 0.10 else []]
    have = {r["type"] for r in rooms}
    # what the building type needs, for the whole building (it was always
    # a bedroom and a bath here, whatever the building)
    need, label = _needs(plan)
    missing = sorted(need - have)
    merged[label] = [FAIL if missing else PASS,
                     [", ".join(missing)] if missing else []]
    if label not in order:
        order.append(label)
    net = sum(rect_area(r["rect"]) for r in rooms)
    merged["Room schedule totals the plan"] = [PASS if net > 0 else FAIL,
                                               [f"{net:,.0f} SF net"]]
    return [(merged[c][0], c, "; ".join(merged[c][1])) for c in order] + \
        _type_checks(plan)


def _stair_reach(lp):
    """Level 2: every room reached from the stair hall through doors."""
    rooms = {r["id"] for r in lp["rooms"]}
    hub = lp["rooms"][0]["id"]
    adj = {r: set() for r in rooms}
    for o in lp["openings"]:
        a, b = o.get("from_room"), o.get("to_room")
        if o["kind"] == "door" and a in rooms and b in rooms:
            adj[a].add(b)
            adj[b].add(a)
    seen, q = {hub}, deque([hub])
    while q:
        for nb in adj[q.popleft()]:
            if nb not in seen:
                seen.add(nb)
                q.append(nb)
    lost = [r["name"] for r in lp["rooms"] if r["id"] not in seen]
    return (FAIL if lost else PASS), ", ".join(lost[:4])


def _audit_level(plan):
    out = []

    def add(status, check, detail=""):
        out.append((status, check, detail))

    rooms = plan.get("rooms", [])
    W, D = float(plan["footprint"]["width"]), float(plan["footprint"]["depth"])
    inner = (W - 0.5) * (D - 0.5)
    covered = sum(rect_area(r["rect"]) for r in rooms)
    gap = inner - covered
    add(PASS if abs(gap) <= 2 else FAIL, "Floor fully covered by rooms",
        f"{covered:,.0f} of {inner:,.0f} SF" if abs(gap) > 2 else "")

    clash = [(a["number"], b["number"]) for i, a in enumerate(rooms)
             for b in rooms[i + 1:] if _overlap(a["rect"], b["rect"]) > 0.01]
    add(FAIL if clash else PASS, "No rooms overlap",
        ", ".join(f"{a}/{b}" for a, b in clash[:4]))

    outside = [r["name"] for r in rooms if r["rect"][0] < -1e-6 or
               r["rect"][1] < -1e-6 or r["rect"][2] > W + 1e-6 or
               r["rect"][3] > D + 1e-6]
    add(FAIL if outside else PASS, "Rooms inside the building",
        ", ".join(outside[:4]))

    narrow_rooms = [r["name"] for r in rooms if r["type"] in HABITABLE and
                    min(r["rect"][2] - r["rect"][0],
                        r["rect"][3] - r["rect"][1]) < 7.0]
    add(WARN if narrow_rooms else PASS, "Habitable rooms at least 7 ft "
        "across", ", ".join(narrow_rooms[:4]))

    doors = [o for o in plan["openings"] if o["kind"] == "door"]
    entry = [o for o in doors if o.get("from_room") == "EXT"]
    add(PASS if entry else FAIL, "An entry door from outside")
    opened = {x for pair in _open_pairs(plan) for x in pair}
    doorless = [r["name"] for r in rooms if r["id"] not in opened and
                not any(r["id"] in (o.get("from_room"), o.get("to_room"))
                        for o in doors)]
    add(FAIL if doorless else PASS, "Every room has a door",
        ", ".join(doorless[:4]))

    # doors that open into each other: hinge points closer than a door
    # width (Venice's swing check)
    walls_ = {w["id"]: w for w in plan.get("walls", [])}

    def hinge(o):
        w = walls_.get(o["wall"])
        if w is None:
            return None
        (ax, ay), (bx, by) = w["a"], w["b"]
        L = wall_length(w) or 1
        f = o["along"] / L
        return ax + (bx - ax) * f, ay + (by - ay) * f
    close = []
    for i, a in enumerate(doors):
        for b in doors[i + 1:]:
            pa, pb = hinge(a), hinge(b)
            if pa and pb and a["wall"] != b["wall"] and \
                    ((pa[0] - pb[0]) ** 2 + (pa[1] - pb[1]) ** 2) ** 0.5 < \
                    (a["width"] + b["width"]) / 2:
                close.append(f"{a['mark']}/{b['mark']}")
    add(WARN if close else PASS, "Doors don't swing into each other",
        ", ".join(close[:4]))

    off = [r["name"] for r in rooms if r.get("target_sf") and
           abs(rect_area(r["rect"]) - r["target_sf"]) > 0.4 * r["target_sf"]]
    add(WARN if off else PASS, "Room sizes within 40% of the program",
        ", ".join(off[:4]))

    seen, ids = _reached(plan)
    lost = [r["name"] for r in rooms if r["id"] not in seen]
    add(FAIL if lost else PASS, "Every room reached from an outside door",
        ", ".join(lost[:4]))

    by = {r["id"]: r for r in rooms}
    ndoors = {}
    for o in plan["openings"]:
        if o["kind"] == "door":
            for k in (o.get("from_room"), o.get("to_room")):
                ndoors[k] = ndoors.get(k, 0) + 1
    # a door from a bedroom into its own bath (a room with no other door)
    # is an en-suite, not walking through
    walk = [f"{by[o['from_room']]['name']} > {by[o['to_room']]['name']}"
            for o in plan["openings"] if o["kind"] == "door"
            and o.get("from_room") in by and o.get("to_room") in by
            and by[o["from_room"]]["type"] in ("bed", "bath", "laundry",
                                               "mech", "restroom")
            and not (ndoors.get(o["to_room"]) == 1 and
                     by[o["to_room"]]["type"] in ("bath", "laundry",
                                                  "mech", "storage"))]
    add(WARN if walk else PASS, "No walking through bedrooms, baths or "
        "service rooms", "; ".join(walk[:3]))

    dark, low = [], []
    for r in rooms:
        if r["type"] not in HABITABLE:
            continue
        glass = sum(o["width"] * o["height"] for o in plan["openings"]
                    if o["kind"] == "window" and o.get("room") == r["id"])
        if glass == 0:
            dark.append(r["name"])
        elif glass < LIGHT_RATIO * rect_area(r["rect"]):
            low.append(r["name"])
    add(FAIL if any("BED" in n for n in dark) else
        WARN if dark else PASS, "Every habitable room has a window",
        ", ".join(dark[:4]))
    add(WARN if low else PASS, f"Window glass at least {LIGHT_RATIO:.0%} "
        "of floor area", ", ".join(low[:4]))

    walls = {w["id"]: w for w in plan.get("walls", [])}
    bad_open, spans = [], {}
    for o in plan["openings"]:
        w = walls.get(o["wall"])
        lo, hi = o["along"] - o["width"] / 2, o["along"] + o["width"] / 2
        if w is None or lo < 0.5 - 1e-6 or hi > wall_length(w) - 0.5 + 1e-6:
            bad_open.append(o["mark"])
        for a, b in spans.get(o["wall"], []):
            if lo < b and hi > a:
                bad_open.append(o["mark"])
        spans.setdefault(o["wall"], []).append((lo, hi))
    add(FAIL if bad_open else PASS, "Doors and windows fit their walls, "
        "none overlap", ", ".join(sorted(set(bad_open))[:6]))

    narrow = [o["mark"] for o in plan["openings"]
              if o["kind"] == "door" and o["width"] < MIN_DOOR]
    add(WARN if narrow else PASS, "Doors at least 2'-0\" wide",
        ", ".join(narrow[:6]))

    add(PASS if _chain(plan) else FAIL, "Dimension string closes on the "
        "overall size")

    net = covered
    target = float(plan["project"].get("gross_sf_target") or 0)
    gross = (W + 0.5) * (D + 0.5)
    if target:
        off = abs(gross - target) / target
        add(PASS if off <= 0.10 else WARN, "Gross area within 10% of the "
            "brief", f"{gross:,.0f} SF vs {target:,.0f} SF" if off > 0.10
            else "")
    add(PASS if net > 0 else FAIL, "Room schedule totals the plan",
        f"{net:,.0f} SF net")

    need, label = _needs(plan)
    have = {r["type"] for r in rooms}
    missing = sorted(need - have)
    add(FAIL if missing else PASS, label, ", ".join(missing))

    gar = plan.get("garage")
    if gar:
        door = next((o for o in plan["openings"]
                     if o.get("from_room") == "GAR"), None)
        into = by.get(door.get("to_room")) if door else None
        add(PASS if into and into["type"] not in ("bed", "bath") else FAIL,
            "Garage door opens into the house (not a bedroom or bath)",
            "" if into else "no door")
        g_walls = {o["wall"] for o in plan["openings"]
                   if o["kind"] == "window" and o["wall"] in ("W2", "W4")}
        side_wall = "W2" if gar["side"] == "E" else "W4"
        D_ = float(plan["footprint"]["depth"])
        covered = [o["mark"] for o in plan["openings"]
                   if o["kind"] == "window" and o["wall"] == side_wall and
                   (o["along"] < gar["depth"] if side_wall == "W2" else
                    o["along"] > D_ - gar["depth"])]
        add(FAIL if covered else PASS, "No windows into the garage",
            ", ".join(covered))
        del g_walls
    s = plan.get("site")
    if s:
        if not s["on_lot"]:
            add(FAIL, "Building fits on the lot", "larger than the lot")
        else:
            det = ", ".join(s["binding"])
            if s.get("assumed"):
                det = (det + "; " if det else "") + "setbacks assumed: " + \
                    ", ".join(s["assumed"])
            add(WARN if s["binding"] else PASS, "Building inside the "
                "setbacks", det)
    add(PASS if plan.get("disclaimer") == DISCLAIMER else FAIL,
        "FOR REVIEW - NOT FOR SEALING on the set")
    if not plan.get("_level_of"):
        out += _type_checks(plan)
        out += site_checks(plan)
    return out


def site_checks(plan, f=None, lay=None):
    """The parking field and the walks as AS-101 draws them (a plan with
    parking or a drive-thru): every walk beside the field, never across a
    stall row or a drive aisle (FAIL - a drawing error); no other drawn
    line across the field either, but the drive-thru lane on its paving
    and the crosswalk (FAIL - views.field_crossings); and the field
    behind the front setback unless the brief allows parking in the front
    yard (WARN - zoning decides). `lay`: the placed site layout to check
    (views.site_layout(plan) when None)."""
    from . import site as site_mod
    if f is None:
        try:
            f = site_mod.features(plan)
        except Exception:                            # noqa: BLE001
            return []
    if not f or not f["rows"]:
        return []
    out = []

    def cuts(w, r):              # overlapping interiors, not just touching
        return (min(w[2], r[2]) - max(w[0], r[0]) > 1e-6 and
                min(w[3], r[3]) - max(w[1], r[1]) > 1e-6)
    bad = [w["kind"] for w in f["walks"]
           for r in f["rows"] + f["aisles"] if cuts(w["rect"], r)]
    out.append((FAIL if bad else PASS, "Walks beside the parking, not "
                "across stalls or aisles",
                f"{len(bad)} crossing{'s' if len(bad) > 1 else ''}"
                if bad else ""))
    try:
        from . import views
        if lay is None:
            lay = views.site_layout(plan)
        cross = views.field_crossings(lay)
    except ImportError:              # no layout to check (no PyMuPDF)
        cross = None
    if cross is not None:
        what = sorted({c[0] for c in cross})
        out.append((FAIL if cross else PASS, "No site plan line across "
                    "the parking but the lane and crosswalks",
                    f"{len(cross)} segment{'s' if len(cross) > 1 else ''} "
                    f"({', '.join(what)})" if cross else ""))
    s = plan.get("site") or {}
    ey0 = f["envelope"][1]                   # the front setback line
    low = min(r[1] for r in f["rows"])
    into = ey0 - low
    if into <= 1e-6:
        out.append((PASS, "Parking out of the front setback", ""))
    elif s.get("front_parking"):
        out.append((PASS, "Parking out of the front setback",
                    "front-yard parking allowed by the brief"))
    else:
        sb = float(s.get("setbacks", {}).get("front", 0))
        past = f["lot"][1] - low                 # past the front lot line
        out.append((WARN, "Parking out of the front setback",
                    f"the field runs {min(into, sb):.0f}' into the "
                    f"{sb:g}' front setback" + (
                        f" and {past:.0f}' past the front lot line"
                        if past > 1e-6 else "") + " - verify with zoning"))
    return out


def summary(results):
    """'PASS' / 'WARN' / 'FAIL' for the whole set (the worst one)."""
    st = {s for s, _c, _d in results}
    return FAIL if FAIL in st else WARN if WARN in st else PASS
