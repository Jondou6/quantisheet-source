"""Service agreements: visits, renewal warnings, profit, due work orders."""
import datetime as dt
from decimal import Decimal

import pytest

from app.estimating import service
from app.service import agreements, workorder
from r111_support import isolate, qapp, records  # noqa: F401


@pytest.fixture(autouse=True)
def svc_home(tmp_path, monkeypatch):
    return isolate(tmp_path, monkeypatch)


def test_term_defaults_and_visit_dates():
    store = agreements.blank()
    aid = agreements.add(store, "Test Smith", "1200", 2, "2027-03-31",
                         site="1 Test Lane")
    agr = agreements.get(store, aid)
    assert agr["start"] == "2026-03-31"
    assert agr["number"] == "SA-0001"
    assert agreements.visit_dates(agr) == [dt.date(2026, 3, 31),
                                           dt.date(2026, 9, 30)]
    # a leap-day renewal steps back to a real day
    aid2 = agreements.add(store, "Test Smith", "100", 1, "2028-02-29",
                          site="2 Test Lane")
    assert agreements.get(store, aid2)["start"] == "2027-02-28"


def test_due_visits_open_once_and_warnings_are_30_60_90():
    rec, prop, _eq = records()
    ag = agreements.blank()
    orders = workorder.blank()
    aid = agreements.add(ag, "", "900", 4, "2027-01-01", property_id=prop,
                         start="2026-01-01", records=rec)
    created = agreements.create_due_work_orders(
        ag, orders, rec, today=dt.date(2026, 8, 1))
    assert len(created) == 3  # Jan, Apr, Jul; October is still ahead
    again = agreements.create_due_work_orders(
        ag, orders, rec, today=dt.date(2026, 8, 1))
    assert again == []
    wo = workorder.get(orders, created[0])
    assert wo["billing"] == "agreement"
    assert wo["call_type"] == "pm"
    assert wo["agreement_id"] == aid
    assert wo["customer"] == "Test Smith"
    # nothing is due before the term starts
    fresh = workorder.blank()
    assert agreements.create_due_work_orders(
        ag, fresh, rec, today=dt.date(2025, 12, 1)) == []

    def band(day):
        rows = agreements.renewal_warnings(ag, today=day)
        return rows[0]["band"] if rows else None

    assert band(dt.date(2026, 8, 1)) is None
    assert band(dt.date(2026, 10, 15)) == 90   # 78 days
    assert band(dt.date(2026, 11, 10)) == 60   # 52 days
    assert band(dt.date(2026, 12, 15)) == 30   # 17 days
    assert band(dt.date(2027, 1, 5)) == "overdue"
    agreements.cancel(ag, aid)
    assert agreements.renewal_warnings(ag, today=dt.date(2026, 12, 15)) == []
    assert agreements.create_due_work_orders(
        ag, workorder.blank(), rec, today=dt.date(2026, 8, 1)) == []


def test_profit_is_price_against_time_and_parts_and_cover():
    ag = agreements.blank()
    orders = workorder.blank()
    aid = agreements.add(ag, "Test Smith", "1200.00", 2, "2027-01-01",
                         site="1 Test Lane", start="2026-01-01")
    wid = workorder.add(orders, customer="Test Smith", site="1 Test Lane",
                        complaint="Planned maintenance visit (SA-0001)",
                        billing="agreement", agreement_id=aid, call_type="pm")
    workorder.add_time(orders, wid, "A Tester", "2", bill="0", cost="40")
    workorder.add_part(orders, wid, "Test filter", "1", cost="20", price="0")
    got = agreements.profit(agreements.get(ag, aid), orders)
    assert got["price"] == Decimal("1200.00")
    assert got["cost"] == Decimal("100.00")
    assert got["profit"] == Decimal("1100.00")
    # ticket profit is the visit cost; the agreement holds the price
    ticket = workorder.ticket_profit(orders, wid)
    assert ticket["price"] == Decimal("0.00")
    assert ticket["profit"] == Decimal("-100.00")
    assert agreements.covers(ag, "Test Smith", dt.date(2026, 6, 1))["id"] == aid
    assert agreements.covers(ag, "Someone else", dt.date(2026, 6, 1)) is None
    assert agreements.covers(ag, "Test Smith", dt.date(2027, 6, 1)) is None


def test_window_lists_profit_and_opens_due_visits(qapp, tmp_path):
    from app.service.agreements_ui import AgreementsWindow
    win = AgreementsWindow()
    win.customer.setText("Test Smith")
    win.site.setText("1 Test Lane")
    win.price.setText("600")
    win.visits.setText("1")
    win.renewal.setText("2026-12-01")
    win.add_clicked()
    assert win.table.rowCount() == 1
    assert "600.00" in win.table.item(0, 3).text()
    # renewal 2026-12-01 is inside 90 days of the test clock only if today
    # is close; the warning column follows the real today, so just require
    # the row. Force a due visit by rewriting the start into the past.
    agr = win.store["agreements"][0]
    agr["start"] = "2020-01-01"
    agreements.save(win.store, win.path)
    win.due_clicked()
    assert "1 planned" in win.msg.text()
    assert workorder.load()["orders"][0]["call_type"] == "pm"
    out = win.print_to(str(tmp_path / "agreements.pdf"))
    assert out and os_path_ok(out)
    win.close()


def os_path_ok(path):
    import os
    return os.path.isfile(path)
