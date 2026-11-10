"""Leveling Board and Trade Scope Sheet Builder (Nov 3, Jon approved
Chief's list, #5 and #7).

Trade scope sheets (#7): for one trade (a CSI division), the checklist a
bid invitation goes out with - each takeoff item of that trade (with its
quantity) plus the "Section Includes" / Part 2-3 items of that trade's
spec sections. The same rows become the leveling board's scope.

Leveling Board (#5), on the bid-day package (bidday.py) - one place to:
  * drop in sub quote PDFs (proposal_level.parse): each quote line is
    matched to a scope row by its description; a close match is a price,
    a loose one is a price marked unclear, exclusions that name a row are
    gaps;
  * see every cell as green (confirmed), yellow (unclear) or red (a gap:
    excluded or not quoted);
  * plug each gap from our own takeoff: the row's quantity x our unit
    price for that item (estimate panel), else the row's typed plug;
  * put the leveled low number into the estimate (bidday.apply_quote).
"""
import difflib
import re
from decimal import Decimal

from . import bidday
from ..dmoney import c2 as _c2

GREEN, YELLOW, RED = "confirmed", "unclear", "gap"
MATCH = 0.80                # description match this close: a price
LOOSE = 0.60                # this close: a price marked unclear
SPEC_ITEMS = 15             # spec lines per section on a scope sheet

_ARTICLE = re.compile(r"^\s*(\d\.\d{1,2})\s+(SECTION INCLUDES|SUMMARY|"
                      r"WORK INCLUDED|SCOPE)\b", re.I)
_PART = re.compile(r"^\s*PART\s+([1-3])\b", re.I)
_ITEM = re.compile(r"^\s*([A-Z]|\d{1,2})\.\s+(.{4,160})$")


def _norm(t):
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", str(t or "").lower())
                    .split())


def similar(a, b):
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 0.9
    return difflib.SequenceMatcher(None, a, b).ratio()


# ---- trade scope sheets (#7) ----------------------------------------------------

def trades(doc):
    """{division "09": [takeoff groups of that trade]} from the estimate
    panel's coded groups (uncoded groups under "")."""
    from .. import csi, estimate
    out = {}
    for g in estimate.lines(doc):
        code = csi.parse_code(g.get("code") or "")
        out.setdefault(code[:2] if code else "", []).append(g)
    return out


def spec_items(spec_doc, division, sections=None):
    """The work items listed in the spec sections of one division:
    [{"section", "title", "text"}] (the Section Includes / Summary
    articles first, then Part 2 product items), at most SPEC_ITEMS a
    section."""
    from .. import specs
    if spec_doc is None:
        return []
    secs = sections if sections is not None else specs.find_sections(
        spec_doc)
    out = []
    for s in secs:
        if s.get("division") != division:
            continue
        got, part, inc = [], None, False
        for pno in range(s["start"], min(s["end"], s["start"] + 6) + 1):
            for line in spec_doc[pno].get_text("text").splitlines():
                m = _PART.match(line)
                if m:
                    part = m.group(1)
                    inc = False
                    continue
                if _ARTICLE.match(line):
                    inc = True
                    continue
                if re.match(r"^\s*\d\.\d{1,2}\s+\S", line):
                    inc = False                    # the next article
                    continue
                m = _ITEM.match(line)
                if m and (inc or part == "2"):
                    t = " ".join(m.group(2).split()).rstrip(".")
                    if t and t not in got:
                        got.append(t)
                if len(got) >= SPEC_ITEMS:
                    break
            if len(got) >= SPEC_ITEMS:
                break
        out += [{"section": s["number"], "title": s["title"], "text": t}
                for t in got]
    return out


