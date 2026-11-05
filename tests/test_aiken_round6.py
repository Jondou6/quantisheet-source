"""Accuracy round 6 (Aiken): schedules framed by ruled lines whose first
header line is a group row with wide gaps, sub-column numbers in the
header, and note text that only names a schedule."""
import pytest


def _frame(pg, x0, x1, ys):
    import fitz
    for y in ys:
        pg.draw_line(fitz.Point(x0, y), fitz.Point(x1, y), width=0.5)


def test_air_device_schedule_with_a_wide_group_row_reads_every_mark():
    fitz = pytest.importorskip("fitz")
    from app import schedules
    doc = fitz.open()
    pg = doc.new_page(width=1728, height=1152)
    pg.insert_text((470, 60), "AIR DISTRIBUTION DEVICE SCHEDULE", fontsize=10)
    _frame(pg, 100, 900, [48, 64, 76])
    # group row: labels centred over wide column groups
    for t, x in (("SIZE (INCHES)", 180), ("MOUNTING", 300),
                 ("MATERIAL", 500), ("DEVICE CONNECTION", 610),
                 ("BASIS OF DESIGN", 760)):
        pg.insert_text((x, 72), t, fontsize=5)
    cols = {"MARK": 110, "FACE": 170, "NECK": 220, "CEILING": 280,
            "DUCT": 330, "STEEL": 480, "ALUMINUM": 530, "1": 600,
            "2": 640, "3": 680, "MANUFACTURER": 740, "MODEL": 820,
            "NOTES": 870}
    for t, x in cols.items():
        pg.insert_text((x, 84), t, fontsize=5)
    marks = ["EG-1", "EG-2", "RG-1", "SD-1", "SD-2"]
    for i, m in enumerate(marks):
        y = 96 + 9 * i
        for t, x in zip([m, "24x24", "8\"", "X", "", "X", "", "X", "", "",
                         "TITUS", "TMS", "1,2"], cols.values()):
            if t:
                pg.insert_text((x, y), t, fontsize=5)
    ts = [t for t in schedules.read_page(pg, "mechanical")
          if "AIR" in t["title"]]
    assert ts
    t = ts[0]
    assert t["key"] == "MARK", t["columns"]
    assert [r["MARK"] for r in t["rows"]] == marks
    assert t["confident"], t["why"]


def test_header_with_a_rating_digit_is_still_header():
    fitz = pytest.importorskip("fitz")
    from app import schedules
    doc = fitz.open()
    pg = doc.new_page(width=1728, height=1152)
    pg.insert_text((300, 60), "SPLIT SYSTEM HEAT PUMP SCHEDULE", fontsize=10)
    _frame(pg, 100, 800, [48, 64])
    pg.insert_text((200, 72), "BASIS OF DESIGN", fontsize=5)
    pg.insert_text((620, 72), "ELECTRICAL", fontsize=5)
    cols = {"MARK": 110, "MANUFACTURER": 170, "MODEL": 250,
            "TOTAL (MBH)": 330, "MIN. SEER2": 420, "MCA": 500,
            "VOLTAGE": 600, "NOTES": 720}
    for t, x in cols.items():
        pg.insert_text((x, 82), t, fontsize=5)
    for t, x in zip(["OHP-1", "DAIKIN", "DH5SEA", "45.5", "15.2", "25.5",
                     "208", "1"], cols.values()):
        pg.insert_text((x, 94), t, fontsize=5)
    ts = [t for t in schedules.read_page(pg, "mechanical")
          if "HEAT PUMP" in t["title"]]
    assert ts and ts[0]["rows"], ts and ts[0]["why"]
    assert ts[0]["rows"][0]["MARK"] == "OHP-1"


def test_a_note_naming_a_schedule_is_not_a_title():
    from app import schedules
    c = {"text": "PLUMBING FIXTURE SCHEDULE FOR INDIVIDUAL RUNOUT SIZES.",
         "x0": 0, "x1": 100, "y0": 0, "y1": 5, "h": 5, "cx": 50, "cy": 2.5}
    assert schedules.titles([c], "plumbing") == []


def test_ruled_fixture_schedule_with_tall_rows_reads_every_mark():
    """P-301: each fixture's name and description run over several lines
    above and below its mark; lines without a mark belong to the nearest
    mark, they don't end the table."""
    fitz = pytest.importorskip("fitz")
    from app import schedules
    doc = fitz.open()
    pg = doc.new_page(width=1728, height=1152)
    pg.insert_text((300, 60), "PLUMBING FIXTURE SCHEDULE", fontsize=10)
    xs = [100, 150, 260, 300, 340, 600]
    top, bot = 64, 64 + 18 + 5 * 36
    for x in xs:
        pg.draw_line(fitz.Point(x, top), fitz.Point(x, bot), width=0.5)
    pg.draw_line(fitz.Point(100, top), fitz.Point(600, top), width=0.5)
    pg.draw_line(fitz.Point(100, 48), fitz.Point(600, 48), width=0.5)
    pg.insert_text((110, 76), "MARK", fontsize=5)
    pg.insert_text((160, 76), "FIXTURE", fontsize=5)
    pg.insert_text((265, 80), "CW", fontsize=5)
    pg.insert_text((305, 80), "HW", fontsize=5)
    pg.insert_text((350, 76), "DESCRIPTION", fontsize=5)
    for i in range(5):
        y = 82 + 36 * i
        pg.draw_line(fitz.Point(100, y), fitz.Point(600, y), width=0.5)
        pg.insert_text((350, y + 8), f"EXAMPLE MAKER MODEL {i}00", fontsize=5)
        pg.insert_text((160, y + 14), "WALL-HUNG", fontsize=5)
        pg.insert_text((110, y + 19), f"P-{i + 1}", fontsize=5)
        pg.insert_text((265, y + 19), "1/2\"", fontsize=5)
        pg.insert_text((305, y + 19), "1/2\"", fontsize=5)
        pg.insert_text((160, y + 24), "LAVATORY", fontsize=5)
        pg.insert_text((350, y + 28), "ANGLE STOPS AND SUPPLIES", fontsize=5)
    ts = [t for t in schedules.read_page(pg, "plumbing")
          if t["kind"] == "plumbing fixtures"]
    assert ts and ts[0]["rows"], ts and ts[0]["why"]
    t = ts[0]
    assert [r["MARK"] for r in t["rows"]] == [f"P-{i}" for i in range(1, 6)]
    assert t["rows"][0]["FIXTURE"] == "WALL-HUNG LAVATORY"


def test_a_mark_with_a_size_in_it_is_a_key():
    from app import schedules
    for k in ('3/4"-WH', '1/2"-HB', "PMP-1", "EWH-1"):
        assert schedules._key_ok(k, "plumbing fixtures"), k
    assert not schedules._key_ok("WALL HUNG LAVATORY", "plumbing fixtures")


def test_words_across_a_column_rule_go_to_their_own_columns():
    from app import schedules
    c = {"text": "ACT-1 / PT-4 VARIES", "x0": 100, "x1": 195, "y0": 0,
         "y1": 5, "h": 5, "cx": 147.5, "cy": 2.5,
         "ws": [(100, 127, "ACT-1"), (129, 132, "/"), (134, 154, "PT-4"),
                (165, 195, "VARIES")]}
    parts = schedules._split_cell(c, [90, 160, 220])
    assert [p["text"] for p in parts] == ["ACT-1 / PT-4", "VARIES"]
    assert schedules._split_cell(c, [90, 220]) == [c]


def test_storefront_types_from_elevation_titles():
    from app import schedules

    def cell(t, x):
        return {"text": t, "x0": x, "x1": x + 60, "y0": 10, "y1": 15,
                "cx": x + 30, "cy": 12.5, "h": 5}
    cs = [cell("STOREFRONT A.1", 0), cell("STOREFRONT A.2", 100),
          cell("STOREFRONT B", 200), cell("STOREFRONT HEAD DETAIL", 300),
          cell("STOREFRONT", 400)]
    t = schedules.elevation_types(cs)
    assert t and t["kind"] == "window"
    assert [r["MARK"] for r in t["rows"]] == ["A.1", "A.2", "B"]
    assert schedules.elevation_types(cs[:1] + cs[3:]) is None


