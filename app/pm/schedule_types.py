"""What kind of project a drawing set / spec book is, what equipment it
names, and a draft activity list for each kind of project.

Pure Python (no PyMuPDF, no Qt): everything here works on sheet rows
({number, title}), spec sections ({number, title}) and lines of drawing
text, so it can be tested without a PDF.

1. detect(): scores each project type from the evidence - sheet titles
   and numbers, spec section numbers and titles, the drawing text on the
   first sheets (cover, general notes, schedules) and the equipment found -
   and keeps WHY (which sheets, sections and words) so it can be shown.
   Nothing recognized -> "unknown"; a building is never assumed.
2. equipment(): named equipment and its tags ("GEN-1 500 KW DIESEL
   GENERATOR", "ATS-1", "RTU-3", "LIFT STATION PUMPS"), with the kinds
   that are long-lead.
3. template(): the activity list for a type, in the same tuple format as
   autoschedule.TEMPLATE - (key, phase, name, needs, duration(f, s),
   preds) - where `name` may also be a function of the scope, so the
   activities carry the equipment tags.

Every duration and lead time here is a STARTING VALUE (our own rule of
thumb, not vendor data) - check it against quotes and the contract.
"""
import re
from collections import OrderedDict

TYPES = OrderedDict([
    ("new_building", "New building"),
    ("renovation", "Renovation / tenant fit-out"),
    ("standby_generator", "Standby generator / ATS"),
    ("electrical_service", "Electrical service / switchgear"),
    ("hvac_replacement", "HVAC equipment replacement"),
    ("reroof", "Reroof"),
    ("sitework_only", "Sitework / civil only"),
    ("pump_or_lift_station", "Pump / lift station"),
    ("treatment_plant", "Water / wastewater treatment upgrade"),
])
UNKNOWN = "unknown"
BUILDING_TYPES = ("new_building", "renovation")
MIN_SCORE = 2.0

# Lead-ins: short real activities that start with the work before them
# (SS, no lag) and that the next trade waits on (FS) - in place of the
# "starts N days after it starts" lags, which DCMA point 3 holds to <= 5%
# of the links. autoschedule.plan drops one whose own predecessor or whose
# follower is out of the scope (the logic then passes through it as
# finish-to-start). Where the work after a lead-in can follow real work
# finish-to-start instead (DCMA point 4: >= 90% FS), it does: the reroof's
# deck inspection follows the first area torn off, the plant's structure
# excavation follows mobilizing (as the yard piping does) - review T10.
LEAD_INS = {"util_layout", "ext_mockup", "win_mockup", "lv_boxes",
            "elec_layout", "seam_test", "grout"}
UTIL_LAYOUT_NAME = "Utility staking, locates & trench layout"
LV_BOXES_NAME = "Fire alarm & low voltage backboxes & sleeves"

STARTING_VALUES_NOTE = ("Durations and lead times are starting values "
                        "(rules of thumb, not vendor data) - check them "
                        "against quotes and the contract.")


def label(key):
    return TYPES.get(key, "Not recognized")


# ------------------------------------------------------------- evidence rules
def _rx(p):
    return re.compile(p, re.I)


# words in sheet titles / section titles / drawing text: (regex, weight)
_BLDG_TITLES = _rx(r"FLOOR PLAN|REFLECTED CEILING|WALL SECTION|BUILDING "
                   r"SECTION|EXTERIOR ELEVATION|BUILDING ELEVATION|INTERIOR "
                   r"ELEVATION|DOOR SCHEDULE|FINISH SCHEDULE|ENLARGED|STAIR|"
                   r"TOILET|CASEWORK|^ELEVATIONS$")
_STRUCT_BLDG = _rx(r"FOUNDATION PLAN|FRAMING PLAN|ROOF FRAMING|"
                   r"FLOOR FRAMING")

WORDS = {
    "new_building": [(_rx(r"NEW BUILDING|NEW CONSTRUCTION|\bADDITION\b|"
                          r"\b(?:NEW|PROPOSED) (?:(?!(?:EXISTING|AT|ON|TO|IN|"
                          r"OF|FOR|THE|AND|OR|WITH|WORK|FROM|BY)\b)[A-Z-]+ )"
                          r"{0,3}(?:RESIDENCE|HOUSE|HOME|DWELLING|DUPLEX|"
                          r"TOWNHOMES?|APARTMENTS?|BUILDING|FACILITY|FIRE "
                          r"STATION|CLINIC|SCHOOL|WAREHOUSE|CHURCH)\b|"
                          r"SINGLE[- ]FAMILY|GROUND[- ]UP"), 4)],
    "renovation": [(_rx(r"RENOVATION|REMODEL|ALTERATION|TENANT IMPROVEMENT|"
                        r"TENANT FIT|FIT[- ]?OUT|INTERIOR IMPROVEMENT|"
                        r"BUILD[- ]?OUT|REFURBISH"), 6),
                   (_rx(r"REPAIRS? AND IMPROVEMENTS|IMPROVEMENTS TO|"
                        r"REQUIRED REPAIRS|REMOVE AND REPLACE|"
                        r"REMOVE & REPLACE"), 4)],
    "standby_generator": [
        (_rx(r"\bGENERATORS?\b|\bGENSETS?\b|GEN[- ]SET|ENGINE[- ]GENERATOR"),
         5),
        (_rx(r"AUTOMATIC TRANSFER|TRANSFER SWITCH|\bATS\b"), 4),
        (_rx(r"STANDBY POWER|EMERGENCY POWER|STANDBY SYSTEM|"
             r"EMERGENCY SYSTEM"), 3),
        (_rx(r"FUEL TANK|SUB-?BASE TANK|BELLY TANK|DAY TANK|LOAD BANK"), 3),
        (_rx(r"ONE[- ]LINE|SINGLE[- ]LINE"), 1)],
    "electrical_service": [
        (_rx(r"SERVICE (?:UPGRADE|ENTRANCE|REPLACEMENT)|ELECTRICAL SERVICE|"
             r"NEW SERVICE"), 5),
        (_rx(r"SWITCHGEAR|SWITCHBOARD"), 4),
        (_rx(r"UTILITY (?:TRANSFORMER|COORDINATION|SERVICE)|PAD[- ]?MOUNT"
             r"(?:ED)? TRANSFORMER"), 3),
        (_rx(r"ONE[- ]LINE|SINGLE[- ]LINE|RISER DIAGRAM|PANELBOARD|PANEL "
             r"SCHEDULE|MAIN DISTRIBUTION|METER (?:CENTER|BASE|SOCKET)"), 2)],
    "hvac_replacement": [
        (_rx(r"(?:HVAC|MECHANICAL|EQUIPMENT|RTU|CHILLER|BOILER|UNIT) "
             r"REPLACEMENT|REPLACE(?:MENT)? (?:OF )?(?:EXISTING )?(?:RTU|"
             r"ROOF ?TOP|CHILLER|BOILER|AIR HANDL)|HVAC (?:UPGRADE|"
             r"IMPROVEMENT|RENOVATION)"), 6),
        (_rx(r"MECHANICAL DEMOLITION|HVAC DEMOLITION"), 3),
        (_rx(r"\bRTUS?\b|ROOF ?TOP UNIT|CHILLER|BOILER|AIR HANDL|\bAHUS?\b|"
             r"COOLING TOWER|CONDENSING UNIT"), 3),
        (_rx(r"CRANE|RIGGING"), 2)],
    "reroof": [
        (_rx(r"RE-?ROOF|ROOF(?:ING)? REPLACEMENT|ROOF RESTORATION|"
             r"ROOF RECOVER"), 6),
        (_rx(r"TEAR[- ]?OFF|ROOF DEMOLITION|EXISTING ROOF"), 3),
        (_rx(r"ROOF PLAN|ROOF DETAILS|ROOFING"), 2)],
    "sitework_only": [
        (_rx(r"GRADING|PAVING|PAVEMENT|PARKING LOT|SITE IMPROVEMENT|ROADWAY|"
             r"STREET|DRAINAGE|STORM|EROSION|SWPPP|SEDIMENT"), 3),
        (_rx(r"WATER ?MAIN|WATERLINE|SANITARY SEWER|\bSEWER|UTILITY PLAN|"
             r"PLAN AND PROFILE|PLAN & PROFILE|PROFILE"), 3),
        (_rx(r"SITE PLAN|\bCIVIL\b"), 1)],
    "pump_or_lift_station": [
        (_rx(r"LIFT STATION|PUMP STATION|PUMPING STATION|BOOSTER STATION|"
             r"BOOSTER PUMP"), 7),
        (_rx(r"WET ?WELL|VALVE VAULT|SUBMERSIBLE PUMP|PUMP CONTROL PANEL|"
             r"FORCE MAIN"), 4),
        (_rx(r"(?<!HEAT )(?<!SUMP )\bPUMPS?\b"), 2)],
    "treatment_plant": [
        (_rx(r"WASTEWATER TREATMENT|WATER TREATMENT|TREATMENT PLANT|"
             r"TREATMENT FACILITY|\bWWTP\b|\bWWTF\b|\bWTP\b|\bWRF\b|"
             r"WATER RECLAMATION|WATER RESOURCE RECOVERY"), 7),
        (_rx(r"CLARIFIERS?\b|DIGESTERS?\b|HEADWORKS|AERATION BASIN|"
             r"TRICKLING FILTER|OXIDATION DITCH|THICKENER|SBR BASIN"), 5),
        (_rx(r"AERATION|UV DISINFECTION|"
             r"DISINFECTION (?:SYSTEM|BUILDING|FACILITY)|CHLORINE CONTACT|"
             r"FILTRATION|FILTER (?:BUILDING|GALLERY|MEDIA|BED)|SLUDGE|"
             r"BIOSOLIDS|CHEMICAL FEED|BAR SCREEN|FINE SCREEN|GRIT "
             r"(?:REMOVAL|CHAMBER|SYSTEM)|EQUALIZATION BASIN|LAGOON|"
             r"(?:AERATION|PROCESS) BLOWER|BLOWER (?:BUILDING|ROOM)"), 4),
        (_rx(r"\bPLCS?\b|PROGRAMMABLE LOGIC|\bMCCS?\b|MOTOR CONTROL "
             r"CENTER"), 3),
        (_rx(r"SCADA|INSTRUMENTATION|P&ID|PROCESS AND INSTRUMENTATION|"
             r"PROCESS MECHANICAL"), 2)],
}

# boilerplate that every set carries ("verify existing conditions", "N.I.C.",
# "existing to remain"): renovation evidence only when the set also has a
# demolition sheet (or D / AD series sheets, or a selective demolition spec)
_RENO_BOILER = (_rx(r"EXISTING (?:BUILDING|FACILITY|CONDITIONS|WORK|"
                    r"STRUCTURE|CONSTRUCTION)|\bN\.\s?I\.\s?C\b|"
                    r"\bTO REMAIN\b"), 4)
_DEMO_SHEET_NO = re.compile(r"^[A-Z]?D[-.\d]")
_EXISTING_PLAN = re.compile(r"^EXISTING\b(?!.*\bROOF).*\bPLAN")

# spec section number prefixes: (prefix, weight)
SECTIONS = {
    "new_building": [("06", 2), ("07 2", 1), ("08", 2), ("09", 2), ("10", 1),
                     ("12", 1), ("14", 2), ("04", 1), ("05 1", 1),
                     ("03 3", 1), ("21", 0.5), ("22", 0.5), ("23", 0.5)],
    "renovation": [("02 41 19", 2), ("02 8", 1), ("06", 2), ("08", 2),
                   ("09", 2), ("10", 1), ("12", 1), ("21", 0.5),
                   ("22", 0.5), ("23", 0.5)],
    "standby_generator": [("26 32 13", 8), ("26 32", 6), ("26 36 23", 6),
                          ("26 36", 6), ("23 13", 2), ("23 11 13", 1)],
    "electrical_service": [("26 23", 5), ("26 24 13", 5), ("26 12", 4),
                           ("26 13", 4), ("26 24 16", 2), ("26 27", 2)],
    "hvac_replacement": [("23 64", 5), ("23 52", 5), ("23 74", 5),
                         ("23 73", 4), ("23 65", 4), ("23 81", 3),
                         ("23 09", 2), ("23 05 93", 1)],
    "reroof": [("07 01 50", 6), ("07 5", 4), ("07 41", 3), ("07 62", 2),
               ("07 22", 2), ("07 71", 2), ("07 72", 1)],
    "sitework_only": [("31", 2), ("32", 2), ("33", 2)],
    "pump_or_lift_station": [("33 32", 8), ("43 21", 5), ("33 31", 1)],
    "treatment_plant": [("46", 6), ("44", 4), ("40", 4), ("43", 2)],
}

# division-only evidence (old callers pass division numbers, no titles)
_DIV_ONLY = {"new_building": {"04": 1, "05": 1, "06": 1.5, "07": 1,
                              "08": 1.5, "09": 1.5, "10": 1, "12": 1,
                              "14": 1},
             "renovation": {"06": 1, "08": 1, "09": 1.5, "10": 0.5},
             "sitework_only": {"31": 1, "32": 1, "33": 1},
             "treatment_plant": {"40": 2, "44": 2, "46": 3}}

# equipment kinds -> type points (once per kind)
_EQUIP_POINTS = {"generator": ("standby_generator", 3),
                 "ats": ("standby_generator", 2),
                 "switchgear": ("electrical_service", 1),
                 "transformer": ("electrical_service", 1),
                 "rtu": ("hvac_replacement", 1),
                 "ahu": ("hvac_replacement", 1),
                 "chiller": ("hvac_replacement", 1),
                 "boiler": ("hvac_replacement", 1),
                 "pump": ("pump_or_lift_station", 1),
                 "blower": ("treatment_plant", 1)}

_TEXT_CAP = 8.0


_JUNK_TITLE = re.compile(r"\bSHALL\b|\bASTM\b|\. \d+\. |[^\x00-\x7f]")


def _rows(sheets):
    """(number, title) of each sheet; a "title" that is really a run of
    note text (long, "SHALL", "ASTM") is no sheet title, so its number is
    not trusted either (an "A325" bolt in a structural note is no A
    sheet)."""
    for r in sheets or ():
        no = (r.get("number") or "").upper().strip()
        title = (r.get("title") or "").upper().strip()
        if len(title) > 70 or _JUNK_TITLE.search(title):
            continue
        yield no, title


def _sections(sections):
    out = []
    for s in sections or ():
        if isinstance(s, dict):
            n, t = s.get("number") or "", s.get("title") or ""
        else:
            n, t = (tuple(s) + ("", ""))[:2]
        n = re.sub(r"\s+", " ", str(n)).strip()
        if re.fullmatch(r"\d{6}", n):
            n = f"{n[:2]} {n[2:4]} {n[4:]}"
        out.append((n, str(t).strip()))
    return out


AMBIGUOUS_SHARE = 0.10     # a lead under this share of the top: ask


