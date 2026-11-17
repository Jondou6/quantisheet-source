"""Live takeoff-to-estimate (Nov 17), made-up data only.

AI Takeoff quantities worked out rather than drawn (steel weight, wall
area, work-note counts) are kept in the PDF and shown in the Estimate
panel as takeoff lines of type "ai"; an estimate line linked to one
follows a re-run; review's accepted items join; quantities only.
"""
import json
import os
import sys

import fitz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import ai_quantities as aq, estimate, estimate_lines as el  # noqa: E402,E501


def doc3():
    d = fitz.open()
    for _ in range(3):
        d.new_page(width=600, height=400)
    return d


def res_of(*qs):
    return {"quantities": [dict(q) for q in qs]}


STEEL = {"engine": "steel", "name": "W8x10 beams", "qty": 1520.0,
         "unit": "LB", "status": "taken off", "page": 1, "sheet": "S-101",
         "csi": "05 12 00", "basis": "152 LF x 10 lb/ft"}
WALL = {"engine": "walls", "name": "Type 1A wall area", "qty": 900.0,
        "unit": "SF", "status": "taken off", "page": 2, "sheet": "A-101",
        "csi": "09 21 16", "basis": "90 LF x 10 ft high"}
NOTE = {"engine": "work notes", "name": "INSTALL GROUND ROD", "qty": 8,
        "unit": "EA", "status": "taken off", "page": None, "sheet": "E-4",
        "csi": "", "basis": "stated in the work notes on E-4"}
PEND = {"engine": "finishes", "name": "Ceiling ACT-1", "qty": 400.0,
        "unit": "SF", "status": "pending review", "page": 2}


def groups(d, page=None):
    return {(g["name"], g["type"], g["unit"]): g
            for g in estimate.lines(d, page)}


def test_taken_off_quantities_show_in_the_estimate():
    d = doc3()
    assert aq.store(d, res_of(STEEL, WALL, NOTE, PEND)) == 3
    g = groups(d)
    steel = g[("W8x10 beams", "ai", "LB")]
    assert steel["quantity"] == 1520.0 and steel["pages"] == "2"
    assert steel["code"] == "05 12 00"            # CSI carried as the code
    assert steel["unit_cost"] == 0.0 and steel["total"] == 0.0   # no price
    assert g[("INSTALL GROUND ROD", "ai", "EA")]["pages"] == ""
    assert ("Ceiling ACT-1", "ai", "SF") not in g     # still in review
    # one sheet's lines
    assert set(k[0] for k in groups(d, 2)) == {"Type 1A wall area"}


def test_no_price_is_stored():
    d = doc3()
    aq.store(d, res_of(dict(STEEL, unit_cost=12.5, total=99)))
    raw = json.loads(d.embfile_get(aq.FILE).decode("utf-8"))
    assert set(raw["rows"][0]) == {"engine", "name", "qty", "unit", "page",
                                   "sheet", "csi", "basis"}


def test_linked_line_follows_a_rerun():
    d = doc3()
    aq.store(d, res_of(STEEL, WALL), pages=[1, 2])
    ln = el.new_line(desc="Structural steel", unit="LB",
                     link={"name": "W8x10 beams", "type": "ai",
                           "unit": "LB"})
    assert float(el.price(ln, groups(d))["quantity"]) == 1520.0
    # run again on S-101 only: its steel changes, the wall stays
    aq.store(d, res_of(dict(STEEL, qty=1600.0)), pages=[1])
    g = groups(d)
    assert float(el.price(ln, g)["quantity"]) == 1600.0
    assert ("Type 1A wall area", "ai", "SF") in g


def test_review_accept_joins_the_estimate():
    from app import review as rv
    d = doc3()
    res = {"quantities": [dict(STEEL)],
           "review": [{"engine": "finishes", "name": "Ceiling ACT-1",
                       "qty": 400.0, "unit": "SF", "page": 2,
                       "sheet": "A-101", "why": "check the ceiling type"}]}
    aq.store(d, res)
    assert ("Ceiling ACT-1", "ai", "SF") not in groups(d)
    item = rv.queue(res)[0]
    rv.accept(res, item, who="Made Up Person", log_path=None)
    aq.store(d, res)
    assert ("Ceiling ACT-1", "ai", "SF") in groups(d)
    basis = [r["basis"] for r in aq.rows(d) if r["name"] == "Ceiling ACT-1"]
    assert basis == ["accepted as found in review"]     # no name kept


def test_bad_rows_from_a_pdf_are_skipped():
    d = doc3()
    rows = [{"name": "ok", "qty": 2, "unit": "EA", "page": 0},
            {"name": "", "qty": 2, "unit": "EA"},
            {"name": "neg", "qty": -1, "unit": "EA"},
            {"name": "bool", "qty": True, "unit": "EA"},
            {"name": "inf", "qty": "inf", "unit": "EA"},
            {"name": "page gone", "qty": 1, "unit": "EA", "page": 99},
            "junk"]
    from app import embfiles
    embfiles.put(d, aq.FILE, json.dumps({"rows": rows}))
    got = aq.rows(d)
    assert [r["name"] for r in got] == ["ok", "page gone"]
    assert got[1]["page"] is None
    embfiles.put(d, aq.FILE, b"not json")
    assert aq.rows(d) == [] and estimate.lines(d) == []


def test_clear_and_empty_store():
    d = doc3()
    assert aq.store(d, {"quantities": []}) == 0
    assert aq.FILE not in d.embfile_names()
    aq.store(d, res_of(STEEL))
    aq.clear(d)
    assert aq.rows(d) == []
