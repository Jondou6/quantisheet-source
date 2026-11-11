"""Bid-Day Quotes: subcontractor and supplier quotes for one scope
package, side by side.

A sheet is your scope list for a package (item, description, unit,
quantity and - if you want - your own plug number) and each bidder's
amount per item; an item a bidder excluded or left blank gets a plug:

  1. your plug number for the item, else
  2. the median of the other bidders' amounts for it, else
  3. nothing - the item stays "unplugged".

For each bidder: the total as quoted, the plugs added, the leveled total
(as quoted + plugs) and whether the quote is complete (every item priced
by the bidder). The sheet names the lowest leveled total and the lowest
COMPLETE quote, so a cheap quote that leaves scope out stands out.

Sheets are kept in the PDF (quantisheet_estimate_bidday.json) by package
name. Quotes can come in as a CSV: Item, Description, Unit, Qty, My plug,
then one column per bidder ("excl" / "n/a" / blank = not quoted).
"""
import datetime
import json
import logging
import statistics
from decimal import Decimal, InvalidOperation

from .. import embfiles
from . import _io
from ..dmoney import c2 as _c2

log = logging.getLogger(__name__)

FILE = "quantisheet_estimate_bidday.json"
EXCLUDED_WORDS = ("excl", "excluded", "n/a", "na", "no bid", "nb", "-")


class BidDayError(ValueError):
    pass


def _amount(v, what):
    s = str(v if v is not None else "").replace(",", "").replace("$", "")
    s = s.strip()
    if not s:
        return None
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise BidDayError(f"{what}: can't read {v!r} as an amount")
    if not d.is_finite() or abs(d) > Decimal("1e12"):
        raise BidDayError(f"{what}: {v!r} is out of range")
    return d.quantize(Decimal("0.01"))


def _group_ref(g):
    if isinstance(g, dict) and g.get("name"):
        return {"name": str(g["name"]), "type": str(g.get("type", "")),
                "unit": str(g.get("unit", ""))}
    return None


def scope_from_takeoff(groups):
    """Scope items from takeoff groups (estimate.lines rows): description,
    unit and measured quantity, and the group itself, so nothing is typed
    twice and Error Check knows the group is priced by the package."""
    out = []
    for i, g in enumerate(groups, 1):
        q = Decimal(str(round(float(g.get("quantity") or 0), 4)))
        out.append({"id": str(i), "desc": g["name"], "unit": g["unit"],
                    "qty": f"{q.normalize():f}", "group": _group_ref(g)})
    return out


def new_sheet(package, scope, bidders):
    def item(i, s):
        out = {"id": str(s.get("id") or i), "desc": str(s.get("desc", "")),
               "unit": str(s.get("unit", "")), "qty": str(s.get("qty", "")),
               "plug": str(s.get("plug") or "")}
        g = _group_ref(s.get("group"))
        if g:
            out["group"] = g
        return out
    return {"package": str(package), "scope": [
        item(i, s) for i, s in enumerate(scope, 1)],
        "bidders": [{"name": str(b["name"]), "kind": b.get("kind", "sub"),
                     # Nov 3: quote dates, for the stale quote warning
                     "quoted_on": str(b.get("quoted_on") or "")[:10],
                     "valid_until": str(b.get("valid_until") or "")[:10],
                     "prices": {str(k): str(v) for k, v in
                                (b.get("prices") or {}).items()},
                     "excluded": [str(x) for x in b.get("excluded") or []],
                     # Nov 3 leveling board: priced but not clearly
                     # included (yellow)
                     "unclear": [str(x) for x in b.get("unclear") or []],
                     "notes": str(b.get("notes", "")),
                     # Nov 11: the quote's own exclusions and inclusions,
                     # word for word, for the Exclusions table
                     **{k: [str(x) for x in b[k]] for k in
                        ("exclusions", "inclusions") if b.get(k)},
                     # ... and where each value is in the quote file
                     **({"file": str(b["file"]),
                         "src": dict(b.get("src") or {}),
                         "ex_src": list(b.get("ex_src") or [])}
                        if b.get("file") else {})}
                    for b in bidders]}


