"""Assemblies: PlanSwift-style estimating from takeoff.

An assembly turns one measurement into a full list of parts with material
and labor. Measure 40 ft of "Interior Wall - 2x4 @ 16\" O.C." and you get
studs, plates, drywall sheets, screws, tape, insulation and labor hours.

    assembly = {
        "name": "Interior Wall - 2x4 @ 16\" O.C.",
        "measure": "length" | "area" | "count",
        "trade": "Framing & Drywall",
        "props": {"Height": 9, "Spacing": 16, "Waste": 10},
        "parts": [{"name": "Studs", "unit": "ea",
                   "qty": "ceil(Length*12/Spacing)+1",
                   "cost": 4.85, "labor": 0.0}, ...],
    }

Formulas can use the measurement (Length, Area, Perimeter, Count,
Segments, Cutouts, Gross_Area; Area is net of cutouts and Perimeter
includes the openings' edges), the assembly's properties, and the results of parts above them
(spaces become underscores: "Drywall Sheets" -> Drywall_Sheets). Functions:
ceil, floor, round, roundup(x, step), min, max, abs, sqrt and
"a if condition else b". Names are not case-sensitive.

Each part has a unit cost (material) and labor hours per unit. Quantities
are worked out per measurement and then added up, so a wall run gets its
own end studs, like a real wall.

The library (built in + ~/.quantisheet/assemblies.json) is copied into a job
the first time it's used; the job's copy, with its own prices and
properties, is saved inside the PDF.
"""
import ast
import copy
import json
import logging
import math
import os

from . import annotate, costbook, csi, labor, settings, takeoff, units
from . import embfiles
from .dmoney import c2 as _c2

log = logging.getLogger(__name__)

JOB_FILE = "quantisheet_assemblies.json"
LIBRARY_PATH = os.path.join(settings.DIR, "assemblies.json")
DEFAULT_LABOR_RATE = 55.0


# ---- formulas ----------------------------------------------------------------

def _roundup(x, step=1):
    return math.ceil(x / step) * step if step else x


FUNCS = {"ceil": math.ceil, "floor": math.floor, "round": round,
         "roundup": _roundup, "min": min, "max": max, "abs": abs,
         "sqrt": math.sqrt}
def _div(op):
    """Division that says so when the divisor is zero (a spacing or size
    left at 0) instead of quietly pricing the part at 0 (review 3b B9).
    Guard on purpose with "a / b if b else 0"."""
    def f(a, b):
        if not b:
            raise FormulaError("division by zero (a value used as a divisor "
                               "is 0)")
        return op(a, b)
    return f


_BIN = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
        ast.Mult: lambda a, b: a * b,
        ast.Div: _div(lambda a, b: a / b),
        ast.Pow: lambda a, b: _pow(a, b),
        ast.Mod: _div(lambda a, b: a % b),
        ast.FloorDiv: _div(lambda a, b: a // b)}
_CMP = {ast.Lt: lambda a, b: a < b, ast.LtE: lambda a, b: a <= b,
        ast.Gt: lambda a, b: a > b, ast.GtE: lambda a, b: a >= b,
        ast.Eq: lambda a, b: a == b, ast.NotEq: lambda a, b: a != b}


class FormulaError(ValueError):
    pass


MAX_FORMULA = 500          # characters
MAX_DEPTH = 40             # nesting
MAX_EXP = 64
MAX_VALUE = 1e15


def _pow(a, b):
    if abs(b) > MAX_EXP:
        raise FormulaError(f"exponent {b:g} is too big (limit {MAX_EXP})")
    if abs(a) > 1 and abs(b) * math.log10(abs(a)) > 15:
        raise FormulaError("result is too big")
    return a ** b


def _check(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            raise FormulaError("result isn't a number")
        if abs(v) > MAX_VALUE:
            raise FormulaError("result is too big")
    return v


def var_name(name):
    """'Drywall Sheets' -> 'drywall_sheets' (how formulas refer to it)."""
    out = "".join(c if c.isalnum() else "_" for c in str(name).strip())
    while "__" in out:
        out = out.replace("__", "_")
    return out.strip("_").lower()


def evaluate(formula, names):
    """Evaluate a formula safely (numbers, names, + - * / ** %, comparisons,
    'x if c else y' and the functions in FUNCS). `names` is lower-case."""
    text = str(formula if formula is not None else "").strip()
    if not text:
        return 0.0
    if text.startswith("="):
        text = text[1:]
    if len(text) > MAX_FORMULA:
        raise FormulaError(f"formula is longer than {MAX_FORMULA} "
                           "characters")
    try:
        tree = ast.parse(text, mode="eval")
    except (SyntaxError, RecursionError, MemoryError) as e:
        raise FormulaError(f"can't read formula {formula!r}") from e

    def depth(n, d=0):
        if d > MAX_DEPTH:
            raise FormulaError("formula is nested too deeply")
        for c in ast.iter_child_nodes(n):
            depth(c, d + 1)
    depth(tree)

    def ev(n):
        return _check(_ev(n))

    def _ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.Name):
            k = n.id.lower()
            if k in names:
                return names[k]
            raise FormulaError(f"unknown name {n.id!r}")
        if isinstance(n, ast.BinOp) and type(n.op) in _BIN:
            return _BIN[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub,
                                                            ast.UAdd)):
            v = ev(n.operand)
            return -v if isinstance(n.op, ast.USub) else v
        if isinstance(n, ast.Compare) and len(n.ops) == 1 \
                and type(n.ops[0]) in _CMP:
            return 1 if _CMP[type(n.ops[0])](ev(n.left),
                                             ev(n.comparators[0])) else 0
        if isinstance(n, ast.IfExp):
            return ev(n.body) if ev(n.test) else ev(n.orelse)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) \
                and n.func.id.lower() in FUNCS and not n.keywords:
            return FUNCS[n.func.id.lower()](*[ev(a) for a in n.args])
        raise FormulaError(f"not allowed in a formula: {ast.dump(n)[:40]}")

    try:
        v = ev(tree)
    except FormulaError:
        raise
    except Exception as e:
        raise FormulaError(f"{formula!r}: {e}") from e
    return float(v)


