"""Manufacturers in Specs (Nov 20): each section's listed manufacturers
and basis-of-design products with pages. Made-up company names."""
import csv
import os
import sys

import fitz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import specmfrs  # noqa: E402

try:
    from test_gui import win, qapp  # noqa: F401,E402
except Exception:                                         # noqa: BLE001
    pass

PAGES = [
    "SECTION 08 71 00 - DOOR HARDWARE\nPART 1 - GENERAL\n1.1 SUMMARY\n"
    "A. Section includes hardware.",
    "PART 2 - PRODUCTS\n2.1 MANUFACTURERS\nA. Subject to compliance with "
    "requirements, provide\nproducts by one of the following:\n"
    "1. Example Lock Company.\n2. Sample Hardware Inc.; or approved equal."
    "\n3. Demo Closers LLC\n2.2 HINGES\nA. Provide five-knuckle hinges.\n"
    "08 71 00 - 2",
    "SECTION 09 91 23 - INTERIOR PAINTING\n2.1 PAINT\nA. Basis-of-Design "
    "Product: Model Paint Co., Pro Line 200. No substitutions.",
]


def _spec(path):
    d = fitz.open()
    for t in PAGES:
        pg = d.new_page()
        y = 72
        for line in t.splitlines():
            pg.insert_text((72, y), line, fontsize=10)
            y += 14
    d.save(path)
    d.close()


def test_listed_and_basis_of_design(tmp_path):
    p = tmp_path / "spec.pdf"
    _spec(str(p))
    rows = specmfrs.find(fitz.open(str(p)))
    got = [(r["section"], r["manufacturer"], r["kind"], r["page"])
           for r in rows]
    assert got == [("08 71 00", "Example Lock Company", "listed", 1),
                   ("08 71 00", "Sample Hardware Inc", "listed", 1),
                   ("08 71 00", "Demo Closers LLC", "listed", 1),
                   ("09 91 23", "Model Paint Co., Pro Line 200", "basis",
                    2)]
    assert rows[0]["title"] == "Door Hardware" and rows[3]["no_subs"]
    out = specmfrs.to_csv(rows, str(tmp_path / "m.csv"))
    lines = list(csv.reader(open(out, encoding="utf-8")))
    assert lines[0][2] == "Manufacturer / product" and len(lines) == 5
    assert lines[4][3] == "basis of design" and lines[4][5] == "yes"


def test_window(win, tmp_path):
    p = tmp_path / "spec.pdf"
    _spec(str(p))
    assert win.open_path(str(p))
    dlg = win.spec_manufacturers(show=False)
    assert dlg.table.rowCount() == 4
    row = [dlg.table.item(i, 2).text() for i in range(4)].index(
        "Model Paint Co., Pro Line 200")
    dlg.go(row)
    assert win._view.page == 2
    assert os.path.exists(dlg.export(str(tmp_path / "x.csv")))
