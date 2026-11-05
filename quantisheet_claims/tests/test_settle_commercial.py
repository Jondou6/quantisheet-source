"""C1-C8: commercial settlement (coinsurance, scheduled/blanket limits,
per-building/per-occurrence deductibles, BI/EE, compound O&P)."""
import dataclasses

from quantisheet_claims import model as m
from quantisheet_claims.settle import settle_claim, op_amount
from .helpers import c8_claim, line


def _one(value, limit, coins, loss, ded, agreed=False):
    return m.Claim(
        id="c", claim_number="C", claim_type="commercial",
        deductible=m.DeductibleSpec(amount_cents=ded),
        deductible_mode="per_building",
        limits=m.LimitPlan(agreed_value=agreed),
        structures=(m.Structure(id="B", name="B", kind="building",
                                value_cents=value, limit_cents=limit,
                                coins_bp=coins),),
        lines=(line(loss, structure="B"),))


def test_c1_coinsurance_textbook():
    s = settle_claim(_one(25_000_000, 10_000_000, 8000, 4_000_000, 25_000))
    st = s.structures[0]
    assert st.after_coinsurance == 2_000_000 and s.total_now == 1_975_000
    w = [w for w in s.warnings if w.code == "coinsurance_penalty"][0]
    assert w.amount == 2_000_000
    assert settle_claim(_one(25_000_000, 20_000_000, 8000, 4_000_000, 25_000)
                        ).total_now == 3_975_000
    assert settle_claim(_one(25_000_000, 10_000_000, 8000, 4_000_000, 25_000,
                             agreed=True)).total_now == 3_975_000


def _two(**kw):
    base = dict(
        id="c2", claim_number="C2", claim_type="commercial",
        deductible=m.DeductibleSpec(amount_cents=500_000),
        deductible_mode="per_building",
        structures=(
            m.Structure(id="B1", name="B1", kind="building", value_cents=100_000_000,
                        limit_cents=80_000_000, coins_bp=8000),
            m.Structure(id="B2", name="B2", kind="building", value_cents=50_000_000,
                        limit_cents=30_000_000, coins_bp=8000)),
        lines=(line(10_000_000, structure="B1"), line(6_000_000, structure="B2")))
    base.update(kw)
    return m.Claim(**base)


def test_c2_scheduled():
    s = settle_claim(_two())
    b1, b2 = s.structures
    assert b1.paid_now == 9_500_000
    assert b2.after_coinsurance == 4_500_000 and b2.paid_now == 4_000_000
    assert s.total_now == 13_500_000


def test_c3_blanket():
    s = settle_claim(_two(deductible_mode="per_occurrence",
                          deductible=m.DeductibleSpec(amount_cents=1_000_000),
                          limits=m.LimitPlan(mode="blanket",
                                             blanket_limit_cents=110_000_000,
                                             blanket_coins_bp=9000)))
    assert s.after_coinsurance == 13_037_037 and s.total_now == 12_037_037
    s = settle_claim(_two(deductible_mode="per_occurrence",
                          deductible=m.DeductibleSpec(amount_cents=1_000_000),
                          limits=m.LimitPlan(mode="blanket",
                                             blanket_limit_cents=130_000_000,
                                             blanket_coins_bp=8000)))
    assert s.total_now == 15_000_000
    assert not any(w.code == "coinsurance_penalty" for w in s.warnings)


def test_c4_limit_cap():
    s = settle_claim(_one(30_000_000, 30_000_000, 8000, 35_000_000, 1_000_000))
    assert s.structures[0].after_deductible == 34_000_000
    assert s.total_now == 30_000_000
    assert any(w.code == "limit_reached" for w in s.warnings)


def test_c5_business_income():
    bi = m.BusinessIncome(daily_net_income_cents=200_000,
                          daily_continuing_expense_cents=150_000,
                          restoration_days=30, waiting_hours=72,
                          extra_expense_cents=1_200_000, limit_cents=10_000_000)
    s = settle_claim(dataclasses.replace(
        _one(25_000_000, 20_000_000, 8000, 4_000_000, 25_000), bi_ee=bi))
    assert (s.bi_days, s.bi, s.ee, s.bi_ee) == (27, 9_450_000, 1_200_000, 10_000_000)
    assert any(w.code == "bi_limit_reached" for w in s.warnings)
    assert s.total_indemnity == 3_975_000 + 10_000_000    # not reduced by deductible
    c = dataclasses.replace(_one(25_000_000, 20_000_000, 8000, 4_000_000, 25_000),
                            bi_ee=dataclasses.replace(bi, limit_cents=None))
    assert settle_claim(c).bi_ee == 10_650_000


def test_c6_commercial_op():
    comp = m.OpPolicy(overhead_bp=1000, profit_bp=1000, compound=True)
    assert op_amount(10_000_000, comp) == (1_000_000, 1_100_000)
    add = m.OpPolicy(overhead_bp=1000, profit_bp=1000)
    assert sum(op_amount(10_000_000, add)) == 2_000_000


def test_c7_deductible_modes():
    s = settle_claim(_two(deductible=m.DeductibleSpec(amount_cents=1_000_000)))
    assert s.total_now == 12_500_000
    s = settle_claim(_two(deductible=m.DeductibleSpec(amount_cents=1_000_000),
                          deductible_mode="per_occurrence"))
    assert s.total_now == 13_500_000


def test_c8_end_to_end():
    s = settle_claim(c8_claim())
    st = s.structures[0]
    assert (s.op, s.rcv, s.dep, s.acv) == (4_200_000, 24_200_000, 5_000_000, 19_200_000)
    assert st.after_coinsurance == 14_222_222
    assert s.total_now == 13_972_222
    assert s.recoverable_holdback == 3_703_704


def test_structure_own_deductible_overrides():
    c = dataclasses.replace(_two(), structures=(
        dataclasses.replace(_two().structures[0],
                            deductible=m.DeductibleSpec(amount_cents=0)),
        _two().structures[1]))
    s = settle_claim(c)
    assert s.structures[0].paid_now == 10_000_000
