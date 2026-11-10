"""Bid leveling (your level.py, in level_core): line up bids by item,
find omissions, carries, buy-ins and outliers, and compare leveled
totals - each bidder's price with omitted scope added back at the
median. Works on a bid tab project in the price database or on files."""
from . import level_core as core
from . import pricedb
from .dmoney import c2 as _c2

DEFAULTS = {"carry": 1.5, "buyin": 0.65, "outlier_z": 3.5, "min_bidders": 2,
            "front_load_gap": 0.10}


def from_project(pid):
    """{bidder: [rows]} of a bid tab project."""
    bids = {}
    with pricedb.connect() as con:
        for r in con.execute("SELECT * FROM bid_rows WHERE project=? ORDER BY"
                             " id", (pid,)):
            bids.setdefault(r["bidder"], []).append({
                "desc": r["desc"], "unit": r["unit"], "qty": r["qty"] or 1.0,
                "price": r["price"], "item_no": r["item_no"] or "",
                "bidder": r["bidder"], "note": r["note"] or ""})
    return bids


def from_files(paths, bidder_column=False):
    from pathlib import Path
    from . import bidtab
    bids = {}
    for p in paths:
        rows = core.bidtab.parse_lines(
            bidtab.read_lines(str(p)), None if bidder_column else
            Path(p).stem, {}, Path(p).name)
        for r in rows:
            bids.setdefault(r.bidder, []).append({
                "desc": r.desc, "unit": r.unit, "qty": r.qty,
                "price": r.price, "item_no": r.item_no, "bidder": r.bidder,
                "note": getattr(r, "note", "")})
    return bids


def vocab_key():
    """Align by the pay item vocabulary where it knows the item."""
    from . import vocab
    try:
        m = vocab.matcher()
    except Exception:
        return core.key_of

    def key(desc, unit):
        r = m.match(desc, unit)
        if r["item_id"]:
            return f"vocab:{r['item_id']}|{(unit or 'EA').upper()}"
        return core.key_of(desc, unit)
    return key


PLUG_KINDS = ("Plug", "Included", "Override", "Adjustment")


