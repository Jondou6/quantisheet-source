"""r34 stage 4 (written before the code). Synthetic pages only."""
import fitz
import pytest

ACC = ["TT", "SDU", "PT/W", "MG1", "SD", "GB18", "GB36", "GB42"]


def _keys(ks):
    return {k.upper(): k for k in ks}


def _acc_page(strip=True, strip_keys=None, y_strip=900):
    d = fitz.open()
    pg = d.new_page(width=1728, height=1152)
    # enlarged plan: tags scattered at their fixtures
    for k, x, y in (("TT", 200, 300), ("TT", 420, 310), ("GB18", 260, 260),
                    ("GB18", 470, 262), ("SD", 330, 420), ("MG1", 520, 430)):
        pg.insert_text((x, y), k, fontsize=9)
    pg.insert_text((200, 620), "ENLARGED TOILET PLAN", fontsize=12)
    pg.insert_text((200, 638), 'SCALE: 1/4" = 1\'-0"', fontsize=8)
    if strip:
        # a strip of every key on one baseline, each with its description
        # under it (a mounting-height elevation / key legend), no title
        for i, k in enumerate(strip_keys or ACC):
            x = 800 + 110 * i
            pg.insert_text((x, y_strip), k, fontsize=9)
            pg.insert_text((x - 10, y_strip + 20), "DISPENSER", fontsize=6)
    return d, pg


def _count(pg, keys):
    from app import schedules
    info = schedules.sheet_info(pg)
    ex = schedules.plan_exclusions(info)
    c = schedules.count_tags(info, _keys(keys), "accessories", ex)
    return {k: len(v) for k, v in c["main"].items()}, c


def test_a_row_of_most_schedule_keys_on_one_baseline_is_a_key_strip():
    d, pg = _acc_page()
    n, c = _count(pg, ACC)
    assert n == {"TT": 2, "GB18": 2, "SD": 1, "MG1": 1}, n
    assert c.get("strips") == 1, c.get("strips")


def test_without_the_strip_the_plan_count_is_unchanged():
    d, pg = _acc_page(strip=False)
    n, _ = _count(pg, ACC)
    assert n == {"TT": 2, "GB18": 2, "SD": 1, "MG1": 1}, n


def test_a_few_different_tags_lined_up_along_a_wall_still_count():
    # three distinct tags on one baseline (a toilet wall) out of 8 keys:
    # not a strip
    d, pg = _acc_page(strip=True, strip_keys=["TT", "GB36", "GB42"])
    n, c = _count(pg, ACC)
    assert n == {"TT": 3, "GB18": 2, "SD": 1, "MG1": 1, "GB36": 1,
                 "GB42": 1}, n
    assert not c.get("strips")


def test_a_row_with_a_key_twice_is_tags_not_a_legend():
    # the same key twice in the row: real tags in a line (e.g. a row of
    # identical fixtures with others), not a one-of-each key legend
    ks = ["TT", "SDU", "TT", "MG1", "SD", "GB36", "GB42"]
    d, pg = _acc_page(strip=True, strip_keys=ks)
    n, c = _count(pg, ACC)
    assert n["TT"] == 4 and n["SDU"] == 1, n
    assert not c.get("strips")


def test_four_of_many_door_keys_in_a_row_are_still_tags():
    # a big schedule (20 keys): four aligned tags are far from half of it
    keys = [f"D{i}" for i in range(1, 21)]
    d = fitz.open()
    pg = d.new_page(width=1728, height=1152)
    for i, k in enumerate(keys[:4]):
        pg.insert_text((300 + 150 * i, 400), k, fontsize=9)
    from app import schedules
    info = schedules.sheet_info(pg)
    ex = schedules.plan_exclusions(info)
    c = schedules.count_tags(info, _keys(keys), "equipment", ex)
    assert sum(len(v) for v in c["main"].values()) == 4


# ---------------------------------------------------------------- B finish
def _fin_table(cols, rows, key="NUMBER"):
    return {"kind": "finish", "confident": True, "key": key, "page": 0,
            "columns": cols, "rows": [dict(zip(cols, r)) for r in rows]}


