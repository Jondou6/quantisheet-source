"""Match Rates (r36 v2 step 7, G4.1 / G4.2 / G4.4): price the unpriced
takeoff groups from YOUR cost books in one go.

Where the rates come from: the cost books in your price database, read
read-only (the database file is opened read-only and is never made,
filled or changed here). QuantiSheet ships no rates.

How a takeoff group is matched to a cost book item, in this order:

  1. your saved match for that description (Save Matches...), when the
     item is still in the book and its unit converts;
  2. the group's cost code (Estimate panel) = the item's code, and the
     item's unit converts to the group's unit (sf <-> sq ft, sy -> sq ft
     at 1/9, lf <-> ft, ea, ...);
  3. the same description (case, spaces and punctuation aside) and a
     unit that converts;
  4. otherwise the closest description sharing at least half its words
     is shown as a LOOSE match - never ticked; you tick it if it's right.

Only 1-3 are ticked. Groups something already prices (a unit cost, a
linked line, an assembly, a civil activity, a bid-day package) are left
alone. Apply sets a group's unit cost, cost code and cost type when the
item has one kind of cost (material, labor, equipment or sub); an item
with more than one adds a line linked to the group so the split is kept.
The group's waste and multiplier are honoured either way.

    read_books() -> {name: costbook.Book}
    match(doc, books, mapping=None) -> {"rows", "counts", "already_priced"}
    preview(doc, rows) -> {"rows": [{name, unit_cost, qty, total, mode}],
                           "total"}
    apply(doc, rows) -> {"priced", "lines", "skipped"}
    load_matches(path) / save_matches(m, path) / remember(m, rows)
"""
import logging
import os
import re
import sqlite3
from decimal import Decimal

from .. import dmoney, estimate_lines as EL
from . import _io, safedb

log = logging.getLogger(__name__)

MATCH_FILE = "rate_matches.json"
LOOSE_MIN = 0.5
UNIT_PLACES = Decimal("0.0001")


class MatchError(ValueError):
    """A saved matches file can't be used."""


# ---- your cost books, read-only -----------------------------------------------

def _read_books(p):
    from .. import costbook
    out = {}
    con = safedb._ro(p)
    try:
        have = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "books" not in have or "items" not in have:
            return out
        import json
        for b in con.execute("SELECT * FROM books"):
            data = {"name": b["name"], "effective": b["effective"],
                    "region": b["region"], "escalation": b["escalation"],
                    "rates": {}, "items": {}}
            for k, col in (("index", "index_json"), ("regions",
                                                     "regions_json")):
                try:
                    data[k] = json.loads(b[col] or "{}")
                except (IndexError, KeyError, ValueError):
                    pass
            if "rates" in have:
                for r in con.execute("SELECT region, trade, rate FROM rates "
                                     "WHERE book=?", (b["name"],)):
                    data["rates"].setdefault(r[0], {})[r[1]] = r[2]
            for r in con.execute("SELECT * FROM items WHERE book=?",
                                 (b["name"],)):
                keys = r.keys()
                data["items"][r["code"]] = {
                    k: r[k] for k in ("desc", "unit", "material", "labor",
                                      "crew", "sub", "equipment")
                    if k in keys and r[k] not in (None, "")}
            out[b["name"]] = costbook.Book(data, path="db:" + b["name"])
    finally:
        con.close()
    return out


def read_books():
    """{name: Book} from the price database, opened read-only; {} when
    there is no database (none is made)."""
    from .. import pricedb
    p = safedb.path()
    if not os.path.isfile(p):
        return {}
    try:
        return _read_books(p)
    except sqlite3.Error as e:
        cache = pricedb.cache_path()
        if pricedb.is_shared(p) and os.path.isfile(cache):
            return _read_books(cache)
        raise pricedb.PriceDBError(
            f"Can't read the price database {p}: {e}") from e


# ---- matching -----------------------------------------------------------------

def _norm(s):
    return " ".join(re.sub(r"[^0-9a-z]+", " ", str(s or "").lower()).split())


def match_key(desc):
    return _norm(desc)


def _words(s):
    return set(_norm(s).split())


def unit_factor(target_unit, item_unit):
    """Decimal f: price per target unit = price per item unit x f; None
    when the units are different kinds of thing (a lump sum only goes
    with a lump sum)."""
    a, b = str(target_unit or "").strip(), str(item_unit or "").strip()
    if not b or a.lower() == b.lower():
        return Decimal(1)
    if "ls" in (a.lower(), b.lower()):
        return None
    try:
        f = EL.convert(Decimal(1), a, b)
    except Exception:                                     # noqa: BLE001
        return None
    return Decimal(str(round(float(f), 10))).normalize()


def _code(c):
    from .. import csi
    return (csi.parse_code(c) or str(c or "").strip()) if c else ""


