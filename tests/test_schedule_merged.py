"""Door schedules with merged cells (round 2): a header cell spanning
two columns, upright strokes inside a header cell, and words printed
twice on top of each other must not lose or garble rows."""
import fitz

from app import schedules


def _sheet(extra_strokes=True, overprint=True):
    doc = fitz.open()
    page = doc.new_page(width=900, height=500)
    x = [50, 95, 260, 330, 380, 470]          # column rules
    top, hdr2, body = 80, 110, 125
    rows = ["D01", "D02", "D03", "D04"]
    bottom = body + 18 * len(rows)
    sh = page.new_shape()
    for xx in x:
        sh.draw_line((xx, top), (xx, bottom))
    for yy in (top, hdr2, body, bottom):
        sh.draw_line((x[0], yy), (x[-1], yy))
    sh.draw_line((x[2], top + 15), (x[4], top + 15))   # SIZE spans W, H
    if extra_strokes:
        # strokes inside the merged ID/ROOM header area, header only
        for xx in (120, 131):
            sh.draw_line((xx, top + 2), (xx, hdr2 - 2))
    sh.finish(color=(0, 0, 0), width=0.7)
    sh.commit()
    page.insert_text((x[0], top - 12), "DOOR SCHEDULE", fontsize=11)
    page.insert_text((60, 100), "ID", fontsize=9)
    page.insert_text((150, 100), "ROOM NAME", fontsize=9)
    page.insert_text((285, 92), "SIZE", fontsize=9)
    page.insert_text((290, 120), "W", fontsize=9)
    page.insert_text((350, 120), "H", fontsize=9)
    page.insert_text((395, 100), "NOTES", fontsize=9)
    names = ["MEN'S RESTROOM", "WOMEN'S RESTROOM", "HALL", "OFFICE"]
    for i, (k, n) in enumerate(zip(rows, names)):
        y = body + 13 + 18 * i
        page.insert_text((55, y), k, fontsize=9)
        page.insert_text((99, y), n, fontsize=9)
        page.insert_text((265, y), "3'-0\"", fontsize=9)
        page.insert_text((335, y), "6'-8\"", fontsize=9)
        page.insert_text((385, y), "STEEL", fontsize=9)
        if overprint:
            page.insert_text((385.3, y + 0.4), "STEEL", fontsize=9)
    return doc


def _door(doc):
    tabs = [t for t in schedules.read_page(doc[0]) if t["kind"] == "door"]
    assert tabs
    return tabs[0]


def test_every_row_read_with_merged_header_and_strokes():
    t = _door(_sheet())
    assert [r[t["key"]] for r in t["rows"]] == ["D01", "D02", "D03", "D04"]
    assert t["rows"][0]["ROOM NAME"] == "MEN'S RESTROOM"


def test_overprinted_word_reads_once():
    t = _door(_sheet())
    assert all(r.get("NOTES") == "STEEL" for r in t["rows"])


def test_two_level_header_read_with_small_glyph_heights_on():
    """The main window turns PyMuPDF's small-glyph-heights switch on, which
    shortens every word box: the W / H header line under the merged cell
    must still be read (and the switch put back afterwards)."""
    import fitz
    prev = fitz.TOOLS.set_small_glyph_heights()
    fitz.TOOLS.set_small_glyph_heights(True)
    try:
        t = _door(_sheet())
    finally:
        fitz.TOOLS.set_small_glyph_heights(prev)
    assert t["rows"][0]["ROOM NAME"] == "MEN'S RESTROOM"
    assert t["rows"][0]["W"] == "3'-0\"" and t["rows"][0]["H"] == "6'-8\""
    assert all(r.get("NOTES") == "STEEL" for r in t["rows"])


def test_make_cells_drops_overprint_only():
    w = [(10, 10, 40, 19, "STEEL", 0, 0, 0), (10.3, 10.4, 40.3, 19.4,
                                                "STEEL", 1, 0, 0),
         (10, 30, 40, 39, "STEEL", 2, 0, 0)]
    cs = schedules.make_cells(w)
    assert [c["text"] for c in cs] == ["STEEL", "STEEL"]


def _grouped_sheet():
    """Two-level header (DOOR PANEL / DOOR FRAME over sub-columns, a
    'HARDWARE SET' column heading) and floor heading rows across the
    table, with two-letter marks (GD1)."""
    doc = fitz.open()
    page = doc.new_page(width=1000, height=600)
    x = [40, 90, 150, 210, 280, 350, 430, 520]
    top = 60
    page.insert_text((300, top - 10), "DOOR SCHEDULE", fontsize=12)
    page.insert_text((160, top + 12), "DOOR PANEL", fontsize=8)
    page.insert_text((300, top + 12), "DOOR FRAME", fontsize=8)
    heads = ["MARK", "TYPE", "WIDTH", "FRAME", "FINISH", "HARDWARE SET",
             "COMMENTS"]
    for xx, hname in zip(x, heads):
        page.insert_text((xx + 4, top + 26), hname, fontsize=8)
    body = [("BASEMENT", None), ("B01", "D1"), ("B02", "D2"),
            ("FIRST FLOOR", None), ("101", "D1"), ("GD1", "D4"),
            ("GD2", "D4"), ("MEZZANINE", None), ("201A", "D1")]
    y = top + 44
    sh = page.new_shape()
    for k, typ in body:
        page.insert_text((x[0] + 4, y), k, fontsize=8)
        if typ:
            for xx, v in zip(x[1:], (typ, "3'-0\"", "F1", "PT", "3.1",
                                     "CARD READER")):
                page.insert_text((xx + 4, y), v, fontsize=8)
        y += 13
    for xx in x + [600]:
        sh.draw_line((xx, top + 17), (xx, y))
    sh.draw_line((x[0], top + 30), (600, top + 30))
    sh.finish(color=(0, 0, 0), width=0.5)
    sh.commit()
    return doc


