"""Time Off page and calendar widget, offscreen: stats, the calendar's
grid and bars, drag-to-request, the request dialog's live summary, approve
/ decline / cancel, search, filter and sort, holidays, and permissions."""
from datetime import date

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from quantisheet_backoffice import hr, pto, timeoff

from .m3_helpers import add_hr

TODAY = date(2026, 11, 4)


@pytest.fixture
def hro(office):
    add_hr(office)
    office.act_as("hr@bo.test")
    return office


def _emp(o, name, no, hours="40"):
    eid = hr.add_employee(o, name, no, "2025-01-06", labor_class="LAB")
    pol = pto.add_policy(o, f"PTO {no}", per_hours="30", cap="80")
    pto.assign(o, eid, pol)
    pto.adjust(o, eid, "2026-10-01", hours, "opening balance")
    return eid


def _page(o, qapp):
    from quantisheet_backoffice.ui.timeoff_page import TimeOffPage
    pg = TimeOffPage(o, today=TODAY)
    pg.resize(1100, 900)
    pg.show()
    qapp.processEvents()
    return pg


def _click(w, pos, kind="press"):
    t = {"press": QMouseEvent.Type.MouseButtonPress,
         "move": QMouseEvent.Type.MouseMove,
         "release": QMouseEvent.Type.MouseButtonRelease}[kind]
    ev = QMouseEvent(t, QPointF(pos), QPointF(pos),
                     Qt.MouseButton.LeftButton,
                     Qt.MouseButton.LeftButton if kind != "release"
                     else Qt.MouseButton.NoButton,
                     Qt.KeyboardModifier.NoModifier)
    {"press": w.mousePressEvent, "move": w.mouseMoveEvent,
     "release": w.mouseReleaseEvent}[kind](ev)


def test_page_shows_team_stats_calendar_and_requests(hro, qapp):
    a = _emp(hro, "R. Diaz", "E401")
    b = _emp(hro, "M. Chen", "E402")
    timeoff.add_holiday(hro, "2026-11-11", "Veterans Day")
    r1 = pto.request(hro, a, "2026-11-09", "2026-11-10", "8")
    pto.decide(hro, r1, "approve")
    pto.request(hro, b, "2026-11-16", "2026-11-16", "8", note="dentist")
    pg = _page(hro, qapp)
    assert [c.value.text() for c in pg.cards] == [
        "1 pending", "0 off today", "2 days off"]
    assert pg.cal.title.text() == "November 2026"
    kinds = sorted(i["kind"] for i in pg.cal.items)
    assert kinds == ["holiday", "pending", "timeoff"]
    pg.cal.grid.repaint()
    assert len(pg.cal.grid.hits) == 3            # three bars painted
    assert pg.grid.rowCount() == 2
    assert pg.grid.item(0, 0).text() == "M. Chen"        # newest first
    pg.search.setText("dentist")
    assert pg.grid.rowCount() == 1
    pg.search.clear()
    pg.status.setCurrentIndex(pg.status.findData("Approved"))
    assert [pg.grid.item(i, 0).text() for i in range(pg.grid.rowCount())] \
        == ["R. Diaz"]
    pg.status.setCurrentIndex(0)
    pg.sort_by(0)                                   # Employee column
    assert pg.grid.item(0, 0).text() == "M. Chen"
    pg.sort_by(0)
    assert pg.grid.item(0, 0).text() == "R. Diaz"


def test_one_employee_view_shows_hours_and_balance(hro, qapp):
    a = _emp(hro, "R. Diaz", "E401", hours="40")
    r1 = pto.request(hro, a, "2026-11-09", "2026-11-10", "8")
    pto.decide(hro, r1, "approve")
    pg = _page(hro, qapp)
    pg.who.setCurrentIndex(pg.who.findData(a))
    assert pg.cards[0].value.text() == "40.00 h available"
    assert pg.cards[2].value.text() == "16.00 h upcoming"
    assert pg.cal.hours["2026-11-09"] == {"work": 0, "pto": 800}


def test_drag_on_calendar_opens_request_and_sends_it(hro, qapp):
    a = _emp(hro, "R. Diaz", "E401", hours="40")
    timeoff.add_holiday(hro, "2026-11-26", "Thanksgiving")
    pg = _page(hro, qapp)
    pg.who.setCurrentIndex(pg.who.findData(a))
    g = pg.cal.grid
    rows = g.rows()
    r = next(i for i, w in enumerate(rows) if date(2026, 11, 23) in w)
    c0 = rows[r].index(date(2026, 11, 23))
    c1 = rows[r].index(date(2026, 11, 27))
    p0 = g.cell(r, c0, len(rows)).center().toPoint() + QPoint(0, 30)
    p1 = g.cell(r, c1, len(rows)).center().toPoint() + QPoint(0, 30)
    seen = {}

    def drive(dlg):
        seen["summary"] = dlg.summary.text()
        seen["values"] = dlg.values()[1:3]
        return True
    got = []
    pg.cal.rangeSelected.disconnect()
    pg.cal.rangeSelected.connect(
        lambda s, e: got.append(pg.new_request(s, e, accept=drive)))
    _click(g, p0, "press")
    _click(g, p1, "move")
    _click(g, p1, "release")
    assert seen["values"] == (date(2026, 11, 23), date(2026, 11, 27))
    assert seen["summary"].startswith("4 working day(s), 32.00 h.")
    assert "after this request 8.00 h" in seen["summary"]
    rid = got[0]
    assert hro.db.get("pto_requests", rid)["total"] == 3200
    assert pg.message.text() == "Request sent."