def detect(sheets=(), sections=(), texts=(), divisions=(), equipment=()):
    """{"type", "label", "score", "recognized", "scores": {type: score},
    "why": {type: [evidence]}, "ranked": [(type, score)], "candidates":
    [types]}.

    A tie, or a lead under AMBIGUOUS_SHARE between the top types, is not
    a decision: type "unknown" (the person picks), with "ambiguous" True
    and the close types in "candidates" (best first)."""
    scores = {k: 0.0 for k in TYPES}
    why = {k: [] for k in TYPES}
    # building points any set of plans has (A-sheets, MEP with them, the
    # trade divisions): a renovation needs evidence of its own to get them
    # in full - floor plans alone are a new building
    shared = []

    def add(t, w, text):
        if w > 0:
            scores[t] += w
            if text not in why[t]:
                why[t].append(text)

    def both(w, text):
        add("new_building", w, text)
        shared.append((w, text))
    rows = list(_rows(sheets))
    secs = _sections(sections)
    a_sheets = [(n, t) for n, t in rows if re.match(r"^A[DEI]?[-.\d]", n)]
    # a demolition sheet / D series / selective demolition spec: then the
    # "existing conditions" boilerplate is renovation evidence too
    demo_set = any(re.search(r"DEMOLI", t) or _DEMO_SHEET_NO.match(n) or
                   (re.match(r"^A[-.\d]", n) and _EXISTING_PLAN.search(t))
                   for n, t in rows) or \
        any(n.startswith(("02 41", "02 42")) for n, _t in secs)
    words = dict(WORDS)
    if demo_set:
        words["renovation"] = WORDS["renovation"] + [_RENO_BOILER]
    bldg_titled = 0
    for no, title in rows:
        ev = f'sheet {no or "?"} "{title}"'
        is_a = re.match(r"^A[DEI]?[-.\d]", no)
        is_s = re.match(r"^S[-.\d]", no)
        if is_a:
            both(1, ev)
            if _BLDG_TITLES.search(title):
                bldg_titled += 1
                both(3, ev)
            elif re.search(r"ELEVATION", title):
                both(1, ev)
            if re.search(r"DEMOLI", title):
                add("renovation", 3, ev)
            elif _EXISTING_PLAN.search(title):
                add("renovation", 2, ev)
        if _DEMO_SHEET_NO.match(no) and not is_a:
            add("renovation", 2, ev)        # MD-101, ED-101, D-1
        if is_s and re.search(r"FOUNDATION", title):
            add("new_building", 3, ev)      # a new building's footings
        elif is_s and _STRUCT_BLDG.search(title):
            add("new_building", 2, ev)
        if a_sheets and re.match(r"^(M|P|E|FP|FA)[-.\d]", no):
            both(0.5, ev)
        for t, rules in words.items():
            best = max((w for rx, w in rules if rx.search(title)), default=0)
            add(t, best, ev)
    sec_divs = {n[:2] for n, _t in secs if n[:2].isdigit()}
    for no, title in secs:
        ev = f"spec {no} {title}".strip()
        up = title.upper()
        for t in TYPES:
            tab = SECTIONS.get(t, ())
            w = max((w for p, w in tab if no.startswith(p)), default=0)
            w = max(w, max((w2 for rx, w2 in words.get(t, ())
                            if rx.search(up)), default=0))
            if t == "renovation":
                own = max((w2 for p, w2 in tab if no.startswith(p) and
                           p.startswith("02")), default=0)
                own = max(own, max((w2 for rx, w2 in words.get(t, ())
                                    if rx.search(up)), default=0))
                add(t, own, ev)
                if w > own:
                    shared.append((w - own, ev))
                continue
            add(t, w, ev)
    for d in divisions or ():
        d = str(d)[:2]
        if d in sec_divs:
            continue
        for t, tab in _DIV_ONLY.items():
            if t == "renovation":
                if tab.get(d):
                    shared.append((tab[d], f"spec Division {d}"))
                continue
            add(t, tab.get(d, 0), f"spec Division {d}")
    seen = {k: set() for k in TYPES}
    got = {k: 0.0 for k in TYPES}
    texts = list(texts or ())
    near_excl = _excluded_lines(texts)
    for n, line in enumerate(texts):
        up = str(line).upper()
        if _LEGEND.search(up):
            up = _LEGEND.sub(" ", up)       # "N.I.C. NOT IN CONTRACT"
        for t, rules in words.items():
            if n in near_excl:
                continue          # "generator ... NOT IN THIS CONTRACT"
            for rx, w in rules:
                m = rx.search(up)
                if not m or m.group(0) in seen[t] or got[t] >= _TEXT_CAP:
                    continue
                seen[t].add(m.group(0))
                w = min(w * 0.5, _TEXT_CAP - got[t])
                got[t] += w
                add(t, w, f'drawing text "{str(line).strip()[:70]}"')
    kinds = set()
    for e in equipment or ():
        k = e.get("kind")
        if e.get("by_others"):
            continue
        if k in _EQUIP_POINTS and k not in kinds:
            kinds.add(k)
            t, w = _EQUIP_POINTS[k]
            add(t, w, "equipment " + (e.get("tag") or e.get("desc") or k))
    # the shared building points: in full when the set shows renovation
    # evidence of its own, half otherwise
    k = 1.0 if scores["renovation"] > 0 else 0.5
    for w, text in shared:
        add("renovation", w * k, text)
    # a set of building drawings (floor plans, wall sections...): its
    # civil sheets, generator, switchgear, RTUs and roof are parts of the
    # building, not the project
    if bldg_titled >= 2 and max(scores["new_building"],
                                scores["renovation"]) >= 6:
        for t in TYPES:
            if t not in BUILDING_TYPES:
                scores[t] *= 0.5
    # a plant's civil sheets (yard piping, grading, profiles) are its yard
    # work: process structures make it a treatment plant
    if scores["treatment_plant"] >= 8:
        scores["sitework_only"] *= 0.6
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])   # stable: order
    best, top = ranked[0]
    recognized = top >= MIN_SCORE
    close = [k for k, v in ranked if v > 0 and top - v < AMBIGUOUS_SHARE *
             top] if recognized else []
    ambiguous = len(close) > 1
    decided = recognized and not ambiguous
    return {"type": best if decided else UNKNOWN,
            "label": label(best) if decided else label(UNKNOWN),
            "score": round(top, 1), "recognized": decided,
            "ambiguous": ambiguous, "candidates": close if ambiguous else [],
            "scores": {k: round(v, 1) for k, v in scores.items()},
            "why": why, "ranked": [(k, round(v, 1)) for k, v in ranked
                                   if v > 0]}


def ambiguous_note(det):
    """"Project type unclear: New building 12 vs Renovation 11.5 ...", or
    None when detect() decided."""
    cands = det.get("candidates") or []
    if not det.get("ambiguous") or len(cands) < 2:
        return None
    sc = det.get("scores") or {}
    parts = " vs ".join(f"{label(k)} {sc.get(k, 0):g}" for k in cands)
    return (f"Project type unclear - the evidence is close: {parts}. Pick "
            "the project type and build again (no type was assumed).")


# ------------------------------------------- scope of work and exclusions
_EXCL = _rx(r"NOT INCLUDED IN|NOT IN (?:THE |THIS )?CONTRACT|"
            r"\bN\.\s?I\.\s?C\b|\bBY OTHERS\b|\bBY (?:THE )?OWNER\b|"
            r"OWNER[- ]FURNISHED|UNDER (?:A )?SEPARATE CONTRACT|\bOFOI\b|"
            r"EXCLUDED FROM (?:THE |THIS )?(?:CONTRACT|SCOPE)")
# owner-furnished, contractor-installed: still our installation - only the
# purchase is the owner's
_OFCI = _rx(r"\bOFCI\b|\bO\.\s?F\.\s?C\.\s?I\b|OWNER[- ]FURNISHED[,/]?\s*"
            r"(?:AND\s+|&\s*)?CONTRACTOR[- ]INSTALLED|FURNISHED BY (?:THE )?"
            r"OWNER[,;]?\s*(?:AND\s+|&\s*)?INSTALLED BY (?:THE )?"
            r"(?:GENERAL )?CONTRACTOR")
# an abbreviation legend's entry ("N.I.C. NOT IN CONTRACT", "OFOI = OWNER
# FURNISHED OWNER INSTALLED") is no note about this job
_LEGEND = _rx(r"(?:^|(?<=[\s,;]))(?:N\.\s?I\.\s?C\.?|NIC|OFOI|OFCI|CFCI|"
              r"OFE|O\.F\.C\.I\.?|O\.F\.O\.I\.?|B\.O\.)\s*[-=:]?\s*"
              r"(?:NOT IN (?:THE )?CONTRACT|BY OTHERS|BY OWNER|(?:OWNER|"
              r"CONTRACTOR)[- ]FURNISHED[,/]?\s*(?:(?:AND\s+)?(?:OWNER|"
              r"CONTRACTOR)[- ]INSTALLED)?|OWNER[- ]FURNISHED EQUIPMENT)")
# "... DESIGN IS / ARE BY OTHERS": a design note - who designs it - not an
# exclusion of the work
_DESIGN_BY_OTHERS = (r"\b(?:(?:DELEGATED[- ])?DESIGN(?:S|ED)?(?:[- /]BUILD)?"
                     r"|DESIGN[- /]BUILD|ENGINEERING|ENGINEERED)\s+(?:(?:IS|"
                     r"ARE|SHALL BE|WILL BE|TO BE|SHALL|WILL)\s+)?(?:(?:"
                     r"PROVIDED|PREPARED|PERFORMED|DONE|COMPLETED)\s+)?"
                     r"BY\s+OTHERS\b")
_DESIGN_NOTE = _rx(_DESIGN_BY_OTHERS + r"|\bDELEGATED[- ]DESIGN\b")
# the owner chooses / approves / requires: not "by owner" work
_NOT_EXCL =_rx(r"\b(?:SELECTIONS?|SELECTED|CHOSEN|APPROVED|APPROVAL|"
                r"DIRECTED|MANDATED|REQUIRED|REVIEWED|ACCEPTED|DETERMINED|"
                r"DESIGNATED|RETAINED|HIRED|EMPLOYED|PAID|COLOU?RS?)\s+"
                r"(?:AS\s+)?BY\s+(?:THE\s+)?OWNER(?:'S)?(?:\s+"
                r"REPRESENTATIVE)?|"
                # delegated design: the design is someone else's, the work
                # is still ours ("TRUSSES DESIGNED BY OTHERS", "FRAMING BY
                # OTHERS. TO BE DESIGNED ...", "MECHANICAL, ELECTRICAL AND
                # PLUMBING DESIGN ARE BY OTHERS", "ENGINEERING BY OTHERS",
                # "DESIGN-BUILD BY OTHERS", "DELEGATED DESIGN BY OTHERS")
                r"\b(?:DESIGNED|ENGINEERED|DESIGN\w*\b(?:(?!INSTALL|WORK|"
                r"CONSTRUCT|FURNISH|SUPPL|LABOR|MATERIAL)[^.]){0,50}?\b(?:"
                r"PROVIDED|PREPARED|PERFORMED|DONE))\s+BY\s+OTHERS\b|"
                + _DESIGN_BY_OTHERS +
                r"|\bBY OTHERS\.?\s*(?=TO BE (?:DESIGNED|ENGINEERED)\b)")
_ONLY = _rx(r"\bSCOPE ONLY\b|\bONLY THE\b.*\bIN (?:THE |THIS )?CONTRACT")
# a lettered / numbered note: "A. ...", "1. ...", "B) ..."
_MARK = re.compile(r"^\s*(?:\d{1,2}[.)]\s*|[A-Z][.)]\s+)(?=[A-Z])")
_CONNECTOR_END = re.compile(r"(?:[,(\[&/-]|\b(?:AND|OR|OF|THE|IN|TO|FOR|"
                            r"WITH|BY|A|AN))\s*$")
# words that are no work: what's left of "SEE SHEET A2 - SCOPE ONLY"
_NO_WORK = {"PRICE", "SCOPE", "ONLY", "BASE", "BID", "ALTERNATE", "ALT",
            "SEE", "NOTE", "NOTES", "THIS", "THE", "FOR", "AND", "ALL",
            "WORK", "CONTRACT", "SHEET", "SHEETS", "DRAWING", "DRAWINGS",
            "ITEM", "ITEMS", "PROVIDE", "FURNISH", "INSTALL", "TYP", "TYPICAL",
            "PER", "WITH", "FROM", "THAT", "ARE", "ITS", "NOT", "INCLUDED",
            "PROJECT", "AREA", "AREAS", "SHOWN", "INDICATED", "CONTRACTOR",
            "OWNER", "PHASE", "PART", "OF", "IN", "TO", "ON", "AT", "IS",
            "BE", "AS", "BY"}


# an abbreviation legend / glossary: the words of the definitions, and the
# abbreviations themselves ("OFCI: OWNER FURNISHED, CONTRACTOR INSTALLED",
# "OWNER FURNISHED, CONTRACTOR INSTALLED (OFCI)", "OFCI: FURNISHED BY
# OWNER, INSTALLED BY CONTRACTOR") - a line with nothing else names no
# work of this job
_ABBREV = re.compile(r"\b(?:O\.?\s?F\.?\s?C\.?\s?I|O\.?\s?F\.?\s?O\.?\s?I|"
                     r"C\.?\s?F\.?\s?C\.?\s?I|C\.?\s?F\.?\s?O\.?\s?I|"
                     r"N\.?\s?I\.?\s?C|O\.?\s?F\.?\s?E|B\.\s?O)\b\.?", re.I)
_LEGEND_WORDS = {"OWNER", "OWNERS", "OWNER'S", "CONTRACTOR", "CONTRACTORS",
                 "FURNISHED", "FURNISH", "INSTALLED", "INSTALL", "SUPPLIED",
                 "PROVIDED", "OTHERS", "NOT", "CONTRACT", "EQUIPMENT",
                 "OWNER-FURNISHED", "CONTRACTOR-INSTALLED",
                 "OWNER-INSTALLED", "CONTRACTOR-FURNISHED", "GENERAL",
                 "SEPARATE", "UNDER", "ABBREVIATIONS", "ABBREVIATION",
                 "LEGEND", "GLOSSARY", "DEFINITIONS", "MEANS", "STANDS",
                 "FOR", "AND", "THE", "BY", "IN", "OR"}
_LEGEND_HEAD = _rx(r"^\s*(?:(?:GENERAL|DRAWING|SHEET|SYMBOLS?\s*(?:AND|&)\s*)"
                   r"\s*)?(?:ABBREVIATIONS?|LEGEND|GLOSSARY|DEFINITIONS)"
                   r"(?:\s*(?:AND|&)\s*(?:SYMBOLS?|ABBREVIATIONS?|LEGEND))?"
                   r"\s*:?\s*$")
# the end of a legend block: the next notes heading or numbered note
_BLOCK_END = _rx(r"\bNOTES?\s*:?\s*$|^\s*(?:SCOPE|DESCRIPTION|SUMMARY) OF\b|"
                 r"^\s*(?:\d{1,2}[.)]|[A-Z][.)])\s+[A-Z]")


def is_legend(text):
    """An abbreviation's definition and nothing else - no work named."""
    t = _ABBREV.sub(" ", str(text))
    if not re.search(r"OWNER|CONTRACTOR|NOT IN|OTHERS", t, re.I):
        return False
    words = re.findall(r"[A-Z][A-Z'-]+", t.upper())
    return not [w for w in words if w not in _LEGEND_WORDS and
                w.strip("-'") not in _LEGEND_WORDS]


