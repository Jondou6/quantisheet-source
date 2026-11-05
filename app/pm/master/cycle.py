"""Monthly update cycle: the data date is the nth (1-4) or last
Thursday of the month (configurable). Reminders are drafts only."""
import calendar as _cal
import datetime as _dt

from .. import schedule
from . import model

WEEKDAYS = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4}


def data_date(cfg, year, month):
    wd = WEEKDAYS.get(str(cfg.get("weekday") or "Thu")[:3].title(), 3)
    nth = cfg.get("nth", "last")
    days = [d for d in range(1, _cal.monthrange(year, month)[1] + 1)
            if _dt.date(year, month, d).weekday() == wd]
    if nth == "last":
        return _dt.date(year, month, days[-1])
    try:
        k = int(nth)
    except (TypeError, ValueError):
        k = 0
    if not 1 <= k <= 4:
        raise ValueError("Which Thursday: 1, 2, 3, 4 or 'last'.")
    return _dt.date(year, month, days[k - 1])


def next_date(cfg, today=None):
    """The cycle's data date on or after `today`."""
    today = today or _dt.date.today()
    y, m = today.year, today.month
    for _ in range(3):
        d = data_date(cfg, y, m)
        if d >= today:
            return d
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    raise ValueError("no cycle date found")


def previous_date(cfg, today=None):
    """The latest cycle data date on or before `today`."""
    today = today or _dt.date.today()
    y, m = today.year, today.month
    for _ in range(3):
        d = data_date(cfg, y, m)
        if d <= today:
            return d
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    raise ValueError("no cycle date found")


def warnings(store, d):
    """4.16: a data date on a project holiday stays put (it's a status
    date), but say so."""
    cal = schedule.Calendar(d, store.setting("holidays") or ())
    if d in cal.hol:
        return [f"The cycle date {d.isoformat()} is a project holiday; it "
                "stays the data date (a status date, not a workday)."]
    return []


def status(store, today=None):
    """The cycle panel: next / previous data date, when the reminder
    drafts are due, and warnings. Reads only."""
    cfg = model.config(store)["cycle"]
    today = today or _dt.date.today()
    nxt = next_date(cfg, today)
    prev = previous_date(cfg, today - _dt.timedelta(days=1)) \
        if nxt == today else previous_date(cfg, today)
    try:
        days = int(cfg.get("remind_days_before", 5))
    except (TypeError, ValueError):
        days = 5
    remind = nxt - _dt.timedelta(days=days)
    return {"next": nxt.isoformat(), "previous": prev.isoformat(),
            "remind_on": remind.isoformat(),
            "remind_due": remind <= today <= nxt,
            "warnings": warnings(store, nxt)}