def test_a_legend_glued_beside_the_finish_schedule_does_not_take_the_ceiling():
    from app import aitakeoff as ait
    cols = ["ACT", "ACOUSTICAL CEILING TILE", "PTB", "PORCELAIN TILE BASE",
            "NUMBER", "NAME", "FLOOR FINISH", "BASE", "WALL FINISH",
            "CEILING FINISH", "HEIGHT"]
    rows = [["ACB:", "ACOUSTICAL CEILING BAFFLE", "PTF:", "PORCELAIN TILE "
             "FLOORING", "100", "LOBBY", "LVT-1", "RB-1", "PT", "ACT-1",
             "9'-0\""],
            ["CPT:", "CARPET", "RN:", "RUBBER NOSING", "101", "OFFICE",
             "CPT-1", "RB-2", "PT", "GB", "10'-0\""]]
    out, bad = ait.finish_rows([_fin_table(cols, rows)])
    assert not bad
    assert [(r["room"], r["ceiling"], r["base"], r["floor"]) for r in out] \
        == [("100", "ACT-1", "RB-1", "LVT-1"), ("101", "GB", "RB-2", "CPT-1")]


def test_a_single_descriptive_ceiling_header_is_still_the_ceiling():
    from app import aitakeoff as ait
    cols = ["ROOM", "NAME", "FLOOR", "BASE", "WALLS", "ACOUSTIC CEILING TILE"]
    rows = [["100", "LOBBY", "LVT-1", "RB-1", "PT", "ACT-1"]]
    out, _ = ait.finish_rows([_fin_table(cols, rows, key="ROOM")])
    assert out[0]["ceiling"] == "ACT-1"


# ---------------------------------------------------------------- C roof
import math  # noqa: E402

APPU = 72 / 8.0          # 1/8" = 1'-0": 9 pt per foot


def _poly(pg, pts, width=0.5, closed=True):
    sh = pg.new_shape()
    sh.draw_polyline(pts)
    sh.finish(width=width, color=(0, 0, 0), closePath=closed)
    sh.commit()


def _roof_page():
    d = fitz.open()
    return d, d.new_page(width=1728, height=1152)


def test_gable_roof_splits_its_edge_into_eaves_and_rakes():
    from app import envelope as ev
    d, pg = _roof_page()
    x0, y0, W, D = 200, 200, 60 * APPU, 30 * APPU
    _poly(pg, [(x0, y0), (x0 + W, y0), (x0 + W, y0 + D), (x0, y0 + D)], 1.0)
    _poly(pg, [(x0, y0 + D / 2), (x0 + W, y0 + D / 2)], 1.0, closed=False)
    pg.insert_text((x0 + W / 3, y0 + D / 2 - 3), "RIDGE", fontsize=7)
    pg.insert_text((x0 + W / 2, y0 + D / 4), "6:12", fontsize=7)
    pg.insert_text((x0 + W / 2, y0 + 3 * D / 4), "6:12", fontsize=7)
    r = ev.roof_takeoff(pg, APPU, "ft")
    assert r["eave_lf"] == pytest.approx(120, rel=0.03)
    assert r["rake_lf"] == pytest.approx(60, rel=0.03)


def test_hip_roof_edge_is_all_eave():
    from app import envelope as ev
    d, pg = _roof_page()
    x0, y0, F = 200, 200, APPU
    A, B, C_, D_ = (x0, y0), (x0 + 60 * F, y0), (x0 + 60 * F, y0 + 30 * F), \
        (x0, y0 + 30 * F)
    R1, R2 = (x0 + 15 * F, y0 + 15 * F), (x0 + 45 * F, y0 + 15 * F)
    _poly(pg, [A, B, C_, D_], 1.0)
    for a, b in ((R1, R2), (A, R1), (D_, R1), (B, R2), (C_, R2)):
        _poly(pg, [a, b], 1.0, closed=False)
    for x, y in ((30, 6), (30, 25), (5, 15), (55, 15)):
        pg.insert_text((x0 + x * F, y0 + y * F), "6:12", fontsize=6)
    r = ev.roof_takeoff(pg, APPU, "ft")
    assert r["edge_lf"] == pytest.approx(180, rel=0.03)
    assert r["eave_lf"] == pytest.approx(180, rel=0.03)
    assert r["rake_lf"] == pytest.approx(0, abs=1)


