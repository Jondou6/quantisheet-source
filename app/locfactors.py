"""Location Factors: your own table of regions (region name, state,
cities, ZIP prefixes or ZIPs, materials / labor / equipment factors and a
note on where the factors came from), searched by state, city,
abbreviation or ZIP, and the location adjustment of an estimate.

The starter rows are QuantiSheet's own public-source state index - the
regions of the shipped starter cost book (materials and equipment: its
materials index; labor: its state wage level against the US). Nothing
else ships: you add cities, ZIPs and factors from your own data or
quotes. Your rows (and your edits of starter rows) live in the price
database; every change is logged in the price history (book "Location
Factors": who, when, old -> new).

Factors apply to base costs priced at national (factor 1.00):

    adjustment = base x (factor - 1)     per cost type, rounded to cents

    location_adjustment(6000, 3000, 1000, "Testville")
    -> materials 600.00 + labor 600.00 + equipment 0.00 = 1200.00 (+12.0%)
"""
import json
import logging
import os
import re
from decimal import ROUND_HALF_UP, Decimal

from . import pricedb
from .dmoney import D, cents

log = logging.getLogger(__name__)

KINDS = ("materials", "labor", "equipment")
FIELDS = ("region", "state", "cities", "zips") + KINDS + ("source",)
_STARTER = {}


def _states():
    from .costbook import STATES
    return STATES


def _starter_book():
    from .costbook import SHIPPED
    try:
        names = sorted(n for n in os.listdir(SHIPPED)
                       if n.endswith(".json") and n.startswith(
                           "QuantiSheet Starter"))
    except OSError:
        return None
    if not names:
        return None
    path = os.path.join(SHIPPED, names[-1])
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    hit = _STARTER.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    _STARTER.clear()
    _STARTER[path] = (mtime, data)
    return data


def starter_rows():
    """The starter rows: one per region of the shipped starter book's
    state index (national 1.00 first)."""
    data = _starter_book()
    if not data:
        return [{"region": "national", "state": "", "cities": "", "zips": "",
                 "materials": 1.0, "labor": 1.0, "equipment": 1.0,
                 "source": "QuantiSheet: national = 1.00", "origin":
                 "starter"}]
    by_name = {v.lower(): k for k, v in _states().items()}
    meta = data.get("regions") or {}
    ver = data.get("version") or ""
    out = []
    for reg, idx in (data.get("index") or {}).items():
        try:
            idx = float(idx)
        except (TypeError, ValueError):
            continue
        info = meta.get(reg) or {}
        try:
            lab = float(info.get("wage_level_vs_us") or 1.0)
        except (TypeError, ValueError):
            lab = 1.0
        if reg == "national":
            src = "QuantiSheet: national = 1.00"
            lab = 1.0
        else:
            src = (f"QuantiSheet starter book {data.get('name', '')} "
                   f"{ver}".strip() + ": materials and equipment = the "
                   "book's materials index (BEA Regional Price Parities, "
                   "goods); labor = the state's wage level vs the US (BLS "
                   "OEWS)")
        out.append({"region": reg, "state": by_name.get(reg.lower(), ""),
                    "cities": "", "zips": "", "materials": idx, "labor": lab,
                    "equipment": idx, "source": src, "origin": "starter"})
    out.sort(key=lambda r: (r["region"] != "national", r["region"].lower()))
    return out


def rows():
    """Every region in the table: the starter rows overlaid with yours
    (a row you edited or added; one you removed is left out). Each row has
    "origin": "starter", "edited" or "yours"."""
    table = {r["region"].lower(): dict(r) for r in starter_rows()}
    try:
        mine = pricedb.location_rows()
    except pricedb.PriceDBError as e:
        log.warning("location factors unreadable: %s", e)
        mine = []
    for r in mine:
        key = str(r["region"]).lower()
        if r.get("deleted"):
            table.pop(key, None)
            continue
        origin = "edited" if key in table and \
            table[key].get("origin") in ("starter", "edited") else "yours"
        row = {k: r.get(k) if r.get(k) is not None else "" for k in FIELDS}
        for k in KINDS:
            try:
                row[k] = float(r.get(k))
            except (TypeError, ValueError):
                row[k] = 1.0
        row["origin"] = origin
        row["modified"] = r.get("modified") or ""
        row["modified_by"] = r.get("modified_by") or ""
        table[key] = row
    out = list(table.values())
    out.sort(key=lambda r: (r["region"] != "national",
                            str(r["region"]).lower()))
    return out


def save(new_rows, note=""):
    """Save edited / added rows (dicts with FIELDS). Rows that match the
    table as it is are skipped. Returns the number of logged changes."""
    cur = {r["region"].lower(): r for r in rows()}
    changes = []
    for r in new_rows:
        old = cur.get(str(r.get("region", "")).strip().lower())
        if r.get("_was") and r["_was"].lower() in cur:
            old = cur[r["_was"].lower()]
        changes.append((old, r))
    return pricedb.save_locations(changes, note)


