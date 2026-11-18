"""Work notes in the estimate once (Nov 17), made-up data only.

Work Notes Takeoff > Add to Estimate and AI Takeoff's work-note step keep
their totals in the same place, so one note is one takeoff line; the
estimate line Add to Estimate makes is linked to it and keeps its price
when the notes are added again.
"""
import os
import sys
from decimal import Decimal

import fitz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import ai_quantities as aq, callouts as co, callouts_ui as cu  # noqa: E402,E501
from app import estimate, estimate_lines as el  # noqa: E402


def notes(n=3, sheet="C-1"):
    return co.read_blocks(
        [(["INSTALL:", f"{n} - 6-INCH PLUG VALVE"], (0, 0, 9, 9))], sheet)


def doc1():
    d = fitz.open()
    d.new_page()
    return d


def ai_groups(d):
    return [g for g in estimate.lines(d) if g["type"] == "ai"]


def ai_run(qty):
    return {"quantities": [{
        "engine": "work notes", "name": "Install 6-INCH PLUG VALVE",
        "qty": qty, "unit": "EA", "status": "taken off", "page": None}]}


def test_ai_takeoff_then_window_gives_one_line():
    d = doc1()
    aq.store(d, ai_run(3))
    assert len(ai_groups(d)) == 1
    cu.add_to_estimate(d, notes(3))
    g = ai_groups(d)
    assert len(g) == 1 and g[0]["quantity"] == 3      # not 6
    (ln,) = el.read(d)
    assert el.price(ln, el._groups(d))["quantity"] == 3


def test_window_then_ai_takeoff_keeps_the_window_row():
    d = doc1()
    cu.add_to_estimate(d, notes(3))
    aq.store(d, ai_run(5))           # AI Takeoff runs again later
    g = ai_groups(d)
    assert len(g) == 1 and g[0]["quantity"] == 3
    assert [r.get("from") for r in aq.rows(d)] == [aq.WINDOW]


def test_price_kept_when_added_again():
    d = doc1()
    cu.add_to_estimate(d, notes(3))
    (ln,) = el.read(d)
    el.update(d, ln["id"], mat="1")              # made-up unit price
    cu.add_to_estimate(d, notes(3) + notes(4, "C-3"))
    (ln,) = el.read(d)
    p = el.price(ln, el._groups(d))
    assert p["quantity"] == 7 and Decimal(ln["mat"]) == 1


def test_old_unlinked_line_is_linked_in_place():
    d = doc1()
    el.add(d, [el.new_line(desc="Install 6-INCH PLUG VALVE", qty=3,
                           unit="ea", source=cu.SOURCE, mat=1)])
    assert cu.add_to_estimate(d, notes(4)) == (0, 1, 0)
    (ln,) = el.read(d)
    assert ln["link"]["name"] == "Install 6-INCH PLUG VALVE"
    assert el.price(ln, el._groups(d))["quantity"] == 4
    assert Decimal(ln["mat"]) == 1


def test_other_ai_quantities_untouched():
    d = doc1()
    aq.store(d, {"quantities": [{"engine": "steel", "name": "W8x10 beams",
                                 "qty": 100.0, "unit": "LB",
                                 "status": "taken off", "page": 0}]})
    cu.add_to_estimate(d, notes(2))
    names = sorted(g["name"] for g in ai_groups(d))
    assert names == ["Install 6-INCH PLUG VALVE", "W8x10 beams"]
