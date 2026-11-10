"""
level.py (your bid leveling tool, used by QuantiSheet's Bid Leveling window;
the command-line version is tools/level.py)
========
Bid leveling and scope gap analysis.

Reads one bid tab per bidder, aligns every line item to a common key, and
produces a leveling matrix with the things that actually cost money flagged:

    omissions   item present in some bids, missing in others
    carries     priced well above the median to bury risk
    buy-ins     priced well below the median, often a scope misread
    outliers    statistical outliers against the median
    unbalanced  front-loaded pricing detected by sequence position

Then computes a leveled total: each bidder's price with their omissions added
back at the median, so bids are compared like for like.

Depends on bidtab.py for parsing and vocab.py for alignment (both optional -
falls back to raw normalisation if absent).

Usage
-----
    python level.py bids/*.csv
    python level.py bids/*.csv --matrix matrix.csv --gaps gaps.csv
    python level.py tab.csv --bidder-column --carry-ratio 1.4 --min-bidders 3
"""

from __future__ import annotations

import argparse
import csv
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Sequence
from .dmoney import c2 as _c2

try:                                  # spreadsheet formula guard (CSV)
    from . import safecell
except ImportError:                   # run as a script
    from app import safecell

try:
    import bidtab
except ImportError:
    try:
        from . import bidtab_core as bidtab
    except ImportError:
        bidtab = None

try:
    import vocab
except ImportError:
    try:
        from . import vocab_core as vocab
    except ImportError:
        vocab = None


# --------------------------------------------------------------------------
# Alignment
# --------------------------------------------------------------------------

NOISE = {"furnish", "install", "provide", "including", "complete", "all", "per",
         "the", "of", "and", "with", "as", "for", "in", "on", "at", "to"}


def key_of(desc: str, unit: str) -> str:
    """Stable alignment key. Uses the controlled vocabulary when available."""
    if vocab:
        norm = vocab.normalize(desc)
    else:
        norm = re.sub(r"[^\w\s.]", " ", str(desc).lower())
        norm = " ".join(t for t in norm.split() if t not in NOISE)
    return f"{norm}|{(unit or 'EA').upper()}"


def fallback_parse(path: Path) -> list[dict]:
    """Minimal parser used only if bidtab.py is unavailable."""
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    lines = [ln for ln in text.replace("\r", "").split("\n") if ln.strip()]
    if not lines:
        return []
    delimiter = max(("\t", "|", ",", ";"), key=lambda d: "\n".join(lines[:5]).count(d))
    rows: list[dict] = []
    for i, line in enumerate(lines):
        cells = next(csv.reader([line], delimiter=delimiter))
        if i == 0 and not any(ch.isdigit() for ch in "".join(cells[:2])):
            continue
        if len(cells) < 3:
            continue
        desc = cells[1] if len(cells) > 3 else cells[0]
        try:
            price = float(re.sub(r"[^\d.]", "", cells[-1]))
        except ValueError:
            continue
        rows.append({"desc": desc.strip(), "unit": "EA", "qty": 1.0, "price": price,
                     "item_no": cells[0].strip()})
    return rows


def load_bids(paths: Sequence[Path], bidder_column: bool) -> dict[str, list[dict]]:
    bids: dict[str, list[dict]] = {}
    for path in paths:
        if not path.exists():
            print(f"missing: {path}", file=sys.stderr)
            continue

        rows: list[dict] = []
        if bidtab:
            parsed = bidtab.parse_file(path, None if bidder_column else path.stem, {})
            for r in parsed:
                rows.append({"desc": r.desc, "unit": r.unit, "qty": r.qty,
                             "price": r.price, "item_no": r.item_no, "bidder": r.bidder,
                             "note": getattr(r, "note", "")})
        else:
            for r in fallback_parse(path):
                r["bidder"] = path.stem
                rows.append(r)

        for r in rows:
            bids.setdefault(r["bidder"], []).append(r)
    return bids


# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------

class Item:
    def __init__(self, key: str, desc: str, unit: str, sequence: int):
        self.key = key
        self.desc = desc
        self.unit = unit
        self.sequence = sequence
        self.prices: dict[str, float] = {}
        self.qtys: dict[str, float] = {}
        self.included: set[str] = set()     # INCL: carried elsewhere, $0
        self.excluded: set[str] = set()     # "by others" / NIC: left out
        self.item_no = ""

    @property
    def qty(self) -> float:
        return statistics.median(self.qtys.values()) if self.qtys else 1.0

    @property
    def median(self) -> float:
        return statistics.median(self.prices.values()) if self.prices else 0.0

    @property
    def spread(self) -> float:
        if len(self.prices) < 2 or not self.median:
            return 0.0
        values = sorted(self.prices.values())
        return (values[-1] - values[0]) / self.median * 100


