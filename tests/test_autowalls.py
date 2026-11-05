"""Auto Walls & Doors: wall centerlines by thickness and door swings,
from a CAD-style floor plan's linework."""
import os

import fitz

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QMessageBox                    # noqa: E402

from app import annotate, autowalls                          # noqa: E402
from test_gui import win, qapp                               # noqa: E402,F401

PPU = 18.0                                   # 1/4" = 1'-0"


def _plan():
    d = fitz.open()
    p = d.new_page(width=792, height=612)
    sh = p.new_shape()
    ox, oy = 60, 60

    def L(x0, y0, x1, y1):
        sh.draw_line((ox + x0 * PPU, oy + y0 * PPU),
                     (ox + x1 * PPU, oy + y1 * PPU))
    t8 = 8 / 12
    # a 20' x 12' room with 8" exterior walls
    L(0, 0, 20, 0), L(t8, t8, 20 - t8, t8)
    L(0, 12, 20, 12), L(t8, 12 - t8, 20 - t8, 12 - t8)
    L(0, 0, 0, 12), L(t8, t8, t8, 12 - t8)
    L(20, 0, 20, 12), L(20 - t8, t8, 20 - t8, 12 - t8)
    # a 5" partition drawn with its stud and gypsum lines
    for dx in (0, .625 / 12, 4.25 / 12, 4.875 / 12):
        L(10 + dx, t8, 10 + dx, 12 - t8)
    # hatching that must not count
    for k in range(10):
        o = k * 4 / 12
        L(2 + o, 3, 2 + o + 3, 6)
    sh.finish(color=(0, 0, 0), width=0.7)
    # a 3'-0" door swing (quarter circle) hinged on the top wall
    cx, cy, r = ox + 14 * PPU, oy + t8 * PPU, 3 * PPU
    sh.draw_line((cx, cy), (cx, cy + r))           # the leaf (NW-17)
    sh.draw_curve((cx + r, cy), (cx + r, cy + r),
                  (cx, cy + r))
    sh.finish(color=(0, 0, 0), width=0.5)
    sh.commit()
    annotate.apply_op(d, annotate.new_op("set_scale", 0, ppu=PPU, unit="ft",
                                         name='1/4" = 1\'-0"'))
    return d


def test_walls_and_doors():
    d = _plan()
    ws = autowalls.walls(d[0], PPU, "ft")
    sm = autowalls.summary(ws, autowalls.doors(d[0], PPU, "ft"))
    assert set(sm["walls"]) == {"Wall 8in", "Wall 5in"}
    assert abs(sm["walls"]["Wall 8in"] - 61.33) < 0.3      # centerlines
    assert abs(sm["walls"]["Wall 5in"] - 11.33) < 0.2
    assert sm["doors"] == {"Door 3'-0\"": 1}


def test_auto_walls_in_app(qapp, win, tmp_path, monkeypatch):
    path = str(tmp_path / "walls.pdf")
    _plan().save(path)
    win.open_path(path)
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: 0))
    sm = win.auto_walls()
    assert sm and "Wall 8in" in sm["walls"]
    items = annotate.takeoff_items(win._view.doc)
    groups = {it["group"] for it in items}
    assert {"Wall 8in", "Wall 5in", "Door 3'-0\""} <= groups
    total = sum(it["value"] for it in items if it["group"] == "Wall 8in")
    assert abs(total - 61.33) < 0.3
    win.undo()
    assert not [it for it in annotate.takeoff_items(win._view.doc)
                if it["group"].startswith("Wall")]


def test_walls_on_a_scan():
    """A scanned plan has no linework: the solid walls in the picture are
    traced instead."""
    src = fitz.open()
    p = src.new_page(width=792, height=612)
    ox, oy = 60, 60
    t8, t5 = 8 / 12, 5 / 12

    def wall(x0, y0, x1, y1):
        p.draw_rect(fitz.Rect(ox + x0 * PPU, oy + y0 * PPU, ox + x1 * PPU,
                              oy + y1 * PPU), color=None, fill=(0, 0, 0))
    wall(0, 0, 20, t8)
    wall(0, 12 - t8, 20, 12)
    wall(0, 0, t8, 12)
    wall(20 - t8, 0, 20, 12)
    wall(10, t8, 10 + t5, 12 - t8)
    pix = p.get_pixmap(dpi=150)
    scan = fitz.open()
    sp = scan.new_page(width=792, height=612)
    sp.insert_image(sp.rect, stream=pix.tobytes("png"))
    assert autowalls.segments(sp) == []                # no linework
    segs = autowalls.raster_segments(sp, PPU, "ft")
    ws = autowalls.walls(sp, PPU, "ft", segs=segs)
    sm = autowalls.summary(ws, [])
    assert set(sm["walls"]) == {"Wall 8in", "Wall 5in"}, sm
    assert abs(sm["walls"]["Wall 8in"] - 61.33) < 2.5, sm
    assert abs(sm["walls"]["Wall 5in"] - 11.33) < 1.0, sm


# ---- a layered exterior wall is a wall, hatching is not (Aiken A-101) ------

def _layered_plan():
    """A 30' x 20' building whose walls are drawn in layers: outer face,
    air space, insulation, CMU and finish lines at uneven spacing (as on
    a real composite exterior wall), plus a patch of evenly spaced hatch
    lines that must not count."""
    d = fitz.open()
    p = d.new_page(width=1224, height=792)
    sh = p.new_shape()
    ox, oy = 100, 100
    layers = [0, 5.5, 10.0, 14.0, 15.25]          # inches from the outside

    def L(x0, y0, x1, y1):
        sh.draw_line((ox + x0 * PPU, oy + y0 * PPU),
                     (ox + x1 * PPU, oy + y1 * PPU))
    W, H = 30.0, 20.0
    for inch in layers:
        t = inch / 12
        L(t, t, W - t, t), L(t, H - t, W - t, H - t)
        L(t, t, t, H - t), L(W - t, t, W - t, H - t)
    for k in range(8):                            # hatch: 3" o.c.
        o = 6 + k * 0.25
        L(8, o, 20, o)
    sh.finish(color=(0, 0, 0), width=0.5)
    sh.commit()
    return d


def test_layered_wall_is_not_taken_for_hatching():
    d = _layered_plan()
    ws = autowalls.walls(d[0], PPU, "ft")
    thick = [w for w in ws if w["thickness"] >= 14.5]
    lf = sum(w["length"] for w in thick)
    assert 85 < lf < 106, (lf, ws)             # ~95 LF of centerline
    # the evenly spaced hatch lines make no wall
    assert not [w for w in ws if 8 < (w["p0"][0] - 100) / PPU < 20 and
                6 <= (w["p0"][1] - 100) / PPU <= 8]


def test_evenly_spaced_lines_are_hatching():
    assert autowalls._evenly_spaced([(1, 4.5), (2, 9.0), (3, 13.5),
                                     (4, -4.5)])
    assert not autowalls._evenly_spaced([(1, -8.26), (2, 6.76), (3, 17.46),
                                         (4, 18.58)])