def test_rating_totals_are_not_a_quantity_column():
    from app import schedules
    cols = [{"name": "MARK"}, {"name": "TOTAL COOLING (MBH)"},
            {"name": "TOTAL HEATING (MBH)"}]
    assert schedules._pick_col(cols, schedules._QTY_HDR,
                               avoid=schedules._NOT_QTY) is None
    cols.append({"name": "QTY"})
    assert schedules._pick_col(cols, schedules._QTY_HDR,
                               avoid=schedules._NOT_QTY) == "QTY"


def test_floor_drain_schedule_is_a_plumbing_schedule():
    from app import schedules
    assert schedules.kind_of("FLOOR DRAIN & CLEANOUT SCHEDULE",
                             "plumbing") == "plumbing equipment"


def test_a_detail_scale_sheet_is_not_counted_for_tags():
    from app import schedules
    assert schedules._detail_scaled({"page": 3, "scale": ("1-1/2\" = 1'-0\"",
                                                          108.0, "ft")})
    assert not schedules._detail_scaled({"page": 3, "scale": (
        "1/4\" = 1'-0\"", 18.0, "ft")})
    assert not schedules._detail_scaled({"page": 3, "scale": None})


def test_two_ceilings_in_one_room_need_the_rcp():
    from app import aitakeoff as ait
    assert ait._two_materials("ACT-1 / PT-4")
    assert not ait._two_materials("PT-1 / PT-2")
    assert not ait._two_materials("ACT-1")


def test_a_thermostat_label_is_not_the_units_tag():
    from app import schedules

    def cell(t, x, y=100):
        return {"text": t, "x0": x, "x1": x + 6 * len(t), "y0": y - 4,
                "y1": y + 4, "cx": x + 3 * len(t), "cy": y, "h": 8}
    tag, t_sym = cell("AHU-1", 120), cell("T", 105)
    assert schedules._sensor_label(tag, [tag, t_sym])
    alone = cell("AHU-1", 400, 300)
    assert not schedules._sensor_label(alone, [alone, t_sym])


def test_a_schedule_title_beside_the_table_does_not_end_it():
    """P-301: FLOOR DRAIN & CLEANOUT SCHEDULE sits to the right of the
    plumbing fixture schedule's lower rows; the fixture rows under it
    (wall hydrant, hose bibb, pump, water heater) are still read."""
    fitz = pytest.importorskip("fitz")
    from app import schedules
    doc = fitz.open()
    pg = doc.new_page(width=1728, height=1152)
    pg.insert_text((150, 60), "PLUMBING FIXTURE SCHEDULE", fontsize=10)
    pg.insert_text((110, 76), "MARK", fontsize=5)
    pg.insert_text((170, 76), "FIXTURE", fontsize=5)
    pg.insert_text((260, 76), "CW", fontsize=5)
    marks = ["P-1", "P-2", "P-3", "3/4\"-WH", "1/2\"-HB", "PMP-1", "EWH-1"]
    for i, m in enumerate(marks):
        y = 88 + 12 * i
        pg.insert_text((110, y), m, fontsize=5)
        pg.insert_text((170, y), "EXAMPLE FIXTURE", fontsize=5)
        pg.insert_text((260, y), "1/2\"", fontsize=5)
    pg.insert_text((600, 118), "FLOOR DRAIN & CLEANOUT SCHEDULE", fontsize=10)
    pg.insert_text((600, 132), "SYMBOL", fontsize=5)
    pg.insert_text((660, 132), "MODEL", fontsize=5)
    pg.insert_text((600, 144), "FD", fontsize=5)
    pg.insert_text((660, 144), "2010", fontsize=5)
    ts = {t["kind"]: t for t in schedules.read_page(pg, "plumbing")}
    assert [r["MARK"] for r in ts["plumbing fixtures"]["rows"]] == marks


def test_a_sized_floor_drain_tag_counts():
    from app import schedules
    keys = {"FD": "FD", "GCO": "GCO"}
    assert schedules._tag_match('3"-FD', keys, "plumbing equipment") == \
        ("FD", 1)
    assert schedules._tag_match('4"-GCO', keys, "plumbing equipment") == \
        ("GCO", 1)
    assert schedules._tag_match('3"-W', keys, "plumbing equipment") is None


def test_water_service_callouts_with_a_count_are_taken_off():
    fitz = pytest.importorskip("fitz")
    from app import civiltakeoff as ct
    doc = fitz.open()
    pg = doc.new_page(width=1728, height=1152)
    lines = ['1 - 6" x 2" DOUBLE STRAP SADDLE TAP PER EXAMPLE CITY',
             '1 - GATE VALVE AND BOX PER EXAMPLE CITY',
             '1 - 2" METER AND BOX (WITHIN RIGHT-OF-WAY)',
             '1 - 2" RPZ BACKFLOW PREVENTER AND ABOVE GROUND ENCLOSURE',
             '1 - FIRE HYDRANT ASSEMBLY PER EXAMPLE CITY']
    for i, t in enumerate(lines):
        pg.insert_text((200, 300 + 9 * i), t, fontsize=6)
    names = [(it["name"], it["qty"]) for it in ct.service_items(pg)]
    assert names == [('6" x 2" saddle tap', 1), ('2" gate valve', 1),
                     ('2" valve box', 1), ('2" water meter', 1),
                     ('2" meter box', 1), ('2" RPZ backflow preventer', 1)]


def test_a_legend_column_of_sized_tags_is_not_counted():
    from app import schedules

    def cell(t, y):
        return {"text": t, "x0": 2156, "x1": 2190, "y0": y, "y1": y + 10,
                "cx": 2173, "cy": y + 5, "h": 10}
    keys = {"FD": "FD", "GCO": "GCO", "FCO": "FCO"}
    hits = [(k, 1, cell(t, y)) for k, t, y in (
        ("GCO", '4"-GCO', 102), ("FCO", '4"-FCO', 124), ("FD", '3"-FD', 145),
        ("GCO", '3"-GCO', 167))]
    kept, strips = schedules._drop_key_strips(hits, keys)
    assert kept == [] and strips == 1


def test_a_unit_drawn_as_labelled_parts():
    from app import schedules

    def cell(t, x, y):
        return {"text": t, "x0": x, "x1": x + 6 * len(t), "y0": y - 5,
                "y1": y + 5, "cx": x + 3 * len(t), "cy": y, "h": 10}
    tag = cell("DOAS-1", 100, 100)
    assert schedules._part_label(tag, [tag, cell("(ERV)", 104, 112)]) == \
        "ERV"
    assert schedules._part_label(tag, [tag, cell("(ERV)", 600, 112)]) is None


def test_exterior_wall_with_masonry_backup_lists_cmu_for_review():
    from app import wall_assembly as wa
    d = ('CEMENT BOARD SIDING 5/8" GLASSMAT GYP SHEATHING 2" RIGID INSUL '
         'VAPOR BARRIER BRICK VENEER HORIZONTAL REINFORCEMENT 8" 1\'-5 1/8"')
    comps = wa.components(d)
    cmu = [c for c in comps if c["kind"] == "cmu"]
    assert cmu and cmu[0]["inferred"] and cmu[0]["size_in"] == 8
    ls = {ln["name"]: ln for ln in wa.lines("1A", 100.0, 10.0, comps)}
    assert ls['Wall Type 1A - 8" CMU wall'].get("review")
    assert ls["Wall Type 1A - cement board siding"]["qty"] == 1000.0
    assert not ls["Wall Type 1A - cement board siding"].get("review")


def test_deck_type_is_read_from_the_structural_notes():
    from app import aitakeoff as ait
    m = ait._DECK.search("VULCRAFT 1.5B20 METAL DECK OR EQUAL")
    assert m and m.group(1) == "1.5B20"
    assert ait._DECK.search("ELEVATED METAL DECK") is None


def test_slab_on_grade_callout_is_read():
    from app import aitakeoff as ait
    t = '4" SLAB-ON-GRADE w/ 6x6 W2.9x W2.9 WWF T/SLAB 0\'-0"'
    m = ait._SOG.search(t)
    assert m and m.group(1) == "4"
    assert ait._WWF.search(t)


