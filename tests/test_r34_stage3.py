"""r34 stage 3: envelope, roof (scaled roof plans only), site, earthwork and
landscape takeoff - synthetic sheets only."""
import math

import fitz
import pytest

PPU = 3.6                      # 1" = 20' on a 72 pt/in sheet (site)
APPU = 18.0                    # 1/4" = 1'-0" (building)


def _page(w=1728, h=1152):
    d = fitz.open()
    return d, d.new_page(width=w, height=h)


def _poly(pg, pts, width=0.5, closed=True, dashes=None, color=(0, 0, 0)):
    sh = pg.new_shape()
    sh.draw_polyline(pts)
    sh.finish(width=width, color=color, dashes=dashes, closePath=closed)
    sh.commit()


# ------------------------------------------------------------ landscape
def _plant_schedule(pg, x=900, y=200):
    rows = [("Ab", "Acer buergerianum", "4"), ("Cv", "Chionanthus", "2"),
            ("DxVJ", "Distylium", "47"), ("SEED", "Bermuda seed", "1,200 SF")]
    pg.insert_text((x, y - 30), "PLANT SCHEDULE", fontsize=10)
    for t, dx in (("SYMBOL", 0), ("CODE", 60), ("BOTANICAL NAME", 120),
                  ("QTY", 400)):
        pg.insert_text((x + dx, y), t, fontsize=8)
    for i, (k, n, q) in enumerate(rows):
        yy = y + 24 + 18 * i
        pg.insert_text((x + 60, yy), k, fontsize=8)
        pg.insert_text((x + 120, yy), n, fontsize=8)
        pg.insert_text((x + 400, yy), q, fontsize=8)


def test_plant_schedule_counts_and_seed_area():
    from app import sitework as sw
    d, pg = _page()
    _plant_schedule(pg)
    got = {r["key"]: (r["qty"], r["unit"]) for r in sw.plant_schedule(pg)}
    assert got == {"Ab": (4, "EA"), "Cv": (2, "EA"), "DxVJ": (47, "EA"),
                   "SEED": (1200, "SF")}


def test_no_plant_schedule_no_plants():
    from app import sitework as sw
    d, pg = _page()
    pg.insert_text((100, 100), "CODE  QTY", fontsize=8)
    assert sw.plant_schedule(pg) == []


# ------------------------------------------------------------ site
def test_paving_area_is_the_closed_shape_its_label_sits_in():
    from app import sitework as sw
    d, pg = _page()
    x0, y0 = 200, 200
    _poly(pg, [(x0, y0), (x0 + 40 * PPU, y0), (x0 + 40 * PPU, y0 + 20 * PPU),
               (x0, y0 + 20 * PPU)])
    _poly(pg, [(600, 600), (600 + 50 * PPU, 600), (600 + 50 * PPU,
               600 + 5 * PPU), (600, 600 + 5 * PPU)])
    pg.insert_text((x0 + 10, y0 + 30), "ASPHALT PAVEMENT", fontsize=6)
    pg.insert_text((605, 612), "CONC. SIDEWALK", fontsize=5)
    pg.insert_text((1300, 900), "ASPHALT PAVEMENT", fontsize=6)   # no shape
    got = sw.site_areas(pg, PPU, "ft")
    by = {}
    for a in got:
        by[a["kind"]] = by.get(a["kind"], 0) + a["area"]
    assert by["asphalt paving"] == pytest.approx(800, rel=0.02)
    assert by["concrete sidewalk"] == pytest.approx(250, rel=0.02)
    assert any(a.get("unclosed") for a in sw.site_areas(pg, PPU, "ft",
                                                        report_unclosed=True))


def test_a_leadered_multiline_label_takes_the_shape_its_leader_points_into():
    from app import sitework as sw
    d, pg = _page()
    x0, y0 = 400, 400
    _poly(pg, [(x0, y0), (x0 + 30 * PPU, y0), (x0 + 30 * PPU, y0 + 30 * PPU),
               (x0, y0 + 30 * PPU)])
    # a three-line note well outside the shape; its leader starts at the
    # first line and ends inside the shape
    pg.insert_text((150, 200), "HEAVY DUTY", fontsize=6)
    pg.insert_text((150, 208), "ASPHALT PAVEMENT", fontsize=6)
    pg.insert_text((150, 216), "SEE DETAIL 1/X-501", fontsize=6)
    _poly(pg, [(185, 202), (x0 + 40, y0 + 40)], closed=False, width=0.25)
    got = sw.site_areas(pg, PPU, "ft")
    assert [round(a["area"]) for a in got
            if a["kind"] == "asphalt paving"] == [900]


