"""Bid-item schedules in and out, in plain generic columns.

Import: the owner's bid-item list from your own CSV or Excel file
(heavy.read_pay_items reads item no., description, unit, quantity); a
"Unit price" column, when the file has one, is kept too.

Export: a schedule (imported, or priced from the civil estimate by
heavy.spread) as CSV or .xlsx with the columns Item, Description, Unit,
Quantity, Unit price, Amount and a Total row. Text a spreadsheet would
run as a formula is written as text.

Generic only: no agency or bid-service file formats.
"""
from decimal import Decimal, InvalidOperation

from .. import dmoney
from . import _io

PRICE_WORDS = ("unit price", "unit bid price", "price", "unit cost")
NO_WORDS = ("item no", "item", "pay item", "line", "no")


def _col(head, words):
    low = [_io.norm(h) for h in head]
    for test in (lambda h, w: h == w, lambda h, w: h.startswith(w)):
        for w in words:
            for i, h in enumerate(low):
                if h and test(h, w):
                    return i
    return None


def import_items(path):
    """[{no, desc, unit, owner_qty, weight, unit_price ('' if none)}]."""
    from .. import heavy
    head, rows = _io.read_table(path)       # a bad file: TableError (step 5)
    items = heavy.read_pay_items(path)
    prices = {}
    try:
        pc, nc = _col(head, PRICE_WORDS), _col(head, NO_WORDS)
        if pc is not None and nc is not None:
            for r in rows:
                no = str(r[nc]).strip() if nc < len(r) else ""
                v = str(r[pc]).replace(",", "").replace("$", "").strip() \
                    if pc < len(r) else ""
                if no and v:
                    try:
                        prices[no] = str(Decimal(v))
                    except InvalidOperation:
                        pass
    except Exception:                                     # noqa: BLE001
        prices = {}
    return [dict(i, unit_price=prices.get(i["no"], "")) for i in items]


def add_to_job(job, items):
    """Add the items the civil job doesn't have yet (by item no.);
    returns how many were added."""
    have = {p.get("no") for p in job.setdefault("pay_items", [])}
    n = 0
    for i in items:
        if i["no"] in have:
            continue
        job["pay_items"].append({"no": i["no"], "desc": i.get("desc", ""),
                                 "unit": i.get("unit", ""),
                                 "owner_qty": str(i.get("owner_qty") or 0),
                                 "weight": str(i.get("weight") or 1)})
        have.add(i["no"])
        n += 1
    return n


def from_job(job, lib):
    """The civil estimate's priced schedule as items with unit prices."""
    from .. import heavy
    s = heavy.spread(job, lib)
    return [{"no": i["no"], "desc": i["desc"], "unit": i["unit"],
             "owner_qty": str(i["owner_qty"]),
             "unit_price": str(i["unit_price"])} for i in s["items"]]


def export_items(items, path):
    head = ["Item", "Description", "Unit", "Quantity", "Unit price",
            "Amount"]
    rows, total = [], Decimal("0.00")
    for i in items:
        qty = dmoney.D(i.get("owner_qty") or 0)
        up = i.get("unit_price")
        amt = dmoney.cents(qty * dmoney.D(up)) if str(up or "").strip() \
            else Decimal("0.00")
        total += amt
        rows.append([i["no"], i.get("desc", ""), i.get("unit", ""),
                     str(qty), str(up or ""), str(amt)])
    rows.append(["", "Total", "", "", "", str(total)])
    return _io.write_table(path, head, rows, "Bid items")