def test_duct_runs_continue_through_fittings_not_across_to_a_neighbour():
    from app import tradetakeoff as tt
    W = 12.0                                  # a 12" round at 12 units/ft
    g = {"w": 12, "h": None, "length": 0.0, "sf": 0.0, "pieces": [
        {"p0": (0, 0), "p1": (100, 0), "length": 100, "width": 12},
        {"p0": (110, 0), "p1": (200, 0), "length": 90, "width": 12},  # damper
        {"p0": (0, 20), "p1": (100, 20), "length": 100, "width": 12},  # beside
        {"p0": (215, 15), "p1": (215, 120), "length": 105, "width": 12}]}
    tt._through_fittings(g, per_ft=12.0, k_ft=1.0)
    fits = [p for p in g["pieces"] if p.get("fitting")]
    lens = sorted(round(p["length"], 1) for p in fits)
    assert lens == [0.8, 1.8]   # ft: the damper gap and the elbow
    assert W


def test_pad_footing_rebar_from_the_schedule():
    from app import structural as st
    r = st.footing_rebar("(5) #5 EW T&B", 4.0, 4.0)
    assert r["bars"] == 20
    assert round(r["lb_each"] * 5, 2) == 365.05     # 5 footings
    assert st.footing_rebar("SEE PLAN", 4.0, 4.0) is None


def test_wall_footing_callouts_are_read():
    from app import aitakeoff as ait
    m = ait._STRIP[0].search('2\'-0" WIDE x 1\'-0" DEEP WALL FOOTING')
    assert m and m.groups() == ("2", "0", "1", "0")
    b = ait._STRIP_BARS.search("(2) #5's CONT (2'-0\" WIDE)")
    assert b and b.group(1) == "2" and b.group(2) == "5"


def test_two_legend_symbols_on_one_spot_keep_the_best_match():
    from app import tradetakeoff as tt
    dup = {"name": "DUPLEX", "hits": [
        {"page": 1, "rect": (100, 100, 110, 110), "score": 0.99},
        {"page": 1, "rect": (300, 100, 310, 110), "score": 0.97}]}
    quad = {"name": "QUAD", "hits": [
        {"page": 1, "rect": (101, 100, 111, 110), "score": 0.83},
        {"page": 1, "rect": (500, 100, 512, 112), "score": 0.95}]}
    tt._compete([dup, quad])
    assert len(dup["hits"]) == 2
    assert [h["rect"] for h in quad["hits"]] == [(500, 100, 512, 112)]


def test_a_device_beside_another_is_not_a_clash():
    from app import tradetakeoff as tt
    rec = {"name": "DUPLEX", "hits": [
        {"page": 1, "rect": (100, 100, 110, 110), "score": 0.99}]}
    data = {"name": "DATA", "hits": [
        {"page": 1, "rect": (109, 100, 119, 110), "score": 0.95}]}
    tt._compete([rec, data])
    assert len(data["hits"]) == 1


def test_a_device_on_two_plans_of_one_floor_counts_once():
    from app import aitakeoff as ait
    rows = {1: {"title": "POWER AND SIGNAL PLAN"},
            2: {"title": "FIRE ALARM PLAN"}}
    hits = [{"page": 1, "rect": (0, 0, 5, 5)},
            {"page": 2, "rect": (0, 0, 5, 5)},
            {"page": 2, "rect": (50, 0, 55, 5)}]
    keep, drop = ait._one_sheet_per_level(hits, rows)
    assert [h["page"] for h in keep] == [2, 2] and drop == {1: 1}


def test_two_areas_of_one_floor_both_count():
    from app import aitakeoff as ait
    rows = {1: {"title": "POWER PLAN"}, 2: {"title": "POWER PLAN"}}
    hits = [{"page": 1, "rect": (0, 0, 5, 5)},
            {"page": 2, "rect": (0, 0, 5, 5)}]
    keep, drop = ait._one_sheet_per_level(hits, rows)
    assert len(keep) == 2 and drop == {}


def test_a_device_elsewhere_on_the_other_plan_still_counts():
    from app import aitakeoff as ait
    rows = {1: {"title": "POWER AND SIGNAL PLAN"},
            2: {"title": "FIRE ALARM PLAN"}}
    hits = [{"page": 1, "rect": (300, 300, 305, 305)},
            {"page": 2, "rect": (0, 0, 5, 5)},
            {"page": 2, "rect": (50, 0, 55, 5)}]
    keep, drop = ait._one_sheet_per_level(hits, rows)
    assert len(keep) == 3 and drop == {}


def test_legend_notes_sizes_and_refs_stay_off_the_review_list():
    from app import aitakeoff as ait
    for t in ["DISTANCE NOTED IS ACTUAL.", '1 1/2"', "4", "(SEE DETAIL )",
              "SEE PLAN", "72-IN. TO 36-IN.",
              "ALL TEMPORARY SEDIMENT BASINS, WHICH ARE NOT TO BE CONVERTED"
              " TO A"]:
        assert ait._legend_note(t), t
    for t in ["SPST TOGGLE SWITCH", "FIRE EXTINGUISHER", "CO",
              "TOP SOILING", '4 7/8" WIDE x 6" DEEP CFS BOX BEAM']:
        assert not ait._legend_note(t), t


def test_a_long_device_name_with_its_qualifier_is_counted():
    from app import tradetakeoff as tt
    assert tt.good_name("WALL MOUNTED DATA OUTLET - STUBBED ABOVE LIFT-OUT "
                        "CEILING")
    assert tt.good_name("DUPLEX CONVENIENCE OUTLET - GROUND FAULT "
                        "INTERRUPTER TYPE")
    assert not tt.good_name("ALL TEMPORARY SEDIMENT BASINS WHICH ARE NOT TO "
                            "BE CONVERTED TO A PERMANENT BASIN SHALL BE "
                            "REMOVED AFTER FINAL SITE STABILIZATION.")


def test_symbols_with_little_ink_in_common_are_not_one_picture():
    cv2 = pytest.importorskip("cv2")
    import numpy as np
    from app import tradetakeoff as tt

    def png(draw):
        im = np.full((60, 60), 255, np.uint8)
        draw(im)
        return cv2.imencode(".png", im)[1].tobytes()
    circ = png(lambda im: cv2.circle(im, (30, 30), 12, 0, 1))
    tri = png(lambda im: cv2.polylines(
        im, [np.array([[18, 40], [42, 40], [30, 18]])], True, 0, 1))
    assert tt._same_picture(circ, [(circ, "C")]) == "C"
    assert tt._same_picture(tri, [(circ, "C")]) is None


def test_a_fire_alarm_device_is_counted_on_the_fire_alarm_plan():
    from app import aitakeoff as ait
    rows = {1: {"title": "POWER AND SIGNAL PLAN"},
            2: {"title": "FIRE ALARM PLAN"}}
    hits = [{"page": 1, "rect": (400, 400, 420, 410)},
            {"page": 2, "rect": (700, 450, 720, 460)}]
    keep, drop = ait._one_sheet_per_level(hits, rows,
                                          "FIRE ALARM CONTROL PANEL")
    assert [h["page"] for h in keep] == [2] and drop == {1: 1}
    keep, drop = ait._one_sheet_per_level(hits, rows, "DATA OUTLET")
    assert [h["page"] for h in keep] == [1] and drop == {2: 1}


def test_a_small_symbol_inside_a_bigger_one_is_part_of_it():
    from app import tradetakeoff as tt
    facp = {"name": "FIRE ALARM CONTROL PANEL", "hits": [
        {"page": 1, "rect": (472, 1158, 501, 1172), "score": 0.88}]}
    pull = {"name": "FIRE ALARM MANUAL PULL STATION", "hits": [
        {"page": 1, "rect": (491, 1158, 500, 1172), "score": 0.89},
        {"page": 1, "rect": (472, 1158, 481, 1172), "score": 0.87},
        {"page": 1, "rect": (900, 900, 909, 914), "score": 0.88}]}
    tt._compete([facp, pull])
    assert len(facp["hits"]) == 1 and len(pull["hits"]) == 1


