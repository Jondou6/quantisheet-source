"""Trade takeoff: pipe runs, ductwork, legend counts, roofing, rebar and
earthwork from synthetic sheets with known answers."""
import math
import os

import fitz

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import tradetakeoff as tt                           # noqa: E402

PPU = 18.0                                   # 1/4" = 1'-0"
OX, OY = 60, 80


def P(x, y):
    return (OX + x * PPU, OY + y * PPU)


def _line(page, a, b, color=(0, 0, 0), width=1.0, dashes=None):
    sh = page.new_shape()
    sh.draw_line(P(*a), P(*b))
    sh.finish(color=color, width=width, dashes=dashes)
    sh.commit()


def _text(page, xy, text, size=7):
    page.insert_text(P(*xy), text, fontsize=size)


def plumbing():
    d = fitz.open()
    p = d.new_page(width=1224, height=792)
    # background walls, thin grey
    for a, b in (((0, 0), (50, 0)), ((0, 0), (0, 30)), ((0, 30), (50, 30))):
        _line(p, a, b, color=(0.6, 0.6, 0.6), width=0.4)
    # 2" CW: 40 ft main + 8 ft branch (a tee)
    _line(p, (2, 10), (42, 10), color=(0, 0, 1), width=1.5)
    _line(p, (20, 10), (20, 18), color=(0, 0, 1), width=1.5)
    _text(p, (10, 9.4), '2" CW')
    # 1" HW: 30 ft, dashed red, with one corner
    _line(p, (2, 14), (22, 14), color=(1, 0, 0), width=1.0, dashes="[4 2] 0")
    _line(p, (22, 14), (22, 24), color=(1, 0, 0), width=1.0,
          dashes="[4 2] 0")
    _text(p, (6, 13.4), '1" HW')
    return d


def test_pipe_runs_by_system():
    d = plumbing()
    sys_ = tt.mep_runs(d[0], PPU, "ft")
    by = {g["name"]: g for g in sys_ if g["labelled"]}
    assert set(by) == {'2" CW', '1" HW'}, [g["name"] for g in sys_]
    assert abs(by['2" CW']["length"] - 48) < 0.5
    assert abs(by['1" HW']["length"] - 30) < 0.5
    assert all(not g["suggested"] for g in sys_ if not g["labelled"])
    marks = tt.run_marks(0, [by['2" CW']], "ft")
    assert sum(m[2]["measure"]["value"] for m in marks) == \
        by['2" CW']["length"]


def test_ducts_with_tags():
    d = fitz.open()
    p = d.new_page(width=1224, height=792)
    # 24" wide duct, 30 ft long, tagged 24x12
    _line(p, (5, 10), (35, 10))
    _line(p, (5, 12), (35, 12))
    _text(p, (18, 11.3), "24x12")
    # 14" round, 20 ft, tagged
    _line(p, (5, 20), (25, 20))
    _line(p, (5, 20 + 14 / 12), (25, 20 + 14 / 12))
    _text(p, (12, 22.8), '14"Ø')
    groups = {g["name"]: g for g in tt.ducts(p, PPU, "ft")}
    assert "24x12" in groups, list(groups)
    g = groups["24x12"]
    assert abs(g["length"] - 30) < 0.5
    assert abs(g["sf"] - 180) < 3                # 2(24+12)/12 x 30
    assert g["gauge"] == 24 and abs(g["lb"] - 180 * 1.156) < 4
    r = groups['14" round']
    assert abs(r["length"] - 20) < 0.5
    assert abs(r["sf"] - math.pi * 14 / 12 * 20) < 2


def _receptacle(page, x, y):
    c = fitz.Point(*P(x, y))
    sh = page.new_shape()
    sh.draw_circle(c, 5)
    sh.draw_line(c + (-7, -2), c + (-5, -2))
    sh.draw_line(c + (-7, 2), c + (-5, 2))
    sh.finish(color=(0, 0, 0), width=0.8)
    sh.commit()


def _jbox(page, x, y):
    c = fitz.Point(*P(x, y))
    sh = page.new_shape()
    sh.draw_rect(fitz.Rect(c.x - 5, c.y - 5, c.x + 5, c.y + 5))
    sh.draw_line(c + (-5, -5), c + (5, 5))
    sh.draw_line(c + (-5, 5), c + (5, -5))
    sh.finish(color=(0, 0, 0), width=0.8)
    sh.commit()