def test_a_shape_with_a_hairline_gap_in_its_outline_still_closes():
    from app import sitework as sw
    d, pg = _page()
    x0, y0 = 200, 200
    W, H = 40 * PPU, 20 * PPU
    _poly(pg, [(x0 + 0.6, y0), (x0 + W, y0), (x0 + W, y0 + H), (x0, y0 + H),
               (x0, y0 + 0.4)], closed=False)
    pg.insert_text((x0 + 10, y0 + 30), "ASPHALT PAVEMENT", fontsize=6)
    got = sw.site_areas(pg, PPU, "ft")
    assert sum(a["area"] for a in got) == pytest.approx(800, rel=0.03)


def test_paving_drawn_as_a_shaded_region_takes_the_region_area():
    from app import sitework as sw
    d, pg = _page()
    x0, y0 = 400, 300
    sh = pg.new_shape()             # grey fill, no outline, an L shape
    sh.draw_polyline([(x0, y0), (x0 + 40 * PPU, y0), (x0 + 40 * PPU,
                      y0 + 20 * PPU), (x0 + 20 * PPU, y0 + 20 * PPU),
                      (x0 + 20 * PPU, y0 + 40 * PPU), (x0, y0 + 40 * PPU)])
    sh.finish(color=None, fill=(0.8, 0.8, 0.8), closePath=True)
    sh.commit()
    for k in range(1, 12):          # hatching across it
        _poly(pg, [(x0, y0 + k * 12), (x0 + 12 * k, y0)], closed=False,
              width=0.2)
    pg.insert_text((150, 200), "ASPHALT PAVEMENT", fontsize=6)
    _poly(pg, [(170, 202), (x0 + 20, y0 + 100)], closed=False, width=0.25)
    got = [a for a in sw.site_areas(pg, PPU, "ft")
           if a["kind"] == "asphalt paving"]
    assert len(got) == 1
    assert got[0]["area"] == pytest.approx(40 * 20 + 20 * 20, rel=0.02)


def test_a_shaded_region_exported_as_strips_is_one_region():
    from app import sitework as sw
    d, pg = _page()
    x0, y0, W, H = 400, 300, 30 * PPU, 20 * PPU
    x = x0
    while x < x0 + W - 1e-6:        # CAD solid fill exported as 2 pt strips
        sh = pg.new_shape()
        x1 = min(x + 2.0, x0 + W)
        sh.draw_polyline([(x, y0), (x1, y0), (x1, y0 + H), (x, y0 + H)])
        sh.finish(color=None, fill=(0.86, 0.86, 0.86), closePath=True)
        sh.commit()
        x = x1
    sh = pg.new_shape()             # the leader's dot, black
    sh.draw_circle((x0 + 30, y0 + 30), 1.0)
    sh.finish(color=None, fill=(0, 0, 0))
    sh.commit()
    pg.insert_text((150, 200), "ASPHALT PAVEMENT", fontsize=6)
    _poly(pg, [(170, 202), (x0 + 30, y0 + 30)], closed=False, width=0.25)
    got = [a for a in sw.site_areas(pg, PPU, "ft")
           if a["kind"] == "asphalt paving"]
    assert [round(a["area"]) for a in got] == [600]


def test_a_leader_drawn_from_its_tip_to_the_label_works_the_same():
    from app import sitework as sw
    d, pg = _page()
    x0, y0 = 400, 400
    _poly(pg, [(x0, y0), (x0 + 30 * PPU, y0), (x0 + 30 * PPU, y0 + 30 * PPU),
               (x0, y0 + 30 * PPU)])
    pg.insert_text((150, 200), "ASPHALT PAVEMENT", fontsize=6)
    _poly(pg, [(x0 + 40, y0 + 40), (300, 300), (185, 202)], closed=False,
          width=0.25)
    got = sw.site_areas(pg, PPU, "ft")
    assert [round(a["area"]) for a in got] == [900]


