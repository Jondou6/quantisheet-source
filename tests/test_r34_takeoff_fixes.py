"""r34 patch: Aiken-run bugs and review findings H2-H5, each on a small
made-up fixture (no real drawing's names, positions or quantities)."""
import math
import fitz
import pytest

from app import aitakeoff as ait


# ---- H5: the mezzanine rule needs a mezzanine-only title ---------------------------
@pytest.mark.parametrize("title,only", [
    ("MEZZANINE PLAN", True),
    ("MEZZANINE FLOOR PLAN", True),
    ("MEZZ. PLAN", True),
    ("FIRST FLOOR AND MEZZANINE PLAN", False),
    ("GROUND FLOOR & MEZZANINE PLAN", False),
    ("LEVEL 1 / MEZZANINE PLAN", False),
    ("FLOOR PLAN", False),
    ("MEZZANINE AND ROOF PLAN", False),            # review 0.13.9 #7
    ("LEVEL 2 MEZZANINE PLAN", True),
])
def test_h5_mezzanine_only_title(title, only):
    assert ait.mezzanine_only(title) is only


def test_h5_combined_first_floor_and_mezzanine_keeps_its_exterior():
    rows = {1: {"title": "FLOOR PLAN"}, 2: {"title": "MEZZANINE PLAN"},
            3: {"title": "FIRST FLOOR AND MEZZANINE PLAN"}}
    # the mezzanine-only sheet skips the exterior pass, the combined one
    # doesn't
    assert ait.no_exterior_pages([1, 2, 3], rows) == {2}
    # a set whose only wall sheet is the combined one keeps it too
    assert ait.no_exterior_pages([3], rows) == set()
    # a mezzanine plan with no other wall sheet keeps its exterior
    assert ait.no_exterior_pages([2], rows) == set()


# ---- H4: a keynote number is never joined into a pipe size -------------------------
def _frac_page(gap, bubble="circle"):
    d = fitz.open()
    pg = d.new_page(width=1728, height=1152)
    if bubble == "circle":
        pg.draw_circle((400 - gap - 3, 397), 6)
    elif bubble == "hexagon":
        cx, cy, r = 400 - gap - 3, 397, 6
        import math
        pts = [(cx + r * math.cos(math.pi / 3 * k),
                cy + r * math.sin(math.pi / 3 * k)) for k in range(7)]
        pg.draw_polyline(pts)
    pg.insert_text((400 - gap - 6, 400), "3", fontsize=8)
    pg.insert_text((400, 400), '1/2"CW', fontsize=8)
    return d, pg


@pytest.mark.parametrize("gap", [2, 6, 9])
@pytest.mark.parametrize("bubble", ["circle", "hexagon"])
def test_h4_keynote_number_not_merged(gap, bubble):
    from app import tradetakeoff as tt
    _d, pg = _frac_page(gap, bubble)
    names = sorted(t["name"] for t in tt.labels(pg) if t["kind"] == "pipe")
    assert names == ['1/2" CW'], names


def test_h4_bare_whole_number_still_joins():
    """The split "1" + "1/2"V" tag (no bubble) is still 1-1/2"."""
    from app import tradetakeoff as tt
    _d, pg = _frac_page(2, bubble=None)
    names = sorted(t["name"] for t in tt.labels(pg) if t["kind"] == "pipe")
    assert names == ['3-1/2" CW'], names


def test_h4_bubble_between_number_and_tag_blocks_the_join():
    """A number with a keynote bubble drawn between it and the tag."""
    from app import tradetakeoff as tt
    d = fitz.open()
    pg = d.new_page(width=1728, height=1152)
    pg.insert_text((388, 400), "1", fontsize=8)
    pg.draw_circle((395, 397), 3.2)
    pg.insert_text((400, 400), '1/2"CW', fontsize=8)
    names = sorted(t["name"] for t in tt.labels(pg) if t["kind"] == "pipe")
    assert names == ['1/2" CW'], names


