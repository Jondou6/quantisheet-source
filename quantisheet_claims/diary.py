"""Claim diary and payments received (ClaimIT 0.2). Records only:
ClaimIT never sends, receives or moves money."""
from __future__ import annotations

import datetime as _dt

from . import model as m
from .cents import parse_money


class DiaryError(ValueError):
    pass


class OverpaymentError(DiaryError):
    """The payment takes the total paid past what the estimate says is
    owed. Recorded only when the user confirms (allow_over=True)."""


# one payment over this is a typing slip, not a claim payment (Chief's
# estimator test, Nov 7: $99,999,999,999 was accepted)
MAX_PAYMENT_CENTS = 100_000_000_00


def _date(text: str) -> str:
    t = (text or "").strip()
    try:
        return _dt.date.fromisoformat(t).isoformat()
    except ValueError as e:
        raise DiaryError(f"{text!r} isn't a date (YYYY-MM-DD)") from e


def add_entry(claim: m.Claim, on: str, kind: str, text: str,
              by: str = "") -> tuple:
    if kind not in m.DIARY_KINDS:
        raise DiaryError(f"kind must be one of {', '.join(m.DIARY_KINDS)}")
    text = (text or "").strip()
    if not text:
        raise DiaryError("write what happened")
    e = m.DiaryEntry(id=m.new_id(), on=_date(on), kind=kind, text=text,
                     by=by)
    return tuple(sorted(claim.diary + (e,), key=lambda x: x.on))


def remove_entry(claim: m.Claim, entry_id: str) -> tuple:
    return tuple(e for e in claim.diary if e.id != entry_id)


def add_payment(claim: m.Claim, on: str, amount: str, kind: str,
                reference: str = "", owed_cents=None,
                allow_over: bool = False) -> tuple:
    """`owed_cents`: the estimate's total owed (now plus later). A payment
    that takes the total paid past it raises OverpaymentError unless
    allow_over."""
    if kind not in m.PAYMENT_KINDS:
        raise DiaryError(f"kind must be one of {', '.join(m.PAYMENT_KINDS)}")
    cents = parse_money(amount)
    if cents <= 0:
        raise DiaryError("a payment is more than $0.00")
    if cents > MAX_PAYMENT_CENTS:
        raise DiaryError("check the amount - one payment can't be more "
                         "than $100,000,000.00")
    # no estimate yet (nothing owed): an advance is recorded as it comes
    if owed_cents is not None and int(owed_cents) > 0 and not allow_over:
        after = claim.paid_cents() + cents
        if after > int(owed_cents):
            from .cents import fmt
            raise OverpaymentError(
                f"this payment makes {fmt(after)} paid, "
                f"{fmt(after - int(owed_cents))} more than the "
                f"{fmt(int(owed_cents))} the estimate says is owed")
    p = m.Payment(id=m.new_id(), on=_date(on), amount_cents=cents, kind=kind,
                  reference=(reference or "").strip()[:60])
    return tuple(sorted(claim.payments + (p,), key=lambda x: x.on))


def remove_payment(claim: m.Claim, payment_id: str) -> tuple:
    return tuple(p for p in claim.payments if p.id != payment_id)


def balance(claim: m.Claim, settlement) -> dict:
    """What the estimate says is owed now and later, what has been paid,
    and what is still open."""
    paid = claim.paid_cents()
    now = settlement.total_indemnity
    later = settlement.holdback_total
    return {"owed_now": now, "recoverable_later": later, "paid": paid,
            "open_now": now - paid, "open_total": now + later - paid,
            "overpaid": max(0, paid - now - later)}


def open_text(b: dict) -> tuple:
    """("Still open", cents) or ("Overpaid", cents) - never a negative
    "still open"."""
    if b["open_total"] < 0:
        return "Overpaid", -b["open_total"]
    return "Still open", b["open_total"]


def text(claim: m.Claim) -> str:
    """Plain text of the diary, oldest first. The diary is the user's own
    notes and never goes into the carrier export."""
    return "\n".join(f"{e.on}  {e.kind:<10} {e.text}" +
                     (f"  ({e.by})" if e.by else "") for e in claim.diary)


