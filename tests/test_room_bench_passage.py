"""Shower benches and door swings on the wall layers (Oct 31, HMB 109).

Harbor Springs A101 draws the shower benches, the door leaves and swings,
grab bars and the shower curtain on the wall layers (WALL-INTR /
WALL-EXTR). The fill out to the wall faces shut every gap under 3 ft
between any two pieces of wall-layer ink as a "doorway", so the 2'-9"
passage beside a 1'-3" bench in a 4' stall, and the floor under a door's
swing, were never filled: Women's Shower 109 came out 114.7 SF against
129.8. A doorway is a gap between walls; a bench outline or a swing is
not a wall. Thin wall-layer lines still bound the fill."""
import os

import cv2
import numpy as np
import pytest

from app import autotakeoff as at

PPF = 24.0                     # pixels per foot, as the sheets are drawn


def _contour(mask):
    cnts, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL,
                               cv2.CHAIN_APPROX_SIMPLE)
    return max(cnts, key=cv2.contourArea)


def _plan_like(wl):
    from types import SimpleNamespace
    p = SimpleNamespace(wl=wl, ppf=PPF)
    p.sqft = lambda px: px / (PPF * PPF)
    return p


def ft(v):
    return int(round(v * PPF))


def _stall_with_bench():
    """A 4' x 7' shower stall: solid (poche) walls 8" thick, a 1'-3" x
    2'-7" bench outline (thin line) against its left wall."""
    wl = np.zeros((ft(12), ft(10)), np.uint8)
    x0, y0, x1, y1 = ft(1), ft(1), ft(5), ft(8)        # inside faces
    t = ft(8 / 12)
    wl[y0 - t:y0, x0 - t:x1 + t] = 1                   # top
    wl[y1:y1 + t, x0 - t:x1 + t] = 1                   # bottom
    wl[y0:y1, x0 - t:x0] = 1                           # left
    wl[y0:y1, x1:x1 + t] = 1                           # right
    bx0, by0, bx1, by1 = x0, ft(3), x0 + ft(1.25), ft(3) + ft(2.6)
    cv2.rectangle(wl, (bx0, by0), (bx1, by1), 1, 1)    # bench outline
    return wl, (x0, y0, x1, y1), (bx0, by0, bx1, by1)


def test_floor_beside_a_bench_is_filled():
    wl, (x0, y0, x1, y1), (bx0, by0, bx1, by1) = _stall_with_bench()
    tr = np.zeros_like(wl)
    tr[y0 + 2:y1 - 2, x0 + 2:x1 - 2] = 1
    # the trace lost the bench and a 7" strip of the 2'-9" passage beside
    # it (as on A101: the open-space trace stops short of thin lines)
    tr[by0 - ft(0.3):by1 + ft(0.3), x0:bx1 + ft(0.6)] = 0
    c = _contour(tr)
    c2, add = at.Plan._fill_to_faces(_plan_like(wl), c)
    strip = 0.6 * (2.6 + 0.6)                      # SF beside the bench
    bench = 1.25 * 2.6
    assert add >= 0.8 * (strip + bench), (add, strip, bench)
    # ...and (Nov 3, Jon: "count it always") the floor under the bench
    m = np.zeros_like(wl)
    cv2.drawContours(m, [c2], -1, 1, -1)
    inside_bench = m[by0 + 3:by1 - 2, bx0 + 3:bx1 - 2]
    assert inside_bench.mean() > 0.95
    # never past the stall's walls
    assert m[:, :x0 - ft(8 / 12)].sum() == 0 and m[y1 + ft(1):, :].sum() == 0


