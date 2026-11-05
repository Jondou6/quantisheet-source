"""Blank starter templates and EXAMPLE crews (v2 step 4).

Starting points for common trades, so a new estimate isn't a blank page:

  * three estimate templates - commercial building GC, sitework / civil
    utilities, residential / insurance repair: the items, units, cost
    types and quantity formulas off takeoff group placeholders;
  * a civil pay-item list (bid items) with pipe and structure items, and
    civil_fill(): every civil activity made from the takeoff put on its
    pay item, with its pipe / structure material on the order list;
  * EXAMPLE crews (codes EX-...): crew make-up and EXAMPLE production
    rates, no wages or equipment rates (all $0 - "enter your ...").

Every price in them is blank (0) - QuantiSheet ships no prices. Labor
hours per unit and production rates are EXAMPLE round numbers to start
from; replace them with your own history. Nothing is installed until you
ask (Estimating Tools > Estimate Templates), and installing never replaces
a template file or library code you already have.

suggest_bindings() picks takeoff groups for a template's placeholders by
the generic trade words in the template ("door", "manhole"); groups that
something already prices are left alone, and each group goes to one
placeholder only. Always look the suggestion over before applying it.
"""
import os
import re

from . import safedb, templates

MARK = "STARTER - every price is blank (0): fill in your own"
BLANK = "price blank - fill in"
EXN = "EXAMPLE production - replace with your own"
VERSION = 1

# ---- estimate templates --------------------------------------------------

AREA, LEN, CNT = ("area", "sq ft"), ("length", "ft"), ("count", "ea")


def _ph(name, kind, match):
    return {"placeholder": name, "group_type": kind[0],
            "group_unit": kind[1], "match": match}


def _it(desc, code, unit, cost_type, ph=None, formula="", hours=0, crew="",
        note=""):
    it = {"desc": desc, "code": code, "unit": unit, "cost_type": cost_type,
          "mat": "0", "lab": "0", "eqp": "0", "sub": "0", "qty": "0",
          "hours": str(hours), "crew": crew,
          "note": "; ".join(filter(None, [BLANK, note] +
                                   ([f"{hours} h per {unit} is {EXN}"]
                                    if hours else []))),
          "placeholder": "", "group_type": "", "group_unit": "",
          "formula": "", "match": ""}
    if ph:
        it.update(ph, formula=formula or "qty")
    return it


ROOM_NO = r"\b\d{3}[A-Z]?$"


