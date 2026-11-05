"""r36 B5: bid-item schedule import from your own CSV / Excel and export
of the schedule (generic columns only, CSV or .xlsx). Made-up items."""
import csv
import os
from decimal import Decimal

import openpyxl
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import heavy, settings                        # noqa: E402
from app.estimating import bid_items                   # noqa: E402

D = Decimal


@pytest.fixture(autouse=True)
def _cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "_cache", {})


def _file(tmp_path):
    p = tmp_path / "owner.csv"
    p.write_text("Item No,Description,Unit,Quantity,Unit Price\n"
                 "101,Test clearing,AC,2.5,3000\n"
                 "102,Test 8 in PVC sewer,LF,1200,\n"
                 "103,=HYPERLINK(\"x\"),EA,3,10\n", encoding="utf-8")
    return str(p)


def test_import_keeps_unit_prices_when_given(tmp_path):
    items = bid_items.import_items(_file(tmp_path))
    assert [i["no"] for i in items] == ["101", "102", "103"]
    assert items[0]["unit_price"] == "3000" and items[1]["unit_price"] == ""
    assert items[0]["owner_qty"] == "2.5"


def test_export_csv_and_xlsx_with_amounts_and_no_live_formulas(tmp_path):
    items = bid_items.import_items(_file(tmp_path))
    p = bid_items.export_items(items, str(tmp_path / "sched.csv"))
    rows = list(csv.reader(open(p, encoding="utf-8")))
    assert rows[0] == ["Item", "Description", "Unit", "Quantity",
                       "Unit price", "Amount"]
    assert rows[1][-1] == "7500.00"
    assert rows[3][1].startswith("'=")
    assert rows[-1][1] == "Total" and rows[-1][-1] == "7530.00"
    x = bid_items.export_items(items, str(tmp_path / "sched.xlsx"))
    ws = openpyxl.load_workbook(x).active
    assert ws["A1"].value == "Item" and ws.cell(4, 2).data_type == "s"


def test_into_a_civil_job_and_priced_schedule(tmp_path):
    job = heavy.blank()
    n = bid_items.add_to_job(job, bid_items.import_items(_file(tmp_path)))
    assert n == 3 and len(job["pay_items"]) == 3
    assert bid_items.add_to_job(job, bid_items.import_items(
        _file(tmp_path))) == 0                        # no duplicates
    lib = {"equipment": {}, "labor": {}, "crews": {}, "settings": {}}
    heavy.add_activity(job, "Test clear", qty=2.5, unit="AC", sub=5000,
                       pay_item="101")
    job["settings"]["markup_pct"] = 0
    sched = bid_items.from_job(job, lib)
    assert sched[0]["no"] == "101" and D(sched[0]["unit_price"]) == D("2000")
    p = bid_items.export_items(sched, str(tmp_path / "bid.csv"))
    assert os.path.getsize(p) > 0
