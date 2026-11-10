"""Wall assemblies from the wall-type legend (accuracy round 5): an
estimator turns each partition / wall type's LF into the materials it is
built of. Quantities only - no prices.

    components(description) -> [component] read from the legend text
    lines(code, lf, height_ft, comps) -> [{name, qty, unit, basis}]

Only what the legend says is built: a layer it doesn't name is not
added. The take-off factors are ordinary estimating practice (a stud at
each spacing plus one per run end, top and bottom track, 4'x8' sheets,
joint compound and screws per SF of board); each line says how it was
worked out.
"""
import math
import re
from .dmoney import c2 as _c2

_STUD = re.compile(
    r"(\d+(?:\s*[- ]\s*\d/\d)?|\d/\d)\s*(?:\"|'')?\s*(?:MTL\.?|METAL|STL\.?|STEEL)"
    r"\s+STUDS?\s*@\s*(\d{1,2})\s*(?:\"|'')?\s*O\.?\s*C", re.I)
_GWB = re.compile(r"(\d/\d|\d+(?:\s*[- ]\s*\d/\d)?)\s*(?:\"|'')?\s*TYPE\s+X\s+"
                  r"GYP(?:SUM)?\s*(?:BOARD|BD\.?|SUM BOARD)?", re.I)
_SIDES = re.compile(r"\b(BOTH|EACH)\s+SIDES?\b", re.I)
_BATT = re.compile(r"\bBATT\s+INSUL", re.I)
_FURR = re.compile(r"(\d/\d|\d+)\s*(?:\"|'')?\s*(?:MTL\.?|METAL)\s+FURRING",
                   re.I)
_RIGID = re.compile(r"(\d+(?:\s*[- ]\s*\d/\d)?)\s*(?:\"|'')?\s*RIGID\s+INSUL",
                    re.I)
_SHEATH = re.compile(r"GLASS\s*MAT\s+GYP(?:SUM)?\s+SHEATHING|GYP(?:SUM)?\s+"
                     r"SHEATHING", re.I)
_VB = re.compile(r"\bVAPOU?R\s+BARRIER\b|\bAIR\s*/\s*VAPOU?R\s+BARRIER\b", re.I)
_CMU = re.compile(r"(\d{1,2})\s*(?:\"|'')?\s*CMU\b", re.I)
_SIDING = re.compile(r"\bCEMENT\s+BOARD\s+SIDING\b|\bFIBER\s+CEMENT\s+SIDING\b",
                     re.I)
_BRICK = re.compile(r"\bBRICK\s+VENEER\b", re.I)

_JOINT_REINF = re.compile(r"\bHORIZONTAL\s+(?:JOINT\s+)?REINFORCEMENT\b",
                          re.I)
_BARE_IN = re.compile(r"(?:^|\s)(4|6|8|10|12)\s*(?:\"|'')(?=\s|$)")

SHEET_SF = 32.0                 # 4' x 8' board
COMPOUND_LB_PER_SF = 0.053      # ready-mix joint compound
SCREWS_PER_SF = 1.33            # 1-1/4" drywall screws
TAPE_FT_PER_SF = 0.8            # joint tape (500' rolls)
CMU_PER_SF = 1.125              # 8x16 block


def _inch(t):
    t = re.sub(r"\s+", " ", t.strip())
    m = re.match(r"^(\d+)\s*[- ]\s*(\d)/(\d)$", t)
    if m:
        return int(m.group(1)) + int(m.group(2)) / int(m.group(3))
    m = re.match(r"^(\d)/(\d)$", t)
    if m:
        return int(m.group(1)) / int(m.group(2))
    return float(t)


def _frac(x):
    whole = int(x)
    rem = round((x - whole) * 8) / 8
    if rem == 0:
        return f"{whole}\""
    num, den = int(rem * 8), 8
    while num % 2 == 0:
        num //= 2
        den //= 2
    return f"{whole}-{num}/{den}\"" if whole else f"{num}/{den}\""


def components(desc):
    """The parts a wall-type description names: [{"kind", ...}]."""
    d = desc or ""
    out = []
    m = _STUD.search(d)
    if m:
        out.append({"kind": "studs", "size_in": _inch(m.group(1)),
                    "oc_in": float(m.group(2))})
    m = _GWB.search(d)
    if m:
        sides = 2 if _SIDES.search(d) else 1
        out.append({"kind": "gwb", "thk_in": _inch(m.group(1)),
                    "sides": sides})
    if _BATT.search(d):
        out.append({"kind": "batt",
                    "where_required": bool(re.search(r"WHERE\s+REQUIRED",
                                                     d, re.I))})
    m = _FURR.search(d)
    if m:
        out.append({"kind": "furring", "size_in": _inch(m.group(1))})
    m = _RIGID.search(d)
    if m:
        out.append({"kind": "rigid", "thk_in": _inch(m.group(1))})
    if _SHEATH.search(d):
        out.append({"kind": "sheathing"})
    if _VB.search(d):
        out.append({"kind": "vapor barrier"})
    m = _CMU.search(d)
    if m:
        out.append({"kind": "cmu", "size_in": int(m.group(1))})
    elif not _STUD.search(d) and _JOINT_REINF.search(d):
        # an exterior wall detail that draws the masonry back-up (joint
        # reinforcement, a bare 8" dimension) without the word CMU: listed
        # for review, never taken off as fact
        m = _BARE_IN.search(d)
        if m:
            out.append({"kind": "cmu", "size_in": int(m.group(1)),
                        "inferred": True})
    if _SIDING.search(d):
        out.append({"kind": "siding"})
    if _BRICK.search(d):
        out.append({"kind": "brick"})
    return out


