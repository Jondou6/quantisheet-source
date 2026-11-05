"""Frozen dataclasses for a claim. Money int cents, rates int bp,
quantities int qty_q4. Collections are tuples, so a saved/approved claim
can't be edited in place (findings 25, 29).
"""
from __future__ import annotations

import dataclasses
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from .cents import apply_qty

UNITS = ("SF", "SY", "LF", "EA", "HR", "CY", "CF", "GAL", "SQ", "BF",
         "LS", "TON", "MO")

# the module's own unit map from snapshot text (finding 30). LS/MO/BF are
# claim-only units; QuantiSheet never sends them.
_UNIT_MAP = {
    "sf": "SF", "sq ft": "SF", "sqft": "SF", "ft2": "SF", "ft²": "SF",
    "lf": "LF", "ft": "LF", "'": "LF", "lin ft": "LF",
    "ea": "EA", "each": "EA", "count": "EA", "ct": "EA",
    "sy": "SY", "sq": "SQ", "cy": "CY", "cf": "CF", "gal": "GAL",
    "hr": "HR", "hrs": "HR", "ton": "TON",
    "ls": "LS", "mo": "MO", "bf": "BF",
}

CLAIM_TYPES = ("residential", "commercial")
STATUSES = ("draft", "review", "submitted", "approved", "supplemented", "void")
SENT = ("submitted", "approved", "supplemented", "void")
STRUCTURE_KINDS = ("dwelling", "other_structure", "building", "business_property")
ORIGINS = ("manual", "takeoff", "import")


def unit_from_text(text: str) -> Optional[str]:
    """Snapshot unit text -> module unit, or None (= line needs review)."""
    t = (text or "").strip()
    if t.upper() in UNITS:
        return t.upper()
    return _UNIT_MAP.get(t.lower())


def new_id() -> str:
    return uuid.uuid4().hex


class FrozenClaimError(Exception):
    """Raised when something tries to change a claim that isn't a draft."""


@dataclass(frozen=True)
class UnitCost:
    material: int = 0
    labor: int = 0
    equipment: int = 0
    other: int = 0

    @property
    def total(self) -> int:
        return self.material + self.labor + self.equipment + self.other

    PARTS = ("material", "labor", "equipment", "other")

    def scaled(self, new_total: int) -> "UnitCost":
        """The same split at a new total (0.2.2, r47 #13: typing a new
        unit cost used to throw the split away). Each part scales in
        proportion, rounded half up; the cents left over go to the
        largest part, so the parts always add up to new_total. No split
        yet (total 0): it all goes on "other"."""
        old = self.total
        if old == new_total:
            return self
        if old <= 0 or new_total < 0:
            return UnitCost(other=new_total)
        from .cents import div_round_half_up
        vals = [div_round_half_up(getattr(self, k) * new_total, old)
                for k in self.PARTS]
        big = max(range(4), key=lambda i: getattr(self, self.PARTS[i]))
        vals[big] += new_total - sum(vals)
        return UnitCost(*vals)


@dataclass(frozen=True)
class Line:
    id: str
    item_code: str
    description: str
    category: str
    qty_q4: int
    unit: str
    unit_cost: UnitCost
    structure_id: str = ""
    room_id: str = ""
    group_id: str = ""
    ordinal: int = 0
    dep_bp: int = 0
    dep_recoverable: bool = True
    tax_exempt: bool = False
    waste_bp: int = 0          # stored, not applied to qty (brief 3.8)
    note: str = ""
    origin: str = "manual"
    created_at: str = ""
    # 0.2: the room measurement this quantity comes from (rooms.MEASURES
    # key) and the factor, so the line re-measures when its room changes
    # or it is copied to another room; "" = typed by hand
    qty_from: str = ""
    qty_factor: str = ""

    @property
    def rc(self) -> int:
        return apply_qty(self.unit_cost.total, self.qty_q4)


@dataclass(frozen=True)
class PerilDeductible:
    peril: str
    spec: "DeductibleSpec"


@dataclass(frozen=True)
class DeductibleSpec:
    """The ONE deductible model (finding 29). kind 'flat' uses amount_cents;
    'percent' uses bp of the Coverage A limit (basis 'coverage_a') or of RCV
    (basis 'rcv'). A matching per-peril entry replaces the whole spec."""
    kind: str = "flat"
    amount_cents: int = 0
    bp: int = 0
    basis: str = "coverage_a"
    per_peril: tuple[PerilDeductible, ...] = ()

    def resolve(self, peril: str) -> "DeductibleSpec":
        p = (peril or "").strip().lower()
        for pd in self.per_peril:
            if pd.peril.strip().lower() == p:
                return pd.spec
        return self


@dataclass(frozen=True)
class OrdinanceLaw:
    bp: int = 0
    cap_cents: Optional[int] = None        # None = no cap
    categories: tuple[str, ...] = ()       # qualifying categories ("" = all)
    apply_op: bool = False
    structure_id: str = ""                 # which structure it pays on ("" = first)


