"""0.13.6 review G4-G6 (G1-G3 are in test_brand_rename.py): the Trade
Takeoff roof pitch cap, Count by Label once per instance on the plan, and
civil size-first split labels. Made-up drawings only."""
import pytest


# ---- G4: Trade Takeoff > Roof Areas is capped at 12:12 --------------------

def test_pitch_value_caps_at_12_12():
    pytest.importorskip("fitz")
    from app import tradetakeoff as tt
    from app.calculators import MAX_PITCH
    assert MAX_PITCH == 12
    assert tt.pitch_value("6:12") == 6
    assert tt.pitch_value("12:12") == 12
    assert tt.pitch_value("18/12") is None
    assert tt.pitch_value("24:12") is None
    assert tt.pitch_value("14:12") is None
    assert tt.pitch_value('1/4" PER FT') == 0.25


def test_steep_pitch_labels_are_flagged_and_never_used():
    fitz = pytest.importorskip("fitz")
    from app import tradetakeoff as tt
    doc = fitz.open()
    pg = doc.new_page(width=792, height=612)
    pg.insert_text((100, 100), "6:12", fontsize=10)
    pg.insert_text((300, 100), "18:12", fontsize=10)
    used = [v for v, _c in tt.pitch_labels(pg)]
    assert used == [6]
    steep = tt.steep_pitch_labels(pg)
    assert [v for _t, v in steep] == [18]
    for v in used:
        assert v <= 12


def test_roof_areas_default_pitch_spin_is_0_to_12():
    pytest.importorskip("PySide6")
    pytest.importorskip("fitz")
    import ast
    import os
    src = open(os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "app", "tradetakeoff_ui.py"),
        encoding="utf-8").read()
    assert "self.default.setRange(0, 24)" not in src
    assert "self.default.setRange(0, MAX_PITCH)" in src
    ast.parse(src)


# ---- G5: Count by Label counts each instance once, on the plan ------------

def _sheet(fitz):
    """A made-up plan sheet: one tag "EF-1" in the floor plan, the same
    tag in an enlarged plan of the same room, in a notes block and in the
    title block."""
    doc = fitz.open()
    pg = doc.new_page(width=1728, height=1152)
    # main plan view and its title
    pg.insert_text((300, 400), "EF-1", fontsize=8)
    pg.insert_text((200, 700), "FIRST FLOOR PLAN", fontsize=12)
    pg.insert_text((200, 716), "SCALE: 1/8\" = 1'-0\"", fontsize=8)
    # enlarged plan of the same room, with the tag again
    pg.insert_text((900, 400), "EF-1", fontsize=8)
    pg.insert_text((850, 700), "ENLARGED TOILET PLAN", fontsize=12)
    pg.insert_text((850, 716), "SCALE: 1/4\" = 1'-0\"", fontsize=8)
    # a notes block naming it
    pg.insert_text((900, 850), "GENERAL NOTES", fontsize=10)
    pg.insert_text((900, 864), "1. EF-1 TO BE INTERLOCKED WITH LIGHTS.",
                   fontsize=8)
    pg.insert_text((900, 876), "2. COORDINATE WITH THE EXAMPLE OWNER.",
                   fontsize=8)
    # title block (right-hand strip)
    pg.draw_line((1450, 20), (1450, 1132))
    pg.insert_text((1480, 900), "EF-1", fontsize=8)
    return doc


def test_count_by_label_is_one_per_instance_on_the_plan():
    fitz = pytest.importorskip("fitz")
    from app import autocount
    doc = _sheet(fitz)
    info = {}
    hits = autocount.find_by_label(doc, "EF-1", use_ocr=False, info=info)
    assert len(hits) == 1
    r = fitz.Rect(hits[0]["rect"])
    assert r.x0 < 400                                  # the floor plan one
    assert info["left_out"] == 3
    every = autocount.find_by_label(doc, "EF-1", use_ocr=False,
                                    plan_area_only=False)
    assert len(every) == 4


def test_count_by_label_on_a_sheet_without_views_counts_each_once():
    fitz = pytest.importorskip("fitz")
    from app import autocount
    doc = fitz.open()
    pg = doc.new_page(width=1728, height=1152)
    for x in (200, 500, 800):
        pg.insert_text((x, 400), "D1", fontsize=8)
        pg.insert_text((x, 400), "D1", fontsize=8)    # drawn twice on top
    hits = autocount.find_by_label(doc, "D1", use_ocr=False)
    assert len(hits) == 3


# ---- G6: civil size-first split labels ------------------------------------

def test_size_first_split_label_with_the_material_below():
    fitz = pytest.importorskip("fitz")
    from app import civiltakeoff as ct
    doc = fitz.open()
    pg = doc.new_page(width=1728, height=1152)
    pg.insert_text((400, 400), '6" - 75 LF', fontsize=6)
    pg.insert_text((404, 408), "PVC", fontsize=6)
    labels = ct.pipe_labels(pg)
    assert len(labels) == 1, labels
    p = labels[0]
    assert p["name"] == '6" PVC sanitary' and p["length"] == 75