# ---- H3: Roof Areas - an over-12:12 label is flagged, never priced at 4:12 ---------
def _roof_page(labels):
    d = fitz.open()
    pg = d.new_page(width=800, height=600)
    for (x, y), text in labels:
        pg.insert_text((x, y), text, fontsize=9)
    return d, pg


SQ = [(50, 50), (300, 50), (300, 300), (50, 300)]


def test_h3_only_label_is_steep_area_flagged_not_defaulted():
    from app import tradetakeoff as tt
    _d, pg = _roof_page([((100, 100), "18:12")])
    pitch, note = tt.roof_pitch(SQ, tt.pitch_labels(pg),
                                tt.steep_pitch_labels_at(pg), 4)
    assert pitch is None
    assert "18:12" in note and "over 12:12" in note


def test_h3_steep_label_inside_wins_over_a_far_good_one():
    from app import tradetakeoff as tt
    _d, pg = _roof_page([((100, 100), "18:12"), ((600, 500), "6:12")])
    pitch, note = tt.roof_pitch(SQ, tt.pitch_labels(pg),
                                tt.steep_pitch_labels_at(pg), 4)
    assert pitch is None and "18:12" in note
    # an area with the 6:12 inside it takes 6:12
    other = [(500, 400), (750, 400), (750, 580), (500, 580)]
    assert tt.roof_pitch(other, tt.pitch_labels(pg),
                         tt.steep_pitch_labels_at(pg), 4)[0] == 6


def test_h3_no_label_at_all_uses_the_default_and_says_so():
    from app import tradetakeoff as tt
    _d, pg = _roof_page([])
    pitch, note = tt.roof_pitch(SQ, tt.pitch_labels(pg),
                                tt.steep_pitch_labels_at(pg), 4)
    assert pitch == 4 and "no pitch printed" in note.lower()


def test_h3_status_keeps_the_over_cap_warning():
    from app import tradetakeoff as tt
    msg = tt.roof_status(n=0, squares=0.0, flagged=["Roof A (18:12)"],
                         steep=["18:12"], any_pitch=True, default=4)
    assert "over 12:12" in msg and "18:12" in msg
    assert "No pitch printed" not in msg
    assert "review" in msg.lower()
    ok = tt.roof_status(n=2, squares=12.3, flagged=[], steep=[],
                        any_pitch=False, default=4)
    assert "No pitch printed, using 4:12" in ok


# ---- H2: Count by Label - separate plan areas and nearby tags all count ------------
def _put(p, x, y, t, fs=9):
    p.insert_text((x, y), t, fontsize=fs)


def _count_sheet(views, notes=True, tb=True):
    d = fitz.open()
    p = d.new_page(width=1728, height=1152)
    for title, x, y, tags in views:
        for (tx, ty) in tags:
            _put(p, tx, ty, "P-1")
        _put(p, x, y, title, 14)
        _put(p, x, y + 16, 'SCALE: 1/8" = 1\'-0"', 9)
        p.draw_rect(fitz.Rect(x - 20, y - 420, x + 560, y - 30), width=1.5)
    if notes:
        _put(p, 1250, 100, "GENERAL NOTES", 12)
        _put(p, 1250, 118, "1. PROVIDE P-1 AT EACH LOCATION SHOWN.", 8)
    if tb:
        p.draw_rect(fitz.Rect(1500, 0, 1728, 1152), width=2)
        _put(p, 1520, 1000, "P-1 FIXTURE SHEET", 8)
        _put(p, 1520, 1100, "SHEET X-101", 10)
    return d


def _n(d):
    from app import autocount
    return len(autocount.find_by_label(d, "P-1"))


THREE = [(200, 700), (350, 650), (500, 800)]


