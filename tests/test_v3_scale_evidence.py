"""AI Takeoff v3 (Oct 31 2026), feature 4: each sheet's scale comes with a
0-100 confidence, the reasons, and a picture of the printed words it was
read from. A doubtful scale (under 60) on a sheet that is measured goes
to review: its lengths and areas wait (counts don't depend on scale)."""
import os

import pytest

fitz = pytest.importorskip("fitz")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import aitakeoff as ait, annotate, scale_evidence as se  # noqa

Q = ('1/4" = 1\'-0"', 18.0, "ft")


def _sheet(doc, scale_text="SCALE: 1/4\" = 1'-0\"", dims_ppu=18.0,
           rotate=0):
    """A plan with a scale note and four dimension strings whose lines
    are drawn at dims_ppu points per foot."""
    page = doc.new_page(width=1224, height=792)
    page.insert_text((900, 740), scale_text, fontsize=10)
    for k, ft in enumerate((10, 12, 14, 16)):
        y = 120 + 80 * k
        x0, x1 = 100, 100 + ft * dims_ppu
        page.draw_line((x0, y), (x1, y), width=0.5)
        page.insert_text(((x0 + x1) / 2 - 15, y - 4), f"{ft}'-0\"",
                         fontsize=8)
    if rotate:
        page.set_rotation(rotate)
    return page


def test_scale_with_the_word_scale_and_agreeing_dimensions_is_sure():
    doc = fitz.open()
    p = _sheet(doc)
    e = se.evidence(p, Q)
    assert e["score"] >= 80 and not e["review"]
    assert any("SCALE" in r for r in e["reasons"])
    assert any("dimensions measure at this scale" in r for r in e["reasons"])
    r = fitz.Rect(e["rect"])
    assert r.width < 200 and r.height < 20       # just the printed words
    assert "1/4" in e["text"] and "SCALE" in e["text"]


def test_dimensions_at_another_scale_send_it_to_review():
    doc = fitz.open()
    p = _sheet(doc, dims_ppu=9.0)          # drawn at 1/8" but says 1/4"
    e = se.evidence(p, Q)
    assert e["score"] < se.REVIEW_BELOW and e["review"]
    assert any("printed to fit" in r for r in e["reasons"])


def test_no_word_scale_no_dimensions_is_middling():
    # Oct 31 calibration on the real sets (Missouri: every plan sheet has
    # one clean scale and no dimension strings): a scale read cleanly with
    # nothing against it is at the line, not sent to review
    doc = fitz.open()
    page = doc.new_page(width=1224, height=792)
    page.insert_text((900, 740), "1/4\" = 1'-0\"", fontsize=10)
    e = se.evidence(page, Q)
    assert e["score"] == se.REVIEW_BELOW and not e["review"]


def test_a_second_scale_on_the_sheet_unchecked_goes_to_review():
    doc = fitz.open()
    page = doc.new_page(width=1224, height=792)
    page.insert_text((900, 740), "1/4\" = 1'-0\"", fontsize=10)
    page.insert_text((300, 500), "ENLARGED PLAN 1/2\" = 1'-0\"", fontsize=10)
    e = se.evidence(page, Q)
    assert e["score"] < se.REVIEW_BELOW and e["review"]


def test_evidence_crop_is_a_picture_of_the_words():
    doc = fitz.open()
    p = _sheet(doc)
    e = se.evidence(p, Q)
    png = se.crop_png(p, e["rect"])
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    pix = fitz.Pixmap(png)
    assert pix.width > pix.height * 3        # a line of text, level
    assert len(set(pix.samples)) > 1         # not blank


def test_crop_on_a_sideways_sheet_is_not_blank():
    doc = fitz.open()
    p = _sheet(doc, rotate=90)
    e = se.evidence(p, Q)
    pix = fitz.Pixmap(se.crop_png(p, e["rect"]))
    assert len(set(pix.samples)) > 1


def test_scale_set_by_a_person_is_100():
    doc = fitz.open()
    p = _sheet(doc)
    assert se.evidence(p, Q, user=True)["score"] == 100


def test_low_dpi_scan_read_by_ocr_is_sent_to_review():
    doc = fitz.open()
    page = doc.new_page(width=1224, height=792)
    e = se.evidence(page, Q, source="ocr", dpi=100)
    assert e["score"] < se.REVIEW_BELOW and e["review"]
    assert any("DPI" in r for r in e["reasons"])
    assert any("OCR" in r for r in e["reasons"])


def test_scan_with_no_text_says_so():
    e = se.evidence(None, None, source="scan", dpi=100)
    assert e["score"] == 0 and e["review"]
    assert any("100 DPI" in r for r in e["reasons"])


def test_plan_set_rows_carry_the_evidence():
    doc = fitz.open()
    p = _sheet(doc)
    p.insert_text((900, 760), "A101 FIRST FLOOR PLAN", fontsize=12)
    rows = ait.plan_set(doc)
    r = rows[0]
    assert r["scale_conf"] >= 80 and r["scale_rect"] and r["scale_why"]
    assert r["scale_review"] is False


def test_doubtful_scale_holds_the_sheets_lengths_and_areas():
    rows = [{"page": 0, "number": "A101", "title": "PLAN",
             "scale": list(Q), "engines": ["rooms"], "wanted": ["rooms"],
             "scale_conf": 45, "scale_review": True,
             "scale_why": ["printed once"], "scale_rect": [1, 2, 3, 4],
             "scale_text": "1/4\" = 1'-0\"", "source": "vector"}]
    res = {"marks": [
        (0, "add_polygon", {"measure": {"type": "area", "value": 100.0,
                                        "unit": "sq ft", "group": "HALL",
                                        "method": "AI takeoff: rooms"}}),
        (0, "add_line", {"measure": {"type": "length", "value": 20.0,
                                     "unit": "ft", "group": "Wall",
                                     "method": "AI takeoff: walls"}}),
        (0, "add_count", {"measure": {"type": "count", "value": 1,
                                      "unit": "ea", "group": "Doors",
                                      "method": "AI takeoff: schedules"}})],
        "sheets": {0: {"rooms": {"found": 1, "missed": 0, "sf": 100.0,
                                 "pending": 0, "pending_sf": 0},
                       "walls": {"Wall 8in": 20.0},
                       "schedules": {"Doors": 1}}},
        "quantities": [{"engine": "walls", "name": "Gross floor area",
                        "qty": 2400.0, "unit": "SF", "status": "taken off",
                        "page": 0}],
        "review": [], "problems": []}
    ait.scale_review(rows, res)
    meth = [m[2]["measure"]["method"] for m in res["marks"]]
    assert meth[0].endswith(annotate.REVIEW_SUFFIX)
    assert meth[1].endswith(annotate.REVIEW_SUFFIX)
    assert not meth[2].endswith(annotate.REVIEW_SUFFIX)     # a count
    item = [x for x in res["review"] if x.get("kind") == "scale"][0]
    assert item["confidence"] == 0.45 and item["rect"] == [1, 2, 3, 4]
    t = ait.totals(res)
    assert t["rooms_sf"] == 0 and t["walls"] == {}
    assert t["schedules"] == {"Doors": 1}
    assert t["pending"][("Rooms (scale to check)", "SF")] == 100.0
    assert t["pending"][("Wall 8in", "LF")] == 20.0
    assert t["pending"][("Gross floor area", "SF")] == 2400.0
    assert res["quantities"][0]["status"] == "pending review"
