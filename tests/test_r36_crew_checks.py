"""r36 v2 step 6 item 2: unrealistic crew output. Production rates far
outside the rest of the library and the EXAMPLE crews, crew hours per day
over a sane limit, crew-days under half a day or absurdly many, and a
$/unit far off the job's other lines - each explained in plain words.
Made-up crews and numbers only (wages are made up for the test)."""
import os
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import assemblies, estimate_lines as EL, heavy, settings  # noqa: E402
from app.estimating import checks                                  # noqa: E402
from estimate_helpers import blank_doc                             # noqa: E402


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


def _lib():
    return {"equipment": {}, "labor": {"LAB": {"code": "LAB", "base": 30}},
            "crews": {"PIPE": {"labor": [["LAB", 4]], "equipment": [],
                               "production": [{"what": "pipe", "rate": 25,
                                               "unit": "LF",
                                               "per": "hour"}]}},
            "settings": {}}


def _job(hpd=10):
    j = heavy.new_job("Test job") if hasattr(heavy, "new_job") else {
        "activities": [], "pay_items": [], "settings": {}}
    j.setdefault("settings", {})["hours_per_day"] = hpd
    j.setdefault("activities", [])
    j.setdefault("pay_items", [])
    return j


def _act(j, name, qty, unit, rate, per="hour", crew="PIPE"):
    return heavy.add_activity(j, name, qty=qty, unit=unit, crew=crew,
                              rate=rate, per=per)


def _rules(found, rule):
    return {f["item"]: f for f in found if f["rule"] == rule}


def test_a_reasonable_job_has_no_crew_flags():
    j = _job()
    _act(j, "Test 8 in pipe", 600, "LF", 28)
    _act(j, "Test 12 in pipe", 400, "LF", 20)
    found = checks.run(None, job=j, lib=_lib())
    assert not [f for f in found if f["rule"] in checks.CREW_RULES]


def test_production_far_outside_library_and_example_ranges():
    j = _job()
    _act(j, "Test fast pipe", 4000, "LF", 400)            # 400 LF / h
    _act(j, "Test slow pipe", 50, "LF", 1)                # 1 LF / h
    _act(j, "Test per day pipe", 600, "LF", 250, per="day")   # 25 / h: ok
    f = _rules(checks.run(None, job=j, lib=_lib()), "crew_rate")
    assert set(f) == {"Test fast pipe", "Test slow pipe"}
    m = f["Test fast pipe"]["message"]
    assert "400" in m and "LF" in m and "per crew hour" in m
    assert "EXAMPLE" in m or "library" in m
    assert f["Test fast pipe"]["severity"] == "warning"


def test_crew_hours_per_day_over_a_sane_limit():
    j = _job(hpd=16)
    _act(j, "Test pipe", 600, "LF", 25)
    f = _rules(checks.run(None, job=j, lib=_lib()), "crew_hours_day")
    assert len(f) == 1
    (x,) = f.values()
    assert "16" in x["message"] and "12" in x["message"]
    j = _job(hpd=30)
    _act(j, "Test pipe", 600, "LF", 25)
    (x,) = _rules(checks.run(None, job=j, lib=_lib()),
                  "crew_hours_day").values()
    assert x["severity"] == "error" and "24" in x["message"]


def test_days_below_half_a_day_or_absurdly_many():
    j = _job()
    _act(j, "Test tiny", 20, "LF", 25)             # 0.08 days
    _act(j, "Test huge", 200000, "LF", 25)         # 800 days
    _act(j, "Test fine", 500, "LF", 25)            # 2 days
    f = _rules(checks.run(None, job=j, lib=_lib()), "crew_days")
    assert set(f) == {"Test tiny", "Test huge"}
    assert "half a day" in f["Test tiny"]["message"]
    assert "800" in f["Test huge"]["message"]
    assert "year" in f["Test huge"]["message"]


def test_unit_cost_far_off_the_jobs_other_lines():
    d = blank_doc()
    EL.add(d, [EL.new_line("Test base A", 100, "sf", mat=3),
               EL.new_line("Test base B", 100, "sf", mat=4),
               EL.new_line("Test base C", 100, "sf", mat=5),
               EL.new_line("Test base D", 100, "sf", mat=4.5),
               EL.new_line("Test typo", 100, "sf", mat=400)])
    f = _rules(checks.run(d), "unit_cost_far")
    assert set(f) == {"Test typo"}
    m = f["Test typo"]["message"]
    assert "400" in m and "sf" in m.lower() and "median" in m


def test_unit_cost_needs_enough_lines_to_compare():
    d = blank_doc()
    EL.add(d, [EL.new_line("Test one", 100, "sf", mat=3),
               EL.new_line("Test two", 100, "sf", mat=400)])
    assert not _rules(checks.run(d), "unit_cost_far")


def test_crew_checks_are_read_only():
    j = _job()
    _act(j, "Test fast pipe", 4000, "LF", 400)
    before = repr(j)
    checks.run(None, job=j, lib=_lib())
    assert repr(j) == before
