"""Import your own price list: a cost data export or price list you are
licensed to use, from Excel (.xlsx) or CSV, into a cost book in this PC's
own price database.

You map the file's columns (Code / CSI, Description, Unit, Material,
Labor, Equipment, Hours, Labor Output, Total), check the first rows, and
name the book and the source and edition the prices came from. Codes are
read as CSI MasterFormat ("033113", "03 31 13" and "03-31-13" are all
"03 31 13"; a sub-section such as "03 31 13.35" is kept); rows whose code
can't be read are listed under "Needs code" to fix or skip. Every
imported row carries the source, the edition and the import date.

Labor hours per unit (worker-hours) come from the Hours column, else from
Labor Output (units per crew-day: crew size x hours a day / output), else
from Labor $ at a labor rate you give.

Licensed data stays yours: the book is marked local-only, so it is kept
only in this PC's local price database (never a shared one - see
pricedb.LocalOnlyError), left out when the database moves to a shared
folder, and exporting or sharing it asks first. Location factors are not
imported (the Location Factors table is your own).
"""
import datetime as _dt
import logging
import os
from decimal import Decimal

from . import costbook, csi, pricedb
from .dmoney import D

log = logging.getLogger(__name__)

FIELDS = [("code", "Code / CSI"), ("desc", "Description"), ("unit", "Unit"),
          ("material", "Material $"), ("labor", "Labor $"),
          ("equipment", "Equipment $"), ("hours", "Hours (labor hrs/unit)"),
          ("output", "Labor Output (units/day)"), ("total", "Total $"),
          ("crew", "Crew")]
LABELS = dict(FIELDS)
# header words that usually mean each field (lower case, exact first)
GUESS = {
    "code": ["code", "csi", "csi code", "cost code", "masterformat",
             "item code", "line number", "line no", "item no", "number"],
    "desc": ["description", "desc", "item description", "item", "name"],
    "unit": ["unit", "units", "uom", "u/m", "um", "unit of measure"],
    "material": ["material", "materials", "mat", "material $",
                 "material cost", "mat cost", "bare material"],
    "labor": ["labor", "labour", "labor $", "labor cost", "lab",
              "bare labor"],
    "equipment": ["equipment", "equip", "eqp", "equipment $",
                  "equipment cost", "bare equipment"],
    "hours": ["hours", "labor hours", "labour hours", "man-hours",
              "manhours", "man hours", "mh", "hrs", "hours/unit",
              "labor hrs"],
    "output": ["labor output", "output", "daily output", "production",
               "units/day", "units per day"],
    "total": ["total", "total cost", "unit cost", "bare total",
              "total $"],
    "crew": ["crew"],
}
PREVIEW_ROWS = 20


def read(path):
    """(header, rows) of the file (every cell as text)."""
    if not str(path).lower().endswith((".xlsx", ".xlsm", ".csv", ".txt",
                                       ".tsv")):
        raise ValueError("Pick an Excel workbook (.xlsx) or a CSV file.")
    return costbook.read_sheet(path)


def guess_mapping(head):
    """{field: column index} from the header words."""
    low = [str(h or "").strip().lower() for h in head]
    out, used = {}, set()
    for exact in (True, False):
        for field, words in GUESS.items():
            if field in out:
                continue
            for w in words:
                hit = next((i for i, h in enumerate(low) if i not in used and
                            (h == w if exact else
                             (len(w) > 3 and w in h))), None)
                if hit is not None:
                    out[field] = hit
                    used.add(hit)
                    break
    return out


def normalize_code(raw):
    """The CSI MasterFormat code ("03 31 13", "03 31 13.35") of what the
    file says, or '' when it can't be read as one."""
    t = costbook.code_text(raw)
    if sum(ch.isdigit() for ch in t) < 4:        # "3" or "abc": not a code
        return ""
    c = csi.parse_code(t)
    return c if c and c[:2] in csi.DIVISIONS else ""


def _cell(row, mapping, field):
    i = mapping.get(field)
    if i is None or i < 0 or i >= len(row):
        return ""
    return str(row[i] or "").strip()


def _blank(v):
    return str(v or "").replace("$", "").replace(",", "").strip() == ""


def mapped(row, mapping):
    return {f: _cell(row, mapping, f) for f, _ in FIELDS}


def labor_hours(vals, crew_size=1, hours_per_day=8, labor_rate=None):
    """(hours per unit as Decimal, how): Hours, else Labor Output, else
    Labor $ / labor rate; (0, '') when there's nothing to go on."""
    if not _blank(vals.get("hours")):
        return D(vals["hours"]), "hours"
    out = D(vals.get("output"))
    if out > 0:
        return costbook.hours_from_output(out, crew_size, hours_per_day), \
            "output"
    lab = D(vals.get("labor"))
    rate = D(labor_rate)
    if lab > 0 and rate > 0:
        return lab / rate, "labor $"
    return Decimal(0), ""


