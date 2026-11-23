"""3D model quantities from an IFC file (Nov 23, Jon: features like our
competitors', built ourselves). IFC is the open building-model standard
(ISO 16739); its text form is ISO 10303-21 ("STEP"). This reads that text
directly - no other program or library is needed - and lists the model's
building elements by kind and type with the quantities the model carries:

    rows = read(path)      -> [{"category", "ifc", "type", "storey",
                                "count", "length", "area", "volume",
                                "unit_len", "csi", "names"}]
    info = summary(path)   -> {"schema", "units", "elements", "with_qty"}

Quantities come from the model's quantity sets (Qto_...BaseQuantities or
any IfcElementQuantity), converted to feet, square feet and cubic yards.
A model exported without quantity sets still gives counts by type; the
window says so. Nothing is worked out from the geometry, so a number shown
is the number the model's author exported.
"""
import os
import re
from collections import OrderedDict
from decimal import Decimal

# element classes we list, with the takeoff category and a CSI code
CLASSES = OrderedDict([
    ("IFCFOOTING", ("Footings", "03 30 00")),
    ("IFCPILE", ("Piles", "31 62 00")),
    ("IFCSLAB", ("Slabs and floors", "03 30 00")),
    ("IFCWALL", ("Walls", "09 21 16")),
    ("IFCWALLSTANDARDCASE", ("Walls", "09 21 16")),
    ("IFCWALLELEMENTEDCASE", ("Walls", "09 21 16")),
    ("IFCCURTAINWALL", ("Curtain walls", "08 44 00")),
    ("IFCCOLUMN", ("Columns", "05 12 00")),
    ("IFCBEAM", ("Beams", "05 12 00")),
    ("IFCMEMBER", ("Framing members", "05 12 00")),
    ("IFCPLATE", ("Plates and panels", "05 50 00")),
    ("IFCROOF", ("Roofs", "07 50 00")),
    ("IFCDOOR", ("Doors", "08 10 00")),
    ("IFCWINDOW", ("Windows", "08 50 00")),
    ("IFCSTAIR", ("Stairs", "05 51 00")),
    ("IFCSTAIRFLIGHT", ("Stairs", "05 51 00")),
    ("IFCRAMP", ("Ramps", "03 30 00")),
    ("IFCRAILING", ("Railings", "05 52 00")),
    ("IFCCOVERING", ("Coverings (ceilings, flooring, cladding)",
                     "09 00 00")),
    ("IFCSPACE", ("Rooms and spaces", "")),
    ("IFCFURNISHINGELEMENT", ("Furnishings", "12 00 00")),
    ("IFCFURNITURE", ("Furnishings", "12 00 00")),
    ("IFCSANITARYTERMINAL", ("Plumbing fixtures", "22 40 00")),
    ("IFCFLOWTERMINAL", ("Fixtures and terminals", "22 40 00")),
    ("IFCPIPESEGMENT", ("Pipe", "22 11 00")),
    ("IFCDUCTSEGMENT", ("Duct", "23 31 00")),
    ("IFCFLOWSEGMENT", ("Pipe and duct", "22 11 00")),
    ("IFCLIGHTFIXTURE", ("Light fixtures", "26 51 00")),
    ("IFCBUILDINGELEMENTPROXY", ("Other elements", "")),
])
# which quantity to use, best first (names from the IFC base quantity sets)
LENGTH_NAMES = ("Length", "NetLength", "GrossLength", "Height", "Depth",
                "Perimeter")
AREA_NAMES = ("NetSideArea", "NetArea", "NetFloorArea", "NetFootprintArea",
              "GrossSideArea", "GrossArea", "GrossFloorArea",
              "GrossFootprintArea", "OuterSurfaceArea", "Area",
              "CrossSectionArea")
VOLUME_NAMES = ("NetVolume", "GrossVolume", "Volume")
# per category, the length we prefer (a slab's "length" means little)
NO_LENGTH = {"Slabs and floors", "Roofs", "Doors", "Windows",
             "Rooms and spaces", "Coverings (ceilings, flooring, cladding)",
             "Furnishings", "Plumbing fixtures", "Fixtures and terminals",
             "Light fixtures"}

M_TO_FT = Decimal("3.280839895013123")
CF_PER_CY = Decimal(27)


class IfcError(ValueError):
    pass


# ----------------------------------------------------------- STEP reading
_ENTITY = re.compile(r"#(\d+)\s*=\s*([A-Z0-9_]+)\s*\((.*)\)\s*$", re.S)


