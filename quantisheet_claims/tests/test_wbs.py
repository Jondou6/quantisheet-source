"""T7 and findings 5, 6, 12."""
import pytest

from quantisheet_claims import model as m
from quantisheet_claims.settle import settle_claim
from quantisheet_claims.wbs import WbsError, auto_group, rollup
from .helpers import line, t1_claim

OP = m.OpPolicy(overhead_bp=1000, profit_bp=1000)


def _tree():
    # ordinals chosen so the paste's "ordinal desc" order is
    # drywall(9), kitchen(5), walls(1), root(0): kitchen would push up
    # before walls arrived and the money would be lost (finding 5)
    return (m.WbsNode("root", "Dwelling", ordinal=0),
            m.WbsNode("kitchen", "Kitchen", "root", ordinal=5),
            m.WbsNode("walls", "Walls", "kitchen", ordinal=1),
            m.WbsNode("drywall", "Drywall", "walls", ordinal=9))


def test_t7_rollup_children_first_and_rcv_recomputed():
    ln = line(100_000, 5000, group="drywall")
    t = rollup(_tree(), [ln], OP)
    r = t["root"]
    assert (r.rc, r.op, r.rcv, r.acv) == (100_000, 20_000, 120_000, 70_000)
    assert t["kitchen"] == t["walls"] == t["drywall"] == r   # finding 6
    s = settle_claim(t1_claim(lines=(ln,)))
    assert (s.rc, s.op, s.rcv, s.acv) == (r.rc, r.op, r.rcv, r.acv)


def test_finding12_aggregate_vs_per_line_both_match_settle():
    lines = [line(2, 0, group="drywall") for _ in range(300)]
    for app, want in (("aggregate", 120), ("per_line", 0)):
        op = m.OpPolicy(overhead_bp=1000, profit_bp=1000, application=app)
        r = rollup(_tree(), lines, op)["root"]
        assert r.op == want
        assert settle_claim(t1_claim(op=op, lines=tuple(lines))).op == want


def test_modes_exempt_custom_and_dep_override():
    nodes = (m.WbsNode("root", "D"),
             m.WbsNode("a", "A", "root", op_mode="exempt"),
             m.WbsNode("b", "B", "root", op_mode="custom", overhead_bp=500,
                       profit_bp=500, dep_override_bp=1000),
             m.WbsNode("b1", "B1", "b"))
    t = rollup(nodes, [line(100_000, 5000, group="a"),
                       line(100_000, 5000, group="b1")], OP)
    assert t["a"].op == 0 and t["b"].op == 10_000 and t["root"].op == 10_000
    assert t["b"].dep == 10_000 and t["root"].dep == 60_000


def test_cycles_and_missing_parents_refused():
    with pytest.raises(WbsError):
        rollup((m.WbsNode("a", "A", "b"), m.WbsNode("b", "B", "a")), [], OP)
    with pytest.raises(WbsError):
        rollup((m.WbsNode("a", "A", "zzz"),), [], OP)


def test_auto_group_by_trade_group():
    c = t1_claim()
    nodes, lines = auto_group(c)
    names = sorted(n.name for n in nodes)
    assert names == ["Dwelling", "Interior finishes", "Site & general"]
    t = rollup(nodes, lines, c.op)
    root = [n for n in nodes if not n.parent_id][0]
    s = settle_claim(c)
    assert t[root.id].rc == s.rc and t[root.id].op == s.op