def compare(sheet):
    scope = sheet.get("scope") or []
    bidders = sheet.get("bidders") or []
    quoted = {}                              # (bidder, item) -> Decimal
    for b in bidders:
        for s in scope:
            v = None if s["id"] in b.get("excluded", []) else _amount(
                b["prices"].get(s["id"]), f"{b['name']}, item {s['id']}")
            if v is not None:
                quoted[(b["name"], s["id"])] = v
    rows = []
    res = {b["name"]: {"name": b["name"], "as_quoted": Decimal("0.00"),
                       "plugs": 0, "plug_amount": Decimal("0.00"),
                       "missing": [], "unplugged": []} for b in bidders}
    for s in scope:
        mine = _amount(s.get("plug"), f"plug for item {s['id']}")
        cells = {}
        for b in bidders:
            k = (b["name"], s["id"])
            if k in quoted:
                cells[b["name"]] = {"amount": quoted[k], "plug": False,
                                    "excluded": False}
                res[b["name"]]["as_quoted"] += quoted[k]
                continue
            others = [v for (n, i), v in quoted.items()
                      if i == s["id"] and n != b["name"]]
            plug = mine if mine is not None else (
                Decimal(str(statistics.median(others))).quantize(
                    Decimal("0.01")) if others else None)
            r = res[b["name"]]
            r["missing"].append(s["id"])
            if plug is None:
                r["unplugged"].append(s["id"])
            else:
                r["plugs"] += 1
                r["plug_amount"] += plug
            cells[b["name"]] = {"amount": plug, "plug": True,
                                "excluded": s["id"] in b.get("excluded",
                                                             [])}
        have = {n: c["amount"] for n, c in cells.items() if not c["plug"]}
        rows.append({"id": s["id"], "desc": s["desc"], "unit": s["unit"],
                     "qty": s["qty"], "plug": mine, "cells": cells,
                     "low": min(have, key=have.get) if have else ""})
    out = []
    for b in bidders:
        r = res[b["name"]]
        r["total"] = r["as_quoted"] + r["plug_amount"]
        r["complete"] = not r["missing"]
        out.append(r)
    leveled = [r for r in out if not r["unplugged"]]
    complete = [r for r in out if r["complete"]]
    return {"package": sheet.get("package", ""), "rows": rows,
            "bidders": out,
            "lowest_leveled": min(leveled, key=lambda r: r["total"])["name"]
            if leveled else "",
            "lowest_complete": min(complete, key=lambda r: r["total"])[
                "name"] if complete else ""}


def export_form(sheet, path):
    """A blank bid form for the package (CSV or .xlsx): Item, Description,
    Unit, Qty, My plug - the bidders' columns go to the right; read it
    back with read_csv(..., base=sheet) to keep the takeoff groups."""
    return _io.write_table(path, ["Item", "Description", "Unit", "Qty",
                                  "My plug"],
                           [[s["id"], s["desc"], s["unit"], s["qty"],
                             s.get("plug", "")]
                            for s in sheet.get("scope") or []], "Bid form")


def read_csv(path, package, base=None):
    """The bidders' CSV; with `base` (the package's sheet) each item keeps
    its takeoff group (matched by item number, else description)."""
    sheet = _read_csv(path, package)
    if base:
        by_id = {s["id"]: s.get("group") for s in base.get("scope") or []}
        by_desc = {_io.norm(s["desc"]): s.get("group")
                   for s in base.get("scope") or []}
        for s in sheet["scope"]:
            g = by_id.get(s["id"]) or by_desc.get(_io.norm(s["desc"]))
            if g:
                s["group"] = dict(g)
    return sheet


def _read_csv(path, package):
    head, rows = _io.read_table(path)
    if len(head) < 6:
        raise BidDayError("Columns: Item, Description, Unit, Qty, My plug, "
                          "then one column per bidder.")
    names = [h for h in head[5:] if h.strip()]
    scope, bidders = [], [{"name": n, "prices": {}, "excluded": []}
                          for n in names]
    for i, r in enumerate(rows, 1):
        sid = r[0].strip() or str(i)
        scope.append({"id": sid, "desc": r[1], "unit": r[2], "qty": r[3],
                      "plug": str(_amount(r[4], f"plug, row {i}") or "")})
        for j, b in enumerate(bidders):
            v = r[5 + j].strip() if 5 + j < len(r) else ""
            if v.lower() in EXCLUDED_WORDS:
                b["excluded"].append(sid)
            elif v:
                b["prices"][sid] = str(_amount(v, f"{b['name']}, row {i}"))
    return new_sheet(package, scope, bidders)