@pytest.mark.parametrize("views,expected", [
    ([("FIRST FLOOR PLAN", 100, 1000, THREE)], 3),
    ([("FIRST FLOOR PLAN", 100, 1000, THREE),
      ("ENLARGED TOILET PLAN", 800, 1000, [(900, 700)])], 3),
    ([("FLOOR PLAN - AREA A", 100, 1000, THREE),
      ("FLOOR PLAN - AREA B", 800, 1000, [(900, 700), (1100, 650)])], 5),
    ([("FIRST FLOOR PLAN - EAST WING", 100, 1000, THREE),
      ("FIRST FLOOR PLAN - WEST WING", 800, 1000, [(900, 700)])], 4),
    ([("FIRST FLOOR PLAN", 100, 1000, THREE),
      ("SECOND FLOOR PLAN", 800, 1000, [(900, 700), (1100, 650)])], 5),
    ([("FIRST FLOOR PLAN", 100, 1000, [(200, 700), (200, 712)])], 2),
    ([("FIRST FLOOR PLAN", 100, 1000, [(200, 700), (226, 700)])], 2),
])
def test_h2_count_by_label(views, expected):
    assert _n(_count_sheet(views)) == expected


def test_h2_same_text_drawn_twice_in_place_counts_once():
    """A tag printed twice on top of itself (a bold/shadow copy) is one."""
    d = _count_sheet([("FIRST FLOOR PLAN", 100, 1000, [(200, 700)])])
    _put(d[0], 200.4, 700.3, "P-1")
    assert _n(d) == 1


# ---- Aiken #2: a room tag on several sheets of one floor is one room ---------------
def _room(name, sf, tag_sf=None, number=None):
    return {"name": name, "sqft": sf, "value": sf, "tag_sf": tag_sf,
            "number": number}


def test_rooms_same_tag_on_other_plans_counted_once_even_if_trace_differs():
    """The floor plan's trace is kept; the same numbered, named room on
    the equipment plan and the ceiling plan (traced smaller or larger,
    their tags carry no area) is the same room - taken off once."""
    rows = {0: {"title": "FLOOR PLAN"},
            1: {"title": "EQUIPMENT PLAN"},
            2: {"title": "REFLECTED CEILING PLAN"}}
    per = {0: [_room("LAB 201", 300, 300, "201"),
               _room("OFFICE 202", 150, 150, "202")],
           1: [_room("LAB 201", 240), _room("OFFICE 202", 151)],
           2: [_room("LAB 201", 190), _room("STORAGE 203", 40, None, "203")]}
    kept, dups = ait.dedupe_rooms(per, rows)
    names = sorted(r["name"] for rs in kept.values() for r in rs)
    assert names == ["LAB 201", "OFFICE 202", "STORAGE 203"]
    assert [r["sqft"] for r in kept[0]] == [300, 150]
    assert {d[0]["name"]: d[2] for d in dups} == {"LAB 201": [1, 2],
                                                  "OFFICE 202": [1]}


def test_rooms_same_number_on_another_building_or_floor_is_not_merged():
    for t0, t1 in (("BUILDING A FLOOR PLAN", "BUILDING B FLOOR PLAN"),
                   ("FIRST FLOOR PLAN", "SECOND FLOOR PLAN"),
                   ("FLOOR PLAN - AREA A", "FLOOR PLAN - AREA B")):
        rows = {0: {"title": t0}, 1: {"title": t1}}
        per = {0: [_room("LAB 101", 300, 300, "101")],
               1: [_room("LAB 101", 300, None, "101")]}
        kept, _d = ait.dedupe_rooms(per, rows)
        assert sum(len(v) for v in kept.values()) == 2, (t0, t1)


def test_rooms_unlevelled_sheet_still_matches_a_levelled_one():
    """'FLOOR PLAN' and 'FIRST FLOOR FINISH PLAN' can be the same floor."""
    rows = {0: {"title": "FLOOR PLAN"},
            1: {"title": "FIRST FLOOR FINISH PLAN"}}
    per = {0: [_room("LAB 101", 300, 300, "101")],
           1: [_room("LAB 101", 210, None, "101")]}
    kept, _d = ait.dedupe_rooms(per, rows)
    assert sum(len(v) for v in kept.values()) == 1