def test_exterior_cmu_back_up_from_the_sections_and_elevations(monkeypatch):
    from app import aitakeoff as ait, envelope

    class Pg:
        def __init__(self, t):
            self.t = t

        def get_text(self):
            return self.t
    doc = {0: Pg("WALL SECTION 8\" CMU EXT FACE/CMU"), 1: Pg("ELEVATIONS")}
    rows = [{"page": 0, "number": "A-302", "title": "WALL SECTIONS"},
            {"page": 1, "number": "A-401", "title": "EXTERIOR ELEVATIONS"}]
    monkeypatch.setattr(envelope, "wall_heights_from_levels",
                        lambda pages: [10.0 + 2 / 3, 15.0])
    res = {"walls": {5: {"legend": {
        "1A": "CEMENT BOARD SIDING 5/8\" GLASSMAT GYP SHEATHING "
              "HORIZONTAL REINFORCEMENT 8\"",
        "2A": "3 5/8\" MTL. STUDS @ 16\" O.C. 5/8\" TYPE X GYPBOARD"}}},
        "quantities": [], "review": [
            {"engine": "assembly", "name": "Wall Type 1A - 8\" CMU wall",
             "qty": 1007.0}]}
    ait._exterior_cmu(doc, rows, res, 277.7,
                      lambda r: r.get("title") or "")
    names = {x["name"]: x for x in res["review"]}
    assert "Wall Type 1A - 8\" CMU wall" not in names
    cmu = names["Exterior wall - 8\" CMU back-up"]
    assert abs(cmu["qty"] - 277.7 * 15) < 1
    assert "at 10.67 ft" in cmu["why"]
    assert names["Exterior wall - 8\" CMU block"]["qty"] >= 4686


def test_no_exterior_cmu_when_the_sections_dont_name_it(monkeypatch):
    from app import aitakeoff as ait, envelope

    class Pg:
        def get_text(self):
            return "WALL SECTION 2x6 WOOD STUDS"
    rows = [{"page": 0, "number": "A-302", "title": "WALL SECTIONS"}]
    monkeypatch.setattr(envelope, "wall_heights_from_levels",
                        lambda pages: [10.0])
    res = {"walls": {5: {"legend": {
        "1A": "CEMENT BOARD SIDING HORIZONTAL REINFORCEMENT 8\""}}},
        "quantities": [], "review": []}
    ait._exterior_cmu({0: Pg()}, rows, res, 100.0,
                      lambda r: r.get("title") or "")
    assert res["review"] == [] and res["quantities"] == []


def test_fittings_from_the_pipe_layout():
    import math
    from app import fittings
    pf = 18.0
    vent = {"name": '2" V', "runs": [{"pts": [(0, 0), (180, 0), (180, 180)]},
                                     {"pts": [(180, 182), (180, 300)]}]}
    br = {"name": '1-1/2" V', "runs": [{"pts": [(90, 0), (90, -90)]}]}
    main = {"name": '3" W', "runs": [{"pts": [(0, 500), (400, 500)]}]}
    wye = {"name": '2" W', "runs": [{"pts": [(200, 500), (260, 440),
                                               (260, 380)]}]}
    arc = [(620 + 20 * math.cos(math.radians(a)) - 20,
            20 * math.sin(math.radians(a))) for a in range(0, 91, 10)]
    cw = {"name": '1/2" CW', "runs": [{"pts": [(600, -100)] + arc +
                                       [(500, 20)]}]}
    got = dict(fittings.names(fittings.count([vent, br, main, wye, cw], pf)))
    assert got == {'2" 90 elbow - vent': 1, '2" x 1-1/2" tee - vent': 1,
                   '2" 45 elbow - waste': 1, '3" x 2" Y-tee - waste': 1,
                   '1/2" 90 elbow - water': 1}, got


def test_brick_wainscot_cap_and_flashing_from_the_wall_detail():
    from app import aitakeoff as ait
    res = {"walls": {5: {"legend": {
        "1A": "CEMENT BOARD SIDING 5/8\" GLASSMAT GYP SHEATHING PRECAST CONC "
              "SILL W/ DRIP THRU WALL FLASHING BRICK VENEER 3'-4\" "
              "1'-5 1/8\""}}},
        "quantities": [], "review": [], "schedules": None}
    ait._exterior_veneer(res, 277.7)
    q = {x["name"]: x for x in res["quantities"]}
    r = {x["name"]: x for x in res["review"]}
    assert q["Exterior wall - through-wall flashing"]["qty"] == 277.7
    assert abs(r["Exterior wall - brick veneer wainscot"]["qty"] -
               277.7 * (3 + 4 / 12)) < 0.2
    assert "doors unknown" in r["Exterior wall - brick veneer wainscot"]["why"]
    assert "Exterior wall - brick wainscot cap (precast sill / rowlock)" in r


def test_door_swings_and_outlines_are_not_pipe():
    import math
    from app import tradetakeoff as tt
    pf = 18.0
    arc = [(54 * math.cos(math.radians(a)), 54 * math.sin(math.radians(a)))
           for a in range(0, 91, 6)]
    assert tt._not_pipe_shape(arc, pf)
    assert tt._not_pipe_shape([(0, 0), (50, 0), (50, 30), (0, 30), (0, 0)],
                              pf)
    assert not tt._not_pipe_shape([(0, 0), (100, 0), (100, 100), (150, 100)],
                                  pf)


def test_legend_build_up_thickness():
    from app import wall_assembly as wa
    assert wa.thickness_in('3 5/8" MTL. STUDS @ 16" O.C. 5/8" TYPE X '
                           'GYPBOARD, TYP BOTH SIDES') == 4.875
    assert wa.thickness_in('8" CMU VERTICAL REINFORCEMENT 7/8" MTL FURRING '
                           'CHANNEL 5/8" TYPE X GYPBOARD') == 9.125
    assert wa.thickness_in('CEMENT BOARD SIDING 5/8" GLASSMAT GYP '
                           'SHEATHING') is None


def test_cross_check_flags_interior_walls_that_dont_add_up():
    from app import crosscheck
    res = {"walls": {1: {"legend": {
        "1A": "CEMENT BOARD SIDING", "2A": '3 5/8" MTL. STUDS @ 16" O.C.'}}},
        "sheets": {1: {"walls": {"Wall Type 2A": 170.0,
                                 "Wall Type 1A": 90.0,
                                 "Exterior Walls": 278.0}}},
        "finishes": {"rooms": [
            {"base_lf": 400.0, "door_lf": 30.0, "floor_sf": 2000.0,
             "ceiling_sf": 2000.0},
            {"base_lf": 380.0, "door_lf": 20.0, "floor_sf": 1400.0,
             "ceiling_sf": 1400.0}]},
        "quantities": [{"name": "Gross floor area", "qty": 4170.0}],
        "review": [], "problems": []}
    out = {c["name"]: c for c in crosscheck.run(res)}
    w = out["Interior wall length"]
    assert w["b"] == 276.0 and not w["ok"]          # (830 - 278) / 2
    assert out["Room floor area"]["ok"]             # 3400 / 4170 = 82%
    assert out["Ceiling area"]["ok"]
    assert any(r["name"] == "Cross-check: Interior wall length"
               for r in res["review"])


def test_paint_runs_to_the_structure_under_a_sloped_roof(monkeypatch):
    from app import aitakeoff as ait, envelope, settings
    monkeypatch.setattr(envelope, "wall_heights_from_levels",
                        lambda pages: [10.0 + 2 / 3, 15.0])
    monkeypatch.setattr(settings, "get",
                        lambda k, d=None: d)
    res = {"walls": {1: {"legend": {
        "2A": "DEFLECTION TRACK 3 5/8\" MTL. STUDS @ 16\" O.C."}}}}
    rows = [{"page": 0, "title": "EXTERIOR ELEVATIONS"}]
    h, why = ait._paint_height({0: None}, rows, res)
    assert abs(h - (10 + 2 / 3 + 15) / 2) < 1e-6 and "average" in why
    res["walls"][1]["legend"]["2A"] = "3 5/8\" MTL. STUDS @ 16\" O.C."
    assert ait._paint_height({0: None}, rows, res) is None


