"""r36 v2 step 7 (G4.3): Price a Workbook... - an Estimate Workbook made
by QuantiSheet (AI Takeoff > Estimate Workbook) priced from YOUR cost
books into a NEW file '<name> - priced.xlsx'. The original is never
changed or overwritten; only the rate cells (H labor hours, I wages, L
material rate, N equipment rate) of ticked lines are filled, with the
source in NOTES; formulas and waste stay. A workbook of another layout is
refused. Made-up data only; the database is a temporary one."""
import glob
import hashlib
import os

import openpyxl
import pytest

from app import assemblies, costbook, estimate_book, pricedb, settings  # noqa
from app.estimating import _io, boq, workbook_pricer as WP          # noqa: E402

from test_r36_rate_matcher import BOOK, _isolated                  # noqa: F401


def _wb(tmp_path, name="Job.xlsx"):
    p = str(tmp_path / name)
    estimate_book.write(p, [
        {"div": "09", "ref": "A1", "description": "Gypsum board 5/8 in",
         "qty": 200.0, "unit": "SF", "status": "taken off", "note": ""},
        {"div": "09", "ref": "A2", "description": "Resilient tile flooring",
         "qty": 90.0, "unit": "SF", "status": "taken off", "note": ""},
        {"div": "09", "ref": "A3", "description": "Paint walls",
         "qty": 50.0, "unit": "SF", "status": "taken off", "note": ""},
        {"div": "06", "ref": "A4", "description": "Carpentry, rough",
         "qty": 10.0, "unit": "LF", "status": "taken off", "note": ""},
        {"div": "09", "ref": "A5", "description": "=cmd|' /C calc'!A0",
         "qty": 1.0, "unit": "EA", "status": "review", "note": "check"}],
        project="Test job", general=False)
    return p


def _sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


def _row(ws, desc):
    for r in range(11, ws.max_row + 1):
        if ws.cell(r, 3).value == desc:
            return r
    raise KeyError(desc)


def test_reads_and_matches_a_quantisheet_workbook(tmp_path):
    pricedb.save_book(costbook.Book(BOOK).to_dict())
    p = _wb(tmp_path)
    lines = WP.read_workbook(p)
    assert [ln["desc"] for ln in lines][:4] == [
        "Carpentry, rough", "Gypsum board 5/8 in", "Resilient tile flooring",
        "Paint walls"]
    res = WP.match(lines, boq.read_books())
    by = {r["target"]["name"]: r for r in res["rows"]}
    assert by["Gypsum board 5/8 in"]["ticked"]
    assert by["Resilient tile flooring"]["unit_cost"] == pytest.approx(3)
    assert by["Carpentry, rough"]["status"] == "fuzzy"
    assert not by["Carpentry, rough"]["ticked"]
    assert res["counts"] == {"exact": 3, "fuzzy": 1, "none": 1}


def test_writes_a_new_priced_copy_and_keeps_formulas(tmp_path):
    pricedb.save_book(costbook.Book(BOOK).to_dict())
    p = _wb(tmp_path)
    before = _sha(p)
    res = WP.match(WP.read_workbook(p), boq.read_books())
    out = WP.write_priced(p, res["rows"])
    assert out["path"] == str(tmp_path / "Job - priced.xlsx")
    assert _sha(p) == before                         # original untouched
    ws = openpyxl.load_workbook(out["path"])["BASE BID"]
    g = _row(ws, "Gypsum board 5/8 in")
    assert ws.cell(g, 12).value == pytest.approx(0.6)          # L
    assert ws.cell(g, 13).value.startswith("=")                # M formula
    assert ws.cell(g, 7).value.startswith("=")                 # waste qty
    assert "Test Rates 09 29 00" in ws.cell(g, 18).value
    t = _row(ws, "Resilient tile flooring")
    assert ws.cell(t, 12).value == pytest.approx(3.0)
    c = _row(ws, "Carpentry, rough")
    assert ws.cell(c, 12).value is None                         # not ticked
    pw = _row(ws, "Paint walls")                                # has sub
    assert ws.cell(pw, 12).value is None
    assert [s["name"] for s in out["skipped"]] == ["Paint walls"]
    assert "sub" in out["skipped"][0]["why"].lower()
    assert out["filled"] == 2
    bad = _row(ws, "'=cmd|' /C calc'!A0")
    assert not str(ws.cell(bad, 18).value or "").startswith("=")
    assert not glob.glob(str(tmp_path / "*.part"))
    out2 = WP.write_priced(p, res["rows"])                      # never over
    assert out2["path"] == str(tmp_path / "Job - priced (2).xlsx")


def test_refuses_a_foreign_workbook_and_typed_rates_stay(tmp_path):
    pricedb.save_book(costbook.Book(BOOK).to_dict())
    f = tmp_path / "Other.xlsx"
    wb = openpyxl.Workbook()
    wb.active.title = "BASE BID"
    wb.active["A10"] = "Item"
    wb.save(f)
    with pytest.raises(WP.WorkbookError):
        WP.read_workbook(str(f))
    p = _wb(tmp_path)
    wb = openpyxl.load_workbook(p)
    ws = wb["BASE BID"]
    ws.cell(_row(ws, "Gypsum board 5/8 in"), 12, 0.99)        # typed rate
    wb.save(p)
    res = WP.match(WP.read_workbook(p), boq.read_books())
    out = WP.write_priced(p, res["rows"])
    ws = openpyxl.load_workbook(out["path"])["BASE BID"]
    assert ws.cell(_row(ws, "Gypsum board 5/8 in"), 12).value == 0.99
    assert "Gypsum board 5/8 in" in [s["name"] for s in out["skipped"]]


def test_never_inside_the_program_folder(tmp_path):
    pricedb.save_book(costbook.Book(BOOK).to_dict())
    p = _wb(tmp_path)
    res = WP.match(WP.read_workbook(p), boq.read_books())
    with pytest.raises(_io.PathError):
        WP.write_priced(p, res["rows"], dest=os.path.join(
            os.path.dirname(_io.__file__), "x - priced.xlsx"))
