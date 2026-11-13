"""Nov 12: rooms on a sheet whose walls are drawn solid on wall layers,
and stall doors. What the checked Harbor Springs sheet showed, rebuilt
as made-up drawings with exact areas."""
import math
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")
import fitz                                                   # noqa: E402

from app import autotakeoff as at                             # noqa: E402

PPF = 18.0                       # 1/4" = 1'-0"
SCALE = {"ppu": PPF, "unit": "ft"}
T = 12.0                         # 8" walls
# the shower room's inside: 14' x 11'
AX0, AY0, AX1, AY1 = 100.0, 100.0, 352.0, 298.0
BX0, BX1 = AX1 + T, AX1 + T + 180.0     # the room beside it: 10' x 11'
INSIDE = [(AX0, 226.0, 124.0, 238.0),   # stub at the first stall front
          (171.0, 226.0, 183.0, AY1),   # stall partitions, solid
          (254.0, 226.0, 266.0, AY1)]
A_SF = ((AX1 - AX0) * (AY1 - AY0) -
        sum((x1 - x0) * (y1 - y0) for x0, y0, x1, y1 in INSIDE)) / PPF ** 2
B_SF = (BX1 - BX0) * (AY1 - AY0) / PPF ** 2


def _tag(page, x, y, name, no, fs=7):
    for i, s in enumerate((name, no)):
        wd = fitz.get_text_length(s, fontsize=fs)
        page.insert_text((x - wd / 2, y + i * fs * 1.15), s, fontsize=fs)


def _solid(sh, oc, x0, y0, x1, y1, piece=40.0):
    """A filled wall, drawn in pieces (as CAD exports do)."""
    if x1 - x0 >= y1 - y0:
        x = x0
        while x < x1 - 1e-6:
            sh.draw_rect(fitz.Rect(x, y0, min(x + piece, x1), y1))
            sh.finish(color=(0, 0, 0), fill=(0, 0, 0), width=0, oc=oc)
            x += piece
    else:
        y = y0
        while y < y1 - 1e-6:
            sh.draw_rect(fitz.Rect(x0, y, x1, min(y + piece, y1)))
            sh.finish(color=(0, 0, 0), fill=(0, 0, 0), width=0, oc=oc)
            y += piece


def _arc(sh, c, r, a0, a1, oc, width=0.3):
    k = 4 / 3 * math.tan((a1 - a0) / 4)
    p0 = fitz.Point(c.x + r * math.cos(a0), c.y + r * math.sin(a0))
    p3 = fitz.Point(c.x + r * math.cos(a1), c.y + r * math.sin(a1))
    p1 = fitz.Point(p0.x - k * r * math.sin(a0), p0.y + k * r * math.cos(a0))
    p2 = fitz.Point(p3.x + k * r * math.sin(a1), p3.y - k * r * math.cos(a1))
    sh.draw_bezier(p0, p1, p2, p3)
    sh.finish(color=(0, 0, 0), width=width, oc=oc)