def test_scale_grade_from_printed_dimensions(monkeypatch):
    from app import scalecheck as sc
    data = [(89.333, 88.433), (4.667, 3.671), (17.333, 16.352), (10, 9.0),
            (20.5, 19.5), (6, 5.0)]
    monkeypatch.setattr(sc, "_words", lambda p: [(0, 0, 1, 1, "x", v)
                                                for v, _ in data])
    monkeypatch.setattr(sc, "_segments", lambda p: [])
    it = iter([m for _, m in data])
    monkeypatch.setattr(sc, "_measure", lambda w, s: next(it) * 18)
    g = sc.grade(None, 18.0)
    assert g["grade"] == "A" and abs(g["ratio"] - 1) < 0.01
    it2 = iter([m * 2 for _, m in data] * 2)
    data2 = data * 2                          # a scale half what it is
    monkeypatch.setattr(sc, "_words", lambda p: [(0, 0, 1, 1, "x", v)
                                                for v, _ in data2])
    monkeypatch.setattr(sc, "_measure", lambda w, s: next(it2) * 18)
    g = sc.grade(None, 18.0)
    assert g["grade"] == "F" and abs(g["ratio"] - 2) < 0.05


def test_duct_fittings_from_the_runs():
    from app import fittings
    pf = 18.0
    main = {"name": '16" round', "pieces": [{"p0": (0, 0), "p1": (300, 0)},
                                           {"p0": (300, 0), "p1": (600, 0)}]}
    big = {"name": '20" round', "pieces": [{"p0": (620, 0), "p1": (900, 0)}]}
    br = {"name": '8" round', "pieces": [{"p0": (150, 10), "p1": (150, 150)},
                                         {"p0": (165, 170), "p1": (300, 170)}]}
    got = dict(fittings.duct_names(fittings.count_ducts(
        [main, big, br], pf, flex=[{"size_in": 8}, {"size_in": 8}])))
    assert got == {'8" round 90 elbow - duct': 1,
                   '8" round to flex connection - duct': 2,
                   '8" round take-off from 16" round - duct': 1,
                   '16" round to 20" round transition - duct': 1}, got


def test_door_and_frame_finishes_from_the_door_schedule():
    from app import aitakeoff as ait
    rows = [{"DOOR NUMBER": "101A", "TYPE": "FG", "WIDTH": "3'-0\"",
             "HEIGHT": "7'-0\"", "FINISH": "FF", "FRAME FINISH": "FF"},
            {"DOOR NUMBER": "103A", "TYPE": "D", "WIDTH": "3'-0\"",
             "HEIGHT": "7'-0\"", "FINISH": "ST-1", "FRAME FINISH": "PT-3"},
            {"DOOR NUMBER": "103B", "TYPE": "D", "WIDTH": "3'-0\"",
             "HEIGHT": "7'-0\"", "FINISH": "ST-1", "FRAME FINISH": "PT-3"},
            {"DOOR NUMBER": "112", "TYPE": "DF", "WIDTH": "6'-0\"",
             "HEIGHT": "7'-0\"", "FINISH": "ST-1", "FRAME FINISH": "PT-3"}]
    res = {"quantities": [], "schedules": {"tables": [
        {"kind": "door", "confident": True, "key": "DOOR NUMBER",
         "rows": rows}]}}
    ait.door_finish_lines(res)
    q = {x["name"]: x["qty"] for x in res["quantities"]}
    assert q["Door finish ST-1: 3'-0\" x 7'-0\" type D"] == 2
    assert q["Door finish ST-1: 6'-0\" x 7'-0\" type DF"] == 1
    assert not any("FF" in n for n in q)
    assert q["Door frame finish PT-3"] == 17 + 17 + 20
    assert q["Door trim finish PT-3 (both faces)"] == 108


def test_exterior_wall_inside_face_furring_and_board(monkeypatch):
    from app import aitakeoff as ait, envelope
    monkeypatch.setattr(envelope, "wall_heights_from_levels",
                        lambda pages: [10.0 + 2 / 3, 15.0])
    res = {"walls": {1: {"legend": {
        "1A": "CEMENT BOARD SIDING 5/8\" GLASSMAT GYP SHEATHING 7/8\" MTL "
              "FURRING",
        "2A": "3 5/8\" MTL. STUDS @ 16\" O.C. 5/8\" TYPE X GYPBOARD, TYP "
              "BOTH SIDES"}}}, "quantities": [
        {"engine": "assembly", "name": "Wall Type 1A - 7/8\" metal furring "
         "channels", "qty": 512.0},
        {"engine": "assembly", "name": "Wall Type 2A - joint compound",
         "qty": 178.0}], "review": []}
    rows = [{"page": 0, "title": "EXTERIOR ELEVATIONS"}]
    ait._exterior_inside_face({0: None}, rows, res, 277.7,
                              lambda r: r.get("title") or "")
    q = {x["name"]: x["qty"] for x in res["quantities"]}
    fur = q["Exterior wall inside face - 7/8\" metal furring channels"]
    assert abs(fur - 277.7 * (10 + 2 / 3) / 2) < 1
    gb = q["Exterior wall inside face - 5/8\" type X gypsum board"]
    assert abs(gb - 277.7 * (10 + 2 / 3)) < 1
    assert q["Exterior wall inside face - gypsum board 4'x8' sheets"] == 93
    assert "Wall Type 1A - 7/8\" metal furring channels" not in q
    assert q["Wall Type 2A - joint compound"] == 178.0


def test_painted_ceilings_are_gypsum_board_with_accessories():
    from app import aitakeoff as ait
    res = {"quantities": []}
    ait._gb_ceilings({"ceiling": {"ACT-1": 1148.1, "PT-4": 380.0,
                                  "EPP-1": 340.3}}, res, "A-901")
    q = {x["name"]: x["qty"] for x in res["quantities"]}
    assert q["Gypsum board ceiling"] == 720.3
    assert q["Gypsum board ceiling - 4'x8' sheets"] == 23
    assert q["Gypsum board ceiling - 1-1/4\" drywall screws"] == 958


def test_weeps_angle_and_ties_from_the_wall_detail():
    from app import aitakeoff as ait
    res = {"walls": {5: {"legend": {
        "1B": "CEMENT BOARD SIDING PRECAST CONC SILL W/ DRIP THRU WALL "
              "FLASHING ANGLE 2\" RIGID INSUL AIR GAP BRICK VENEER 3'-4\" "
              "FLASHING W/ WEEPS @ 24\" OC 8\""}}},
        "quantities": [], "review": [], "schedules": None}
    ait._exterior_veneer(res, 277.7)
    q = {x["name"]: x for x in res["quantities"]}
    r = {x["name"]: x for x in res["review"]}
    assert q['Brick weeps @ 24" OC']["qty"] == 139
    assert r["Steel angle at the brick (size per the wall detail)"][
        "qty"] == 277.7
    ties = [x for n, x in r.items() if n.startswith("Brick ties")][0]
    assert ties["qty"] == 521
    assert r["Sill flashing under the brick cap"]["qty"] == 277.7


def test_exterior_doors_from_glass_and_hardware_sets():
    from app import aitakeoff as ait
    rows = [{"DOOR NUMBER": "101A", "WIDTH": "3'-0\"", "TYPE 2": "TMPD/ID 1\"",
             "HARDWARE": "Set 1.0"},
            {"DOOR NUMBER": "101B", "WIDTH": "3'-0\"", "TYPE 2": "TMPD/ID 1\"",
             "HARDWARE": "Set 2.0"},
            {"DOOR NUMBER": "114B", "WIDTH": "3'-0\"", "TYPE 2": "-",
             "HARDWARE": "Set 2.0"},
            {"DOOR NUMBER": "105", "WIDTH": "3'-0\"", "TYPE 2": "TMPD",
             "HARDWARE": "Set 6.0"}]
    res = {"schedules": {"tables": [{"kind": "door", "confident": True,
                                     "rows": rows}]}}
    got = ait._ext_doors(res)
    assert len(got) == 3 and sum(w for w, _ in got) == 9.0
    res.update({"walls": {5: {"legend": {
        "1B": "PRECAST CONC SILL THRU WALL FLASHING BRICK VENEER 3'-4\" "
              "FLASHING W/ WEEPS @ 24\" OC"}}}, "quantities": [],
        "review": []})
    ait._exterior_veneer(res, 277.7)
    r = {x["name"]: x for x in res["review"]}
    cap = r["Exterior wall - brick wainscot cap (precast sill / rowlock)"]
    assert abs(cap["qty"] - 268.7) < 0.01 and "insulated glass" in cap["why"]


