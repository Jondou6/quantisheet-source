"""Accuracy phase 2: spec sections, RFI rule false positives, submittals in
other article formats. Made-up text that reproduces each pattern found on
the Aiken and Colleton project manuals (no real document is used)."""
from app import specs
from app.ai import rfi_finder, rfi_rules
from app.pm import submittals

HEAD = ["MADE-UP ANIMAL CLINIC", "SOMEWHERE, SC", "9999.0001"]


def _pages(*texts):
    """[[line, ...] per page] -> [[(y fraction, line)]] top to bottom."""
    return [[(0.04 + 0.03 * k, t) for k, t in enumerate(lines)]
            for lines in texts]             # ~ 12 pt lines on a Letter page


def _secs(*texts):
    return [(s["number"], s["title"], s["start"], s["end"])
            for s in specs.sections_in(_pages(*texts))]


# ---- 1. find_sections -------------------------------------------------------------

def test_quoted_cross_reference_is_not_a_section():
    # Aiken p544: 'Section 033000 "Cast-in-Place Concrete."' near the top
    # of an HVAC page was listed as a second 03 30 00
    got = _secs(
        HEAD + ["SECTION 033000 - CAST-IN-PLACE CONCRETE", "PART 1 - GENERAL",
                "1.1", "SUMMARY"],
        HEAD + ["PART 2 - PRODUCTS", "END OF SECTION 033000"],
        HEAD + ["SECTION 238129 - VARIABLE-REFRIGERANT-FLOW HVAC SYSTEMS",
                "PART 1 - GENERAL"],
        HEAD + ["3.", "Pad-Mounted Installations: Install outdoor units on",
                "bases. Comply with requirements specified in",
                'Section 033000 "Cast-in-Place Concrete."', "a.", "b."],
        HEAD + ["END OF SECTION 238129"])
    assert got == [
        ("03 30 00", "Cast-In-Place Concrete", 0, 1),
        ("23 81 29", "Variable-Refrigerant-Flow Hvac Systems", 2, 4)]


def test_site_clearing_quote_and_the_real_earth_moving_heading():
    # Colleton C10: a quoted '31 20 00 "Earth Moving."' inside Site
    # Clearing made a fake section, cut Site Clearing to one page, and
    # the real SECTION 312000 was then skipped as a "repeat"
    got = _secs(
        HEAD + ["END OF SECTION 310000"],
        HEAD + ["SECTION 311000 - SITE CLEARING", "PART 1 - GENERAL",
                "1.2", "RELATED REQUIREMENTS"],
        HEAD + ["A.", 'Section 31 20 00 "Earth Moving." for topsoil',
                "stripping.", "PART 2 - PRODUCTS"],
        HEAD + ["PART 3 - EXECUTION", "END OF SECTION 311000"],
        HEAD + ["SECTION 312000 - EARTH MOVING", "PART 1 - GENERAL"],
        HEAD + ["END OF SECTION 312000"])
    assert ("31 10 00", "Site Clearing", 1, 3) in got
    assert ("31 20 00", "Earth Moving", 4, 5) in got
    assert [g[0] for g in got].count("31 20 00") == 1


def test_running_header_and_duplicates_listed_once():
    got = _secs(
        ["SECTION 03 30 00 - CAST-IN-PLACE CONCRETE", "PART 1 - GENERAL"],
        ["SECTION 03 30 00 - CAST-IN-PLACE CONCRETE", "PART 2 - PRODUCTS",
         "END OF SECTION 03 30 00"],
        ["SECTION 23 33 00 - AIR DUCT ACCESSORIES", "PART 1 - GENERAL",
         "END OF SECTION"],
        ["SECTION 26 05 53 - IDENTIFICATION FOR ELECTRICAL SYSTEMS",
         "PART 1 - GENERAL", "END OF SECTION"],
        ["SECTION 23 33 00 - AIR DUCT ACCESSORIES"],      # a stray copy
        ["SECTION 26 05 53 - IDENTIFICATION FOR ELECTRICAL SYSTEMS"])
    nums = [g[0] for g in got]
    assert nums == ["03 30 00", "23 33 00", "26 05 53"]
    assert got[0][2:] == (0, 1)


