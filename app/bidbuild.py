"""Bid build-up: the markup cascade behind every proposal and SOV.

Based on your estimate.py. Each step is applied in order to a basis:

    direct    % of direct cost (general conditions)
    material  % of material cost (sales tax)
    subtotal  % of the running subtotal (overhead, profit, insurance ...)
    trade     extra margin % for named trades, on that trade's subtotal
    bond      surety premium on the FINAL contract amount (graduated
              schedule, or a flat %), so the bond covers the whole contract

Every step is tracked per line, so line prices, trade revenue and the
schedule of values add up to the bid to the cent. With only tax, overhead
and profit set it gives exactly the old proposal prices.
"""
import math
import re
from .dmoney import c2 as _c2

# Your BOND_TABLE as a graduated (marginal) schedule: the first $1M at 1.5%,
# the next $4M at 1.25% ... so the premium never drops as the contract grows.
BOND_TABLE = [(1_000_000, 1.50), (5_000_000, 1.25), (20_000_000, 1.00),
              (50_000_000, 0.85), (float("inf"), 0.75)]

# key, label, basis - the order they're applied in
STEPS = [("gc", "General conditions", "direct"),
         ("tax", "Sales tax on material", "material"),
         ("overhead", "Overhead", "subtotal"),
         ("profit", "Profit", "subtotal"),
         ("margins", "Trade margins", "trade"),
         ("insurance", "Insurance", "subtotal"),
         ("contingency", "Contingency", "subtotal"),
         ("escalation", "Escalation", "subtotal"),
         ("bond", "Bond", "bond")]
RATE_KEYS = [k for k, _l, b in STEPS if b not in ("trade", "bond")]


def bond_premium(contract, table=BOND_TABLE):
    prem, lo = 0.0, 0.0
    for hi, rate in table:
        if contract <= lo:
            break
        prem += (min(contract, hi) - lo) * rate / 100
        lo = hi
    return prem


def bond_rate(contract):
    """Effective bond % for a contract amount."""
    return bond_premium(contract) / contract * 100 if contract > 0 else 0.0


def parse_margins(spec):
    """'03 Concrete=14, 26 Electrical=6' -> {'03 Concrete': 14.0, ...}."""
    if isinstance(spec, dict):
        return {str(k).strip(): float(v) for k, v in spec.items()}
    out = {}
    for part in filter(None, (p.strip() for p in str(spec or "").split(","))):
        if "=" not in part:
            raise ValueError(f"bad margin '{part}' - use trade=percent")
        trade, value = part.rsplit("=", 1)
        out[trade.strip()] = float(value.strip().rstrip("%"))
    return out


def format_margins(margins):
    return ", ".join(f"{t}={v:g}" for t, v in margins.items())