def shower_sheet(stall_door=False):
    doc = fitz.open()
    page = doc.new_page(width=700, height=420)
    wall = doc.add_ocg("A-WALL")
    sh = page.new_shape()
    # the outside walls and the wall between the rooms, with a 3' door
    # at the left end of the top wall (its leaf opens against the left
    # wall, 4" off it) and a 3' door between the rooms
    _solid(sh, wall, AX0 - T, AY0 - T, AX0 + 6, AY0)
    _solid(sh, wall, AX0 + 60, AY0 - T, BX1 + T, AY0)            # top
    _solid(sh, wall, AX0 - T, AY1, BX1 + T, AY1 + T)             # bottom
    _solid(sh, wall, AX0 - T, AY0, AX0, AY1)                     # left
    _solid(sh, wall, BX1, AY0, BX1 + T, AY1)                     # right
    _solid(sh, wall, AX1, AY0, AX1 + T, 130.0)                   # between,
    _solid(sh, wall, AX1, 184.0, AX1 + T, AY1)                   # door gap
    for r in INSIDE:
        _solid(sh, wall, *r)
    thin = dict(color=(0, 0, 0), width=0.3, oc=wall)
    # door 1: hinge at the top wall, leaf open 90 degrees into the room
    sh.draw_rect(fitz.Rect(AX0 + 6, AY0, AX0 + 8.25, AY0 + 54))
    sh.finish(**thin)
    _arc(sh, fitz.Point(AX0 + 6, AY0), 54.0, math.pi / 2, 0.0, wall)
    # door 2 (between the rooms): leaf open into the shower room
    sh.draw_rect(fitz.Rect(AX1 - 54, 130.0, AX1, 132.25))
    sh.finish(**thin)
    _arc(sh, fitz.Point(AX1, 130.0), 54.0, math.pi, math.pi / 2, wall)
    # things the wall layer also carries: a shelf on the right wall...
    sh.draw_rect(fitz.Rect(AX1 - 3, 196.0, AX1, 222.0))
    sh.finish(**thin)
    for y in (200.0, 208.0, 216.0):
        sh.draw_rect(fitz.Rect(AX1 - 6, y, AX1 - 3, y + 1.2))
        sh.finish(color=(0, 0, 0), fill=(0, 0, 0), width=0, oc=wall)
    # ...a shower curtain along the stall fronts...
    x = 124.0
    while x < AX1 - 6:
        sh.draw_line((x, 232.0), (x + 3, 230.5))
        sh.draw_line((x + 3, 230.5), (x + 6, 232.0))
        sh.finish(color=(0, 0, 0), width=0.5, oc=wall)
        x += 6
    # ...and a bench in the first stall
    sh.draw_rect(fitz.Rect(AX0, 246.0, AX0 + 15, 290.0))
    sh.finish(**thin)
    sh.draw_line((AX0 + 11, 246.0), (AX0 + 11, 290.0))
    sh.finish(**thin)
    if stall_door:
        # toilet partitions (not walls, no wall layer) in the other room,
        # and a stall door hung on a partition post: it shuts onto the
        # other post, and its open leaf's tip rests by the bottom wall
        hx, hy = BX0 + 60.0, AY1 - 56.0
        sh.draw_line((BX0 + 60, AY1 - 56), (BX0 + 60, AY1))
        sh.draw_line((BX0 + 60, AY1 - 56), (BX0 + 66, AY1 - 56))
        sh.draw_line((BX0 + 114, AY1 - 56), (BX1, AY1 - 56))
        sh.finish(color=(0, 0, 0), width=0.4)
        sh.draw_line((hx + 6, hy), (hx + 6, hy + 54))          # open leaf
        sh.finish(color=(0, 0, 0), width=0.3)
        _arc(sh, fitz.Point(hx + 6, hy), 54.0, math.pi / 2, 0.0, None)
    sh.commit()
    _tag(page, 226.0, 166.0, "SHOWER", "201")
    _tag(page, (BX0 + BX1) / 2, 180.0, "STORAGE", "202")
    return doc, page


def _rooms(page):
    found, missed = at.all_rooms(at.cached_page(page), SCALE,
                                 skip_measured=False)
    by = {}
    for r in found:
        by[str(r.get("number") or at.room_number(r.get("name") or ""))] = r
    return by, missed


def _sf(r):
    return r.get("net_sf") or r.get("sqft")


def test_the_sheet_is_read_as_wall_layers_drawn_solid():
    doc, page = shower_sheet()
    pg = at.cached_page(page)
    assert at.wall_layers(pg) == frozenset({"A-WALL"})
    plan = at.Plan(pg, SCALE, claimed=False)
    assert plan.wl is not None and plan.doors_closed == 2


def test_room_runs_to_the_solid_walls_past_what_hangs_on_them():
    doc, page = shower_sheet()
    by, missed = _rooms(page)
    assert not missed and {"201", "202"} <= set(by)
    a = _sf(by["201"])
    # behind the open door, beside the shelf, the stall fronts from jamb
    # to jamb and the bench: all floor
    assert abs(a - A_SF) <= 0.012 * A_SF, (a, A_SF)
    assert abs(_sf(by["202"]) - B_SF) <= 0.012 * B_SF


def test_without_it_the_room_came_out_short(monkeypatch):
    monkeypatch.setattr(at.Plan, "_fill_to_solid", lambda self, c, o=(): None)
    doc, page = shower_sheet()
    by, _missed = _rooms(page)
    a = _sf(by["201"]) if "201" in by else 0.0
    assert a < A_SF * 0.985, (a, A_SF)      # the 4% the real sheet lost


