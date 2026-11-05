"""Concrete, brick / block and roofing calculators (Estimate tab)."""
import math

import pytest

from app import calculators as calc


def test_slab_yards_and_trucks_no_bags():
    r = calc.concrete("slab", 1, 5, length=20, width=20, thick_in=4)
    assert r["cf"] == pytest.approx(133.333, abs=0.001)
    assert r["cy"] == pytest.approx(4.938, abs=0.001)
    assert r["cy_with_waste"] == pytest.approx(5.185, abs=0.001)
    assert r["order_cy"] == 5.25
    assert r["trucks"] == 1
    assert "bags" not in r                 # concrete is in CY (Jon, Oct 22)
    # an older caller's bag size is ignored
    assert calc.concrete("slab", 1, 5, bag_lb=80, length=20, width=20,
                         thick_in=4)["order_cy"] == 5.25


def test_other_shapes():
    assert calc.concrete_cf("footing", length=100, width_in=20,
                            depth_in=10) == pytest.approx(138.889, abs=0.001)
    assert calc.concrete_cf("wall", length=40, height=8,
                            thick_in=8) == pytest.approx(213.333, abs=0.001)
    assert calc.concrete_cf("column", dia_in=12, height=10) == \
        pytest.approx(math.pi * 0.25 * 10)
    assert calc.concrete_cf("pier", side_in=16, height=4) == \
        pytest.approx((16 / 12) ** 2 * 4)
    # 3 steps, 4 ft wide, 7" rise, 11" run: 1+2+3 risers
    assert calc.concrete_cf("steps", width=4, rise_in=7, run_in=11,
                            count=3) == pytest.approx(4 * 11 / 12 * 7 / 12 * 6)
    r = calc.concrete("column", 6, 0, dia_in=12, height=10)
    assert r["cy"] == pytest.approx(6 * math.pi * 0.25 * 10 / 27)


def test_bad_input_is_refused():
    with pytest.raises(ValueError):
        calc.concrete("slab", 1, 5, length=-1, width=2, thick_in=4)
    with pytest.raises(ValueError):
        calc.concrete("slab", 1, 5, length="abc", width=2, thick_in=4)
    with pytest.raises(ValueError):
        calc.concrete_cf("dome")


def test_units_per_square_foot():
    assert calc.units_per_sf("Modular brick") == pytest.approx(6.857, abs=0.001)
    assert calc.units_per_sf("8x8x16 CMU") == pytest.approx(1.125)


def test_brick_wall_less_openings():
    r = calc.masonry(40, 8, "Modular brick", openings_sf=40, waste_pct=5)
    assert r["net_sf"] == 280
    assert r["units"] == pytest.approx(280 * 144 / (8 * 2.625))
    assert r["units_with_waste"] == math.ceil(r["units"] * 1.05)
    assert r["mortar_bags"] == math.ceil(r["units_with_waste"] / 1000 * 7)
    assert r["kind"] == "brick"


def test_block_wall_by_area():
    r = calc.masonry(0, 0, "8x8x16 CMU", area_sf=1000, waste_pct=0)
    assert r["units_with_waste"] == 1125
    assert r["mortar_bags"] == math.ceil(1.125 * 33)
    assert r["kind"] == "cmu"
    assert calc.masonry(10, 10, openings_sf=500)["units_with_waste"] == 0


def test_dialog_and_menu(qapp=None):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app.calculators_ui import CalculatorDialog
    d = CalculatorDialog(None, None, 0)
    c = d.concrete
    c.inputs["length"].setValue(20)
    c.inputs["width"].setValue(20)
    c.inputs["thick_in"].setValue(4)
    assert "5.19 cubic yards (CY)" in c.out.text()
    assert "bag" not in c.out.text().lower()
    t = d.copy()
    assert t.startswith("Concrete - Slab") and "5.25 CY" in t
    assert "bag" not in t.lower()
    d.tabs.setCurrentIndex(1)
    m = d.masonry
    m.unit.setCurrentText("8x8x16 CMU")
    m.area.setValue(1000)
    m.waste.setValue(0)
    assert "1,125 8x8x16 CMU" in m.out.text()
    assert m.mortar.value() == 33
    # solid grouted by default for CMU: 1,000 sf x 0.30 = 300 cf = 11.11 CY
    assert m.grout_spacing.currentData() == "solid"
    assert "Grout: <b>12.22 CY</b>" in m.out.text()     # +10% waste
    m.grout_spacing.setCurrentIndex(m.grout_spacing.findData(48))
    assert "Grout:" in m.out.text() and "CY" in d.copy()
    m.unit.setCurrentText("Modular brick")
    assert "Grout" not in m.out.text()
    assert not m.grout_spacing.isEnabled()
    d.tabs.setCurrentIndex(2)
    rf = d.roofing
    rf.plan.setValue(2000)
    rf.pitch.setValue(6)
    rf.waste.setValue(10)
    rf.eave.setValue(120)
    rf.rake.setValue(80)
    rf.ridge.setValue(50)
    assert "24.60 squares" in rf.out.text()
    assert "74 bundles" in rf.out.text()
    assert d.copy().startswith("Roofing - Shingles: 24.60 squares")
    d.close()


