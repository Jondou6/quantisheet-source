"""AI Takeoff v3 (Oct 31 2026), feature 2: AI markups look different from
a person's on the drawing until they are accepted - a dashed line / ring
and a small "AI" badge - and that survives save, reopen and export.

Export rule (annotate.EXPORT_RULE): a drawing export (save, flattened PDF,
print, XFDF) shows the canvas as it is - a not-yet-accepted AI markup
keeps its dashes and badge, an accepted one is solid with no badge; a
quantity export totals only accepted and hand measurements, says where
each line came from, and lists AI items still in review apart."""
import csv

import pytest

fitz = pytest.importorskip("fitz")

from app import annotate, estimate  # noqa: E402

PENCIL = [6, 4]


def _add(d, oid, ai=True, kind="add_polygon", pts=None, group="Room",
         value=100.0, review=False, mtype="area", unit="sq ft"):
    pts = pts or [[50, 50], [150, 50], [150, 150], [50, 150]]
    payload = {"pts": pts, "label": f"{group}: {value:g}",
               "measure": {"type": mtype, "value": value, "unit": unit,
                           "group": group}}
    if kind == "add_count":
        payload = {"pt": pts[0], "n": 1,
                   "measure": {"type": "count", "value": 1, "unit": "ea",
                               "group": group}}
    if ai:
        payload["measure"]["method"] = "AI takeoff: rooms" + (
            annotate.REVIEW_SUFFIX if review else "")
        payload["dashes"] = list(PENCIL)
        payload["badge"] = True
    annotate.apply_op(d, {"kind": kind, "page": 0, "id": oid,
                          "payload": payload}, fresh=True)


def _badges(d, pno=0):
    page = d[pno]
    return [(a.info or {}).get("content") and a for a in page.annots() or []
            if annotate.is_badge(d, a)]


def _doc():
    d = fitz.open()
    d.new_page(width=600, height=400)
    return d


def test_ai_mark_gets_a_badge_a_hand_mark_does_not():
    d = _doc()
    _add(d, "ai1")
    _add(d, "me1", ai=False, pts=[[300, 50], [400, 50], [400, 150]])
    b = _badges(d)
    assert len(b) == 1
    assert (b[0].info or {}).get("content") == annotate.BADGE_TEXT
    assert annotate.tag_of(b[0]) == "ai1"
    origins = sorted(annotate.origin(d, a) for a in d[0].annots()
                     if (a.info or {}).get("subject", "").startswith(
                         annotate.TAKEOFF + ":"))
    assert origins == ["ai-pending", "manual"]


def test_badge_is_part_of_the_measurement_not_a_markup_of_its_own():
    d = _doc()
    _add(d, "ai1")
    assert len(annotate.takeoff_items(d)) == 1
    assert all(m.get("tag") != "ai1" or m.get("type") != "freetext"
               for m in annotate.markup_items(d)
               if "AI" == str(m.get("text", "")).strip())
    # an area label refresh (cutouts) never rewrites the badge
    annotate.refresh_area_labels(d, 0)
    assert [(x.info or {}).get("content") for x in _badges(d)] == ["AI"]


def test_count_gets_a_badge_too():
    d = _doc()
    _add(d, "c1", kind="add_count", pts=[[200, 200]], group="Doors")
    assert len(_badges(d)) == 1


def test_accepting_takes_the_badge_off_and_makes_it_solid():
    d = _doc()
    _add(d, "ai1")
    annotate.apply_op(d, {"kind": "set_annot", "page": 0, "id": "acc",
                          "payload": {"target": "ai1", "status": "Accepted",
                                      "dashes": [], "badge": False}},
                      fresh=True)
    assert _badges(d) == []
    page = d[0]
    poly = [a for a in page.annots() if a.type[0] == fitz.PDF_ANNOT_POLYGON]
    assert not (poly[0].border or {}).get("dashes")
    assert annotate.origin(d, poly[0]) == "ai-accepted"


