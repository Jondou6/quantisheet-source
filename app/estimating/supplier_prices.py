"""Supplier price lists: a dealer's or supplier's price list you were
given (CSV or Excel) imported into a NEW price list file you name.

You map the columns (item / SKU number, description, unit, price, pack
size, category - guessed from the header words), check the rows, give the
supplier's name and the date the prices are good from, and save. The file
is plain JSON you keep where you like; QuantiSheet never writes it into
its own program folder, never over a file that's there (unless you say
so) and never into a price database. No price list ships with QuantiSheet.

    {"kind": "supplier_prices", "version": 1, "supplier": "...",
     "effective": "2026-10-01", "source_file": "...", "imported": "...",
     "items": [{"sku", "desc", "unit", "price", "pack", "category"}]}

Material Order List (materials.py) finds an item's supplier in these
files, and Link to Cost Item (costlink.py) can price a line from one.
"""
import datetime
import os
import re
from decimal import Decimal, InvalidOperation

from . import _io

KIND = "supplier_prices"
VERSION = 1
FIELDS = ("sku", "desc", "unit", "price", "pack", "category")
GUESS = {
    "sku": ("sku", "item #", "item no", "item number", "part #",
            "part number", "product code", "item", "code"),
    "desc": ("description", "item description", "product", "desc", "name"),
    "unit": ("uom", "unit", "units", "u/m", "unit of measure"),
    "price": ("unit price", "price", "cost", "net price", "your price",
              "each"),
    "pack": ("pack", "pack size", "per", "qty per", "case qty"),
    "category": ("category", "class", "group", "department", "dept"),
}


class PriceListError(ValueError):
    pass


def read(path):
    return _io.read_table(path)


def guess_mapping(head):
    low = [_io.norm(h) for h in head]
    out, used = {}, set()
    for exact in (True, False):
        for field in FIELDS:
            if field in out:
                continue
            for w in GUESS[field]:
                hit = next((i for i, h in enumerate(low) if i not in used and
                            (h == w if exact else h.startswith(w))), None)
                if hit is not None:
                    out[field] = hit
                    used.add(hit)
                    break
    return out


def _price(v):
    s = re.sub(r"[,$\s]", "", str(v or ""))
    if not s:
        raise PriceListError("no price")
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise PriceListError(f"can't read {v!r} as a price")
    if not d.is_finite() or d < 0 or d > Decimal("1e9"):
        raise PriceListError(f"{v!r} is out of range")
    return d.quantize(Decimal("0.01")) if d == d.quantize(Decimal("0.01")) \
        or d >= 1 else d.quantize(Decimal("0.0001"))


def build(head, rows, mapping, supplier, effective="", file_name=""):
    """{"pricelist": {...}, "skipped": [{"row", "why"}]}."""
    supplier = " ".join(str(supplier or "").split())
    if not supplier:
        raise PriceListError("Type the supplier's name.")
    for f in ("sku", "desc", "price"):
        if f not in mapping:
            raise PriceListError(f"Pick the column for {f}.")
    items, skipped, seen = [], [], set()

    def cell(r, f):
        i = mapping.get(f)
        return " ".join(str(r[i]).split()) if i is not None and i < len(r) \
            else ""
    for n, r in enumerate(rows, 2):
        sku, desc = cell(r, "sku"), cell(r, "desc")
        if not sku:
            skipped.append({"row": n, "why": "no item number"})
            continue
        try:
            price = _price(cell(r, "price"))
        except PriceListError as e:
            skipped.append({"row": n, "why": str(e)})
            continue
        if sku in seen:
            skipped.append({"row": n, "why": f"item {sku} is listed twice"})
            continue
        seen.add(sku)
        pack = cell(r, "pack") or "1"
        try:
            pack = str(Decimal(pack.replace(",", "")) or 1)
        except InvalidOperation:
            pack = "1"
        items.append({"sku": sku[:60], "desc": desc[:300],
                      "unit": cell(r, "unit")[:12], "price": str(price),
                      "pack": pack, "category": cell(r, "category")[:60]})
    return {"pricelist": {"kind": KIND, "version": VERSION,
                          "supplier": supplier[:120],
                          "effective": str(effective or ""),
                          "source_file": file_name,
                          "imported": datetime.date.today().isoformat(),
                          "items": items},
            "skipped": skipped}


def validate(pl):
    if not isinstance(pl, dict) or pl.get("kind") != KIND or \
            not isinstance(pl.get("items"), list):
        raise PriceListError("Not a QuantiSheet supplier price list file.")
    return pl


def save(pl, path, overwrite=False):
    return _save(pl, path, overwrite)[0]


def _save(pl, path, overwrite=False):
    """(path, backup): replacing a file you said may be replaced keeps a
    copy of the old one in <data folder>/backups first (v2 step 5)."""
    p = _io.check_user_path(path, (".json",))
    validate(pl)
    bak = None
    if os.path.exists(p):
        if not overwrite:
            raise PriceListError(f"{os.path.basename(p)} is already there; "
                                 "pick a new file name.")
        bak = _io.backup_file(p, "price-import")
    return _io.write_json(p, pl), bak


def load(path):
    try:
        return validate(_io.read_json(path))
    except (OSError, ValueError) as e:
        if isinstance(e, PriceListError):
            raise
        raise PriceListError(f"Can't read {os.path.basename(path)}: {e}")


def import_file(path, supplier, out_path, mapping=None, effective="",
                overwrite=False):
    head, rows = read(path)
    mapping = guess_mapping(head) if mapping is None else mapping
    res = build(head, rows, mapping, supplier, effective,
                os.path.basename(path))
    if not res["pricelist"]["items"]:
        raise PriceListError("No rows with an item number and a price.")
    res["saved"], res["backup"] = _save(res["pricelist"], out_path,
                                        overwrite)
    return res


def find(pl, sku=None, desc=None):
    """The item by number, else by description (case and spaces ignored)."""
    items = pl.get("items") or []
    if sku is not None:
        return next((i for i in items if str(i.get("sku")) == str(sku)),
                    None)
    if desc is not None:
        d = _io.norm(desc)
        return next((i for i in items if _io.norm(i.get("desc")) == d), None)
    return None