def test_rooms_name_disagrees_is_not_merged():
    rows = {0: {"title": "FLOOR PLAN"}, 1: {"title": "FINISH PLAN"}}
    per = {0: [_room("LAB 201", 300, 300, "201")],
           1: [_room("KENNEL 201", 200)]}
    kept, _d = ait.dedupe_rooms(per, rows)
    assert sum(len(v) for v in kept.values()) == 2


# ---- Aiken civil: coincident copies and a label crossing another line --------------
PER_FT = 3.6                     # 1" = 20' on a 72 pt/in sheet


def _civil_page():
    d = fitz.open()
    pg = d.new_page(width=1200, height=800)
    return d, pg


def _line(pg, a, b, width=0.5, color=(0, 0, 0)):
    sh = pg.new_shape()
    sh.draw_line(a, b)
    sh.finish(width=width, color=color)
    sh.commit()


def test_civil_pipe_drawn_three_times_on_top_of_itself_counts_once():
    from app import civiltakeoff as ct
    d, pg = _civil_page()
    # the pipe drawn as thin outlined slivers end to end (each piece a
    # narrow closed shape: two long edges and a short one)
    for i in range(10):
        x0 = 100 + i * 72
        sh = pg.new_shape()
        sh.draw_polyline([(x0, 400), (x0 + 72, 400), (x0 + 72, 400.9),
                          (x0, 400)])
        sh.finish(width=0, color=(0, 0, 0), closePath=True)
        sh.commit()
    pg.insert_text((300, 396), '6" PVC SANITARY', fontsize=8)
    gs = ct.pipe_systems(pg, PER_FT, "ft")
    g = next(g for g in gs if g["size"] == 6)
    assert g["length"] == pytest.approx(720 / PER_FT, rel=0.03), g["length"]


def test_civil_label_names_the_pipe_it_runs_along_not_a_line_crossing_it():
    """A label set along its pipe where an outline (a parking lot edge,
    another pen) crosses it: the pipe gets the label, the outline isn't
    pipe."""
    from app import civiltakeoff as ct
    d, pg = _civil_page()
    _line(pg, (100, 400), (1100, 400), width=0.25)          # the pipe
    sh = pg.new_shape()                                     # an outline
    sh.draw_polyline([(331, 150), (331, 700), (900, 700), (900, 150)])
    sh.finish(width=0.75, color=(0, 0, 0), closePath=False)
    sh.commit()
    pg.insert_text((320, 397), '2" PW', fontsize=8)
    gs = ct.pipe_systems(pg, PER_FT, "ft")
    g = next(g for g in gs if g["size"] == 2)
    assert g["length"] == pytest.approx(1000 / PER_FT, rel=0.03), \
        [(x["name"], x["length"]) for x in gs]


def test_civil_leader_label_takes_the_pen_its_twin_labels_name():
    """The same label printed along a pipe twice, and once more with a
    leader whose tip lands where an outline (another pen) meets the pipe:
    that label names the pipe's pen too, so the outline isn't pipe."""
    from app import civiltakeoff as ct
    d, pg = _civil_page()
    _line(pg, (100, 400), (1100, 400), width=0.25)          # the pipe
    sh = pg.new_shape()                                     # an outline
    sh.draw_polyline([(700, 150), (700, 396), (1000, 396), (1000, 150)])
    sh.finish(width=0.75, color=(0, 0, 0), closePath=False)
    sh.commit()
    pg.insert_text((200, 397), '2" PW', fontsize=8)
    pg.insert_text((450, 397), '2" PW', fontsize=8)
    labs = [{"center": (800.0, 396.0), "dir": None}]
    real = ct._leaders

    def fake_leaders(page, ls):
        real(page, ls)
        extra = dict(ls[0], center=labs[0]["center"], dir=None,
                     leader=[(760.0, 300.0), labs[0]["center"]])
        ls.append(extra)
    import pytest as _p
    mp = _p.MonkeyPatch()
    mp.setattr(ct, "_leaders", fake_leaders)
    try:
        gs = ct.pipe_systems(pg, PER_FT, "ft")
    finally:
        mp.undo()
    g = next(g for g in gs if g["size"] == 2)
    assert g["length"] == pytest.approx(1000 / PER_FT, rel=0.03), \
        [(x["name"], x["length"]) for x in gs]