def _num(v):
    """A rate or amount; 0 for blank or unreadable. NaN and infinity are
    unreadable too (torture test, Nov 10: an overhead of nan made the bid
    total nan)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0.0
    return f if math.isfinite(f) else 0.0


def _margin_for(trade, margins):
    """Exact trade name, else a CSI division prefix ('03' matches
    '03 Concrete' and '03 30 00 Cast-in-place')."""
    if trade in margins:
        return margins[trade]
    t = (trade or "").strip().lower()
    for k, v in margins.items():
        kk = k.strip().lower()
        if t == kk:
            return v
        m = re.match(r"(\d{2})\b", kk)
        if m and re.match(m.group(1) + r"\b", t):
            return v
    return 0.0


def build(lines, data, cents=True):
    """lines: [{"key", "trade", "direct", "material"}] (material is the
    material part of direct). data: rates in % (gc, tax, overhead, profit,
    insurance, contingency, escalation), "margins" (dict or text),
    "bond" ("none" | "auto" | "fixed") and "bond_rate".

    Returns {"steps": [{key, label, rate, amount, running}], "direct",
    "material", "total", "lines": [{..., "price"}], "by_trade"}."""
    margins = parse_margins(data.get("margins") or {})
    work = [dict(ln, direct=_num(ln.get("direct")),
                 material=_num(ln.get("material")),
                 price=_num(ln.get("direct"))) for ln in lines]
    direct = sum(w["direct"] for w in work)
    material = sum(w["material"] for w in work)
    running = direct
    steps = []
    for key, label, basis in STEPS:
        rate = _num(data.get(key)) if basis not in ("trade", "bond") else 0.0
        if basis == "trade":
            if not margins:
                continue
            amt = 0.0
            for w in work:
                a = w["price"] * _margin_for(w.get("trade"), margins) / 100
                w["price"] += a
                amt += a
            rate = amt / running * 100 if running else 0.0
        elif basis == "bond":
            mode = data.get("bond") or "none"
            if mode == "none":
                continue
            if mode == "fixed":
                flat = _num(data.get("bond_rate")) / 100
                # premium on the final contract: C = S + flat*C
                amt = running * flat / (1 - flat) if flat < 1 else 0.0
            else:
                amt = bond_premium(running)
                for _ in range(20):          # premium is on S + premium
                    nxt = bond_premium(running + amt)
                    if abs(nxt - amt) < 0.005:
                        amt = nxt
                        break
                    amt = nxt
            share = amt / running if running else 0.0
            for w in work:
                w["price"] *= 1 + share
            rate = amt / (running + amt) * 100 if running + amt else 0.0
        else:
            if not rate:
                continue
            amt = 0.0
            for w in work:
                b = w["direct"] if basis == "direct" else \
                    w["material"] if basis == "material" else w["price"]
                a = b * rate / 100
                w["price"] += a
                amt += a
        running += amt
        steps.append({"key": key, "label": label, "rate": rate,
                      "basis": basis, "amount": amt, "running": running})
    total = _c2(running)
    if cents:
        _cents(work, total)
    by_trade = {}
    for w in work:
        t = by_trade.setdefault(w.get("trade") or "General",
                                {"trade": w.get("trade") or "General",
                                 "direct": 0.0, "price": 0.0})
        t["direct"] += w["direct"]
        t["price"] += w["price"]
    for t in by_trade.values():
        t["share_pct"] = t["direct"] / direct * 100 if direct else 0.0
        t["margin_pct"] = ((t["price"] - t["direct"]) / t["price"] * 100
                           if t["price"] else 0.0)
        t["extra_margin_pct"] = _margin_for(t["trade"], margins)
    return {"steps": steps, "direct": direct, "material": material,
            "total": total, "lines": work,
            "by_trade": sorted(by_trade.values(), key=lambda t: t["trade"]),
            "uplift_pct": (total - direct) / direct * 100 if direct else 0.0}


def _cents(rows, total, key="price"):
    """Round to cents; put the penny drift on the largest row."""
    for r in rows:
        r[key] = _c2(r[key])
    if rows:
        big = max(rows, key=lambda r: abs(r[key]))
        big[key] = _c2(big[key] + total - sum(r[key] for r in rows))


# ---- front loading ------------------------------------------------------------

def timeline(values, months):
    """Earned value by month: the lines laid end to end in schedule order,
    each taking time in proportion to its value (a cost-loaded straight
    line schedule)."""
    return _rebill(values, values, months)


def npv(earned, discount=7.0, retention=10.0, payment_days=30,
        release_months=3):
    """Present value of the payments for work earned month by month: billed
    at each month end, paid `payment_days` later, retention released
    `release_months` after the last payment."""
    r = (1 + discount / 100) ** (1 / 12) - 1
    lag = payment_days / 30.0
    out = 0.0
    for m, v in enumerate(earned):
        out += v * (1 - retention / 100) / (1 + r) ** (m + 1 + lag)
    held = sum(earned) * retention / 100
    out += held / (1 + r) ** (len(earned) + lag + release_months)
    return out


def front_load(values, factor=0.06, months=12, discount=7.0, retention=10.0,
               payment_days=30):
    """Shift value from the last third of the schedule (by time) to the first
    third, keeping the total. values: scheduled values in schedule order.
    Returns the loaded values and the cash flow gain."""
    if not 0 <= factor < 0.5:
        raise ValueError("front-load factor must be between 0 and 0.5")
    total = sum(values)
    pos, mult = 0.0, []
    for v in values:
        mid = (pos + v / 2) / total if total else 0.0
        pos += v
        mult.append(1 + factor if mid < 1 / 3 else
                    1 - factor if mid > 2 / 3 else 1.0)
    raw = [v * k for v, k in zip(values, mult)]
    scale = total / sum(raw) if sum(raw) else 1.0
    loaded = [x * scale for x in raw]
    rows = [{"price": x} for x in loaded]
    _cents(rows, _c2(total))
    loaded = [r["price"] for r in rows]
    # value moves, time doesn't: the work earned each month is the same, the
    # billing against it follows the loaded values over the same timeline
    base_e = timeline(values, months)
    load_e = _rebill(values, loaded, months)
    base = npv(base_e, discount, retention, payment_days)
    new = npv(load_e, discount, retention, payment_days)
    change = [((l - v) / v * 100 if v else 0.0)
              for v, l in zip(values, loaded)]
    return {"values": loaded, "base_npv": base, "loaded_npv": new,
            "improvement": new - base,
            "improvement_pct": (new - base) / base * 100 if base else 0.0,
            "max_change_pct": max((abs(c) for c in change), default=0.0),
            "change_pct": change}


def _rebill(values, loaded, months):
    """Monthly billing when each line is billed at its loaded value as its
    work (on the original timeline) gets done."""
    months = max(1, int(months))
    total = sum(values)
    out = [0.0] * months
    if total <= 0:
        return out
    pos = 0.0
    for v, lv in zip(values, loaded):
        start, end = pos / total * months, (pos + v) / total * months
        pos += v
        m = int(start)
        while m < months and m < end:
            lo, hi = max(start, m), min(end, m + 1)
            if end > start:
                out[m] += lv * (hi - lo) / (end - start)
            m += 1
    return out
