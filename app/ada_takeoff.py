"""ADA from the drawings: counts and measured sizes from the takeoff.

Counts are read by their group name - "Parking", "Accessible Parking",
"Van Parking", "Water Closet - Men", "Urinal - Men", "Lavatory - Men",
"Seat", "Wheelchair Space", "Entrance", "Drinking Fountain", "Guest
Room", "Dwelling Unit" ... - and fill the ADA Checker's boxes
(counts(doc) -> project fields). Toilet fixtures are grouped into rooms by
what follows a dash or colon in the group name ("WC - Men", "Lav: Men");
without one, all on a sheet are one room.

Lengths are measured sizes: a group named "Door Clear Width", "Accessible
Route", "Ramp Width", "Parking Space Width", "Access Aisle", "Turning
Space", "Toilet Compartment Width", "Counter Height", "Grab Bar Height"...
is checked against its 2010 ADA Standards minimum or maximum
(elements(doc) -> findings that point at the measurement, so they can be
clouded on the drawing)."""
import re

from . import units
from .ada_check import Finding

# (words in the group name, what it is, "min"|"max"|"range", inches, cite)
# first match wins, so the specific names come first
ELEMENTS = [
    (("ambulatory",), "Ambulatory compartment width", "range", (35, 37),
     "604.8.2.1"),
    (("compartment", "depth"), "Wheelchair compartment depth", "min", 56,
     "604.8.1.1"),
    (("toilet", "stall"), "Wheelchair compartment width", "min", 60,
     "604.8.1.1"),
    (("compartment",), "Wheelchair compartment width", "min", 60,
     "604.8.1.1"),
    (("van", "aisle"), "Van access aisle", "min", 60, "502.3.1"),
    (("access aisle",), "Access aisle", "min", 60, "502.3.1"),
    (("van", "space"), "Van parking space width", "min", 96, "502.2"),
    (("van", "stall"), "Van parking space width", "min", 96, "502.2"),
    (("parking", "width"), "Parking space width", "min", 96, "502.2"),
    (("stall", "width"), "Parking space width", "min", 96, "502.2"),
    (("grab bar", "height"), "Grab bar height", "range", (33, 36), "609.4"),
    (("side", "grab"), "Side wall grab bar length", "min", 42, "604.5.1"),
    (("rear", "grab"), "Rear wall grab bar length", "min", 36, "604.5.2"),
    (("water closet", "centerline"), "Water closet centerline from side "
     "wall", "range", (16, 18), "604.2"),
    (("wc", "centerline"), "Water closet centerline from side wall",
     "range", (16, 18), "604.2"),
    (("counter", "height"), "Sales / service counter height", "max", 36,
     "904.4.1"),
    (("counter", "length"), "Accessible counter length", "min", 36,
     "904.4.1"),
    (("dining", "height"), "Dining / work surface height", "range",
     (28, 34), "902.3"),
    (("work surface",), "Dining / work surface height", "range", (28, 34),
     "902.3"),
    (("reach",), "Reach to operable part", "max", 48, "308.2.1"),
    (("handrail", "height"), "Handrail height", "range", (34, 38), "505.4"),
    (("ramp", "rise"), "Ramp run rise", "max", 30, "405.6"),
    (("ramp", "width"), "Ramp clear width", "min", 36, "405.5"),
    (("landing",), "Ramp landing length", "min", 60, "405.7.3"),
    (("turning",), "Turning space diameter", "min", 60, "304.3.1"),
    (("passing",), "Passing space", "min", 60, "403.5.3"),
    (("door", "clear"), "Door clear width", "min", 32, "404.2.3"),
    (("door", "width"), "Door clear width", "min", 32, "404.2.3"),
    (("door", "pull"), "Pull-side maneuvering depth", "min", 60,
     "404.2.4.1"),
    (("door", "latch"), "Latch-side clearance (pull side)", "min", 18,
     "404.2.4.1"),
    (("accessible route",), "Accessible route clear width", "min", 36,
     "403.5.1"),
    (("route", "width"), "Accessible route clear width", "min", 36,
     "403.5.1"),
    (("corridor", "width"), "Accessible route clear width", "min", 36,
     "403.5.1"),
    (("walk", "width"), "Accessible route clear width", "min", 36,
     "403.5.1"),
    (("wheelchair space", "width"), "Wheelchair space width", "min", 36,
     "802.1.2"),
]


