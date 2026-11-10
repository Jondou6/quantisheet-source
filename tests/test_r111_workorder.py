"""Service work orders: one ticket, fill-in PDF, close requires notes,
time and parts, one-click invoice, profit. Made-up customers only."""
import os
from decimal import Decimal

import fitz
import pytest

from app.service import pdfdoc, workorder
from r111_support import isolate, png, qapp, records, use_company  # noqa: F401


@pytest.fixture(autouse=True)
def svc_home(tmp_path, monkeypatch):
    return isolate(tmp_path, monkeypatch)


def test_ticket_from_service_records_and_refuses_a_bad_unit():
    rec, prop, eq = records()
    store = workorder.blank()
    wid = workorder.add(store, rec, property_id=prop, equipment_id=eq,
                        complaint="No heat in the test hall", tech="A Tester")
    wo = workorder.get(store, wid)
    assert wo["number"] == "WO-0001"
    assert wo["customer"] == "Test Smith"
    assert wo["site"] == "Test Smith house"
    assert "TF-80" in wo["unit"] and "SN-TEST-1" in wo["unit"]
    assert wo["status"] == "open"
    other = workorder.blank()
    try:
        workorder.add(other, rec, property_id=prop, equipment_id="missing",
                      complaint="No heat")
        assert False, "a unit that is not on the record must be refused"
    except workorder.WorkOrderError:
        pass


def test_close_requires_notes_time_and_parts_then_invoices_tm():
    store = workorder.blank()
    workorder.set_rates(store, "100", "40")
    wid = workorder.add(store, customer="Test Smith", site="1 Test Lane",
                        complaint="No cooling")
    for notes, hours, parts in (
            ("", None, None),
            ("Checked the test unit.", None, None),
            ("Checked the test unit.", "2", None),
    ):
        try:
            if hours:
                workorder.add_time(store, wid, "A Tester", hours)
            if parts is not None:
                workorder.no_parts(store, wid)
            workorder.close(store, wid, notes=notes or None)
            assert False, "close must wait for notes, time and parts"
        except workorder.WorkOrderError:
            pass
    # the failed close that added time already recorded 2 hours; reset by
    # using that time, then mark parts and close for real
    workorder.no_parts(store, wid)
    inv = workorder.close_and_invoice(
        store, wid, notes="Replaced the test filter.", write_pdf=False)
    assert inv["number"] == "INV-0001"
    assert inv["billing"] == "tm"
    assert inv["total"] == "200.00"
    got = workorder.ticket_profit(store, wid)
    assert got["price"] == Decimal("200.00")
    assert got["cost"] == Decimal("80.00")
    assert got["profit"] == Decimal("120.00")
    try:
        workorder.close_and_invoice(store, wid, write_pdf=False)
        assert False, "a second invoice must be refused"
    except workorder.WorkOrderError:
        pass


def test_flat_rate_profit_uses_the_task_price_not_time_and_material():
    from app.service import pricebook
    book = pricebook.blank()
    tid = pricebook.add_task(
        book, "Test capacitor kit", "300", "250", code="CAP", hours="1.5",
        labor_cost="40", parts=[{"desc": "Test capacitor", "qty": "1",
                                 "cost": "10"}])
    task = pricebook.get(book, tid)
    assert pricebook.task_cost(task) == Decimal("70.00")
    store = workorder.blank()
    workorder.set_rates(store, "90", "40")
    wid = workorder.add(store, customer="Test Smith", site="1 Test Lane",
                        complaint="Weak airflow")
    workorder.apply_task(store, wid, task, member=True)
    workorder.use_book(store, wid, tech="A Tester")
    wo = workorder.get(store, wid)
    assert wo["billing"] == "flat"
    assert wo["flat_price"] == "250.00"
    assert wo["parts_recorded"] and wo["time"]
    assert len(wo["parts"]) == 1
    got = workorder.ticket_profit(store, wo)
    # member price 250, book cost 1.5 x 40 + 10 = 70
    assert got["price"] == Decimal("250.00")
    assert got["cost"] == Decimal("70.00")
    assert got["profit"] == Decimal("180.00")
    inv = workorder.close_and_invoice(
        store, wid, notes="Installed the test kit.", write_pdf=False)
    assert inv["total"] == "250.00"
    assert len(inv["lines"]) == 1
    assert inv["lines"][0]["desc"] == "Test capacitor kit"