def test_check_takeoff_accept_takes_the_badge_off_too():
    # Check Takeoff accepts with status + solid line only (_solid)
    from app import tradetakeoff_ui
    d = _doc()
    _add(d, "ai1")
    assert len(_badges(d)) == 1
    pay = dict({"target": "ai1", "status": "Accepted"},
               **tradetakeoff_ui._solid({"method": "AI takeoff: rooms"}))
    annotate.apply_op(d, {"kind": "set_annot", "page": 0, "id": "acc",
                          "payload": pay}, fresh=True)
    assert _badges(d) == []


def test_deleting_takes_the_badge_with_it():
    d = _doc()
    _add(d, "ai1")
    annotate.apply_op(d, {"kind": "delete_annot", "page": 0, "id": "del",
                          "payload": {"target": "ai1"}}, fresh=True)
    assert list(d[0].annots() or []) == []


def test_survives_save_and_reopen(tmp_path):
    d = _doc()
    _add(d, "ai1")
    _add(d, "ai2", pts=[[300, 50], [400, 50], [400, 150], [300, 150]])
    annotate.apply_op(d, {"kind": "set_annot", "page": 0, "id": "acc",
                          "payload": {"target": "ai2", "status": "Accepted",
                                      "dashes": [], "badge": False}},
                      fresh=True)
    p = str(tmp_path / "saved.pdf")
    d.save(p)
    d2 = fitz.open(p)
    b = _badges(d2)
    assert [annotate.tag_of(x) for x in b] == ["ai1"]
    page = d2[0]
    polys = {annotate.tag_of(a): a for a in page.annots()
             if a.type[0] == fitz.PDF_ANNOT_POLYGON}
    assert (polys["ai1"].border or {}).get("dashes")
    assert not (polys["ai2"].border or {}).get("dashes")
    assert annotate.origin(d2, polys["ai1"]) == "ai-pending"
    assert annotate.origin(d2, polys["ai2"]) == "ai-accepted"


def test_flattened_export_shows_the_badge():
    from app import acrobat
    d = _doc()
    _add(d, "ai1")
    acrobat.flatten(d)
    assert "AI" in d[0].get_text()
    assert not list(d[0].annots() or [])


def test_quantity_export_rule(tmp_path):
    d = _doc()
    _add(d, "acc", group="Office", value=100.0)
    _add(d, "pend", group="Shower", value=40.0, review=True,
         pts=[[300, 50], [400, 50], [400, 150], [300, 150]])
    _add(d, "me", ai=False, group="Hall", value=60.0,
         pts=[[50, 200], [150, 200], [150, 300], [50, 300]])
    annotate.apply_op(d, {"kind": "set_annot", "page": 0, "id": "a",
                          "payload": {"target": "acc", "status": "Accepted",
                                      "dashes": [], "badge": False}},
                      fresh=True)
    p = str(tmp_path / "q.csv")
    estimate.export_csv(d, p)
    rows = list(csv.reader(open(p, encoding="utf-8-sig")))
    i = rows.index(["Detail"])
    hdr = rows[i + 1]
    assert hdr[-1] == "Origin"
    end = rows.index([], i)
    detail = {r[1]: r[-1] for r in rows[i + 2:end]}
    assert detail["Office"] == "AI, accepted"
    assert detail["Hall"] == "manual"
    assert "Shower" not in detail                    # not in any total
    j = rows.index(["Pending review (AI, not in the totals)"])
    pend = [r for r in rows[j + 1:] if len(r) >= 4]
    assert pend[1][1] == "Shower" and pend[1][-1] == "AI, not checked"


def test_export_rule_is_written_down():
    assert "badge" in annotate.EXPORT_RULE and \
        "not in" in annotate.EXPORT_RULE


def test_xfdf_round_trip_keeps_the_badge(tmp_path):
    from app import xfdf
    d = _doc()
    _add(d, "ai1")
    p = str(tmp_path / "m.xfdf")
    xfdf.export(d, p)
    assert "ps-badge" in open(p, encoding="utf-8").read()
