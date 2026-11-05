"""Units for construction quantities.

A Quantity carries its dimensions (length, mass, time, count, money) and
refuses to add unlike things, so "square metres where square feet were
expected" is an error when the estimate is built, not a wrong bid.

Base units: ft, lb, hr, ea, $. "day" and "wk" are 8 and 40 crew-hours.
(Adapted from the Venice AI draft; multiply/divide rewritten.)
"""
import re

__all__ = ["UnitError", "Quantity", "q", "parse_unit", "parse_quantity",
           "compatible", "measure_to_base", "MEASURE_BASE"]


class UnitError(ValueError):
    """Unknown unit, or two quantities that can't be combined."""


# unit -> (factor to base, dimensions)
_UNITS = {
    "in": (1 / 12, {"L": 1}), "ft": (1.0, {"L": 1}), "yd": (3.0, {"L": 1}),
    "mi": (5280.0, {"L": 1}), "mm": (0.0032808398950131233, {"L": 1}),
    "cm": (0.03280839895013123, {"L": 1}), "m": (3.280839895013123, {"L": 1}),
    "km": (3280.839895013123, {"L": 1}), "lf": (1.0, {"L": 1}),
    "sf": (1.0, {"L": 2}), "msf": (1000.0, {"L": 2}), "sy": (9.0, {"L": 2}),
    "sq": (100.0, {"L": 2}), "sm": (10.763910416709722, {"L": 2}),
    "si": (1 / 144, {"L": 2}), "acre": (43560.0, {"L": 2}),
    "cf": (1.0, {"L": 3}), "cy": (27.0, {"L": 3}),
    "m3": (35.31466672148859, {"L": 3}), "ci": (1 / 1728, {"L": 3}),
    "gal": (0.13368055555555555, {"L": 3}), "l": (0.03531466672148859, {"L": 3}),
    "lb": (1.0, {"M": 1}), "ton": (2000.0, {"M": 1}),
    "kg": (2.2046226218487757, {"M": 1}), "mt": (2204.6226218487757, {"M": 1}),
    "min": (1 / 60, {"T": 1}), "hr": (1.0, {"T": 1}), "day": (8.0, {"T": 1}),
    "wk": (40.0, {"T": 1}),
    "ea": (1.0, {"C": 1}), "$": (1.0, {"$": 1}),
}
_ALIAS = {
    "'": "ft", "feet": "ft", "foot": "ft", '"': "in", "inch": "in",
    "inches": "in", "sqft": "sf", "sq ft": "sf", "sq.ft.": "sf",
    "sq in": "si", "sq m": "sm", "sqm": "sm", "m2": "sm", "sq yd": "sy",
    "cu ft": "cf", "cuft": "cf", "cu yd": "cy", "cuyd": "cy", "cu m": "m3",
    "cu in": "ci", "each": "ea", "pcs": "ea", "pc": "ea", "set": "ea",
    "pr": "ea", "ls": "ea", "hrs": "hr", "hour": "hr", "hours": "hr",
    "days": "day", "tons": "ton", "lbs": "lb", "usd": "$",
}
_BASE = {"L": "ft", "M": "lb", "T": "hr", "C": "ea", "$": "$"}
_PREFERRED = ["ft", "sf", "cf", "lb", "hr", "ea", "$"]


def _norm(dims):
    return tuple(sorted((k, int(v) if abs(v - round(v)) < 1e-9 else v)
                        for k, v in dims.items() if abs(v) > 1e-9))


_BY_DIMS = {}
for _u in _PREFERRED + list(_UNITS):
    _BY_DIMS.setdefault(_norm(_UNITS[_u][1]), _u)


def _one(tok):
    m = re.match(r"^([A-Za-z$'\"]+)(?:\^?(-?\d+))?$", tok)
    if not m:
        raise UnitError(f"can't read unit {tok!r}")
    name = _ALIAS.get(m.group(1).lower(), m.group(1).lower())
    if name not in _UNITS:
        raise UnitError(f"unknown unit {name!r}")
    exp = int(m.group(2)) if m.group(2) else 1
    f, dims = _UNITS[name]
    return f ** exp, {k: v * exp for k, v in dims.items()}


def parse_unit(text):
    """(factor to base, dimensions) for 'sf', 'hr/sf', '$/cy', 'sq ft'."""
    t = str(text or "").strip().lower()
    t = t.replace("²", "^2").replace("³", "^3")
    if not t or t in ("1", "-"):
        return 1.0, ()
    if t in _ALIAS:
        t = _ALIAS[t]
    else:   # "sq cm", "cu mm", "sq. ft"
        m = re.match(r"^(sq|cu)\.?\s+([a-z]+)\.?$", t)
        if m:
            t = f"{_ALIAS.get(m.group(2), m.group(2))}^" \
                f"{2 if m.group(1) == 'sq' else 3}"
    t = t.replace(" per ", "/")
    t = re.sub(r"\s*([*/])\s*", r"\1", t)
    t = re.sub(r"\s+", "*", t)
    factor, dims, sign = 1.0, {}, 1
    for part in re.split(r"([*/])", t):
        if part in ("*", "/"):
            sign = 1 if part == "*" else -1
            continue
        if not part:
            continue
        f, d = _one(part)
        factor *= f ** sign
        for k, v in d.items():
            dims[k] = dims.get(k, 0) + sign * v
    return factor, _norm(dims)


