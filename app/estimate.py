"""Quantity takeoff summary and cost estimate.

Pricing (unit cost, waste %, multiplier) is stored per line inside the PDF
(embedded file quantisheet_estimate.json), so it travels with the drawings.
A line is one (name, type, unit) group of measurements, e.g. all
"Interior Wall" lengths in feet.

    total = quantity x (1 + waste%) x multiplier x unit cost

Use the multiplier for wall height (length -> wall area), slab depth
(area -> volume), or units per item.
"""
import decimal
import json
import logging
import math

from . import safecell
from . import annotate
from . import dmoney
from . import embfiles
from . import rounding
from .dmoney import c2 as _c2
from .dmoney import half_up as _hu

_Z = decimal.Decimal(0)
log = logging.getLogger(__name__)

FILE = "quantisheet_estimate.json"
# quantities a Generate Set wrote into its own PDF (0.12.21): lines with
# type "set", priced like any takeoff line
SET_FILE = "quantisheet_set_quantities.json"
MAX_SET_ROWS = 500


def key_of(name, mtype, unit):
    """Price key for a summary line. "name|type|unit" as always, unless a
    part itself holds a "|" ("2x4 | 2x6"), which would collide with another
    line: then an unambiguous JSON list (review 3 #17)."""
    parts = [str(name), str(mtype), str(unit)]
    if any("|" in p for p in parts):
        return json.dumps(parts)
    return "|".join(parts)


