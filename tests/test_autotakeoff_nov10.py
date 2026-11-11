"""Auto Takeoff Rooms, the Nov 10 deep dive: what the hard made-up plans
(tools/accuracy_hard.py) found. Made-up drawings only."""
import math
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")
import fitz                                                   # noqa: E402


# ---- walls: one line just under 180 degrees ------------------------------

def test_a_line_at_179_degrees_does_not_tip_the_walls():
    from app import autowalls as aw
    segs = [(100, 100, 500, 100), (100, 109, 500, 109),
            (100, 300, 600, 300), (100, 309, 600, 309)]
    a = math.radians(179.3)
    segs.append((700, 700, 700 + 40 * math.cos(a), 700 + 40 * math.sin(a)))
    ws = aw.walls(None, 18.0, "ft", segs=segs)
    assert len(ws) == 2
    for w in ws:
        (x0, y0), (x1, y1) = w["p0"], w["p1"]
        assert abs(y1 - y0) < 0.5, w            # was 11 degrees: 80 pt off
        assert abs(w["thickness"] - 6.0) < 0.2


def test_a_chain_of_directions_is_not_one_direction():
    from app import autowalls as aw
    segs = []
    for k in range(0, 40):                      # chords of an arc: 0-20 deg
        a = math.radians(k * 0.5)
        segs.append((100, 100 + 30 * k, 100 + 60 * math.cos(a),
                     100 + 30 * k + 60 * math.sin(a)))
    segs += [(1000, 100, 1400, 100), (1000, 109, 1400, 109)]
    ws = aw.walls(None, 18.0, "ft", segs=segs)
    flat = [w for w in ws if abs(w["p0"][0] - 1000) < 2]
    assert flat and abs(flat[0]["p1"][1] - flat[0]["p0"][1]) < 0.5


# ---- the outline on the drawing's lines -----------------------------------

def _trace(faces, seed, door=None):
    img = np.zeros((130, 180), np.uint8)
    for x0, y0, x1, y1 in faces:
        cv2.line(img, (round(x0), round(y0)), (round(x1), round(y1)), 1, 1)
    if door:
        cv2.line(img, door[0], door[1], 1, door[2])
    n, lab = cv2.connectedComponents((1 - img).astype(np.uint8),
                                     connectivity=4)
    room = (lab == lab[seed[1], seed[0]]).astype(np.uint8)
    cs, _ = cv2.findContours(room, cv2.RETR_EXTERNAL,
                             cv2.CHAIN_APPROX_SIMPLE)
    return max(cs, key=cv2.contourArea)


def _lines(faces):
    from app import roomsnap as rs
    pts = np.array([p for f in faces for p in ((f[0], f[1]), (f[2], f[3]))],
                   float)
    return rs.face_lines(pts, np.arange(0, len(pts) + 1, 2),
                         np.ones(len(faces), bool), 3)


def test_an_l_shaped_room_comes_out_exact():
    from app import roomsnap as rs
    faces = [(20.3, 15.6, 92.7, 15.6), (92.7, 15.6, 92.7, 63.2),
             (92.7, 63.2, 60.4, 63.2), (60.4, 63.2, 60.4, 45.1),
             (60.4, 45.1, 20.3, 45.1), (20.3, 45.1, 20.3, 15.6)]
    c = _trace(faces, (40, 30))
    true = (92.7 - 20.3) * (63.2 - 15.6) - (60.4 - 20.3) * (63.2 - 45.1)
    pts, share = rs.snap(c, 4.8, _lines(faces), 1.0)
    assert share == pytest.approx(1.0)
    assert rs.area(pts) == pytest.approx(true, rel=1e-6)
    # the picture alone was half a percent short
    raster = cv2.contourArea(c) + cv2.arcLength(c, True) * 1.0
    assert abs(raster - true) / true > 0.003


def test_a_side_with_a_shut_door_goes_to_the_wall_face():
    from app import roomsnap as rs
    # the face is in two pieces a third of a pixel apart, either side of
    # the door; the door's line sits a pixel inside it
    faces = [(20.3, 15.6, 141.3, 15.6), (141.3, 15.6, 141.3, 86.67),
             (141.3, 86.67, 117.6, 86.67), (57.3, 87.0, 20.3, 87.0),
             (20.3, 87.0, 20.3, 15.6)]
    c = _trace(faces, (60, 40), door=((57, 86), (118, 86), 2))
    pts, share = rs.snap(c, 4.8, _lines(faces), 1.0)
    assert share == pytest.approx(1.0)
    assert pts[:, 1].max() == pytest.approx(86.85, abs=0.2)
    assert rs.area(pts) == pytest.approx(121.0 * (86.85 - 15.6), rel=2e-3)


def test_a_side_with_no_line_beside_it_keeps_its_place():
    from app import roomsnap as rs
    faces = [(20.3, 15.6, 92.7, 15.6), (92.7, 15.6, 92.7, 63.2),
             (92.7, 63.2, 20.3, 63.2), (20.3, 63.2, 20.3, 15.6)]
    c = _trace(faces, (40, 30))
    lines = _lines(faces[:3])                     # the left face unknown
    pts, share = rs.snap(c, 4.8, lines, 1.0)
    assert 0.6 < share < 0.9
    assert pts[:, 0].min() == pytest.approx(20.0, abs=0.01)   # 21 - inset
    assert pts[:, 0].max() == pytest.approx(92.7)


