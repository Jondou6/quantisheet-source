"""Auto takeoff: room areas traced from the walls."""
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import annotate, autotakeoff                       # noqa: E402
from test_gui import win, qapp                              # noqa: E402,F401

PPF = 18.0                    # 1/4" = 1'-0": 18 points per foot
OX, OY = 90.0, 90.0           # where the building starts on the page


def _ft(x, y):
    return fitz.Point(OX + x * PPF, OY + y * PPF)


def _wall(page, x0, y0, x1, y1):
    page.draw_rect(fitz.Rect(_ft(x0, y0), _ft(x1, y1)), color=(0, 0, 0),
                   fill=(0, 0, 0), width=0)


def make_plan(path=None):
    """Two rooms with 6" walls: OFFICE 20' x 15' (300 SF) and STORAGE
    12' x 15' (180 SF), a 3' door between them, a 3' door to outside,
    a toilet-sized fixture in the office, dimension and door-swing lines,
    and a room tag in each."""
    d = fitz.open()
    pg = d.new_page(width=900, height=600)
    _wall(pg, 0, 0, 33.5, 0.5)                 # top
    _wall(pg, 0, 15.5, 8, 16)                  # bottom, door at 8'-11'
    _wall(pg, 11, 15.5, 33.5, 16)
    _wall(pg, 0, 0, 0.5, 16)                   # left
    _wall(pg, 33, 0, 33.5, 16)                 # right
    _wall(pg, 20.5, 0.5, 21, 6)                # partition, door at 6'-9'
    _wall(pg, 20.5, 9, 21, 15.5)
    _wall(pg, 4, 4, 6, 5.5)                    # fixture, free-standing
    # thin lines that aren't walls: a door swing and a dimension
    pg.draw_line(_ft(8, 15.5), _ft(8, 12.5), color=(0, 0, 0), width=0.5)
    pg.draw_line(_ft(0, 18), _ft(33.5, 18), color=(0, 0, 0), width=0.5)
    pg.insert_text(_ft(12, 18.6), "33'-6\"", fontsize=7)
    pg.insert_text(_ft(8, 6), "OFFICE\n300 SF", fontsize=8)
    pg.insert_text(_ft(25, 6), "STORAGE\n180 SF", fontsize=8)
    annotate.apply_op(d, annotate.new_op("set_scale", 0, ppu=PPF, unit="ft"))
    if path:
        d.save(path)
    return d


def _scale(d):
    return annotate.read_scales(d)[0]


def test_room_tags_read_name_and_area():
    d = make_plan()
    tags = autotakeoff.room_tags(d[0])
    assert [(t["name"], t["sf"]) for t in tags] == [("OFFICE", 300),
                                                    ("STORAGE", 180)]


def test_click_a_room_traces_its_floor_area():
    d = make_plan()
    room = autotakeoff.room_at(d[0], _scale(d), _ft(14, 11))
    assert room["name"] == "OFFICE" and room["tag_sf"] == 300
    assert room["value"] == pytest.approx(300, rel=0.03)
    assert room["unit"] == "sq ft"
    xs = [p.x for p in room["pts"]]
    ys = [p.y for p in room["pts"]]
    # along the inside faces of the walls; door openings are closed off
    # within the wall's thickness (6" = 9 pt), not followed outside
    assert min(xs) == pytest.approx(_ft(0.5, 0).x, abs=3)
    assert max(xs) == pytest.approx(_ft(20.5, 0).x, abs=7)
    assert max(ys) == pytest.approx(_ft(0, 15.5).y, abs=7)
    room = autotakeoff.room_at(d[0], _scale(d), _ft(27, 12))
    assert room["name"] == "STORAGE"
    assert room["value"] == pytest.approx(180, rel=0.03)


def test_whole_sheet_and_measured_rooms_count_as_walls():
    d = make_plan()
    found, missed = autotakeoff.all_rooms(d[0], _scale(d))
    assert not missed
    got = {r["name"]: r["value"] for r in found}
    assert got == pytest.approx({"OFFICE": 300, "STORAGE": 180}, rel=0.03)
    # measure the office; clicking it again is refused, and a second pass
    # over the sheet only finds the storage room
    office = next(r for r in found if r["name"] == "OFFICE")
    pts = [fitz.Point(p) * d[0].derotation_matrix for p in office["pts"]]
    annotate.apply_op(d, annotate.new_op(
        "add_polygon", 0, pts=[[p.x, p.y] for p in pts],
        measure={"type": "area", "value": office["value"], "unit": "sq ft",
                 "group": "OFFICE"}))
    with pytest.raises(autotakeoff.AutoTakeoffError):
        autotakeoff.room_at(d[0], _scale(d), _ft(14, 11))
    found, missed = autotakeoff.all_rooms(d[0], _scale(d))
    assert [r["name"] for r in found] == ["STORAGE"] and not missed


def test_rotated_sheet():
    d = make_plan()
    d[0].set_rotation(90)
    tags = autotakeoff.room_tags(d[0])
    office = next(t for t in tags if t["name"] == "OFFICE")
    # click a little off the tag, in screen coordinates
    room = autotakeoff.room_at(d[0], _scale(d),
                               office["pt"] + fitz.Point(-20, 30))
    assert room["value"] == pytest.approx(300, rel=0.03)


def test_no_scale_and_open_space():
    d = make_plan()
    with pytest.raises(autotakeoff.AutoTakeoffError):
        autotakeoff.room_at(d[0], None, _ft(14, 11))
    with pytest.raises(autotakeoff.AutoTakeoffError):     # outside
        autotakeoff.room_at(d[0], _scale(d), fitz.Point(800, 550))


