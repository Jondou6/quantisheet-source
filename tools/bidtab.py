"""
bidtab.py (your bid tab tool, used by QuantiSheet's Bid Tabs window; the
command-line version is tools/bidtab.py)
=========
Turn public bid tab data into a local unit cost library.

Reads one or more bid tab files (one file per bidder, or a single file with a
bidder column), normalises descriptions and units, classifies each line into a
trade, computes low / median / mean / high and spread across bidders, escalates
to a target date, and writes a library, a full analysis, or a trade rollup.

Standard library only. No pandas required.

Usage
-----
    python bidtab.py bids/*.csv --from 2024-06 --out library.csv
    python bidtab.py tab.csv --from 2024-06 --format roll --out rollup.csv
    python bidtab.py tab.csv --list-columns
    python bidtab.py --write-sample sample_bidtab.csv

Override auto-detected columns with --map desc=2,unit=3,qty=4,price=5
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import statistics
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable, Sequence

# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------

FIELDS = ("item", "desc", "unit", "qty", "price", "total", "bidder")

HEADER_KEYWORDS: dict[str, tuple[str, ...]] = {
    "item":   ("item no", "item number", "item #", "bid item", "item", "no."),
    "desc":   ("description", "desc", "pay item", "work", "scope", "item description"),
    "unit":   ("unit", "uom", "u/m", "units", "unit of measure"),
    "qty":    ("qty", "quantity", "quant", "est qty", "estimated qty"),
    "price":  ("unit price", "unit cost", "price", "rate", "unit bid", "unit amount"),
    "total":  ("extended", "ext amount", "total", "amount", "bid amount", "extended price"),
    "bidder": ("bidder", "contractor", "vendor", "company", "firm", "proposer"),
}

UNIT_ALIASES: dict[str, str] = {
    "sf": "SF", "sq ft": "SF", "sqft": "SF", "square feet": "SF", "square foot": "SF",
    "sy": "SY", "sq yd": "SY", "square yard": "SY",
    "lf": "LF", "lin ft": "LF", "linear feet": "LF", "linear foot": "LF",
    "cy": "CY", "cu yd": "CY", "cubic yards": "CY", "cubic yard": "CY",
    "ea": "EA", "each": "EA",
    "ls": "LS", "lump sum": "LS",
    "ton": "TON", "tons": "TON",
    "gal": "GAL", "gallon": "GAL", "gallons": "GAL",
    "lb": "LB", "lbs": "LB", "pound": "LB", "pounds": "LB",
    "hr": "HR", "hour": "HR", "hours": "HR",
    "day": "DAY", "mo": "MO", "month": "MO",
    "mbh": "MBH", "kw": "KW", "bf": "BF", "cf": "CF", "fl": "FL", "pt": "PT",
    "mi": "MI", "mile": "MI", "cy.": "CY",
}

# Ordered: first match wins. Broad patterns go last.
# Patterns are word stems ("excavat", "reinforc"), so they match from the
# start of a word only (no closing \b, which made stems never match).
TRADE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(p[:-2] if p.endswith(r"\b") else p, re.I), t) for p, t in (
        (r"\b(pavement mark|painted pavement|striping)\b", "32 Exterior Improvements"),
        (r"\b(excavat|earthwork|grading|trench|backfill|unclassified|soil|clearing|demolition|shoring)\b", "31 Earthwork"),
        (r"\b(concrete|footing|rebar|reinforc|formwork|grout|cast.in.place|retaining|slab on grade|curb|sidewalk)\b", "03 Concrete"),
        (r"\b(masonry|block|brick|cmu|stone veneer)\b", "04 Masonry"),
        (r"\b(structural steel|steel|joist|metal deck|misc\.? metal|handrail|lintel|fabricat|bollard)\b", "05 Metals"),
        (r"\b(carpent|wood|framing|truss|plywood|millwork|glulam|sheathing)\b", "06 Wood"),
        (r"\b(insulation|roof|waterproof|flashing|membrane|dampproof|sealant|caulk)\b", "07 Thermal & Moisture"),
        (r"\b(door|window|glaz|hardware|storefront|curtain wall|hatch)\b", "08 Openings"),
        (r"\b(drywall|gypsum|paint|tile|ceiling|acoustic|carpet|floor finish|plaster|vct|epoxy)\b", "09 Finishes"),
        (r"\b(specialt|locker|signage|accessor|partition|mirror)\b", "10 Specialties"),
        (r"\b(equipment|kitchen|lab casework|cooler)\b", "11 Equipment"),
        (r"\b(furnish|cabinet|casework|furniture|window treatment)\b", "12 Furnishings"),
        (r"\b(elevator|conveying|lift|escalator)\b", "14 Conveying"),
        (r"\b(sprinkler|fire protection|standpipe|suppression|fire alarm|firestopping)\b", "21 Fire Suppression"),
        (r"\b(plumbing|water heater|lavator|water closet|urinal|sink|domestic water|sanitary)\b", "22 Plumbing"),
        (r"\b(hvac|duct|chiller|boiler|rtu|vav|exhaust fan|air condition|heating|ventilat)\b", "23 HVAC"),
        (r"\b(electric|conduit|wire|panelboard|switchgear|light|fixture|receptacle|transformer|generator|photovolt|grounding)\b", "26 Electrical"),
        (r"\b(data|telecom|communication|fiber|cctv|security|access control|paging)\b", "27-28 Comm & Security"),
        (r"\b(water main|sanitary sewer|storm sewer|manhole|catch basin|culvert|force main|hydrant|utility)\b", "33 Utilities"),
        (r"\b(asphalt|paving|pavement|striping|marking|parking)\b", "32 Exterior Improvements"),
        (r"\b(landscap|irrigation|topsoil|seed|tree|fence|flagpole|riprap)\b", "32 Site Improvements"),
        (r"\b(process piping|wastewater|clarifier|blower|digester|sludge|bar screen|grit|aeration|disinfect)\b", "40-46 Process"),
        (r"\b(traffic|signal|rail|railroad|bridge)\b", "34 Transportation"),
    )
)

# Default annual escalation %, editable via --rates-file
DEFAULT_RATES: dict[str, float] = {
    "31 Earthwork": 3.5, "03 Concrete": 4.5, "04 Masonry": 4.0, "05 Metals": 3.5,
    "06 Wood": 3.0, "07 Thermal & Moisture": 4.0, "08 Openings": 4.5, "09 Finishes": 4.0,
    "10 Specialties": 4.0, "11 Equipment": 5.0, "12 Furnishings": 4.5, "14 Conveying": 4.5,
    "21 Fire Suppression": 5.0, "22 Plumbing": 5.0, "23 HVAC": 5.5, "26 Electrical": 5.5,
    "27-28 Comm & Security": 4.5, "33 Utilities": 3.5, "32 Exterior Improvements": 3.5,
    "32 Site Improvements": 3.5, "40-46 Process": 5.0, "34 Transportation": 4.0,
    "Unclassified": 4.0,
}

DELIMITERS = ("\t", "|", ",", ";")


# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------

@dataclass
class BidRow:
    bidder: str
    desc: str
    unit: str
    qty: float
    price: float
    trade: str
    item_no: str = ""
    note: str = ""          # "included" (INCL) or "excluded" (by others)


INCLUDED = re.compile(r"^\s*(incl\.?|included|inc\.?|in base( bid)?|"
                      r"n/c|no charge)\s*$", re.I)
EXCLUDED = re.compile(r"^\s*(excl\.?|excluded|by others|nic|n\.i\.c\.?|"
                      r"not included|no bid|n/b)\s*$", re.I)


@dataclass
class ItemStats:
    n: int
    low: float
    median: float
    mean: float
    high: float
    spread_pct: float


@dataclass
class Item:
    desc: str
    unit: str
    trade: str
    qty: float
    stats: ItemStats

    @property
    def flagged(self) -> bool:
        return self.stats.n > 1 and self.stats.spread_pct > 35.0


@dataclass
class Rollup:
    trade: str
    items: int
    extended_base: float
    extended_low: float
    extended_escalated: float
    avg_spread: float
    max_spread: float


@dataclass
class ColumnMap:
    index: dict[str, int] = field(default_factory=dict)
    delimiter: str = ","
    header_row: int = 0

    def get(self, name: str) -> int:
        return self.index.get(name, -1)


# --------------------------------------------------------------------------
# Parsing helpers
# --------------------------------------------------------------------------

def sniff_delimiter(lines: Sequence[str]) -> str:
    sample = "\n".join(lines[:5])
    return max(DELIMITERS, key=lambda d: sample.count(d))


def split_row(line: str, delimiter: str) -> list[str]:
    """CSV-aware split that respects quoted fields."""
    return next(csv.reader(io.StringIO(line), delimiter=delimiter))


def detect_columns(lines: Sequence[str]) -> ColumnMap:
    delimiter = sniff_delimiter(lines)
    best_row, best_score = 0, -1

    for i, line in enumerate(lines[:8]):
        cells = [c.strip().lower() for c in split_row(line, delimiter)]
        score = sum(
            1 for f in FIELDS
            if any(k in c for c in cells for k in HEADER_KEYWORDS[f])
        )
        if score > best_score:
            best_row, best_score = i, score

    header = [c.strip().lower() for c in split_row(lines[best_row], delimiter)]
    index: dict[str, int] = {}
    for f in FIELDS:
        for i, cell in enumerate(header):
            if any(cell == k or k in cell for k in HEADER_KEYWORDS[f]):
                index[f] = i
                break

    return ColumnMap(
        index=index,
        delimiter=delimiter,
        header_row=best_row if best_score >= 2 else 0,
    )


def parse_map(spec: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for part in spec.split(","):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k = k.strip().lower()
        if k in FIELDS:
            out[k] = int(v)
    return out


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


def normalize_desc(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip().strip("\"'")


def normalize_unit(text: str) -> str:
    key = re.sub(r"\.", "", str(text).strip().lower())
    return UNIT_ALIASES.get(key, str(text).strip().upper() or "EA")


def classify_trade(desc: str) -> str:
    for pattern, trade in TRADE_PATTERNS:
        if pattern.search(desc):
            return trade
    return "Unclassified"


def read_lines(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    return [ln for ln in text.replace("\r", "").split("\n") if ln.strip()]


def parse_file(path: Path, bidder: str | None, overrides: dict[str, int]) -> list[BidRow]:
    return parse_lines(read_lines(path), bidder or path.stem, overrides,
                       path.name)


def _cell(cells: Sequence[str], i: int) -> str | None:
    return cells[i] if 0 <= i < len(cells) else None


def parse_lines(lines: Sequence[str], default_bidder: str,
                overrides: dict[str, int], label: str = "bid tab") -> list[BidRow]:
    if not lines:
        return []

    cmap = detect_columns(lines)
    cmap.index.update(overrides)

    if cmap.get("desc") < 0:
        raise ValueError(
            f"{label}: could not find a description column. "
            f"Detected: {cmap.index}. Override with --map desc=N,unit=N,qty=N,price=N"
        )

    rows: list[BidRow] = []
    delim = cmap.delimiter

    for i, line in enumerate(lines):
        if i == cmap.header_row:
            continue
        cells = split_row(line, delim)
        if len(cells) <= cmap.get("desc"):
            continue

        desc = normalize_desc(cells[cmap.get("desc")])
        if not desc or desc.lower() in {"description", "item description"}:
            continue

        qty = to_float(_cell(cells, cmap.get("qty")))
        price = to_float(_cell(cells, cmap.get("price")))

        if price is None and cmap.get("total") >= 0 and qty:
            total = to_float(_cell(cells, cmap.get("total")))
            if total is not None:
                price = total / qty

        note = ""
        if price is None:
            raw = _cell(cells, cmap.get("price")) or \
                _cell(cells, cmap.get("total")) or ""
            if INCLUDED.match(raw):
                price, note = 0.0, "included"    # carried elsewhere
            elif EXCLUDED.match(raw):
                price, note = 0.0, "excluded"    # left out: an omission
            else:
                continue

        row_bidder = default_bidder
        if cmap.get("bidder") >= 0 and cmap.get("bidder") < len(cells):
            candidate = normalize_desc(cells[cmap.get("bidder")])
            if candidate:
                row_bidder = candidate

        rows.append(BidRow(
            bidder=row_bidder,
            desc=desc,
            unit=normalize_unit(_cell(cells, cmap.get("unit")) or "EA"),
            qty=qty or 1.0,
            price=price,
            trade=classify_trade(desc),
            item_no=normalize_desc(_cell(cells, cmap.get("item")) or ""),
            note=note,
        ))

    return rows


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------

def stats_of(prices: Sequence[float]) -> ItemStats:
    values = sorted(prices)
    n = len(values)
    median = statistics.median(values)
    spread = ((values[-1] - values[0]) / median * 100.0) if n > 1 and median else 0.0
    return ItemStats(
        n=n,
        low=values[0],
        median=median,
        mean=statistics.fmean(values),
        high=values[-1],
        spread_pct=spread,
    )


def group_items(rows: Iterable[BidRow]) -> list[Item]:
    groups: dict[tuple[str, str], list[BidRow]] = {}
    for row in rows:
        if row.note:                 # INCL / excluded lines aren't prices
            continue
        groups.setdefault((row.desc.lower(), row.unit), []).append(row)

    items = [
        Item(
            desc=members[0].desc,
            unit=members[0].unit,
            trade=members[0].trade,
            qty=members[0].qty,
            stats=stats_of([m.price for m in members]),
        )
        for members in groups.values()
    ]
    items.sort(key=lambda i: (i.trade, -i.stats.spread_pct))
    return items


def months_between(start: str, end: str) -> int:
    sy, sm = (int(x) for x in start.split("-"))
    ey, em = (int(x) for x in end.split("-"))
    return max(0, (ey - sy) * 12 + (em - sm))


def escalation_factor(trade: str, months: int, rates: dict[str, float], fallback: float) -> float:
    rate = rates.get(trade, DEFAULT_RATES.get(trade, fallback)) / 100.0
    return (1.0 + rate) ** (months / 12.0)


def build_rollup(items: Sequence[Item], months: int, rates: dict[str, float],
                 fallback: float) -> list[Rollup]:
    by_trade: dict[str, list[Item]] = {}
    for item in items:
        by_trade.setdefault(item.trade, []).append(item)

    rollup: list[Rollup] = []
    for trade, members in sorted(by_trade.items()):
        factor = escalation_factor(trade, months, rates, fallback)
        base = sum(m.stats.median * m.qty for m in members)
        rollup.append(Rollup(
            trade=trade,
            items=len(members),
            extended_base=base,
            extended_low=sum(m.stats.low * m.qty for m in members),
            extended_escalated=base * factor,
            avg_spread=statistics.fmean([m.stats.spread_pct for m in members]),
            max_spread=max(m.stats.spread_pct for m in members),
        ))
    return rollup


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def render(items: Sequence[Item], rollup: Sequence[Rollup], fmt: str,
           months: int, rates: dict[str, float], fallback: float) -> str:
    buf = io.StringIO()

    if fmt == "roll":
        writer = csv.writer(buf)
        writer.writerow(["Trade", "Items", "Extended_Base_Median", "Extended_Low",
                         "Extended_Escalated", "Avg_Spread_Pct", "Max_Spread_Pct"])
        for r in rollup:
            writer.writerow([r.trade, r.items, f"{r.extended_base:.2f}", f"{r.extended_low:.2f}",
                             f"{r.extended_escalated:.2f}", f"{r.avg_spread:.0f}", f"{r.max_spread:.0f}"])
        writer.writerow(["TOTAL", sum(r.items for r in rollup),
                         f"{sum(r.extended_base for r in rollup):.2f}",
                         f"{sum(r.extended_low for r in rollup):.2f}",
                         f"{sum(r.extended_escalated for r in rollup):.2f}", "", ""])
        return buf.getvalue()

    delimiter = "\t" if fmt == "tsv" else ","
    writer = csv.writer(buf, delimiter=delimiter)

    if fmt == "lib":
        writer.writerow(["Trade", "Item_Description", "Unit", "Unit_Cost", "Bids",
                         "Low", "High", "Factor", "Escalated_Unit_Cost"])
    else:
        writer.writerow(["Trade", "Item_Description", "Unit", "Bids", "Low", "Median",
                         "Mean", "High", "Spread_Pct", "Factor", "Escalated_Unit_Cost", "Flag"])

    for item in items:
        factor = escalation_factor(item.trade, months, rates, fallback)
        escalated = item.stats.median * factor
        if fmt == "lib":
            writer.writerow([item.trade, item.desc, item.unit, f"{item.stats.median:.2f}",
                             item.stats.n, f"{item.stats.low:.2f}", f"{item.stats.high:.2f}",
                             f"{factor:.3f}", f"{escalated:.2f}"])
        else:
            writer.writerow([item.trade, item.desc, item.unit, item.stats.n,
                             f"{item.stats.low:.2f}", f"{item.stats.median:.2f}",
                             f"{item.stats.mean:.2f}", f"{item.stats.high:.2f}",
                             f"{item.stats.spread_pct:.0f}", f"{factor:.3f}",
                             f"{escalated:.2f}", "REVIEW" if item.flagged else ""])
    return buf.getvalue()


SAMPLE = """Item,Description,Unit,Qty,Bidder,Unit Price
1,"Excavation, unclassified",CY,1200,Meridian Excavating,17.50
2,"Structural backfill, compacted",CY,800,Meridian Excavating,25.00
3,"Reinforced concrete footing",CY,150,Meridian Excavating,505.00
4,"Cast-in-place retaining wall, 12 in",SF,2400,Meridian Excavating,37.00
5,"Concrete sidewalk, 4 in",SF,3200,Meridian Excavating,7.10
6,"Reinforcing steel, in place",LB,18000,Meridian Excavating,1.12
7,"Storm sewer, RCP 18 in",LF,640,Meridian Excavating,56.00
8,"Catch basin, precast",EA,6,Meridian Excavating,3400.00
9,"Asphalt paving, 2 in",SF,8500,Meridian Excavating,3.35
10,"Painted pavement markings",LF,1800,Meridian Excavating,1.05
1,"Excavation, unclassified",CY,1200,Sage Civil,19.25
2,"Structural backfill, compacted",CY,800,Sage Civil,27.50
3,"Reinforced concrete footing",CY,150,Sage Civil,540.00
4,"Cast-in-place retaining wall, 12 in",SF,2400,Sage Civil,41.00
5,"Concrete sidewalk, 4 in",SF,3200,Sage Civil,7.80
6,"Reinforcing steel, in place",LB,18000,Sage Civil,1.24
7,"Storm sewer, RCP 18 in",LF,640,Sage Civil,61.00
8,"Catch basin, precast",EA,6,Sage Civil,3650.00
9,"Asphalt paving, 2 in",SF,8500,Sage Civil,3.60
10,"Painted pavement markings",LF,1800,Sage Civil,1.15
1,"Excavation, unclassified",CY,1200,Northline Grading,18.00
2,"Structural backfill, compacted",CY,800,Northline Grading,26.00
3,"Reinforced concrete footing",CY,150,Northline Grading,515.00
4,"Cast-in-place retaining wall, 12 in",SF,2400,Northline Grading,39.00
5,"Concrete sidewalk, 4 in",SF,3200,Northline Grading,7.40
6,"Reinforcing steel, in place",LB,18000,Northline Grading,1.18
7,"Storm sewer, RCP 18 in",LF,640,Northline Grading,58.50
8,"Catch basin, precast",EA,6,Northline Grading,5200.00
9,"Asphalt paving, 2 in",SF,8500,Northline Grading,3.45
10,"Painted pavement markings",LF,1800,Northline Grading,1.10
"""


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def current_month() -> str:
    today = date.today()
    return f"{today.year:04d}-{today.month:02d}"


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Turn public bid tab data into a local unit cost library.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("paths", nargs="*", type=Path, help="bid tab files (one per bidder, or one file with a bidder column)")
    p.add_argument("--bidder", help="bidder name when files carry no bidder column")
    p.add_argument("--map", default="", help="override columns, e.g. desc=2,unit=3,qty=4,price=5")
    p.add_argument("--from", dest="start", default="2024-06", metavar="YYYY-MM", help="date the bid tabs were bid")
    p.add_argument("--to", dest="end", default=current_month(), metavar="YYYY-MM", help="date to escalate to")
    p.add_argument("--global-rate", type=float, default=4.0, help="fallback annual escalation %% (default 4.0)")
    p.add_argument("--rates-file", type=Path, help="JSON file of per-trade annual rates")
    p.add_argument("--spread-flag", type=float, default=35.0, help="flag spread above this %% (default 35)")
    p.add_argument("--min-bids", type=int, default=1, help="drop items with fewer than N bids")
    p.add_argument("--format", choices=("lib", "full", "roll", "tsv"), default="lib")
    p.add_argument("--out", type=Path, help="output file (default stdout)")
    p.add_argument("--list-columns", action="store_true", help="show detected columns and exit")
    p.add_argument("--write-sample", type=Path, help="write a sample bid tab file and exit")
    args = p.parse_args(argv)

    if args.write_sample:
        args.write_sample.write_text(SAMPLE, encoding="utf-8")
        print(f"wrote {args.write_sample}")
        return 0

    if not args.paths:
        p.print_help()
        return 1

    overrides = parse_map(args.map)

    if args.list_columns:
        for path in args.paths:
            lines = read_lines(path)
            if not lines:
                continue
            cmap = detect_columns(lines)
            print(f"{path.name}: delimiter={cmap.delimiter!r} header_row={cmap.header_row}")
            print(f"  detected columns: {cmap.index}")
        return 0

    rows: list[BidRow] = []
    for path in args.paths:
        if not path.exists():
            print(f"missing: {path}", file=sys.stderr)
            continue
        rows.extend(parse_file(path, args.bidder, overrides))

    if not rows:
        print("no priced rows found", file=sys.stderr)
        return 1

    items = [i for i in group_items(rows) if i.stats.n >= args.min_bids]
    rates: dict[str, float] = {}
    if args.rates_file and args.rates_file.exists():
        rates = json.loads(args.rates_file.read_text(encoding="utf-8"))

    months = months_between(args.start, args.end)
    rollup = build_rollup(items, months, rates, args.global_rate)

    flagged = sum(1 for i in items if i.stats.n > 1 and i.stats.spread_pct > args.spread_flag)
    bidders = len({r.bidder for r in rows})

    print(
        f"{len(items)} items | {len(rows)} priced rows | {bidders} bidders | "
        f"{flagged} flagged | escalating {months} months",
        file=sys.stderr,
    )

    output = render(items, rollup, args.format, months, rates, args.global_rate)

    if args.out:
        args.out.write_text(output, encoding="utf-8")
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(output)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())