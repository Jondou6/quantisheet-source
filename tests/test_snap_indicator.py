import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import fitz
import pytest
from app import snap, snap_indicator as si


def idx():
    return snap.SnapIndex([((0, 0), (100, 0)), ((50, -50), (50, 50))])


def test_labels_and_colors_for_every_kind():
    for k in (snap.ENDPOINT, snap.MIDPOINT, snap.ONLINE, snap.INTERSECTION,
              si.PERP, si.GRID):
        lab, col = si.style(k)
        assert lab in ("END", "MID", "EDGE", "INT", "PERP", "GRID")
        assert col.startswith("#")


def test_alt_bypasses_shift_locks_straight():
    p = fitz.Point(99, 2)
    pt, kind = si.resolve(p, None, idx(), 5, alt=True)
    assert (pt.x, pt.y, kind) == (99, 2, None)
    pt, kind = si.resolve(fitz.Point(40, 3), fitz.Point(0, 0), idx(), 5, shift=True)
    assert pt.y == pytest.approx(0) and kind is None


def test_endpoint_and_mode_filter():
    pt, kind = si.resolve(fitz.Point(99, 2), None, idx(), 5)
    assert kind == snap.ENDPOINT and (pt.x, pt.y) == (100, 0)
    pt, kind = si.resolve(fitz.Point(99, 2), None, idx(), 5,
                          modes={"EDGE"})
    assert kind == snap.ONLINE


def test_perpendicular_from_anchor():
    segs = [((0, 0), (100, 0))]
    pt, kind = si.resolve(fitz.Point(31, 4), fitz.Point(30, 40),
                          snap.SnapIndex(segs), 6, modes={"PERP"}, segs=segs)
    assert kind == si.PERP and pt.x == pytest.approx(30) and pt.y == pytest.approx(0)


def test_grid_snap():
    pt, kind = si.resolve(fitz.Point(49, 23), None, snap.SnapIndex([]), 5,
                          modes={"GRID"}, grid=24)
    assert kind == si.GRID and (pt.x, pt.y) == (48, 24)


def test_status_text_lists_modes():
    t = si.status_text({"END", "INT"})
    assert t.startswith("Snap: END INT") and "Alt" in t and "Shift" in t
    assert si.status_text(set()) .startswith("Snap: off")


def test_modes_saved(monkeypatch):
    store = {}
    monkeypatch.setattr(si.settings, "get", lambda k, d=None: store.get(k, d))
    monkeypatch.setattr(si.settings, "set", lambda k, v: store.__setitem__(k, v))
    assert si.load_modes() == set(si.DEFAULT_MODES)
    si.save_modes({"END", "GRID"})
    assert si.load_modes() == {"END", "GRID"}


def test_paint_draws_box_and_label():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QImage, QPainter, QColor
    from PySide6.QtCore import QPointF
    QApplication.instance() or QApplication([])
    img = QImage(120, 60, QImage.Format_ARGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    si.paint(p, QPointF(30, 30), snap.MIDPOINT)
    p.end()
    lab, col = si.style(snap.MIDPOINT)
    c = QColor(col)
    hits = sum(1 for x in range(120) for y in range(60)
               if QColor(img.pixel(x, y)).rgb() == c.rgb())
    assert hits > 10