def legend_lines(lines):
    """Indexes of the lines in a block titled ABBREVIATIONS / LEGEND /
    GLOSSARY: its entries define words, they are no notes about the job.
    The block ends at the next notes heading or numbered note."""
    out = set()
    lines = [str(x) for x in lines or ()]
    i = 0
    while i < len(lines):
        if not _LEGEND_HEAD.match(lines[i]):
            i += 1
            continue
        out.add(i)
        j = i + 1
        while j < len(lines) and j - i <= 80:
            ln = lines[j].strip()
            if _LEGEND_HEAD.match(ln):
                out.add(j)
                j += 1
                continue
            if not ln or _BLOCK_END.search(ln) or len(ln) > 90:
                break
            out.add(j)
            j += 1
        i = j
    return out


def _clean_excl(text):
    """The text with abbreviation legends and "selection by owner" style
    phrases taken out (they name the owner but exclude nothing)."""
    return _NOT_EXCL.sub(" ", _LEGEND.sub(" ", str(text)))


def work_words(text):
    """The words in a note that say what the work is ([] for "SEE SHEET
    A2 - SCOPE ONLY" or a bare "B")."""
    return [w for w in re.findall(r"[A-Z][A-Z'-]{2,}", str(text).upper())
            if w not in _NO_WORK]


def _excluded_lines(lines):
    """Indexes of the lines in or next to a "not in this contract" note."""
    out = set()
    lines = [str(x) for x in lines or ()]
    legend = legend_lines(lines)
    for i, ln in enumerate(lines):
        if i in legend or is_legend(ln):
            continue
        c = _clean_excl(ln)
        if _EXCL.search(c) and not _OFCI.search(c):
            out.update(range(max(0, i - 2), i + 3))
    return out


def _note_around(lines, i):
    """The note sentence(s) around line i: back to the start of its
    lettered / numbered note ("A.", "1.") when there is one a few lines
    up, else back while the line before is an unfinished upper-case note
    line; on until a line ends the sentence or the next note starts."""
    a = i
    if not _MARK.match(lines[i]):
        for j in range(i - 1, max(-1, i - 6), -1):
            ln = lines[j].rstrip()
            if ln.endswith((".", ":")) or ln != ln.upper() or not ln:
                break                   # an earlier, finished note
            if _MARK.match(ln):
                a = j
                break
    if a == i:
        while a > 0 and i - a < 2:
            prev = lines[a - 1]
            if prev != prev.upper() or _MARK.match(lines[a]) or \
                    not _CONNECTOR_END.search(prev.rstrip()):
                break                   # the note starts on this line
            a -= 1
    b = i
    while b + 1 < len(lines) and b - i < 3 and \
            not lines[b].rstrip().endswith(".") and \
            not _MARK.match(lines[b + 1]):
        b += 1
    return " ".join(lines[a:b + 1])


def kinds_named(text):
    """The equipment kinds a note names, by word ("GENERATOR") or by tag
    ("GEN-1", "RTU-3"; not the prefixes that are plain words)."""
    up = str(text).upper()
    out = [k for k, rx in _KIND_RX.items() if rx.search(up)]
    for m in _TAG.finditer(up):
        k = _PREFIX.get(m.group(1))
        if k and m.group(1) not in _AMBIG and k not in out:
            out.append(k)
    return out


def _what(before):
    """A short name for the thing a note is about, from the words before
    its "NOT IN CONTRACT" / "OFCI" phrase ("" when there are none)."""
    t = re.sub(r"[\s,;:(\[-]*(?:\b(?:IS|ARE|TO BE|SHALL BE|WILL BE|BE|"
               r"WORK)\b[\s,;:(\[-]*)*$", "", str(before).strip(),
               flags=re.I).strip(" ,;:([-")
    if not work_words(t):
        return ""
    name = item_name(t)
    return name if len(re.sub(r"[^A-Za-z]", "", name)) >= 3 else ""


def exclusions(lines):
    """What the drawings say is NOT in this contract ("GENERATOR PACKAGE
    [GENERATOR, FUEL TANK, ATS ...] NOT INCLUDED IN THIS CONTRACT", "BY
    OWNER", "N.I.C."): [{text, kinds}], kinds = the equipment kinds it
    names. Limited-scope notes ("PRICE WOOD ENCLOSURE SCOPE ONLY") come
    back with only=True; owner-furnished, contractor-installed equipment
    ("OFCI") with ofci=True - we still install it."""
    lines = [re.sub(r"\s+", " ", str(x)).strip() for x in lines or ()]
    legend = legend_lines(lines)
    out, seen = [], set()
    for i, ln in enumerate(lines):
        if i in legend:
            continue                # ABBREVIATIONS / LEGEND block entries
        c = _clean_excl(ln)
        if not (_EXCL.search(c) or _ONLY.search(c) or _OFCI.search(c)):
            continue
        text = _note_around([x if k not in legend else "" for k, x in
                             enumerate(lines)], i)
        text = _NOT_EXCL.sub(lambda m: " " if "OTHERS" in m.group(0).upper()
                             else m.group(0), text)
        for sent in re.split(r"(?<=[a-z\]\)]\.)\s+|(?<=[A-Z\]\)]{2}\.)\s+"
                             r"|\s+(?=(?:[A-Z]|\d{1,2})[.)]\s+[A-Z]{2})",
                             text):
            sent = _MARK.sub("", sent.strip()).strip()
            c = _clean_excl(sent)
            ofci = _OFCI.search(c)
            excl = None if ofci else _EXCL.search(c)
            only = _ONLY.search(c)
            if not (excl or only or ofci):
                continue
            bare = re.sub(r"[^A-Z]", "", sent.upper())
            if bare in ("NIC", "") or len(sent) < 12 or bare in seen:
                continue
            if is_legend(sent):
                continue        # "OFCI: OWNER FURNISHED, CONTRACTOR ..."
            what = c[:(excl or ofci or only).start()] if not only or \
                excl or ofci else c
            if not work_words(_ONLY.sub(" ", what)) and not (
                    (excl or ofci) and work_words(c[(excl or ofci).end():])):
                continue        # "SEE A2 - SCOPE ONLY", "B. BY OWNER"
            seen.add(bare)
            kinds = kinds_named(sent) if excl or ofci else []
            e = {"text": sent[:160], "kinds": kinds,
                 "only": bool(only and not excl and not ofci)}
            if ofci:
                e["ofci"] = True
            elif excl:
                tr = trades_excluded(c[:excl.start()])
                if tr:
                    e["trades"] = tr
            out.append(e)
    return out[:12]


# whole trades a note takes out of the contract ("ELECTRICAL WORK BY
# OTHERS (N.I.C.)", "ALL PLUMBING IS NOT IN CONTRACT")
_TRADE_WORDS = [(r"PLUMBING", "plumbing"),
                (r"MECHANICAL|HVAC", "hvac"),
                (r"ELECTRICAL", "electrical"),
                (r"FIRE (?:PROTECTION|SPRINKLERS?|SUPPRESSION)|SPRINKLERS?",
                 "fire_supp"),
                (r"FIRE ALARMS?", "fire_alarm"),
                (r"LOW[- ]VOLTAGE|TELECOM\w*|DATA", "technology")]
_TRADE_FILLER = _rx(r"\b(?:ALL|THE|ANY|AND|OR|&|WORK|SCOPE|SYSTEMS?|TRADES?|"
                    r"INSTALLATIONS?|IS|ARE|TO BE|SHALL BE|WILL BE|BE|"
                    r"CONTRACTS?|CONTRACTOR'?S?|SUBCONTRACTS?)\b|[,/();:-]")


def trades_excluded(what):
    """The trades (plumbing / hvac / electrical / fire_supp / fire_alarm /
    technology) when `what` - the words before a "BY OTHERS" / "N.I.C."
    phrase - is nothing but whole trades ("ELECTRICAL WORK", "MECHANICAL,
    PLUMBING AND ELECTRICAL"); [] when it names anything else (an
    "ELECTRICAL CONNECTION TO THE OWNER'S OVEN" excludes no trade)."""
    t = " " + _MARK.sub("", str(what).upper()) + " "
    out = []
    for rx, trade in _TRADE_WORDS:
        if re.search(rf"\b(?:{rx})\b", t):
            out.append(trade)
            t = re.sub(rf"\b(?:{rx})\b", " ", t)
    if not out or re.search(r"[A-Z0-9]", _TRADE_FILLER.sub(" ", t)):
        return []
    return out


_SCOPE_HEAD = _rx(r"^(?:DESCRIPTION|SCOPE|SUMMARY) OF (?:THE )?WORK\b|"
                  r"^WORK (?:INCLUDES|SCOPE)\b|^PROJECT SCOPE\b|"
                  r"^SCOPE(?: OF PROJECT)?\s*:?\s*$")
_ITEM = re.compile(r"^\s*(\d{1,2})\s*[.)]\s*(\S.*)$")


def scope_items(lines, most=40):
    """The numbered list under a DESCRIPTION OF WORK / SCOPE OF WORK
    heading (a repairs-and-improvements job's whole scope), each item's
    wrapped lines joined: ["REPAIR DAMAGED STUCCO AT THE FRONT ENTRANCE
    STEPS, INCLUDING ...", ...]. Items must run 1, 2, 3...; [] if fewer
    than 2."""
    lines = [re.sub(r"\s+", " ", str(x)).strip() for x in lines or ()]
    for i, ln in enumerate(lines):
        if not _SCOPE_HEAD.search(ln):
            continue
        items, expect, gap, j = [], 1, 0, i + 1
        while j < len(lines) and gap <= 8 and len(items) < most:
            cur = lines[j]
            m = _ITEM.match(cur)
            if m and int(m.group(1)) == expect:
                items.append(m.group(2).strip())
                expect += 1
                gap = 0
            elif items and not m and cur and \
                    not items[-1].endswith(".") and len(items[-1]) < 300:
                items[-1] += " " + cur
            else:
                gap += 1
            j += 1
        if len(items) >= 2:
            return items
    return []


# durations (working days) for a listed item, by its words - assumed
_ITEM_DAYS = [
    (r"POWER ?WASH|PRESSURE ?WASH", 2),
    (r"WATER SOFTENER|WATER HEATER|EXHAUST FAN|FIXTURE|LIGHT", 2),
    (r"CAULK|SEALANT", 4),
    (r"STUCCO|EIFS|MASONRY|CONCRETE", 4),
    (r"STRUCTURAL STEEL|CORROSION", 4),
    (r"PAINT|COATING|PRIME", 3),
    (r"GROUT|TILE|CRACK|NAIL POP|PATCH", 2),
]


_WASH = r"POWER ?WASH|PRESSURE ?WASH"
_TRADES = [("cleaning", _WASH), ("sealants", r"CAULK|SEALANT"),
           ("stucco", r"STUCCO|EIFS"),
           ("drywall", r"NAIL POP|CRACK|DRYWALL|GYP"),
           ("tile", r"TILE|GROUT"),
           ("plumbing", r"PLUMB|SOFTENER|WATER HEATER|FAUCET|TOILET"),
           ("electrical", r"LIGHT|FIXTURE|ELECTRIC|RECEPTACLE"),
           ("hvac", r"EXHAUST FAN|HVAC|DUCT|AIR HANDL"),
           ("painting", r"PAINT|COATING|PRIME|RUST")]   # last: "repainting"


def item_trade(text):
    """The crew a listed item is for (items of one trade run one after
    another), or None."""
    up = text.upper()
    for trade, rx in _TRADES:
        if re.search(rx, up):
            return trade
    return None


def item_days(text):
    up = text.upper()
    for rx, d in _ITEM_DAYS:
        if re.search(rx, up):
            return d
    return 3


_TRAIL = re.compile(r"\s+(?:AND|OR|THE|WITH|TO|FOR|OF|IN|ON|AT|FROM|BY|"
                    r"LOCATED|FOLLOWING|APPLY|ALL|NEW)$", re.I)


def item_name(text, most=80):
    """A short activity name from a scope item: up to ", INCLUDING" or
    the first comma / period, sentence case."""
    t = re.split(r",?\s+INCLUDING\b|[.;]\s|,\s(?=[A-Z]{3,} [A-Z]+ [A-Z]+)",
                 text.strip(), maxsplit=1)[0].strip(" ,.")
    if len(t) > most:
        t = t[:most].rsplit(" ", 1)[0]
        cut = re.search(r"^(.{30,}?)\s+(?:AND APPLY|AND INSTALL|TO REMOVE|"
                        r"LOCATED|FOLLOWING|WITH NEW|FOR THE)\b", t, re.I)
        if cut:
            t = cut.group(1)
    while _TRAIL.search(t):
        t = _TRAIL.sub("", t)
    words = []
    for k, w in enumerate(t.split()):
        core = w.strip(",.")
        prev = words[-1].upper() if words else ""
        if len(core) == 1 and core.isalpha() and (
                core.upper() != "A" or w.endswith(",") or
                re.match(r"(BUILDINGS?|SUITE|AREA|PHASE|UNIT)$", prev)):
            words.append(w.upper())        # buildings A, B, C and D
        elif core.upper() in ("HVAC", "ATS", "ADA", "LED", "GFCI", "RTU",
                              "AHU", "MEP", "HQ"):
            words.append(w.upper())
        else:
            words.append(w.lower())
    t = " ".join(words)
    return t[:1].upper() + t[1:]


# ------------------------------------------------------------- spec TOC
_TOC = re.compile(r"^\s*(?:SECTION\s+)?(\d{2})\s?(\d{2})\s?(\d{2})"
                  r"(?:\.\d{2})?\s*[-–—:.]*\s+([A-Za-z][A-Za-z0-9 ,&/()'\-]"
                  r"{2,80}?)\s*(?:\.{2,}.*|\s\d{1,4})?\s*$")


def toc_sections(lines):
    """[{number, title}] from table-of-contents style lines
    ("26 32 13  ENGINE GENERATORS", "263213 - Engine Generators ..... 4")."""
    out, seen = [], set()
    for ln in lines or ():
        for part in str(ln).splitlines():
            m = _TOC.match(part)
            if not m:
                continue
            no = f"{m.group(1)} {m.group(2)} {m.group(3)}"
            title = m.group(4).strip(" -.")
            if no in seen or int(m.group(1)) > 49 or len(title) < 3:
                continue
            seen.add(no)
            out.append({"number": no, "title": title,
                        "division": m.group(1)})
    return out


