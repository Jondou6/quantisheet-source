"""r36 C: planning-level parametric estimator (wastewater and similar) -
you define the processes, their sizing parameters and your own cost
curves (cost = a x X^b + c); it totals capital and O&M with contingency
and engineering. No cost curve data ships: these numbers are synthetic."""
import os
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import settings                               # noqa: E402
from app.estimating import _io, parametric as PM       # noqa: E402

D = Decimal


@pytest.fixture(autouse=True)
def _cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "_cache", {})


def _model():
    m = PM.blank("Test plant")
    m["design"] = {"Q": "2"}                     # synthetic: 2 flow units
    m["processes"] = [
        {"name": "Test screening", "params": {"X": "Q"},
         "capital": {"a": "100000", "b": "0.5", "c": "0"},
         "om": {"a": "1000", "b": "1", "c": "500"}},
        {"name": "Test basins", "params": {"X": "Q * 1.5"}, "count": "2",
         "capital": {"a": "200000", "b": "1", "c": "0", "min": "1",
                     "max": "2"},
         "om": {"a": "0", "b": "1", "c": "0"}}]
    m.update(contingency_pct="20", engineering_pct="10")
    return m


def test_curves_and_totals():
    r = PM.evaluate(_model())
    by = {x["name"]: x for x in r["processes"]}
    # 100000 x 2^0.5 = 141421.36
    assert by["Test screening"]["capital"] == D("141421.36")
    assert by["Test screening"]["om"] == D("2500.00")
    # X = 3 (outside your curve's 1-2 range: warned), 2 units
    assert by["Test basins"]["x"] == D("3")
    assert by["Test basins"]["capital"] == D("1200000.00")
    assert any("Test basins" in w and "range" in w for w in r["warnings"])
    t = r["totals"]
    assert t["capital_subtotal"] == D("1341421.36")
    assert t["contingency"] == D("268284.27")
    assert t["engineering"] == D("160970.56")    # on subtotal + contingency
    assert t["capital_total"] == D("1770676.19")
    assert t["om_annual"] == D("2500.00")


def test_present_worth_when_years_and_rate_given():
    m = _model()
    m.update(years="20", rate_pct="0")
    t = PM.evaluate(m)["totals"]
    assert t["om_present_worth"] == D("50000.00")
    assert t["present_worth"] == t["capital_total"] + D("50000.00")
    m.update(rate_pct="5")
    pw = PM.evaluate(m)["totals"]["om_present_worth"]
    assert D("31155") < pw < D("31157")          # 2500 x 12.4622


def test_bad_models_are_refused():
    m = _model()
    m["processes"][0]["params"]["X"] = "Q +"
    with pytest.raises(PM.ModelError):
        PM.evaluate(m)
    m = _model()
    m["processes"][0]["capital"]["a"] = "abc"
    with pytest.raises(PM.ModelError):
        PM.evaluate(m)
    m = _model()
    m["processes"][0]["params"]["X"] = "Q - 5"   # negative size
    with pytest.raises(PM.ModelError):
        PM.evaluate(m)


def test_save_load_and_export(tmp_path):
    m = _model()
    p = PM.save(m, str(tmp_path / "plant.json"))
    assert PM.load(p) == PM.validate(m)
    with pytest.raises(_io.PathError):
        PM.save(m, os.path.join(_io.APP_DIR, "data", "plant.json"))
    out = PM.export(PM.evaluate(m), str(tmp_path / "plant.csv"))
    assert "Capital total" in open(out, encoding="utf-8").read()


def test_blank_model_ships_no_curves():
    b = PM.blank("x")
    assert b["processes"] == [] and b["design"] == {}
    assert PM.evaluate(b)["totals"]["capital_total"] == D("0.00")
