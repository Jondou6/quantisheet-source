"""Copy-on-write revisions (brief 3.9). A Revision is a frozen dataclass
holding tuples, so editing one raises (finding 25: the paste's freeze was
shallow). release_recoverable only on approved revisions and never more
than was held back minus what's already released (finding 17)."""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import datetime

from .diff import Change, check_final, diff
from .model import Claim
from .settle import settle_claim


class RevisionError(Exception):
    pass


@dataclass(frozen=True)
class Release:
    at: str
    actor: str
    amount_cents: int
    note: str


@dataclass(frozen=True)
class Revision:
    number: int
    claim: Claim
    status: str = "draft"            # draft / approved / void
    created_at: str = ""
    author: str = ""
    changes: tuple[Change, ...] = ()
    recoverable_cents: int = 0       # held back at approval
    releases: tuple[Release, ...] = ()
    note: str = ""

    @property
    def released_cents(self) -> int:
        return sum(r.amount_cents for r in self.releases)


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def create_revision(prev: Revision | None, claim: Claim, author: str = "",
                    at: str = "") -> Revision:
    changes = diff(prev.claim.lines, claim.lines) if prev else ()
    return Revision(number=(prev.number + 1) if prev else 0, claim=claim,
                    created_at=at or _now(), author=author, changes=changes)


def approve(rev: Revision) -> Revision:
    check_final(rev.changes)
    return dataclasses.replace(
        rev, status="approved",
        recoverable_cents=settle_claim(rev.claim).holdback_total)


def release_recoverable(rev: Revision, amount_cents: int, proof_note: str,
                        actor: str, at: str = "") -> Revision:
    if rev.status != "approved":
        raise RevisionError("only an approved revision can release depreciation")
    if not isinstance(amount_cents, int) or amount_cents <= 0:
        raise RevisionError("release amount must be a positive number of cents")
    if not (proof_note or "").strip():
        raise RevisionError("a proof note is required (invoice, photos, ...)")
    left = rev.recoverable_cents - rev.released_cents
    if amount_cents > left:
        raise RevisionError(f"only {left} cents are left to release")
    return dataclasses.replace(rev, releases=rev.releases + (
        Release(at or _now(), actor, amount_cents, proof_note.strip()),))
