"""The building plan (schema quantisheet.genset_plan/2): one JSON object that
every sheet and the Modulor op list read. Decimal feet; origin at the
south-west exterior corner, +X east, +Y north; walls are centerlines.

Schema 2 (Phase 1 of the commercial / industrial types) adds, all
optional - a /1 plan is a valid /2 plan and still reads:
  * "floors": [{level, walls, rooms, openings}] - levels 2..n of a
    multi-story building (a two-story house keeps its "upper");
  * opening kind "overhead" (a dock or drive-in door; exterior walls
    only), drawn and scheduled like the garage's overhead doors;
  * wall kind "open" with "rooms": [a, b] - two areas of one space with
    no partition between them (an L-shaped warehouse around its office);
    not built, not counted, walked through;
  * "grid" (grid.py), "code" (codes.py), "truck_court", "warehouse";
    Phase 2: "strip", "restaurant", "parking" (the field in front,
    types/parts.py) and "drive_thru" (the lane beside the building);
  * room "use" - the IBC Table 1004.5 function (app/codecheck.py USES)."""
import copy
import json
import math

from . import DISCLAIMER
from .. import oldnames as _oldnames

SCHEMA = "quantisheet.genset_plan/2"
# what from_json reads (and plans saved under the old name - oldnames)
SCHEMAS = (SCHEMA,) + _oldnames.GENSET_OLD
HABITABLE = {"living", "bed", "office", "dining", "kitchen", "open_office",
             "sales", "conference", "lobby"}


class PlanError(ValueError):
    """The plan can't be drawn (overlapping rooms, a door off its wall)."""


def fmt_ftin(ft):
    """9.5 -> 9'-6"  (rounded to the nearest 1/2 inch)."""
    neg = ft < 0
    half_in = round(abs(ft) * 24)            # half inches
    feet, rem = divmod(half_in, 24)
    inches, half = divmod(rem, 2)
    s = f"{feet}'-{inches}" + (" 1/2" if half else "") + '"'
    return "-" + s if neg else s


def rect_area(r):
    return max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])


