import fitz
from app import rules, page_ops, takeoff


def _doc(pages=2):
    d = fitz.open()
    for _ in range(pages):
        p = d.new_page(width=612, height=792)
        p.insert_text((40, 60), "The wall shall be rated. fire rating 2 hr.")
    return d


def test_rules_apply():
    d = _doc()
    n = rules.apply_rules(d)
    assert n > 0


def test_bates():
    d = _doc(3)
    n = page_ops.bates_number(d, "EX", 1)
    assert n == 3


def test_takeoff_distance():
    cal = takeoff.Calibration(fitz.Point(0, 0), fitz.Point(100, 0), 10, "ft")
    v = takeoff.distance(cal, fitz.Point(0, 0), fitz.Point(50, 0))
    assert abs(v - 5.0) < 0.001


def test_takeoff_area():
    cal = takeoff.Calibration(fitz.Point(0, 0), fitz.Point(10, 0), 10, "ft")
    v = takeoff.area(cal, [fitz.Point(0, 0), fitz.Point(10, 0),
                           fitz.Point(10, 10), fitz.Point(0, 10)])
    assert abs(v - 100.0) < 0.01
