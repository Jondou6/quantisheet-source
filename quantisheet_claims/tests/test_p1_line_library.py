"""P1 (claims #4): the user's own line-item library - user codes and
categories, import from the user's CSV, nothing third-party shipped."""
import csv
import os
import pathlib

import pytest

from quantisheet_claims import categories, library, settings


def test_library_starts_empty_and_ships_no_codes():
    assert library.items() == {}
    root = pathlib.Path(library.__file__).parent
    for p in root.rglob("*"):
        if p.suffix.lower() in (".csv", ".json") and "tests" not in p.parts:
            assert "library" not in p.name.lower(), p


def test_user_codes_and_categories():
    c = library.add_category("STUCCO", "Stucco repair", "Exterior")
    assert categories.is_known(c)
    it = library.add_item("ex-stc-1", "Example stucco patch", c, "sf",
                          material=150, labor="2.25")
    assert it["code"] == "EX-STC-1" and it["unit"] == "SF"
    assert it["unit_cost"] == {"material": 150, "labor": 225,
                               "equipment": 0, "other": 0}
    ln = library.line_from("EX-STC-1", qty_q4=20_000)
    assert ln.category == "STUCCO" and ln.unit_cost.total == 375
    assert ln.rc == 750 and ln.origin == "library"
    with pytest.raises(library.LibraryError):
        library.add_item("bad code!", "x")
    with pytest.raises(library.LibraryError):
        library.add_item("EX-2", "Example", "NOPE")
    with pytest.raises(library.LibraryError):
        library.add_item("EX-3", "Example", "OTHER", "EA", other="abc")
    assert library.remove_item("ex-stc-1") and library.items() == {}


def test_import_user_csv_keeps_good_rows(tmp_path):
    p = tmp_path / "mine.csv"
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Code", "Description", "Category", "Unit", "Material",
                    "Labor"])
        w.writerow(["EX-DW-1", "Example drywall hang", "DRYWALL", "SF",
                    "0.55", "$1.10"])
        w.writerow(["EX-PT-1", "Example paint 2 coats", "painting", "sf",
                    "", "0.95"])
        w.writerow(["EX-BAD", "Bad unit", "OTHER", "furlong", "", ""])
        w.writerow(["EX-BAD2", "Bad money", "OTHER", "EA", "lots", ""])
        w.writerow(["", "", "", "", "", ""])
    rep = library.import_csv(str(p))
    assert rep["added"] == 2 and rep["replaced"] == 0
    assert len(rep["errors"]) == 2 and rep["errors"][0].startswith("row 4")
    assert library.items()["EX-DW-1"]["unit_cost"]["labor"] == 110
    rep2 = library.import_csv(str(p))
    assert rep2["replaced"] == 2
    out = tmp_path / "out.csv"
    assert library.export_csv(str(out)) == 2
    rows = list(csv.reader(open(out, encoding="utf-8-sig")))
    assert rows[0][0] == "code" and rows[1][:2] == ["EX-DW-1",
                                                     "Example drywall hang"]
    # the export comes back in unchanged
    settings.set(library.SETTING, {})
    assert library.import_csv(str(out))["added"] == 2


def test_csv_without_header_is_refused(tmp_path):
    p = tmp_path / "x.csv"
    p.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(library.LibraryError):
        library.import_csv(str(p))


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_window_library_dialog_and_add_lines(qapp, tmp_path):
    from quantisheet_claims.ui.workspace import ClaimsWindow, new_claim
    win = ClaimsWindow()
    win.add_claim(new_claim("residential", "EX-1"))
    assert win.add_from_library() is False          # empty: says so
    assert "library is empty" in win.last_error
    dlg = win.library_dialog(show=False)
    assert dlg.add("EX-RF-1", "Example shingle", "ROOFING", "SQ",
                   "310.00") is not None
    assert dlg.new_category("GUTTERS", "Gutters", "Exterior") == "GUTTERS"
    assert dlg.fill() == 1
    n = len(win.claim.lines)
    assert win.add_from_library(["EX-RF-1"])
    ln = win.claim.lines[-1]
    assert len(win.claim.lines) == n + 1 and ln.item_code == "EX-RF-1"
    assert ln.unit == "SQ" and ln.unit_cost.total == 31000
    win.close()
