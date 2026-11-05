"""Date and time calculators (Jon, Oct 21): plain math, no Qt
(datecalc_ui.py is the dialog).

  * between(a, b)       - days between two dates (calendar days, weeks,
                          years / months / days, and workdays)
  * duration(a, b)      - between two date-times (days, hours, minutes)
  * add(d, ...)         - add or subtract years, months, weeks, days - or
                          workdays - and hours / minutes (like
                          timeanddate.com's Date Calculator)
  * weekday_info(d)     - what day is this date
  * week_info(d)        - ISO week number (and the US Sunday-start week)

Workdays are Monday to Friday, less the holidays given: a list of dates
(the project's schedule holidays) and, optionally, the US federal
holidays (observed dates - Saturday moves to Friday, Sunday to Monday).
"""
import calendar as _cal
import datetime as _dt

DAY = _dt.timedelta(days=1)
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
            "Saturday", "Sunday")


# ---------------------------------------------------------------- parsing
def to_date(v):
    """A date from a date, a datetime, 2026-10-21, 10/21/2026 or 10/21/26."""
    if isinstance(v, _dt.datetime):
        return v.date()
    if isinstance(v, _dt.date):
        return v
    t = str(v or "").strip()
    try:
        return _dt.date.fromisoformat(t[:10])
    except ValueError:
        pass
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y"):
        try:
            return _dt.datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"not a date: {t!r}")


def _nth_weekday(year, month, weekday, n):
    """The n-th weekday (0 = Monday) of the month; n = -1 is the last."""
    if n > 0:
        d = _dt.date(year, month, 1)
        d += _dt.timedelta(days=(weekday - d.weekday()) % 7)
        return d + _dt.timedelta(weeks=n - 1)
    d = _dt.date(year, month, _cal.monthrange(year, month)[1])
    return d - _dt.timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d):
    if d.weekday() == 5:
        return d - DAY
    if d.weekday() == 6:
        return d + DAY
    return d


def us_federal_holidays(year):
    """{date: name} - the observed dates of the 11 US federal holidays."""
    fixed = {(1, 1): "New Year's Day", (6, 19): "Juneteenth",
             (7, 4): "Independence Day", (11, 11): "Veterans Day",
             (12, 25): "Christmas Day"}
    out = {_observed(_dt.date(year, m, d)): n for (m, d), n in fixed.items()}
    out[_nth_weekday(year, 1, 0, 3)] = "Martin Luther King Jr. Day"
    out[_nth_weekday(year, 2, 0, 3)] = "Washington's Birthday"
    out[_nth_weekday(year, 5, 0, -1)] = "Memorial Day"
    out[_nth_weekday(year, 9, 0, 1)] = "Labor Day"
    out[_nth_weekday(year, 10, 0, 2)] = "Columbus Day"
    out[_nth_weekday(year, 11, 3, 4)] = "Thanksgiving Day"
    # New Year's Day on a Saturday is observed the Friday before (Dec 31)
    nxt = _dt.date(year + 1, 1, 1)
    if nxt.weekday() == 5:
        out[nxt - DAY] = "New Year's Day (observed)"
    return out


class Workdays:
    """Mon-Fri less the given holidays (and the federal ones if asked)."""

    def __init__(self, holidays=(), federal=False):
        self.hol = set()
        for h in holidays or ():
            try:
                self.hol.add(to_date(h))
            except ValueError:
                continue
        self.federal = bool(federal)
        self._fed = {}

    def _fed_year(self, y):
        if y not in self._fed:
            self._fed[y] = set(us_federal_holidays(y))
        return self._fed[y]

    def is_work(self, d):
        if d.weekday() >= 5 or d in self.hol:
            return False
        return not (self.federal and d in self._fed_year(d.year))

    def holidays_between(self, a, b):
        """Weekday holidays in [a, b] that were skipped."""
        out, d = [], a
        while d <= b:
            if d.weekday() < 5 and not self.is_work(d):
                out.append(d)
            d += DAY
        return out


# ---------------------------------------------------------------- results
def ymd(a, b):
    """(years, months, days) from a to b (a <= b), counting whole months
    the way people do: Jan 31 + 1 month is Feb 28/29."""
    y, m = b.year - a.year, b.month - a.month
    if b.day < a.day:
        m -= 1
    if m < 0:
        y, m = y - 1, m + 12
    mid = add_months(a, y * 12 + m)
    return y, m, (b - mid).days


def add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    y += d.year
    m += 1
    return d.replace(year=y, month=m,
                     day=min(d.day, _cal.monthrange(y, m)[1]))


