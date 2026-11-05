"""Added lines in the Estimate panel (typed quantity, cost book, linked to
a takeoff group) with CSI code, cost type and the Mat / Lab / Eqp / Sub
split; saved in the PDF; fed to the proposal, the Excel and CSV exports,
Sage and the bid build-up. Made-up data only."""
import os
from decimal import Decimal

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import (assemblies, estimate, estimate_lines as EL,     # noqa: E402
                 proposal, sage_export, settings)
from estimate_helpers import area, blank_doc, markup_count       # noqa: E402
from test_gui import ANSWERS, win, qapp                          # noqa: E402,F401


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


SLAB = {"name": "Test slab", "type": "area", "unit": "sq ft"}


def _allowance(doc, qty=1):
    return EL.add(doc, [EL.new_line("Test permit allowance", qty, "ls",
                                    sub="$1,250")])[0]


# ---- the money ---------------------------------------------------------------

def test_allowance_line_totals_and_survives_save(tmp_path):
    d = blank_doc()
    lid = _allowance(d)
    p = EL.priced(d)[0]
    assert p["total"] == Decimal("1250.00")
    assert EL.total(EL.priced(d)) == Decimal("1250.00")
    assert p["kind"] == "Subcontract"
    EL.update(d, lid, qty="2")
    assert EL.priced(d)[0]["total"] == Decimal("2500.00")
    path = str(tmp_path / "job.pdf")
    d.save(path)
    d.close()
    d = fitz.open(path)
    lines = EL.read(d)
    assert len(lines) == 1 and lines[0]["desc"] == "Test permit allowance"
    assert Decimal(lines[0]["qty"]) == 2
    assert EL.priced(d)[0]["total"] == Decimal("2500.00")
    assert EL.FILE in d.embfile_names()          # with the drawings


def test_split_columns_add_up_to_the_total():
    p = EL.price(EL.new_line("Test topping", 100, "sf", mat="1.20",
                             lab="0.90", eqp="0.40"))
    assert p["unit_cost"] == Decimal("2.50")
    assert p["total"] == Decimal("250.00")
    assert sum(p["ext"].values()) == p["total"]
    assert p["ext"] == {"mat": Decimal("120.00"), "lab": Decimal("90.00"),
                        "eqp": Decimal("40.00"), "sub": Decimal("0.00")}
    assert p["kind"] == "Mixed"


def test_no_float_drift():
    d = blank_doc()
    EL.add(d, [EL.new_line(f"Test item {i}", 1, "ea", mat="0.10")
               for i in range(3)] +
           [EL.new_line("Test thirds", 3, "ea", mat="0.3333")])
    rows = EL.priced(d)
    assert EL.total(rows) == Decimal("1.30")           # 0.30 + 1.00 (0.9999)
    assert all(isinstance(r["total"], Decimal) for r in rows)
    split = EL.by_type(rows)
    assert sum(split.values()) == EL.total(rows)


def test_takeoff_line_plus_allowance_is_exact():
    d = blank_doc()
    area(d, "Test slab", 50, 20)                          # 1,000 sf
    estimate.set_price(d, "Test slab", "area", "sq ft", unit_cost=2.50,
                       code="033113", cost_type="Material")
    g = estimate.lines(d)[0]
    assert g["code"] == "03 31 13" and g["cost_type"] == "Material"
    _allowance(d)
    from app.dmoney import cents
    grand = sum((cents(x["total"]) for x in estimate.lines(d)),
                Decimal("0.00")) + EL.total(EL.priced(d))
    assert grand == Decimal("3750.00")


def test_bad_values_are_refused_not_zeroed():
    d = blank_doc()
    lid = _allowance(d)
    for bad in ("twelve", "1.2O", "inf"):
        with pytest.raises(EL.LineError):
            EL.update(d, lid, qty=bad)
    with pytest.raises(EL.LineError):
        EL.update(d, lid, cost_type="Bananas")
    assert Decimal(EL.read(d)[0]["qty"]) == 1


