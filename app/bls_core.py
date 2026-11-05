"""
bls.py (your BLS PPI tool, used by QuantiSheet's Escalation window; the
command-line version is tools/bls.py)
======
Fetch BLS Producer Price Index series and turn them into escalation factors.

Replaces guessed escalation rates with real, citable data. No API key needed
for the public endpoint (25 series per query, 10 years). Add a free
registration key for 50 series and 20 years.

Usage
-----
    python bls.py --list
    python bls.py --fetch --start 2023 --end 2026 --cache ppi.json
    python bls.py --factor --from 2024-06 --to 2026-10
    python bls.py --emit-rates rates.json --from 2024-06 --to 2026-10
    python bls.py --fetch --offline          # use cache only

The BLS API does not return series titles, so verify any series ID at
https://data.bls.gov/timeseries/<SERIES_ID> before you publish a number.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import Sequence

API = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

# Series ID -> (title, bidtab trade(s) for --emit-rates).
# IDs and titles checked against the AGC monthly PPI tables
# (https://www.agc.org/sites/default/files/users/user21902/PPI%20Tables%202026_08.pdf)
# and fetched live from the BLS API on 2026-10-14 (all returned data through
# 2026-08). The contractor IDs need the full form (PCU23811X23811X), and
# WPU1321 is sand/gravel/crushed stone - cement is WPU1322.
DEFAULT_SERIES: dict[str, tuple[str, object]] = {
    "PCU23811X23811X": ("Concrete contractors, nonresidential building work",
                        "03 Concrete"),
    "WPU1333":     ("Ready-mixed concrete",                  "03 Concrete"),
    "WPU1322":     ("Cement",                                "03 Concrete"),
    "WPU1331":     ("Concrete block and brick",              "04 Masonry"),
    "WPU1017":     ("Steel mill products",                   "05 Metals"),
    "WPU107405":   ("Fabricated structural metal",           "05 Metals"),
    "WPUSI004011": ("Lumber and plywood",                    "06 Wood"),
    "PCU23816X23816X": ("Roofing contractors, nonresidential building work",
                        "07 Thermal & Moisture"),
    "WPU1392":     ("Insulation materials",                  "07 Thermal & Moisture"),
    "WPU1311":     ("Flat glass",                            "08 Openings"),
    "WPU13710102": ("Gypsum building materials",             "09 Finishes"),
    "WPU062101":   ("Architectural coatings",                "09 Finishes"),
    "PCU23822X23822X": ("Plumbing contractors, nonresidential building work",
                        ("22 Plumbing", "21 Fire Suppression")),
    "WPU1073":     ("Sheet metal products",                  "23 HVAC"),
    "WPU101706":   ("Steel pipe and tube",                   ("23 HVAC", "21 Fire Suppression", "40-46 Process")),
    "PCU23821X23821X": ("Electrical contractors, nonresidential building work",
                        ("26 Electrical", "27-28 Comm & Security")),
    "WPU102502":   ("Copper and brass mill shapes",          ("26 Electrical", "22 Plumbing")),
    "WPU1321":     ("Construction sand, gravel and crushed stone", "31 Earthwork"),
    "WPU1394":     ("Paving mixtures and blocks (asphalt)",  "32 Exterior Improvements"),
    "WPU1332":     ("Concrete pipe",                         "33 Utilities"),
    "WPU0721":     ("Plastic construction products",         "33 Utilities"),
    "WPU112":      ("Construction machinery and equipment",  "40-46 Process"),
    "WPU801":      ("New nonresidential building construction", "Unclassified"),
    "WPUIP231200": ("Inputs to new nonresidential construction", "Unclassified"),
}


def trades_of(entry) -> tuple[str, ...]:
    t = entry[1]
    return tuple(t) if isinstance(t, (list, tuple)) else (t,)


# --------------------------------------------------------------------------
# Fetch
# --------------------------------------------------------------------------

def fetch_series(series_ids: Sequence[str], start: int, end: int,
                 key: str | None) -> dict[str, dict[str, float]]:
    body = {"seriesid": list(series_ids), "startyear": str(start), "endyear": str(end)}
    if key:
        body["registrationkey"] = key

    request = urllib.request.Request(
        API,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    from . import policy
    policy.check("rates", API)
    with urllib.request.urlopen(request, timeout=45) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if payload.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"BLS returned {payload.get('status')}: {payload.get('message')}")

    out: dict[str, dict[str, float]] = {}
    for series in payload["Results"]["series"]:
        points: dict[str, float] = {}
        for entry in series.get("data", []):
            period = entry.get("period", "")
            if not period.startswith("M") or period == "M13":   # skip annual average
                continue
            ym = f"{entry['year']}-{int(period[1:]):02d}"
            try:
                points[ym] = float(entry["value"])
            except (KeyError, ValueError):
                continue
        out[series["seriesID"]] = dict(sorted(points.items()))
    return out


def load_cache(path: Path) -> dict[str, dict[str, float]]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------

def value_at(points: dict[str, float], ym: str) -> tuple[float, str] | None:
    """Nearest observation at or before ym; falls back to the earliest."""
    if not points:
        return None
    keys = sorted(points)
    candidates = [k for k in keys if k <= ym]
    chosen = candidates[-1] if candidates else keys[0]
    return points[chosen], chosen


def months_between(a: str, b: str) -> int:
    ay, am = (int(x) for x in a.split("-"))
    by, bm = (int(x) for x in b.split("-"))
    return (by - ay) * 12 + (bm - am)


def cagr(points: dict[str, float], window_months: int = 12) -> float:
    """Annualised growth over the trailing window."""
    keys = sorted(points)
    if len(keys) < 2:
        return 0.0
    end_ym = keys[-1]
    target = keys[0]
    ey, em = (int(x) for x in end_ym.split("-"))
    total = em + ey * 12
    cutoff = total - window_months
    prior = [k for k in keys if (int(k.split("-")[1]) + int(k.split("-")[0]) * 12) <= cutoff]
    start_ym = prior[-1] if prior else target
    months = months_between(start_ym, end_ym)
    if months <= 0 or points[start_ym] <= 0:
        return 0.0
    return ((points[end_ym] / points[start_ym]) ** (12 / months) - 1) * 100


# Projecting the trailing growth rate further than this past the last
# published month is a guess, not data; the projection stops here.
MAX_EXTRAPOLATE_MONTHS = 24


def escalation(points: dict[str, float], start_ym: str, end_ym: str) -> dict:
    """Factor from start to end, extrapolating past the last observation
    (at most MAX_EXTRAPOLATE_MONTHS). "warnings" says when the projection
    was capped or a month before the data had to use the first point."""
    warnings: list[str] = []
    start = value_at(points, start_ym)
    end = value_at(points, end_ym)
    if not start or not end:
        return {"factor": 1.0, "observed": 0.0, "annual_pct": 0.0,
                "extrapolated": 0, "capped": False,
                "warnings": ["no data for this series"]}
    first_ym = sorted(points)[0]
    if start_ym < first_ym:
        warnings.append(f"start {start_ym} is before the first data month "
                        f"{first_ym}; {first_ym} was used")
    if end_ym < first_ym:
        warnings.append(f"end {end_ym} is before the first data month "
                        f"{first_ym}; {first_ym} was used")

    factor = end[0] / start[0]
    observed = factor
    last_ym = sorted(points)[-1]
    extrapolated = 0
    capped = False

    if end_ym > last_ym:
        extra = months_between(last_ym, end_ym)
        if extra > MAX_EXTRAPOLATE_MONTHS:
            warnings.append(f"projection capped at {MAX_EXTRAPOLATE_MONTHS} "
                            f"months past {last_ym} (asked for {extra})")
            extra = MAX_EXTRAPOLATE_MONTHS
            capped = True
        rate = cagr(points) / 100.0
        factor *= (1 + rate) ** (extra / 12)
        extrapolated = extra

    # annualise over the span the factor actually covers: past the cap the
    # factor stops growing, so the asked-for span would understate the
    # rate (review 3 #14)
    months = months_between(start_ym, end_ym)
    if capped:
        months = months_between(start_ym, last_ym) + extrapolated
    annual = ((factor ** (12 / months)) - 1) * 100 if months > 0 else 0.0
    return {"factor": factor, "observed": observed, "annual_pct": annual,
            "extrapolated": extrapolated, "capped": capped,
            "warnings": warnings}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def current_month() -> str:
    today = date.today()
    return f"{today.year:04d}-{today.month:02d}"


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Fetch BLS PPI series and build escalation factors.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--fetch", action="store_true", help="pull series and update the cache")
    p.add_argument("--offline", action="store_true", help="use the cache only")
    p.add_argument("--series", help="comma separated series IDs (default: built-in map)")
    p.add_argument("--start", type=int, default=date.today().year - 3)
    p.add_argument("--end", type=int, default=date.today().year)
    p.add_argument("--key", help="BLS registration key (optional)")
    p.add_argument("--cache", type=Path, default=Path("ppi_cache.json"))
    p.add_argument("--factor", action="store_true", help="print escalation factors")
    p.add_argument("--from", dest="start_ym", default="2024-01", metavar="YYYY-MM")
    p.add_argument("--to", dest="end_ym", default=current_month(), metavar="YYYY-MM")
    p.add_argument("--emit-rates", type=Path, help="write a rates.json for bidtab.py")
    p.add_argument("--list", action="store_true", help="show the built-in series map")
    args = p.parse_args(argv)

    if args.list:
        for sid, entry in DEFAULT_SERIES.items():
            print(f"{sid:<16} {entry[0][:44]:<44} -> {', '.join(trades_of(entry))}")
        print("\nVerify each at https://data.bls.gov/timeseries/<SERIES_ID>")
        return 0

    series_map = DEFAULT_SERIES
    if args.series:
        series_map = {sid.strip(): (sid.strip(), sid.strip()) for sid in args.series.split(",")}

    cache = load_cache(args.cache)

    if args.fetch and not args.offline:
        try:
            fresh = fetch_series(list(series_map), args.start, args.end, args.key)
            for sid, points in fresh.items():
                cache.setdefault(sid, {}).update(points)
                cache[sid] = dict(sorted(cache[sid].items()))
            args.cache.write_text(json.dumps(cache, indent=2), encoding="utf-8")
            print(f"fetched {len(fresh)} series -> {args.cache}", file=sys.stderr)
        except (urllib.error.URLError, RuntimeError, TimeoutError) as exc:
            print(f"fetch failed ({exc}); using cache", file=sys.stderr)

    if not cache:
        print("no cached data - run with --fetch first", file=sys.stderr)
        return 1

    missing = [sid for sid in series_map if sid not in cache]
    for sid in missing:
        print(f"  ! {sid} not in cache (check the series ID)", file=sys.stderr)

    if not (args.factor or args.emit_rates):
        p.print_help()
        return 0

    rates: dict[str, float] = {}
    print(f"\nescalation {args.start_ym} -> {args.end_ym}\n")
    print(f"{'series':<12} {'label':<34} {'factor':>8} {'%/yr':>7}  note")
    print("-" * 78)

    collected: dict[str, list[float]] = {}
    for sid, entry in series_map.items():
        label = entry[0]
        points = cache.get(sid)
        if not points:
            continue
        result = escalation(points, args.start_ym, args.end_ym)
        note = f"extrapolated {result['extrapolated']} mo" if result["extrapolated"] else ""
        if result["warnings"]:
            note = (note + "  " if note else "") + "; ".join(result["warnings"])
        print(f"{sid:<12} {label[:34]:<34} {result['factor']:>8.3f} "
              f"{result['annual_pct']:>7.2f}  {note}")
        for trade in trades_of(entry):
            collected.setdefault(trade, []).append(result["annual_pct"])
    # every series for a trade counts equally (the old pairwise average
    # weighted the last series at 50%)
    rates = {t: sum(v) / len(v) for t, v in collected.items()}

    if args.emit_rates:
        rounded = {k: round(v, 2) for k, v in rates.items()}
        args.emit_rates.write_text(json.dumps(rounded, indent=2), encoding="utf-8")
        print(f"\nwrote {args.emit_rates}")
        print("use it with:  python bidtab.py bids/*.csv --rates-file " + str(args.emit_rates))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())