def test_length_first_split_label_still_reads():
    fitz = pytest.importorskip("fitz")
    from app import civiltakeoff as ct
    doc = fitz.open()
    pg = doc.new_page(width=1728, height=1152)
    pg.insert_text((400, 400), '110 LF-4"', fontsize=6)
    pg.insert_text((404, 408), "SDR-35 PVC", fontsize=6)
    labels = ct.pipe_labels(pg)
    assert [(p["size"], p["length"]) for p in labels] == [(4.0, 110.0)]


def test_size_first_text_alone_is_not_a_pipe():
    from app import civiltakeoff as ct
    assert ct._join_two('6" - 75 LF', "GENERAL NOTES") is None
    assert ct._length_first('6" - 75 LF') == '75 LF-6"'
    assert ct._length_first("PVC") == "PVC"


# ---- Aiken #4: a legend's symbols count on its own discipline only --------

def test_legend_symbols_count_on_their_own_discipline():
    pytest.importorskip("fitz")
    from app import tradetakeoff as tt
    disc = {0: "general", 1: "plumbing", 2: "mechanical", 3: "electrical",
            4: "electrical"}
    pages = [1, 2, 3, 4]
    assert tt._pages_for_legend(3, pages, disc) == [3, 4]     # E legend
    assert tt._pages_for_legend(0, pages, disc) == pages      # G legend
    assert tt._pages_for_legend(1, pages, disc) == [1]
    assert tt._pages_for_legend(3, pages, None) == pages


# ---- Aiken: a door schedule whose title and group row sit to the right ---

def test_door_schedule_with_a_narrow_group_row_reads_its_key_column():
    """The DOOR SCHEDULE title is at the table's right end and the first
    header line is a group row ('DOOR', 'GLAZING') that doesn't reach the
    NUMBER column at the left: the header is still read in full and every
    door row is read (Aiken A-801)."""
    fitz = pytest.importorskip("fitz")
    from app import schedules
    doc = fitz.open()
    pg = doc.new_page(width=1728, height=1152)
    x = {"NUMBER": 400, "WIDTH": 470, "HEIGHT": 540, "MATERIAL": 610,
         "TYPE": 690, "THICKNESS": 750, "HARDWARE": 830}
    pg.insert_text((720, 60), "DOOR SCHEDULE", fontsize=18)
    pg.insert_text((560, 90), "DOOR", fontsize=6)
    pg.insert_text((700, 90), "GLAZING", fontsize=6)
    for name, xx in x.items():
        pg.insert_text((xx, 100), name, fontsize=6)
    for i in range(6):
        y = 112 + 10 * i
        vals = [f"10{i + 1}A", "3'-0\"", "7'-0\"", "HM", "TMPD", "1/4\"",
                f"Set {i + 1}.0"]
        for (name, xx), v in zip(x.items(), vals):
            pg.insert_text((xx, y), v, fontsize=6)
    ts = [t for t in schedules.read_page(pg, "architectural")
          if t["kind"] == "door"]
    assert ts, "door schedule not found"
    t = ts[0]
    assert t["key"] == "NUMBER", t["columns"]
    assert [r["NUMBER"] for r in t["rows"]] == [f"10{i + 1}A"
                                                for i in range(6)]


# ---- Aiken: '1' and '1/2"V' printed as two pieces are 1-1/2" V ------------

def test_whole_number_printed_apart_joins_the_fraction():
    fitz = pytest.importorskip("fitz")
    from app import tradetakeoff as tt
    doc = fitz.open()
    pg = doc.new_page(width=1728, height=1152)
    # two text pieces: the whole number in its own block, close beside it
    pg.insert_text((400, 400), "1", fontsize=8)
    pg.insert_text((406, 400), '1/2"V', fontsize=8)
    # a lone 1/2" CW with nothing before it stays 1/2"
    pg.insert_text((800, 400), '1/2" CW', fontsize=8)
    names = sorted(t["name"] for t in tt.labels(pg) if t["kind"] == "pipe")
    assert names == ['1-1/2" V', '1/2" CW'], names


def test_a_whole_number_of_a_neighbouring_tag_is_not_taken():
    """Tags set in a row up the sheet: the "1" of one tag ('1' + '1/2"CW')
    is not joined to the '3/4"HWR' in the next column."""
    fitz = pytest.importorskip("fitz")
    from app import tradetakeoff as tt
    doc = fitz.open()
    pg = doc.new_page(width=1728, height=1152)
    # text turned to run up the sheet, one tag per column
    pg.insert_text((560, 503), '3/4"HWR', fontsize=8, rotate=90)
    pg.insert_text((580, 503), "1", fontsize=8, rotate=90)
    pg.insert_text((580, 496), '1/2"CW', fontsize=8, rotate=90)
    names = sorted(t["name"] for t in tt.labels(pg) if t["kind"] == "pipe")
    assert names == ['1-1/2" CW', '3/4" HWR'], names