def test_walls_drawn_as_lines_are_left_to_the_older_fill():
    # two-line (hollow) walls on a wall layer: nothing solid to run to
    doc = fitz.open()
    page = doc.new_page(width=500, height=400)
    wall = doc.add_ocg("A-WALL")
    sh = page.new_shape()
    for k in range(12):                        # enough paths to be a layer
        for off in (0.0, 9.0):
            sh.draw_rect(fitz.Rect(100 - off, 100 - off, 316 + off,
                                   280 + off))
            sh.finish(color=(0, 0, 0), width=0.5, oc=wall)
    for i in range(50):
        sh.draw_line((330 + i, 50), (330 + i, 52))
        sh.finish(color=(0, 0, 0), width=0.2)
    sh.commit()
    _tag(page, 208.0, 186.0, "OFFICE", "301")
    pg = at.cached_page(page)
    plan = at.Plan(pg, SCALE, claimed=False)
    c = np.array([[[140, 140]], [[140, 360]], [[410, 360]], [[410, 140]]],
                 np.int32)
    assert plan.wl is not None
    assert plan._fill_to_solid(c) is None
    by, _m = _rooms(page)
    assert abs(_sf(by["301"]) - 12 * 10) <= 0.02 * 120


def test_a_stall_door_is_not_shut_along_its_open_leaf():
    doc, page = shower_sheet(stall_door=True)
    pg = at.cached_page(page)
    swings = at.door_swings(pg, PPF)
    assert len(swings) == 3                        # the stall door is read
    plan = at.Plan(pg, SCALE, claimed=False)
    assert plan.doors_closed == 2                  # ...but only doors shut
    # no bar of "wall" down the open leaf, out on the floor
    z = plan.zoom
    x = int(round((BX0 + 66.0) * z))
    y0, y1 = int(round((AY1 - 46.0) * z)), int(round((AY1 - 12.0) * z))
    assert not plan._doorlines[y0:y1, x - 3:x + 4].any()
    by, missed = _rooms(page)
    assert abs(_sf(by["202"]) - B_SF) <= 0.02 * B_SF, _sf(by["202"])


# ---- door count ------------------------------------------------------------

def _swing(page, hx, hy, r_ft):
    sh = page.new_shape()
    r = r_ft * PPF
    sh.draw_line((hx, hy), (hx, hy + r))
    sh.finish(color=(0, 0, 0), width=0.3)
    _arc(sh, fitz.Point(hx, hy), r, math.pi / 2, 0.0, None)
    sh.commit()


def test_a_two_six_door_counts_and_a_stall_door_does_not():
    from app import autowalls
    doc = fitz.open()
    page = doc.new_page(width=900, height=300)
    # 2'-6" drawn a hair short, exactly, and a hair long; a 2'-2" stall
    # door; a 3'-0" door
    for i, r in enumerate((2.5 - 0.004, 2.5, 2.5 + 0.004, 2.17, 3.0)):
        _swing(page, 80 + i * 150, 60, r)
    ds = autowalls.doors(page, PPF, "ft")
    assert sorted(round(d["width"], 1) for d in ds) == [2.5, 2.5, 2.5, 3.0]
    every = autowalls.doors(page, PPF, "ft", include_narrow=True)
    assert len(every) == 5 and sum(1 for d in every if d["narrow"]) == 1


def test_doors_on_the_hard_plans_are_counted():
    import sys
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(root, "tools"))
    import accuracy_hard
    rows = accuracy_hard.doors_score(3, seed=21, verbose=False)
    assert len(rows) == 3
    for _i, t1, t2, f1, f2, _other in rows:
        assert (f1, f2) == (t1, t2), rows


# ---- Auto Area: a click in a room -------------------------------------------

def test_a_click_finds_the_room_on_a_hard_plan():
    """A third of the clicks found no room: where a space ran on through
    a cased opening it held two tags, none was taken as the room's own,
    and every outline was turned down for holding "another room's" tag."""
    import sys
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(root, "tools"))
    import accuracy_hard
    got = accuracy_hard.click_score(1, seed=21, verbose=False)
    n = got["rooms"]
    assert n >= 15
    assert got["found"] == n, got["worst"]
    assert got["within2"] >= 0.95 * n and got["within5"] == n, got["worst"]


def test_a_click_in_a_named_room_does_not_take_the_room_next_door():
    doc, page = shower_sheet()
    res = at.room_at(page, SCALE, fitz.Point(226.0, 200.0))
    assert abs(res["sqft"] - A_SF) <= 0.012 * A_SF
    assert "SHOWER" in str(res.get("name"))
    res = at.room_at(page, SCALE, fitz.Point(BX0 + 40.0, 250.0))
    assert abs(res["sqft"] - B_SF) <= 0.012 * B_SF