@dataclass(frozen=True)
class AleCoverage:
    daily_cents: int = 0
    days: int = 0
    days_limit: Optional[int] = None       # None = no limit (finding 23)
    cap_cents: Optional[int] = None        # None = no cap, 0 = $0 (finding 3)
    pct_of_cov_a_bp: Optional[int] = None  # None = no % limit, 0 = 0% (f. 22)


@dataclass(frozen=True)
class BusinessIncome:
    daily_net_income_cents: int = 0
    daily_continuing_expense_cents: int = 0
    restoration_days: int = 0
    waiting_hours: int = 72
    extra_expense_cents: int = 0
    limit_cents: Optional[int] = None


TAX_CODES = {"TAX", "SALES TAX", "SALESTAX", "SALES-TAX"}


def is_tax_line(ln) -> bool:
    """A sales-tax line: category TAX, item code TAX / SALES TAX, or a
    description that starts with 'Tax' or 'Sales tax'."""
    import re
    if (ln.category or "").upper() == "TAX":
        return True
    if (ln.item_code or "").strip().upper() in TAX_CODES:
        return True
    return bool(re.match(r"\s*(sales\s+)?tax\b", ln.description or "",
                         re.I))


def op_excluded(ln, op) -> bool:
    """No O&P on this line: its category is excluded, or it's sales tax
    and the policy doesn't put O&P on tax."""
    excl = {c.upper() for c in op.exclude_categories}
    return (ln.category or "").upper() in excl or \
        (is_tax_line(ln) and not op.op_on_tax)


@dataclass(frozen=True)
class OpPolicy:
    overhead_bp: int = 0
    profit_bp: int = 0
    compound: bool = False
    application: str = "aggregate"         # or "per_line" (finding 12)
    exclude_categories: tuple[str, ...] = ()
    # O&P is not charged on sales tax unless this is on (PM review NW-15);
    # older claim files without it read as False
    op_on_tax: bool = False


@dataclass(frozen=True)
class DepPolicy:
    base: str = "rcv-excl-op"              # or "rcv" (finding 16)


@dataclass(frozen=True)
class RoundingPolicy:
    line_step: int = 1
    total_step: int = 1


@dataclass(frozen=True)
class TaxPolicy:
    mode: str = "input_line"
    rate_bp: int = 0
    tax_equipment: bool = False


@dataclass(frozen=True)
class Structure:
    id: str
    name: str
    kind: str = "dwelling"
    value_cents: int = 0
    limit_cents: Optional[int] = None      # None = no limit entered
    coins_bp: int = 0                      # 0 = no coinsurance
    valuation: str = "rc"
    deductible: Optional[DeductibleSpec] = None


@dataclass(frozen=True)
class LimitPlan:
    mode: str = "scheduled"                # or "blanket"
    blanket_limit_cents: Optional[int] = None
    blanket_coins_bp: int = 0
    agreed_value: bool = False


@dataclass(frozen=True)
class Opening:
    kind: str
    width_ft: Decimal
    height_ft: Decimal


@dataclass(frozen=True)
class RoomPart:
    """A piece that makes a room not a plain rectangle (0.2.2): "bump" adds
    an alcove or the other leg of an L, built out from a wall
    (along_ft x depth_ft); "cut" takes a corner out (an L made by
    notching a corner)."""
    kind: str                      # "bump" / "cut"
    along_ft: Decimal = Decimal(0)
    depth_ft: Decimal = Decimal(0)


@dataclass(frozen=True)
class Room:
    id: str
    name: str
    structure_id: str = ""
    length_ft: Decimal = Decimal(0)
    width_ft: Decimal = Decimal(0)
    height_ft: Decimal = Decimal(0)
    openings: tuple[Opening, ...] = ()
    parts: tuple[RoomPart, ...] = ()


@dataclass(frozen=True)
class WbsNode:
    id: str
    name: str
    parent_id: str = ""
    ordinal: int = 0
    op_mode: str = "inherit"               # inherit / exempt / custom
    overhead_bp: int = 0                   # custom only
    profit_bp: int = 0                     # custom only
    dep_override_bp: Optional[int] = None


@dataclass(frozen=True)
class ClaimRecipe:
    name: str
    unit: str
    item_code: str
    description: str = ""
    category: str = "OTHER"
    factor_bp: int = 10_000
    waste_bp: int = 0
    unit_cost: UnitCost = UnitCost()


@dataclass(frozen=True)
class Photo:
    """A damage photo (PM review NW-16). The file is kept beside the claim
    file in <claim>.photos/ under its SHA-256, so the claim file stays
    small and a changed or missing photo is noticed."""
    id: str
    sha256: str
    file_name: str                 # the original name, for the caption
    ext: str = ".jpg"
    caption: str = ""
    taken: str = ""                # YYYY-MM-DD (photo date or file date)
    line_id: str = ""
    room_id: str = ""