# ------------------------------------------------------------- equipment
# kind: (words that name it, tag prefixes, default lead weeks or None,
#        generic name). Lead weeks are ASSUMED starting values.
KINDS = OrderedDict([
    ("generator", (r"GENERATOR|GENSET|GEN[- ]SET", ("GEN", "EG", "G"), 30,
                   "generator")),
    ("ats", (r"TRANSFER SWITCH|\bATS\b", ("ATS", "TS"), 20,
             "automatic transfer switch")),
    ("switchgear", (r"SWITCHGEAR|SWITCHBOARD|PARALLELING|MAIN DISTRIBUTION",
                    ("SWGR", "SWBD", "MSB", "MDP"), 30, "switchgear")),
    ("transformer", (r"TRANSFORMER", ("XFMR", "TR", "T"), 40,
                     "transformer")),
    ("fuel_tank", (r"FUEL (?:OIL )?(?:STORAGE )?TANK|SUB-?BASE TANK|BELLY "
                   r"TANK|DAY TANK", ("FT", "DT", "FOT"), 10, "fuel tank")),
    ("ups", (r"\bUPS\b|UNINTERRUPTIBLE", ("UPS",), 12, "UPS")),
    ("mcc", (r"MOTOR CONTROL CENTER|\bMCC\b", ("MCC",), 20,
             "motor control center")),
    ("rtu", (r"PACKAGED ROOF ?TOP UNIT|ROOF ?TOP UNIT|PACKAGED ROOF ?TOP|"
             r"\bRTU\b", ("RTU",), 16,
             "rooftop unit")),
    ("ahu", (r"AIR HANDL|\bAHU\b", ("AHU",), 20, "air handling unit")),
    ("chiller", (r"CHILLER", ("CH", "CHLR"), 26, "chiller")),
    ("boiler", (r"BOILER", ("B", "BLR"), 16, "boiler")),
    ("cooling_tower", (r"COOLING TOWER", ("CT",), 20, "cooling tower")),
    ("pump", (r"(?<!HEAT )(?<!SUMP )\bPUMPS?\b", ("P", "PMP", "LSP"), 16,
              "pumps")),
    ("blower", (r"BLOWER", ("BL", "BLWR"), 20, "blowers")),
])
LONG_LEAD_WEEKS = 12          # this long or longer: its own procurement
DEFAULT_LEAD_WEEKS = {k: v[2] for k, v in KINDS.items() if v[2]}
_KIND_RX = {k: _rx(v[0]) for k, v in KINDS.items()}
_PREFIX = {}
for _k, _v in KINDS.items():
    for _p in _v[1]:
        _PREFIX.setdefault(_p, _k)
# prefixes that are also plain words / sheet numbers: need the kind's word
_AMBIG = {"G", "B", "P", "T", "TR", "TS", "CT", "CH", "EG", "FT", "DT",
          "BL", "LSP", "PMP", "FOT"}
_TAG = re.compile(r"(?<![A-Z0-9-])(" + "|".join(sorted(_PREFIX, key=len,
                                                       reverse=True)) +
                  r")[- ]?(\d{1,3}[A-Z]?)(?![A-Z0-9])")
_CUT = re.compile(r"\b(?:SEE|REFER|NOTE|PER|MODEL|MANUFACTURER|MFR|BY|"
                  r"PROVIDE|FURNISH|LOCATION|LOCATED|SCHEDULE|WITH|W/)\b|[;:(]", re.I)
_UNITS = [(r"\bkw\b", "kW"), (r"\bkva\b", "kVA"), (r"\bhp\b", "HP"),
          (r"\bgpm\b", "GPM"), (r"\bats\b", "ATS"), (r"\brtu\b", "RTU"),
          (r"\bahu\b", "AHU"), (r"\bmbh\b", "MBH"), (r"\bcfm\b", "CFM"),
          (r"\bups\b", "UPS"), (r"\bmcc\b", "MCC"), (r"\b(\d+)v\b", r"\1V"),
          (r"\b(\d+)a\b", r"\1A"), (r"\bkw(?=\d)", "kW")]


def _describe(text, kind):
    t = re.sub(r"\s+", " ", text).strip(" -–—,.:")
    m = _CUT.search(t)
    if m:
        t = t[:m.start()].strip(" -–—,.")
    t = re.sub(r"(\d)\s*(KW|KVA|HP|GPM|V|A)\b", r"\1 \2", t, flags=re.I)
    m = _KIND_RX[kind].search(t.upper())
    if m:                              # "... diesel generator" - stop there
        size = re.match(r"[\s,-]*(\d[\d,.]*\s*(?:TONS?|KW|KVA|HP|GPM|CFM|"
                        r"MBH|AMPS?|A)\b)", t[m.end():], re.I)
        t = t[:m.end()]
        if size and not re.search(r"\d", t):
            t = size.group(1) + " " + t
    words = t.split()[:7]
    t = " ".join(words).lower()
    for a, b in _UNITS:
        t = re.sub(a, b, t)
    t = re.sub(r"(\d) a\b", r"\1A", t)
    t = re.sub(r"(\d) v\b", r"\1V", t)
    if not t or not _KIND_RX[kind].search(t.upper()):
        name = KINDS[kind][3]
        t = (t + " " + name).strip() if t and len(t.split()) <= 4 and \
            re.search(r"\d", t) else name
    return t


def _kind_of(line_up, prefix):
    for k, rx in _KIND_RX.items():
        if rx.search(line_up):
            if prefix is None or _PREFIX.get(prefix) == k or \
                    prefix in KINDS[k][1]:
                return k
    if prefix and prefix not in _AMBIG:
        return _PREFIX[prefix]
    return None


def equipment(lines=(), sheets=(), sections=()):
    """Named equipment: [{tag, kind, desc, kw, long_lead, source}].
    `lines`: drawing text (schedules, notes) and titles; sheet numbers in
    `sheets` are never tags."""
    sheet_nos = {re.sub(r"[-.\s]", "", n) for n, _t in _rows(sheets) if n}
    found = OrderedDict()
    untagged = OrderedDict()
    lines = [str(x) for x in lines or ()]
    for i, raw in enumerate(lines):
        line = re.sub(r"\s+", " ", raw).strip()
        up = line.upper()
        for m in _TAG.finditer(up):
            pre, num = m.group(1), m.group(2)
            tag = f"{pre}-{num}"
            if (pre + num) in sheet_nos or tag in found:
                continue
            rest = _TAG.sub(" ", line[m.end():].upper())
            rest = re.sub(r"^[\s&,/+-]*(?:AND\b)?[\s&,/+-]*", "", rest)
            ctx = up
            if len(rest.split()) < 2 and i + 1 < len(lines):
                nxt = " ".join(lines[i + 1:i + 3])
                if not _TAG.search(nxt.upper()):
                    rest = (rest + " " + nxt).strip()
                    ctx = up + " " + nxt.upper()
            kind = _kind_of(ctx, pre)
            if kind is None:
                continue
            found[tag] = {"tag": tag, "kind": kind,
                          "desc": _describe(rest, kind), "source": line[:80]}
        if not _TAG.search(up):
            for k, rx in _KIND_RX.items():
                if rx.search(up) and re.search(r"\d\s*(?:KW|KVA|HP|GPM|TONS?|"
                                               r"MBH|A\b|AMP)", up) and \
                        k not in untagged:
                    untagged[k] = {"tag": "", "kind": k,
                                   "desc": _describe(line, k),
                                   "source": line[:80]}
                    break
    titles = [t for _n, t in _rows(sheets)] + \
        [t for _n, t in _sections(sections)]
    for t in titles:
        up = t.upper()
        for k, rx in _KIND_RX.items():
            if rx.search(up) and k not in untagged:
                if k == "pump" and not re.search(r"LIFT|PUMP STATION|"
                                                 r"BOOSTER|PUMPING|SUBMERS|"
                                                 r"\b43 21", up):
                    continue
                untagged[k] = {"tag": "", "kind": k,
                               "desc": (_describe(t, k) if re.search(
                                   r"STATION|\d", up) else KINDS[k][3]),
                               "source": t[:80]}
    out = list(found.values())
    have = {e["kind"] for e in out}
    out += [e for k, e in untagged.items() if k not in have]
    for e in out:
        m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*KW\b", e["desc"].upper() +
                      " " + e["source"].upper())
        e["kw"] = float(m.group(1).replace(",", "")) if m else None
        e["long_lead"] = (DEFAULT_LEAD_WEEKS.get(e["kind"]) or 0) >= \
            LONG_LEAD_WEEKS
    return out


# long-lead materials a set's own quantities show (set_items): their
# assumed lead weeks - fabrication and delivery after the approval
SET_LEAD_WEEKS = OrderedDict([("storefront", 8), ("windows", 6),
                              ("overhead_doors", 8), ("joists", 8),
                              ("trusses", 4), ("roofing", 4), ("doors", 6)])


def _default_weeks(kind):
    return float(DEFAULT_LEAD_WEEKS.get(kind) or
                 SET_LEAD_WEEKS.get(kind) or 12)


def lead_weeks(sc, kind):
    w = (sc.get("lead_weeks") or {}).get(kind)
    return float(w) if w else _default_weeks(kind)


def lead_assumed(sc, kind):
    """No lead time given for the kind - or the one given is just our
    default (the dialog pre-fills the defaults, "generator 30, ats 20"):
    still an assumption, not a quote."""
    w = (sc.get("lead_weeks") or {}).get(kind)
    return not w or float(w) == _default_weeks(kind)


def parse_lead_weeks(text):
    """"generator 36, ats 20" -> {"generator": 36, "ats": 20}. A bare
    number applies to the generator (or the first long-lead kind)."""
    out = {}
    for part in re.split(r"[,;\n]+", text or ""):
        m = re.match(r"^\s*([A-Za-z_ ]*?)\s*[=:]?\s*(\d+(?:\.\d+)?)\s*"
                     r"(?:w|wk|wks|weeks?)?\s*$", part, re.I)
        if not m:
            continue
        k = m.group(1).strip().lower().replace(" ", "_") or "*"
        k = {"gen": "generator", "generators": "generator",
             "transfer_switch": "ats", "rtus": "rtu", "pumps": "pump",
             "xfmr": "transformer", "swgr": "switchgear",
             "chillers": "chiller", "boilers": "boiler",
             "glazing": "storefront", "window": "windows",
             "overhead": "overhead_doors", "overhead_door": "overhead_doors",
             "hardware": "doors", "door": "doors", "truss": "trusses",
             "joist": "joists", "steel_joists": "joists"}.get(k, k)
        if k == "*" or k in KINDS or k in SET_LEAD_WEEKS:
            out[k] = float(m.group(2))
    return out


def format_lead_weeks(sc):
    kinds = [k for k in KINDS if any(e["kind"] == k and e.get("long_lead")
                                     for e in sc.get("equipment") or ())]
    if sc.get("type") == "standby_generator":
        kinds = list(OrderedDict.fromkeys(["generator", "ats"] + kinds))
    try:                        # the set's long-lead materials (T4)
        if (sc.get("type") or "new_building") in BUILDING_TYPES:
            kinds += [it["item"] for it in set_items(sc)
                      if it["item"] not in kinds]
    except (KeyError, TypeError, ValueError):     # an old / partial scope
        pass
    return ", ".join(f"{k} {lead_weeks(sc, k):g}" for k in kinds)


# ------------------------------------------------------------- features
_FEATURES = {
    "utility": r"\bUTILITY\b|POWER COMPANY|ELECTRIC COMPANY|SERVICE "
               r"ENTRANCE|\bMETER\b|\bPOCO\b",
    "underground": r"UNDERGROUND|DUCT ?BANK|TRENCH|DIRECTIONAL BOR|"
                   r"HANDHOLE|\bHDD\b|ELECTRICAL SITE PLAN|SITE PLAN",
    "fuel_tank": r"\bFUEL\b|DIESEL|SUB-?BASE|BELLY TANK|DAY TANK|23 13 13|"
                 r"23 11 13",
    "natural_gas": r"NATURAL GAS|\bNAT\.? GAS|PROPANE|\bLP GAS|\bLPG\b",
    "switchgear": r"SWITCHGEAR|SWITCHBOARD|PARALLELING|\bMDP\b|MAIN "
                  r"DISTRIBUTION|\bMSB\b|26 23|26 24 13",
    "transformer": r"TRANSFORMER|\bXFMR\b|26 12",
    "panelboard": r"PANELBOARD|PANEL SCHEDULE|26 24 16",
    "demolition": r"DEMOLI|\bDEMO\b",
    "crane": r"CRANE|RIGGING|HOIST",
    "controls": r"CONTROLS|\bBAS\b|\bBMS\b|\bDDC\b|23 09|BUILDING "
                r"AUTOMATION",
    "ductwork": r"DUCT(?:WORK)?\b(?!\s*BANK)",
    "piping": r"PIPING|HYDRONIC|CHILLED WATER|HEATING WATER|STEAM|23 21|"
              r"23 22",
    "curbs": r"\bCURBS?\b(?! AND GUTTER| & GUTTER)|ADAPTER",
    "structural": r"STRUCTURAL|DUNNAGE|STEEL SUPPORT|ROOF FRAMING",
    "commissioning": r"COMMISSIONING|01 91|23 08",
    "tab": r"TEST(?:ING)?,? (?:AND|&) BALANC|\bTAB\b|23 05 93",
    "tearoff": r"TEAR[- ]?OFF|REMOVE EXISTING ROOF|ROOF DEMOLITION|"
               r"REMOVAL OF EXISTING ROOF|07 01 50",
    "recover": r"RECOVER|RE-COVER|OVERLAY",
    "deck": r"DECK REPAIR|DECK REPLACEMENT|ROOF DECK|05 31",
    "sheetmetal": r"SHEET METAL|COPING|GUTTER|DOWNSPOUT|EDGE METAL|07 62|"
                  r"07 71",
    "grading": r"GRADING|EARTHWORK|EXCAVAT|\b31 2",
    "clearing": r"CLEARING|GRUBBING|TREE REMOVAL|\b31 1",
    "paving": r"PAVING|PAVEMENT|ASPHALT|PARKING|\b32 1",
    "curb_gutter": r"CURB AND GUTTER|CURB & GUTTER|SIDEWALK|\b32 16",
    "storm": r"STORM|DRAINAGE|CULVERT|\b33 4",
    "sewer": r"SANITARY|\bSEWER|\b33 3",
    "water": r"WATER ?MAIN|WATERLINE|WATER LINE|WATER SERVICE|\b33 1",
    "landscape": r"LANDSCAP|PLANTING|SEEDING|\bSOD\b|IRRIGAT|\b32 9",
    "erosion": r"EROSION|SWPPP|SEDIMENT|\b31 25",
    "bypass": r"BYPASS",
    "wet_well": r"WET ?WELL",
    "valve_vault": r"VALVE VAULT|METER VAULT|VALVE PIT",
    "force_main": r"FORCE MAIN",
    "scada": r"SCADA|TELEMETRY|INSTRUMENTATION|P&ID|\b40 9|RADIO",
    "concrete": r"CONCRETE|\b03 3|BASIN|CLARIFIER|STRUCTURES?\b",
    "abatement": r"ASBESTOS|ABATEMENT|HAZARDOUS MATERIAL|LEAD PAINT|\b02 8",
    "generator": r"\bGENERATORS?\b|GENSET|\b26 32",
    "ats": r"TRANSFER SWITCH|\bATS\b|\b26 36",
    "roof": r"\bROOF",
}
# a section number starts a number ("26 32 13" is not "32 1...")
_FEATURES = {k: _rx(re.sub(r"(?:\\b)?(\d{2} \d)", r"(?<!\\d )\\b\1", v))
             for k, v in _FEATURES.items()}