def compute(assembly, meas):
    """Parts for one measurement. `meas` has length/area/perimeter/count/
    segments. Returns [{name, unit, qty, cost, material, labor_hours}]
    and raises FormulaError with the part's name if a formula is bad."""
    names = {k: 0.0 for k in ("length", "area", "perimeter", "count",
                              "volume", "segments", "cutouts",
                              "gross_area")}
    names.update({k.lower(): float(v) for k, v in meas.items()})
    for k, v in (assembly.get("props") or {}).items():
        try:
            names[var_name(k)] = float(v)
        except (TypeError, ValueError):
            raise FormulaError(f"property {k!r} must be a number")
    out = []
    from .assembly_csv import qty_for
    for part in assembly.get("parts") or []:
        try:
            q = evaluate(qty_for(assembly, part), names)
        except FormulaError as e:
            raise FormulaError(f"{part.get('name', '?')}: {e}") from e
        names[var_name(part.get("name", ""))] = q
        cost = float(part.get("cost") or 0)
        hours = float(part.get("labor") or 0)
        out.append({"name": part.get("name", ""), "unit": part.get("unit", ""),
                    "qty": q, "cost": cost, "material": q * cost,
                    "labor_hours": q * hours, "crew": part.get("crew", ""),
                    "code": part.get("code", "")})
    return out


# ---- library -----------------------------------------------------------------

def _p(name, unit, qty, cost=0.0, labor=0.0):
    return {"name": name, "unit": unit, "qty": qty, "cost": cost,
            "labor": labor}