def preview(head, rows, mapping, n=PREVIEW_ROWS, **opts):
    """The first `n` rows as they would import: [{"row": file row number,
    "code" (normalised or ''), "raw_code", "desc", "unit", "material",
    "labor", "equipment", "hours", "total", "status"}]."""
    out = []
    for i, r in enumerate(rows[:n]):
        v = mapped(r, mapping)
        code = normalize_code(v["code"])
        hours, how = labor_hours(v, opts.get("crew_size", 1),
                                 opts.get("hours_per_day", 8),
                                 opts.get("labor_rate"))
        out.append(dict(v, row=i + 2, raw_code=v["code"], code=code,
                        hours=f"{hours.normalize():f}" if hours else "",
                        hours_from=how,
                        status="ok" if code else "Needs code"))
    return out


def today():
    return _dt.date.today().isoformat()


def build(head, rows, mapping, name, source, edition="", imported=None,
          crew_size=1, hours_per_day=8, labor_rate=None, fixes=None,
          skip=None, file_name=""):
    """The book and what happened: {"book": costbook.Book, "imported":
    [codes], "needs_code": [{"index", "row", "code", "desc"}],
    "warnings": [...]}. `fixes` = {row index: code typed for it}; `skip` =
    row indexes left out."""
    name = str(name or "").strip()
    source = str(source or "").strip()
    edition = str(edition or "").strip()
    if not name:
        raise ValueError("Give the book a name.")
    if not source:
        raise ValueError("Type where the prices came from (Source).")
    if "code" not in mapping:
        raise ValueError("Map the Code / CSI column.")
    imported = imported or today()
    fixes, skip = dict(fixes or {}), set(skip or ())
    note = (f"Imported {imported} from {file_name or 'your file'}: source "
            f"{source}" + (f", edition {edition}" if edition else "") +
            ". Licensed price data, kept only in this PC's price database "
            "(local-only); not part of QuantiSheet.")
    book = costbook.Book({"name": name, "effective": imported,
                          "escalation": 0.0, "local_only": True,
                          "license_note": note, "notes": note})
    done, needs, warnings, seen = [], [], [], {}
    for i, r in enumerate(rows):
        if i in skip:
            continue
        v = mapped(r, mapping)
        if all(_blank(x) for x in v.values()):
            continue
        raw = fixes.get(i, v["code"])
        code = normalize_code(raw)
        if not code:
            needs.append({"index": i, "row": i + 2, "code": str(raw),
                          "desc": v["desc"]})
            continue
        hours, how = labor_hours(v, crew_size, hours_per_day, labor_rate)
        if not how and not _blank(v["labor"]) and D(v["labor"]):
            warnings.append(f"row {i + 2} ({code}): Labor $ "
                            f"{v['labor']} not turned into hours - map "
                            "Hours or Labor Output, or give a labor rate")
        mat, eqp = D(v["material"]), D(v["equipment"])
        sub = Decimal(0)
        tot = D(v["total"])
        if tot and not (mat or eqp or hours or D(v["labor"])):
            sub = tot             # an all-in unit price only
        if code in seen:
            warnings.append(f"row {i + 2}: code {code} again (row "
                            f"{seen[code]}) - the later row is kept")
        seen[code] = i + 2
        book.set(code, v["unit"] or "ea", material=float(mat),
                 labor=float(hours), crew=v["crew"], sub=float(sub),
                 equipment=float(eqp),
                 desc=v["desc"] or csi.division_title(code),
                 source=source, edition=edition, imported=imported,
                 license=pricedb.LOCAL_ONLY, basis="imported")
        done.append(code)
    return {"book": book, "imported": done, "needs_code": needs,
            "warnings": warnings}


def can_save_here():
    """'' when a local-only book can be saved in the price database in
    use, else the reason it can't."""
    if pricedb.is_shared():
        return pricedb.local_only_message("This price list")
    return ""


def save(book):
    """Save the imported (local-only) book in this PC's price database.
    Raises pricedb.LocalOnlyError when the database is on a shared
    folder: nothing is written there."""
    data = book.to_dict()
    data["local_only"] = True
    pricedb.refuse_local_only(data)
    return costbook.save(book, note=f"imported price list ({book.name})")


def import_file(path, name=None, source="", edition="", mapping=None,
                **opts):
    """Read, map (guessed unless given), build and save in one go.
    Returns the build() result plus "saved" ("db:<name>")."""
    head, rows = read(path)
    mapping = guess_mapping(head) if mapping is None else mapping
    res = build(head, rows, mapping,
                name or os.path.splitext(os.path.basename(path))[0], source,
                edition, file_name=os.path.basename(path), **opts)
    if not res["imported"]:
        raise ValueError("No rows with a readable code - check the Code / "
                         "CSI column.")
    res["saved"] = save(res["book"])
    return res
