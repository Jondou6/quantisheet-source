"""settle_claim(claim) -> Settlement for residential and commercial claims
(brief 3.7). One rounding per step, all through cents.div_round_half_up.

Fixes: ALE % limit is off Coverage A (f.2); None = no limit, 0 = 0 (f.3,
f.22); ALE days clamp (f.23); O&L cap applied after its O&P (f.4); O&P
application honoured (f.12); DepPolicy.base (f.16); one deductible model
(f.29). Commercial: coinsurance with one rounding, scheduled/blanket
limits, per-building/per-occurrence deductibles, BI/EE, compound O&P.

The math follows common property-claim practice (INFERRED, not checked
against a specific policy). Every rate, limit and mode is an input: the
policy on the claim always wins. No policy-form text is reproduced here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .cents import apply_bp, div_round_half_up, round_to
from .model import (Claim, DeductibleSpec, Line, OpPolicy, Structure,
                    op_excluded)


@dataclass(frozen=True)
class Warn:
    code: str
    detail: str = ""
    amount: int = 0
    structure_id: str = ""

    def plain(self) -> str:
        from .cents import fmt
        msg = {
            "ol_capped": "Ordinance or law reached its cap",
            "ale_capped_by": "ALE was limited by",
            "deductible_exceeds_acv": "Deductible is larger than the ACV",
            "coinsurance_penalty": "Coinsurance penalty",
            "limit_reached": "Limit reached",
            "bi_limit_reached": "Business income / extra expense limit reached",
            "no_coverage_a_limit": "No Coverage A limit entered",
            "unassigned_lines": "Lines with no structure were put on",
            "contents_limit_reached": "Contents limit reached",
        }.get(self.code, self.code)
        bits = [msg]
        if self.detail:
            bits.append(self.detail)
        if self.amount:
            bits.append(fmt(self.amount))
        return " – ".join([bits[0], " ".join(bits[1:])]) if len(bits) > 1 else msg


@dataclass(frozen=True)
class StructureResult:
    id: str
    name: str
    rc: int
    op: int
    overhead: int
    profit: int
    ol: int
    rcv: int
    dep: int
    recoverable_dep: int
    acv: int
    loss_now: int
    loss_full: int
    after_coinsurance: int
    deductible: int
    after_deductible: int
    paid_now: int
    paid_full: int
    limit_cents: Optional[int]


@dataclass(frozen=True)
class Settlement:
    claim_type: str
    rc: int
    op: int
    overhead: int
    profit: int
    ol_uncapped: int
    ol: int
    rcv: int
    dep: int
    recoverable_dep: int
    acv: int
    after_coinsurance: int
    deductible: int
    net: int                      # property paid now (after ded + limits)
    paid_full: int                # same chain on RCV (after release)
    recoverable_holdback: int     # paid_full - net
    ale: int
    bi_days: int
    bi: int
    ee: int
    bi_ee: int
    structures: tuple[StructureResult, ...]
    warnings: tuple[Warn, ...]
    # contents / business personal property (0.2.2)
    contents_rcv: int = 0
    contents_dep: int = 0
    contents_acv: int = 0
    contents_deductible: int = 0
    contents_now: int = 0
    contents_full: int = 0

    @property
    def total_now(self) -> int:
        return self.net

    @property
    def contents_holdback(self) -> int:
        return self.contents_full - self.contents_now

    @property
    def total_indemnity(self) -> int:
        return self.net + self.ale + self.bi_ee + self.contents_now

    @property
    def holdback_total(self) -> int:
        """Everything paid later: property and contents depreciation."""
        return self.recoverable_holdback + self.contents_holdback


# ---------------------------------------------------------------- pieces

def op_amount(base: int, op: OpPolicy, oh_bp: Optional[int] = None,
              pr_bp: Optional[int] = None) -> tuple[int, int]:
    """(overhead, profit) on one base. Additive: one rounding of the sum
    rate, split as overhead first. Compound: profit on base + overhead."""
    oh = op.overhead_bp if oh_bp is None else oh_bp
    pr = op.profit_bp if pr_bp is None else pr_bp
    if op.compound:
        o = apply_bp(base, oh)
        return o, apply_bp(base + o, pr)
    total = apply_bp(base, oh + pr)
    o = apply_bp(base, oh)
    return o, total - o


def _op_for_lines(lines, op: OpPolicy, line_rc) -> tuple[int, int, dict]:
    """O&P on a set of lines honouring application; returns (oh, pr,
    per-line total share) - the share is used by DepPolicy 'rcv'."""
    base_lines = [ln for ln in lines if not op_excluded(ln, op)]
    shares = {ln.id: sum(op_amount(line_rc[ln.id], op)) for ln in base_lines}
    if op.application == "per_line":
        oh = pr = 0
        for ln in base_lines:
            a, b = op_amount(line_rc[ln.id], op)
            oh += a
            pr += b
        return oh, pr, shares
    oh, pr = op_amount(sum(line_rc[ln.id] for ln in base_lines), op)
    return oh, pr, shares


def deductible_amount(spec: DeductibleSpec, peril: str, cov_a: Optional[int],
                      rcv: int) -> int:
    spec = spec.resolve(peril)
    if spec.kind == "flat":
        return spec.amount_cents
    if spec.basis == "rcv":
        return apply_bp(rcv, spec.bp)
    return apply_bp(cov_a or 0, spec.bp)


def coinsurance(loss: int, limit: Optional[int], value: int, coins_bp: int,
                agreed: bool) -> tuple[int, int]:
    """(paid_loss, required). One rounding: never a rounded ratio."""
    if coins_bp <= 0 or agreed or value <= 0 or limit is None:
        return loss, 0
    required = apply_bp(value, coins_bp)
    if limit >= required:
        return loss, required
    return div_round_half_up(loss * limit * 10_000, coins_bp * value), required


def _allocate(ded: int, losses: list[int]) -> list[int]:
    """Spread one per-occurrence deductible over structures, largest loss
    first, so the total is max(0, sum - ded)."""
    out = [0] * len(losses)
    left = ded
    for i in sorted(range(len(losses)), key=lambda k: -losses[k]):
        take = min(left, max(losses[i], 0))
        out[i] = take
        left -= take
    return out


def _clamp(v: int, limit: Optional[int]) -> int:
    return v if limit is None else min(v, limit)


# ---------------------------------------------------------------- main

def settle_claim(claim: Claim) -> Settlement:
    warns: list[Warn] = []
    structures = list(claim.structures) or [Structure(id="", name="Claim")]
    ids = [s.id for s in structures]
    step = claim.rounding.line_step
    line_rc = {ln.id: round_to(ln.rc, step) for ln in claim.lines}

    by_s: dict[str, list[Line]] = {sid: [] for sid in ids}
    stray = 0
    for ln in claim.lines:
        sid = ln.structure_id if ln.structure_id in by_s else ids[0]
        stray += ln.structure_id not in by_s
        by_s[sid].append(ln)
    if stray and claim.structures:
        warns.append(Warn("unassigned_lines", structures[0].name, 0, ids[0]))

    # O&L, claim level, paid on one structure; cap AFTER its O&P (f.4)
    ol_uncapped = ol = 0
    ol_sid = ids[0]
    if claim.ol is not None and claim.ol.bp:
        cats = {c.upper() for c in claim.ol.categories}
        qual = sum(line_rc[ln.id] for ln in claim.lines
                   if not cats or ln.category.upper() in cats)
        base = apply_bp(qual, claim.ol.bp)
        if claim.ol.apply_op:
            base += sum(op_amount(base, claim.op))
        ol_uncapped = base
        ol = _clamp(base, claim.ol.cap_cents)
        if claim.ol.cap_cents is not None and base >= claim.ol.cap_cents:
            warns.append(Warn("ol_capped", "", base - ol))
        if claim.ol.structure_id in by_s:
            ol_sid = claim.ol.structure_id

    cov_a = claim.coverage_a_limit()
    rows = []
    for s in structures:
        lines = by_s[s.id]
        rc = sum(line_rc[ln.id] for ln in lines)
        oh, pr, shares = _op_for_lines(lines, claim.op, line_rc)
        op = oh + pr
        s_ol = ol if s.id == ol_sid else 0
        rcv = rc + op + s_ol
        dep = nonrec = 0
        for ln in lines:
            b = line_rc[ln.id]
            if claim.dep.base == "rcv":
                b += shares.get(ln.id, 0)
            d = apply_bp(b, ln.dep_bp)
            dep += d
            if not ln.dep_recoverable:
                nonrec += d
        acv = rcv - dep
        full = rcv - nonrec if s.valuation == "rc" else acv
        rows.append(dict(s=s, rc=rc, oh=oh, pr=pr, op=op, ol=s_ol, rcv=rcv,
                         dep=dep, rec=dep - nonrec if s.valuation == "rc" else 0,
                         acv=acv, now=acv, full=full))

    peril = claim.peril
    commercial = claim.claim_type == "commercial"
    blanket = commercial and claim.limits.mode == "blanket"

    def ded_for(r) -> int:
        s = r["s"]
        spec = s.deductible if (commercial and s.deductible is not None) \
            else claim.deductible
        a = cov_a if not commercial else s.limit_cents
        rs = spec.resolve(peril)
        if rs.kind == "percent" and rs.basis == "coverage_a" and a is None \
                and s.id not in ded_warned:
            ded_warned.append(s.id)
            warns.append(Warn("no_coverage_a_limit", s.name, 0, s.id))
        return deductible_amount(spec, peril, a, r["rcv"])

    ded_warned = []

    def occurrence_deductible() -> int:
        """One deductible for the whole claim. A percentage deductible on
        basis 'coverage_a' uses the Coverage A limit (residential) or the
        sum of the limits (commercial: blanket limit, else each
        structure's limit); basis 'rcv' uses the claim's total RCV."""
        spec = claim.deductible.resolve(peril)
        if not commercial:
            base = cov_a
        elif blanket:
            base = claim.limits.blanket_limit_cents
        else:
            lims = [s.limit_cents for s in structures if s.limit_cents is not None]
            base = sum(lims) if lims else None
        if spec.kind == "percent" and spec.basis == "coverage_a" and base is None \
                and not ded_warned:
            ded_warned.append(1)
            warns.append(Warn("no_coverage_a_limit", "deductible"))
        return deductible_amount(spec, "", base, sum(r["rcv"] for r in rows))

    def chain(key: str, record: bool):
        losses = [r[key] for r in rows]
        res = []
        if blanket:
            lp = claim.limits
            tot = sum(losses)
            value = sum(r["s"].value_cents for r in rows)
            after_c, req = coinsurance(tot, lp.blanket_limit_cents, value,
                                       lp.blanket_coins_bp, lp.agreed_value)
            if record and after_c < tot:
                warns.append(Warn("coinsurance_penalty", "blanket",
                                  tot - after_c))
            if claim.deductible_mode == "per_building":
                ded = sum(ded_for(r) for r in rows)
            else:
                ded = occurrence_deductible()
            after_d = max(0, after_c - ded)
            paid = _clamp(after_d, lp.blanket_limit_cents)
            if record and paid < after_d:
                warns.append(Warn("limit_reached", "blanket", after_d - paid))
            if record and ded > after_c:
                warns.append(Warn("deductible_exceeds_acv", "", ded - after_c))
            for r, loss in zip(rows, losses):
                res.append((loss, loss, 0, loss, None))
            return res, after_c, ded, paid

        after_cs = []
        for r, loss in zip(rows, losses):
            s = r["s"]
            if commercial:
                a, req = coinsurance(loss, s.limit_cents, s.value_cents,
                                     s.coins_bp, claim.limits.agreed_value)
                if record and a < loss:
                    warns.append(Warn("coinsurance_penalty",
                                      s.name, loss - a, s.id))
            else:
                a = loss
            after_cs.append(a)
        if commercial and claim.deductible_mode == "per_building":
            deds = [ded_for(r) for r in rows]
        else:
            one = occurrence_deductible()
            if record and one > sum(after_cs):
                warns.append(Warn("deductible_exceeds_acv", "", one - sum(after_cs)))
            deds = _allocate(one, after_cs)
        total = 0
        for r, loss, a, d in zip(rows, losses, after_cs, deds):
            s = r["s"]
            if record and commercial and claim.deductible_mode == "per_building" \
                    and d > a:
                warns.append(Warn("deductible_exceeds_acv", s.name, d - a, s.id))
            after_d = max(0, a - d)
            paid = _clamp(after_d, s.limit_cents)
            if record and paid < after_d:
                warns.append(Warn("limit_reached", s.name, after_d - paid, s.id))
            res.append((loss, a, min(d, a) if not commercial or
                        claim.deductible_mode != "per_building" else d,
                        after_d, paid))
            total += paid
        return res, sum(after_cs), sum(deds), total

    now, after_c_total, ded_total, net = chain("now", True)
    full, _, _, paid_full = chain("full", False)
    if blanket:
        # split blanket payment for display only, by loss share
        tot_loss = sum(r["now"] for r in rows) or 1
        paid_split = [div_round_half_up(net * r["now"], tot_loss) for r in rows]
        full_split = [div_round_half_up(paid_full * r["full"],
                                        sum(x["full"] for x in rows) or 1)
                      for r in rows]
    else:
        paid_split = [x[4] for x in now]
        full_split = [x[4] for x in full]

    results = []
    for r, n, f, pn, pf in zip(rows, now, full, paid_split, full_split):
        s = r["s"]
        results.append(StructureResult(
            id=s.id, name=s.name, rc=r["rc"], op=r["op"], overhead=r["oh"],
            profit=r["pr"], ol=r["ol"], rcv=r["rcv"], dep=r["dep"],
            recoverable_dep=r["rec"], acv=r["acv"], loss_now=r["now"],
            loss_full=r["full"], after_coinsurance=n[1], deductible=n[2],
            after_deductible=n[3], paid_now=pn, paid_full=pf,
            limit_cents=s.limit_cents))

    # ALE (residential) / BI-EE (commercial): outside the deductible
    ale = bi_days = bi = ee = bi_ee = 0
    if not commercial and claim.ale is not None:
        a = claim.ale
        days = a.days if a.days_limit is None else min(a.days, a.days_limit)
        cands = [("days_x_daily", days * a.daily_cents)]
        if a.cap_cents is not None:
            cands.append(("cap", a.cap_cents))
        if a.pct_of_cov_a_bp is not None:
            if cov_a is None:
                warns.append(Warn("no_coverage_a_limit", "ALE % limit"))
            cands.append(("pct_of_coverage_a", apply_bp(cov_a or 0,
                                                        a.pct_of_cov_a_bp)))
        by, ale = min(cands, key=lambda kv: kv[1])
        if by != "days_x_daily" and ale < cands[0][1]:
            warns.append(Warn("ale_capped_by", by, cands[0][1] - ale))
    if commercial and claim.bi_ee is not None:
        b = claim.bi_ee
        wait_days = -(-b.waiting_hours // 24) if b.waiting_hours > 0 else 0
        bi_days = max(0, b.restoration_days - wait_days)
        bi = (b.daily_net_income_cents + b.daily_continuing_expense_cents) * bi_days
        ee = b.extra_expense_cents
        bi_ee = _clamp(bi + ee, b.limit_cents)
        if bi_ee < bi + ee:
            warns.append(Warn("bi_limit_reached", "", bi + ee - bi_ee))

    from . import contents as _contents
    ct = _contents.totals(claim)
    if ct["over_limit"]:
        warns.append(Warn("contents_limit_reached", "", ct["over_limit"]))

    tstep = claim.rounding.total_step
    return Settlement(
        claim_type=claim.claim_type,
        rc=sum(r["rc"] for r in rows), op=sum(r["op"] for r in rows),
        overhead=sum(r["oh"] for r in rows), profit=sum(r["pr"] for r in rows),
        ol_uncapped=ol_uncapped, ol=ol,
        rcv=sum(r["rcv"] for r in rows), dep=sum(r["dep"] for r in rows),
        recoverable_dep=sum(r["rec"] for r in rows),
        acv=sum(r["acv"] for r in rows),
        after_coinsurance=after_c_total, deductible=ded_total,
        net=round_to(net, tstep), paid_full=round_to(paid_full, tstep),
        recoverable_holdback=round_to(paid_full, tstep) - round_to(net, tstep),
        ale=ale, bi_days=bi_days, bi=bi, ee=ee, bi_ee=bi_ee,
        structures=tuple(results), warnings=tuple(warns),
        contents_rcv=ct["rcv"], contents_dep=ct["dep"],
        contents_acv=ct["acv"], contents_deductible=ct["deductible"],
        contents_now=ct["now"], contents_full=ct["full"])