def test_downspouts_are_the_DS_tags_on_the_roof_plan():
    from app import envelope as ev
    d, pg = _roof_page()
    x0, y0, W, D = 200, 200, 60 * APPU, 30 * APPU
    _poly(pg, [(x0, y0), (x0 + W, y0), (x0 + W, y0 + D), (x0, y0 + D)], 1.0)
    _poly(pg, [(x0, y0 + D / 2), (x0 + W, y0 + D / 2)], 1.0, closed=False)
    pg.insert_text((x0 + W / 2, y0 + D / 4), "6:12", fontsize=7)
    pg.insert_text((x0 + W / 2, y0 + 3 * D / 4), "6:12", fontsize=7)
    for x, y in ((x0 - 20, y0 - 8), (x0 + W + 6, y0 - 8),
                 (x0 + W + 6, y0 + D + 12)):
        pg.insert_text((x, y), "DS", fontsize=7)
    pg.insert_text((1300, 900), "DS DOWNSPOUT, SEE DETAIL 4/A-501", fontsize=7)
    r = ev.roof_takeoff(pg, APPU, "ft")
    assert r["downspouts"] == 3


def test_ai_takeoff_roof_plan_gives_gutter_line_and_downspouts():
    from app import aitakeoff as ait
    d, pg = _roof_page()
    x0, y0, W, D = 200, 200, 60 * APPU, 30 * APPU
    _poly(pg, [(x0, y0), (x0 + W, y0), (x0 + W, y0 + D), (x0, y0 + D)], 1.0)
    _poly(pg, [(x0, y0 + D / 2), (x0 + W, y0 + D / 2)], 1.0, closed=False)
    pg.insert_text((x0 + W / 2, y0 + D / 4), "6:12", fontsize=7)
    pg.insert_text((x0 + W / 2, y0 + 3 * D / 4), "6:12", fontsize=7)
    for x, y in ((x0 - 20, y0 - 8), (x0 + W + 6, y0 - 8)):
        pg.insert_text((x, y), "DS", fontsize=7)
    rows = [{"page": 0, "number": "X-301", "title": "ROOF PLAN",
             "kind": "plan", "scale": ('1/8" = 1\'-0"', APPU, "ft")}]
    res = {"quantities": [], "review": [], "problems": []}
    ait._stage3(d, rows, res)
    q = {x["name"]: x for x in res["quantities"]}
    assert q["Roof eave (gutter line)"]["qty"] == pytest.approx(120, rel=0.03)
    assert q["Roof eave (gutter line)"]["unit"] == "LF"
    assert q["Downspouts"]["qty"] == 2 and q["Downspouts"]["unit"] == "EA"


# ------------------------------------------------- D tags inside fixtures
def _circle(pg, c, r, w=0.6):
    sh = pg.new_shape()
    sh.draw_circle(c, r)
    sh.finish(color=(0, 0, 0), width=w)
    sh.commit()


