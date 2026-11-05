"""Price a Workbook... (r36 v2 step 7, G4.3): an Estimate Workbook made by
QuantiSheet (AI Takeoff > 4. Estimate Workbook) priced from YOUR cost
books, written to a NEW file.

  * Only a QuantiSheet Estimate Workbook is read: its BASE BID sheet's
    header row must be estimate_book.HEAD; anything else is refused.
  * The lines are matched as Match Rates matches takeoff groups (saved
    match, then the same description + a unit that converts; a loose
    description match is shown but never ticked) - the workbook has no
    cost codes.
  * For each ticked line only the rate cells are filled - H labor hours
    per unit, I wages, L material rate, N equipment rate - converted to
    the line's unit, and the source goes in NOTES. A line whose rate
    cells already hold something is left as it is; an item with a
    subcontract cost is left out (the workbook has no sub rate column).
    Formulas, waste and markups are not touched.
  * The result is '<name> - priced.xlsx' next to the original ('(2)',
    '(3)' ... when that exists): the original is never changed or
    overwritten, and nothing is written inside the program folder.

    read_workbook(path) -> [{row, desc, qty, unit, note}]
    match(lines, books, mapping=None, job=None) -> like boq.match
    write_priced(path, rows, dest=None) -> {path, filled, skipped}
"""
import os
from decimal import Decimal

from .. import estimate_book
from . import _io, boq

SHEET = "BASE BID"
HEAD_ROW = 10
COL = {"desc": 3, "qty": 4, "unit": 5, "hours": 8, "wages": 9, "mat": 12,
       "eqp": 14, "notes": 18}


class WorkbookError(ValueError):
    """Not a workbook this can price."""


def _open(path, **kw):
    import openpyxl
    try:
        return openpyxl.load_workbook(path, **kw)
    except Exception as e:                                # noqa: BLE001
        raise WorkbookError(f"{os.path.basename(path)} can't be opened as "
                            f"an Excel workbook: {e}") from e


def _check(wb, path):
    name = os.path.basename(path)
    if SHEET not in wb.sheetnames:
        raise WorkbookError(f"{name} has no {SHEET} sheet - only an "
                            "Estimate Workbook made by QuantiSheet can be "
                            "priced.")
    ws = wb[SHEET]
    got = [ws.cell(HEAD_ROW, i + 1).value or "" for i in
           range(len(estimate_book.HEAD))]
    if [str(x).strip() for x in got] != estimate_book.HEAD:
        raise WorkbookError(f"{name}: the {SHEET} header row is not "
                            "QuantiSheet's Estimate Workbook layout - "
                            "nothing was changed.")
    return ws


def _lines(ws):
    out = []
    for r in range(estimate_book.FIRST_ROW, ws.max_row + 1):
        a = ws.cell(r, 1).value
        if isinstance(a, str) and a.strip().upper() == "PROJECTED COST":
            break
        desc = ws.cell(r, COL["desc"]).value
        if not isinstance(a, (int, float)) or not desc:
            continue
        q = ws.cell(r, COL["qty"]).value
        out.append({"row": r, "desc": str(desc),
                    "qty": q if isinstance(q, (int, float)) else None,
                    "unit": str(ws.cell(r, COL["unit"]).value or ""),
                    "note": str(ws.cell(r, COL["notes"]).value or ""),
                    "filled": [k for k in ("hours", "wages", "mat", "eqp")
                               if ws.cell(r, COL[k]).value not in
                               (None, "")]})
    return out


def read_workbook(path):
    wb = _open(path, read_only=False)
    try:
        return _lines(_check(wb, path))
    finally:
        wb.close()


def match(lines, books, mapping=None, job=None):
    """The workbook lines matched to your cost book items (boq rows)."""
    saved = (mapping or {}).get("matches") or {}
    items = list(boq._items(books))
    by_desc = {}
    for bname, code, it in items:
        by_desc.setdefault(boq._norm(it.get("desc")), []).append(
            (bname, code, it))
    rows = []
    for ln in lines:
        q = Decimal(str(ln["qty"])) if ln["qty"] is not None else Decimal(0)
        t = {"id": f"row:{ln['row']}", "row": ln["row"], "name": ln["desc"],
             "type": "", "unit": ln["unit"], "qty": q, "adjusted": q,
             "waste": 0, "multiplier": 1, "code": "",
             "filled": ln["filled"], "note": ln["note"]}
        rows.append(boq._match_one(None, t, books, saved, {}, by_desc, items,
                                   job))
    counts = {k: sum(1 for r in rows if r["status"] == k)
              for k in ("exact", "fuzzy", "none")}
    return {"rows": rows, "counts": counts, "already_priced": 0}


def _dest(path):
    stem, _ = os.path.splitext(path)
    p = f"{stem} - priced.xlsx"
    n = 2
    while os.path.exists(p):
        p = f"{stem} - priced ({n}).xlsx"
        n += 1
    return p


def _num(d):
    return float(Decimal(d).quantize(Decimal("0.0001")))


def write_priced(path, rows, dest=None):
    """Fill the ticked lines' rate cells into a new copy (see the module).
    Returns {"path", "filled", "skipped": [{name, why}]}."""
    dest = dest or _dest(path)
    p = _io.check_user_path(dest, (".xlsx",))
    if os.path.exists(p) or os.path.abspath(p) == os.path.abspath(path):
        raise _io.PathError(f"{os.path.basename(p)} is there already; "
                            "QuantiSheet never overwrites a workbook.")
    wb = _open(path)
    ws = _check(wb, path)
    filled, skipped = 0, []
    for r in rows:
        t = r["target"]
        if not r["ticked"]:
            continue
        if r["item"] is None or r.get("factor") is None:
            skipped.append({"name": t["name"], "why": r["reason"] or
                            "no item"})
            continue
        if t.get("filled"):
            skipped.append({"name": t["name"], "why": "its rate cells "
                            "already hold a value - left as typed"})
            continue
        it, f = r["item"], r["factor"]
        if it["parts"]["sub"]:
            skipped.append({"name": t["name"], "why": f"{it['source']} has "
                            "a subcontract cost; the workbook has no sub "
                            "rate column"})
            continue
        row = t["row"]
        hrs = Decimal(str(it["hours"] or 0))
        if hrs and it["parts"]["lab"]:
            ws.cell(row, COL["hours"], _num(hrs * f))
            ws.cell(row, COL["wages"], _num(it["parts"]["lab"] / hrs))
        if it["parts"]["mat"]:
            ws.cell(row, COL["mat"], _num(it["parts"]["mat"] * f))
        if it["parts"]["eqp"]:
            ws.cell(row, COL["eqp"], _num(it["parts"]["eqp"] * f))
        src = f"Priced from {it['source']} ({r['how']})"
        old = str(ws.cell(row, COL["notes"]).value or "")
        ws.cell(row, COL["notes"],
                estimate_book._safe((old + " | " if old else "") + src))
        filled += 1
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    tmp = p + ".part"
    try:
        wb.save(tmp)
        if os.path.exists(p):
            raise _io.PathError(f"{os.path.basename(p)} appeared while "
                                "saving; nothing was overwritten.")
        os.replace(tmp, p)
    finally:
        wb.close()
        if os.path.exists(tmp):
            os.remove(tmp)
    return {"path": p, "filled": filled, "skipped": skipped}
