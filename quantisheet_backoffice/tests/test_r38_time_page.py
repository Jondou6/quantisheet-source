"""r38 G2.4: the Time page can enter time (pay types REG/OT/DT/PTO/HOL),
edit a Draft line, submit, import QuantiSheet time cards and turn a day's
punches into Draft time. Made-up data only (fixture job 2611)."""
import pytest

from quantisheet_backoffice import cents, remote, timeentry


def _page(office):
    from quantisheet_backoffice.ui.time_page import TimePage
    return TimePage(office)


def _punch(office, wid, job, code, kind, t, rid):
    with office.db.tx():
        office.db.insert("punches", remote_id=rid, worker_id=wid, job_id=job,
                         cost_code=code, kind=kind, punch_time=t,
                         synced_at=t, status="New")


def test_window_time_page_is_the_entry_screen(office, job, qapp):
    from quantisheet_backoffice.ui.main_window import NAV, BackOfficeWindow
    from quantisheet_backoffice.ui.time_page import TimePage
    w = BackOfficeWindow(office)
    pg = w.show_page(NAV.index("Time"))
    assert isinstance(pg, TimePage)
    w.close()


def test_add_ot_line_from_the_page(office, job, qapp):
    timeentry.add_labor_class(office, "LAB", "Laborer", "0", "0")
    wid = timeentry.add_worker(office, "W. Example", "LAB")
    pg = _page(office)
    assert [pg.pay_type.itemText(i) for i in range(pg.pay_type.count())] == \
        list(timeentry.PAY_TYPES)
    assert "Pay type" in [pg.grid.horizontalHeaderItem(i).text()
                          for i in range(pg.grid.columnCount())]
    lid = pg.add_line(worker_id=wid, date="2026-10-20", job_id=job,
                      cost_code="03-3000", pay_type="OT", hours="2.5")
    ln = office.db.get("time_lines", lid)
    assert (ln["pay_type"], ln["hours"], ln["status"], ln["source"]) == \
        ("OT", 250, "Draft", "manual")
    texts = [pg.grid.item(r, c).text() for r in range(pg.grid.rowCount())
             for c in range(pg.grid.columnCount()) if pg.grid.item(r, c)]
    assert "OT" in texts and "2.50" in texts


def test_form_fields_drive_add(office, job, qapp):
    timeentry.add_labor_class(office, "LAB", "Laborer", "0", "0")
    wid = timeentry.add_worker(office, "W. Example", "LAB")
    pg = _page(office)
    pg.worker.setCurrentIndex(pg.worker.findData(wid))
    pg.date.setText("2026-10-21")
    pg.job.setCurrentIndex(pg.job.findData(job))
    pg.code.setCurrentText("03-3000")
    pg.pay_type.setCurrentText("DT")
    pg.hours.setText("1.25")
    pg.add_btn.click()
    (ln,) = office.db.rows("SELECT * FROM time_lines WHERE deleted = 0")
    assert (ln["worker_id"], ln["date"], ln["pay_type"], ln["hours"]) == \
        (wid, "2026-10-21", "DT", 125)
    assert pg.msg.text().startswith("Added")


def test_edit_and_submit_selected(office, job, qapp):
    timeentry.add_labor_class(office, "LAB", "Laborer", "0", "0")
    wid = timeentry.add_worker(office, "W. Example", "LAB")
    lid = timeentry.add_line(office, wid, "2026-10-20", job, "03-3000", "8")
    pg = _page(office)
    pg.select_line(lid)
    pg.edit_selected(hours="7.5", pay_type="OT")
    ln = office.db.get("time_lines", lid)
    assert (ln["hours"], ln["pay_type"]) == (750, "OT")
    pg.select_line(lid)
    pg.submit_selected()
    assert office.db.get("time_lines", lid)["status"] == "Submitted"


def test_errors_show_on_the_page_not_a_modal(office, job, qapp):
    timeentry.add_labor_class(office, "LAB", "Laborer", "0", "0")
    wid = timeentry.add_worker(office, "W. Example", "LAB")
    pg = _page(office)
    pg.worker.setCurrentIndex(pg.worker.findData(wid))
    pg.date.setText("2026-10-21")
    pg.hours.setText("30")
    pg.add_btn.click()
    assert "between 0 and 24" in pg.msg.text()
    assert office.db.scalar("SELECT COUNT(*) FROM time_lines") == 0


def test_import_time_cards_button(office, job, qapp):
    pg = _page(office)
    pg.job.setCurrentIndex(pg.job.findData(job))
    pg.import_btn.click()
    assert office.db.scalar("SELECT COUNT(*) FROM time_lines") == 4
    assert "4" in pg.msg.text()
    pg.import_btn.click()
    assert office.db.scalar("SELECT COUNT(*) FROM time_lines") == 4


def test_convert_punches_for_a_day(office, job, qapp):
    wid = timeentry.add_worker(office, "W. Example", "LAB")
    w2 = timeentry.add_worker(office, "V. Example", "LAB")
    _punch(office, wid, job, "03-3000", "in", "2026-10-27T07:00:00", "p1")
    _punch(office, wid, job, "03-3000", "out", "2026-10-27T15:30:00", "p2")
    _punch(office, w2, job, "03-3000", "in", "2026-10-27T07:00:00", "p3")
    _punch(office, w2, job, "03-3000", "out", "2026-10-27T11:00:00", "p4")
    _punch(office, wid, job, "03-3000", "in", "2026-10-28T07:00:00", "p5")
    ids = remote.punches_to_time_for_day(office, "2026-10-27")
    hrs = sorted(office.db.get("time_lines", i)["hours"] for i in ids)
    assert hrs == [400, 850]
    assert remote.punches_to_time_for_day(office, "2026-10-27") == []
    pg = _page(office)
    pg.date.setText("2026-10-28")
    pg.punch_btn.click()           # only an "in": nothing to pair
    assert office.db.scalar("SELECT COUNT(*) FROM time_lines") == 2
    assert "0" in pg.msg.text()


def test_viewer_cannot_enter_time(office, job, qapp):
    office.act_as("viewer@bo.test")
    pg = _page(office)
    for b in (pg.add_btn, pg.edit_btn, pg.submit_btn, pg.import_btn,
              pg.punch_btn):
        assert not b.isEnabled()
    assert pg.grid is not None
