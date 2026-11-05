"""Rooms with stalls (Oct 31, round 2). Harbor Springs: the shower rooms'
stalls open off a narrow strip, so bridging openings at the usual 3.6 ft
door width cut every stall off (Women's Shower 109: 15 SF, its dims give
about 152). Bridging only narrow gaps keeps the stalls; it is taken when
what it adds is stall-sized pockets, or when the usual trace is too small
to be the named room at all (a pocket around its tag)."""
import numpy as np
import cv2

from app import autotakeoff as at

PPF = 10.0                         # pixels per foot


def _contour(mask):
    cnts, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL,
                               cv2.CHAIN_APPROX_SIMPLE)
    return max(cnts, key=cv2.contourArea)


def _room(stalls=3, stall_ft=(3, 5), strip_ft=(12, 4)):
    m = np.zeros((200, 200), np.uint8)
    sw, sh = int(strip_ft[0] * PPF), int(strip_ft[1] * PPF)
    m[10:10 + sh, 10:10 + sw] = 1                      # the strip
    big = m.copy()
    w, h = int(stall_ft[0] * PPF), int(stall_ft[1] * PPF)
    for i in range(stalls):
        x = 10 + i * (w + 5)
        big[10 + sh:10 + sh + h, x:x + w] = 1          # stalls below it
    return m, big


def test_stall_pockets_join_the_room():
    strip, whole = _room()
    assert at.stalls_join(_contour(strip), _contour(whole), PPF)


def test_a_big_space_beyond_a_narrow_gap_does_not_join():
    strip, _ = _room()
    other = strip.copy()
    other[10 + 40:10 + 40 + 120, 10:10 + 120] = 1     # a 12' x 12' room
    assert not at.stalls_join(_contour(strip), _contour(other), PPF)


def test_a_trace_too_small_for_the_room_takes_the_narrow_bridging():
    # the tag sits in a 2' x 3' pocket; the narrow bridging finds the room
    pocket = np.zeros((200, 200), np.uint8)
    pocket[10:40, 10:30] = 1
    room = np.zeros((200, 200), np.uint8)
    room[10:130, 10:120] = 1                           # 11' x 12'
    assert at.stalls_join(_contour(pocket), _contour(room), PPF)
    # ...but not a whole floor
    floor = np.zeros((900, 900), np.uint8)
    floor[10:890, 10:890] = 1
    assert not at.stalls_join(_contour(pocket), _contour(floor), PPF)


def _layered(name, thick_in, n=25):
    import fitz
    doc = fitz.open()
    page = doc.new_page(width=1000, height=800)
    oc = doc.add_ocg(name)
    sh = page.new_shape()
    ppf = 18.0
    for i in range(n):
        x = 50 + i * 30
        sh.draw_rect(fitz.Rect(x, 100, x + thick_in / 12 * ppf, 100 + 5 * ppf))
        sh.finish(color=(0, 0, 0), fill=(0, 0, 0), oc=oc)
    sh.commit()
    return doc, page


def test_toilet_partition_layer_is_not_a_room_wall():
    # 1" partitions on 'WALL-PARTITIONS' (Harbor Springs A101) split rooms
    doc, page = _layered("0 | WALL-PARTITIONS", 1.2)
    assert at.partition_layers(page, {"0 | WALL-PARTITIONS"}, 18.0) == \
        {"0 | WALL-PARTITIONS"}


def test_a_partition_wall_layer_of_real_walls_stays():
    # NCS 'A-WALL-PRTN' holds the interior partition walls (4"+)
    doc, page = _layered("A-WALL-PRTN", 4.5)
    assert at.partition_layers(page, {"A-WALL-PRTN"}, 18.0) == set()


