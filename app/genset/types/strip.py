"""Strip retail center: a one-story, multi-tenant mercantile building (M),
4,000 - 60,000 SF.

Rules (Claude, Oct 20 - for Jon to confirm; every default is an
assumption and the set says so):
  * A row of tenant bays along the street, the storefronts on the south
    (parking) side and the service doors on the north. A typical bay is
    25 ft wide x 70 ft deep (the usual 20-30 x 60-80 ft); the brief's
    "6 tenants" / "6 bays" / "6 units" sets the count, its gross SF the
    size, and an "end cap" a bay about 1.6 times as wide at one end ("end
    caps" / "both ends": at both).
  * Each bay is a tenant (rooms carry tenant "T1", "T2"... west to east):
    a SALES room the full width at the front, and behind it STOCK, a
    single-user RESTROOM and a JAN / ELEC room (the restroom stack on
    alternate sides, so two tenants share a wet wall). Storefront glass
    and a 3'-0" entrance on the south, a 3'-0" service door (the second
    exit) on the north. No door between tenants: demising walls, 8" (the
    rating by the design professional).
  * Structural grid on the exterior walls and the demising walls (a bay
    over 40 ft gets a line between), and an east-west line at the back of
    the sales rooms.
  * 16 ft to the roof bearing, a low-slope roof inside a 4 ft parapet.
  * Parking in front: the brief's count, else 4 spaces per 1,000 SF
    (assumed - zoning decides), double-loaded rows the building's length.
"""
import math
import re

from .base import BuildingType

BAY_W, BAY_D = 25.0, 70.0           # typical tenant bay, ft (assumed)
TYPICAL_W, TYPICAL_D = (20.0, 30.0), (60.0, 80.0)
MIN_BAY_W = 18.0                    # narrower than this: fewer tenants
CAP = 1.6                           # an end cap's width, typical bays
MAX_TENANTS = 40
BACK_SHARE, BACK_MIN, BACK_MAX = 0.28, 16.0, 24.0   # stock zone depth, ft
RR_W, RR_D = 8.0, 9.0               # single-user restroom, ft
DEMISING_T = 8.0 / 12               # 8" demising wall (CMU or rated stud)
PLATE = 16.0
PARAPET = 4.0
PARKING_PER_1000 = 4.0              # assumed (zoning decides)
SPLIT_BAY = 40.0                    # grid: a bay wider than this is split
SF_DOOR = (3.0, 7.0)                # storefront entrance (w, h)
SF_GLASS_H, SF_SILL, SF_PANE = 8.0, 1.5, 8.0
REAR_DOOR = (3.0, 7.0)

PATTERNS = (r"\bstrip\s+(?:center|centre|mall|retail|shopping|plaza)\b",
            r"\bretail\s+strip\b", r"\bstrip[- ]retail\b",
            r"\bshopping\s+(?:center|centre|plaza)\b",
            r"\bretail\s+(?:center|centre|plaza)\b",
            r"\bin-?line\s+retail\b")
_RETAIL = re.compile(r"\b(?:retail|shops?|stores?|storefronts?|"
                     r"mercantile|shopping)\b", re.I)
# a building for offices or clinics with tenants is not strip retail (the
# office rules in brief.py take it)
_OFFICE = re.compile(r"\b(?:office|offices|medical|clinic|dental|"
                     r"professional)\b", re.I)
_MULTI = re.compile(r"\bmulti[- ]?tenant\b", re.I)
_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
          "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
_COUNT = re.compile(r"\b(\d+|" + "|".join(_WORDS) + r")[\s-]*(?:(?:retail|"
                    r"tenant|commercial|shop|store)\s+)?(?:tenants?|bays?|"
                    r"units?|shops|stores|suites?|spaces)\b", re.I)
_PER = re.compile(r"\b(\d+)[\s-]*(?:tenants?|bays|units|shops|suites)\s*"
                  r"(?:of|at|@)\s*(\d[\d,]*)\s*(?:sf|s\.f\.|sq\.?\s*ft|"
                  r"square\s*feet)", re.I)
_SIZE = re.compile(r"\b(\d{2})\s*(?:'|ft\.?|feet)?\s*(?:x|by)\s*(\d{2,3})\s*"
                   r"(?:'|ft\.?|feet)?\s*(?:deep\s+)?(?:tenant\s+)?"
                   r"(?:bays?|units?|suites?|spaces?)\b", re.I)
_DEEP = re.compile(r"\b(\d{2,3})\s*(?:'|ft\.?|feet|foot)\s*deep\b", re.I)
_CAP = re.compile(r"\bend[- ]?caps?\b", re.I)
_TWO_CAPS = re.compile(r"\b(?:end[- ]?caps\b|two\s+end[- ]?caps?|"
                       r"(?:end[- ]?caps?\s+)?(?:at\s+)?both\s+ends)", re.I)


def _parking_like(word):
    """"120 spaces" is parking; "5 tenant spaces" is not."""
    return bool(re.search(r"spaces$", word, re.I)) and not re.search(
        r"tenant|retail|commercial|shop|store", word, re.I)


def _count(m):
    s = m.group(1).lower()
    return _WORDS.get(s) or int(s)


def detect(text):
    """A count of tenants ("6 tenants", "a 4-tenant building"), "multi-
    tenant", or a count of bays / units / shops with a retail word ("8
    retail bays") - unless the brief is for offices or a clinic."""
    t = text or ""
    if _OFFICE.search(t) and not _RETAIL.search(t):
        return None
    retail = bool(_RETAIL.search(t))
    hits = []
    for m in _COUNT.finditer(t):
        word = m.group(0).strip().lower()
        if not 2 <= _count(m) <= MAX_TENANTS or _parking_like(word):
            continue
        if re.search(r"tenants?$", word) or retail:
            hits.append(word)
    hits += [m.group(0).lower() for m in _MULTI.finditer(t)]
    return hits or None


