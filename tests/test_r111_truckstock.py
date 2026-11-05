"""Truck stock: issue to a work order, restock list into the order export."""
import os
from decimal import Decimal

import pytest

from app.estimating.materials import NO_SUPPLIER
from app.service import truckstock
from r111_support import isolate, qapp  # noqa: F401


@pytest.fixture(autouse=True)
def svc_home(tmp_path, monkeypatch):
    return isolate(tmp_path, monkeypatch)


def test_issue_takes_stock_off_the_named_truck():
    store = truckstock.blank()
    a = truckstock.add_truck(store, "Test truck A", tech="A Tester")
    b = truckstock.add_truck(store, "Test truck B")
    truckstock.add_part(store, "Test capacitor", "12.50", "24", sku="CAP-1",
                        supplier="Test Supply", min_qty="2")
    truckstock.receive(store, a, "CAP-1", "3")
    truckstock.receive(store, b, "CAP-1", "1")
    line = truckstock.issue(store, a, "CAP-1", "2", work_order_id="WO-1")
    assert line["cost"] == "12.50"
    assert line["price"] == "24.00"
    assert truckstock.on_hand(store, a, line["part_id"]) == Decimal("1")
    assert truckstock.on_hand(store, b, line["part_id"]) == Decimal("1")
    try:
        truckstock.issue(store, b, "CAP-1", "2")
        assert False, "the truck does not have two"
    except truckstock.TruckError:
        pass
    # truck A is under the minimum of 2; truck B is under it too
    lines = truckstock.restock_lines(store)
    assert {(r["truck"], r["order_qty"]) for r in lines} == {
        ("Test truck A", Decimal("1")), ("Test truck B", Decimal("1"))}


def test_restock_feeds_the_material_order_export(tmp_path):
    store = truckstock.blank()
    a = truckstock.add_truck(store, "Test truck A")
    b = truckstock.add_truck(store, "Test truck B")
    truckstock.add_part(store, "Test capacitor", "10", "20", sku="CAP-1",
                        supplier="Test Supply", min_qty="4")
    truckstock.add_part(store, "Test fuse", "1", "3", sku="F-1", min_qty="2")
    truckstock.receive(store, a, "CAP-1", "1")
    truckstock.receive(store, b, "CAP-1", "1")
    # fuse stays at zero on both trucks
    order = truckstock.as_material_order(store)
    assert set(order) == {"Test Supply", NO_SUPPLIER}
    cap = order["Test Supply"][0]
    assert cap["desc"] == "Test capacitor"
    assert cap["sku"] == "CAP-1"
    # each truck is short 3, one purchase line
    assert cap["qty"] == Decimal("6")
    assert cap["cost"] == Decimal("60.00")
    assert sorted(cap["sources"]) == ["truck Test truck A", "truck Test truck B"]
    fuse = order[NO_SUPPLIER][0]
    assert fuse["desc"] == "Test fuse"
    assert fuse["qty"] == Decimal("4")
    path = truckstock.export_restock(store, str(tmp_path / "restock.csv"))
    text = open(path, encoding="utf-8").read()
    assert "Test capacitor" in text
    assert "Test Supply" in text
    assert "Test fuse" in text
    assert os.path.basename(path) == "restock.csv"


def test_window_receives_and_lists_the_restock(qapp, tmp_path):
    from app.service.truckstock_ui import TruckWindow
    win = TruckWindow()
    win.truck_name.setText("Test truck A")
    win.tech.setText("A Tester")
    win.add_truck_clicked()
    win.desc.setText("Test fuse")
    win.sku.setText("F-1")
    win.cost.setText("1")
    win.price.setText("3")
    win.minimum.setText("2")
    win.add_part_clicked()
    win.which.setCurrentIndex(0)
    win.part.setCurrentIndex(0)
    win.qty.setText("1")
    win.receive_clicked()
    assert "1" in win.table.item(0, 3).text()
    assert win.restock.rowCount() == 1
    path = win.export_to(str(tmp_path / "restock.csv"))
    assert path and "Test fuse" in open(path, encoding="utf-8").read()
    win.close()
