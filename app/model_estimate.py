"""Model (conceptual) estimate: a building priced from a few inputs,
two ways, side by side.

Inputs: building type (Generate Set's types, or a type from your job
history), gross SF, stories, and options - structure (wood / steel /
concrete / pre-engineered metal building), exterior (brick / EIFS / metal
panel / storefront, % of the exterior walls), roof (low-slope /
pitched), site area and sprinklered or not.

(a) From your job history: the quick $/SF median of your past jobs of the
    type (quick_sf.py), split by division the way those jobs split, then
    each option's factor - a % of the divisions it names or a $ per SF
    into one division - listed with what it changed. The factors are
    yours to edit (kept in settings); the past jobs are taken as the
    baseline (one story, as built).
(b) From quantities: Generate Set lays out a plan for the inputs (in
    memory - nothing is drawn or saved), its quantities (genset
    quantities.rows) are adjusted for the options, and each is priced
    with the job's assemblies (the job's copy first, then your library)
    and cost book - the same pricing as the takeoff. Every quantity
    without a price is listed with the reason.

Either result goes into the Estimate panel as one allowance line per CSI
division (estimate_lines), with a note naming the method and the inputs.
Money is Decimal cents and the lines add up to the result exactly. With
no history and nothing to price the quantities with, it says what is
missing and adds nothing.
"""
import copy
import logging
import math
import re
from decimal import Decimal

from . import csi, dmoney

log = logging.getLogger(__name__)

Z = Decimal("0.00")
STRUCTURES = {"wood": "Wood frame", "steel": "Steel frame",
              "concrete": "Concrete / masonry",
              "pemb": "Pre-engineered metal building"}
ROOFS = {"low": "Low-slope", "pitched": "Pitched"}
EXTERIORS = {"brick": "Brick", "eifs": "EIFS", "metal": "Metal panel",
             "storefront": "Storefront"}
FACTOR_KEY = "model_estimate_factors"        # settings: {factor key: value}
PRICE_KEY = "model_estimate_prices"          # settings: {qty key: source}
PITCH_FACTOR = Decimal("1.118")              # 6:12 slope, when a flat
#                                              plan is priced as pitched

# the options each Generate Set type starts from in the dialog
TYPE_DEFAULTS = {"single_family": {"structure": "wood", "roof": "pitched"},
                 "small_commercial": {"structure": "wood", "roof": "low"},
                 "warehouse": {"structure": "concrete", "roof": "low"},
                 "strip_retail": {"structure": "steel", "roof": "low"},
                 "restaurant": {"structure": "wood", "roof": "low"}}


class ModelError(ValueError):
    pass


# ---- inputs -------------------------------------------------------------------

def gs_types():
    """[(key, label)] of Generate Set's building types."""
    try:
        from .genset import types as gt
        return [(k, gt.get(k).label) for k in gt.keys()]
    except Exception:                                     # noqa: BLE001
        log.warning("Generate Set types unavailable", exc_info=True)
        return []


def _norm(t):
    return " ".join(str(t or "").split()).lower()


def type_key(text):
    """The Generate Set key for a type name or key, or '' for a type only
    your history knows."""
    t = _norm(text)
    for k, label in gs_types():
        if t in (k, _norm(label), _norm(k.replace("_", " "))):
            return k
    return ""


def _pct(v, what):
    if v in (None, ""):
        return Decimal(0)
    if dmoney.bad(v):
        raise ModelError(f"{what}: can't read {v!r} as a percent")
    d = dmoney.D(str(v).replace("%", "")) if isinstance(v, str) else \
        dmoney.D(v)
    if d < 0 or d > 100:
        raise ModelError(f"{what}: {v}% is not between 0 and 100")
    return d


def inputs(btype, sf, stories=1, structure="", exterior=None, roof="",
           site_sf=None, sprinklered=False):
    """The model's inputs, checked (ModelError says what's wrong)."""
    label = " ".join(str(btype or "").split())
    if not label:
        raise ModelError("Pick a building type.")
    if dmoney.bad(sf, blank_ok=False) or dmoney.D(sf) <= 0:
        raise ModelError("Enter the building's gross square feet.")
    try:
        n = int(str(stories or 1).strip())
    except ValueError:
        raise ModelError(f"Stories: can't read {stories!r}")
    if not 1 <= n <= 60:
        raise ModelError("Stories: 1 to 60.")
    key = type_key(label)
    d = TYPE_DEFAULTS.get(key, {"structure": "wood", "roof": "low"})
    st = structure or d["structure"]
    if st not in STRUCTURES:
        raise ModelError(f"Structure: one of {', '.join(STRUCTURES)}")
    rf = roof or d["roof"]
    if rf not in ROOFS:
        raise ModelError("Roof: low or pitched")
    ext = {k: _pct((exterior or {}).get(k), f"{EXTERIORS[k]} %")
           for k in EXTERIORS}
    if sum(ext.values()) > 100:
        raise ModelError("The exterior shares add up to more than 100%.")
    site = Decimal(0)
    if site_sf not in (None, ""):
        if dmoney.bad(site_sf) or dmoney.D(site_sf) < 0:
            raise ModelError(f"Site area: can't read {site_sf!r}")
        site = dmoney.D(site_sf)
    labels = dict(gs_types())
    name = labels.get(key, label)
    return {"type": name, "key": key,
            "sf": dmoney.D(sf), "stories": n, "structure": st,
            "exterior": ext, "roof": rf, "site_sf": site,
            "sprinklered": bool(sprinklered),
            "warnings": range_warnings(key, name, dmoney.D(sf), n)}


def range_warnings(key, name, sf, stories):
    """[text] for a Generate Set type whose SF (the whole building) or
    stories are outside what Generate Set plans for it; [] inside the
    range or for a type only your history knows."""
    if not key:
        return []
    try:
        from .genset import types as gt
        lim = gt.limits(key)
    except Exception:                                     # noqa: BLE001
        log.warning("Generate Set limits unavailable", exc_info=True)
        return []
    out = []
    lo, hi = lim["sf"]
    if not lo <= float(sf) <= hi:
        out.append(f"Outside the usual size: Generate Set plans a {name} "
                   f"of {lo:,.0f} to {hi:,.0f} SF; this one is "
                   f"{float(sf):,.0f} SF. Treat the price as a rough "
                   "guide.")
    lo_st, hi_st = lim["stories"]
    if not lo_st <= stories <= hi_st:
        rng = (f"{lo_st} stor{'y' if lo_st == 1 else 'ies'}" if lo_st ==
               hi_st else f"{lo_st} to {hi_st} stories")
        out.append(f"Outside the usual height: Generate Set plans a {name} "
                   f"of {rng}; this one has {stories}.")
    return out