BUILT_IN = [
    {"name": "Interior Wall - 2x4 @ 16\" O.C.", "measure": "length",
     "trade": "Framing & Drywall", "color": [0.85, 0.1, 0.1],
     "props": {"Height": 9, "Spacing": 16, "Waste": 10},
     "parts": [
         _p("Studs", "ea", "ceil(Length*12/Spacing)+1+Segments", 4.85, 0.12),
         _p("Plates", "lf", "Length*3*(1+Waste/100)", 0.65, 0.02),
         _p("Drywall Sheets", "ea",
            "ceil(Length*Height*2/32*(1+Waste/100))", 14.50, 0.35),
         _p("Drywall Screws", "lb", "roundup(Drywall_Sheets*32/1000*2.5,1)",
            6.25),
         _p("Tape & Mud", "sf", "Length*Height*2", 0.09, 0.012),
         _p("Sound Batt Insulation", "sf", "Length*Height", 0.55, 0.006),
     ]},
    {"name": "Interior Wall - 3-5/8\" Metal Stud", "measure": "length",
     "trade": "Framing & Drywall", "color": [0.9, 0.3, 0.1],
     "props": {"Height": 10, "Spacing": 16, "Waste": 10},
     "parts": [
         _p("Metal Studs", "ea", "ceil(Length*12/Spacing)+1+Segments", 6.40,
            0.10),
         _p("Track", "lf", "Length*2*(1+Waste/100)", 1.10, 0.02),
         _p("Drywall Sheets 5/8\" Type X", "ea",
            "ceil(Length*Height*2/32*(1+Waste/100))", 17.25, 0.35),
         _p("Tape & Mud", "sf", "Length*Height*2", 0.09, 0.012),
     ]},
    {"name": "Exterior Wall - 8\" CMU", "measure": "length",
     "trade": "Masonry", "color": [0.1, 0.3, 0.85],
     "props": {"Height": 12, "Waste": 5, "GroutEvery": 32},
     "parts": [
         _p("CMU Block 8in", "ea", "ceil(Length*Height*1.125*(1+Waste/100))",
            2.35, 0.11),
         _p("Mortar", "bag", "ceil(CMU_Block_8in/30)", 12.50),
         _p("Grout", "cy", "roundup(Length*12/GroutEvery*Height*0.0123,0.5)",
            165.0, 1.0),
         _p("Horizontal Joint Reinforcing", "lf",
            "Length*ceil(Height*12/16)", 0.45),
         _p("Vertical Rebar #5", "lf", "(ceil(Length*12/GroutEvery)+1)*Height",
            1.15, 0.01),
     ]},
    {"name": "Slab on Grade - 4\"", "measure": "area", "trade": "Concrete",
     "color": [0.5, 0.5, 0.5], "props": {"Depth": 4, "Waste": 5},
     "parts": [
         _p("Concrete", "cy", "roundup(Area*Depth/12/27*(1+Waste/100),0.5)",
            165.0, 0.0),
         _p("Vapor Barrier", "sf", "Area*1.1", 0.12, 0.002),
         _p("Welded Wire Mesh", "sf", "Area*1.1", 0.32, 0.004),
         _p("Edge Form", "lf", "Perimeter", 1.80, 0.05),
         _p("Place & Finish", "sf", "Area", 0.0, 0.025),
     ]},
    {"name": "Flooring - Resilient (LVT/VCT)", "measure": "area",
     "trade": "Flooring", "color": [0.2, 0.65, 0.2],
     "props": {"Waste": 8},
     "parts": [
         _p("Flooring", "sf", "ceil(Area*(1+Waste/100))", 3.25, 0.03),
         _p("Adhesive", "gal", "ceil(Area/150)", 32.0),
         _p("Rubber Base 4\"", "lf", "ceil(Perimeter*1.05)", 1.45, 0.02),
     ]},
    {"name": "Ceiling - 2x2 ACT", "measure": "area", "trade": "Ceilings",
     "color": [0.55, 0.3, 0.75], "props": {"Waste": 5},
     "parts": [
         _p("Ceiling Tiles 2x2", "ea", "ceil(Area/4*(1+Waste/100))", 3.10,
            0.0),
         _p("Main Tee", "lf", "ceil(Area/4)", 0.85),
         _p("Cross Tee", "lf", "ceil(Area/2*1.05)", 0.55),
         _p("Wall Angle", "lf", "ceil(Perimeter*1.05)", 0.60),
         _p("Hanger Wire", "ea", "ceil(Area/16)", 0.45),
         _p("Install Grid & Tile", "sf", "Area", 0.0, 0.018),
     ]},
    {"name": "Paint - Walls (2 coats)", "measure": "length", "trade": "Painting",
     "color": [0.95, 0.6, 0.1], "props": {"Height": 9, "Coats": 2,
                                           "Coverage": 350, "Sides": 2},
     "parts": [
         _p("Primer", "gal", "roundup(Length*Height*Sides/Coverage,1)", 28.0),
         _p("Paint", "gal",
            "roundup(Length*Height*Sides*Coats/Coverage,1)", 42.0),
         _p("Paint Labor", "sf", "Length*Height*Sides", 0.0, 0.006),
     ]},
    {"name": "Door - Hollow Metal Frame & Wood Door", "measure": "count",
     "trade": "Doors & Hardware", "color": [0.9, 0.45, 0],
     "props": {"HingesPerDoor": 3},
     "parts": [
         _p("HM Frame", "ea", "Count", 285.0, 1.5),
         _p("Wood Door", "ea", "Count", 410.0, 1.0),
         _p("Hinges", "ea", "Count*HingesPerDoor", 18.0),
         _p("Lockset", "ea", "Count", 165.0, 0.75),
         _p("Closer", "ea", "Count", 210.0, 0.75),
     ]},
    {"name": "Duplex Outlet", "measure": "count", "trade": "Electrical",
     "color": [0.85, 0.1, 0.1], "props": {"WirePerDevice": 25},
     "parts": [
         _p("Duplex Receptacle", "ea", "Count", 3.20, 0.25),
         _p("Box & Cover", "ea", "Count", 4.10, 0.15),
         _p("12/2 MC Cable", "lf", "Count*WirePerDevice", 1.05, 0.01),
     ]},
]

# MasterFormat section of each built-in assembly
for _a, _code in zip(BUILT_IN, ("09 21 16", "09 21 16", "04 22 00",
                                "03 30 00", "09 65 19", "09 51 13",
                                "09 91 23", "08 11 13", "26 27 26")):
    _a["csi"] = _code


