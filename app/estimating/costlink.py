"""Link takeoff to your own cost items.

A cost item is one of your own priced items: a cost book item
(costbook.py), a supplier price list item (supplier_prices.py) or one you
type. Linking it to a takeoff group adds an estimate line
(estimate_lines.py) whose quantity is read from the group every time the
estimate is priced, so it follows the markups as they are drawn. An
optional quantity formula turns the group's quantity into the item's unit:

    ceil(qty / 32 * 1.1)     4x8 sheets for an area, 10 % waste
    count * 4                four anchors per counted item

`qty` is the group's measured quantity in the group's own unit and
`count` its number of markups; the functions are the assembly formulas'
(ceil, floor, round, roundup, min, max, abs, sqrt). The formula is kept
on the line's link inside the PDF, with the line.
"""
from decimal import Decimal

from .. import estimate_lines as EL


def groups(doc):
    """The takeoff groups on the drawings: [{name, type, unit, quantity,
    count}]."""
    from .. import estimate
    if doc is None:
        return []
    return [{"name": g["name"], "type": g["type"], "unit": g["unit"],
             "quantity": g["quantity"], "count": g["count"]}
            for g in estimate.lines(doc)]


def check_formula(formula):
    """'' when the formula works, else LineError."""
    from .. import assemblies
    f = str(formula or "").strip()
    if not f:
        return ""
    try:
        float(assemblies.evaluate(f, {"qty": 1.0, "count": 1.0}))
    except Exception as e:                                # noqa: BLE001
        raise EL.LineError(f"Quantity formula {f!r}: {e}") from e
    return f


def _group_key(group):
    if isinstance(group, (tuple, list)):
        name, typ, unit = group
    else:
        name, typ, unit = group["name"], group["type"], group["unit"]
    return {"name": name, "type": typ, "unit": unit}


def link_item(doc, item, group, formula=""):
    """Add `item` ({desc, unit, code, cost_type, mat, lab, eqp, sub,
    source, hours, crew}) as an estimate line linked to `group` (a
    group dict or (name, type, unit)). Returns the line id."""
    f = check_formula(formula)
    link = _group_key(group)
    if f:
        link["formula"] = f
    vals = {k: item.get(k) for k in ("desc", "code", "cost_type", "mat",
                                     "lab", "eqp", "sub", "source", "hours",
                                     "crew", "note") if item.get(k)
            is not None}
    unit = item.get("unit") or link["unit"]
    if not f:
        why = EL.link_problem(link, unit)
        if why:
            raise EL.LineError(why + " - add a quantity formula to convert")
    line = EL.new_line(qty=0, unit=unit, link=link, **vals)
    return EL.add(doc, [line])[0]


def set_formula(doc, line_id, formula):
    """Change (or with '' remove) a linked line's quantity formula."""
    ln = EL.get(doc, line_id)
    if ln is None or not ln.get("link"):
        raise EL.LineError("That line isn't linked to a takeoff group.")
    f = check_formula(formula)
    link = dict(ln["link"])
    link.pop("formula", None)
    if f:
        link["formula"] = f
    else:
        why = EL.link_problem(link, ln["unit"] or link["unit"])
        if why:
            raise EL.LineError(why + " - keep a quantity formula")
    return EL.update(doc, line_id, link=link)


def item_from_book(book, code, **opts):
    """A cost item from a cost book item, priced as the job prices it
    (estimate_lines.from_book: region index, escalation, crew rates)."""
    ln = EL.from_book(book, code, **opts)
    return {k: ln.get(k) for k in ("desc", "unit", "code", "cost_type",
                                   "mat", "lab", "eqp", "sub", "source",
                                   "hours", "crew")}


def item_from_supplier(pricelist, sku):
    """A material cost item from a supplier price list file's item."""
    for it in pricelist.get("items") or []:
        if str(it.get("sku")) == str(sku):
            price = Decimal(str(it.get("price") or 0))
            pack = Decimal(str(it.get("pack") or 1)) or Decimal(1)
            return {"desc": it.get("desc", ""), "unit": it.get("unit", ""),
                    "code": it.get("code", ""), "cost_type": "Material",
                    "mat": str((price / pack).quantize(EL.UNIT_PLACES))
                    if pack != 1 else str(price),
                    "source": f"{pricelist.get('supplier', '')} "
                              f"#{it.get('sku')}".strip()}
    raise KeyError(sku)


def linked(doc):
    """The linked lines, priced (quantity from their groups now)."""
    return [p for p in EL.priced(doc) if p["linked"]]
