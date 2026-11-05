"""Nov 1: reshape a drawn outline by its corners (its quantity follows,
an AI one becomes 'AI, edited'), select several markups at once (box or
Ctrl+click, combined total, delete / move to an item together), and the
Origin column in the Markups List."""
import os

import pytest

fitz = pytest.importorskip("fitz")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import annotate  # noqa: E402

PPU = 10.0                     # 10 points per foot


def _doc():
    d = fitz.open()
    d.new_page(width=800, height=600)
    annotate.apply_op(d, {"kind": "set_scale", "page": 0, "id": "sc",
                          "payload": {"ppu": PPU, "unit": "ft"}}, fresh=True)
    return d


def _op(d, oid, kind, payload):
    return annotate.apply_op(d, {"kind": kind, "page": 0, "id": oid,
                                 "payload": payload}, fresh=True)


def _area(d, oid="a1", pts=None, method="manual", group="Office",
          extra=None):
    pts = pts or [[100, 100], [200, 100], [200, 200], [100, 200]]
    p = {"pts": pts, "label": f"{group}: 100.00 sq ft",
         "measure": {"type": "area", "value": 100.0, "unit": "sq ft",
                     "group": group, "method": method}}
    p.update(extra or {})
    assert _op(d, oid, "add_polygon", p)
    return oid


class _S:
    """What a test needs of a markup, read while its page is loaded (an
    annotation must not outlive the page object it came from)."""


def _shape(d, oid):
    pg = d[0]
    a = [x for x in annotate.find_annots(pg, {"target": oid})
         if annotate.reshapable(d, x)][0]
    s = _S()
    s.subject = (a.info or {}).get("subject", "")
    s.value = s.subject.split(":")[2]
    s.tag = annotate.tag_of(a)
    s.status = annotate.status_of(d, a)
    s.mult = annotate.multiplier_of(d, a)
    s.verts = [tuple(map(round, v)) for v in (a.vertices or [])]
    s.audit = annotate.audit_of(d, a)
    s.origin = annotate.origin(d, a)
    s.pending = annotate.is_pending(d, a)
    return s


def _badges(d):
    pg = d[0]
    return [fitz.Rect(a.rect) for a in pg.annots() if annotate.is_badge(d, a)]


def _label(d, oid):
    pg = d[0]
    return [(a.info or {}).get("content", "")
            for a in annotate.find_annots(pg, {"target": oid})
            if d.xref_get_key(a.xref, "PSLabel")[1] == "true"]


def test_reshape_area_measures_again_and_keeps_everything():
    d = _doc()
    _area(d)
    _op(d, "st", "set_annot", {"target": "a1", "status": "Accepted",
                               "multiplier": 2})
    new = [[100, 100], [300, 100], [300, 200], [100, 200]]        # 20 x 10
    assert _op(d, "rs", "set_vertices", {"target": "a1", "pts": new,
                                         "ppu": PPU})
    a = _shape(d, "a1")
    assert a.tag == "a1"
    assert a.value == "200.0"
    assert a.status == "Accepted"
    assert a.mult == 2
    assert a.verts == [tuple(p) for p in new]
    assert any("200.00 sq ft" in t for t in _label(d, "a1"))
    assert a.audit["edited"]["at"]
    assert a.origin == "manual"                         # hand-made stays
    its = [it for it in annotate.takeoff_items(d) if it["tag"] == "a1"]
    assert its[0]["value"] == pytest.approx(400.0)     # x 2 typical


def test_reshaped_ai_measurement_is_ai_edited():
    d = _doc()
    _area(d, method="AI takeoff: rooms")
    assert _shape(d, "a1").origin == "ai-pending"
    _op(d, "rs", "set_vertices", {"target": "a1", "ppu": PPU,
                                  "pts": [[100, 100], [250, 100],
                                          [250, 200], [100, 200]]})
    assert _shape(d, "a1").origin == "ai-edited"
    assert annotate.ORIGIN_TEXT["ai-edited"] == "AI, edited"
    row = [m for m in annotate.markup_items(d)
           if m["ref"] == {"target": "a1"}][0]
    assert row["origin"] == "AI, edited"


def test_scale_from_the_page_when_none_given():
    d = _doc()
    _area(d)
    _op(d, "rs", "set_vertices", {"target": "a1", "pts": [
        [100, 100], [200, 100], [200, 300], [100, 300]]})
    assert _shape(d, "a1").value == "200.0"


def test_polyline_and_line_lengths():
    d = _doc()
    _op(d, "l1", "add_polyline", {"pts": [[0, 0], [100, 0]], "label": "10 ft",
                                  "measure": {"type": "length", "value": 10,
                                              "unit": "ft", "group": "Wall"}})
    _op(d, "rs", "set_vertices", {"target": "l1", "ppu": PPU,
                                  "pts": [[0, 0], [100, 0], [100, 50]]})
    assert _shape(d, "l1").value == "15.0"
    _op(d, "l2", "add_line", {"pts": [[0, 100], [100, 100]], "label": "10",
                              "measure": {"type": "length", "value": 10,
                                          "unit": "ft", "group": "Pipe"}})
    assert not _op(d, "bad", "set_vertices", {"target": "l2", "ppu": PPU,
                                              "pts": [[0, 0], [1, 1],
                                                      [2, 2]]})
    assert _op(d, "ok", "set_vertices", {"target": "l2", "ppu": PPU,
                                         "pts": [[0, 100], [200, 100]]})
    assert _shape(d, "l2").value == "20.0"