def _migrate_all(items):
    """Formulas saved by the bad catalog parse, put right as they're read
    (assembly_csv.migrate); saved that way the next time the job or
    library is written."""
    try:
        from . import assembly_csv
        for a in items:
            assembly_csv.migrate(a)
    except Exception:                                     # noqa: BLE001
        log.warning("assembly formulas not checked", exc_info=True)


def library():
    """Built-in assemblies, the catalog shipped with QuantiSheet
    (data/assembly_catalog.csv) and your own (which override by name)."""
    items = {a["name"]: copy.deepcopy(a) for a in BUILT_IN}
    try:
        from . import assembly_csv
        items.update(assembly_csv.catalog())
    except Exception:
        log.warning("assembly catalog unavailable", exc_info=True)
    try:
        with open(LIBRARY_PATH, encoding="utf-8") as f:
            for a in json.load(f):
                if isinstance(a, dict) and a.get("name"):
                    items[a["name"]] = a
                    _migrate_all([a])
    except FileNotFoundError:
        pass
    except (OSError, ValueError):
        log.warning("assembly library unreadable", exc_info=True)
    return items


def save_many_to_library(items):
    """Add or replace several assemblies in your library at once."""
    try:
        with open(LIBRARY_PATH, encoding="utf-8") as f:
            user = [a for a in json.load(f) if isinstance(a, dict)]
    except (OSError, ValueError):
        user = []
    new = {a["name"]: a for a in items}
    user = [a for a in user if a.get("name") not in new] + list(new.values())
    os.makedirs(os.path.dirname(LIBRARY_PATH), exist_ok=True)
    tmp = LIBRARY_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(user, f, indent=1)
    os.replace(tmp, LIBRARY_PATH)
    return len(new)


def save_to_library(assembly):
    try:
        with open(LIBRARY_PATH, encoding="utf-8") as f:
            user = [a for a in json.load(f) if isinstance(a, dict)]
    except (OSError, ValueError):
        user = []
    user = [a for a in user if a.get("name") != assembly["name"]]
    user.append(copy.deepcopy(assembly))
    os.makedirs(settings.DIR, exist_ok=True)
    tmp = LIBRARY_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(user, f, indent=1)
    os.replace(tmp, LIBRARY_PATH)


# ---- the job (saved inside the PDF) ------------------------------------------------

def read_job(doc):
    try:
        if JOB_FILE in doc.embfile_names():
            data = json.loads(doc.embfile_get(JOB_FILE).decode("utf-8"))
            if isinstance(data, dict):
                data.setdefault("assemblies", {})
                data.setdefault("labor_rate", DEFAULT_LABOR_RATE)
                _migrate_all(data["assemblies"].values())
                return data
    except Exception:
        log.warning("could not read job assemblies", exc_info=True)
    return {"assemblies": {}, "labor_rate": DEFAULT_LABOR_RATE}


def write_job(doc, job):
    data = json.dumps(job, indent=1).encode("utf-8")
    embfiles.put(doc, JOB_FILE, data, "QuantiSheet job assemblies")


def set_job_assembly(doc, assembly):
    job = read_job(doc)
    job["assemblies"][assembly["name"]] = copy.deepcopy(assembly)
    write_job(doc, job)


def set_labor_rate(doc, rate):
    job = read_job(doc)
    job["labor_rate"] = float(rate)
    write_job(doc, job)


def any_known(doc, names):
    """Whether any of these takeoff groups has an assembly - checked
    without opening (or making) the price database when there isn't one
    yet (the practice job keeps everything in its sandbox)."""
    names = [n for n in names if n]
    if not names:
        return False
    job = read_job(doc)
    if any(n in job["assemblies"] for n in names):
        return True
    from . import pricedb
    if os.path.isfile(pricedb.path()):
        lib = library()
    else:
        lib = {a["name"]: a for a in BUILT_IN}
        try:
            from . import assembly_csv
            for f in assembly_csv.catalog_files():
                got, _p = assembly_csv.parse(f)
                lib.update({a["name"]: a for a in got})
        except Exception:                                 # noqa: BLE001
            log.warning("assembly catalog unavailable", exc_info=True)
        try:
            with open(LIBRARY_PATH, encoding="utf-8") as fh:
                for a in json.load(fh):
                    if isinstance(a, dict) and a.get("name"):
                        lib[a["name"]] = a
        except (OSError, ValueError):
            pass
    return any(n in lib for n in names)


def find(doc, name, job=None, lib=None):
    """The assembly for a measurement group: the job's copy first, then
    the library."""
    job = job if job is not None else read_job(doc)
    if name in job["assemblies"]:
        return job["assemblies"][name]
    lib = lib if lib is not None else library()
    return lib.get(name)


# ---- measurements ---------------------------------------------------------------

