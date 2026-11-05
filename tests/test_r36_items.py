"""r36 v2 step 1: one estimate object - every priced item of the drawing
in one list (added lines, takeoff groups priced by a plain unit cost,
assembly rows with their parts and civil crew activities), each with a
stable id, so actuals, material lists and quotes cover all of them.
Made-up data only."""
import os
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import assemblies, estimate, estimate_lines as EL, heavy, settings  # noqa: E402,E501
from app.estimating import items                              # noqa: E402
from estimate_helpers import area, blank_doc                  # noqa: E402

D = Decimal
LIB = {"equipment": {"EXC": {"code": "EXC", "use": "own", "own_hr": "50",
                             "op_hr": "0", "fuel_gph": "0"}},
       "labor": {"LAB": {"code": "LAB", "base": "30", "fringe": "0"}},
       "crews": {"PIPE": {"labor": [["LAB", 2]], "equipment": [["EXC", 1]]}},
       "settings": {"fuel": 0}}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


def _doc():
    d = blank_doc()
    area(d, "Test floor", 10, 10)                        # 100 sq ft
    estimate.set_price(d, "Test floor", "area", "sq ft", unit_cost=4,
                       waste=10, cost_type="Material")
    area(d, "Test paint", 10, 20, x0=300)                # 200 sq ft
    estimate.set_price(d, "Test paint", "area", "sq ft", unit_cost="1.5",
                       cost_type="Subcontract")
    area(d, "Test bare", 5, 5, x0=700)                   # not priced
    asm = {"name": "Test patio", "measure": "area", "trade": "Concrete",
           "parts": [{"name": "Test pavers", "unit": "ea",
                      "qty": "Area*4", "cost": 0.5, "labor": 0}]}
    job = assemblies.read_job(d)
    job["assemblies"]["Test patio"] = asm
    assemblies.write_job(d, job)
    area(d, "Test patio", 10, 10, y0=400)
    EL.add(d, [EL.new_line("Test anchor", 30, "ea", mat="1.10")])
    cj = heavy.blank()
    heavy.add_activity(cj, "Test lay pipe", qty=400, unit="LF", crew="PIPE",
                       rate=40, materials=[{"desc": "Test 8 in pipe",
                                            "qty_per": 1, "cost": "10",
                                            "unit": "LF"}])
    return d, cj


def test_every_kind_is_one_item_with_a_stable_id():
    d, cj = _doc()
    est = items.collect(d, cj, LIB)
    kinds = sorted(i["kind"] for i in est["items"])
    assert kinds == ["assembly", "civil", "line", "takeoff", "takeoff"]
    by = {i["desc"]: i for i in est["items"]}
    floor = by["Test floor"]
    assert floor["id"] == items.takeoff_id("Test floor", "area", "sq ft")
    assert floor["qty"] == D("110.0000") and floor["total"] == D("440.00")
    assert floor["parts"]["mat"] == D("440.00")
    assert by["Test paint"]["parts"]["sub"] == D("300.00")
    assert by["Test paint"]["materials"] == []
    patio = by["Test patio"]
    assert patio["id"] == "assembly:Test patio"
    assert patio["total"] == D("200.00")
    assert [m["desc"] for m in patio["materials"]] == ["Test pavers"]
    pipe = by["Test lay pipe"]
    assert pipe["id"].startswith("civil:") and pipe["hours"] == D("10.00")
    c = heavy.activity_cost(cj["activities"][0], LIB, cj)   # heavy prices it
    assert pipe["total"] == c["total"] and pipe["parts"]["mat"] == D("4000.00")
    assert pipe["parts"]["lab"] == c["labor"] and pipe["parts"]["eqp"] == D("500.00")
    assert pipe["materials"][0]["qty"] == D("400")
    assert by["Test anchor"]["kind"] == "line"
    assert est["total"] == sum((i["total"] for i in est["items"]), D("0"))
    assert "Test bare" not in by                       # unpriced group
    again = items.collect(d, cj, LIB)
    assert [i["id"] for i in again["items"]] == [i["id"] for i in
                                                 est["items"]]


def test_without_civil_job_and_without_doc():
    d, _cj = _doc()
    assert sorted(i["kind"] for i in items.collect(d)["items"]) == [
        "assembly", "line", "takeoff", "takeoff"]
    assert items.collect(None)["items"] == []


def test_blank_cost_type_is_not_counted_as_material():
    # v2 step 4 (was: counted as material, "assumed")
    d = blank_doc()
    area(d, "Test tile", 10, 10)
    estimate.set_price(d, "Test tile", "area", "sq ft", unit_cost=3)
    it = items.collect(d)["items"][0]
    assert it["parts"]["mat"] == D("0.00") and it["total"] == D("300.00")
    assert it["materials"] == [] and it["no_cost_type"] is True
