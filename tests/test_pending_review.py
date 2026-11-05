"""Jon, Oct 31: an AI item still in review is not in any total; it is a
separate 'pending review' subtotal until a person accepts it."""
import pytest

fitz = pytest.importorskip("fitz")

from app import aitakeoff, annotate, estimate_book, takeoff_items  # noqa
from app.takeoff_tree import group_items, pending_text  # noqa: E402


def _room(d, i, value, review):
    annotate.apply_op(d, {"kind": "add_polygon", "page": 0, "id": f"r{i}",
                          "payload": {
                              "pts": [[50 + 60 * i, 50], [100 + 60 * i, 50],
                                      [100 + 60 * i, 100], [50 + 60 * i, 100]],
                              "dashes": [6, 4],
                              "measure": {"type": "area", "value": value,
                                          "unit": "sq ft", "group": "Room",
                                          "method": "AI takeoff: rooms" + (
                                              annotate.REVIEW_SUFFIX
                                              if review else "")}}},
                      fresh=True)


def _doc():
    d = fitz.open()
    d.new_page()
    _room(d, 0, 100.0, False)
    _room(d, 1, 40.0, True)
    return d


def test_review_item_is_pending_and_out_of_totals():
    d = _doc()
    its = annotate.takeoff_items(d)
    assert sorted(it["pending"] for it in its) == [False, True]
    assert [it["value"] for it in annotate.totals_items(d)] == [100.0]
    g = group_items(d)[0][("Room", "area", "sq ft")]
    assert (g["total"], g["n"], g["pending"], g["n_pending"]) == \
        (100.0, 1, 40.0, 1)
    it = [x for x in takeoff_items.items(d) if x["name"] == "Room"][0]
    assert it["total"] == 100.0 and it["pending"] == 40.0
    assert "(+40.0 sq ft pending)" in takeoff_items.fmt_total(it)


def test_accepting_it_puts_it_in_the_total():
    d = _doc()
    a = [x for x in d[0].annots() if annotate.is_pending(d, x)][0]
    annotate.apply_op(d, {"kind": "set_annot", "page": 0, "id": "acc",
                          "payload": {"xref": a.xref, "status": "Accepted",
                                      "dashes": []}}, fresh=True)
    g = group_items(d)[0][("Room", "area", "sq ft")]
    assert (g["total"], g["n_pending"]) == (140.0, 0)
    assert sum(it["value"] for it in annotate.totals_items(d)) == 140.0


def test_hand_measurement_is_never_pending():
    d = fitz.open()
    d.new_page()
    annotate.apply_op(d, {"kind": "add_polygon", "page": 0, "id": "m",
                          "payload": {"pts": [[10, 10], [60, 10], [60, 60]],
                                      "measure": {"type": "area",
                                                  "value": 5.0,
                                                  "unit": "sq ft",
                                                  "group": "Room"}}},
                      fresh=True)
    assert not annotate.takeoff_items(d)[0]["pending"]


def test_pending_text():
    assert pending_text(100.0, 40.0, "SF") == "100.0 SF (+40.0 SF pending)"


def _res():
    return {"sheets": {0: {"rooms": {"found": 2, "missed": 0, "sf": 300.0,
                                     "pending": 1, "pending_sf": 120.0}}},
            "quantities": [
                {"engine": "finishes", "name": "Floor VCT", "qty": 300.0,
                 "unit": "SF", "status": "taken off"},
                {"engine": "finishes", "name": "Floor VCT", "qty": 120.0,
                 "unit": "SF", "status": "pending review"},
                {"engine": "walls", "name": "Gross floor area",
                 "qty": 2400.0, "unit": "SF", "status": "review"}],
            "review": [{"sheet": "A101", "page": 0, "name":
                        "Gross floor area", "qty": 2400.0, "unit": "SF",
                        "engine": "walls", "why": "cross-check",
                        "line": True}],
            "marks": [(0, "add_polygon", {"measure": {
                "type": "area", "value": 120.0, "group": "Shower",
                "method": "AI takeoff: rooms (review)"}})],
            "problems": [], "scales": []}


def test_ai_totals_keep_pending_apart():
    t = aitakeoff.totals(_res())
    assert t["rooms_sf"] == 300.0 and t["rooms"] == 2
    assert t["finishes"] == {("Floor VCT", "SF"): 300.0}
    assert t["pending"] == {("Rooms in review", "SF"): 120.0,
                            ("Floor VCT", "SF"): 120.0,
                            ("Gross floor area", "SF"): 2400.0}
    txt = aitakeoff.summary_text([], _res())
    assert "Pending review (not in the totals until accepted" in txt
    assert "Gross floor area: 2,400 SF" in txt


def test_estimate_lists_pending_as_review_once():
    lines = estimate_book.collect([], _res())
    gross = [ln for ln in lines if ln["description"].startswith("Gross")]
    assert len(gross) == 1 and gross[0]["qty"] == 2400.0 and \
        gross[0]["status"] == "review"
    assert not any(ln["description"] == "Shower" and
                   ln["status"] == "taken off" for ln in lines)
    vct = {ln["status"]: ln["qty"] for ln in lines
           if "VCT" in ln["description"]}
    assert vct.get("taken off") == 300.0 and vct.get("review") == 120.0


def test_gypsum_ceiling_from_review_rooms_is_pending():
    """Gypsum board figured from the ceilings of rooms still in review is
    a pending line, not taken off (it was counted on the first run)."""
    from app import aitakeoff as ait
    res = {"quantities": [], "review": [], "problems": []}
    ait._gb_ceilings({"ceiling": {"PT-4": 400.0}}, res, "A-901",
                     {"PT-4": 150.0})
    gb = [q for q in res["quantities"] if q["name"] == "Gypsum board ceiling"]
    st = {q["status"]: q["qty"] for q in gb}
    assert st == {"taken off": 250.0, "pending review": 150.0}
    sheets = [q for q in res["quantities"] if "sheets" in q["name"]]
    assert sheets and sheets[0]["status"] == "taken off"
    res = {"quantities": [], "review": [], "problems": []}
    ait._gb_ceilings({"ceiling": {"PT-4": 400.0}}, res, "A-901",
                     {"PT-4": 400.0})
    assert [q["status"] for q in res["quantities"]] == ["pending review"]
