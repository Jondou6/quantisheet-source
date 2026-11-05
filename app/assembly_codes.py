"""HeavyBid-coded assemblies (v28): labor / material / equipment components
per unit, keyed by HeavyBid biditem / activity / resource codes so the
library round-trips with civil_export.heavybid_export (v22).

This sits beside assemblies.py (formula parts, cost book, rollup) rather
than replacing it: assemblies.py prices material + labor hours by formula;
this is the flat code-based library estimators import from / export to
HeavyBid, with equipment as its own component type.

Library file (CSV or XLSX, one row per component; codes stay text):
    Biditem Code, Description, Unit, Trade, Activity Code, Resource Code,
    Type (L/M/E), Component, Qty per Unit, Component Unit, Rate

No prices ship with QuantiSheet: data/assembly_codes_TEMPLATE.csv is the
header only, and data/assembly_codes_EXAMPLE.csv shows the layout with
EXAMPLE descriptions and blank rates. A blank rate is "unpriced" and is
reported, never treated as $0.

A takeoff group is priced only when the user binds it to an assembly
(bind); nothing is chosen automatically from the markup type. Bindings and
inserted lines are saved inside the PDF (quantisheet_assembly_codes.json).
All money is Decimal, rounded to cents (half up) per component line.
"""
import csv
import json
import logging
import os
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from . import annotate, embfiles, safecell

log = logging.getLogger(__name__)

COLS = ["Biditem Code", "Description", "Unit", "Trade", "Activity Code",
        "Resource Code", "Type", "Component", "Qty per Unit",
        "Component Unit", "Rate"]
TYPES = ("L", "M", "E")
FILE = "quantisheet_assembly_codes.json"
_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
TEMPLATE = os.path.join(_DATA, "assembly_codes_TEMPLATE.csv")
EXAMPLE = os.path.join(_DATA, "assembly_codes_EXAMPLE.csv")
CENT = Decimal("0.01")


def dec(v, blank=None):
    if v is None:
        return blank
    if isinstance(v, Decimal):
        return v
    s = str(v).replace("$", "").replace(",", "").strip()
    if not s:
        return blank
    try:
        return Decimal(s)
    except InvalidOperation:
        raise ValueError(f"not a number: {v!r}")


def cents(v):
    return Decimal(v).quantize(CENT, rounding=ROUND_HALF_UP)


