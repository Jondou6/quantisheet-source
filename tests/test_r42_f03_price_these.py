"""GUI user test r42 F03: an estimate of measured-but-unpriced takeoffs
exported $0 and nothing led to pricing it. Price These lists every
unpriced line; a cost typed there prices it everywhere (made-up data,
the user's own made-up price book - nothing bundled)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz                                                  # noqa: E402

from app import estimate, price_these as pt                  # noqa: E402
from test_gui import win, qapp                               # noqa: E402,F401


def test_suggestion_only_from_the_users_own_book_same_unit():
    book = {"name": "My Book", "items": {
        "C-1": {"desc": "Carpet tile, broadloom", "unit": "SF",
                "material": 3.10, "labor": 0.90},
        "C-2": {"desc": "Carpet tile", "unit": "SY", "material": 30.0}}}
    s = pt.suggest({"name": "Carpet", "unit": "sq ft"}, [book])
    assert s and abs(s[0] - 4.0) < 1e-9 and "C-1" in s[1]
    assert pt.suggest({"name": "Area", "unit": "sq ft"}, [book]) is None
    assert pt.suggest({"name": "Base", "unit": "ft"}, [book]) is None
    assert pt.suggest({"name": "Carpet", "unit": "sq ft"}, []) is None


def test_price_these_prices_the_lines(win, monkeypatch):
    v = win._view
    assert v.calibrate(240.0, real=24, unit="ft", all_pages=False)
    v.style["subject"] = "Carpet"
    v.tool = "measure_area"
    v.commit_points("measure_area", [fitz.Point(100, 100),
                                     fitz.Point(200, 100),
                                     fitz.Point(200, 200)])
    lines = pt.unpriced_lines(v.doc)
    assert [g["name"] for g in lines] == ["Carpet"]
    dlg = win.price_these(show=False)
    assert dlg.table.rowCount() == 1
    dlg.table.item(0, 3).setText("$4.25")
    assert dlg.save() == 1
    g = next(x for x in estimate.lines(v.doc) if x["name"] == "Carpet")
    assert g["unit_cost"] == 4.25 and g["total"] > 0
    assert pt.unpriced_lines(v.doc) == []
    assert win.price_these(show=False) is None        # nothing left
