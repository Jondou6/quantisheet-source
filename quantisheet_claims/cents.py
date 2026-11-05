"""Money and quantity arithmetic: integer cents, basis points, qty_q4.

One rounding rule for the whole module: round half up, exact halves go
AWAY FROM ZERO (a -0.5 cent credit is -1 cent). This matches QuantiSheet's
app/dmoney.cents (Decimal ROUND_HALF_UP). The pasted money.ts added the
half and then rounded again (double rounding, ~50% of results 1 cent
high); that is not repeated here.

Never use float or Python round() for money (round() is half-to-even).
"""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

BP = 10_000          # basis points in 100%
Q4 = 10_000          # qty_q4 units in 1.0


class MoneyError(ValueError):
    """Text that can't be read as a number ("12,5OO"). Never silently 0."""


def div_round_half_up(num: int, den: int) -> int:
    """Round num/den to the nearest int; exact halves go away from zero."""
    if isinstance(num, bool) or isinstance(den, bool) or \
            not isinstance(num, int) or not isinstance(den, int):
        raise TypeError("div_round_half_up takes ints")
    if den <= 0:
        raise ValueError("den must be > 0")
    if num < 0:
        return -div_round_half_up(-num, den)
    q, r = divmod(num, den)
    return q + 1 if 2 * r >= den else q


def apply_bp(cents: int, bp: int) -> int:
    """cents x bp / 10000, rounded once."""
    return div_round_half_up(cents * bp, BP)


def apply_qty(unit_cents: int, q4: int) -> int:
    """unit price (cents) x quantity (ten-thousandths), rounded once."""
    return div_round_half_up(unit_cents * q4, Q4)


def scale_qty(q4: int, factor_bp: int) -> int:
    """quantity x factor (bp), rounded once to qty_q4."""
    return div_round_half_up(q4 * factor_bp, BP)


def round_to(cents: int, step: int) -> int:
    """Round to a multiple of `step` cents (1 = no change)."""
    if step <= 1:
        return cents
    return div_round_half_up(cents, step) * step


def mul_div(a: int, b: int, c: int) -> int:
    """a x b / c rounded once (c > 0). Used for ratios such as coinsurance
    so a ratio is never rounded on its own."""
    return div_round_half_up(a * b, c)


# ---- text at the boundary (a copy of app/dmoney.D / bad logic; no import)

def _clean(text) -> str:
    if isinstance(text, bool):
        raise MoneyError("a yes/no value is not a number")
    if isinstance(text, float):
        raise MoneyError("floats are not accepted; pass text or Decimal")
    s = str(text).replace("$", "").replace(",", "").strip()
    return s


def parse_decimal(text) -> Decimal:
    """Decimal from text such as "$1,234.50" or "(5.00)" (= -5.00).
    Raises MoneyError for blank or bad text."""
    if isinstance(text, Decimal):
        if not text.is_finite():
            raise MoneyError("not a finite number")
        return text
    if isinstance(text, int) and not isinstance(text, bool):
        return Decimal(text)
    s = _clean(text)
    if not s:
        raise MoneyError("blank")
    neg = s.startswith("(") and s.endswith(")")
    if neg:
        s = s[1:-1].strip()
        if s.startswith(("-", "+")):
            raise MoneyError(f"can't read {text!r} (which sign?)")
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise MoneyError(f"can't read {text!r} as a number") from None
    if not d.is_finite():
        raise MoneyError(f"can't read {text!r} as a number")
    return -d if neg else d


def to_cents(d) -> int:
    d = parse_decimal(d)
    return int(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100)


def to_q4(d) -> int:
    d = parse_decimal(d)
    return int((d * Q4).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def to_bp(pct) -> int:
    """Percent text ("12.5") -> basis points (1250)."""
    d = parse_decimal(pct)
    return int((d * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def parse_money(text) -> int:
    return to_cents(text)


def parse_qty(text) -> int:
    return to_q4(text)


def fmt(cents: int) -> str:
    """$1,234.50 / -$5.00"""
    sign = "-" if cents < 0 else ""
    c = abs(int(cents))
    return f"{sign}${c // 100:,}.{c % 100:02d}"


def money_text(cents: int) -> str:
    """Plain exact text for files: 1234.50 / -5.00"""
    sign = "-" if cents < 0 else ""
    c = abs(int(cents))
    return f"{sign}{c // 100}.{c % 100:02d}"


def qty_text(q4: int) -> str:
    sign = "-" if q4 < 0 else ""
    q = abs(int(q4))
    return f"{sign}{q // Q4}.{q % Q4:04d}"


def bp_text(bp: int) -> str:
    """1250 -> 12.5 (percent, no trailing zeros)"""
    d = (Decimal(bp) / 100).normalize()
    return format(d, "f")
