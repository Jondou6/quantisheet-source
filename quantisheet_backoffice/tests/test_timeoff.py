"""Time Off page logic (timeoff.py): company holidays, working-day counts,
request preview, cancel, the requests table, stats and the calendar's
dates, events and lanes. Made-up data only."""
from datetime import date

import pytest

from quantisheet_backoffice import hr, pto, timeoff, timeentry
from quantisheet_backoffice.security import Denied

from .m3_helpers import add_hr, approve_time


@pytest.fixture
def hro(office):
    add_hr(office)
    office.act_as("hr@bo.test")
    return office


def _emp(o, name="R. Diaz", no="E401", hours="40"):
    eid = hr.add_employee(o, name, no, "2025-01-06", labor_class="LAB")
    pol = pto.add_policy(o, f"PTO {no}", per_hours="30", cap="80")
    pto.assign(o, eid, pol)
    pto.adjust(o, eid, "2026-10-01", hours, "opening balance")
    return eid


def test_holidays_are_not_working_days(hro):
    timeoff.add_holiday(hro, "2026-11-26", "Thanksgiving")
    timeoff.add_holiday(hro, "2026-11-27", "Day after Thanksgiving")
    with pytest.raises(timeoff.TimeOffError, match="already"):
        timeoff.add_holiday(hro, "2026-11-26", "Again")
    days = timeoff.workdays(hro, "2026-11-23", "2026-11-29")
    assert [d.isoformat() for d in days] == ["2026-11-23", "2026-11-24",
                                            "2026-11-25"]
    assert [h["name"] for h in timeoff.holidays(hro)] == [
        "Thanksgiving", "Day after Thanksgiving"]


def test_viewer_cannot_add_holidays(hro):
    hro.act_as("viewer@bo.test")
    with pytest.raises(Denied):
        timeoff.add_holiday(hro, "2026-12-25", "Christmas")


def test_request_skips_holidays_and_charges_only_workdays(hro):
    eid = _emp(hro, hours="40")
    timeoff.add_holiday(hro, "2026-11-26", "Thanksgiving")
    p = timeoff.preview(hro, eid, "2026-11-23", "2026-11-27", "8")
    assert (p["days"], p["hours"], p["available"], p["after"], p["ok"]) == \
        (4, 3200, 4000, 800, True)
    rid = pto.request(hro, eid, "2026-11-23", "2026-11-27", "8")
    assert hro.db.get("pto_requests", rid)["total"] == 3200
    ids = pto.decide(hro, rid, "approve")
    dates = [hro.db.get("time_lines", i)["date"] for i in ids]
    assert "2026-11-26" not in dates and len(dates) == 4


def test_preview_explains_what_is_wrong(hro):
    eid = _emp(hro, hours="16")
    assert timeoff.preview(hro, eid, "2026-11-28", "2026-11-29")["why"] \
        .startswith("No working days")
    assert "before the first" in timeoff.preview(
        hro, eid, "2026-11-10", "2026-11-09")["why"]
    p = timeoff.preview(hro, eid, "2026-11-09", "2026-11-11", "8")
    assert not p["ok"] and "Not enough balance" in p["why"]


def test_cancel_only_pending(hro):
    eid = _emp(hro)
    rid = pto.request(hro, eid, "2026-11-09", "2026-11-09", "8")
    timeoff.cancel(hro, rid)
    assert hro.db.get("pto_requests", rid)["status"] == "Cancelled"
    with pytest.raises(timeoff.TimeOffError, match="Cancelled"):
        timeoff.cancel(hro, rid)
    # a cancelled request no longer holds balance
    assert timeoff.preview(hro, eid, "2026-11-16", "2026-11-20",
                           "8")["available"] == 4000


def test_request_rows_search_filter_sort(hro):
    a = _emp(hro, "R. Diaz", "E401")
    b = _emp(hro, "M. Chen", "E402")
    r1 = pto.request(hro, a, "2026-11-16", "2026-11-17", "8",
                     note="family visit")
    r2 = pto.request(hro, b, "2026-11-09", "2026-11-09", "8")
    pto.decide(hro, r2, "approve")
    rows = timeoff.request_rows(hro)
    assert [r["id"] for r in rows] == [r2, r1]
    assert [r["id"] for r in timeoff.request_rows(hro, status="Pending")] \
        == [r1]
    assert [r["id"] for r in timeoff.request_rows(hro, search="family")] \
        == [r1]
    assert [r["name"] for r in timeoff.request_rows(hro, sort="name")] == \
        ["M. Chen", "R. Diaz"]
    assert rows[1]["days"] == 2