def describe_inputs(inp):
    ext = ", ".join(f"{EXTERIORS[k]} {v.normalize():f}%"
                    for k, v in inp["exterior"].items() if v)
    parts = [inp["type"], f"{float(inp['sf']):,.0f} SF",
             f"{inp['stories']} stor{'y' if inp['stories'] == 1 else 'ies'}",
             STRUCTURES[inp["structure"]].lower(),
             f"{ROOFS[inp['roof']].lower()} roof"]
    if ext:
        parts.append(f"exterior {ext}")
    if inp["site_sf"]:
        parts.append(f"site {float(inp['site_sf']):,.0f} SF")
    parts.append("sprinklered" if inp["sprinklered"] else "not sprinklered")
    return ", ".join(parts)


# ---- (a) from your job history: factors ----------------------------------

# kind: "pct" - % of the named divisions' history amount ("all": every
# division); "per_sf" - $ per building SF into the first division named;
# "per_site_sf" - $ per SF of site outside the building. "fills": only
# when your history has nothing in those divisions (so it isn't counted
# twice). "per": "story" - times each story above the first; "share" -
# times the option's share of the walls.
FACTORS = [
    {"key": "story", "label": "Each story above the first",
     "kind": "pct", "divisions": "all", "value": "3", "per": "story"},
    {"key": "structure_wood", "label": "Structure: wood frame",
     "kind": "pct", "divisions": ["06"], "value": "0"},
    {"key": "structure_steel", "label": "Structure: steel frame",
     "kind": "pct", "divisions": ["05"], "value": "10"},
    {"key": "structure_concrete", "label": "Structure: concrete / masonry",
     "kind": "pct", "divisions": ["03", "04"], "value": "12"},
    {"key": "structure_pemb", "label": "Structure: pre-engineered metal "
     "building", "kind": "pct", "divisions": ["05", "13"], "value": "-10"},
    {"key": "ext_brick", "label": "Exterior: brick (at 100% of the walls)",
     "kind": "per_sf", "divisions": ["04"], "value": "3.00",
     "per": "share"},
    {"key": "ext_eifs", "label": "Exterior: EIFS (at 100% of the walls)",
     "kind": "per_sf", "divisions": ["07"], "value": "1.50",
     "per": "share"},
    {"key": "ext_metal", "label": "Exterior: metal panel (at 100% of the "
     "walls)", "kind": "per_sf", "divisions": ["07"], "value": "1.00",
     "per": "share"},
    {"key": "ext_storefront", "label": "Exterior: storefront (at 100% of "
     "the walls)", "kind": "per_sf", "divisions": ["08"], "value": "4.00",
     "per": "share"},
    {"key": "roof_low", "label": "Roof: low-slope", "kind": "pct",
     "divisions": ["07"], "value": "0"},
    {"key": "roof_pitched", "label": "Roof: pitched", "kind": "pct",
     "divisions": ["07"], "value": "8"},
    {"key": "sprinklers", "label": "Sprinklered (when your history has no "
     "division 21)", "kind": "per_sf", "divisions": ["21"], "value": "3.50",
     "fills": True},
    {"key": "site", "label": "Site work per SF of site outside the "
     "building (when your history has no 31-33)", "kind": "per_site_sf",
     "divisions": ["32", "31", "33"], "value": "1.50", "fills": True},
]
KIND_LABEL = {"pct": "% of division", "per_sf": "$ / building SF",
              "per_site_sf": "$ / site SF"}


def factors():
    """The factors with your values (settings) in "value" (Decimal)."""
    from . import settings
    mine = settings.get(FACTOR_KEY) or {}
    if not isinstance(mine, dict):
        mine = {}
    out = []
    for f in FACTORS:
        g = copy.deepcopy(f)
        v = mine.get(f["key"], f["value"])
        g["value"] = dmoney.D(v) if not dmoney.bad(v) else dmoney.D(
            f["value"])
        g["default"] = dmoney.D(f["value"])
        out.append(g)
    return out


def set_factor(key, value):
    """Your value for one factor (blank: back to the default)."""
    from . import settings
    if key not in {f["key"] for f in FACTORS}:
        raise ModelError(f"unknown factor {key!r}")
    mine = dict(settings.get(FACTOR_KEY) or {})
    if value in (None, ""):
        mine.pop(key, None)
    else:
        if dmoney.bad(value):
            raise ModelError(f"Factor: can't read {value!r} as a number")
        d = dmoney.D(value)
        if not d.is_finite() or abs(d) > 100000:
            raise ModelError(f"Factor: {value!r} is out of range")
        mine[key] = str(d)
    settings.set(FACTOR_KEY, mine)


def history_jobs(inp):
    """Your past jobs of the type (by its name, or its key)."""
    from . import quick_sf
    seen, out = set(), []
    for name in dict.fromkeys([inp["type"], inp["key"],
                               inp["key"].replace("_", " ")]):
        if not name:
            continue
        for j in quick_sf.history(name):
            if j["id"] not in seen:
                seen.add(j["id"])
                out.append(j)
    return out


def _title(d):
    t = csi.DIVISIONS.get(d, "") if d else ""
    return (t[:1].upper() + t[1:]) if t else "Uncoded"


