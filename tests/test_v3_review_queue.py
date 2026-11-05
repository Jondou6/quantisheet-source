"""AI Takeoff v3 (Oct 31 2026), feature 3: one review queue for every
kind of finding - doors, windows, rooms, areas, lines, schedule rows, a
doubtful scale - least sure first, with Accept, Deny and Undo. A room
that is both a CHECK item and an outline on the drawing is one entry;
deciding it decides both. Nothing pending is in a total until accepted."""
import os

import pytest

fitz = pytest.importorskip("fitz")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import aitakeoff as ait, annotate, review_queue as rq  # noqa: E402
from app.takeoff_tree import group_items  # noqa: E402

PENCIL = [6, 4]


def _doc():
    d = fitz.open()
    d.new_page(width=800, height=600)
    d.new_page(width=800, height=600)
    return d


def _mark(d, oid, kind, payload, page=0):
    payload = dict(payload, dashes=list(PENCIL), badge=True)
    annotate.apply_op(d, {"kind": kind, "page": page, "id": oid,
                          "payload": payload}, fresh=True)


def _setup():
    d = _doc()
    _mark(d, "r109", "add_polygon", {
        "pts": [[50, 50], [150, 50], [150, 150], [50, 150]],
        "label": "WOMEN'S SHOWER 109: 115 sq ft",
        "measure": {"type": "area", "value": 114.7, "unit": "sq ft",
                    "group": "WOMEN'S SHOWER 109",
                    "method": "AI takeoff: rooms" + annotate.REVIEW_SUFFIX}})
    _mark(d, "d1", "add_count", {
        "pt": [400, 300], "n": 1,
        "measure": {"type": "count", "value": 1, "unit": "ea",
                    "group": "Doors", "method": "AI takeoff: schedules"}})
    res = {"review": [
        {"sheet": "A101", "page": 0, "name": "WOMEN'S SHOWER 109",
         "qty": 114.7, "unit": "sq ft", "engine": "rooms",
         "confidence": 0.63, "why": "no area in the tag - size check only"},
        {"sheet": "A003", "page": 1, "name": "Window W01 LAUNDRY ROOM",
         "qty": 1, "unit": "ea", "engine": "schedules", "kind": "window",
         "why": "the same key twice: W03"},
        {"sheet": "A101", "page": 0, "name": "Scale 1/8\" = 1'-0\" on A101",
         "qty": None, "unit": "", "engine": "scale", "kind": "scale",
         "confidence": 0.45, "why": "printed once; no dimensions",
         "rect": [10, 10, 60, 20], "scale": "1/8\" = 1'-0\""}],
        "quantities": [], "sheets": {}, "marks": [], "problems": [],
        "scales": [], "decisions": []}
    return d, res


def test_one_queue_least_sure_first_and_a_room_is_one_entry():
    d, res = _setup()
    q = rq.build(d, res)
    kinds = [e["kind"] for e in q]
    assert sorted(kinds) == ["area", "count", "scale", "schedule row"]
    assert [e["score"] for e in q] == sorted(e["score"] for e in q)
    room = [e for e in q if e["kind"] == "area"][0]
    assert room["mark"] is not None and room["item"] is not None
    assert room["name"] == "WOMEN'S SHOWER 109" and room["pending"]


def test_pending_room_is_out_of_totals_until_accepted_then_in_both():
    d, res = _setup()
    g = group_items(d)[0][("WOMEN'S SHOWER 109", "area", "sq ft")]
    assert g["total"] == 0 and g["pending"] == pytest.approx(114.7)
    q = rq.build(d, res)
    room = [e for e in q if e["kind"] == "area"][0]
    s = rq.Session(d, res)
    s.accept(room)
    g = group_items(d)[0][("WOMEN'S SHOWER 109", "area", "sq ft")]
    assert g["total"] == pytest.approx(114.7) and g["pending"] == 0
    assert [x["name"] for x in res["quantities"]] == ["WOMEN'S SHOWER 109"]
    assert not any(annotate.is_badge(d, a) and annotate.tag_of(a) == "r109"
                   for a in d[0].annots())


def test_deny_removes_it_from_drawing_and_takeoff():
    d, res = _setup()
    room = [e for e in rq.build(d, res) if e["kind"] == "area"][0]
    s = rq.Session(d, res)
    s.deny(room, reason="wrong shape")
    assert not [a for a in d[0].annots() if annotate.tag_of(a) == "r109"]
    assert res["decisions"][-1]["action"] == "deleted"
    assert not any(x["name"] == "WOMEN'S SHOWER 109" for x in res["review"])


def test_undo_puts_back_drawing_and_takeoff():
    d, res = _setup()
    before = d.tobytes()
    n_rev = len(res["review"])
    s = rq.Session(d, res)
    room = [e for e in rq.build(d, res) if e["kind"] == "area"][0]
    s.accept(room)
    door = [e for e in rq.build(d, res) if e["kind"] == "count"][0]
    s.deny(door)
    assert s.undo() and s.undo()
    assert len(res["review"]) == n_rev and not res["quantities"] and \
        not res["decisions"]
    g = group_items(d)[0][("WOMEN'S SHOWER 109", "area", "sq ft")]
    assert g["pending"] == pytest.approx(114.7)
    assert len(rq.build(d, res)) == 4
    assert not s.undo()                     # nothing more to undo
    assert len(d.tobytes()) > 0 and before


def test_schedule_row_accept_goes_to_quantities():
    d, res = _setup()
    w = [e for e in rq.build(d, res) if e["kind"] == "schedule row"][0]
    rq.Session(d, res).accept(w)
    assert ait.totals(res)["quantities"] == {
        ("schedules: Window W01 LAUNDRY ROOM", "ea"): 1.0}


def test_scale_accept_is_a_decision_not_a_quantity():
    d, res = _setup()
    sc = [e for e in rq.build(d, res) if e["kind"] == "scale"][0]
    assert sc["score"] == 45
    rq.Session(d, res).accept(sc)
    assert not res["quantities"]
    assert res["decisions"][-1]["action"] == "scale confirmed"
