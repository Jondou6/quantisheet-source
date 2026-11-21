"""Earthwork, aggregate / asphalt, drywall and paint calculators (Nov 20).
Made-up sizes; the defaults are the usual rules of thumb."""
import os
import sys

import fitz
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import estimate_lines as el, sitecalc as s  # noqa: E402

try:
    from test_gui import win, qapp  # noqa: F401,E402
except Exception:                                         # noqa: BLE001
    pass


def test_excavation_and_trench():
    e = s.excavation(100, 54, 3)                    # 600 CY bank
    assert e["bank_cy"] == 600 and e["loose_cy"] == 750
    assert e["compacted_cy"] == 540 and e["loads"] == 63
    assert s.excavation(bank_cy=27)["bank_cy"] == 27
    t = s.trench(100, 6, 3, side_slope=1, pipe_in=0, bedding_in=6)
    assert t["top_width_ft"] == 15 and t["excavation_cy"] == 200
    assert abs(t["bedding_cy"] - 3 * 0.5 * 100 / 27) < 1e-9
    with pytest.raises(ValueError):
        s.trench(100, 6, 3, truck_cy=0)


def test_material_drywall_paint():
    m = s.material_tons(2700, 12, 1.5, waste_pct=0)  # 100 CY
    assert m["cy"] == 100 and m["tons"] == 150
    d = s.drywall(4000, 1000, 0, "4 x 8", waste_pct=0)
    assert d["boards"] == 157 and d["tape_lf"] == 1850   # 5000/32, 5 x 370
    assert d["compound_lb"] == 700 and d["screws"] == 5000
    with pytest.raises(ValueError):
        s.drywall(100, board="5 x 9")
    p = s.paint(3500, 2, 350, primer_coats=1, primer_sf_per_gal=350,
                waste_pct=0)
    assert (p["finish_gal"], p["finish_pails"], p["finish_extra"]) == \
        (20, 4, 0)
    assert p["primer_gal"] == 10


def test_tabs_and_add_to_estimate(win, tmp_path):
    dd = fitz.open()
    dd.new_page()
    path = tmp_path / "job.pdf"
    dd.save(path)
    dd.close()
    assert win.open_path(str(path))
    d = win.calculators(9, show=False)
    assert d.tabs.count() == 13
    ew = d.earth
    ew.length.setValue(100)
    ew.wide.setValue(54)
    ew.depth.setValue(3)
    assert "600.00 CY bank" in ew.out.text()
    rows = [el.get(win._view.doc, i) for i in d.add_to_estimate()]
    assert [r["code"][:8] for r in rows] == ["31 23 16", "31 23 16"]
    ew.use_takeoff("length", "ft", 200)
    assert ew.kind.currentData() == "trench"
    d.tabs.setCurrentIndex(10)
    ag = d.aggregate
    ag.mat.setCurrentText("Asphalt (hot mix)")
    assert ag.density.value() == 2.0
    d.tabs.setCurrentIndex(11)
    assert "boards" in d.drywall.out.text()
    assert len(d.add_to_estimate()) == 4
    d.tabs.setCurrentIndex(12)
    assert "gal finish" in d.paint.out.text()
    assert d.copy().startswith("Paint - ")
