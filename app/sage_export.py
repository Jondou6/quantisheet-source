"""Sage 300 CRE (Timberline) Job Cost budget export.

One row per Job / Extra / Cost Code / Category, the shape Job Cost's
budget import reads: Job, Extra, Cost Code, Category, Description,
Units, Unit of Measure, Amount.

Lines are estimate lines. Two shapes are read:
  * coded lines (assembly_codes.priced_lines): "code", "desc", "unit",
    "qty" and the L / M / E split - one row per category with money;
  * plain lines (estimate.lines, or anything else): "name" or "desc",
    "quantity" / "adjusted" or "qty", "unit", "total", with the cost
    code in "cost_code" (or "csi" / "code") and the category in
    "category" (or "cost_type").

A line that cannot go in as it is - no cost code, no category, a zero,
negative or non-number quantity or amount, unpriced components - is
returned in the problems list with the reason, never exported. Rows
with the same cost code, category and unit are added together, since
Sage keeps one budget per code and category.
"""
import csv
from decimal import Decimal

from . import csi
from .assembly_codes import cents, dec

HEADERS = ["Job", "Extra", "Cost Code", "Category", "Description",
           "Units", "Unit of Measure", "Amount"]
# CSI "03 30 00" -> "03-3000"; tokens {div} {a} {b} {ext}
CODE_FORMAT = "{div}-{a}{b}"
CATEGORIES = {
    "l": "L", "labor": "L", "labour": "L",
    "m": "M", "material": "M", "materials": "M",
    "s": "S", "sub": "S", "subcontract": "S", "subcontractor": "S",
    "e": "E", "eq": "E", "equipment": "E", "equipment rental": "E",
    "o": "O", "other": "O", "x": "O", "overhead": "O",
    "overhead and profit": "O",
}
UNIT_PLACES = Decimal("0.0001")


def category(v):
    """Sage category letter for "Labor", "Subcontract", "EQ"...; "" when
    it isn't one."""
    t = " ".join(str(v or "").lower().split())
    if not t:
        return ""
    if t in CATEGORIES:
        return CATEGORIES[t]
    name = csi.COST_TYPES.get(t.upper(), "")
    return CATEGORIES.get(name.lower(), "")


def cost_code(v, fmt=CODE_FORMAT):
    """A CSI number in the Sage cost code format, or "" if it isn't
    one."""
    p = csi.parse_code(v)
    if not p:
        return ""
    sec, _, ext = p.partition(".")
    div, a, b = sec.split()
    out = fmt
    for k, val in (("div", div), ("a", a), ("b", b), ("ext", ext)):
        out = out.replace("{" + k + "}", val)
    return out


def _number(v):
    """Decimal, or None when blank, not a number or not finite."""
    try:
        d = dec(v)
    except (ValueError, TypeError):
        return None
    if d is None or not d.is_finite():
        return None
    return d


def _code_of(ln, phase_from, fmt):
    if phase_from == "code":
        raw = ln.get("cost_code") or ln.get("code") or ""
        return " ".join(str(raw).split())
    for k in ("cost_code", "csi", "code"):
        c = cost_code(ln.get(k), fmt)
        if c:
            return c
    return ""


def _qty_of(ln):
    for k in ("adjusted", "quantity", "qty"):
        if ln.get(k) not in (None, ""):
            return ln.get(k)
    return None


def _desc_of(ln):
    return " ".join(str(ln.get("desc") or ln.get("name") or
                        ln.get("group") or "").split())


def _split(ln, default_category):
    """[(category, amount)] for a line: the L / M / E split when it has
    one, else its total under its own (or the default) category."""
    if any(k in ln for k in ("L", "M", "E")) and not (
            ln.get("category") or ln.get("cost_type")):
        out = []
        for k in ("L", "M", "E"):
            a = _number(ln.get(k))
            if a is None and ln.get(k) not in (None, ""):
                return None, f"{k} amount is not a number"
            if a:
                out.append((k, a))
        return out, ""
    cat = category(ln.get("category") or ln.get("cost_type") or
                   default_category)
    if not cat:
        got = ln.get("category") or ln.get("cost_type")
        return None, (f"unknown cost category {got!r}" if got else
                      "no cost category")
    a = _number(ln.get("total"))
    if a is None:
        return None, "amount is blank or not a number"
    return [(cat, a)], ""