def price_history(inp, jobs=None, facs=None):
    """{"method": "history", "count", "per_sf", "base_total", "effects":
    [{label, division, amount}], "notes", "lines": [{division, title,
    amount}], "total"} or None with no history for the type."""
    from . import quick_sf
    jobs = history_jobs(inp) if jobs is None else jobs
    if not jobs:
        return None
    facs = factors() if facs is None else facs
    base = quick_sf.estimate(inp["type"], inp["sf"], jobs)
    amounts = {x["division"]: x["amount"] for x in base["lines"]}
    have = set(amounts)
    effects, notes = [], list(inp.get("warnings") or [])

    def add(label, d, amt):
        amt = dmoney.cents(amt)
        if amt:
            amounts[d] = amounts.get(d, Z) + amt
            effects.append({"label": label, "division": d, "amount": amt})

    if not inp["sprinklered"] and amounts.get("21"):
        effects.append({"label": "Not sprinklered: division 21 of your "
                        "history left out", "division": "21",
                        "amount": -amounts["21"]})
        amounts["21"] = Z
    active = {"story": inp["stories"] > 1,
              f"structure_{inp['structure']}": True,
              f"roof_{inp['roof']}": True,
              "sprinklers": inp["sprinklered"],
              "site": inp["site_sf"] > 0}
    for k, v in inp["exterior"].items():
        active[f"ext_{k}"] = v > 0
    footprint = inp["sf"] / inp["stories"]
    for f in facs:
        if not active.get(f["key"]) or not f["value"]:
            continue
        divs = f["divisions"]
        val = f["value"]
        if f["kind"] == "pct":
            mult = Decimal(inp["stories"] - 1) if f.get("per") == "story" \
                else Decimal(1)
            targets = sorted(have) if divs == "all" else \
                [d for d in divs if d in have]
            if not targets:
                notes.append(f"{f['label']}: your history has nothing in "
                             f"division {', '.join(divs)} - no change.")
            for d in targets:
                # of the history's own amount, so factors don't compound
                add(f"{f['label']} ({val.normalize():f}%"
                    f"{' x ' + str(mult) if mult != 1 else ''})", d,
                    base_amount(base, d) * val * mult / 100)
            continue
        if f.get("fills") and any(d in have and base_amount(base, d)
                                  for d in divs):
            notes.append(f"{f['label']}: in your history already - not "
                         "added again.")
            continue
        if f["kind"] == "per_sf":
            qty = inp["sf"]
            if f.get("per") == "share":
                share = inp["exterior"][f["key"][4:]]
                qty = qty * share / 100
            add(f"{f['label']}: {dmoney.fmt(val)}/SF x "
                f"{float(qty):,.0f} SF", divs[0], val * qty)
        elif f["kind"] == "per_site_sf":
            qty = inp["site_sf"] - footprint
            if qty <= 0:
                notes.append(f"{f['label']}: the site is no bigger than the "
                             "building footprint - nothing added.")
                continue
            add(f"{f['label']}: {dmoney.fmt(val)}/SF x "
                f"{float(qty):,.0f} SF", divs[0], val * qty)
    lines = [{"division": d, "title": _title(d), "amount": amounts[d]}
             for d in sorted(amounts, key=lambda d: (d == "", d))
             if amounts[d]]
    return {"method": "history", "inputs": inp, "count": base["count"],
            "per_sf": base["per_sf"], "low_per_sf": base["low_per_sf"],
            "high_per_sf": base["high_per_sf"],
            "base_total": base["median"], "base_lines": base["lines"],
            "effects": effects, "notes": notes, "lines": lines,
            "total": sum((x["amount"] for x in lines), Z)}


def base_amount(base, d):
    """The division's amount in the history split (before any factor)."""
    return next((x["amount"] for x in base["lines"] if x["division"] == d),
                Z)


# ---- (b) from quantities: the plan ------------------------------------------

def make_plan(inp):
    """(plan, floors, notes): Generate Set's plan for the inputs, and how
    many times its per-floor quantities count (a type Generate Set draws
    one story only is drawn at SF / stories and its floors counted)."""
    from .genset import layout, types as gt
    if not inp["key"]:
        raise ModelError(f"{inp['type']} is not a Generate Set building "
                         "type, so there is no plan to measure.")
    lim = gt.limits(inp["key"])
    lo_st, hi_st = lim["stories"]
    notes = []
    stories, floors, gross = inp["stories"], 1, float(inp["sf"])
    if stories > hi_st > 1:
        # the type has its own multi-story plans: stacking copies of
        # them is not a plan Generate Set would draw
        raise ModelError(f"Generate Set plans a {inp['type']} of {lo_st} "
                         f"to {hi_st} stories; this one has {stories}.")
    if stories > hi_st:
        floors = stories
        gross = float(inp["sf"]) / stories
        notes.append(f"Generate Set draws a {inp['type']} up to {hi_st} "
                     f"stor{'y' if hi_st == 1 else 'ies'}: planned as one "
                     f"floor of {gross:,.0f} SF, the floor quantities "
                     f"counted {stories} times.")
        stories = 1
    lo, hi = lim["sf"]
    if not lo <= gross <= hi:
        raise ModelError(f"Generate Set plans a {inp['type']} of "
                         f"{lo:,.0f} to {hi:,.0f} SF"
                         f"{' per floor' if floors > 1 else ''}; this one "
                         f"is {gross:,.0f} SF.")
    fields = {"building_type": inp["key"], "gross_sf": gross,
              "stories": stories}
    try:
        plan = layout.make_plan(fields)
    except Exception as e:                                # noqa: BLE001
        raise ModelError(f"Generate Set couldn't lay out the plan: {e}")
    return plan, floors, notes


_FLOOR_GROUPS = ("Framing & walls", "Openings", "Finishes")
_SIZE = re.compile(r"(\d+)'-(\d+)\"?\s*x\s*(\d+)'-(\d+)")


def _q(item, qty, unit, div, measure, words, key, how="", alt=False,
       covered="", measures=None):
    """One model quantity. `measures`: [(measure, qty, unit)] it may be
    priced by, best first (a partition by its length, else its area);
    by default just its own."""
    qty = dmoney.D(qty)
    return {"item": item, "qty": qty, "unit": unit,
            "division": div, "measure": measure, "words": list(words),
            "key": key, "how": how, "alt": alt, "covered": covered,
            "measures": [(m, dmoney.D(v), u) for m, v, u in measures]
            if measures else [(measure, qty, unit)]}


def _floor_words(code):
    c = code.upper()
    if c.startswith("CPT"):
        return ["carpet"]
    if c in ("LVT", "LVP"):
        return ["luxury vinyl", "lvt", "vinyl plank", "vct"]
    if c == "VCT":
        return ["vct"]
    if c in ("CT", "PT"):
        return ["ceramic floor tile", "floor tile", "porcelain"]
    if c == "QT":
        return ["quarry tile", "floor tile"]
    if c == "SC":
        return ["sealed concrete"]
    if c in ("EP", "EPX", "MFR"):
        return ["epoxy", "resinous"]
    if c in ("WD", "HW"):
        return ["wood floor", "hardwood"]
    return [f"floor finish {c.lower()}"]