def test_cmu_grout_cy():
    # 8 in CMU solid grouted: 0.30 cf/sf (published wall tables)
    g = calc.grout(1000, "8x8x16 CMU", "solid", 0, 0)
    assert g["cf"] == pytest.approx(300.0)
    assert g["cy"] == pytest.approx(300 / 27)
    assert g["order_cy"] == 11.25
    # cells at 48 in o.c.: 1/6 of solid; plus 100 ft of 8 in bond beam
    g = calc.grout(1000, "8x8x16 CMU", 48, 100, 0)
    assert g["cells_cf"] == pytest.approx(50.0)
    assert g["bond_beam_cf"] == pytest.approx(100 * 0.30 * 8 / 12)
    assert g["cy"] == pytest.approx(70 / 27)
    # 16 in o.c. is half of solid; width sets the rate
    assert calc.grout(100, "8x8x16 CMU", 16, 0, 0)["cf"] == \
        pytest.approx(15.0)
    assert calc.grout(100, "12x8x16 CMU", "solid", 0, 0)["cf"] == \
        pytest.approx(51.0)
    assert calc.grout(100, "8x8x16 CMU", "none", 0, 0)["cf"] == 0
    with pytest.raises(ValueError):
        calc.grout(100, "8x8x16 CMU", 4)
    # waste
    assert calc.grout(1000, "8x8x16 CMU", "solid", 0, 10)["cy_with_waste"] \
        == pytest.approx(330 / 27)
    # masonry() carries it for CMU only
    assert calc.masonry(0, 0, "Modular brick", area_sf=100)["grout"] is None
    r = calc.masonry(0, 0, "8x8x16 CMU", area_sf=100, grout_spacing="solid",
                     grout_waste_pct=0)
    assert r["grout"]["cf"] == pytest.approx(30.0)


def test_roofing_squares_and_order_lines():
    r = calc.roofing(2000, 6, 10, eave_lf=120, rake_lf=80, ridge_lf=50,
                     hip_lf=10, valley_lf=20)
    f = math.sqrt(1 + 0.25)
    assert r["factor"] == pytest.approx(f)
    assert r["sloped_sf"] == pytest.approx(2000 * f)
    assert r["squares_with_waste"] == pytest.approx(20 * f * 1.1)
    assert r["bundles"] == math.ceil(20 * f * 1.1 * 3)
    assert r["order_squares"] == pytest.approx(
        math.ceil(20 * f * 1.1 * 3) / 3)
    assert r["underlay_rolls"] == 3
    assert r["ice_water_rolls"] == math.ceil((120 + 20) / 66)
    assert r["starter_bundles"] == 2 and r["starter_lf"] == 200
    assert r["ridge_bundles"] == 2 and r["ridge_lf"] == 60
    assert r["drip_pieces"] == math.ceil(200 * 1.05 / 10)
    # a sloped area typed directly wins; flat roof factor 1
    assert calc.roofing(0, 0, 0, sloped_sf=1500)["squares"] == 15
    # metal / membrane: squares and trim, no shingle bundles
    m = calc.roofing(2000, 1, 5, kind="Metal", eave_lf=100)
    assert m["bundles"] == 0 and m["starter_bundles"] == 0
    assert m["drip_pieces"] == math.ceil(105 / 10)
    # rates are editable; bad ones refused
    assert calc.roofing(1000, 0, 0, bundles_per_square=4)["bundles"] == 40
    with pytest.raises(ValueError):
        calc.roofing(1000, 30)
    # hard cap 12:12 (Jon, Oct 23)
    assert calc.roofing(1000, 12)["squares"] > 0
    with pytest.raises(ValueError):
        calc.roofing(1000, 12.5)
    with pytest.raises(ValueError):
        calc.roofing(1000, 6, nails=3)
