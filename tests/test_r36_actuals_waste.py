"""r36 v2 step 7 (G3.1): Estimate vs Actual knows about waste. Each row
shows the measured quantity, the planned waste %, the quantity with waste,
the actual (purchased) quantity, the installed quantity and the actual
waste %, and splits the cost variance into a quantity part and a price
part. Old saved actuals still read; old export columns are unchanged.
Made-up data only."""
import csv
import json
import os
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import assemblies, embfiles, estimate, estimate_lines as EL, settings  # noqa
from app.estimating import actuals, costlink, items                 # noqa: E402
from estimate_helpers import area, blank_doc                        # noqa: E402

D = Decimal


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


def _row(res, desc):
    return next(r for r in res["rows"] if r["desc"].startswith(desc))


def _floor(waste=10):
    d = blank_doc()
    area(d, "Test floor", 10, 10)                          # 100 sq ft
    estimate.set_price(d, "Test floor", "area", "sq ft", unit_cost=4,
                       waste=waste, cost_type="Material")
    return d


def test_takeoff_row_has_measured_waste_and_gross_qty():
    r = _row(actuals.compare(_floor()), "Test floor")
    assert r["net_qty"] == D("100") and r["waste_pct"] == D("10")
    assert r["est_qty"] == D("110")                 # unchanged: with waste
    assert r["waste_basis"] == "takeoff"
    assert r["act_installed"] is None and r["act_waste_pct"] is None


def test_actual_waste_and_variance_split():
    d = _floor()
    iid = items.takeoff_id("Test floor", "area", "sq ft")
    actuals.record(d, iid, qty="105", cost="441", installed="100")
    r = _row(actuals.compare(d), "Test floor")
    assert r["act_qty"] == D("105") and r["act_installed"] == D("100")
    assert r["act_waste_pct"] == D("5.0")            # 105 / 100 - 1
    assert r["qty_var_cost"] == D("-20.00")          # (105 - 110) x 4
    assert r["price_var"] == D("21.00")              # 441 - 105 x 4
    assert r["qty_var_cost"] + r["price_var"] == r["cost_var"] == D("1.00")


def test_zero_waste_and_missing_installed():
    d = _floor(waste=0)
    iid = items.takeoff_id("Test floor", "area", "sq ft")
    actuals.record(d, iid, qty="100", cost="400")
    r = _row(actuals.compare(d), "Test floor")
    assert r["waste_pct"] == D("0") and r["net_qty"] == r["est_qty"]
    assert r["act_waste_pct"] is None                # installed not given
    assert r["qty_var_cost"] == D("0.00") and r["price_var"] == D("0.00")


def test_formula_line_and_assembly_waste():
    d = blank_doc()
    area(d, "Test slab", 10, 10)
    costlink.link_item(d, {"desc": "Test vapor barrier", "unit": "sf",
                           "mat": "0.10", "cost_type": "Material"},
                       ("Test slab", "area", "sq ft"), formula="qty * 1.05")
    annotate_line(d)
    assemblies.set_job_assembly(d, {
        "name": "Test wall", "measure": "length", "props": {"Waste": 12},
        "parts": [{"name": "Board", "unit": "sf",
                   "qty": "Length*10*(1+Waste/100)", "cost": 1}]})
    res = actuals.compare(d)
    vb = _row(res, "Test vapor barrier")
    assert vb["waste_basis"] == "in formula" and vb["waste_pct"] is None
    w = _row(res, "Test wall")
    assert w["waste_basis"] == "assembly" and w["waste_pct"] == D("12")


def annotate_line(d):
    from app import annotate
    annotate.apply_op(d, annotate.new_op(
        "add_line", 0, pts=[[100, 500], [300, 500]],
        measure={"type": "length", "value": 20, "unit": "ft",
                 "group": "Test wall"}))


def test_old_saved_actuals_still_read():
    d = _floor()
    iid = items.takeoff_id("Test floor", "area", "sq ft")
    embfiles.put(d, actuals.FILE, json.dumps({"version": 1, "lines": {
        iid: {"qty": "108", "cost": "430", "note": "", "at": "2026-01-01"}}
    }).encode(), "test")
    r = _row(actuals.compare(d), "Test floor")
    assert r["act_qty"] == D("108") and r["act_installed"] is None


def test_export_keeps_old_columns_and_adds_new_ones(tmp_path):
    d = _floor()
    iid = items.takeoff_id("Test floor", "area", "sq ft")
    actuals.record(d, iid, qty="105", cost="441", installed="100")
    p = tmp_path / "e.csv"
    actuals.export(actuals.compare(d), str(p))
    rows = list(csv.reader(open(p, encoding="utf-8-sig")))
    old = ["Kind", "Code", "Description", "Unit", "Estimate qty",
           "Actual qty", "Estimate cost", "Actual cost", "Variance $",
           "Variance %", "Estimate unit cost", "Actual unit cost", "Note"]
    assert rows[0][:len(old)] == old
    assert rows[0][len(old):] == ["Measured qty", "Waste % planned",
                                  "Installed qty", "Waste % actual",
                                  "Quantity variance $", "Price variance $",
                                  "Item id"]
    r = dict(zip(rows[0], rows[1]))
    assert r["Waste % actual"] == "5.0" and r["Item id"] == iid


def test_bad_installed_qty_is_refused():
    d = _floor()
    iid = items.takeoff_id("Test floor", "area", "sq ft")
    with pytest.raises(actuals.ActualsError):
        actuals.record(d, iid, qty="105", installed="lots")
