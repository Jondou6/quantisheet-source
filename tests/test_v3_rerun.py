"""AI Takeoff v3 (Oct 31 2026), feature 1: running AI Takeoff again never
counts anything twice. Each new result is matched by place and shape
against what is already on the drawing (an AI mark from the first run,
accepted or not, or a person's own measurement), within a tolerance:
areas by overlap, lines by distance, counts by distance. Matches are
'previously detected' (locked - never added again); the rest are 'new'
and the person picks which to add. Review decisions made on the first
run carry over to the second."""
import os

import pytest

fitz = pytest.importorskip("fitz")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import aitakeoff as ait, annotate, rerun  # noqa: E402

SQ = [[50, 50], [150, 50], [150, 150], [50, 150]]


def _poly(pts, group="OFFICE 101", value=100.0, review=True):
    return (0, "add_polygon", {
        "pts": pts, "label": f"{group}: {value:g} sq ft",
        "measure": {"type": "area", "value": value, "unit": "sq ft",
                    "group": group,
                    "method": "AI takeoff: rooms" + (
                        annotate.REVIEW_SUFFIX if review else "")}})


def _line(a, b, group="Wall 8in", value=20.0):
    return (0, "add_line", {"pts": [a, b], "label": f"{group}: {value:g}",
                            "measure": {"type": "length", "value": value,
                                        "unit": "ft", "group": group,
                                        "method": "AI takeoff: walls"}})


def _count(pt, group="Doors", n=1):
    return (0, "add_count", {"pt": pt, "n": n,
                             "measure": {"type": "count", "value": 1,
                                         "unit": "ea", "group": group,
                                         "method": "AI takeoff: schedules"}})


def _apply(d, marks):
    for i, (p, k, pl) in enumerate(marks):
        annotate.apply_op(d, {"kind": k, "page": p, "id": f"m{id(pl)}{i}",
                              "payload": dict(pl)}, fresh=True)


def _doc():
    d = fitz.open()
    d.new_page(width=800, height=600)
    return d


def _shift(pts, dx, dy):
    return [[x + dx, y + dy] for x, y in pts]


def test_same_marks_again_are_previous_not_new():
    d = _doc()
    first = [_poly(SQ), _line([200, 100], [400, 100]), _count([500, 300])]
    _apply(d, first)
    again = [_poly(_shift(SQ, 2, -2)), _line([201, 101], [399, 100]),
             _count([503, 302]), _poly(_shift(SQ, 400, 300), "NEW 120")]
    s = rerun.split(d, again)
    assert [m[2]["measure"]["group"] for m in s["new"]] == ["NEW 120"]
    assert len(s["previous"]) == 3
    assert all(p["locked"] for p in s["previous"])


def test_far_enough_away_is_new():
    d = _doc()
    _apply(d, [_count([500, 300]), _line([200, 100], [400, 100])])
    s = rerun.split(d, [_count([500 + 3 * rerun.COUNT_TOL_PT, 300]),
                        _line([200, 100 + 3 * rerun.LINE_TOL_PT],
                              [400, 100 + 3 * rerun.LINE_TOL_PT])])
    assert len(s["new"]) == 2 and not s["previous"]


def test_an_edited_renamed_accepted_area_is_still_the_same_room():
    d = _doc()
    _apply(d, [_poly(SQ)])
    a = [x for x in d[0].annots() if x.type[0] == fitz.PDF_ANNOT_POLYGON][0]
    tag = annotate.tag_of(a)
    annotate.apply_op(d, {"kind": "set_annot", "page": 0, "id": "e",
                          "payload": {"target": tag, "group": "Carpet",
                                      "status": "Accepted"}}, fresh=True)
    # the second run traces it 5 pt off (or the person nudged it)
    s = rerun.split(d, [_poly(_shift(SQ, 5, 5))])
    assert not s["new"]
    assert s["previous"][0]["status"] == "accepted"
    assert s["previous"][0]["have_group"] == "Carpet"


def test_a_hand_measurement_of_the_room_blocks_the_ai_one():
    d = _doc()
    annotate.apply_op(d, {"kind": "add_polygon", "page": 0, "id": "hand",
                          "payload": {"pts": _shift(SQ, 3, 3),
                                      "measure": {"type": "area",
                                                  "value": 99.0,
                                                  "unit": "sq ft",
                                                  "group": "Office"}}},
                      fresh=True)
    s = rerun.split(d, [_poly(SQ)])
    assert not s["new"] and s["previous"][0]["status"] == "manual"


def test_a_count_of_another_item_on_the_same_spot_does_not_block():
    d = _doc()
    annotate.apply_op(d, {"kind": "add_count", "page": 0, "id": "h",
                          "payload": {"pt": [500, 300], "n": 1,
                                      "measure": {"type": "count",
                                                  "value": 1, "unit": "ea",
                                                  "group": "Smoke detector"}}},
                      fresh=True)
    s = rerun.split(d, [_count([500, 300], "Doors")])
    assert len(s["new"]) == 1


def test_two_runs_leave_the_totals_unchanged():
    d = _doc()
    marks = [_poly(SQ), _poly(_shift(SQ, 300, 0), "HALL 106", 80.0, False),
             _line([200, 400], [600, 400]), _count([500, 300]),
             _count([520, 300], n=2)]
    _apply(d, marks)
    t1 = rerun.drawing_totals(d)
    s = rerun.split(d, [(p, k, dict(pl)) for p, k, pl in marks])
    _apply(d, s["new"])
    assert rerun.drawing_totals(d) == t1 and not s["new"]


def _res(review, quantities=()):
    return {"review": [dict(x) for x in review],
            "quantities": [dict(q) for q in quantities], "sheets": {},
            "marks": [], "problems": [], "scales": [], "decisions": []}


ROOM = {"sheet": "A101", "page": 4, "name": "HALL 106", "qty": 139.0,
        "unit": "sq ft", "engine": "rooms", "confidence": 0.7,
        "why": "no area in the tag - size check only"}
DUCT = {"sheet": "M101", "page": 18, "name": "Duct 8in wide", "qty": 101.5,
        "unit": "ft", "engine": "ducts", "why": "no size tag"}
WIN = {"sheet": "A003", "page": 2, "name": "Window W01", "qty": 1,
       "unit": "ea", "engine": "schedules", "kind": "window"}


def test_review_decisions_carry_over_to_the_second_run():
    from app import review
    prev = _res([ROOM, DUCT, WIN])
    review.accept(prev, prev["review"][0], who="me", log_path=None)
    review.delete(prev, prev["review"][0], who="me", log_path=None)
    t_prev = ait.totals(dict(prev, sheets={}))
    new = _res([ROOM, DUCT, WIN])
    got = rerun.carry_decisions(prev, new)
    assert [x["name"] for x in new["review"]] == ["Window W01"]
    assert sorted(x["name"] for x in got["locked"]) == \
        ["Duct 8in wide", "HALL 106"]
    assert ait.totals(new) == t_prev
    assert [q["name"] for q in new["quantities"]] == ["HALL 106"]


def test_a_changed_quantity_is_not_carried_over():
    from app import review
    prev = _res([ROOM])
    review.accept(prev, prev["review"][0], who="me", log_path=None)
    new = _res([dict(ROOM, qty=180.0)])
    got = rerun.carry_decisions(prev, new)
    assert not got["locked"] and len(new["review"]) == 1