def read(text):
    """tenants, end_caps, bay_w, bay_d, parking from the brief."""
    from .warehouse import _PARKING
    t = text or ""
    out = {}
    m = _PER.search(t)
    if m and 2 <= int(m.group(1)) <= MAX_TENANTS:
        out["tenants"] = int(m.group(1))
        out["bay_sf"] = float(m.group(2).replace(",", ""))
    for m in _COUNT.finditer(t):
        if _parking_like(m.group(0).strip()):
            continue
        n = _count(m)
        if 1 <= n <= MAX_TENANTS:
            out.setdefault("tenants", n)
            break
    if _CAP.search(t):
        out["end_caps"] = 2 if _TWO_CAPS.search(t) else 1
    m = _SIZE.search(t)
    if m:
        w, d = float(m.group(1)), float(m.group(2))
        if 16 <= w <= 80 and 40 <= d <= 120:
            out["bay_w"], out["bay_d"] = w, d
    m = _DEEP.search(t)
    if m and "bay_d" not in out and 40 <= int(m.group(1)) <= 120:
        out["bay_d"] = float(m.group(1))
    m = _PARKING.search(t)
    if m and 0 < int(m.group(1)) <= 5000:
        out["parking"] = int(m.group(1))
    return out


# ---- the plan --------------------------------------------------------------
def _units(n, caps):
    """Width of the row in typical bays."""
    return (n - caps) + caps * CAP


def size(fields, warnings, assumed):
    """(W, D, n, caps, gross): the footprint (centrelines), the bays and
    the gross SF the plan is drawn to."""
    from .. import model
    from ..layout import _r2
    lo, hi = TYPE.sf_range
    gross = float(fields.get("gross_sf") or 0)
    n = int(fields.get("tenants") or 0)
    caps = int(fields.get("end_caps") or 0)
    bw0 = float(fields.get("bay_w") or 0)
    D0 = float(fields.get("bay_d") or 0)
    if fields.get("bay_sf") and n:
        g = n * float(fields["bay_sf"])
        if gross and abs(gross - float(fields["bay_sf"])) > 1 and \
                abs(g - gross) / g > 0.1:
            warnings.append(f"{n} bays of {fields['bay_sf']:,.0f} SF is "
                            f"{g:,.0f} SF, not the brief's {gross:,.0f} "
                            f"SF; drawn at {g:,.0f} SF.")
        gross = g
    if not gross and n:
        bw, dd = bw0 or BAY_W, D0 or BAY_D
        gross = (_units(n, min(caps, n - 1)) * bw + 0.5) * (dd + 0.5)
        assumed.append(f"gross area from {n} bays of {bw:g} x {dd:g} ft")
    if not gross:
        raise model.PlanError("Enter the gross SF or the number of "
                              "tenants.")
    if gross < lo:
        raise model.PlanError(f"Strip retail starts at {lo:,.0f} SF.")
    if gross > hi:
        raise model.PlanError(f"v1 covers strip retail up to {hi:,.0f} SF "
                              "(one story).")
    target = bw0 or BAY_W
    if not n:
        width = gross / ((D0 or BAY_D) + 0.5) - 0.5
        n = max(2, int(round(width / target - caps * (CAP - 1))))
        assumed.append(f"{n} tenant bays (about {target:g} ft wide)")
    n = max(2, min(MAX_TENANTS, n))
    caps = min(caps, n - 1, 2)

    def bay_w(d):
        return (gross / (d + 0.5) - 0.5) / _units(n, caps)
    if D0:
        D = D0
    else:
        # the depth in the usual 60 - 80 ft that brings the typical bay
        # nearest its width (25 ft unless the brief gave one)
        D = min((float(d) for d in range(int(TYPICAL_D[0]),
                                         int(TYPICAL_D[1]) + 1, 2)),
                key=lambda d: (round(abs(bay_w(d) - target), 1),
                               abs(d - BAY_D)))
        assumed.append(f"bays {D:g} ft deep")
    width = gross / (D + 0.5) - 0.5
    while width > TYPE.max_w and D < TYPE.max_d:
        D += 10.0
        width = gross / (D + 0.5) - 0.5
    W = float(_r2(width))
    if W > TYPE.max_w:
        raise model.PlanError(f"v1 draws strip centers up to "
                              f"{TYPE.max_w:g} ft long.")
    while n > 2 and W / _units(n, caps) < MIN_BAY_W:
        n -= 1
    if W / _units(n, caps) < MIN_BAY_W:
        raise model.PlanError("Too many tenants for the area; add SF or "
                              "fewer bays.")
    if fields.get("tenants") and n != int(fields["tenants"]):
        warnings.append(f"{fields['tenants']} tenants don't fit at "
                        f"{MIN_BAY_W:g} ft or wider; drawn as {n}.")
    bw = W / _units(n, caps)
    if not (TYPICAL_W[0] <= bw <= TYPICAL_W[1] + 10):
        warnings.append(f"Typical bay {bw:.0f} ft wide - outside the usual "
                        f"{TYPICAL_W[0]:g}-{TYPICAL_W[1]:g} ft; check the "
                        "tenant count.")
    return W, float(D), n, caps, gross


def demising(W, n, caps):
    """x of the demising wall centrelines, west to east (whole feet). With
    one end cap it is the east bay; with two, both ends."""
    widths = [1.0] * n
    if caps >= 1:
        widths[-1] = CAP
    if caps >= 2:
        widths[0] = CAP
    tot = sum(widths)
    xs, acc = [], 0.0
    for w in widths[:-1]:
        acc += w
        xs.append(float(round(W * acc / tot)))
    return xs


def _back_depth(D):
    return max(BACK_MIN, min(BACK_MAX, round((D - 0.5) * BACK_SHARE)))


