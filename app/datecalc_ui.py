"""Date and Time Calculators dialog (Estimate › Calculators and Project
menu; Jon, Oct 21). The math is in datecalc.py. Tabs: Between Dates,
Date & Time Duration, Add / Subtract, Weekday, Week Number. Results update
as you type; Copy Results puts the current tab's answer on the clipboard.

Workdays skip weekends, the open project's schedule holidays (when one is
open) and - ticked by default - the US federal holidays."""
import datetime as _dt

from PySide6.QtCore import QDate, Qt, QTime
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox,
                               QDateEdit, QDialog, QDialogButtonBox,
                               QFormLayout, QHBoxLayout, QLabel, QPushButton,
                               QSpinBox, QTabWidget, QTimeEdit, QVBoxLayout,
                               QWidget)

from . import datecalc as dc
from .dmoney import c2 as _c2


def _qd(d):
    return QDate(d.year, d.month, d.day)


def _pd(q):
    return _dt.date(q.year(), q.month(), q.day())


def _fmt(d):
    return f"{d:%A, %B} {d.day}, {d:%Y}"


def _fmt_dt(v):
    if isinstance(v, _dt.datetime):
        h = v.strftime("%I:%M %p").lstrip("0")
        return f"{_fmt(v.date())} at {h}"
    return _fmt(v)


def _plural(n, word):
    return f"{n:,} {word}{'' if abs(n) == 1 else 's'}"


def _date_edit(d=None):
    e = QDateEdit()
    e.setCalendarPopup(True)
    e.setDisplayFormat("ddd MM/dd/yyyy")
    e.setDate(_qd(d or _dt.date.today()))
    return e


def _num(top=100000, lo=0):
    s = QSpinBox()
    s.setRange(lo, top)
    return s


class _Tab(QWidget):
    def __init__(self, opts):
        super().__init__()
        self.opts = opts                      # the dialog: holidays, federal
        self.v = QVBoxLayout(self)
        self.form = QFormLayout()
        self.v.addLayout(self.form)
        self.out = QLabel()
        self.out.setObjectName("calcResult")
        self.out.setWordWrap(True)
        self.out.setTextFormat(Qt.RichText)
        self.v.addWidget(self.out)
        self.v.addStretch(1)
        self._text = ""

    def hol(self):
        return {"holidays": self.opts.holidays,
                "federal": self.opts.federal.isChecked()}

    def show_result(self, html, text):
        self.out.setText(html)
        self._text = text

    def text(self):
        return self._text

    def _today_btn(self, edit):
        b = QPushButton("Today")
        b.clicked.connect(lambda: edit.setDate(QDate.currentDate()))
        row = QHBoxLayout()
        row.addWidget(edit, 1)
        row.addWidget(b)
        return row


class BetweenTab(_Tab):
    """Duration Between Two Dates."""

    def __init__(self, opts):
        super().__init__(opts)
        self.a = _date_edit()
        self.b = _date_edit(_dt.date.today() + _dt.timedelta(days=30))
        self.inc = QCheckBox("Include the end date (Mon-Fri = 5 days)")
        self.form.addRow("Start date", self._today_btn(self.a))
        self.form.addRow("End date", self._today_btn(self.b))
        self.form.addRow("", self.inc)
        for w in (self.a, self.b):
            w.dateChanged.connect(self.update)
        self.inc.toggled.connect(self.update)
        self.update()

    def update(self, *_):
        a, b = _pd(self.a.date()), _pd(self.b.date())
        r = dc.between(a, b, self.inc.isChecked(), **self.hol())
        neg = " (the end is before the start)" if r["sign"] < 0 else ""
        parts = [_plural(r["years"], "year")] if r["years"] else []
        if r["months"]:
            parts.append(_plural(r["months"], "month"))
        parts.append(_plural(r["ymd_days"], "day"))
        hol = ""
        if r["holidays"]:
            hol = (f"<br><span style='color:gray'>Holidays skipped: "
                   + ", ".join(f"{d:%m/%d/%y}" for d in r["holidays"][:12])
                   + ("…" if len(r["holidays"]) > 12 else "") + "</span>")
        self.show_result(
            f"<b>{_plural(r['days'], 'calendar day')}</b>{neg}<br>"
            f"= {_plural(r['weeks'], 'week')} and "
            f"{_plural(r['weeks_days'], 'day')}<br>"
            f"= {', '.join(parts)}<br>"
            f"<b>{_plural(r['workdays'], 'workday')}</b> (Mon-Fri, less "
            f"holidays); {_plural(r['weekend_days'], 'weekend day')}"
            f"{hol}",
            f"{a:%m/%d/%Y} to {b:%m/%d/%Y}"
            f"{' (end date included)' if self.inc.isChecked() else ''}: "
            f"{r['days']} calendar days ({r['weeks']} weeks "
            f"{r['weeks_days']} days; {', '.join(parts)}); "
            f"{r['workdays']} workdays")
        return r