def _gc():
    slab = _ph("Slab area", AREA, r"slab|\bsog\b|concrete")
    floor = _ph("Floor area", AREA, r"floor|room|office|lobby|corridor|hall|"
                r"toilet|restroom|\btlt\b|storage|exam|break|class|" + ROOM_NO)
    ceil = _ph("Ceiling area", AREA, r"ceiling|\bclg\b|\bact\b")
    roof = _ph("Roof area", AREA, r"roof")
    ext = _ph("Exterior wall length", LEN, r"exterior|ext\.? wall|veneer|"
              r"brick|siding|curtain")
    intw = _ph("Interior wall length", LEN, r"partition|interior|int\.? wall|"
               r"wall type|gyp|drywall|stud|wall")
    doors = _ph("Doors", CNT, r"door")
    wins = _ph("Windows", CNT, r"window|storefront|glaz")
    plumb = _ph("Plumbing fixtures", CNT, r"\blav|water closet|\bwc\b|toilet|"
                r"urinal|sink|fixture|bibb|fountain|shower|drinking|mop")
    light = _ph("Light fixtures", CNT, r"light|luminaire|lamp|exit sign")
    dev = _ph("Electrical devices", CNT, r"outlet|receptacle|switch|data|"
              r"device|panel|motor|electrical")
    duct = _ph("Duct runs", LEN, r"duct|\b\d+\s*x\s*\d+\b|supply|return|"
               r"exhaust")
    pipe = _ph("Plumbing pipe runs", LEN, r"pipe|water|sewer|gas|drain|vent|"
               r"waste")
    T = [
        _it("Superintendent", "01 31 13", "wk", "Labor"),
        _it("Temporary facilities", "01 50 00", "mo", "Equipment"),
        _it("Dumpster hauls", "01 74 19", "ea", "Equipment"),
        _it("Permits and fees", "01 41 26", "ls", "Other"),
        _it("Slab concrete", "03 30 00", "cy", "Material", slab,
            "qty * 4 / 12 / 27", note="EXAMPLE 4 in slab - set yours"),
        _it("Slab vapor barrier", "07 26 00", "sf", "Material", slab,
            "qty * 1.1", note="EXAMPLE 10% lap"),
        _it("Slab place and finish", "03 35 00", "sf", "Labor", slab,
            hours=0.01, crew="EX-CARP"),
        _it("Interior wall framing", "09 22 16", "ft", "Material", intw),
        _it("Drywall, both faces", "09 29 00", "sf", "Material", intw,
            "qty * 10 * 2", note="EXAMPLE 10 ft wall, 2 faces - set yours"),
        _it("Drywall hang and finish", "09 29 00", "sf", "Labor", intw,
            "qty * 10 * 2", hours=0.02, crew="EX-CARP"),
        _it("Paint walls", "09 91 00", "sf", "Subcontract", intw,
            "qty * 10 * 2"),
        _it("Exterior wall finish", "07 46 00", "sf", "Subcontract", ext,
            "qty * 12", note="EXAMPLE 12 ft wall - set yours"),
        _it("Acoustic ceiling", "09 51 00", "sf", "Subcontract", ceil),
        _it("Flooring", "09 60 00", "sf", "Material", floor, "qty * 1.05",
            note="EXAMPLE 5% waste"),
        _it("Flooring install", "09 60 00", "sf", "Labor", floor,
            hours=0.02, crew="EX-CARP"),
        _it("Fire sprinkler", "21 10 00", "sf", "Subcontract", floor),
        _it("Doors, frames and hardware", "08 11 00", "ea", "Material",
            doors),
        _it("Door install", "08 11 00", "ea", "Labor", doors, hours=2,
            crew="EX-CARP"),
        _it("Windows / storefront", "08 50 00", "ea", "Subcontract", wins),
        _it("Roofing", "07 50 00", "sq", "Subcontract", roof, "qty / 100"),
        _it("Plumbing fixtures", "22 40 00", "ea", "Subcontract", plumb),
        _it("Plumbing piping", "22 11 00", "ft", "Subcontract", pipe),
        _it("HVAC ductwork", "23 31 00", "ft", "Subcontract", duct),
        _it("HVAC equipment", "23 70 00", "ls", "Subcontract"),
        _it("Light fixtures", "26 51 00", "ea", "Subcontract", light),
        _it("Electrical devices", "26 27 26", "ea", "Subcontract", dev),
        _it("Final cleaning", "01 74 23", "sf", "Labor", floor, hours=0.005,
            crew="EX-CARP"),
    ]
    return T


