"""r36 v2 step 1c: one path through the estimate on a synthetic drawing,
nothing typed twice - takeoff groups -> linked cost items with quantity
formulas -> crew hours -> error check -> quote with options -> material
order list -> estimate vs actual, every step reading the same estimate
(items.collect via flow.run). Drawing more takeoff changes every step.
Made-up items, crews and prices only."""
import os
from decimal import Decimal

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import assemblies, estimate, heavy, settings         # noqa: E402
from app.estimating import actuals, bidday, costlink, flow, quotes  # noqa: E402,E501
from estimate_helpers import area, blank_doc                  # noqa: E402

D = Decimal
LIB = {"equipment": {"TESTDOZER": {"code": "TESTDOZER", "use": "own",
                                   "own_hr": "60", "op_hr": "0",
                                   "fuel_gph": "0"}},
       "labor": {"TESTOP": {"code": "TESTOP", "base": "40", "fringe": "0"}},
       "crews": {"TESTGRADE": {"labor": [["TESTOP", 1]],
                               "equipment": [["TESTDOZER", 1]]}},
       "settings": {"fuel": 0}}
SLAB = {"name": "Test slab", "type": "area", "unit": "sq ft"}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


def _drawing():
    d = blank_doc()
    area(d, "Test slab", 20, 30)                         # 600 sq ft
    area(d, "Test site grading", 50, 40, x0=300)         # 2000 sq ft
    area(d, "Test tile", 10, 10, y0=400)                 # 100 sq ft
    # 1. takeoff -> your cost items, quantities by formula
    costlink.link_item(d, {"desc": "Test concrete", "unit": "cy",
                           "mat": "150", "code": "03 30 00"}, SLAB,
                       formula="ceil(qty * 0.5 / 12 / 27)")
    costlink.link_item(d, {"desc": "Test rebar mat", "unit": "ea",
                           "mat": "40"}, SLAB, formula="ceil(qty / 100)")
    # a takeoff group priced by a plain unit cost
    estimate.set_price(d, "Test tile", "area", "sq ft", unit_cost=8,
                       cost_type="Material", code="09 30 00")
    # 2. a civil activity tied to a takeoff group (quantity follows it)
    job = heavy.blank()
    job["pay_items"] = [{"no": "10", "desc": "Test grading", "unit": "sq ft",
                         "owner_qty": "2000", "weight": "1"}]
    heavy.add_activity(job, "Test fine grade", unit="sq ft",
                       crew="TESTGRADE", rate=500, pay_item="10",
                       group="Test site grading")
    heavy.write(d, job)
    # 3. a bid-day package
    bidday.save(d, bidday.new_sheet("Test roofing", [
        {"id": "1", "desc": "Test roof membrane", "unit": "SQ", "qty": "20"},
        {"id": "2", "desc": "Test roof flashing", "unit": "LF",
         "qty": "200"}],
        [{"name": "Test Roofer A", "prices": {"1": "12000", "2": "3000"}},
         {"name": "Test Roofer B", "prices": {"1": "11000"},
          "excluded": ["2"]}]))
    return d


def test_one_path_takeoff_to_actuals_without_retyping(tmp_path):
    d = _drawing()
    bidday.apply_quote(d, "Test roofing")               # lowest complete
    spec = dict(quotes.blank(), pct="10")
    tile = flow.item_id_of_group("Test tile", "area", "sq ft")
    spec["assign"] = {tile: "Better"}
    quotes.write(d, spec)
    r = flow.run(d, lib=LIB)
    est = r["estimate"]
    by = {i["desc"]: i for i in est["items"]}
    # takeoff -> linked items
    assert by["Test concrete"]["qty"] == D("1")         # 600*.5/12/27=0.93
    assert by["Test rebar mat"]["qty"] == D("6")
    assert by["Test tile"]["total"] == D("800.00")
    # civil activity took the takeoff quantity; crew hours from it
    assert by["Test fine grade"]["qty"] == D("2000")
    assert r["crew_hours"]["items"][0]["hours"] == D("4.00")
    # error check: nothing wrong on this drawing - except (v2 step 6) the
    # 4 h fine grade is under half a crew-day, an advisory warning
    assert [(f["rule"], f["item"], f["severity"]) for f in r["checks"]] == \
        [("crew_days", "Test fine grade", "warning")]
    # quote: every item, tile in the Better option
    q = r["quote"]
    assert {t["name"] for t in q["tiers"]} == {"Good", "Better", "Best"}
    better = next(t for t in q["tiers"] if t["name"] == "Better")
    assert [ln["id"] for ln in better["lines"]] == [tile]
    assert q["base"]["cost"] + better["cost"] == est["total"]
    # material list: linked items, tile, roofing is sub (not material)
    mats = {m["desc"] for rows in r["materials"].values() for m in rows}
    assert mats == {"Test concrete", "Test rebar mat", "Test tile"}
    # actuals: every item has a row
    assert {x["id"] for x in r["actuals"]["rows"]} == {i["id"] for i in
                                                       est["items"]}
    assert est["by_kind"]["line"] == D("150") + D("240") + D("15000.00")
    # draw more: everything follows, nothing retyped
    area(d, "Test slab", 20, 30, x0=700)                # 1200 sq ft
    area(d, "Test site grading", 50, 40, x0=300, y0=500)  # 4000 sq ft
    r2 = flow.run(d, lib=LIB)
    by2 = {i["desc"]: i for i in r2["estimate"]["items"]}
    assert by2["Test rebar mat"]["qty"] == D("12")
    assert by2["Test fine grade"]["qty"] == D("4000")
    assert r2["crew_hours"]["items"][0]["hours"] == D("8.00")
    # actuals on any item, saved with the drawing
    actuals.record(d, tile, cost="750", lib=LIB)
    p = str(tmp_path / "job.pdf")
    d.save(p)
    r3 = flow.run(fitz.open(p), lib=LIB)
    row = next(x for x in r3["actuals"]["rows"] if x["id"] == tile)
    assert row["cost_var"] == D("-50.00")
    assert r3["estimate"]["total"] == r2["estimate"]["total"]


def test_run_reports_problems_instead_of_hiding_them():
    d = _drawing()
    bidday.apply_quote(d, "Test roofing", "Test Roofer B")   # with a plug
    estimate.set_price(d, "Test slab", "area", "sq ft", unit_cost=9)
    r = flow.run(d, lib={"crews": {}, "labor": {}, "equipment": {},
                         "settings": {}})
    rules = {f["rule"] for f in r["checks"]}
    assert {"bid_plug", "double_priced", "missing_crew"} <= rules
    assert r["summary"]["errors"] >= 1
