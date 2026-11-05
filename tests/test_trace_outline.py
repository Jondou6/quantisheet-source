"""Trace Outline: an area tool whose clicks land on the drawn linework
and follow it - a notched slab is traced in four clicks."""
import os

import fitz

from app import trace_outline as to

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from test_gui import win, qapp                     # noqa: F401
except Exception:                  # no Qt here: the geometry tests still run
    win = qapp = None

PPU = 12.0                                    # 12 points per foot
OX, OY = 100.0, 100.0

# a 40' x 30' slab with a 10' x 10' notch out of one corner: 1100 SF,
# perimeter 140'
SLAB = [(0, 0), (40, 0), (40, 20), (30, 20), (30, 30), (0, 30)]


def _p(x, y):
    return (OX + x * PPU, OY + y * PPU)


def _slab_items():
    pts = [_p(*q) for q in SLAB]
    return [("l", pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))]


# ---- pure geometry (no PDF) ----------------------------------------------------------
def test_one_closed_path_follows_the_shorter_way():
    idx = to.TraceIndex(to.chains_from_drawings([{"items": _slab_items()}]))
    assert len(idx.chains) == 1 and idx.chains[0].closed
    a = idx.snap((_p(0, 0)[0] + 2, _p(0, 0)[1] + 2), 5)
    b = idx.snap((_p(40, 20)[0] - 1, _p(40, 20)[1] + 1), 5)
    assert a.kind == to.VERTEX and b.kind == to.VERTEX
    assert idx.between(a, b) == [_p(40, 0)]               # 60' vs 80' round
    c = idx.snap(_p(30, 30), 5)
    assert idx.between(b, c) == [_p(30, 20)]
    assert idx.between(c, a) == [_p(0, 30)]
    pts = [(a.x, a.y), _p(40, 0), (b.x, b.y), _p(30, 20), (c.x, c.y),
           _p(0, 30)]
    m = to.measures(pts, PPU)
    assert abs(m["area"] - 1100) < 1e-6
    assert abs(m["perimeter"] - 140) < 1e-6
    assert m["points"] == 6


def test_separate_line_pieces_are_followed_through_their_ends():
    """CAD exports often draw each edge as its own path."""
    drawings = [{"items": [it]} for it in _slab_items()]
    idx = to.TraceIndex(to.chains_from_drawings(drawings))
    assert len(idx.chains) == 6
    a = idx.snap(_p(0, 0), 3)
    c = idx.snap(_p(30, 30), 3)
    assert idx.between(a, c) == [_p(0, 30)]             # the shorter way
    b = idx.snap(_p(40, 20), 3)
    assert idx.between(a, b) == [_p(40, 0)]


def test_edge_snap_and_open_messy_outline():
    """Paving edge drawn open (it runs off the sheet): a click on an edge
    lands on the line, and the corners in between come in."""
    zig = [_p(0, 0), _p(10, 0), _p(12, 5), _p(20, 6), _p(25, 15)]
    items = [("l", zig[i], zig[i + 1]) for i in range(len(zig) - 1)]
    idx = to.TraceIndex(to.chains_from_drawings([{"items": items}]))
    assert not idx.chains[0].closed
    a = idx.snap((_p(5, 0)[0], _p(5, 0)[1] + 3), 5)
    assert a.kind == to.EDGE and abs(a.y - _p(5, 0)[1]) < 1e-9
    b = idx.snap(zig[-1], 2)
    assert idx.between(a, b) == zig[1:4]
    assert idx.between(b, a) == zig[3:0:-1]
    assert idx.snap((0, 0), 5) is None                   # nothing near


def test_curves_are_followed_and_corners_win_over_edges():
    p0, p3 = _p(0, 0), _p(10, 10)
    items = [("c", p0, _p(0, 5), _p(5, 10), p3), ("l", p3, _p(20, 10))]
    idx = to.TraceIndex(to.chains_from_drawings([{"items": items}]))
    a = idx.snap(p0, 2)
    b = idx.snap(_p(20, 10), 2)
    mids = idx.between(a, b)
    assert len(mids) == to.CURVE_STEPS              # 7 on the curve + p3
    assert mids[-1] == p3
    # near the curve's inner points: they are not corners, the edge wins
    q = mids[3]
    s = idx.snap((q[0] + 0.3, q[1]), 2)
    assert s.kind == to.EDGE
    # near a real corner: the corner
    s = idx.snap((p3[0] + 1, p3[1] + 1), 3)
    assert s.kind == to.VERTEX and (s.x, s.y) == p3