def scope_sheet(doc, division, spec_doc=None, sections=None):
    """One trade's scope checklist: [{"id", "desc", "unit", "qty",
    "group", "source"}] - takeoff items first, then spec items (no
    quantity) not already covered by a takeoff item."""
    from .. import csi
    rows = []
    for g in trades(doc).get(division, []):
        q = Decimal(str(round(float(g.get("quantity") or 0), 4)))
        rows.append({"desc": g["name"], "unit": g.get("unit", ""),
                     "qty": f"{q.normalize():f}",
                     "group": {"name": g["name"], "type": g.get("type", ""),
                               "unit": g.get("unit", "")},
                     "source": "takeoff"})
    for it in spec_items(spec_doc, division, sections):
        if any(similar(it["text"], r["desc"]) >= MATCH for r in rows):
            continue
        rows.append({"desc": it["text"], "unit": "ls", "qty": "",
                     "source": f"spec {it['section']}"})
    for i, r in enumerate(rows, 1):
        r["id"] = str(i)
    title = csi.DIVISIONS.get(division, "Unclassified") if division else \
        "Uncoded items"
    return {"division": division, "trade": title, "rows": rows}


def scope_csv(sheet, path):
    import csv
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([f"Scope - {sheet['trade']}"])
        w.writerow(["#", "Item", "Qty", "Unit", "From", "Included? (Y/N)",
                    "Price"])
        for r in sheet["rows"]:
            w.writerow([r["id"], r["desc"], r["qty"], r["unit"],
                        r["source"], "", ""])
    return path


def start_board(doc, sheet, package=None):
    """A bid-day package (the board) from a trade scope sheet."""
    package = package or sheet["trade"]
    scope = [{"id": r["id"], "desc": r["desc"], "unit": r["unit"] or "ls",
              "qty": r["qty"], "group": r.get("group")}
             for r in sheet["rows"]]
    have = bidday.load(doc, package)
    bidders = (have or {}).get("bidders") or []
    bidday.save(doc, bidday.new_sheet(package, scope, bidders))
    return package


# ---- our own price for a row ------------------------------------------------------

def our_prices(doc):
    """{group name: unit cost (Decimal)} from the estimate panel."""
    from .. import estimate
    out = {}
    for g in estimate.lines(doc):
        try:
            uc = Decimal(str(g.get("unit_cost") or 0))
        except Exception:                                 # noqa: BLE001
            uc = Decimal(0)
        if uc:
            out[g["name"]] = uc
    return out


def our_plug(row, prices):
    """Quantity x our unit price for a scope row (None = no price)."""
    g = row.get("group") or {}
    uc = prices.get(g.get("name") or row.get("desc"))
    try:
        q = Decimal(str(row.get("qty") or 0))
    except Exception:                                     # noqa: BLE001
        q = Decimal(0)
    if uc and q:
        return (uc * q).quantize(Decimal("0.01"))
    return None


# ---- the board ------------------------------------------------------------------

def board(doc, package):
    """{"package", "rows": [{"id", "desc", "unit", "qty", "plug",
    "cells": {bidder: {"status", "amount", "plugged"}}}], "bidders":
    [{"name", "quoted", "plugs", "gaps", "unclear", "total"}], "low"}."""
    sheet = bidday.load(doc, package)
    if sheet is None:
        raise bidday.BidDayError(f"No package named {package!r}.")
    prices = our_prices(doc)
    rows, tot = [], {}
    for b in sheet["bidders"]:
        tot[b["name"]] = {"name": b["name"], "quoted": Decimal("0.00"),
                          "plugs": Decimal("0.00"), "gaps": 0, "unclear": 0,
                          "unpluggable": 0, "valid_until":
                          b.get("valid_until", "")}
    for s in sheet["scope"]:
        plug = our_plug(s, prices)
        if plug is None and s.get("plug"):
            plug = Decimal(str(s["plug"])).quantize(Decimal("0.01"))
        cells = {}
        for b in sheet["bidders"]:
            t = tot[b["name"]]
            price = None if s["id"] in b.get("excluded", []) else \
                bidday._amount(b["prices"].get(s["id"]), b["name"])
            if price is None:
                cells[b["name"]] = {"status": RED, "amount": plug,
                                    "plugged": True}
                t["gaps"] += 1
                if plug is None:
                    t["unpluggable"] += 1
                else:
                    t["plugs"] += plug
                continue
            st = YELLOW if s["id"] in b.get("unclear", []) else GREEN
            if st == YELLOW:
                t["unclear"] += 1
            cells[b["name"]] = {"status": st, "amount": price,
                                "plugged": False}
            t["quoted"] += price
        rows.append({"id": s["id"], "desc": s["desc"], "unit": s["unit"],
                     "qty": s["qty"], "plug": plug, "cells": cells})
    bidders = []
    for b in sheet["bidders"]:
        t = tot[b["name"]]
        t["total"] = t["quoted"] + t["plugs"]
        bidders.append(t)
    ok = [t for t in bidders if not t["unpluggable"]]
    low = min(ok, key=lambda t: t["total"])["name"] if ok else ""
    return {"package": package, "rows": rows, "bidders": bidders,
            "low": low}


