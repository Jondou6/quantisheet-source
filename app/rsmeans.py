"""Import RSMeans assembly costs (the text export with one line per
assembly):

    A1010 110   Strip footings, 12 x 12 in   C-14A  LF   M 18.00  L 32.00
    E 3.00  TOTAL 53.00  Incl O&P 60.95

Each line becomes an assembly in the "RSMeans" catalog in your price
database, with three parts - material, labor and equipment - priced by
a new cost book that also holds your starter prices. RSMeans labor
dollars are turned into hours at RSMeans' labor rates (about 1.6 x
QuantiSheet's national open-shop rates - change `labor_factor`), so a job in
one of the book's states is costed at that state's crew rates; material
and equipment follow the state's index. Prices are bare cost; RSMeans'
O&P is not added (use your proposal markup).

Catalog assemblies with the same name and unit as an RSMeans line are
calibrated to it: their material, equipment and labor are scaled so one
unit costs what RSMeans says (national), keeping their parts.

RSMeans data is licensed to you; it lives in your price database and is
not part of QuantiSheet. (Check your RSMeans license before sharing the
database with other estimators.)
"""
import copy
import csv
import datetime as _dt
import difflib
import io
import logging
import os
import re

from . import assemblies, assembly_csv, costbook, csi, labor

log = logging.getLogger(__name__)

LINE = re.compile(
    r"^(?P<code>(?:WW \d\d \d\d \d\d)|(?:[A-G]\d{4} \d{3}))\s+"
    r"(?P<name>.+?)\s+(?P<crew>[A-Z]+-\d+[A-Z]?)\s+(?P<unit>[A-Z]+)\s+"
    r"M\s+(?P<m>[\d,.]+)\s+L\s+(?P<l>[\d,.]+)\s+E\s+(?P<e>[\d,.]+)\s+"
    r"TOTAL\s+(?P<t>[\d,.]+)(?:\s+Incl O&P\s*(?P<op>[\d,.]*))?", re.M)
LABOR_FACTOR = 1.6
SOURCE = "RSMeans assemblies (your file), national average"

# section (from the "== ... ==" headings) -> (CSI division, crew)
SECTIONS = [
    (r"Basement Excavation|Site Earthwork", "31", "L-2"),
    (r"Substructure|Floor Construction|Roof Construction", "03", "F-4"),
    (r"Exterior Walls", "04", "M-3"),
    (r"Exterior Windows", "08", "G-2"),
    (r"Doors", "08", "C-2"),
    (r"Roof Coverings|Roof Openings", "07", "RF-3"),
    (r"Partitions", "09", "D-2"),
    (r"Fittings", "10", "C-2"),
    (r"Stair", "05", "S-3"),
    (r"Wall Finishes", "09", "PT-1"),
    (r"Floor Finishes", "09", "FL-2"),
    (r"Ceiling Finishes", "09", "D-2"),
    (r"Elevators|Escalators|Other Conveying", "14", "EL-2"),
    (r"Plumbing|Domestic Water|Rain Water", "22", "P-2"),
    (r"Energy Supply|Heat Generating|Cooling Generating|Terminal",
     "23", "SM-2"),
    (r"Sprinklers|Standpipes|Fire Protection", "21", "SF-2"),
    (r"Electrical Service|Lighting|Other Electrical|Site Lighting",
     "26", "E-2"),
    (r"Communications", "27", "LV-1"),
    (r"Equipment - ", "11", "MW-2"),
    (r"Furnishings", "12", "C-2"),
    (r"Special Construction", "13", "C-2"),
    (r"Roadways|Parking|Pedestrian", "32", "PV-5"),
    (r"Site Development", "32", "L-2"),
    (r"Water Supply|Sanitary Sewer|Storm Sewer|Fuel Distribution",
     "33", "UT-4"),
]
WW_CREW = {"03": "F-4", "05": "S-3", "13": "C-2", "23": "SM-2",
           "26": "E-2", "33": "UT-4", "40": "PF-2", "48": "E-2"}
# capacity units: count the items and enter the size per item
CAPACITY = {"TON": ("T", "tons per item"), "KW": ("K", "kW per item"),
            "MBH": ("B", "MBH per item")}
DRIVER = {"LF": "L", "SF": "A", "SY": "A", "CY": "V", "CF": "V",
          "GAL": "V"}


def _f(s):
    return float(str(s or "0").replace(",", "") or 0)


def parse(text):
    """[{code, name, section, crew, unit, m, l, e, total, op}] and the
    header ("... O&P 15%")."""
    out, section = [], ""
    header = {}
    m = re.search(r"O&P\s+(\d+(?:\.\d+)?)%", text)
    if m:
        header["op"] = float(m.group(1)) / 100
    m = re.search(r"city:\s*([^|]+)", text)
    if m:
        header["city"] = m.group(1).strip()
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("==") and s.endswith("=="):
            section = s.strip("= ").strip()
            continue
        r = LINE.match(s)
        if not r:
            continue
        out.append({"code": r["code"], "name": r["name"].strip(),
                    "section": section, "crew": r["crew"],
                    "unit": r["unit"].upper(), "m": _f(r["m"]),
                    "l": _f(r["l"]), "e": _f(r["e"]), "total": _f(r["t"]),
                    "op": _f(r["op"])})
    return out, header