def test_heading_rows_and_header_cells():
    tabs = schedules.read_page(_grouped_sheet()[0])
    kinds = [t["kind"] for t in tabs]
    assert "hardware" not in kinds          # a column heading, not a title
    t = [t for t in tabs if t["kind"] == "door"][0]
    assert [r[t["key"]] for r in t["rows"]] == ["B01", "B02", "101", "GD1",
                                                "GD2", "201A"]
    assert t["confident"]


def test_title_on_its_own_line_still_found():
    cells = schedules.make_cells([(10, 10, 120, 22, "DOOR", 0, 0, 0),
                                  (125, 10, 220, 22, "SCHEDULE", 0, 0, 1),
                                  (600, 10, 700, 22, "WINDOW", 1, 0, 0),
                                  (705, 10, 800, 22, "SCHEDULE", 1, 0, 1)])
    assert sorted(k for _c, k in schedules.titles(cells)) == ["door",
                                                              "window"]


def _two_line_keys():
    """Rows ruled one by one, the key cell printed on two lines ('1A101
    TO' over '1D102', '258A' over '258B') beside one-line cells."""
    doc = fitz.open()
    page = doc.new_page(width=800, height=400)
    x = [40, 100, 230, 300, 360, 600]
    top = 60
    page.insert_text((45, top - 8), "DOOR SCHEDULE UNIT 1", fontsize=11)
    for xx, h in zip(x, ["DOOR #", "ROOM NAME", "TYPE", "QUANTITY",
                         "REMARKS"]):
        page.insert_text((xx + 3, top + 11), h, fontsize=7)
    rows = [(("1A101 TO", "1D102"), "CELL A101-D102", "8"),
            (("1A103 TO", "1D116"), "CELL A103-D116", "56"),
            (("258A", "258B"), "SALLYPORT 258", "2")]
    sh = page.new_shape()
    y = top + 16
    ys = [top, y]
    for (k1, k2), name, q in rows:
        page.insert_text((x[0] + 3, y + 7), k1, fontsize=7)
        page.insert_text((x[0] + 3, y + 15), k2, fontsize=7)
        page.insert_text((x[1] + 3, y + 11), name, fontsize=7)
        page.insert_text((x[2] + 3, y + 11), "1", fontsize=7)
        page.insert_text((x[3] + 3, y + 11), q, fontsize=7)
        page.insert_text((x[4] + 3, y + 11), "REPLACE LOCK", fontsize=7)
        y += 18
        ys.append(y)
    for yy in ys:
        sh.draw_line((x[0], yy), (x[-1], yy))
    for xx in x:
        sh.draw_line((xx, top), (xx, y))
    sh.finish(color=(0, 0, 0), width=0.5)
    sh.commit()
    return doc


def test_two_line_key_cells_are_one_row():
    t = _door(_two_line_keys())
    assert [(r[t["key"]], r["QUANTITY"]) for r in t["rows"]] == [
        ("1A101 TO 1D102", "8"), ("1A103 TO 1D116", "56"),
        ("258A 258B", "2")]
    assert t["confident"]


def test_key_runs_and_lists():
    ok = schedules._key_ok
    assert ok("1A101 TO 1D102", "door") and ok("151A 151B 151C", "door")
    assert ok("GD1", "door") and ok("D01", "door") and ok("108A", "door")
    assert not ok("FIRST FLOOR", "door") and not ok("MEN'S", "door")


def test_drawing_index_entry_is_not_a_title():
    cells = schedules.make_cells([
        (10, 10, 40, 19, "A601", 0, 0, 0),
        (60, 10, 120, 19, "DOOR", 1, 0, 0),
        (124, 10, 190, 19, "SCHEDULE", 1, 0, 1),
        (194, 10, 200, 19, "&", 1, 0, 2),
        (204, 10, 260, 19, "DETAILS", 1, 0, 3)])
    assert schedules.titles(cells) == []


def _c(text, x0, cy, h=10.0):
    w = 6.0 * len(text)
    return {"text": text, "x0": x0, "x1": x0 + w, "y0": cy - h / 2,
            "y1": cy + h / 2, "cx": x0 + w / 2, "cy": cy, "h": h}


def test_panel_headings_side_by_side_stay_titles():
    """'PANEL LP1' beside 'PANEL LP2' (and other labels on the line) are
    still panel headings - the heading-row test is for column heads like
    'HARDWARE SET', not for panels drawn side by side."""
    from app import schedules as S
    cells = [_c("PANEL LP1", 100, 500), _c("PANEL LP2", 200, 500),
             _c("CABINET", 300, 500), _c("FIRE ALARM", 400, 500)]
    got = {c["text"]: k for c, k in S.titles(cells, "electrical")}
    assert got.get("PANEL LP1") == "panel"
    assert got.get("PANEL LP2") == "panel"