def test_a_curved_outline_of_many_short_pieces_still_bounds_the_area():
    from app import sitework as sw
    d, pg = _page()
    cx, cy, r = 500, 500, 15 * PPU
    n = 400                          # an arc exported as 400 short lines
    pts = [(cx + r * math.cos(2 * math.pi * i / n),
            cy + r * math.sin(2 * math.pi * i / n)) for i in range(n)]
    for a, b in zip(pts, pts[1:] + pts[:1]):
        _poly(pg, [a, b], closed=False)
    for k in range(-5, 6):           # and a hatch pen crossing it
        _poly(pg, [(cx - r + 3, cy + k * 8), (cx + r - 3, cy + k * 8 + 4)],
              closed=False, width=0.2)
    pg.insert_text((cx - 20, cy - 10), "ASPHALT PAVEMENT", fontsize=5)
    got = sw.site_areas(pg, PPU, "ft")
    assert sum(a["area"] for a in got) == pytest.approx(math.pi * 15 ** 2,
                                                        rel=0.03)


def test_a_leader_ending_in_a_speck_is_not_an_area():
    from app import sitework as sw
    d, pg = _page()
    x0, y0 = 400, 400
    _poly(pg, [(x0, y0), (x0 + 3 * PPU, y0), (x0 + 3 * PPU, y0 + 3 * PPU),
               (x0, y0 + 3 * PPU)])          # a 3 ft box: a symbol
    pg.insert_text((150, 200), "INSTALL SEED", fontsize=6)
    _poly(pg, [(170, 202), (x0 + 5, y0 + 5)], closed=False, width=0.25)
    got = sw.site_areas(pg, PPU, "ft", report_unclosed=True)
    assert [a["area"] for a in got] == [None]


def test_curb_length_follows_the_line_its_label_names():
    from app import sitework as sw
    d, pg = _page()
    pts = [(200, 500), (200 + 60 * PPU, 500), (200 + 60 * PPU, 500 + 40 * PPU)]
    _poly(pg, pts, closed=False, width=0.7)
    _poly(pg, [(200, 700), (900, 700)], closed=False, width=0.3)  # other pen
    pg.insert_text((260, 496), "CURB & GUTTER", fontsize=6)
    got = sw.curb_lengths(pg, PPU, "ft")
    assert sum(c["length"] for c in got) == pytest.approx(100, rel=0.03)


# ------------------------------------------------------------ earthwork
def _contours(pg, levels, x_of, y0, y1, dashes, lab=True, at=0.5):
    for z in levels:
        x = x_of(z)
        _poly(pg, [(x, y0), (x, y1)], closed=False, width=0.4, dashes=dashes)
        if lab:
            pg.insert_text((x + 1, y0 + (y1 - y0) * at), f"{z}", fontsize=6,
                           rotate=90)


def test_cut_and_fill_from_existing_and_proposed_contours():
    from app import sitework as sw
    d, pg = _page()
    X0, Y0, Y1 = 200, 200, 200 + 100 * PPU
    # existing ground rises 1 ft per 25 ft (dashed); proposed 1 ft per 50 ft
    _contours(pg, [100, 101, 102, 103, 104], lambda z: X0 + (z - 100) * 25 *
              PPU, Y0, Y1, "[6 3] 0", at=0.2)
    _contours(pg, [101, 102, 103], lambda z: X0 + 7 + (z - 101) * 50 * PPU,
              Y0, Y1, None, at=0.8)
    r = sw.earthwork(pg, PPU, "ft")
    assert r["rfi"] is None
    assert r["cut_cy"] == pytest.approx(92.6, rel=0.2)
    assert r["fill_cy"] == pytest.approx(92.6, rel=0.2)


def test_earthwork_without_two_contour_sets_is_an_rfi():
    from app import sitework as sw
    d, pg = _page()
    _contours(pg, [100, 101, 102], lambda z: 200 + (z - 100) * 90, 200, 500,
              "[6 3] 0")
    r = sw.earthwork(pg, PPU, "ft")
    assert r["cut_cy"] is None and r["rfi"]


