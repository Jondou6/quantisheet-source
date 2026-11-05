"""Dispatch board: unassigned tickets, assign a day, print the day sheet."""
import os

import fitz
import pytest
from PySide6.QtWidgets import QAbstractItemView

from app.service import dispatch, workorder
from r111_support import isolate, qapp, use_company  # noqa: F401


@pytest.fixture(autouse=True)
def svc_home(tmp_path, monkeypatch):
    return isolate(tmp_path, monkeypatch)


def _open(store, customer, complaint):
    return workorder.add(store, customer=customer, site="1 Test Lane",
                         complaint=complaint)


def test_assign_moves_the_ticket_and_the_day_sheet_prints(tmp_path, monkeypatch):
    use_company(monkeypatch)
    store = workorder.blank()
    a = _open(store, "Test Smith", "No heat")
    b = _open(store, "Test Jones", "No cooling")
    day = "2026-11-04"
    info = dispatch.board(store, day)
    assert {w["id"] for w in info["unassigned"]} == {a, b}
    dispatch.add_tech(store, "A Tester")
    dispatch.assign(store, a, "A Tester", day)
    info = dispatch.board(store, day)
    assert [w["id"] for w in info["by_tech"]["A Tester"]] == [a]
    assert [w["id"] for w in info["unassigned"]] == [b]
    # a different day does not show Tuesday's ticket as that tech's work
    other = dispatch.board(store, "2026-11-05")
    assert other["by_tech"]["A Tester"] == []
    # Tuesday's ticket stays on Tuesday; only the open unscheduled one is waiting
    assert {w["id"] for w in other["unassigned"]} == {b}
    dispatch.assign(store, a, "", day)
    assert workorder.get(store, a)["tech"] == ""
    assert workorder.get(store, a)["scheduled"] == ""
    dispatch.assign(store, a, "A Tester", day)
    workorder.add_time(store, a, "A Tester", "1", bill="10", cost="5")
    workorder.no_parts(store, a)
    workorder.close(store, a, notes="Heat restored on the test unit.")
    try:
        dispatch.assign(store, a, "B Tester", day)
        assert False, "a closed ticket is not moved"
    except workorder.WorkOrderError:
        pass
    path = dispatch.day_sheet(store, day, str(tmp_path / "day.pdf"))
    with fitz.open(path) as doc:
        text = doc[0].get_text()
    assert "Test Plumbing Co" in text
    assert "Test Smith" in text
    assert "No heat" in text
    assert "2026-11-04" in text


def test_window_drag_lanes_assign(qapp, tmp_path, monkeypatch):
    use_company(monkeypatch)
    from PySide6.QtCore import QDate
    from app.service.dispatch_ui import DispatchWindow, _Lane
    store = workorder.blank()
    wid = _open(store, "Test Smith", "No heat")
    workorder.save(store)
    win = DispatchWindow()
    win.day.setDate(QDate(2026, 11, 4))
    assert win.lanes[""].count() == 1
    assert win.lanes[""].dragDropMode() == QAbstractItemView.DragDrop
    win.tech_name.setText("A Tester")
    win.add_tech_clicked()
    assert isinstance(win.lanes["A Tester"], _Lane)
    win.assign_to(wid, "A Tester")
    assert win.lanes["A Tester"].count() == 1
    assert win.lanes[""].count() == 0
    assert workorder.load()["orders"][0]["scheduled"] == "2026-11-04"
    # the drop handler is what a drag calls
    import inspect
    assert "assign_to" in inspect.getsource(_Lane.dropEvent)
    path = win.print_to(str(tmp_path / "day.pdf"))
    assert path and os.path.isfile(path)
    win.assign_to(wid, "")
    assert workorder.load()["orders"][0]["tech"] == ""
    win.close()