def test_parts_come_off_the_truck_and_profit_uses_the_catalog_price():
    from app.service import truckstock
    trucks = truckstock.blank()
    tid = truckstock.add_truck(trucks, "Test truck 1", tech="A Tester")
    truckstock.add_part(trucks, "Test contactor", cost="10", price="25",
                        sku="TC-1", min_qty="1")
    truckstock.receive(trucks, tid, "TC-1", "1")
    store = workorder.blank()
    workorder.set_rates(store, "100", "50")
    wid = workorder.add(store, customer="Test Smith", site="1 Test Lane",
                        complaint="No heat")
    workorder.add_time(store, wid, "A Tester", "2")
    workorder.add_part(store, wid, "", "1", sku="TC-1", truck_store=trucks,
                       truck_id=tid)
    assert truckstock.on_hand(trucks, tid, truckstock.find_part(
        trucks, "TC-1")["id"]) == Decimal("0")
    got = workorder.ticket_profit(store, wid)
    assert got["price"] == Decimal("225.00")
    assert got["cost"] == Decimal("110.00")
    assert got["profit"] == Decimal("115.00")
    try:
        workorder.add_part(store, wid, "", "1", sku="TC-1", truck_store=trucks,
                           truck_id=tid)
        assert False, "an empty truck cannot issue the part"
    except workorder.WorkOrderError:
        pass


def test_fill_in_pdf_uses_the_company_and_keeps_fields(tmp_path, monkeypatch):
    base = use_company(monkeypatch)
    logo = png(tmp_path / "logo.png")
    from app import proposal
    shown = dict(base, logo=logo)
    monkeypatch.setattr(proposal, "company", lambda: dict(shown))
    store = workorder.blank()
    workorder.set_rates(store, "80", "30")
    wid = workorder.add(store, customer="Test Smith", site="1 Test Lane",
                        address="1 Test Lane", complaint="No hot water",
                        tech="A Tester")
    workorder.add_time(store, wid, "A Tester", "1")
    workorder.no_parts(store, wid)
    photo = png(tmp_path / "coil.png", (0.6, 0.2, 0.2))
    workorder.add_photo(store, wid, photo, caption="Test coil")
    path = workorder.print_work_order(store, wid, str(tmp_path / "wo.pdf"))
    fields = pdfdoc.read_fields(path)
    assert fields["wo_customer"] == "Test Smith"
    assert fields["wo_complaint"] == "No hot water"
    assert "A Tester" in fields["wo_time"]
    with fitz.open(path) as doc:
        text = "".join(page.get_text() for page in doc)
        assert "Test Plumbing Co" in text
        assert "555-0100" in text
        # the customer copy keeps cost and profit off (Chief, Nov 7)
        assert "Profit" not in text and "Cost " not in text
        assert "Test coil" in text
        images = [img for page in doc for img in page.get_images()]
    assert len(images) >= 2  # company logo and the coil photo
    inv = workorder.close_and_invoice(
        store, wid, notes="Flushed the test tank.",
        pdf_path=str(tmp_path / "inv.pdf"))
    with fitz.open(inv["pdf"]) as doc:
        text = doc[0].get_text()
    assert "Test Plumbing Co" in text
    assert "80.00" in text
    assert os.path.isfile(path)


def test_window_opens_closes_and_invoices(qapp, tmp_path):
    from app.service.workorder_ui import WorkOrderWindow
    win = WorkOrderWindow()
    win.customer.setText("Test Smith")
    win.site.setCurrentText("1 Test Lane")
    win.complaint.setText("No heat in the test hall")
    win.tech.setText("A Tester")
    win.bill.setText("100")
    win.cost_rate.setText("40")
    win.add_clicked()
    assert win.table.rowCount() == 1
    assert win.table.item(0, 0).text() == "WO-0001"
    win.hours.setText("2")
    win.add_time_clicked()
    win.no_parts_clicked()
    win.notes.setPlainText("Replaced the test filter.")
    win.close_clicked()
    assert "INV-0001" in win.msg.text()
    assert "$200.00" in win.msg.text()
    assert "$120.00" in win.profit.text()
    assert os.path.isfile(os.path.join(
        os.path.dirname(workorder.default_path()), "INV-0001.pdf"))
    printed = win.print_to(str(tmp_path / "from-window.pdf"))
    assert printed and os.path.isfile(printed)
    win.close()