def test_topsoil_strip_from_the_notes():
    from app import sitework as sw
    assert sw.strip_depth_in("CONTRACTOR SHALL STRIP 6\" OF TOPSOIL") == 6
    assert sw.strip_depth_in("REMOVE AND STOCKPILE TOPSOIL (4 INCHES)") == 4
    assert sw.strip_depth_in("GRADING NOTES") is None


# ------------------------------------------------------------ roof
def _roof(pg, w_ft=60, d_ft=30, pitch="6:12", x0=200, y0=200):
    W, D = w_ft * APPU, d_ft * APPU
    _poly(pg, [(x0, y0), (x0 + W, y0), (x0 + W, y0 + D), (x0, y0 + D)],
          width=1.0)
    for k in range(1, int(w_ft)):                          # standing seams
        _poly(pg, [(x0 + k * APPU, y0), (x0 + k * APPU, y0 + D)],
              closed=False, width=0.2)
    _poly(pg, [(x0, y0 + D / 2), (x0 + W, y0 + D / 2)], closed=False,
          width=1.0)
    pg.insert_text((x0 + W / 3, y0 + D / 2 - 3), "RIDGE", fontsize=7)
    pg.insert_text((x0 + W / 2, y0 + D / 4), pitch, fontsize=7)
    pg.insert_text((x0 + W / 2, y0 + 3 * D / 4), pitch, fontsize=7)
    return W, D


def test_roof_area_by_pitch_from_a_scaled_roof_plan():
    from app import envelope as ev
    d, pg = _page()
    _roof(pg)
    r = ev.roof_takeoff(pg, APPU, "ft")
    assert r["plan_sf"] == pytest.approx(1800, rel=0.03)
    by = {p["pitch"]: p["sloped_sf"] for p in r["by_pitch"]}
    assert by[6.0] == pytest.approx(1800 * math.sqrt(1 + 0.25), rel=0.03)
    assert r["edge_lf"] == pytest.approx(180, rel=0.03)
    assert r["ridge_lf"] == pytest.approx(60, rel=0.03)


def test_a_ridge_drawn_as_a_thin_cap_band_counts_once():
    from app import envelope as ev
    d, pg = _page()
    x0, y0, W, D = 200, 200, 60 * APPU, 30 * APPU
    _poly(pg, [(x0, y0), (x0 + W, y0), (x0 + W, y0 + D), (x0, y0 + D)],
          width=1.0)
    for o in (-3, -1, 1, 3):                 # ridge cap: four thin lines
        _poly(pg, [(x0, y0 + D / 2 + o), (x0 + W, y0 + D / 2 + o)],
              closed=False, width=0.25)
    pg.insert_text((x0 + W / 3, y0 + D / 2 - 6), "RIDGE", fontsize=7)
    pg.insert_text((x0 + W / 2, y0 + D / 4), "6:12", fontsize=7)
    r = ev.roof_takeoff(pg, APPU, "ft")
    assert r["ridge_lf"] == pytest.approx(60, rel=0.03)


def test_roof_needs_a_scale():
    from app import envelope as ev
    d, pg = _page()
    _roof(pg)
    with pytest.raises(ValueError):
        ev.roof_takeoff(pg, None, "ft")


def test_roof_area_split_between_two_pitches():
    from app import envelope as ev
    d, pg = _page()
    x0, y0 = 200, 200
    _poly(pg, [(x0, y0), (x0 + 40 * APPU, y0), (x0 + 40 * APPU,
               y0 + 20 * APPU), (x0, y0 + 20 * APPU)], width=1.0)
    _poly(pg, [(x0 + 20 * APPU, y0), (x0 + 20 * APPU, y0 + 20 * APPU)],
          closed=False, width=1.0)
    pg.insert_text((x0 + 8 * APPU, y0 + 10 * APPU), "4:12", fontsize=7)
    pg.insert_text((x0 + 28 * APPU, y0 + 10 * APPU), "8:12", fontsize=7)
    r = ev.roof_takeoff(pg, APPU, "ft")
    by = {p["pitch"]: p["plan_sf"] for p in r["by_pitch"]}
    assert by[4.0] == pytest.approx(400, rel=0.06)
    assert by[8.0] == pytest.approx(400, rel=0.06)