def _site():
    site = _ph("Site area", AREA, r"site|clear|grub|disturb|limits")
    pave = _ph("Paving area", AREA, r"pav|asphalt|parking|drive")
    walk = _ph("Sidewalk area", AREA, r"sidewalk|walk|pad")
    curb = _ph("Curb length", LEN, r"curb|gutter")
    silt = _ph("Silt fence length", LEN, r"silt|erosion|fence")
    storm = _ph("Storm pipe", LEN, r"storm|\bsd\b|rcp|cmp|culvert|drain")
    san = _ph("Sanitary pipe", LEN, r"sanitary|sewer|\bss\b|force main")
    water = _ph("Water pipe", LEN, r"water|\bwm\b|\bdip\b|fire line")
    mh = _ph("Manholes", CNT, r"manhole|\bmh\b")
    inl = _ph("Storm structures", CNT, r"inlet|catch basin|\bcb\b|basin|"
              r"headwall")
    hyd = _ph("Hydrants and valves", CNT, r"hydrant|valve|\bfh\b|\bgv\b")
    svc = _ph("Services", CNT, r"service|\btap\b|cleanout|meter")
    return [
        _it("Mobilization", "1", "ls", "Other"),
        _it("Clearing and grubbing", "2", "ac", "Subcontract", site,
            "qty / 43560"),
        _it("Silt fence", "3", "ft", "Material", silt),
        _it("Silt fence install", "3", "ft", "Labor", silt, hours=0.02,
            crew="EX-PIPE"),
        _it("Storm pipe material", "5", "ft", "Material", storm),
        _it("Storm pipe install", "5", "ft", "Labor", storm, hours=0.04,
            crew="EX-PIPE"),
        _it("Storm structures", "6", "ea", "Material", inl),
        _it("Storm structure set", "6", "ea", "Labor", inl, hours=4,
            crew="EX-MH"),
        _it("Sanitary pipe material", "7", "ft", "Material", san),
        _it("Sanitary pipe install", "7", "ft", "Labor", san, hours=0.04,
            crew="EX-PIPE"),
        _it("Sanitary manholes", "8", "ea", "Material", mh),
        _it("Manhole set", "8", "ea", "Labor", mh, hours=4, crew="EX-MH"),
        _it("Water pipe material", "9", "ft", "Material", water),
        _it("Water pipe install", "9", "ft", "Labor", water, hours=0.03,
            crew="EX-PIPE"),
        _it("Hydrants and valves", "10", "ea", "Material", hyd),
        _it("Services", "11", "ea", "Subcontract", svc),
        _it("Fine grading", "12", "sy", "Equipment", pave, "qty / 9"),
        _it("Paving base stone", "13", "cy", "Material", pave,
            "qty * 6 / 12 / 27", note="EXAMPLE 6 in base - set yours"),
        _it("Asphalt paving", "13", "sy", "Subcontract", pave, "qty / 9"),
        _it("Sidewalk", "13", "sf", "Subcontract", walk),
        _it("Curb and gutter", "14", "ft", "Subcontract", curb),
        _it("Testing, disinfection and as-builts", "15", "ls", "Other"),
        _it("Traffic control", "1", "ls", "Other"),
    ]


def _repair():
    room = _ph("Room floor area", AREA, r"floor|room|bed|bath|kitchen|"
               r"living|dining|hall|closet|laundry|family|den|" + ROOM_NO)
    wall = _ph("Damaged wall length", LEN, r"wall|partition|drywall")
    ceil = _ph("Ceiling area", AREA, r"ceiling|\bclg\b")
    roof = _ph("Roof area", AREA, r"roof|shingle")
    edge = _ph("Roof edge length", LEN, r"eave|rake|drip|edge|gutter")
    doors = _ph("Doors", CNT, r"door")
    wins = _ph("Windows", CNT, r"window")
    fix = _ph("Fixtures to detach and reset", CNT, r"fixture|toilet|sink|"
              r"vanity|tub|light|fan|outlet|switch")
    return [
        _it("Inspection and documentation", "", "hr", "Labor", hours=1,
            crew="EX-REPAIR"),
        _it("Contents move-out and reset", "", "hr", "Labor", hours=1,
            crew="EX-REPAIR"),
        _it("Water extraction", "", "sf", "Labor", room, hours=0.005,
            crew="EX-REPAIR"),
        _it("Drying equipment", "", "day", "Equipment"),
        _it("Antimicrobial treatment", "", "sf", "Material", room),
        _it("Flood cut and tear out drywall", "", "sf", "Labor", wall,
            "qty * 2", hours=0.01, crew="EX-REPAIR",
            note="EXAMPLE 2 ft flood cut - set yours"),
        _it("Debris haul", "", "load", "Equipment"),
        _it("Drywall", "", "sf", "Material", wall, "qty * 8",
            note="EXAMPLE 8 ft wall - set yours"),
        _it("Drywall hang, tape and finish", "", "sf", "Labor", wall,
            "qty * 8", hours=0.02, crew="EX-REPAIR"),
        _it("Paint walls", "", "sf", "Labor", wall, "qty * 8", hours=0.01,
            crew="EX-REPAIR"),
        _it("Paint ceiling", "", "sf", "Labor", ceil, hours=0.01,
            crew="EX-REPAIR"),
        _it("Remove flooring", "", "sf", "Labor", room, hours=0.01,
            crew="EX-REPAIR"),
        _it("Flooring", "", "sf", "Material", room, "qty * 1.1",
            note="EXAMPLE 10% waste"),
        _it("Flooring install", "", "sf", "Labor", room, hours=0.02,
            crew="EX-REPAIR"),
        _it("Baseboard", "", "ft", "Material", wall),
        _it("Roof tear-off", "", "sq", "Labor", roof, "qty / 100", hours=1,
            crew="EX-ROOF"),
        _it("Shingles", "", "sq", "Material", roof, "qty / 100 * 1.1",
            note="EXAMPLE 10% waste"),
        _it("Underlayment", "", "sq", "Material", roof, "qty / 100"),
        _it("Drip edge", "", "ft", "Material", edge),
        _it("Door replace", "", "ea", "Material", doors),
        _it("Window replace", "", "ea", "Subcontract", wins),
        _it("Detach and reset fixtures", "", "ea", "Labor", fix, hours=0.5,
            crew="EX-REPAIR"),
        _it("Permit", "", "ls", "Other"),
        _it("Supervision", "", "hr", "Labor"),
    ]