def _ceiling_words(code):
    c = code.upper()
    if c.startswith("ACT"):
        return ["acoustic ceiling", "2x2 act", "act ceiling"]
    if c.startswith("GWB") or c.startswith("GYP"):
        return ["gypsum board ceiling", "gypsum board", "drywall"]
    if c == "MFR":
        return ["frp", "washable ceiling", "acoustic ceiling"]
    return [f"ceiling {c.lower()}"]


def _base_words(code):
    c = code.upper()
    if c == "RB":
        return ["rubber base", "resilient base", "vinyl base"]
    if c == "WD":
        return ["wood base"]
    if c in ("CT", "QT", "PT"):
        return ["tile base", "rubber base"]
    return [f"base {c.lower()}"]


def _door(item):
    t = item.lower()
    if "cased opening" in t:
        return None, "a cased opening has no door"
    if "walk-in" in t:
        return None, "by the walk-in supplier"
    if "storefront" in t:
        return ("door_sf", ["storefront entrance", "storefront door",
                            "aluminum door", "storefront"]), ""
    if "overhead" in t or "dock door" in t or "drive-in" in t:
        return ("door_oh", ["overhead coiling door", "overhead door",
                            "sectional door", "roll-up"]), ""
    if any(w in t for w in ("hollow metal", "exterior", "service",
                            "receiving")):
        return ("door_hm", ["hollow metal", "exterior door",
                            "metal door"]), ""
    return ("door_int", ["wood door", "interior door", "solid core door"]), \
        ""


