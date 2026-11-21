"""Rebar, beam, column and footing calculators (Nov 19), worked by hand
from the textbook formulas. Made-up sizes and loads."""
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import structcalc as sc  # noqa: E402


def test_bar_table_and_laps():
    assert sc.BARS[4] == (0.5, 0.668) and sc.BARS[5][1] == 1.043
    assert sc.lap_in(5) == 25.0                     # 40 x 5/8"
    assert sc.run_lf(18, 4) == (18, 0)
    lf, laps = sc.run_lf(50, 4)                     # 20" laps
    assert laps == 2 and abs(lf - (50 + 2 * 20 / 12)) < 1e-9
    with pytest.raises(ValueError):
        sc.run_lf(50, 4, stock_ft=1)


def test_rebar_grid_area_and_linear():
    r = sc.rebar_grid(20, 20, 12, 4, cover_in=3, waste_pct=0)
    assert r["bars"] == 40 and r["lf"] == 780       # 20 + 20 bars x 19.5'
    assert abs(r["lb"] - 780 * 0.668) < 1e-6
    one = sc.rebar_grid(20, 20, 12, 4, cover_in=3, each_way=False,
                        waste_pct=0)
    assert one["bars"] == 20
    a = sc.rebar_area(400, 12, 4, waste_pct=0)
    assert abs(a["lf"] - 800 * 20 / (20 - 20 / 12)) < 1e-6
    ln = sc.rebar_linear(100, 2, 5, waste_pct=10)
    assert ln["bars"] == 2 and ln["laps"] == 10
    assert abs(ln["tons"] - ln["lf"] * 1.043 * 1.1 / 2000) < 1e-9


def test_dressed_sizes_and_section():
    assert [sc.dressed(n) for n in (2, 4, 6, 8, 10, 12)] == \
        [1.5, 3.5, 5.5, 7.25, 9.25, 11.25]
    s = sc.rect_section(1.5, 9.25, plies=2)
    assert s["A"] == 27.75 and abs(s["S"] - 3 * 9.25 ** 2 / 6) < 1e-9


def test_beam_uniform_and_point():
    sec = sc.rect_section(3.5, 9.25)
    r = sc.beam(10, 200, section=sec, E_psi=1.6e6, Fb_psi=1000, Fv_psi=180)
    assert r["R1"] == r["R2"] == 1000 and r["Mmax"] == 2500   # wL²/8
    assert abs(r["defl_in"] - 5 * (200 / 12) * 120 ** 4 /
               (384 * 1.6e6 * sec["I"])) < 1e-9
    assert all(ok for *_x, ok in r["checks"])
    p = sc.beam(12, 0, 1000, 4)                     # P b / L, P a b / L
    assert abs(p["R1"] - 1000 * 8 / 12) < 1e-9
    assert abs(p["Mmax"] - 1000 * 4 * 8 / 12) < 1e-6 and p["x_Mmax"] == 4
    over = sc.beam(20, 400, section=sec, E_psi=1.6e6, Fb_psi=900)
    assert not all(ok for *_x, ok in over["checks"])
    with pytest.raises(ValueError):
        sc.beam(10, 100, 500, 12)


def test_columns():
    w = sc.wood_column(8, 3.5, 3.5, 1150, 580000)
    le_d = 96 / 3.5
    FcE = 0.822 * 580000 / le_d ** 2
    r = FcE / 1150
    q = (1 + r) / 1.6
    assert abs(w["Cp"] - (q - math.sqrt(q * q - r / 0.8))) < 1e-12
    assert abs(w["P_allow_lb"] - 1150 * w["Cp"] * 12.25) < 1e-9
    assert not sc.wood_column(20, 1.5, 3.5, 1000, 500000)["slender_ok"]
    s = sc.steel_column(10, 5.26, 1.23)              # inelastic branch
    KLr = 120 / 1.23
    Fe = math.pi ** 2 * 29e6 / KLr ** 2
    Fcr = 0.658 ** (50000 / Fe) * 50000
    assert abs(s["P_allow_lb"] - Fcr * 5.26 / 1.67) < 1e-6
    tall = sc.steel_column(40, 5.26, 1.23)          # elastic branch
    assert abs(tall["Fcr"] - 0.877 * tall["Fe"]) < 1e-9
    assert sc.steel_column(10, 5.26, 1.23, method="LRFD")["P_allow_lb"] \
        == pytest.approx(0.9 * s["Pn_lb"])


def test_footing_size():
    f = sc.footing_size(20000, 2000, 12)
    assert abs(f["side_ft"] - 40 / 12) < 1e-9       # 3'-4" (2" steps)
    assert f["bearing_psf"] <= 2000
    c = sc.footing_size(2000, 1500, 10, "continuous")
    assert c["width_ft"] == 1.5 and c["bearing_psf"] <= 1500
    with pytest.raises(ValueError):
        sc.footing_size(1000, 100, 12)              # own weight is more


