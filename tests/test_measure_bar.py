import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import fitz
import pytest
from app import measure_bar as mb
from app import takeoff


def cal(ppu=12.0):   # 12 pt per foot (1" = 6')
    c = takeoff.Calibration(fitz.Point(0, 0), fitz.Point(ppu, 0), 1, "ft")
    return c


@pytest.mark.parametrize("text,ft", [("12'6", 12.5), ("12'-6\"", 12.5),
                                     ("150\"", 12.5), ("12.5", 12.5),
                                     ("12' 6 1/2\"", 12 + 6.5 / 12),
                                     ("3 m", 3 / 0.3048)])
def test_parse_entry(text, ft):
    assert mb.parse_entry(text, "ft") == pytest.approx(ft, rel=1e-6)


def test_parse_entry_rejects_junk():
    assert mb.parse_entry("abc", "ft") is None
    assert mb.parse_entry("-3", "ft") is None


def test_live_values_use_calibration():
    c = cal()
    pts = [fitz.Point(0, 0), fitz.Point(120, 0), fitz.Point(120, 60)]
    assert mb.live(pts, c, "length") == pytest.approx(15.0)
    sq = [fitz.Point(0, 0), fitz.Point(120, 0), fitz.Point(120, 120), fitz.Point(0, 120)]
    assert mb.live(sq, c, "area") == pytest.approx(100.0)
    assert mb.live(pts, c, "count") == 3
    assert mb.live(pts, None, "length") is None


def test_set_segment_moves_last_point_along_direction():
    c = cal()
    pts = [fitz.Point(0, 0), fitz.Point(30, 40)]          # 50 pt
    out = mb.set_segment(pts, 12.5, c)
    d = ((out[-1].x) ** 2 + (out[-1].y) ** 2) ** 0.5
    assert d == pytest.approx(12.5 * 12)
    assert out[-1].x / out[-1].y == pytest.approx(30 / 40)
    with pytest.raises(ValueError):
        mb.set_segment(pts, 5, None)


def _doc_with_takeoff():
    from app import annotate
    doc = fitz.open()
    doc.new_page()
    doc.new_page()
    for p, v in ((0, 120.0), (1, 80.5)):
        annotate.apply_op(doc, annotate.new_op(
            "add_count", p, pt=[50, 50], n=1, color=[1, 0, 0],
            measure={"type": "count", "value": 1, "unit": "ea", "group": "Outlets"}))
    return doc


def test_job_total_is_real_not_hardcoded():
    doc = _doc_with_takeoff()
    t = mb.job_total(doc, "count", group="Outlets")
    assert t == 2
    assert mb.job_total(fitz.open(), "area") == 0


def test_bar_enter_commits_esc_cancels_add_button(qapp=None):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    app = QApplication.instance() or QApplication([])
    bar = mb.MeasureBar()
    got = {}
    bar.committed.connect(lambda v: got.setdefault("v", v))
    bar.cancelled.connect(lambda: got.setdefault("c", True))
    bar.add_requested.connect(lambda: got.setdefault("a", True))
    bar.set_live("length", 15.0, "ft", job_total=230.5)
    assert "15'-0\"" in bar.readout.text() and "230" in bar.readout.text()
    bar.entry.setText("12'6")
    QTest.keyClick(bar.entry, Qt.Key_Return)
    assert got["v"] == pytest.approx(12.5)
    QTest.keyClick(bar.entry, Qt.Key_Escape)
    assert got["c"] and bar.entry.text() == ""
    bar.add_btn.click()
    assert got["a"]
    bar.set_live("length", None, "ft")
    assert "Set Scale" in bar.readout.text()
