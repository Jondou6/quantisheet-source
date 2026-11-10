"""Concrete and brick / block calculators (Estimate tab, Oct 20).

Plain math, no Qt (calculators_ui.py is the dialog). Every rule of thumb is
a named default the user can change in the dialog; nothing here is a code
requirement.

Concrete: slab, footing, wall, round column, square pier, steps -> cubic
yards (and cubic feet), with waste, the order rounded up to 1/4 yard, and
truckloads (10 cy). Ready-mix is priced by the yard, so there are no bags
(Jon, Oct 22).

Masonry: wall area less openings -> units from the unit's size and joint
(modular brick 6.86 / sf, 8x8x16 CMU 1.125 / sf), with waste; mortar bags
and sand from per-1,000-unit rates; for CMU, grout in cubic yards - solid
grouted, or cells grouted at a spacing, plus bond beams (Jon, Oct 22).

Roofing: plan area and pitch (or sloped area) -> squares with waste, and
the usual order lines (shingle bundles, underlayment, ice & water, starter,
ridge cap, drip edge) from typed eave / rake / ridge / hip / valley
lengths. All from typed numbers; nothing aerial (roof.py is the plan
takeoff).
"""
import math
from .dmoney import c2 as _c2

CY = 27.0                          # cu ft in a cubic yard

TRUCK_CY = 10.0

SHAPES = ("slab", "footing", "wall", "column", "pier", "steps")


def _pos(v, name):
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{name}: not a number")
    if not math.isfinite(f) or f < 0:
        raise ValueError(f"{name}: must be 0 or more")
    return f


def concrete_cf(shape, **d):
    """Cubic feet of one piece. Lengths in feet, thicknesses in inches:
    slab(length, width, thick_in); footing(length, width_in, depth_in);
    wall(length, height, thick_in); column(dia_in, height);
    pier(side_in, height); steps(width, rise_in, run_in, count)."""
    g = lambda k: _pos(d.get(k, 0), k)                       # noqa: E731
    if shape == "slab":
        return g("length") * g("width") * g("thick_in") / 12
    if shape == "footing":
        return g("length") * g("width_in") / 12 * g("depth_in") / 12
    if shape == "wall":
        return g("length") * g("height") * g("thick_in") / 12
    if shape == "column":
        r = g("dia_in") / 24
        return math.pi * r * r * g("height")
    if shape == "pier":
        s = g("side_in") / 12
        return s * s * g("height")
    if shape == "steps":
        # a solid flight: step k (1..n) is k risers tall, one run deep
        n = int(g("count"))
        rise, run = g("rise_in") / 12, g("run_in") / 12
        return g("width") * run * rise * n * (n + 1) / 2
    raise ValueError(f"unknown shape {shape!r}")


def concrete(shape, qty=1, waste_pct=5.0, **d):
    """{cf, cy, cy_with_waste, order_cy, trucks} for `qty` identical
    pieces. Cubic yards are the result (no bags)."""
    d.pop("bag_lb", None)              # older callers passed a bag size
    cf = concrete_cf(shape, **d) * _pos(qty, "qty")
    w = _pos(waste_pct, "waste_pct")
    cfw = cf * (1 + w / 100)
    cyw = cfw / CY
    # round before ceil so 5.25000000001 stays 5.25
    return {"cf": cf, "cy": cf / CY, "cy_with_waste": cyw,
            "order_cy": math.ceil(round(cyw * 4, 9)) / 4,   # to 1/4 yard
            "trucks": math.ceil(round(cyw / TRUCK_CY, 9)) if cfw else 0}


# masonry units: (length, height, thickness) in inches, actual size
UNITS = {
    "Modular brick": (7.625, 2.25, 3.625),
    "Queen brick": (7.625, 2.75, 3.0),
    "King brick": (9.625, 2.625, 3.0),
    "Utility brick": (11.625, 3.625, 3.625),
    "Engineer modular brick": (7.625, 2.75, 3.625),
    "8x8x16 CMU": (15.625, 7.625, 7.625),
    "6x8x16 CMU": (15.625, 7.625, 5.625),
    "10x8x16 CMU": (15.625, 7.625, 9.625),
    "12x8x16 CMU": (15.625, 7.625, 11.625),
}
# Grout to fill every cell of a hollow CMU wall, cu ft per sq ft of wall,
# by nominal width. Worked out from the Angelus Block "Wall Weights and
# Areas" table (equivalent solid thickness, normal weight units, by grout
# spacing): the empty-unit thickness h solves EST(16" o.c.) - h =
# 3 x (EST(48" o.c.) - h), and solid grout = EST(solid) - h. 8": 7.6 -
# 4.0 = 3.6 in = 0.30 cf/sf. Starting points; units vary by maker.
GROUT_CF_PER_SF = {6: 0.19, 8: 0.30, 10: 0.41, 12: 0.51}
CELL_PITCH_IN = 8.0           # one cell every 8 in along a running bond wall
GROUT_SPACINGS = (16, 24, 32, 40, 48)
GROUT_WASTE_PCT = 10.0
# mortar (bags of masonry cement, 70 lb) and sand (tons) per 1,000 units -
# common starting points; check the supplier's numbers
MORTAR_PER_1000 = {"brick": 7.0, "cmu": 33.0}
SAND_TONS_PER_1000 = {"brick": 0.5, "cmu": 2.5}