def import_quote(doc, package, path=None, parsed=None):
    """Add (or replace) a sub's quote from its PDF. Returns
    {"bidder", "matched", "unclear", "excluded", "unmatched"}."""
    from .. import proposal_level
    sheet = bidday.load(doc, package)
    if sheet is None:
        raise bidday.BidDayError(f"No package named {package!r}.")
    p = parsed or proposal_level.parse(path)
    prices, unclear, matched, unmatched = {}, [], [], []
    for ln in p.get("lines") or []:
        best, score = None, 0.0
        for s in sheet["scope"]:
            if s["id"] in prices:
                continue
            sc = similar(ln["desc"], s["desc"])
            if sc > score:
                best, score = s, sc
        if best is None or score < LOOSE:
            unmatched.append(ln["desc"])
            continue
        prices[best["id"]] = f"{_c2(Decimal(str(ln['amount']))):.2f}"
        (matched if score >= MATCH else unclear).append(best["id"])
    excluded = []
    for ex in p.get("exclusions") or []:
        for s in sheet["scope"]:
            if s["id"] not in prices and similar(ex, s["desc"]) >= LOOSE \
                    and s["id"] not in excluded:
                excluded.append(s["id"])
    name = p.get("bidder") or "Bidder"
    bidders = [b for b in sheet["bidders"] if b["name"] != name]
    bidders.append({"name": name, "kind": "sub", "prices": prices,
                    "excluded": excluded, "unclear": unclear,
                    "notes": "; ".join(filter(None, [
                        p.get("check", ""),
                        ("Exclusions: " + "; ".join(p["exclusions"]))
                        if p.get("exclusions") else ""]))[:500]})
    sheet["bidders"] = bidders
    bidday.save(doc, bidday.new_sheet(package, sheet["scope"], bidders))
    return {"bidder": name, "matched": matched, "unclear": unclear,
            "excluded": excluded, "unmatched": unmatched,
            "check": p.get("check", ""), "ocr": p.get("ocr", "")}


def set_status(doc, package, bidder, row_id, status, amount=None):
    """Change one cell by hand: confirmed, unclear or gap."""
    sheet = bidday.load(doc, package)
    b = next(x for x in sheet["bidders"] if x["name"] == bidder)
    b.setdefault("unclear", [])
    for k in ("excluded", "unclear"):
        if row_id in b[k]:
            b[k].remove(row_id)
    if status == RED:
        b["excluded"].append(row_id)
        b["prices"].pop(row_id, None)
    else:
        if amount is not None:
            b["prices"][row_id] = str(amount)
        if status == YELLOW:
            b["unclear"].append(row_id)
    bidday.save(doc, bidday.new_sheet(package, sheet["scope"],
                                      sheet["bidders"]))


def use_low(doc, package, bidder=None):
    """Our plugs written on the gaps, then the leveled low (or `bidder`)
    goes into the estimate. Returns bidday.apply_quote's result."""
    b = board(doc, package)
    sheet = bidday.load(doc, package)
    plugs = {r["id"]: r["plug"] for r in b["rows"] if r["plug"] is not None}
    for s in sheet["scope"]:
        if s["id"] in plugs:
            s["plug"] = f"{_c2(plugs[s['id']]):.2f}"
    bidday.save(doc, bidday.new_sheet(package, sheet["scope"],
                                      sheet["bidders"]))
    return bidday.apply_quote(doc, package, bidder or b["low"] or None)
