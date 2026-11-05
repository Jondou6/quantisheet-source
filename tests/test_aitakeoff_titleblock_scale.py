"""AI Takeoff accuracy, Oct 31 2026 (public bid sets): the sheet title is
read from title blocks that print it sideways under a "DRAWING:" label or
under a "SHEET NAME" label, and a scale split over three text lines
('SCALE: 1/4"' / '=' / "1'-0\"") is read. Without the title every plan
looked like the same floor, so walls were taken from the site plan or the
demolition plan instead of the floor plan. Every drawing here is made up
in the test - no real project drawings.
"""
import os

import fitz

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import aitakeoff as ait, sheets, takeoff                    # noqa: E402

W, H = 2592, 1728


def _sideways_sheet(doc, number, title, scale_lines):
    """Title block on the right edge: 'DRAWING:' and the title printed
    bottom-to-top, the sheet number upright under 'SHEET:'."""
    page = doc.new_page(width=W, height=H)
    page.draw_rect(fitz.Rect(36, 36, W - 36, H - 36), color=(0, 0, 0))
    page.insert_text((2470, 1210), "PROJECT:", fontsize=8, rotate=90)
    page.insert_text((2485, 1210), "MADE-UP TEST PROJECT", fontsize=10,
                     rotate=90)
    page.insert_text((2524, 1219), "DRAWING:", fontsize=8, rotate=90)
    page.insert_text((2546, 1214), title, fontsize=22, rotate=90)
    page.insert_text((2459, 1622), "SHEET:", fontsize=14)
    page.insert_text((2431, 1670), number, fontsize=45)
    y = 1500
    for ln in scale_lines:
        page.insert_text((300, y), ln, fontsize=12)
        y += 16
    return page


def _sheet_name_block(doc, number, title_lines):
    """'SHEET NAME' label with the title on lines below it, then
    'SHEET NUMBER'."""
    page = doc.new_page(width=W, height=H)
    page.insert_text((2357, 1536), "SHEET NAME", fontsize=7.5)
    y = 1560
    for ln in title_lines:
        page.insert_text((2357, y), ln, fontsize=20)
        y += 23
    page.insert_text((2357, 1659), "SHEET NUMBER", fontsize=7.5)
    page.insert_text((2424, 1695), number, fontsize=37)
    page.insert_text((300, 1500), "SCALE: 1/8\" = 1'-0\"", fontsize=12)
    return page


def test_sideways_title_under_a_drawing_label():
    doc = fitz.open()
    _sideways_sheet(doc, "A101", "MAIN LEVEL FLOOR PLAN",
                    ["SCALE: 1/4\" = 1'-0\""])
    r = sheets.scan(doc, [0], numbers=False)[0]
    assert r["number"] == "A101"
    assert r["title"] == "MAIN LEVEL FLOOR PLAN"


def test_title_on_lines_under_a_sheet_name_label():
    doc = fitz.open()
    _sheet_name_block(doc, "A-101.5", ["THIRD LEVEL", "FLOOR PLAN AND",
                                        "RCP"])
    r = sheets.scan(doc, [0], numbers=False)[0]
    assert r["number"] == "A-101.5"
    assert r["title"] == "THIRD LEVEL FLOOR PLAN AND RCP"


def test_label_with_no_bigger_text_after_it_gives_no_title():
    doc = fitz.open()
    page = doc.new_page(width=W, height=H)
    page.insert_text((2357, 1536), "SHEET NAME", fontsize=7.5)
    page.insert_text((2357, 1550), "see index", fontsize=7.5)
    page.insert_text((2424, 1695), "A-102", fontsize=37)
    assert sheets.title_from_lines(page) == ""


def test_scale_split_over_three_lines_is_read():
    text = "1  MAIN LEVEL PLAN - MECHANICAL\nSCALE: 1/4\"\n=\n1'-0\"\n"
    assert takeoff.main_scale(text) == ("1/4\" = 1'-0\"", 18.0, "ft")
    text = "SITE PLAN\nSCALE: 1\"\n=\n20'\n"
    assert takeoff.main_scale(text)[1:] == (3.6, "ft")


def test_split_scale_join_stays_narrow():
    # a sheet-number tail and a lone fraction on the next line is still
    # not a mixed number, and '=' with nothing in feet after it is nothing
    assert takeoff.find_scales("A-02\n1/2\"\n=\nSEE NOTE 4\n") == []
    assert takeoff.find_scales("1/4\"\n=\n\n1'-0\"") == []