def features(strings, equip=(), sheets=()):
    """Feature words found anywhere in the evidence, plus the equipment
    kinds; S-sheets mean structural work."""
    out = set()
    blob = "\n".join(str(s).upper() for s in strings or ())
    for k, rx in _FEATURES.items():
        if rx.search(blob):
            out.add(k)
    for e in equip or ():
        out.add(e["kind"])
    for no, _t in _rows(sheets):
        if re.match(r"^S[-.\d]", no):
            out.add("structural")
    if out & {"storm", "sewer", "water", "force_main"}:
        out.add("utilities")
    return out


# ------------------------------------------------------------- naming help
def items(s, *kinds):
    return [e for e in s.get("equipment") or () if e["kind"] in kinds]


def count(s, *kinds):
    return max(1, len([e for e in items(s, *kinds) if e.get("tag")]))


def lab(s, kind, default=None):
    """"GEN-1 (500 kW diesel generator)", "RTU-1, RTU-2 (rooftop units)",
    or the generic name."""
    es = items(s, kind)
    generic = default or KINDS.get(kind, ("", (), 0, kind))[3]
    if not es:
        return generic
    tagged = [e for e in es if e.get("tag")]
    if not tagged:
        return es[0]["desc"] or generic
    if len(tagged) == 1:
        e = tagged[0]
        return f"{e['tag']} ({e['desc']})" if e["desc"] else e["tag"]
    descs = {e["desc"] for e in tagged}
    tags = ", ".join(e["tag"] for e in tagged[:6]) + \
        (" ..." if len(tagged) > 6 else "")
    if len(descs) == 1:
        d = next(iter(descs))
        return f"{tags} ({d}{'' if d.endswith('s') else 's'})"
    return tags


def _lead(kind, generic=None):
    def name(s):
        w = lead_weeks(s, kind)
        return (f"Procure {lab(s, kind, generic)} - long lead ({w:g} wk"
                f"{', assumed' if lead_assumed(s, kind) else ''})")
    return name


def _lead_days(kind):
    return lambda f, s: lead_weeks(s, kind) * 5


def has(s, *feats):
    return bool(set(feats) & set(s.get("flags") or ()))


# ------------------------------------------------------------- templates
_CLOSE = [
    ("punch", "Closeout", "Punch list & corrections", (),
     lambda f, s: 5, []),
    ("sc", "Closeout", "Substantial Completion", (), lambda f, s: 0,
     ["punch"]),
    ("closeout", "Closeout", "Closeout - O&M manuals, as-builts & "
     "warranties", (), lambda f, s: 10, ["sc"]),
    ("fc", "Closeout", "Final Completion", (), lambda f, s: 0,
     ["closeout"]),
]


def _close(punch_preds, sc_preds=(), punch_days=5):
    out = [list(t) for t in _CLOSE]
    out[0][5] = list(punch_preds)
    out[0][4] = lambda f, s, d=punch_days: d
    out[1][5] = ["punch"] + list(sc_preds)
    return [tuple(t) for t in out]


def _with_final_insp(close):
    """The closeout rows with a final inspection after the punch list and
    before Substantial Completion (a hold point - review T3)."""
    out = [list(t) for t in close]
    out[1][5] = list(out[1][5]) + ["final_insp"]
    return [tuple(out[0]), ("final_insp", "Closeout", "Final inspection",
                            (), lambda f, s: 1, ["punch"])] + \
        [tuple(t) for t in out[1:]]


PERMIT_NAME = "Building permit (issue date assumed - enter it)"
TRADE_PERMIT_NAME = "Trade permits - plumbing, mechanical, electrical"


def _gone(s):
    """The trades the drawings put out of this contract ("ELECTRICAL WORK
    BY OTHERS (N.I.C.)")."""
    return set((s or {}).get("excluded_trades") or ())


def trade_permits_name(s):
    """TRADE_PERMIT_NAME without the trades that are by others."""
    gone = _gone(s)
    left = [w for f, w in (("plumbing", "plumbing"), ("hvac", "mechanical"),
                           ("electrical", "electrical")) if f not in gone]
    if len(left) == 3:
        return TRADE_PERMIT_NAME
    return "Trade permits" + (" - " + ", ".join(left) if left else "")


def without_electrical(full, short, no_plumbing=None):
    """A combined row's name: `short` (no electrical) when the electrical
    work is by others, `no_plumbing` (no plumbing) when the plumbing is
    ("ALL PLUMBING IS NOT IN CONTRACT" - review 0.12.39 #4), else `full`.
    With both by others the row has no trade left and is not made."""
    def name(s):
        gone = _gone(s)
        if "electrical" in gone:
            return short
        if no_plumbing and "plumbing" in gone:
            return no_plumbing
        return full
    return name
OTHER_PERMIT_NAME = "Permits (issue date assumed - enter it)"


def _start(subs):
    return [
        ("ntp", "Preconstruction", "Notice to Proceed", (),
         lambda f, s: 0, []),
        ("permit", "Preconstruction", OTHER_PERMIT_NAME, (),
         lambda f, s: 10, ["ntp"]),
        ("submittals", "Preconstruction", subs, (), lambda f, s: 10,
         ["ntp"]),
        ("sub_review", "Preconstruction", "Submittal review & approval",
         (), lambda f, s: 15, ["submittals"]),
    ]


def _gen_subs(s):
    parts = ["generator", "ATS"]
    if has(s, "fuel_tank") and not has(s, "natural_gas"):
        parts.append("fuel tank")
    if has(s, "switchgear"):
        parts.append("switchgear")
    return "Submittals - " + ", ".join(parts)


GENERATOR = _start(_gen_subs) + [
    ("utility", "Preconstruction", "Utility coordination (service / "
     "metering requirements)", ("utility",), lambda f, s: 10, ["ntp"]),
    ("proc_gen", "Procurement", _lead("generator"), (),
     _lead_days("generator"), ["sub_review"]),
    ("proc_ats", "Procurement", _lead("ats"), (), _lead_days("ats"),
     ["sub_review"]),
    ("proc_swgr", "Procurement", _lead("switchgear",
                                       "switchgear / breakers"),
     ("switchgear",), _lead_days("switchgear"), ["sub_review"]),
    ("proc_tank", "Procurement", lambda s: f"Procure {lab(s, 'fuel_tank')} "
     f"& fuel system materials", ("fuel_tank",),
     lambda f, s: lead_weeks(s, "fuel_tank") * 5, ["sub_review"]),
    ("mobilize", "Site & Pad", "Mobilize", (), lambda f, s: 2,
     ["sub_review"]),
    ("demo", "Site & Pad", "Demolition / removal of existing equipment",
     ("demolition",), lambda f, s: 3, ["mobilize"]),
    ("layout", "Site & Pad", "Locate utilities & lay out pad and conduit "
     "routes", (), lambda f, s: 2, ["mobilize"]),
    ("trench", "Site & Pad", "Underground conduit / duct bank (trench, "
     "conduit, backfill)", ("underground",),
     lambda f, s: 6 + 2 * count(s, "generator"), ["layout"]),
    ("pad_form", "Site & Pad", "Generator pad - forming & rebar", (),
     lambda f, s: 2 + count(s, "generator"), ["layout", "demo"]),
    ("pad_insp", "Site & Pad", "Generator pad - rebar & stub-up "
     "inspection", (), lambda f, s: 1, ["pad_form", "trench"]),
    ("pad_pour", "Site & Pad", "Generator pad - pour", (), lambda f, s: 1,
     ["pad_insp"]),
    ("pad_cure", "Site & Pad", "Generator pad - cure", (), lambda f, s: 7,
     ["pad_pour"]),
    ("feeders", "Installation", lambda s: "Conduit & feeders - " +
     ("site and " if has(s, "underground") else "") + "building "
     "(generator / ATS / distribution)", (),
     lambda f, s: 6 + 2 * count(s, "ats"), ["mobilize"]),
    ("set_gen", "Installation", lambda s: f"Set {lab(s, 'generator')} - "
     "crane pick", (), lambda f, s: count(s, "generator"),
     ["pad_cure", "proc_gen"]),
    ("set_ats", "Installation", lambda s: f"Set {lab(s, 'ats')}", (),
     lambda f, s: 1 + count(s, "ats"), ["proc_ats", "feeders"]),
    ("swgr_mods", "Installation", "Switchgear / distribution "
     "modifications", ("switchgear",), lambda f, s: 5,
     ["proc_swgr", "feeders"]),
    ("fuel", "Installation", lambda s: "Gas piping & regulator to the "
     "generator" if has(s, "natural_gas") else "Fuel system - tank, "
     "piping, fill & leak detection", ("fuel_tank", "natural_gas"),
     lambda f, s: 3, ["set_gen", "proc_tank"]),
    ("ground", "Installation", "Grounding & bonding (ground rods / ring)",
     (), lambda f, s: 2, ["set_gen"]),
    ("pull", "Installation", "Pull feeders & terminations", (),
     lambda f, s: 3 + 2 * count(s, "generator", "ats"),
     ["set_gen", "set_ats", "feeders", "swgr_mods", "trench"]),
    ("controls", "Installation", "Controls, annunciator, remote alarm & "
     "ATS signal wiring", (), lambda f, s: 3, ["pull"]),
    ("insp", "Installation", "Electrical inspection (rough / cover)", (),
     lambda f, s: 1, ["ground", "pull", "controls", "fuel"]),
    ("startup", "Startup & Testing", lambda s: "Manufacturer's startup - "
     f"{lab(s, 'generator')}", (), lambda f, s: 1 + count(s, "generator"),
     ["insp", "fuel"]),
    ("loadbank", "Startup & Testing", "Load bank test (per specs)", (),
     lambda f, s: count(s, "generator"), ["startup"]),
    ("outage", "Startup & Testing", lambda s: "Coordinate shutdown / outage"
     " with the owner" + (" & utility" if has(s, "utility") else ""), (),
     lambda f, s: 5, ["controls"]),
    ("cutover", "Startup & Testing", lambda s: "Permanent power shutdown & "
     f"cutover to {lab(s, 'ats')}", (), lambda f, s: 1,
     ["loadbank", "outage", "utility"]),
    ("transfer", "Startup & Testing", "ATS transfer test & building-load "
     "run test (4-hour / 2-hour per specs)", (), lambda f, s: 1,
     ["cutover"]),
    ("final_insp", "Startup & Testing", "Final electrical inspection", (),
     lambda f, s: 1, ["transfer"]),
    ("training", "Startup & Testing", "Owner training - generator & ATS",
     (), lambda f, s: 1, ["transfer"]),
] + _close(["final_insp"], ["training"], 3)


ELECTRICAL = _start(lambda s: "Submittals - " + ", ".join(
    ["switchgear"] + (["transformer"] if has(s, "transformer") else []) +
    (["panelboards"] if has(s, "panelboard") else []))) + [
    ("utility", "Preconstruction", "Utility coordination - service "
     "application, design & metering", (), lambda f, s: 15, ["ntp"]),
    ("utility_work", "Procurement", "Utility work order & transformer (by "
     "utility - lead time assumed)", ("utility", "transformer"),
     lambda f, s: 60, ["utility"]),
    ("proc_swgr", "Procurement", _lead("switchgear"), (),
     _lead_days("switchgear"), ["sub_review"]),
    ("proc_xfmr", "Procurement", _lead("transformer"), ("transformer",),
     _lead_days("transformer"), ["sub_review"]),
    ("proc_panels", "Procurement", "Procure panelboards", ("panelboard",),
     lambda f, s: 40, ["sub_review"]),
    ("mobilize", "Installation", "Mobilize", (), lambda f, s: 2,
     ["sub_review"]),
    ("demo", "Installation", "Demolition of existing electrical",
     ("demolition",), lambda f, s: 3, ["mobilize"]),
    ("trench", "Installation", "Underground service conduit / duct bank",
     ("underground",), lambda f, s: 8, ["mobilize"]),
    # the new pads where the old gear came out (no open-ended demolition)
    ("pad", "Installation", "Equipment pads (switchgear / transformer)",
     ("switchgear", "transformer"), lambda f, s: 8, ["trench", "mobilize",
                                                     "demo"]),
    ("feeders", "Installation", "Conduit & feeders", (), lambda f, s: 10,
     ["mobilize"]),
    ("set_swgr", "Installation", lambda s: f"Set {lab(s, 'switchgear')}",
     (), lambda f, s: 2 + count(s, "switchgear"), ["proc_swgr", "pad"]),
    ("set_xfmr", "Installation", lambda s: f"Set {lab(s, 'transformer')}",
     ("transformer",), lambda f, s: 2, ["proc_xfmr", "pad"]),
    ("set_panels", "Installation", "Set panelboards", ("panelboard",),
     lambda f, s: 3, ["proc_panels", "feeders"]),
    ("ground", "Installation", "Grounding & bonding", (), lambda f, s: 2,
     ["set_swgr"]),
    ("terminate", "Installation", "Pull feeders & terminations", (),
     lambda f, s: 6, ["set_swgr", "set_xfmr", "set_panels", "feeders",
                      "trench"]),
    ("insp", "Installation", "Electrical inspection", (), lambda f, s: 1,
     ["terminate", "ground"]),
    ("test", "Cutover", "Testing - insulation resistance, torque, breaker "
     "settings", (), lambda f, s: 3, ["insp"]),
    ("release", "Cutover", "Utility inspection & meter release",
     ("utility",), lambda f, s: 5, ["test", "utility_work"]),
    ("outage", "Cutover", "Coordinate shutdown / outage with the owner & "
     "utility", (), lambda f, s: 5, ["terminate"]),
    ("cutover", "Cutover", "Shutdown, cutover & energize new service", (),
     lambda f, s: 1, ["test", "release", "outage"]),
    ("training", "Cutover", "Owner training", (), lambda f, s: 1,
     ["cutover"]),
] + _close(["cutover"], ["training"])


_HVAC_KINDS = ("rtu", "ahu", "chiller", "boiler", "cooling_tower")


