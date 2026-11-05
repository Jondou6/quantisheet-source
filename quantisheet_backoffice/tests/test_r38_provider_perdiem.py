"""r38 G2.3: approved per diem goes to the payroll provider file as its own
non-wage earning line (code PERDIEM, mappable; no hours, no rate). It is kept
out of gross: wage rows, hours, the 'amount' total and the register gross
check are exactly what they were. Made-up EXAMPLE amounts; file only."""
import csv
import io

from quantisheet_backoffice import cents, payroll, perdiem, provider, timeentry

from .m3_helpers import WEEK, add_hr, approve_time, second_job

import pytest


@pytest.fixture
def hr(office):
    add_hr(office)
    timeentry.add_labor_class(office, "CARP", "Carpenter EXAMPLE", "0", "0")
    office.act_as("hr@bo.test")
    return office


def _worker(office, name, no):
    wid = timeentry.add_worker(office, name, "CARP", employee_no=no)
    payroll.pay_setup(office, wid, pay_rate="20.00")       # EXAMPLE rate
    return wid


def _pd(office, wid, d, job, amt, code="03-3000", approve=True):
    who = office.user
    office.act_as("admin@bo.test")
    pid = perdiem.add(office, wid, d, job, code, amt)
    if approve:
        perdiem.submit(office, [pid])
        office.act_as("pm@bo.test")
        perdiem.decide(office, [pid], "approve")
    office.act_as(who["id"])
    return pid


def _rows(path):
    return list(csv.DictReader(io.StringIO(open(path).read())))


def _week(office, job, wid):
    approve_time(office, [timeentry.add_line(office, wid, d, job, "03-3000", "8")
                          for d in WEEK])


def _period(office):
    return payroll.add_period(office, "2026-10-19", "2026-10-25", "2026-10-30")


def test_r38_per_diem_row_outside_gross(hr, job, tmp_path):
    wid = _worker(hr, "M. Chen", "E101")
    _week(hr, job, wid)
    pid = _period(hr)
    m = provider.add_map(hr, "Generic CSV")
    before = provider.export(hr, pid, m, path=str(tmp_path / "a.csv"))
    rows_before = _rows(before["path"])
    for d in WEEK[:3]:
        _pd(hr, wid, d, job, "45.50")
    _pd(hr, wid, WEEK[3], job, "45.50", approve=False)          # not approved
    _pd(hr, wid, "2026-10-26", job, "45.50")                    # next period
    out = provider.export(hr, pid, m, path=str(tmp_path / "b.csv"))
    rows = _rows(out["path"])
    assert rows[:len(rows_before)] == rows_before               # wages unchanged
    (pd,) = rows[len(rows_before):]
    assert (pd["Employee number"], pd["Earning code"], pd["Hours"], pd["Rate"],
            pd["Amount"]) == ("E101", "PERDIEM", "", "", "136.50")
    assert (out["amount"], out["hours"]) == (before["amount"], before["hours"])
    assert out["non_wage_amount"] == 13650
    assert out["rows"] == before["rows"] + 1


def test_r38_per_diem_code_is_mappable_and_old_maps_work(hr, job, tmp_path):
    wid = _worker(hr, "M. Chen", "E101")
    _week(hr, job, wid)
    _pd(hr, wid, WEEK[0], job, "10")
    pid = _period(hr)
    m = provider.add_map(hr, "Mapped", earning_codes={"PERDIEM": "E09"})
    assert [r["Earning code"] for r in provider.export_rows(hr, pid, m)][-1] == "E09"
    old = provider.add_map(hr, "Old")                 # as a 0.13.9 map was saved
    hr.db.update("provider_maps", old, earning_codes='{"REG": "REG", "OT": "OT", '
                 '"DT": "DT", "PTO": "PTO", "HOL": "HOL"}')
    assert [r["Earning code"] for r in provider.export_rows(hr, pid, old)][-1] == "PERDIEM"


def test_r38_job_detail_and_per_diem_only_worker(hr, job, tmp_path):
    other = second_job(hr)
    a = _worker(hr, "A. Example", "E201")
    b = _worker(hr, "B. Example", "E202")
    _week(hr, job, a)
    _pd(hr, a, WEEK[0], job, "10")
    _pd(hr, a, WEEK[1], other, "12", code="06-1000")
    _pd(hr, b, WEEK[2], job, "7")                    # no time this period
    pid = _period(hr)
    m = provider.add_map(hr, "By job", detail="job")
    pd = [r for r in provider.export_rows(hr, pid, m) if r["Earning code"] == "PERDIEM"]
    assert [(r["Employee number"], r["Job"], r["Cost code"], r["Amount"]) for r in pd] == \
        [("E201", "2611", "03-3000", "10.00"), ("E201", "2702", "06-1000", "12.00"),
         ("E202", "2611", "03-3000", "7.00")]


def test_r38_register_gross_check_unaffected(hr, job, tmp_path):
    wid = _worker(hr, "M. Chen", "E101")
    _week(hr, job, wid)
    _pd(hr, wid, WEEK[0], job, "45.50")
    pid = _period(hr)
    m = provider.add_map(hr, "Generic CSV")
    gross = payroll.preview(hr, pid)["workers"][0]["gross"]
    text = ("Employee number,Gross,Employer taxes,Deductions,Net,Reference\n"
            f"E101,{cents.text(gross)},0.00,0.00,{cents.text(gross)},EX-1\n")
    assert provider.preview_register(hr, pid, m, text=text)["mismatches"] == []


def test_r38_payroll_page_export_says_per_diem_is_non_wage(hr, job, qapp):
    from quantisheet_backoffice.ui.people_pages import PayrollPage
    wid = _worker(hr, "M. Chen", "E101")
    _week(hr, job, wid)
    _pd(hr, wid, WEEK[0], job, "45.50")
    _period(hr)
    import shiboken6
    pg = PayrollPage(hr)
    try:
        pg.export()
        assert "per diem $45.50 as a non-wage line (not in gross)" in pg.rule.text()
    finally:
        # PayrollPage (0.13.9) wires its buttons with lambdas; a page left
        # alive until interpreter exit can crash PySide's teardown, so the
        # test destroys it itself.
        shiboken6.delete(pg)
