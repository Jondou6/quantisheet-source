"""T8, T9, T14 and findings 1, 9, 13, 18, 28: the one rounding rule."""
import random
from decimal import ROUND_HALF_UP, Decimal

import pytest

from quantisheet_claims import cents as c


def test_t14_apply_bp_no_double_rounding():
    # finding 1: money.ts gave 2, 2, 200001, 1019, 12201, 1100001, 200
    assert c.apply_bp(100, 100) == 1
    assert c.apply_bp(10000, 1) == 1
    assert c.apply_bp(1_000_000, 2000) == 200_000
    assert c.apply_bp(12345, 825) == 1018
    assert c.apply_qty(122, 1_000_000) == 12_200          # 100 SF x $1.22
    assert c.scale_qty(1_000_000, 11000) == 1_100_000
    assert c.round_to(100, 100) == 100
    assert c.round_to(149, 100) == 100
    assert c.round_to(150, 100) == 200


def test_t14_negatives_away_from_zero():
    # finding 18: README formula gave 0 and -1; one rule here
    assert c.apply_bp(-5000, 1) == -1
    assert c.apply_bp(-15000, 1) == -2
    assert c.apply_bp(-6000, 1) == -1
    assert c.div_round_half_up(-5, 2) == -3


def test_t14_matches_decimal_half_up_200k():
    rnd = random.Random(7)
    for _ in range(200_000):
        a, b = rnd.randint(-10**7, 10**7), rnd.randint(0, 30000)
        want = int((Decimal(a) * b / 10000).quantize(Decimal(1), ROUND_HALF_UP))
        assert c.apply_bp(a, b) == want


def test_finding28_big_amounts_exact():
    # JS lost exactness past 2^53; Python ints don't
    a = 460_000_000_000
    assert c.apply_bp(a, 10000) == a
    assert c.apply_bp(10**20 + 1, 5000) == 5 * 10**19 + 1


def test_t8_parsing_and_rounding():
    # finding 9: no floats, no Math.round surprises
    assert c.to_cents("1.005") == 101
    assert c.to_cents("-0.005") == -1
    assert c.parse_money("1,234.50") == 123450
    assert c.parse_money("$12.00") == 1200
    assert c.parse_money("(5.00)") == -500
    assert c.parse_qty("1,234.50") == 12_345_000
    for bad in ("12.5O", "12,5OO", "", "twenty", "(-5)"):
        with pytest.raises(c.MoneyError):
            c.parse_money(bad)
    with pytest.raises(c.MoneyError):
        c.parse_money(0.1)                     # floats refused
    with pytest.raises(TypeError):
        c.div_round_half_up(1.5, 2)


def test_fmt_and_text():
    assert c.fmt(-123456) == "-$1,234.56"
    assert c.fmt(5) == "$0.05"
    assert c.money_text(13972222) == "139722.22"
    assert c.money_text(-123450) == "-1234.50"
    assert c.qty_text(12_345_000) == "1234.5000"
    assert c.to_bp("12.5") == 1250 and c.bp_text(1250) == "12.5"


def test_t9_drift_bound():
    # finding 13: per-line vs aggregate O&P drift is at most 0.5 cent/line
    lines = [2] * 300
    per = sum(c.apply_bp(x, 2000) for x in lines)
    agg = c.apply_bp(sum(lines), 2000)
    assert per - agg == -120
    rnd = random.Random(1)
    for _ in range(300):
        L = [rnd.randint(1000, 40000) for _ in range(300)]
        d = sum(c.apply_bp(x, 2000) for x in L) - c.apply_bp(sum(L), 2000)
        assert abs(d) * 2 <= len(L)
    half = [100] * 300                          # 10.5% of $1.00 = 10.5 cents
    assert sum(c.apply_bp(x, 1050) for x in half) - c.apply_bp(30000, 1050) == 150
