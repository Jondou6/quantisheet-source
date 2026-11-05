"""Design rules from the Oct 31 2026 patent review (informational, not
legal advice). Each rule has a guard here so a later change that breaks it
fails the build. See the comments marked DESIGN RULE in the code."""
import inspect
import os
import re

import fitz

from app import aitakeoff as ait, autotakeoff

APP = os.path.join(os.path.dirname(__file__), "..", "app")


def _src(name):
    with open(os.path.join(APP, name), encoding="utf-8") as f:
        return f.read()


# (1) counting: whole-symbol scoring only; no piece-by-piece pass, no
# colour/size pre-filter before matching
def test_rule1_counting_has_no_component_pass_or_colour_prefilter():
    for name in ("autocount.py", "count_several.py",
                 "count_triage.py"):
        s = _src(name)
        assert "connectedComponents" not in s, name
        assert "inRange" not in s, name          # colour mask pre-filter
    assert "DESIGN RULE" in _src("autocount.py")


# (2) area: one step, finished result; text excluded automatically
def _two_rooms(text):
    d = fitz.open()
    p = d.new_page(width=792, height=612)
    x0, y0, t, w, h = 100, 100, 9, 180, 216     # 10' x 12' at 1/4"=1'
    sh = p.new_shape()
    for r in ((x0 - t, y0 - t, x0 + 2 * w + 2 * t, y0),
              (x0 - t, y0 + h, x0 + 2 * w + 2 * t, y0 + h + t),
              (x0 - t, y0, x0, y0 + h), (x0 + w, y0, x0 + w + t, y0 + h),
              (x0 + 2 * w + t, y0, x0 + 2 * w + 2 * t, y0 + h)):
        sh.draw_rect(fitz.Rect(*r))
    sh.finish(fill=(0, 0, 0), color=None)
    sh.commit()
    if text:
        p.insert_text((x0 + 40, y0 + 100), "OFFICE 101", fontsize=14)
        p.insert_text((x0 + w + t + 40, y0 + 100), "OFFICE 102",
                      fontsize=14)
    return d, p


SCALE = {"ppu": 18.0, "unit": "ft"}


def test_rule2_area_is_one_step_and_ignores_text():
    _d, plain = _two_rooms(False)
    _d2, texted = _two_rooms(True)
    a = autotakeoff.room_at(plain, SCALE, fitz.Point(190, 160))
    b = autotakeoff.room_at(texted, SCALE, fitz.Point(190, 160))
    assert abs(a["sqft"] - b["sqft"]) < 0.5         # text left out by itself
    assert a["pts"] and a["sqft"] > 0               # finished outline, once
    s = _src("autotakeoff.py")
    for word in ("QTimer", "processEvents"):
        assert word not in s                        # nothing drawn growing
    assert "DESIGN RULE" in s


# (3) no rank/dominance split of shared wall area, no 50/50 tie rule
def test_rule3_each_room_to_its_own_wall_faces():
    _d, p = _two_rooms(False)
    a = autotakeoff.room_at(p, SCALE, fitz.Point(190, 160))
    b = autotakeoff.room_at(p, SCALE, fitz.Point(379, 160))
    assert abs(a["sqft"] - 120) < 2 and abs(b["sqft"] - 120) < 2
    # the 6" shared wall (6 SF) is in neither room, not split between them
    assert a["sqft"] + b["sqft"] < 120 + 120 + 1
    for name in ("autotakeoff.py", "autowalls.py", "aitakeoff.py"):
        s = _src(name).lower()
        assert not re.search(r"dominan|50\s*/\s*50|fifty.fifty", s), name


# (4) scale from printed scale text and dimension strings, never from
# counting pixels on something of known length
def test_rule4_scale_comes_from_text_not_pixels():
    d = fitz.open()
    p = d.new_page(width=792, height=612)
    p.insert_text((600, 580), "FLOOR PLAN", fontsize=12)
    p.insert_text((600, 595), "SCALE: 1/4\" = 1'-0\"", fontsize=9)
    p.draw_line((100, 100), (400, 100), width=6)
    q = d.new_page(width=792, height=612)           # no scale printed
    q.draw_line((100, 100), (400, 100), width=6)
    rows = ait.plan_set(d)
    assert rows[0]["scale"] and abs(rows[0]["scale"][1] - 18.0) < 0.01
    assert not rows[1]["scale"]                    # no guess from pixels
    src = inspect.getsource(ait.plan_set)
    assert "get_pixmap" not in src
    assert "DESIGN RULE" in _src("takeoff.py")


# ---- round 2 (Jon, Oct 31): template counting and the room fill code are
# kept behind these rules; the picture matcher has an off switch

def test_rule1_no_multipass_or_piece_steps_in_any_counter():
    for name in ("autocount.py", "count_several.py",
                 "count_triage.py", "second_symbol.py"):
        s = _src(name)
        for word in ("connectedComponents", "findContours", "pyrDown",
                     "pyrUp", "inRange", "calcHist", "ndimage.label"):
            assert word not in s, (name, word)


def test_rule1_ink_check_compares_whole_masks():
    from app import autocount
    src = inspect.getsource(autocount._ink_check)
    assert "connected" not in src.lower() and "label" not in src.lower()
    import numpy as np
    t = np.full((10, 10), 255, np.uint8)
    t[2:8, 2] = 0
    t[2:8, 7] = 0                    # two separate strokes, one symbol
    g = np.full((20, 20), 255, np.uint8)
    g[2:8, 2] = 0                    # only one of the strokes is there
    found, _expl = autocount._ink_check(g, 0, 0, t)
    assert 0.4 < found < 0.6         # one share for the whole symbol


def test_picture_count_switch_skips_every_picture_step(monkeypatch):
    from app import autocount, tradetakeoff, settings

    def boom(*a, **k):
        raise AssertionError("picture step ran with picture_count off")
    monkeypatch.setattr(autocount, "find_symbols", boom)
    monkeypatch.setattr(autocount, "symbol_template", boom)
    d = fitz.open()
    p = d.new_page(width=792, height=612)
    p.insert_text((600, 80), "LEGEND", fontsize=10)
    p.draw_circle((610, 100), 4)
    p.insert_text((620, 103), "DUPLEX RECEPTACLE", fontsize=8)
    tradetakeoff.legend_counts(d, pictures=False)          # no AssertionError
    monkeypatch.setattr(settings, "get",
                        lambda k, dflt=None: False if k == "picture_count"
                        else dflt)
    assert ait.picture_count_on() is False


def test_picture_count_is_on_unless_turned_off(monkeypatch):
    from app import settings
    monkeypatch.setattr(settings, "get", lambda k, dflt=None: dflt)
    assert ait.picture_count_on() is True


def test_rule2_room_tools_take_no_user_ignore_pick():
    for fn in (autotakeoff.room_at, autotakeoff.all_rooms):
        params = inspect.signature(fn).parameters
        assert not any(re.search(r"ignore|exclude", p) for p in params), fn
    # the stall / partition model and the pocket join decide by themselves
    src = inspect.getsource(autotakeoff.join_pockets) + \
        inspect.getsource(autotakeoff.partition_layers)
    assert "QTimer" not in src and "processEvents" not in src


def test_rule4_gross_outline_uses_the_scale_not_pixel_counts():
    from app import wall_roles
    src = inspect.getsource(wall_roles.layer_outline)
    assert "ppu" in src and "get_pixmap" not in src
