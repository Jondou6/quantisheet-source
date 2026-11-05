"""JSON files the service tools keep in the data folder.

Money is stored as cent text ("12.50") so a file round-trips through
Decimal without binary floats. Paths go through estimating._io, the same
guard the other estimating files use. Nothing here makes a network call.
"""
import datetime as dt
import os
import uuid
from decimal import ROUND_HALF_UP, Decimal

from .. import dmoney
from ..estimating import _io


class FileError(ValueError):
    pass


def new_id():
    return uuid.uuid4().hex[:10]


def txt(v, n=200):
    return " ".join(str(v or "").split())[:n]


def iso_date(v, what, blank_ok=True):
    if v in (None, ""):
        if blank_ok:
            return ""
        raise FileError(f"{what}: type a date (YYYY-MM-DD).")
    if isinstance(v, dt.datetime):
        v = v.date()
    if isinstance(v, dt.date):
        return v.isoformat()
    try:
        return dt.date.fromisoformat(str(v).strip()).isoformat()
    except ValueError:
        raise FileError(f"{what}: {v!r} isn't a date (YYYY-MM-DD).")


def as_date(v):
    return dt.date.fromisoformat(v) if v else None


def money(v, what, allow_blank=False):
    """Cent text, or '' when blank is allowed. Negative amounts are refused."""
    if v in (None, "") and allow_blank:
        return ""
    if dmoney.bad(v, blank_ok=False):
        raise FileError(f"{what} isn't a dollar amount.")
    d = dmoney.D(v)
    if d < 0:
        raise FileError(f"{what} can't be negative.")
    return dmoney.text(d)


def qty(v, what, places="0.01"):
    if dmoney.bad(v, blank_ok=False):
        raise FileError(f"{what} isn't a number.")
    d = dmoney.D(v).quantize(Decimal(places), rounding=ROUND_HALF_UP)
    if d <= 0:
        raise FileError(f"{what} must be more than zero.")
    return format(d, "f")


def lbs(v, what, allow_zero=True):
    """Pounds to a thousandth (refrigerant added or recovered)."""
    if dmoney.bad(v, blank_ok=False):
        raise FileError(f"{what} isn't a number of pounds.")
    d = dmoney.D(v).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    if d < 0:
        raise FileError(f"{what} can't be negative.")
    if d == 0 and not allow_zero:
        raise FileError(f"{what} must be more than zero.")
    return format(d, "f")


def plain(v):
    if isinstance(v, Decimal):
        return dmoney.text(v)
    if isinstance(v, dict):
        return {str(k): plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [plain(x) for x in v]
    return v


def path_for(name, path=None):
    if path:
        return os.path.abspath(os.path.expanduser(str(path)))
    return _io.data_file(name)


def read(path, kind, blank):
    """The file at `path`, or `blank()` when it is not there yet."""
    base = blank()
    if not path or not os.path.isfile(path):
        return base
    try:
        data = _io.read_json(path)
    except ValueError as e:
        raise FileError(f"Can't read {os.path.basename(path)}: {e}") from e
    if not isinstance(data, dict) or data.get("kind") != kind:
        raise FileError(f"{os.path.basename(path)} is not a {kind} file.")
    for k, v in base.items():
        if k not in data:
            data[k] = v
    return data


def write(path, data):
    return _io.write_json(path, plain(data))
