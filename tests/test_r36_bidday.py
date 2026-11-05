"""r36 B4: bid-day quote intake and side-by-side comparison - each sub /
supplier's prices per scope item, plugs for what they left out (your own
plug number, else the other bidders' median), the lowest leveled total
and the lowest complete quote. Made-up bidders and prices only."""
import csv
import os
from decimal import Decimal

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.estimating import bidday                      # noqa: E402

D = Decimal


def _sheet():
    return bidday.new_sheet("Test earthwork", [
        {"id": "1", "desc": "Test strip topsoil", "unit": "SY", "qty": "5000"},
        {"id": "2", "desc": "Test mass excavation", "unit": "CY",
         "qty": "8000", "plug": "64000"},
        {"id": "3", "desc": "Test erosion control", "unit": "LS",
         "qty": "1"}],
        [{"name": "Test Sub A", "prices": {"1": "10000", "2": "60000",
                                           "3": "5000"}},
         {"name": "Test Sub B", "prices": {"1": "9000", "3": "4000"},
          "excluded": ["2"]},
         {"name": "Test Sub C", "prices": {"1": "12000", "2": "58000"}}])


def test_plugs_leveled_totals_and_lowest():
    r = bidday.compare(_sheet())
    b = {x["name"]: x for x in r["bidders"]}
    assert b["Test Sub A"]["total"] == D("75000.00")
    assert b["Test Sub A"]["complete"] and b["Test Sub A"]["plugs"] == 0
    # B left out item 2: your plug 64,000 goes in
    assert b["Test Sub B"]["total"] == D("9000") + D("64000") + D("4000")
    assert b["Test Sub B"]["missing"] == ["2"] and not b["Test Sub B"][
        "complete"]
    # C left out item 3 (no plug of yours): the others' median 4,500
    assert b["Test Sub C"]["total"] == D("12000") + D("58000") + D("4500")
    assert b["Test Sub C"]["as_quoted"] == D("70000.00")
    assert r["lowest_complete"] == "Test Sub A"
    assert r["lowest_leveled"] == "Test Sub C"         # 74,500
    row2 = next(x for x in r["rows"] if x["id"] == "2")
    assert row2["cells"]["Test Sub B"] == {"amount": D("64000.00"),
                                           "plug": True, "excluded": True}
    assert row2["low"] == "Test Sub C"


def test_item_nobody_priced_and_no_plug_leaves_everyone_incomplete():
    s = _sheet()
    s["scope"].append({"id": "4", "desc": "Test dewatering", "unit": "LS",
                       "qty": "1", "plug": ""})
    r = bidday.compare(s)
    assert r["lowest_complete"] == ""
    assert all("4" in x["unplugged"] for x in r["bidders"])


def test_csv_intake_round_trip(tmp_path):
    p = tmp_path / "bids.csv"
    p.write_text("Item,Description,Unit,Qty,My plug,Test Sub A,Test Sub B\n"
                 "1,Test strip topsoil,SY,5000,,\"$10,000\",9000\n"
                 "2,Test mass excavation,CY,8000,64000,60000,excl\n",
                 encoding="utf-8")
    s = bidday.read_csv(str(p), "Test earthwork")
    assert [x["name"] for x in s["bidders"]] == ["Test Sub A", "Test Sub B"]
    assert s["bidders"][1]["excluded"] == ["2"]
    assert s["bidders"][0]["prices"]["1"] == "10000.00"
    r = bidday.compare(s)
    assert r["lowest_complete"] == "Test Sub A"
    out = bidday.export(r, str(tmp_path / "compare.csv"))
    rows = list(csv.reader(open(out, encoding="utf-8")))
    assert rows[0][:4] == ["Item", "Description", "Unit", "Qty"]
    assert any("PLUG" in c for r_ in rows for c in r_)


def test_saved_in_the_pdf_by_package():
    d = fitz.open()
    d.new_page()
    bidday.save(d, _sheet())
    other = bidday.new_sheet("Test paving", [], [])
    bidday.save(d, other)
    assert bidday.packages(d) == ["Test earthwork", "Test paving"]
    assert bidday.load(d, "Test earthwork")["bidders"][0]["name"] == \
        "Test Sub A"
    bidday.delete(d, "Test paving")
    assert bidday.packages(d) == ["Test earthwork"]


def test_bad_amount_is_refused():
    s = _sheet()
    s["bidders"][0]["prices"]["1"] = "ten thousand"
    with pytest.raises(bidday.BidDayError):
        bidday.compare(s)
