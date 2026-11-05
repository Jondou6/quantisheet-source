"""Material Order List: what to order, grouped by supplier.

The material in the estimate - every priced item (items.py): the added
lines' material part (quantity x Mat), takeoff groups priced by a unit
cost with cost type Material (one with no cost type is not material -
no_cost_type() lists those), the assembly parts and civil activities' materials or
material quotes - merged by item (description + unit), each under:

  1. the supplier you set for the item (kept in the PDF,
     quantisheet_estimate_suppliers.json), else the vendor of the civil
     material quote in use, else
  2. the first of your supplier price list files (supplier_prices.py)
     that lists it by description, with its item number and price, else
  3. "(no supplier yet)".

Exported as CSV or Excel for the purchase orders.
"""
import json
import logging
from decimal import Decimal

from .. import embfiles
from . import _io, safedb, supplier_prices

log = logging.getLogger(__name__)

FILE = "quantisheet_estimate_suppliers.json"
NO_SUPPLIER = "(no supplier yet)"


def suppliers(doc):
    try:
        if doc is not None and FILE in embfiles.names(doc):
            data = json.loads(embfiles.get(doc, FILE).decode("utf-8"))
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in
                        dict(data.get("suppliers") or {}).items()}
    except Exception:                                     # noqa: BLE001
        log.warning("could not read the material suppliers", exc_info=True)
    return {}


def set_supplier(doc, item, supplier):
    """Set (or with '' clear) the supplier of an item (its description)."""
    m = suppliers(doc)
    k = _io.norm(item)
    if str(supplier or "").strip():
        m[k] = " ".join(str(supplier).split())[:120]
    else:
        m.pop(k, None)
    embfiles.put(doc, FILE, json.dumps({"version": 1, "suppliers": m},
                                       indent=1).encode("utf-8"),
                 "QuantiSheet material suppliers")
    return m


@safedb.read_only
def no_cost_type(doc, job=None, lib=None):
    """The priced items left off the list because they have no cost type
    (pick one - Material puts them on the list)."""
    from . import items
    if doc is None and job is None:
        return []
    return [i for i in items.collect(doc, job, lib)["items"]
            if i.get("no_cost_type")]


@safedb.read_only
def collect(doc, job=None, lib=None):
    """[{desc, unit, code, qty, cost, sources}] - material only, merged
    by description + unit (quantities and cost added up), from every
    priced item of the estimate (items.collect): added lines, takeoff
    groups priced by a unit cost, assembly parts and - with a civil job -
    the activities' materials or material quotes."""
    from . import items
    merged = {}
    if doc is None and job is None:
        return []
    for it in items.collect(doc, job, lib)["items"]:
        src = {"line": "estimate line", "assembly": f"assembly {it['desc']}",
               "civil": f"civil {it['desc']}"}.get(it["kind"], "")
        for m in it["materials"]:
            s = src or "takeoff group"
            k = (_io.norm(m["desc"]), _io.norm(m["unit"]))
            r = merged.setdefault(k, {"desc": " ".join(str(m["desc"]).split()),
                                      "unit": m["unit"], "code": m["code"],
                                      "qty": Decimal(0),
                                      "cost": Decimal("0.00"), "sources": [],
                                      "quote_supplier": ""})
            r["qty"] += m["qty"]
            r["cost"] += m["cost"]
            r["code"] = r["code"] or m["code"]
            r["quote_supplier"] = r["quote_supplier"] or m.get("supplier", "")
            if s not in r["sources"]:
                r["sources"].append(s)
    return sorted(merged.values(), key=lambda r: r["desc"].lower())


@safedb.read_only
def order_list(doc, pricelists=(), job=None, lib=None):
    """{supplier: [rows]} (suppliers sorted, "(no supplier yet)" last);
    a row also has "sku" and "supplier_price" when a price list has it.
    A civil material quote in use names its vendor unless you set one."""
    mine = suppliers(doc) if doc is not None else {}
    out = {}
    for r in collect(doc, job, lib):
        r = dict(r, sku="", supplier_price=None)
        who = mine.get(_io.norm(r["desc"])) or r.get("quote_supplier") or None
        for pl in pricelists:
            hit = supplier_prices.find(pl, desc=r["desc"])
            if hit and (who is None or who == pl.get("supplier")):
                who = who or pl.get("supplier")
                r["sku"] = hit.get("sku", "")
                r["supplier_price"] = Decimal(str(hit.get("price") or 0))
                break
        out.setdefault(who or NO_SUPPLIER, []).append(r)
    keys = sorted((k for k in out if k != NO_SUPPLIER), key=str.lower)
    if NO_SUPPLIER in out:
        keys.append(NO_SUPPLIER)
    return {k: out[k] for k in keys}


def export(order, path):
    head = ["Supplier", "Item #", "Description", "Quantity", "Unit",
            "Supplier price", "Estimate material cost", "Code", "From"]
    rows = []
    for who, items in order.items():
        for r in items:
            rows.append([who, r.get("sku", ""), r["desc"], r["qty"],
                         r["unit"], r.get("supplier_price") or "",
                         r["cost"], r["code"], "; ".join(r["sources"])])
    return _io.write_table(path, head, rows, "Order list")
