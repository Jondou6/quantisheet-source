"""Truck stock.

Each truck is a stock location. Parts used on a work order come off that
truck. What is under the minimum becomes a restock list in the shape the
Material Order List already exports (estimating/materials.py export), so
the purchase order is the same spreadsheet the estimate already uses.

Money is Decimal. No network calls.
"""
import datetime as dt
from decimal import Decimal

from .. import dmoney
from ..estimating.materials import NO_SUPPLIER
from . import files

FILE = "service_truck_stock.json"
KIND = "service_truck_stock"


class TruckError(ValueError):
    pass


def blank():
    return {"kind": KIND, "version": 1, "trucks": [], "parts": [],
            "levels": [], "issues": []}


def default_path():
    return files.path_for(FILE)


def load(path=None):
    return files.read(path or default_path(), KIND, blank)


def save(store, path=None):
    return files.write(path or default_path(), store)


def _err(exc):
    if isinstance(exc, files.FileError):
        raise TruckError(str(exc)) from exc
    raise exc


def add_truck(store, name, tech=""):
    name = files.txt(name)
    if not name:
        raise TruckError("Name the truck.")
    if any(t["name"].lower() == name.lower() for t in store["trucks"]):
        raise TruckError("That truck is already on the list.")
    row = {"id": files.new_id(), "name": name, "tech": files.txt(tech)}
    store["trucks"].append(row)
    return row["id"]


def add_part(store, desc, cost="0", price="0", sku="", unit="ea",
             supplier="", min_qty="0"):
    desc = files.txt(desc)
    if not desc:
        raise TruckError("Name the part.")
    sku = files.txt(sku, 40)
    if sku and any(p["sku"].lower() == sku.lower() for p in store["parts"]):
        raise TruckError("That item number is already in the catalog.")
    try:
        if str(min_qty) in ("", "0", "0.0", "0.00"):
            minimum = "0.00"
        else:
            minimum = files.qty(min_qty, "Minimum")
        row = {"id": files.new_id(), "sku": sku, "desc": desc,
               "unit": files.txt(unit, 20) or "ea",
               "cost": files.money(cost, "Cost"),
               "price": files.money(price, "Price"),
               "supplier": files.txt(supplier, 120), "min_qty": minimum}
    except files.FileError as e:
        _err(e)
    store["parts"].append(row)
    return row["id"]


def _truck(store, tid):
    for t in store["trucks"]:
        if t["id"] == tid:
            return t
    raise TruckError("That truck isn't on the list.")


def find_part(store, sku_or_id):
    key = files.txt(sku_or_id, 40).lower()
    if not key:
        raise TruckError("Name the part.")
    for p in store["parts"]:
        if p["id"] == sku_or_id or p["sku"].lower() == key \
                or p["desc"].lower() == key:
            return p
    raise TruckError(f"No catalog part {sku_or_id!r}.")


def _level(store, truck_id, part_id):
    for row in store["levels"]:
        if row["truck_id"] == truck_id and row["part_id"] == part_id:
            return row
    row = {"truck_id": truck_id, "part_id": part_id, "qty": "0.00"}
    store["levels"].append(row)
    return row


def on_hand(store, truck_id, part_id):
    for row in store["levels"]:
        if row["truck_id"] == truck_id and row["part_id"] == part_id:
            return dmoney.D(row["qty"])
    return Decimal("0")


def receive(store, truck_id, part, qty):
    """Put quantity on the truck (a delivery, or the start of the count)."""
    _truck(store, truck_id)
    part = find_part(store, part)
    try:
        q = files.qty(qty, "Quantity")
    except files.FileError as e:
        _err(e)
    row = _level(store, truck_id, part["id"])
    row["qty"] = format(dmoney.D(row["qty"]) + dmoney.D(q), "f")
    return row


def issue(store, truck_id, part, qty, work_order_id=""):
    """Take quantity off the truck for a work order. Returns the part line
    (cost and sell price from the catalog)."""
    truck = _truck(store, truck_id)
    part = find_part(store, part)
    try:
        q = dmoney.D(files.qty(qty, "Quantity"))
    except files.FileError as e:
        _err(e)
    have = on_hand(store, truck_id, part["id"])
    if have < q:
        raise TruckError(f"{truck['name']} has {have} of {part['desc']}, "
                         f"not {q}.")
    row = _level(store, truck_id, part["id"])
    row["qty"] = format(have - q, "f")
    rec = {"id": files.new_id(), "truck_id": truck_id, "part_id": part["id"],
           "qty": format(q, "f"), "work_order_id": work_order_id or "",
           "when": dt.date.today().isoformat()}
    store["issues"].append(rec)
    return {"sku": part["sku"], "desc": part["desc"], "qty": format(q, "f"),
            "unit": part["unit"], "cost": part["cost"], "price": part["price"],
            "truck_id": truck_id, "part_id": part["id"], "issue_id": rec["id"]}


def restock_lines(store):
    """Parts under their minimum, one row per truck."""
    out = []
    for truck in store["trucks"]:
        for part in store["parts"]:
            have = on_hand(store, truck["id"], part["id"])
            minimum = dmoney.D(part["min_qty"])
            if minimum <= 0 or have >= minimum:
                continue
            need = minimum - have
            out.append({"truck_id": truck["id"], "truck": truck["name"],
                        "part_id": part["id"], "sku": part["sku"],
                        "desc": part["desc"], "unit": part["unit"],
                        "on_hand": have, "min_qty": minimum,
                        "order_qty": need, "cost": dmoney.D(part["cost"]),
                        "supplier": part["supplier"]})
    return out


def as_material_order(store):
    """{supplier: [rows]} for estimating.materials.export.

    The same part on two trucks is one purchase line. Quantity and cost
    are Decimal, which that export already accepts.
    """
    merged = {}
    for line in restock_lines(store):
        who = line["supplier"] or NO_SUPPLIER
        key = (who, (line["sku"] or line["desc"]).lower(), line["unit"])
        row = merged.get(key)
        if row is None:
            row = {"desc": line["desc"], "unit": line["unit"],
                   "qty": Decimal("0"), "cost": Decimal("0.00"), "code": "",
                   "sources": [], "sku": line["sku"],
                   "supplier_price": line["cost"], "_who": who}
            merged[key] = row
        row["qty"] += line["order_qty"]
        row["cost"] += dmoney.cents(line["order_qty"] * line["cost"])
        src = f"truck {line['truck']}"
        if src not in row["sources"]:
            row["sources"].append(src)
    order = {}
    for row in merged.values():
        who = row.pop("_who")
        order.setdefault(who, []).append(row)
    keys = sorted((k for k in order if k != NO_SUPPLIER), key=str.lower)
    if NO_SUPPLIER in order:
        keys.append(NO_SUPPLIER)
    return {k: order[k] for k in keys}


def export_restock(store, path):
    """Write the restock list with the Material Order List exporter."""
    from ..estimating import materials
    return materials.export(as_material_order(store), path)