def quantities(plan, inp, floors=1):
    """The plan's quantities for the model: Generate Set's rows with the
    options applied (exterior skin and structure, roof style, sprinklers,
    site) - [{item, qty, unit, division, measure, words, key, how, alt,
    covered}]. `words` are what an assembly or cost book item's name is
    matched on, best first; `alt` rows are priced only when the other
    rows of their key aren't; `covered` rows are shown, not priced."""
    from .genset import quantities as gq
    rows = gq.rows(plan)
    out = []
    plate = float((plan.get("level") or {}).get("plate_height") or 10)
    W = float(plan["footprint"]["width"])
    D = float(plan["footprint"]["depth"])
    footprint = Decimal(str(round(W * D, 0)))
    roof_area = None
    paved = Decimal(0)
    has_storefront_sf = any(str(r[1]).lower().startswith("storefront glaz")
                            for r in rows)
    st = inp["structure"]
    for group, item, qty, unit, how in [tuple(r) + ("",) * (5 - len(r))
                                        for r in rows]:
        t = re.sub(r"^l\d+ ", "", str(item).lower())    # "L2 Exterior..."
        n = floors if group in _FLOOR_GROUPS else 1
        q = dmoney.D(qty) * n
        how = str(how or "")
        if n > 1:
            how = (how + "; " if how else "") + f"x {n} floors"
        u = str(unit).upper()
        if t.startswith("slab on grade"):
            out.append(_q(item, q, u, "03", "area",
                          ["slab on grade", "slab"], "slab", how))
            footprint = q
        elif t.startswith("slab concrete"):
            out.append(_q(item, q, u, "03", "volume",
                          ["slab on grade", "slab concrete", "slab"],
                          "slab", how, alt=True))
        elif "footing" in t or "thickened edge" in t:
            out.append(_q(item, q, u, "03", "length",
                          ["strip footing", "footing", "thickened edge"],
                          "footing", how))
        elif "paving" in t:
            paved += q
            out.append(_q(item, q, u, "32", "area",
                          ["asphalt paving", "paving"], "paving", how))
        elif "walk" in t and "walk-in" not in t and u == "SF":
            paved += q
            out.append(_q(item, q, u, "32", "area",
                          ["concrete sidewalk", "sidewalk", "walk"],
                          "walk", how))
        elif t.startswith("parking stalls"):
            out.append(_q(item, q, u, "32", "count",
                          ["parking stall", "striping", "pavement marking"],
                          "stalls", how))
        elif t.startswith("tilt-up wall panels, gross"):
            out.append(_q(item, q, u, "03", "area", [], "ext_wall", how,
                          covered="the net panel area is priced"))
        elif t.startswith("exterior walls") and u == "LF":
            out.append(_q(item, q, u, "06", "length", [], "ext_wall", how,
                          covered="priced as wall area"))
        elif "exterior wall area, net" in t or \
                t.startswith("tilt-up wall panels, net"):
            out.extend(_exterior(item, q, u, inp, how,
                                 tilt="tilt-up" in t))
        elif "partitions" in t and u == "LF" and \
                not t.startswith("demising"):
            area = (q * Decimal(str(plate))).quantize(Decimal(1))
            words = ["2x4", "wood stud partition", "stud partition",
                     "interior wall"] if st == "wood" else \
                ["metal stud", "steel stud", "stud partition",
                 "interior wall"]
            out.append(_q(item, q, u, "06" if st == "wood" else "09",
                          "length", words, "partitions",
                          (how + "; " if how else "") +
                          f"{plate:g} ft high = {area:f} SF",
                          measures=[("length", q, "LF"),
                                    ("area", area, "SF")]))
        elif t.startswith("demising walls"):
            out.append(_q(item, q, u, "09", "length", [], "partitions", how,
                          covered="part of the partitions"))
        elif t.startswith("gypsum board"):
            out.append(_q(item, q, u, "09", "area",
                          ["gypsum board", "drywall"], "gyp", how))
        elif t.startswith("door") or t.startswith("overhead door"):
            got, why = _door(item)
            if got is None:
                out.append(_q(item, q, u, "08", "count", [], "door", how,
                              covered=why))
            else:
                out.append(_q(item, q, u, "08", "count", got[1], got[0],
                              how))
        elif t.startswith("window"):
            sf_ = "storefront" in t
            m = _SIZE.search(how)
            words = ["storefront", "aluminum window", "window"] if sf_ \
                else ["aluminum window", "window"]
            key = "storefront" if sf_ else "window"
            if m:
                a, b, c, d = (int(x) for x in m.groups())
                each = Decimal(a * 12 + b) * Decimal(c * 12 + d) / 144
                area = (q * each).quantize(Decimal(1))
                out.append(_q(f"{item} ({q:f} x {each.normalize():f} SF)",
                              area, "SF", "08", "area", words, key, how,
                              alt=sf_ and has_storefront_sf,
                              measures=[("area", area, "SF"),
                                        ("count", q, "EA")]))
            else:
                out.append(_q(item, q, u, "08", "count", words, key, how,
                              alt=sf_ and has_storefront_sf))
        elif t.startswith("storefront glaz"):
            out.append(_q(item, q, u, "08", "area",
                          ["storefront", "curtain wall", "aluminum window"],
                          "storefront", how))
        elif t.startswith("dock"):
            w = "leveler" if "leveler" in t else "bumper" if "bumper" in t \
                else "seal"
            out.append(_q(item, q, u, "11", "count",
                          [f"dock {w}", "dock"], f"dock_{w}", how))
        elif t.startswith("floor finish"):
            code = str(item).split()[-1]
            if code.upper() == "TBD":
                out.append(_q(item, q, u, "09", "area", [], "floor", how,
                              covered="finish not picked yet"))
            else:
                out.append(_q(item, q, u, "09", "area", _floor_words(code),
                              f"floor_{code.lower()}", how))
        elif t.startswith("base "):
            code = str(item).split()[-1]
            out.append(_q(item, q, u, "09", "length", _base_words(code),
                          f"base_{code.lower()}", how))
        elif t.startswith("ceiling"):
            code = str(item).split()[-1]
            if code.upper() == "EXP":
                out.append(_q(item, q, u, "09", "area", [], "ceiling", how,
                              covered="exposed structure, no ceiling"))
            else:
                out.append(_q(item, q, u, "09", "area",
                              _ceiling_words(code),
                              f"ceiling_{code.lower()}", how))
        elif group == "Roof":
            if t.startswith("roof,") or t.startswith("low-slope roof"):
                roof_area = q, ("gable" if t.startswith("roof,") else "flat")
            elif t.startswith("parapet"):
                out.append(_q(item, q, u, "07", "length",
                              ["parapet", "coping"], "parapet", how))
            elif t.startswith("roof drains"):
                out.append(_q(item, q, u, "22", "count",
                              ["roof drain"], "roof_drain", how))
            elif t.startswith("eaves"):
                out.append(_q(item, q, u, "07", "length",
                              ["roof gutter", "gutters", "downspout"],
                              "gutter", how))
            else:
                out.append(_q(item, q, u, "07", "length" if u == "LF"
                              else "area", [], "roof", how,
                              covered="in the roof area"))
        elif t.startswith("garage slab") or t.startswith("porch slab"):
            out.append(_q(item, q, u, "03", "area",
                          ["slab on grade", "slab"], "slab_garage", how))
        elif t.startswith("garage walls"):
            out.append(_q(item, q, u, "06", "length",
                          ["garage wall", "exterior wall"], "garage_wall",
                          how))
        elif t.startswith("garage roof") or t.startswith("porch roof"):
            out.append(_q(item, q, u, "07", "area",
                          ["asphalt shingle", "shingle", "roofing"],
                          "roof_small", how))
        elif t.startswith("porch posts"):
            out.append(_q(item, q, u, "06", "count", ["porch post", "post"],
                          "posts", how))
        elif t == "deck":
            out.append(_q(item, q, u, "06", "area", ["wood deck", "deck"],
                          "deck", how))
        elif t.startswith("deck guard"):
            out.append(_q(item, q, u, "06", "length",
                          ["guard", "railing"], "guard", how))
        elif t.startswith("stair"):
            out.append(_q(item, q, u, "06" if st == "wood" else "05",
                          "count", ["stair"], "stair", how))
        elif t.startswith("floor framing"):
            out.append(_floor_structure(item, q, inp, how))
        elif t.startswith("interior columns"):
            out.append(_q(item, q, u, "05", "count",
                          ["steel column", "column"], "columns", how))
        elif _extra(t):
            key, div, words = _extra(t)
            out.append(_q(item, q, u, div, "area" if u == "SF" else
                          "length" if u == "LF" else "count", words, key,
                          how))
        else:
            out.append(_q(item, q, u, "", "count", [], "other", how,
                          covered=""))
    # roof, as the option says
    if roof_area is None:
        roof_area = (footprint, "flat")
    area, drawn = roof_area
    if inp["roof"] == "pitched":
        a = area if drawn == "gable" else (area * PITCH_FACTOR).quantize(
            Decimal(1))
        how = "" if drawn == "gable" else \
            "flat plan area x 1.118 (6:12 slope assumed)"
        words = ["standing seam", "metal roof", "asphalt shingle",
                 "shingle", "roofing"] if st == "pemb" else \
            ["asphalt shingle", "shingle", "metal roof", "standing seam",
             "roofing"]
        out.append(_q("Roof, pitched", a, "SF", "07", "area", words,
                      "roof", how))
    else:
        a = area if drawn == "flat" else footprint
        how = "" if drawn == "flat" else "building footprint (flat roof)"
        out.append(_q("Roof, low-slope membrane", a, "SF", "07", "area",
                      ["tpo", "epdm", "membrane roof", "built-up roof",
                       "roofing"], "roof", how))
    # structure above the slab
    if st == "pemb":
        out.append(_q("Pre-engineered metal building system", footprint,
                      "SF", "13", "area", ["pre-engineered", "metal building",
                                           "pemb"], "frame"))
    elif st == "steel":
        out.append(_q("Roof structure, steel joists and deck", footprint,
                      "SF", "05", "area", ["roof deck", "metal deck",
                                           "steel joist"], "frame"))
    elif st == "concrete" and inp["key"] != "warehouse":
        out.append(_q("Roof structure (concrete / masonry building)",
                      footprint, "SF", "05", "area",
                      ["roof deck", "metal deck", "steel joist"], "frame"))
    else:
        out.append(_q("Roof framing", footprint, "SF", "06", "area",
                      ["roof framing", "roof truss", "rafter"], "frame"))
    if floors > 1:
        out.append(_floor_structure(f"Upper floors ({floors - 1})",
                                    footprint * (floors - 1), inp,
                                    "footprint x floors above the first"))
    if inp["sprinklered"]:
        out.append(_q("Fire sprinklers, wet system", inp["sf"], "SF", "21",
                      "area", ["wet sprinkler", "sprinkler"], "sprinkler",
                      "gross SF"))
    if inp["site_sf"] > 0:
        rest = inp["site_sf"] - footprint
        if rest > 0:
            out.append(_q("Site grading (site less building)", rest, "SF",
                          "31", "area", ["fine grading", "grading"],
                          "grading"))
            soft = rest - paved
            if soft > 0:
                out.append(_q("Landscape (site less building and paving)",
                              soft, "SF", "32", "area",
                              ["topsoil", "seeding", "landscap", "sod"],
                              "landscape"))
    return out