def division_and_crew(item):
    if item["code"].startswith("WW"):
        div = item["code"].split()[1]
        return div, WW_CREW.get(div, "MW-2")
    for pat, div, crew in SECTIONS:
        if re.search(pat, item["section"]):
            return div, crew
    return "01", "C-2"


def assembly_id(item):
    return "RSM-" + item["code"].replace(" ", "-")


def national_rate(crew, book):
    # at the book's own date, so hours x rate = RSMeans $ / factor then
    rates = book.labor_rates("national", book.effective) if book else {}
    return labor.crew_rate(crew, rates) or 45.0


def catalog_rows(items, book, labor_factor=LABOR_FACTOR):
    """Rows of a catalog CSV (assembly_csv.COLUMNS) for the items."""
    rows = []
    for it in items:
        div, crew = division_and_crew(it)
        unit = it["unit"]
        if unit in CAPACITY:
            var, desc = CAPACITY[unit]
            formula, variables = var, f"{var} = {desc}"
        elif unit in DRIVER:
            formula = DRIVER[unit]
            variables = {"L": "L = length (LF)", "A": "A = area (SF)",
                         "V": "V = volume"}[formula]
        else:
            formula, variables = "N", "N = count"
        head = {"Assembly_ID": assembly_id(it),
                "Assembly_Name": f"{it['name']} (RSMeans {it['code']})",
                "CSI_Division": div,
                "CSI_Division_Title": csi.division_title(div) or "Other",
                "Process_Area": it["section"], "Assembly_Unit": unit,
                "Assembly_Formula": formula, "Variables": variables,
                "Waste_Pct": "0"}
        hours = it["l"] / (labor_factor * national_rate(crew, book))
        seq = 0
        for desc, ctype, iunit, calc, keep in (
                ("Material", "Material", unit, "1", it["m"]),
                (f"Labor, crew {crew}", "Labor", "HR", f"{hours:.6g}",
                 it["l"]),
                ("Equipment", "Equipment", unit, "1", it["e"])):
            if not keep:
                continue
            seq += 1
            rows.append(dict(head, Item_Seq=str(seq), Item_Description=desc,
                             Cost_Type=ctype, Item_Unit=iunit,
                             Calc_Method="Factor", Calculation=calc,
                             Notes=(f"RSMeans {it['code']}, {it['crew']}; "
                                    f"national bare ${it['total']:,.2f}/"
                                    f"{unit}" if seq == 1 else "")))
    return rows


def _unit_values(unit):
    meas = {"length": 0.0, "area": 0.0, "count": 0.0, "volume": 0.0,
            "perimeter": 0.0, "segments": 0.0}
    key, q = {"LF": ("length", 1), "SF": ("area", 1), "SY": ("area", 9),
              "CY": ("volume", 27), "CF": ("volume", 1),
              "GAL": ("volume", 1 / 7.48052)}.get(unit, ("count", 1))
    meas[key] = q
    return meas


def per_unit(assembly, book, region="national"):
    """(material $, equipment $, labor $) for one unit of the assembly,
    priced from the book (inputs taken as 1)."""
    a, _ = assemblies.priced(assembly, book, region, book.effective)
    for k in (a.get("inputs") or {}):
        a.setdefault("props", {})[k] = 1
    parts = assemblies.compute(a, _unit_values(str(a.get("unit") or
                                                   "").upper()))
    rates = book.labor_rates(region, book.effective)
    mat = equip = lab = 0.0
    for p, src in zip(parts, a.get("parts") or []):
        kind = (src.get("type") or "").lower()
        if kind == "equipment":
            equip += p["material"]
        else:
            mat += p["material"]
        lab += p["labor_hours"] * (labor.crew_rate(p.get("crew"), rates) or
                                   0.0)
    return mat, equip, lab