@dataclass(frozen=True)
class AuditEvent:
    at: str
    actor: str
    action: str
    target: str = ""
    before: str = ""
    after: str = ""


DIARY_KINDS = ("note", "call", "email", "inspection", "meeting", "letter")
PAYMENT_KINDS = ("acv", "depreciation", "supplement", "ale", "other")


@dataclass(frozen=True)
class DiaryEntry:
    """One line of the claim diary: who said what, when (ClaimIT 0.2)."""
    id: str
    on: str                     # YYYY-MM-DD
    kind: str = "note"
    text: str = ""
    by: str = ""


@dataclass(frozen=True)
class Payment:
    """Money the carrier has paid on this claim - a record only; ClaimIT
    never moves money (ClaimIT 0.2)."""
    id: str
    on: str                     # YYYY-MM-DD
    amount_cents: int = 0
    kind: str = "acv"
    reference: str = ""         # check or transfer number, as the user types it


CONTENTS_VALUATIONS = ("rc", "acv")


@dataclass(frozen=True)
class ContentsItem:
    """One personal-property item on the contents list (Coverage C;
    business personal property on a commercial claim) - 0.2.2."""
    id: str
    description: str
    qty: int = 1
    unit_rc_cents: int = 0                 # replacement cost, each
    dep_bp: int = 0
    room_id: str = ""
    age: str = ""                          # free text, e.g. "3 yrs"
    note: str = ""                         # brand / model / where bought


@dataclass(frozen=True)
class ContentsCoverage:
    limit_cents: Optional[int] = None      # None = no limit entered
    valuation: str = "rc"                  # "rc" (holdback paid later) / "acv"
    deductible_cents: int = 0              # if the contents carry their own


@dataclass(frozen=True)
class Claim:
    id: str
    claim_number: str
    claim_type: str = "residential"
    schema_version: int = 1
    insured: str = ""
    carrier: str = ""
    loss_address: str = ""
    loss_date: str = ""
    peril: str = ""
    op: OpPolicy = OpPolicy()
    dep: DepPolicy = DepPolicy()
    deductible: DeductibleSpec = DeductibleSpec()
    deductible_mode: str = "per_occurrence"
    limits: LimitPlan = LimitPlan()
    structures: tuple[Structure, ...] = ()
    ale: Optional[AleCoverage] = None
    bi_ee: Optional[BusinessIncome] = None
    ol: Optional[OrdinanceLaw] = None
    rounding: RoundingPolicy = RoundingPolicy()
    tax: TaxPolicy = TaxPolicy()
    lines: tuple[Line, ...] = ()
    rooms: tuple[Room, ...] = ()
    wbs: tuple[WbsNode, ...] = ()
    recipes: tuple[ClaimRecipe, ...] = ()
    photos: tuple[Photo, ...] = ()
    status: str = "draft"
    audit: tuple[AuditEvent, ...] = ()
    diary: tuple[DiaryEntry, ...] = ()
    payments: tuple[Payment, ...] = ()
    contents: tuple[ContentsItem, ...] = ()
    contents_cov: ContentsCoverage = ContentsCoverage()

    def __post_init__(self):
        if self.claim_type not in CLAIM_TYPES:
            raise ValueError(f"claim_type must be one of {CLAIM_TYPES}")
        if self.status not in STATUSES:
            raise ValueError(f"status must be one of {STATUSES}")

    def coverage_a_limit(self) -> Optional[int]:
        for s in self.structures:
            if s.kind == "dwelling":
                return s.limit_cents
        return None

    def structure_ids(self) -> list[str]:
        return [s.id for s in self.structures]

    def paid_cents(self) -> int:
        return sum(p.amount_cents for p in self.payments)


def edit(claim: Claim, actor: str, action: str, at: str = "",
         reopen: bool = False, **changes) -> Claim:
    """The one way to change a claim: only drafts change (invariant 5),
    and every change appends an AuditEvent."""
    # the diary and payments go on after a claim is submitted (0.2)
    if claim.status != "draft" and set(changes) - {"status", "diary",
                                                   "payments"}:
        raise FrozenClaimError(f"claim is {claim.status}; make a revision")
    # a sent claim never goes back to draft or review: a supplement is a
    # new revision (r47 review #2)
    new = changes.get("status", claim.status)
    if claim.status in SENT and new in ("draft", "review") and not reopen:
        raise FrozenClaimError(
            f"claim is {claim.status}: to change it, start a supplement "
            "(Revisions & supplements > Start a supplement)")
    if not at:
        from datetime import datetime
        at = datetime.now().isoformat(timespec="seconds")
    before = ",".join(sorted(changes))
    ev = AuditEvent(at=at, actor=actor, action=action, target=claim.id,
                    before=before,
                    after=str(changes.get("status", "")))
    return dataclasses.replace(claim, audit=claim.audit + (ev,), **changes)