def _statements(text):
    """The DATA section's statements, joined across lines, with strings
    (which may hold ';') kept whole."""
    m = re.search(r"\bDATA\s*;", text)
    if not m:
        raise IfcError("This isn't an IFC file (no DATA section).")
    i, n = m.end(), len(text)
    buf, out, in_str = [], [], False
    while i < n:
        c = text[i]
        if in_str:
            buf.append(c)
            if c == "'":
                if i + 1 < n and text[i + 1] == "'":
                    buf.append("'")
                    i += 1
                else:
                    in_str = False
        elif c == "'":
            in_str = True
            buf.append(c)
        elif c == "/" and text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 1
        elif c == ";":
            s = "".join(buf).strip()
            if s.upper() == "ENDSEC":
                break
            if s:
                out.append(s)
            buf = []
        else:
            buf.append(c)
        i += 1
    return out


def _decode(s):
    """STEP string escapes: '' and \\X2\\...\\X0\\ (UTF-16 hex)."""
    s = s.replace("''", "'")

    def x2(m):
        h = m.group(1)
        try:
            return "".join(chr(int(h[k:k + 4], 16))
                           for k in range(0, len(h), 4))
        except ValueError:
            return m.group(0)
    s = re.sub(r"\\X2\\([0-9A-Fa-f]+)\\X0\\", x2, s)
    s = re.sub(r"\\X\\([0-9A-Fa-f]{2})",
               lambda m: chr(int(m.group(1), 16)), s)
    return s


def _args(s):
    """Parse a STEP argument list into Python values: str, int/float as
    Decimal, ('#', id) references, None ($ or *), ('.', ENUM), lists, and
    ('TYPED', name, value) for IFCLENGTHMEASURE(1.5) and the like."""
    pos = 0
    n = len(s)

    def ws():
        nonlocal pos
        while pos < n and s[pos] in " \t\r\n":
            pos += 1

    def value():
        nonlocal pos
        ws()
        c = s[pos]
        if c == "'":
            j = pos + 1
            buf = []
            while j < n:
                if s[j] == "'":
                    if j + 1 < n and s[j + 1] == "'":
                        buf.append("''")
                        j += 2
                        continue
                    break
                buf.append(s[j])
                j += 1
            pos = j + 1
            return _decode("".join(buf))
        if c == "(":
            pos += 1
            items = []
            ws()
            if s[pos] == ")":
                pos += 1
                return items
            while True:
                items.append(value())
                ws()
                if s[pos] == ",":
                    pos += 1
                    continue
                if s[pos] == ")":
                    pos += 1
                    return items
                raise IfcError("bad list")
        if c == "#":
            m = re.compile(r"#(\d+)").match(s, pos)
            pos = m.end()
            return ("#", int(m.group(1)))
        if c in "$*":
            pos += 1
            return None
        if c == ".":
            m = re.compile(r"\.([A-Z0-9_]+)\.").match(s, pos)
            pos = m.end()
            return (".", m.group(1))
        m = re.compile(r"[A-Z][A-Z0-9_]*").match(s, pos)
        if m:
            name = m.group(0)
            pos = m.end()
            ws()
            if pos < n and s[pos] == "(":
                pos += 1
                v = value()
                ws()
                pos += 1          # ')'
                return ("TYPED", name, v)
            return name
        m = re.compile(r"[-+]?\d+\.?\d*(?:[Ee][-+]?\d+)?").match(s, pos)
        if m:
            pos = m.end()
            try:
                return Decimal(m.group(0))
            except Exception:                             # noqa: BLE001
                return None
        raise IfcError(f"can't read {s[pos:pos + 20]!r}")

    out = []
    ws()
    if pos >= n:
        return out
    while True:
        out.append(value())
        ws()
        if pos >= n:
            break
        if s[pos] == ",":
            pos += 1
            continue
        break
    return out


def parse(text):
    """{id: (TYPE, args)} for every entity in the DATA section."""
    ents = {}
    for st in _statements(text):
        m = _ENTITY.match(st)
        if not m:
            continue
        try:
            ents[int(m.group(1))] = (m.group(2).upper(), _args(m.group(3)))
        except (IfcError, IndexError):
            continue
    return ents


def _schema(text):
    m = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", text)
    return m.group(1) if m else ""


# ------------------------------------------------------------------ units
_PREFIX = {"MILLI": Decimal("0.001"), "CENTI": Decimal("0.01"),
           "DECI": Decimal("0.1"), "KILO": Decimal(1000), None: Decimal(1)}
_UNIT_KINDS = {"LENGTHUNIT": 1, "AREAUNIT": 2, "VOLUMEUNIT": 3}