def calibrate(book, items, catalog=None, labor_factor=LABOR_FACTOR,
              cutoff=0.82, limits=(0.2, 5.0)):
    """Scale the book's prices for catalog assemblies that match an
    RSMeans line (same name, same unit). Returns (done, skipped) lists of
    (catalog name, RSMeans code, note)."""
    catalog = catalog if catalog is not None else assembly_csv.catalog()
    by = {it["name"].lower(): it for it in items}
    done, skipped = [], []
    for name, a in catalog.items():
        if a.get("source") not in (None, "catalog"):
            continue
        hit = difflib.get_close_matches(name.lower(), by, 1, cutoff)
        if not hit:
            continue
        it = by[hit[0]]
        if it["unit"] != str(a.get("unit") or "").upper():
            skipped.append((name, it["code"], f"unit {a.get('unit')} vs "
                            f"{it['unit']}"))
            continue
        if a.get("inputs"):
            skipped.append((name, it["code"], "needs inputs ("
                            + ", ".join(a["inputs"]) + ")"))
            continue
        try:
            mat, equip, lab = per_unit(a, book)
        except Exception as e:
            skipped.append((name, it["code"], f"can't price: {e}"))
            continue
        ours = mat + equip + lab
        theirs = it["m"] + it["e"] + it["l"] / labor_factor
        ratio = ours / theirs if theirs else 0
        if not (limits[0] <= ratio <= limits[1]):
            skipped.append((name, it["code"], f"too different ({ratio:.2f}x)"
                            " - probably a different scope"))
            continue
        # target $ per unit
        tm, te = it["m"], it["e"]
        if not equip:
            tm, te = it["m"] + it["e"], 0.0
        tl = it["l"] / labor_factor
        sm = tm / mat if mat else None
        se = te / equip if equip else None
        sl = tl / lab if lab else None
        note = f"calibrated to RSMeans {it['code']} ({SOURCE})"
        for part in a.get("parts") or []:
            item = book.get(part.get("code"))
            if not item:
                continue
            kind = (part.get("type") or "").lower()
            new = dict(item)
            if kind == "labor" and sl:
                new["labor"] = round(item["labor"] * sl, 6)
            elif kind == "equipment" and se:
                new["material"] = round(item["material"] * se, 4)
            elif kind not in ("labor", "equipment", "other") and sm:
                new["material"] = round(item["material"] * sm, 4)
            else:
                continue
            new["basis"] = "RSMeans-calibrated"
            new["source"] = note + "; was " + (item.get("source") or "")
            book.items[costbook.csi.parse_code(part["code"]) or
                       part["code"]] = new
        done.append((name, it["code"], f"{ratio:.2f}x before"))
    return done, skipped


def build_book(items, base, header=None, labor_factor=LABOR_FACTOR,
               name=None):
    """A new cost book: the base book's prices, regions and labor rates,
    plus every RSMeans item."""
    data = copy.deepcopy(base.to_dict())
    book = costbook.Book(data)
    book.name = name or f"RSMeans + {base.name}"
    book.version = ""
    book.path = None
    for it in items:
        div, crew = division_and_crew(it)
        aid = assembly_id(it)
        seq = 0
        for kind, val in (("Material", it["m"]), ("Labor", it["l"]),
                          ("Equipment", it["e"])):
            if not val:
                continue
            seq += 1
            code = f"{aid}.{seq}"
            if kind == "Labor":
                book.set(code, "hr", 0.0, 1.0, crew,
                         desc=f"{it['name']} - labor", type="Labor",
                         basis="RSMeans", source=f"{SOURCE}; ${val:,.2f}/"
                         f"{it['unit']} at {labor_factor:g} x QuantiSheet "
                         "national crew rate")
            else:
                book.set(code, it["unit"].lower(), val, 0.0, "",
                         desc=f"{it['name']} - {kind.lower()}", type=kind,
                         basis="RSMeans", source=SOURCE)
    op = (header or {}).get("op")
    book.notes = (base.notes + f" RSMeans assemblies imported "
                  f"{_dt.date.today().isoformat()} ({len(items)} lines"
                  + (f", O&P {op * 100:g}% not included" if op else "") +
                  "); labor $ converted to hours at "
                  f"{labor_factor:g} x QuantiSheet's national rates.")
    return book


def import_text(text, base=None, labor_factor=LABOR_FACTOR, name=None,
                make_default=False, region=None):
    """Import an RSMeans text export. Writes the catalog CSV and the cost
    book into your folders. Returns a summary dict."""
    items, header = parse(text)
    if not items:
        raise ValueError("No RSMeans lines found. Each line needs a code "
                         "(A1010 110 or WW 40 05 13), a name, crew, unit and"
                         " M / L / E / TOTAL figures.")
    if base is None:
        base = assemblies.default_costbook()[0]
        # re-importing: start again from the book the RSMeans book was
        # built on, not from the RSMeans book itself
        while base is not None and base.name.startswith("RSMeans + "):
            base = costbook.find(base.name[len("RSMeans + "):])
        base = base or next(
            (costbook.load(p) for n, p in costbook.list_books().items()
             if n.startswith(costbook.STARTER)), None)
    if base is None:
        base = costbook.Book({"name": "Cost Book"})
    rows = catalog_rows(items, base, labor_factor)
    buf = io.StringIO()
    w = csv.DictWriter(buf, assembly_csv.COLUMNS, lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k, "") for k in assembly_csv.COLUMNS})
    from . import pricedb
    pricedb.put_catalog("RSMeans", buf.getvalue())
    assembly_csv.forget_cache()
    path = "db:RSMeans"
    book = build_book(items, base, header, labor_factor, name)
    shipped = {n: a for n, a in assembly_csv.catalog().items()
               if a.get("source") == "catalog"}
    done, skipped = calibrate(book, items, shipped, labor_factor)
    saved = costbook.save(book)
    if make_default:
        from . import settings
        keep = (settings.get("default_costbook") or {}).get("region")
        if keep not in book.region_names():
            keep = None
        costbook.set_default(book, region or keep or
                             costbook.home_region(book))
    return {"assemblies": len(items), "catalog": path, "book": book.name,
            "book_path": saved, "calibrated": done, "skipped": skipped,
            "header": header}


def import_file(path, **kw):
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        return import_text(f.read(), **kw)
