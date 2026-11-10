"""Cost rollup and bid summary for the HeavyBid-coded assemblies (v29).

Extended cost by trade (labor / material / equipment), sales tax on the
MATERIAL components only (computed from the components, never an assumed
share of the total), then a markup cascade the user edits and orders
(default order GC, overhead, profit, bond, insurance, contingency,
escalation; every rate starts at 0 - nothing is assumed), each step
compounded on the running subtotal. Cost per SF only from a building SF the
user entered. Decimal throughout; each amount rounded to cents (half up).

bidbuild.py (the proposal cascade with graduated bond and trade margins)
stays the proposal engine; this is the summary for code-based lines and the
v30 change report. Lines come from assembly_codes.priced_lines().
"""
import csv
from decimal import Decimal

from . import safecell
from .assembly_codes import cents, dec
from .dmoney import c2 as _c2

DEFAULT_CASCADE = [("gc", "0"), ("overhead", "0"), ("profit", "0"),
                   ("bond", "0"), ("insurance", "0"), ("contingency", "0"),
                   ("escalation", "0")]
LABELS = {"gc": "General conditions", "overhead": "Overhead",
          "profit": "Profit", "bond": "Bond", "insurance": "Insurance",
          "contingency": "Contingency", "escalation": "Escalation"}
Z = Decimal("0.00")


def by_trade(lines):
    out = {}
    for ln in lines:
        t = out.setdefault(ln.get("trade") or "(no trade)",
                           {"L": Z, "M": Z, "E": Z, "total": Z})
        for k in ("L", "M", "E", "total"):
            t[k] += dec(ln.get(k), Z)
    return out


def summary(lines, cascade=None, tax_pct=0, building_sf=None):
    cascade = DEFAULT_CASCADE if cascade is None else cascade
    trades = by_trade(lines)
    direct = sum((t["total"] for t in trades.values()), Z)
    material = sum((t["M"] for t in trades.values()), Z)
    tax = cents(material * dec(tax_pct, Z) / 100)
    running = direct + tax
    steps = []
    for key, pct in cascade:
        p = dec(pct, Z)
        amt = cents(running * p / 100)
        running += amt
        steps.append({"key": key, "label": LABELS.get(key, key.title()),
                      "pct": p, "amount": amt, "subtotal": running})
    sf = dec(building_sf, None)
    per = cents(running / sf) if sf and sf > 0 else None
    return {"trades": trades, "direct": direct, "material": material,
            "tax_pct": dec(tax_pct, Z), "tax": tax, "steps": steps,
            "total": running, "building_sf": sf, "per_sf": per,
            "per_sf_text": f"{per}" if per is not None else "enter building SF"}


def table(r):
    rows = [["Section", "Item", "Labor", "Material", "Equipment", "Amount"]]
    for t, v in sorted(r["trades"].items()):
        rows.append(["Trade", t, v["L"], v["M"], v["E"], v["total"]])
    rows.append(["Summary", "Direct cost", "", "", "", r["direct"]])
    rows.append(["Summary", f"Sales tax on material ({r['tax_pct']}%)", "",
                 r["material"], "", r["tax"]])
    for s in r["steps"]:
        rows.append(["Markup", f"{s['label']} ({s['pct']}%)", "", "", "",
                     s["amount"]])
    rows.append(["Summary", "Total", "", "", "", r["total"]])
    rows.append(["Summary", "Building SF", "", "", "",
                 r["building_sf"] if r["building_sf"] else ""])
    rows.append(["Summary", "Cost per SF", "", "", "",
                 r["per_sf"] if r["per_sf"] is not None else r["per_sf_text"]])
    return rows


def export(path, r):
    rows = table(r)
    if path.lower().endswith(".xlsx"):
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Bid Summary"
        for row in rows:
            safecell.append_row(ws, [float(v) if isinstance(v, Decimal)
                                     else v for v in row])
        for row in ws.iter_rows(min_row=2):
            for c in row[2:]:
                if isinstance(c.value, float):
                    c.number_format = "0.00"
        wb.save(path)
    else:
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = safecell.writer(f, lineterminator="\r\n")
            for row in rows:
                w.writerow([f"{_c2(v):.2f}" if isinstance(v, Decimal) and
                            v == v.quantize(Decimal("0.01")) else v
                            for v in row])
    return path
