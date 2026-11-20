"""Wood Sheathing Helper (Nov 19): span ratings by use and spacing, sheets
for an area, and an estimate line that follows the area. Made-up areas."""
import os
import sys

import fitz
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import estimate_lines as el, sheathing as sh  # noqa: E402
from estimate_helpers import area  # noqa: E402

try:
    from test_gui import win, qapp  # noqa: F401,E402
except Exception:                                         # noqa: BLE001
    pass


@pytest.mark.parametrize("use,spacing,rating", [
    ("roof", 16, "24/0"), ("roof", 24, "24/0"), ("roof", 32, "32/16"),
    ("roof", 48, "48/24"), ("subfloor", 16, "24/16"),
    ("subfloor", 19.2, "40/20"), ("subfloor", 24, "48/24"),
    ("single-layer floor", 16, "16 oc"), ("single-layer floor", 24, "24 oc"),
    ("wall", 16, "16/0 or more"), ("wall", 24, "24/0 or more")])
def test_smallest_rating_that_covers_the_spacing(use, spacing, rating):
    p = sh.pick(use, spacing)
    assert p["rating"] == rating and p["thickness"]
    assert "E30" in p["source"]


def test_out_of_range_and_bad_input():
    for use, s in (("roof", 60), ("subfloor", 32), ("wall", 32)):
        with pytest.raises(sh.SheathingError):
            sh.pick(use, s)
    with pytest.raises(sh.SheathingError):
        sh.pick("deck", 16)
    with pytest.raises(sh.SheathingError):
        sh.pick("roof", 0)


def test_sheets_and_formula():
    assert sh.sheets(1000, 10) == 35            # 1100 / 32 = 34.4 -> 35
    assert sh.sheets(320, 0) == 10              # exact
    assert sh.sheets(0) == 0
    assert sh.formula(10) == "ceil(qty * 1.1 / 32)"
    p = sh.pick("roof", 24)
    assert sh.description(p).startswith("APA Rated Sheathing 24/0")


def test_window_adds_a_line_that_follows_the_area(win, tmp_path):
    d = fitz.open()
    d.new_page(width=1224, height=792)
    area(d, "Roof deck", 40, 25)                # 1000 SF, made up
    p = tmp_path / "roof.pdf"
    d.save(p)
    d.close()
    assert win.open_path(str(p))
    dlg = win.sheathing_helper(show=False)
    dlg.use.setCurrentText("roof")
    dlg.spacing.setCurrentText('24"')
    assert "35" in dlg.result.text()
    lid = dlg.add_to_estimate()
    ln = el.get(win._view.doc, lid)
    q = el.price(ln, el._groups(win._view.doc))["quantity"]
    assert q == 35
    assert ln["link"]["formula"] == "ceil(qty * 1.1 / 32)"