def test_linked_line_follows_its_group_and_refuses_typed_quantity():
    d = blank_doc()
    area(d, "Test slab", 50, 20)
    lid = EL.add(d, [EL.new_line("Test slab finish", 0, "sf", mat="2.10",
                                 code="03 31 13.35", link=SLAB)])[0]
    p = EL.priced(d)[0]
    assert p["quantity"] == Decimal("1000") and p["linked"]
    assert p["total"] == Decimal("2100.00")
    area(d, "Test slab", 20, 10, x0=700)               # another 200 sf
    p = EL.priced(d)[0]
    assert p["quantity"] == Decimal("1200")
    assert p["total"] == Decimal("2520.00")
    with pytest.raises(EL.LineError):
        EL.update(d, lid, qty=5)
    # a linear group can't feed a line priced per sf
    assert EL.link_problem({"name": "Curb", "type": "length", "unit": "ft"},
                           "sf")
    assert not EL.link_problem(SLAB, "sf")


def test_delete_removes_lines_never_markups():
    d = blank_doc()
    area(d, "Test slab", 50, 20)
    n0 = markup_count(d)
    ids = [_allowance(d), EL.add(d, [EL.new_line(
        "Test slab line", 0, "sf", mat=1, link=SLAB)])[0]]
    assert EL.delete(d, ids) == 2
    assert EL.read(d) == [] and markup_count(d) == n0
    assert estimate.lines(d)[0]["quantity"] == pytest.approx(1000)


def test_damaged_data_in_a_pdf_is_skipped():
    d = blank_doc()
    from app import embfiles
    embfiles.put(d, EL.FILE, b'{"lines": [{"desc": "Test ok", "qty": "2", '
                 b'"sub": "5"}, 7, {"qty": "lots", "mat": [1]}, '
                 b'{"desc": "Test dup", "id": "x"}, {"id": "x"}]}')
    lines = EL.read(d)
    assert len(lines) == 4
    assert len({x["id"] for x in lines}) == 4
    assert EL.priced(d)[0]["total"] == Decimal("10.00")
    embfiles.put(d, EL.FILE, b"not json")
    assert EL.read(d) == []


# ---- the rest of the program sees them ----------------------------------------

def _priced_job():
    d = blank_doc()
    EL.add(d, [EL.new_line("Test permit allowance", 1, "ls",
                           code="01 41 26", sub=1250),
               EL.new_line("Test topping", 100, "sf", code="03 53 00",
                           mat="1.20", lab="0.90", eqp="0.40")])
    return d


def test_rollup_proposal_and_bid_buildup_include_added_lines():
    d = _priced_job()
    rows, totals, errors = assemblies.rollup(d)
    added = [r for r in rows if r.get("added")]
    assert {r["name"] for r in added} == {"Test permit allowance",
                                          "Test topping"}
    assert totals["total"] == pytest.approx(1500.0)
    assert not assemblies.rollup(d, added=False)[0]
    data = dict(proposal.defaults(d), tax=10, overhead=0, profit=0)
    pr = proposal.price(d, data)
    # tax on the material only (120.00), not on labor, equipment or sub
    assert pr["tax"] == pytest.approx(12.0)
    assert pr["total"] == pytest.approx(1512.0)
    assert sum(ln["price"] for ln in pr["lines"]) == pytest.approx(1512.0)


def test_sage_and_csv_exports_include_added_lines(tmp_path):
    d = _priced_job()
    rows, problems = sage_export.job_cost_rows(EL.sage_lines(d), job="T-1")
    got = {(r["Cost Code"], r["Category"]): r["Amount"] for r in rows}
    assert got == {("01-4126", "S"): Decimal("1250.00"),
                   ("03-5300", "M"): Decimal("120.00"),
                   ("03-5300", "L"): Decimal("90.00"),
                   ("03-5300", "E"): Decimal("40.00")}
    assert not problems
    path = str(tmp_path / "e.csv")
    estimate.export_csv(d, path)
    text = open(path, encoding="utf-8-sig").read()
    assert "Added Lines" in text and "Test permit allowance" in text
    assert "Grand Total" in text and "1500.0" in text
    xlsx = str(tmp_path / "e.xlsx")
    assemblies.export_xlsx(d, xlsx)
    import openpyxl
    ws = openpyxl.load_workbook(xlsx)["Estimate Summary"]
    names = [r[2] for r in ws.iter_rows(values_only=True)]
    assert "Test permit allowance" in names and "Test topping" in names


