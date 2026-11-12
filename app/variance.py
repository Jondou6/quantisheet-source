"""Line-by-line variance against our own estimate (Nov 11).

For each scope row: our number, each bidder's number, and the difference
in dollars and percent, with rows far above or below ours flagged. Scope
we carry that a bidder didn't price or excluded is listed per bidder with
our dollar value - the same dollars the Leveling Board and Scope Sheets
plug.

All money is whole cents (integers), so the rows add up to the total
exactly:

    leveled total - our total
        = sum of the row differences
        + what the bidder priced on rows we have no estimate for
        - our value of rows the bidder says are included elsewhere

A blank is not $0.00: a row a bidder left blank is missing scope (plugged
at our number, difference 0, listed); a row priced at $0.00 is a price
(difference: minus our whole number). A row we have no number for shows
"no estimate", never 0%.

Pure Python, no Qt.
"""
from decimal import ROUND_HALF_UP, Decimal

PRICED, MISSING, INCLUDED, NA = "priced", "missing", "included", "na"
HIGH, LOW = "high", "low"
DEFAULT_PCT = 15.0
SETTING = "variance_pct"


def threshold():
    """The +/- percent that counts as high or low (a setting)."""
    from . import settings
    try:
        v = float(settings.get(SETTING, DEFAULT_PCT))
    except (TypeError, ValueError):
        return DEFAULT_PCT
    return v if 0 < v <= 1000 else DEFAULT_PCT


def set_threshold(pct):
    from . import settings
    v = float(pct)
    if not 0 < v <= 1000:
        raise ValueError("The percent must be more than 0.")
    settings.set(SETTING, v)
    return v


def cents(v):
    """Decimal / str dollars -> whole cents, half up (None stays None)."""
    if v is None or v == "":
        return None
    return int((Decimal(str(v)) * 100).quantize(Decimal("1"),
                                                rounding=ROUND_HALF_UP))


def pct_of(var, ours):
    """Percent of our number to one decimal, half up; None when ours is
    0 or unknown."""
    if not ours:
        return None
    return float((Decimal(var) * 100 / Decimal(ours)).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP))


def compare(rows, bidders, pct=None):
    """`rows`: [{"id", "desc", "ours": cents or None, "cells": {bidder:
    (state, cents or None)}}]; states: PRICED (their amount), MISSING
    (blank or excluded), INCLUDED (they say it is in another line), NA
    (the bidder gave one price, no breakdown). Returns {"pct", "rows",
    "bidders", "ours"}; see the module text for how it adds up."""
    pct = threshold() if pct is None else float(pct)
    out_rows = []
    tot = {b: {"name": b, "priced": 0, "missing": 0, "missing_rows": [],
               "unplugged": [], "no_estimate": 0, "included": 0,
               "var_rows": 0, "breakdown": False, "high": 0, "low": 0}
           for b in bidders}
    ours_total = 0
    for r in rows:
        ours = r.get("ours")
        if ours is not None:
            ours_total += ours
        cells = {}
        for b in bidders:
            state, amt = (r.get("cells") or {}).get(b) or (NA, None)
            t = tot[b]
            c = {"state": state, "amount": None, "var": None, "pct": None,
                 "flag": ""}
            if state == PRICED and amt is not None:
                t["breakdown"] = True
                t["priced"] += amt
                c["amount"] = amt
                if ours is None:
                    t["no_estimate"] += amt
                else:
                    c["var"] = amt - ours
                    c["pct"] = pct_of(c["var"], ours)
                    t["var_rows"] += c["var"]
                    if c["pct"] is not None and c["pct"] >= pct:
                        c["flag"] = HIGH
                        t["high"] += 1
                    elif c["pct"] is not None and c["pct"] <= -pct:
                        c["flag"] = LOW
                        t["low"] += 1
            elif state == MISSING:
                t["breakdown"] = True
                if ours is None:
                    t["unplugged"].append(r.get("desc") or "")
                else:
                    c["amount"] = ours           # plugged at our number
                    c["var"] = 0
                    t["missing"] += ours
                    t["missing_rows"].append((r.get("desc") or "", ours))
            elif state == INCLUDED:
                t["breakdown"] = True
                if ours is not None:
                    t["included"] += ours
            cells[b] = c
        out_rows.append({"id": r.get("id"), "desc": r.get("desc") or "",
                         "ours": ours, "cells": cells})
    for t in tot.values():
        if not t["breakdown"]:         # one price, no lines to compare
            t.update(leveled=None, var_total=None, pct_total=None)
            continue
        t["leveled"] = t["priced"] + t["missing"]
        t["var_total"] = t["leveled"] - ours_total
        # the identity the report prints; a failure here is a bug
        if t["var_total"] != t["var_rows"] + t["no_estimate"] - \
                t["included"]:
            raise ArithmeticError(f"variance does not add up: {t}")
        t["pct_total"] = pct_of(t["var_total"], ours_total)
    return {"pct": pct, "rows": out_rows, "ours": ours_total,
            "bidders": [tot[b] for b in bidders]}


# ---------------------------------------------------------------- sources
def from_board(board):
    """(rows, bidders) from estimating.levelboard.board(): our number is
    the plug (takeoff quantity x our unit price); a red cell is missing
    scope."""
    names = [b["name"] for b in board["bidders"]]
    rows = []
    for r in board["rows"]:
        cells = {}
        for n in names:
            c = r["cells"][n]
            cells[n] = (MISSING, None) if c["plugged"] else \
                (PRICED, cents(c["amount"]))
        rows.append({"id": r["id"], "desc": r["desc"],
                     "ours": cents(r["plug"]), "cells": cells})
    return rows, names