def build_items(bids: dict[str, list[dict]], key=None) -> list[Item]:
    """`key(desc, unit)` aligns lines (default key_of); an INCL line marks
    the item included for that bidder (not an omission, not a price)."""
    key = key or key_of
    items: dict[str, Item] = {}
    sequence = 0
    for bidder, rows in bids.items():
        for row in rows:
            k = key(row["desc"], row["unit"])
            if k not in items:
                sequence += 1
                items[k] = Item(k, row["desc"], row["unit"], sequence)
                items[k].item_no = row.get("item_no", "")
            item = items[k]
            note = row.get("note") or ""
            if note == "included":
                item.included.add(bidder)
                continue
            if note == "excluded":
                item.excluded.add(bidder)
                continue
            if bidder not in item.prices:
                item.prices[bidder] = row["price"]
                item.qtys[bidder] = row.get("qty", 1.0)
    return sorted(items.values(), key=lambda i: i.sequence)


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------

def analyse(items: Sequence[Item], bidders: Sequence[str], carry_ratio: float,
            buyin_ratio: float, outlier_z: float, min_bidders: int) -> dict:
    omissions: dict[str, list[Item]] = defaultdict(list)
    carries: dict[str, list[Item]] = defaultdict(list)
    buyins: dict[str, list[Item]] = defaultdict(list)
    outliers: dict[str, list[Item]] = defaultdict(list)
    ratios: dict[str, dict[str, float]] = defaultdict(dict)

    for item in items:
        if len(item.prices) < min_bidders:
            continue
        median = item.median
        if not median:
            continue

        # robust z (median / MAD, Iglewicz-Hoaglin): with n bids a plain
        # z-score can never exceed sqrt(n-1), so z >= 2.5 needed 8+ bidders
        mad = 0.0
        if len(item.prices) >= 3:
            values = list(item.prices.values())
            mad = statistics.median(abs(v - median) for v in values)

        for bidder in bidders:
            if bidder not in item.prices:
                if bidder not in item.included:
                    omissions[bidder].append(item)
                continue
            price = item.prices[bidder]
            ratio = price / median
            ratios[bidder][item.key] = ratio

            if ratio >= carry_ratio:
                carries[bidder].append(item)
            elif ratio <= buyin_ratio:
                buyins[bidder].append(item)

            if mad and 0.6745 * abs(price - median) / mad >= outlier_z:
                outliers[bidder].append(item)

    return {"omissions": omissions, "carries": carries, "buyins": buyins,
            "outliers": outliers, "ratios": ratios}


