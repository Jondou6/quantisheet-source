"""AI Takeoff, Oct 31 2026: each sheet says whether it is vector linework
or a scan (and a scan's resolution, with a warning under 150 DPI); every
CHECK item carries its sheet's source and a score, the summary lists them
least sure first and shows what review removed or logged as missed; a
second run doesn't add the same measurements again; a rough-opening note
("RO" by a door tag) is not a room. Made-up drawings only."""
import os

import fitz

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import aitakeoff as ait, annotate, autotakeoff, review   # noqa: E402


def _scan_page(doc, px_w):
    """A sheet that is one picture px_w pixels wide over a 36" page."""
    page = doc.new_page(width=2592, height=1728)
    pix = fitz.Pixmap(fitz.csGRAY, fitz.IRect(0, 0, px_w,
                                              int(px_w * 2 / 3)), False)
    pix.clear_with(255)
    page.insert_image(page.rect, pixmap=pix)
    return page


def test_scan_resolution_and_source_per_sheet():
    doc = fitz.open()
    _scan_page(doc, 3600)         # 100 DPI across 36"
    _scan_page(doc, 10800)        # 300 DPI
    v = doc.new_page(width=2592, height=1728)
    v.insert_text((100, 100), "SCALE: 1/4\" = 1'-0\"", fontsize=10)
    assert round(ait.scan_dpi(doc[0])) == 100
    assert round(ait.scan_dpi(doc[1])) == 300
    assert ait.scan_dpi(v) is None
    rows = ait.plan_set(doc)
    assert [r["source"] for r in rows] == ["scan", "scan", "vector"]
    assert "under 150 DPI" in rows[0]["note"]
    assert "under 150 DPI" not in rows[1]["note"]
    assert "about 300 DPI" in rows[1]["note"]     # the DPI is always shown
    text = ait.summary_text(rows, ait.run(doc, rows))
    assert "1 vector, 2 scanned" in text
    assert "under 150 DPI" in text


def _res():
    return {"marks": [], "scales": [], "assemblies": {}, "sheets": {},
            "problems": [], "existing": [], "unfinished": [],
            "rooms_dup": [], "timing": {}, "quantities": [],
            "schedules": None, "steel_dup": [], "finishes": None,
            "walls": {},
            "review": [
                {"sheet": "A101", "page": 0, "name": "HALL 106",
                 "qty": 131.0, "unit": "sq ft", "engine": "rooms",
                 "confidence": 0.7, "why": "no area in the tag"},
                {"sheet": "A1", "page": 1, "name": "STORAGE",
                 "qty": 80.0, "unit": "sq ft", "engine": "rooms",
                 "confidence": 0.7, "why": "room trace not sure"},
                {"sheet": "M101", "page": 0, "name": "Duct 8in wide",
                 "qty": 102.0, "unit": "ft", "engine": "ducts",
                 "why": "no size tag at this duct - measure it by hand"}]}


def test_sources_and_scores_go_on_every_item_and_least_sure_comes_first():
    rows = [{"page": 0, "number": "A101", "title": "", "engines": [],
             "wanted": [], "kind": "plan", "source": "vector",
             "note": ""},
            {"page": 1, "number": "A1", "title": "", "engines": [],
             "wanted": [], "kind": "raster", "source": "scan",
             "note": "raster sheet"}]
    res = _res()
    ait.mark_sources(rows, res)
    assert [x["source"] for x in res["review"]] == ["vector", "scan",
                                                    "vector"]
    text = ait.summary_text(rows, res)
    i_duct = text.index("Duct 8in wide")
    i_store = text.index("STORAGE")
    i_hall = text.index("HALL 106")
    assert i_duct < i_store < i_hall           # 35 < 42 < 70
    assert "score 35/100" in text
    assert "least sure first" in text


def test_summary_shows_what_review_removed_and_missed():
    rows = []
    res = _res()
    review.delete(res, res["review"][2], reason="not there", log_path=None)
    review.missed(res, "WOMEN'S SHOWER 109", sheet="A101", qty=151.7,
                  unit="sq ft", log_path=None)
    text = ait.summary_text(rows, res)
    assert "Removed or missed in review (2)" in text
    assert "Duct 8in wide - deleted (not there)" in text
    assert "WOMEN'S SHOWER 109 - missed" in text


