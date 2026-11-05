"""Money in exact decimal cents. New money math goes through here; older
float code is converted at the boundary with D().

    D(0.1) + D(0.2) == D("0.3")      # True - floats go through str()
    cents(12.345)  -> Decimal("12.35")   (half up)
    fmt(1234.5)    -> "$1,234.50"
"""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")


def D(v):
    """A Decimal from a number or text ("$1,234.50"); 0 for blank/bad."""
    if isinstance(v, Decimal):
        return v
    if v is None or v == "":
        return Decimal(0)
    if isinstance(v, float):
        v = repr(v)                  # shortest text: 0.1 -> "0.1"
    s = str(v).replace("$", "").replace(",", "").strip()
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    try:
        d = Decimal(s)
    except InvalidOperation:
        return Decimal(0)
    return -d if neg else d


def bad(v, blank_ok=True):
    """True when `v` can't be read as a number - text like "twenty" or
    "8.5O" (letter O) - which D() quietly turns into 0. Blank is bad only
    when blank_ok is False (a rate that must be filled in)."""
    if v is None or str(v).strip() == "":
        return not blank_ok
    if isinstance(v, bool):
        return True
    if isinstance(v, (int, Decimal)):
        return isinstance(v, Decimal) and not v.is_finite()
    if isinstance(v, float):
        v = repr(v)
    s = str(v).replace("$", "").replace(",", "").strip()
    if s.startswith("(") and s.endswith(")"):
        s = s[1:-1].strip()
        if s.startswith(("-", "+")):
            return True                       # "(-500)": which sign?
    try:
        return not Decimal(s).is_finite()
    except InvalidOperation:
        return True


def cents(v):
    return D(v).quantize(CENT, rounding=ROUND_HALF_UP)


def text(v):
    """Cents as plain text for storage: "1234.50"."""
    return str(cents(v))


def fmt(v):
    c = cents(v)
    sign = "-" if c < 0 else ""
    return f"{sign}${abs(c):,.2f}"
