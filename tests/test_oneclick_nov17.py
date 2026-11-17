"""One-click takeoff (Nov 17), all on made-up data:

(a) AI Takeoff adds the work notes' totals: a plain count is taken off, a
    length or a flagged note waits for review, and a count another engine
    already made waits for review instead of being added twice.
(b) A drawing with unsaved changes (no file) still has its notes read,
    from a temporary copy.
(c) A scanned floor plan with a scale goes to the rooms engine; without a
    scale it asks for one; a scanned detail sheet is still measured by
    hand.
(d) A scanned plan with no readable room names says to run OCR first, and
    the summary lists the scanned plans whose rooms were traced.
"""
import os
import sys

import fitz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import aitakeoff as ait  # noqa: E402

W, H = 1728, 1152


def note(action, what, qty, unit="EA", sheet="E-101", check=(), approx=False):
    return {"action": action, "what": what, "qty": qty, "unit": unit,
            "sheet": sheet, "check": list(check), "approx": approx}


def saved_doc(tmp_path, text="GENERAL NOTES"):
    d = fitz.open()
    p = d.new_page(width=W, height=H)
    p.insert_text((100, 100), text, fontsize=10)
    f = tmp_path / "madeup.pdf"
    d.save(f)
    d.close()
    return fitz.open(f)


def blank_res():
    return {"quantities": [], "problems": [], "review": [], "sheets": {}}


# ---- (a) ------------------------------------------------------------------
def test_a_counts_taken_off_lengths_and_flags_pending(tmp_path):
    doc = saved_doc(tmp_path)
    rows = [note("INSTALL", "MANUAL TRANSFER SWITCH", 2),
            note("INSTALL", "MANUAL TRANSFER SWITCH", 1, sheet="E-102"),
            note("REPLACE", "CHAIN LINK FENCE", 120, unit="LF"),
            note("INSTALL", "PULL BOX", 3, check=["two notes on one sheet"])]
    res = blank_res()
    n = ait.worknotes(doc, {0: {"number": "E-101"}}, res,
                      read=lambda path: (rows, {}))
    assert n == 3
    by = {q["name"]: q for q in res["quantities"]}
    mts = by["INSTALL MANUAL TRANSFER SWITCH"]
    assert mts["qty"] == 3 and mts["status"] == "taken off"
    assert mts["engine"] == ait.WORKNOTE_SOURCE
    assert "E-101" in mts["sheet"] and "E-102" in mts["sheet"]
    assert by["REPLACE CHAIN LINK FENCE"]["status"] == "pending review"
    pb = by["INSTALL PULL BOX"]
    assert pb["status"] == "pending review"
    assert "check: two notes on one sheet" in pb["basis"]


def test_a_count_already_made_by_a_symbol_waits(tmp_path):
    doc = saved_doc(tmp_path)
    res = blank_res()
    res["sheets"][0] = {"devices": {"Manual transfer switch": 2}}
    ait.worknotes(doc, {0: {"number": "E-101"}}, res,
                  read=lambda path: ([note("INSTALL",
                                           "MANUAL TRANSFER SWITCH", 2)], {}))
    q = res["quantities"][0]
    assert q["status"] == "pending review"
    assert "may already have it" in q["basis"]


def test_a_zero_quantity_notes_left_out(tmp_path):
    doc = saved_doc(tmp_path)
    res = blank_res()
    assert ait.worknotes(doc, {}, res, read=lambda path: (
        [note("INSTALL", "GROUND ROD", 0)], {})) == 0
    assert res["quantities"] == []


# ---- (b) ------------------------------------------------------------------
def test_b_unsaved_drawing_read_from_a_temporary_copy():
    d = fitz.open()
    d.new_page(width=W, height=H)
    seen = []

    def read(path):
        seen.append(path)
        assert os.path.isfile(path)
        return [note("INSTALL", "GROUND ROD", 8)], {}
    res = blank_res()
    assert ait.worknotes(d, {}, res, read=read) == 1
    assert seen and not os.path.exists(seen[0])     # cleaned up
    assert res["quantities"][0]["qty"] == 8


def test_b_run_with_no_notes_adds_nothing(tmp_path):
    doc = saved_doc(tmp_path)
    res = ait.run(doc, [], engines=["worknotes"])
    assert not [q for q in res["quantities"]
                if q["engine"] == ait.WORKNOTE_SOURCE]
    assert "work notes" in res["timing"]


# ---- (c) ------------------------------------------------------------------
def scanned(doc, number, title, scale="1/4\" = 1'-0\"", rooms=()):
    """A made-up scan: a picture over the whole sheet with a text layer
    (what OCR leaves) for its title block and room names."""
    page = doc.new_page(width=W, height=H)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 64, 48), False)
    pix.clear_with(235)
    page.insert_image(page.rect, pixmap=pix)
    for (x, y), s in [((W - 285, H - 182), title),
                      ((W - 285, H - 110), f"SCALE: {scale}" if scale
                       else ""),
                      ((W - 285, H - 60), number)] + list(rooms):
        if s:
            page.insert_text((x, y), s, fontsize=12, render_mode=3)
    return page


def test_c_scanned_plan_goes_to_rooms_engine():
    d = fitz.open()
    scanned(d, "A-101", "FLOOR PLAN")
    rows = ait.plan_set(d)
    r = rows[0]
    assert r["raster"] and r["source"] == "scan"
    assert r["kind"] == "plan"
    assert r["engines"] == ["rooms"]
    assert "rooms traced from the picture" in r["note"]


def test_c_scanned_plan_without_scale_asks_for_one():
    d = fitz.open()
    scanned(d, "A-102", "FLOOR PLAN", scale="")
    r = ait.plan_set(d)[0]
    assert r["engines"] == [] and r["wanted"] == ["rooms"]
    assert "set its scale" in r["note"]


def test_c_scanned_detail_sheet_still_by_hand():
    d = fitz.open()
    scanned(d, "A-501", "WALL SECTIONS AND DETAILS", scale="1-1/2\" = 1'-0\"")
    r = ait.plan_set(d)[0]
    assert r["kind"] == "raster" and r["engines"] == []
    assert "measure by hand" in r["note"]


def test_c_scanned_plans_not_used_for_walls():
    rows = [{"page": 0, "engines": ["rooms"], "scale": ("1/4", 18.0, "ft"),
             "kind": "plan", "raster": True, "title": "FLOOR PLAN"}]
    assert ait.walls_pages(rows)[0] == []


# ---- (d) ------------------------------------------------------------------
def test_d_scan_with_no_room_names_says_ocr(tmp_path):
    d = fitz.open()
    scanned(d, "A-101", "FLOOR PLAN")
    rows = ait.plan_set(d)
    res = ait.run(d, rows, engines=["rooms"])
    assert any("Make Searchable (OCR)" in p for p in res["problems"]), \
        res["problems"]
    text = ait.summary_text(rows, res)
    assert "rooms traced from the picture (1): A-101" in text