def _vertex_index(page):
    """{("t", tag) or ("x", xref): vertices} of the page's takeoff shapes
    (the first shape for a tag; its label shares the tag)."""
    out = {}
    for a in annotate.iter_annots(page) or []:
        if not (a.info or {}).get("subject", "").startswith(
                annotate.TAKEOFF + ":"):
            continue
        v = [tuple(p) for p in (a.vertices or [])
             if isinstance(p, (list, tuple)) and len(p) == 2]
        t = annotate.tag_of(a)
        if t:
            out.setdefault(("t", t), v)
        out.setdefault(("x", a.xref), v)
    return out


def measurements(doc):
    """Takeoff items with the variables formulas use."""
    scales = annotate.read_scales(doc)
    vports = annotate.read_viewports(doc)
    pages = {}
    out = []
    for it in annotate.totals_items(doc):
        m = {"length": 0.0, "area": 0.0, "perimeter": 0.0, "count": 0.0,
             "volume": 0.0,
             "segments": 0.0, "cutouts": float(it.get("cutouts") or 0),
             "gross_area": float(it.get("gross") or it["value"])
             if it["type"] == "area" else 0.0}
        t = it["type"]
        if t == "length":
            m["length"] = it["value"]
        elif t == "area":
            m["area"] = it["value"]
        elif t == "count":
            m["count"] = it["value"]
        elif t == "volume":
            m["volume"] = it["value"]
        try:
            # a measurement's label shares its id; use the shape itself.
            # One pass over each page's markups (looking each one up
            # separately was quadratic: seconds on a busy sheet)
            idx = pages.get(it["page"])
            if idx is None:
                idx = pages[it["page"]] = _vertex_index(doc[it["page"]])
            ref = it["ref"]
            key = ("t", ref["target"]) if "target" in ref else \
                ("x", ref.get("xref"))
            verts = [annotate.fitz.Point(v) for v in idx.get(key, ())]
        except Exception:
            verts = []
        sc = annotate.scale_at(doc, it["page"], [(v.x, v.y) for v in verts],
                               scales, vports) if verts else \
            scales.get(it["page"])
        if verts and sc and sc.get("ppu"):
            mult = float(it.get("multiplier") or 1)   # typical areas
            if t == "area" and len(verts) > 2:
                # outer edge plus the edges of any openings cut out of it
                m["perimeter"] = takeoff.path_length(
                    verts + [verts[0]]) / sc["ppu"] * mult + \
                    float(it.get("hole_perimeter") or 0)
            if t == "length":
                m["segments"] = max(0, len(verts) - 2) * mult  # corners
        # formulas are written in feet: a metric drawing's 10 sq m is
        # 107.64 Area, and its perimeter is in feet too
        unit_error = ""
        try:
            for key, mt in (("length", "length"), ("area", "area"),
                            ("gross_area", "area"), ("volume", "volume")):
                if m[key] and t in ("length", "area", "volume"):
                    m[key] = units.measure_to_base(m[key], it["unit"], mt)
            lu = (sc or {}).get("unit") or _length_unit(it["unit"])
            if m["perimeter"] and lu:
                m["perimeter"] = units.measure_to_base(m["perimeter"], lu,
                                                       "length")
        except units.UnitError as e:
            unit_error = f"{it['unit']!r} is not a {t} unit ({e})"
        out.append({**it, "vars": m, "unit_error": unit_error})
    return out


def _length_unit(unit):
    """'ft' from 'sq ft' or 'cu ft'."""
    u = str(unit or "").strip().lower()
    for pre in ("sq ", "cu "):
        if u.startswith(pre):
            return u[len(pre):]
    return u


MEASURE_TYPES = ("length", "area", "volume", "count")


def set_job_settings(doc, **kw):
    """Job-wide estimating settings: rates={trade: $/hr},
    adjust={"height": ...}, labor_rate=55."""
    job = read_job(doc)
    for k, v in kw.items():
        if v is None:
            job.pop(k, None)
        else:
            job[k] = v
    write_job(doc, job)


def set_costbook(doc, book, region=None, as_of=None):
    """Price this job from `book` (a costbook.Book, or None for the
    assemblies' own prices). A copy of the book goes into the PDF so the
    estimate is the same on any computer."""
    job = read_job(doc)
    if book is None:
        job.pop("costbook", None)
        job["own_prices"] = True
    else:
        job.pop("own_prices", None)
        if region:
            real = book.resolve_region(region)
            if real is None:
                raise ValueError(
                    f"{book.name} has no region {region!r}. Its regions: "
                    + ", ".join(book.region_names()))
            region = real
        job["costbook"] = {"name": book.name, "region": region or book.region,
                           "as_of": as_of or "", "book": book.to_dict()}
        if getattr(book, "local_only", False):
            # licensed (local-only) prices stay in this PC's price
            # database: the PDF names the book instead of carrying a copy
            job["costbook"].pop("book")
            job["costbook"]["local_only"] = True
    write_job(doc, job)