def remove(region, note=""):
    cur = {r["region"].lower(): r for r in rows()}
    old = cur.get(str(region).strip().lower())
    if not old:
        return 0
    return pricedb.save_locations([(old, None)], note)


def history(limit=500):
    return pricedb.history(pricedb.LOCATION_BOOK, limit=limit)


# ---- search ----------------------------------------------------------------------

_ZIP_TOKEN = re.compile(r"\d{3,5}(?:\s*-\s*\d{3,5})?")


def zip_score(zips, z):
    """How well ZIP (or ZIP start) `z` matches a ZIPs field ("99901-99905,
    29401, 294"): 3 exact ZIP, 2 inside a range, 1 + length/10 for a ZIP
    prefix, 0 no match."""
    z = str(z or "").strip()
    if not z.isdigit():
        return 0
    best = 0
    for tok in _ZIP_TOKEN.findall(str(zips or "")):
        tok = tok.replace(" ", "")
        if "-" in tok:
            lo, hi = tok.split("-", 1)
            if len(z) == 5 and len(lo) == len(hi) == 5 and lo <= z <= hi:
                best = max(best, 2)
            elif len(z) < 5 and (lo.startswith(z) or hi.startswith(z)):
                best = max(best, 0.5)
            continue
        if len(tok) == 5:
            if tok == z:
                best = max(best, 3)
            elif len(z) < 5 and tok.startswith(z):
                best = max(best, 0.5)
        elif z.startswith(tok):
            best = max(best, 1 + len(tok) / 10)
        elif len(z) < len(tok) and tok.startswith(z):
            best = max(best, 0.5)
    return best


def _cities(row):
    return [c.strip().lower() for c in re.split(r"[;,\n]", str(
        row.get("cities") or "")) if c.strip()]


def search(text, table=None):
    """Rows matching `text` - a ZIP or ZIP start, a 2-letter state
    abbreviation, a state name, a city or part of a region name - best
    first. Empty text: every row."""
    table = rows() if table is None else table
    q = " ".join(str(text or "").split())
    if not q:
        return list(table)
    states = _states()
    scored = []
    if q.isdigit():
        for r in table:
            sc = zip_score(r.get("zips"), q)
            if sc:
                scored.append((-sc, str(r["region"]).lower(), r))
        return [x[2] for x in sorted(scored, key=lambda x: x[:2])]
    low = q.lower()
    code = q.upper() if len(q) == 2 and q.upper() in states else ""
    full = states.get(code, "").lower() if code else ""
    if not full:
        for ab, name in states.items():
            if name.lower() == low:
                code, full = ab, name.lower()
                break
    for r in table:
        name = str(r["region"]).lower()
        st = str(r.get("state") or "").upper()
        cities = _cities(r)
        sc = 0
        if name == low:
            sc = 10
        elif code and (st == code or name == full):
            sc = 8 if name == full else 6
        elif low in cities:
            sc = 7
        elif name.startswith(low):
            sc = 5
        elif len(low) > 2 and low in name:
            sc = 4
        elif len(low) > 2 and any(low in c for c in cities):
            sc = 3
        if sc:
            scored.append((-sc, name, r))
    return [x[2] for x in sorted(scored, key=lambda x: x[:2])]


def find_region(text, table=None):
    """The best row for a region name, ZIP, city or state, or None. A
    state abbreviation or name finds the state's own row when there is
    one."""
    q = str(text or "").strip()
    if not q:
        return None
    hits = search(q, table)
    if not hits:
        return None
    if q.isdigit() and len(q) < 3:
        return None
    return hits[0]


def no_match_message(text):
    return f"No region for {str(text).strip()} - pick one or add it"


# ---- adjustment ----------------------------------------------------------------

def _factor(v):
    try:
        f = D(v)
    except Exception:
        return Decimal(1)
    return f if f > 0 else Decimal(1)


def adjustment(mat, lab, eqp, region, table=None):
    """See costbook.location_adjustment."""
    base = {"materials": cents(mat), "labor": cents(lab),
            "equipment": cents(eqp)}
    base["total"] = base["materials"] + base["labor"] + base["equipment"]
    row = None
    if isinstance(region, dict):
        row = region
    elif region:
        tbl = rows() if table is None else table
        row = next((r for r in tbl if str(r["region"]).lower() ==
                    str(region).strip().lower()), None) or \
            find_region(region, tbl)
    factors = {k: _factor(row.get(k)) if row else Decimal(1) for k in KINDS}
    out = {"region": row["region"] if row else None, "found": bool(row),
           "factors": factors, "base": base}
    total = Decimal("0.00")
    for k in KINDS:
        amt = cents(base[k] * (factors[k] - 1))
        out[k] = amt
        total += amt
    out["total"] = total
    pct = (total / base["total"] * 100) if base["total"] else Decimal(0)
    out["percent"] = pct.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    out["percent_text"] = f"{out['percent']:+.1f}%"
    out["grand_total"] = base["total"] + total
    out["lines"] = [("Base estimate", base["total"]),
                    (f"Location adjustment ({out['percent_text']})", total),
                    ("Grand total", out["grand_total"])]
    return out
