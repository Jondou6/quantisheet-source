"""r38 G2.1: per diem records. A per diem is a flat daily amount paid to a
worker for a day on a job (made-up EXAMPLE amounts only; Back Office ships
no rate: until someone sets a job's rate nothing is made). It is entered or
made from time, approved like time, locked with the week, frozen by a final
payroll, and rolls up to the job's cost code (not as labor)."""
import pytest

from quantisheet_backoffice import approvals, jobcost, perdiem, store, timeentry
from quantisheet_backoffice.security import Denied


def _w(office, name="M. Chen"):
    return timeentry.add_worker(office, name, "LAB")


def test_r38_tables_are_additive():
    assert "per_diem_lines" in store.TABLES and "per_diem_rates" in store.TABLES
    for t in ("time_lines", "workers", "jobs"):
        assert "per_diem" not in store.TABLES[t]


def test_r38_no_rate_shipped_nothing_made(office, job):
    wid = _w(office)
    timeentry.add_line(office, wid, "2026-10-20", job, "03-3000", "8")
    assert perdiem.job_rate(office, job, "2026-10-20") is None
    assert perdiem.from_time(office, "2026-10-19", "2026-10-25") == []
    with pytest.raises(perdiem.PerDiemError, match="no per diem rate"):
        perdiem.add(office, wid, "2026-10-20", job, "03-3000")


def test_r38_manual_add_and_one_per_worker_day(office, job):
    wid = _w(office)
    pid = perdiem.add(office, wid, "2026-10-20", job, "03-3000", "45.50")
    ln = office.db.get("per_diem_lines", pid)
    assert (ln["amount"], ln["status"], ln["source"], ln["kind"]) == \
        (4550, "Draft", "manual", "Per diem")
    with pytest.raises(perdiem.PerDiemError, match="already has a per diem"):
        perdiem.add(office, wid, "2026-10-20", job, "03-3000", "10")
    with pytest.raises(perdiem.PerDiemError, match="more than \\$0"):
        perdiem.add(office, wid, "2026-10-21", job, "03-3000", "0")
    with pytest.raises(perdiem.PerDiemError, match="kind"):
        perdiem.add(office, wid, "2026-10-21", job, "03-3000", "5", kind="Bonus")


def test_r38_rate_and_made_from_time_once(office, job):
    a, b = _w(office, "A. Example"), _w(office, "B. Example")
    timeentry.add_line(office, a, "2026-10-20", job, "03-3000", "6")
    timeentry.add_line(office, a, "2026-10-20", job, "03-3000", "2", pay_type="OT")
    timeentry.add_line(office, b, "2026-10-21", job, "03-3000", "8")
    timeentry.add_line(office, b, "2026-10-22", job, "03-3000", "0")
    perdiem.set_job_rate(office, job, "12.34", "03-3000")
    assert perdiem.job_rate(office, job, "2026-10-20")["amount"] == 1234
    ids = perdiem.from_time(office, "2026-10-19", "2026-10-25")
    rows = sorted((r["worker_id"], r["date"], r["amount"], r["source"])
                  for r in (office.db.get("per_diem_lines", i) for i in ids))
    assert rows == [(a, "2026-10-20", 1234, "time"), (b, "2026-10-21", 1234, "time")]
    assert perdiem.from_time(office, "2026-10-19", "2026-10-25") == []


def test_r38_rate_effective_from(office, job):
    perdiem.set_job_rate(office, job, "10", "03-3000", effective_from="2026-10-01")
    perdiem.set_job_rate(office, job, "20", "03-3000", effective_from="2026-10-21")
    assert perdiem.job_rate(office, job, "2026-10-20")["amount"] == 1000
    assert perdiem.job_rate(office, job, "2026-10-21")["amount"] == 2000
    assert perdiem.job_rate(office, job, "2026-09-30") is None


