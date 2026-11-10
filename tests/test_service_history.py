"""Customer History (Nov 5): one customer's sites, units, work orders,
invoices and refrigerant entries, newest first, with totals. Made-up
customers only."""
import pytest

from app.estimating import service as records_api
from app.service import agreements, history, refrigerant, workorder
from r111_support import isolate, qapp, records  # noqa: F401


@pytest.fixture(autouse=True)
def svc_home(tmp_path, monkeypatch):
    return isolate(tmp_path, monkeypatch)


def _setup():
    rec, prop, eq = records()
    other = records_api.add_property(rec, "Other Test Shop", "9 Test Rd",
                                     customer="Other Tester")
    records_api.save(rec)
    orders = workorder.blank()
    workorder.set_rates(orders, "100", "40")
    w1 = workorder.add(orders, rec, property_id=prop, equipment_id=eq,
                       complaint="No heat", tech="A Tester", when="2026-10-01")
    workorder.add_time(orders, w1, "A Tester", "2")
    workorder.no_parts(orders, w1)
    workorder.close_and_invoice(orders, w1, notes="Reset the test furnace.",
                                write_pdf=False, when="2026-10-02")
    workorder.add(orders, rec, property_id=prop, complaint="Noisy blower",
                  when="2026-10-20")
    workorder.add(orders, rec, property_id=other, complaint="Not mine",
                  when="2026-10-21")
    # same name typed by hand, no site link: matched by exact name only
    workorder.add(orders, customer="  test   SMITH ", site="Shop",
                  complaint="Walk-in", when="2026-10-22")
    workorder.add(orders, customer="Test Smithson", site="Shop",
                  complaint="Close name, not the same", when="2026-10-23")
    workorder.save(orders)
    ref = refrigerant.blank()
    uid = refrigerant.add_unit(ref, rec, eq, "R-410A", "8",
                               "comfort_cooling")
    refrigerant.add_visit(ref, uid, "2026-10-02", lbs_added="1.5",
                          cylinder="CYL-TEST", cert_no="TEST-608", tech="A")
    refrigerant.save(ref)
    return rec, prop, eq


def test_by_name_and_by_property():
    rec, prop, _eq = _setup()
    h = history.history(customer="Test Smith")
    nums = sorted(o["complaint"] for o in h["work_orders"])
    assert nums == ["No heat", "Noisy blower", "Walk-in"]   # not Smithson
    t = h["totals"]
    assert (t["work_orders"], t["open"], t["invoices"], t["units"]) == \
        (3, 2, 1, 1)
    assert t["billed"] == "200.00"
    assert h["refrigerant"] and h["refrigerant"][0]["refrigerant"] == "R-410A"
    assert h["events"][0][0] >= h["events"][-1][0]           # newest first
    assert "exact name" in " ".join(history.summary_lines(h))
    hp = history.history(property_id=prop)
    assert sorted(o["complaint"] for o in hp["work_orders"]) == \
        ["No heat", "Noisy blower"]                         # site-linked only
    names = [n for n, _k in history.customers(
        records_api.load(), workorder.load(), agreements.load())]
    assert "Test Smith" in names and "Other Tester" in names


def test_window(qapp):
    _setup()
    from app.service import history_ui
    w = history_ui.open_window(customer="Test Smith")
    assert w.history["totals"]["work_orders"] == 3
    assert w.table.rowCount() == len(w.history["events"])
    assert w.units.rowCount() == 1
    w.close()