def _make_rooms(W, D, xs, caps):
    """The rooms, tenant by tenant, and each tenant's rectangles."""
    from . import parts
    t = 0.25
    edges = [t] + xs + [W - t]
    ys = float(round(D - t - _back_depth(D)))
    rooms, tenants = [], []
    n = len(edges) - 1
    k = 0
    for i in range(n):
        tid = f"T{i + 1}"
        xa, xb = edges[i], edges[i + 1]
        east = i % 2 == 0                   # the restroom stack's side
        xc = float(round(xb - RR_W)) if east else float(round(xa + RR_W))
        yr = ys + RR_D
        cap = (caps >= 1 and i == n - 1) or (caps >= 2 and i == 0)
        spec = [("SALES", "sales", (xa, t, xb, ys)),
                ("STOCK", "storage", (xa, ys, xc, D - t) if east else
                 (xc, ys, xb, D - t)),
                ("RESTROOM", "restroom", (xc, ys, xb, yr) if east else
                 (xa, ys, xc, yr)),
                ("JAN / ELEC", "mech", (xc, yr, xb, D - t) if east else
                 (xa, yr, xc, D - t))]
        ids = []
        for name, kind, rc in spec:
            k += 1
            r = parts.room(f"R{100 + k}", 100 + k, f"{tid} {name}", kind, rc,
                           tenant=tid)
            r["ceiling_ht"] = {"sales": 12.0, "storage": 14.0,
                               "restroom": 9.0, "mech": 10.0}[kind]
            rooms.append(r)
            ids.append(r["id"])
        tenants.append({"id": tid, "x0": xa, "x1": xb, "end_cap": cap,
                        "rooms": ids, "east_stack": east})
    return rooms, tenants, ys


def _openings(rooms, walls, pair, tenants, W, D, warnings):
    from . import parts
    by = {r["id"]: r for r in rooms}
    wall = {w["id"]: w for w in walls}
    ops = []
    for tn in tenants:
        sales, stock, rr, jan = (by[i] for i in tn["rooms"])
        xa, xb = tn["x0"], tn["x1"]
        # the storefront: the entrance in the middle, glass either side
        c = round((xa + xb) / 2, 3)
        dw, dh = SF_DOOR
        ops.append({"id": "", "kind": "door", "mark": "", "type": "SF",
                    "wall": "W1", "along": c, "width": dw, "height": dh,
                    "swing": "out", "from_room": "EXT",
                    "to_room": sales["id"], "exit": True,
                    "tenant": tn["id"]})
        for lo, hi in ((xa + 1.0, c - dw / 2 - 0.75),
                       (c + dw / 2 + 0.75, xb - 1.0)):
            L = hi - lo
            if L < 2.0:
                continue
            k = max(1, int(math.ceil(L / SF_PANE)))
            pw = (L - 0.25 * (k - 1)) / k
            for j in range(k):
                a = lo + j * (pw + 0.25) + pw / 2
                ops.append({"id": "", "kind": "window", "mark": "SF",
                            "type": "SF", "wall": "W1",
                            "along": round(a, 3), "width": round(pw, 3),
                            "height": SF_GLASS_H, "sill": SF_SILL,
                            "room": sales["id"], "tenant": tn["id"]})
        # the service door: the north wall of the stock room
        sx0, _y, sx1, _y1 = stock["rect"]
        w3 = wall["W3"]
        rw, rh = REAR_DOOR
        a = parts.place(ops, w3, W - (sx0 + sx1) / 2, rw, lo=W - sx1 + 0.5,
                        hi=W - sx0 - 0.5)
        if a is None:
            warnings.append(f"{tn['id']}: no room for a service door")
        else:
            ops.append({"id": "", "kind": "door", "mark": "", "type": "A",
                        "wall": "W3", "along": a, "width": rw, "height": rh,
                        "swing": "out", "from_room": "EXT",
                        "to_room": stock["id"], "exit": True,
                        "tenant": tn["id"]})
        # inside: sales -> stock away from the restroom stack, stock ->
        # restroom and stock -> jan / elec
        for frm, to, far in ((sales, stock, True), (stock, rr, False),
                             (stock, jan, False)):
            w = pair.get((frm["id"], to["id"]))
            if w is None:
                warnings.append(f"{to['name']} has no wall to "
                                f"{frm['name']} for a door")
                continue
            L = parts.wall_len(w)
            want = 1.75 + 1.5           # 18 in. past the latch + the wall
            if far and not tn["east_stack"]:
                # the end away from the restroom stack (the wall runs
                # west to east: _shared's order)
                want = L - want
            a = parts.place(ops, w, want, 3.0)
            if a is None:
                warnings.append(f"No room for a door into {to['name']}")
                continue
            ops.append({"id": "", "kind": "door", "mark": "", "type": "B",
                        "wall": w["id"], "along": a, "width": 3.0,
                        "height": 7.0, "swing": "in", "from_room": frm["id"],
                        "to_room": to["id"], "tenant": tn["id"]})
    parts.renumber(ops)
    return ops


def make_grid(W, D, xs, ys):
    """Lines on the exterior walls and the demising walls (bays over 40 ft
    split evenly), and east-west at the back of the sales rooms."""
    from ..grid import _letters
    lines = [0.0]
    for x in xs + [W]:
        a = lines[-1]
        k = max(1, int(math.ceil((x - a) / SPLIT_BAY - 1e-9)))
        lines += [round(a + (x - a) * j / k, 3) for j in range(1, k + 1)]
    yl = [0.0, D] if D <= 50 else [0.0, ys, D]
    bx = [b - a for a, b in zip(lines, lines[1:])]
    return {"x": lines, "y": [round(y, 3) for y in yl],
            "x_labels": [str(i + 1) for i in range(len(lines))],
            "y_labels": _letters(len(yl)), "bay": round(max(bx), 3),
            "speed_bay": None, "assumed": True, "on": "demising walls"}


