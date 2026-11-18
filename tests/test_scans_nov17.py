"""Nov 17: small-scale scans. A box drawn with an X (equipment, a
refrigerator space) is cut into thin triangles that were filled as wall;
and on a scan the room now reaches round small things against its walls
(a sink, a faucet stub, the end of a counter). Made-up pictures."""
import pytest

np = pytest.importorskip("numpy")
cv2 = pytest.importorskip("cv2")

from app import autotakeoff as at                             # noqa: E402

PPF = 24


def test_box_with_an_x_is_not_wall_but_hollow_walls_still_are():
    img = np.zeros((600, 900), np.uint8)
    for a, b in (((100, 100), (700, 500)), ((116, 116), (684, 484))):
        cv2.rectangle(img, a, b, 1, 2)             # 8" hollow outside wall
    x0, y0 = 120, 120                              # a 3' box in the corner
    s = 3 * PPF
    cv2.rectangle(img, (x0, y0), (x0 + s, y0 + s), 1, 1)
    cv2.line(img, (x0, y0), (x0 + s, y0 + s), 1, 1)
    cv2.line(img, (x0 + s, y0), (x0, y0 + s), 1, 1)
    at.fill_hollow(img, PPF)
    assert img[108, 400] == 1                      # the wall is filled
    c = x0 + s // 2
    assert img[c, c] == 1                          # the X's own crossing
    assert img[c - 12, c] == 0 and img[c, c - 12] == 0   # triangles left


def test_constants_are_switches():
    assert at.HOLLOW_FAT_FT > at.HOLLOW_MAX_FT
    assert at.SCAN_REACH in (True, False) and at.SCAN_REACH_MIN_SF > 30
