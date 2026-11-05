"""r36 v2 step 7: the Estimating Tools window - Estimate vs Actual shows
waste and the quantity / price split and imports an actuals file (preview,
one Undo). Made-up data only."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QDialog                             # noqa: E402

from app import assemblies, estimate, estimate_lines as EL, heavy  # noqa: E402
from app.estimating import actuals, items, ui                     # noqa: E402
from estimate_helpers import area                                  # noqa: E402
from test_gui import ANSWERS, win, qapp                            # noqa: E402,F401
from test_r36_end_to_end import LIB                                # noqa: E402


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(QDialog, "exec", lambda self, *a: 0)
    monkeypatch.setattr(heavy, "library", lambda: LIB)   # no price db


def _heads(t):
    return [t.horizontalHeaderItem(i).text() for i in range(t.columnCount())]


def test_actuals_page_shows_waste_and_imports(win, qapp, tmp_path):
    d = win._view.doc
    area(d, "Test floor", 10, 10)
    estimate.set_price(d, "Test floor", "area", "sq ft", unit_cost=4,
                       waste=10, cost_type="Material", code="09 65 00")
    tid = items.takeoff_id("Test floor", "area", "sq ft")
    pg = ui.open_tools(win, "actuals").page("actuals")
    pg.refresh()
    h = _heads(pg.table)
    assert h[:8] == ["Description", "Unit", "Est. qty", "Actual qty",
                     "Est. cost", "Actual cost", "Variance", "Variance %"]
    assert h[8:] == ["Installed qty", "Measured qty", "Waste % planned",
                     "Waste % actual", "Qty variance", "Price variance"]
    pg.set_actual(tid, qty="105", cost="441", installed="100")
    r = pg.ids.index(tid)
    assert pg.table.item(r, 11).text() == "5.0%"
    assert pg.table.item(r, 10).text() == "10%"
    csvp = tmp_path / "act.csv"
    csvp.write_text("Cost Code,Actual Cost\n09 65 00,500\n99,1\n",
                    encoding="utf-8")
    ANSWERS["open"] = str(csvp)
    pg.import_actuals()
    assert actuals.read(win._view.doc)[tid]["cost"] == "500.00"
    assert "1 item" in pg.msg.text() and "not matched: 1" in pg.msg.text()
    win.undo()
    assert actuals.read(win._view.doc)[tid]["cost"] == "441.00"


def test_import_bad_file_says_so_and_writes_nothing(win, qapp, tmp_path):
    d = win._view.doc
    EL.add(d, [EL.new_line("Test x", 1, "ea", mat=1, code="10 00 00")])
    before = actuals.read(d)
    p = tmp_path / "x.csv"
    p.write_text("foo,bar\n1,2\n", encoding="utf-8")
    ANSWERS["open"] = str(p)
    pg = ui.open_tools(win, "actuals").page("actuals")
    pg.import_actuals()
    assert "nothing was imported" in pg.msg.text()
    assert actuals.read(win._view.doc) == before


def test_match_rates_page_apply_once_and_undo(win, qapp, tmp_path):
    from app import costbook, pricedb
    from test_r36_rate_matcher import BOOK
    pricedb.save_book(costbook.Book(BOOK).to_dict())     # temp test db
    d = win._view.doc
    area(d, "Resilient tile flooring", 10, 10)
    from test_r36_rate_matcher import _line
    _line(d, "Carpentry rough", 30)
    area(d, "Nothing like it", 5, 5, x0=500)
    win._doc_edited()                        # the markups are one step
    pg = ui.open_tools(win, "rates").page("rates")
    pg.refresh()
    assert "exact 1, loose 1, none 1" in pg.msg.text()
    names = [pg.table.item(i, 1).text() for i in range(pg.table.rowCount())]
    r = names.index("Resilient tile flooring")
    from PySide6.QtCore import Qt
    assert pg.table.item(r, 0).checkState() == Qt.Checked
    c = names.index("Carpentry rough")
    assert pg.table.item(c, 0).checkState() == Qt.Unchecked
    pg.apply()
    g = {x["name"]: x for x in estimate.lines(win._view.doc)}
    assert round(g["Resilient tile flooring"]["unit_cost"], 4) == 3.0
    assert "1 group(s) priced" in pg.msg.text()
    win.undo()
    g = {x["name"]: x for x in estimate.lines(win._view.doc)}
    assert g["Resilient tile flooring"]["unit_cost"] == 0
    ANSWERS["save"] = str(tmp_path / "m.json")
    pg.refresh()
    pg.save_matches()
    assert os.path.exists(tmp_path / "m.json")


def test_price_a_workbook_from_the_page(win, qapp, tmp_path):
    from app import costbook, pricedb
    from test_r36_rate_matcher import BOOK
    from test_r36_price_workbook import _wb
    pricedb.save_book(costbook.Book(BOOK).to_dict())
    p = _wb(tmp_path)
    ANSWERS["open"] = p
    pg = ui.open_tools(win, "rates").page("rates")
    pg.price_workbook()
    assert pg.mode == "workbook" and pg.table.rowCount() == 5
    pg.apply()
    assert os.path.exists(tmp_path / "Job - priced.xlsx")
    assert "Job - priced.xlsx" in pg.msg.text()


def test_assembly_rules_page_preview_apply_undo(win, qapp, tmp_path,
                                                monkeypatch):
    from app.estimating import wall_legends as WL
    from test_r36_wall_legend_assemblies import DESCS
    from test_r36_rate_matcher import _line
    d = win._view.doc
    _line(d, "Wall Type 1A", 20)
    area(d, "Floor LVT-1", 10, 10)
    _line(d, "Thing 7", 5, y=600)
    win._doc_edited()
    monkeypatch.setattr(WL, "_read", lambda doc, rows=None: (
        {"1A": DESCS[0] + " H= 10'-0\""}, [0], ""))
    pg = ui.open_tools(win, "assembly_rules").page("assembly_rules")
    ANSWERS["save"] = str(tmp_path / "rules.json")
    pg.write_example()
    assert os.path.exists(tmp_path / "rules.json")
    pg.refresh()
    assert "apply 2" in pg.msg.text() and "needs review 1" in pg.msg.text()
    pg.apply()
    rows, _t, _e = assemblies.rollup(win._view.doc, added=False)
    assert {r["name"] for r in rows} == {"Wall Type 1A", "Floor LVT-1"}
    assert all(r["material"] == 0 for r in rows)
    win.undo()
    rows, _t, _e = assemblies.rollup(win._view.doc, added=False)
    assert rows == []
    pg.legend = None
    pg.build_walls()
    assert "Wall Type 1A" in pg.msg.text() and "VERIFIED 1" in pg.msg.text()
    rows, _t, _e = assemblies.rollup(win._view.doc, added=False)
    assert [r["name"] for r in rows] == ["Wall Type 1A"]
