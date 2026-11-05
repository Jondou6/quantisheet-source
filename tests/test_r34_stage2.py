"""r34 stage 2: measured-quantity accuracy - each on a small synthetic
sheet (no real drawing data)."""
import math

import fitz
import pytest

from app import tradetakeoff as tt


def _hexagon(sh, cx, cy, r=7):
    pts = [(cx + r * math.cos(math.radians(a)), cy + r * math.sin(math.radians(a)))
           for a in range(0, 360, 60)]
    sh.draw_polyline(pts + [pts[0]])


EXPLODED = {"on": False}


def _bubble(pg, sh, cx, cy, num):
    if EXPLODED["on"]:
        # CAD exports often draw a hexagon as six separate lines
        pts = [(cx + 7 * math.cos(math.radians(a)),
                cy + 7 * math.sin(math.radians(a))) for a in range(0, 360, 60)]
        for a, b in zip(pts, pts[1:] + pts[:1]):
            sh.draw_line(a, b)
            sh.finish(width=0.5, color=(0, 0, 0))
    else:
        _hexagon(sh, cx, cy)
        sh.finish(width=0.5, color=(0, 0, 0))  # one path per bubble
    pg.insert_text((cx - 2.5, cy + 3), str(num), fontsize=8)


def _drop_sheet():
    d = fitz.open()
    pg = d.new_page(width=1728, height=1152)
    sh = pg.new_shape()
    # the notes list, top right
    pg.insert_text((1400, 100), "PIPING NOTES:", fontsize=10)
    notes = [(3, '1/2"CW DOWN'), (4, '1/2"CW & HW DOWN (FIELD ROUTE)'),
             (5, "VALVE IN CEILING SPACE"), (6, '1 1/2"CW UP TO HOSE BIBB'),
             (7, '2"V UP THRU ROOF')]
    for i, (n, txt) in enumerate(notes):
        y = 130 + 22 * i
        _bubble(pg, sh, 1410, y, n)
        pg.insert_text((1425, y + 3), txt, fontsize=8)
    # the plan: keynote bubbles at fixtures
    for (x, y), n in zip([(200, 300), (300, 300), (400, 300), (200, 500),
                          (300, 500), (500, 700), (600, 700), (700, 700)],
                         [3, 3, 3, 4, 4, 5, 6, 7]):
        _bubble(pg, sh, x, y, n)
    sh.finish(width=0.5, color=(0, 0, 0))
    sh.commit()
    # a bare 3 (a dimension) is not a keynote
    pg.insert_text((800, 800), "3", fontsize=8)
    return d, pg


@pytest.mark.parametrize("exploded", [False, True])
def test_drops_counted_from_down_and_up_keynotes(exploded, monkeypatch):
    monkeypatch.setitem(EXPLODED, "on", exploded)
    _d, pg = _drop_sheet()
    got = {g["name"]: g for g in tt.keynote_drops(pg)}
    assert set(got) == {'1/2" CW', '1/2" HW', '1-1/2" CW', '2" V'}
    assert got['1/2" CW']["drops"] == 5            # 3 x note 3 + 2 x note 4
    assert got['1/2" HW']["drops"] == 2
    assert got['1-1/2" CW']["drops"] == 1
    for nm in ('1/2" CW', '1/2" HW', '1-1/2" CW'):
        g = got[nm]
        assert g["length_ft"] == pytest.approx(g["drops"] * tt.DROP_FT_DEFAULT)
        assert "assum" in g["basis"].lower()
    # a vent / waste rise is not a supply drop: counted, no length guessed
    assert got['2" V']["drops"] == 1 and got['2" V']["length_ft"] is None
    assert "review" in got['2" V']["basis"].lower()


def test_drop_height_can_be_changed():
    _d, pg = _drop_sheet()
    got = {g["name"]: g for g in tt.keynote_drops(pg, drop_ft=4.5)}
    assert got['1/2" CW']["length_ft"] == pytest.approx(5 * 4.5)


def test_no_notes_list_no_drops():
    d = fitz.open()
    pg = d.new_page(width=1728, height=1152)
    sh = pg.new_shape()
    _bubble(pg, sh, 200, 300, 3)
    sh.finish(width=0.5)
    sh.commit()
    pg.insert_text((400, 300), '1/2"CW', fontsize=8)
    assert tt.keynote_drops(pg) == []