def lines(code, lf, h, comps, runs=1):
    """Material lines for `lf` LF of wall type `code`, `h` ft high."""
    if not lf or not h or not comps:
        return []
    out = []
    face = lf * h
    tag = f"Wall Type {code}"

    def add(name, qty, unit, basis):
        out.append({"name": f"{tag} - {name}", "qty": round(qty, 1),
                    "unit": unit, "basis": basis})
    gwb_sf = 0.0
    for c in comps:
        k = c["kind"]
        if k == "studs":
            n = math.ceil(lf / (c["oc_in"] / 12.0)) + runs
            add(f"{_frac(c['size_in'])} metal studs @ {c['oc_in']:g}\" OC",
                n * h, "LF", f"{n} studs ({lf:,.1f} LF at {c['oc_in']:g}\" "
                f"OC + 1 per run) x {_c2(h):.2f} ft")
            add(f"{_frac(c['size_in'])} top & bottom track", 2 * lf, "LF",
                f"2 x {lf:,.1f} LF")
        elif k == "gwb":
            gwb_sf = face * c["sides"]
            add(f"{_frac(c['thk_in'])} type X gypsum board", gwb_sf, "SF",
                f"{lf:,.1f} LF x {_c2(h):.2f} ft x {c['sides']} side(s)")
            add("sealant (top and bottom of the board)",
                2 * lf * c["sides"], "LF",
                f"2 x {lf:,.1f} LF x {c['sides']} side(s)")
        elif k == "batt":
            add("batt insulation", face, "SF",
                f"{lf:,.1f} LF x {_c2(h):.2f} ft"
                + (" (legend: where required for sound - check where)"
                   if c.get("where_required") else ""))
        elif k == "furring":
            add(f"{_frac(c['size_in'])} metal furring channels",
                math.ceil(lf / 2.0) * h, "LF",
                f"at 24\" OC over {lf:,.1f} LF x {_c2(h):.2f} ft")
        elif k == "rigid":
            add(f"{_frac(c['thk_in'])} rigid insulation", face, "SF",
                f"{lf:,.1f} LF x {_c2(h):.2f} ft")
        elif k == "sheathing":
            add("glass mat gypsum sheathing", face, "SF",
                f"{lf:,.1f} LF x {_c2(h):.2f} ft")
        elif k == "vapor barrier":
            add("vapor barrier", face, "SF", f"{lf:,.1f} LF x {_c2(h):.2f} ft")
        elif k == "cmu":
            why = (" (the legend draws masonry with joint reinforcement and "
                   f"a {c['size_in']}\" dimension but doesn't name CMU - "
                   "confirm the back-up wall)") if c.get("inferred") else ""
            add(f"{c['size_in']}\" CMU wall", face, "SF",
                f"{lf:,.1f} LF x {_c2(h):.2f} ft" + why)
            add(f"{c['size_in']}\" CMU block", math.ceil(face * CMU_PER_SF),
                "EA", f"{face:,.0f} SF x {CMU_PER_SF} blocks per SF" + why)
            if c.get("inferred"):
                out[-1]["review"] = out[-2]["review"] = True
        elif k == "siding":
            add("cement board siding", face, "SF",
                f"{lf:,.1f} LF x {_c2(h):.2f} ft (the full wall face - take off "
                "any brick wainscot from the elevations)")
    if gwb_sf:
        add("gypsum board 4'x8' sheets", math.ceil(gwb_sf / SHEET_SF),
            "SHEETS", f"{gwb_sf:,.0f} SF / 32 SF")
        add("joint tape (500' rolls)", math.ceil(gwb_sf * TAPE_FT_PER_SF
                                                 / 500.0), "ROLLS",
            f"{gwb_sf:,.0f} SF x {TAPE_FT_PER_SF} LF per SF")
        add("joint compound", math.ceil(gwb_sf * COMPOUND_LB_PER_SF), "LB",
            f"{gwb_sf:,.0f} SF x {COMPOUND_LB_PER_SF} lb per SF")
        add("1-1/4\" drywall screws", math.ceil(gwb_sf * SCREWS_PER_SF), "EA",
            f"{gwb_sf:,.0f} SF x {SCREWS_PER_SF} per SF")
    return out


def thickness_in(desc):
    """The finished thickness (in) an interior wall type's legend builds
    up to - studs + board each side + furring + block (actual size) - or
    None for an exterior type (siding / brick / sheathing, built up from
    a section) or when the legend names no studs or block."""
    comps = components(desc)
    kinds = {c["kind"] for c in comps}
    if kinds & {"siding", "brick", "sheathing"}:
        return None
    if not kinds & {"studs", "cmu"}:
        return None
    t = 0.0
    for c in comps:
        k = c["kind"]
        if k == "studs":
            t += c["size_in"]
        elif k == "gwb":
            t += c["thk_in"] * c["sides"]
        elif k == "furring":
            t += c["size_in"]
        elif k == "cmu" and not c.get("inferred"):
            t += c["size_in"] - 0.375
    return round(t, 3) if t > 0 else None
