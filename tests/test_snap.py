"""Snap to content."""
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import snap                                        # noqa: E402
from test_gui import win, qapp                               # noqa: E402,F401


def _idx(*segs):
    return snap.SnapIndex(list(segs))


def test_snap_kinds():
    idx = _idx(((0, 0), (100, 0)), ((50, -50), (50, 50)))
    p, kind = idx.snap(fitz.Point(2, 3), 6)
    assert kind == snap.ENDPOINT and p == fitz.Point(0, 0)
    p, kind = idx.snap(fitz.Point(52, 2), 6)
    assert kind == snap.INTERSECTION and abs(p.x - 50) < 1e-6 and abs(p.y) < 1e-6
    p, kind = idx.snap(fitz.Point(25, 2), 6)
    assert kind == snap.MIDPOINT or kind == snap.ONLINE
    p, kind = idx.snap(fitz.Point(80, 3), 6)
    assert kind == snap.ONLINE and p == fitz.Point(80, 0)
    assert idx.snap(fitz.Point(80, 30), 6) is None


def test_midpoint_beats_on_line():
    idx = _idx(((0, 0), (100, 0)))
    p, kind = idx.snap(fitz.Point(48, 2), 6)
    assert kind == snap.MIDPOINT and p == fitz.Point(50, 0)


def test_ortho():
    a = fitz.Point(0, 0)
    q = snap.ortho(a, fitz.Point(100, 7))
    assert abs(q.y) < 1e-6 and abs(q.x - 100.245) < 0.01
    q = snap.ortho(a, fitz.Point(50, 48))
    assert abs(q.x - q.y) < 1e-6                       # 45 degrees


@pytest.mark.parametrize("rot", [0, 90, 180, 270])
def test_page_drawing_on_rotated_pages(rot):
    d = fitz.open()
    page = d.new_page(width=612, height=792)
    page.draw_line((100, 100), (300, 100))
    page.draw_rect(fitz.Rect(400, 500, 450, 560))
    page.draw_quad(fitz.Rect(100, 600, 200, 700).quad)
    page.draw_circle((300, 300), 40)
    page.draw_polyline([(50, 50), (80, 90), (120, 60)])
    page.set_rotation(rot)
    page = d[0]
    idx = snap.SnapIndex(snap.page_segments(page))
    m = page.rotation_matrix
    for corner in (fitz.Point(100, 100), fitz.Point(300, 100),
                   fitz.Point(450, 560), fitz.Point(200, 700),
                   fitz.Point(80, 90)):
        want = corner * m                               # as displayed
        hit = idx.snap(want + (3, 2), 8)
        assert hit and hit[1] == snap.ENDPOINT, (rot, corner, hit)
        assert abs(hit[0].x - want.x) < 0.5 and abs(hit[0].y - want.y) < 0.5


def test_measure_snaps_to_wall_ends(win):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    v = win._view
    assert v.zoom == pytest.approx(1.0)
    assert v.calibrate(240.0, real=24, unit="ft", all_pages=False)
    v.set_tool("measure_length")
    v.set_snap(True)
    # sloppy drag near the ends of the 24' line (60,400)-(300,400)
    QTest.mousePress(v, Qt.LeftButton, Qt.NoModifier, QPoint(64, 404))
    QTest.mouseMove(v, QPoint(296, 397))
    assert v._snap_hit and v._snap_hit[1] == snap.ENDPOINT
    QTest.mouseRelease(v, Qt.LeftButton, Qt.NoModifier, QPoint(296, 397))
    lines = [a for a in v.pg.annots() if a.type[1] == "Line"]
    assert lines, "no measurement made"
    (x0, y0), (x1, y1) = lines[-1].vertices[:2]
    assert (round(x0), round(y0), round(x1), round(y1)) == (60, 400, 300, 400)
    from app import annotate
    vals = [i for i in annotate.takeoff_items(v.doc)]
    assert vals and abs(vals[-1]["value"] - 24) < 0.01


def test_alt_and_toggle_turn_snap_off(win):
    v = win._view
    v.set_tool("measure_length")
    v.set_snap(True)
    p = v.snap_point(fitz.Point(64, 404))
    assert p == fitz.Point(60, 400)
    assert v.snap_point(fitz.Point(64, 404), alt=True) == fitz.Point(64, 404)
    win.snap_action.setChecked(False)
    assert not win._view.snap_enabled
    assert v.snap_point(fitz.Point(64, 404)) == fitz.Point(64, 404)
    win.snap_action.setChecked(True)
    v.set_tool("add_highlight")                        # text tools don't snap
    assert v.snap_point(fitz.Point(64, 404)) == fitz.Point(64, 404)


# the left end of the 89'-4" overall dimension on A-102 (Aiken County Spay &
# Neuter Clinic): dimension line, extension lines and a filled arrowhead
# drawn twice (fill + outline)
ARROW = [((384.88, 197.1), (1993.98, 197.1)),
         ((384.88, 197.1), (393.89, 198.69)), ((393.89, 198.69), (393.89, 195.52)),
         ((393.89, 195.52), (384.88, 197.1)),
         ((384.88, 197.1), (393.89, 198.69)), ((393.89, 198.69), (393.89, 195.52)),
         ((393.89, 195.52), (384.88, 197.1)),
         ((384.88, 197.1), (384.88, 192.6)), ((384.88, 197.1), (384.88, 765.66))]


def test_arrow_tip_beats_arrow_corners():
    import random
    idx = snap.SnapIndex(ARROW)
    random.seed(3)
    for _ in range(200):
        p = fitz.Point(384.88 + random.uniform(-5, 5),
                       197.1 + random.uniform(-4, 4))
        hit = idx.snap(p, 18)
        assert hit and abs(hit[0].x - 384.88) < 0.01 \
            and abs(hit[0].y - 197.1) < 0.01, (p, hit)
    # even right on the back of the arrowhead, it's the tip that counts
    for p in (fitz.Point(393.6, 195.7), fitz.Point(393.89, 198.69),
              fitz.Point(392, 197.3)):
        hit = idx.snap(p, 18)
        assert abs(hit[0].x - 384.88) < 0.01, (p, hit)
    # but a lone short line elsewhere is untouched
    idx2 = snap.SnapIndex([((0, 0), (5, 0)), ((5, 0), (5, 3))])
    assert idx2.snap(fitz.Point(5.2, 0.2), 4)[0] == fitz.Point(5, 0)


def test_length_by_two_clicks(win):
    """Click the start, click the end (as in Bluebeam) - no drag needed."""
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from app import annotate
    v = win._view
    assert v.calibrate(240.0, real=24, unit="ft", all_pages=False)
    v.set_tool("measure_length")
    v.set_snap(True)
    before = len(annotate.takeoff_items(v.doc))
    QTest.mouseClick(v, Qt.LeftButton, Qt.NoModifier, QPoint(64, 404))
    assert v._drag and v._click_line            # waiting for the end
    QTest.mouseMove(v, QPoint(200, 398))
    QTest.mouseClick(v, Qt.LeftButton, Qt.NoModifier, QPoint(296, 397))
    items = annotate.takeoff_items(v.doc)
    assert len(items) == before + 1 and abs(items[-1]["value"] - 24) < 0.01
    assert v._drag is None and not v._click_line
    # Esc after the first click cancels
    QTest.mouseClick(v, Qt.LeftButton, Qt.NoModifier, QPoint(64, 404))
    QTest.keyClick(v, Qt.Key_Escape)
    assert v._drag is None
    assert len(annotate.takeoff_items(v.doc)) == before + 1
