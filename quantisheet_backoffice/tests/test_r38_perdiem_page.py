"""r38 G2.1: per diem on the Time page - set a job's rate (none shipped),
make per diem from time, add one by hand, submit and approve. Errors stay on
the page. Made-up EXAMPLE amounts only (fixture job 2611)."""
from quantisheet_backoffice import perdiem, timeentry


def _page(office):
    from quantisheet_backoffice.ui.time_page import TimePage
    return TimePage(office)


def _worker(office):
    timeentry.add_labor_class(office, "LAB", "Laborer", "0", "0")
    return timeentry.add_worker(office, "W. Example", "LAB")


def test_r38_page_has_per_diem_controls(office, job, qapp):
    pg = _page(office)
    for b in (pg.pd_rate_btn, pg.pd_add_btn, pg.pd_make_btn, pg.pd_submit_btn,
              pg.pd_approve_btn):
        assert b.isEnabled()
    assert [pg.pd_grid.horizontalHeaderItem(i).text()
            for i in range(pg.pd_grid.columnCount())] == \
        ["Date", "Worker", "Job", "Cost code", "Kind", "Amount", "Status", "Source"]
    assert pg.pd_amount.text() == ""          # no default amount is shipped


def test_r38_rate_make_submit_approve(office, job, qapp):
    wid = _worker(office)
    timeentry.add_line(office, wid, "2026-10-20", job, "03-3000", "8")
    pg = _page(office)
    pg.make_per_diem("2026-10-19", "2026-10-25")
    assert "no job has a per diem rate" in pg.msg.text().lower() or "0 " in pg.msg.text()
    pg.set_rate(job, "12.34", "03-3000")
    (pid,) = pg.make_per_diem("2026-10-19", "2026-10-25")
    assert office.db.get("per_diem_lines", pid)["amount"] == 1234
    assert pg.pd_grid.item(0, 5).text() == "12.34"
    pg.select_per_diem(pid)
    pg.submit_per_diem()
    office.act_as("pm@bo.test")
    pg.select_per_diem(pid)
    pg.approve_per_diem()
    assert office.db.get("per_diem_lines", pid)["status"] == "Approved"
    assert pg.pd_grid.item(0, 6).text() == "Approved"


def test_r38_add_by_hand_and_error_on_page(office, job, qapp):
    wid = _worker(office)
    pg = _page(office)
    pid = pg.add_per_diem(wid, "2026-10-21", job, "03-3000", "20")
    assert office.db.get("per_diem_lines", pid)["amount"] == 2000
    pg.pd_amount.setText("20")
    pg.date.setText("2026-10-21")
    pg.worker.setCurrentIndex(pg.worker.findData(wid))
    pg.pd_add_btn.click()
    assert "already has a per diem" in pg.msg.text()


def test_r38_viewer_per_diem_disabled(office, job, qapp):
    office.act_as("viewer@bo.test")
    pg = _page(office)
    assert not any(b.isEnabled() for b in (pg.pd_rate_btn, pg.pd_add_btn,
                   pg.pd_make_btn, pg.pd_submit_btn, pg.pd_approve_btn))