def _num(v):
    try:
        return float(str(v).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _matches(row_or_item, ref):
    """Does a bid row / leveling item match a plug's item reference (item
    number or description)?"""
    ref = str(ref or "").strip().lower()
    if not ref:
        return False
    if isinstance(row_or_item, dict):
        no, desc = row_or_item.get("item_no"), row_or_item.get("desc")
    else:
        no = getattr(row_or_item, "item_no", "")
        desc = getattr(row_or_item, "desc", "")
    return ref in (str(no or "").strip().lower(),
                   str(desc or "").strip().lower())


def _pre_plugs(bids, plugs):
    """Overrides change a bidder's price; Included marks an item included
    in that bidder's number."""
    bids = {b: [dict(r) for r in rows] for b, rows in bids.items()}
    for p in plugs or []:
        kind, who = p.get("kind"), p.get("bidder")
        if who not in bids:
            continue
        if kind == "Override":
            val = _num(p.get("amount"))
            if val is None:
                continue
            hit = [r for r in bids[who] if _matches(r, p.get("item"))]
            for r in hit:
                r["price"] = val
            if not hit:               # an item they left off: price it
                proto = next((r for rows in bids.values() for r in rows
                              if _matches(r, p.get("item"))), None)
                if proto:
                    bids[who].append(dict(proto, price=val, bidder=who,
                                          note=""))
        elif kind == "Included":
            if any(_matches(r, p.get("item")) for r in bids[who]):
                continue
            proto = next((r for rows in bids.values() for r in rows
                          if _matches(r, p.get("item"))), None)
            if proto:
                bids[who].append(dict(proto, price=0.0, bidder=who,
                                      note="included"))
    return bids


def run(bids, carry=None, buyin=None, outlier_z=None, min_bidders=None,
        front_load_gap=None, use_vocab=True, plugs=None):
    """Level the bids. `plugs`: [{"bidder", "item", "kind", "amount",
    "note"}] - Plug (your number for an item a bidder left out, instead of
    the median), Included (the bidder says it's in their number),
    Override (correct a bidder's unit price) and Adjustment (add or take
    off an amount, e.g. for an exclusion)."""
    plugs = [p for p in plugs or [] if isinstance(p, dict) and
             p.get("kind") in PLUG_KINDS and p.get("bidder")]
    bids = _pre_plugs(bids, plugs)
    o = dict(DEFAULTS)
    for k, v in (("carry", carry), ("buyin", buyin),
                 ("outlier_z", outlier_z), ("min_bidders", min_bidders),
                 ("front_load_gap", front_load_gap)):
        if v is not None:
            o[k] = v
    if len(bids) < 2:
        raise ValueError("Leveling needs at least two bidders.")
    bidders = sorted(bids)
    items = core.build_items(bids, vocab_key() if use_vocab else None)
    an = core.analyse(items, bidders, o["carry"], o["buyin"],
                      o["outlier_z"], o["min_bidders"])
    results = core.level(bids, items, an, bidders, o["min_bidders"])
    for r in results:
        r["plugged"] = 0.0
        r["adjust"] = 0.0
        r["plug_notes"] = []
        missing = an["omissions"].get(r["bidder"], [])
        for p in plugs:
            if p["bidder"] != r["bidder"]:
                continue
            val = _num(p.get("amount"))
            if p["kind"] == "Plug" and val is not None:
                it = next((i for i in missing if _matches(i, p.get("item"))),
                          None)
                if it is not None:
                    at_median = it.median * it.qty \
                        if len(it.prices) >= o["min_bidders"] else 0.0
                    r["added"] += val - at_median
                    r["plugged"] += val
                    r["plug_notes"].append(f"plug {it.desc}: ${val:,.0f}")
            elif p["kind"] == "Adjustment" and val is not None:
                r["adjust"] += val
                r["plug_notes"].append(
                    f"{p.get('note') or p.get('item') or 'adjustment'}: "
                    f"{'+' if val >= 0 else '-'}${abs(val):,.0f}")
        r["leveled"] = r["base"] + r["added"] + r["adjust"]
    results.sort(key=lambda r: r["leveled"])
    for r in results:
        fl = r["front_load"]
        r["flag"] = ("FRONT-LOADED" if fl > 0 else "BACK-LOADED") \
            if abs(fl) >= o["front_load_gap"] else ""
    low_base = min(results, key=lambda r: r["base"])
    low_lev = results[0]
    risk = ""
    if low_base["bidder"] != low_lev["bidder"]:
        rank = [r["bidder"] for r in results].index(low_base["bidder"]) + 1
        risk = (f"{low_base['bidder']} is low on base bid but omitted "
                f"{low_base['omissions']} item(s) worth "
                f"${low_base['added']:,.0f}; leveled they rank #{rank}. "
                f"Low leveled: {low_lev['bidder']}.")
    gaps = sorted((i for i in items
                   if len(i.prices) + len(i.included) < len(bidders)
                   and len(i.prices) >= o["min_bidders"]),
                  key=lambda i: -(i.median * i.qty))
    return {"bidders": bidders, "items": items, "analysis": an,
            "results": results, "risk": risk, "gaps": gaps, "options": o,
            "plugs": plugs}


def plug_for(res, item, bidder):
    """The plug or override set on this cell, or None."""
    for p in res.get("plugs") or []:
        if p["bidder"] == bidder and p["kind"] in ("Plug", "Override",
                                                   "Included") and \
                _matches(item, p.get("item")):
            return p
    return None


def cell(res, item, bidder):
    """(text, mark) of one matrix cell: mark is "omit", "incl", "carry",
    "buyin", "outlier" or ""."""
    o = res["options"]
    pl = plug_for(res, item, bidder)
    if bidder in item.included:
        return "INCL", "incl"
    if pl is not None and pl["kind"] == "Plug" and bidder not in item.prices:
        return f"PLUG {_num(pl.get('amount')) or 0:,.0f}", "plug"
    if bidder not in item.prices:
        return ("OMIT" if len(item.prices) >= o["min_bidders"] else "-"), \
            "omit"
    p = item.prices[bidder]
    mark = ""
    if item.median:
        ratio = p / item.median
        if ratio >= o["carry"]:
            mark = "carry"
        elif ratio <= o["buyin"]:
            mark = "buyin"
    if item in res["analysis"]["outliers"].get(bidder, []):
        mark = mark or "outlier"
    return f"{_c2(p):,.2f}", mark


def export_xlsx(res, path):
    from . import acrobat
    b = res["bidders"]
    summary = [["Bidder", "Base bid", "Omissions", "Added (median / plugs)",
                "Adjustments", "Leveled", "Carries", "Buy-ins", "Outliers",
                "Flag", "Plugs and adjustments"]]
    for r in res["results"]:
        summary.append([r["bidder"], _c2(r["base"]), r["omissions"],
                        _c2(r["added"]), _c2(r.get("adjust", 0)),
                        _c2(r["leveled"]), r["carries"], r["buyins"],
                        r["outliers"], r["flag"],
                        "; ".join(r.get("plug_notes") or [])])
    if res["risk"]:
        summary += [[], ["AWARD RISK: " + res["risk"]]]
    matrix = [["Item", "Description", "Unit", "Qty", "Median", "Spread %"]
              + b]
    for it in res["items"]:
        row = [it.item_no, it.desc, it.unit, _c2(it.qty),
               _c2(it.median), round(it.spread)]
        for bd in b:
            text, mark = cell(res, it, bd)
            row.append(text + {"carry": " ^", "buyin": " v", "outlier": " *"}
                       .get(mark, ""))
        matrix.append(row)
    gaps = [["Item", "Description", "Unit", "Qty", "Median", "Omitted by",
             "Omission value", "Spread %"]]
    for it in res["gaps"]:
        om = [x for x in b if x not in it.prices and x not in it.included]
        gaps.append([it.item_no, it.desc, it.unit, _c2(it.qty),
                     _c2(it.median), "; ".join(om),
                     _c2(it.median * it.qty), round(it.spread)])
    acrobat.write_xlsx(path, [("Leveling", summary), ("Matrix", matrix),
                              ("Scope Gaps", gaps)])
    return path