def test_division_00_and_01_formats():
    got = _secs(
        ["DOCUMENT 00 11 13 - INVITATION TO BID", "1.1 PROJECT"],
        ["END OF DOCUMENT 00 11 13"],
        ["DOCUMENT 002113", "INSTRUCTIONS TO BIDDERS", "1.1 DEFINITIONS"],
        ["00 41 13 - BID FORM", "BIDDER:"],
        ["SECTION", "01 10 00", "SUMMARY", "PART 1 - GENERAL"],
        ["SECTION 01 25 00 - SUBSTITUTION PROCEDURES", "PART 1 - GENERAL",
         "END OF SECTION 01 25 00",
         "SECTION 01 26 00 - CONTRACT MODIFICATION PROCEDURES",
         "PART 1 - GENERAL"],
        ["SECTION 01300 - SUBMITTALS", "PART 1 - GENERAL"])
    by = {g[0]: g for g in got}
    assert by["00 11 13"] == ("00 11 13", "Invitation To Bid", 0, 1)
    assert by["00 21 13"][1] == "Instructions To Bidders"
    assert by["00 41 13"][1] == "Bid Form"
    assert by["01 10 00"][1:] == ("Summary", 4, 4)
    assert by["01 25 00"][2:] == (5, 5)
    # a new section right after END OF SECTION on the same page
    assert by["01 26 00"][2:] == (5, 5)
    assert by["01 30 00"][1] == "Submittals"


def test_related_sections_in_capitals_start_nothing():
    got = _secs(
        ["SECTION 31 10 00 - SITE CLEARING", "PART 1 - GENERAL",
         "1.2 RELATED REQUIREMENTS", "SECTION 31 20 00 - EARTH MOVING",
         "SECTION 32 92 00 - TURF AND GRASSES"],
        ["PART 3 - EXECUTION", "END OF SECTION 31 10 00"])
    assert got == [("31 10 00", "Site Clearing", 0, 1)]


def test_table_of_contents_page_starts_nothing():
    got = _secs(
        ["TABLE OF CONTENTS", "SECTION 03 30 00 - CAST-IN-PLACE CONCRETE",
         "SECTION 04 20 00 - UNIT MASONRY", "SECTION 05 12 00 - STRUCTURAL "
         "STEEL FRAMING", "SECTION 09 91 23 - INTERIOR PAINTING"],
        ["SECTION 03 30 00 - CAST-IN-PLACE CONCRETE", "PART 1 - GENERAL"])
    assert got == [("03 30 00", "Cast-In-Place Concrete", 1, 1)]


def test_headless_section_recovered_from_its_end_marker():
    # Aiken pp146-150: Rough Carpentry's heading isn't in the text layer,
    # its footer and END OF SECTION are; it was folded into 05 50 00
    got = _secs(
        ["SECTION 055000 - METAL FABRICATIONS", "PART 1 - GENERAL",
         "END OF SECTION 055000", "METAL FABRICATIONS", "055000 - 1"],
        ["PART 1 - GENERAL", "1.1", "SUMMARY", "ROUGH CARPENTRY",
         "061000 - 1"],
        ["PART 3 - EXECUTION", "END OF SECTION 061000", "ROUGH CARPENTRY",
         "061000 - 2"],
        ["SECTION 064116 - PLASTIC-LAMINATE-CLAD ARCHITECTURAL CABINETS"])
    assert got[:2] == [("05 50 00", "Metal Fabrications", 0, 0),
                       ("06 10 00", "Rough Carpentry", 1, 2)]
    assert got[2][0] == "06 41 16"


def test_heading_rules():
    h = specs.heading
    assert h("SECTION 033000 - CAST-IN-PLACE CONCRETE") == \
        ("03 30 00", "CAST-IN-PLACE CONCRETE")
    assert h("SECTION 074113.16 - STANDING-SEAM METAL ROOF PANELS")[0] == \
        "07 41 13.16"
    assert h("Section 26 05 19 - Low-Voltage Conductors")[0] == "26 05 19"
    assert h("SECTION 09 91 23", ["INTERIOR PAINTING"]) == \
        ("09 91 23", "INTERIOR PAINTING")
    for cross in ('Section 031000 "Concrete Forming and Accessories" for',
                  'SECTION 312000 "EARTH MOVING"',
                  "Section 079200 - Joint Sealants: Perimeter sealants.",
                  "Section 033000 for concrete.",
                  "Section 4 - Concrete Mixtures"):
        assert h(cross) is None, cross