def kind_of(unit):
    return "cmu" if "CMU" in unit else "brick"


def units_per_sf(unit, joint_in=0.375, length_in=None, height_in=None):
    if length_in is None or height_in is None:
        length_in, height_in, _ = UNITS[unit]
    j = _pos(joint_in, "joint_in")
    return 144.0 / ((_pos(length_in, "length_in") + j) *
                    (_pos(height_in, "height_in") + j))


def nominal_width(unit):
    """6, 8, 10 or 12 for a CMU name like '8x8x16 CMU', else None."""
    if kind_of(unit) != "cmu":
        return None
    try:
        return int(unit.split("x")[0])
    except (ValueError, IndexError):
        return None


def grout(net_sf, unit="8x8x16 CMU", spacing="solid", bond_beam_lf=0.0,
          waste_pct=GROUT_WASTE_PCT, cf_per_sf=None):
    """Grout for a CMU wall in cubic yards. `spacing` "solid" (every
    cell), "none", or the vertical cell spacing in inches (16, 24, 32,
    40, 48 - cells at that spacing, full height). `bond_beam_lf`: total
    length of grouted bond beam courses (one 8 in course each), counted
    as a solid-grouted 8 in course. Returns {cf_per_sf, cells_cf,
    bond_beam_cf, cf, cy, cy_with_waste, order_cy}."""
    w = nominal_width(unit)
    solid = (_pos(cf_per_sf, "cf_per_sf") if cf_per_sf is not None else
             GROUT_CF_PER_SF.get(w or 8, GROUT_CF_PER_SF[8]))
    net = _pos(net_sf, "net_sf")
    if spacing in (None, "", "none", 0):
        per_sf = 0.0
    elif spacing == "solid":
        per_sf = solid
    else:
        sp = _pos(spacing, "spacing")
        if sp < CELL_PITCH_IN:
            raise ValueError("spacing: at least 8 in")
        per_sf = solid * CELL_PITCH_IN / sp
    cells = net * per_sf
    # a bond beam course is 8 in tall: a solid-grouted strip 8 in high
    bb = _pos(bond_beam_lf, "bond_beam_lf") * solid * (8.0 / 12.0)
    if spacing == "solid":
        bb = 0.0                       # already full
    cf = cells + bb
    cyw = cf * (1 + _pos(waste_pct, "waste_pct") / 100) / CY
    return {"cf_per_sf": per_sf, "cells_cf": cells, "bond_beam_cf": bb,
            "cf": cf, "cy": cf / CY, "cy_with_waste": cyw,
            "order_cy": math.ceil(round(cyw * 4, 9)) / 4}


def masonry(length, height, unit="Modular brick", openings_sf=0.0,
            waste_pct=5.0, joint_in=0.375, wythes=1, area_sf=None,
            mortar_per_1000=None, sand_per_1000=None, grout_spacing="none",
            bond_beam_lf=0.0, grout_waste_pct=GROUT_WASTE_PCT,
            grout_cf_per_sf=None):
    """Units, mortar and sand for a wall (length x height ft, or area_sf),
    less openings; grout (CY) for CMU. Returns {net_sf, per_sf, units,
    units_with_waste, mortar_bags, sand_tons, kind, grout}; grout is
    grout()'s dict for CMU, None for brick."""
    if area_sf is None:
        area = _pos(length, "length") * _pos(height, "height")
    else:
        area = _pos(area_sf, "area_sf")
    net = max(0.0, area - _pos(openings_sf, "openings_sf"))
    per = units_per_sf(unit, joint_in)
    n = net * per * max(1, int(_pos(wythes, "wythes")))
    nw = math.ceil(n * (1 + _pos(waste_pct, "waste_pct") / 100))
    k = kind_of(unit)
    m = MORTAR_PER_1000[k] if mortar_per_1000 is None else \
        _pos(mortar_per_1000, "mortar_per_1000")
    s = SAND_TONS_PER_1000[k] if sand_per_1000 is None else \
        _pos(sand_per_1000, "sand_per_1000")
    g = None
    if k == "cmu":
        g = grout(net, unit, grout_spacing, bond_beam_lf, grout_waste_pct,
                  grout_cf_per_sf)
    return {"net_sf": net, "per_sf": per, "units": n, "units_with_waste": nw,
            "mortar_bags": math.ceil(nw / 1000 * m) if nw else 0,
            "sand_tons": _c2(nw / 1000 * s), "kind": k, "grout": g}