def default_costbook():
    """(Book, region) set as your default for jobs that haven't picked a
    book (Cost Books > Make Default), or (None, None)."""
    d = settings.get("default_costbook") or {}
    if not isinstance(d, dict) or not d.get("name"):
        return None, None
    try:
        book = costbook.find(d["name"])
    except Exception:
        log.warning("default cost book unreadable", exc_info=True)
        book = None
    return (book, d.get("region") or None) if book else (None, None)


def job_costbook(job, default=True):
    """(Book, region, as_of) the job is priced from, or (None, None, None).
    A job that hasn't picked a book uses your default book."""
    cb = job.get("costbook") or {}
    if not cb:
        if default and not job.get("own_prices"):
            book, region = default_costbook()
            if book is not None:
                return book, region, None
        return None, None, None
    book = costbook.Book(cb["book"]) if cb.get("book") else \
        costbook.find(cb.get("name", ""))
    return book, cb.get("region") or None, cb.get("as_of") or None


def _book_price(part, item, f):
    """(unit cost, labor hrs per unit) of a cost book item in the part's
    unit; raises UnitError when the units don't match (e.g. the book
    prices per sf and the part is counted in ea)."""
    pu, bu = str(part.get("unit") or "").strip(), str(item.get("unit") or
                                                      "").strip()
    conv = 1.0
    if bu and pu and pu.lower() != bu.lower():
        try:
            fp, dp = units.parse_unit(pu)
            fb, db = units.parse_unit(bu)
        except units.UnitError:
            raise units.UnitError(f"part is in {pu!r}, the cost book prices "
                                  f"per {bu!r}")
        if dp != db:
            raise units.UnitError(f"part is in {pu!r}, the cost book prices "
                                  f"per {bu!r}")
        conv = fp / fb        # book units per part unit
    cost = (float(item.get("material") or 0) + float(item.get("sub") or 0) +
            float(item.get("equipment") or 0))        # Equipment $ (0.13)
    return cost * f * conv, float(item.get("labor") or 0) * conv


def priced(assembly, book=None, region=None, as_of=None, quiet=False):
    """A copy of `assembly` with each coded part's cost, labor and crew
    from the cost book. Returns (assembly, problems). quiet=True keeps a
    part's own price, without a problem, when its code isn't in the book
    (used for your default book)."""
    a = copy.deepcopy(assembly)
    problems = []
    if book is None:
        return a, problems
    f0 = book.factor(region, as_of)
    for part in a.get("parts") or []:
        f = book.factor(region, as_of, part.get("code")) \
            if book.escalation_by_div else f0
        item = book.get(part.get("code"))
        if item and item.get("sizes"):        # pipe priced by diameter
            from .costbook import size_price
            d = (a.get("props") or {}).get("D")
            if d not in (None, ""):
                item, note = size_price(item, d)
                if note:
                    problems.append(f"{a['name']} - {part.get('name')}: "
                                    f"{note}")
                part["size"] = d
        if not item:
            if part.get("code") and not (quiet and (part.get("cost") or
                                                    part.get("labor"))):
                problems.append(f"{a['name']} - {part.get('name')}: cost code "
                                f"{part['code']} is not in {book.name}")
            continue
        if not any(_filled(item.get(k)) for k in ("material", "labor",
                                                   "sub", "equipment")):
            problems.append(f"{a['name']} - {part.get('name')}: {book.name} "
                            f"prices {part.get('code')} at $0 - enter your "
                            "number")
        try:
            part["cost"], part["labor"] = _book_price(part, item, f)
        except units.UnitError as e:
            problems.append(f"{a['name']} - {part.get('name')}: {e}")
            continue
        if item.get("crew") and not part.get("crew"):
            part["crew"] = item["crew"]
    return a, problems


def _filled(v):
    try:
        return float(v) != 0
    except (TypeError, ValueError):
        return False


