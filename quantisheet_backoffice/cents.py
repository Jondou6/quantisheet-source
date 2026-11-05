"""Exact money: whole cents end to end, half-up rounding in one place.

Money is held as int cents and read/written as decimal strings. A float is
refused everywhere (it can't hold $0.10 exactly). Hours are held as int
hundredths of an hour the same way.
"""
from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

_AMOUNT = re.compile(r"^\(?-?\$?\s*-?(\d{1,3}(,\d{3})+|\d+)?(\.\d+)?\)?$")


class MoneyError(ValueError):
    """A value that can't be read as an exact amount."""


def D(v) -> Decimal:
    """Decimal from a str / int / Decimal. Floats are refused."""
    if isinstance(v, bool):
        raise MoneyError(f"{v!r} is not an amount")
    if isinstance(v, float):
        raise MoneyError(f"{v!r} is a float; use a decimal string")
    if isinstance(v, Decimal):
        return v
    if isinstance(v, int):
        return Decimal(v)
    if isinstance(v, str):
        try:
            d = Decimal(v.strip())
        except InvalidOperation:
            raise MoneyError(f"can't read {v!r} as a number") from None
        if not d.is_finite():
            raise MoneyError(f"can't read {v!r} as a number")
        return d
    raise MoneyError(f"can't read {v!r} as a number")


def round_half_up(d: Decimal, places: str = "1") -> Decimal:
    """THE one rounding rule (half up)."""
    return d.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def to_cents(v) -> int:
    """'12.50' / Decimal / int dollars -> 1250. Rounded half up to the cent."""
    return int(round_half_up(D(v) * 100))


def amount_in(v) -> int:
    """THE rule for amounts handed to a Back Office function: dollars, as
    text ('1,234.50', '(312.47)') or a Decimal, -> int cents. An int is
    refused (it was ambiguous: cents or dollars?). Code holding cents passes
    from_cents(c), which is an exact Decimal."""
    if isinstance(v, str):
        return parse_amount(v)
    if isinstance(v, Decimal):
        return to_cents(v)
    raise MoneyError(f"amounts are dollars as text or Decimal, not {v!r} "
                     f"(use cents.from_cents() for int cents)")


def parse_amount(text) -> int:
    """User / file text (or a Decimal) -> cents: '$1,234.50', '(312.47)',
    '-5'. Strict: '1,234.5x', '12,34' and a doubled sign such as '(-5)'
    raise MoneyError. An int is refused, as in amount_in."""
    if isinstance(text, Decimal):
        return to_cents(text)
    if not isinstance(text, str):
        raise MoneyError(f"can't read {text!r} as an amount")
    s = text.strip()
    if not s or not _AMOUNT.match(s) or not re.search(r"\d", s):
        raise MoneyError(f"can't read {text!r} as an amount")
    neg = s.startswith("(") and s.endswith(")")
    if s.startswith("(") != s.endswith(")"):
        raise MoneyError(f"can't read {text!r} as an amount")
    s = s.strip("()").replace("$", "").replace(",", "").replace(" ", "")
    if s.count("-") > 1 or (neg and "-" in s):
        raise MoneyError(f"can't read {text!r} as an amount")
    c = to_cents(s)
    return -c if neg else c


def from_cents(c: int) -> Decimal:
    if not isinstance(c, int) or isinstance(c, bool):
        raise MoneyError(f"cents must be an int, not {c!r}")
    return (Decimal(c) / 100).quantize(Decimal("0.01"))


def text(c: int) -> str:
    """1250 -> '12.50' (decimal string, for files and snapshots)."""
    return str(from_cents(c))


def fmt(c: int) -> str:
    """1234556 -> '$12,345.56'; negatives '-$312.47'."""
    d = from_cents(c)
    s = f"${abs(d):,.2f}"
    return "-" + s if d < 0 else s


def pct_of(c: int, pct) -> int:
    """pct % of c cents, half up: pct_of(123455, '10') == 12346."""
    return int(round_half_up(Decimal(c) * D(pct) / 100))


def mul(c: int, factor) -> int:
    """c cents x an exact factor (hours, quantity), half up."""
    return int(round_half_up(Decimal(c) * D(factor)))


def split(c: int, n: int) -> list[int]:
    """Split c into n parts that add back to c; the extra cents go first."""
    if n <= 0:
        raise MoneyError("split into at least one part")
    base, extra = divmod(abs(c), n)
    parts = [base + (1 if i < extra else 0) for i in range(n)]
    return [-p for p in parts] if c < 0 else parts


def hours(v) -> int:
    """'8', '9.5', Decimal('8.25') -> hundredths of an hour (int)."""
    return int(round_half_up(D(v) * 100))


def hours_text(h: int) -> str:
    return str((Decimal(h) / 100).quantize(Decimal("0.01")))


def percent_text(num: int, den: int, places: str = "0.1") -> str:
    """num/den as a percent string, half up: (3121000, 4800000) -> '65.0'."""
    if not den:
        return str(Decimal(0).quantize(Decimal(places)))
    return str(round_half_up(Decimal(num) * 100 / Decimal(den), places))