def test_stats_one_employee_and_team(hro):
    eid = _emp(hro, hours="40")
    rid = pto.request(hro, eid, "2026-11-09", "2026-11-10", "8")
    pto.decide(hro, rid, "approve")
    pto.request(hro, eid, "2026-11-16", "2026-11-16", "8")
    s = timeoff.stats(hro, eid, today="2026-10-27")
    assert (s["available"], s["pending"], s["upcoming"]) == \
        (4000 - 800, 800, 1600)
    t = timeoff.stats(hro, today="2026-11-09")
    assert (t["pending"], t["off_today"], t["days_ahead"]) == (1, 1, 1)


def test_month_grid_and_weeks():
    g = timeoff.month_grid(2026, 11)
    assert g[0][0] == date(2026, 10, 26) and len(g) == 6
    assert all(len(w) == 7 for w in g)
    assert date(2026, 11, 30) in g[-1]
    assert timeoff.month_grid(2026, 2)[0][0] == date(2026, 1, 26)
    assert timeoff.week_days("2026-11-10")[0] == date(2026, 11, 9)
    assert timeoff.week_days("2026-11-10", starts_on=6)[0] == \
        date(2026, 11, 8)
    assert timeoff.add_months("2026-01-31", 1) == date(2026, 2, 28)


def test_events_and_lanes(hro):
    a = _emp(hro, "R. Diaz", "E401")
    b = _emp(hro, "M. Chen", "E402")
    timeoff.add_holiday(hro, "2026-11-11", "Veterans Day")
    r1 = pto.request(hro, a, "2026-11-09", "2026-11-13", "8")
    pto.decide(hro, r1, "approve")
    pto.request(hro, b, "2026-11-10", "2026-11-12", "8")
    ev = timeoff.events(hro, "2026-11-09", "2026-11-15")
    assert [(e["kind"], e["start"], e["end"]) for e in ev] == [
        ("timeoff", "2026-11-09", "2026-11-13"),
        ("pending", "2026-11-10", "2026-11-12"),
        ("holiday", "2026-11-11", "2026-11-11")]
    lanes = timeoff.lanes(ev, timeoff.week_days("2026-11-09"))
    got = {(it["kind"], ln, c0, c1) for it, ln, c0, c1 in lanes}
    assert got == {("timeoff", 0, 0, 4), ("pending", 1, 1, 3),
                   ("holiday", 2, 2, 2)}
    only_a = timeoff.events(hro, "2026-11-09", "2026-11-15", employee_id=a)
    assert {e["kind"] for e in only_a} == {"holiday", "timeoff"}


def test_day_hours_splits_work_and_pto(hro, job):
    eid = _emp(hro)
    wid = hr.employee(hro, eid)["worker_id"]
    hro.act_as("admin@bo.test")
    ids = [timeentry.add_line(hro, wid, "2026-11-02", job, "03-3000", "8"),
           timeentry.add_line(hro, wid, "2026-11-03", job, "03-3000", "6")]
    approve_time(hro, ids)
    hro.act_as("hr@bo.test")
    rid = pto.request(hro, eid, "2026-11-04", "2026-11-04", "8")
    pto.decide(hro, rid, "approve")
    h = timeoff.day_hours(hro, "2026-11-02", "2026-11-08", eid)
    assert h == {"2026-11-02": {"work": 800, "pto": 0},
                 "2026-11-03": {"work": 600, "pto": 0},
                 "2026-11-04": {"work": 0, "pto": 800}}


def test_year_end_carry_over_and_the_report(hro, tmp_path):
    """What carries into next year at the policy's limit, and the
    printable report listing it with the year's requests and holidays."""
    eid = hr.add_employee(hro, "M. Example", "E402", "2025-01-06",
                          labor_class="LAB")
    pol = pto.add_policy(hro, "PTO carry", per_hours="30", cap="80",
                         carryover="24")
    pto.assign(hro, eid, pol)
    pto.adjust(hro, eid, "2026-10-01", "40", "opening balance")
    other = _emp(hro, "N. Example", "E403", hours="10")   # no limit
    rows = {r["name"]: r for r in timeoff.year_end(hro, 2026)}
    m = rows["M. Example"]
    assert (m["balance"], m["limit"], m["carried"], m["lost"]) == \
        (4000, 2400, 2400, 1600)
    assert rows["N. Example"]["lost"] == 0
    assert pto.balance(hro, eid, "2027-01-15")["balance"] == 2400
    timeoff.add_holiday(hro, "2026-12-25", "Christmas")
    rid = pto.request(hro, other, "2026-12-01", "2026-12-01", "8")
    out = timeoff.report_pdf(hro, 2026, path=str(tmp_path / "r.pdf"),
                             today="2026-10-28")
    import fitz
    with fitz.open(out) as d:
        text = "".join(p.get_text() for p in d)
    assert "M. Example" in text and "Christmas" in text
    assert "Requests 2026 (1)" in text and "16.00" in text
    assert hro.db.get("pto_requests", rid)["status"] == "Pending"