def rollup(doc, page=None, book=False, region=None, as_of=None, refs=None,
           added=True):
    """Estimate by assembly. Returns (rows, totals, errors); each row is
    {name, trade, csi, measure, quantity, unit, items, parts:[...],
    material, labor_hours, labor_cost, crew_days, total}.

    Prices come from the job's cost book when it has one (pass `book` to
    price from another book instead, or None for the assemblies' own
    prices; `refs` limits it to those measurements). Labor hours are
    multiplied by the job's and the assembly's
    adjustment factors and costed at the part's crew rate, or the job's
    labor rate when the part has no crew.

    The lines added in the Estimate panel (estimate_lines.py) come last,
    one row each ("added": True), for the whole job only (no `page`, no
    `refs`; added=False leaves them out)."""
    job = read_job(doc)
    lib = library()
    rate = float(job.get("labor_rate") or 0)
    quiet = False
    if book is False:
        book, region, as_of = job_costbook(job)
        quiet = book is not None and not job.get("costbook")
    rows, errors = {}, []
    if book is not None and region:
        real = book.resolve_region(region)
        if real is None:
            errors.append(f"Cost book {book.name} has no region {region!r}"
                          f" - priced at {book.region} instead. Pick one of: "
                          + ", ".join(book.region_names()))
            region = book.region
        else:
            region = real
    # the book's labor rates for the region, then the job's own rates
    job_rates = dict(book.labor_rates(region, as_of)) if book is not None \
        else {}
    job_rates.update(job.get("rates") or {})
    priced_cache = {}
    for it in measurements(doc):
        if page is not None and it["page"] != page:
            continue
        if refs is not None and it["ref"] not in refs:
            continue
        a = find(doc, it["group"], job, lib)
        if not a:
            continue
        if it.get("unit_error"):
            errors.append(f"{a['name']} - {it['unit_error']}")
            continue
        want = a.get("measure")
        if want in MEASURE_TYPES and it["type"] in MEASURE_TYPES and \
                want != it["type"]:
            errors.append(f"{a['name']} is measured by {want}, but a "
                          f"{it['type']} measurement on page {it['page'] + 1}"
                          f" uses it")
            continue
        missing = [f"{k} ({d})" for k, d in (a.get("inputs") or {}).items()
                   if not _filled((a.get("props") or {}).get(k))]
        if missing:
            msg = (f"{a['name']} - enter {', '.join(missing)} in Edit "
                   "Assembly")
            if msg not in errors:
                errors.append(msg)
            continue
        if a["name"] not in priced_cache:
            pa, probs = priced(a, book, region, as_of, quiet)
            priced_cache[a["name"]] = pa
            errors.extend(probs)
        pa = priced_cache[a["name"]]
        try:
            parts = compute(pa, it["vars"])
        except FormulaError as e:
            errors.append(f"{a['name']} - {e}")
            continue
        r = rows.get(a["name"])
        if r is None:
            r = rows[a["name"]] = {
                "name": a["name"], "trade": a.get("trade", ""),
                "csi": csi.parse_code(a.get("csi") or "") or
                csi.classify(a["name"] + " " + a.get("trade", "")) or "",
                "measure": a.get("measure", it["type"]), "quantity": 0.0,
                "unit": it["unit"], "items": 0, "parts": {},
                "adjust": labor.factor(dict(job.get("adjust") or {},
                                            **(a.get("adjust") or {})))}
        value = it["value"]
        if it["unit"] != r["unit"]:
            try:
                value = units.Quantity(value, it["unit"]).to(r["unit"]).value
            except units.UnitError:
                # don't add feet to square feet: leave it out and say so
                # (review 3b B10)
                msg = (f"{a['name']} - a {it['unit']} measurement can't be "
                       f"added to {r['unit']}; left out of the quantity")
                if msg not in errors:
                    errors.append(msg)
                value = None
        if value is not None:
            r["quantity"] += value
        r["items"] += 1
        # copies of a typical (x3 typical): each copy is priced to the
        # cent, as the estimator checks it by hand - four 100-ton chillers,
        # not one 400-ton one (Chief's re-test, Nov 7: a penny high)
        try:
            copies = float(it.get("multiplier") or 1)
        except (TypeError, ValueError):
            copies = 1.0
        copies = int(copies) if copies >= 1 and copies == int(copies) \
            else 1
        for p in parts:
            q = r["parts"].setdefault(p["name"], {
                "name": p["name"], "unit": p["unit"], "qty": 0.0,
                "cost": p["cost"], "material": 0.0, "labor_hours": 0.0,
                "crew": p.get("crew", ""), "code": p.get("code", ""),
                "_each": []})
            q["qty"] += p["qty"]
            q["material"] += p["material"]
            hrs = p["labor_hours"] * r["adjust"]
            q["labor_hours"] += hrs
            q["_each"].append((p["material"], hrs, copies))
    out = []
    for name in sorted(rows, key=lambda n: (rows[n]["trade"], n)):
        r = rows[name]
        r["parts"] = list(r["parts"].values())
        for q in r["parts"]:
            cr = labor.crew_rate(q["crew"], job_rates) if q["crew"] else None
            q["labor_rate"] = cr if cr is not None else rate
            # each part's material and labor to the cent, then added up -
            # the way an estimator checks it by hand (Chief's re-test,
            # Nov 7: the chiller row came out a penny high when the
            # unrounded amounts were added first)
            each = q.pop("_each", None) or [(q["material"],
                                             q["labor_hours"], 1)]
            q["material"] = _c2(sum(_cent(m / n) * n
                                      for m, _h, n in each))
            q["labor_cost"] = _c2(sum(_cent(h / n * q["labor_rate"]) * n
                                        for _m, h, n in each))
            q["crew_days"] = labor.crew_days(q["labor_hours"], q["crew"]) \
                if q["crew"] and cr is not None else q["labor_hours"] / 8.0
            q["total"] = q["material"] + q["labor_cost"]
        for k in ("material", "labor_hours", "labor_cost", "crew_days",
                  "total"):
            r[k] = sum(q[k] for q in r["parts"])
        out.append(r)
    if added and page is None and refs is None:
        try:
            from . import estimate_lines
            out.extend(estimate_lines.rollup_rows(
                doc, taken=[r["name"] for r in out]))
        except Exception:                                 # noqa: BLE001
            log.warning("added estimate lines left out", exc_info=True)
            errors.append("The lines added in the Estimate panel couldn't "
                          "be read")
        try:
            from . import estimate
            out.extend(estimate.rollup_rows(
                doc, taken=[r["name"] for r in out]))
        except Exception:                                 # noqa: BLE001
            log.warning("priced takeoff lines left out", exc_info=True)
            errors.append("The prices typed on takeoff lines couldn't be "
                          "read")
    totals = {k: sum(r[k] for r in out)
              for k in ("material", "labor_hours", "labor_cost", "crew_days",
                        "total")}
    totals["labor_rate"] = rate
    totals["costbook"] = book.name if book else ""
    totals["region"] = (region or book.region) if book else ""
    return out, totals, errors


