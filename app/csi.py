"""CSI MasterFormat divisions, Uniformat II and a keyword classifier.
(From the Venice AI draft; the code reader was fixed.)

A cost code is how a GC's accounting system, its buyout packages and its
schedule of values agree on what a line item is.  Anything that produces a
quantity without a code is un-billable, so every assembly, cost book entry and
export carries one.
"""

import re

__all__ = ["DIVISIONS", "COST_TYPES", "division_title", "parse_code",
           "is_valid", "classify", "UNIFORMAT"]

DIVISIONS = {
    "01": "General requirements", "02": "Existing conditions",
    "03": "Concrete", "04": "Masonry", "05": "Metals",
    "06": "Wood, plastics and composites",
    "07": "Thermal and moisture protection", "08": "Openings",
    "09": "Finishes", "10": "Specialties", "11": "Equipment",
    "12": "Furnishings", "13": "Special construction",
    "14": "Conveying equipment", "21": "Fire suppression",
    "22": "Plumbing", "23": "Heating, ventilating and air conditioning",
    "25": "Integrated automation", "26": "Electrical",
    "27": "Communications", "28": "Electronic safety and security",
    "31": "Earthwork", "32": "Exterior improvements", "33": "Utilities",
    "34": "Transportation", "35": "Waterway and marine construction",
    "40": "Process interconnections", "41": "Material processing",
    "42": "Process heating, cooling and drying",
    "43": "Process gas and liquid handling",
    "44": "Pollution and waste control",
    "46": "Water and wastewater equipment",
    "48": "Electrical power generation",
}

UNIFORMAT = {
    "A": "Substructure", "B": "Shell", "C": "Interiors", "D": "Services",
    "E": "Equipment and furnishings", "F": "Special construction",
    "G": "Building sitework",
}

COST_TYPES = {
    "L": "Labour", "M": "Material", "E": "Equipment", "S": "Subcontract",
    "EQ": "Equipment rental", "O": "Other", "X": "Overhead and profit",
}

# division -> keywords used by classify()
KEYWORDS = {
    "02": ("demolition", "demo", "abatement", "asbestos", "sawcut"),
    "03": ("concrete", "footing", "slab", "grade beam", "rebar", "formwork",
           "pier", "pile cap", "curb", "podium", "topping"),
    "04": ("masonry", "cmu", "brick", "block", "mortar", "grout", "lintel",
           "veneer", "tie", "flashing"),
    "05": ("steel", "joist", "deck", "beam", "column", "bolt", "weld",
           "handrail", "lintel", "misc metals", "fireproofing", "stud rail"),
    "06": ("wood", "plywood", "sheathing", "truss", "millwork", "casework",
           "cabinet", "countertop", "blocking"),
    "07": ("roofing", "membrane", "insulation", "waterproofing", "flashing",
           "sealant", "caulk", "dampproof", "taper", "sheet metal roof"),
    "08": ("door", "frame", "hardware", "window", "glazing", "storefront",
           "curtain wall", "glass", "hollow metal", "overhead door"),
    "09": ("drywall", "gypsum", "board", "tape", "texture", "paint", "coating",
           "flooring", "carpet", "tile", "acoustical", "ceiling", "terrazzo",
           "stucco", "plaster", "resilient", "base"),
    "10": ("specialty", "toilet accessory", "partition", "signage",
           "fire extinguisher", "locker", "flagpole", "awning"),
    "11": ("equipment", "appliance", "kitchen", "laboratory", "loading dock",
           "projection", "athletic"),
    "12": ("furnishing", "furniture", "window treatment", "artwork"),
    "14": ("elevator", "escalator", "lift", "conveyor"),
    "21": ("sprinkler", "fire suppression", "standpipe", "fire pump", "head"),
    "22": ("plumbing", "pipe", "fixture", "water closet", "lavatory", "sink",
           "drain", "water heater", "gas piping", "storm"),
    "23": ("hvac", "duct", "diffuser", "vav", "ahu", "chiller", "boiler",
           "fan", "damper", "insulation pipe", "refrigerant"),
    "26": ("electrical", "conduit", "wire", "panel", "receptacle", "switch",
           "lighting", "fixture", "transformer", "grounding", "device"),
    "27": ("communications", "data", "telecom", "cabling", "rack", "av"),
    "28": ("fire alarm", "security", "access control", "cctv", "card reader"),
    "31": ("earthwork", "excavation", "backfill", "grading", "fill",
           "dewatering", "shoring", "compaction"),
    "32": ("paving", "asphalt", "curb", "sidewalk", "landscape", "fence",
           "striping", "irrigation", "site concrete"),
    "33": ("utility", "sanitary sewer", "water main", "storm sewer",
           "manhole", "ductbank"),
}

_SPACED = re.compile(r"^(\d{1,2})(?:[\s.-]+(\d{2}))?(?:[\s.-]+(\d{2}))?"
                     r"(?:[\s.-]+(\d{1,2}))?$")
_PACKED = re.compile(r"^(\d{2})(\d{2})(\d{2})?(?:\.(\d{1,2}))?$")


def parse_code(code):
    """'092116', '09 21 16', '9.21.16' -> '09 21 16'; a level-4 suffix is
    kept ('09 21 16.13'). '' if it isn't a MasterFormat number."""
    t = str(code or "").strip()
    m = _PACKED.match(t) or _SPACED.match(t)
    if not m:
        return ""
    div = m.group(1).zfill(2)
    a, b, ext = m.group(2) or "00", m.group(3) or "00", m.group(4)
    out = f"{div} {a} {b}"
    return f"{out}.{ext.zfill(2)}" if ext else out


def is_valid(code):
    return bool(parse_code(code)) and parse_code(code)[:2] in DIVISIONS


def division_title(code):
    return DIVISIONS.get(parse_code(code)[:2], "Unclassified")


def classify(text):
    """Best-guess division code for a description, or '' if unsure."""
    t = " " + re.sub(r"[^a-z0-9 ]", " ", str(text or "").lower()) + " "
    best, score = "", 0
    for div, words in KEYWORDS.items():
        hits = sum(1 for w in words if " %s " % w in t or t.endswith(" %s " % w))
        if hits > score:
            best, score = div, hits
    return "%s 00 00" % best if best else ""