def _unit_for(dims):
    if not dims:
        return ""
    hit = _BY_DIMS.get(_norm(dict(dims)))
    if hit:
        return hit

    def side(parts):
        return "*".join(u if e == 1 else f"{u}^{e}" for u, e in sorted(parts))
    num = [(_BASE[k], v) for k, v in dims if v > 0]
    den = [(_BASE[k], -v) for k, v in dims if v < 0]
    return (side(num) or "1") + ("/" + side(den) if den else "")


class Quantity:
    """A number with a unit. Arithmetic checks dimensions."""

    __slots__ = ("value", "unit", "dims", "factor")

    def __init__(self, value=0.0, unit=""):
        self.factor, self.dims = parse_unit(unit)
        self.value = float(value)
        self.unit = str(unit or "").strip()

    def base(self):
        return self.value * self.factor

    def to(self, unit):
        f, d = parse_unit(unit)
        if d != self.dims:
            raise UnitError(f"{self.unit or 'a number'} can't be shown "
                            f"as {unit}")
        return Quantity(self.base() / f, unit)

    @staticmethod
    def _of_base(value, dims):
        unit = _unit_for(dims)
        f = parse_unit(unit)[0] if unit else 1.0
        return Quantity(value / f, unit)

    def __add__(self, other):
        o = _as_q(other)
        if o.dims != self.dims:
            raise UnitError(f"can't add {o.unit or 'a number'} to "
                            f"{self.unit or 'a number'}")
        return Quantity(self.value + o.base() / self.factor, self.unit)

    __radd__ = __add__

    def __neg__(self):
        return Quantity(-self.value, self.unit)

    def __sub__(self, other):
        return self + (-_as_q(other))

    def __rsub__(self, other):
        return _as_q(other) - self

    def _combine(self, o, sign):
        d = dict(self.dims)
        for k, v in o.dims:
            d[k] = d.get(k, 0) + sign * v
        return _norm(d)

    def __mul__(self, other):
        o = _as_q(other)
        return Quantity._of_base(self.base() * o.base(), self._combine(o, 1))

    __rmul__ = __mul__

    def __truediv__(self, other):
        o = _as_q(other)
        if o.base() == 0:
            raise UnitError("divide by zero")
        return Quantity._of_base(self.base() / o.base(), self._combine(o, -1))

    def __rtruediv__(self, other):
        return _as_q(other) / self

    def __pow__(self, n):
        return Quantity._of_base(self.base() ** n,
                                 _norm({k: v * n for k, v in self.dims}))

    def round_to(self, step=1, up=True):
        import math
        if step <= 0:
            return Quantity(self.value, self.unit)
        n = self.value / step
        return Quantity((math.ceil(n) if up else math.floor(n)) * step,
                        self.unit)

    def same_dim(self, other):
        return _as_q(other).dims == self.dims

    def __eq__(self, other):
        try:
            o = _as_q(other)
        except UnitError:
            return False
        return o.dims == self.dims and abs(self.base() - o.base()) < 1e-9

    def __lt__(self, other):
        o = _as_q(other)
        if o.dims != self.dims:
            raise UnitError("can't compare unlike units")
        return self.base() < o.base()

    def __gt__(self, other):
        return _as_q(other) < self

    def __hash__(self):
        return hash((round(self.base(), 9), self.dims))

    def __float__(self):
        return self.value

    def __bool__(self):
        return abs(self.value) > 1e-12

    def __str__(self):
        return f"{self.value:,.4g} {self.unit}".strip()

    __repr__ = __str__


def _as_q(x):
    if isinstance(x, Quantity):
        return x
    if isinstance(x, (int, float)):
        return Quantity(x, "")
    if isinstance(x, str):
        return parse_quantity(x)
    raise UnitError(f"can't use {x!r} as a quantity")


def q(value, unit=""):
    return Quantity(value, unit)


def parse_quantity(text):
    """'12.5 sf' or '3 cy' -> Quantity."""
    m = re.match(r"^\s*(-?[\d,]*\.?\d+)\s*(.*)$", str(text))
    if not m:
        raise UnitError(f"can't read quantity {text!r}")
    return Quantity(float(m.group(1).replace(",", "")), m.group(2).strip())


def compatible(a, b):
    try:
        return parse_unit(getattr(a, "unit", a))[1] == \
            parse_unit(getattr(b, "unit", b))[1]
    except UnitError:
        return False


# ---- measurements ------------------------------------------------------------

# what an assembly formula's measurement names are in: feet based
MEASURE_BASE = {"length": "ft", "area": "sf", "volume": "cf", "count": "ea"}


def measure_to_base(value, unit, mtype):
    """A measurement in the drawing's units (e.g. 12 'sq m') as the
    feet-based number assembly formulas expect (129.17 sf). Raises
    UnitError if the unit doesn't fit the measurement type."""
    base = MEASURE_BASE.get(mtype)
    if base is None or mtype == "count":
        return float(value)
    u = (unit or "").strip().lower()
    if not u:
        return float(value)
    return Quantity(value, u).to(base).value