def read_prices(doc):
    try:
        if FILE in doc.embfile_names():
            data = json.loads(doc.embfile_get(FILE).decode("utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        log.warning("could not read estimate data", exc_info=True)
    return {}


def _key_parts(k):
    """key_of() back to [name, type, unit] (None if it isn't one)."""
    try:
        if k.startswith("["):
            parts = json.loads(k)
        else:
            parts = k.split("|")
    except (ValueError, AttributeError):
        return None
    return parts if isinstance(parts, list) and len(parts) == 3 else None


def follow_rename(doc, old, mtype, new):
    """A takeoff item renamed: its prices and the estimate lines linked to
    it go with it, instead of being matched by the old name and lost
    (Nov 4). A price already on the new name is kept, not overwritten.
    Returns (prices moved, lines relinked)."""
    from . import estimate_lines
    old, new, mtype = str(old), str(new), str(mtype)
    if not new or new == old:
        return 0, 0
    prices = read_prices(doc)
    moved = 0
    for k in list(prices):
        parts = _key_parts(k)
        if parts and parts[0] == old and parts[1] == mtype:
            nk = key_of(new, mtype, parts[2])
            if nk not in prices:
                prices[nk] = prices.pop(k)
                moved += 1
    if moved:
        write_prices(doc, prices)
    lines = estimate_lines.read(doc)
    relinked = 0
    for ln in lines:
        link = ln.get("link")
        if link and link.get("name") == old and link.get("type") == mtype:
            link["name"] = new
            relinked += 1
    if relinked:
        estimate_lines.write(doc, lines)
    return moved, relinked


def write_prices(doc, prices):
    data = json.dumps(prices, indent=1).encode("utf-8")
    embfiles.put(doc, FILE, data, "QuantiSheet estimate pricing")


def set_items(doc):
    """[{page, group, item, quantity, unit, how}] stored by Generate Set."""
    try:
        if SET_FILE not in doc.embfile_names():
            return []
        data = json.loads(doc.embfile_get(SET_FILE).decode("utf-8"))
        page = _anchor(doc, data)
        out = []
        rows = data.get("rows")
        if not isinstance(rows, list):       # Venice review M6
            rows = []
        for r in rows[:MAX_SET_ROWS]:
            if not isinstance(r, dict):
                continue
            try:                 # data from a PDF: bad rows are skipped
                if isinstance(r.get("quantity"), bool):
                    continue
                q = float(r.get("quantity"))
            except (TypeError, ValueError, AttributeError):
                continue
            if 0 < q < 1e9 and r.get("item") and r.get("unit"):
                out.append({"page": page,
                            "group": str(r.get("group", ""))[:80],
                            "item": str(r["item"])[:120], "quantity": q,
                            "unit": str(r["unit"])[:12],
                            "how": str(r.get("how", ""))[:200]})
        return out
    except Exception:                                     # noqa: BLE001
        log.warning("could not read the set quantities", exc_info=True)
        return []


def _anchor(doc, data):
    """The page the set's rows belong to: the page labelled as stored
    ("A-701") wherever it is now - pages may have been added, removed or
    moved since (0.12.21 review M2) - else the stored index, kept in
    range."""
    n = getattr(doc, "page_count", 0) or 1
    label = data.get("label")
    if isinstance(label, str) and label:
        try:
            for i in range(n):
                if doc[i].get_label() == label:
                    return i
        except Exception:                                 # noqa: BLE001
            pass
    try:
        page = int(data.get("page", 0))
    except (TypeError, ValueError, OverflowError):
        page = n - 1
    return page if 0 <= page < n else n - 1


def write_set_items(doc, rows, page, label=None):
    """Store Generate Set quantity rows (group, item, qty, unit, how)."""
    data = {"page": int(page), "label": label, "rows": [
        {"group": g, "item": i, "quantity": q, "unit": u, "how": h}
        for g, i, q, u, h in rows]}
    embfiles.put(doc, SET_FILE, json.dumps(data, indent=1).encode("utf-8"),
                 "QuantiSheet generated-set quantities")


# what a price field may hold: inf / nan / 1e30 typed in a cell or stored
# in a PDF made the money math raise and froze the panel (0.12.21 review S1)
LIMITS = {"waste": (-100.0, 1000.0), "multiplier": (0.0, 1e6),
          "unit_cost": (-1e9, 1e9)}


def _num(v, default, field=None):
    try:
        if isinstance(v, bool):
            return default
        f = float(v)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(f):
        return default
    if field in LIMITS:
        lo, hi = LIMITS[field]
        f = min(hi, max(lo, f))
    return f


def roof_waste():
    """The roof waste % used for derived rows (Roof Plan Takeoff)."""
    from . import settings
    return _num(settings.get("roof_waste", 10), 10.0, "roof_waste")


def roof_rows(doc):
    """Derived roof rows (squares, membrane, wall flashing, curb
    perimeter) for the roof measurements in `doc`; [] when there are none."""
    from . import roof
    its = roof.roof_items(annotate.totals_items(doc))
    if not its:
        return []
    return roof.derived_items(its, roof_waste())


def lines(doc, page=None):
    """Summary lines, one per (name, type, unit)."""
    prices = read_prices(doc)
    groups = {}
    for it in annotate.totals_items(doc):
        if page is not None and it["page"] != page:
            continue
        # markups come from any PDF: a value no estimate can use is
        # skipped, not allowed to stop the panel (Venice review S3)
        v = _num(it.get("value"), None)
        if v is None:
            continue
        it = dict(it, value=v, type=str(it.get("type") or ""),
                  unit=str(it.get("unit") or ""),
                  group=str(it.get("group") or ""))
        name = it["group"] or it["type"].title()
        if isinstance(it.get("roof"), dict) and not it["group"]:
            from . import roof
            name = roof.name_of(it)
        k = (name, it["type"], it["unit"])
        g = groups.setdefault(k, {"name": name, "type": it["type"],
                                  "unit": it["unit"], "count": 0,
                                  "quantity": 0.0, "pages": set()})
        g["count"] += 1
        g["_q"] = g.get("_q", _Z) + dmoney.D(it["value"])
        g["pages"].add(it["page"] + 1)
    for it in roof_rows(doc):
        if page is not None and it["page"] != page:
            continue
        k = (it["name"], "roof", it["unit"])
        g = groups.setdefault(k, {"name": it["name"], "type": "roof",
                                  "unit": it["unit"], "count": 0,
                                  "quantity": 0.0, "pages": set()})
        g["count"] += 1
        g["_q"] = g.get("_q", _Z) + dmoney.D(it["quantity"])
        g["pages"].add(it["page"] + 1)
    for it in set_items(doc):
        if page is not None and it["page"] != page:
            continue
        k = (it["item"], "set", it["unit"])
        g = groups.setdefault(k, {"name": it["item"], "type": "set",
                                  "unit": it["unit"], "count": 0,
                                  "quantity": 0.0, "pages": set()})
        g["count"] += 1
        g["_q"] = g.get("_q", _Z) + dmoney.D(it["quantity"])
        g["pages"].add(it["page"] + 1)
    out = []
    for k in sorted(groups):
        g = groups[k]
        p = prices.get(key_of(*k), {})
        g["waste"] = _num(p.get("waste"), 0.0, "waste")
        g["multiplier"] = _num(p.get("multiplier"), 1.0, "multiplier")
        g["unit_cost"] = _num(p.get("unit_cost"), 0.0, "unit_cost")
        # CSI code and cost type typed on the line (0.13: Estimate panel)
        g["code"] = _text(p.get("code"), 40)
        g["cost_type"] = _text(p.get("cost_type"), 20)
        # Venice #15 (Nov 4): quantities add up in exact decimals (each
        # markup's value as shown, no float drift from the order they were
        # drawn), waste and multiplier are applied in decimals, and the
        # adjusted quantity is kept to 4 places before money (rounding.py)
        q = g.pop("_q", _Z)
        try:
            adj = rounding.qty(q * (1 + dmoney.D(g["waste"]) / 100) *
                               dmoney.D(g["multiplier"]))
        except (decimal.InvalidOperation, OverflowError, ValueError):
            adj = _Z
        g["quantity"] = float(q)
        g["adjusted"] = float(adj)
        # exact cents, not float drift (review 3 #16); a quantity no money
        # can hold (a crafted markup) totals 0 instead of stopping the panel
        try:
            g["total"] = float(dmoney.cents(
                rounding.money_qty(adj) * dmoney.D(g["unit_cost"])))
        except (decimal.InvalidOperation, OverflowError, ValueError):
            log.warning("estimate line %r: total out of range", g["name"])
            g["total"] = 0.0
        g["pages"] = ", ".join(str(n) for n in sorted(g["pages"]))
        out.append(g)
    return out


# where a takeoff line's typed price goes, by its cost type (as
# estimate_lines.TYPE_PART; no type: material)
_TYPE_PART = {"Material": "mat", "Labor": "lab", "Equipment": "eqp",
              "Subcontract": "sub", "Allowance": "sub", "Other": "sub"}


def rollup_rows(doc, taken=()):
    """Takeoff lines that carry a typed unit cost, as assembly-rollup rows
    (assemblies.rollup), so the proposal, the bid build-up, the exports
    and the schedule of values include them - they were in the Estimate
    panel's total but in none of those (hands-on pass, Nov 10; Jon: include
    them). Same shape as estimate_lines.rollup_rows."""
    from . import csi
    rows, names = [], set(taken)
    for g in lines(doc):
        if not g["total"]:
            continue
        name = base = g["name"] or "Takeoff line"
        n = 2
        while name in names:
            name = f"{base} ({n})"
            n += 1
        names.add(name)
        code = csi.parse_code(g.get("code") or "") or ""
        trade = csi.DIVISIONS.get(code[:2], "") if code else ""
        trade = trade[:1].upper() + trade[1:] if trade else "General"
        part_key = _TYPE_PART.get(g.get("cost_type") or "", "mat")
        total = float(g["total"])
        mat = total if part_key == "mat" else 0.0
        lab = total if part_key == "lab" else 0.0
        eqp = total if part_key == "eqp" else 0.0
        sub = total if part_key == "sub" else 0.0
        qty = float(rounding.money_qty(dmoney.D(g["adjusted"])))
        part = {"name": name, "unit": g["unit"], "qty": qty,
                "cost": float(g["unit_cost"]),
                "material": mat + eqp + sub, "material_only": mat,
                "equipment": eqp, "sub": sub, "labor_hours": 0.0,
                "labor_cost": lab, "labor_rate": 0.0, "crew_days": 0.0,
                "crew": "", "code": code, "total": total, "line_id": ""}
        rows.append({"name": name, "trade": trade, "csi": code,
                     "measure": "line", "quantity": qty, "unit": g["unit"],
                     "items": g["count"], "parts": [part], "adjust": 1.0,
                     "material": mat + eqp + sub, "labor_hours": 0.0,
                     "labor_cost": lab, "crew_days": 0.0, "total": total,
                     "added": True, "takeoff": True, "line_id": ""})
    return rows


def _text(v, limit):
    return " ".join(str(v).split())[:limit] if isinstance(v, str) else ""


def set_price(doc, name, mtype, unit, **values):
    prices = read_prices(doc)
    entry = prices.setdefault(key_of(name, mtype, unit), {})
    for k in ("waste", "multiplier", "unit_cost"):
        if k in values:
            entry[k] = _num(values[k], 0.0 if k != "multiplier" else 1.0, k)
    for k, limit in (("code", 40), ("cost_type", 20)):
        if k in values:
            t = _text(str(values[k] or ""), limit)
            if k == "code" and t:
                from . import csi
                t = csi.parse_code(t) or t
            if t:
                entry[k] = t
            else:
                entry.pop(k, None)
    write_prices(doc, prices)


def _qty_text(q):
    t = f"{q:f}"
    return t.rstrip("0").rstrip(".") if "." in t else t


def _assembly_rows(doc, page=None, names=None):
    """The assembly-priced rows (Material + Labor in cents, as the
    estimate summary counts them). Nothing is rolled up (no cost book is
    opened) when no takeoff group in `names` has an assembly."""
    from . import assemblies
    if names is not None:
        try:
            if not assemblies.any_known(doc, names):
                return []
        except Exception:                                 # noqa: BLE001
            return []
    try:
        rows, _t, _e = assemblies.rollup(doc, page=page, added=False)
    except Exception:                                     # noqa: BLE001
        logging.getLogger(__name__).warning("assembly estimate left out",
                                            exc_info=True)
        return []
    out = []
    for r in rows:
        mat, lab = dmoney.cents(r["material"]), dmoney.cents(r["labor_cost"])
        if mat or lab:
            out.append(dict(r, _mat=mat, _lab=lab, _total=mat + lab))
    return out


def export_csv(doc, path, page=None):
    rows = lines(doc, page)
    # takeoffs priced by an assembly carry that price, not 0 (Chief's
    # estimator test, Nov 7: a $393,567.92 job exported Grand Total 0.0)
    asm = _assembly_rows(doc, page, [g["name"] for g in rows])
    from . import estimate_export
    by_asm = estimate_export.priced_by_assembly(
        doc, [g["name"] for g in rows], {r["name"] for r in asm})
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = safecell.writer(f)
        w.writerow(["Item", "Type", "Count", "Quantity", "Unit", "Waste %",
                    "Multiplier", "Adjusted Qty", "Unit Cost", "Total",
                    "Pages", "Priced By"])
        for g in rows:
            via = by_asm.get(g["name"]) if not dmoney.cents(g["total"]) \
                else None
            w.writerow([g["name"], g["type"], g["count"],
                        _hu(g["quantity"], 3), g["unit"], g["waste"],
                        g["multiplier"], _hu(g["adjusted"], 3),
                        "" if via else _c2(g["unit_cost"]),
                        "" if via else _c2(g["total"]),
                        g["pages"],
                        f"Assembly: {via}" if via else
                        ("Unit cost" if dmoney.cents(g["total"]) else "")])
        if asm:
            w.writerow([])
            w.writerow(["Assembly Lines"])
            w.writerow(["Assembly", "Trade", "CSI", "Quantity", "Unit",
                        "Items", "Material", "Labor Hours", "Labor",
                        "Total"])
            for r in asm:
                w.writerow([r["name"], r.get("trade", ""), r.get("csi", ""),
                            _hu(r["quantity"], 3), r["unit"],
                            r.get("items", ""), str(r["_mat"]),
                            _c2(r.get("labor_hours") or 0),
                            str(r["_lab"]), str(r["_total"])])
        # lines added in the Estimate panel (typed, from a cost book, or
        # linked to a takeoff group)
        from . import estimate_lines
        added = estimate_lines.priced(doc, page)
        if added:
            w.writerow([])
            w.writerow(["Added Lines"])
            w.writerow(["Code", "Description", "Cost Type", "Quantity",
                        "Unit", "Mat", "Lab", "Eqp", "Sub", "Unit Cost",
                        "Total", "Linked To"])
            for a in added:
                up = a["unit_price"]
                w.writerow([a["code"], a["desc"], a["kind"],
                            _qty_text(a["quantity"]), a["unit_label"],
                            str(up["mat"]), str(up["lab"]), str(up["eqp"]),
                            str(up["sub"]), str(a["unit_cost"]),
                            str(a["total"]),
                            (a.get("link") or {}).get("name", "")])
        w.writerow([])
        grand = sum((dmoney.cents(g["total"]) for g in rows),
                    decimal.Decimal("0.00")) + estimate_lines.total(added) \
            + sum((r["_total"] for r in asm), decimal.Decimal("0.00"))
        w.writerow(["Grand Total", "", "", "", "", "", "", "", "",
                    float(grand)])
        w.writerow([])
        w.writerow(["Detail"])
        # export rule (annotate.EXPORT_RULE): each line says where it came
        # from; AI items still in review are listed apart, in no total
        w.writerow(["Page", "Item", "Type", "Quantity", "Unit", "Origin"])
        org = annotate.ORIGIN_TEXT
        for it in annotate.totals_items(doc):
            if page is None or it["page"] == page:
                w.writerow([it["page"] + 1, it["group"] or it["type"].title(),
                            it["type"], _hu(it["value"], 3), it["unit"],
                            org.get(it.get("origin"), "manual")])
        for it in set_items(doc):
            if page is None or it["page"] == page:
                w.writerow([it["page"] + 1, it["item"], "set",
                            _hu(it["quantity"], 3), it["unit"], "manual"])
        pend = [it for it in annotate.takeoff_items(doc)
                if it.get("pending") and (page is None or
                                          it["page"] == page)]
        if pend:
            w.writerow([])
            w.writerow(["Pending review (AI, not in the totals)"])
            w.writerow(["Page", "Item", "Type", "Quantity", "Unit",
                        "Origin"])
            for it in pend:
                w.writerow([it["page"] + 1, it["group"] or
                            it["type"].title(), it["type"],
                            _hu(it["value"], 3), it["unit"],
                            org["ai-pending"]])
        w.writerow([])                  # Venice #16: how the numbers round
        for r in rounding.csv_rows():
            w.writerow(r)
    return path