def estimate_templates():
    """The three blank starter estimate templates (validated)."""
    out = []
    for name, note, items in (
            ("Starter - Commercial Building GC (blank prices)",
             "Division-by-division GC estimate off the takeoff.", _gc()),
            ("Starter - Sitework and Civil Utilities (blank prices)",
             "Site and utility items; codes are the starter pay item "
             "numbers.", _site()),
            ("Starter - Residential and Insurance Repair (blank prices)",
             "Mitigation, rebuild and roofing items for a repair claim.",
             _repair())):
        out.append(templates.validate({
            "kind": "estimate", "version": templates.VERSION, "name": name,
            "note": f"{MARK}. {note} Labor hours per unit are EXAMPLE "
                    "production rates; formulas use EXAMPLE heights and "
                    "waste - set your own.", "items": items}))
    return out


PAY_ITEMS = [
    ("1", "Mobilization", "LS"),
    ("2", "Clearing and grubbing", "AC"),
    ("3", "Erosion control", "LS"),
    ("4", "Earthwork (excavation and embankment)", "CY"),
    ("5", "Storm drain pipe", "LF"),
    ("6", "Storm structures (inlets, catch basins, headwalls)", "EA"),
    ("7", "Sanitary sewer pipe", "LF"),
    ("8", "Sanitary manholes", "EA"),
    ("9", "Water main", "LF"),
    ("10", "Fire hydrants and valves", "EA"),
    ("11", "Water and sewer services", "EA"),
    ("12", "Fine grading", "SF"),
    ("13", "Paving", "SY"),
    ("14", "Curb and gutter", "LF"),
    ("15", "Testing, disinfection and as-builts", "LS"),
]


def civil_pay_items():
    """The starter civil pay-item list (bid-item template, quantities 0)."""
    return templates.validate({
        "kind": "bid_items", "version": templates.VERSION,
        "name": "Starter - Civil Utilities Pay Items (blank)",
        "note": f"{MARK}. Owner quantities 0 - type the bid form's.",
        "items": [{"no": n, "desc": d, "unit": u, "owner_qty": "0",
                   "weight": "1"} for n, d, u in PAY_ITEMS]})


def _file(tpl):
    return templates.default_file(tpl["name"])