def test_dialog_blocks_a_request_over_the_balance(hro, qapp):
    a = _emp(hro, "R. Diaz", "E401", hours="8")
    from quantisheet_backoffice.ui.timeoff_page import RequestDialog
    from PySide6.QtWidgets import QDialogButtonBox
    dlg = RequestDialog(hro, [{"id": a, "name": "R. Diaz"}], a,
                        date(2026, 11, 9), date(2026, 11, 11))
    ok = dlg.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert not ok.isEnabled()
    assert "Not enough balance" in dlg.summary.text()
    dlg.b.setDate(dlg.a.date())
    assert ok.isEnabled()


def test_approve_decline_cancel_from_the_table(hro, qapp):
    a = _emp(hro, "R. Diaz", "E401")
    b = _emp(hro, "M. Chen", "E402")
    c = _emp(hro, "L. Park", "E403")
    r1 = pto.request(hro, a, "2026-11-09", "2026-11-09", "8")
    r2 = pto.request(hro, b, "2026-11-10", "2026-11-10", "8")
    r3 = pto.request(hro, c, "2026-11-12", "2026-11-12", "8")
    pg = _page(hro, qapp)
    by_id = {r["id"]: i for i, r in enumerate(pg.rows)}
    pg.grid.setCurrentCell(by_id[r1], 0)
    pg.decide("approve")
    by_id = {r["id"]: i for i, r in enumerate(pg.rows)}
    pg.grid.setCurrentCell(by_id[r2], 0)
    pg.decide("reject")
    by_id = {r["id"]: i for i, r in enumerate(pg.rows)}
    pg.grid.setCurrentCell(by_id[r3], 0)
    pg.cancel()
    st = {r: hro.db.get("pto_requests", r)["status"] for r in (r1, r2, r3)}
    assert st == {r1: "Approved", r2: "Rejected", r3: "Cancelled"}
    assert pg.message.text() == "L. Park: request cancelled."


def test_clicking_a_bar_selects_its_request(hro, qapp):
    a = _emp(hro, "R. Diaz", "E401")
    pto.request(hro, a, "2026-11-09", "2026-11-10", "8")
    pg = _page(hro, qapp)
    pg.cal.grid.repaint()
    rect, it = pg.cal.grid.hits[0]
    _click(pg.cal.grid, rect.center().toPoint(), "press")
    assert pg.grid.currentRow() == 0


def test_holidays_dialog_adds_and_removes(hro, qapp):
    from quantisheet_backoffice.ui.timeoff_page import HolidaysDialog
    from PySide6.QtCore import QDate
    d = HolidaysDialog(hro)
    d.day.setDate(QDate(2026, 12, 25))
    d.name.setText("Christmas Day")
    d.add()
    assert d.list.item(0).text() == "2026-12-25  Christmas Day"
    d.list.setCurrentRow(0)
    d.remove()
    assert d.list.count() == 0


def test_week_view_and_navigation(hro, qapp):
    pg = _page(hro, qapp)
    pg.cal.set_mode("week")
    a, b = pg.cal.span()
    assert (a, b) == (date(2026, 11, 2), date(2026, 11, 8))
    pg.cal.step(1)
    assert pg.cal.span()[0] == date(2026, 11, 9)
    pg.cal.set_mode("month")
    pg.cal.step(-1)
    assert pg.cal.title.text() == "October 2026"
    pg.cal.go_today()
    assert pg.cal.title.text() == "November 2026"


def test_viewer_and_approver_see_no_names(office, qapp):
    from quantisheet_backoffice.ui.timeoff_page import TimeOffPage
    office.act_as("viewer@bo.test")
    pg = TimeOffPage(office, today=TODAY)
    assert not pg.ready
    office.act_as("pm@bo.test")
    assert not TimeOffPage(office, today=TODAY).ready


def test_year_end_and_print_report_buttons(hro, qapp, tmp_path):
    _emp(hro, "R. Example", "E451", hours="40")
    pg = _page(hro, qapp)
    assert pg.yearend_btn.text() == "Year end…"
    text = pg.year_end_text()
    assert "R. Example" in text and "carries" in text
    out = pg.print_report(path=str(tmp_path / "t.pdf"))
    assert out and out.endswith("t.pdf")