def _cent(x):
    """A float amount to the cent, half-up (as a float)."""
    from decimal import Decimal, ROUND_HALF_UP
    return float(Decimal(repr(float(x or 0))).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP))


def reprice(doc, book, region=None, as_of=None):
    """What switching the job to `book` would change, before it's applied:
    ([{name, trade, before, after, change}], before_total, after_total,
    problems)."""
    old, ot, _ = rollup(doc)
    new, nt, problems = rollup(doc, book=book, region=region, as_of=as_of)
    before = {r["name"]: r for r in old}
    after = {r["name"]: r for r in new}
    diff = []
    for name in sorted(set(before) | set(after)):
        b = before.get(name, {}).get("total", 0.0)
        a = after.get(name, {}).get("total", 0.0)
        diff.append({"name": name,
                     "trade": (after.get(name) or before.get(name))["trade"],
                     "before": b, "after": a, "change": a - b})
    return diff, ot["total"], nt["total"], problems


def export_xlsx(doc, path, page=None):
    """Excel workbook: a summary by assembly and every part."""
    from . import acrobat
    rows, totals, errors = rollup(doc, page)
    summary = [["CSI", "Trade", "Assembly", "Takeoff Qty", "Unit", "Items",
                "Material $", "Labor Hrs", "Labor $", "Crew Days", "Total $"]]
    detail = [["CSI", "Trade", "Assembly", "Part", "Cost Code", "Crew", "Qty",
               "Unit", "Unit Cost", "Material $", "Labor Hrs", "Labor $",
               "Total $"]]
    for r in rows:
        summary.append([r["csi"], r["trade"], r["name"],
                        _c2(r["quantity"]),
                        r["unit"], r["items"], _c2(r["material"]),
                        _c2(r["labor_hours"]), _c2(r["labor_cost"]),
                        _c2(r["crew_days"]), _c2(r["total"])])
        for q in r["parts"]:
            detail.append([r["csi"], r["trade"], r["name"], q["name"],
                           q.get("code", ""), q.get("crew", ""),
                           _c2(q["qty"]), q["unit"], _c2(q["cost"]),
                           _c2(q["material"]), _c2(q["labor_hours"]),
                           _c2(q["labor_cost"]), _c2(q["total"])])
    summary += [[], ["", "", "Total", "", "", "", _c2(totals["material"]),
                     _c2(totals["labor_hours"]),
                     _c2(totals["labor_cost"]),
                     _c2(totals["crew_days"]),
                     _c2(totals["total"])],
                ["", "", f"Labor rate ${_c2(totals['labor_rate']):,.2f}/hr"
                 " (parts with a crew use the crew's rate)" +
                 (f"; priced from "
                  f"{_costbook_shown(totals['costbook'])}"
                  f" ({totals.get('region') or 'national'})"
                  if totals["costbook"] else "")]]
    sheets = [("Estimate Summary", summary), ("Parts", detail)]
    if errors:
        sheets.append(("Problems", [["Formula problems"]] +
                       [[e] for e in errors]))
    acrobat.write_xlsx(path, sheets)
    return path


def _costbook_shown(name):
    """The cost book's name as people see it (a name saved before the
    rename shows today's - GUI user test r42 F09)."""
    try:
        from . import costbook
        return costbook.display_name(name)
    except Exception:                                     # noqa: BLE001
        return name