def install(where=None):
    """Write the starter templates to the templates folder (inside the
    data folder), or `where`.
    {"written": [paths], "skipped": [paths already there - kept]}."""
    out = {"written": [], "skipped": []}
    for t in estimate_templates() + [civil_pay_items()]:
        p = os.path.join(where, templates._file_name(t["name"])) if where \
            else _file(t)
        if os.path.exists(p):
            out["skipped"].append(p)
            continue
        out["written"].append(templates.save(t, p))
    return out


# ---- EXAMPLE crews --------------------------------------------------------

def _lab(code, what):
    return {"code": code, "desc": f"EXAMPLE {what} - enter your wage "
            "(blank, $0)", "base": 0, "fringe": 0, "ot_pct": 0, "wc_rate": 0,
            "fica": 0, "unemp": 0, "gl_pct": 0, "other_pct": 0,
            "source": MARK}


def _eqp(code, what):
    return {"code": code, "desc": f"EXAMPLE {what} - enter your rate "
            "(blank, $0)", "class": "", "own_hr": 0, "op_hr": 0,
            "fuel_gph": 0, "rent_month": 0, "hours_month": 176, "use": "own",
            "source": MARK}


def _prod(what, rate, unit, per="hour"):
    return {"what": what, "rate": rate, "unit": unit, "per": per,
            "note": EXN}


def crew_pack():
    """{"labor", "equipment", "crews"} - EXAMPLE crews for the civil
    library: make-up and EXAMPLE production rates, every wage and rate
    $0."""
    labor = [_lab("EX-FMN", "foreman"), _lab("EX-OPR", "equipment operator"),
             _lab("EX-LAB", "laborer"), _lab("EX-PIPE", "pipe layer"),
             _lab("EX-CARP", "carpenter"), _lab("EX-FIN", "finisher"),
             _lab("EX-ROOF", "roofer")]
    eqp = [_eqp("EX-EXC", "excavator"), _eqp("EX-LDR", "loader"),
           _eqp("EX-BOX", "trench box"), _eqp("EX-PLT", "plate compactor"),
           _eqp("EX-DOZ", "dozer"), _eqp("EX-TRK", "pickup truck"),
           _eqp("EX-DRY", "drying equipment set")]

    def crew(code, what, lab, eq, prod):
        return {"code": code, "desc": f"EXAMPLE {what} crew - "
                "production rates are EXAMPLE, wages $0", "labor": lab,
                "equipment": eq, "production": prod, "source": MARK}
    crews = [
        crew("EX-PIPE", "pipe", [["EX-FMN", 1], ["EX-OPR", 2],
                                 ["EX-PIPE", 2], ["EX-LAB", 2]],
             [["EX-EXC", 1], ["EX-LDR", 1], ["EX-BOX", 1], ["EX-PLT", 1],
              ["EX-TRK", 1]],
             [_prod("pipe up to 10 in, 0-6 ft deep", 30, "LF"),
              _prod("pipe 12-18 in", 20, "LF"),
              _prod("pipe over 18 in", 12, "LF")]),
        crew("EX-MH", "manhole / structure",
             [["EX-FMN", 1], ["EX-OPR", 1], ["EX-LAB", 2]],
             [["EX-EXC", 1], ["EX-PLT", 1], ["EX-TRK", 1]],
             [_prod("manhole or inlet set", 0.25, "EA")]),
        crew("EX-CUT", "earthwork", [["EX-OPR", 2], ["EX-LAB", 1]],
             [["EX-EXC", 1], ["EX-DOZ", 1]],
             [_prod("cut and fill", 50, "CY")]),
        crew("EX-GRADE", "fine grading", [["EX-OPR", 1], ["EX-LAB", 1]],
             [["EX-DOZ", 1]], [_prod("fine grading", 3000, "SF")]),
        crew("EX-CARP", "building carpentry",
             [["EX-CARP", 2], ["EX-LAB", 1]], [["EX-TRK", 1]],
             [_prod("drywall hang and finish", 50, "SF"),
              _prod("door install", 0.5, "EA")]),
        crew("EX-REPAIR", "repair / mitigation",
             [["EX-CARP", 1], ["EX-FIN", 1], ["EX-LAB", 1]],
             [["EX-TRK", 1], ["EX-DRY", 1]],
             [_prod("drywall replace", 50, "SF"),
              _prod("paint", 100, "SF")]),
        crew("EX-ROOF", "roofing", [["EX-ROOF", 3], ["EX-LAB", 1]],
             [["EX-TRK", 1]], [_prod("tear-off and re-shingle", 1, "SQ")]),
    ]
    return {"labor": labor, "equipment": eqp, "crews": crews}