def tenant_rows(plan):
    """[{id, name, width, gross, net, sales, stock, rooms, end_cap}]: each
    tenant's gross area runs to the demising wall centrelines and the
    outside face of the exterior walls - they add up to the building."""
    D = plan["footprint"]["depth"]
    W = plan["footprint"]["width"]
    by = {r["id"]: r for r in plan["rooms"]}
    out = []
    for tn in plan["strip"]["tenants"]:
        a = 0.0 - 0.25 if tn["x0"] < 0.3 else tn["x0"]
        b = W + 0.25 if tn["x1"] > W - 0.3 else tn["x1"]
        rs = [by[i] for i in tn["rooms"]]
        out.append({"id": tn["id"], "width": round(b - a, 3),
                    "gross": round((b - a) * (D + 0.5), 1),
                    "net": round(sum(r["area"] for r in rs), 1),
                    "sales": round(sum(r["area"] for r in rs
                                       if r["type"] == "sales"), 1),
                    "stock": round(sum(r["area"] for r in rs
                                       if r["type"] == "storage"), 1),
                    "rooms": [r["id"] for r in rs],
                    "end_cap": tn["end_cap"]})
    return out


_USE = {"sales": "mercantile", "storage": "mercantile_storage",
        "restroom": "support", "mech": "storage_mech"}


def make_plan(fields):
    """The strip center plan JSON from the brief's fields."""
    from .. import DISCLAIMER, model, site as site_mod
    from .. import codes
    from . import parts
    occ = "M"
    warnings = list(fields.get("warnings") or [])
    assumed = []
    if int(fields.get("stories") or 1) > 1:
        warnings.append("Multi-story strip retail is a later phase; drawn "
                        "as one story.")
    if fields.get("room_sizes"):
        warnings.append("Room sizes in the brief aren't used for strip "
                        "retail; the bays are sized as a whole.")
    W, D, n, caps, gross = size(fields, warnings, assumed)
    xs = demising(W, n, caps)
    if caps:
        assumed.append(f"{caps} end cap{'s' if caps > 1 else ''} about "
                       f"{CAP:g} times a typical bay")
    rooms, tenants, ys = _make_rooms(W, D, xs, caps)
    tn_of = {r["id"]: r["tenant"] for r in rooms}

    def thick(a, b):
        if tn_of[a["id"]] != tn_of[b["id"]]:
            return DEMISING_T, {"demising": True}
        from ..layout import INT_T
        return INT_T, {}
    walls, pair = parts.walls_for(rooms, W, D, thick)
    openings = _openings(rooms, walls, pair, tenants, W, D, warnings)
    for r in rooms:
        r["use"] = _USE[r["type"]]
    grid = make_grid(W, D, xs, ys)
    spaces = fields.get("parking")
    ratio = None
    if not spaces:
        ratio = PARKING_PER_1000
        spaces = int(math.ceil(gross / 1000.0 * ratio))
        assumed.append(f"{spaces} parking spaces ({ratio:g} per 1,000 SF - "
                       "zoning decides)")
    assumed += [f"typical bay {fmt(W / _units(n, caps))} wide",
                "storefront glass and a 3'-0\" entrance per tenant, a "
                "3'-0\" service door at the rear",
                "8\" demising walls (rating by the design professional)",
                f"{PLATE:g} ft to the roof bearing, {PARAPET:g} ft parapet",
                "structural grid on the demising walls",
                "fully sprinklered (NFPA 13)"]
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
                      "from": "brief"},
        "level": {"name": "L1", "floor_elev": 0.0, "plate_height": PLATE,
                  "slab": 0.42},
        "roof": {"type": "flat", "pitch": 0.25, "ridge_dir": None,
                 "overhang": 0, "parapet": PARAPET},
        "walls": walls, "rooms": rooms, "openings": openings,
        "door_types": {
            "A": "Exterior service door, insulated hollow metal",
            "B": "Interior, solid core, 3'-0\" (ADA 32 in. clear)",
            "SF": "Storefront entrance, aluminum and glass, 3'-0\" "
                  "(assumed)"},
        "window_types": {"SF": "Aluminum storefront glazing (assumed)"},
        "notes": {"general": [], "project": [], "from_ai": False},
        "warnings": warnings,
        "grid": grid,
        "strip": {"tenants": tenants, "typical_bay": [
            round(W / _units(n, caps), 1), D], "end_caps": caps,
            "back_depth": round(D - 0.25 - ys, 2), "sales_depth":
            round(ys - 0.25, 2), "assumed": assumed,
            "elev_note": {"S": "Storefronts on the parking side - glazing, "
                               "entrances and signage band by the design "
                               "professional (assumed).",
                          "N": "Service doors on the rear (delivery) side "
                               "- grades by the civil engineer."}},
    }
    if ratio is not None or fields.get("parking"):
        plan["parking"] = parts.parking(W, spaces, ratio, gross)
    plan["dropped"] = []
    if fields.get("ratio"):
        plan["warnings"].append("A sketch's proportions aren't used for "
                                "strip retail; the bays set the shape.")
    # the building moves back on the lot for the parking field when it
    # has to (site_for, Oct 22); the field widens when that's not enough
    plan["site"], sw = site_mod.site_for(plan, fields.get("lot"))
    wide = site_mod.widen_parking(plan, fields.get("lot"))   # review #10
    if wide is not None:
        sw = wide
    plan["warnings"].extend(w for w in sw if w not in plan["warnings"])
    # the tenant bays beside the rooms (the .genset.json sidecar is this
    # plan): gross area as A-601 measures it and the storefront frontage
    plan["tenant_bays"] = [
        {"id": r["id"], "area_sf": r["gross"], "net_sf": r["net"],
         "frontage_ft": r["width"], "depth_ft": round(D + 0.5, 3),
         "end_cap": r["end_cap"], "rooms": r["rooms"]}
        for r in tenant_rows(plan)]
    plan["code"] = codes.analyze(plan)
    model.validate(plan)
    return plan


def fmt(ft):
    from ..model import fmt_ftin
    return fmt_ftin(round(ft * 2) / 2)


