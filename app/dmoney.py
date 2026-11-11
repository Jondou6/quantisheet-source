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


def _quantize(d, exp, v):
    """d rounded half up to `exp`. ValueError, not decimal's
    InvalidOperation, when the number is too big to carry those places
    (torture test, Nov 10: c2(1e300) and c2("1e400") raised an error no
    caller catches)."""
    try:
        return d.quantize(exp, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise ValueError(f"too large to round: {v!r}") from None


def cents(v):
    return _quantize(D(v), CENT, v)


def text(v):
    """Cents as plain text for storage: "1234.50"."""
    return str(cents(v))


def fmt(v):
    c = cents(v)
    sign = "-" if c < 0 else ""
    return f"{sign}${abs(c):,.2f}"


def _dec(v):
    """The Decimal of a number or of money text as people type it
    ("$1,000.125", "(1.125)" for a negative). ValueError for anything
    else, "nan" and "inf" text included - never a silent half-even
    fallback (Chief's round 7, Nov 9). A float NaN or infinity passes
    through c2/half_up unchanged, so a broken number shows as itself."""
    if isinstance(v, float):
        return Decimal(repr(v))
    if isinstance(v, (int, Decimal)):
        return Decimal(v)
    t = str(v).strip().replace("$", "").replace(",", "").strip()
    if t.startswith("(") and t.endswith(")"):
        t = "-" + t[1:-1].strip()
    try:
        d = Decimal(t)
    except (InvalidOperation, ValueError):
        raise ValueError(f"not a number: {v!r}") from None
    if not d.is_finite():
        raise ValueError(f"not a number: {v!r}")
    return d


def c2(v):
    """A float rounded to the cent, half up - the way an estimator rounds
    by hand: 1.125 -> 1.13, 0.125 -> 0.13 (Chief's round 5, Nov 9: float
    round() gave 1.12 and 0.12 - it rounds half to even, and 1.125 is
    exactly half). Decimal(repr(x)), so 2.675 is 2.68, not 2.67.

    A float is first rounded to 8 places (6 from $1M, 4 from $100M) so the
    noise of float arithmetic doesn't decide the cent: 1.15 x 10% is
    0.11499999999999999 in a float and comes out 0.12. That is a choice,
    not exact half-up: a value within about 5e-9 below a half cent
    (1.00499999999) rounds up too. Money is never meant to carry that many
    digits, so for money that is the right side to err on. None and blank
    are 0.0."""
    if v is None or v == "":
        return 0.0
    if isinstance(v, bool):
        v = int(v)
    if isinstance(v, float) and v != v:              # NaN stays NaN
        return v
    if isinstance(v, float) and abs(v) < 1e15:
        # float arithmetic leaves 0.11499999999999999 for 1.15 x 10%;
        # trimmed to the digits a float really holds, that's 0.115
        v = round(v, 8 if abs(v) < 1e6 else 6 if abs(v) < 1e8 else 4)
    d = _dec(v)
    if not d.is_finite():
        return float(d)
    return float(_quantize(d, CENT, v))


def half_up(v, places=2):
    """round(v, places) the way people round by hand: a 5 rounds up
    (0.125 -> 0.13 at 2 places, 2.25 -> 2.3 at 1). For quantities, hours
    and report figures; c2() is the money version (same float pre-trim).
    None and blank are 0.0."""
    if v is None or v == "":
        return 0.0
    if isinstance(v, bool):
        v = int(v)
    if isinstance(v, float):
        if v != v or abs(v) >= 1e15:
            return v
        v = round(v, max(places + 6, 8 if abs(v) < 1e6 else places + 4))
    d = _dec(v)
    if not d.is_finite():
        return float(d)
    return float(_quantize(d, Decimal(1).scaleb(-places), v))
