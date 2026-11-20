"""Calculators > Add to Estimate (Nov 20): each quantity tab's results go
onto the open drawing's estimate as lines to price. Made-up sizes."""
import os
import sys

import fitz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import estimate_lines as el  # noqa: E402

try:
    from test_gui import win, qapp  # noqa: F401,E402
except Exception:                                         # noqa: BLE001
    pass


def _open(win, tmp_path):
    d = fitz.open()
    d.new_page()
    p = tmp_path / "job.pdf"
    d.save(p)
    d.close()
    assert win.open_path(str(p))


def test_add_lines_from_each_quantity_tab(win, tmp_path):
    _open(win, tmp_path)
    d = win.calculators(0, show=False)
    c = d.concrete
    c.inputs["length"].setValue(20)
    c.inputs["width"].setValue(20)
    c.inputs["thick_in"].setValue(4)
    ids = d.add_to_estimate()
    ln = el.get(win._view.doc, ids[0])
    assert ln["unit"] == "cy" and ln["code"].startswith("03 30 00")
    assert float(ln["qty"]) == 5.19 and ln["source"] == "Calculators"
    d.tabs.setCurrentIndex(1)
    d.masonry.unit.setCurrentText("8x8x16 CMU")
    d.masonry.area.setValue(1000)
    d.masonry.waste.setValue(0)
    got = [el.get(win._view.doc, i) for i in d.add_to_estimate()]
    assert [g["unit"] for g in got] == ["ea", "bag", "ton", "cy"]
    assert float(got[0]["qty"]) == 1125
    d.tabs.setCurrentIndex(3)
    d.rebar.wide.setValue(20)
    d.rebar.length.setValue(20)
    d.rebar.waste.setValue(0)
    r = el.get(win._view.doc, d.add_to_estimate()[0])
    assert r["unit"] == "lb" and float(r["qty"]) == 521.04   # 780 x .668
    d.tabs.setCurrentIndex(7)
    st = [el.get(win._view.doc, i) for i in d.add_to_estimate()]
    assert st[0]["unit"] == "ea" and st[1]["unit"] == "lf"
    d.tabs.setCurrentIndex(8)
    d.steel.list.setPlainText("W12x26, 20, 5")
    d.steel.extra.setValue(0)
    s = el.get(win._view.doc, d.add_to_estimate()[0])
    assert s["unit"] == "ton" and float(s["qty"]) == 1.3
    assert len(el.read(win._view.doc)) == 1 + 4 + 1 + 3 + 1


def test_checks_and_no_drawing_add_nothing(win, tmp_path):
    from app.calculators_ui import CalculatorDialog
    d = CalculatorDialog(None, None, 0)
    assert not d.add_btn.isEnabled() and d.add_to_estimate() == []
    _open(win, tmp_path)
    d = win.calculators(4, show=False)          # Beam: a check
    assert not d.add_btn.isEnabled() and d.add_to_estimate() == []
    d.tabs.setCurrentIndex(6)                   # Footing: concrete
    assert d.add_btn.isEnabled()
    f = el.get(win._view.doc, d.add_to_estimate()[0])
    assert f["unit"] == "cy" and "preliminary" in f["desc"]
