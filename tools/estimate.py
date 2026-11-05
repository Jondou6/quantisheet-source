#!/usr/bin/env python3
"""
estimate.py
===========
Estimate rollup, markup cascade, and bid builder.

Takes a priced takeoff (or a bare direct cost) and produces a bid: direct cost,
general conditions, overhead, profit, bond, insurance, contingency, escalation
and tax, applied in a defined order and fully auditable.

Also produces:
    - margin analysis by trade
    - schedule of values
    - front-load optimisation with cash flow NPV

Usage
-----
    # from a priced takeoff, priced against cost.db
    python estimate.py --takeoff takeoff.csv --db cost.db --out bid.csv

    # from a bare number
    python estimate.py --direct 2500000 --gc 9 --profit 8

    # trade-specific margin ("03=14" matches every trade in division 03)
    python estimate.py --takeoff t.csv --db cost.db --margin "03 Concrete=14,26 Electrical=6"

    # front-load analysis, and a front-loaded schedule of values
    python estimate.py --takeoff t.csv --db cost.db --front-load 0.06 --discount 7 \
        --sov sov.csv --sov-front-loaded

Takeoff CSV columns: description (or code), qty, unit, and optionally
unit_cost, cost_type, trade. Missing prices are looked up in cost.db
(through the vocabulary, so aliases and close wordings find their price,
and only in the same unit).

The cascade (QuantiSheet uses the same one, app/bidbuild.py):

    general conditions   % of direct
    sales tax            % of material lines
    overhead, profit     % of the running subtotal
    trade margins        extra % on that trade's subtotal
    insurance, contingency, escalation   % of the running subtotal
    bond                 premium on the final contract (graduated schedule)

Changes from the original
-------------------------
- trade margins were added twice: once into the unit costs (so GC, overhead
  and profit were charged on them, and the "direct" cost shown included
  them) and again in the margin report. Now they're one step of the cascade.
- the bond was priced on 1.4 x direct and charged before insurance,
  contingency and escalation, so it didn't cover the whole contract; and the
  flat rate by size band made a $1.01M job's bond cheaper than a $0.99M
  job's. Now it's a graduated schedule on the final contract amount.
- column lookup by substring took "unit_cost" for the unit column when it
  came first; exact names win now and a column is never used twice.
- the description lookup was exact text only and ignored units (a CY price
  could land on a SF line); lines with no price and no database were carried
  at zero without a warning; two items with the same name in different
  units overwrote each other.
- the schedule of values could miss the bid by a few cents; front-loading
  split by item count, not time, and paid each month one month early.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

try:
    import costdb
except ImportError:
    costdb = None

try:
    import vocab
except ImportError:
    vocab = None

# Surety bond schedule, graduated: the first $1M at 1.50%, the next $4M at
# 1.25% ... Approximate - use your broker's schedule.
BOND_TABLE = [
    (1_000_000, 1.50), (5_000_000, 1.25), (20_000_000, 1.00),
    (50_000_000, 0.85), (float("inf"), 0.75),
]


def bond_premium(contract: float) -> float:
    prem, lo = 0.0, 0.0
    for hi, rate in BOND_TABLE:
        if contract <= lo:
            break
        prem += (min(contract, hi) - lo) * rate / 100
        lo = hi
    return prem


def bond_rate(contract: float) -> float:
    """Effective bond % for a contract amount."""
    return bond_premium(contract) / contract * 100 if contract > 0 else 0.0


# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------

@dataclass
class LineItem:
    description: str
    qty: float
    unit: str
    unit_cost: float
    cost_type: str = "Other"
    trade: str = "Unclassified"
    sequence: int = 0
    code: str = ""
    source: str = ""
    price: float = 0.0          # bid price of the line, after the cascade

    @property
    def extended(self) -> float:
        return self.qty * self.unit_cost

    @property
    def is_material(self) -> bool:
        return self.cost_type.lower().startswith("mat")


@dataclass
class Markup:
    name: str
    rate: float
    basis: str = "subtotal"     # direct | subtotal | material | trade | bond
    amount: float = 0.0


@dataclass
class Rollup:
    direct: float = 0.0
    # name, rate %, amount, running total
    steps: list[tuple[str, float, float, float]] = field(default_factory=list)

    @property
    def total(self) -> float:
        return self.steps[-1][3] if self.steps else self.direct


def margin_for(trade: str, margins: dict[str, float]) -> float:
    """Exact trade name, else a division number: '03' (or '03 Concrete')
    matches '03 Concrete' and '03 30 00 Cast-in-place'."""
    if trade in margins:
        return margins[trade]
    t = (trade or "").strip().lower()
    for key, value in margins.items():
        k = key.strip().lower()
        if t == k:
            return value
        m = re.match(r"(\d{2})\b", k)
        if m and re.match(m.group(1) + r"\b", t):
            return value
    return 0.0


def apply_markups(items: Sequence[LineItem], markups: Sequence[Markup],
                  margins: dict[str, float] | None = None) -> Rollup:
    """Run the cascade line by line, so every line carries its own share of
    every markup and the lines add up to the bid."""
    margins = margins or {}
    direct = sum(i.extended for i in items)
    for i in items:
        i.price = i.extended
    rollup = Rollup(direct=direct)
    running = direct

    for m in markups:
        if m.basis == "bond":
            amount = bond_premium(running)
            if m.rate:                            # flat rate on the contract
                amount = running * m.rate / (100 - m.rate)
            else:                                 # premium on S + premium
                for _ in range(20):
                    nxt = bond_premium(running + amount)
                    if abs(nxt - amount) < 0.005:
                        amount = nxt
                        break
                    amount = nxt
            share = amount / running if running else 0.0
            for i in items:
                i.price *= 1 + share
            rate = amount / (running + amount) * 100 if running + amount else 0
        else:
            amount = 0.0
            for i in items:
                if m.basis == "direct":
                    a = i.extended * m.rate / 100
                elif m.basis == "material":
                    a = i.extended * m.rate / 100 if i.is_material else 0.0
                elif m.basis == "trade":
                    a = i.price * margin_for(i.trade, margins) / 100
                else:
                    a = i.price * m.rate / 100
                i.price += a
                amount += a
            rate = m.rate if m.basis != "trade" else \
                (amount / running * 100 if running else 0.0)
        running += amount
        rollup.steps.append((m.name, rate, amount, running))

    _cents(items, round(running, 2))
    return rollup


def _cents(rows, total: float, attr: str = "price") -> None:
    """Round to cents and put the drift on the largest line."""
    for r in rows:
        setattr(r, attr, round(getattr(r, attr), 2))
    if rows:
        big = max(rows, key=lambda r: abs(getattr(r, attr)))
        setattr(big, attr, round(getattr(big, attr) + total -
                                 sum(getattr(r, attr) for r in rows), 2))


# --------------------------------------------------------------------------
# Input
# --------------------------------------------------------------------------

def parse_margins(spec: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for part in filter(None, (p.strip() for p in spec.split(","))):
        if "=" not in part:
            raise SystemExit(f"bad margin '{part}' - use trade=percent")
        trade, value = part.rsplit("=", 1)
        out[trade.strip()] = float(value.strip().rstrip("%"))
    return out


class PriceBook:
    """Latest unit prices from cost.db, found by code or description."""

    def __init__(self, db: Path | None):
        self.rows: dict[int, dict] = {}
        self.by_code: dict[str, dict] = {}
        self.by_key: dict[tuple[str, str], dict] = {}
        self.matcher = None
        if not costdb or not db or not db.exists():
            return
        conn = costdb.connect(db)
        costdb.require(conn)
        for row in conn.execute(
                "SELECT item_id, code, canonical, unit, trade_code, cost_type, "
                "value FROM v_library WHERE value IS NOT NULL"):
            r = dict(row)
            self.rows[r["item_id"]] = r
            if r["code"]:
                self.by_code[r["code"].strip().lower()] = r
            self.by_key[(self._norm(r["canonical"]), (r["unit"] or "").upper())] = r
        if vocab:
            self.matcher = vocab.Matcher(conn)
        conn.close()

    @staticmethod
    def _norm(text: str) -> str:
        return vocab.normalize(text) if vocab else text.strip().lower()

    def __bool__(self) -> bool:
        return bool(self.rows)

    def find(self, desc: str, unit: str, code: str = "") -> dict | None:
        if code and code.strip().lower() in self.by_code:
            r = self.by_code[code.strip().lower()]
            return r if not unit or _same_unit(unit, r["unit"]) else None
        if self.matcher:
            hit = self.matcher.match(desc, unit or None)
            return self.rows.get(hit["item_id"]) if hit["item_id"] else None
        key = self._norm(desc)
        if unit:
            return self.by_key.get((key, unit.upper()))
        hits = [r for (k, _u), r in self.by_key.items() if k == key]
        return hits[0] if len(hits) == 1 else None


def _same_unit(a: str, b: str) -> bool:
    if vocab:
        return vocab.same_unit(a, b)
    return (a or "").upper() == (b or "").upper()


def _num(text: str) -> float | None:
    t = re.sub(r"[^\d.\-]", "", text or "")
    try:
        return float(t) if t not in ("", "-", ".") else None
    except ValueError:
        return None


def load_takeoff(path: Path, prices: PriceBook) -> list[LineItem]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    reader = csv.DictReader(text.splitlines())
    names = list(reader.fieldnames or [])
    used: set[str] = set()

    def col(*wanted: str) -> str | None:
        for exact in (True, False):          # exact names first
            for name in wanted:
                for f in names:
                    low = f.strip().lower()
                    if f in used:
                        continue
                    if low == name or (not exact and name in low):
                        used.add(f)
                        return f
        return None

    c_cost = col("unit_cost", "unit cost", "unit price", "price", "rate")
    c_desc = col("description", "desc", "item")
    c_code = col("code", "item code", "pay item")
    c_qty = col("qty", "quantity")
    c_unit = col("unit", "uom", "units")
    c_type = col("cost_type", "cost type", "type")
    c_trade = col("trade", "division")

    if not (c_desc or c_code) or not c_qty:
        raise SystemExit(f"{path.name}: need description (or code) and qty columns")

    items: list[LineItem] = []
    missing: list[str] = []

    for seq, row in enumerate(reader, start=1):
        desc = (row.get(c_desc) or "").strip() if c_desc else ""
        code = (row.get(c_code) or "").strip() if c_code else ""
        if not desc and not code:
            continue
        qty = _num(row.get(c_qty) or "")
        if not qty or qty <= 0:
            continue

        unit = (row.get(c_unit) or "").strip() if c_unit else ""
        unit_cost = _num(row.get(c_cost) or "") if c_cost else None
        trade = (row.get(c_trade) or "").strip() if c_trade else ""
        cost_type = (row.get(c_type) or "").strip() if c_type else ""

        if unit_cost is None:
            hit = prices.find(desc or code, unit, code) if prices else None
            if hit:
                unit_cost = hit["value"]
                unit = unit or hit["unit"]
                trade = trade or hit["trade_code"] or ""
                cost_type = cost_type or hit["cost_type"] or ""
                desc = desc or hit["canonical"]
            else:
                missing.append(desc or code)
                unit_cost = 0.0

        items.append(LineItem(
            description=desc or code, qty=qty, unit=unit or "EA",
            unit_cost=unit_cost, cost_type=cost_type or "Other",
            trade=trade or "Unclassified", sequence=seq, code=code,
        ))

    if missing:
        print(f"  ! {len(missing)} lines had no price and were carried at zero:",
              file=sys.stderr)
        for desc in missing[:8]:
            print(f"      {desc[:70]}", file=sys.stderr)
    return items


# --------------------------------------------------------------------------
# Margin by trade
# --------------------------------------------------------------------------

def margin_analysis(items: Sequence[LineItem], rollup: Rollup,
                    margins: dict[str, float]) -> list[dict]:
    direct = rollup.direct or 1.0
    by_trade: dict[str, list[float]] = {}
    for item in items:
        d = by_trade.setdefault(item.trade, [0.0, 0.0])
        d[0] += item.extended
        d[1] += item.price
    rows = []
    for trade, (trade_direct, revenue) in sorted(by_trade.items()):
        rows.append({
            "trade": trade,
            "direct": trade_direct,
            "share_pct": trade_direct / direct * 100,
            "allocated_markup": revenue - trade_direct,
            "extra_margin_pct": margin_for(trade, margins),
            "revenue": revenue,
            "margin_pct": (revenue - trade_direct) / revenue * 100 if revenue else 0.0,
        })
    return rows


# --------------------------------------------------------------------------
# Front loading
# --------------------------------------------------------------------------

def billed_by_month(work: Sequence[float], billed: Sequence[float],
                    months: int) -> list[float]:
    """Lines laid end to end in schedule order, each taking time in
    proportion to its work; each is billed at `billed` as it's done."""
    months = max(1, months)
    total = sum(work)
    out = [0.0] * months
    if total <= 0:
        return out
    pos = 0.0
    for w, b in zip(work, billed):
        start, end = pos / total * months, (pos + w) / total * months
        pos += w
        m = int(start)
        while m < months and m < end:
            if end > start:
                out[m] += b * (min(end, m + 1) - max(start, m)) / (end - start)
            m += 1
    return out


