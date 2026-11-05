"""Typical areas (one takeoff x N units) and submittal review stamps."""
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import annotate, assemblies                       # noqa: E402
from test_gui import win, qapp                              # noqa: E402,F401

_KEEP = []


def _room():
    d = fitz.open()
    d.new_page(width=800, height=600)
    annotate.apply_op(d, annotate.new_op("set_scale", 0, ppu=10, unit="ft"))
    op = annotate.new_op(
        "add_polygon", 0, pts=[[100, 100], [200, 100], [200, 200],
                               [100, 200]],
        label="Guest Room: 100.00 sq ft",
        measure={"type": "area", "value": 100, "unit": "sq ft",
                 "group": "Guest Room"})
    annotate.apply_op(d, op)
    return d, op["id"]


def _labels(d):
    page = d[0]
    _KEEP.append(page)
    return [a.info["content"] for a in page.annots()
            if annotate.is_label(d, a)]


def test_typical_area_counts_n_times():
    d, tag = _room()
    assert annotate.apply_op(d, annotate.new_op("set_annot", 0, target=tag,
                                                multiplier=200))
    it = annotate.takeoff_items(d)[0]
    assert it["multiplier"] == 200
    assert it["unit_value"] == pytest.approx(100)
    assert it["value"] == pytest.approx(20000)
    assert it["gross"] == pytest.approx(20000)
    assert annotate.refresh_area_labels(d, 0) == 1
    assert _labels(d) == ["Guest Room: 100.00 sq ft x 200 typical = "
                          "20,000.00"]
    m = assemblies.measurements(d)[0]["vars"]
    assert m["area"] == pytest.approx(20000)
    assert m["perimeter"] == pytest.approx(40 * 200)
    # back to one
    annotate.apply_op(d, annotate.new_op("set_annot", 0, target=tag,
                                         multiplier=1))
    assert annotate.takeoff_items(d)[0]["value"] == pytest.approx(100)


def test_typical_with_cutout_and_count():
    d, tag = _room()
    annotate.apply_op(d, annotate.new_op(
        "add_polygon", 0, pts=[[120, 120], [140, 120], [140, 140],
                               [120, 140]],
        measure={"type": "cutout", "value": 4, "unit": "sq ft",
                 "group": "Guest Room", "parent": tag}))
    annotate.apply_op(d, annotate.new_op("set_annot", 0, target=tag,
                                         multiplier=10))
    it = annotate.takeoff_items(d)[0]
    assert it["value"] == pytest.approx((100 - 4) * 10)
    assert it["hole_perimeter"] == pytest.approx(8 * 10)
    cnt = annotate.new_op("add_count", 0, pt=[300, 300], n=1,
                          measure={"type": "count", "value": 1, "unit": "ea",
                                   "group": "Toilet"})
    annotate.apply_op(d, cnt)
    annotate.apply_op(d, annotate.new_op("set_annot", 0, target=cnt["id"],
                                         multiplier=12))
    toilets = [i for i in annotate.takeoff_items(d) if i["group"] == "Toilet"]
    assert toilets[0]["value"] == pytest.approx(12)


def test_typical_count_from_the_menu(win, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    monkeypatch.setattr(QInputDialog, "getDouble",
                        staticmethod(lambda *a, **k: (24.0, True)))
    v = win._view
    assert v.calibrate(240.0, real=24, unit="ft", all_pages=False)
    v.style["subject"] = "Unit A"
    v.commit_points("measure_area", [fitz.Point(100, 100),
                                     fitz.Point(200, 100),
                                     fitz.Point(200, 200),
                                     fitz.Point(100, 200)])
    shape = [a for a in v.pg.annots() if (a.info or {}).get(
        "subject", "").startswith("Takeoff:area")][-1]
    v.select(shape)
    assert v.ask_typical_count()
    unit_a = [i for i in annotate.takeoff_items(v.doc)
              if i["group"] == "Unit A"][0]
    assert unit_a["value"] == pytest.approx(100 * 24)


def test_submittal_review_stamp(win):
    v = win._view
    before = len(list(v.pg.annots()))
    assert v.review_stamp(fitz.Rect(300, 300, 400, 340),
                          action="REVISE AND RESUBMIT", reviewer="Jon")
    stamps = [a for a in v.pg.annots()
              if (a.info or {}).get("subject") == "Submittal Review"]
    assert len(list(v.pg.annots())) == before + 1 and stamps
    text = stamps[0].info["content"]
    assert text.startswith("REVISE AND RESUBMIT") and "Reviewed by: Jon" \
        in text
    assert stamps[0].rect.width >= 229