def _hvac(sc):
    kinds = [k for k in _HVAC_KINDS if items(sc, k)] or [None]
    t = _start(lambda s: "Submittals - " + ", ".join(
        [lab(s, k) if k else "HVAC equipment" for k in kinds] +
        (["controls"] if has(s, "controls") else [])))
    t += [("crane_plan", "Preconstruction", "Crane / rigging plan, permits "
           "& street or lot closure", ("crane", "rtu", "chiller",
                                       "cooling_tower"),
           lambda f, s: 5, ["sub_review"])]
    sets = []
    for k in kinds:
        kk = k or "hvac"
        t.append((f"proc_{kk}", "Procurement", _lead(k) if k else (
            lambda s: "Procure HVAC equipment - long lead (16 wk, assumed)"),
            (), _lead_days(k) if k else (lambda f, s: 80), ["sub_review"]))
    t += [
        ("curbs", "Procurement", "Curb adapters / roof curbs - fabricate",
         ("curbs", "rtu"), lambda f, s: 20, ["sub_review"]),
        ("mobilize", "Replacement", "Mobilize", (), lambda f, s: 2,
         ["sub_review"]),
        ("supports", "Replacement", "Structural supports / dunnage",
         ("structural",), lambda f, s: 5, ["mobilize"]),
    ]
    for k in kinds:
        kk = k or "hvac"
        name = (lambda s, k=k: f"Disconnect & remove existing - "
                f"{lab(s, k)}") if k else \
            "Disconnect & remove existing HVAC equipment"
        # the old unit comes out as the new one arrives: finished with the
        # delivery (FF, no lead), so the building is without it no longer
        # than the swap takes
        t.append((f"demo_{kk}", "Replacement", name, (),
                  lambda f, s, k=k: 1 + count(s, k) if k else 3,
                  [f"proc_{kk}:FF", "mobilize", "crane_plan"]))
        crane = k in ("rtu", "chiller", "cooling_tower", None)
        sname = (lambda s, k=k, c=crane: f"Set {lab(s, k)}" +
                 (" - crane pick" if c else "")) if k else \
            "Set new HVAC equipment - crane pick"
        t.append((f"set_{kk}", "Replacement", sname, (),
                  lambda f, s, k=k: count(s, k) if k else 2,
                  [f"demo_{kk}", f"proc_{kk}", "curbs", "supports"]))
        sets.append(f"set_{kk}")
    t += [
        ("roofing", "Replacement", "Roofing - curb flashing & patching",
         ("rtu", "curbs", "roof"), lambda f, s: 3, sets),
        ("ducts", "Connections", "Ductwork connections & modifications",
         ("ductwork", "rtu", "ahu"), lambda f, s: 3 + count(s, *_HVAC_KINDS),
         sets),
        ("piping", "Connections", "Piping connections (hydronic / gas / "
         "refrigerant)", ("piping", "chiller", "boiler", "natural_gas"),
         lambda f, s: 3 + count(s, *_HVAC_KINDS), sets),
        ("elec", "Connections", "Electrical disconnects & power "
         "connections", (), lambda f, s: 2 + count(s, *_HVAC_KINDS), sets),
        ("controls", "Connections", "Controls / BAS integration",
         ("controls",), lambda f, s: 5, ["elec", "ducts", "piping"]),
        # a hold point before startup (review T3)
        ("insp", "Connections", "Mechanical & electrical inspection", (),
         lambda f, s: 1, ["elec", "ducts", "piping", "controls"]),
        ("startup", "Startup", "Manufacturer startup", (),
         lambda f, s: 1 + count(s, *_HVAC_KINDS) // 2,
         ["insp", "roofing"]),
        ("tab", "Startup", "Test & balance", (), lambda f, s: 3,
         ["startup"]),
        ("cx", "Startup", "Functional testing / commissioning",
         ("commissioning",), lambda f, s: 3, ["tab"]),
        ("training", "Startup", "Owner training", (), lambda f, s: 1,
         ["tab", "cx"]),
    ]
    return t + _with_final_insp(_close(["tab", "cx"], ["training"]))


REROOF = _start("Submittals - roofing system, insulation & flashing") + [
    ("materials", "Procurement", "Roofing materials & sheet metal "
     "fabrication", (), lambda f, s: 15, ["sub_review"]),
    ("mobilize", "Roofing", "Mobilize - hoisting, staging & protection", (),
     lambda f, s: 2, ["sub_review"]),
    ("survey", "Roofing", "Existing roof survey / core cuts", (),
     lambda f, s: 1, ["mobilize"]),
    ("rtu", "Roofing", "Disconnect / raise rooftop equipment",
     ("rtu", "curbs"), lambda f, s: 2, ["survey"]),
    # the first area is opened up on its own (finish-to-start into the
    # deck inspection, review T10), the rest of the roof follows it
    ("tear1", "Roofing", lambda s: "Prepare first roof area for recover"
     if has(s, "recover") and not has(s, "tearoff") else "Tear-off - "
     "first roof area", (), lambda f, s: 1,
     ["survey", "materials", "rtu"]),
    ("deck_insp", "Roofing", "Deck inspection - first area torn off", (),
     lambda f, s: 1, ["tear1"]),
    ("tearoff", "Roofing", lambda s: "Prepare remaining roof for recover"
     if has(s, "recover") and not has(s, "tearoff") else "Tear-off "
     "existing roofing - remaining areas", (), lambda f, s: 2 + 0.7 * f,
     ["tear1"]),
    ("deck", "Roofing", "Deck repair (unit price / allowance)", ("deck",),
     lambda f, s: 2, ["deck_insp"]),
    # the nailers go in at the opened edges and curbs while the field
    # insulation starts (they're set to its height before it reaches them)
    ("nailers", "Roofing", "Wood nailers & blocking at edges and curbs",
     (), lambda f, s: 2, ["deck_insp"]),
    ("insul", "Roofing", "Roof insulation & cover board", (),
     lambda f, s: 2 + 0.5 * f, ["deck_insp", "deck"]),
    # lead-in (LEAD_INS) for the work the old 1 - 3 day lag stood for
    ("seam_test", "Roofing", "Membrane test seams & adhesion test", (),
     lambda f, s: 1, ["insul:SS"]),
    ("membrane", "Roofing", "Roof membrane", (), lambda f, s: 3 + 0.8 * f,
     ["seam_test"]),
    # flashing and edge metal once the test seams pass, behind the field
    # membrane
    ("flashing", "Roofing", "Flashings, curbs & penetrations", (),
     lambda f, s: 3 + 0.3 * f, ["nailers", "seam_test"]),
    ("sheetmetal", "Roofing", "Sheet metal - edge, coping, gutters & "
     "downspouts", ("sheetmetal",), lambda f, s: 3 + 0.3 * f,
     ["nailers", "seam_test"]),
    ("reset", "Roofing", "Reset & reconnect rooftop equipment",
     ("rtu", "curbs"), lambda f, s: 2, ["flashing"]),
    # the tear-off, insulation and membrane finish before the inspection
    # (their other successors start with them: no dangling finish)
    ("mfr", "Roofing", "Manufacturer's inspection & warranty", (),
     lambda f, s: 1, ["flashing", "sheetmetal", "reset", "tearoff",
                      "insul", "membrane"]),
] + _close(["mfr"])


def _utility_name(s):
    parts = [n for k, n in (("storm", "storm"), ("sewer", "sanitary sewer"),
                            ("water", "water"), ("force_main", "force main"))
             if has(s, k)]
    return "Underground utilities" + (f" - {', '.join(parts)}" if parts
                                      else "")


SITEWORK = _start("Submittals - materials, mix designs & pipe") + [
    ("mobilize", "Sitework", "Mobilize", (), lambda f, s: 3,
     ["sub_review"]),
    ("survey", "Sitework", "Survey & staking", (), lambda f, s: 2,
     ["mobilize"]),
    ("erosion", "Sitework", "Erosion control (SWPPP)", (), lambda f, s: 3,
     ["mobilize"]),
    ("demo", "Sitework", "Demolition & removals", ("demolition",),
     lambda f, s: 5, ["erosion"]),
    ("clearing", "Sitework", "Clearing & grubbing", ("clearing",),
     lambda f, s: 4, ["erosion", "demo"]),
    ("grading", "Sitework", "Earthwork & grading", ("grading", "paving"),
     lambda f, s: 10, ["clearing", "survey", "demo", "erosion"]),
    ("util_layout", "Utilities", UTIL_LAYOUT_NAME, ("utilities",),
     lambda f, s: 3, ["grading:SS"]),
    ("utilities", "Utilities", _utility_name, ("utilities",),
     lambda f, s: max(8, s.get("pipe_lf", 0) / 80), ["util_layout"]),
    ("util_test", "Utilities", "Utility testing (pressure, mandrel, "
     "bacteriological)", ("utilities",), lambda f, s: 3, ["utilities"]),
    ("base", "Paving", "Subgrade & aggregate base", ("paving",),
     lambda f, s: 5, ["grading", "utilities"]),
    ("curb", "Paving", "Curb, gutter & sidewalks", ("curb_gutter",),
     lambda f, s: 6, ["base"]),
    ("paving", "Paving", "Paving", ("paving",), lambda f, s: 5,
     ["base", "curb"]),
    ("striping", "Paving", "Striping & signage", ("paving",),
     lambda f, s: 2, ["paving"]),
    ("landscape", "Restoration", "Landscaping, seeding & restoration",
     ("landscape",), lambda f, s: 5, ["paving", "util_test"]),
    ("stabilize", "Restoration", "Final stabilization & SWPPP closeout",
     (), lambda f, s: 3, ["landscape", "striping", "util_test", "grading"]),
] + _with_final_insp(_close(["stabilize"]))


LIFT = _start(lambda s: "Submittals - " + ", ".join(
    ["pumps", "control panel"] + (["generator"] if has(s, "generator")
                                  else []) +
    (["precast"] if has(s, "wet_well") else []))) + [
    ("proc_pumps", "Procurement", _lead("pump", "pumps"), (),
     _lead_days("pump"), ["sub_review"]),
    ("proc_panel", "Procurement", "Pump control panel - fabricate", (),
     lambda f, s: 60, ["sub_review"]),
    ("proc_gen", "Procurement", _lead("generator", "standby generator"),
     ("generator",), _lead_days("generator"), ["sub_review"]),
    ("proc_precast", "Procurement", "Precast wet well / vault - fabricate",
     ("wet_well", "valve_vault"), lambda f, s: 30, ["sub_review"]),
    ("mobilize", "Site & Structures", "Mobilize", (), lambda f, s: 3,
     ["sub_review"]),
    ("bypass", "Site & Structures", "Bypass pumping - set up & maintain",
     ("bypass",), lambda f, s: 3, ["mobilize"]),
    ("demo", "Site & Structures", "Demolition of existing station",
     ("demolition",), lambda f, s: 5, ["bypass", "mobilize"]),
    ("excavate", "Site & Structures", "Excavation, shoring & dewatering",
     (), lambda f, s: 6, ["demo", "mobilize"]),
    ("wetwell", "Site & Structures", "Wet well - set precast / cast in "
     "place", (), lambda f, s: 6, ["excavate", "proc_precast"]),
    ("vault", "Site & Structures", "Valve vault", ("valve_vault",),
     lambda f, s: 4, ["wetwell"]),
    ("piping", "Site & Structures", lambda s: "Force main & yard piping"
     if has(s, "force_main") else "Yard piping & connections", (),
     lambda f, s: max(5, s.get("pipe_lf", 0) / 80), ["wetwell"]),
    ("backfill", "Site & Structures", "Backfill", (), lambda f, s: 3,
     ["wetwell", "vault"]),
    ("pumps", "Mechanical & Electrical", lambda s: f"Set {lab(s, 'pump')},"
     " rails & discharge piping", (), lambda f, s: 3,
     ["proc_pumps", "vault", "backfill"]),
    ("elec", "Mechanical & Electrical", "Electrical service, conduit & "
     "control panel installation", (), lambda f, s: 8,
     ["proc_panel", "backfill"]),
    ("gen", "Mechanical & Electrical", lambda s: f"Generator pad, set "
     f"{lab(s, 'generator')} & ATS", ("generator",), lambda f, s: 5,
     ["proc_gen", "backfill"]),
    ("scada", "Mechanical & Electrical", "SCADA / telemetry & alarms",
     ("scada",), lambda f, s: 4, ["elec"]),
    ("fm_test", "Startup", "Force main pressure test", ("force_main",),
     lambda f, s: 2, ["piping"]),
    # hold points (review T3: a station job had none): the trades'
    # inspections before startup, a final inspection before Substantial
    ("elec_insp", "Mechanical & Electrical", "Electrical inspection", (),
     lambda f, s: 1, ["elec", "gen"]),
    ("mech_insp", "Mechanical & Electrical", "Mechanical / piping "
     "inspection", ("hvac", "plumbing", "utilities"), lambda f, s: 1,
     ["pumps", "piping"]),
    ("startup", "Startup", "Pump startup & drawdown testing", (),
     lambda f, s: 3, ["pumps", "mech_insp", "elec_insp", "scada",
                      "fm_test"]),
    ("restore", "Startup", "Site restoration (paving / grading / fence)",
     (), lambda f, s: 5, ["startup"]),
    ("training", "Startup", "Operator training", (), lambda f, s: 1,
     ["startup"]),
]
LIFT = LIFT + _with_final_insp(_close(["restore"], ["training"]))


_PROCESS_KINDS = ("blower", "pump", "generator", "mcc", "switchgear",
                  "transformer", "chiller", "boiler")


def _treatment(sc):
    t = _start("Submittals - process equipment, electrical & "
               "instrumentation")
    long_ = [k for k in _PROCESS_KINDS if any(
        e.get("long_lead") for e in items(sc, k))]
    for k in long_:
        t.append((f"proc_{k}", "Procurement", _lead(k), (), _lead_days(k),
                  ["sub_review"]))
    if not long_:
        t.append(("proc_process", "Procurement", "Procure process equipment"
                  " - long lead (26 wk, assumed)", (), lambda f, s: 130,
                  ["sub_review"]))
    procs = [f"proc_{k}" for k in long_] or ["proc_process"]
    t += [
        ("mobilize", "Site & Structures", "Mobilize", (), lambda f, s: 5,
         ["sub_review"]),
        ("mop", "Site & Structures", "Maintenance of plant operations / "
         "sequence-of-construction plan", (), lambda f, s: 5, ["ntp"]),
        ("bypass", "Site & Structures", "Bypass pumping / temporary "
         "treatment", ("bypass",), lambda f, s: 5, ["mobilize", "mop"]),
        ("demo", "Site & Structures", "Demolition of existing process "
         "equipment", ("demolition",), lambda f, s: 10,
         ["mobilize", "mop", "bypass"]),
        ("yard", "Site & Structures", "Excavation & yard piping",
         ("utilities", "sewer", "water"),
         lambda f, s: max(10, s.get("pipe_lf", 0) / 60), ["mobilize"]),
        # the structure excavation starts when the yard piping does (both
        # after mobilizing: finish-to-start, no start-to-start link)
        ("excav", "Site & Structures", "Structure excavation, dewatering "
         "& mud mat", ("concrete",), lambda f, s: 5, ["mobilize"]),
        ("structures", "Site & Structures", "Concrete structures (basins / "
         "tanks / pads)", ("concrete",), lambda f, s: 40,
         ["excav", "demo"]),
        ("leak", "Site & Structures", "Leak testing of water-holding "
         "structures", ("concrete",), lambda f, s: 5, ["structures"]),
        ("bldg_fdn", "Site & Structures", "Process building foundations "
         "& slab - pour & cure", ("architectural",), lambda f, s: 10,
         ["excav"]),
        ("bldg", "Site & Structures", "Process building / enclosure",
         ("architectural",), lambda f, s: 30, ["bldg_fdn"]),
        ("equip", "Process & Electrical", lambda s: "Install process "
         "equipment" + (" - " + "; ".join(lab(s, k) for k in long_)
                        if long_ else ""), (),
         lambda f, s: 15, procs + ["structures", "demo"]),
        ("grout", "Process & Electrical", "Equipment anchors, base grout "
         "& cure - first units", (), lambda f, s: 5, ["equip:SS"]),
        ("mech", "Process & Electrical", "Process mechanical piping & "
         "valves", (), lambda f, s: 20, ["grout"]),
        ("elec", "Process & Electrical", "Electrical - MCCs, power & "
         "conduit", (), lambda f, s: 25, ["grout"]),
        ("ic_panels", "Process & Electrical", "Control panels, instrument "
         "stands & conduit stub-ups", ("scada",), lambda f, s: 10,
         ["grout"]),
        ("ic", "Process & Electrical", "Instrumentation, controls & SCADA "
         "integration", ("scada",), lambda f, s: 15, ["ic_panels"]),
        # hold points (review T3): the trades' inspections before
        # startup, a final inspection before Substantial Completion
        ("mech_insp", "Process & Electrical", "Mechanical / process piping "
         "inspection", (), lambda f, s: 1, ["mech"]),
        ("elec_insp", "Process & Electrical", "Electrical inspection", (),
         lambda f, s: 1, ["elec"]),
        ("startup", "Startup", "Equipment startup & manufacturer field "
         "services", (), lambda f, s: 10, ["mech_insp", "elec_insp", "ic",
                                           "leak", "equip"]),
        ("process", "Startup", "Process startup & performance testing", (),
         lambda f, s: 15, ["startup"]),
        ("training", "Startup", "Operator training", (), lambda f, s: 3,
         ["startup"]),
        ("restore", "Startup", "Site restoration", (), lambda f, s: 5,
         ["process", "bldg", "yard"]),
    ]
    return t + _with_final_insp(_close(["process", "restore"],
                                       ["training"], 10))