def test_storefront_widths_and_head_flashing():
    from app import aitakeoff as ait, schedules

    def cell(t, x, y, w=60):
        return {"text": t, "x0": x, "x1": x + w, "y0": y, "y1": y + 5,
                "cx": x + w / 2, "cy": y + 2.5, "h": 5}
    cs = [cell("STOREFRONT A.1", 0, 300), cell("STOREFRONT B", 200, 300),
          cell("STOREFRONT C", 0, 700),
          # A.1: overall 4'-0" over 3'-8"; B: 12'-0" over three 3'-9"
          cell("4'-0\"", 30, 40, 14), cell("3'-8\"", 30, 50, 14),
          cell("12'-0\"", 300, 40, 16), cell("3'-9\"", 220, 50, 14),
          cell("3'-9\"", 300, 50, 14),
          # C, below the first row: 7'-4"; a dimension of B's row above
          cell("7'-4\"", 60, 420, 14), cell("2'-0\"", 10, 650, 14)]
    t = schedules.elevation_types(cs)
    w = {r["MARK"]: r.get("_width_ft") for r in t["rows"]}
    assert w == {"A.1": 4.0, "B": 12.0, "C": 7.333}, w
    t["elevations"] = True
    marks = [(0, "add_count", {"measure": {
        "method": "AI takeoff: schedules", "group": g, "type": "count"}})
        for g in ["Window A.1"] * 3 + ["Window C"]]
    res = {"schedules": {"tables": [t]}, "marks": marks, "quantities": [],
           "review": []}
    lf = ait.window_head_lines(res)
    assert abs(lf - (3 * (4 + 8 / 12) + 7.333 + 8 / 12)) < 0.01
    r = res["review"][0]
    assert r["name"] == "Window head flashing" and "Window B" in r["why"]


def test_two_ceiling_rooms_split_by_the_rcp_grid():
    from app import aitakeoff as ait
    out = {"ceiling": {"ACT-1": 1148.1, "ACT-1 / PT-4": 1704.5,
                       "EPP-1": 340.3, "PT-4": 257.3}}
    res = {"quantities": [], "problems": []}
    assert ait._split_ceiling("ACT-1 / PT-4", 1704.5, 6, out, res,
                              (2601.0, "grid", "A-201"), "A-901")
    q = {x["name"]: x["qty"] for x in res["quantities"]}
    assert q["Ceiling ACT-1 (rooms with ACT-1 / PT-4)"] == 1452.9
    assert q["Ceiling PT-4 (rooms with ACT-1 / PT-4)"] == 251.6
    ait._gb_ceilings(out, res, "A-901")
    q = {x["name"]: x["qty"] for x in res["quantities"]}
    assert q["Gypsum board ceiling"] == 849.2
    # a grid bigger than every lay-in ceiling listed: left for review
    res = {"quantities": [], "problems": []}
    assert not ait._split_ceiling("ACT-1 / PT-4", 1704.5, 6, out, res,
                                  (4000.0, "grid", "A-201"), "A-901")
    assert res["problems"] and not res["quantities"]


def test_lay_in_grid_area():
    from app import actgrid, tradetakeoff as tt
    pf = 18.0
    segs = [(0, y * pf, 40 * pf, y * pf) for y in range(2, 30, 2)] + \
        [(x * pf, 0, x * pf, 30 * pf) for x in range(2, 40, 2)]
    orig = tt.styled_segments
    tt.styled_segments = lambda page: {((0, 0, 0), 0.25, ()): segs,
                                       ((0, 0, 0), 1.0, ()): [(0, 0, 9, 0)]}
    try:
        g = actgrid.grid_area(None, pf)
    finally:
        tt.styled_segments = orig
    assert g["spacing_ft"] == (2, 2)
    assert 1100 <= g["sf"] <= 1200            # 40' x 30' room, full tiles


def test_silt_fence_drawn_as_a_line_with_squares():
    from app import sitelines, tradetakeoff as tt

    class Pt:
        def __init__(self, x, y):
            self.x, self.y = x, y

    def seg(a, b):
        return ("l", Pt(*a), Pt(*b))

    class Page:
        def get_drawings(self):
            out = []
            for i in range(20):             # a square every 26 pt
                x = i * 26.0
                out.append({"color": (0, 0, 0), "items": [
                    seg((x - 24, 0), (x, 0)), seg((x, 0), (x - 1.8, 0)),
                    seg((x - 1.8, 0), (x - 1.8, -3.6)),
                    seg((x - 1.8, -3.6), (x + 1.8, -3.6)),
                    seg((x + 1.8, -3.6), (x + 1.8, 0)),
                    seg((x + 1.8, 0), (x, 0))]})
            return out
    gs = sitelines.marker_chains(Page(), 3.6)
    g = gs[0]
    assert g["markers"] == 20 and abs(g["spacing_ft"] - 7.22) < 0.01
    assert abs(g["length_ft"] - 20 * 26 / 3.6) < 0.2     # + half each end
    assert g["drawn_ft"] > 0


def test_panels_named_on_the_schedule_sheet_are_counted():
    from app import aitakeoff as ait
    res = {"schedules": {"tables": [], "panel_names": {
        "LP1": (79, "E-401"), "LP2": (79, "E-401")}},
        "quantities": [], "review": []}
    assert ait._panel_names(res) == 2
    q = {x["name"]: x["qty"] for x in res["quantities"]}
    assert q == {"Panel LP1": 1.0, "Panel LP2": 1.0}
    assert res["review"][0]["name"] == "Panel breakers"


def test_wheel_stops_and_accessible_emblem_from_the_site_plan():
    from app import aitakeoff as ait

    class Pg:
        def __init__(self, t):
            self.t = t

        def get_text(self, kind):
            return self.t
    doc = [Pg("2 ADA ACCESSIBLE PARKING SIGN\nLAYOUT AND STAKING PLAN\n7 SPACES\n8 SPACES\n15 PARKING "
              "SPACES PROVIDED (14 REGULAR, 1 ACCESSIBLE)\n"),
           Pg("PRECAST CONCRETE WHEEL STOP\n")]
    rows = [{"page": 0, "discipline": "civil", "kind": "plan",
             "number": "C-101"},
            {"page": 1, "discipline": "civil", "kind": "detail",
             "number": "C-601"}]
    res = {"quantities": [], "review": []}
    assert ait._parking(doc, rows, res) == 15
    q = {x["name"]: x["qty"] for x in res["quantities"]}
    assert q == {"Wheel stops (one per parking space)": 15.0,
                 "Accessible parking space emblem": 1.0}


def test_aggregate_base_under_the_slab():
    from app import aitakeoff as ait
    m = ait._SOG_BASE.search('4" GRADED AGGREGATE BASE (GAB)')
    assert m and m.group(1) == "4"
    assert ait._SOG_BASE.search('6" COMPACTED #57 STONE').group(1) == "6"


def test_slab_base_skips_a_feet_dimension(monkeypatch):
    from app import aitakeoff as ait

    class Pg:
        def get_text(self, *a):
            return ("4\" SLAB-ON-GRADE 1'-0\" GAB SHOULDER 4\" GRADED "
                    "AGGREGATE BASE (GAB)")
    res = {"quantities": [], "review": [], "finishes": None}
    monkeypatch.setattr(ait, "totals", lambda r: {"rooms_sf": 2700.0})
    rows = [{"page": 0, "discipline": "structural", "number": "S-301"}]
    ait._slab_on_grade([Pg()], rows, res)
    names = [x["name"] for x in res["review"]]
    assert 'Slab on grade - 4" graded aggregate base' in names, names