def from_scope_sheet(sheet):
    """(rows, bidders) from a Scope Sheet: our number is the budget line
    (Qty x Unit $ or the lump sum); a line flagged N or left blank by a
    bidder who broke the bid down is missing scope; flagged Y with no
    amount is included elsewhere."""
    from .pm import scope_sheet as ss
    live = [(i, b) for i, b in enumerate(sheet["bidders"])
            if ss.active(sheet, b)]
    names = [ss.bidder_name(sheet, b, i) for i, b in live]
    rows = []
    for ln in sheet["lines"]:
        cells = {}
        for (i, b), n in zip(live, names):
            if not ss.has_breakdown(sheet, b):
                cells[n] = (NA, None)
                continue
            c = ss.bid_cell(ln, b["id"])
            if c["amount"] is not None:
                cells[n] = (PRICED, int(c["amount"]))
            elif ss.excluded(sheet, ln, b):
                cells[n] = (MISSING, None)
            else:
                cells[n] = (INCLUDED, None)
        rows.append({"id": ln["id"], "desc": ln.get("desc") or "",
                     "ours": ss.budget_line_total(ln), "cells": cells})
    return rows, names


# ----------------------------------------------------------------- report
def money(c):
    if c is None:
        return ""
    s = f"{abs(c) // 100:,}.{abs(c) % 100:02d}"
    return f"(${s})" if c < 0 else f"${s}"


def signed(c):
    if c is None:
        return ""
    s = f"{abs(c) // 100:,}.{abs(c) % 100:02d}"
    return ("-$" if c < 0 else "+$") + s if c else "$0.00"


def pct_text(p):
    return "" if p is None else "0.0%" if p == 0 else f"{p:+.1f}%"


def cell_text(row, c):
    """(their number, difference, note) as text for one cell."""
    if c["state"] == NA:
        return "", "", "no breakdown"
    if c["state"] == INCLUDED:
        return "", "", "included elsewhere"
    if c["state"] == MISSING:
        if row["ours"] is None:
            return "", "", "missing scope - no estimate to plug"
        return money(c["amount"]), "", "MISSING SCOPE - plugged at ours"
    if row["ours"] is None:
        return money(c["amount"]), "", "no estimate"
    note = {HIGH: "HIGH", LOW: "LOW"}.get(c["flag"], "")
    return money(c["amount"]), \
        f"{signed(c['var'])} ({pct_text(c['pct']) or 'n/a'})", note


def tables(res, title=""):
    """[(name, rows)] for a report: Variance (one line per scope row),
    Missing Scope (per bidder), Totals (how it adds up)."""
    names = [b["name"] for b in res["bidders"]]
    head = ["Scope row", "Our number"]
    for n in names:
        head += [n, "Difference", "Note"]
    var = [head]
    for r in res["rows"]:
        line = [r["desc"], money(r["ours"]) if r["ours"] is not None
                else "no estimate"]
        for n in names:
            line += list(cell_text(r, r["cells"][n]))
        var.append(line)
    miss = [["Bidder", "Scope we carry that they didn't price",
             "Our value"]]
    for b in res["bidders"]:
        for desc, v in b["missing_rows"]:
            miss.append([b["name"], desc, money(v)])
        for desc in b["unplugged"]:
            miss.append([b["name"], desc, "no estimate"])
        if b["missing_rows"]:
            miss.append([b["name"], "Total missing scope",
                         money(b["missing"])])
    tot = [["Bidder", "Priced", "Missing scope (plugged at ours)",
            "Leveled total", "Our total", "Difference", "%",
            "Sum of row differences", "Priced on rows with no estimate",
            "Our value of rows included elsewhere", f"Rows +{res['pct']:g}%"
            " or more", f"Rows -{res['pct']:g}% or less"]]
    for b in res["bidders"]:
        if not b["breakdown"]:
            tot.append([b["name"], "no breakdown"] + [""] * 10)
            continue
        tot.append([b["name"], money(b["priced"]), money(b["missing"]),
                    money(b["leveled"]), money(res["ours"]),
                    signed(b["var_total"]), pct_text(b["pct_total"]),
                    signed(b["var_rows"]), money(b["no_estimate"]),
                    money(b["included"]), b["high"], b["low"]])
    return [("Variance", var), ("Missing Scope", miss), ("Totals", tot)]


def export_xlsx(res, path, title=""):
    from . import acrobat
    acrobat.write_xlsx(path, tables(res, title))
    return path


def export_pdf(res, path, title="", company=""):
    """The same three tables as a landscape PDF."""
    from . import forms
    f = forms.Form("Variance Against Our Estimate", title, landscape=True,
                   company=company)
    f.para(f"Rows {res['pct']:g}% or more above or below our number are "
           "marked HIGH or LOW. Missing scope is plugged at our number. A "
           "blank is not $0.00.")
    for name, rows in tables(res, title):
        if len(rows) < 2:
            continue
        f.heading(name)
        n = len(rows[0])
        first = 2.2 if n > 4 else 1.6
        unit = 1.0 / (first + n - 1)
        widths = [first * unit] + [unit] * (n - 1)
        f.table(rows[0], [[str(v) for v in r] for r in rows[1:]], widths,
                size=6.5 if n > 8 else 7.5)
    return f.save(path)