def test_area_needs_three_corners():
    d = _doc()
    _area(d)
    assert not _op(d, "rs", "set_vertices", {"target": "a1", "ppu": PPU,
                                             "pts": [[0, 0], [10, 10]]})


def test_volume_keeps_its_depth():
    d = _doc()
    _op(d, "v1", "add_polygon", {
        "pts": [[100, 100], [200, 100], [200, 200], [100, 200]],
        "label": "50 cu ft", "measure": {"type": "volume", "value": 50.0,
                                         "unit": "cu ft", "group": "Slab"}})
    _op(d, "rs", "set_vertices", {"target": "v1", "ppu": PPU, "pts": [
        [100, 100], [300, 100], [300, 200], [100, 200]]})
    assert _shape(d, "v1").value == "100.0"


def test_badge_and_hatch_follow():
    d = _doc()
    _area(d, method="AI takeoff: rooms" + annotate.REVIEW_SUFFIX,
          extra={"badge": True})
    assert _badges(d)
    _op(d, "rs", "set_vertices", {"target": "a1", "ppu": PPU, "pts": [
        [300, 300], [400, 300], [400, 400], [300, 400]]})
    badges = _badges(d)
    assert len(badges) == 1 and badges[0].y1 <= 301
    assert _shape(d, "a1").pending                     # still in review


# ---- the window ------------------------------------------------------------
from test_gui import win, qapp  # noqa: E402,F401


def _win_area(win, oid, pts, group="Office"):
    v = win._view
    v.apply_marks([(v.page, "set_scale", {"ppu": PPU, "unit": "ft"})])
    v.apply_marks([(v.page, "add_polygon", {
        "pts": pts, "label": f"{group}: x",
        "measure": {"type": "area", "value": 1.0, "unit": "sq ft",
                    "group": group}})])
    return v


def _find(v, group):
    for a in annotate.iter_annots(v.pg):
        if (a.info or {}).get("subject", "").endswith(":" + group) and \
                annotate.reshapable(v.doc, a):
            return a
    return None


def test_window_drag_corner_add_corner_remove_corner_undo(win):
    v = win._view
    v.set_zoom(1.0)
    _win_area(win, "w1", [[100, 100], [200, 100], [200, 200], [100, 200]])
    a = _find(v, "Office")
    v.select(a)
    hs = v.vertex_handles()
    assert sum(1 for h in hs if not h[2]) == 4 and \
        sum(1 for h in hs if h[2]) == 4
    corner = [h for h in hs if not h[2]][2][0]          # (200, 200)
    assert v.handle_at(corner) == (2, False)
    assert v.drag_vertex(2, fitz.Point(corner.x + 100, corner.y))
    a = _find(v, "Office")
    assert float((a.info or {})["subject"].split(":")[2]) > 100
    n = len(a.vertices)
    assert v.drag_vertex(0, fitz.Point(150, 80), mid=True)   # a 5th corner
    assert len(_find(v, "Office").vertices) == n + 1
    assert v.remove_vertex(1)
    assert len(_find(v, "Office").vertices) == n
    win.undo()
    assert len(_find(v, "Office").vertices) == n + 1


def test_window_box_select_totals_delete_and_reassign(win):
    v = win._view
    v.set_zoom(1.0)
    _win_area(win, "b1", [[300, 300], [320, 300], [320, 320], [300, 320]],
              group="Room A")
    _win_area(win, "b2", [[340, 300], [360, 300], [360, 320], [340, 320]],
              group="Room B")
    n = v.select_in_rect(annotate.from_page(v.pg, fitz.Rect(290, 290,
                                                            370, 330)))
    assert n >= 2 and len(v.selected_refs()) >= 2
    tot, _others = v.multi_totals()
    assert tot[("area", "sq ft")][0] >= 2
    assert "selected" in v.multi_summary()
    assert v.reassign_selected("Room C")
    groups = {it["group"] for it in annotate.takeoff_items(v.doc)
              if it["page"] == v.page}
    assert "Room C" in groups and "Room A" not in groups
    v.select_in_rect(annotate.from_page(v.pg, fitz.Rect(290, 290, 370, 330)))
    assert v.delete_selected()
    assert not any(it["group"] == "Room C" for it in
                   annotate.takeoff_items(v.doc))
    win.undo()
    assert any(it["group"] == "Room C" for it in
               annotate.takeoff_items(v.doc))


def test_window_ctrl_click_toggles(win):
    v = win._view
    _win_area(win, "c1", [[500, 100], [520, 100], [520, 120], [500, 120]],
              group="X1")
    _win_area(win, "c2", [[540, 100], [560, 100], [560, 120], [540, 120]],
              group="X2")
    a, b = _find(v, "X1"), _find(v, "X2")
    v.select(a)
    v.select(b, add=True)
    assert len(v.multi) == 2
    v.select(b, add=True)                        # out again
    assert v.multi == [] and v.selected["ref"] == annotate.ref(a)
    v.select(None)
    assert v.selected is None and v.multi == []


def test_markups_list_has_origin_column(tmp_path):
    from app import docks
    assert docks.MarkupsPanel.COLS[-1] == "Origin"
