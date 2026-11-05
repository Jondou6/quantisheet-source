"""r36 A1: link takeoff to your own cost items - an estimate line from
one of your cost book items or supplier price list items, linked to a
takeoff group with an optional quantity formula (sheets = qty / 32 x
1.1), so the quantity follows the markups as they are drawn. Made-up data
only."""
import os
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import assemblies, estimate_lines as EL, settings   # noqa: E402
from app.estimating import costlink                           # noqa: E402
from estimate_helpers import area, blank_doc, make_book       # noqa: E402

SLAB = {"name": "Test slab", "type": "area", "unit": "sq ft"}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


def test_formula_link_turns_area_into_sheets_and_follows_markups():
    d = blank_doc()
    area(d, "Test slab", 10, 32)                    # 320 sq ft
    item = {"desc": "Test board sheet", "unit": "ea", "mat": "12.00",
            "code": "09 29 00", "source": "my list"}
    lid = costlink.link_item(d, item, SLAB, formula="ceil(qty / 32 * 1.1)")
    p = EL.priced(d)[0]
    assert p["id"] == lid and p["linked"]
    assert p["quantity"] == Decimal("11")            # ceil(320/32*1.1)
    assert p["total"] == Decimal("132.00")
    area(d, "Test slab", 10, 32, x0=500)            # draw more: 640 sq ft
    assert EL.priced(d)[0]["quantity"] == Decimal("22")
    assert EL.priced(d)[0]["problem"] == ""


def test_plain_link_without_formula_is_unchanged():
    d = blank_doc()
    area(d, "Test slab", 10, 10)
    lid = costlink.link_item(d, {"desc": "Test sealer", "unit": "sf",
                                 "mat": "0.50"}, SLAB)
    p = EL.priced(d)[0]
    assert p["quantity"] == Decimal("100") and p["total"] == Decimal("50.00")
    assert "formula" not in EL.get(d, lid)["link"]   # same as before r36


def test_bad_formula_is_refused_and_stored_bad_formula_reports_problem():
    d = blank_doc()
    area(d, "Test slab", 10, 10)
    with pytest.raises(EL.LineError):
        costlink.link_item(d, {"desc": "x", "unit": "ea", "mat": 1}, SLAB,
                           formula="__import__('os')")
    with pytest.raises(EL.LineError):
        costlink.link_item(d, {"desc": "x", "unit": "ea", "mat": 1}, SLAB,
                           formula="qty +")
    # a PDF from anywhere: a stored formula that doesn't work prices at 0
    EL.add(d, [EL.new_line("Test bad", 0, "ea", mat=1,
                           link=dict(SLAB, formula="nosuch * 2"))])
    p = EL.priced(d)[0]
    assert p["quantity"] == 0 and p["problem"]


def test_count_variable_and_set_formula():
    d = blank_doc()
    area(d, "Test slab", 10, 10)
    area(d, "Test slab", 10, 10, x0=500)
    lid = costlink.link_item(d, {"desc": "Test edge form", "unit": "ea",
                                 "mat": 2}, SLAB, formula="count * 4")
    assert EL.priced(d)[0]["quantity"] == Decimal("8")
    costlink.set_formula(d, lid, "qty * 2")
    assert EL.priced(d)[0]["quantity"] == Decimal("400")
    # each, from an area: removing the formula would leave a unit mismatch
    with pytest.raises(EL.LineError):
        costlink.set_formula(d, lid, "")
    lid2 = costlink.link_item(d, {"desc": "Test cure", "unit": "sf",
                                  "mat": 1}, SLAB, formula="qty * 1.05")
    assert EL.get(d, lid2)["link"]["formula"] == "qty * 1.05"
    costlink.set_formula(d, lid2, "")
    assert EL.priced(d)[1]["quantity"] == Decimal("200")


def test_item_from_cost_book_and_supplier_list():
    book = make_book()
    it = costlink.item_from_book(book, "09 29 10.30")
    assert it["desc"] == "Test gyp board" and Decimal(it["mat"]) == \
        Decimal("0.55")
    pl = {"supplier": "Test Supply Co", "items": [
        {"sku": "A-1", "desc": "Test stud 2x4", "unit": "ea",
         "price": "3.10", "pack": "1"}]}
    it2 = costlink.item_from_supplier(pl, "A-1")
    assert it2["desc"] == "Test stud 2x4" and it2["mat"] == "3.10"
    assert "Test Supply Co" in it2["source"]
    with pytest.raises(KeyError):
        costlink.item_from_supplier(pl, "NOPE")


def test_groups_lists_takeoff_groups():
    d = blank_doc()
    area(d, "Test slab", 10, 10)
    g = costlink.groups(d)
    assert [(x["name"], x["type"], x["unit"]) for x in g] == \
        [("Test slab", "area", "sq ft")]