# ---- Aiken #3: a word beside the table between two header lines --------------------
def _acc_schedule(stray=True):
    d = fitz.open()
    pg = d.new_page(width=1728, height=1152)
    put = lambda x, y, t, fs=9: pg.insert_text((x, y), t, fontsize=fs)
    put(400, 100, "ACCESSORY SCHEDULE", 14)
    # two-line headers, with KEY / DESCRIPTION set level with the gap
    put(640, 130, "MAKER NO.", 10)
    put(760, 130, "MOUNTING", 10)
    put(400, 143, "KEY", 10)
    put(460, 143, "DESCRIPTION", 10)
    put(640, 149, "/ ALT NO. *", 10)
    put(760, 149, "HEIGHT", 10)
    if stray:                       # title-block words far to the right
        put(1300, 137, "use", 8)
    keys = ["TP", "MR1", "SD", "GB36", "GB42"]
    for i, k in enumerate(keys):
        y = 170 + 24 * i
        put(404, y, k, 8)
        put(460, y, f"ACCESSORY ITEM {i + 1}", 8)
        put(640, y, f"B-{2000 + i}", 8)
        put(760, y, f"TOP OF UNIT - {3 + i}'-0\"", 8)
    return d, pg, keys


@pytest.mark.parametrize("stray", [False, True])
def test_accessory_schedule_reads_with_a_stray_word_beside_its_header(stray):
    from app import schedules as sch
    _d, pg, keys = _acc_schedule(stray)
    ts = [t for t in sch.read_page(pg) if "ACCESSORY" in t["title"]]
    assert ts, "table not found"
    t = ts[0]
    assert t["key"] == "KEY", t["columns"]
    assert [r["KEY"] for r in t["rows"]] == keys
    assert t["confident"], t["why"]


# ---- Aiken #3b: an untagged schedule item whose QTY column is proven ---------------
def _keyed_run(rows, plan_counts, confident=True):
    from app import schedules as sch
    t = {"kind": "equipment", "key": "TAG", "qty": "QTY", "desc": "DESC",
         "rows": rows, "confident": confident, "why": "", "title": "EQUIP",
         "csi": "11 00 00", "sheet": "X-1", "page": 0}
    plans = [{"page": 1, "title": "EQUIPMENT PLAN"}]

    def counts_on(pr, keys, kind):
        main = {}
        for k, n in plan_counts.items():
            main[k] = [{"rect": (10 * i, 0, 10 * i + 5, 5), "n": 1}
                       for i in range(n)]
        return {"main": main, "other": []}
    res = {"lines": [], "review": []}
    sch._keyed(t, plans, counts_on, res, lambda p: f"S-{p}", {})
    return {ln["key"]: (ln["status"], ln["qty"]) for ln in res["lines"]}


def _rows(spec):
    return [{"TAG": k, "QTY": str(q), "DESC": f"ITEM {k}"} for k, q in spec]


def test_untagged_item_takes_the_schedule_qty_when_the_column_is_proven():
    got = _keyed_run(_rows([("E1", 2), ("E2", 3), ("E3", 1), ("E4", 2)]),
                     {"E1": 2, "E2": 3, "E3": 1})
    assert got["E4"] == ("taken off", 2)
    assert got["E1"] == ("taken off", 2)