# ---- hooks ------------------------------------------------------------------
def _tenant_loads(plan, rows=None):
    from .. import codes
    rows = rows if rows is not None else codes.occupant_load(plan)
    tn = {r["id"]: r.get("tenant") for r in plan["rooms"]}
    out = {}
    for r in rows:
        k = tn.get(r["room"])
        out[k] = out.get(k, 0) + r["load"]
    return out


def tenant_doors(plan):
    """{tenant: {"front": n, "rear": n, "exits": n}}."""
    out = {t["id"]: {"front": 0, "rear": 0, "exits": 0}
           for t in plan["strip"]["tenants"]}
    tn = {r["id"]: r.get("tenant") for r in plan["rooms"]}
    for o in plan["openings"]:
        if o["kind"] != "door" or o.get("from_room") != "EXT":
            continue
        k = tn.get(o.get("to_room"))
        if k not in out:
            continue
        out[k]["exits"] += 1
        if o["wall"] == "W1":
            out[k]["front"] += 1
        elif o["wall"] == "W3":
            out[k]["rear"] += 1
    return out


def _reached_within(plan, tid):
    """The tenant's rooms reached from its own outside doors through its
    own doors only."""
    from collections import deque
    tn = {r["id"]: r.get("tenant") for r in plan["rooms"]}
    mine = {r for r, k in tn.items() if k == tid}
    start = {o["to_room"] for o in plan["openings"] if o["kind"] == "door"
             and o.get("from_room") == "EXT" and o.get("to_room") in mine}
    adj = {r: set() for r in mine}
    for o in plan["openings"]:
        a, b = o.get("from_room"), o.get("to_room")
        if o["kind"] == "door" and a in mine and b in mine:
            adj[a].add(b)
            adj[b].add(a)
    seen, q = set(start), deque(start)
    while q:
        for nb in adj[q.popleft()]:
            if nb not in seen:
                seen.add(nb)
                q.append(nb)
    return seen, mine


def checks(plan):
    """Self-check lines for a strip center (audit.py adds them)."""
    from ... import codecheck
    from .. import codes
    from ..audit import FAIL, PASS, WARN
    out = []
    W, D = plan["footprint"]["width"], plan["footprint"]["depth"]
    rows = tenant_rows(plan)
    tot = sum(r["gross"] for r in rows)
    gross = (W + 0.5) * (D + 0.5)
    out.append((PASS if abs(tot - gross) < 1.0 else FAIL,
                "Tenant bays add up to the building",
                "" if abs(tot - gross) < 1.0 else
                f"{tot:,.0f} SF of {gross:,.0f} SF"))
    doors = tenant_doors(plan)
    bad = [k for k, d in doors.items() if not d["front"] or not d["rear"]]
    out.append((FAIL if bad else PASS, "Each tenant has a storefront and "
                "a rear door", ", ".join(bad[:8])))
    tn = {r["id"]: r.get("tenant") for r in plan["rooms"]}
    across = [o["mark"] for o in plan["openings"] if o["kind"] == "door"
              and o.get("from_room") in tn and o.get("to_room") in tn and
              tn[o["from_room"]] != tn[o["to_room"]]]
    out.append((FAIL if across else PASS, "No door through a demising wall",
                ", ".join(across[:6])))
    lost = []
    for t in plan["strip"]["tenants"]:
        seen, mine = _reached_within(plan, t["id"])
        lost += [r["name"] for r in plan["rooms"]
                 if r["id"] in mine - seen]
    out.append((FAIL if lost else PASS, "Every tenant room reached from "
                "the tenant's own doors", ", ".join(lost[:4])))
    c = codes.analyze(plan, store=False)
    loads = _tenant_loads(plan, c["rooms"])
    one = codecheck.one_exit_max("M")
    short = [f"{k} ({loads.get(k, 0)} occ., {d['exits']} exits)"
             for k, d in doors.items()
             if d["exits"] < (2 if loads.get(k, 0) > one else 1)]
    out.append((WARN if short else PASS, "Exits per tenant (Table 1006.2.1 "
                "screening)", ", ".join(short[:4]) if short else
                f"two exits where a tenant's load is over {one}; "
                f"largest {max(loads.values() or [0])}"))
    pl = plumbing(plan, loads)
    out.append((WARN if pl["over"] or pl["fx"] is None else PASS,
                "Plumbing fixtures per tenant (IPC 2902.1, M row)",
                pl["detail"]))
    g = plan.get("grid") or {}
    xs = sorted({round(w["a"][0], 3) for w in plan["walls"]
                 if w.get("demising") and abs(w["a"][0] - w["b"][0]) < 1e-6})
    ok = bool(g) and all(any(abs(x - gx) < 1e-6 for gx in g["x"])
                         for x in xs) and abs(g["x"][-1] - W) < 1e-6
    out.append((PASS if ok else FAIL, "Structural grid on the demising "
                "walls", "" if ok else "grid lines off the demising walls"))
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


# IPC 2902.2 (2015 edition onward): separate facilities for each sex are
# not required in a tenant space with a total occupant load of 15 or
# fewer (Exc. 2), nor in a mercantile occupancy with a maximum occupant
# load of 100 or less (Exc. 3). Every strip tenant is M, so Exc. 3 is the
# line; Exc. 2 stays for a tenant of another group
SINGLE_USER_MAX = 15                 # Exc. 2, any group
MERCANTILE_MAX = 100                 # Exc. 3, M
EXC = {"M": ("IPC 2902.2 Exc. 3 (2015+)", MERCANTILE_MAX)}
EXC_ANY = ("IPC 2902.2 Exc. 2 (2015+)", SINGLE_USER_MAX)