def test_no_end_markers_still_runs_to_the_next_section():
    got = _secs(["COVER"], ["SECTION 03 30 00", "CAST-IN-PLACE CONCRETE"],
                ["PART 2 - PRODUCTS"], ["SECTION 09 91 23 - INTERIOR "
                                        "PAINTING"], ["PART 3"])
    assert got == [("03 30 00", "Cast-In-Place Concrete", 1, 2),
                   ("09 91 23", "Interior Painting", 3, 4)]


# ---- 2. RFI rules / finder false positives ----------------------------------------

def _set(*sheets):
    return [(i, num, title, "\n".join(lines))
            for i, (num, title, lines) in enumerate(sheets)]


PLUMBING = _set(
    ("P-001", "PLUMBING LEGEND", ["SYMBOLS"]),
    ("P-101", "PLUMBING PLAN", ["SEE P-201 FOR RISERS", "REFER TO P-401",
                                "P-001 FOR LEGEND", "PUMP P-3 IN MECH ROOM",
                                "SEE 2/P-201"]),
    ("P-201", "PLUMBING RISERS", ["P-101"]),
    ("P-401", "PLUMBING SCHEDULES", ["PUMP SCHEDULE", "P-1 CIRC PUMP",
                                     "P-2 CIRC PUMP", "P-4 SUMP PUMP"]))


def test_sheet_numbers_are_not_unscheduled_equipment():
    found = rfi_rules.find(PLUMBING)
    tags = {f["subject"] for f in found if f["kind"] == "unscheduled_equip"}
    assert tags == {"P-3"}                      # the real one stays
    q = " ".join(f["question"] for f in rfi_finder.checks(PLUMBING))
    assert "P-001" not in q and "P-101" not in q and "P-201 " not in q


NOISE = _set(
    ("C-507", "SITE DETAILS", ["STA 14 13 12 TO 11 17 16",
                               "GRID 20 19 18", "33 43 54 TYP",
                               "10 10 11 12 13", "12 12 12", "13 14 15",
                               "19 19 19", "47 17 18",
                               "PIPE BEDDING PER SECTION 33 05 13."]),
    ("S-002", "GENERAL NOTES", ["FRAMING PER SPEC SECTION 05 40 00",
                                "SEE SPECIFICATIONS 09 91 99",
                                "DOORS PER SECTION 08 71 00"]))
SPECS = _set(("", "", ["SECTION 33 31 00 - SANITARY SEWERAGE PIPING"]),
             ("", "", ["SECTION 05 12 00 - STRUCTURAL STEEL FRAMING"]),
             ("", "", ["SECTION 09 91 23 - INTERIOR PAINTING"]))


def test_number_fragments_are_not_spec_sections():
    found = rfi_rules.find(NOISE, SPECS)
    got = {f["subject"] for f in found if f["kind"] == "missing_spec"}
    # real citations of divisions the manual has
    assert got == {"33 05 13", "05 40 00", "09 91 99"}, got
    near = [f for f in found if f["subject"] == "09 91 99"][0]
    assert "09 91 23" in near["question"]          # the nearest section
    q = " ".join(f["question"] for f in rfi_finder.checks(NOISE, SPECS))
    for noise in ("14 13 12", "11 17 16", "20 19 18", "33 43 54",
                  "10 10 11", "10 11 12", "12 12 12", "13 14 15", "19 19 19",
                  "47 17 18", "08 71 00"):   # 08: no Division 08 in book
        assert noise not in q, noise
    assert "33 05 13" in q and "05 40 00" in q


def test_spec_ref_rules():
    import re
    ok = rfi_rules.spec_ref_ok
    have = {"033000", "087100"}
    for text, want in (("PER SECTION 03 31 00", True),
                       ("SEE SPEC 08 71 13 FOR HARDWARE", True),
                       ("03 31 00 PER SPECIFICATIONS", True),
                       ("03 31 00 TYP", False),        # no context word
                       ("SECTION 12 12 12", False),    # a run
                       ("SECTION 47 17 18", False),    # no Division 47
                       ("SECTION 26 05 19", False)):   # no Div 26 in book
        m = re.search(r"(\d{2})\s(\d{2})\s(\d{2})", text)
        assert ok(text, m, have) is want, text


