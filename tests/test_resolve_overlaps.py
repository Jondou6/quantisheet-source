"""Nov 1 (Collenton A-101): a small piece of floor two traces both take is
given to one room - the one that then comes closer to its tag - instead
of being counted twice and sending both rooms to review."""
import pytest

pytest.importorskip("cv2")

from app import autotakeoff as at  # noqa: E402

PPF = 10.0                       # page points per foot


def _room(name, x0, y0, x1, y1, tag):
    pts = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    sf = (x1 - x0) * (y1 - y0) / PPF ** 2
    r = {"name": name, "pts": pts, "sqft": sf, "net_sf": sf, "value": sf,
         "tag_sf": tag, "perimeter_lf": 2 * ((x1 - x0) + (y1 - y0)) / PPF,
         "flags": []}
    return at.score_room(r)


def test_overlap_goes_to_the_room_it_fits():
    a = _room("CORRIDOR 1", 0, 0, 200, 100, 190)      # 200 SF, 10 over
    b = _room("TOILET 2", 190, 0, 300, 100, 110)      # 110 SF, on its tag
    assert at.resolve_overlaps([a, b], PPF) == 1
    assert a["sqft"] == pytest.approx(190, abs=0.6)
    assert a["net_sf"] == a["sqft"] and a["value"] == pytest.approx(
        a["sqft"], rel=1e-6)
    assert a["perimeter_lf"] == pytest.approx(58, abs=0.6)
    assert max(p[0] for p in a["pts"]) == pytest.approx(190, abs=1)
    assert b["sqft"] == 110                            # the winner is untouched
    assert not a["review"] and a["trace_confidence"] >= 0.95
    assert any("left to that room" in f for f in a["flags"])
    assert at.flag_overlaps([a, b], PPF) == 0          # no double count now


def test_no_gain_no_change_both_flagged():
    a = _room("A", 0, 0, 200, 100, 200)                # both on their tags
    b = _room("B", 190, 0, 300, 100, 110)
    assert at.resolve_overlaps([a, b], PPF) == 0
    assert a["sqft"] == 200 and b["sqft"] == 110
    assert at.flag_overlaps([a, b], PPF) == 1 and a["review"] and b["review"]


def test_no_tags_left_alone():
    a = _room("A", 0, 0, 200, 100, None)
    b = _room("B", 190, 0, 300, 100, None)
    assert at.resolve_overlaps([a, b], PPF) == 0


def test_big_overlap_is_not_resolved():
    a = _room("A", 0, 0, 200, 100, 150)                # 50 SF overlap
    b = _room("B", 150, 0, 300, 100, 150)
    assert at.resolve_overlaps([a, b], PPF) == 0


def test_rooms_apart_untouched():
    a = _room("A", 0, 0, 100, 100, 90)
    b = _room("B", 200, 0, 300, 100, 90)
    assert at.resolve_overlaps([a, b], PPF) == 0


def test_points_stay_the_tracers_kind():
    """Nov 1: a resolved room came back with tuples instead of fitz.Point
    and AI Takeoff failed drawing its mark (to_page multiplies by a
    Matrix)."""
    fitz = pytest.importorskip("fitz")
    a = _room("CORRIDOR 1", 0, 0, 200, 100, 190)
    b = _room("TOILET 2", 190, 0, 300, 100, 110)
    for r in (a, b):
        r["pts"] = [fitz.Point(*p) for p in r["pts"]]
    assert at.resolve_overlaps([a, b], PPF) == 1
    assert all(isinstance(p, fitz.Point) for p in a["pts"])
    m = fitz.Matrix(2, 2)
    assert [p * m for p in a["pts"]]                  # transforms like before
    assert abs(a["pts"][1] - a["pts"][0]) > 0


# ---- Nov 1 (Aiken A-101): each room ends at a drawn line between them ------
np = pytest.importorskip("numpy")


def _tagged(name, x0, y0, x1, y1, tag, tag_pt):
    r = _room(name, x0, y0, x1, y1, tag)
    r["tag_pt"] = tag_pt
    return r


def _line(*xy):
    return np.array([xy], float)


def test_shared_floor_ends_at_the_line_between_the_tags():
    a = _tagged("RECEPTION 103", 0, 0, 200, 100, 180, (50, 50))   # 200 SF
    b = _tagged("LOBBY 101", 160, 0, 340, 100, 160, (280, 50))    # 180 SF
    # 40 SF shared; giving all of it to either room makes it no better
    assert at.resolve_overlaps([dict(a), dict(b)], PPF) == 0
    n = at.resolve_overlaps([a, b], PPF, lines=_line(180, -5, 180, 105))
    assert n == 1
    assert a["sqft"] == pytest.approx(180, abs=0.6)
    assert b["sqft"] == pytest.approx(160, abs=0.6)
    assert max(p[0] for p in a["pts"]) == pytest.approx(180, abs=1)
    assert min(p[0] for p in b["pts"]) == pytest.approx(180, abs=1)
    assert any("drawn line" in f for f in a["flags"])
    assert any("drawn line" in f for f in b["flags"])
    assert at.flag_overlaps([a, b], PPF) == 0
    assert not a["review"] and not b["review"]


def test_diagonal_line():
    a = _tagged("A", 0, 0, 200, 100, None, (40, 50))
    b = _tagged("B", 160, 0, 360, 100, None, (300, 50))
    # a counter drawn corner to corner across the shared 40 SF
    n = at.resolve_overlaps([a, b], PPF, lines=_line(160, 100, 200, 0))
    assert n == 1
    assert a["sqft"] + b["sqft"] == pytest.approx(360, abs=1.5)   # once
    assert at.flag_overlaps([a, b], PPF) == 0


def test_line_with_both_tags_on_one_side_does_nothing():
    a = _tagged("A", 0, 0, 200, 100, 180, (50, 50))
    b = _tagged("B", 160, 0, 340, 100, 160, (170, 50))   # tag left of line
    assert at.resolve_overlaps([a, b], PPF,
                               lines=_line(180, -5, 180, 105)) == 0
    assert a["sqft"] == 200 and b["sqft"] == 180


def test_short_line_or_line_elsewhere_does_nothing():
    a = _tagged("A", 0, 0, 200, 100, 180, (50, 50))
    b = _tagged("B", 160, 0, 340, 100, 160, (280, 50))
    short = _line(180, 40, 180, 60)                      # 2 ft of 10
    away = _line(100, -5, 100, 105)                      # not in the overlap
    assert at.resolve_overlaps([a, b], PPF, lines=np.vstack([short, away])) == 0
    assert a["sqft"] == 200 and b["sqft"] == 180


def test_line_that_moves_rooms_away_from_their_tags_is_not_used():
    a = _tagged("A", 0, 0, 200, 100, 200, (50, 50))      # both on their tags
    b = _tagged("B", 160, 0, 340, 100, 180, (280, 50))
    assert at.resolve_overlaps([a, b], PPF,
                               lines=_line(180, -5, 180, 105)) == 0


def test_result_carries_the_tag_point():
    fitz = pytest.importorskip("fitz")

    class P:
        pts_per_ft = PPF
        unit = "ft"

        def to_units(self, sf):
            return sf
    r = at._result(P(), {"pts": [fitz.Point(0, 0), fitz.Point(10, 0),
                                 fitz.Point(10, 10)], "sqft": 5.0},
                   {"name": "OFFICE 1", "sf": 5, "pt": (3.0, 4.0)})
    assert r["tag_pt"] == (3.0, 4.0)
