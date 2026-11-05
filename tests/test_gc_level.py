"""Big sets skip the slow duplicate-merge pass when saved (an 800-sheet
set never finished saving; External Issue of a 309-sheet set took
2.5 minutes)."""
import fitz

from app import safeio


def _doc(n):
    d = fitz.open()
    for _ in range(n):
        d.new_page()
    return d


def test_small_sets_still_fully_cleaned():
    assert safeio.gc_level(_doc(5)) == 3


def test_big_sets_use_the_fast_level():
    assert safeio.gc_level(_doc(safeio.BIG_SET + 1)) == 1


def test_odd_input_is_safe():
    assert safeio.gc_level(None) == 1
