"""P1-05 time entry (5.1-5.3) and P1-06 time approvals and lock (6.1-6.3)."""
import pytest

from quantisheet_backoffice import approvals, cents, security, timeentry
from quantisheet_backoffice.security import Denied


def test_5_1_import_time_card(office, job):
    office.act_as("ap@bo.test")
    ids = timeentry.import_timecards(office, job)
    rows = [office.db.get("time_lines", i) for i in ids]
    assert len(rows) == 4
    assert all(r["status"] == "Draft" and r["cost_code"] == "03-3000" and
               r["date"] == "2026-10-19" for r in rows)
    assert cents.hours_text(sum(r["hours"] for r in rows)) == "32.00"
    assert timeentry.import_timecards(office, job) == []


def _chen_week(office, job, user_id=None):
    wid = timeentry.add_worker(office, "M. Chen", "LAB", user_id=user_id)
    days = ["2026-10-19", "2026-10-20", "2026-10-21", "2026-10-22",
            "2026-10-23"]
    ids = [timeentry.add_line(office, wid, d, job, "03-3000", h)
           for d, h in zip(days, ["9", "10", "9", "9.5", "8.5"])]
    return wid, ids


def test_5_2_weekly_total_and_overtime_flag(office, job):
    wid, _ = _chen_week(office, job)
    t = timeentry.weekly_total(office, wid, "2026-10-24")
    assert cents.hours_text(t["hours"]) == "46.00"
    assert t["flag"] == "over 40 h: 6.00 h may be overtime"
    assert t["colour"] == "yellow"


def test_5_3_unknown_cost_code_cannot_be_submitted(office, job):
    wid = timeentry.add_worker(office, "J. Ruiz", "LAB")
    lid = timeentry.add_line(office, wid, "2026-10-20", job, "09-9000", "8")
    with pytest.raises(timeentry.TimeError, match="09-9000"):
        timeentry.submit(office, [lid])
    assert office.db.get("time_lines", lid)["status"] == "Draft"


def _path_foreman_pm(office, job):
    approvals.set_path(office, "time_line",
                       [approvals.step("jobrole:Foreman"),
                        approvals.step("jobrole:PM")], job_id=job)


def test_6_1_foreman_then_pm_reject_one_day(office, job):
    _path_foreman_pm(office, job)
    wid, ids = _chen_week(office, job)
    timeentry.submit(office, ids)
    office.act_as("fm@bo.test")
    timeentry.decide(office, ids, "approve")
    assert all(timeentry.status_text(office, i) == "Submitted, waiting on PM"
               for i in ids)
    office.act_as("pm@bo.test")
    timeentry.decide(office, [ids[2]], "reject", "wrong cost code")
    ln = office.db.get("time_lines", ids[2])
    assert ln["status"] == "Draft" and ln["reject_reason"] == "wrong cost code"
    for i in ids[:2] + ids[3:]:
        req = approvals.request(office, "time_line", i)
        assert req["status"] == "pending" and req["step"] == 1   # step 1 done
        assert office.db.get("time_lines", i)["status"] == "Submitted"


def test_6_2_locked_week_and_admin_unlock(office, job):
    approvals.set_path(office, "time_line", [approvals.step("jobrole:PM")],
                       job_id=job)
    wid, ids = _chen_week(office, job)
    timeentry.submit(office, ids)
    office.act_as("pm@bo.test")
    timeentry.decide(office, ids, "approve")
    timeentry.lock_week(office, "2026-10-24")
    office.act_as("ap@bo.test")
    with pytest.raises(timeentry.TimeError, match="locked"):
        timeentry.edit_line(office, ids[0], hours="7")
    with pytest.raises(Denied):
        timeentry.unlock_week(office, "2026-10-24", "fix")
    office.act_as("admin@bo.test")
    with pytest.raises(timeentry.TimeError, match="reason"):
        timeentry.unlock_week(office, "2026-10-24", "")
    timeentry.unlock_week(office, "2026-10-24", "payroll correction")
    acts = [r["action"] for r in security.audit_rows(office.db,
                                                      record_type="week")]
    assert "lock" in acts and "unlock" in acts
    un = security.audit_rows(office.db, action="unlock")[-1]
    assert "payroll correction" in un["after"]


def test_6_3_no_approving_own_time(office, job):
    pm = office.user_id("pm@bo.test")
    approvals.set_path(office, "time_line", [approvals.step("jobrole:PM")],
                       job_id=job)
    wid = timeentry.add_worker(office, "Pat Morgan", "FMN", user_id=pm)
    lid = timeentry.add_line(office, wid, "2026-10-20", job, "03-3000", "8")
    timeentry.submit(office, [lid])
    office.act_as("pm@bo.test")
    assert security.allowed("Approver", "time.approve")
    with pytest.raises(Denied, match="own"):
        timeentry.decide(office, [lid], "approve")
    assert office.db.get("time_lines", lid)["status"] == "Submitted"


def test_5_1_time_cards_brought_in_before_the_rename_are_not_doubled(
        office, job):
    """Cards imported under the program's earlier name keep that key;
    importing the same cards again adds nothing."""
    office.act_as("ap@bo.test")
    ids = timeentry.import_timecards(office, job)
    for i in ids:
        key = office.db.get("time_lines", i)["source_key"]
        office.db.update("time_lines", i, source_key=key.replace(
            "quantisheet:timecard:", timeentry.OLD_CARD_PREFIX, 1))
    assert timeentry.import_timecards(office, job) == []