def _norm(group):
    return " " + re.sub(r"[^a-z0-9]+", " ", str(group or "").lower()) + " "


def element_rule(group):
    g = _norm(group)
    for words, label, op, val, cite in ELEMENTS:
        if all(f" {w} " in g or (" " in w and w in g) for w in words):
            return label, op, val, cite
    return None


def _ok(op, val, inches):
    if op == "min":
        return inches + 1e-6 >= val
    if op == "max":
        return inches - 1e-6 <= val
    lo, hi = val
    return lo - 1e-6 <= inches <= hi + 1e-6


def _need(op, val):
    if op == "min":
        return f"{val} in. min"
    if op == "max":
        return f"{val} in. max"
    return f"{val[0]}-{val[1]} in."


def elements(doc, items=None):
    """A finding for every measured length whose group names an ADA
    element. Each one carries page and ref (the measurement)."""
    from . import annotate
    out = []
    for it in items if items is not None else annotate.takeoff_items(doc):
        if it.get("type") != "length":
            continue
        rule = element_rule(it.get("group"))
        if not rule:
            continue
        label, op, val, cite = rule
        try:
            inches = units.measure_to_base(it["value"], it["unit"],
                                           "length") * 12
        except (units.UnitError, KeyError, TypeError, ValueError):
            continue
        out.append(Finding(
            f"{label} ({it.get('group')}, sheet {it.get('page', 0) + 1})",
            cite, _need(op, val), round(inches, 1),
            "ok" if _ok(op, val, inches) else "short",
            "Measured on the drawing", "Measured", it.get("page"),
            it.get("ref")))
    return out


# ------------------------------------------------------------ counts
# (field, words that must all be in the group name, words that must not)
COUNTS = [
    ("van", ("van",), ("aisle", "width")),
    ("accessible_parking", ("accessible", "parking"), ("aisle", "width")),
    ("accessible_parking", ("ada", "parking"), ("aisle", "width")),
    ("accessible_parking", ("hc", "parking"), ("aisle", "width")),
    ("parking", ("parking",), ("aisle", "width")),
    ("ambulatory_compartments", ("ambulatory",), ()),
    ("wheelchair_compartments", ("accessible", "stall"), ("parking",)),
    ("wheelchair_compartments", ("ada", "stall"), ("parking",)),
    ("wheelchair_compartments", ("wheelchair", "compartment"), ()),
    ("compartments", ("toilet", "stall"), ()),
    ("compartments", ("compartment",), ()),
    ("urinals", ("urinal",), ()),
    ("water_closets", ("water closet",), ()),
    ("water_closets", ("wc",), ()),
    ("water_closets", ("toilet",), ("room", "paper", "partition")),
    ("lavatories", ("lavatory",), ()),
    ("lavatories", ("lav",), ()),
    ("fountains_low", ("fountain", "low"), ()),
    ("fountains_high", ("fountain", "high"), ()),
    ("drinking_fountains", ("fountain",), ()),
    ("drinking_fountains", ("bottle filler",), ()),
    ("wheelchair_spaces", ("wheelchair", "space"), ()),
    ("companion_seats", ("companion",), ()),
    ("designated_aisle", ("designated", "aisle"), ()),
    ("aisle_seats", ("aisle", "seat"), ()),
    ("dining_seats", ("dining",), ()),
    ("seats", ("seat",), ()),
    ("accessible_entrances", ("accessible", "entrance"), ()),
    ("public_entrances", ("entrance",), ("service",)),
    ("guest_rooms", ("guest room",), ()),
    ("dwelling_units", ("dwelling",), ()),
    ("dwelling_units", ("apartment",), ()),
    ("dressing_rooms", ("dressing",), ()),
    ("dressing_rooms", ("fitting room",), ()),
    ("lockers", ("locker",), ()),
    ("patient_rooms", ("patient room",), ()),
]
ROOM_FIELDS = {"compartments", "wheelchair_compartments",
               "ambulatory_compartments", "urinals", "water_closets",
               "lavatories"}
SEAT_FIELDS = {"seats", "wheelchair_spaces", "companion_seats",
               "aisle_seats", "designated_aisle"}


def count_field(group):
    g = _norm(group)

    def has(w):
        return f" {w} " in g or (" " in w and w in g)
    for field, need, never in COUNTS:
        if all(has(w) for w in need) and not any(has(w) for w in never):
            return field
    return None