def test_location_lines_only_when_the_cost_book_offers_them(monkeypatch):
    from app import costbook
    monkeypatch.setattr(costbook, "location_adjustment",
                        lambda m, l, e, r: {"materials": m * 0.10,
                                            "labor": l * 0.20,
                                            "equipment": 0.0, "found": True},
                        raising=False)
    rows = EL.location_lines(Decimal("10000"), Decimal("6000"),
                             Decimal("3000"), Decimal("1000"), "Testville")
    assert rows == [("Base estimate", Decimal("10000.00")),
                    ("Location adjustment (+12.0%)", Decimal("1200.00")),
                    ("Grand total", Decimal("11200.00"))]
    monkeypatch.setattr(costbook, "location_adjustment",
                        lambda *a: 1 / 0, raising=False)
    assert EL.location_lines(Decimal(1), 1, 0, 0, "x") == []
    monkeypatch.delattr(costbook, "location_adjustment", raising=False)
    assert EL.location_lines(Decimal(1), 1, 0, 0, "x") == []


# ---- the Estimate panel ---------------------------------------------------------

def _rows_of(e):
    return [g for k, g in e.kinds if k == "added"]


def test_panel_add_line_type_quantity_save_reopen(win, tmp_path):
    e = win.estimate
    lid = e.add_line(desc="Test permit allowance", qty=1, unit="ls",
                     sub="1250")
    assert lid
    p = _rows_of(e)[0]
    assert p["total"] == Decimal("1250.00")
    assert "$1,250.00" in e.total.text()
    r = e._row_of(lid)
    assert e.table.item(r, e.C_TOTAL).text() == "1,250.00"
    e.table.item(r, e.C_QTY).setText("2")              # typed in the table
    r = e._row_of(lid)
    assert e.table.item(r, e.C_TOTAL).text() == "2,500.00"
    assert "$2,500.00" in e.total.text()
    ANSWERS["save"] = str(tmp_path / "saved.pdf")
    assert win.save_as()
    d = fitz.open(str(tmp_path / "saved.pdf"))
    lines = EL.read(d)
    assert [(x["desc"], Decimal(x["qty"])) for x in lines] == [
        ("Test permit allowance", Decimal(2))]
    d.close()


def test_panel_takeoff_line_plus_allowance(win):
    v, e = win._view, win.estimate
    area(v.doc, "Test slab", 50, 20)
    e.refresh()
    e.set_price("Test slab", "area", "sq ft", unit_cost=2.50)
    e.add_line(desc="Test permit allowance", qty=1, unit="ls", sub=1250)
    assert "$3,750.00" in e.total.text()


def test_panel_split_and_columns(win):
    e = win.estimate
    lid = e.add_line(desc="Test topping", qty=100, unit="sf")
    r = e._row_of(lid)
    for col, v in ((e.C_MAT, "1.20"), (e.C_LAB, "0.90"), (e.C_EQP, "0.40")):
        e.table.item(e._row_of(lid), col).setText(v)
    r = e._row_of(lid)
    assert e.table.item(r, e.C_UC).text() == "2.50"
    assert e.table.item(r, e.C_TOTAL).text() == "250.00"
    assert e.table.horizontalHeaderItem(e.C_CODE).text() == "Code"
    for name in ("Code", "Description", "Cost Type", "Mat", "Lab", "Eqp",
                 "Sub", "Unit Cost", "Total"):
        assert name in e.COLS
    # a bad number is refused with a message, the line keeps its value
    e.table.item(r, e.C_MAT).setText("1.2O")
    assert e.msg.text() and "1.2O" in e.msg.text()
    assert e.table.item(e._row_of(lid), e.C_MAT).text() == "1.20"
    # code and cost type
    e.table.item(e._row_of(lid), e.C_CODE).setText("035300")
    e.table.item(e._row_of(lid), e.C_CTYPE).setText("Material")
    ln = EL.get(win._view.doc, lid)
    assert ln["code"] == "03 53 00" and ln["cost_type"] == "Material"