# ------------------------------------------------------------- roofing
# order rules of thumb - every one is editable in the dialog; check the
# product's own coverage
ROOF_DEFAULTS = {
    "bundles_per_square": 3.0,        # 3-tab / architectural shingles
    "underlay_sq_per_roll": 10.0,     # synthetic underlayment
    "ice_water_lf_per_roll": 66.0,    # 36 in x 66 ft roll
    "ice_water_rows": 1,              # rows along the eaves
    "starter_lf_per_bundle": 100.0,
    "ridge_lf_per_bundle": 30.0,
    "drip_piece_ft": 10.0,
}
MAX_PITCH = 12                       # in 12; the calculator's hard cap
ROOF_KINDS = ("Shingles", "Metal", "Low slope (membrane)")


def slope_factor(pitch):
    """Sloped area (or rafter length) per plan foot at pitch/12."""
    r = _pos(pitch, "pitch")
    if r > MAX_PITCH:                # Jon, Oct 23: 12:12 is the steepest
        raise ValueError(f"pitch: 0 to {MAX_PITCH} (in 12)")
    return math.sqrt(1 + (r / 12.0) ** 2)


def roofing(plan_sf=0.0, pitch=6.0, waste_pct=10.0, sloped_sf=None,
            eave_lf=0.0, rake_lf=0.0, ridge_lf=0.0, hip_lf=0.0,
            valley_lf=0.0, kind="Shingles", **rates):
    """Roofing order quantities. Area: `sloped_sf` if given, else
    plan_sf x slope factor. Lengths are true lengths in feet. Returns
    {factor, sloped_sf, squares, squares_with_waste, order_squares,
    bundles, underlay_rolls, ice_water_rolls, starter_lf, starter_bundles,
    ridge_lf, ridge_bundles, drip_lf, drip_pieces, valley_lf, kind}."""
    r = dict(ROOF_DEFAULTS)
    for k, v in rates.items():
        if k not in r:
            raise ValueError(f"unknown rate {k!r}")
        r[k] = _pos(v, k)
    f = slope_factor(pitch)
    area = (_pos(sloped_sf, "sloped_sf") if sloped_sf is not None
            else _pos(plan_sf, "plan_sf") * f)
    sq = area / 100.0
    sqw = sq * (1 + _pos(waste_pct, "waste_pct") / 100)
    eave, rake = _pos(eave_lf, "eave_lf"), _pos(rake_lf, "rake_lf")
    ridge = _pos(ridge_lf, "ridge_lf") + _pos(hip_lf, "hip_lf")
    valley = _pos(valley_lf, "valley_lf")

    def up(x, per):
        return math.ceil(round(x / per, 9)) if x and per else 0
    out = {"factor": f, "sloped_sf": area, "squares": sq,
           "squares_with_waste": sqw,
           "order_squares": math.ceil(round(sqw * 3, 9)) / 3,  # 1/3 square
           "kind": kind, "valley_lf": valley,
           "underlay_rolls": up(sqw, r["underlay_sq_per_roll"]),
           "ice_water_rolls": up(eave * r["ice_water_rows"] + valley,
                                 r["ice_water_lf_per_roll"]),
           "drip_lf": eave + rake,
           "drip_pieces": up((eave + rake) * 1.05, r["drip_piece_ft"]),
           "starter_lf": 0.0, "starter_bundles": 0, "ridge_lf": ridge,
           "ridge_bundles": 0, "bundles": 0}
    if kind == "Shingles":
        out["bundles"] = math.ceil(round(sqw * r["bundles_per_square"], 9))
        out["starter_lf"] = eave + rake
        out["starter_bundles"] = up(eave + rake, r["starter_lf_per_bundle"])
        out["ridge_bundles"] = up(ridge, r["ridge_lf_per_bundle"])
    return out
