"""r36 v2 step 1a: Bid-Day 'Use this quote' - the chosen (or lowest
complete) sub/supplier quote goes into the estimate as lines, plugs
marked; re-applying replaces instead of adding; one Undo takes it back;
Estimate Error Check knows about plugs and quotes that changed after use.
Made-up bidders and prices only."""
import os
from decimal import Decimal

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import assemblies, estimate_lines as EL, settings   # noqa: E402
from app.history import History                               # noqa: E402
from app.estimating import bidday, checks, items              # noqa: E402
from estimate_helpers import blank_doc                        # noqa: E402
from test_r36_bidday import _sheet                            # noqa: E402

D = Decimal


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


def _doc():
    d = blank_doc()
    EL.add(d, [EL.new_line("Test own line", 2, "ea", mat="10")])
    bidday.save(d, _sheet())
    return d


def _bid_lines(d):
    return [ln for ln in EL.read(d) if ln["source"].startswith("Bid day:")]


def test_lowest_complete_goes_in_as_sub_lines_matching_the_quote():
    d = _doc()
    res = bidday.apply_quote(d, "Test earthwork")
    assert res["bidder"] == "Test Sub A" and res["plugs"] == []
    lines = _bid_lines(d)
    assert len(lines) == 3
    priced = {p["desc"]: p for p in EL.priced(d) if p["id"] in
              res["line_ids"].values()}
    assert priced["Test strip topsoil"]["total"] == D("10000.00")
    assert priced["Test strip topsoil"]["quantity"] == D("5000")
    assert priced["Test strip topsoil"]["ext"]["sub"] == D("10000.00")
    assert sum(p["total"] for p in priced.values()) == D("75000.00")
    assert all(ln["cost_type"] == "Subcontract" for ln in lines)
    assert bidday.load(d, "Test earthwork")["applied"]["bidder"] == \
        "Test Sub A"
    assert len(EL.read(d)) == 4                  # own line kept


def test_chosen_bidder_with_plugs_marked():
    d = _doc()
    res = bidday.apply_quote(d, "Test earthwork", "Test Sub B")
    assert res["plugs"] == ["2"]
    lines = {ln["desc"]: ln for ln in _bid_lines(d)}
    exc = lines["Test mass excavation"]
    assert exc["note"].startswith("PLUG")
    assert "your plug" in exc["note"]
    assert sum(p["total"] for p in EL.priced(d) if p["id"] in
               res["line_ids"].values()) == D("77000.00")


def test_reapplying_replaces_not_duplicates():
    d = _doc()
    bidday.apply_quote(d, "Test earthwork", "Test Sub B")
    bidday.apply_quote(d, "Test earthwork", "Test Sub B")
    assert len(_bid_lines(d)) == 3
    bidday.apply_quote(d, "Test earthwork", "Test Sub A")
    assert len(_bid_lines(d)) == 3
    assert {ln["source"] for ln in _bid_lines(d)} == {
        "Bid day: Test earthwork - Test Sub A"}
    assert len(EL.read(d)) == 4


def test_one_undo_takes_it_back():
    d = _doc()
    h = History(lambda: d.tobytes())
    bidday.apply_quote(d, "Test earthwork")
    h.snapshot()                                 # what the window does
    back = fitz.open(stream=h.undo(d), filetype="pdf")
    assert _bid_lines(back) == []
    assert "applied" not in bidday.load(back, "Test earthwork")
    assert len(EL.read(back)) == 1


def test_remove_quote_lines():
    d = _doc()
    bidday.apply_quote(d, "Test earthwork")
    assert bidday.remove_quote(d, "Test earthwork") == 3
    assert _bid_lines(d) == [] and len(EL.read(d)) == 1
    assert "applied" not in bidday.load(d, "Test earthwork")


def test_error_check_knows_plugs_and_quotes_changed_after_use():
    d = _doc()
    bidday.apply_quote(d, "Test earthwork", "Test Sub B")
    rules = [f["rule"] for f in checks.run(d)]
    assert rules.count("bid_plug") == 1
    assert "bid_stale" not in rules
    s = bidday.load(d, "Test earthwork")
    s["bidders"][1]["prices"]["1"] = "9500"        # B revised a price
    bidday.save(d, s)
    stale = [f for f in checks.run(d) if f["rule"] == "bid_stale"]
    assert len(stale) == 1 and "Test Sub B" in stale[0]["message"]
    # a bid line deleted by hand is reported too
    bidday.apply_quote(d, "Test earthwork", "Test Sub B")
    lid = _bid_lines(d)[0]["id"]
    EL.write(d, [ln for ln in EL.read(d) if ln["id"] != lid])
    assert any("no longer in the estimate" in f["message"]
               for f in checks.run(d) if f["rule"] == "bid_stale")


def test_auto_pick_reported_stale_when_lowest_complete_changes():
    d = _doc()
    bidday.apply_quote(d, "Test earthwork")           # A is lowest complete
    s = bidday.load(d, "Test earthwork")
    s["bidders"][1]["prices"]["2"] = "50000"          # B now complete, lower
    s["bidders"][1]["excluded"] = []
    bidday.save(d, s)
    msg = [f["message"] for f in checks.run(d) if f["rule"] == "bid_stale"]
    assert any("Test Sub B" in m and "lowest complete" in m for m in msg)


def test_unplugged_item_goes_in_at_zero_and_is_an_error():
    d = blank_doc()
    bidday.save(d, bidday.new_sheet("Test paving", [
        {"id": "1", "desc": "Test base", "unit": "SY", "qty": "100"},
        {"id": "2", "desc": "Test striping", "unit": "LS", "qty": "1"}],
        [{"name": "Test Paver", "prices": {"1": "2500"}}]))
    res = bidday.apply_quote(d, "Test paving")       # only bidder, no plug
    assert res["missing"] == ["2"]
    f = [x for x in checks.run(d) if x["item"] == "Test striping"]
    assert {x["rule"] for x in f} == {"no_cost"}
    assert items.collect(d)["total"] == D("2500.00")


def test_supplier_quote_goes_in_as_material_and_bad_package_refused():
    d = blank_doc()
    bidday.save(d, bidday.new_sheet("Test pipe", [
        {"id": "1", "desc": "Test 8 in pipe", "unit": "LF", "qty": "300"}],
        [{"name": "Test Supply", "kind": "supplier",
          "prices": {"1": "3000"}}]))
    bidday.apply_quote(d, "Test pipe")
    ln = EL.priced(d)[0]
    assert ln["ext"]["mat"] == D("3000.00") and ln["kind"] == "Material"
    with pytest.raises(bidday.BidDayError):
        bidday.apply_quote(d, "nope")
    with pytest.raises(bidday.BidDayError):
        bidday.apply_quote(d, "Test pipe", "Nobody")


def test_amount_that_does_not_divide_evenly_keeps_the_quoted_total():
    d = blank_doc()
    bidday.save(d, bidday.new_sheet("Test odd", [
        {"id": "1", "desc": "Test odd item", "unit": "LF", "qty": "30000"}],
        [{"name": "Test Odd Sub", "prices": {"1": "100"}}]))
    bidday.apply_quote(d, "Test odd")
    p = EL.priced(d)[0]
    assert p["total"] == D("100.00")
    assert "30000 LF" in EL.read(d)[0]["note"]   # 100/30000 rounds off