def _units(ents):
    """{1: feet per model length unit, 2: square feet per model area unit,
    3: cubic feet per model volume unit, "label": length unit name}.
    A unit the model doesn't give is taken as metric or imperial
    to match its length unit."""
    found, label = {}, None
    for _id, (t, a) in ents.items():
        if t != "IFCUNITASSIGNMENT" or not a or not isinstance(a[0], list):
            continue
        for ref in a[0]:
            u = ents.get(_ref(ref))
            if not u or len(u[1]) < 3:
                continue
            ut, ua = u
            kind = ua[1][1] if isinstance(ua[1], tuple) else None
            if kind not in _UNIT_KINDS:
                continue
            p = _UNIT_KINDS[kind]
            if ut == "IFCSIUNIT" and len(ua) >= 4:
                prefix = ua[2][1] if isinstance(ua[2], tuple) else None
                found[p] = (_PREFIX.get(prefix, Decimal(1)) * M_TO_FT) ** p
                if p == 1:
                    label = {"MILLI": "mm", "CENTI": "cm", None: "m"}.get(
                        prefix, "m")
            elif ut == "IFCCONVERSIONBASEDUNIT" and len(ua) >= 3:
                name = (ua[2] or "").upper()
                if "INCH" in name:
                    found[p] = (Decimal(1) / 12) ** p
                    label = label or ("in" if p == 1 else None)
                elif "FOOT" in name or "FEET" in name:
                    found[p] = Decimal(1)
                    label = label or ("ft" if p == 1 else None)
                elif "YARD" in name:
                    found[p] = Decimal(3) ** p
    ft = found.get(1)
    if ft is None:
        ft, label = M_TO_FT, "m (assumed)"
    # an area or volume unit the model leaves out: square / cubic metres
    # in a metric model (what exporters mean, even with mm lengths), square
    # / cubic feet in an imperial one
    metric = label not in ("ft", "in")
    base = M_TO_FT if metric else Decimal(1)
    return {1: ft, 2: found.get(2, base ** 2), 3: found.get(3, base ** 3),
            "label": label or "m"}


def _length_scale(ents):
    u = _units(ents)
    return u[1], u["label"]


# ------------------------------------------------------------- the model
def _ref(v):
    return v[1] if isinstance(v, tuple) and v and v[0] == "#" else None


def _num(v):
    if isinstance(v, Decimal):
        return v
    if isinstance(v, tuple) and v and v[0] == "TYPED":
        return _num(v[2])
    return None


def _str(v):
    return v if isinstance(v, str) else ""


def _quantities(ents):
    """element id -> {quantity name: (kind, value in model units)}."""
    out = {}
    for _id, (t, a) in ents.items():
        if t != "IFCRELDEFINESBYPROPERTIES" or len(a) < 6:
            continue
        q = ents.get(_ref(a[5]))
        if not q or q[0] != "IFCELEMENTQUANTITY":
            continue
        qa = q[1]
        values = {}
        for r in (qa[5] if len(qa) > 5 and isinstance(qa[5], list) else []):
            qe = ents.get(_ref(r))
            if not qe:
                continue
            qt, qargs = qe
            kind = {"IFCQUANTITYLENGTH": "length", "IFCQUANTITYAREA": "area",
                    "IFCQUANTITYVOLUME": "volume",
                    "IFCQUANTITYCOUNT": "count"}.get(qt)
            if kind and len(qargs) > 3 and _num(qargs[3]) is not None:
                values.setdefault(_str(qargs[0]), (kind, _num(qargs[3])))
        for r in (a[4] if isinstance(a[4], list) else []):
            el = _ref(r)
            if el is not None:
                out.setdefault(el, {}).update(
                    {k: v for k, v in values.items()
                     if k not in out.get(el, {})})
    return out


def _types(ents):
    """element id -> its type's name (IfcRelDefinesByType)."""
    out = {}
    for _id, (t, a) in ents.items():
        if t == "IFCRELDEFINESBYTYPE" and len(a) >= 6:
            ty = ents.get(_ref(a[5]))
            name = _str(ty[1][2]) if ty and len(ty[1]) > 2 else ""
            for r in (a[4] if isinstance(a[4], list) else []):
                if _ref(r) is not None and name:
                    out[_ref(r)] = name
    return out


def _storeys(ents):
    """element id -> the storey (or building) it is in."""
    out = {}
    for _id, (t, a) in ents.items():
        if t == "IFCRELCONTAINEDINSPATIALSTRUCTURE" and len(a) >= 6:
            sp = ents.get(_ref(a[5]))
            name = _str(sp[1][2]) if sp and len(sp[1]) > 2 else ""
            for r in (a[4] if isinstance(a[4], list) else []):
                if _ref(r) is not None:
                    out[_ref(r)] = name
    return out


# never taken as an element's length, area or volume when nothing better
# is there: a wall's width is its thickness, an opening's area isn't the
# wall's
_NOT_FALLBACK = ("width", "thickness", "opening", "window", "door",
                 "crosssection", "outer", "footprint")