RENOVATION = [
    ("ntp", "Preconstruction", "Notice to Proceed", (), lambda f, s: 0, []),
    ("submittals", "Preconstruction", "Submittals & procurement", (),
     lambda f, s: 15, ["ntp"]),
    ("permit", "Preconstruction", PERMIT_NAME, (), lambda f, s: 10,
     ["ntp"]),
    ("trade_permits", "Preconstruction", trade_permits_name,
     ("plumbing", "hvac", "electrical", "fire_supp"), lambda f, s: 3,
     ["permit"]),
    ("mobilize", "Preconstruction", "Mobilize, phasing & protection "
     "(temporary partitions)", (), lambda f, s: 3, ["permit"]),
    ("abate", "Demolition", "Hazardous material abatement",
     ("abatement",), lambda f, s: 5 + f, ["mobilize"]),
    ("demo", "Demolition", "Selective demolition", (),
     lambda f, s: 3 + 1.5 * f, ["mobilize", "abate"]),
    ("framing", "Rough-ins", "Interior framing & partitions",
     ("architectural",), lambda f, s: 4 + 1.5 * f, ["demo"]),
    ("plumb_rough", "Rough-ins", "Plumbing rough-in", ("plumbing",),
     lambda f, s: 4 + f, ["demo", "trade_permits"]),
    ("hvac_rough", "Rough-ins", "HVAC rough-in & ductwork", ("hvac",),
     lambda f, s: 5 + f, ["demo", "trade_permits"]),
    # lead-ins (LEAD_INS) for the work the old 3 day lags stood for
    ("elec_layout", "Rough-ins", "Electrical layout - device & box "
     "locations walked", ("electrical",), lambda f, s: 3,
     ["framing:SS"]),
    ("elec_rough", "Rough-ins", "Electrical rough-in", ("electrical",),
     lambda f, s: 5 + f, ["elec_layout", "demo", "trade_permits"]),
    ("fs_rough", "Rough-ins", "Fire sprinkler rough-in / modifications",
     ("fire_supp",), lambda f, s: 3 + f / 2, ["demo", "trade_permits"]),
    ("lv_boxes", "Rough-ins", LV_BOXES_NAME, ("fire_alarm", "technology"),
     lambda f, s: 3, ["elec_rough:SS"]),
    ("fa_rough", "Rough-ins", "Fire alarm & low voltage rough-in",
     ("fire_alarm", "technology"), lambda f, s: 3 + f / 2, ["lv_boxes"]),
    ("inspect", "Rough-ins", "Rough-in inspections", (), lambda f, s: 2,
     ["framing", "plumb_rough", "hvac_rough", "elec_rough", "fs_rough",
      "fa_rough"]),
    ("drywall", "Finishes", "Drywall hang, tape & finish",
     ("finishes", "architectural"), lambda f, s: 6 + 2 * f, ["inspect"]),
    ("ceilings", "Finishes", "Ceilings", ("finishes", "architectural"),
     lambda f, s: 3 + f, ["drywall"]),
    ("paint", "Finishes", "Painting", ("finishes", "architectural"),
     lambda f, s: 4 + f, ["drywall"]),
    ("flooring", "Finishes", "Flooring", ("finishes", "architectural"),
     lambda f, s: 3 + f, ["paint", "ceilings"]),
    ("doors", "Finishes", "Doors, frames & hardware",
     ("openings", "architectural"), lambda f, s: 3 + f / 2,
     ["paint", "submittals"]),
    ("casework", "Finishes", "Casework, specialties & accessories",
     ("specialties", "architectural"), lambda f, s: 3 + f / 2,
     ["paint", "submittals"]),
    ("mep_trim", "MEP Trim & Startup", without_electrical(
        "Plumbing & electrical trim", "Plumbing trim", "Electrical trim"),
     ("plumbing", "electrical"), lambda f, s: 4 + f / 2, ["paint"]),
    ("hvac_trim", "MEP Trim & Startup", "HVAC trim - grilles, diffusers & "
     "equipment connections", ("hvac",), lambda f, s: 2 + f / 2,
     ["ceilings", "paint"]),
    ("fs_trim", "MEP Trim & Startup", "Fire sprinkler trim - heads at "
     "finished ceilings", ("fire_supp",), lambda f, s: 2 + f / 2,
     ["ceilings"]),
    ("hvac_start", "MEP Trim & Startup", "HVAC startup, test & balance",
     ("hvac",), lambda f, s: 3, ["mep_trim", "hvac_trim", "ceilings"]),
    ("fa_final", "MEP Trim & Startup", "Fire alarm & sprinkler testing",
     ("fire_alarm", "fire_supp"), lambda f, s: 2, ["mep_trim", "fs_trim"]),
    ("punch", "Closeout", "Punch list & corrections", (), lambda f, s: 5,
     ["flooring", "doors", "casework", "mep_trim", "hvac_start",
      "fa_final", "inspect"]),
    ("co", "Closeout", "Final inspections & certificate of occupancy", (),
     lambda f, s: 3, ["punch"]),
    ("sc", "Closeout", "Substantial Completion", (), lambda f, s: 0,
     ["co"]),
    ("clean", "Closeout", "Final cleaning", (), lambda f, s: 2, ["sc"]),
    ("closeout", "Closeout", "Closeout documents, O&Ms & warranties", (),
     lambda f, s: 10, ["sc"]),
    ("fc", "Closeout", "Final Completion", (), lambda f, s: 0,
     ["clean", "closeout"]),
]

UNKNOWN_TEMPLATE = _start("Submittals & procurement") + [
    ("mobilize", "Work", "Mobilize", (), lambda f, s: 3, ["sub_review"]),
    ("work", "Work", "Project work - TYPE NOT RECOGNIZED: pick the project "
     "type and rebuild", (), lambda f, s: 20, ["mobilize"]),
] + _close(["work"])

# "FOLLOWING COMPLETION OF X, PAINT ...": the clause first, the work after
_CLAUSE_FIRST = re.compile(r"^\s*((?:FOLLOWING|AFTER|ONCE|UPON)\b[^,]{3,120}),"
                           r"\s*(\S.*)$", re.I | re.S)
_CLAUSE_AFTER = re.compile(r"\b(?:FOLLOWING|AFTER|ONCE|UPON)\b", re.I)


def split_clause(text):
    """(the work, the "following ..." clause) of a listed item: "PAINT ALL
    FRAMES FOLLOWING COMPLETION OF CAULKING" and "FOLLOWING COMPLETION OF
    CAULKING, PAINT ALL FRAMES" both give ("PAINT ALL FRAMES", "FOLLOWING
    COMPLETION OF CAULKING")."""
    m = _CLAUSE_FIRST.match(text)
    if m:
        return m.group(2).strip(), m.group(1).strip()
    m = _CLAUSE_AFTER.search(text)
    if m and m.start() > 0:
        return text[:m.start()].strip(" ,"), text[m.start():].strip()
    return text.strip(), ""


# the same work by other words: "following the sealant work" means the
# caulking item
_SYNONYMS = [r"CAULK\w*|(?:JOINT )?SEALANTS?\b|SEALERS?\b",
             r"PAINT\w*|REPAINT\w*|COATINGS?\b|PRIM(?:E|ER|ING)\b",
             _WASH + r"|\bWASH(?:ING)?\b",
             r"DRYWALL|GYP\w*|NAIL POPS?|SHEETROCK|WALLBOARD",
             r"STUCCO|EIFS", r"\bTILE|GROUT", r"FLOORING|CARPET|\bLVT\b|"
             r"\bVCT\b", r"DEMOLI\w*|\bDEMO\b", r"FRAMING|PARTITIONS?\b",
             r"ROOF\w*", r"CEILINGS?\b", r"STRUCTURAL STEEL|CORROSION|RUST"]

# a default order across trades for listed items (interior work):
# demo -> framing -> drywall -> ceilings -> paint -> flooring -> specialties
_STAGES = [("specialties", r"SPECIALT|ACCESSOR|SIGNAGE|TOILET PARTITION|"
                           r"CASEWORK|MILLWORK|CABINET|FIRE EXTINGUISHER|"
                           r"MARKERBOARD|WHITEBOARD|LOCKERS?\b|BLINDS|"
                           r"WINDOW TREATMENT|CORNER GUARD", 6),
           ("demo", r"DEMOLI|\bDEMO\b|TEAR[- ]?OUT", 0),
           ("flooring", r"FLOORING|CARPET|\bLVT\b|\bVCT\b|VINYL (?:PLANK|"
                        r"TILE)|RESILIENT|FLOOR (?:TILE|COVERING|FINISH)|"
                        r"RUBBER BASE|EPOXY FLOOR", 5),
           ("ceilings", r"ACOUSTIC\w* (?:CEILING|TILE)|SUSPENDED CEILING|"
                        r"CEILING (?:TILES?|GRID|SYSTEM|PANELS?)\b|\bACT\b|"
                        r"\bCEILINGS\b", 3),
           ("drywall", r"DRYWALL|GYP|SHEETROCK|WALLBOARD|NAIL POP|TAPE AND "
                       r"FINISH", 2),
           ("framing", r"FRAMING|(?<!TOILET )PARTITIONS?\b|\bSTUDS?\b|"
                       r"FURRING|\bFRAME NEW\b", 1)]
_PAINT_STAGE = 4
_EXTERIOR = re.compile(r"\bEXTERIOR|\bOUTSIDE|FA[CÇ]ADE|STUCCO|EIFS|"
                       r"RAILINGS?\b|\bROOF|SIDING|SOFFIT|FASCIA|"
                       r"WINDOWS?\b(?! (?:BLINDS|TREATMENTS?|SHADES))|"
                       r"BENEATH|\bSITE\b|PARKING|SIDEWALK|ENTRANCE STEPS")


def item_stage(text):
    """Where a listed item falls in the default trade order (0 demo ... 6
    specialties), or None."""
    up = text.upper()
    for _name, rx, k in _STAGES:
        if re.search(rx, up):
            return k
    return _PAINT_STAGE if item_trade(up) == "painting" else None


def _strip_mark(text):
    return _MARK.sub("", str(text).strip()).strip()


def listed_scope(sc):
    """Scope activities from the drawings' own list: each DESCRIPTION OF
    WORK item, each "... SCOPE ONLY" note, and a coordination activity for
    work the drawings say is by others (one per excluded equipment kind).
    [(key, name, days)]."""
    out = []
    for n, it in enumerate(sc.get("scope_items") or (), 1):
        main, clause = split_clause(it)
        text = main if _CLAUSE_FIRST.match(it) else it
        out.append((f"item{n}", f"{n}. {item_name(text)}", item_days(main)))
    excl = sc.get("exclusions") or ()
    by_others = [e for e in excl if not e.get("only") and not e.get("ofci")]
    gen = any("generator" in e.get("kinds", ()) for e in by_others)
    for n, e in enumerate([e for e in excl if e.get("only")], 1):
        t = re.sub(r"\b(?:PRICE|SCOPE ONLY|PROVIDE|FURNISH AND INSTALL)\b",
                   "", _strip_mark(e["text"]), flags=re.I)
        if not work_words(t):
            continue                   # "SEE SHEET A2 - SCOPE ONLY"
        name = item_name(t)
        if len(re.sub(r"[^A-Za-z]", "", name)) < 3:
            name = "Limited scope item"
        if gen and re.search(r"ENCLOSURE|PAD|SLAB|FENCE", t, re.I):
            name += " (for the generator by others)"
        out.append((f"only{n}", name, 8))
    covered, n = set(), 0
    for e in by_others:
        kinds = set(e.get("kinds") or ())
        if kinds and kinds <= covered:
            continue                   # that equipment has its row already
        covered |= kinds
        what = _what(re.split(_EXCL, _clean_excl(_strip_mark(
            e["text"])))[0])
        if not what:
            what = ", ".join(KINDS[k][3] for k in KINDS if k in kinds) or \
                "Work by others"
        n += 1
        out.append((f"byoth{n}", f"Coordinate work by others: {what} "
                    "(not in this contract)", 1))
        if n >= 4:
            break
    return out


def _depends(preds, a, b):
    """Does activity a already wait (directly or not) on b?"""
    todo, seen = [a], set()
    while todo:
        x = todo.pop()
        if x == b:
            return True
        if x in seen:
            continue
        seen.add(x)
        todo += [p.split(":")[0] for p in preds.get(x, ())]
    return False