def test_a_stall_closed_off_by_a_curtain_line_joins_the_room():
    """Harbor Springs 104: shower curtains drawn across the stall fronts
    close each stall; a closed pocket of stall size behind a thin line
    (not a wall) belongs to the room. A wall's hollow core does not."""
    walls = np.zeros((200, 200), np.uint8)
    walls[0:4, :] = walls[:, 0:4] = walls[196:, :] = walls[:, 196:] = 1
    walls[100:104, 4:120] = 1          # 4 px = 0.4 ft wall below the room
    walls[100:140, 120:124] = 1
    walls[100:101, 124:196] = 1        # a curtain line (1 px) closes a stall
    walls[140:144, 120:196] = 1        # the stall's back wall
    room = np.zeros_like(walls)
    room[4:100, 4:196] = 1
    room[100:101, 124:196] = 0
    got = at.join_pockets(_contour(room), walls, PPF, others=[])
    assert cv2.contourArea(got) / PPF ** 2 > \
        cv2.contourArea(_contour(room)) / PPF ** 2 + 20      # + the stall
    # the space below the 0.4 ft wall (12' x 9') stays out
    assert cv2.contourArea(got) / PPF ** 2 < 260


# --- out to the wall-layer faces (fixture notches), round 2 ---------------

def _plan_like(wl):
    from types import SimpleNamespace
    p = SimpleNamespace(wl=wl, ppf=PPF)
    p.sqft = lambda px: px / (PPF * PPF)
    return p


def _walls_box(x0, y0, x1, y1, shape=(300, 300), door=None):
    """A wall-layer rectangle (pixels), with an optional opening
    (x0, x1) cut in its bottom wall."""
    wl = np.zeros(shape, np.uint8)
    cv2.rectangle(wl, (x0, y0), (x1, y1), 1, 3)
    if door:
        wl[y1 - 2:y1 + 3, door[0]:door[1]] = 0
    return wl


def test_fixture_notch_is_filled_to_the_wall_faces():
    # a 12' x 10' room; a 3' x 2' bench against the right wall cut out of
    # the trace (its outline is not on a wall layer)
    wl = _walls_box(20, 20, 140, 120)
    tr = np.zeros_like(wl)
    tr[23:118, 23:138] = 1
    tr[40:70, 118:138] = 0                       # the bench notch
    c = _contour(tr)
    c2, add = at.Plan._fill_to_faces(_plan_like(wl), c)
    assert 4.5 <= add <= 7.5                     # about the 6 SF notch
    assert cv2.contourArea(c2) > cv2.contourArea(c)


def test_fill_does_not_run_out_through_a_doorway():
    # the same room with a 3' door in its bottom wall and a corridor
    # beyond: at most a sliver of the door's width is added
    wl = _walls_box(20, 20, 140, 120, door=(60, 90))
    cv2.line(wl, (0, 160), (299, 160), 1, 3)      # the corridor's far wall
    tr = np.zeros_like(wl)
    tr[23:118, 23:138] = 1
    c = _contour(tr)
    _c2, add = at.Plan._fill_to_faces(_plan_like(wl), c)
    assert add < 2.0


def test_fill_never_takes_another_rooms_tag_or_runs_without_layers():
    wl = _walls_box(20, 20, 140, 120)
    tr = np.zeros_like(wl)
    tr[23:118, 23:138] = 1
    tr[40:70, 118:138] = 0
    c = _contour(tr)
    same, add = at.Plan._fill_to_faces(_plan_like(wl), c, [(128, 55)])
    assert add == 0.0 and same is c
    same, add = at.Plan._fill_to_faces(_plan_like(None), c)
    assert add == 0.0 and same is c


def test_a_big_fill_is_flagged_for_the_benches():
    r = at.score_room({"net_sf": 115.0, "face_fill_sf": 6.5,
                       "tag_sf": None, "flags": []})
    assert any("wall faces around fixtures" in f for f in r["flags"])
    r = at.score_room({"net_sf": 150.0, "face_fill_sf": 1.0,
                       "tag_sf": None, "flags": []})
    assert not any("wall faces" in f for f in r["flags"])