def test_panel_delete_asks_cancel_ok_undo_keeps_markups(win, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    v, e = win._view, win.estimate
    area(v.doc, "Test slab", 50, 20)
    win._doc_edited()
    n0 = markup_count(v.doc)
    a = e.add_line(desc="Test line A", qty=1, sub=10)
    b = e.add_line(desc="Test line B", qty=1, sub=20)
    asked = []
    answer = [QMessageBox.Cancel]
    monkeypatch.setattr(QMessageBox, "question", staticmethod(
        lambda *x, **k: (asked.append(x[2]), answer[0])[1]))
    e.select_lines([a, b])
    assert e.delete_selected() == 0
    assert asked == ["Delete 2 line(s)?"]
    assert len(EL.read(v.doc)) == 2
    answer[0] = QMessageBox.Ok
    e.select_lines([a, b])
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    e.table.setFocus()
    QTest.keyClick(e.table, Qt.Key_Delete)           # the Delete key
    assert len(asked) == 2 and EL.read(v.doc) == []
    assert markup_count(v.doc) == n0
    win.undo()
    assert {x["desc"] for x in EL.read(win._view.doc)} == {"Test line A",
                                                           "Test line B"}
    assert {x["desc"] for x in _rows_of(win.estimate)} == {"Test line A",
                                                           "Test line B"}
    assert markup_count(win._view.doc) == n0
    # a takeoff line can't be deleted here
    e = win.estimate
    e.table.clearSelection()
    e.table.selectRow(0)
    assert e.kinds[0][0] == "takeoff"
    assert e.delete_selected() == 0 and "markups" in e.msg.text()
    assert markup_count(win._view.doc) == n0


def test_panel_linked_quantity_read_only_with_group_tooltip(win, qtbot):
    from PySide6.QtCore import Qt
    v, e = win._view, win.estimate
    assert v.calibrate(100.0, real=10, unit="ft", all_pages=True)
    v.style = {"subject": "Test slab"}
    pts = [fitz.Point(40, 40), fitz.Point(540, 40), fitz.Point(540, 240),
           fitz.Point(40, 240)]                         # 50 x 20 ft
    assert v.commit_points("measure_area", pts)
    e.refresh()
    lid = e.add_line(desc="Test slab finish", qty=0, unit="sf", mat="2.10")
    e.select_lines([lid])
    assert e.link_selected("Test slab")
    r = e._row_of(lid)
    cell = e.table.item(r, e.C_QTY)
    assert not cell.flags() & Qt.ItemIsEditable
    assert "Test slab" in cell.toolTip()
    assert float(cell.text().replace(",", "")) == pytest.approx(1000, abs=0.5)
    # draw 200 sf more in the group: the line follows without reopening
    pts = [fitz.Point(40, 300), fitz.Point(240, 300), fitz.Point(240, 400),
           fitz.Point(40, 400)]                         # 20 x 10 ft
    assert v.commit_points("measure_area", pts)

    def follows():
        p = [g for g in _rows_of(win.estimate) if g["id"] == lid][0]
        return abs(p["quantity"] - 1200) < Decimal("0.5")
    qtbot.waitUntil(follows, timeout=5000)
    p = [g for g in _rows_of(e) if g["id"] == lid][0]
    assert p["total"] == (p["quantity"] * Decimal("2.10")).quantize(
        Decimal("0.01"))


def test_panel_header_sections_sit_over_their_columns(win):
    """Every header label sits over its own column and fits in it, at
    normal size and with 150% text (as at 150% display scaling)."""
    from app.estimate_ui import header_aligned, header_fits
    e = win.estimate
    e.add_line(desc="Test permit allowance", qty=1, unit="ls", sub=1250)
    e.table.resize(1600, 300)
    assert header_aligned(e.table) and header_fits(e.table)
    f = _bigger(e.table.font())
    e.table.setFont(f)
    e.table.horizontalHeader().setFont(f)
    e.refresh()
    assert header_aligned(e.table) and header_fits(e.table)


def _bigger(f):
    """The font at 150% (what 150% display scaling does to text)."""
    if f.pointSizeF() > 0:
        f.setPointSizeF(f.pointSizeF() * 1.5)
    else:
        f.setPixelSize(round(f.pixelSize() * 1.5))
    return f
