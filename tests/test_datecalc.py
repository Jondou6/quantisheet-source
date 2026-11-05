"""Date and Time Calculators (Jon, Oct 21): between dates, date + time
duration, add / subtract (days and workdays), weekday, week number."""
import datetime as dt
import os

import pytest

from app import datecalc as dc

D = dt.date


def test_between_dates_calendar_weeks_ymd_workdays():
    r = dc.between("2026-10-01", "2026-12-25")
    assert r["days"] == 85 and (r["weeks"], r["weeks_days"]) == (12, 1)
    assert (r["years"], r["months"], r["ymd_days"]) == (0, 2, 24)
    # Thanksgiving 11/26 is skipped with federal holidays on
    plain = dc.between("2026-11-23", "2026-11-28")["workdays"]
    fed = dc.between("2026-11-23", "2026-11-28", federal=True)
    assert plain == 5 and fed["workdays"] == 4
    assert fed["holidays"] == [D(2026, 11, 26)]


def test_include_end_date_and_reversed():
    assert dc.between("10/19/2026", "10/23/2026")["days"] == 4
    r = dc.between("10/19/2026", "10/23/2026", include_end=True)
    assert r["days"] == 5 and r["workdays"] == 5
    back = dc.between("2026-10-23", "2026-10-19")
    assert back["days"] == -4 and back["sign"] == -1
    assert dc.between("2024-01-01", "2025-01-01")["years"] == 1


def test_project_holidays_are_skipped():
    r = dc.between("2026-07-01", "2026-07-08", holidays=["7/3/2026"])
    assert r["workdays"] == 4                     # 7/1, 7/2, 7/6, 7/7


def test_time_and_date_duration():
    r = dc.duration(dt.datetime(2026, 10, 21, 7, 0),
                    dt.datetime(2026, 10, 22, 15, 30))
    assert (r["days"], r["hours"], r["minutes"]) == (1, 8, 30)
    assert r["total_hours"] == pytest.approx(32.5)
    assert dc.duration(dt.datetime(2026, 1, 2), dt.datetime(2026, 1, 1)
                       )["sign"] == -1


def test_add_and_subtract():
    assert dc.add("2026-01-31", months=1) == D(2026, 2, 28)
    assert dc.add("2024-02-29", years=1) == D(2025, 2, 28)
    assert dc.add("2026-10-21", weeks=2, days=3) == D(2026, 11, 7)
    assert dc.add("2026-10-21", days=10, subtract=True) == D(2026, 10, 11)
    # 10 workdays from Fri 11/20 with Thanksgiving off
    assert dc.add("2026-11-20", workdays=10, federal=True) == D(2026, 12, 7)
    assert dc.add("2026-11-20", workdays=10) == D(2026, 12, 4)
    assert dc.add("2026-10-26", workdays=1, subtract=True) == D(2026, 10, 23)
    t = dc.add("2026-10-21", hours=30, time=dt.time(8, 0))
    assert t == dt.datetime(2026, 10, 22, 14, 0)


def test_add_out_of_range_and_negative_workdays():
    """Review of tonight's changes #9: the dialog's maxima subtracted are
    a clear ValueError, not OverflowError; negative workdays go back."""
    for kw in (dict(years=500, months=6000, weeks=30000, days=200000,
                    subtract=True),
               dict(years=9000),
               dict(hours=10 ** 9)):
        with pytest.raises(ValueError) as e:
            dc.add("2026-10-21", **kw)
        assert "date out of range" in str(e.value), kw
    with pytest.raises(ValueError):
        dc.add("0001-01-03", workdays=3, subtract=True)
    # Mon 10/26 - 3 workdays = Wed 10/21, either way of asking
    assert dc.add("2026-10-26", workdays=-3) == D(2026, 10, 21)
    assert dc.add("2026-10-26", workdays=3, subtract=True) == D(2026, 10, 21)
    assert dc.add("2026-10-21", workdays=-3, subtract=True) == D(2026, 10, 26)
    assert dc.add("2026-10-21", workdays=0) == D(2026, 10, 21)
    with pytest.raises(ValueError) as e:                 # bad input as before
        dc.add("not a date", days=1)
    assert "not a date" in str(e.value)


def test_federal_holidays_observed():
    h = dc.us_federal_holidays(2026)
    assert h[D(2026, 7, 3)] == "Independence Day"      # 7/4 is a Saturday
    assert h[D(2026, 11, 26)] == "Thanksgiving Day"
    assert h[D(2026, 5, 25)] == "Memorial Day"
    assert len(h) == 11
    assert D(2027, 12, 31) in dc.us_federal_holidays(2027)  # 1/1/28 Sat


def test_weekday_and_week_number():
    w = dc.weekday_info("2026-10-21")
    assert w["weekday"] == "Wednesday" and w["day_of_year"] == 294
    assert w["nth"].startswith("3rd Wednesday of October")
    assert w["workday"]
    assert dc.weekday_info("2026-12-25")["holiday"] == "Christmas Day"
    k = dc.week_info("2026-10-21")
    assert (k["iso_year"], k["iso_week"]) == (2026, 43)
    assert k["iso_start"] == D(2026, 10, 19) and k["iso_end"] == D(2026,
                                                                   10, 25)
    assert k["us_week"] == 43 and k["us_start"] == D(2026, 10, 18)
    assert dc.week_info("2027-01-01")["iso_week"] == 53       # of 2026
    assert dc.iso_week_dates(2026, 1) == (D(2025, 12, 29), D(2026, 1, 4))


def test_dialog(qtbot=None):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QDate
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app.datecalc_ui import DateCalcDialog
    d = DateCalcDialog(None, holidays=["2026-10-23"])
    assert d.tabs.count() == 5
    names = [d.tabs.tabText(i) for i in range(5)]
    assert "Week Number" in names and not any("Birthday" in n
                                              for n in names)
    b = d.pages[0]
    b.a.setDate(QDate(2026, 10, 19))
    b.b.setDate(QDate(2026, 10, 26))
    r = b.update()
    assert r["days"] == 7 and r["workdays"] == 4      # 10/23 is a holiday
    d.tabs.setCurrentIndex(0)
    assert "7 calendar days" in d.copy()
    a = d.pages[2]
    a.start.setDate(QDate(2026, 10, 21))
    a.days.setValue(10)
    assert a.update() == D(2026, 10, 31)
    a.op.setCurrentIndex(1)
    assert a.update() == D(2026, 10, 11)
    for w in (a.years, a.months, a.weeks, a.days):      # all at maximum
        w.setValue(w.maximum())
    assert a.update() is None
    assert "out of range" in a.out.text()
    for w in (a.years, a.months, a.weeks, a.days):
        w.setValue(0)
    wk = d.pages[4]
    wk.wy.setValue(2026)
    wk.wn.setValue(43)
    assert wk.from_week() == D(2026, 10, 19)
    assert "Week 43" in wk.out.text()
    wd = d.pages[3]
    wd.d.setDate(QDate(2026, 10, 21))
    assert "Wednesday" in wd.out.text()
    d.federal.setChecked(False)
    d.close()


def test_menu_entry():
    import ast
    src = open(os.path.join(os.path.dirname(__file__), "..", "app",
                            "main_window.py"), encoding="utf-8").read()
    assert "Date and Time Calculators…" in src
    assert '("Date and Time Calculators",' in src
    ast.parse(src)