def _overlap(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(0.0, w) * max(0.0, h)


def wall_length(w):
    (ax, ay), (bx, by) = w["a"], w["b"]
    return math.hypot(bx - ax, by - ay)


def levels(plan):
    """One plan per floor: [level 1, level 2...]. Level 1 is the plan
    itself; each upper level is the plan with its own level, walls, rooms
    and openings - a two-story house keeps them under plan["upper"], a
    taller building under plan["floors"] (levels 2..n, schema 2)."""
    out = [plan]
    for up in ([plan["upper"]] if plan.get("upper") else []) + \
            list(plan.get("floors") or ()):
        lp = dict(plan)
        lp.pop("upper", None)
        lp.pop("floors", None)
        for k in ("garage", "porch", "deck"):   # these are on the ground
            lp.pop(k, None)
        lp.update(level=up["level"], walls=up["walls"], rooms=up["rooms"],
                  openings=up["openings"])
        out.append(lp)
    return out


def top_level(plan):
    return levels(plan)[-1]["level"]


def stories(plan):
    return len(levels(plan))


def validate(plan):
    """Raise PlanError for a plan that can't be drawn; return the list of
    warnings (also added to plan["warnings"]). The building type's own
    checks (types/*.py) run after the geometry's."""
    if plan.get("upper") or plan.get("floors"):
        warn = []
        for i, lp in enumerate(levels(plan)):
            lp = dict(lp, warnings=plan.setdefault("warnings", []))
            try:
                warn += _validate_level(lp)
            except PlanError as e:
                raise PlanError(f"level {i + 1}: {e}") from None
    else:
        warn = _validate_level(plan)
    from . import types
    more = types.for_plan(plan).run("validate", plan, default=None)
    if more:
        warn = warn + list(more)
        for w_ in more:
            if w_ not in plan.setdefault("warnings", []):
                plan["warnings"].append(w_)
    return warn


def _validate_level(plan):
    warn = []
    if plan.get("disclaimer") != DISCLAIMER:
        raise PlanError("the disclaimer must read exactly: " + DISCLAIMER)
    if (plan.get("source") or {}).get("kernel") != "modulor":
        raise PlanError("source.kernel must be \"modulor\" for v1 builds")
    fp = plan["footprint"]
    W, D = float(fp["width"]), float(fp["depth"])
    rooms = plan.get("rooms", [])
    for r in rooms:
        x0, y0, x1, y1 = r["rect"]
        if x0 < -1e-6 or y0 < -1e-6 or x1 > W + 1e-6 or y1 > D + 1e-6:
            raise PlanError(f"room {r['number']} lies outside the footprint")
        if x1 <= x0 or y1 <= y0:
            raise PlanError(f"room {r['number']} has no area")
        if abs(rect_area(r["rect"]) - float(r["area"])) > 0.5:
            raise PlanError(f"room {r['number']} area {r['area']} doesn't "
                            f"match its rectangle ({rect_area(r['rect']):.1f})")
    for i, a in enumerate(rooms):
        for b in rooms[i + 1:]:
            if _overlap(a["rect"], b["rect"]) > 0.01:
                raise PlanError(f"rooms {a['number']} and {b['number']} "
                                "overlap")
    walls = {w["id"]: w for w in plan.get("walls", [])}
    ids = {r["id"] for r in rooms} | {"EXT"}
    for o in plan.get("openings", []):
        w = walls.get(o["wall"])
        if w is None:
            raise PlanError(f"opening {o['id']} is on a wall that doesn't "
                            "exist")
        L = wall_length(w)
        lo, hi = o["along"] - o["width"] / 2, o["along"] + o["width"] / 2
        if lo < 0.5 - 1e-6 or hi > L - 0.5 + 1e-6:
            raise PlanError(f"opening {o['id']} runs off wall {w['id']}")
        if o["kind"] == "overhead" and w["kind"] != "exterior":
            raise PlanError(f"overhead door {o['id']} is not on an "
                            "exterior wall")
        if w["kind"] == "open":
            raise PlanError(f"opening {o['id']} is in an open (unbuilt) "
                            f"wall {w['id']}")
        if o["kind"] == "door" and w["kind"] == "interior":
            if o.get("from_room") not in ids or o.get("to_room") not in ids:
                raise PlanError(f"door {o['id']} doesn't connect two rooms")
    spans = {}
    for o in plan.get("openings", []):
        lo, hi = o["along"] - o["width"] / 2, o["along"] + o["width"] / 2
        for oid, a, b in spans.get(o["wall"], []):
            if lo < b - 1e-6 and hi > a + 1e-6:
                raise PlanError(f"openings {oid} and {o['id']} overlap on "
                                f"wall {o['wall']}")
        spans.setdefault(o["wall"], []).append((o["id"], lo, hi))
    for r in rooms:
        t = float(r.get("target_sf") or 0)
        if t and abs(rect_area(r["rect"]) - t) > 0.4 * t:
            warn.append(f"{r['name']} came out at "
                        f"{rect_area(r['rect']):,.0f} SF (asked about "
                        f"{t:,.0f} SF)")
    for r in rooms:
        if r["type"] in HABITABLE and not any(
                o["kind"] == "window" and o.get("room") == r["id"]
                for o in plan.get("openings", [])):
            warn.append(f"{r['name']} ({r['number']}) has no window")
    plan.setdefault("warnings", [])
    for w_ in warn:
        if w_ not in plan["warnings"]:
            plan["warnings"].append(w_)
    return warn


def to_json(plan):
    return json.dumps(plan, indent=2, sort_keys=False)


def from_json(text):
    plan = json.loads(text)
    if plan.get("schema") not in SCHEMAS:
        raise PlanError(f"not a {SCHEMA} plan")
    if plan["schema"] in _oldnames.GENSET_OLD:   # saved under the old name
        plan["schema"] = SCHEMA
    return plan


def clone(plan):
    return copy.deepcopy(plan)
