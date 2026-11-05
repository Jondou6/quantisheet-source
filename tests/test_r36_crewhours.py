"""r36 B1: crew hours and cost per pay item from your own crews and
production rates (heavy.py prices each activity: hours = qty / rate).
Made-up crews and rates only."""
import os
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import heavy, settings                        # noqa: E402
from app.estimating import crewhours                   # noqa: E402

D = Decimal
LIB = {"equipment": {"EXC": {"code": "EXC", "use": "own", "own_hr": "50",
                             "op_hr": "0", "fuel_gph": "0"}},
       "labor": {"LAB": {"code": "LAB", "base": "30", "fringe": "0"}},
       "crews": {"PIPE": {"labor": [["LAB", 2]], "equipment": [["EXC", 1]]},
                 "GRADE": {"labor": [["LAB", 1]], "equipment": []}},
       "settings": {"fuel": 0}}


@pytest.fixture(autouse=True)
def _cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "_cache", {})


def _job():
    job = heavy.blank()
    job["pay_items"] = [
        {"no": "10", "desc": "Test 8 in sewer", "unit": "LF",
         "owner_qty": "400", "weight": "1"},
        {"no": "20", "desc": "Test fine grade", "unit": "SY",
         "owner_qty": "1000", "weight": "1"}]
    heavy.add_activity(job, "Test lay pipe", qty=400, unit="LF", crew="PIPE",
                       rate=40, pay_item="10")            # 10 crew hours
    heavy.add_activity(job, "Test backfill", qty=400, unit="LF", crew="PIPE",
                       rate=80, pay_item="10")            # 5 crew hours
    heavy.add_activity(job, "Test grade", qty=1000, unit="SY", crew="GRADE",
                       rate=10, per="day", pay_item="20")  # 1/hr -> 1000 h
    heavy.add_activity(job, "Test loose", qty=10, unit="EA", crew="GRADE",
                       rate=5)                             # no pay item
    return job


def test_hours_and_cost_per_pay_item():
    rows = crewhours.by_pay_item(_job(), LIB)
    by = {r["no"]: r for r in rows["items"]}
    assert by["10"]["hours"] == D("15.00")
    assert by["10"]["crews"] == {"PIPE": D("15.00")}
    # hours x crew rate: PIPE costs its labor and equipment each hour
    costs = {a["name"]: heavy.activity_cost(a, LIB, _job())
             for a in _job()["activities"]}
    assert by["10"]["direct"] == costs["Test lay pipe"]["total"] + \
        costs["Test backfill"]["total"]
    assert by["10"]["unit_cost"] == (by["10"]["direct"] / 400).quantize(
        D("0.01"))
    assert by["20"]["hours"] == D("1000.00")
    assert by["20"]["crew_days"] == D("100.00")          # 10 h a day
    assert rows["unassigned"]["hours"] == D("2.00")
    assert rows["total_hours"] == D("1017.00")


def test_by_crew_totals_and_export(tmp_path):
    job = _job()
    crews = crewhours.by_crew(job, LIB)
    assert crews["PIPE"]["hours"] == D("15.00")
    assert crews["GRADE"]["hours"] == D("1002.00")
    p = crewhours.export(crewhours.by_pay_item(job, LIB),
                         str(tmp_path / "hours.csv"))
    text = open(p, encoding="utf-8").read()
    assert "Crew hours" in text and "Test 8 in sewer" in text


def test_problem_activities_are_listed_not_hidden():
    job = _job()
    heavy.add_activity(job, "Test no rate", qty=10, unit="LF", crew="PIPE",
                       rate=0, pay_item="10")
    rows = crewhours.by_pay_item(job, LIB)
    assert any("Test no rate" in p for p in rows["problems"])