# rows some building types add (restaurant kitchen and restrooms...):
# (words in the item, key, division, words to match a price on)
_EXTRAS = (("walk-in", "walkin", "11", ["walk-in cooler", "walk-in"]),
           ("hood fire suppression", "hood_fs", "21",
            ["kitchen hood suppression", "hood suppression"]),
           ("kitchen hood", "hood", "23", ["kitchen hood", "exhaust hood"]),
           ("grease interceptor", "grease", "22", ["grease interceptor"]),
           ("water closet", "wc", "22", ["water closet"]),
           ("lavator", "lav", "22", ["lavatory"]),
           ("urinal", "urinal", "22", ["urinal"]),
           ("service sink", "sink", "22", ["service sink", "mop sink"]),
           ("mop sink", "sink", "22", ["mop sink", "service sink"]),
           ("drinking fountain", "fountain", "22",
            ["drinking fountain", "water cooler"]))


def _extra(t):
    return next(((k, d, w) for x, k, d, w in _EXTRAS if x in t), None)


def _floor_structure(item, q, inp, how=""):
    st = inp["structure"]
    if st == "concrete":
        return _q(item, q, "SF", "03", "area",
                  ["elevated slab", "concrete floor"], "floors", how)
    if st in ("steel", "pemb"):
        return _q(item, q, "SF", "05", "area",
                  ["composite metal deck", "metal deck", "floor deck"],
                  "floors", how)
    return _q(item, q, "SF", "06", "area",
              ["floor framing", "floor joist", "i-joist"], "floors", how)


def _exterior(item, q, u, inp, how, tilt=False):
    """The exterior wall area: its structure / backup, then the finish by
    the exterior shares (the rest as the building is drawn)."""
    st = inp["structure"]
    out = []
    if tilt:
        out.append(_q(item, q, u, "03", "area",
                      ["tilt-up", "concrete wall panel", "concrete wall"],
                      "ext_wall", how))
    elif st == "wood":
        out.append(_q(f"{item} - wood framing", q, u, "06", "area",
                      ["2x6", "exterior wall", "wood stud"], "ext_wall",
                      how))
    elif st == "steel":
        out.append(_q(f"{item} - metal stud backup", q, u, "05", "area",
                      ["metal stud", "steel stud", "exterior wall"],
                      "ext_wall", how))
    elif st == "concrete":
        out.append(_q(f"{item} - CMU / concrete", q, u, "04", "area",
                      ["cmu wall", "concrete masonry", "concrete wall"],
                      "ext_wall", how))
    else:
        out.append(_q(f"{item} - metal building wall panels", q, u, "13",
                      "area", ["metal wall panel", "metal building",
                               "metal panel"], "ext_wall", how))
    used = Decimal(0)
    skins = (("brick", "04", ["brick veneer", "brick"]),
             ("eifs", "07", ["eifs", "exterior insulation"]),
             ("metal", "07", ["metal wall panel", "metal panel",
                              "metal siding"]),
             ("storefront", "08", ["storefront", "curtain wall",
                                   "aluminum window"]))
    for k, div, words in skins:
        share = inp["exterior"][k]
        if not share:
            continue
        used += share
        out.append(_q(f"Exterior {EXTERIORS[k].lower()} "
                      f"({share.normalize():f}% of the walls)",
                      (q * share / 100).quantize(Decimal(1)), "SF", div,
                      "area", words, f"ext_{k}"))
    rest = 100 - used
    if rest > 0 and not tilt and st != "pemb":
        out.append(_q(f"Exterior finish, rest of the walls "
                      f"({rest.normalize():f}%)",
                      (q * rest / 100).quantize(Decimal(1)), "SF", "07",
                      "area", ["siding", "stucco", "exterior finish",
                               "exterior paint"], "ext_rest"))
    return out


# ---- (b) pricing the quantities ---------------------------------------------

_UNIT = {"sf": "sf", "sq ft": "sf", "sqft": "sf", "ft2": "sf",
         "lf": "lf", "ft": "lf", "lin ft": "lf", "ea": "ea", "each": "ea",
         "cy": "cy", "cu yd": "cy", "sq": "sq", "ls": "ls"}


def _unit(u):
    return _UNIT.get(" ".join(str(u or "").lower().split()), str(u or "")
                     .lower())