def _room_name(group, page):
    m = re.search(r"\s[-–:]\s*(.+)$|:\s*(.+)$", str(group or ""))
    name = (m.group(1) or m.group(2)).strip() if m else ""
    return name or f"Sheet {page + 1}"


def counts(doc, items=None):
    """{field: value} for the ADA Checker, plus "toilet_rooms",
    "assembly_areas" and "parking" lists, from the counts on the
    drawings. Only fields something was counted for are present."""
    from . import annotate
    flat, rooms, areas = {}, {}, {}
    lots = {}
    for it in items if items is not None else annotate.takeoff_items(doc):
        if it.get("type") != "count":
            continue
        field = count_field(it.get("group"))
        if not field:
            continue
        try:
            n = float(it.get("value") or 0)
        except (TypeError, ValueError):
            continue
        if n <= 0 or n != n:
            continue
        page = it.get("page", 0)
        if field in ROOM_FIELDS:
            r = rooms.setdefault(_room_name(it.get("group"), page), {})
            r[field] = r.get(field, 0) + n
        elif field in SEAT_FIELDS:
            a = areas.setdefault(_room_name(it.get("group"), page), {})
            a[field] = a.get(field, 0) + n
        elif field in ("parking", "accessible_parking", "van"):
            key = {"parking": "total", "accessible_parking": "accessible",
                   "van": "van"}[field]
            lot = lots.setdefault(page, {})
            lot[key] = lot.get(key, 0) + n
        else:
            flat[field] = flat.get(field, 0) + n
    out = {k: int(v) for k, v in flat.items()}
    for r in rooms.values():          # accessible stalls are stalls too
        extra = r.get("wheelchair_compartments", 0) + \
            r.get("ambulatory_compartments", 0)
        if extra:
            r["compartments"] = r.get("compartments", 0) + extra
    if rooms:
        out["toilet_rooms"] = [dict({k: int(v) for k, v in r.items()},
                                    name=name)
                               for name, r in sorted(rooms.items())]
    if areas:
        out["assembly_areas"] = [dict({k: int(v) for k, v in a.items()},
                                      name=name)
                                 for name, a in sorted(areas.items())]
    if lots:
        rows = []
        for page, lot in sorted(lots.items()):
            lot = {k: int(v) for k, v in lot.items()}
            # accessible and van stalls are parking spaces too
            lot["total"] = lot.get("total", 0) + lot.get("accessible", 0) + \
                lot.get("van", 0)
            lot["accessible"] = lot.get("accessible", 0) + lot.get("van", 0)
            lot["name"] = f"Parking, sheet {page + 1}"
            rows.append(lot)
        out["parking"] = rows
    if "fountains_low" in out or "fountains_high" in out:
        out["drinking_fountains"] = out.get("drinking_fountains", 0) + \
            out.get("fountains_low", 0) + out.get("fountains_high", 0)
    if "accessible_entrances" in out:
        out["public_entrances"] = out.get("public_entrances", 0) + \
            out["accessible_entrances"]
    return out


def markup(doc, findings, author=""):
    """A red cloud, with the finding as its note, around each measured
    element that falls short. Returns how many were added."""
    from . import annotate
    import fitz
    n = 0
    for f in findings:
        page, ref = getattr(f, "page", None), getattr(f, "ref", None)
        if f.status != "short" or page is None or not ref:
            continue
        pg = doc[page]              # kept: the annots need their page
        found = annotate.find_annots(pg, ref)
        if not found:
            continue
        a = found[0]
        pts = [fitz.Point(v) for v in (a.vertices or [])]
        r = fitz.Rect(pts[0], pts[0]) if pts else fitz.Rect(a.rect)
        for p in pts[1:]:
            r |= p
        r = fitz.Rect(r.x0 - 14, r.y0 - 14, r.x1 + 14, r.y1 + 14)
        note = (f"ADA ({f.cite}): {f.item} is {f.provided} in., needs "
                f"{f.required}.")
        op = annotate.new_op("add_cloud", page,
                             rect=[r.x0, r.y0, r.x1, r.y1],
                             color=[0.9, 0.1, 0.1], note=note,
                             subject="ADA Check", author=author)
        if annotate.apply_op(doc, op):
            n += 1
    return n