def job_cost_rows(lines, job="", phase_from="csi", code_format=CODE_FORMAT,
                  default_category=""):
    """(rows, problems). rows are dicts keyed by HEADERS; problems are
    {"line": n, "description": ..., "reason": ...} (n counts from 1).

    phase_from "csi" reads the cost code as a CSI number and writes it in
    code_format; "code" passes the line's code through as it is."""
    if phase_from not in ("csi", "code"):
        raise ValueError(f"phase_from must be 'csi' or 'code', "
                         f"not {phase_from!r}")
    job = " ".join(str(job or "").split())
    merged, order, problems = {}, [], []
    for n, ln in enumerate(lines, 1):
        desc = _desc_of(ln)

        def bad(reason):
            problems.append({"line": n, "description": desc,
                             "reason": reason})
        code = _code_of(ln, phase_from, code_format)
        if not code:
            bad("no cost code" if phase_from == "code" else
                "no CSI cost code")
            continue
        qty = _number(_qty_of(ln))
        if qty is None:
            bad("quantity is blank or not a number")
            continue
        if qty <= 0:
            bad(f"quantity is {qty}")
            continue
        if ln.get("unpriced"):
            bad("unpriced components: " + ", ".join(
                str(u) for u in ln["unpriced"]))
            continue
        parts, why = _split(ln, default_category)
        if parts is None:
            bad(why)
            continue
        if not parts:
            bad("amount is 0")
            continue
        neg = [(c, a) for c, a in parts if a <= 0]
        if neg:
            bad(f"{neg[0][0]} amount is {neg[0][1]}")
            continue
        unit = " ".join(str(ln.get("unit") or "").split())
        for cat, amt in parts:
            k = (code, cat, unit.lower())
            if k not in merged:
                merged[k] = {"Job": job, "Extra": "", "Cost Code": code,
                             "Category": cat, "Description": desc,
                             "Units": Decimal(0), "Unit of Measure": unit,
                             "Amount": Decimal(0)}
                order.append(k)
            merged[k]["Units"] += qty
            merged[k]["Amount"] += cents(amt)
    units = {}
    for k in order:
        units.setdefault(k[:2], []).append(k)
    rows = []
    for (code, cat), keys in units.items():
        if len(keys) > 1:
            got = ", ".join(repr(merged[k]["Unit of Measure"]) for k in keys)
            problems.append({"line": None,
                             "description": merged[keys[0]]["Description"],
                             "reason": f"cost code {code} category {cat} "
                                       f"has more than one unit ({got})"})
            continue
        r = merged[keys[0]]
        rows.append(dict(r, Units=r["Units"].quantize(UNIT_PLACES),
                         Amount=cents(r["Amount"])))
    rows.sort(key=lambda r: (r["Cost Code"], r["Category"]))
    return rows, problems


def _cell(h, v):
    if isinstance(v, Decimal):
        if h == "Amount":
            return f"{v:.2f}"
        t = f"{v:f}"
        return t.rstrip("0").rstrip(".") if "." in t else t
    return _no_formula("" if v is None else str(v))


def _no_formula(t):
    """Text a spreadsheet would run as a formula (=, +, -, @ first) loses
    those leading characters: Sage's import wants the plain text, not an
    apostrophe. Numbers ("-312.47") are left alone."""
    from . import safecell
    while safecell.risky(t):
        t = t.lstrip("".join(safecell.FORMULA_START)).lstrip()
    return t


def export_csv(path, rows):
    """rows from job_cost_rows -> a CSV for Sage's import (UTF-8 with a
    BOM, Windows line ends)."""
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, lineterminator="\r\n")
        w.writerow(HEADERS)
        for r in rows:
            w.writerow([_cell(h, r.get(h)) for h in HEADERS])
    return path



# ---- check before export, and a reversal (review QS-029, Nov 4) -----------------

def preview(rows, problems):
    """Plain summary of what an export would write."""
    from decimal import Decimal
    total = Decimal("0")
    for r in rows:
        try:
            total += Decimal(str(r.get("Amount") or 0))
        except Exception:                                 # noqa: BLE001
            pass
    jobs = sorted({str(r.get("Job") or "") for r in rows})
    return {"lines": len(rows), "total": total, "jobs": jobs,
            "left_out": len(problems)}


def reversal(rows):
    """The same budget lines with amounts and units negated: importing it
    backs out an import that went to the wrong job or twice."""
    out = []
    for r in rows:
        x = dict(r)
        for k in ("Amount", "Units"):
            v = x.get(k)
            if v in (None, ""):
                continue
            try:
                from decimal import Decimal
                d = Decimal(str(v))
                x[k] = str(-d) if d else str(d)
            except Exception:                             # noqa: BLE001
                pass
        out.append(x)
    return out