def install_crews(confirm, lib=None):
    """Add the EXAMPLE crews' codes your civil library doesn't have yet
    (yours are never replaced). Returns how many records were added.

    v2 step 5: nothing is written unless confirm(question) says Yes -
    the question says how many records go in; Cancel leaves the price
    database byte-for-byte as it was (and makes no backup). A backup copy
    of the database is made first (safedb.backup). The library is read
    read-only (an empty database is not filled with the starter
    library)."""
    from .. import heavy
    if lib is None:
        lib, _empty = safedb.read_civil_library()
    plan = {}
    for kind, recs in crew_pack().items():
        have = lib.get(kind) or {}
        new = [r for r in recs if r["code"] not in have]
        if new:
            plan[kind] = new
    total = sum(len(v) for v in plan.values())
    if not total:
        return 0
    q = (f"Add {total} EXAMPLE record(s) to your price database's civil "
         "library? " + ", ".join(f"{len(v)} {k}" for k, v in plan.items()) +
         " - codes EX-..., wages and equipment rates $0 for you to fill "
         "in. Codes you already have are not changed. A backup copy of "
         "the price database is made first.")
    if not confirm(q):
        return 0
    safedb.backup("example-crews")
    n = 0
    for kind, new in plan.items():
        n += heavy.save_items(kind, new, note="EXAMPLE starter crews - "
                              "fill in your wages and rates")
    return n


# ---- suggest takeoff groups ------------------------------------------------

# an exterior / interior qualifier in a group name (v2 step 6: 'Exterior
# Walls' went to 'Interior wall length', whose pattern has a bare 'wall')
_QUAL = {"exterior": re.compile(r"\bexterior\b|\bext\b\.?", re.I),
         "interior": re.compile(r"\binterior\b|\bint\b\.?|partition", re.I)}
_BARE_WALL = re.compile(r"^walls?$", re.I)


def _quals(text):
    return {q for q, rx in _QUAL.items() if rx.search(text or "")}


@safedb.read_only
def suggest_bindings(doc, tpl, job=None, notes=None):
    """{placeholder: [(name, type, unit), ...]} - takeoff groups whose
    names have the placeholder's trade words, of its takeoff type; groups
    already priced are left out and each group goes to the first
    placeholder (template order) that wants it - except that a name's
    exterior / interior qualifier wins over a bare 'wall' match, and a
    group matched only by a bare 'wall' goes to a placeholder that is
    neither exterior nor interior, or stays unbound (a line in `notes`,
    when given a list)."""
    from . import checks, costlink
    groups = costlink.groups(doc)
    taken = set(checks.priced_groups(doc, job))
    out = {}
    pats = []
    for it in tpl.get("items") or []:
        ph = it.get("placeholder")
        if ph and it.get("match") and ph not in [p[0] for p in pats]:
            pats.append((ph, it.get("group_type"),
                         re.compile(it["match"], re.I)))
    for g in groups:
        k = (g["name"], g["type"], g["unit"])
        if k in taken:
            continue
        gtype = "length" if g["type"] == "polylength" else g["type"]
        cands = []
        for ph, t, rx in pats:
            if t != gtype:
                continue
            hits = [m.group(0) for m in rx.finditer(g["name"])]
            if hits:
                cands.append((ph, all(_BARE_WALL.match(h.strip())
                                      for h in hits)))
        if not cands:
            continue
        want = _quals(g["name"])
        pick = None
        if want:
            # the qualifier says which: never the opposite placeholder
            ok = [c for c in cands if not (_quals(c[0]) - want)]
            pick = next((c[0] for c in ok if _quals(c[0]) & want), None) \
                or next((c[0] for c in ok if not c[1]), None) \
                or next((c[0] for c in ok), None)
        else:
            pick = next((c[0] for c in cands if not c[1]), None)
            if pick is None:
                # only a bare 'wall': a generic wall placeholder, if any
                pick = next((c[0] for c in cands if not _quals(c[0])), None)
                if pick is None and notes is not None:
                    notes.append(
                        f"{g['name']!r} not bound: the name doesn't say "
                        "interior or exterior - pick its placeholder by "
                        "hand")
        if pick:
            out.setdefault(pick, []).append(k)
            taken.add(k)
    return out