def test_paint_codes_are_not_missing_sheets():
    plans = _set(("A-101", "FLOOR PLAN", ["WALLS 1/PT-2", "SEE SHEET PT-4",
                                          "SEE 4/A-501 FOR HEAD"]),
                 ("A-601", "FINISH SCHEDULE", ["PT-1 EGGSHELL",
                                               "PT-2 SEMI-GLOSS",
                                               "PT-3 EPOXY"]))
    found = rfi_rules.find(plans)
    miss = {f["subject"] for f in found if f["kind"] == "missing_sheet"}
    assert miss == {"A-501"}
    assert not [f for f in found if f["subject"].startswith("PT-")]
    q = " ".join(f["question"] for f in rfi_finder.checks(plans))
    assert "A-501" in q and "sheet PT-2" not in q


def test_ada_figures_and_r_values_are_not_equipment():
    plans = _set(
        ("G-002", "CODE / ADA REQUIREMENTS", ["FIG R-5", "R-7 REACH RANGE",
                                              "R-10", "R-13", "B-0", "B-054"]),
        ("A-201", "WALL SECTIONS", ["R-19 BATT", "R-38 ATTIC", "R-13 WALL"]),
        ("A-601", "ROOM FINISH SCHEDULE", ["R-1 LOBBY", "R-2 EXAM",
                                           "R-3 SURGERY", "B-1", "B-2",
                                           "B-3"]))
    found = rfi_rules.find(plans)
    assert not [f for f in found if f["kind"] == "unscheduled_equip"], found
    assert not [f for f in rfi_finder.checks(plans)
                if f["reference"] == "Page 1" or "R-" in f["question"]]
    # an equipment schedule that lists R-# registers makes them tags
    plans = _set(
        ("M-101", "MECHANICAL PLAN", ["R-4 RETURN GRILLE"]),
        ("M-601", "MECHANICAL SCHEDULES", ["REGISTER SCHEDULE",
                                           "R-1 12X12", "R-2 24X24",
                                           "R-3 10X10"]))
    tags = {f["subject"] for f in rfi_rules.find(plans)
            if f["kind"] == "unscheduled_equip"}
    assert tags == {"R-4"}


def test_pages_are_reported_one_based():
    plans = [(i, f"A-{900 + i}", "", "") for i in range(46)]
    plans.append((46, "A-901", "DETAILS", "SEE 3/A-999\nWORK BY OTHERS"))
    found = rfi_rules.find(plans)
    assert found and all(f["page"] == 46 and f["page_no"] == 47
                         for f in found)
    assert all(c["page_no"] == 47 for f in found for c in f["cites"])
    found = rfi_finder.checks(plans)
    assert found and all(f["page_no"] == f["page"] + 1 == 47 for f in found)


# ---- 3. submittals in other article formats ----------------------------------------

OLD_STYLE = """SECTION 03 30 00
Cast-in-Place Concrete
PART 1  GENERAL
1.01 SECTION INCLUDES
A. Concrete for footings.
1.04 SUBMITTALS
A. Submit under provisions of Section 01 33 00.
B. Product Data: Provide data on admixtures and curing compounds.
C. Shop Drawings: Indicate reinforcing layout.
D. Samples: Submit two samples of the finish.
1.05 QUALITY ASSURANCE
A. Perform work in accordance with ACI 301.
PART 2  PRODUCTS
2.01 MATERIALS
A. Cement: ASTM C150.
END OF SECTION
"""
NUMBERED = """Section 09 29 00 - Gypsum Board
PART ONE - GENERAL
1.3
SUBMITTALS
1. Product Data: For each type of board.
2. Shop Drawings: Show control joints.
3. Samples: Of each texture.
PART TWO - PRODUCTS
END OF SECTION 09 29 00
"""
UNDER_INTRO = """SECTION 087100 - DOOR HARDWARE
PART 1 - GENERAL
1.4 ACTION SUBMITTALS
A. Submit the following in accordance with Section 01 33 00:
1. Product Data: Manufacturer's catalog cuts.
2. Shop Drawings: Hardware schedule.
3. Samples: Lever in each finish.
B. Keying Schedule: Prepared with the Owner.
PART 2 - PRODUCTS
END OF SECTION 087100
"""
NO_PARTS = """SECTION 07 92 00 - JOINT SEALANTS
1.1 SUMMARY
A. Sealants at exterior joints.
1.2 SUBMITTALS
A. Product Data: For each sealant.
B. Samples: For each color.
2.1 MATERIALS
A. Silicone: ASTM C920.
"""


def _got(*pages):
    return {(p["spec"], p["title"], p["type"])
            for p in submittals.from_spec_text(list(pages))}