def front_load_index(item_ratios: dict[str, float], items: Sequence[Item]) -> float:
    """Positive = loaded early. Uses item order as a construction sequence proxy."""
    ordered = [i.key for i in items if i.key in item_ratios]
    if len(ordered) < 10:
        return 0.0
    cut = max(1, len(ordered) // 5)
    early = statistics.fmean(item_ratios[k] for k in ordered[:cut])
    late = statistics.fmean(item_ratios[k] for k in ordered[-cut:])
    return early - late


def level(bids: dict[str, list[dict]], items: Sequence[Item],
          analysis: dict, bidders: Sequence[str], min_bidders: int) -> list[dict]:
    results = []
    for bidder in bidders:
        base = sum(r["price"] * r["qty"] for r in bids.get(bidder, []))
        missing = analysis["omissions"].get(bidder, [])
        added = sum(i.median * i.qty for i in missing if len(i.prices) >= min_bidders)
        results.append({
            "bidder": bidder,
            "base": base,
            "omissions": len(missing),
            "added": added,
            "leveled": base + added,
            "carries": len(analysis["carries"].get(bidder, [])),
            "buyins": len(analysis["buyins"].get(bidder, [])),
            "outliers": len(analysis["outliers"].get(bidder, [])),
            "front_load": front_load_index(analysis["ratios"].get(bidder, {}), items),
        })
    results.sort(key=lambda r: r["leveled"])
    return results


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def write_matrix(path: Path, items: Sequence[Item], bidders: Sequence[str],
                 analysis: dict, carry_ratio: float, buyin_ratio: float) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = safecell.writer(fh)
        writer.writerow(["item_no", "description", "unit", "qty", "median", "spread_pct"]
                        + list(bidders))
        for item in items:
            row = [item.item_no, item.desc, item.unit, f"{_c2(item.qty):.2f}",
                   f"{_c2(item.median):.2f}", f"{item.spread:.0f}"]
            for bidder in bidders:
                if bidder in item.included:
                    row.append("INCL")
                    continue
                if bidder not in item.prices:
                    row.append("OMIT")
                    continue
                price = item.prices[bidder]
                mark = ""
                if item.median:
                    ratio = price / item.median
                    if ratio >= carry_ratio:
                        mark = " ^"
                    elif ratio <= buyin_ratio:
                        mark = " v"
                row.append(f"{_c2(price):.2f}{mark}")
            writer.writerow(row)


def write_gaps(path: Path, items: Sequence[Item], bidders: Sequence[str],
               analysis: dict, min_bidders: int) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = safecell.writer(fh)
        writer.writerow(["item_no", "description", "unit", "qty", "median",
                         "omitted_by", "omission_value", "spread_pct"])
        for item in items:
            omitted = [b for b in bidders if b not in item.prices
                       and b not in item.included]
            if not omitted or len(item.prices) < min_bidders:
                continue
            writer.writerow([item.item_no, item.desc, item.unit, f"{_c2(item.qty):.2f}",
                             f"{_c2(item.median):.2f}", "; ".join(omitted),
                             f"{_c2(item.median * item.qty):.2f}", f"{item.spread:.0f}"])


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Bid leveling and scope gap analysis.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("paths", nargs="+", type=Path, help="one bid tab per bidder")
    p.add_argument("--bidder-column", action="store_true",
                   help="bidder names come from a column, not the filename")
    p.add_argument("--carry-ratio", type=float, default=1.5)
    p.add_argument("--buyin-ratio", type=float, default=0.65)
    p.add_argument("--outlier-z", type=float, default=3.5,
                   help="robust z (median/MAD) for outliers (default 3.5)")
    p.add_argument("--min-bidders", type=int, default=2,
                   help="ignore items bid by fewer than N bidders")
    p.add_argument("--front-load-gap", type=float, default=0.10)
    p.add_argument("--matrix", type=Path)
    p.add_argument("--gaps", type=Path)
    args = p.parse_args(argv)

    bids = load_bids(args.paths, args.bidder_column)
    if len(bids) < 2:
        print("need at least two bidders", file=sys.stderr)
        return 1

    bidders = sorted(bids)
    items = build_items(bids)
    analysis = analyse(items, bidders, args.carry_ratio, args.buyin_ratio,
                       args.outlier_z, args.min_bidders)
    results = level(bids, items, analysis, bidders, args.min_bidders)

    print(f"\nBID LEVELING - {len(bidders)} bidders, {len(items)} distinct items\n")
    print(f"{'bidder':<26}{'base bid':>14}{'omit':>6}{'added':>14}{'leveled':>14}"
          f"{'carry':>7}{'buyin':>7}{'flags':>7}")
    print("-" * 100)
    for r in results:
        flag = ""
        if abs(r["front_load"]) >= args.front_load_gap:
            flag = "FRONT-LOADED" if r["front_load"] > 0 else "BACK-LOADED"
        print(f"{r['bidder'][:25]:<26}{r['base']:>14,.0f}{r['omissions']:>6}"
              f"{r['added']:>14,.0f}{r['leveled']:>14,.0f}"
              f"{r['carries']:>7}{r['buyins']:>7}  {flag}")

    if results:
        low_base = min(results, key=lambda r: r["base"])
        low_leveled = results[0]
        print(f"\nlow on base bid      {low_base['bidder']}  ({low_base['base']:,.0f})")
        print(f"low on leveled       {low_leveled['bidder']}  ({low_leveled['leveled']:,.0f})")
        if low_base["bidder"] != low_leveled["bidder"]:
            exposure = low_base["added"]
            print(f"\n! AWARD RISK: '{low_base['bidder']}' is low on base but omitted "
                  f"{low_base['omissions']} items worth {exposure:,.0f}.")
            print(f"  Leveled, they rank #{[r['bidder'] for r in results].index(low_base['bidder']) + 1}.")

    top_gaps = sorted(
        (i for i in items if len(i.prices) + len(i.included) < len(bidders)
         and len(i.prices) >= args.min_bidders),
        key=lambda i: -(i.median * i.qty),
    )[:15]
    if top_gaps:
        print(f"\nlargest scope gaps:\n")
        for item in top_gaps:
            omitted = [b for b in bidders if b not in item.prices
                       and b not in item.included]
            print(f"  {item.median * item.qty:>11,.0f}  {item.desc[:44]:<46} "
                  f"omitted by {len(omitted)}: {', '.join(o[:14] for o in omitted[:3])}")

    if args.matrix:
        write_matrix(args.matrix, items, bidders, analysis, args.carry_ratio, args.buyin_ratio)
        print(f"\nwrote matrix -> {args.matrix}")
    if args.gaps:
        write_gaps(args.gaps, items, bidders, analysis, args.min_bidders)
        print(f"wrote gaps -> {args.gaps}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())