def _light_page(n_fixtures=8, grid=True, beside=0):
    d = fitz.open()
    pg = d.new_page(width=1728, height=1152)
    if grid:
        # grid bubbles A and B at both ends of their grid lines
        for lab, x in (("A", 300), ("B", 700)):
            for y, y2 in ((100, 900), (1000, 200)):
                _circle(pg, (x, y), 16)
                sh = pg.new_shape()
                sh.draw_line((x, y + (16 if y < y2 else -16)), (x, y2))
                sh.finish(color=(0, 0, 0), width=0.4)
                sh.commit()
                pg.insert_text((x - 3.5, y + 3.5), lab, fontsize=10)
    # downlights: a circle with its type letter in it
    for i in range(n_fixtures):
        x, y = 360 + 80 * i, 500
        _circle(pg, (x, y), 16)
        pg.insert_text((x - 3, y + 3), "A", fontsize=9)
    if beside:
        # a reflected ceiling plan: a 2 ft ceiling grid drawn as short
        # pieces, small downlight circles with the type letter beside them
        sh = pg.new_shape()
        for gx in range(900, 1500, 18):
            for gy in range(600, 1000, 18):
                sh.draw_line((gx, gy), (gx + 18, gy))
                sh.draw_line((gx, gy), (gx, gy + 18))
        sh.finish(color=(0.5, 0.5, 0.5), width=0.25)
        sh.commit()
        for i in range(beside):
            x, y = 927 + 72 * (i % 7), 627 + 72 * (i // 7)
            _circle(pg, (x, y), 4)
            pg.insert_text((x + 5, y + 13), "A", fontsize=9)
    return d, pg


def _light_counts(pg):
    from app import schedules
    info = schedules.sheet_info(pg)
    ex = schedules.plan_exclusions(info)
    c = schedules.count_tags(info, {"A": "A", "B": "B"}, "light fixtures",
                             ex)
    return {k: len(v) for k, v in c["main"].items()}


def test_fixture_letters_beside_small_circles_in_a_ceiling_grid_count():
    d, pg = _light_page(n_fixtures=0, beside=10)
    assert _light_counts(pg) == {"A": 10}


def test_fixture_letters_on_a_stippled_floor_hatch_count():
    import random
    d, pg = _light_page(n_fixtures=0, beside=4)
    rnd = random.Random(3)
    sh = pg.new_shape()
    for _ in range(4000):                 # concrete stipple: 1 pt dashes
        x, y = rnd.uniform(900, 1200), rnd.uniform(600, 720)
        a = rnd.uniform(0, 3.14)
        sh.draw_line((x, y), (x + math.cos(a), y + math.sin(a)))
    sh.finish(color=(0.6, 0.6, 0.6), width=0.2)
    sh.commit()
    assert _light_counts(pg) == {"A": 4}


def test_small_subscript_letters_beside_switches_are_not_fixture_tags():
    d, pg = _light_page(n_fixtures=0, beside=10)
    for i in range(3):                    # dimmer switches: a small letter
        _circle(pg, (400 + 60 * i, 300), 2)  # by the switch symbol
        pg.insert_text((404 + 60 * i, 296), "A", fontsize=5.5)
    assert _light_counts(pg) == {"A": 10}


def test_sheet_border_zone_letters_are_not_fixture_tags():
    d, pg = _light_page(n_fixtures=0, beside=10)
    for y in (200, 500, 800):             # zone letters A.. in the margin
        pg.insert_text((40, y), "A", fontsize=14)
    assert _light_counts(pg) == {"A": 10}


def test_one_size_of_tags_is_counted_whatever_the_size():
    d, pg = _light_page(n_fixtures=0, beside=3)
    assert _light_counts(pg) == {"A": 3}


def test_grid_bubbles_alone_are_still_skipped():
    d, pg = _light_page(n_fixtures=0)
    assert _light_counts(pg) == {}


def test_a_few_circled_letters_without_grid_lines_are_still_bubbles():
    d, pg = _light_page(n_fixtures=3, grid=False)
    assert _light_counts(pg) == {}


# ---- E: light fixtures are counted on the lighting plans
def _rows(*titles):
    return [{"page": i, "number": f"E-{i}", "title": t, "kind": "plan",
             "discipline": "electrical"} for i, t in enumerate(titles)]


def test_light_fixtures_are_counted_on_lighting_plans_not_power_plans():
    from app import schedules
    rs = _rows("LIGHTING PLAN", "POWER AND SIGNAL PLAN", "FIRE ALARM PLAN")
    got = schedules.fixture_plans("light fixtures", rs)
    assert [r["title"] for r in got] == ["LIGHTING PLAN"]


def test_without_a_lighting_plan_every_electrical_plan_is_used():
    from app import schedules
    rs = _rows("ELECTRICAL PLAN", "POWER PLAN")
    assert schedules.fixture_plans("light fixtures", rs) == rs


def test_other_schedules_keep_every_plan():
    from app import schedules
    rs = _rows("LIGHTING PLAN", "POWER AND SIGNAL PLAN")
    assert schedules.fixture_plans("equipment", rs) == rs


def test_fixture_letters_anywhere_on_a_ceiling_grid_count():
    # a fine ceiling grid: the letter can land anywhere in a square, so
    # grid pieces sit round it in all four quarters - but only across and
    # up, never along the diagonals as a drawn circle does
    d, pg = _light_page(n_fixtures=0, beside=0)
    sh = pg.new_shape()
    for gx in range(900, 1350, 6):
        for gy in range(600, 1000, 6):
            sh.draw_line((gx, gy), (gx + 6, gy))
            sh.draw_line((gx, gy), (gx, gy + 6))
    sh.finish(color=(0.5, 0.5, 0.5), width=0.25)
    sh.commit()
    n = 0
    for i in range(6):
        for j in range(4):
            x, y = 930 + 66 * i, 640 + 80 * j
            _circle(pg, (x, y), 4)
            ox, oy = (i * 1.3) % 6, (j * 2.1 + i * 0.7) % 6
            pg.insert_text((x + 8 + ox, y + 10 + oy), "A", fontsize=9)
            n += 1
    assert _light_counts(pg) == {"A": n}


def test_a_circuit_arc_by_a_letter_on_a_ceiling_grid_is_not_a_bubble():
    d, pg = _light_page(n_fixtures=0, beside=6)
    sh = pg.new_shape()
    for i in range(6):                    # homerun arcs swinging past
        x, y = 927 + 72 * i, 627
        sh.draw_curve((x + 2, y + 20), (x + 20, y + 30), (x + 34, y + 12))
    sh.finish(color=(0, 0, 0), width=0.4)
    sh.commit()
    assert _light_counts(pg) == {"A": 6}


def test_a_section_marker_letter_over_its_sheet_number_is_not_a_tag():
    d, pg = _light_page(n_fixtures=0, grid=False, beside=0)
    for i in range(3):
        x, y = 400 + 120 * i, 400
        _circle(pg, (x, y), 18)
        sh = pg.new_shape()
        sh.draw_line((x - 18, y), (x + 18, y))      # split circle
        sh.finish(color=(0, 0, 0), width=0.5)
        sh.commit()
        pg.insert_text((x - 4, y - 4), "A", fontsize=12)
        pg.insert_text((x - 12, y + 13), "A-401", fontsize=8)
    assert _light_counts(pg) == {}


# ---- H: a schedule row keyed by a sheet number is a cross-reference
def test_a_schedule_row_keyed_by_a_sheet_number_is_not_a_type():
    from app import schedules
    t = {"rows": [{"MARK": "A", "DESC": "FIXED"},
                  {"MARK": "Q-901", "DESC": "STOREFRONT ELEVATIONS"}],
         "key": "MARK", "desc": "DESC", "qty": None, "kind": "window",
         "title": "WINDOW SCHEDULE", "why": "", "confident": True,
         "csi": "08 50 00", "page": 3, "sheet": "Q-601"}
    by_page = {0: {"page": 0, "number": "Q-101"},
               3: {"page": 3, "number": "Q-601"},
               9: {"page": 9, "number": "Q-901"}}
    hit = {"rect": (0, 0, 1, 1), "n": 1}

    def counts_on(pr, keys, kind):           # 4 window tags, and 2
        return {"main": {"A": [hit] * 4,     # callouts naming the sheet
                         "Q-901": [hit] * 2} if "Q-901" in keys
                else {"A": [hit] * 4}, "other": []}
    res = {"lines": [], "review": []}
    schedules._keyed(t, [{"page": 0, "title": "FLOOR PLAN"}], counts_on,
                     res, lambda p: by_page[p]["number"], by_page)
    assert [(ln["key"], ln["qty"]) for ln in res["lines"]] == [("A", 4)]


# ---- I: collinear lines merge only where they touch
def test_collinear_faces_with_a_gap_stay_two_pieces_whatever_the_float_noise():
    from app import autowalls
    d = fitz.open()
    pg = d.new_page(width=1224, height=792)
    # one 20" duct (30 pt apart at 1/4" = 1'-0") drawn in two stretches with
    # an 8 ft gap (equipment) between; the lower stretch's faces sit a
    # hair (6e-5 pt) to the side of the upper ones, as CAD output does
    x0, x1, e = 300.0, 330.0, 6e-5
    segs = [(x0, 100.0, x0, 290.0), (x1, 290.0, x1, 100.0),
            (x1 + e, 434.0, x1 + e, 473.0), (x0 + e, 473.0, x0 + e, 434.0)]
    ws = autowalls.walls(pg, 18.0, "ft", min_t=19.0, max_t=21.0, segs=segs)
    got = sorted(round(w["length"], 1) for w in ws)
    assert got == [2.2, 10.6]