def _renovation(sc):
    """A renovation. When the drawings list the work (a repairs and
    improvements job), the schedule is that list - not the generic
    interior fit-out trades; otherwise the fit-out template."""
    listed = listed_scope(sc)
    if len([k for k, _n, _d in listed if k.startswith(("item", "only"))]) \
            < 3:
        return RENOVATION
    flags = set(sc.get("flags") or ())
    acts = [t for t in RENOVATION if t[0] in ("ntp", "submittals",
                                              "permit", "mobilize")]
    texts = {f"item{n}": it.upper() for n, it in
             enumerate(sc.get("scope_items") or (), 1)}
    parts = {k: split_clause(t) for k, t in texts.items()}   # (main, clause)
    order = [k for k, _n, _d in listed]
    preds = {}

    def link(k, p):
        """k after p, unless that would close a loop."""
        if p != k and p not in preds[k] and not _depends(preds, p, k):
            preds[k].append(p)
    for key, name, _d in listed:
        preds[key] = ["ntp"] if key.startswith("byoth") else ["mobilize"]
    work = [k for k in order if not k.startswith("byoth")]
    mains = {k: parts[k][0] if k in parts else
             next(n for kk, n, _d in listed if kk == k).upper()
             for k in work}
    # 1. what the item itself says: "... following completion of caulking"
    for k in work:
        clause = parts.get(k, ("", ""))[1]
        if not clause:
            continue
        hit = False
        for rx in _SYNONYMS:
            if re.search(rx, clause):
                for o in work:
                    if o != k and re.search(rx, mains[o]):
                        link(k, o)
                        hit = True
        if not hit:
            m = re.search(r"(?:FOLLOWING|AFTER|ONCE|UPON) (?:THE )?"
                          r"(?:COMPLETION OF )?(?:THE )?([A-Z]{4,})", clause)
            if m:
                stem = m.group(1)[:5]
                for o in work:
                    if o != k and stem in mains[o]:
                        link(k, o)
                        break
    # 2. material to buy first; one crew per trade, in list order; the
    # power wash before exterior coatings
    last_of = {}
    wash = [k for k in work if re.search(_WASH, mains[k])]
    for k in work:
        main = mains[k]
        if re.search(r"\bINSTALL|\bREPLACE\b|\bFURNISH|\bNEW\b", main):
            link(k, "submittals")
        trade = item_trade(main)
        if trade in last_of:
            link(k, last_of[trade])
        if trade:
            last_of[trade] = k
        if wash and k not in wash and trade in (
                "painting", "sealants", "stucco") and \
                "INTERIOR" not in texts.get(k, main):
            for w in wash:
                link(k, w)
    # 3. the default trade order between interior items (only when both
    # trades are listed)
    stage = {k: item_stage(mains[k]) for k in work
             if not _EXTERIOR.search(texts.get(k, mains[k]))}
    for k, st in stage.items():
        if st is None:
            continue
        lower = [v for v in stage.values() if v is not None and v < st]
        if not lower:
            continue
        prev = max(lower)
        for o, so in stage.items():
            if so == prev:
                link(k, o)
    for key, name, days in listed:
        acts.append((key, "Scope of Work", name, (),
                     lambda f, s, d=days: d, preds[key]))
    keys = list(order)
    # sheets of a discipline the list doesn't mention: their own activity
    words = " ".join(sc.get("scope_items") or ()).upper()
    for flag, key, name, rx in (
            ("hvac", "hvac_work", "HVAC work per the M sheets",
             r"HVAC|DUCT|AIR HANDL|HEAT PUMP|MINI.?SPLIT|EXHAUST"),
            ("electrical", "elec_work", "Electrical work per the E sheets",
             r"ELECTRIC|LIGHT|PANEL|RECEPTACLE|WIRING"),
            ("plumbing", "plumb_work", "Plumbing work per the P sheets",
             r"PLUMB|WATER|FIXTURE|PIPING"),
            ("fire_supp", "fs_work", "Fire sprinkler work per the FP sheets",
             r"SPRINKLER|FIRE PROTECTION|FIRE SUPPRESSION")):
        if flag in flags and not re.search(rx, words):
            acts.append((key, "Scope of Work", name, (),
                         lambda f, s: 5 + f, ["submittals", "mobilize"]))
            keys.append(key)
    work = [k for k in keys if not k.startswith("byoth")]
    acts.append(("inspect", "Closeout", "Inspections", (), lambda f, s: 2,
                 work))
    # the work by others is coordinated before the punch list (no open
    # end - review T10 logic)
    close = _close(["inspect"] + [k for k in keys if k.startswith("byoth")],
                   ["final_insp"])
    return acts + close[:1] + [
        ("final_insp", "Closeout", "Final inspection", (), lambda f, s: 1,
         ["punch"])] + close[1:]


_TEMPLATES = {"renovation": _renovation, "standby_generator": GENERATOR,
              "electrical_service": ELECTRICAL, "hvac_replacement": _hvac,
              "reroof": REROOF, "sitework_only": SITEWORK,
              "pump_or_lift_station": LIFT, "treatment_plant": _treatment,
              UNKNOWN: UNKNOWN_TEMPLATE}

# kinds a template already schedules; other long-lead equipment found in
# the set gets its own procurement activity, feeding the anchor activity
_COVERED = {"standby_generator": {"generator", "ats", "switchgear",
                                  "fuel_tank"},
            "electrical_service": {"switchgear", "transformer"},
            "hvac_replacement": set(_HVAC_KINDS),
            "pump_or_lift_station": {"pump", "generator"},
            "treatment_plant": set(_PROCESS_KINDS),
            "reroof": set(KINDS), "sitework_only": set(KINDS)}
_ANCHOR = {"new_building": ("submittals", "mep_trim"),
           "renovation": ("submittals", "mep_trim"),
           "standby_generator": ("sub_review", "pull"),
           "electrical_service": ("sub_review", "terminate"),
           "hvac_replacement": ("sub_review", "elec"),
           "pump_or_lift_station": ("sub_review", "elec"),
           "treatment_plant": ("sub_review", "equip"),
           UNKNOWN: ("sub_review", "work")}
# the procurement row a template has for a kind (besides proc_<kind>)
_PROC_KEYS = {"generator": ("proc_gen",), "ats": ("proc_ats",),
              "switchgear": ("proc_swgr",), "transformer": ("proc_xfmr",),
              "fuel_tank": ("proc_tank",), "pump": ("proc_pumps",)}


# ------------------------------------------- set items' procurement (T4)
# The long-lead materials a set's own quantities show - Generate Set's
# quantity rows, a takeoff - each get submit -> approve -> fabricate &
# deliver, the delivery a predecessor of its install row (review T4: a
# Generate Set project had one "Submittals & procurement" row for all).
# (install activity, productivity family whose MEASURED quantity says the
# item is in the job). Tagged equipment keeps its own procurement
# (template() below, the types' proc_ rows).
_SET_ITEMS = [("windows", "windows"), ("oh_doors", "overhead_doors"),
              ("roofstruct", "roofing"), ("roofing", "roofing"),
              ("doors", "doors")]
CHAIN_DAYS = {"sub": 10, "appr": 10}       # assumed: prepare, review


def _setq(sc, key):
    return (sc.get("set_quantities") or {}).get(key) or (0, "")


def overhead_doors_name(s):
    n = _setq(s, "overhead_doors")[0]
    return ("Overhead doors" + (f" ({n:g})" if n else "") +
            (", dock levelers & seals" if _setq(s, "dock_levelers")[0]
             else ""))


def _item_of(install, sc):
    """(item key, what it's called) for an install row's material."""
    if install == "windows":
        return ("storefront", "storefront & windows") if \
            _setq(sc, "storefront")[0] else ("windows", "windows")
    if install == "oh_doors":
        return "overhead_doors", "overhead doors" + (
            " & dock equipment" if _setq(sc, "dock_levelers")[0] else "")
    if install == "roofstruct":
        return ("trusses", "roof trusses") if roof_trusses(sc) else \
            ("joists", "steel joists & roof deck")
    if install == "roofing":
        return "roofing", "roofing materials"
    return "doors", "hollow metal frames, doors & hardware"


# a building this size or smaller with no steel named is framed in wood
# (trusses / rafters), unless the set names steel joists (review 0.12.38
# #9: a 1,525 SF house got "steel joists & roof deck")
SMALL_BUILDING_SF = 5000


def roof_trusses(sc):
    """True when the roof structure is trusses / rafters, not steel joists:
    the set names no steel joists and the roof is pitched, or the building
    is wood-framed, residential, or small (SMALL_BUILDING_SF) with no
    steel or warehouse in the set. A low-slope roof the set measures is
    joists and deck even on a "residential" set."""
    if sc.get("joists_named"):
        return False
    how = _setq(sc, "roof_sq")[1]
    flags = set(sc.get("building_flags") or ()) | set(sc.get("flags") or ())
    if "pitched" in how or "wood" in flags:
        return True
    # a low-slope roof the set gives is joists and deck, whatever the
    # words read (review 0.12.39 #1: checked before the residential flag)
    if "low-slope" in how:
        return False
    if sc.get("residential"):
        return True
    if sc.get("warehouse") or "steel" in flags:
        return False
    return float(sc.get("area_sf") or 0) <= SMALL_BUILDING_SF


def set_items(sc, table=None):
    """[{item, install, label, quantity, unit, of, how, source}]: the long-
    lead materials whose quantity the set itself gives (source "genset" or
    "takeoff" - an estimate from the floor area is no evidence of one)."""
    from . import productivity as _prod
    table = table or _prod.defaults()
    est = _prod.estimates(sc, table)
    out = []
    for install, fam in _SET_ITEMS:
        q, how, measured = _prod.quantity(fam, sc, table, est)
        if not measured or not q or q <= 0:
            continue
        item, label = _item_of(install, sc)
        f = table["families"][fam]
        out.append({"item": item, "install": install, "label": label,
                    "quantity": q, "unit": f["unit"], "of": f["of"],
                    "how": how, "source": "genset" if
                    how.startswith("genset") else "takeoff"})
    return out


def _chain_rows(sc, it):
    item, label = it["item"], it["label"]
    w = lead_weeks(sc, item)
    tail = ", assumed" if lead_assumed(sc, item) else ""
    return [
        (f"sub_{item}", "Procurement", f"Submit {label} - shop drawings & "
         "product data", (), lambda f, s: CHAIN_DAYS["sub"], ["ntp"]),
        (f"appr_{item}", "Procurement", f"Review & approve {label} "
         "submittal", (), lambda f, s: CHAIN_DAYS["appr"], [f"sub_{item}"]),
        (f"deliver_{item}", "Procurement", f"Fabricate & deliver {label} - "
         f"lead time ({w:g} wk{tail})", (), lambda f, s, d=w * 5: d,
         [f"appr_{item}"]),
    ]


def _add_set_chains(sc, base):
    """`base` with a procurement chain per set item whose install row is
    in the scope; the generic submittals row is then the other
    materials'."""
    flags = set(sc.get("flags") or ())
    by = {t[0]: t for t in base}
    chains, feeds = [], {}
    for it in set_items(sc):
        t = by.get(it["install"])
        if t is None or (t[3] and not set(t[3]) & flags) or \
                f"deliver_{it['item']}" in by:
            continue
        chains += _chain_rows(sc, it)
        feeds[it["install"]] = f"deliver_{it['item']}"
    if not chains:
        return base
    at = "submittals" if "submittals" in by else "ntp"
    out = []
    for t in base:
        if t[0] in feeds:
            t = t[:5] + (list(t[5]) + [feeds[t[0]]],)
        if t[0] == "submittals" and t[2] == "Submittals & procurement":
            t = (t[0], t[1], "Submittals & procurement - other "
                 "materials") + t[3:]
        out.append(t)
        if t[0] == at:
            out += chains
    return out


def chain_basis(key, sc, days):
    """(BASIS text, source) of a set item's procurement row, else None."""
    pre, _, item = key.partition("_")
    if pre not in ("sub", "appr", "deliver") or item not in SET_LEAD_WEEKS:
        return None
    it = next((x for x in set_items(sc) if x["item"] == item), None)
    if it is None:
        return None
    q = it["quantity"]
    qty = (f"{q:,.0f}" if q >= 10 else f"{q:g}") + \
        f" {it['unit']} {it['of']} ({it['how']})"
    if pre == "deliver":
        w = lead_weeks(sc, item)
        how = "assumed" if lead_assumed(sc, item) else "the lead time you " \
            "entered"
        return (f"lead time {w:g} wk = {days} d ({how}) for {qty}",
                it["source"])
    what = "submittal preparation" if pre == "sub" else \
        "architect / engineer review"
    return f"{what} {days} d (assumed) for {qty}", it["source"]


def _owner_name(what):
    return lambda s: (f"Owner delivers {what(s) if callable(what) else what}"
                      " (OFCI - date from the owner)")


def _ofci(sc):
    """[(key part, kind or None, what)] of the owner-furnished,
    contractor-installed equipment: each kind once, plus OFCI notes that
    name no equipment kind."""
    out, seen = [], set()
    for e in sc.get("equipment") or ():
        k = e["kind"]
        if e.get("ofci") and k not in seen:
            seen.add(k)
            out.append((k, k, lambda s, k=k: lab(s, k)))
    for n, e in enumerate(sc.get("exclusions") or (), 1):
        if not e.get("ofci"):
            continue
        ks = [k for k in e.get("kinds") or () if k in KINDS]
        for k in ks:
            if k not in seen:
                seen.add(k)
                out.append((k, k, lambda s, k=k: lab(s, k)))
        if not ks:
            what = _what(re.split(r"\bOWNER[- ]FURNISHED|FURNISHED BY|"
                                  r"\bOFCI\b|\bO\.\s?F\.", _clean_excl(
                                      _strip_mark(e["text"])),
                                  flags=re.I)[0]) or "owner-furnished items"
            out.append((f"item{n}", None, what[:1].lower() + what[1:]))
    return out


def template(type_key, sc, building_template=None):
    """The activity tuples for a type (new_building takes the caller's
    building template), plus a procurement activity for each long-lead
    item the type's own list doesn't cover. Owner-furnished, contractor-
    installed (OFCI) equipment: its procurement row becomes an "Owner
    delivers ..." milestone (we still install it)."""
    if type_key == "new_building":
        base = list(building_template or ())
    else:
        base = _TEMPLATES.get(type_key, UNKNOWN_TEMPLATE)
        base = list(base(sc) if callable(base) else base)
    if any(t[0] == "permit" for t in base):   # no mobilizing before it
        base = [t[:5] + (list(t[5]) + ["permit"],) if t[0] == "mobilize" and
                "permit" not in t[5] else t for t in base]
    if type_key in BUILDING_TYPES:     # the trades' own materials
        base = _add_set_chains(sc, base)
    keys = [t[0] for t in base]
    covered = _COVERED.get(type_key, set())
    after, anchor = _ANCHOR.get(type_key, (None, None))
    if after not in keys:
        after = next((k for k in ("sub_review", "submittals", "ntp")
                      if k in keys), None)
    if anchor not in keys:
        anchor = "punch" if "punch" in keys else None
    ofci = _ofci(sc)
    owner_kinds = {k for _p, k, _w in ofci if k}
    extra = []
    seen = set()
    for e in sc.get("equipment") or ():
        k = e["kind"]
        if not e.get("long_lead") or e.get("by_others") or k in covered \
                or k in seen or k in owner_kinds or not anchor:
            continue
        seen.add(k)
        extra.append((f"proc_x_{k}", "Procurement", _lead(k), (),
                      _lead_days(k), [after]))
    feeds = [x[0] for x in extra]
    installs = []
    for part, k, what in ofci:
        mine = [key for key in (f"proc_{k}",) + _PROC_KEYS.get(k, ())
                if key in keys] if k else []
        if mine:
            base = [(t[0], t[1], _owner_name(what), t[3], lambda f, s: 0,
                     t[5]) if t[0] in mine else t for t in base]
            continue
        if not after or not anchor:
            continue
        own = f"own_{part}"
        extra.append((own, "Procurement", _owner_name(what), (),
                      lambda f, s: 0, [after]))
        if k in covered:
            feeds.append(own)              # the template installs it
            continue
        inst = f"inst_{part}"
        name = (lambda s, w=what: f"Install owner-furnished "
                f"{w(s) if callable(w) else w} (OFCI)")
        installs.append((inst, own, name))
        feeds.append(inst)
    if not extra:
        return base
    phase = next((t[1] for t in base if t[0] == anchor), "Closeout")
    start = "mobilize" if "mobilize" in keys else after
    out = []
    for t in base:
        if t[0] == anchor:
            t = t[:5] + (list(t[5]) + feeds,)
        if t[0] == anchor:
            out += [(inst, phase, name, (), lambda f, s: 2, [own, start])
                    for inst, own, name in installs]
        out.append(t)
        if t[0] == after:
            out += extra
    return out