def cash_flow_npv(values_by_month: Sequence[float], discount_annual: float,
                  retention_pct: float, payment_days: int,
                  release_months: int = 3) -> float:
    """Billed at each month end, paid `payment_days` later; retention is
    released `release_months` after the last payment."""
    monthly_rate = (1 + discount_annual / 100) ** (1 / 12) - 1
    lag = payment_days / 30
    npv = 0.0
    for month, value in enumerate(values_by_month):
        npv += value * (1 - retention_pct / 100) / (1 + monthly_rate) ** (month + 1 + lag)
    retained = sum(values_by_month) * retention_pct / 100
    npv += retained / (1 + monthly_rate) ** (len(values_by_month) + lag + release_months)
    return npv


def front_load(items: list[LineItem], factor: float, months: int,
               discount: float, retention: float, payment_days: int) -> dict:
    """Raise the lines in the first third of the schedule (by time) by
    `factor`, lower the last third, keep the total. Sets item.loaded."""
    if not 0 <= factor < 0.5:
        raise SystemExit("--front-load must be between 0 and 0.5")
    ordered = sorted(items, key=lambda i: i.sequence)
    work = [i.price for i in ordered]
    total = sum(work)
    pos, raw = 0.0, []
    for i in ordered:
        mid = (pos + i.price / 2) / total if total else 0.0
        pos += i.price
        mult = 1 + factor if mid < 1 / 3 else 1 - factor if mid > 2 / 3 else 1.0
        raw.append(i.price * mult)
    scale = total / sum(raw) if sum(raw) else 1.0
    for i, r in zip(ordered, raw):
        i.loaded = r * scale
    _cents(ordered, round(total, 2), "loaded")

    base = cash_flow_npv(billed_by_month(work, work, months), discount,
                         retention, payment_days)
    new = cash_flow_npv(billed_by_month(work, [i.loaded for i in ordered], months),
                        discount, retention, payment_days)
    change = max((abs(i.loaded - i.price) / i.price * 100 for i in ordered
                  if i.price), default=0.0)
    return {"base_npv": base, "loaded_npv": new, "improvement": new - base,
            "improvement_pct": (new - base) / base * 100 if base else 0.0,
            "max_change_pct": change}


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def print_rollup(rollup: Rollup) -> None:
    print(f"\n{'direct cost':<34}{rollup.direct:>16,.0f}")
    print("-" * 66)
    for name, rate, amount, running in rollup.steps:
        print(f"{name:<26}{rate:>6.2f}%{amount:>16,.0f}{running:>16,.0f}")
    print("-" * 66)
    print(f"{'BID':<34}{rollup.total:>16,.0f}")
    print(f"{'markup uplift':<34}{(rollup.total - rollup.direct) / rollup.direct * 100:>15.2f}%")


