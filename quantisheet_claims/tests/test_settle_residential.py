"""T1-T5 (residential) and findings 2, 3, 4, 16, 22, 23, 29."""
import dataclasses

from quantisheet_claims import model as m
from quantisheet_claims.settle import settle_claim
from .helpers import line, t1_claim


def test_t1_ten_thousand_dollar_example():
    s = settle_claim(t1_claim())
    assert (s.rc, s.op, s.rcv, s.dep, s.acv, s.net) == (
        1_024_000, 204_800, 1_228_800, 512_000, 716_800, 616_800)
    assert s.deductible == 100_000
    assert s.recoverable_holdback == 512_000          # paid later on proof
    assert s.total_now == 616_800


def test_t1_dep_on_op_base_rcv():
    # finding 16: DepPolicy.base replaces the hard-coded rule
    s = settle_claim(t1_claim(dep=m.DepPolicy(base="rcv")))
    assert s.dep == 614_400 and s.net == 514_400


def test_t2_percent_deductible_off_coverage_a():
    c = t1_claim(deductible=m.DeductibleSpec(kind="percent", bp=200,
                                             basis="coverage_a"))
    s = settle_claim(c)
    assert s.deductible == 600_000                 # 2% of $300,000, not RCV
    c = t1_claim(deductible=m.DeductibleSpec(kind="percent", bp=200, basis="rcv"))
    assert settle_claim(c).deductible == 24_576    # 2% of $12,288.00


def test_t2_per_peril_override_one_model():
    # finding 29: one DeductibleSpec, per-peril override replaces the base
    spec = m.DeductibleSpec(kind="flat", amount_cents=100_000, per_peril=(
        m.PerilDeductible("Wind", m.DeductibleSpec(kind="percent", bp=200)),))
    assert settle_claim(t1_claim(deductible=spec, peril="wind")).deductible == 600_000
    assert settle_claim(t1_claim(deductible=spec, peril="fire")).deductible == 100_000


def test_t3_ale_outside_deductible():
    s = settle_claim(t1_claim(ale=m.AleCoverage(daily_cents=10_000, days=30)))
    assert s.net == 616_800 and s.ale == 300_000
    assert s.total_indemnity == 916_800


def _ale(**kw):
    c = t1_claim(ale=m.AleCoverage(**kw))
    return settle_claim(c)


def test_t4_ale_limits():
    # (a) 20% of Cov A $300,000 = $60,000; cap $30,000; 120 x $300 = $36,000
    assert _ale(daily_cents=30_000, days=120, cap_cents=3_000_000,
                pct_of_cov_a_bp=2000).ale == 3_000_000
    # (b) no cap -> $36,000 (finding 2: % is off Cov A, not off the cap)
    assert _ale(daily_cents=30_000, days=120, cap_cents=None,
                pct_of_cov_a_bp=2000).ale == 3_600_000
    # (c) 10% of Cov A = $30,000 < cap $50,000 < 200 x $300
    s = _ale(daily_cents=30_000, days=200, cap_cents=5_000_000,
             pct_of_cov_a_bp=1000)
    assert s.ale == 3_000_000
    assert any(w.code == "ale_capped_by" and w.detail == "pct_of_coverage_a"
               for w in s.warnings)
    # (d) cap 0 means $0 (finding 3)
    assert _ale(daily_cents=30_000, days=120, cap_cents=0).ale == 0


def test_finding22_zero_percent_is_zero():
    assert _ale(daily_cents=30_000, days=10, pct_of_cov_a_bp=0).ale == 0
    assert _ale(daily_cents=30_000, days=10, pct_of_cov_a_bp=None).ale == 300_000


def test_finding23_days_limit_clamps():
    assert _ale(daily_cents=30_000, days=400, days_limit=365).ale == 30_000 * 365


def test_t5_ol_cap_after_op():
    ol = m.OrdinanceLaw(bp=1000, cap_cents=250_000, apply_op=True)
    c = t1_claim(ol=ol, lines=(line(5_000_000, 0, lid="Q"),))
    s = settle_claim(c)
    assert s.ol_uncapped == 600_000 and s.ol == 250_000   # finding 4
    assert any(w.code == "ol_capped" for w in s.warnings)
    ol2 = dataclasses.replace(ol, cap_cents=None)
    assert settle_claim(dataclasses.replace(c, ol=ol2)).ol == 600_000


def test_ol_categories_filter_and_not_depreciated():
    ol = m.OrdinanceLaw(bp=1000, categories=("FRAMING",))
    c = t1_claim(ol=ol, lines=(line(100_000, 5000, category="FRAMING"),
                               line(100_000, 5000, category="PAINTING")))
    s = settle_claim(c)
    assert s.ol == 10_000 and s.dep == 100_000


def test_deductible_exceeds_acv_warning_and_structure_limit():
    c = t1_claim(deductible=m.DeductibleSpec(kind="flat", amount_cents=10_000_000))
    s = settle_claim(c)
    assert s.net == 0 and any(w.code == "deductible_exceeds_acv" for w in s.warnings)
    c = t1_claim(structures=(m.Structure(id="S1", name="D", kind="dwelling",
                                         limit_cents=500_000),))
    s = settle_claim(c)
    assert s.net == 500_000 and any(w.code == "limit_reached" for w in s.warnings)


def test_rcv_basis_uses_total_rcv_across_structures():
    c = t1_claim(deductible=m.DeductibleSpec(kind="percent", bp=100, basis="rcv"),
                 structures=(m.Structure(id="S1", name="Dwelling", kind="dwelling",
                                         limit_cents=30_000_000),
                             m.Structure(id="S2", name="Garage",
                                         kind="other_structure")),
                 lines=t1_claim().lines + (line(100_000, 0, structure="S2"),))
    s = settle_claim(c)
    assert s.rcv == 1_228_800 + 120_000
    assert s.deductible == 13_488                    # 1% of $13,488.00
    assert s.net == s.acv - 13_488


def test_missing_coverage_a_warns_once():
    c = t1_claim(deductible=m.DeductibleSpec(kind="percent", bp=200),
                 structures=(m.Structure(id="S1", name="Dwelling"),))
    s = settle_claim(c)
    assert [w.code for w in s.warnings].count("no_coverage_a_limit") == 1
    assert s.deductible == 0