def test_a_tub_or_big_casework_outline_is_not_a_bench():
    # the same stall with a 2'-6" x 5' outline (a tub) against the wall
    wl, (x0, y0, x1, y1), _b = _stall_with_bench()
    wl[y0:y1, x0:x1] = 0
    t = ft(8 / 12)
    wl[y0 - t:y0, x0 - t:x1 + t] = 1
    bx0, by0, bx1, by1 = x0, ft(2), x0 + ft(2.5), ft(7)
    cv2.rectangle(wl, (bx0, by0), (bx1, by1), 1, 1)
    tr = np.zeros_like(wl)
    tr[y0 + 2:y1 - 2, x0 + 2:x1 - 2] = 1
    tr[by0 - 2:by1 + 2, x0:bx1 + 2] = 0
    c2, _add = at.Plan._fill_to_faces(_plan_like(wl), _contour(tr))
    m = np.zeros_like(wl)
    cv2.drawContours(m, [c2], -1, 1, -1)
    assert m[by0 + 3:by1 - 2, bx0 + 3:bx1 - 2].mean() < 0.05


def test_doorway_between_hollow_walls_stays_shut():
    # walls drawn hollow (two face lines 8" apart, no poche) with a 3'
    # door in the bottom wall and a corridor beyond it
    wl = np.zeros((ft(16), ft(16)), np.uint8)
    x0, y0, x1, y1 = ft(1), ft(1), ft(13), ft(11)
    t = ft(8 / 12)
    cv2.rectangle(wl, (x0, y0), (x1, y1), 1, 1)
    cv2.rectangle(wl, (x0 - t, y0 - t), (x1 + t, y1 + t), 1, 1)
    wl[y1 - 1:y1 + t + 2, ft(5):ft(8)] = 0                 # the door
    cv2.line(wl, (ft(5), y1), (ft(5), y1 + t), 1, 1)       # its jambs
    cv2.line(wl, (ft(8), y1), (ft(8), y1 + t), 1, 1)
    cv2.line(wl, (0, y1 + ft(4)), (ft(16) - 1, y1 + ft(4)), 1, 1)
    tr = np.zeros_like(wl)
    tr[y0 + 3:y1 - 3, x0 + 3:x1 - 3] = 1
    _c2, add = at.Plan._fill_to_faces(_plan_like(wl), _contour(tr))
    # the face strip all round (about 3 px) and at most a sliver of the
    # door's width - not the 3' x 2' of corridor beyond it
    assert add < 3.0, add


# the HMB set is test data only, never in the repo: on Jon's PC it is in
# _incoming\plans (Nov 2, from Chief); QS_HMB_PLAN can point elsewhere
_HERE = os.path.dirname(os.path.abspath(__file__))
PLAN = next((p for p in (
    os.path.join(_HERE, "..", "_incoming", "plans",
                 "harbor_springs_hmb_bid_drawings.pdf"),
    os.path.join(_HERE, "..", "..", "..", "..", "plans",
                 "harbor_springs_hmb_bid_drawings.pdf"))
    if os.path.exists(p)), "")
PLAN = os.environ.get("QS_HMB_PLAN", PLAN)
HMB_TRUTH = {"109": (129.8, 8), "104": (135.3, 8), "103": (170.6, 8),
             "108": (153.1, 8), "105": (159.7, 8), "106": (139.5, 8),
             "110": (145.4, 5), "111": (199.1, 8), "112": (248.0, 8)}


def _hmb_a101_rooms():
    """A101's rooms read the way AI Takeoff reads them: with PyMuPDF's
    small-glyph switch off (aitakeoff puts it back as it found it). The
    switch is process-wide and something earlier in a full run can leave it
    on; with it on, room 111's tag reads differently and the room is lost
    (Oct 31: this test failed only in the full suite)."""
    import fitz
    prev = fitz.TOOLS.set_small_glyph_heights()
    fitz.TOOLS.set_small_glyph_heights(False)
    try:
        doc = fitz.open(PLAN)
        found, _missed = at.all_rooms(at.cached_page(doc[4]),
                                      {"ppu": 18.0, "unit": "ft"})
    finally:
        fitz.TOOLS.set_small_glyph_heights(prev)
    return {f["name"][-3:]: f["sqft"] for f in found}


@pytest.mark.skipif(not os.path.exists(PLAN), reason="HMB plan set not here")
def test_hmb_a101_rooms_with_shower_benches():
    got = _hmb_a101_rooms()
    for num, (truth, tol) in HMB_TRUTH.items():
        assert num in got, num
        assert abs(got[num] - truth) <= truth * tol / 100, (num, got[num])
