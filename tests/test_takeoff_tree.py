"""The Takeoff panel on the left: sheets, items with color and total, and
an eye to hide them (PlanSwift-style)."""
import os

import fitz
from PySide6.QtCore import Qt

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import annotate                                      # noqa: E402
from app.takeoff_tree import group_items                      # noqa: E402
from test_gui import win, qapp                                # noqa: E402,F401


def _measure(v):
    assert v.calibrate(240.0, real=24, unit="ft", all_pages=False)
    for y in (400, 450):
        v.commit_line("measure_length", fitz.Point(60, y), fitz.Point(300, y))


def test_panel_lists_items_and_hides_them(win):
    v = win._view
    v.style["subject"] = "Wall Type A"
    _measure(v)
    win._refresh_panels()
    t = win.takeoff_tree
    t.refresh()
    assert t.tree.topLevelItemCount() == 1
    top = t.tree.topLevelItem(0)
    item = top.child(0)
    assert item.text(0) == "Wall Type A" and item.text(1) == "48.0 ft"
    assert item.checkState(2) == Qt.Checked
    g = group_items(v.doc)[v.page][("Wall Type A", "length", "ft")]
    assert g["n"] == 2 and g["color"] is not None
    # the eye hides them on the drawing; they still count
    item.setCheckState(2, Qt.Unchecked)
    flags = [a.flags & fitz.PDF_ANNOT_IS_HIDDEN
             for a in annotate.iter_annots(v.pg)
             if annotate.ref(a) in g["refs"]]
    assert flags and all(flags)
    assert sum(i["value"] for i in annotate.takeoff_items(v.doc)) == 48
    t.refresh()
    assert t.tree.topLevelItem(0).child(0).checkState(2) == Qt.Unchecked
    t.tree.topLevelItem(0).child(0).setCheckState(2, Qt.Checked)
    assert not any(a.flags & fitz.PDF_ANNOT_IS_HIDDEN
                   for a in annotate.iter_annots(v.pg))
    # search, go to, totals
    t.search.setText("nothing like it")
    assert t.tree.topLevelItem(0).data(0, Qt.UserRole) == ("empty",)
    t.search.setText("wall")
    assert t.tree.topLevelItemCount() == 1
    assert t.grand[("Wall Type A", "length", "ft")] == 48
    t._open(t.tree.topLevelItem(0).child(0))
    assert v.selected is not None


def test_clean_display_and_item_settings(win):
    v = win._view
    v.style["subject"] = "Manhole"
    _measure(v)
    t = win.takeoff_tree
    t.set_doc(v.doc)
    assert t.clean_display() >= 2
    cols = {tuple(round(x, 2) for x in (a.colors or {}).get("stroke") or ())
            for a in annotate.iter_annots(v.pg)
            if (a.info or {}).get("subject", "").startswith("Takeoff:")}
    assert len(cols) == 1
    rec = t.item_settings("Manhole", prefix="MH", depth=8, drop=0.1)
    assert rec["prefix"] == "MH" and rec["depth"] == 8