def export(result, path):
    names = [b["name"] for b in result["bidders"]]
    head = ["Item", "Description", "Unit", "Qty", "My plug"] + names
    rows = []
    for r in result["rows"]:
        cells = []
        for n in names:
            c = r["cells"][n]
            if c["amount"] is None:
                cells.append("MISSING")
            else:
                cells.append(("PLUG " if c["plug"] else "") +
                             f"{_c2(c['amount']):.2f}")
        rows.append([r["id"], r["desc"], r["unit"], r["qty"],
                     "" if r["plug"] is None else f"{_c2(r['plug']):.2f}"] + cells)
    by = {b["name"]: b for b in result["bidders"]}
    rows.append(["", "As quoted", "", "", ""] +
                [f"{_c2(by[n]['as_quoted']):.2f}" for n in names])
    rows.append(["", "Leveled (with plugs)", "", "", ""] +
                [f"{_c2(by[n]['total']):.2f}" for n in names])
    rows.append(["", "Complete quote", "", "", ""] +
                ["yes" if by[n]["complete"] else "no" for n in names])
    rows.append(["", f"Lowest leveled: {result['lowest_leveled'] or '-'}; "
                 f"lowest complete: {result['lowest_complete'] or '-'}"])
    return _io.write_table(path, head, rows, "Bid day")


# ---- in the PDF ---------------------------------------------------------------

# sheet-level records that outlive new_sheet(): the Exclusions table's
# split / merge choices, and the reason given for using a quote in spite
# of a qualification warning
KEEP = ("ex_moves", "award_override")


def set_extra(doc, package, key, value):
    """Set (or with a falsy value, clear) one of the KEEP records."""
    if key not in KEEP:
        raise BidDayError(f"Not a record of the sheet: {key!r}.")
    sheet = load(doc, package)
    if sheet is None:
        raise BidDayError(f"No package named {package!r}.")
    sheets = [s for s in _all(doc) if s.get("package") != package]
    if value:
        sheet[key] = value
    else:
        sheet.pop(key, None)
    sheets.append(sheet)
    _put(doc, sheets)


def exclusion_bids(doc, package):
    """Each bidder's exclusions and inclusions for the Exclusions table:
    the quote's own lists, plus as inclusions the scope rows it priced."""
    sheet = load(doc, package)
    if sheet is None:
        return []
    out = []
    for b in sheet["bidders"]:
        inc = list(b.get("inclusions") or [])
        for s in sheet["scope"]:
            if s["id"] not in b.get("excluded", []) and \
                    str(b["prices"].get(s["id"]) or "").strip():
                inc.append(s["desc"])
        out.append({"bidder": b["name"],
                    "exclusions": list(b.get("exclusions") or []),
                    "inclusions": inc})
    return out


def _all(doc):
    try:
        if FILE in embfiles.names(doc):
            data = json.loads(embfiles.get(doc, FILE).decode("utf-8"))
            if isinstance(data, dict) and isinstance(data.get("sheets"),
                                                     list):
                return data["sheets"]
    except Exception:                                     # noqa: BLE001
        log.warning("could not read the bid-day sheets", exc_info=True)
    return []


def _put(doc, sheets):
    embfiles.put(doc, FILE, json.dumps({"version": 1, "sheets": sheets},
                                       indent=1).encode("utf-8"),
                 "QuantiSheet bid-day quotes")


def packages(doc):
    return [s.get("package", "") for s in _all(doc)]


def load(doc, package):
    return next((s for s in _all(doc) if s.get("package") == package), None)


def save(doc, sheet):
    compare(sheet)                                   # refuse bad amounts
    was = load(doc, sheet["package"]) or {}
    for k in KEEP:                  # kept when the sheet is rebuilt
        if k not in sheet and was.get(k):
            sheet[k] = was[k]
    sheets = [s for s in _all(doc) if s.get("package") != sheet["package"]]
    sheets.append(sheet)
    _put(doc, sheets)