def test_untagged_item_stays_in_review_when_qty_isnt_proven():
    # the other keys disagree with their QTY: the column isn't trusted
    got = _keyed_run(_rows([("E1", 2), ("E2", 3), ("E3", 1), ("E4", 2)]),
                     {"E1": 5, "E2": 1, "E3": 1})
    assert got["E4"][0] == "review"
    # only one other key to prove it: not enough
    got = _keyed_run(_rows([("E1", 2), ("E4", 2)]), {"E1": 2})
    assert got["E4"][0] == "review"
    # a schedule not read with confidence: never
    got = _keyed_run(_rows([("E1", 2), ("E2", 3), ("E3", 1), ("E4", 2)]),
                     {"E1": 2, "E2": 3, "E3": 1}, confident=False)
    assert got["E4"][0] == "review"


# ---- Aiken #4: untagged double lines outside the ductwork's layer aren't ducts -----
def test_duct_review_lists_only_double_lines_in_the_duct_layer():
    from app import aitakeoff
    d = fitz.open()
    pg = d.new_page(width=1728, height=1152)
    ppu = 18.0                                 # 1/4" = 1'-0"
    duct = (0, 0, 0)
    sh = pg.new_shape()
    # a tagged 12" round duct, 30 ft long, in the duct pen (1.5 pt)
    for y in (300, 300 + 12 / 12 * ppu):
        sh.draw_line((200, y), (200 + 30 * ppu, y))
    sh.finish(width=1.5, color=duct)
    # an untagged 8"-wide pair in the duct pen, 20 ft long (a duct)
    for y in (600, 600 + 8 / 12 * ppu):
        sh.draw_line((200, y), (200 + 20 * ppu, y))
    sh.finish(width=1.5, color=duct)
    # a 6" wall pair in a thin grey background pen, 25 ft (not a duct)
    for y in (900, 900 + 6 / 12 * ppu):
        sh.draw_line((200, y), (200 + 25 * ppu, y))
    sh.finish(width=0.25, color=(0.5, 0.5, 0.5))
    sh.commit()
    pg.insert_text((300, 296), '12"Ø', fontsize=9)
    pg.insert_text((700, 296), '12"Ø', fontsize=9)
    kept, review, _dropped = aitakeoff.duct_groups(pg, ppu, "ft")
    assert [g["name"] for g in kept] == ['12" round']
    names = [n for n, _l, _w in review]
    assert any("8in" in n for n in names), names
    assert not any("6in" in n for n in names), names


# ---- Aiken #5: a dashed pipe is measured along its whole line, gaps included --
def _dashed(sh, a, b, dash, gap):
    L = math.hypot(b[0] - a[0], b[1] - a[1])
    ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
    # like CAD: the pattern starts and ends on a dash at the line's ends
    t, e = 0.0, 0.0
    while t < L:
        e = min(L, t + dash)
        sh.draw_line((a[0] + ux * t, a[1] + uy * t), (a[0] + ux * e, a[1] + uy * e))
        t = e + gap
    if e < L:
        s0 = max(e + 1.0, L - dash)
        sh.draw_line((a[0] + ux * s0, a[1] + uy * s0), b)


@pytest.mark.parametrize("dash,gap", [(8, 9), (20, 4), (40, 9)])
def test_dashed_pipe_counts_its_full_length(dash, gap):
    from app import tradetakeoff as tt
    d = fitz.open()
    pg = d.new_page(width=1728, height=1152)
    ppu = 18.0
    sh = pg.new_shape()
    _dashed(sh, (200, 400), (200 + 40 * ppu, 400), dash, gap)        # 40 ft
    _dashed(sh, (200 + 40 * ppu, 400), (200 + 40 * ppu, 400 + 12 * ppu),
            dash, gap)                                                # 12 ft
    sh.finish(width=1.5, color=(0, 0, 0))
    sh.commit()
    pg.insert_text((400, 396), '1/2"CW', fontsize=8)
    gs = [g for g in tt.mep_runs(pg, ppu, "ft") if g["labelled"]]
    assert [g["name"] for g in gs] == ['1/2" CW']
    assert abs(gs[0]["length"] * ppu / ppu - 52.0) / 52.0 < 0.04, gs[0]["length"]