# ------------------------------------------------------------ envelope
def test_wall_envelope_deducts_openings_and_carries_layers_from_the_notes():
    from app import envelope as ev
    r = ev.wall_envelope(200.0, 10.0, [(3.0, 7.0)] * 4,
                         notes="2\" RIGID INSULATION ... FLUID APPLIED AIR "
                               "BARRIER", system="Exterior wall")
    assert r["gross_sf"] == pytest.approx(2000)
    assert r["openings_sf"] == pytest.approx(84)
    assert r["net_sf"] == pytest.approx(1916)
    names = {l["name"]: l["qty"] for l in r["lines"]}
    assert names["Exterior wall - net wall area"] == pytest.approx(1916)
    assert names["Exterior wall - insulation"] == pytest.approx(1916)
    assert names["Exterior wall - air/vapor barrier"] == pytest.approx(1916)


def test_wall_envelope_without_layer_notes_has_no_layer_lines():
    from app import envelope as ev
    r = ev.wall_envelope(100.0, 10.0, [], notes="", system="Exterior wall")
    assert [l["name"] for l in r["lines"]] == ["Exterior wall - net wall area"]
    assert r["confidence"] < 0.6              # openings unknown -> review


def test_wall_height_from_level_marks():
    from app import envelope as ev
    d, pg = _page()
    pg.insert_text((100, 300), "FIN. FLOOR", fontsize=7)
    pg.insert_text((100, 310), "0'-0\"", fontsize=7)
    pg.insert_text((100, 120), "T.O. PLATE", fontsize=7)
    pg.insert_text((100, 130), "10'-8\"", fontsize=7)
    assert ev.wall_height_from_levels([pg]) == pytest.approx(10 + 8 / 12)


def test_roof_bearing_marks_give_the_wall_height_and_the_lowest_one_wins():
    from app import envelope as ev
    d, pg = _page()
    for x in (100, 700):
        pg.insert_text((x, 100), "DORMER ROOF BEARING", fontsize=7)
        pg.insert_text((x, 110), "15'-0\"", fontsize=7)
        pg.insert_text((x, 200), "MAIN ROOF BEARING", fontsize=7)
        pg.insert_text((x, 210), "10'-8\"", fontsize=7)
        pg.insert_text((x, 400), "FINISHED FLOOR", fontsize=7)
        pg.insert_text((x, 410), "0'-0\"", fontsize=7)
    assert ev.wall_height_from_levels([pg]) == pytest.approx(10 + 8 / 12)
    assert ev.wall_heights_from_levels([pg]) == pytest.approx(
        [10 + 8 / 12, 15.0])


# ------------------------------------------------------------ AI Takeoff
def test_ai_lines_are_labelled_ai_derived_with_confidence_and_low_ones_go_to_review():
    from app import aitakeoff as ait
    res = {"quantities": [], "review": [], "problems": []}
    ait._ai_line(res, "site", "Asphalt paving", 800.0, "SF", 3, "X-101",
                 "32 12 16", "closed shape at the label", 0.8)
    ait._ai_line(res, "earthwork", "Cut", 92.0, "CY", 3, "X-201",
                 "31 23 16", "contours", 0.4)
    q = res["quantities"][0]
    assert q["ai_derived"] is True and q["confidence"] == 0.8
    assert "AI-derived" in q["basis"]
    assert res["review"][0]["name"] == "Cut" and \
        "confidence 0.40" in res["review"][0]["why"]


def test_roof_takeoff_reads_roof_plans_not_framing_or_detail_sheets():
    from app import aitakeoff as ait
    assert ait._roof_sheet("ROOF PLAN")
    assert ait._roof_sheet("OVERALL ROOF PLAN")
    assert not ait._roof_sheet("ROOF FRAMING PLAN")
    assert not ait._roof_sheet("ROOF DETAILS")
    assert not ait._roof_sheet("ROOF PLAN DETAILS")