def test_a_second_run_does_not_add_the_same_measurements():
    doc = fitz.open()
    doc.new_page(width=600, height=400)
    mark = (0, "add_polygon", {
        "pts": [(10, 10), (110, 10), (110, 60), (10, 60)],
        "label": "OFFICE 101: 100 sq ft",
        "measure": {"type": "area", "value": 100.0, "unit": "sq ft",
                    "group": "OFFICE 101", "method": "AI takeoff: rooms"}})
    other = (0, "add_polyline", {
        "pts": [(10, 100), (210, 100)], "label": "Wall Type A: 11 ft",
        "measure": {"type": "length", "value": 11.1, "unit": "ft",
                    "group": "Wall Type A", "method": "AI takeoff: walls"}})
    kept, dropped = ait.skip_repeats(doc, [mark, other])
    assert len(kept) == 2 and dropped == 0
    annotate.apply_op(doc, annotate.new_op(mark[1], 0, **mark[2]))
    kept, dropped = ait.skip_repeats(doc, [mark, other])
    assert kept == [other] and dropped == 1


def test_rough_opening_note_is_not_a_room():
    doc = fitz.open()
    page = doc.new_page(width=600, height=400)
    assert autotakeoff._not_a_room(page, "RO", fitz.Point(50, 50),
                                   fitz.Point(50, 50))
    assert autotakeoff._not_a_room(page, "R.O. D07", fitz.Point(50, 50),
                                   fitz.Point(50, 50))
    assert not autotakeoff._not_a_room(page, "ROOM 101",
                                       fitz.Point(50, 50),
                                       fitz.Point(50, 50))
    assert not autotakeoff._not_a_room(page, "ROBING", fitz.Point(50, 50),
                                       fitz.Point(50, 50))


def test_scan_dpi_reads_a_scan_saved_in_strips():
    """Scanners often save a sheet as many thin strips: the DPI is read
    from the strips together, not only from one picture covering it."""
    import io
    import numpy as np
    from PIL import Image
    d = fitz.open()
    p = d.new_page(width=720, height=480)          # 10" x 6.67"
    buf = io.BytesIO()
    Image.fromarray(np.full((56, 1000), 200, np.uint8)).save(buf, "PNG")
    png = buf.getvalue()                           # 1000 px over 10" = 100
    for k in range(12):
        p.insert_image(fitz.Rect(0, k * 40, 720, k * 40 + 40), stream=png)
    dpi = ait.scan_dpi(p)
    assert dpi is not None and 95 <= dpi <= 105, dpi


def test_a_second_run_skips_unlabelled_wall_lines_too():
    """Wall lines carry no label (only a measure group): found on the real
    HMB set, where a second run added 105 wall lines again."""
    doc = fitz.open()
    doc.new_page(width=600, height=400)

    def wall(y, x1=300):
        return (0, "add_line", {
            "pts": [[20.4, y + 0.3], [x1 + 0.2, y + 0.4]],
            "color": [0.85, 0.2, 0.2], "width": 3, "opacity": 0.55,
            "measure": {"type": "length", "value": 10.0, "unit": "ft",
                        "group": "Exterior Walls",
                        "method": "AI takeoff: walls"}})
    first = [wall(50), wall(90), wall(130)]
    for m in first:
        annotate.apply_op(doc, annotate.new_op(m[1], 0, **m[2]))
    kept, dropped = ait.skip_repeats(doc, first + [wall(170)])
    assert dropped == 3 and len(kept) == 1
    # same place, other item: not a repeat
    other = (0, "add_line", dict(first[0][2], measure=dict(
        first[0][2]["measure"], group="Interior Walls")))
    kept, dropped = ait.skip_repeats(doc, [other])
    assert dropped == 0 and len(kept) == 1


def test_engines_read_the_drawing_without_earlier_ai_marks():
    """Found on the real HMB set: a second run read the first run's room
    outlines as 'already measured' and traced walls and rooms differently,
    so its repeats didn't line up. The engines' copy drops the AI's own
    marks (a person's measurements stay, so rooms they did are skipped)."""
    doc = fitz.open()
    doc.new_page(width=600, height=400)
    ai = (0, "add_polygon", {
        "pts": [(10, 10), (110, 10), (110, 60), (10, 60)],
        "label": "OFFICE 101: 100 sq ft",
        "measure": {"type": "area", "value": 100.0, "unit": "sq ft",
                    "group": "OFFICE 101", "method": "AI takeoff: rooms"}})
    hand = (0, "add_polygon", {
        "pts": [(200, 10), (300, 10), (300, 60), (200, 60)],
        "label": "OFFICE 102: 100 sq ft",
        "measure": {"type": "area", "value": 100.0, "unit": "sq ft",
                    "group": "OFFICE 102", "method": "manual"}})
    for m in (ai, hand):
        annotate.apply_op(doc, annotate.new_op(m[1], 0, **m[2]))
    n = ait.strip_ai_marks(doc)
    assert n >= 1
    left = [(a.info or {}).get("subject", "") for a in doc[0].annots()]
    assert any("OFFICE 102" in s for s in left)
    assert not any("OFFICE 101" in s for s in left)
