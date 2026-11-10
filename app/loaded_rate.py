"""
labor.py (your loaded labor rate engine, used by QuantiSheet's Loaded Rate
Builder; the command-line version is tools/labor_rate.py)
========
Loaded labor rate engine.

Takes a base wage and builds the real hourly cost: fringes, payroll burden,
workers' comp, general liability, small tools, supervision, per diem. Then
applies productivity factors for site conditions and returns an effective
rate you can drop straight into a unit cost.

Base wage is typically only 55-65% of true loaded cost. This closes that gap.

Usage
-----
    python labor.py --trade Electrician --list-conditions
    python labor.py --trade Carpenter --base 34.00 --fringes 13.00
    python labor.py --trade Ironworker --conditions height=1.15,winter=1.12
    python labor.py --crew "4*Laborer,1*Foreman,0.5*Operator" --conditions night=1.10
    python labor.py --trade Plumber --json --out rate.json
    python labor.py --write-presets presets.json

Worker's comp varies enormously by state. Override with --wc.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence
from .dmoney import c2 as _c2

# --------------------------------------------------------------------------
# Defaults - national average, union-ish. Override everything.
# --------------------------------------------------------------------------

@dataclass
class TradePreset:
    base: float
    fringes: float
    wc: float          # workers' comp % of base+fringes


PRESETS: dict[str, TradePreset] = {
    "Apprentice":       TradePreset(20.00,  6.00, 10.0),
    "Laborer":          TradePreset(24.00,  9.50, 12.0),
    "Teamster":         TradePreset(28.00, 11.00, 13.0),
    "Painter":          TradePreset(28.00, 10.00,  9.0),
    "Roofer":           TradePreset(30.00, 11.00, 18.0),
    "Drywall Hanger":   TradePreset(30.00, 11.00, 12.0),
    "Tile Setter":      TradePreset(31.00, 11.50, 10.0),
    "Carpenter":        TradePreset(32.00, 12.50,  9.5),
    "Glazier":          TradePreset(32.00, 12.00, 12.5),
    "Cement Mason":     TradePreset(32.50, 12.00, 10.5),
    "Mason":            TradePreset(34.00, 12.00, 11.0),
    "Sheet Metal":      TradePreset(36.00, 13.00,  7.0),
    "Operating Engineer": TradePreset(36.00, 14.00, 8.0),
    "Plumber":          TradePreset(37.00, 13.50,  6.5),
    "Ironworker":       TradePreset(38.00, 15.50, 16.0),
    "Pipefitter":       TradePreset(38.00, 14.50,  7.5),
    "Electrician":      TradePreset(38.50, 14.00,  5.5),
    "Foreman":          TradePreset(44.00, 16.00,  8.0),
    "General Foreman":  TradePreset(50.00, 18.00,  8.0),
}

# Productivity multipliers. >1.0 means slower, so cost per unit goes UP.
CONDITIONS: dict[str, tuple[float, str]] = {
    "height":        (1.15, "Work above 12 ft"),
    "multi_story":   (1.10, "Upper floors, vertical transport"),
    "congested":     (1.12, "Tight site, material handling friction"),
    "occupied":      (1.15, "Occupied building, phased access"),
    "retrofit":      (1.20, "Renovation inside existing structure"),
    "night":         (1.10, "Night shift, lighting and fatigue"),
    "winter":        (1.12, "Cold weather protection"),
    "hot_weather":   (1.08, "Heat, hydration breaks"),
    "remote":        (1.10, "Remote site, logistics and morale"),
    "union_rules":   (1.05, "Restrictive work rules"),
    "accelerated":   (1.20, "Compressed schedule, stacking trades"),
    "small_qty":     (1.25, "Small quantities, no learning curve"),
    "high_finish":   (1.15, "High finish standard, rework exposure"),
}

DEFAULT_BURDEN_PCT = 22.0   # FICA, FUTA/SUTA, holiday, vacation, training
DEFAULT_GL_PCT = 2.5        # general liability / umbrella
DEFAULT_TOOLS_PCT = 1.5     # small tools and consumables
DEFAULT_SUPER_PCT = 0.0     # set if you carry supervision in the rate


# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------

@dataclass
class LoadedRate:
    trade: str
    base: float
    fringes: float
    burden_pct: float
    wc_pct: float
    gl_pct: float
    tools_pct: float
    super_pct: float
    per_diem: float
    conditions: dict[str, float] = field(default_factory=dict)

    @property
    def productivity(self) -> float:
        factor = 1.0
        for mult in self.conditions.values():
            factor *= mult
        return factor

    def breakdown(self) -> dict[str, float]:
        direct = self.base + self.fringes
        burden = direct * self.burden_pct / 100
        wc = direct * self.wc_pct / 100
        gl = direct * self.gl_pct / 100
        tools = direct * self.tools_pct / 100
        supervision = direct * self.super_pct / 100
        loaded = direct + burden + wc + gl + tools + supervision + self.per_diem
        # a factor above 1.0 means slower work, so the cost of the work goes
        # UP: multiply (dividing, as before, made "height=1.15" 13% cheaper)
        effective = loaded * self.productivity
        return {
            "base": self.base,
            "fringes": self.fringes,
            "direct": direct,
            "burden": burden,
            "workers_comp": wc,
            "general_liability": gl,
            "small_tools": tools,
            "supervision": supervision,
            "per_diem": self.per_diem,
            "loaded_rate": loaded,
            "productivity_factor": self.productivity,
            "effective_rate": effective,
            "burden_pct_of_loaded": (loaded - direct) / loaded * 100 if loaded else 0.0,
        }


def parse_conditions(spec: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for part in filter(None, (p.strip() for p in spec.split(","))):
        if "=" not in part:
            raise SystemExit(f"bad condition '{part}' - use name=factor, e.g. winter=1.12")
        name, value = part.split("=", 1)
        name = name.strip()
        if name not in CONDITIONS:
            raise SystemExit(
                f"unknown condition '{name}'. Known: {', '.join(sorted(CONDITIONS))}"
            )
        out[name] = float(value)
    return out


def resolve_conditions(spec: str, use_defaults: bool) -> dict[str, float]:
    explicit = parse_conditions(spec)
    if not use_defaults:
        return explicit
    merged = {k: v[0] for k, v in CONDITIONS.items() if k in explicit}
    for name, factor in explicit.items():
        merged[name] = factor
    return merged


# --------------------------------------------------------------------------
# Crew
# --------------------------------------------------------------------------

@dataclass
class CrewMember:
    count: float
    trade: str


def parse_crew(spec: str) -> list[CrewMember]:
    crew: list[CrewMember] = []
    for part in filter(None, (p.strip() for p in spec.split(","))):
        if "*" not in part:
            raise SystemExit(f"bad crew member '{part}' - use count*Trade, e.g. 4*Laborer")
        count, trade = part.split("*", 1)
        trade = trade.strip()
        if trade not in PRESETS:
            raise SystemExit(f"unknown trade '{trade}'. Use --list-trades.")
        crew.append(CrewMember(float(count), trade))
    return crew


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def print_breakdown(rate: LoadedRate, as_json: bool) -> None:
    b = rate.breakdown()
    if as_json:
        print(json.dumps({"trade": rate.trade, **b, "conditions": rate.conditions}, indent=2))
        return

    print(f"\n{rate.trade}")
    print("-" * 46)
    print(f"  base wage                     {_c2(b['base']):>10,.2f}")
    print(f"  fringes                       {_c2(b['fringes']):>10,.2f}")
    print(f"  direct (base + fringes)       {_c2(b['direct']):>10,.2f}")
    print(f"  payroll burden  {rate.burden_pct:>5.1f}%         {_c2(b['burden']):>10,.2f}")
    print(f"  workers' comp   {rate.wc_pct:>5.1f}%         {_c2(b['workers_comp']):>10,.2f}")
    print(f"  general liab.   {rate.gl_pct:>5.1f}%         {_c2(b['general_liability']):>10,.2f}")
    print(f"  small tools     {rate.tools_pct:>5.1f}%         {_c2(b['small_tools']):>10,.2f}")
    if rate.super_pct:
        print(f"  supervision     {rate.super_pct:>5.1f}%         {_c2(b['supervision']):>10,.2f}")
    if rate.per_diem:
        print(f"  per diem                      {_c2(b['per_diem']):>10,.2f}")
    print("-" * 46)
    print(f"  LOADED RATE                   {_c2(b['loaded_rate']):>10,.2f} /hr")
    if rate.conditions:
        print(f"\n  productivity factor           {b['productivity_factor']:>10,.3f}")
        for name, mult in rate.conditions.items():
            print(f"    {name:<14} x{mult:.3f}   {CONDITIONS[name][1]}")
    print(f"\n  EFFECTIVE RATE                {_c2(b['effective_rate']):>10,.2f} /hr")
    print(f"  burden is {b['burden_pct_of_loaded']:.0f}% of loaded cost\n")


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Build a loaded labor rate from a base wage.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--trade", help="trade name (see --list-trades)")
    p.add_argument("--crew", help='crew spec, e.g. "4*Laborer,1*Foreman"')
    p.add_argument("--base", type=float, help="override base wage")
    p.add_argument("--fringes", type=float, help="override fringes")
    p.add_argument("--burden", type=float, default=DEFAULT_BURDEN_PCT, help="payroll burden %%")
    p.add_argument("--wc", type=float, help="workers' comp %% (state specific)")
    p.add_argument("--gl", type=float, default=DEFAULT_GL_PCT, help="general liability %%")
    p.add_argument("--tools", type=float, default=DEFAULT_TOOLS_PCT, help="small tools %%")
    p.add_argument("--supervision", type=float, default=DEFAULT_SUPER_PCT, help="supervision %%")
    p.add_argument("--per-diem", type=float, default=0.0, help="$/hr per diem")
    p.add_argument("--conditions", default="", help="e.g. height=1.15,night=1.10")
    p.add_argument("--presets", type=Path, help="JSON file overriding trade presets")
    p.add_argument("--write-presets", type=Path, help="dump default presets and exit")
    p.add_argument("--list-trades", action="store_true")
    p.add_argument("--list-conditions", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    if args.write_presets:
        data = {k: vars(v) for k, v in PRESETS.items()}
        args.write_presets.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"wrote {args.write_presets}")
        return 0

    presets = dict(PRESETS)
    if args.presets and args.presets.exists():
        for name, vals in json.loads(args.presets.read_text(encoding="utf-8")).items():
            presets[name] = TradePreset(**vals)

    if args.list_trades:
        for name, preset in sorted(presets.items()):
            print(f"{name:<22} base {_c2(preset.base):>7.2f}  fringes {_c2(preset.fringes):>6.2f}  wc {preset.wc:>5.1f}%")
        return 0

    if args.list_conditions:
        for name, (factor, note) in sorted(CONDITIONS.items()):
            print(f"{name:<14} x{_c2(factor):.2f}   {note}")
        return 0

    conditions = parse_conditions(args.conditions)

    def build(trade: str, base: float | None, fringes: float | None, wc: float | None) -> LoadedRate:
        preset = presets.get(trade, TradePreset(0.0, 0.0, 0.0))
        return LoadedRate(
            trade=trade,
            base=base if base is not None else preset.base,
            fringes=fringes if fringes is not None else preset.fringes,
            burden_pct=args.burden,
            wc_pct=wc if wc is not None else preset.wc,
            gl_pct=args.gl,
            tools_pct=args.tools,
            super_pct=args.supervision,
            per_diem=args.per_diem,
            conditions=conditions,
        )

    if args.crew:
        crew = parse_crew(args.crew)
        rates = [build(m.trade, None, None, None) for m in crew]
        hours = sum(m.count for m in crew)
        blended_loaded = sum(r.breakdown()["loaded_rate"] * m.count for r, m in zip(rates, crew)) / hours
        blended_effective = sum(r.breakdown()["effective_rate"] * m.count for r, m in zip(rates, crew)) / hours

        if args.json:
            print(json.dumps({
                "crew": args.crew,
                "headcount": hours,
                "blended_loaded_rate": blended_loaded,
                "blended_effective_rate": blended_effective,
                "members": [
                    {"count": m.count, "trade": m.trade, **r.breakdown()}
                    for m, r in zip(crew, rates)
                ],
            }, indent=2))
        else:
            for m, r in zip(crew, rates):
                b = r.breakdown()
                print(f"{m.count:>4.1f} x {m.trade:<20} loaded {_c2(b['loaded_rate']):>9,.2f}  effective {_c2(b['effective_rate']):>9,.2f}")
            print("-" * 60)
            print(f"     crew hours {hours:>6.1f}            blended loaded {_c2(blended_loaded):>9,.2f}")
            print(f"{'':>36}blended effective {_c2(blended_effective):>9,.2f}\n")
        return 0

    if not args.trade:
        p.print_help()
        return 1

    rate = build(args.trade, args.base, args.fringes, args.wc)
    print_breakdown(rate, args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())