# ---- civil: pay items and pipe material -----------------------------------

_PIPE = [("5", r"storm|\bsd\b|rcp|cmp|culvert|drain"),
         ("7", r"sanitary|sewer|\bss\b|force main|\bfm\b"),
         ("9", r"water|\bwm\b|\bdip\b|fire line")]
_EACH = [("6", r"inlet|catch basin|\bcb\b|headwall|storm"),
         ("10", r"hydrant|valve|\bfh\b|\bgv\b"),
         ("11", r"service|\btap\b|meter|cleanout"),
         ("8", r"manhole|\bmh\b")]
_DEPTH = re.compile(r",?\s*(depth unknown|\d+\s*-\s*\d+\s*ft deep|\d+\+?\s*"
                    r"ft deep)", re.I)


def _kind(a):
    u = str(a.get("unit") or "").strip().upper()
    if u in ("LF", "FT"):
        return "pipe"
    if u in ("EA",):
        return "each"
    if u in ("CY",):
        return "volume"
    if u in ("SF", "SQ FT", "SY", "SQ YD"):
        return "area"
    return ""


def _pay_for(a):
    name, kind = str(a.get("name") or ""), _kind(a)
    rules = {"pipe": _PIPE, "each": _EACH}.get(kind)
    if rules:
        return next((no for no, rx in rules if re.search(rx, name, re.I)), "")
    return {"volume": "4", "area": "12"}.get(kind, "")


def material_name(a):
    base = " ".join(_DEPTH.sub("", str(a.get("name") or "")).split())
    base = base.strip(" ,;-")
    if _kind(a) == "pipe" and not re.search(r"pipe|main", base, re.I):
        base += " pipe"
    return base


def civil_fill(job):
    """Put the starter pay items in the civil job (the ones it lacks),
    each activity without a pay item on the matching one (by the pipe /
    structure words in its name), and a material row (price blank) on
    every pipe and structure activity that has no material or material
    quote. {"pay_items_added", "assigned", "materials_added",
    "not_matched": [activity names left without a pay item]}."""
    added = templates.apply_bid_items(job, civil_pay_items())
    have = {p.get("no") for p in job.get("pay_items") or []}
    out = {"pay_items_added": len(added), "assigned": 0,
           "materials_added": 0, "not_matched": []}
    for a in job.get("activities") or []:
        if not a.get("pay_item"):
            no = _pay_for(a)
            if no and no in have:
                a["pay_item"] = no
                out["assigned"] += 1
            else:
                out["not_matched"].append(a.get("name", ""))
        quoted = any(q.get("use") and q.get("kind") != "sub"
                     for q in a.get("quotes") or [])
        if a.get("materials") or quoted or not (
                _kind(a) == "pipe" or (_kind(a) == "each" and _pay_for(a))):
            continue                       # every pipe; known structures
        a["materials"] = [{"desc": material_name(a),
                           "unit": "LF" if _kind(a) == "pipe" else "EA",
                           "qty_per": "1", "cost": "0",
                           "code": a.get("pay_item", ""), "note": BLANK}]
        out["materials_added"] += 1
    return out