def plumbing(plan, loads=None, group="M"):
    """Each tenant's one single-user restroom against IPC Table 2902.1's
    row for the group (codecheck.fixtures): enough where the tenant's
    load is within the 2902.2 exception (one unisex WC - the row asks 1
    per 500 for M); over it the row's per-sex count (2902.1.1) stands.
    {"over": [tenant ids], "fx": the row at the largest load, "need_wc":
    {tenant: WC}, "limit", "cite", "detail": the self-check text}."""
    from ... import codecheck
    from .. import codes
    if loads is None:
        loads = _tenant_loads(plan, codes.analyze(plan, store=False)["rooms"])
    cite, limit = EXC.get(group, EXC_ANY)
    big = max(loads.values() or [0])
    fx = codecheck.fixtures(big, group)
    if fx is None:
        return {"over": [], "fx": None, "need_wc": {}, "limit": limit,
                "cite": cite, "detail": f"UNVERIFIED - no {group} row in "
                "this tool's tables"}
    need = {}
    for k, ld in loads.items():
        need[k] = 1 if ld <= limit else codecheck.fixtures(ld, group)["wc"]
    over = sorted((k for k in need if loads[k] > limit),
                  key=lambda k: int(k[1:]) if k[1:].isdigit() else 0)
    if not over:
        detail = (f"1 single-user restroom each; every tenant's load is "
                  f"{limit} or fewer (largest {big}) - separate facilities "
                  f"not required, {cite}")
    else:
        detail = (f"1 single-user restroom each; {len(over)} of "
                  f"{len(need)} tenants over {limit} occupants (largest "
                  f"{big}, past {cite}) - there the {group} row asks "
                  f"{fx['wc']} WC ({fx['wc_each']} per sex, 2902.1.1)")
    return {"over": over, "fx": fx, "need_wc": need, "limit": limit,
            "cite": cite, "detail": detail}


def validate(plan):
    from .. import model
    tn = plan.get("strip", {}).get("tenants") or []
    ids = {r["id"] for r in plan["rooms"]}
    for t in tn:
        if not set(t["rooms"]) <= ids:
            raise model.PlanError(f"tenant {t['id']} names a room that "
                                  "isn't in the plan")
    g = plan.get("grid")
    if g:
        W, D = plan["footprint"]["width"], plan["footprint"]["depth"]
        if abs(g["x"][-1] - W) > 1e-6 or abs(g["y"][-1] - D) > 1e-6:
            raise model.PlanError("the structural grid doesn't end on the "
                                  "exterior walls")
    return []


def notes(plan):
    st = plan.get("strip") or {}
    n = len(st.get("tenants") or [])
    out = [f"One-story multi-tenant retail building (M), {n} tenant bays, "
           "on a slab on grade; storefronts face the parking.",
           "Each tenant space is shown as a shell with a sales area, stock "
           "room, single-user restroom and janitor / electrical room; "
           "tenant improvements by others.",
           "Demising walls between tenants run to the roof deck; their "
           "fire-resistance rating is by the design professional.",
           "Structural grid, bay sizes and column locations are a starting "
           "point for the structural engineer.",
           "Storefront system, signage band, canopies and the parking "
           "layout to be confirmed with the owner, the civil engineer and "
           "zoning.",
           "Fire sprinklers and fire alarm by the fire protection engineer.",
           "Code summary on the code sheet is a screening only; code "
           "analysis by the design professional."]
    if st.get("assumed"):
        out.append("ASSUMED (not in the brief - verify): " +
                   "; ".join(st["assumed"]) + ".")
    return out


