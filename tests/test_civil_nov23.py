"""A callout drawn in the plan and again up the profile is one structure,
also when the profile copy's station can't be read (Nov 23, civil set).
Made-up text and positions only."""
import os
import sys

import fitz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import civiltakeoff as ct  # noqa: E402

R = fitz.Rect


def _item(text, rect):
    return {"id": "MH x", "kind": "manhole", "unnumbered": True,
            "rect": rect, "center": ((rect.x0 + rect.x1) / 2,
                                     (rect.y0 + rect.y1) / 2), "text": text}


LS = [("STA 1+65", R(100, 100, 160, 110)),
      ("1-AIR RELEASE", R(100, 112, 170, 122)),
      ("VALVE & MANHOLE", R(100, 124, 180, 134)),
      ("1-AIR RELEASE", R(500, 600, 510, 670)),        # up the profile
      ("VALVE & MANHOLE", R(512, 600, 522, 680)),
      ("PROFILE", R(800, 900, 860, 912))]


def test_profile_copy_without_station_is_dropped():
    plan = _item("VALVE & MANHOLE", R(100, 124, 180, 134))
    prof = _item("VALVE & MANHOLE", R(512, 600, 522, 680))
    out = ct._one_per_station([plan, prof], LS)
    assert out == [plan] and plan["station"] == 165.0


def test_two_different_manholes_stay():
    ls = LS[:3] + [("STA 3+10", R(400, 100, 460, 110)),
                   ("SANITARY", R(400, 112, 460, 122)),
                   ("MANHOLE", R(400, 124, 460, 134)),
                   ("PROFILE", R(800, 900, 860, 912))]
    a = _item("VALVE & MANHOLE", R(100, 124, 180, 134))
    b = _item("MANHOLE", R(400, 124, 460, 134))
    assert len(ct._one_per_station([a, b], ls)) == 2


def test_no_profile_on_the_sheet_keeps_both():
    plan = _item("VALVE & MANHOLE", R(100, 124, 180, 134))
    prof = _item("VALVE & MANHOLE", R(512, 600, 522, 680))
    out = ct._one_per_station([plan, prof], LS[:-1])
    assert len(out) == 2


def test_scale_read_again_close_up():
    from app import autoscale as asc
    words = [(500, 700, 530, 708, "SCALE:", 0, 0, 0),
             (495, 740, 540, 748, "GRAPHIC", 0, 0, 1),
             (545, 740, 575, 748, "SCALE", 0, 0, 2)]
    seen = []

    def ocr(page, clip, dpi=None):
        seen.append(clip)
        return "SITE PLAN\nSCALE: 1\" = 5'\n0' 5' 10'\nGRAPHIC SCALE"
    got = asc.zoom_scale(None, words, ocr=ocr)
    assert got[0] == "1\" = 5'" and abs(got[1] - 72.0 / 5) < 1e-9
    assert len(seen) == 1                    # one close look
    assert asc.zoom_scale(None, words[:1], ocr=ocr) is None   # no bar
    assert asc.zoom_scale(None, words, ocr=lambda p, c, d=0: "NOTES") is None
    # the "= 5'" lost: not taken for 1" = 10'
    assert asc.zoom_scale(None, words, ocr=lambda p, c, d=0:
                          "SITE PLAN | SCALE: 1\" | 10' | GRAPHIC SCALE") \
        is None
    assert asc.zoom_scale(None, [(0, 0, 9, 9, "WALL", 0, 0, 0)],
                          ocr=ocr) is None


def test_close_up_reads_as_one_block_first(monkeypatch):
    # Nov 23 (C01.20): the sparse-text reading lost "= 5'", the block
    # reading kept it - so the block reading goes first
    from app import autoscale as asc
    words = [(495, 740, 540, 748, "GRAPHIC", 0, 0, 1)]
    calls = []

    def fake(page, clip, dpi=asc.ZOOM_DPI, psm=11):
        calls.append((dpi, psm))
        return ("SCALE: 1\" = 5' | 0' 5) 10' | GRAPHIC SCALE" if psm == 6
                else "SCALE: 1\" | 0 | 5 | 10 | GRAPHIC SCALE")
    monkeypatch.setattr(asc, "_ocr_clip_text", fake)
    got = asc.zoom_scale(None, words)
    assert got[0] == "1\" = 5'" and calls == [(asc.ZOOM_DPI, 6)]


def test_close_up_architectural_scale_read_twice():
    from app import autoscale as asc
    words = [(495, 740, 540, 748, "GRAPHIC", 0, 0, 1),
             (495, 1340, 540, 1348, "GRAPHIC", 0, 0, 1)]
    one = "TOP PLAN\nSCALE: 1/2\u201d = 1\u2019-0\u201d\n0 2 4\nGRAPHIC SCALE"
    got = asc.zoom_scale(None, words, ocr=lambda p, c, d=0: one)
    assert got[0] == "1/2\" = 1'-0\"" and abs(got[1] - 36.0) < 1e-9
    # read once only: not enough
    reads = iter([one] + ["GRAPHIC SCALE"] * 9)
    assert asc.zoom_scale(None, words, ocr=lambda p, c, d=0:
                          next(reads)) is None
    # once, and its inches again with the rest lost (D01.20): enough
    part = "PIPING PLAN\nSCALE: 1/2\u201d =\n0 2 4\nGRAPHIC SCALE"
    reads = iter([one] + [part] * 9)
    assert asc.zoom_scale(None, words, ocr=lambda p, c, d=0:
                          next(reads))[0] == "1/2\" = 1'-0\""
    reads = iter([one] + [part.replace("1/2", "1/4")] * 9)
    assert asc.zoom_scale(None, words, ocr=lambda p, c, d=0:
                          next(reads)) is None
    # two views, two different scales: no one scale for the sheet
    two = iter([one, one.replace("1/2", "1/4")] * 5)
    assert asc.zoom_scale(None, words, ocr=lambda p, c, d=0:
                          next(two)) is None


def test_tesseract_page_mode_is_passed(monkeypatch):
    import subprocess
    from app import acrobat
    seen = {}

    class R:
        returncode, stdout, stderr = 0, b"h\n", b""

    def run(cmd, **kw):
        seen["cmd"] = cmd
        return R()
    monkeypatch.setattr(subprocess, "run", run)
    acrobat._tess_tile("tess", "x.png", "eng", None, psm=6)
    assert seen["cmd"][seen["cmd"].index("--psm") + 1] == "6"
    acrobat._tess_tile("tess", "x.png", "eng", None)
    assert seen["cmd"][seen["cmd"].index("--psm") + 1] == "11"


def test_civil_scale_of_five_feet():
    from app import autoscale as asc
    assert asc.civil_scale("SCALE: 1\" = 5'")[0] == "1\" = 5'"
    assert asc.civil_scale("SCALE: 1/2\" = 1'-0\"") is None