def test_auto_area_tool_and_whole_sheet_in_the_app(win, tmp_path):
    path = str(tmp_path / "rooms.pdf")
    make_plan(path)
    assert win.open_path(path)
    v = win._view
    v.style["subject"] = ""
    assert v.commit_click("auto_area", _ft(14, 11)) == 1
    items = annotate.takeoff_items(v.doc)
    assert len(items) == 1 and items[0]["group"] == "OFFICE"
    assert items[0]["value"] == pytest.approx(300, rel=0.03)
    win.undo()
    assert not annotate.takeoff_items(win._view.doc)
    win.auto_takeoff_rooms()
    items = annotate.takeoff_items(win._view.doc)
    assert sorted(i["group"] for i in items) == ["OFFICE", "STORAGE"]
    win.undo()                                   # one step for the sheet
    assert not annotate.takeoff_items(win._view.doc)


def test_tag_area_used_when_trace_is_off_and_scale_check():
    from app import autotakeoff as at

    def room(sf, tag, value=None):
        return {"sqft": sf, "tag_sf": tag, "value": value or sf,
                "unit": "sq ft", "pts": [], "name": "R"}
    found = [room(100, 102), room(80, 100), room(50, 50), room(30, None)]
    assert at.scale_ratio(found) == pytest.approx(1.0, abs=0.05)
    assert not at.scale_looks_wrong(found)
    assert at.prefer_tags(found) == 1
    r = found[1]
    assert r["per_tag"] and r["sqft"] == 100 and r["traced_sf"] == 80 and \
        r["value"] == pytest.approx(100)
    assert not found[0].get("per_tag") and found[3]["sqft"] == 30
    # every room off by the same factor: the scale is wrong - leave them
    bad = [room(25, 100), room(26, 100), room(24.5, 100)]
    assert at.scale_looks_wrong(bad) and at.prefer_tags(bad) == 0
    assert at.scale_ratio([room(1, 2)]) is None


def test_addendum_markers_are_not_rooms():
    doc = fitz.open()
    pg = doc.new_page(width=1224, height=792)
    pg.insert_text((200, 200), "OFFICE 102", fontsize=8)
    pg.insert_text((400, 200), "ASI 0042", fontsize=8)
    pg.insert_text((400, 300), "RFI 012", fontsize=8)
    pg.insert_text((600, 300), "JAN 113", fontsize=8)
    names = [r["name"] for r in autotakeoff.room_labels(pg)]
    assert names == ["OFFICE 102", "JAN 113"] or \
        sorted(names) == ["JAN 113", "OFFICE 102"]


def test_room_in_a_detail_at_its_own_scale():
    """An enlarged detail drawn at 1/2" = 1'-0" on a 1/4" sheet: the room
    is measured at the detail's scale, not the sheet's."""
    d = fitz.open()
    pg = d.new_page(width=1224, height=792)
    k = 36.0                                   # 1/2" = 1'-0"
    x0, y0 = 120.0, 120.0

    def w(a, b, c, e):
        pg.draw_rect(fitz.Rect(x0 + a * k, y0 + b * k, x0 + c * k,
                               y0 + e * k), color=(0, 0, 0), fill=(0, 0, 0),
                     width=0)
    w(0, 0, 10.5, 0.5)
    w(0, 10, 10.5, 10.5)
    w(0, 0, 0.5, 10.5)
    w(10, 0, 10.5, 10.5)
    pg.insert_text((x0 + 4 * k, y0 + 5 * k), "OFFICE\n100 SF", fontsize=8)
    pg.insert_text((x0, y0 + 12 * k), "2  ENLARGED OFFICE", fontsize=12)
    pg.insert_text((x0, y0 + 12.6 * k), 'SCALE: 1/2" = 1\'-0"', fontsize=7)
    found, missed = autotakeoff.all_rooms(pg, {"ppu": 18.0, "unit": "ft"},
                                          skip_measured=False)
    assert not missed
    (r,) = found
    # 9.5' x 9.5' inside, 10.5' x 10.5' outside: at the sheet's 1/4"
    # it would come out a quarter of that (about 25 SF)
    assert 85 <= r["sqft"] <= 115
    assert r["detail_scale"] == '1/2" = 1\'-0"'


def test_closet_tag_outside_on_a_leader():
    d = fitz.open()
    pg = d.new_page(width=900, height=600)
    x0, y0 = 300.0, 200.0                      # closet 4' x 3' inside

    def w(a, b, c, e):
        pg.draw_rect(fitz.Rect(x0 + a * PPF, y0 + b * PPF, x0 + c * PPF,
                               y0 + e * PPF), color=(0, 0, 0),
                     fill=(0, 0, 0), width=0)
    w(0, 0, 5, 0.5)
    w(0, 3.5, 5, 4)
    w(0, 0, 0.5, 4)
    w(4.5, 0, 5, 4)
    tx, ty = x0 - 110, y0 + 2 * PPF
    pg.insert_text((tx, ty), "JAN\n12 SF", fontsize=7)
    tag = autotakeoff.room_tags(pg)[0]
    pg.draw_line((tag["pt"].x + 14, tag["pt"].y),
                 (x0 + 2.5 * PPF, y0 + 2 * PPF), color=(0, 0, 0), width=0.25)
    found, missed = autotakeoff.all_rooms(pg, {"ppu": PPF, "unit": "ft"},
                                          skip_measured=False)
    assert not missed
    assert abs(found[0]["sqft"] - 12) <= 2