def targets(doc, job=None):
    """(unpriced takeoff groups, how many are already priced)."""
    from .. import estimate
    from . import checks
    priced = checks.priced_groups(doc, job)
    out, skipped = [], 0
    for g in estimate.lines(doc):
        key = (g["name"], g["type"], g["unit"])
        if key in priced:
            skipped += 1
            continue
        out.append({"id": "takeoff:" + estimate.key_of(*key),
                    "name": g["name"], "type": g["type"], "unit": g["unit"],
                    "qty": dmoney.D(round(g["quantity"], 4)),
                    "adjusted": dmoney.D(round(g["adjusted"], 4)),
                    "waste": g["waste"], "multiplier": g["multiplier"],
                    "code": g.get("code") or ""})
    return out, skipped


def _items(books):
    for bname, book in sorted((books or {}).items()):
        for code, it in sorted(book.items.items()):
            yield bname, code, it


def _priced(doc, book, code, job):
    ln = EL.from_book(book, code, job=job)
    parts = {k: Decimal(ln[k]) for k in EL.PARTS}
    return {"desc": ln["desc"], "unit": ln["unit"], "code": ln["code"],
            "book": book.name, "parts": parts,
            "unit_cost": sum(parts.values(), Decimal(0)),
            "hours": ln["hours"], "crew": ln["crew"],
            "source": f"{book.name} {ln['code']}"}


def _row(t, status, how="", reason="", item=None, factor=None):
    r = {"target": t, "status": status, "how": how, "reason": reason,
         "item": item, "ticked": status == "exact", "unit_cost": None}
    if item is not None and factor is not None:
        r["factor"] = factor
        r["unit_cost"] = (item["unit_cost"] * factor).quantize(UNIT_PLACES)
    return r


def match(doc, books, mapping=None, job=None):
    """Every unpriced takeoff group with its best item (see the module)."""
    from .. import assemblies
    ajob = assemblies.read_job(doc)
    tg, skipped = targets(doc, job)
    saved = (mapping or {}).get("matches") or {}
    items = list(_items(books))
    by_code = {}
    by_desc = {}
    for bname, code, it in items:
        by_code.setdefault(_code(code), []).append((bname, code, it))
        by_desc.setdefault(_norm(it.get("desc")), []).append(
            (bname, code, it))
    rows = []
    for t in tg:
        rows.append(_match_one(doc, t, books, saved, by_code, by_desc, items,
                               ajob))
    counts = {k: sum(1 for r in rows if r["status"] == k)
              for k in ("exact", "fuzzy", "none")}
    return {"rows": rows, "counts": counts, "already_priced": skipped}


def _match_one(doc, t, books, saved, by_code, by_desc, items, ajob):
    why = []
    s = saved.get(match_key(t["name"]))
    if s:
        book = (books or {}).get(s.get("book"))
        it = book.get(s.get("code")) if book is not None else None
        if it is None:
            why.append(f"your saved match {s.get('book')} {s.get('code')} "
                       "is no longer in your cost books")
        else:
            f = unit_factor(t["unit"], it.get("unit"))
            if f is None:
                why.append(f"your saved match {s.get('code')} is priced per "
                           f"{it.get('unit')}; the group is in {t['unit']}")
            else:
                return _row(t, "exact", "your saved match", "",
                            _priced(doc, book, s["code"], ajob), f)
    if t["code"]:
        for bname, code, it in by_code.get(_code(t["code"]), []):
            f = unit_factor(t["unit"], it.get("unit"))
            if f is None:
                why.append(f"{_code(code)} in {bname} is priced per "
                           f"{it.get('unit')}; the group is measured in "
                           f"{t['unit']}")
                continue
            return _row(t, "exact", "cost code + unit", "",
                        _priced(doc, books[bname], code, ajob), f)
    for bname, code, it in by_desc.get(_norm(t["name"]), []):
        f = unit_factor(t["unit"], it.get("unit"))
        if f is None:
            why.append(f"{it.get('desc')!r} is priced per {it.get('unit')}; "
                       f"the group is measured in {t['unit']}")
            continue
        return _row(t, "exact", "same description + unit", "",
                    _priced(doc, books[bname], code, ajob), f)
    best, score = None, 0.0
    tw = _words(t["name"])
    for bname, code, it in items:
        iw = _words(it.get("desc"))
        if not tw or not iw:
            continue
        sc = len(tw & iw) / len(tw | iw)
        if sc > score and unit_factor(t["unit"], it.get("unit")) is not None:
            best, score = (bname, code, it), sc
    if best is not None and score >= LOOSE_MIN:
        bname, code, it = best
        reason = ("same words in a different order" if score == 1.0 else
                  f"description {round(score * 100)}% alike")
        return _row(t, "fuzzy", "loose description", reason + " - check it "
                    "before ticking", _priced(doc, books[bname], code, ajob),
                    unit_factor(t["unit"], it.get("unit")))
    if not books:
        why.append("no cost books in your price database")
    return _row(t, "none", "", "; ".join(why) or "no item with this code or "
                "description")


