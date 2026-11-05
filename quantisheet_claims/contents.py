"""The contents list (Coverage C - business personal property on a
commercial claim), ClaimIT 0.2.2.

Each item: quantity x replacement cost each = RCV; less its depreciation
% = ACV. Paid now = ACV, less the contents deductible, up to the
contents limit. Paid in full = RCV (replacement-cost policy, after the
items are replaced) or ACV (actual-cash-value policy), the same way. The
difference is the contents holdback. All whole cents, one rounding per
step. The policy on the claim always wins: every number is an input.
"""
from __future__ import annotations

import dataclasses

from . import model as m
from .cents import MoneyError, apply_bp, parse_money, to_bp


class ContentsError(ValueError):
    pass


def item_rcv(it: m.ContentsItem) -> int:
    return it.qty * it.unit_rc_cents


def item_dep(it: m.ContentsItem) -> int:
    return apply_bp(item_rcv(it), it.dep_bp)


def item_acv(it: m.ContentsItem) -> int:
    return item_rcv(it) - item_dep(it)


def _limit(v: int, cov: m.ContentsCoverage) -> int:
    v = max(0, v - min(v, cov.deductible_cents))
    return v if cov.limit_cents is None else min(v, cov.limit_cents)


def totals(claim: m.Claim) -> dict:
    cov = claim.contents_cov
    rcv = sum(item_rcv(i) for i in claim.contents)
    dep = sum(item_dep(i) for i in claim.contents)
    acv = rcv - dep
    now = _limit(acv, cov) if claim.contents else 0
    full = _limit(rcv if cov.valuation == "rc" else acv, cov) \
        if claim.contents else 0
    ded = min(acv, cov.deductible_cents) if claim.contents else 0
    over = 0
    if cov.limit_cents is not None and claim.contents:
        base = rcv if cov.valuation == "rc" else acv
        over = max(0, base - min(base, cov.deductible_cents)
                   - cov.limit_cents)
    return {"rcv": rcv, "dep": dep, "acv": acv, "deductible": ded,
            "now": now, "full": full, "holdback": max(0, full - now),
            "over_limit": over, "count": len(claim.contents)}


def _dep(dep_pct) -> int:
    try:
        bp = to_bp(str(dep_pct).strip().rstrip("%") or "0")
    except Exception as e:                                # noqa: BLE001
        raise ContentsError(f"depreciation {dep_pct!r} is not a number") \
            from e
    if not 0 <= bp <= 10_000:
        raise ContentsError("depreciation must be 0 to 100%")
    return bp


def make_item(description, qty="1", unit_cost="0", dep_pct="0", room_id="",
              age="", note="", item_id=None) -> m.ContentsItem:
    d = " ".join(str(description or "").split())
    if not d:
        raise ContentsError("an item needs a description")
    try:
        q = int(str(qty).strip() or "1")
    except ValueError as e:
        raise ContentsError(f"quantity {qty!r} must be a whole number") from e
    if not 1 <= q <= 100_000:
        raise ContentsError("quantity must be 1 to 100,000")
    try:
        unit = parse_money(str(unit_cost).strip().lstrip("$") or "0")
    except (MoneyError, Exception) as e:                  # noqa: BLE001
        raise ContentsError(f"cost {unit_cost!r} is not an amount") from e
    if unit < 0:
        raise ContentsError("the cost can't be negative")
    return m.ContentsItem(id=item_id or m.new_id(), description=d[:200],
                          qty=q, unit_rc_cents=unit, dep_bp=_dep(dep_pct),
                          room_id=room_id or "", age=str(age or "")[:30],
                          note=str(note or "")[:200])


def add_item(claim: m.Claim, *a, **kw) -> tuple:
    return claim.contents + (make_item(*a, **kw),)


def replace_item(claim: m.Claim, item: m.ContentsItem) -> tuple:
    return tuple(item if i.id == item.id else i for i in claim.contents)


def remove_item(claim: m.Claim, item_id: str) -> tuple:
    return tuple(i for i in claim.contents if i.id != item_id)


def coverage(limit="", valuation="rc", deductible="") -> m.ContentsCoverage:
    if valuation not in m.CONTENTS_VALUATIONS:
        raise ContentsError("valuation must be rc or acv")
    try:
        lim = None if not str(limit).strip() else \
            parse_money(str(limit).strip().lstrip("$"))
        ded = parse_money(str(deductible).strip().lstrip("$") or "0")
    except Exception as e:                                # noqa: BLE001
        raise ContentsError("limit and deductible must be amounts") from e
    if (lim is not None and lim < 0) or ded < 0:
        raise ContentsError("amounts can't be negative")
    return m.ContentsCoverage(limit_cents=lim, valuation=valuation,
                              deductible_cents=ded)


def label(claim: m.Claim) -> str:
    return ("Business personal property" if claim.claim_type == "commercial"
            else "Contents (Coverage C)")