def test_old_style_1_04_submittals_and_part_1_general():
    got = _got(OLD_STYLE)
    assert got == {
        ("03 30 00", "Cast-In-Place Concrete - Product Data", "Product Data"),
        ("03 30 00", "Cast-In-Place Concrete - Shop Drawings",
         "Shop Drawings"),
        ("03 30 00", "Cast-In-Place Concrete - Samples", "Samples")}, got


def test_numbered_paragraphs_title_case_heading_and_part_one():
    got = _got(NUMBERED)
    assert {g[2] for g in got} == {"Product Data", "Shop Drawings",
                                   "Samples"}
    assert all(g[0] == "09 29 00" and g[1].startswith("Gypsum Board - ")
               for g in got)


def test_numbered_list_under_a_procedural_paragraph():
    got = {g[1] for g in _got(UNDER_INTRO)}
    assert got == {"Door Hardware - Product Data",
                   "Door Hardware - Shop Drawings", "Door Hardware - Samples",
                   "Door Hardware - Keying Schedule"}, got


def test_book_without_part_headings():
    got = {g[1] for g in _got(NO_PARTS)}
    assert got == {"Joint Sealants - Product Data", "Joint Sealants - Samples"}


def test_cross_reference_mid_page_does_not_switch_sections():
    page = "\n".join(HEAD + [
        "SECTION 08 11 13 - HOLLOW METAL DOORS AND FRAMES",
        "PART 1 - GENERAL", "1.1 SUMMARY", "A. Related requirements:",
        "1. Hardware is specified in", "Section 08 71 00 - Door Hardware",
        "1.3 SUBMITTALS", "A. Product Data: For each type of door.",
        "PART 2 - PRODUCTS", "END OF SECTION"])
    props = submittals.from_spec_text([page])
    assert [(p["spec"], p["title"]) for p in props] == [
        ("08 11 13", "Hollow Metal Doors And Frames - Product Data")]


def test_related_section_in_capitals_mid_page_is_not_a_heading():
    page = "\n".join([
        "SECTION 311000 - SITE CLEARING", "PART 1 - GENERAL",
        "1.2 RELATED REQUIREMENTS", "A. Related sections:",
        "SECTION 312000 - EARTH MOVING",
        "1.3 SUBMITTALS", "A. Product Data: For each herbicide.",
        "PART 2 - PRODUCTS", "END OF SECTION 311000",
        "SECTION 312000 - EARTH MOVING", "PART 1 - GENERAL",
        "1.3 ACTION SUBMITTALS", "A. Samples: For each fill material.",
        "END OF SECTION 312000"])
    got = {(p["spec"], p["title"]) for p in submittals.from_spec_text([page])}
    assert got == {("31 10 00", "Site Clearing - Product Data"),
                   ("31 20 00", "Earth Moving - Samples")}, got


def test_text_after_end_of_section_is_not_the_last_section():
    pages = [NO_PARTS + "END OF SECTION 07 92 00\n",
             "WATER LINES AND APPURTENANCES\n9.4 SUBMITTALS\n"
             "A. Product Data: For each valve.\n"]
    assert {p["spec"] for p in submittals.from_spec_text(pages)} == \
        {"07 92 00"}


def test_headless_section_gets_its_number_from_the_footer():
    pages = ["SECTION 055000 - METAL FABRICATIONS\nPART 1 - GENERAL\n"
             "1.2 SUBMITTALS\nA. Shop Drawings: Lintels.\n"
             "END OF SECTION 055000\n",
             "PART 1 - GENERAL\n1.3 ACTION SUBMITTALS\n"
             "A. Product Data: For each preservative.\nROUGH CARPENTRY\n"
             "061000 - 1\n"]
    got = {(p["spec"], p["title"]) for p in submittals.from_spec_text(pages)}
    assert got == {("05 50 00", "Metal Fabrications - Shop Drawings"),
                   ("06 10 00", "Rough Carpentry - Product Data")}


def test_a_big_old_style_manual_finds_every_section():
    # Colleton: 0 submittals from 142 sections
    pages = []
    for k in range(40):
        pages.append(OLD_STYLE.replace("03 30 00", f"0{k % 9 + 1} {10 + k} 00"))
    props = submittals.from_spec_text(pages)
    assert len({p["spec"] for p in props}) == 40
    assert len(props) == 120
