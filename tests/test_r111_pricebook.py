"""Flat-rate pricebook: customer and member prices, option quotes."""
import os
from decimal import Decimal

import fitz
import pytest

from app.estimating import quotes
from app.service import pricebook
from r111_support import isolate, qapp, use_company  # noqa: F401


@pytest.fixture(autouse=True)
def svc_home(tmp_path, monkeypatch):
    return isolate(tmp_path, monkeypatch)


def _book():
    store = pricebook.blank()
    pricebook.add_task(store, "Test good filter", "180", "150", code="G",
                       hours="1", labor_cost="30", tier="Good",
                       parts=[{"desc": "Test filter", "qty": "1", "cost": "8"}])
    pricebook.add_task(store, "Test better filter", "240", "200", code="B",
                       hours="1", labor_cost="30", tier="Better")
    pricebook.add_task(store, "Test best filter", "320", "260", code="T",
                       hours="1.5", labor_cost="30", tier="Best")
    return store


def test_built_in_cost_and_member_price():
    store = _book()
    good = store["tasks"][0]
    assert pricebook.task_cost(good) == Decimal("38.00")
    assert pricebook.price_of(good, member=False) == Decimal("180.00")
    assert pricebook.price_of(good, member=True) == Decimal("150.00")


def test_option_quote_good_better_best(tmp_path, monkeypatch):
    use_company(monkeypatch)
    store = _book()
    q = pricebook.option_quote(store, [t["id"] for t in store["tasks"]],
                               selected_tier="Better")
    assert [t["name"] for t in q["tiers"]] == ["Good", "Better", "Best"]
    assert q["tiers"][0]["total"] == Decimal("180.00")
    assert q["tiers"][1]["total"] == Decimal("240.00")
    assert q["tiers"][2]["total"] == Decimal("320.00")
    assert q["selected"]["tier"] == "Better"
    assert q["selected"]["total"] == Decimal("240.00")
    # the customer quote shows prices, not the built-in cost
    member = pricebook.option_quote(
        store, [store["tasks"][0]["id"]], member=True, selected_tier="Good")
    assert member["tiers"][0]["price"] == Decimal("150.00")
    path = pricebook.save_quote(str(tmp_path / "options.pdf"), q)
    with fitz.open(path) as doc:
        text = "".join(page.get_text() for page in doc)
    assert "Test Plumbing Co" in text
    assert "Test better filter" in text
    assert "$240.00" in text
    assert "38.00" not in text
    with pytest.raises(quotes.QuoteError):
        quotes.service_option_quote([{"desc": "", "price": "10"}])
    with pytest.raises(quotes.QuoteError):
        quotes.service_option_quote([{"desc": "Test work", "price": "nope"}])


def test_window_adds_a_task_and_writes_a_quote(qapp, tmp_path, monkeypatch):
    use_company(monkeypatch)
    from app.service.pricebook_ui import PricebookWindow
    win = PricebookWindow()
    win.code.setText("CAP")
    win.name.setText("Test capacitor")
    win.customer.setText("199")
    win.member.setText("149")
    win.hours.setText("1")
    win.labor.setText("25")
    win.part.setText("Test capacitor, 1, 12.50")
    win.tier.setCurrentText("option")
    win.add_clicked()
    assert win.table.rowCount() == 1
    assert "$199.00" in win.table.item(0, 2).text()
    path = win.quote_to(str(tmp_path / "pb.pdf"))
    assert path and os.path.isfile(path)
    with fitz.open(path) as doc:
        assert "Test capacitor" in doc[0].get_text()
    win.close()