class _Pricer:
    """The job's assemblies, your library and the job's cost book, ready
    to price quantities the way the takeoff is priced."""

    def __init__(self, doc=None):
        from . import assemblies, settings
        self.job = assemblies.read_job(doc) if doc is not None else \
            {"assemblies": {}, "labor_rate": assemblies.DEFAULT_LABOR_RATE}
        try:
            self.lib = assemblies.library()
        except Exception:                                 # noqa: BLE001
            log.warning("assembly library unavailable", exc_info=True)
            self.lib = {}
        try:
            self.book, self.region, self.as_of = assemblies.job_costbook(
                self.job)
        except Exception:                                 # noqa: BLE001
            log.warning("job cost book unavailable", exc_info=True)
            self.book, self.region, self.as_of = None, None, None
        self.quiet = self.book is not None and not self.job.get("costbook")
        self.rate = float(self.job.get("labor_rate") or 0)
        self.rates = {}
        if self.book is not None:
            try:
                self.rates = dict(self.book.labor_rates(self.region,
                                                        self.as_of))
            except Exception:                             # noqa: BLE001
                self.rates = {}
        self.rates.update(self.job.get("rates") or {})
        mine = settings.get(PRICE_KEY) or {}
        self.map = mine if isinstance(mine, dict) else {}
        self._priced = {}

    def has_prices(self):
        return bool(self.job.get("assemblies") or self.lib or
                    (self.book is not None and self.book.items))

    def assemblies_for(self, measure, word):
        out = []
        for src, items in (("job", self.job.get("assemblies") or {}),
                           ("library", self.lib)):
            for name in sorted(items):
                a = items[name]
                if not isinstance(a, dict) or a.get("measure") != measure:
                    continue
                if word in name.lower():
                    out.append((src, a))
        return out

    def price_assembly(self, a, measure, qty, unit):
        """(Decimal mat, Decimal lab, problem) for qty of assembly a."""
        from . import assemblies, labor
        name = a.get("name", "")
        missing = [k for k in (a.get("inputs") or {})
                   if not assemblies._filled((a.get("props") or {}).get(k))]
        if missing:
            return None, None, (f"assembly {name!r} needs "
                                f"{', '.join(missing)} (Edit Assembly)")
        if name not in self._priced:
            try:
                pa, _probs = assemblies.priced(a, self.book, self.region,
                                               self.as_of, self.quiet)
            except Exception as e:                        # noqa: BLE001
                return None, None, f"assembly {name!r}: {e}"
            self._priced[name] = pa
        pa = self._priced[name]
        v = float(qty)
        meas = {measure: v}
        if measure == "volume" and _unit(unit) == "cy":
            meas = {"volume": v * 27.0}               # assemblies: cu ft
        if measure == "area":
            meas["gross_area"] = v
        try:
            parts = assemblies.compute(pa, meas)
        except Exception as e:                            # noqa: BLE001
            return None, None, f"assembly {name!r}: {e}"
        mat = Decimal(0)
        lab = Decimal(0)
        for p in parts:
            mat += dmoney.D(round(p["material"], 6))
            cr = None
            if p.get("crew"):
                try:
                    cr = labor.crew_rate(p["crew"], self.rates)
                except Exception:                         # noqa: BLE001
                    cr = None
            rate = cr if cr is not None else self.rate
            lab += dmoney.D(round(p["labor_hours"] * rate, 6))
        return dmoney.cents(mat), dmoney.cents(lab), ""

    def book_items_for(self, word, unit):
        if self.book is None:
            return []
        out = []
        for code in sorted(self.book.items):
            it = self.book.items[code]
            if word in str(it.get("desc", "")).lower() and \
                    _unit(it.get("unit")) == _unit(unit):
                out.append(code)
        return out

    def price_book(self, code, qty):
        from . import estimate_lines
        try:
            ln = estimate_lines.from_book(self.book, code, self.region,
                                          self.as_of, self.job, qty=qty)
            p = estimate_lines.price(ln)
        except Exception as e:                            # noqa: BLE001
            return None, f"cost book {code}: {e}"
        return p["ext"], ""

    def _find(self, name):
        return (self.job.get("assemblies") or {}).get(name) or \
            self.lib.get(name)

    def candidates(self, q):
        """[(kind, assembly or code, measure, qty, unit)] in the order
        they're tried: your pick for the quantity, then by its words."""
        out, tried = [], []
        forced = self.map.get(q["key"])
        if isinstance(forced, str) and forced.startswith("assembly:"):
            a = self._find(forced[9:])
            if a is None:
                tried.append(f"your pick {forced[9:]!r} is not in the "
                             "assemblies")
            else:
                m = next((x for x in q["measures"]
                          if x[0] == a.get("measure")), None)
                if m is None:
                    tried.append(f"your pick {a.get('name')!r} is measured "
                                 f"by {a.get('measure')}")
                else:
                    out.append(("assembly", a) + tuple(m))
        elif isinstance(forced, str) and forced.startswith("book:"):
            out.append(("book", forced[5:]) + tuple(q["measures"][0]))
        for w in q["words"]:
            for m in q["measures"]:
                for _src, a in self.assemblies_for(m[0], w):
                    out.append(("assembly", a) + tuple(m))
                for code in self.book_items_for(w, m[2]):
                    out.append(("book", code) + tuple(m))
        return out, tried

    def price(self, q):
        """{"by", "ext": {mat, lab, eqp, sub}, "total", "problem"}."""
        cands, tried = self.candidates(q)
        seen = set()
        for kind, c, measure, qty, unit in cands:
            ident = (kind, c.get("name") if kind == "assembly" else c)
            if ident in seen:
                continue
            seen.add(ident)
            if kind == "assembly":
                mat, lab, why = self.price_assembly(c, measure, qty, unit)
                if why:
                    tried.append(why)
                    continue
                ext = {"mat": mat, "lab": lab, "eqp": Z, "sub": Z}
                by = f"assembly {c.get('name')}"
            else:
                if self.book is None or self.book.get(c) is None:
                    tried.append(f"cost book item {c} not found")
                    continue
                ext, why = self.price_book(c, qty)
                if why:
                    tried.append(why)
                    continue
                by = f"{self.book.name} {c}"
            if unit != q["unit"]:
                by += f" (as {qty:f} {unit})"
            tot = sum(ext.values(), Z)
            if not tot:
                tried.append(f"{by} prices it at $0")
                continue
            return {"by": by, "ext": ext, "total": tot, "problem": ""}
        if not q["words"]:
            why = "no pricing rule for this quantity"
        elif tried:
            why = "; ".join(dict.fromkeys(tried))[:300]
        else:
            what = " or ".join(dict.fromkeys(
                {"area": "an area", "length": "a length",
                 "count": "a count", "volume": "a volume"}.get(m, m)
                for m, _v, _u in q["measures"]))
            why = (f"no {what} assembly or cost book item named like "
                   f"'{q['words'][0]}'")
        return {"by": "", "ext": None, "total": Z, "problem": why}


