"""T6, T10, T11 and findings 7, 8, 10, 11, 17, 24, 25."""
import dataclasses

import pytest

from quantisheet_claims import model as m
from quantisheet_claims.diff import (UnexplainedChanges, check_final, diff,
                                   render_text, set_reason, supplement_totals,
                                   unexplained)
from quantisheet_claims.revision import (RevisionError, approve, create_revision,
                                       release_recoverable)
from .helpers import line, t1_claim


def sf(lid, q, price, group="g1", room="R1", item="DW"):
    return m.Line(id=lid, item_code=item, description=item, category="DRYWALL",
                  qty_q4=q * 10_000, unit="SF", unit_cost=m.UnitCost(labor=price),
                  structure_id="S1", group_id=group, room_id=room)


def test_t6_split_exact_no_cross_term():
    old = [sf("x", 100, 100)]
    new = [sf("x", 200, 122), sf("n", 100, 122)]
    ch = {c.line_id: c for c in diff(old, new)}
    assert ch["n"].kind == "added" and ch["n"].rc_delta == 12_200
    c = ch["x"]
    assert (c.kind, c.qty_part, c.price_part, c.rc_delta) == (
        "qty_price", 10_000, 4_400, 14_400)
    assert c.rc_delta == 24_400 - 10_000            # finding 7: not $166.00


def test_t10_unexplained_and_finalize():
    ch = diff([sf("x", 100, 100)], [sf("x", 120, 100)])
    assert ch[0].reason is None and len(unexplained(ch)) == 1   # finding 8
    assert ch[0].suggestion() == "hidden damage"
    with pytest.raises(UnexplainedChanges):
        check_final(ch)
    ch = set_reason(ch, 0, "hidden damage behind cabinets")
    check_final(ch)
    assert unexplained(ch) == []


def test_t10_same_item_two_rooms_and_regrouped():
    old = [sf("a", 100, 100, room="R1"), sf("b", 100, 100, room="R2")]
    new = [sf("a", 100, 100, room="R1"), sf("b", 150, 100, room="R2")]
    ch = diff(old, new)
    assert len(ch) == 1 and ch[0].line_id == "b"               # finding 10
    ch = diff(old, [old[0], dataclasses.replace(old[1], group_id="g2")])
    assert [c.kind for c in ch] == ["regrouped"]               # finding 11
    assert ch[0].old_group == "g1" and ch[0].new_group == "g2"


def test_supplement_net_due_counts_ol_ale_payments():
    old = t1_claim(ale=m.AleCoverage(daily_cents=10_000, days=30),
                   ol=m.OrdinanceLaw(bp=1000))
    new = dataclasses.replace(old, lines=old.lines + (line(100_000, 0),))
    t = supplement_totals(old, new)
    assert t.rc == 100_000 and t.op == 20_000 and t.ol == 10_000
    assert t.payments_made == 916_800 + 102_400             # old total incl. O&L
    assert t.net_due == 130_000                              # finding 24
    t2 = supplement_totals(old, new, payments_made=500_000)
    assert t2.net_due == 916_800 + 102_400 + 130_000 - 500_000
    assert "Net due" in render_text(diff(old.lines, new.lines), t)


def test_t11_revision_frozen_and_release_rules():
    r0 = create_revision(None, t1_claim(), author="Jon")
    with pytest.raises(dataclasses.FrozenInstanceError):
        r0.status = "approved"                                  # finding 25
    with pytest.raises(AttributeError):
        r0.changes.append(1)
    with pytest.raises(RevisionError):
        release_recoverable(r0, 100, "invoice", "Jon")          # not approved
    a = approve(r0)
    assert a.recoverable_cents == 512_000
    a = release_recoverable(a, 300_000, "invoice #12", "Jon")
    a = release_recoverable(a, 212_000, "invoice #13", "Jon")   # remainder ok
    assert a.released_cents == 512_000
    with pytest.raises(RevisionError):
        release_recoverable(a, 1, "again", "Jon")               # finding 17


def test_approve_refuses_unexplained_changes():
    r0 = create_revision(None, t1_claim())
    new = dataclasses.replace(r0.claim, lines=r0.claim.lines + (line(5_000),))
    r1 = create_revision(r0, new)
    assert r1.number == 1 and len(r1.changes) == 1
    with pytest.raises(UnexplainedChanges):
        approve(r1)
    r1 = dataclasses.replace(r1, changes=set_reason(r1.changes, 0, "found more"))
    assert approve(r1).status == "approved"
