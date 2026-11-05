"""Cutouts: openings taken off the area they're drawn in."""
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import annotate, assemblies                       # noqa: E402
from test_gui import win, qapp                              # noqa: E402,F401

SLAB = 'Slab on Grade - 4"'


@pytest.fixture(autouse=True)
def _own_library(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))


def _labels(doc, pno=0):
    return [a.info["content"] for a in doc[pno].annots()
            if doc.xref_get_key(a.xref, "PSLabel")[1] == "true"]


def _slab_with_cutout():
    """20' x 10' slab at 1/4" = 1'-0" with a 5' x 4' opening."""
    d = fitz.open()
    d.new_page(width=2592, height=1728)
    annotate.apply_op(d, annotate.new_op("set_scale", 0, ppu=18, unit="ft"))
    area = annotate.new_op("add_polygon", 0,
                           pts=[[100, 100], [460, 100], [460, 280],
                                [100, 280]],
                           label=f"{SLAB}: 200.00 sq ft",
                           measure={"type": "area", "value": 200,
                                    "unit": "sq ft", "group": SLAB})
    annotate.apply_op(d, area)
    annotate.apply_op(d, annotate.new_op(
        "add_polygon", 0, pts=[[200, 150], [290, 150], [290, 222],
                               [200, 222]],
        dashes=True, fill=[1, 1, 1], label="Cutout -20.00 sq ft",
        measure={"type": "cutout", "value": 20, "unit": "sq ft",
                 "group": SLAB, "parent": area["id"]}))
    return d, area["id"]


def test_net_area_and_opening_edge():
    d, _ = _slab_with_cutout()
    items = annotate.takeoff_items(d)
    assert len(items) == 1                       # the cutout isn't a line
    it = items[0]
    assert it["value"] == pytest.approx(180)
    assert it["gross"] == 200 and it["cutouts"] == 1
    assert it["hole_perimeter"] == pytest.approx(18)     # 5+4+5+4 ft
    both = annotate.takeoff_items(d, include_cutouts=True)
    assert [i["type"] for i in both] == ["area", "cutout"]
    rows = {r["type"]: r["measure"] for r in annotate.markup_items(d)}
    assert rows == {"Area": "180.00 sq ft net", "Cutout": "-20.00 sq ft"}


def test_label_shows_net_and_cutout_without_parent_is_ignored():
    d, _ = _slab_with_cutout()
    assert annotate.refresh_area_labels(d, 0) == 1
    assert f"{SLAB}: 180.00 sq ft net (1 cutout)" in _labels(d)
    assert annotate.refresh_area_labels(d, 0) == 0       # already right
    orphan = annotate.new_op("add_polygon", 0,
                             pts=[[1000, 1000], [1090, 1000], [1090, 1072]],
                             measure={"type": "cutout", "value": 5,
                                      "unit": "sq ft", "group": SLAB,
                                      "parent": "missing"})
    annotate.apply_op(d, orphan)
    assert annotate.takeoff_items(d)[0]["value"] == pytest.approx(180)


def test_assembly_uses_net_area_and_opening_perimeter():
    d, _ = _slab_with_cutout()
    rows, _totals, errors = assemblies.rollup(d)
    assert not errors
    slab = assemblies.find(d, SLAB)
    want = {p["name"]: p["qty"] for p in assemblies.compute(
        slab, {"area": 180, "perimeter": 60 + 18, "length": 0, "count": 0,
               "segments": 0, "cutouts": 1, "gross_area": 200})}
    got = {p["name"]: p["qty"] for p in rows[0]["parts"]}
    assert got == pytest.approx(want)
    assert got["Edge Form"] == pytest.approx(78, abs=0.1)


def test_cutout_tool_in_the_app(win):
    from PySide6.QtWidgets import QMessageBox
    v = win._view
    assert v.calibrate(240.0, real=24, unit="ft", all_pages=False)  # 10/ft
    P = fitz.Point
    v.style["subject"] = "Floor"
    assert v.commit_points("measure_area", [P(100, 100), P(300, 100),
                                            P(300, 300), P(100, 300)])
    assert annotate.takeoff_items(v.doc)[0]["value"] == pytest.approx(400)
    assert v.commit_points("measure_cutout", [P(150, 150), P(200, 150),
                                              P(200, 200), P(150, 200)])
    it = annotate.takeoff_items(v.doc)[0]
    assert it["value"] == pytest.approx(375) and it["cutouts"] == 1
    assert "Floor: 375.00 sq ft net (1 cutout)" in _labels(v.doc)
    win.undo()
    it = annotate.takeoff_items(win._view.doc)[0]
    assert it["value"] == pytest.approx(400) and not it["cutouts"]
    assert "Floor: 400.00 sq ft" in _labels(win._view.doc)
    win.redo()
    assert annotate.takeoff_items(win._view.doc)[0]["value"] == \
        pytest.approx(375)
    # outside any area: nothing happens
    shown = []
    QMessageBox.information = staticmethod(lambda *a, **k: shown.append(a))
    v = win._view
    assert v.commit_points("measure_cutout", [P(500, 500), P(540, 500),
                                              P(540, 540)]) == 0
    assert shown
