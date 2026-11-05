"""Auto Takeoff run + review: pick item types, review lowest confidence
first, accept / reject / reassign, then commit only what was accepted."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import annotate, autotakeoff_review as atr         # noqa: E402
from test_autotakeoff import make_plan                       # noqa: E402
from test_autowalls import _plan as wall_plan                 # noqa: E402


def _sc(d):
    return annotate.read_scales(d)[0]


def test_item_type_picker_runs_only_selected():
    d = make_plan()
    c = atr.collect(d, 0, _sc(d), types={"rooms"})
    assert c and {x["type"] for x in c} == {"rooms"}
    names = {x["group"] for x in c}
    assert {"OFFICE", "STORAGE"} <= names
    office = [x for x in c if x["group"] == "OFFICE"][0]
    assert office["value"] == pytest.approx(300, rel=0.03)
    assert office["conf"] >= 0.9                       # matches its tag


def test_walls_doors_and_paint_from_height():
    d = wall_plan()
    c = atr.collect(d, 0, _sc(d), types={"walls", "doors", "paint"},
                    wall_height=9.0, paint_sides=2)
    walls = sum(x["value"] for x in c if x["type"] == "walls")
    paint = sum(x["value"] for x in c if x["type"] == "paint")
    assert walls == pytest.approx(61.33 + 11.33, abs=1.0)
    assert paint == pytest.approx(walls * 9 * 2, rel=0.01)
    assert any(x["type"] == "doors" for x in c)
    assert all(x["unit"] == "sq ft" for x in c if x["type"] == "paint")


def test_review_order_and_commit_only_accepted():
    d = make_plan()
    c = atr.collect(d, 0, _sc(d), types={"rooms"})
    ordered = atr.review_order(c)
    assert [x["conf"] for x in ordered] == sorted(x["conf"] for x in c)
    for x in c:
        x["state"] = "rejected"
    c[0]["state"] = "accepted"
    c[0]["group"] = "Office Carpet"                  # reassigned
    marks = atr.marks(c)
    assert len(marks) == 1
    assert marks[0][2]["measure"]["group"] == "Office Carpet"
    assert marks[0][2]["measure"]["method"].startswith("auto takeoff (reviewed)")
    n = atr.commit(d, c)
    assert n == 1
    assert [i["group"] for i in annotate.takeoff_items(d)].count("Office Carpet") == 1


def test_review_dialog_keys():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    QApplication.instance() or QApplication([])
    d = make_plan()
    c = atr.collect(d, 0, _sc(d), types={"rooms"})
    dlg = atr.ReviewDialog(d, c, groups=["Office Carpet", "VCT"])
    assert all(x["state"] == "pending" for x in dlg.items)
    dlg.table.setCurrentCell(0, 0)
    QTest.keyClick(dlg.table, Qt.Key_A)                 # accept, move down
    assert dlg.items[0]["state"] == "accepted" and dlg.table.currentRow() == 1
    QTest.keyClick(dlg.table, Qt.Key_X)                 # reject
    assert dlg.items[1]["state"] == "rejected"
    dlg.reassign(0, "VCT")
    assert dlg.items[0]["group"] == "VCT"
    assert [x["group"] for x in dlg.accepted()] == ["VCT"]


def test_refuses_without_scale():
    import fitz
    d = fitz.open()
    d.new_page()
    with pytest.raises(atr.NeedScale):
        atr.collect(d, 0, None, types={"rooms"})