def _pick(q, names, kind):
    for n in names:
        if n in q and q[n][0] == kind:
            return q[n][1]
    for n, (k, v) in q.items():
        if k == kind and not any(w in n.lower().replace(" ", "")
                                 for w in _NOT_FALLBACK):
            return v
    return None


def load(path):
    if not os.path.exists(path):
        raise IfcError("That file isn't there.")
    if os.path.getsize(path) > 600 * 1024 * 1024:
        raise IfcError("That model is over 600 MB - export a smaller part.")
    with open(path, "rb") as f:
        raw = f.read()
    if raw[:2] == b"PK":
        raise IfcError("This is a zipped IFC (.ifczip) - unzip it first.")
    text = raw.decode("utf-8", "replace")
    if "ISO-10303-21" not in text[:200]:
        raise IfcError("This isn't an IFC file in text (STEP) form.")
    return text


def read(path, text=None):
    """The model's elements grouped by category, type and storey."""
    text = text if text is not None else load(path)
    ents = parse(text)
    units = _units(ents)
    ft, sf, cf = units[1], units[2], units[3]
    qty, types, storeys = _quantities(ents), _types(ents), _storeys(ents)
    groups = OrderedDict()
    for eid in sorted(ents):
        t, a = ents[eid]
        if t not in CLASSES:
            continue
        cat, csi = CLASSES[t]
        tname = types.get(eid) or _str(a[4] if len(a) > 4 else "") or \
            _str(a[2] if len(a) > 2 else "") or t.title()
        st = storeys.get(eid, "")
        key = (cat, tname, st)
        g = groups.get(key)
        if g is None:
            g = groups[key] = {"category": cat, "ifc": t, "type": tname,
                               "storey": st, "count": 0,
                               "length": Decimal(0), "area": Decimal(0),
                               "volume": Decimal(0), "csi": csi,
                               "has_qty": False, "names": []}
        g["count"] += 1
        nm = _str(a[2] if len(a) > 2 else "")
        if nm and len(g["names"]) < 5:
            g["names"].append(nm)
        q = qty.get(eid, {})
        if q:
            g["has_qty"] = True
        if cat in NO_LENGTH:
            ln = None
        elif cat in ("Columns", "Piles", "Footings"):
            ln = _pick(q, LENGTH_NAMES, "length")
        else:                         # a run: its length only, never height
            ln = next((q[n][1] for n in ("Length", "NetLength",
                                          "GrossLength")
                       if n in q and q[n][0] == "length"), None)
        ar = _pick(q, AREA_NAMES, "area")
        vo = _pick(q, VOLUME_NAMES, "volume")
        if ln is not None:
            g["length"] += ln * ft
        if ar is not None:
            g["area"] += ar * sf
        if vo is not None:
            g["volume"] += vo * cf / CF_PER_CY
    return list(groups.values())


def summary(path, text=None, rows=None):
    text = text if text is not None else load(path)
    ents = parse(text)
    rows = rows if rows is not None else read(path, text)
    return {"schema": _schema(text), "units": _length_scale(ents)[1],
            "elements": sum(r["count"] for r in rows),
            "with_qty": sum(r["count"] for r in rows if r["has_qty"]),
            "project": next((_str(a[2]) for t, a in ents.values()
                             if t == "IFCPROJECT" and len(a) > 2), "")}


def estimate_rows(rows):
    """[(desc, qty, unit, code)] for Add to Estimate: one line per row,
    in its best unit (volume for concrete, area for slabs, walls and
    coverings, length for framing, pipe and duct, else a count)."""
    out = []
    for r in rows:
        desc = f"{r['category']} - {r['type']}" + (
            f" ({r['storey']})" if r["storey"] else "")
        cat = r["category"]
        if cat in ("Footings", "Piles") and r["volume"]:
            out.append((desc, r["volume"], "cy", r["csi"]))
        elif cat in ("Slabs and floors", "Roofs", "Walls", "Curtain walls",
                     "Coverings (ceilings, flooring, cladding)",
                     "Rooms and spaces", "Plates and panels") and r["area"]:
            out.append((desc, r["area"], "sf", r["csi"]))
        elif cat in ("Beams", "Columns", "Framing members", "Pipe", "Duct",
                     "Pipe and duct", "Railings") and r["length"]:
            out.append((desc, r["length"], "lf", r["csi"]))
        else:
            out.append((desc, Decimal(r["count"]), "ea", r["csi"]))
    return out


def to_csv(rows, path):
    import csv
    from .dmoney import half_up
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Category", "Type", "Storey", "IFC class", "Count",
                    "Length (LF)", "Area (SF)", "Volume (CY)"])
        for r in rows:
            w.writerow([r["category"], r["type"], r["storey"], r["ifc"],
                        r["count"], half_up(r["length"], 2),
                        half_up(r["area"], 2), half_up(r["volume"], 2)])
    return path
