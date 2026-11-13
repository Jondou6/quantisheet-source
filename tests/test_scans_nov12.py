"""Nov 12: rooms on scanned plans. A scan has no linework, so walls
drawn hollow or hatched are filled in the picture before the wall
picture is made. Made-up pictures."""
import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from app import autotakeoff as at                             # noqa: E402

PPF = 24


def plan():
    img = np.zeros((600, 900), np.uint8)
    for a, b in (((100, 100), (500, 400)), ((116, 116), (484, 384))):
        cv2.rectangle(img, a, b, 1, 2)             # 8" outside wall, hollow
    for x in (292, 308):                           # partition with a 3' door
        cv2.line(img, (x, 116), (x, 200), 1, 2)
        cv2.line(img, (x, 272), (x, 384), 1, 2)
    for y in (200, 272):
        cv2.line(img, (292, y), (308, y), 1, 2)
    for y in range(100, 400, 10):                  # a hatched wall
        cv2.line(img, (700, y), (716, y + 10), 1, 1)
    cv2.rectangle(img, (700, 100), (716, 400), 1, 2)
    return img


def test_hollow_and_hatched_walls_are_filled_rooms_are_not():
    img = plan()
    before = at.wall_mask(None, PPF, ink=img.copy())
    assert before[108, 200] == 0                   # the wall was opened away
    assert at.fill_hollow(img, PPF) > 3
    w = at.wall_mask(None, PPF, ink=img.copy())
    assert w[108, 200] == 1 and w[150, 300] == 1 and w[250, 708] == 1
    assert w[236, 300] == 0                        # the door opening stays
    assert w[250, 200] == 0 and w[250, 400] == 0   # the rooms stay
    # each room is its size inside the faces, within a pixel a side
    free = (w == 0).astype(np.uint8)
    _n, lab, st, _c = cv2.connectedComponentsWithStats(free, connectivity=4)
    left = st[lab[250, 200], cv2.CC_STAT_AREA] / PPF ** 2
    assert lab[250, 200] == lab[250, 400]          # joined through the door
    both = (292 - 116 + 484 - 308) * (384 - 116) / PPF ** 2
    assert abs(left - both) / both < 0.03


def test_nothing_to_fill():
    solid = np.zeros((200, 300), np.uint8)
    cv2.rectangle(solid, (20, 20), (280, 180), 1, 12)
    keep = solid.copy()
    assert at.fill_hollow(solid, PPF) == 0
    assert (solid == keep).all()
    # a long narrow room is not a wall: 2' wide is thicker than any wall
    hall = np.zeros((300, 600), np.uint8)
    cv2.rectangle(hall, (50, 100), (550, 100 + 2 * PPF + 4), 1, 2)
    assert at.fill_hollow(hall, PPF) == 0


def test_soft_edges_land_on_the_wall_face():
    g = np.full((60, 200), 255, np.uint8)
    g[20:40, 50:150] = 90                       # a grey-filled wall, 100 px
    soft = cv2.GaussianBlur(g, (0, 0), 2.0)     # a scan's soft edge
    old = int((soft[30] < at.INK_LEVEL).sum())
    new = int(at.scan_ink_of(soft)[30].sum())
    assert old == 102                           # the plain cut ran wide
    assert new == 100
    hair = np.full((20, 40), 255, np.uint8)
    hair[10, :] = 180                           # a light hairline is still ink
    assert at.scan_ink_of(hair)[10].sum() == 40
    assert at.SCAN_OPEN_FT < at.OPEN_FT         # a 4" partition is kept


def test_a_four_inch_partition_survives_on_a_scan():
    img = np.zeros((300, 400), np.uint8)
    cv2.rectangle(img, (40, 40), (360, 260), 1, 16)       # 8" outside wall
    img[40:260, 196:204] = 1                              # 4" partition
    assert at.wall_mask(None, PPF, ink=img.copy())[150, 200] == 0
    w = at.wall_mask(None, PPF, ink=img.copy(), open_ft=at.SCAN_OPEN_FT)
    assert w[150, 200] == 1 and w[150, 120] == 0


def shelf_plan(pen_grey, pen_px):
    g = np.full((700, 1000), 255, np.uint8)
    for a, b in (((100, 100), (900, 600)), ((116, 116), (884, 584))):
        cv2.rectangle(g, a, b, 0, 2)                     # hollow outside wall
    for x in (392, 408, 642, 658):                       # two partitions
        cv2.line(g, (x, 116), (x, 584), 0, 2)
    # shelving 15" deep, 10' long, by the top wall of the first room
    cv2.rectangle(g, (130, 128), (370, 158), pen_grey, pen_px)
    return cv2.GaussianBlur(g, (0, 0), 0.8)


def test_shelving_in_a_fine_pen_is_not_filled_as_wall():
    g = shelf_plan(170, 2)                               # a fine grey pen
    ink = at.scan_ink_of(g)
    assert at.fill_hollow(ink, PPF, gray=g) == 3         # the walls only
    w = at.wall_mask(None, PPF, ink=ink, open_ft=at.SCAN_OPEN_FT)
    assert w[143, 250] == 0                              # floor under the shelf
    assert w[108, 300] == 1 and w[300, 400] == 1         # walls are walls
    # without the grey picture there is nothing to tell them apart by
    ink2 = at.scan_ink_of(g)
    at.fill_hollow(ink2, PPF)
    assert at.wall_mask(None, PPF, ink=ink2,
                        open_ft=at.SCAN_OPEN_FT)[143, 250] == 1
    # a box drawn as heavy as the walls still reads as wall (a chase)
    h = shelf_plan(0, 2)
    ink3 = at.scan_ink_of(h)
    at.fill_hollow(ink3, PPF, gray=h)
    assert at.wall_mask(None, PPF, ink=ink3,
                        open_ft=at.SCAN_OPEN_FT)[143, 250] == 1


def test_too_few_walls_to_compare_pens_fills_as_before():
    g = np.full((300, 500), 255, np.uint8)
    cv2.rectangle(g, (50, 50), (450, 250), 0, 2)
    cv2.rectangle(g, (66, 66), (434, 234), 0, 2)         # one hollow wall
    cv2.rectangle(g, (100, 80), (300, 108), 140, 2)      # one light box
    ink = at.scan_ink_of(g)
    at.fill_hollow(ink, PPF, gray=g)
    assert ink[94, 200] == 1                 # filled: nothing to compare with