class DurationTab(_Tab):
    """Time and Date Duration - date and time both."""

    def __init__(self, opts):
        super().__init__(opts)
        self.a, self.b = _date_edit(), _date_edit()
        self.ta, self.tb = QTimeEdit(QTime(7, 0)), QTimeEdit(QTime(15, 30))
        for t in (self.ta, self.tb):
            t.setDisplayFormat("hh:mm AP")
        for label, d, t in (("Start", self.a, self.ta),
                            ("End", self.b, self.tb)):
            row = QHBoxLayout()
            row.addWidget(d, 1)
            row.addWidget(t)
            self.form.addRow(label, row)
            d.dateChanged.connect(self.update)
            t.timeChanged.connect(self.update)
        self.update()

    def _dt(self, d, t):
        q = t.time()
        return dc.to_datetime(_pd(d.date()), _dt.time(q.hour(), q.minute()))

    def update(self, *_):
        a, b = self._dt(self.a, self.ta), self._dt(self.b, self.tb)
        r = dc.duration(a, b)
        neg = " (the end is before the start)" if r["sign"] < 0 else ""
        self.show_result(
            f"<b>{_plural(r['days'], 'day')}, {_plural(r['hours'], 'hour')}"
            f", {_plural(r['minutes'], 'minute')}</b>{neg}<br>"
            f"= {_c2(r['total_hours']):,.2f} hours<br>"
            f"= {_plural(r['total_minutes'], 'minute')}",
            f"{_fmt_dt(a)} to {_fmt_dt(b)}: {r['days']} days "
            f"{r['hours']} h {r['minutes']} min ({_c2(r['total_hours']):.2f} h)")
        return r


class AddTab(_Tab):
    """Add to or subtract from a date (timeanddate.com's dateadd)."""

    def __init__(self, opts):
        super().__init__(opts)
        self.start = _date_edit()
        self.form.addRow("Start date", self._today_btn(self.start))
        self.op = QComboBox()
        self.op.addItems(["Add (+)", "Subtract (-)"])
        self.form.addRow("", self.op)
        self.years, self.months = _num(500), _num(6000)
        self.weeks, self.days = _num(30000), _num(200000)
        self.work = _num(100000)
        self.hours, self.minutes = _num(100000), _num(100000)
        for label, w in (("Years", self.years), ("Months", self.months),
                         ("Weeks", self.weeks), ("Days", self.days),
                         ("Workdays (skip weekends + holidays)", self.work),
                         ("Hours", self.hours), ("Minutes", self.minutes)):
            self.form.addRow(label, w)
            w.valueChanged.connect(self.update)
        self.start.dateChanged.connect(self.update)
        self.op.currentIndexChanged.connect(self.update)
        self.update()

    def update(self, *_):
        s = _pd(self.start.date())
        sub = self.op.currentIndex() == 1
        try:
            r = dc.add(s, self.years.value(), self.months.value(),
                       self.weeks.value(), self.days.value(),
                       self.work.value(), self.hours.value(),
                       self.minutes.value(), subtract=sub, **self.hol())
        except ValueError:                   # before year 1 / after 9999
            self.show_result("Date out of range: dates run from year 1 "
                             "to 9999.", "")
            return None
        bits = [_plural(w.value(), n) for w, n in (
            (self.years, "year"), (self.months, "month"),
            (self.weeks, "week"), (self.days, "day"),
            (self.work, "workday"), (self.hours, "hour"),
            (self.minutes, "minute")) if w.value()]
        what = (" - " if sub else " + ") + ", ".join(bits) if bits else ""
        d = r.date() if isinstance(r, _dt.datetime) else r
        span = dc.between(s, d)["days"]
        self.show_result(
            f"<b>{_fmt_dt(r)}</b><br>{s:%m/%d/%Y}{what}<br>"
            f"<span style='color:gray'>{_plural(span, 'calendar day')} "
            f"from the start; ISO week {d.isocalendar()[1]}</span>",
            f"{s:%m/%d/%Y}{what} = {_fmt_dt(r)}")
        return r