def test_r38_submit_approve_reject(office, job):
    approvals.set_path(office, "per_diem", [approvals.step("jobrole:PM")], job_id=job)
    wid = _w(office)
    p1 = perdiem.add(office, wid, "2026-10-20", job, "03-3000", "30")
    p2 = perdiem.add(office, wid, "2026-10-21", job, "03-3000", "30")
    perdiem.submit(office, [p1, p2])
    assert perdiem.status_text(office, p1) == "Submitted, waiting on PM"
    with pytest.raises(perdiem.PerDiemError, match="Submitted"):
        perdiem.edit(office, p1, amount="31")
    office.act_as("pm@bo.test")
    perdiem.decide(office, [p1], "approve")
    perdiem.decide(office, [p2], "reject", "not on site")
    assert office.db.get("per_diem_lines", p1)["status"] == "Approved"
    r2 = office.db.get("per_diem_lines", p2)
    assert (r2["status"], r2["reject_reason"]) == ("Draft", "not on site")
    perdiem.edit(office, p2, amount="25")
    assert office.db.get("per_diem_lines", p2)["amount"] == 2500


def test_r38_unknown_cost_code_cannot_be_submitted(office, job):
    wid = _w(office)
    pid = perdiem.add(office, wid, "2026-10-20", job, "09-9000", "30")
    with pytest.raises(perdiem.PerDiemError, match="09-9000"):
        perdiem.submit(office, [pid])


def test_r38_permissions(office, job):
    wid = _w(office)
    office.act_as("viewer@bo.test")
    with pytest.raises(Denied):
        perdiem.add(office, wid, "2026-10-20", job, "03-3000", "30")
    with pytest.raises(Denied):
        perdiem.set_job_rate(office, job, "10", "03-3000")


def _approved(office, job, wid, d="2026-10-20", amt="30"):
    pid = perdiem.add(office, wid, d, job, "03-3000", amt)
    perdiem.submit(office, [pid])
    office.act_as("pm@bo.test")
    perdiem.decide(office, [pid], "approve")
    office.act_as("admin@bo.test")
    return pid


def test_r38_week_lock_and_unlock(office, job):
    wid = _w(office)
    pid = _approved(office, job, wid)
    timeentry.lock_week(office, "2026-10-24")
    assert office.db.get("per_diem_lines", pid)["status"] == "Locked"
    with pytest.raises(perdiem.PerDiemError, match="locked"):
        perdiem.add(office, wid, "2026-10-21", job, "03-3000", "30")
    timeentry.unlock_week(office, "2026-10-24", "fix a day")
    assert office.db.get("per_diem_lines", pid)["status"] == "Approved"


def test_r38_jobcost_rollup(office, job):
    before = jobcost.by_code(office, job)["03-3000"]
    wid = _w(office)
    pid = _approved(office, job, wid, amt="45.50")
    perdiem.add(office, wid, "2026-10-21", job, "03-3000", "99")   # Draft: not counted
    r = jobcost.by_code(office, job)["03-3000"]
    assert r["per_diem"] == 4550
    assert r["labor"] == before["labor"]                 # not labor
    assert r["actual"] == before["actual"] + 4550
    src = [s for s in r["sources"] if s["type"] == "per_diem"]
    assert [(s["id"], s["amount"]) for s in src] == [(pid, 4550)]
    assert jobcost.totals(office, job)["per_diem"] == 4550
    assert jobcost.by_code(office, job, date_to="2026-10-19")["03-3000"]["per_diem"] == 0


def test_r38_delete_draft_only(office, job):
    wid = _w(office)
    pid = _approved(office, job, wid)
    with pytest.raises(perdiem.PerDiemError, match="Approved"):
        perdiem.delete(office, pid)
    p2 = perdiem.add(office, wid, "2026-10-21", job, "03-3000", "5")
    perdiem.delete(office, p2)
    assert office.db.get("per_diem_lines", p2)["deleted"] == 1
    assert perdiem.add(office, wid, "2026-10-21", job, "03-3000", "6")   # day free again


def test_r38_int_amount_refused(office, job):
    wid = _w(office)
    from quantisheet_backoffice.cents import MoneyError
    with pytest.raises(MoneyError):
        perdiem.add(office, wid, "2026-10-20", job, "03-3000", 30)


def test_r38_final_payroll_freezes_per_diem(office, job):
    wid = _w(office)
    pid = perdiem.add(office, wid, "2026-10-20", job, "03-3000", "30")
    with office.db.tx():
        office.db.insert("pay_periods", start="2026-10-19", end="2026-10-25",
                         status="Final")
    with pytest.raises(perdiem.PerDiemError, match="final"):
        perdiem.edit(office, pid, amount="31")
    with pytest.raises(perdiem.PerDiemError, match="final"):
        perdiem.add(office, wid, "2026-10-21", job, "03-3000", "30")
