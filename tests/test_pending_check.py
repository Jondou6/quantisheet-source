"""Nov 1: the bid error check warns when AI Takeoff items are still in
review - they are out of every total, so the bid would go out short."""
import pytest

fitz = pytest.importorskip("fitz")

from app import annotate  # noqa: E402
from app.estimating import checks  # noqa: E402


def _room(d, i, value, review, group="Room"):
    annotate.apply_op(d, {"kind": "add_polygon", "page": 0, "id": f"r{i}",
                          "payload": {
                              "pts": [[50 + 60 * i, 50], [100 + 60 * i, 50],
                                      [100 + 60 * i, 100], [50 + 60 * i, 100]],
                              "measure": {"type": "area", "value": value,
                                          "unit": "sq ft", "group": group,
                                          "method": "AI takeoff: rooms" + (
                                              annotate.REVIEW_SUFFIX
                                              if review else "")}}},
                      fresh=True)


def test_pending_ai_items_are_flagged_per_group():
    d = fitz.open()
    d.new_page()
    _room(d, 0, 100.0, False)
    _room(d, 1, 40.0, True)
    _room(d, 2, 60.0, True)
    _room(d, 3, 25.0, True, group="Floor EPX")
    found = [f for f in checks.run(d, off=()) if f["rule"] == "ai_pending"]
    assert [f["item"] for f in found] == ["Floor EPX", "Room"]
    room = found[1]
    assert room["severity"] == "error" and room["count"] == 2
    assert room["quantity"] == 100.0 and "100 sq ft not in the totals" in \
        room["message"]
    assert "ai_pending" in checks.RULES and "ai_pending" in checks.HOW_TO


def test_nothing_pending_nothing_flagged():
    d = fitz.open()
    d.new_page()
    _room(d, 0, 100.0, False)
    assert not [f for f in checks.run(d, off=()) if f["rule"] == "ai_pending"]


def test_accepted_items_are_not_flagged():
    d = fitz.open()
    d.new_page()
    _room(d, 1, 40.0, True)
    a = [x for x in d[0].annots() if annotate.is_pending(d, x)][0]
    annotate.apply_op(d, {"kind": "set_annot", "page": 0, "id": "acc",
                          "payload": {"xref": a.xref, "status": "Accepted"}},
                      fresh=True)
    assert not [f for f in checks.run(d, off=()) if f["rule"] == "ai_pending"]


def test_rule_can_be_switched_off():
    d = fitz.open()
    d.new_page()
    _room(d, 1, 40.0, True)
    assert not [f for f in checks.run(d, off=("ai_pending",))
                if f["rule"] == "ai_pending"]
