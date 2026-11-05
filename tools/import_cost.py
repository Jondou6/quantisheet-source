#!/usr/bin/env python3
"""
import_cost.py
==============
Import bid tabs and cost library exports into cost.db.

Normalises every description on the way through, matches it against the
controlled vocabulary, and routes each line one of three ways:

    auto    - matched with confidence, written as a price
    review  - low confidence, ambiguous, or unit mismatch, queued for a human
    new     - no match, clustered as a candidate for a new vocabulary item

Nothing ambiguous is ever written silently.

Dry run by default. Add --commit to write.

Usage
-----
    # see what would happen
    python import_cost.py --db cost.db --source "TX DOT 2026-03" bids/*.csv

    # write it
    python import_cost.py --db cost.db --source "TX DOT 2026-03" bids/*.csv --commit

    # with review and new-item queues
    python import_cost.py --db cost.db --source "TX DOT 2026-03" bids/*.csv \
        --queue review.csv --new new_items.csv --commit

    # create vocabulary items from big clusters (re-running a committed
    # import: --replace-source, or its prices are refused as duplicates)
    python import_cost.py --db cost.db --source "TX DOT 2026-03" bids/*.csv \
        --create-new --min-cluster 3 --replace-source --commit

Depends on vocab.py and costdb.py in the same folder. QuantiSheet does the
same routing when you import a bid tab (Takeoff > Bid Tabs).
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Iterable, Sequence

import vocab
import costdb

# --------------------------------------------------------------------------
# Light parser (bid tab or library export)
# --------------------------------------------------------------------------

FIELDS = ("item", "desc", "unit", "qty", "price", "total", "bidder")
KW = {
    "item":   ("item no", "item number", "item #", "bid item", "item", "no."),
    "desc":   ("description", "desc", "pay item", "work", "scope", "item description"),
    "unit":   ("unit", "uom", "u/m", "units"),
    "qty":    ("qty", "quantity", "quant"),
    "price":  ("unit price", "unit cost", "price", "rate", "unit bid"),
    "total":  ("extended", "ext amount", "total", "amount"),
    "bidder": ("bidder", "contractor", "vendor", "company", "firm"),
}
UNITS = {
    "sf": "SF", "sq ft": "SF", "sqft": "SF", "square feet": "SF",
    "sy": "SY", "sq yd": "SY", "lf": "LF", "lin ft": "LF", "linear feet": "LF",
    "cy": "CY", "cu yd": "CY", "ea": "EA", "each": "EA", "ls": "LS", "lump sum": "LS",
    "ton": "TON", "tons": "TON", "gal": "GAL", "lb": "LB", "lbs": "LB",
    "hr": "HR", "day": "DAY", "mbh": "MBH", "kw": "KW", "bf": "BF", "cf": "CF",
}


def split_lines(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    return [ln for ln in text.replace("\r", "").split("\n") if ln.strip()]


def sniff_delimiter(lines: Sequence[str]) -> str:
    sample = "\n".join(lines[:5])
    return max(("\t", "|", ",", ";"), key=lambda d: sample.count(d))


def split_row(line: str, delimiter: str) -> list[str]:
    return next(csv.reader(io.StringIO(line), delimiter=delimiter))


def to_float(value: str | None) -> float | None:
    if value is None:
        return None
    cleaned = re.sub(r"[^\d.\-]", "", str(value))
    if not cleaned or cleaned in {"-", "."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def norm_unit(text: str) -> str:
    key = re.sub(r"\.", "", str(text).strip().lower())
    return UNITS.get(key, str(text).strip().upper() or "")


def detect_columns(lines: Sequence[str]) -> tuple[dict[str, int], str, int]:
    delimiter = sniff_delimiter(lines)
    best_row, best_score = 0, -1
    for i, line in enumerate(lines[:8]):
        cells = [c.strip().lower() for c in split_row(line, delimiter)]
        score = sum(1 for f in FIELDS if any(k in c for c in cells for k in KW[f]))
        if score > best_score:
            best_row, best_score = i, score

    header = [c.strip().lower() for c in split_row(lines[best_row], delimiter)]
    index: dict[str, int] = {}
    for f in FIELDS:
        for i, cell in enumerate(header):
            if any(cell == k or k in cell for k in KW[f]):
                index[f] = i
                break
    return index, delimiter, (best_row if best_score >= 2 else 0)


def parse_rows(path: Path) -> list[dict]:
    lines = split_lines(path)
    if not lines:
        return []
    index, delimiter, header_row = detect_columns(lines)
    if index.get("desc", -1) < 0:
        raise ValueError(f"{path.name}: no description column found (detected: {index})")

    rows = []
    for i, line in enumerate(lines):
        if i == header_row:
            continue
        cells = split_row(line, delimiter)
        if len(cells) <= index["desc"]:
            continue
        desc = re.sub(r"\s+", " ", cells[index["desc"]]).strip().strip("\"'")
        if not desc:
            continue

        def cell(name):
            i = index.get(name, -1)
            return cells[i] if 0 <= i < len(cells) else None

        qty = to_float(cell("qty"))
        price = to_float(cell("price"))
        if price is None and qty:
            total = to_float(cell("total"))
            if total is not None:
                price = total / qty
        if price is None or price <= 0:
            continue

        rows.append({
            "desc": desc,
            "unit": norm_unit(cell("unit") or ""),
            "qty": qty or 1.0,
            "price": price,
            "bidder": (cells[index["bidder"]] if index.get("bidder", -1) >= 0
                       and index["bidder"] < len(cells) else path.stem),
            "file": path.name,
        })
    return rows


# --------------------------------------------------------------------------
# Resolution
# --------------------------------------------------------------------------

def top_matches(matcher: vocab.Matcher, text: str, n: int = 2,
                unit: str | None = None) -> list[tuple]:
    # through the matcher: sizes must agree ("6 in" never scores against
    # "4 in", which used to auto-accept at ~0.95) and learned aliases count;
    # other units are kept so classify() can queue them as a mismatch
    return matcher.candidates(text, unit, n, check_units=False)


AMBIGUITY_GAP = 0.03


def classify(row: dict, matcher: vocab.Matcher, auto: float, review: float,
             check_units: bool) -> dict:
    tops = top_matches(matcher, row["desc"], 2, row.get("unit") or None)
    if not tops:
        return {**row, "status": "new", "item_id": None, "match": None,
                "score": 0.0, "reason": "no vocabulary match"}

    score, item_id, canonical, item_unit = tops[0]

    if score < review:
        return {**row, "status": "new", "item_id": None, "match": canonical,
                "score": score, "reason": f"below review floor ({score:.2f})"}

    if score < auto:
        return {**row, "status": "review", "item_id": item_id, "match": canonical,
                "score": score, "reason": f"low confidence ({score:.2f})"}

    if len(tops) > 1 and (score - tops[1][0]) < AMBIGUITY_GAP:
        return {**row, "status": "review", "item_id": item_id, "match": canonical,
                "score": score, "reason": f"ambiguous vs '{tops[1][2]}'"}

    if check_units and row["unit"] and item_unit and row["unit"] != item_unit:
        return {**row, "status": "review", "item_id": item_id, "match": canonical,
                "score": score, "reason": f"unit {row['unit']} vs {item_unit}"}

    return {**row, "status": "auto", "item_id": item_id, "match": canonical,
            "score": score, "reason": ""}


def aggregate(rows: Iterable[dict]) -> list[dict]:
    buckets: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for r in rows:
        buckets[(r["item_id"], r["unit"] or "EA")].append(r)

    out = []
    for (item_id, unit), members in buckets.items():
        values = sorted(m["price"] for m in members)
        median = statistics.median(values)
        spread = ((values[-1] - values[0]) / median * 100) if len(values) > 1 and median else 0.0
        out.append({
            "item_id": item_id,
            "unit": unit,
            "value": median,
            "n_obs": len(values),
            "low": values[0],
            "high": values[-1],
            "median": median,
            "spread": spread,
            "qty_basis": members[0]["qty"],
        })
    return out


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------

def ensure_source(conn: sqlite3.Connection, name: str, kind: str, region: str,
                  create: bool) -> int:
    row = conn.execute("SELECT id FROM source WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    if not create:
        raise SystemExit(f"source '{name}' not found - add it or pass --create-source")
    cur = conn.execute(
        "INSERT INTO source (name, kind, region, retrieved_at) VALUES (?,?,?,?)",
        (name, kind, region, costdb.now()),
    )
    return cur.lastrowid


def write_prices(conn: sqlite3.Connection, source_id: int, aggs: list[dict],
                 price_date: str, region: str, kind: str) -> int:
    for a in aggs:
        conn.execute(
            "INSERT INTO price (item_id, source_id, value, unit, qty_basis, region, "
            "price_date, kind, n_obs, low, high, median, spread_pct, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (a["item_id"], source_id, a["value"], a["unit"], a["qty_basis"], region,
             price_date, kind, a["n_obs"], a["low"], a["high"], a["median"],
             a["spread"], costdb.now()),
        )
    costdb.log(conn, "price", source_id, "import", f"{len(aggs)} aggregates")
    conn.commit()
    return len(aggs)


def create_items(conn: sqlite3.Connection, clusters: list[tuple[str, list[str], str]]) -> int:
    created = 0
    for canonical, examples, unit in clusters:
        trade = "Unclassified"
        try:                       # classify like the bid tab tool, when
            from bidtab import classify_trade      # the trade is seeded
            guess = classify_trade(canonical)
            if conn.execute("SELECT 1 FROM trade WHERE code = ?",
                            (guess,)).fetchone():
                trade = guess
        except ImportError:
            pass
        row = conn.execute(
            "INSERT INTO item (canonical, unit, trade_code, created_at, updated_at) "
            "VALUES (?,?,?,?,?)",
            (canonical, unit or "EA", trade, costdb.now(), costdb.now()),
        )
        item_id = row.lastrowid
        for example in set(examples):
            conn.execute(
                "INSERT INTO alias (item_id, text, norm) VALUES (?,?,?)",
                (item_id, example, vocab.normalize(example)),
            )
        created += 1
    conn.commit()
    return created


# --------------------------------------------------------------------------

def current_month() -> str:
    today = date.today()
    return f"{today.year:04d}-{today.month:02d}"


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Import bid tabs into cost.db with normalisation and routing.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("paths", nargs="+", type=Path)
    p.add_argument("--db", type=Path, default=Path("cost.db"))
    p.add_argument("--source", required=True, help="source name recorded against every price")
    p.add_argument("--kind", default="bid_tab")
    p.add_argument("--region", default="")
    p.add_argument("--date", default=current_month(), metavar="YYYY-MM")
    p.add_argument("--auto", type=float, default=0.92, help="auto-accept floor (default 0.92)")
    p.add_argument("--review", type=float, default=0.75, help="review floor (default 0.75)")
    p.add_argument("--no-unit-check", action="store_true")
    p.add_argument("--commit", action="store_true", help="write (default is dry run)")
    p.add_argument("--create-source", action="store_true")
    p.add_argument("--replace-source", action="store_true",
                   help="delete existing prices from this source first")
    p.add_argument("--append", action="store_true",
                   help="add to a source that already has prices")
    p.add_argument("--create-new", action="store_true", help="create items from clusters")
    p.add_argument("--min-cluster", type=int, default=3)
    p.add_argument("--queue", type=Path, help="write review queue CSV")
    p.add_argument("--new", dest="new_path", type=Path, help="write proposed new items CSV")
    p.add_argument("--preview", type=int, default=12, help="rows to show per bucket")
    args = p.parse_args(argv)

    conn = costdb.connect(args.db)
    costdb.require(conn)
    matcher = vocab.Matcher(conn, threshold=min(args.review, 0.6))

    all_rows: list[dict] = []
    for path in args.paths:
        if not path.exists():
            print(f"missing: {path}", file=sys.stderr)
            continue
        all_rows.extend(parse_rows(path))

    if not all_rows:
        print("no priced rows parsed", file=sys.stderr)
        return 1

    decisions = [classify(r, matcher, args.auto, args.review, not args.no_unit_check)
                 for r in all_rows]

    auto = [d for d in decisions if d["status"] == "auto"]
    review = [d for d in decisions if d["status"] == "review"]
    new = [d for d in decisions if d["status"] == "new"]

    aggs = aggregate(auto)
    total = sum(a["value"] * a["qty_basis"] for a in aggs)

    print(f"\n{len(all_rows)} rows parsed from {len(args.paths)} file(s)")
    print(f"  auto    {len(auto):>5}  -> {len(aggs)} price records")
    print(f"  review  {len(review):>5}")
    print(f"  new     {len(new):>5}")
    print(f"  aggregate value {total:,.0f}\n")

    if auto:
        print(f"auto-accepted (first {args.preview}):")
        for d in sorted(auto, key=lambda x: -x["score"])[:args.preview]:
            print(f"  {d['score']:.2f}  {d['desc'][:46]:<48} -> {d['match']}")
        print()

    if review:
        print(f"queued for review (first {args.preview}):")
        for d in review[:args.preview]:
            print(f"  {d['score']:.2f}  {d['desc'][:40]:<42} -> {d['match'] or ''}  [{d['reason']}]")
        print()

    if new:
        print(f"unmatched (first {args.preview}):")
        for d in new[:args.preview]:
            print(f"  {d['score']:.2f}  {d['desc'][:60]}")
        print()

    # ---- queues -----------------------------------------------------------
    if args.queue:
        with args.queue.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["input", "matched_to", "item_id", "score", "reason",
                        "unit_hint", "price", "qty", "source_file", "bidder"])
            for d in review:
                w.writerow([d["desc"], d["match"] or "", d["item_id"] or "", f"{d['score']:.3f}",
                            d["reason"], d["unit"], f"{d['price']:.4f}", d["qty"],
                            d["file"], d["bidder"]])
        print(f"wrote review queue -> {args.queue}")

    clusters: list[tuple[str, list[str], str]] = []
    if new and (args.new_path or args.create_new):
        grouped: dict[str, list[dict]] = defaultdict(list)
        for d in new:
            grouped[vocab.normalize(d["desc"])].append(d)
        for norm, members in sorted(grouped.items(), key=lambda kv: -len(kv[1])):
            if len(members) < args.min_cluster:
                continue
            unit = Counter(m["unit"] for m in members if m["unit"]).most_common(1)
            canonical = members[0]["desc"].strip().rstrip(".")
            clusters.append((canonical[:120], [m["desc"] for m in members], unit[0][0] if unit else ""))

        if args.new_path:
            with args.new_path.open("w", newline="", encoding="utf-8") as fh:
                w = csv.writer(fh)
                w.writerow(["proposed_canonical", "unit", "occurrences", "examples"])
                for canonical, examples, unit in clusters:
                    w.writerow([canonical, unit, len(examples), " | ".join(examples[:3])])
            print(f"wrote {len(clusters)} new-item candidates -> {args.new_path}")

    # ---- commit -----------------------------------------------------------
    if not args.commit:
        print("\ndry run - nothing written. add --commit")
        return 0

    source_id = ensure_source(conn, args.source, args.kind, args.region, args.create_source)

    if args.replace_source:
        removed = conn.execute("DELETE FROM price WHERE source_id = ?", (source_id,)).rowcount
        conn.commit()
        print(f"removed {removed} existing prices from source {source_id}")
    elif not args.append and conn.execute(
            "SELECT 1 FROM price WHERE source_id = ? LIMIT 1", (source_id,)).fetchone():
        # re-running a committed import would write every price twice
        print(f"source '{args.source}' already has prices - pass --replace-source "
              "to redo the import, or --append to add to it", file=sys.stderr)
        return 1

    written = write_prices(conn, source_id, aggs, args.date, args.region, args.kind)
    print(f"wrote {written} price records from source {source_id} ({args.source})")

    if args.create_new and clusters:
        created = create_items(conn, clusters)
        print(f"created {created} new vocabulary items")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())