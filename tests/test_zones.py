"""Nov 1: AI Takeoff zones - boxes drawn on a sheet decide which finished
results are kept (only here / leave out). Nothing is measured differently
and a room is kept or left out whole."""
import pytest

fitz = pytest.importorskip("fitz")

from app import annotate, zones  # noqa: E402


def _doc():
    d = fitz.open()
    d.new_page(width=800, height=600)
    d.new_page(width=800, height=600)
    return d


def _zone(d, rect, kind, page=0):
    p, k, pl = zones.mark(page, rect, kind)
    assert annotate.apply_op(d, {"kind": k, "page": p, "id": f"z{rect[0]}{kind}",
                                 "payload": pl}, fresh=True)


def _room(page, x0, y0, x1, y1, name="ROOM"):
    return (page, "add_polygon", {
        "pts": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
        "measure": {"type": "area", "group": name, "value": 1,
                    "method": "AI takeoff: rooms"}})


def _count(page, x, y, name="OUTLET"):
    return (page, "add_count", {"pt": [x, y], "n": 1, "measure": {
        "type": "count", "group": name, "value": 1,
        "method": "AI takeoff: devices"}})


def test_zone_is_a_markup_that_saves():
    d = _doc()
    _zone(d, [100, 100, 400, 400], "include")
    _zone(d, [500, 100, 700, 300], "exclude")
    z = zones.on_page(d, 0)
    assert len(z["include"]) == 1 and len(z["exclude"]) == 1
    d2 = fitz.open("pdf", d.tobytes())
    assert len(zones.on_page(d2, 0)["include"]) == 1     # survives save
    assert zones.on_page(d2, 1) == {"include": [], "exclude": []}
    assert set(zones.any_zones(d2)) == {0}


def test_only_here_keeps_what_is_inside():
    d = _doc()
    _zone(d, [100, 100, 400, 400], "include")
    marks = [(0, "set_scale", {"ppu": 10}),
             _room(0, 150, 150, 250, 250, "IN"),
             _room(0, 500, 150, 600, 250, "OUT"),
             _count(0, 200, 300), _count(0, 600, 500),
             _room(1, 500, 150, 600, 250, "OTHER SHEET")]
    kept, dropped = zones.filter_marks(d, marks)
    names = [m[2].get("measure", {}).get("group") for m in kept]
    assert names == [None, "IN", "OUTLET", "OTHER SHEET"]  # scale kept
    assert len(dropped) == 2


def test_leave_out_drops_what_is_inside():
    d = _doc()
    _zone(d, [600, 450, 800, 600], "exclude")             # a title block
    kept, dropped = zones.filter_marks(d, [_count(0, 700, 500),
                                           _count(0, 100, 100)])
    assert len(kept) == 1 and kept[0][2]["pt"] == [100, 100]


def test_room_kept_whole_by_its_middle_not_cut():
    d = _doc()
    _zone(d, [0, 0, 300, 600], "include")
    big = _room(0, 100, 100, 400, 200)                 # middle x=250: inside
    kept, _ = zones.filter_marks(d, [big])
    assert kept == [big]
    assert kept[0][2]["pts"][1] == [400, 100]          # outline unchanged


def test_l_shaped_room_by_its_centroid():
    d = _doc()
    _zone(d, [0, 0, 150, 600], "include")
    l_shape = (0, "add_polygon", {"pts": [[0, 0], [300, 0], [300, 40],
                                          [40, 40], [40, 300], [0, 300]],
                                  "measure": {"group": "L"}})
    kept, _ = zones.filter_marks(d, [l_shape])
    assert kept == [l_shape]


def test_no_zones_nothing_changes():
    d = _doc()
    marks = [_room(0, 10, 10, 50, 50), _count(1, 5, 5)]
    assert zones.filter_marks(d, marks) == (marks, [])


def test_check_items_follow_their_outlines():
    d = _doc()
    _zone(d, [100, 100, 400, 400], "include")
    marks = [_room(0, 500, 150, 600, 250, "STORAGE 9")]
    _kept, dropped = zones.filter_marks(d, marks)
    res = {"review": [{"page": 0, "name": "STORAGE 9", "engine": "rooms"},
                      {"page": 0, "name": "X", "rect": [600, 500, 620, 520]},
                      {"page": 0, "name": "Y", "rect": [200, 200, 220, 220]},
                      {"page": 1, "name": "STORAGE 9"}]}
    assert zones.filter_result(d, res, dropped) == 2
    assert [x["name"] for x in res["review"]] == ["Y", "STORAGE 9"]


def test_room_tools_still_take_no_ignore_pick():
    """The patent design rule (tests/test_patent_design_rules.py): zones
    are not an input of the room tools."""
    import inspect
    from app import autotakeoff
    for fn in (autotakeoff.room_at, autotakeoff.all_rooms):
        assert "zone" not in str(inspect.signature(fn))


# ---- the window ------------------------------------------------------------
from test_gui import win, qapp  # noqa: E402,F401


def test_window_draw_and_clear_zones(win):
    v = win._view
    assert v.add_zone(fitz.Rect(300, 300, 500, 500), "include") == 1
    assert v.add_zone(fitz.Rect(10, 10, 12, 12), "exclude") == 0   # too small
    assert len(zones.on_page(v.doc, v.page)["include"]) == 1
    assert v.clear_zones() == 1
    assert zones.on_page(v.doc, v.page)["include"] == []
    win.undo()
    assert len(zones.on_page(v.doc, v.page)["include"]) == 1
