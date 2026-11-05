"""P2-01 payroll calculation (1.1-1.3) and P2-02 payroll provider export and
register import (2.1-2.2). Back Office calculates gross pay only; it never
withholds, files or moves money (decision 8 = A)."""
import csv
import io

import pytest

from quantisheet_backoffice import cents, jobcost, payroll, provider, timeentry

from .m3_helpers import WEEK, add_hr, approve_time, second_job

D = "2026-10-25"          # period end (pay week Mon 10-19 .. Sun 10-25)


@pytest.fixture
def hr(office):
    add_hr(office)
    office.act_as("admin@bo.test")
    timeentry.add_labor_class(office, "CARP", "Carpenter", "38.00", "0")
    office.act_as("hr@bo.test")
    return office


def _chen(office, classification="Carpenter"):
    wid = timeentry.add_worker(office, "M. Chen", "CARP", employee_no="E101")
    payroll.pay_setup(office, wid, pay_rate="38.00",
                      classification=classification)
    return wid


def _period(office, start="2026-10-19", end=D, rule=None):
    return payroll.add_period(office, start, end, "2026-10-30",
                              ot_rule_id=rule)


def test_1_1_weekly_overtime_gross(hr, job):
    wid = _chen(hr)
    ids = [timeentry.add_line(hr, wid, d, job, "03-3000", h)
           for d, h in zip(WEEK, ["9", "10", "9", "9.5", "8.5"])]
    approve_time(hr, ids)
    pid = _period(hr)
    p = payroll.preview(hr, pid)
    (w,) = p["workers"]
    assert w["name"] == "M. Chen"
    assert {k: cents.hours_text(v) for k, v in w["hours"].items() if v} == \
        {"REG": "40.00", "OT": "6.00"}
    by_type = {}
    for ln in w["lines"]:
        by_type[ln["pay_type"]] = by_type.get(ln["pay_type"], 0) + ln["gross"]
    assert by_type == {"REG": 152_000, "OT": 34_200}
    assert cents.fmt(w["gross"]) == "$1,862.00"
    assert "Weekly over 40" in w["rule"]
    # estimated until final; then job cost uses payroll gross (+ burden 0 %)
    assert jobcost.by_code(hr, job)["03-3000"]["labor_estimated"] is True
    hr.act_as("hr@bo.test")
    payroll.finalize(hr, pid)
    r = jobcost.by_code(hr, job)["03-3000"]
    assert r["labor"] == 186_200 and r["labor_estimated"] is False
    with pytest.raises(timeentry.TimeError, match="final"):
        timeentry.edit_line(hr, ids[0], hours="8")


def _split_week(office, job, wid):
    """30 h on job 2702, then 16 h on prevailing-wage job 2611 (Thu 7.5 +
    Fri 8.5): the last 6 hours of the week are on 2611."""
    other = second_job(office)
    plan = [(WEEK[0], other, "9"), (WEEK[1], other, "10"),
            (WEEK[2], other, "9"), (WEEK[3], other, "2"),
            (WEEK[3], job, "7.5"), (WEEK[4], job, "8.5")]
    ids = [timeentry.add_line(office, wid, d, j, "03-3000", h)
           for d, j, h in plan]
    approve_time(office, ids)
    return other


def _determination(office, job, base="52.40", start="2026-01-01", end=None):
    return payroll.add_rate(office, "prevailing", base, start,
                            effective_to=end, job_id=job,
                            determination_no="WD OR20260001",
                            classification="Carpenter",
                            fringes=[{"name": "Health & pension",
                                      "amount": "21.10", "to": "plan"}])


@pytest.mark.parametrize("basis,gross,premium_text", [
    ("rate_in_effect", 213_560, "1.5 x the rate of the hours worked"),
    ("weighted_average", 210_743, "weighted-average regular rate")])