def delete(doc, package):
    _put(doc, [s for s in _all(doc) if s.get("package") != package])


# ---- Use this quote: into the estimate -------------------------------------------

SOURCE = "Bid day: {package} - {bidder}"
KIND_PART = {"sub": ("sub", "Subcontract"), "supplier": ("mat", "Material"),
             "material": ("mat", "Material")}


def _source_prefix(package):
    return f"Bid day: {package} - "


def _pick(result, bidder):
    names = [b["name"] for b in result["bidders"]]
    if bidder:
        if bidder not in names:
            raise BidDayError(f"No bidder named {bidder!r} in package "
                              f"{result['package']!r}.")
        return bidder, "chosen"
    if result["lowest_complete"]:
        return result["lowest_complete"], "lowest complete"
    if result["lowest_leveled"]:
        return result["lowest_leveled"], "lowest leveled (no complete quote)"
    if not result["bidders"]:
        raise BidDayError("This package has no bidders.")
    # nothing complete or fully plugged: the fewest missing items, then
    # the lowest total (the missing items go in at 0 and show as errors)
    b = min(result["bidders"], key=lambda r: (len(r["unplugged"]),
                                             r["total"]))
    return b["name"], "fewest missing items (nothing complete)"


def _qty(s):
    try:
        q = Decimal(str(s.get("qty") or "").replace(",", "").strip())
    except InvalidOperation:
        return None
    return q if q.is_finite() and q > 0 else None


def _line_for(row, cell, bidder, kind, package):
    from .. import dmoney, estimate_lines as EL
    part, ctype = KIND_PART.get(kind or "sub", KIND_PART["sub"])
    amount = cell["amount"]
    unit = row["unit"] or "ls"
    q = _qty(row)
    note = ""
    if amount is None:
        note = (f"MISSING: not in {bidder}'s quote and no plug - price it "
                "before the bid")
        amount = Decimal("0.00")
    elif cell["plug"]:
        how = "your plug" if row["plug"] is not None else \
            "median of the other bidders"
        note = f"PLUG: not in {bidder}'s quote - {how}"
    qty, unit_price = Decimal(1), amount
    if q is not None:
        up = (amount / q).quantize(EL.UNIT_PLACES)
        if dmoney.cents(up * q) == amount:
            qty, unit_price = q, up
        else:
            # keep the quoted amount to the cent: one lump sum
            note = "; ".join(filter(None, [note, f"quoted for {q.normalize():f}"
                                                 f" {unit} as a lump sum"]))
            unit = "ls"
    return EL.new_line(row["desc"] or f"Item {row['id']}", qty, unit,
                       cost_type=ctype, source=SOURCE.format(
                           package=package, bidder=bidder)[:120],
                       note=note, **{part: unit_price})


def _strip(lines, sheet):
    """The estimate lines without this package's bid-day lines."""
    old = set(((sheet or {}).get("applied") or {}).get("line_ids", {})
              .values())
    pre = _source_prefix(sheet["package"])
    return [ln for ln in lines if ln["id"] not in old and
            not ln["source"].startswith(pre)]


def apply_quote(doc, package, bidder=None):
    """Put a package's quote into the estimate: one added line per scope
    item (subcontract for a sub, material for a supplier), plugs marked
    in the line's note, an item nobody priced in at 0 (Error Check shows
    it). `bidder` None = the lowest complete quote (else the lowest
    leveled). Re-applying replaces the package's lines. One document
    change, so one Undo takes it all back."""
    from .. import estimate_lines as EL
    sheet = load(doc, package)
    if sheet is None:
        raise BidDayError(f"No bid-day package named {package!r}.")
    result = compare(sheet)
    name, how = _pick(result, bidder)
    kind = next((b.get("kind", "sub") for b in sheet["bidders"]
                 if b["name"] == name), "sub")
    new, ids, plugs, missing = [], {}, [], []
    for row in result["rows"]:
        cell = row["cells"][name]
        ln = _line_for(row, cell, name, kind, package)
        new.append(ln)
        ids[row["id"]] = ln["id"]
        if cell["amount"] is None:
            missing.append(row["id"])
        elif cell["plug"]:
            plugs.append(row["id"])
    kept = _strip(EL.read(doc), sheet)
    if len(kept) + len(new) > EL.MAX_LINES:
        raise BidDayError(f"An estimate holds at most {EL.MAX_LINES} lines.")
    EL.write(doc, kept + new)
    total = next(b["total"] for b in result["bidders"] if b["name"] == name)
    sheet["applied"] = {"bidder": name, "how": how, "auto": bidder is None,
                        "line_ids": ids, "plugs": plugs, "missing": missing,
                        "total": str(total),
                        "amounts": {i: str(row["cells"][name]["amount"] or
                                           "0.00")
                                    for i, row in zip(ids, result["rows"])},
                        "at": datetime.date.today().isoformat()}
    save(doc, sheet)
    return {"bidder": name, "how": how, "line_ids": ids, "plugs": plugs,
            "missing": missing, "total": total}