def test_close_dash_gaps_leaves_real_gaps_and_turns_alone():
    from app import tradetakeoff as tt

    def total(rs):
        out, linked = tt.close_dash_gaps(rs)
        return round(sum(tt.poly_len(r) for r in out), 6), len(out), linked
    # a wall broken by a 3 ft door at 1/4" scale (54 pt) is left as it is
    assert total([[(0, 0), (100, 0)], [(154, 0), (300, 0)]]) == (246, 2, set())
    # three dashes in a row: the gaps count, the pieces stay separate
    assert total([[(0, 0), (8, 0)], [(17, 0), (25, 0)], [(34, 0), (42, 0)]]) \
        == (42, 3, {0, 1, 2})
    # one break (a fitting, a tag) between two lines is not a dash pattern
    assert total([[(0, 0), (100, 0)], [(106, 0), (200, 0)]])[2] == set()
    # nor is a row of uneven breaks
    assert total([[(0, 0), (30, 0)], [(31, 0), (60, 0)], [(71, 0), (90, 0)]])[2] \
        == set()
    # side by side lines (a wall's faces) never close up
    assert total([[(0, 0), (8, 0)], [(10, 6), (18, 6)]])[2] == set()
    # a line that turns a corner across a gap is not a dash
    assert total([[(0, 0), (8, 0)], [(12, 4), (12, 20)]])[2] == set()


def test_dashed_pipe_keeps_its_size_change():
    """Dashes closed up must not carry one size past a tag for another."""
    from app import tradetakeoff as tt
    d = fitz.open()
    pg = d.new_page(width=1728, height=1152)
    ppu = 18.0
    sh = pg.new_shape()
    _dashed(sh, (200, 400), (200 + 30 * ppu, 400), 8, 9)              # 30 ft 1"
    _dashed(sh, (200 + 30 * ppu, 400), (200 + 60 * ppu, 400), 8, 9)   # 30 ft 3/4"
    sh.finish(width=1.5, color=(0, 0, 0))
    sh.commit()
    pg.insert_text((300, 396), '1"HW', fontsize=8)
    pg.insert_text((1000, 396), '3/4"HW', fontsize=8)
    gs = {g["name"]: g["length"] for g in tt.mep_runs(pg, ppu, "ft")
          if g["labelled"]}
    assert set(gs) == {'1" HW', '3/4" HW'}
    assert abs(gs['1" HW'] + gs['3/4" HW'] - 60.0) < 2.0
    assert 20 < gs['1" HW'] < 40 and 20 < gs['3/4" HW'] < 40


# ---- Aiken #3: accessory tags in a mounting-heights view are not plan tags ----
@pytest.mark.parametrize("title,scale_above,tight", [
    ("TOILET ACCESSORIES- MOUNTING HEIGHTS", True, False),
    ("ACCESSORY MOUNTING HEIGHTS", False, False),
    ("TYPICAL MOUNTING HEIGHT DIAGRAM", False, False)])
def test_tags_in_a_mounting_heights_view_are_not_counted(title, scale_above,
                                                        tight):
    from app import schedules
    d = fitz.open()
    pg = d.new_page(width=1728, height=1152)
    # the enlarged plan with two TT tags, titled with the scale under it
    for x, y in ((200, 300), (420, 300)):
        pg.insert_text((x, y), "TT", fontsize=9)
    pg.insert_text((200, 520), "ENLARGED TOILET PLAN", fontsize=12)
    pg.insert_text((200, 538), 'SCALE: 1/4" = 1\'-0"', fontsize=8)
    # the mounting heights drawing with the same tag once
    pg.insert_text((900, 300), "TT", fontsize=7)
    pg.insert_text((900, 320), "TOILET PAPER DISPENSER", fontsize=6)
    if scale_above:
        pg.insert_text((900, 502), 'SCALE: 3/8" = 1\'-0"', fontsize=8)
        pg.insert_text((900, 520), title, fontsize=12)
    else:
        pg.insert_text((900, 520), title, fontsize=20 if tight else 12)
        pg.insert_text((920, 529 if tight else 538), 'SCALE: 3/8" = 1\'-0"',
                       fontsize=8)
    info = schedules.sheet_info(pg)
    ex = schedules.plan_exclusions(info)
    c = schedules.count_tags(info, {"TT": "TT"}, "accessories", ex)
    assert len(c["main"].get("TT", [])) == 2, c


