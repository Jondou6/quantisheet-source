"""The user's own line-item library (P1: "Own line-item library (user
codes), no Xactimate codes").

Nothing is shipped in it: the library starts empty and every code in it
was typed or imported by the user from their own CSV. It lives in the
module's settings ("library": code -> item). A user category can be added
too (settings "categories", the same table categories.py reads).

CSV columns (header row, any order; only code and description are needed):
  code, description, category, unit, material, labor, equipment, other
Money is dollars ("12.50", "$1,234.00"); bad money is an error for that
row, never 0. Rows that fail are reported, the good ones still come in.
"""
from __future__ import annotations

import csv
import re

from . import categories, settings
from . import model as m
from .cents import MoneyError, parse_money

SETTING = "library"
CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9._/-]{0,23}$")
COST_FIELDS = ("material", "labor", "equipment", "other")
MAX_ROWS = 20_000


class LibraryError(ValueError):
    pass


def _clean_code(code) -> str:
    c = str(code or "").strip().upper()
    if not CODE_RE.match(c):
        raise LibraryError(f"{code!r} isn't a usable code (letters, numbers "
                           "and . _ / -, up to 24 characters)")
    return c


def items() -> dict:
    """{code: {code, description, category, unit, unit_cost{...}}}."""
    raw = settings.get(SETTING) or {}
    return dict(sorted(raw.items())) if isinstance(raw, dict) else {}


def _check(code, description, category, unit, costs) -> dict:
    code = _clean_code(code)
    desc = " ".join(str(description or "").split())[:200]
    if not desc:
        raise LibraryError(f"{code}: a description is needed")
    cat = str(category or "OTHER").strip().upper()
    if not categories.is_known(cat):
        raise LibraryError(f"{code}: unknown category {category!r} - add "
                           "it first")
    u = m.unit_from_text(str(unit or "EA"))
    if u is None:
        raise LibraryError(f"{code}: unknown unit {unit!r}")
    cost = {}
    for k in COST_FIELDS:
        v = (costs or {}).get(k, 0)
        cost[k] = int(v) if isinstance(v, int) else parse_money(
            str(v)) if str(v).strip() else 0
        if cost[k] < 0:
            raise LibraryError(f"{code}: {k} can't be negative")
    return {"code": code, "description": desc, "category": cat, "unit": u,
            "unit_cost": cost}


def add_item(code, description, category="OTHER", unit="EA", **costs):
    """Add or replace one item (costs in cents, or dollar text)."""
    try:
        it = _check(code, description, category, unit, costs)
    except MoneyError as e:
        raise LibraryError(f"{code}: {e}") from None
    lib = items()
    lib[it["code"]] = it
    settings.set(SETTING, lib)
    return it


def remove_item(code) -> bool:
    lib = items()
    gone = lib.pop(str(code or "").strip().upper(), None)
    settings.set(SETTING, lib)
    return gone is not None


def add_category(code, label, group) -> str:
    """A user category (code -> label, trade group)."""
    c = str(code or "").strip().upper()
    if not re.match(r"^[A-Z][A-Z0-9_]{0,23}$", c):
        raise LibraryError(f"{code!r} isn't a usable category code")
    label, group = " ".join(str(label or "").split()), \
        " ".join(str(group or "").split())
    if not label or not group:
        raise LibraryError("A category needs a name and a trade group")
    extra = dict(settings.get("categories") or {})
    extra[c] = [label[:60], group[:60]]
    settings.set("categories", extra)
    return c


def import_csv(path) -> dict:
    """Read the user's CSV. Returns {"added": n, "replaced": n,
    "errors": ["row 4: ..."]}; every good row is kept."""
    lib = items()
    added = replaced = 0
    errors = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)
        heads = {(h or "").strip().lower(): h for h in rd.fieldnames or ()}
        if "code" not in heads or "description" not in heads:
            raise LibraryError("The CSV needs a header row with at least "
                               "'code' and 'description'")

        def col(row, name):
            h = heads.get(name)
            return (row.get(h) or "").strip() if h else ""
        for n, row in enumerate(rd, start=2):
            if n > MAX_ROWS + 1:
                errors.append(f"stopped after {MAX_ROWS} rows")
                break
            if not any((v or "").strip() for v in row.values()
                       if isinstance(v, str)):
                continue
            try:
                it = _check(col(row, "code"), col(row, "description"),
                            col(row, "category") or "OTHER",
                            col(row, "unit") or "EA",
                            {k: col(row, k) for k in COST_FIELDS})
            except (LibraryError, MoneyError) as e:
                errors.append(f"row {n}: {e}")
                continue
            if it["code"] in lib:
                replaced += 1
            else:
                added += 1
            lib[it["code"]] = it
    settings.set(SETTING, lib)
    return {"added": added, "replaced": replaced, "errors": errors}


def export_csv(path) -> int:
    from .cents import money_text
    rows = list(items().values())
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["code", "description", "category", "unit", *COST_FIELDS])
        for it in rows:
            cells = [it["code"], it["description"], it["category"],
                     it["unit"]] + [money_text(it["unit_cost"].get(k, 0))
                                    for k in COST_FIELDS]
            w.writerow(["'" + c if isinstance(c, str) and c[:1] in "=+-@"
                        else c for c in cells])
    return len(rows)


def search(text="") -> list:
    t = str(text or "").lower()
    return [it for it in items().values()
            if not t or t in it["code"].lower() or
            t in it["description"].lower()]


def line_from(code, qty_q4=10_000, structure_id="", ordinal=0) -> m.Line:
    it = items().get(str(code or "").strip().upper())
    if it is None:
        raise LibraryError(f"{code!r} isn't in your library")
    uc = it["unit_cost"]
    return m.Line(id=m.new_id(), item_code=it["code"],
                  description=it["description"], category=it["category"],
                  qty_q4=qty_q4, unit=it["unit"],
                  unit_cost=m.UnitCost(**{k: int(uc.get(k, 0))
                                          for k in COST_FIELDS}),
                  structure_id=structure_id, ordinal=ordinal,
                  origin="library")