def test_ai_takeoff_lists_drops_as_assumed_quantities():
    from app import aitakeoff
    _d, pg = _drop_sheet()
    res = {"quantities": [], "review": [], "problems": []}
    aitakeoff._pipe_drops(pg, 0, "P-1", "ft", res)
    q = {x["name"]: x for x in res["quantities"]}
    assert q['1/2" CW drops']["qty"] == pytest.approx(5 * tt.DROP_FT_DEFAULT)
    assert q['1/2" CW drops']["unit"] == "LF"
    assert q['1/2" CW drops']["engine"] == "pipe drops"
    assert q['1/2" CW drops']["assumption"] is True
    assert "ASSUMED" in q['1/2" CW drops']["basis"]
    assert not any("V" in n.split()[1] for n in q)       # vents not guessed
    assert any(r["name"].startswith('2" V') for r in res["review"])
    assert any("assumed" in p.lower() for p in res["problems"])


def test_drop_height_setting_is_used(monkeypatch):
    from app import aitakeoff, settings
    real = settings.get
    monkeypatch.setattr(settings, "get", lambda k, d=None: 9.0
                        if k == "pipe_drop_ft" else real(k, d))
    _d, pg = _drop_sheet()
    res = {"quantities": [], "review": [], "problems": []}
    aitakeoff._pipe_drops(pg, 0, "P-1", "ft", res)
    q = {x["name"]: x for x in res["quantities"]}
    assert q['1/2" CW drops']["qty"] == pytest.approx(45.0)


# ---- 2: pipe drawn as two outlines at its true size is measured once ---------
def _double_line(sh, pts, off):
    """Two outlines `off` pt either side... drawn as an offset pair."""
    for sgn in (-0.5, 0.5):
        for a, b in zip(pts, pts[1:]):
            dx, dy = b[0] - a[0], b[1] - a[1]
            L = math.hypot(dx, dy)
            nx, ny = -dy / L * off * sgn, dx / L * off * sgn
            sh.draw_line((a[0] + nx, a[1] + ny), (b[0] + nx, b[1] + ny))


def test_double_line_pipe_measured_once_along_its_centre():
    d = fitz.open()
    pg = d.new_page(width=1728, height=1152)
    ppu = 18.0                                    # 1/4" = 1'-0"
    sh = pg.new_shape()
    # 4" waste: outlines 6 pt apart (4" at this scale), 40 ft + 10 ft
    h = 4 / 12 * ppu / 2                           # mitred corner, as CAD
    x1, y1 = 200 + 40 * ppu, 400 + 10 * ppu
    for o in (-h, h):
        sh.draw_polyline([(200, 400 + o), (x1 - o, 400 + o), (x1 - o, y1)])
    sh.finish(width=1.5, color=(0, 0, 0))
    sh.commit()
    pg.insert_text((400, 392), '4"W', fontsize=8)
    gs = {g["name"]: g["length"] for g in tt.mep_runs(pg, ppu, "ft")
          if g["labelled"]}
    assert '4" W' in gs, gs
    assert gs['4" W'] == pytest.approx(50.0, rel=0.05)


def test_wall_pair_beside_a_small_pipe_tag_is_not_a_pipe():
    d = fitz.open()
    pg = d.new_page(width=1728, height=1152)
    ppu = 18.0
    sh = pg.new_shape()
    _double_line(sh, [(200, 400), (200 + 40 * ppu, 400)], 6 / 12 * ppu)  # 6" wall
    sh.finish(width=1.5, color=(0, 0, 0))
    sh.commit()
    pg.insert_text((400, 392), '2"W', fontsize=8)
    gs = {g["name"]: g["length"] for g in tt.mep_runs(pg, ppu, "ft")
          if g["labelled"]}
    assert gs.get('2" W', 0) < 1.0, gs