def test_filled_triangle_in_a_ring_found_at_another_size():
    fitz = pytest.importorskip("fitz")
    from app import tradetakeoff as tt
    import math
    d = fitz.open()
    d.new_page(width=400, height=400)
    d.new_page(width=400, height=400)
    leg, plan = d[0], d[1]

    def symbol(pg, cx, cy, rad):
        sh = pg.new_shape()
        pts = [fitz.Point(cx + rad * math.cos(a * math.pi / 8),
                          cy + rad * math.sin(a * math.pi / 8))
               for a in range(17)]
        sh.draw_polyline(pts)
        sh.finish(color=(0, 0, 0), width=0.8)
        t = 0.7 * rad
        sh.draw_polyline([fitz.Point(cx, cy - t), fitz.Point(cx + t, cy + t),
                          fitz.Point(cx - t, cy + t), fitz.Point(cx, cy - t)])
        sh.finish(color=None, fill=(0, 0, 0), closePath=True)
        sh.commit()
    symbol(leg, 50, 50, 8.5)                       # legend: bigger
    for i in range(4):
        symbol(plan, 60 + 60 * i, 200, 5.6)        # plans: smaller
    # a plain circle and a filled square elsewhere: not the symbol
    sh = plan.new_shape()
    sh.draw_circle(fitz.Point(300, 300), 6)
    sh.finish(color=(0, 0, 0))
    sh.draw_rect(fitz.Rect(100, 300, 106, 306))
    sh.finish(fill=(0, 0, 0))
    sh.commit()
    leg, plan = d[0], d[1]                 # pages again after drawing
    sig = tt.fill_ring_signature(leg.get_drawings(), fitz.Rect(40, 40, 60, 60))
    assert sig and abs(sig[0] - 0.5) < 0.05        # a triangle
    assert len(tt.fill_ring_hits(plan, sig)) == 4


def test_legend_symbol_that_is_only_a_word_is_counted_by_the_word():
    fitz = pytest.importorskip("fitz")
    from app import tradetakeoff as tt
    d = fitz.open()
    d.new_page(width=600, height=400)
    d.new_page(width=600, height=400)
    leg = d[0]
    leg.insert_text((400, 80), "LEGEND", fontsize=10)
    leg.insert_text((402, 107), "OS", fontsize=7)
    leg.insert_text((430, 107), "WALL MOUNTED DUAL TECHNOLOGY SENSOR",
                    fontsize=7)
    plan = d[1]
    for x in (60, 160, 260):
        plan.insert_text((x, 200), "OS", fontsize=7)
    plan.insert_text((60, 300), "OSB SHEATHING BY OTHERS", fontsize=7)
    d[1].insert_text((360, 200), "OS", fontsize=7)    # inside a counted one
    syms = []
    assert tt.legend_rows(d[0], text_syms=syms) == []
    assert [(n, t) for n, t, _r in syms] == \
        [("WALL MOUNTED DUAL TECHNOLOGY SENSOR", "OS")]
    other = [{"name": "CEILING SENSOR", "page": 0, "symbol": None,
              "hits": [{"page": 1, "rect": [355, 190, 375, 205]}]}]
    got = tt._text_symbol_counts(d, [(0, syms[0][0], "OS")], other, [],
                                 None, None)
    assert len(got) == 1 and len(got[0]["hits"]) == 3
    counts = {c["name"]: len(c["hits"]) for c in tt.legend_counts(d)}
    assert counts == {"WALL MOUNTED DUAL TECHNOLOGY SENSOR": 4}, counts



def test_equipment_in_two_schedules_is_counted_once():
    from app import schedules as sc
    hit = {"page": 3, "rect": (10.0, 10.0, 30.0, 18.0)}
    other = {"page": 3, "rect": (100.0, 10.0, 120.0, 18.0)}
    res = {"lines": [
        {"kind": "plumbing equipment", "key": "EWH-1", "name": "EWH-1 WATER HEATER",
         "qty": 2, "status": "taken off", "page": 3, "hits": [hit, other]},
        {"kind": "electrical equipment", "key": "EWH-1", "name": "EWH-1 WATER HEATER",
         "qty": 2, "status": "taken off", "page": 3, "hits": [hit, other]},
        {"kind": "mechanical equipment", "key": "AHU-1", "name": "AHU-1",
         "qty": 1, "status": "taken off", "page": 3, "hits": [other]},
        {"kind": "plumbing equipment", "key": "WH-2", "name": "WH-2",
         "qty": 1, "status": "taken off", "page": 4, "hits": [hit]}],
        "review": []}
    sc._one_line_per_tag(res, lambda p: f"P-{p}")
    assert [ln["key"] for ln in res["lines"]] == ["EWH-1", "AHU-1", "WH-2"]
    assert len(res["review"]) == 1 and "counted once" in res["review"][0]["why"]


def test_legend_symbol_counted_on_its_own_plan():
    from app import tradetakeoff as tt
    titles = {1: "LIGHTING PLAN", 2: "POWER PLAN", 3: "FIRE ALARM PLAN",
              4: "ELECTRICAL SCHEDULES"}
    where = [1, 2, 3, 4]
    assert tt._plans_for_symbol("FIRE ALARM MANUAL PULL STATION", where,
                                titles) == [3]
    assert tt._plans_for_symbol("CEILING MOUNTED SMOKE DETECTOR", where,
                                titles) == [3]
    assert tt._plans_for_symbol("2'X4' FIXTURE W/ EMERGENCY BATTERY PACK",
                                where, titles) == [1]
    assert tt._plans_for_symbol("DUPLEX CONVENIENCE OUTLET", where,
                                titles) == [2]
    assert tt._plans_for_symbol("PANELBOARD", where, titles) == where
    # no lighting plan in the set: the symbol is looked for everywhere
    assert tt._plans_for_symbol("DOWN LIGHT FIXTURE", [2, 3, 4],
                                titles) == [2, 3, 4]
    assert tt._plans_for_symbol("EXIT SIGN", where, None) == where


def test_equipment_tagged_only_on_the_mezzanine_plan_is_counted():
    from app import schedules as sc

    def cell(t, x, y, h=10):
        return {"text": t, "x0": x - 15, "x1": x + 15, "y0": y - h / 2,
                "y1": y + h / 2, "cx": x, "cy": y, "h": h}
    cells = [cell("HVAC PLAN", 1200, 1440),
             cell("SCALE: 1/4\" = 1'-0\"", 1200, 1455, 8),
             cell("MEZZANINE HVAC PLAN", 400, 700),
             cell("SCALE: 1/4\" = 1'-0\"", 400, 715, 8),
             cell("OCU-1", 1000, 380), cell("AHU-1", 1300, 900),
             cell("AHU-1", 300, 500)]
    info = {"cells": cells, "w": 2592, "segs": []}
    keys = {"OCU-1": "OCU-1", "AHU-1": "AHU-1"}
    vs = sc.views(cells, [])
    out = sc.count_tags(info, keys, "mechanical equipment", [], vs)
    # OCU-1 is only on the mezzanine plan: counted; AHU-1 is on the floor
    # plan, so its mezzanine copy stays a repeat for review
    assert {k: len(v) for k, v in out["main"].items()} == \
        {"OCU-1": 1, "AHU-1": 1}
    assert [(k, len(h)) for k, h, _t in out["other"]] == [("AHU-1", 1)]


def test_hvac_schedule_with_a_two_level_header_reads_its_marks():
    from app import schedules as sc

    def c(t, x, y, h=6.0):
        w = 3.2 * len(t)
        return {"text": t, "x0": x - w / 2, "x1": x + w / 2, "y0": y - h / 2,
                "y1": y + h / 2, "cx": x, "cy": y, "h": h}
    title = c("INDOOR FURNACE/COOLING COIL UNIT SCHEDULE", 730, 300, 8)
    cells = [title,
             c("BASIS OF DESIGN", 398, 322), c("HEATING", 773, 322),
             c("ELECTRICAL", 1014, 322),
             c("E.S.P. (IN", 562, 330),
             c("MARK", 225, 337), c("COOLING COIL", 494, 337),
             c("NOM. CFM", 622, 337), c("OA CFM", 684, 337),
             c("INPUT", 743, 337), c("MIN. EFF.", 804, 337),
             c("WC)", 562, 344), c("MANUFACTURER", 309, 344),
             c("AMPS", 870, 344), c("VOLTAGE", 1014, 344),
             c("FURNACE MODEL", 405, 351), c("MODEL", 494, 351),
             c("(MBH)", 743, 351), c("(%)", 804, 351)]
    for i, (mk, cfm) in enumerate((("IFC-1", "1,600"), ("IFC-2", "1,600"),
                                   ("IFC-3", "1,200"))):
        y = 366 + 12 * i
        cells += [c(mk, 225, y), c("TRANE", 309, y),
                  c("S9X2B080U4PSB", 405, y), c("5TXCB006AS3", 494, y),
                  c("0.5", 562, y), c(cfm, 622, y), c("290", 684, y),
                  c("80.0", 743, y), c("95.0", 804, y), c("11.3", 870, y),
                  c("115", 1014, y)]
    # the frame: a rule over the whole header under the title, and the
    # group row's rule only over its own columns (MARK's cell is boxed alone)
    segs = [(330, 314, 1100, 314), (200, 326, 250, 326)]
    t = sc.read_table(cells, title, "mechanical equipment", segs=segs)
    assert t["key"] == "MARK", (t["key"], t["why"], t["columns"])
    assert [r["MARK"] for r in t["rows"]] == ["IFC-1", "IFC-2", "IFC-3"]