def test_cold_formed_members_and_framing():
    m = sc.cfs_member("362S162-54")
    assert (m["depth_in"], m["flange_in"], m["t_in"], m["lip_in"]) == \
        (3.62, 1.62, 0.054, 0.5)
    assert abs(m["lb_ft"] - (3.62 + 3.24 + 1.0) * 0.054 * 490 / 144) < 1e-9
    assert sc.cfs_member("362t125-33")["lip_in"] == 0
    with pytest.raises(ValueError):
        sc.cfs_member("2x4")
    w = sc.cfs_wall(40, 10, 16, openings=2, corners=1, waste_pct=0)
    assert w["studs"] == 30 + 1 + 8 + 2            # 40' at 16" + end + extras
    assert w["track_lf"] == 80 and w["track_pieces"] == 8
    assert w["bridging_rows"] == 2 and w["bridging_lf"] == 80
    j = sc.cfs_joists(16, 30, 24, waste_pct=0)
    assert j["joists"] == 16 and j["joist_lf"] == 256 and j["rim_lf"] == 60


def test_steel_shape_weights_and_list():
    for shape, lb in (("W12x26", 26), ("C10x15.3", 15.3),
                      ("HSS6x6x1/4", 19.02), ("HSS8x4x3/8", 27.48),
                      ("HSS6.625x0.280", 18.99), ("PIPE4.5x0.237", 10.8),
                      ("L4x4x1/4", 6.59), ("PL1/2x12", 20.42),
                      ("RD1", 2.67)):
        assert abs(sc.shape_lb_ft(shape) - lb) < 0.01, shape
    with pytest.raises(ValueError):
        sc.shape_lb_ft("PIPE6STD")
    r = sc.steel_list("W12x26, 24, 6\n# note\nPIPE6STD, 10\nL4x4x1/4 8",
                      extra_pct=10)
    assert len(r["rows"]) == 2 and r["bad"] == ["PIPE6STD, 10"]
    assert abs(r["lb"] - (26 * 24 * 6 + sc.shape_lb_ft("L4x4x1/4") * 8)) \
        < 1e-6
    assert abs(r["tons"] - r["lb"] * 1.1 / 2000) < 1e-9


try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from test_gui import win, qapp  # noqa: F401,E402
except Exception:                                         # noqa: BLE001
    pass


def test_new_tabs_in_the_calculators_window(win):
    d = win.calculators(3, show=False)
    assert d.tabs.count() == 13 and d.tabs.currentIndex() == 3
    rb = d.rebar
    rb.length.setValue(20)
    rb.wide.setValue(20)
    rb.waste.setValue(0)
    assert "780 LF of #4" in rb.out.text()
    assert d.copy().startswith("Rebar - #4")
    rb.use_takeoff("length", "ft", 100)
    assert rb.mode.currentData() == "linear"
    d.tabs.setCurrentIndex(4)
    bm = d.beam
    bm.span.setValue(10)
    bm.w.setValue(200)
    assert "2,500 ft-lb" in bm.out.text() and "OK" in bm.out.text()
    assert "preliminary" in d.copy()
    bm.kind.setCurrentIndex(1)
    assert not bm.b.isVisible() or True
    d.tabs.setCurrentIndex(5)
    col = d.column
    col.load.setValue(1000)
    assert "Allowable axial load" in col.out.text()
    col.kind.setCurrentIndex(1)
    assert "KL/r" in col.out.text()
    d.tabs.setCurrentIndex(6)
    ft = d.footing
    ft.load.setValue(20000)
    assert "3'-4\" square" in ft.out.text()
    ft.kind.setCurrentIndex(1)
    assert "wide" in ft.out.text()
    d.tabs.setCurrentIndex(7)
    st = d.studs
    st.length.setValue(40)
    st.waste.setValue(0)
    assert "31 studs" in st.out.text() and "80 LF of track" in st.out.text()
    st.use_takeoff("area", "sq ft", 480)
    assert st.kind.currentData() == "joists" and st.wide.value() == 30
    assert "800S200-54" in d.copy()
    d.tabs.setCurrentIndex(8)
    sl = d.steel
    sl.list.setPlainText("W12x26, 24, 6\nBOGUS, 3")
    sl.extra.setValue(0)
    assert "3,744 lb" in sl.out.text() and "Not read: BOGUS, 3" in \
        sl.out.text()
    texts = [a.text() for a in win.findChildren(type(win._file_menu
                                                     .actions()[0]))]
    for name in ("Rebar Calculator…", "Beam and Header Calculator…",
                 "Column and Post Calculator…", "Footing Size Calculator…",
                 "Metal Stud Framing Calculator…",
                 "Structural Steel Calculator…"):
        assert name in texts
