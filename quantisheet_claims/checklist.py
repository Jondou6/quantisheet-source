"""What to check before a claim goes out (ClaimIT 0.2). Each item says
which tab fixes it, so the window can take the user there.

Levels: "fix" = the estimate is wrong or incomplete; "check" = worth a
look; "ok" never appears (an empty list means ready).
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

from . import categories
from . import model as m
from .diff import unexplained

# tab index in the window (ui/workspace.py TAB_NAMES)
TAB = {"claim": 0, "coverage": 1, "lines": 2, "groups": 3, "op": 4,
       "settlement": 5, "revisions": 6, "diary": 7, "contents": 8,
       "export": 9}


@dataclass(frozen=True)
class Item:
    level: str        # "fix" or "check"
    tab: str          # a key of TAB
    text: str


def _is_date(t: str) -> bool:
    try:
        _dt.date.fromisoformat((t or "").strip())
        return True
    except ValueError:
        return False


def check(claim: m.Claim, revisions=(), photo_problems=()) -> list:
    out = []
    add = lambda lvl, tab, txt: out.append(Item(lvl, tab, txt))  # noqa: E731
    if not claim.claim_number.strip() or claim.claim_number == "NEW-CLAIM":
        add("fix", "claim", "Give the claim its claim number")
    if not claim.insured.strip():
        add("fix", "claim", "Add the insured's name")
    if not claim.loss_address.strip():
        add("check", "claim", "Add the loss address")
    if not _is_date(claim.loss_date):
        add("fix", "claim", "Enter the date of loss as YYYY-MM-DD")
    elif claim.loss_date > _dt.date.today().isoformat():
        add("fix", "claim", "The date of loss is in the future")
    if not claim.peril.strip():
        add("check", "claim", "Say what caused the loss (the peril)")
    if claim.claim_type == "residential" and claim.coverage_a_limit() is None:
        add("check", "coverage", "Enter the Coverage A (dwelling) limit")
    if claim.claim_type == "commercial" and not any(
            s.limit_cents for s in claim.structures) and \
            not claim.limits.blanket_limit_cents:
        add("check", "coverage", "Enter the building limits")
    d = claim.deductible
    if not d.amount_cents and not d.bp and not d.per_peril:
        add("check", "coverage", "No deductible is set")
    if not claim.lines and not claim.contents:
        add("fix", "lines", "No line items yet")
    for i, ln in enumerate(claim.lines, 1):
        name = f"Line {i} ({ln.description or ln.item_code})"
        if ln.qty_q4 == 0:              # a credit (negative) line is fine
            add("fix", "lines", f"{name}: quantity is 0")
        if not 0 <= ln.dep_bp <= 10_000:
            add("fix", "lines", f"{name}: depreciation must be 0% to 100%")
        if ln.unit_cost.total <= 0:
            add("fix", "lines", f"{name}: no unit cost")
        if not categories.is_known(ln.category):
            add("fix", "lines", f"{name}: unknown category {ln.category}")
        if ln.item_code in ("", "NEW") or ln.description in ("", "New item"):
            add("check", "lines", f"{name}: still has the placeholder text")
    if claim.rooms and any(not ln.room_id for ln in claim.lines):
        n = sum(1 for ln in claim.lines if not ln.room_id)
        add("check", "lines", f"{n} line(s) aren't in a room")
    for i, it in enumerate(claim.contents, 1):           # 0.2.2
        if it.unit_rc_cents <= 0:
            add("fix", "contents", f"Contents item {i} ({it.description}): "
                "no replacement cost")
    if claim.contents and claim.contents_cov.limit_cents is None:
        add("check", "contents", "Enter the contents limit")
    for rev in revisions:
        left = len(unexplained(rev.changes))
        if rev.status == "draft" and left:
            add("fix", "revisions",
                f"Revision {rev.number}: {left} change(s) need a reason")
    if claim.payments:
        from .diary import balance
        from .settle import settle_claim
        b = balance(claim, settle_claim(claim))
        if b["open_total"] < 0:
            add("check", "diary", "Payments are more than the claim is "
                "worth - check the payments or the estimate")
    for p in photo_problems:
        add("check", "lines", f"Photo missing or changed: {p}")
    return out


def summary(items) -> str:
    fix = sum(1 for i in items if i.level == "fix")
    chk = len(items) - fix
    if not items:
        return "Ready: nothing to check"
    parts = []
    if fix:
        parts.append(f"{fix} to fix")
    if chk:
        parts.append(f"{chk} to check")
    return ", ".join(parts)
