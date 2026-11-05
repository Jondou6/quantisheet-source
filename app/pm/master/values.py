"""Cell / form values -> normalized values (no Qt)."""
import datetime as _dt
import math
import re

EPOCH = _dt.date(1899, 12, 30)          # Excel's serial day 0


class Bad(ValueError):
    pass


def num(v):
    """int when whole, else float; None for blank. Bad for text."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, bool):
        raise Bad(f"'{v}' isn't a number")
    if isinstance(v, (int, float)):
        f = float(v)
    else:
        t = str(v).strip().rstrip("%").replace(",", "").strip()
        try:
            f = float(t)
        except ValueError:
            raise Bad(f"'{v}' isn't a number") from None
    if math.isnan(f) or math.isinf(f):
        raise Bad(f"'{v}' isn't a number")
    return int(f) if f == int(f) else f


def date(v):
    """ISO date text; accepts dates, Excel serial numbers, ISO and US
    text (11/04/2026, 11/4/26). None for blank. Bad otherwise."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    if isinstance(v, _dt.datetime):
        return v.date().isoformat()
    if isinstance(v, _dt.date):
        return v.isoformat()
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if 20000 <= v <= 80000:
            return (EPOCH + _dt.timedelta(days=int(v))).isoformat()
        raise Bad(f"'{v}' isn't a date")
    t = str(v).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}([ T].*)?", t):
        try:
            return _dt.date.fromisoformat(t[:10]).isoformat()
        except ValueError:
            raise Bad(f"'{v}' isn't a date") from None
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y"):
        try:
            return _dt.datetime.strptime(t, fmt).date().isoformat()
        except ValueError:
            continue
    raise Bad(f"'{v}' isn't a date (use 2026-11-05 or 11/05/2026)")


def text(v, limit=2000):
    return "" if v is None else str(v).strip()[:limit]


def base_of(act):
    """An activity's sub-editable values, normalized."""
    def n(v):
        try:
            return num(v)
        except Bad:
            return None

    def d(v):
        try:
            return date(v)
        except Bad:
            return None
    return {"duration": n(act.get("duration")),
            "expected_finish": None,
            "percent": n(act.get("percent")),
            "actual_start": d(act.get("actual_start")),
            "actual_finish": d(act.get("actual_finish")),
            "note": ""}
