"""Working-time calendars.

The arithmetic (next workday, index of a date) reuses
``app.pm.schedule.Calendar``. This module only decides which dates count
as work: a 5-day week, a 7-day cure week, a 24-hour lag calendar, or a
weather calendar that drops whole months. Holidays are the project's.

A 7-day cure calendar does not skip holidays: a cure runs in calendar
days. The 24-hour calendar is for lags that mean calendar days.
"""
import datetime as _dt

from ..schedule import Calendar as _Base

from .model import HOURS_PER_DAY, as_date

DAY = _dt.timedelta(days=1)


class WorkCalendar(_Base):
    """``schedule.Calendar`` with a chosen set of weekdays and months off.

    ``hours_per_day`` is how a workday converts to hours. The 24-hour lag
    calendar uses 24 so one calendar day is 24 hours, not an 8-hour shift.
    """

    def __init__(self, base, holidays=(), weekdays=None, months_off=(),
                 hours_per_day=HOURS_PER_DAY, name="5-day workweek",
                 key="5day"):
        self.weekdays = set(range(5) if weekdays is None else weekdays)
        self.months_off = set(months_off or ())
        self.hours_per_day = float(hours_per_day or HOURS_PER_DAY)
        self.name = name
        self.key = key
        super().__init__(as_date(base) or _dt.date.today(), holidays or ())

    def is_work(self, d):
        if d.month in self.months_off:
            return False
        return d.weekday() in self.weekdays and d not in self.hol


class IntersectCalendar(WorkCalendar):
    """A day counts only when every member calendar says it is work.

    Used for resource-dependent activities: the activity and each assigned
    resource have to be working. Member calendars must share a base that
    has at least one common workday, or building the index would spin.
    """

    def __init__(self, base, parts, name="Resource calendar", key="resource"):
        self.parts = list(parts)
        hpd = parts[0].hours_per_day if parts else HOURS_PER_DAY
        super().__init__(base, holidays=(), weekdays=range(7),
                         hours_per_day=hpd, name=name, key=key)

    def is_work(self, d):
        return bool(self.parts) and all(p.is_work(d) for p in self.parts)


def hours_per_day(key, act=None):
    if act is not None and act.get("_hpd"):
        return float(act["_hpd"])
    return float(HOURS_PER_DAY)


def snap_forward(cal, d):
    """First workday on or after ``d``."""
    d = as_date(d)
    return cal.date(cal.index(d))


def snap_back(cal, d):
    """Last workday on or before ``d``."""
    d = as_date(d)
    for _ in range(21):
        if cal.is_work(d):
            return d
        d -= DAY
    return cal.date(cal.index(as_date(d)))


def add_workdays(cal, start, days):
    """Finish date of a ``days``-workday activity that starts on ``start``.

    ``days`` of 0 returns the start workday (a milestone). ``days`` of 5
    starting Monday finishes Friday.
    """
    start = snap_forward(cal, start)
    n = int(round(days or 0))
    if n <= 0:
        return start
    return cal.date(cal.index(start) + n - 1)


def sub_workdays(cal, finish, days):
    """Start date of a ``days``-workday activity that finishes on ``finish``."""
    finish = snap_back(cal, finish)
    n = int(round(days or 0))
    if n <= 0:
        return finish
    return cal.date(cal.index(finish) - (n - 1))


def workdays_between(cal, a, b):
    """Workdays from date ``a`` to date ``b`` (b - a), signed."""
    if a is None or b is None:
        return 0
    return cal.index(as_date(b)) - cal.index(as_date(a))


def shift(cal, date, workdays):
    """Move ``workdays`` workdays from ``date`` (0 keeps a workday)."""
    date = as_date(date)
    return cal.date(cal.index(date) + int(round(workdays or 0)))


def standard_specs(holidays=(), weather_months=()):
    """The calendars a compiled schedule starts with.

    Keys are stable ids stored on activities. Names are what a person sees.
    """
    hol = [iso for iso in (str(h)[:10] for h in (holidays or ())) if iso]
    return {
        "5day": {
            "key": "5day",
            "name": "5-day workweek",
            "weekdays": [0, 1, 2, 3, 4],
            "months_off": [],
            "hours_per_day": 8,
            "holidays": hol,
            "kind": "project",
        },
        "7day": {
            "key": "7day",
            "name": "7-day cure calendar",
            "weekdays": [0, 1, 2, 3, 4, 5, 6],
            "months_off": [],
            "hours_per_day": 8,
            "holidays": [],          # a cure counts calendar days
            "kind": "project",
        },
        "24hour": {
            "key": "24hour",
            "name": "24-hour calendar",
            "weekdays": [0, 1, 2, 3, 4, 5, 6],
            "months_off": [],
            "hours_per_day": 24,
            "holidays": [],
            "kind": "project",
        },
        "weather": {
            "key": "weather",
            "name": "Weather calendar",
            "weekdays": [0, 1, 2, 3, 4],
            "months_off": list(weather_months or ()),
            "hours_per_day": 8,
            "holidays": hol,
            "kind": "project",
        },
    }


def build_calendar(spec, anchor):
    return WorkCalendar(
        anchor,
        holidays=spec.get("holidays") or (),
        weekdays=spec.get("weekdays"),
        months_off=spec.get("months_off") or (),
        hours_per_day=spec.get("hours_per_day") or HOURS_PER_DAY,
        name=spec.get("name") or spec.get("key") or "Calendar",
        key=spec.get("key") or "5day",
    )


def build_all(doc):
    """``{key: WorkCalendar}`` anchored well before the project start so a
    one-day lead still has an index."""
    start = as_date(doc["project"].get("start")) or _dt.date.today()
    anchor = start - _dt.timedelta(days=420)
    specs = doc.get("calendars") or {}
    if "5day" not in specs:
        specs = dict(standard_specs(), **specs)
        doc["calendars"] = specs
    out = {}
    for key, spec in specs.items():
        spec = dict(spec)
        spec["key"] = key
        out[key] = build_calendar(spec, anchor)
    return out