def test_tag_prefers_the_double_line_pipe_of_its_size_over_a_nearer_thin_line():
    d = fitz.open()
    pg = d.new_page(width=1728, height=1152)
    ppu = 18.0
    sh = pg.new_shape()
    h = 3 / 12 * ppu / 2
    for o in (-h, h):
        sh.draw_line((200, 400 + o), (200 + 30 * ppu, 400 + o))
    sh.finish(width=1.5, color=(0, 0, 0))
    # a thin background line (a wall face) running right under the tag
    sh.draw_line((300, 386), (300 + 20 * ppu, 386))
    sh.finish(width=0.25, color=(0.4, 0.4, 0.4))
    sh.commit()
    pg.insert_text((400, 389), '3"W', fontsize=8)
    gs = {(g["name"], g["style_name"]): g["length"]
          for g in tt.mep_runs(pg, ppu, "ft") if g["labelled"]}
    assert gs.get(('3" W', "black, 1.5 pt"), 0) == pytest.approx(30.0, rel=0.05), gs


# ---------------------------------------------------------------- flex duct
def _flex(sh, pts, dia_pt, step):
    """A flex run-out as drawn: short cross-ticks of the duct's diameter
    along a curved centreline."""
    import math as _m
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        L = _m.hypot(x1 - x0, y1 - y0)
        n = max(int(L // step), 1)
        ux, uy = (x1 - x0) / L, (y1 - y0) / L
        for k in range(n):
            cx, cy = x0 + ux * step * k, y0 + uy * step * k
            sh.draw_line((cx - uy * dia_pt / 2, cy + ux * dia_pt / 2),
                         (cx + uy * dia_pt / 2, cy - ux * dia_pt / 2))


def _arc(c, r, a0, a1, n=24):
    import math as _m
    return [(c[0] + r * _m.cos(a0 + (a1 - a0) * k / n),
             c[1] + r * _m.sin(a0 + (a1 - a0) * k / n)) for k in range(n + 1)]


def test_flex_runouts_measured_along_their_curve_with_size_from_the_drawing():
    import math as _m
    d = fitz.open()
    pg = d.new_page(width=1728, height=1152)
    ppu = 18.0
    sh = pg.new_shape()
    _flex(sh, _arc((400, 400), 3 * ppu, 0, _m.pi / 2), 8 / 12 * ppu, 3.6)
    _flex(sh, [(900, 300), (900 + 5 * ppu, 300)], 6 / 12 * ppu, 2.7)
    sh.finish(width=1.25, color=(0, 0, 0))
    sh.commit()
    got = {f["name"]: f["length"] for f in tt.flex_runs(pg, ppu, "ft")}
    assert set(got) == {'8" round flex', '6" round flex'}, got
    assert got['8" round flex'] == pytest.approx(3 * _m.pi / 2, rel=0.08)
    assert got['6" round flex'] == pytest.approx(5.0, rel=0.08)


def test_hatching_and_treads_are_not_flex():
    d = fitz.open()
    pg = d.new_page(width=1728, height=1152)
    ppu = 18.0
    sh = pg.new_shape()
    for k in range(30):                  # 45-degree wall hatch
        x = 200 + 4 * k
        sh.draw_line((x, 400), (x + 8, 408))
    for k in range(12):                  # stair treads, 11" apart, 4' wide
        y = 600 + k * 11 / 12 * ppu
        sh.draw_line((900, y), (900 + 4 * ppu, y))
    for k in range(12):                  # widely spaced short ticks
        sh.draw_line((300 + 9 * k, 800), (300 + 9 * k, 812))
    sh.finish(width=0.5, color=(0, 0, 0))
    sh.commit()
    assert tt.flex_runs(pg, ppu, "ft") == []


def test_ai_takeoff_takes_off_flex_runouts_as_measured_size_lines():
    import math as _m
    from app import aitakeoff
    d = fitz.open()
    pg = d.new_page(width=1728, height=1152)
    ppu = 18.0
    sh = pg.new_shape()
    _flex(sh, _arc((400, 400), 3 * ppu, 0, _m.pi / 2), 8 / 12 * ppu, 3.6)
    sh.finish(width=1.25, color=(0, 0, 0))
    sh.commit()
    res = {"marks": [], "review": [], "problems": [], "quantities": []}
    sheet = {}
    aitakeoff._ducts(d, 0, "X-101", ppu, "ft", res, sheet)
    tot = sum(m[2]["measure"]["value"] for m in res["marks"]
              if m[2]["measure"]["group"] == '8" round flex')
    assert tot == pytest.approx(3 * _m.pi / 2, rel=0.08)
    assert any("flex" in p and "size read from" in p for p in res["problems"])


# ---------------------------------------------------------------- civil
CIV_FT = 3.6                       # 1" = 20' on a 72 pt/in sheet


def _civ_line(pg, a, b, width=0.5, dashes=None):
    sh = pg.new_shape()
    sh.draw_line(a, b)
    sh.finish(width=width, color=(0, 0, 0), dashes=dashes)
    sh.commit()


def test_pipe_past_a_match_line_belongs_to_the_next_sheet():
    from app import civiltakeoff as ct
    d = fitz.open()
    pg = d.new_page(width=1200, height=800)
    _civ_line(pg, (100, 400), (1100, 400), width=0.25)          # the pipe
    _civ_line(pg, (100, 600), (900, 600), width=0.25)           # another
    _civ_line(pg, (900, 40), (900, 760), width=1.5, dashes="[12 4 2 4] 0")
    pg.insert_text((905, 700), "MATCH LINE SEE SHEET X-302", fontsize=9,
                   rotate=90)
    pg.insert_text((320, 397), '6" PVC SANITARY', fontsize=8)
    pg.insert_text((320, 597), '8" PVC SANITARY', fontsize=8)
    gs = {g["size"]: g["length"] for g in ct.pipe_systems(pg, CIV_FT, "ft")}
    assert gs[6] == pytest.approx(800 / CIV_FT, rel=0.03), gs
    assert gs[8] == pytest.approx(800 / CIV_FT, rel=0.03), gs


def test_no_match_line_no_clip():
    from app import civiltakeoff as ct
    d = fitz.open()
    pg = d.new_page(width=1200, height=800)
    _civ_line(pg, (100, 400), (1100, 400), width=0.25)
    _civ_line(pg, (900, 40), (900, 760), width=1.5)             # a long edge
    pg.insert_text((320, 397), '6" PVC SANITARY', fontsize=8)
    gs = {g["size"]: g["length"] for g in ct.pipe_systems(pg, CIV_FT, "ft")}
    assert gs[6] == pytest.approx(1000 / CIV_FT, rel=0.03), gs


def test_pipe_only_past_the_match_line_leaves_no_empty_group():
    from app import civiltakeoff as ct
    d = fitz.open()
    pg = d.new_page(width=1200, height=800)
    _civ_line(pg, (100, 400), (850, 400), width=0.25)
    _civ_line(pg, (950, 600), (1150, 600), width=0.25)
    _civ_line(pg, (900, 40), (900, 760), width=1.5)
    pg.insert_text((905, 700), "MATCH LINE SEE SHEET X-302", fontsize=9,
                   rotate=90)
    pg.insert_text((320, 397), '6" PVC SANITARY', fontsize=8)
    pg.insert_text((1000, 597), '8" PVC SANITARY', fontsize=8)
    gs = {g["size"]: g["length"] for g in ct.pipe_systems(pg, CIV_FT, "ft")}
    assert 8 not in gs and gs[6] == pytest.approx(750 / CIV_FT, rel=0.03), gs


def test_match_line_is_the_line_by_the_note_not_the_sheet_border():
    from app import civiltakeoff as ct
    d = fitz.open()
    pg = d.new_page(width=1200, height=800)
    _civ_line(pg, (100, 400), (1100, 400), width=0.25)
    _civ_line(pg, (900, 100), (900, 700), width=1.5)            # match line
    _civ_line(pg, (940, 20), (940, 780), width=1.5)             # border
    pg.insert_text((915, 600), "MATCH LINE SEE SHEET X-302", fontsize=9,
                   rotate=90)
    assert ct.match_lines(pg) == [("x", 900.0)]


def _band(pg, a, b, w, hatch=True, fill=None):
    """A large pipe drawn to scale: two edges w apart, hatched (or a filled
    strip with no edges)."""
    import math as _m
    L = _m.dist(a, b)
    ux, uy = (b[0] - a[0]) / L, (b[1] - a[1]) / L
    nx, ny = -uy * w / 2, ux * w / 2
    sh = pg.new_shape()
    if fill is not None:
        sh.draw_polyline([(a[0] + nx, a[1] + ny), (b[0] + nx, b[1] + ny),
                          (b[0] - nx, b[1] - ny), (a[0] - nx, a[1] - ny)])
        sh.finish(width=0, color=None, fill=fill, closePath=True)
        sh.commit()
        return
    for s in (1, -1):
        sh.draw_line((a[0] + s * nx, a[1] + s * ny),
                     (b[0] + s * nx, b[1] + s * ny))
    sh.finish(width=0.42, color=(0, 0, 0))
    if hatch:
        k = 0.0
        while k < L - w:
            p = (a[0] + ux * k, a[1] + uy * k)
            sh.draw_line((p[0] + nx, p[1] + ny),
                         (p[0] - nx + ux * w * 0.8, p[1] - ny + uy * w * 0.8))
            k += 1.5
        sh.finish(width=0.3, color=(0.3, 0.3, 0.3))
    sh.commit()


@pytest.mark.parametrize("kind", ["hatched", "filled"])
def test_large_pipe_drawn_as_a_band_is_measured_along_its_centre(kind):
    from app import civiltakeoff as ct
    d = fitz.open()
    pg = d.new_page(width=1200, height=800)
    w = 22 / 12 * CIV_FT                         # 18" RCP, OD to scale
    a, b, c = (200, 300), (200 + 30 * CIV_FT, 300), \
        (200 + 30 * CIV_FT, 300 + 19 * CIV_FT)
    for p, q in ((a, b), (b, c)):
        _band(pg, p, q, w, fill=(0.3, 0.3, 0.3) if kind == "filled"
              else None)
    pg.insert_text((240, 285), '49 LF-18" RCP', fontsize=8)
    gs = {g["size"]: g["length"] for g in ct.pipe_systems(pg, CIV_FT, "ft")}
    assert gs.get(18, 0) == pytest.approx(49.0, rel=0.06), gs


def test_curb_and_gutter_beside_a_pipe_label_is_not_a_band():
    """Two plain parallel edges a pipe's width apart, no fill or hatch
    (a curb and gutter), are not the pipe."""
    from app import civiltakeoff as ct
    d = fitz.open()
    pg = d.new_page(width=1200, height=800)
    w = 22 / 12 * CIV_FT
    _band(pg, (200, 300), (200 + 60 * CIV_FT, 300), w, hatch=False)
    _civ_line(pg, (200, 340), (200 + 20 * CIV_FT, 340), width=0.25)
    pg.insert_text((240, 336), '18" RCP', fontsize=8)
    gs = {g["size"]: g["length"] for g in ct.pipe_systems(pg, CIV_FT, "ft")}
    assert gs.get(18, 0) < 30, gs


# ---------------------------------------------------------------- gross area
def test_gross_floor_area_is_the_area_inside_the_outer_face_loop():
    from app import wall_roles as wr
    P = 10.0

    def W(x0, y0, x1, y1, th):
        return {"p0": (x0 * P, y0 * P), "p1": (x1 * P, y1 * P),
                "thickness": th, "length": ((x1 - x0) ** 2 +
                                            (y1 - y0) ** 2) ** 0.5}
    walls = [W(0, 0, 60, 0, 8), W(0, 40, 60, 40, 8), W(0, 0, 0, 40, 8),
             W(60, 0, 60, 19, 8), W(60, 23, 60, 40, 8),
             W(0, 18, 10, 18, 5), W(13, 18, 45, 18, 5), W(30, 0, 30, 18, 6)]
    ext = wr.exterior_outline(walls, P, "ft")
    assert ext["outer_face_lf"]
    face = 8 / 12
    assert ext["gross_area"] == pytest.approx((60 + face) * (40 + face),
                                              rel=0.02)


def test_ai_takeoff_gross_area_line():
    from app import aitakeoff
    q = aitakeoff._gross_area_line({"gross_area": 2467.0, "loops": 1},
                                   1.0, 3, "X-105", "ft")
    assert q["name"] == "Gross floor area" and q["unit"] == "SF"
    assert q["qty"] == pytest.approx(2467.0)
    assert "outer face" in q["basis"]
    assert aitakeoff._gross_area_line({"gross_area": None}, 1.0, 3,
                                      "X-105", "ft") is None


# ---------------------------------------------------------------- finishes
def test_finish_schedule_with_a_two_row_header_lost_reads_columns_by_order():
    """Upper header row (FLOOR / WALLS / CEILING) not read: a bare FINISH
    before BASE is the floor, a bare MATERIAL after the walls the
    ceiling."""
    from app import aitakeoff as ait
    t = {"kind": "finish", "confident": True, "key": "NO.", "page": 4,
         "columns": ["NO.", "ROOM NAME", "FINISH", "BASE", "WALL FINISH",
                     "MATERIAL", "FINISH 2", "HEIGHT"],
         "rows": [{"NO.": "201", "ROOM NAME": "OFFICE", "FINISH": "VCT",
                   "BASE": "RB", "WALL FINISH": "PT-1", "MATERIAL": "ACT",
                   "FINISH 2": "ACT-1", "HEIGHT": "9'-0\""}]}
    rows, bad = ait.finish_rows([t])
    r = rows[0]
    assert (r["floor"], r["base"], r["walls"], r["ceiling"],
            r["ceiling_height"]) == ("VCT", "RB", "PT-1", "ACT", "9'-0\"")


def test_explicit_floor_and_ceiling_columns_still_win():
    from app import aitakeoff as ait
    t = {"kind": "finish", "confident": True, "key": "NO.", "page": 4,
         "columns": ["NO.", "FLOOR", "FINISH", "BASE", "WALL FINISH",
                     "CEILING", "MATERIAL"],
         "rows": [{"NO.": "201", "FLOOR": "CPT", "FINISH": "X",
                   "BASE": "RB", "WALL FINISH": "PT-1", "CEILING": "GB",
                   "MATERIAL": "Y"}]}
    r = ait.finish_rows([t])[0][0]
    assert (r["floor"], r["ceiling"]) == ("CPT", "GB")


def test_room_with_no_height_gets_the_schedules_usual_height_as_an_assumption():
    from app import room_finishes as rf
    rooms = [{"name": "OFFICE 201", "number": "201", "sqft": 100,
              "perimeter_lf": 40},
             {"name": "OFFICE 202", "number": "202", "sqft": 100,
              "perimeter_lf": 40},
             {"name": "LOBBY 203", "number": "203", "sqft": 200,
              "perimeter_lf": 60}]
    sched = [{"room": "201", "walls": "PT-1", "ceiling_height": "9'-0\""},
             {"room": "202", "walls": "PT-1", "ceiling_height": "9'-0\""},
             {"room": "203", "walls": "PT-1", "ceiling_height": "VARIES"}]
    out = rf.room_finishes(rooms, finish_schedule=sched)
    lob = out["rooms"][2]
    assert lob["wall_sf"] == pytest.approx(60 * 9)
    assert lob["wall_height_assumed"] is True
    assert any("ASSUMED" in f for f in lob["flags"])
    assert lob["review"] is True
    assert out["walls"]["PT-1"] == pytest.approx((40 + 40 + 60) * 9)
    # no height anywhere in the schedule: still not measured
    out2 = rf.room_finishes(rooms[2:], finish_schedule=sched[2:])
    assert out2["rooms"][0]["wall_sf"] is None


def test_a_smaller_pipe_tag_does_not_take_a_double_line_pipe_of_the_next_size():
    """A 1-1/2" vent tag set beside a 2" waste pipe drawn double-line (its
    outlines 2.375" apart - the 2" outside diameter) names the dashed vent
    under it, not the waste pipe."""
    d = fitz.open()
    pg = d.new_page(width=1728, height=1152)
    ppu = 18.0
    sh = pg.new_shape()
    h = 2.375 / 12 * ppu / 2
    for o in (-h, h):
        sh.draw_line((200, 400 + o), (200 + 30 * ppu, 400 + o))
    sh.finish(width=1.5, color=(0, 0, 0))
    sh.draw_line((300, 392), (300 + 20 * ppu, 392))
    sh.finish(width=0.5, color=(0, 0, 0), dashes="[8 4] 0")
    sh.commit()
    pg.insert_text((400, 389), '1 1/2"V', fontsize=8)
    gs = {(g["name"], g["style_name"]): g["length"]
          for g in tt.mep_runs(pg, ppu, "ft") if g["labelled"]}
    assert not any(n == '1-1/2" V' and "1.5 pt" in st for n, st in gs), gs
