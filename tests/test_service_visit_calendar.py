"""Agreement visit calendar (Nov 5): every planned visit with its state -
done, work order open, due with no work order, upcoming."""
import datetime as dt

import pytest

from app.service import agreements, workorder
from r111_support import isolate, qapp, records  # noqa: F401

TODAY = dt.date(2026, 8, 1)


@pytest.fixture(autouse=True)
def svc_home(tmp_path, monkeypatch):
    return isolate(tmp_path, monkeypatch)


def _setup():
    rec, prop, _eq = records()
    ag = agreements.blank()
    orders = workorder.blank()
    agreements.add(ag, "", "900", 4, "2027-01-01", property_id=prop,
                   start="2026-01-01", records=rec)
    gone = agreements.add(ag, "Test Gone", "100", 1, "2027-01-01",
                          site="9 Test Lane", start="2026-01-01")
    agreements.cancel(ag, gone)
    return rec, ag, orders


def test_states_and_rescheduled_dates():
    rec, ag, orders = _setup()
    cal = agreements.visit_calendar(ag, orders, "2026-01-01", "2026-12-31",
                                    today=TODAY)
    assert [(v["date"], v["state"]) for v in cal] == [
        ("2026-01-01", "due"), ("2026-04-01", "due"), ("2026-07-01", "due"),
        ("2026-10-01", "upcoming")]                     # cancelled: left out
    made = agreements.create_due_work_orders(ag, orders, rec, today=TODAY)
    workorder.get(orders, made[0])["status"] = "closed"
    workorder.get(orders, made[1])["scheduled"] = "2026-04-03"
    cal = agreements.visit_calendar(ag, orders, "2026-01-01", "2026-12-31",
                                    today=TODAY)
    assert [(v["date"], v["planned"], v["state"]) for v in cal] == [
        ("2026-01-01", "2026-01-01", "done"),
        ("2026-04-03", "2026-04-01", "open"),
        ("2026-07-01", "2026-07-01", "open"),
        ("2026-10-01", "2026-10-01", "upcoming")]
    assert cal[1]["work_order"] == workorder.get(orders, made[1])["number"]
    assert agreements.visit_calendar(ag, orders, *agreements.month_range(
        2026, 4), today=TODAY)[0]["date"] == "2026-04-03"
    assert agreements.month_range(2026, 12) == ("2026-12-01", "2026-12-31")
    assert agreements.month_range(2028, 2) == ("2028-02-01", "2028-02-29")


def test_window_shows_the_month_and_opens_due_visits(qapp):
    from app.service import visit_calendar_ui
    from app.estimating import service
    rec, ag, orders = _setup()
    service.save(rec)
    agreements.save(ag)
    workorder.save(orders)
    w = visit_calendar_ui.VisitCalendarWindow(today=TODAY)
    w.cal.setCurrentPage(2026, 7)
    assert w.month() == ("2026-07-01", "2026-07-31")
    assert w.table.rowCount() == 1
    assert w.table.item(0, 4).text().startswith("Due")
    assert "1 visit(s) this month" in w.msg.text()
    made = w.due_clicked()
    assert made is not None, w.msg.text()
    assert len(made) == 3
    assert w.table.item(0, 4).text() == "Work order open"
    assert len(workorder.load()["orders"]) == 3            # saved
    w.cal.setCurrentPage(2026, 10)
    assert w.table.item(0, 4).text() == "Upcoming"
    w.cal.setCurrentPage(2026, 11)
    assert w.table.rowCount() == 0
    assert w.msg.text() == "No agreement visits this month."
    w.close()


def test_agreements_window_opens_the_calendar(qapp):
    from app.service import agreements_ui
    w = agreements_ui.AgreementsWindow()
    cal = w.calendar_clicked()
    assert cal.isVisible() and cal.windowTitle() == "Agreement Visit Calendar"
    cal.close()
    w.close()