def _text(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return " ".join(str(v).split())


# ------------------------------------------------------------- read / write
def _rows(path):
    if path.lower().endswith(".xlsx"):
        import openpyxl
        ws = openpyxl.load_workbook(path, read_only=True, data_only=True).active
        rows = [[_text(c) for c in r] for r in ws.iter_rows(values_only=True)]
    else:
        from .textio import open_csv          # Excel's Windows-1252 too
        with open_csv(path) as f:
            rows = [[safecell.unquote(_text(c)) for c in r]
                    for r in csv.reader(f)]
    return [r for r in rows if any(r)]


def read(path):
    """{biditem code: assembly} from a library file."""
    rows = _rows(path)
    if not rows:
        return {}
    head = [h.strip().lower() for h in rows[0]]
    idx = {c: head.index(c.lower()) for c in COLS if c.lower() in head}
    missing = [c for c in COLS if c not in idx]
    if missing:
        raise ValueError(f"{os.path.basename(path)}: missing columns {missing}")
    lib = {}
    for n, r in enumerate(rows[1:], 2):
        g = lambda c: r[idx[c]] if idx[c] < len(r) else ""
        code = g("Biditem Code")
        if not code:
            continue
        t = g("Type").upper()[:1]
        if t not in TYPES:
            raise ValueError(f"row {n}: Type must be L, M or E (got {g('Type')!r})")
        a = lib.setdefault(code, {"code": code, "desc": g("Description"),
                                  "unit": g("Unit"), "trade": g("Trade"),
                                  "components": []})
        a["components"].append({
            "type": t, "activity": g("Activity Code"),
            "resource": g("Resource Code"), "desc": g("Component"),
            "qty": dec(g("Qty per Unit"), Decimal(0)),
            "unit": g("Component Unit"), "rate": dec(g("Rate"))})
    return lib


def _flat(lib):
    for a in lib.values():
        for c in a["components"]:
            yield [a["code"], a["desc"], a["unit"], a["trade"], c["activity"],
                   c["resource"], c["type"], c["desc"], str(c["qty"]),
                   c["unit"], "" if c["rate"] is None else str(c["rate"])]


def write_rows(path, rows):
    if path.lower().endswith(".xlsx"):
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Assemblies"
        safecell.append_row(ws, COLS)
        for r in rows:
            safecell.append_row(ws, [v if v != "" else None for v in r])
        for row in ws.iter_rows(min_row=2):
            for c in row:
                c.number_format = "@"
        wb.save(path)
    else:
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = safecell.writer(f, lineterminator="\r\n")
            w.writerow(COLS)
            w.writerows(rows)
    return path


def write(path, lib):
    return write_rows(path, list(_flat(lib)))


# ------------------------------------------------------- HeavyBid exchange
def to_heavybid(lib, qty_by_code):
    """(biditems, activities, resources) dicts for civil_export writers."""
    bids, acts, res = [], [], []
    for code, a in lib.items():
        q = dec(qty_by_code.get(code), None)
        if q is None:
            continue
        bids.append({"code": code, "desc": a["desc"], "unit": a["unit"],
                     "qty": q, "notes": a["trade"]})
        seen = set()
        for c in a["components"]:
            act = c["activity"] or f"{code}.01"
            if act not in seen:
                seen.add(act)
                acts.append({"biditem": code, "code": act, "desc": a["desc"],
                             "qty": q, "unit": a["unit"]})
            res.append({"biditem": code, "activity": act,
                        "code": c["resource"], "desc": c["desc"],
                        "qty": c["qty"] * q, "unit": c["unit"],
                        "price": c["rate"], "type": c["type"]})
    return bids, acts, res


def from_heavybid(bids, acts, res):
    """Inverse of to_heavybid: qty per unit = resource qty / biditem qty."""
    lib = {}
    q = {b["code"]: dec(b.get("qty"), Decimal(0)) for b in bids}
    for b in bids:
        lib[b["code"]] = {"code": b["code"], "desc": b.get("desc", ""),
                          "unit": b.get("unit", ""),
                          "trade": b.get("notes", ""), "components": []}
    for r in res:
        a = lib.get(r["biditem"])
        if a is None:
            continue
        bq = q.get(r["biditem"]) or Decimal(0)
        rq = dec(r.get("qty"), Decimal(0))
        a["components"].append({
            "type": (r.get("type") or "M")[:1].upper(),
            "activity": r.get("activity", ""), "resource": r.get("code", ""),
            "desc": r.get("desc", ""),
            "qty": (rq / bq).normalize() if bq else rq,
            "unit": r.get("unit", ""), "rate": dec(r.get("price"))})
    return lib


# ------------------------------------------------------------------ pricing
def extend(a, qty, waste_pct=0, waste_on=("M",)):
    """Extended cost of `qty` units. Waste % raises the quantity of the
    component types in `waste_on` (material by default)."""
    qty = dec(qty, Decimal(0))
    w = Decimal(1) + dec(waste_pct, Decimal(0)) / Decimal(100)
    out = {"L": Decimal("0.00"), "M": Decimal("0.00"), "E": Decimal("0.00"),
           "lines": [], "unpriced": []}
    for c in a["components"]:
        cq = c["qty"] * qty * (w if c["type"] in waste_on else 1)
        if c["rate"] is None:
            out["unpriced"].append(f"{c['resource']} {c['desc']}".strip())
            cost = Decimal("0.00")
        else:
            cost = cents(cq * c["rate"])
        out[c["type"]] += cost
        out["lines"].append(dict(c, ext_qty=cq, cost=cost))
    out["total"] = out["L"] + out["M"] + out["E"]
    return out


# --------------------------------------------------------- job data in PDF
def read_job(doc):
    try:
        if FILE in doc.embfile_names():
            d = json.loads(doc.embfile_get(FILE).decode("utf-8"))
            if isinstance(d, dict):
                d.setdefault("bindings", {})
                d.setdefault("inserted", [])
                return d
    except Exception:
        log.warning("could not read assembly bindings", exc_info=True)
    return {"bindings": {}, "inserted": []}


def write_job(doc, data):
    embfiles.put(doc, FILE, json.dumps(data, indent=1).encode("utf-8"),
                 "QuantiSheet assembly bindings")


def key_of(group, mtype, unit):
    return f"{group}|{mtype}|{unit}"


def bind(doc, group, mtype, unit, code, waste_pct=0, library=None):
    """Bind a takeoff group (group, type, unit) to an assembly code chosen
    by the user."""
    if library is not None and code not in library:
        raise KeyError(f"no assembly {code!r} in the library")
    d = read_job(doc)
    d["bindings"][key_of(group, mtype, unit)] = {"code": str(code),
                                                 "waste": str(waste_pct)}
    write_job(doc, d)


def unbind(doc, group, mtype, unit):
    d = read_job(doc)
    d["bindings"].pop(key_of(group, mtype, unit), None)
    write_job(doc, d)


def insert(doc, code, qty, note=""):
    """Add an assembly line with a typed quantity (no takeoff behind it)."""
    d = read_job(doc)
    d["inserted"].append({"code": str(code), "qty": str(qty), "note": note})
    write_job(doc, d)


def group_quantities(doc, items=None):
    """{(group, type, unit): Decimal qty} from the real takeoff."""
    out = {}
    for it in (annotate.totals_items(doc) if items is None else items):
        k = (it.get("group") or it["type"].title(), it["type"],
             it.get("unit") or "")
        v = (it.get("multiplier") or 1) if it["type"] == "count" else \
            (it.get("value") or 0)
        out[k] = out.get(k, Decimal(0)) + dec(v, Decimal(0))
    return out


def price_item(a, qty, waste, **extra):
    x = extend(a, qty, waste)
    return dict(extra, code=a["code"], desc=a["desc"], trade=a["trade"],
                unit=a["unit"], qty=dec(qty), L=x["L"], M=x["M"], E=x["E"],
                total=x["total"], unpriced=x["unpriced"])


def priced_lines(doc, library, items=None):
    """(lines, unbound takeoff groups). Only bound groups are priced."""
    d = read_job(doc)
    lines, unbound = [], []
    for (g, t, u), q in group_quantities(doc, items).items():
        b = d["bindings"].get(key_of(g, t, u))
        if not b:
            unbound.append({"group": g, "type": t, "unit": u, "qty": q})
            continue
        a = library.get(b["code"])
        if a is None:
            unbound.append({"group": g, "type": t, "unit": u, "qty": q,
                            "why": f"assembly {b['code']} not in library"})
            continue
        lines.append(price_item(a, q, b.get("waste") or 0, group=g,
                                source="takeoff"))
    for ins in d["inserted"]:
        a = library.get(ins["code"])
        if a is not None:
            lines.append(price_item(a, ins["qty"], 0, group=ins.get("note", ""),
                                    source="inserted"))
    return lines, unbound
