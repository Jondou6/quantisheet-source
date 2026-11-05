"""r36 v2 step 1b: Estimate vs Actual, the Material Order List and the
Customer Quote cover EVERY priced item - added lines, takeoff groups
priced by a plain unit cost, assembly parts and civil crew activities.
Made-up data only."""
import os
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import assemblies, heavy, settings                   # noqa: E402
from app.estimating import actuals, items, materials, quotes  # noqa: E402
from test_r36_items import LIB, _doc                          # noqa: E402

D = Decimal


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


def test_material_list_has_takeoff_assembly_civil_and_lines():
    d, cj = _doc()
    rows = {r["desc"]: r for r in materials.collect(d, cj, LIB)}
    assert set(rows) == {"Test floor", "Test pavers", "Test anchor",
                         "Test 8 in pipe"}
    assert rows["Test floor"]["qty"] == D("110.0000")
    assert rows["Test floor"]["cost"] == D("440.00")
    assert rows["Test floor"]["sources"] == ["takeoff group"]
    assert rows["Test 8 in pipe"]["qty"] == D("400")
    assert rows["Test 8 in pipe"]["sources"] == ["civil Test lay pipe"]
    # no doc job given: lines, takeoff and assemblies still there
    assert "Test floor" in {r["desc"] for r in materials.collect(d)}


def test_takeoff_group_without_cost_type_is_left_off_the_list():
    # v2 step 4: no longer counted as material (test_r36_no_cost_type)
    from app import estimate
    from estimate_helpers import area, blank_doc
    d = blank_doc()
    area(d, "Test tile", 10, 10)
    estimate.set_price(d, "Test tile", "area", "sq ft", unit_cost=3)
    assert materials.collect(d) == []
    assert [i["desc"] for i in materials.no_cost_type(d)] == ["Test tile"]


def test_civil_material_quote_goes_under_its_vendor():
    d, cj = _doc()
    a = cj["activities"][0]
    heavy.add_quote(a, "Test Pipe Supply", "9", kind="material", per="unit")
    heavy.use_quote(a, a["quotes"][0]["id"])
    order = materials.order_list(d, job=cj, lib=LIB)
    assert "Test Pipe Supply" in order
    assert order["Test Pipe Supply"][0]["cost"] == D("3600.00")


def test_actuals_cover_every_item_and_record_by_item_id():
    d, cj = _doc()
    est = items.collect(d, cj, LIB)
    floor = items.takeoff_id("Test floor", "area", "sq ft")
    pipe = next(i["id"] for i in est["items"] if i["kind"] == "civil")
    actuals.record(d, floor, qty="120", cost="500", job=cj, lib=LIB)
    actuals.record(d, "assembly:Test patio", cost="180", job=cj, lib=LIB)
    actuals.record(d, pipe, cost="6000", job=cj, lib=LIB)
    res = actuals.compare(d, cj, LIB)
    rows = {r["id"]: r for r in res["rows"]}
    assert set(rows) == {i["id"] for i in est["items"]}
    assert rows[floor]["cost_var"] == D("60.00")
    assert rows[floor]["kind"] == "takeoff"
    assert rows["assembly:Test patio"]["cost_var"] == D("-20.00")
    assert rows[pipe]["act_cost"] == D("6000.00")
    assert res["totals"]["est_cost"] == est["total"]
    assert res["totals"]["lines_with_actuals"] == 3
    with pytest.raises(actuals.ActualsError):
        actuals.record(d, "takeoff:nothing", cost="1")
    # a civil id is only known when the civil job is given
    with pytest.raises(actuals.ActualsError):
        actuals.record(d, pipe, cost="1")


def test_quote_prices_every_item_not_only_added_lines():
    d, cj = _doc()
    est = items.collect(d, cj, LIB)
    q = quotes.compute(d, dict(quotes.blank(), pct="10"), job=cj, lib=LIB)
    ids = {ln["id"] for ln in q["base"]["lines"]}
    assert ids == {i["id"] for i in est["items"]}
    assert q["base"]["cost"] == est["total"]
    assert q["selected"]["total"] == sum(
        (ln["price"] for ln in q["base"]["lines"]), D("0.00"))