def price_quantities(inp, doc=None, pricer=None):
    """{"method": "quantities", "rows": [quantity + {"by", "ext", "total",
    "problem", "status"}], "unpriced": [rows], "lines": [{division, title,
    ext: {mat, lab, eqp, sub}, amount}], "total", "notes", "error"}.
    "error" (and no lines) when there's no plan or nothing to price
    with."""
    res = {"method": "quantities", "inputs": inp, "rows": [],
           "unpriced": [], "lines": [], "total": Z, "notes": [],
           "error": ""}
    res["notes"] += list(inp.get("warnings") or [])
    try:
        plan, floors, notes = make_plan(inp)
    except ModelError as e:
        res["error"] = str(e)
        return res
    res["notes"] += notes
    pricer = pricer or _Pricer(doc)
    rows = quantities(plan, inp, floors)
    if not pricer.has_prices():
        res["error"] = ("No assemblies and no cost book to price the "
                        "quantities with: add assemblies (Assembly Library) "
                        "or pick a cost book (Cost Books).")
    keys_priced = set()
    for q in rows:
        r = dict(q)
        if q["covered"] or not q["qty"]:
            r.update(by="", ext=None, total=Z, problem="",
                     status=q["covered"] or "nothing to price")
            res["rows"].append(r)
            continue
        if q["alt"]:
            res["rows"].append(r)               # priced below, if needed
            continue
        r.update(pricer.price(q) if not res["error"] else
                 {"by": "", "ext": None, "total": Z,
                  "problem": "nothing to price with"})
        r["status"] = r["by"] or ""
        if r["ext"] is not None:
            keys_priced.add(q["key"])
        res["rows"].append(r)
    for r in res["rows"]:
        if not r["alt"] or "status" in r:
            continue
        if r["key"] in keys_priced:
            r.update(by="", ext=None, total=Z, problem="",
                     status="covered by the other "
                            f"{r['key'].replace('_', ' ')} line")
            continue
        r.update(pricer.price(r) if not res["error"] else
                 {"by": "", "ext": None, "total": Z,
                  "problem": "nothing to price with"})
        r["status"] = r["by"] or ""
    divs = {}
    for r in res["rows"]:
        if r.get("ext") is None:
            if r.get("problem"):
                res["unpriced"].append(r)
            continue
        d = divs.setdefault(r["division"], {k: Z for k in
                                            ("mat", "lab", "eqp", "sub")})
        for k in d:
            d[k] += r["ext"][k]
    for d in sorted(divs, key=lambda d: (d == "", d)):
        amt = sum(divs[d].values(), Z)
        if amt:
            res["lines"].append({"division": d, "title": _title(d),
                                 "ext": divs[d], "amount": amt})
    res["total"] = sum((x["amount"] for x in res["lines"]), Z)
    if not res["error"] and not res["lines"]:
        res["error"] = ("None of the plan's quantities matched an assembly "
                        "or cost book item with a price.")
    return res


def set_price_source(key, source):
    """Price a quantity (its key) with 'assembly:<name>' or 'book:<code>'
    from now on; blank goes back to matching by name."""
    from . import settings
    mine = dict(settings.get(PRICE_KEY) or {})
    if source:
        mine[str(key)] = str(source)[:200]
    else:
        mine.pop(str(key), None)
    settings.set(PRICE_KEY, mine)


# ---- both, and the lines ----------------------------------------------------

def run(inp, doc=None, jobs=None, pricer=None):
    """{"history": price_history() or None, "quantities":
    price_quantities(), "missing": text when neither priced anything}."""
    hist = price_history(inp, jobs)
    qty = price_quantities(inp, doc, pricer)
    missing = ""
    if hist is None and not qty["lines"]:
        missing = ("Nothing to price this from. Job history: no past "
                   f"{inp['type']} jobs with a building SF in Job Cost "
                   "Feedback (add them in Quick $/SF Estimate's past-jobs "
                   "table). Quantities: " + (qty["error"] or
                                             "no prices.") +
                   " Nothing was added.")
    return {"history": hist, "quantities": qty, "missing": missing,
            "warnings": list(inp.get("warnings") or [])}


def to_lines(res):
    """Allowance lines (estimate_lines.new_line), one per division, for a
    history or a quantities result; [] for None or no lines."""
    from . import estimate_lines
    if not res or not res.get("lines"):
        return []
    inp = res["inputs"]
    text = describe_inputs(inp)
    if res["method"] == "history":
        how = "job history"
        src = f"Model estimate - job history ({res['count']} job(s))"
        note = (f"Model estimate from your job history: median "
                f"{dmoney.fmt(res['per_sf'])}/SF of {res['count']} past "
                f"job(s), with factors. Inputs: {text}.")
    else:
        how = "quantities"
        n = sum(1 for r in res["rows"] if r.get("ext") is not None)
        src = "Model estimate - plan quantities"
        note = (f"Model estimate from a Generate Set plan's quantities "
                f"priced with the job's assemblies / cost book ({n} priced, "
                f"{len(res['unpriced'])} without a price). Inputs: {text}.")
    out = []
    for x in res["lines"]:
        what = (f"Division {x['division']} {x['title']}" if x["division"]
                else "Uncoded")
        ext = x.get("ext") or {"mat": Z, "lab": Z, "eqp": Z,
                               "sub": x["amount"]}
        out.append(estimate_lines.new_line(
            desc=f"Allowance - {what} (model estimate, {how}, "
                 f"{inp['type']}, {float(inp['sf']):,.0f} SF)",
            qty=1, unit="ls",
            code=f"{x['division']} 00 00" if x["division"] else "",
            cost_type="Allowance", mat=ext["mat"], lab=ext["lab"],
            eqp=ext["eqp"], sub=ext["sub"], source=src, note=note))
    return out


def describe_history(res, inp=None):
    if res is None:
        t = inp["type"] if inp else "this type"
        return (f"No past {t} jobs with a building SF in your Job Cost "
                "Feedback history.")
    text = (f"{res['count']} past job(s): median "
            f"{dmoney.fmt(res['per_sf'])}/SF (range "
            f"{dmoney.fmt(res['low_per_sf'])} - "
            f"{dmoney.fmt(res['high_per_sf'])}) = "
            f"{dmoney.fmt(res['base_total'])}")
    if res["effects"]:
        net = sum((e["amount"] for e in res["effects"]), Z)
        text += f"; factors {dmoney.fmt(net)}"
    return text + f". Total {dmoney.fmt(res['total'])}."


def describe_quantities(res):
    if res["error"] and not res["lines"]:
        return res["error"]
    n = sum(1 for r in res["rows"] if r.get("ext") is not None)
    text = (f"{n} plan quantities priced, {len(res['unpriced'])} without a "
            f"price. Total {dmoney.fmt(res['total'])}.")
    return text


def per_sf(res):
    inp = res["inputs"]
    return dmoney.cents(res["total"] / inp["sf"]) if inp["sf"] else Z


def round_up(x):
    return math.ceil(x)