def test_walls_come_from_the_floor_plan_not_the_site_or_demo_plan():
    """Read the titles, and the walls engine takes the floor plan for
    the level, not the site plan or the demolition plan (both used to
    win because every title was empty)."""
    doc = fitz.open()
    _sideways_sheet(doc, "A002", "SITE PLAN", ["SCALE: 1\" = 10'"])
    _sideways_sheet(doc, "AD101", "MAIN LEVEL DEMOLITION PLAN",
                    ["SCALE: 1/4\"", "=", "1'-0\""])
    _sideways_sheet(doc, "A101", "MAIN LEVEL FLOOR PLAN",
                    ["SCALE: 1/4\"", "=", "1'-0\""])
    rows = ait.plan_set(doc)
    titles = {r["number"]: r["title"] for r in rows}
    assert titles["A101"] == "MAIN LEVEL FLOOR PLAN"
    assert all(r["scale"] for r in rows)
    keep, _skipped = ait.walls_pages(rows)
    assert keep == [2]


def _row(page, number, title):
    return {"page": page, "number": number, "title": title,
            "engines": ["rooms"], "scale": ("1/4\"", 18.0, "ft"),
            "kind": "plan"}


def test_a_demolition_plan_never_beats_the_floor_plan():
    rows = [_row(1, "AD-101.5", "THIRD LEVEL FLOOR PLAN AND RCP DEMOLITION"),
            _row(2, "A-101.5", "THIRD LEVEL FLOOR PLAN AND RCP")]
    assert ait.plan_rank(rows[0]) > ait.plan_rank(rows[1])
    keep, skipped = ait.walls_pages(rows)
    assert keep == [2]


def test_untitled_level_plans_join_the_one_named_level():
    """One building level: an ADA clearance plan and an enlarged plan
    (no level in their titles) are the same floor as MAIN LEVEL PLAN,
    so its walls are taken once, from the main plan."""
    rows = [_row(4, "A101", "MAIN LEVEL PLAN"),
            _row(5, "A102", "ENLARGED FLOOR PLAN & ADA"),
            _row(6, "A103", "ADA CLEARANCE PLAN")]
    keep, _skipped = ait.walls_pages(rows)
    assert keep == [4]
    # and with titles that don't say ADA / ENLARGED, the fold still works
    rows = [_row(4, "A101", "MAIN LEVEL PLAN"),
            _row(6, "A103", "CODE PLAN")]
    keep, skipped = ait.walls_pages(rows)
    assert keep == [4] and skipped == [(6, 4)]


def test_two_named_levels_stay_apart():
    rows = [_row(1, "A101", "FIRST FLOOR PLAN"),
            _row(2, "A102", "SECOND FLOOR PLAN"),
            _row(3, "A103", "ENLARGED TOILET PLAN")]
    keep, _ = ait.walls_pages(rows)
    assert 1 in keep and 2 in keep and 3 not in keep


def test_tags_on_a_plan_with_no_level_join_the_one_named_level():
    """Found on HMB once titles were read: A101 MAIN LEVEL PLAN and A102
    ENLARGED FLOOR PLAN & ADA show the same windows; A102 names no level,
    so its tags were counted as another floor (windows 6 -> 9)."""
    from app import schedules
    assert schedules.fold_levels(["1", "", "1", ""]) == ["1", "1", "1", "1"]
    # two named levels: a plan with no level can't be placed - left alone
    assert schedules.fold_levels(["1", "2", ""]) == ["1", "2", ""]
    assert schedules.fold_levels(["", ""]) == ["", ""]
    # the real HMB set also has A105 ROOF PLAN: a roof isn't a floor, so
    # it neither blocks the fold nor takes the unnamed plans
    assert schedules.fold_levels(["1", "", "", "ROOF"]) == \
        ["1", "1", "1", "ROOF"]
    assert schedules.fold_levels(["", "ROOF"]) == ["", "ROOF"]


def test_a_room_tagged_with_its_number_and_a_shorter_name_on_another_plan_is_one_room():
    """Found on HMB once titles were read: A101 tags 'MEN'S PUBLIC TOILET
    ROOM 111', the ADA plan A103 tags 'MEN'S PUBLIC RESTROOM 111' - one
    room taken off twice (rooms 12 -> 14)."""
    from app import aitakeoff as ait
    a = {"name": "MEN'S PUBLIC TOILET ROOM 111", "sqft": 185.8}
    b = {"name": "MEN'S PUBLIC RESTROOM 111", "sqft": 143.6}
    assert ait._same_tag(a, b)
    rows = {4: {"title": "MAIN LEVEL PLAN"},
            6: {"title": "ADA CLEARANCE PLAN"}}
    kept, dups = ait.dedupe_rooms({4: [a], 6: [b]}, rows)
    assert kept == {4: [a], 6: []} and dups
    # the same number with nothing in common in the names stays two
    assert not ait._same_tag({"name": "OFFICE 101"},
                             {"name": "STORAGE 101"})