def test_a_far_line_is_not_a_face():
    from app import roomsnap as rs
    faces = [(20.3, 15.6, 92.7, 15.6), (92.7, 15.6, 92.7, 63.2),
             (92.7, 63.2, 20.3, 63.2), (20.3, 63.2, 20.3, 15.6)]
    c = _trace(faces, (40, 30))
    other = faces[:3] + [(14.0, 63.2, 14.0, 15.6)]   # the wall's far face
    pts, _share = rs.snap(c, 4.8, _lines(other), 1.0)
    assert pts[:, 0].min() == pytest.approx(20.0, abs=0.01)


# ---- doors -----------------------------------------------------------------

def _page_with(draw):
    doc = fitz.open()
    pg = doc.new_page(width=600, height=400)
    sh = pg.new_shape()
    draw(sh)
    sh.commit()
    return doc, pg


def test_an_oval_is_not_four_door_swings():
    from app import autotakeoff as at

    def draw(sh):
        sh.draw_oval(fitz.Rect(100, 100, 260, 172))       # a table
        sh.finish(color=(0, 0, 0), width=0.3)
        sh.draw_oval(fitz.Rect(300, 100, 330, 150))       # a toilet
        sh.finish(color=(0, 0, 0), width=0.3)
    doc, pg = _page_with(draw)
    assert at.door_swings(at.cached_page(pg), 18.0) == []


def test_a_quarter_circle_is_still_a_swing():
    from app import autotakeoff as at

    def draw(sh):
        k = 0.5523
        r = 54.0
        c = fitz.Point(200, 200)
        sh.draw_line(c, (c.x, c.y + r))
        sh.finish(color=(0, 0, 0), width=0.3)
        sh.draw_bezier((c.x, c.y + r), (c.x + r * k, c.y + r),
                       (c.x + r, c.y + r * k), (c.x + r, c.y))
        sh.finish(color=(0, 0, 0), width=0.3)
    doc, pg = _page_with(draw)
    got = at.door_swings(at.cached_page(pg), 18.0)
    assert len(got) == 1
    assert abs(got[0][0] - fitz.Point(200, 200)) < 1.0


def test_a_wall_stub_is_kept_and_a_fixture_blob_is_not():
    from app import autotakeoff as at
    ppf = 24
    ink = np.zeros((300, 400), np.uint8)
    ink[20:32, 20:380] = 1                               # a wall
    ink[150:162, 100:135] = 1                            # a 1'-6" stub
    cv2.circle(ink, (300, 200), 14, 1, 1)                # a fixture
    cv2.circle(ink, (300, 200), 9, 1, 1)
    w = at.wall_mask(None, ppf, ink=ink.copy())
    assert w[156, 117] == 1
    assert w[195:205, 290:310].sum() == 0


# ---- the hard plans ---------------------------------------------------------

@pytest.fixture(scope="module")
def hard():
    import accuracy_hard
    return accuracy_hard.score(3, seed=21, verbose=False)


def test_every_room_on_the_hard_plans_is_found(hard):
    assert hard["found"] == hard["rooms"], hard
    assert hard["extra"] == 0, hard


def test_hard_plans_areas(hard):
    n = hard["rooms"]
    assert hard["within2"] >= 0.96 * n, hard      # 21% before Nov 10
    assert hard["within1"] >= 0.90 * n, hard
    assert hard["within5"] >= 0.98 * n, hard
    assert abs(hard["total_err_pct"]) < 0.5, hard
    assert hard["median"] < 0.2, hard


def test_no_wrong_area_goes_unflagged(hard):
    assert hard["silent_wrong"] == 0, hard


# ---- walls: pen by pen ------------------------------------------------------

def test_wall_length_on_the_hard_plans():
    """Pairing every line with every other found 7.6% more wall than is
    drawn, in two dozen thicknesses (a wall face against a counter)."""
    import accuracy_hard
    rows = accuracy_hard.walls_score(3, seed=21, verbose=False)
    assert len(rows) == 3
    for _i, _ppf, _style, drawn, found in rows:
        assert abs(found - drawn) <= 0.04 * drawn, rows


def test_walls_pair_only_lines_of_one_pen():
    from app import autowalls as aw
    doc = fitz.open()
    pg = doc.new_page(width=800, height=600)
    sh = pg.new_shape()
    for y in (100, 109):                      # a 6" wall at 1/4" scale
        sh.draw_line((100, y), (500, y))
        sh.finish(color=(0, 0, 0), width=0.7)
    for y in (300, 309):                      # another, for a second pen
        sh.draw_line((100, y), (500, y))
        sh.finish(color=(0, 0, 0), width=0.7)
    sh.draw_line((100, 115), (500, 115))      # a counter's edge, fine pen
    sh.finish(color=(0.3, 0.3, 0.3), width=0.25)
    sh.draw_line((100, 121), (500, 121))
    sh.finish(color=(0.3, 0.3, 0.3), width=0.25)
    sh.commit()
    ws = aw.walls(pg, 18.0, "ft")
    assert sorted(round(w["thickness"]) for w in ws) == [6, 6]
    every = aw.walls(pg, 18.0, "ft", by_pen=False)
    assert len(every) > 2 or any(round(w["thickness"]) != 6 for w in every)