class WeekdayTab(_Tab):
    """What day is this date?"""

    def __init__(self, opts):
        super().__init__(opts)
        self.d = _date_edit()
        self.form.addRow("Date", self._today_btn(self.d))
        self.d.dateChanged.connect(self.update)
        self.update()

    def update(self, *_):
        r = dc.weekday_info(_pd(self.d.date()), **self.hol())
        d = r["date"]
        hol = f"<br>US federal holiday: <b>{r['holiday']}</b>" \
            if r["holiday"] else ""
        self.show_result(
            f"<b>{_fmt(d)}</b> is a <b>{r['weekday']}</b><br>"
            f"the {r['nth']}<br>day {r['day_of_year']} of {d.year} "
            f"({_plural(r['days_left'], 'day')} left); ISO week "
            f"{r['iso_week']}<br>"
            f"{'A workday' if r['workday'] else 'Not a workday'}{hol}",
            f"{d:%m/%d/%Y} is a {r['weekday']} ({r['nth']}; day "
            f"{r['day_of_year']}; week {r['iso_week']})")
        return r


class WeekTab(_Tab):
    """Week Number Calculator - both ways."""

    def __init__(self, opts):
        super().__init__(opts)
        self.d = _date_edit()
        self.form.addRow("Date", self._today_btn(self.d))
        self.d.dateChanged.connect(self.update)
        row = QHBoxLayout()
        self.wy = _num(2200, 1900)
        self.wy.setValue(_dt.date.today().year)
        self.wn = _num(53, 1)
        self.wn.setValue(_dt.date.today().isocalendar()[1])
        go = QPushButton("Show Dates")
        go.clicked.connect(self.from_week)
        for w in (QLabel("Year"), self.wy, QLabel("Week"), self.wn, go):
            row.addWidget(w)
        row.addStretch(1)
        self.form.addRow("or week", row)
        self.update()

    def from_week(self):
        try:
            mon, _ = dc.iso_week_dates(self.wy.value(), self.wn.value())
        except ValueError:
            self.show_result(f"{self.wy.value()} has no week "
                             f"{self.wn.value()}.", "")
            return None
        self.d.setDate(_qd(mon))
        return mon

    def update(self, *_):
        r = dc.week_info(_pd(self.d.date()))
        d = r["date"]
        self.show_result(
            f"<b>Week {r['iso_week']}</b> of {r['iso_year']} (ISO 8601, "
            f"weeks start Monday): {r['iso_start']:%a %m/%d} - "
            f"{r['iso_end']:%a %m/%d/%Y}; {r['iso_year']} has "
            f"{r['weeks_in_year']} weeks<br>"
            f"US week {r['us_week']} (weeks start Sunday, week 1 holds "
            f"Jan 1): {r['us_start']:%a %m/%d} - {r['us_end']:%a %m/%d/%Y}",
            f"{d:%m/%d/%Y}: ISO week {r['iso_week']} of {r['iso_year']} "
            f"({r['iso_start']:%m/%d} - {r['iso_end']:%m/%d/%Y}); US week "
            f"{r['us_week']}")
        return r


class DateCalcDialog(QDialog):
    TABS = (("Between Dates", BetweenTab),
            ("Date && Time Duration", DurationTab),
            ("Add / Subtract", AddTab), ("Weekday", WeekdayTab),
            ("Week Number", WeekTab))

    def __init__(self, parent=None, holidays=(), tab=0):
        super().__init__(parent)
        self.setWindowTitle("Date and Time Calculators")
        self.resize(560, 520)
        self.holidays = list(holidays or ())
        v = QVBoxLayout(self)
        self.federal = QCheckBox("Workdays skip US federal holidays")
        self.federal.setChecked(True)
        note = (f" and the project's {len(self.holidays)} schedule "
                "holiday(s)" if self.holidays else "")
        self.federal.setToolTip("Weekends are never workdays" + note + ".")
        self.tabs = QTabWidget()
        self.pages = []
        for name, cls in self.TABS:
            p = cls(self)
            self.pages.append(p)
            self.tabs.addTab(p, name)
        self.tabs.setCurrentIndex(tab)
        self.federal.toggled.connect(self.refresh)
        v.addWidget(self.tabs, 1)
        v.addWidget(self.federal)
        if self.holidays:
            v.addWidget(QLabel(f"Also skips this project's "
                               f"{len(self.holidays)} schedule holiday(s)."))
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        copy = bb.addButton("Copy Results", QDialogButtonBox.ActionRole)
        copy.clicked.connect(self.copy)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def refresh(self, *_):
        for p in self.pages:
            p.update()

    def copy(self):
        t = self.tabs.currentWidget().text()
        QApplication.clipboard().setText(t)
        return t
