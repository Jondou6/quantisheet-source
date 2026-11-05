"""Fast rendering must look exactly like a plain render: markups drawn over
a cached drawing, tiles, rotated pages."""
import os

import fitz

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import annotate                                     # noqa: E402
from test_gui import win, qapp                               # noqa: E402,F401


def _doc():
    d = fitz.open()
    p = d.new_page(width=900, height=600)
    sh = p.new_shape()
    for k in range(30):
        sh.draw_line((20 + k * 25, 30), (40 + k * 25, 560))
    sh.finish(color=(0, 0, 0), width=1)
    sh.commit()
    p.insert_text((60, 80), "FLOOR PLAN", fontsize=20)
    for k in range(12):
        annotate.apply_op(d, annotate.new_op(
            "add_cloud" if k % 2 else "add_rect", 0,
            rect=[100 + k * 40, 200, 130 + k * 40, 240]))
    annotate.apply_op(d, annotate.new_op(
        "add_polyline", 0, pts=[[100, 400], [500, 400], [500, 500]],
        measure={"type": "length", "value": 20, "unit": "ft",
                 "group": "Wall"}))
    return d


def _same(a, b):
    assert (a.width, a.height, a.n) == (b.width, b.height, b.n)
    diff = sum(abs(x - y) for x, y in zip(a.samples, b.samples))
    return diff / len(a.samples)


def test_layered_render_matches_plain(qapp, win):
    v = win._view
    for rot in (0, 90):
        d = _doc()
        d[0].set_rotation(rot)
        pg = d[0]
        plain = pg.get_pixmap(matrix=fitz.Matrix(0.9, 0.9), alpha=False)
        base = pg.get_pixmap(matrix=fitz.Matrix(0.9, 0.9), alpha=False,
                             annots=False)
        lay = v._with_markups(pg, base, 0.9)
        assert _same(plain, lay) < 0.5, rot


def test_markup_edit_reuses_the_drawing(qapp, win, tmp_path):
    p = tmp_path / "layers.pdf"
    _doc().save(str(p))
    win.open_path(str(p))
    v = win._view
    win.fit_page()
    v.apply_marks([(0, "add_rect", {"rect": [600, 100, 700, 180]})])
    first = v._content_raster                     # drawing at this zoom
    assert first is not None
    v.apply_marks([(0, "add_rect", {"rect": [600, 300, 700, 380]})])
    assert v._content_raster is first             # drawing not redrawn
    img = v.rendered.toImage()
    plain = v.pg.get_pixmap(matrix=fitz.Matrix(v.zoom, v.zoom), alpha=False)
    assert (img.width(), img.height()) == (plain.width, plain.height)
    # a content edit (text) redraws the drawing
    v.apply_marks([(0, "add_redact", {"rect": [55, 60, 300, 90]})])
    assert v._content_raster is not first
    win.undo()
    win._rotate_pages([0], 90)
    assert v._content_raster[0][2] == 90