# ---- preview and apply --------------------------------------------------------

def _mode(item):
    filled = [k for k, v in item["parts"].items() if v]
    return "price" if len(filled) <= 1 else "line"


def _qty_factor(t, r):
    """Group quantity -> item quantity, waste and multiplier included."""
    q = Decimal(1) / r["factor"] if r["factor"] else Decimal(1)
    q *= Decimal(str(1 + float(t["waste"] or 0) / 100))
    q *= Decimal(str(t["multiplier"] or 1))
    return q


def preview(doc, rows):
    """What Apply would do for the ticked rows (nothing is written)."""
    out = []
    for r in rows:
        if not r["ticked"] or r["item"] is None:
            continue
        t = r["target"]
        mode = _mode(r["item"])
        if mode == "price":
            total = dmoney.cents(t["adjusted"] * r["unit_cost"])
        else:
            qty = (t["qty"] * _qty_factor(t, r)).quantize(EL.QTY_PLACES)
            total = sum((dmoney.cents(qty * v) for v in
                         r["item"]["parts"].values()), Decimal("0.00"))
        out.append({"name": t["name"], "unit": t["unit"],
                    "unit_cost": r["unit_cost"], "qty": t["adjusted"],
                    "total": total, "mode": mode,
                    "source": r["item"]["source"], "how": r["how"]})
    return {"rows": out, "total": sum((x["total"] for x in out),
                                      Decimal("0.00"))}


_LABEL = {"mat": "Material", "lab": "Labor", "eqp": "Equipment",
          "sub": "Subcontract"}


def apply(doc, rows, job=None):
    """Price the ticked groups. Re-checks that each is still unpriced, so
    applying twice never doubles anything."""
    from .. import estimate
    from . import checks, costlink
    priced = checks.priced_groups(doc, job)
    out = {"priced": 0, "lines": 0, "skipped": []}
    for r in rows:
        if not r["ticked"]:
            continue
        t = r["target"]
        if r["item"] is None or r.get("factor") is None:
            out["skipped"].append({"name": t["name"],
                                   "why": r["reason"] or "no item"})
            continue
        key = (t["name"], t["type"], t["unit"])
        if key in priced:
            continue
        it = r["item"]
        if _mode(it) == "price":
            part = next((k for k, v in it["parts"].items() if v), "mat")
            estimate.set_price(doc, *key, unit_cost=float(r["unit_cost"]),
                               code=it["code"], cost_type=_LABEL[part])
            out["priced"] += 1
        else:
            q = _qty_factor(t, r)
            formula = "" if q == 1 else \
                f"qty * {format(q.quantize(Decimal('0.000001')).normalize(), 'f')}"
            costlink.link_item(doc, {
                "desc": it["desc"], "unit": it["unit"], "code": it["code"],
                "mat": str(it["parts"]["mat"]), "lab": str(it["parts"]["lab"]),
                "eqp": str(it["parts"]["eqp"]), "sub": str(it["parts"]["sub"]),
                "hours": it["hours"], "crew": it["crew"],
                "source": it["source"]}, key, formula=formula)
            out["lines"] += 1
        priced.add(key)
    return out


# ---- saved matches --------------------------------------------------------------

def default_path():
    return _io.data_file(MATCH_FILE)


def load_matches(path=None):
    p = path or default_path()
    if not os.path.isfile(p):
        return {"version": 1, "matches": {}}
    try:
        data = _io.read_json(p)
    except (OSError, ValueError) as e:
        raise MatchError(f"{os.path.basename(p)} can't be read: {e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("matches"),
                                                    dict):
        raise MatchError(f"{os.path.basename(p)} is not a saved matches "
                         "file.")
    return {"version": 1, "matches": {
        str(k): {"book": str(v.get("book", "")), "code": str(v.get("code",
                                                                  "")),
                 "desc": str(v.get("desc", ""))[:200]}
        for k, v in data["matches"].items() if isinstance(v, dict)}}


def remember(mapping, rows):
    """`mapping` plus the ticked rows' matches."""
    m = {"version": 1, "matches": dict((mapping or {}).get("matches") or {})}
    for r in rows:
        if r["ticked"] and r["item"] is not None:
            m["matches"][match_key(r["target"]["name"])] = {
                "book": r["item"]["book"], "code": r["item"]["code"],
                "desc": r["item"]["desc"]}
    return m


def save_matches(mapping, path=None):
    """Write the matches file (a backup copy of the old one first);
    returns how many matches it holds."""
    p = _io.check_user_path(path or default_path())
    _io.backup_file(p)
    _io.write_json(p, {"version": 1, "matches": mapping.get("matches")
                       or {}})
    return len(mapping.get("matches") or {})