def test_rect_items_and_readout():
    r = (OX, OY, OX + 10 * PPU, OY + 5 * PPU)
    idx = to.TraceIndex(to.chains_from_drawings([{"items": [("re", r)]}]))
    assert idx.chains[0].closed and len(idx.chains[0].pts) == 4
    text = to.readout([(0, 0), (10 * PPU, 0), (10 * PPU, 5 * PPU)], PPU,
                      "ft")
    assert text.startswith("Area 25.00 sq ft") and "3 pts" in text
    assert "Perim" in text and "Len" in text


# ---- on a real PDF ------------------------------------------------------------------------
def _pdf(separate=False):
    d = fitz.open()
    page = d.new_page(width=792, height=612)
    sh = page.new_shape()
    pts = [fitz.Point(*_p(*q)) for q in SLAB]
    if separate:
        for i in range(len(pts)):
            sh.draw_line(pts[i], pts[(i + 1) % len(pts)])
            sh.finish(color=(0, 0, 0), width=0.8)
    else:
        sh.draw_polyline(pts + [pts[0]])
        sh.finish(color=(0, 0, 0), width=0.8, closePath=True)
    # some other linework nearby: a grid line and a dimension
    sh.draw_line(fitz.Point(*_p(-5, 45)), fitz.Point(*_p(50, 45)))
    sh.finish(color=(0.5, 0.5, 0.5), width=0.3)
    sh.commit()
    from app import annotate
    annotate.apply_op(d, annotate.new_op("set_scale", 0, ppu=PPU, unit="ft",
                                         name="1 in = 6 ft"))
    return d


def test_index_from_a_pdf_page():
    for separate in (False, True):
        d = _pdf(separate)
        idx = to.TraceIndex.from_page(d[0])
        a = idx.snap(_p(0, 0), 3)
        b = idx.snap(_p(40, 20), 3)
        c = idx.snap(_p(30, 30), 3)
        assert a and b and c
        pts = [(a.x, a.y)] + idx.between(a, b) + [(b.x, b.y)] + \
            idx.between(b, c) + [(c.x, c.y)] + idx.between(c, a)
        assert len(pts) == 6, (separate, pts)
        assert abs(to.measures(pts, PPU)["area"] - 1100) < 0.5


def test_trace_outline_tool_in_the_app(qapp, win, tmp_path):
    from app import annotate, settings
    path = str(tmp_path / "slab.pdf")
    _pdf().save(path)
    win.open_path(path)
    v = win._view
    win.set_tool("trace_outline", ask=False)
    assert v.tool == "trace_outline"
    assert "corners" in v.hint()
    z = v.zoom
    # four rough clicks (a few pixels off each corner); the last one back
    # on the start closes and finishes the outline
    for x, y in ((0, 0), (40, 20), (30, 30), (0, 0)):
        px, py = _p(x, y)
        q = v.snap_point(fitz.Point(px + 3 / z, py - 2 / z))
        assert abs(q.x - px) < 1e-6 and abs(q.y - py) < 1e-6
        v.trace_click(q)
    items = [it for it in annotate.takeoff_items(v.doc)
             if it["type"] == "area"]
    assert len(items) == 1
    assert abs(items[0]["value"] - 1100) < 0.5
    assert v._pts == []
    # Ctrl+click (follow off): straight from point to point
    for x, y in ((0, 0), (40, 20), (0, 30)):
        q = v.snap_point(fitz.Point(*_p(x, y)))
        v.trace_click(q, follow=False)
    assert len(v._pts) == 3
    v._finish_points()
    items = [it for it in annotate.takeoff_items(v.doc)
             if it["type"] == "area"]
    assert sorted(round(it["value"]) for it in items) == [600, 1100]
    # Alt = a free point, off the linework
    q = v.snap_point(fitz.Point(*_p(20, 10)), alt=True)
    assert (q.x, q.y) == _p(20, 10)
    # the follow switch in the Takeoff menu
    win.trace_follow_act.setChecked(False)
    assert settings.get("trace_follow") is False
    win.trace_follow_act.setChecked(True)
    win.undo()
    assert len([it for it in annotate.takeoff_items(v.doc)
                if it["type"] == "area"]) == 1