def cover(plan, rows):
    from ..grid import describe
    from ..model import fmt_ftin
    st = plan.get("strip") or {}
    tn = st.get("tenants") or []
    pk = plan.get("parking")
    out = []
    for k, v in rows:
        if k in ("Garage", "Porch / deck"):
            continue
        if k == "Construction type":
            v = "by design professional (masonry or steel stud shell " \
                "assumed)"
        elif k == "Code analysis":
            v = "screening on G-003 - by design professional"
        out.append([k, v])
        if k == "Stories":
            bw, bd = st.get("typical_bay") or (0, 0)
            caps = st.get("end_caps") or 0
            out += [["Tenant bays", f"{len(tn)} (T1-T{len(tn)}), typical "
                     f"{fmt(bw)} x {fmt_ftin(bd)}" + (
                         f", {caps} end cap{'s' if caps > 1 else ''}"
                         if caps else "") + " (assumed)"],
                    ["Structural grid", describe(plan["grid"]) +
                     " (assumed)"],
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
    dem = sum(parts.wall_len(w) for w in plan["walls"] if w.get("demising"))
    h = plan["level"]["plate_height"]
    add(G[1], "Demising walls (of the partitions)", q._r(dem), "LF",
        f"centreline, to the roof deck ({h:g} ft); rating by the design "
        "professional")
    glass = sum(o["width"] * o["height"] for o in plan["openings"]
                if o["kind"] == "window" and o["type"] == "SF")
    add(G[2], "Storefront glazing", q._r(glass), "SF", "the storefront "
        "openings, frames not deducted")
    add(G[1], "Interior columns", max(0, len(plan["grid"]["x"]) - 2) *
        max(0, len(plan["grid"]["y"]) - 2), "EA",
        "at the grid intersections (assumed grid)")
    pk = plan.get("parking")
    if pk:
        W = plan["footprint"]["width"]
        add(G[0], f"Parking stalls ({pk['spaces']})", pk["spaces"], "EA",
            f"of them {pk['accessible']} accessible, {pk['van']} van")
        add(G[0], "Parking field paving (assumed layout)",
            q._r(parts.field_width(pk, W) * (pk["depth"] - parts.WALK)),
            "SF", parts.field_words(pk, "the building's length x the parking rows"))
        add(G[0], "Storefront walk", q._r((W + 0.5) * parts.WALK), "SF",
            f"{parts.WALK:g} ft wide, the building's length")
    from .. import site as _site
    sq = _site.site_quantities(plan)
    if sq.get("walk_sf"):
        add(G[0], "Walk to the street (assumed)", q._r(sq["walk_sf"]),
            "SF", "the 5 ft walk drawn on AS-101")
    return out


def typical_tenant(plan):
    """The tenant the enlarged plan shows: an inside bay (demising walls
    both sides) that isn't an end cap, else the first."""
    tn = plan["strip"]["tenants"]
    W = plan["footprint"]["width"]
    inside = [t for t in tn if not t["end_cap"] and t["x0"] > 0.3 and
              t["x1"] < W - 0.3]
    return (inside or [t for t in tn if not t["end_cap"]] or tn)[0]


def bay_subplan(plan):
    """A-102: the typical tenant bay as a plan of its own (parts.part_plan)
    - its rooms, its demising walls and its doors and storefront."""
    from . import parts
    t = typical_tenant(plan)
    W, D = plan["footprint"]["width"], plan["footprint"]["depth"]
    box = (0.0 if t["x0"] < 0.3 else t["x0"], 0.0,
           W if t["x1"] > W - 0.3 else t["x1"], D)
    rooms = [r for r in plan["rooms"] if r["id"] in set(t["rooms"])]
    return parts.part_plan(plan, box, rooms)


def tenant_table_rows(plan):
    """[[tenant, width, gross SF, net SF, sales SF, stock SF, end cap]]
    and a total row - the A-601 tenant area schedule."""
    rows = tenant_rows(plan)
    out = [[r["id"], fmt(r["width"]), f"{r['gross']:,.0f}",
            f"{r['net']:,.0f}", f"{r['sales']:,.0f}", f"{r['stock']:,.0f}",
            "YES" if r["end_cap"] else ""] for r in rows]
    out.append(["TOTAL", "", f"{sum(r['gross'] for r in rows):,.0f}",
                f"{sum(r['net'] for r in rows):,.0f}",
                f"{sum(r['sales'] for r in rows):,.0f}",
                f"{sum(r['stock'] for r in rows):,.0f}", ""])
    return out


ROOM_COLS = [("NO.", 60, "center"), ("ROOM NAME", 250, "left"),
             ("AREA (SF)", 100, "right"), ("FLOOR", 80, "center"),
             ("BASE", 70, "center"), ("WALLS", 90, "center"),
             ("CEILING", 80, "center"), ("CLG HT", 90, "center")]
ROOM_ROW_H = 15


def _room_columns(plan, part):
    """The room finish rows of an A-601 sheet as columns: [(rows, col)],
    col 0 the left (under the tenant schedule on the first sheet), 1 the
    right - from room_pages, so the sheet list and the drawing agree."""
    from .. import schedules
    from ..sheets import DRAW_Y0, DRAW_Y1, rows_fit
    rows = schedules.room_rows(plan)
    a, b = part["rows"] if part else (0, len(rows))
    rows = rows[a:b]
    y = DRAW_Y0 + 40
    if not part or not part["k"]:
        fit = int((DRAW_Y1 - 140 - (y + 20)) / ROOM_ROW_H) - 1
        return [(rows[:fit], 1), (rows[fit:], 0)]
    col = rows_fit(y + 20, ROOM_ROW_H, DRAW_Y1 - 120)
    return [(rows[:col], 0), (rows[col:], 1)]


def _tenant_table_foot(plan):
    from ..sheets import DRAW_Y0, rows_fit
    y = DRAW_Y0 + 40
    n = len(tenant_table_rows(plan))
    k = rows_fit(y + 20, 16, DRAW_Y0 + 820)
    return y + 20 + 16 * (1 + min(n, k) + (n > k))


def room_pages(plan):
    """[(a, b)]: the room finish rows split over A-601 (the right column
    and under the tenant schedule) and continuation sheets (two full
    columns each). Pure Python."""
    from .. import schedules
    from ..sheets import DRAW_Y0, DRAW_Y1, rows_fit, split_rows
    y = DRAW_Y0 + 40
    right = int((DRAW_Y1 - 140 - (y + 20)) / ROOM_ROW_H) - 1
    left = rows_fit(_tenant_table_foot(plan) + 60 + 12, ROOM_ROW_H,
                    DRAW_Y1 - 120)
    col = rows_fit(y + 20, ROOM_ROW_H, DRAW_Y1 - 120)
    return split_rows(len(schedules.room_rows(plan)), right + left,
                      2 * col)


def schedules_sheet(ctx, page, part=None):
    """A-601: the tenant area schedule (gross to the demising wall
    centrelines and the outside face) and the room finish schedule, in
    two columns when the rooms run long; with a part (sheets.continued)
    only its rooms, a continuation sheet two columns of rooms alone."""
    from .. import draw, schedules
    from ..codes import _cont_note, part_has_next
    from ..draw import DRAW
    plan = ctx["plan"]
    x, y = DRAW.x0 + 20, DRAW.y0 + 40
    cols = ROOM_COLS
    row_h = ROOM_ROW_H
    x2 = x + sum(c[1] for c in cols) + 60
    last = part is None or not part_has_next(part)
    if part is not None and part["k"]:
        draw.text(page, x, y, "ROOM FINISH SCHEDULE (CONTINUED)", 16,
                  bold=True)
        yr, xr = y + 20, x
        for rows, c in _room_columns(plan, part):
            if rows:
                xr = x2 if c else x
                yr = max(yr, draw.table(page, xr, y + 20, cols, rows,
                                        size=8, row_h=row_h,
                                        max_y=DRAW.y1 - 120))
        if last:
            draw.text(page, xr + 410 - 5, yr + 20,
                      f"TOTAL  {schedules.room_total(plan):,.0f} SF", 11,
                      bold=True, align="right")
        _cont_note(page, x, yr + 44, part)
        return
    draw.text(page, x, y, "TENANT AREA SCHEDULE", 16, bold=True)
    tcols = [("TENANT", 90, "center"), ("WIDTH", 110, "center"),
             ("GROSS (SF)", 130, "right"), ("NET (SF)", 120, "right"),
             ("SALES (SF)", 120, "right"), ("STOCK (SF)", 120, "right"),
             ("END CAP", 90, "center")]
    yy = draw.table(page, x, y + 20, tcols, tenant_table_rows(plan), size=9,
                    row_h=16, max_y=DRAW.y0 + 820)
    draw.text(page, x, yy + 16, "Gross: to the demising wall centrelines "
              "and the outside face of the exterior walls (assumed method "
              "- the lease decides how area is measured).", 9,
              color=draw.GREY)
    y1 = yy + 60
    draw.text(page, x2, y, "ROOM FINISH SCHEDULE", 16, bold=True)
    (right, _c), (left, _c0) = _room_columns(plan, part)
    yr = draw.table(page, x2, y + 20, cols, right, size=8, row_h=row_h,
                    max_y=DRAW.y1 - 120)
    if left:                    # the rest under the tenant schedule
        draw.text(page, x, y1, "ROOM FINISH SCHEDULE (CONTINUED)", 12,
                  bold=True)
        yr = max(yr, draw.table(page, x, y1 + 12, cols, left, size=8,
                                row_h=row_h, max_y=DRAW.y1 - 120))
    if last:
        draw.text(page, x2 + 410 - 5, yr + 20,
                  f"TOTAL  {schedules.room_total(plan):,.0f} SF", 11,
                  bold=True, align="right")
    else:
        _cont_note(page, x2, yr + 20, part)


def sheets(plan):
    from .. import sheets as S
    from . import parts
    from .. import ada_plan, codes, schedules
    out = [S.SheetSpec("G-001", "Cover", S.cover),
           S.SheetSpec("G-002", "General Notes", S.general_notes)]
    # a schedule longer than its sheet continues on the next ones (a
    # center of 10+ tenants: the occupant loads, the doors, the scoping)
    out += S.continued(codes.load_pages(plan), "G-003", "Code Summary",
                       "Code Summary (Continued)",
                       lambda ctx, page, pt: codes.sheet(page, ctx["plan"],
                                                         pt))
    out += [S.SheetSpec("AS-101", "Site Plan", S.site_plan, nts=False),
           S.SheetSpec("A-101", "Floor Plan", S.level_plan(0, "Floor Plan"),
                       nts=False),
           S.SheetSpec("A-102", "Enlarged Typical Tenant Bay",
                       parts.part_sheet(
                           bay_subplan, "Enlarged Typical Tenant Bay",
                           "Dimensions to the outside face of the exterior "
                           "walls and the centreline of the demising walls. "
                           "See A-101 for the whole building."),
                       nts=False),
           S.SheetSpec("A-103", "Roof Plan", S.roof_plan, nts=False)]
    out += S.elevation_sheets(plan)
    out.append(S.SheetSpec("A-301", "Building Section", S.section,
                           nts=False))
    out += S.continued(room_pages(plan), "A-601",
                       "Room & Tenant Area Schedules",
                       "Room Finish Schedule (Continued)", schedules_sheet)
    out += S.continued(schedules.door_pages(plan), "A-602",
                       "Door & Window Schedules", "Door Schedule (Continued)",
                       lambda ctx, page, pt: schedules.door_window_sheet(
                           page, ctx["plan"], pt))
    out += [S.SheetSpec("A-701", "Quantity Summary", S.quantity_sheet)]
    out += S.continued(ada_plan.scoping_pages(plan), "A-801",
                       "Accessibility", "Accessibility (Continued)",
                       lambda ctx, page, pt: ada_plan.sheet(page,
                                                            ctx["plan"], pt))
    for series in ("G-", "A-6", "A-8"):
        S.renumber(out, series)
    return out


def scoping(plan, proj):
    """A-801: a shopping center (no elevator exception), one accessible
    entrance per tenancy, and the parking."""
    proj = dict(proj)
    proj["tenant_spaces"] = len(plan["strip"]["tenants"])
    pk = plan.get("parking")
    if pk:
        proj["parking"] = [{"name": "Parking", "total": pk["spaces"]}]
    return proj


def code_lines(plan, c):
    from ... import codecheck
    loads = _tenant_loads(plan, c["rooms"])
    one = codecheck.one_exit_max("M")
    doors = tenant_doors(plan)
    two = sum(1 for k in loads if loads[k] > one)
    big = max(loads.values() or [0])
    fx = codecheck.fixtures(big, "M")
    pl = plumbing(plan, loads)
    return [["Exits per tenant (Table 1006.2.1)",
             f"2 where a tenant's load > {one} ({two} of {len(loads)} "
             "tenants)",
             f"each tenant: storefront + rear door "
             f"({min(d['exits'] for d in doors.values())} min.)"],
            ["Plumbing per tenant (IPC 2902.1, M)",
             (f"1 unisex WC up to {pl['limit']} occ. ({pl['cite']}); "
              f"over: {fx['wc']} WC, {fx['lav']} lav at {big} (largest)")
             if fx else "UNVERIFIED",
             "1 single-user restroom each" + (
                 f" - {len(pl['over'])} tenants over {pl['limit']}: "
                 "VERIFY" if pl["over"] else " - all within 2902.2")]]


TYPE = BuildingType(
    key="strip_retail", label="Strip retail (multi-tenant)",
    occupancies=("M",), default_occ="M",
    sf_range=(4000, 60000), stories_range=(1, 1), ratio=8.0,
    plate_height=PLATE, floor_to_floor=PLATE, ceiling_ht=12.0,
    ext_wall="By design professional",
    roof_default={"type": "flat", "pitch": 0.25, "overhang": 0,
                  "parapet": PARAPET},
    setbacks={"front": 20.0, "side": 15.0, "rear": 25.0},
    ada_use="shopping_center", patterns=PATTERNS, detect=detect, read=read,
    max_w=800.0, max_d=100.0, cover_label="Strip retail center "
    "(multi-tenant)", code_sheet=True,
    needs=(("restroom", "sales"), "Has sales rooms and restrooms"),
    layout=make_plan, checks=checks, sheets=sheets, notes=notes,
    quantities=quantities, validate=validate, cover=cover, scoping=scoping,
    code_lines=code_lines)
