"""AI Takeoff reads with full word boxes even when PyMuPDF's process-wide
small-glyph-heights switch was left on (PyMuPDF's table finder flips it),
and puts the switch back as it found it."""
import fitz

from app import aitakeoff as ait


def test_run_and_plan_set_are_guarded():
    assert ait.run.__wrapped__ and ait.plan_set.__wrapped__


def test_switch_off_inside_and_put_back():
    seen = []
    f = ait._full_glyph_boxes(
        lambda: seen.append(bool(fitz.TOOLS.set_small_glyph_heights())))
    prev = fitz.TOOLS.set_small_glyph_heights()
    try:
        fitz.TOOLS.set_small_glyph_heights(True)
        f()
        assert seen == [False]
        assert fitz.TOOLS.set_small_glyph_heights() is True
        fitz.TOOLS.set_small_glyph_heights(False)
        f()
        assert seen == [False, False]
        assert fitz.TOOLS.set_small_glyph_heights() is False
    finally:
        fitz.TOOLS.set_small_glyph_heights(prev)


def test_switch_put_back_after_an_error():
    def boom():
        raise ValueError("x")
    prev = fitz.TOOLS.set_small_glyph_heights()
    try:
        fitz.TOOLS.set_small_glyph_heights(True)
        try:
            ait._full_glyph_boxes(boom)()
        except ValueError:
            pass
        assert fitz.TOOLS.set_small_glyph_heights() is True
    finally:
        fitz.TOOLS.set_small_glyph_heights(prev)


def test_plan_set_same_words_with_switch_on():
    doc = fitz.open()
    pg = doc.new_page(width=1224, height=792)
    pg.insert_text((900, 760), "A101", fontsize=14)
    pg.insert_text((900, 740), "FIRST FLOOR PLAN", fontsize=10)
    pg.insert_text((900, 720), 'SCALE: 1/4" = 1\'-0"', fontsize=8)
    a = ait.plan_set(doc)
    prev = fitz.TOOLS.set_small_glyph_heights()
    try:
        fitz.TOOLS.set_small_glyph_heights(True)
        b = ait.plan_set(doc)
    finally:
        fitz.TOOLS.set_small_glyph_heights(prev)
    assert repr(a) == repr(b)