def test_legend_counts():
    d = fitz.open()
    p = d.new_page(width=1224, height=792)
    p.insert_text((900, 80), "LEGEND", fontsize=10)
    lx = 900
    # legend rows: symbol left of its description
    c = fitz.Point(lx + 10, 104)
    sh = p.new_shape()
    sh.draw_circle(c, 5)
    sh.draw_line(c + (-7, -2), c + (-5, -2))
    sh.draw_line(c + (-7, 2), c + (-5, 2))
    sh.draw_rect(fitz.Rect(lx + 5, 119, lx + 15, 129))
    sh.draw_line((lx + 5, 119), (lx + 15, 129))
    sh.draw_line((lx + 5, 129), (lx + 15, 119))
    sh.finish(color=(0, 0, 0), width=0.8)
    sh.commit()
    p.insert_text((lx + 30, 107), "DUPLEX RECEPTACLE", fontsize=7)
    p.insert_text((lx + 30, 127), "JUNCTION BOX", fontsize=7)
    for x, y in ((3, 3), (10, 5), (18, 3), (25, 9), (33, 4)):
        _receptacle(p, x, y)
    for x, y in ((5, 15), (20, 18), (30, 15)):
        _jbox(p, x, y)
    rows = tt.legend_rows(p)
    assert [r[0] for r in rows] == ["DUPLEX RECEPTACLE", "JUNCTION BOX"]
    counts = {c["name"]: len(c["hits"]) for c in tt.legend_counts(d)}
    assert counts == {"DUPLEX RECEPTACLE": 5, "JUNCTION BOX": 3}, counts


def test_roof_pitch():
    d = fitz.open()
    p = d.new_page(width=1224, height=792)
    _text(p, (10, 10), "6:12")
    poly = [P(0, 0), P(40, 0), P(40, 30), P(0, 30)]
    assert tt.pitch_for(poly, tt.pitch_labels(p)) == 6
    r = tt.roof_area(1200, 6, waste=0.1)
    assert abs(r["factor"] - 1.1180) < 1e-3
    assert abs(r["sloped"] - 1341.6) < 0.5 and abs(r["squares"] - 14.76) \
        < 0.01


def test_rebar():
    rows = tt.rebar_linear(100, bar=4, bars=3)
    assert rows[0]["laps"] == 15                  # 5 splices per bar
    assert abs(rows[0]["lf"] - 3 * (100 + 5 * 40 * 0.5 / 12)) < 0.01
    slab = tt.rebar_slab(20 * 10, 60, bar=4, spacing_in=12)
    long_, short = slab
    assert long_["count"] == 11 and abs(long_["lf"] - 11 * 20) < 0.01
    assert short["count"] == 21 and abs(short["lf"] - 21 * 10) < 0.01
    tot = tt.rebar_totals(rows + slab)
    assert tot[0]["bar"] == 4 and abs(tot[0]["lb"] - tot[0]["lf"] * 0.668) \
        < 0.01


def test_cut_fill():
    d = fitz.open()
    p = d.new_page(width=1224, height=1100)
    b = 10                                       # boundary starts here
    for k in range(5):                            # existing 100..104
        y = b + k * 10
        _line(p, (0, y), (40, y), dashes="[3 3] 0", width=0.5)
        _text(p, (0.5, y - 0.3), f"{100 + k}")
    for k in range(6):                            # proposed: 0.5 ft higher
        y = b + k * 10 - 5
        _line(p, (0, y), (40, y), width=1.0)
        _text(p, (35, y - 0.3), f"{100 + k}")
    sets = tt.contour_sets(p, PPU, "ft")
    assert len(sets) == 2, [s["style_name"] for s in sets]
    ex = next(s for s in sets if s["dashed"])
    pr = next(s for s in sets if not s["dashed"])
    assert sorted({l["z"] for l in ex["lines"]}) == [100, 101, 102, 103, 104]
    assert sorted({l["z"] for l in pr["lines"]}) == [100, 101, 102, 103, 104,
                                                     105]
    bnd = [P(0, b), P(40, b), P(40, b + 40), P(0, b + 40)]
    res = tt.cut_fill(ex["lines"], pr["lines"], bnd, PPU, "ft", cell_ft=2)
    assert abs(res["fill"] - 1600 * 0.5 / 27) < 1.5, res["fill"]
    assert res["cut"] < 0.5
    assert abs(res["area"] - 1600) < 1


def test_steel_members():
    d = fitz.open()
    p = d.new_page(width=1224, height=792)
    _line(p, (0, 5), (30, 5), width=1.5)
    _text(p, (12, 4.4), "W12X26")
    _line(p, (0, 15), (30, 15), width=1.5)
    _text(p, (12, 14.4), "W12X26")
    _line(p, (0, 25), (20, 25), width=1.5)
    _text(p, (8, 24.4), "HSS6X6X1/4")
    by = {g["name"]: g for g in tt.steel_members(p, PPU, "ft")}
    assert by["W12X26"]["count"] == 2
    assert abs(by["W12X26"]["lb"] - 60 * 26) < 20
    assert abs(by["HSS6X6X1/4"]["length"] - 20) < 0.5
    assert abs(tt.steel_weight("HSS6X6X1/4") - 19.02) < 0.1
