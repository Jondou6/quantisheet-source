"""Nov 3: Leveling Board (#5) and Trade Scope Sheet Builder (#7). Made-up
data only."""
import os
from decimal import Decimal

import fitz
import pytest

from app import estimate_lines as EL
from app.estimating import bidday, levelboard as LB

GROUPS = [{"name": "Gypsum board walls", "unit": "sf", "type": "area",
           "quantity": 1000, "code": "09 21 16", "unit_cost": 2.5},
          {"name": "Acoustic ceiling", "unit": "sf", "type": "area",
           "quantity": 400, "code": "09 51 13", "unit_cost": 4.0},
          {"name": "Concrete slab", "unit": "sf", "type": "area",
           "quantity": 900, "code": "03 30 00", "unit_cost": 6.0}]


@pytest.fixture
def doc(monkeypatch):
    from app import estimate
    monkeypatch.setattr(estimate, "lines", lambda d, page=None: GROUPS)
    d = fitz.open()
    d.new_page()
    return d


def _spec():
    d = fitz.open()
    pg = d.new_page()
    y = 60
    for t in ("SECTION 09 21 16 - GYPSUM BOARD ASSEMBLIES", "PART 1 GENERAL",
              "1.1 SECTION INCLUDES", "A. Gypsum board walls",
              "B. Fire-rated shaft walls", "C. Sound attenuation blankets",
              "1.2 SUBMITTALS", "A. Product data", "PART 2 PRODUCTS",
              "A. Corner beads and trim", "END OF SECTION"):
        pg.insert_text((50, y), t, fontsize=9)
        y += 14
    return d


def test_scope_sheet_from_takeoff_and_specs(doc, tmp_path):
    assert set(LB.trades(doc)) == {"09", "03"}
    sheet = LB.scope_sheet(doc, "09", _spec())
    descs = [r["desc"] for r in sheet["rows"]]
    assert descs[:2] == ["Gypsum board walls", "Acoustic ceiling"]
    assert "Fire-rated shaft walls" in descs
    assert "Corner beads and trim" in descs
    assert "Product data" not in descs           # submittals aren't scope
    assert descs.count("Gypsum board walls") == 1
    p = LB.scope_csv(sheet, str(tmp_path / "s.csv"))
    assert "Fire-rated shaft walls" in open(p, encoding="utf-8").read()


def test_board_colors_plugs_and_low(doc):
    sheet = LB.scope_sheet(doc, "09")
    pkg = LB.start_board(doc, sheet)
    parsed_a = {"bidder": "Acme Drywall", "lines": [
        {"desc": "Gypsum board walls", "amount": 2400.0},
        {"desc": "Acoustical ceilings and grid", "amount": 1500.0}],
        "exclusions": []}
    parsed_b = {"bidder": "Bravo Interiors", "lines": [
        {"desc": "Gypsum board walls", "amount": 2200.0}],
        "exclusions": ["Acoustic ceiling"]}
    a = LB.import_quote(doc, pkg, parsed=parsed_a)
    assert a["matched"] == ["1"] and a["unclear"] == ["2"]
    b = LB.import_quote(doc, pkg, parsed=parsed_b)
    assert b["excluded"] == ["2"]
    d = LB.board(doc, pkg)
    row2 = d["rows"][1]
    assert row2["plug"] == Decimal("1600.00")            # 400 sf x $4.00
    assert row2["cells"]["Acme Drywall"]["status"] == LB.YELLOW
    assert row2["cells"]["Bravo Interiors"]["status"] == LB.RED
    tot = {t["name"]: t["total"] for t in d["bidders"]}
    assert tot["Bravo Interiors"] == Decimal("3800.00")  # 2200 + our 1600
    assert tot["Acme Drywall"] == Decimal("3900.00")
    assert d["low"] == "Bravo Interiors"
    LB.set_status(doc, pkg, "Acme Drywall", "2", LB.GREEN)
    assert LB.board(doc, pkg)["rows"][1]["cells"]["Acme Drywall"][
        "status"] == LB.GREEN
    got = LB.use_low(doc, pkg)
    assert got["bidder"] == "Bravo Interiors"
    assert EL.priced(doc) and sum(p["total"] for p in EL.priced(doc)) == \
        Decimal("3800.00")


def test_board_window(doc, tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app.estimating import levelboard_ui
    w = levelboard_ui.LevelBoard(doc)
    assert w.data is None
    sheet = w.new_from_trade("09", ask=False)
    assert w.package() == sheet["trade"] and w.table.rowCount() == 2
    LB.import_quote(doc, w.package(), parsed={
        "bidder": "Acme Drywall", "lines": [
            {"desc": "Gypsum board walls", "amount": 2400.0}],
        "exclusions": []})
    w.refresh()
    assert w.table.columnCount() == len(levelboard_ui.FIXED) + 1
    assert "(plug)" in w.table.item(1, 4).text()
    assert w.export_scope(str(tmp_path / "x.csv"))
    assert w.use_low()["bidder"] == "Acme Drywall"