def between(a, b, include_end=False, holidays=(), federal=False):
    """Days from a to b. include_end counts the end date too (a job from
    Monday to Friday inclusive is 5 days). Negative when b is before a."""
    a, b = to_date(a), to_date(b)
    sign = 1
    if b < a:
        a, b, sign = b, a, -1
    end = b + DAY if include_end else b
    days = (end - a).days
    wd = Workdays(holidays, federal)
    work, d = 0, a
    while d < end:
        work += wd.is_work(d)
        d += DAY
    y, m, dd = ymd(a, end)
    skipped = wd.holidays_between(a, end - DAY) if days else []
    return {"days": sign * days, "weeks": days // 7,
            "weeks_days": days % 7, "years": y, "months": m,
            "ymd_days": dd, "workdays": sign * work,
            "weekend_days": sum(1 for i in range(days)
                                if (a + i * DAY).weekday() >= 5),
            "holidays": skipped, "hours": days * 24,
            "start": a, "end": b, "sign": sign}


def to_datetime(v, t=None):
    if isinstance(v, _dt.datetime):
        return v
    d = to_date(v)
    if t is None:
        return _dt.datetime(d.year, d.month, d.day)
    if isinstance(t, str):
        t = _dt.time.fromisoformat(t.strip())
    return _dt.datetime.combine(d, t)


def duration(a, b):
    """Between two date-times: total and broken down."""
    a, b = to_datetime(a), to_datetime(b)
    sign = 1
    if b < a:
        a, b, sign = b, a, -1
    s = int((b - a).total_seconds())
    days, rem = divmod(s, 86400)
    h, rem = divmod(rem, 3600)
    mi, sec = divmod(rem, 60)
    return {"sign": sign, "days": days, "hours": h, "minutes": mi,
            "seconds": sec, "total_hours": sign * s / 3600,
            "total_minutes": sign * s // 60, "total_seconds": sign * s}


def add(start, years=0, months=0, weeks=0, days=0, workdays=0,
        hours=0, minutes=0, subtract=False, holidays=(), federal=False,
        time=None):
    """start +/- the amounts. Years and months first (clamped to the
    month's end), then weeks and days, then workdays (stepping over
    weekends and holidays), then hours and minutes. Returns a datetime
    when a time or hours / minutes are involved, else a date. Negative
    amounts go the other way. Raises ValueError('date out of range') when
    the result would be before year 1 or after year 9999."""
    sg = -1 if subtract else 1
    d = to_date(start)
    try:
        d = add_months(d, sg * (int(years) * 12 + int(months)))
        d += sg * _dt.timedelta(weeks=int(weeks), days=int(days))
        n = int(workdays)
        if n:
            # a negative count steps the other way (add(workdays=-3) is
            # three workdays back, like subtract=True with 3)
            wd = Workdays(holidays, federal)
            step = (sg if n > 0 else -sg) * DAY
            n = abs(n)
            while n > 0:
                d += step
                if wd.is_work(d):
                    n -= 1
        if time is None and not hours and not minutes:
            return d
        dt = to_datetime(d, time or _dt.time(0, 0))
        return dt + sg * _dt.timedelta(hours=float(hours),
                                       minutes=float(minutes))
    except (OverflowError, ValueError) as e:
        # before year 1 or after 9999 (Python's date range)
        raise ValueError("date out of range") from e


def nth_of_month(d):
    """'3rd Wednesday of October' (and 'last' when it is)."""
    n = (d.day - 1) // 7 + 1
    suf = {1: "1st", 2: "2nd", 3: "3rd"}.get(n, f"{n}th")
    last = d + _dt.timedelta(weeks=1)
    tail = " (the last)" if last.month != d.month else ""
    return f"{suf} {WEEKDAYS[d.weekday()]} of {d:%B}{tail}"


def weekday_info(d, holidays=(), federal=True):
    d = to_date(d)
    y_len = 366 if _cal.isleap(d.year) else 365
    doy = d.timetuple().tm_yday
    fed = us_federal_holidays(d.year).get(d)
    return {"date": d, "weekday": WEEKDAYS[d.weekday()],
            "day_of_year": doy, "days_left": y_len - doy,
            "nth": nth_of_month(d), "iso_week": d.isocalendar()[1],
            "holiday": fed,
            "workday": Workdays(holidays, federal).is_work(d)}


def us_week(d):
    """US week number: weeks start Sunday, week 1 holds January 1."""
    jan1 = _dt.date(d.year, 1, 1)
    first_sun = jan1 - _dt.timedelta(days=(jan1.weekday() + 1) % 7)
    return (d - first_sun).days // 7 + 1


def week_info(d):
    d = to_date(d)
    iy, iw, _ = d.isocalendar()
    mon = d - _dt.timedelta(days=d.weekday())
    sun0 = d - _dt.timedelta(days=(d.weekday() + 1) % 7)
    return {"date": d, "iso_year": iy, "iso_week": iw,
            "iso_start": mon, "iso_end": mon + 6 * DAY,
            "us_week": us_week(d), "us_start": sun0, "us_end": sun0 + 6 * DAY,
            "weeks_in_year": _dt.date(iy, 12, 28).isocalendar()[1]}


def iso_week_dates(year, week):
    """(Monday, Sunday) of ISO week `week` of `year`."""
    mon = _dt.date.fromisocalendar(int(year), int(week), 1)
    return mon, mon + 6 * DAY
