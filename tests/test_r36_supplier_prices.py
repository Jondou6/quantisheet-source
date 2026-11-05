"""r36 A5: import a supplier / dealer price list from your own CSV or
Excel file into a NEW price list file you name - never into the
program's folders, never over an existing file, never a database.
Made-up supplier data only."""
import json
import os

import openpyxl
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import settings                                   # noqa: E402
from app.estimating import _io, supplier_prices as SP       # noqa: E402


@pytest.fixture(autouse=True)
def _cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "_cache", {})


def _csv(tmp_path):
    p = tmp_path / "dealer.csv"
    p.write_text("Item #,Description,UOM,Unit Price,Pack,Category\n"
                 "A-100,Test 2x4x8 stud,EA,$3.25,1,Lumber\n"
                 "A-200,Test 1/2 board 4x8,SHT,12.80,1,Drywall\n"
                 ",Test no sku,EA,1.00,1,Misc\n"
                 "A-300,Test screws,BOX,bad,1,Fasteners\n", encoding="utf-8")
    return str(p)


def test_guess_columns_and_build(tmp_path):
    head, rows = SP.read(_csv(tmp_path))
    m = SP.guess_mapping(head)
    assert m["sku"] == 0 and m["desc"] == 1 and m["unit"] == 2
    assert m["price"] == 3 and m["pack"] == 4 and m["category"] == 5
    res = SP.build(head, rows, m, "Test Lumber Yard", effective="2026-10-01",
                   file_name="dealer.csv")
    pl = res["pricelist"]
    assert pl["supplier"] == "Test Lumber Yard"
    assert [i["sku"] for i in pl["items"]] == ["A-100", "A-200"]
    assert pl["items"][0]["price"] == "3.25"
    assert len(res["skipped"]) == 2           # no sku, unreadable price
    assert pl["source_file"] == "dealer.csv"


def test_save_new_file_only_and_load_back(tmp_path):
    head, rows = SP.read(_csv(tmp_path))
    pl = SP.build(head, rows, SP.guess_mapping(head), "Test Yard")["pricelist"]
    out = str(tmp_path / "mine" / "yard_prices.json")
    assert SP.save(pl, out) == out
    assert SP.load(out) == pl
    with pytest.raises(SP.PriceListError):          # never over a file
        SP.save(pl, out)
    SP.save(pl, out, overwrite=True)
    with pytest.raises(_io.PathError):
        SP.save(pl, str(tmp_path / "prices.db"))
    with pytest.raises(_io.PathError):
        SP.save(pl, os.path.join(_io.APP_DIR, "data", "yard.json"))
    with pytest.raises(_io.PathError):
        SP.save(pl, str(tmp_path / "yard.csv"))


def test_excel_import(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["SKU", "Item Description", "Unit", "Price"])
    ws.append(["B-1", "Test shingle bundle", "BDL", 31.5])
    p = str(tmp_path / "list.xlsx")
    wb.save(p)
    res = SP.import_file(p, "Test Roofing Supply",
                         str(tmp_path / "roof.json"))
    assert res["saved"].endswith("roof.json")
    data = json.load(open(res["saved"], encoding="utf-8"))
    assert data["items"][0]["price"] == "31.50"


def test_find_by_sku_or_description(tmp_path):
    head, rows = SP.read(_csv(tmp_path))
    pl = SP.build(head, rows, SP.guess_mapping(head), "Y")["pricelist"]
    assert SP.find(pl, sku="A-200")["desc"] == "Test 1/2 board 4x8"
    assert SP.find(pl, desc="test 2X4X8  stud")["sku"] == "A-100"
    assert SP.find(pl, sku="none") is None


def test_no_bundled_supplier_data():
    # the program ships no price list: nothing under app/ looks like one
    for dp, _dn, fn in os.walk(_io.APP_DIR):
        for f in fn:
            if f.endswith(".json") and "supplier" in f.lower():
                raise AssertionError(os.path.join(dp, f))