def test_schedule_line_taken_from_qty_reaches_the_quantities(monkeypatch):
    """A key taken off from the schedule's QTY column has no plan tags to
    mark - it must still be a takeoff quantity, not vanish."""
    from app import aitakeoff, schedules
    sres = {"lines": [
        {"kind": "equipment", "key": "K6", "name": "K6 SIX UNIT BANK",
         "csi": "11 00 00", "qty": 2, "unit": "ea", "page": 0,
         "basis": "0 tag(s) on the plans, schedule QTY 2",
         "status": "taken off", "from_qty": True,
         "why": "not tagged on the plans - taken from the schedule's QTY "
                "column (the other keys' tags agree with it)", "hits": []},
        {"kind": "equipment", "key": "K7", "name": "K7 OTHER", "csi": "",
         "qty": 1, "unit": "ea", "page": 0, "basis": "", "status": "taken off",
         "why": "", "hits": []}],
        "review": [], "problems": [], "tables": []}
    monkeypatch.setattr(schedules, "takeoff", lambda *a, **k: sres)
    res = {"marks": [], "review": [], "problems": [], "sheets": {},
           "quantities": []}
    d = fitz.open()
    d.new_page()
    aitakeoff._schedules(d, [{"page": 0, "number": "X-105", "title": "X"}],
                         [0], res)
    q = [x for x in res["quantities"] if x["name"].startswith("K6")]
    assert len(q) == 1 and q[0]["qty"] == 2 and q[0]["unit"] == "EA"
    assert q[0]["status"] == "taken off" and "QTY" in q[0]["basis"]
    # a taken-off line with no tags and no QTY flag is not invented
    assert not [x for x in res["quantities"] if x["name"].startswith("K7")]


def test_keyed_line_from_qty_is_flagged():
    from app import schedules as sch
    t = {"kind": "equipment", "key": "TAG", "qty": "QTY", "desc": "DESC",
         "rows": _rows([("E1", 2), ("E2", 3), ("E3", 1), ("E4", 2)]),
         "confident": True, "why": "", "title": "EQUIP", "csi": "11 00 00",
         "sheet": "X-1", "page": 0}

    def counts_on(pr, keys, kind):
        return {"main": {k: [{"rect": (10 * i, 0, 10 * i + 5, 5), "n": 1}
                             for i in range(n)]
                         for k, n in {"E1": 2, "E2": 3, "E3": 1}.items()},
                "other": []}
    res = {"lines": [], "review": []}
    sch._keyed(t, [{"page": 1, "title": "EQUIPMENT PLAN"}], counts_on, res,
               lambda p: f"S-{p}", {})
    by = {ln["key"]: ln for ln in res["lines"]}
    assert by["E4"].get("from_qty") is True
    assert not by["E1"].get("from_qty")



def test_a_notes_line_under_a_scale_note_is_not_a_view_title():
    from app import schedules
    d = fitz.open()
    pg = d.new_page(width=1728, height=1152)
    pg.insert_text((200, 300), 'VERIFY SCALE OF 1/4" = 1\'-0" BEFORE USE WITH', fontsize=8)
    pg.insert_text((200, 311), "ARCHITECTURAL DETAILS AND SHOP DRAWINGS.", fontsize=8)
    info = schedules.sheet_info(pg)
    assert schedules.views(info["cells"]) == []
