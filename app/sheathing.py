"""Wood structural panel helper (Nov 19, Jon: use APA's published
guidance as a resource): the panel span rating and thickness for a roof,
floor or wall at a framing spacing, and the sheets to buy for a takeoff
area.

How a span rating reads (APA - The Engineered Wood Association,
Engineered Wood Construction Guide, Form E30): a Rated Sheathing panel's
stamp "32/16" means rafters up to 32" on center when used on a roof and
joists up to 16" on center when used as subflooring (under a separate
underlayment); a Rated Sturd-I-Floor panel's "24 oc" means a single-layer
floor on joists up to 24" on center. The thicknesses below are the ones
the guide lists as commonly made for each rating. Roof spans assume the
panel edges are supported (clips or blocking) where the guide asks for
it; check the guide and the drawings' structural notes before ordering -
QuantiSheet picks the smallest rating that covers the spacing, nothing
more.

    pick(use, spacing_in) -> {rating, thickness, use, spacing, note}
    sheets(area_sf, waste_pct=10, panel_sf=32) -> int
    formula(waste_pct=10, panel_sf=32) -> 'ceil(qty * 1.1 / 32)'
"""
import math

SOURCE = ("APA - The Engineered Wood Association, Engineered Wood "
          "Construction Guide (Form E30), span ratings")
USES = ("roof", "subfloor", "single-layer floor", "wall")
SPACINGS = (12, 16, 19.2, 24, 32, 48)

# Rated Sheathing: (roof span, floor span, rating, thicknesses)
SHEATHING = (
    (24, 0, "24/0", ('3/8"', '7/16"')),
    (24, 16, "24/16", ('7/16"', '15/32"')),
    (32, 16, "32/16", ('15/32"', '1/2"')),
    (40, 20, "40/20", ('19/32"', '5/8"')),
    (48, 24, "48/24", ('23/32"', '3/4"')),
)
# Rated Sturd-I-Floor: (joist spacing, rating, thicknesses)
STURD_I_FLOOR = (
    (16, "16 oc", ('19/32"', '5/8"')),
    (20, "20 oc", ('19/32"', '5/8"')),
    (24, "24 oc", ('23/32"', '3/4"')),
    (32, "32 oc", ('7/8"', '1"')),
    (48, "48 oc", ('1-3/32"', '1-1/8"')),
)
# wall sheathing: the stud spacing a rating covers
WALL = ((16, "16/0 or more", ('5/16"', '3/8"')),
        (24, "24/0 or more", ('3/8"', '7/16"')))


class SheathingError(ValueError):
    pass


def pick(use, spacing_in):
    """The smallest rating that covers `spacing_in` for `use`."""
    try:
        s = float(spacing_in)
    except (TypeError, ValueError):
        raise SheathingError("Give the framing spacing in inches.")
    if s <= 0:
        raise SheathingError("Give the framing spacing in inches.")
    use = str(use or "").lower()
    if use == "roof":
        for roof, _floor, rating, th in SHEATHING:
            if roof >= s:
                return _out(rating, th, use, s, "Rated Sheathing, roof span "
                            "(first number of the rating)")
    elif use == "subfloor":
        for _roof, floor, rating, th in SHEATHING:
            if floor and floor >= s:
                return _out(rating, th, use, s, "Rated Sheathing used as "
                            "subfloor under a separate underlayment (second "
                            "number of the rating)")
    elif use == "single-layer floor":
        for span, rating, th in STURD_I_FLOOR:
            if span >= s:
                return _out(rating, th, use, s, "Rated Sturd-I-Floor, one "
                            "layer (subfloor and underlayment)")
    elif use == "wall":
        for span, rating, th in WALL:
            if span >= s:
                return _out(rating, th, use, s, "Rated Sheathing on studs")
    else:
        raise SheathingError(f"Use one of: {', '.join(USES)}.")
    raise SheathingError(f"No standard rating covers {s:g}\" on center for "
                         f"a {use} - check the framing or an engineer.")


def _out(rating, th, use, s, note):
    return {"rating": rating, "thickness": th[0], "thicknesses": list(th),
            "use": use, "spacing": s, "note": note, "source": SOURCE}


def sheets(area_sf, waste_pct=10, panel_sf=32):
    """4x8 panels (32 SF) for `area_sf` with waste, rounded up."""
    a = float(area_sf or 0)
    if a <= 0:
        return 0
    return int(math.ceil(round(a * (1 + float(waste_pct) / 100) /
                               float(panel_sf), 9)))


def formula(waste_pct=10, panel_sf=32):
    """The same as an estimate-line formula off the area (it follows the
    takeoff)."""
    w = 1 + float(waste_pct) / 100
    return f"ceil(qty * {w:g} / {float(panel_sf):g})"


def description(p):
    """'APA Rated Sheathing 32/16, 15/32" - roof at 24" o.c.'"""
    kind = "Rated Sturd-I-Floor" if p["use"] == "single-layer floor" \
        else "Rated Sheathing"
    return (f"APA {kind} {p['rating']}, {p['thickness']} - {p['use']} at "
            f"{p['spacing']:g}\" o.c.")
