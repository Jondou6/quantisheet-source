"""ClaimIT 0.2.2 (r47 #13): a unit cost's material / labor / equipment /
other split is kept, edited and exported. Made-up data only."""
import csv
import dataclasses

import pytest

from quantisheet_claims import model as m, practice
from quantisheet_claims.export import SPLIT_HEAD, build_model, to_csv, to_xlsx


def test_scaled_keeps_proportions_and_adds_up():
    uc = m.UnitCost(material=600, labor=300, equipment=100, other=0)
    s = uc.scaled(2000)
    assert (s.material, s.labor, s.equipment, s.other) == (1200, 600, 200, 0)
    odd = uc.scaled(1001)
    assert odd.total == 1001 and odd.material >= odd.labor > odd.equipment
    assert uc.scaled(uc.total) is uc
    assert m.UnitCost().scaled(500) == m.UnitCost(other=500)
    assert uc.scaled(0).total == 0


@pytest.mark.parametrize("new", [1, 7, 333, 99_999, 12_345_678])
def test_scaled_always_sums_exactly(new):
    uc = m.UnitCost(material=333, labor=333, equipment=334, other=1)
    assert uc.scaled(new).total == new


def _split_claim():
    c = practice.claim()
    ln = dataclasses.replace(c.lines[0], unit_cost=m.UnitCost(
        material=150, labor=250, equipment=0, other=0))
    return dataclasses.replace(c, lines=(ln,) + c.lines[1:])


def test_exports_show_the_split(tmp_path):
    from openpyxl import load_workbook
    md = build_model(_split_claim(), printed="2026-11-01", author="Example")
    rows = list(csv.reader(open(to_csv(md, str(tmp_path / "s.csv")),
                                encoding="utf-8-sig")))
    head = next(r for r in rows if r and r[0] == "Structure")
    assert head[-4:] == list(SPLIT_HEAD)
    body = rows[rows.index(head) + 1:]
    assert any(r[-4:] == ["1.50", "2.50", "0.00", "0.00"] for r in body
               if len(r) == len(head))
    wb = load_workbook(to_xlsx(md, str(tmp_path / "s.xlsx")))
    li = wb["Line Items"]
    assert [li.cell(1, c).value for c in range(14, 18)] == list(SPLIT_HEAD)


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_window_cost_split_and_retyped_total(qapp):
    from quantisheet_claims.ui.workspace import ClaimsWindow
    win = ClaimsWindow()
    win.add_claim(_split_claim())
    win.lines_table.setCurrentCell(0, 0)
    assert win.cost_split(["1.00", "2.00", "0.50", "0"])
    uc = win.claim.lines[0].unit_cost
    assert (uc.material, uc.labor, uc.equipment, uc.other) == (100, 200, 50, 0)
    assert win.cost_split(["-1", "0", "0", "0"]) is False
    assert win.cost_split(["x", "0", "0", "0"]) is False
    # a retyped unit cost keeps the split in proportion
    win.lines_table.item(0, 5).setText("7.00")
    qapp.processEvents()
    qapp.processEvents()
    uc = win.claim.lines[0].unit_cost
    assert uc.total == 700 and (uc.material, uc.labor, uc.equipment) == \
        (200, 400, 100)
    win.close()