def test_1_2_prevailing_wage_hours_and_ot_rule(hr, job, basis, gross,
                                               premium_text):
    wid = _chen(hr)
    _split_week(hr, job, wid)
    _determination(hr, job)
    rule = payroll.add_ot_rule(hr, f"Federal weekly ({basis})",
                               weekly_over="40", rate_basis=basis)
    (w,) = payroll.preview(hr, _period(hr, rule=rule))["workers"]
    pw = [ln for ln in w["lines"] if ln["job_id"] == job]
    assert cents.hours_text(sum(ln["hours"] for ln in pw)) == "16.00"
    assert all(ln["base"] == 5_240 and "WD OR20260001" in ln["rate_source"]
               and ln["prevailing"] for ln in pw)
    assert {ln["pay_type"]: cents.hours_text(ln["hours"]) for ln in pw
            if ln["date"] == WEEK[4]} == {"REG": "2.50", "OT": "6.00"}
    assert all(ln["base"] == 3_800 for ln in w["lines"] if ln["job_id"] != job)
    assert w["gross"] == gross
    assert w["fringe_plan"] == 33_760 and w["fringe_cash"] == 0
    assert premium_text in w["rule"]
    assert all(ln["rule"] == w["rule"] for ln in w["lines"])


def test_1_3_later_rate_change_leaves_earlier_period(hr, job):
    wid = _chen(hr)
    _split_week(hr, job, wid)
    _determination(hr, job, end="2026-10-31")
    pid = _period(hr)
    before = payroll.preview(hr, pid)["workers"][0]["gross"]
    _determination(hr, job, base="55.00", start="2026-11-01")
    after = payroll.preview(hr, pid)["workers"][0]
    assert after["gross"] == before
    assert {ln["base"] for ln in after["lines"] if ln["job_id"] == job} == \
        {5_240}
    assert payroll.resolve_rate(hr, wid, job, "2026-11-02")["base"] == 5_500


def _twelve(office, job):
    other = second_job(office)
    ids = []
    for i in range(12):
        wid = timeentry.add_worker(office, f"Worker {i + 1:02d}", "CARP",
                                   employee_no=f"E2{i + 1:02d}")
        payroll.pay_setup(office, wid, pay_rate="30.00")
        for d in WEEK:
            ids.append(timeentry.add_line(office, wid, d, job, "03-3000",
                                          "9"))
        ids.append(timeentry.add_line(office, wid, "2026-10-24", other,
                                      "06-1000", "1.25"))
    approve_time(office, ids)
    return ids


def test_2_1_provider_export_rows_and_hours(hr, job):
    ids = _twelve(hr, job)
    pid = _period(hr)
    m = provider.add_map(hr, "Generic CSV",
                         earning_codes={"REG": "E01", "OT": "E02"})
    out = provider.export(hr, pid, m)
    rows = list(csv.DictReader(io.StringIO(open(out["path"]).read())))
    assert out["rows"] == len(rows) == 12 * 2
    assert {r["Earning code"] for r in rows} == {"E01", "E02"}
    approved = sum(hr.db.get("time_lines", i)["hours"] for i in ids)
    assert sum(cents.hours(r["Hours"]) for r in rows) == approved
    assert out["hours"] == approved == 12 * 4625
    assert "SSN" not in rows[0] and all(r["Employee number"].startswith("E2")
                                        for r in rows)


def test_2_2_register_unknown_employee_listed_nothing_else_changes(hr, job):
    _twelve(hr, job)
    pid = _period(hr)
    m = provider.add_map(hr, "Generic CSV")
    text = ("Employee number,Gross,Employer taxes,Federal tax,State tax,"
            "Deductions,Net,Reference\n"
            "E201,1500.00,120.00,150.00,60.00,25.00,1265.00,ACH-1001\n"
            "E999,900.00,70.00,90.00,30.00,0.00,780.00,ACH-1002\n")
    workers_before = hr.db.rows("SELECT * FROM workers ORDER BY id")
    prev = provider.preview_register(hr, pid, m, text=text)
    assert prev["unmatched"] == ["row 3: employee number E999 is not known"]
    res = provider.import_register(hr, pid, m, text=text)
    assert res["imported"] == 1 and res["unmatched"] == prev["unmatched"]
    (reg,) = provider.register(hr, pid)
    assert (reg["employee_no"], reg["gross"], reg["net"], reg["reference"]) \
        == ("E201", 150_000, 126_500, "ACH-1001")
    assert reg["taxes"] == {"Federal tax": 15_000, "State tax": 6_000}
    assert hr.db.rows("SELECT * FROM workers ORDER BY id") == workers_before
    assert not hr.db.one("SELECT id FROM provider_registers WHERE "
                         "employee_no = 'E999'")