def write_bid(path: Path, items: Sequence[LineItem], rollup: Rollup) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["seq", "trade", "description", "qty", "unit", "unit_cost",
                         "extended", "markup", "bid_price", "bid_unit_price"])
        for item in items:
            writer.writerow([item.sequence, item.trade, item.description, f"{item.qty:.2f}",
                             item.unit, f"{item.unit_cost:.2f}", f"{item.extended:.2f}",
                             f"{item.price - item.extended:.2f}", f"{item.price:.2f}",
                             f"{item.price / item.qty:.4f}"])
        writer.writerow(["", "", "TOTAL", "", "", "", f"{rollup.direct:.2f}",
                         f"{rollup.total - rollup.direct:.2f}", f"{rollup.total:.2f}", ""])


def write_sov(path: Path, items: Sequence[LineItem], rollup: Rollup,
              loaded: bool = False) -> None:
    by_trade: dict[str, float] = {}
    for item in sorted(items, key=lambda i: i.sequence):
        value = getattr(item, "loaded", item.price) if loaded else item.price
        by_trade[item.trade] = by_trade.get(item.trade, 0.0) + value
    total = round(rollup.total, 2)
    lines = [[t, round(v, 2)] for t, v in by_trade.items()]
    if lines:                                   # add up to the bid exactly
        big = max(lines, key=lambda x: abs(x[1]))
        big[1] = round(big[1] + total - sum(x[1] for x in lines), 2)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["sov_item", "trade", "scheduled_value", "pct_of_contract"])
        for index, (trade, scheduled) in enumerate(lines, start=1):
            writer.writerow([index, trade, f"{scheduled:.2f}",
                             f"{scheduled / total * 100:.2f}"])
        writer.writerow(["", "TOTAL", f"{total:.2f}", "100.00"])


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Estimate rollup, markup cascade and bid builder.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--takeoff", type=Path)
    p.add_argument("--db", type=Path, default=Path("cost.db"))
    p.add_argument("--direct", type=float, help="bare direct cost, skips takeoff")
    p.add_argument("--gc", type=float, default=8.0, help="general conditions %% of direct")
    p.add_argument("--overhead", type=float, default=5.0, help="%% of running subtotal")
    p.add_argument("--profit", type=float, default=8.0, help="%% of running subtotal")
    p.add_argument("--insurance", type=float, default=2.0, help="%% of running subtotal")
    p.add_argument("--contingency", type=float, default=5.0, help="%% of running subtotal")
    p.add_argument("--escalation", type=float, default=0.0, help="%% of running subtotal")
    p.add_argument("--tax", type=float, default=0.0, help="sales tax %% on material")
    p.add_argument("--bond", type=float, help="flat bond %% of contract; omit for the graduated schedule")
    p.add_argument("--no-bond", action="store_true")
    p.add_argument("--margin", default="", help="per-trade extra margin, e.g. '03 Concrete=14'")
    p.add_argument("--front-load", type=float, default=0.0, help="front-load factor, e.g. 0.06")
    p.add_argument("--months", type=int, default=12, help="project duration for cash flow")
    p.add_argument("--discount", type=float, default=7.0, help="annual discount rate %%")
    p.add_argument("--retention", type=float, default=10.0, help="retention %%")
    p.add_argument("--payment-days", type=int, default=30)
    p.add_argument("--out", type=Path, help="write priced bid CSV")
    p.add_argument("--sov", type=Path, help="write schedule of values CSV")
    p.add_argument("--sov-front-loaded", action="store_true",
                   help="schedule of values at the front-loaded values")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    if args.takeoff:
        items = load_takeoff(args.takeoff, PriceBook(args.db))
    elif args.direct:
        items = [LineItem("Direct cost", 1.0, "LS", args.direct, cost_type="Other",
                          trade="Unclassified", sequence=1)]
    else:
        p.print_help()
        return 1

    direct = sum(i.extended for i in items)
    if direct <= 0:
        print("direct cost is zero - check pricing", file=sys.stderr)
        return 1

    margins = parse_margins(args.margin)
    unknown = [t for t in margins if not any(margin_for(i.trade, {t: 1}) for i in items)]
    if unknown:
        print(f"  ! no takeoff lines in trade(s): {', '.join(unknown)}", file=sys.stderr)

    markups: list[Markup] = [Markup("general conditions", args.gc, "direct")]
    if args.tax:
        if not any(i.is_material for i in items):
            print("  ! --tax set but no lines have cost_type Material - no tax "
                  "charged", file=sys.stderr)
        markups.append(Markup("sales tax on material", args.tax, "material"))
    markups.append(Markup("overhead", args.overhead))
    markups.append(Markup("profit", args.profit))
    if margins:
        markups.append(Markup("trade margins", 0.0, "trade"))
    markups.append(Markup("insurance", args.insurance))
    if args.contingency:
        markups.append(Markup("contingency", args.contingency))
    if args.escalation:
        markups.append(Markup("escalation", args.escalation))
    if not args.no_bond:
        markups.append(Markup("bond", args.bond or 0.0, "bond"))

    rollup = apply_markups(items, markups, margins)
    margin_rows = margin_analysis(items, rollup, margins)

    if args.json:
        print(json.dumps({
            "direct": rollup.direct,
            "steps": [{"name": n, "rate": r, "amount": a, "running": v}
                      for n, r, a, v in rollup.steps],
            "bid": rollup.total,
            "margins": margin_rows,
        }, indent=2))
    else:
        print_rollup(rollup)
        if margins:
            print("\nmargin strategy by trade\n")
            print(f"{'trade':<28}{'direct':>14}{'revenue':>14}{'margin':>9}")
            print("-" * 66)
            for row in margin_rows:
                print(f"{row['trade'][:27]:<28}{row['direct']:>14,.0f}"
                      f"{row['revenue']:>14,.0f}{row['margin_pct']:>8.1f}%")

    if args.front_load:
        result = front_load(items, args.front_load, args.months,
                            args.discount, args.retention, args.payment_days)
        print(f"\nfront-load analysis (factor {args.front_load:.2f}, {args.months} months, "
              f"{args.discount}% discount)")
        print(f"  npv base          {result['base_npv']:>14,.0f}")
        print(f"  npv front-loaded  {result['loaded_npv']:>14,.0f}")
        print(f"  improvement       {result['improvement']:>14,.0f}  "
              f"({result['improvement_pct']:.2f}%)")
        print(f"  total bid unchanged - only timing moved; lines move up to "
              f"{result['max_change_pct']:.1f}%")
        if result["max_change_pct"] > 10:
            print("  ! an owner can reject a materially unbalanced bid", file=sys.stderr)
    elif args.sov_front_loaded:
        print("  ! --sov-front-loaded needs --front-load", file=sys.stderr)

    if args.out:
        write_bid(args.out, items, rollup)
        print(f"\nwrote bid -> {args.out}")
    if args.sov:
        write_sov(args.sov, items, rollup, args.sov_front_loaded and bool(args.front_load))
        print(f"wrote schedule of values -> {args.sov}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
