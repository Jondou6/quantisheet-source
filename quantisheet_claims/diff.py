"""Revision diff and supplement totals (brief 3.9).

Fixes: key is the stable line id, so the same item in two rooms stays two
lines (f.10) and a move between groups is 'regrouped' (f.11); the qty and
price parts are split exactly, no double-counted cross term (f.7); reason
starts as None so 'unexplained' really counts (f.8); net due counts O&L,
ALE/BI and payments already made (f.24).
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Optional

from .cents import apply_bp, apply_qty, fmt
from .settle import settle_claim

# offered in the window as suggestions only - never filled in automatically
SUGGESTED_REASONS = {
    "added": "hidden damage",
    "qty_up": "hidden damage",
    "qty_down": "measurement correction",
    "price": "price list update",
    "dep": "condition / age review",
    "removed": "over-measured",
    "regrouped": "moved to the right group",
}


class UnexplainedChanges(Exception):
    pass


@dataclass(frozen=True)
class Change:
    line_id: str
    kind: str                  # added/removed/qty/price/qty_price/dep/regrouped
    description: str
    rc_delta: int = 0
    qty_part: int = 0
    price_part: int = 0
    dep_delta: int = 0
    old_group: str = ""
    new_group: str = ""
    reason: Optional[str] = None
    included: bool = True

    def suggestion(self) -> str:
        k = self.kind
        if k in ("qty", "qty_price"):
            k = "qty_up" if self.qty_part >= 0 else "qty_down"
        return SUGGESTED_REASONS.get(k, "")


def _where(ln) -> tuple:
    return (ln.structure_id, ln.group_id, ln.room_id)


def diff(old_lines, new_lines) -> tuple[Change, ...]:
    old = {ln.id: ln for ln in old_lines}
    new = {ln.id: ln for ln in new_lines}
    if len(old) != len(tuple(old_lines)) or len(new) != len(tuple(new_lines)):
        raise ValueError("duplicate line id")
    out: list[Change] = []
    order = [ln.id for ln in old_lines] + [ln.id for ln in new_lines
                                           if ln.id not in old]
    for lid in order:
        a, b = old.get(lid), new.get(lid)
        if a is None:
            out.append(Change(lid, "added", b.description, rc_delta=b.rc,
                              new_group=b.group_id,
                              dep_delta=apply_bp(b.rc, b.dep_bp)))
            continue
        if b is None:
            out.append(Change(lid, "removed", a.description, rc_delta=-a.rc,
                              old_group=a.group_id,
                              dep_delta=-apply_bp(a.rc, a.dep_bp)))
            continue
        if _where(a) != _where(b):
            out.append(Change(lid, "regrouped", b.description,
                              old_group=a.group_id, new_group=b.group_id))
        p0, p1, q0, q1 = a.unit_cost.total, b.unit_cost.total, a.qty_q4, b.qty_q4
        if (p0, q0) != (p1, q1):
            qty_part = apply_qty(p0, q1) - apply_qty(p0, q0)
            price_part = apply_qty(p1, q1) - apply_qty(p0, q1)
            kind = ("qty_price" if (q0 != q1 and p0 != p1)
                    else "qty" if q0 != q1 else "price")
            out.append(Change(lid, kind, b.description,
                              rc_delta=qty_part + price_part,
                              qty_part=qty_part, price_part=price_part,
                              dep_delta=apply_bp(b.rc, b.dep_bp)
                              - apply_bp(a.rc, a.dep_bp)))
        elif a.dep_bp != b.dep_bp:
            out.append(Change(lid, "dep", b.description,
                              dep_delta=apply_bp(b.rc, b.dep_bp)
                              - apply_bp(b.rc, a.dep_bp)))
    return tuple(out)


def set_reason(changes, index: int, reason: Optional[str]) -> tuple[Change, ...]:
    r = (reason or "").strip() or None
    return tuple(dataclasses.replace(c, reason=r) if i == index else c
                 for i, c in enumerate(changes))


def unexplained(changes) -> list[Change]:
    return [c for c in changes if c.included and c.reason is None]


def check_final(changes) -> None:
    left = unexplained(changes)
    if left:
        raise UnexplainedChanges(f"{len(left)} change(s) still need a reason")


@dataclass(frozen=True)
class SupplementTotals:
    rc: int
    op: int
    ol: int
    rcv: int
    dep: int
    acv: int
    net: int
    ale_or_bi: int
    total_indemnity: int
    payments_made: int
    net_due: int


def supplement_totals(old_claim, new_claim,
                      payments_made: Optional[int] = None) -> SupplementTotals:
    """Difference of every settlement step. net_due = new total indemnity
    (property + O&L + ALE or BI/EE) minus payments already made. If no
    payment figure is entered, the old total is taken as paid."""
    o, n = settle_claim(old_claim), settle_claim(new_claim)
    paid = o.total_indemnity if payments_made is None else payments_made
    return SupplementTotals(
        rc=n.rc - o.rc, op=n.op - o.op, ol=n.ol - o.ol, rcv=n.rcv - o.rcv,
        dep=n.dep - o.dep, acv=n.acv - o.acv, net=n.net - o.net,
        ale_or_bi=(n.ale + n.bi_ee) - (o.ale + o.bi_ee),
        total_indemnity=n.total_indemnity - o.total_indemnity,
        payments_made=paid, net_due=n.total_indemnity - paid)


def render_text(changes, totals: SupplementTotals) -> str:
    rows = ["Supplement", ""]
    for c in changes:
        if not c.included:
            continue
        extra = ""
        if c.kind == "qty_price":
            extra = f" (qty {fmt(c.qty_part)} + price {fmt(c.price_part)})"
        rows.append(f"{c.kind:<10} {c.description[:40]:<40} {fmt(c.rc_delta):>14}"
                    f"{extra}  reason: {c.reason or 'NEEDS A REASON'}")
    rows += ["", f"RC change      {fmt(totals.rc)}", f"O&P change     {fmt(totals.op)}",
             f"O&L change     {fmt(totals.ol)}", f"Dep change     {fmt(totals.dep)}",
             f"ACV change     {fmt(totals.acv)}",
             f"Payments made  {fmt(totals.payments_made)}",
             f"Net due        {fmt(totals.net_due)}"]
    return "\n".join(rows)