def test_symbol_with_letters_is_counted_by_its_letters():
    fitz = pytest.importorskip("fitz")
    from app import tradetakeoff as tt
    d = fitz.open()
    d.new_page(width=600, height=400)
    d.new_page(width=600, height=400)
    leg = d[0]
    leg.insert_text((400, 80), "LEGEND", fontsize=10)
    sh = leg.new_shape()
    sh.draw_circle(fitz.Point(410, 104), 8)
    sh.finish(color=(0, 0, 0), width=0.8)
    sh.commit()
    leg = d[0]
    leg.insert_text((403, 107), "OS", fontsize=7)
    leg.insert_text((430, 107), "OCCUPANCY SENSOR", fontsize=7)
    plan = d[1]
    # on the plans the sensor is drawn smaller, with a square, not the
    # legend's circle: the picture doesn't match, the letters do
    for x in (60, 160, 260, 360):
        s2 = plan.new_shape()
        s2.draw_rect(fitz.Rect(x - 3, 192, x + 13, 204))
        s2.finish(color=(0, 0, 0), width=0.5)
        s2.commit()
        plan = d[1]
        plan.insert_text((x, 200), "OS", fontsize=5)
    plan.insert_text((60, 300), "OSB SHEATHING", fontsize=7)
    counts = {c["name"]: len(c["hits"]) for c in tt.legend_counts(d)}
    assert counts.get("OCCUPANCY SENSOR") == 4, counts


def test_schedule_beside_dimensioned_plans_keeps_its_own_width():
    from app import schedules as sc

    def c(t, x, y, h=10.0):
        w = 5.5 * len(t)
        return {"text": t, "x0": x - w / 2, "x1": x + w / 2, "y0": y - h / 2,
                "y1": y + h / 2, "cx": x, "cy": y, "h": h}
    title = c("ACCESSORY SCHEDULE", 1705, 69, 20)
    cells = [title,
             # an enlarged plan's dimension string level with the header
             c("11'-6\"", 488, 92), c("3'-2 3/8\"", 687, 92),
             c("9'-8 5/8\"", 861, 92), c("9'-11\"", 1127, 92),
             c("3'-0\"", 1301, 92),
             c("KEY", 1633, 110), c("ACCESSORY DESCRIPTION", 1770, 110),
             c("MOUNTING HEIGHT", 2066, 110)]
    for i, (k, d) in enumerate((("TT", "JUMBO ROLL TISSUE"),
                                ("SDU", "SANITARY NAPKIN DISPOSAL"),
                                ("MG1", "GLASS MIRROR"))):
        y = 140 + 30 * i
        cells += [c(k, 1632, y), c(d, 1760, y),
                  c("BOTTOM OF UNIT - 1'-6\"", 2058, y)]
    t = sc.read_table(cells, title, "toilet accessories")
    assert t["key"] == "KEY", (t["key"], t["columns"])
    assert t["bbox"][0] > 1400, t["bbox"]
    assert [r["KEY"] for r in t["rows"]] == ["TT", "SDU", "MG1"]


def test_tags_go_to_the_drawing_they_sit_in_not_the_nearest_title():
    pytest.importorskip("cv2")
    from app import schedules as sc

    def cell(t, x, y, h=10):
        return {"text": t, "x0": x - 15, "x1": x + 15, "y0": y - h / 2,
                "y1": y + h / 2, "cx": x, "cy": y, "h": h}

    def box(x0, y0, x1, y1, step=40):
        out = [(x0, y0, x1, y0), (x0, y1, x1, y1), (x0, y0, x0, y1),
               (x1, y0, x1, y1)]
        y = y0 + step
        while y < y1:                       # walls inside the drawing
            out.append((x0, y, x1, y))
            y += step
        return out
    # a wide floor plan with its title centred under it, and a small
    # mezzanine plan at the left with its title lower than the plan's top
    segs = box(640, 330, 1750, 1330) + box(250, 380, 600, 690)
    cells = [cell("HVAC PLAN", 1220, 1440),
             cell("SCALE: 1/4\" = 1'-0\"", 1220, 1455, 8),
             cell("MEZZANINE HVAC PLAN", 400, 705),
             cell("SCALE: 1/4\" = 1'-0\"", 400, 720, 8),
             cell("RG-1", 1000, 380),          # in the floor plan, near its top
             cell("RG-1", 400, 500)]           # in the mezzanine plan
    vs = sc.view_regions(sc.views(cells, []), segs, 2592, 1728)
    assert all(v.get("region") for v in vs)
    assert sc.view_of(cells[4], vs, 2592)["title"] == "HVAC PLAN"
    assert sc.view_of(cells[5], vs, 2592)["title"] == "MEZZANINE HVAC PLAN"


def test_detail_dimensions_at_another_scale_do_not_fail_the_sheet(
        monkeypatch):
    """A 1/8" plan sheet whose only measurable dimensions sit in its 1/4"
    details: they measure 2x at the plan's scale, which is the details'
    scale, not a wrong plan scale."""
    from app import scalecheck as sc
    vals = [1, 12.833, 15.5, 1, 1, 1, 1, 1, 2.5, 4, 6, 1, 1, 8, 3.25]
    monkeypatch.setattr(sc, "_words", lambda p: [(0, 0, 1, 1, "x", v)
                                                for v in vals])
    monkeypatch.setattr(sc, "_segments", lambda p: [])
    pf = 1 / 8 * 72                       # 1/8" = 1'-0" in points per foot

    def run(**kw):
        it = iter([v * 2 * pf for v in vals])
        monkeypatch.setattr(sc, "_measure", lambda w, s: next(it))
        return sc.grade(None, pf, **kw)
    assert run()["grade"] == "F"
    g = run(others=[1 / 4 * 72])
    assert g["grade"] != "F" and g["other_view"] == len(vals)
    # dimensions whose fit (with a tick offset) is the detail scale
    vals2 = [4, 6, 8, 10, 12, 14, 16, 20, 24, 30]
    monkeypatch.setattr(sc, "_words", lambda p: [(0, 0, 1, 1, "x", v)
                                                for v in vals2])
    it = iter([(v * 4 / 3 - 2) * 27.0 for v in vals2])
    monkeypatch.setattr(sc, "_measure", lambda w, s: next(it))
    g = sc.grade(None, 3 / 8 * 72, others=[1 / 2 * 72])
    assert g["grade"] is None and "another view" in g["why"]


def test_wall_type_diamond_drawn_as_four_loose_lines_is_read():
    """A wall-type diamond drawn as four separate strokes (no one closed
    path) around its code is still a tag; a lone V of two strokes isn't."""
    import fitz
    from app import autowalls
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    top, rt, bt, lf = (100, 89), (118, 107), (100, 125), (82, 107)
    for a, b in ((top, lf), (rt, top), (lf, bt), (bt, rt)):
        page.draw_line(a, b, width=0.8)
    page.insert_text((97, 111), "3", fontsize=10)
    page.draw_line((250, 89), (232, 107), width=0.8)       # half a diamond
    page.draw_line((268, 107), (250, 89), width=0.8)
    page.insert_text((247, 111), "4", fontsize=10)
    tags = autowalls.find_type_tags(page)
    assert [(t["code"], t["shape"]) for t in tags] == [("3", "diamond")]
    assert abs(tags[0]["pt"][0] - 100) < 1 and abs(tags[0]["pt"][1] - 107) < 1