def remove_quote(doc, package):
    """Take a package's bid-day lines out of the estimate; how many."""
    from .. import estimate_lines as EL
    sheet = load(doc, package)
    if sheet is None:
        raise BidDayError(f"No bid-day package named {package!r}.")
    lines = EL.read(doc)
    kept = _strip(lines, sheet)
    EL.write(doc, kept)
    sheet.pop("applied", None)
    save(doc, sheet)
    return len(lines) - len(kept)


def applied_problems(doc):
    """[(package, item, kind, message)] for Estimate Error Check: plugs in
    the estimate ("plug") and quotes that changed after they were used,
    lines removed or edited by hand ("stale")."""
    from .. import estimate_lines as EL
    out = []
    priced = {p["id"]: p for p in EL.priced(doc)}
    for sheet in _all(doc):
        ap = sheet.get("applied")
        if not isinstance(ap, dict):
            continue
        pkg = sheet.get("package", "")
        try:
            result = compare(sheet)
        except BidDayError as e:
            out.append((pkg, pkg, "stale", f"package {pkg!r}: {e}"))
            continue
        name = ap.get("bidder", "")
        desc = {r["id"]: r["desc"] or f"Item {r['id']}"
                for r in result["rows"]}
        for i in ap.get("plugs") or []:
            out.append((pkg, desc.get(i, i), "plug",
                        f"{pkg}: item {i} is a plug, not in {name}'s quote"))
        now = next((b for b in result["bidders"] if b["name"] == name), None)
        if now is None:
            out.append((pkg, pkg, "stale", f"{pkg}: bidder {name} is no "
                        "longer on the sheet - use a quote again"))
            continue
        if str(now["total"]) != ap.get("total"):
            out.append((pkg, pkg, "stale",
                        f"{pkg}: {name}'s leveled total is now "
                        f"{_c2(now['total']):.2f}, the estimate has "
                        f"{_c2(Decimal(ap.get('total') or 0)):.2f} - use the "
                        "quote again"))
        if ap.get("auto") and result["lowest_complete"] and \
                result["lowest_complete"] != name:
            out.append((pkg, pkg, "stale",
                        f"{pkg}: {result['lowest_complete']} is now the "
                        f"lowest complete quote; the estimate has {name}"))
        for i, lid in (ap.get("line_ids") or {}).items():
            p = priced.get(lid)
            if p is None:
                out.append((pkg, desc.get(i, i), "stale",
                            f"{pkg}: the line for item {i} is no longer in "
                            "the estimate"))
            elif str(p["total"]) != (ap.get("amounts") or {}).get(i, str(
                    p["total"])):
                out.append((pkg, desc.get(i, i), "stale",
                            f"{pkg}: the line for item {i} was changed by "
                            f"hand ({_c2(p['total']):.2f}, quoted "
                            f"{ap['amounts'][i]})"))
    return out


def applied_groups(doc):
    """{(name, type, unit): package} - takeoff groups in the scope of a
    bid-day package whose quote is in the estimate."""
    out = {}
    for sheet in _all(doc):
        if not isinstance(sheet.get("applied"), dict):
            continue
        for s in sheet.get("scope") or []:
            g = _group_ref(s.get("group"))
            if g:
                out[(g["name"], g["type"], g["unit"])] = sheet.get(
                    "package", "")
    return out
