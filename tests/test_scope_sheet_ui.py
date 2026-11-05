"""Scope Sheets window (app/pm/scope_sheet_ui.py) with pytest-qt: open the
dialog, add a trade, type amounts (including "(500)") into the grid,
totals and the math check update, paste a block from Excel, leveling,
award, export, delete; opening it with no project never blocks. Made-up
companies and numbers only."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")
pytest.importorskip("pytestqt")

from PySide6.QtCore import Qt                                 # noqa: E402
from PySide6.QtWidgets import (QApplication, QDialog,         # noqa: E402
                               QInputDialog, QMessageBox,
                               QTableWidgetSelectionRange, QWidget)

from app import settings                                      # noqa: E402
from app.pm import scope_sheet as ss                          # noqa: E402
from app.pm import scope_sheet_ui as ui                       # noqa: E402
from app.pm.store import ProjectStore                         # noqa: E402


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache",
                        {"author": "Pat Example",
                         "company": {"name": "Example Builders"}})
    monkeypatch.setenv("QUANTISHEET_NO_OPEN", "1")
    for n in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, n, staticmethod(lambda *a, **k: 0))
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.Yes))
    monkeypatch.setattr(QInputDialog, "getItem",
                        staticmethod(lambda *a, **k: ("", False)))
    s = ProjectStore(str(tmp_path / "Job"))
    s.data["name"] = "Harbor Example"
    s.set_setting("number", "26-101")
    return s


@pytest.fixture
def dlg(qtbot, store):
    d = ui.ScopeSheetsDialog(store)
    qtbot.addWidget(d)
    d.show()
    return d


def text(grid, r, c):
    it = grid.item(r, c)
    return it.text() if it is not None else ""


def test_add_trade_type_amounts_totals_and_math_check(qtbot, dlg, store):
    p = dlg.panel
    assert p.table.rowCount() == 0 and p.empty.isVisibleTo(p)
    sh = p.new_sheet("09 29 00", "Drywall & framing")
    assert p.table.rowCount() == 1
    assert p.table.item(0, 1).text() == "Drywall & framing"
    ed = p.editor
    assert ed.fields["project"].text() == "Harbor Example"
    assert ed.fields["project_no"].text() == "26-101"
    g = ed.grid
    # template order: B:C description, D-G budget, then H/I, J/K ...
    assert g.columnCount() == ui.C_B0 + 2 * ss.DEFAULT_BIDDERS
    h, i = ui._bidder_col(0)
    assert ed.commit_text(ui.R_COMPANY, h, "Example Drywall LLC") == ""
    assert ed.commit_text(ui.R_PRICE, h, "$2,400.00") == ""
    # typing in the blank last row adds a scope line
    ed.commit_text(ed.row_new(), ui.C_DESC, "Metal stud framing")
    ed.commit_text(ed.row_new(), ui.C_DESC, "Credit: owner-furnished doors")
    assert ed.n_lines() == 2
    r1, r2 = ui.R_LINE0, ui.R_LINE0 + 1
    ed.commit_text(r1, ui.C_QTY, "1,000")
    ed.commit_text(r1, ui.C_UPRICE, "$2.875")
    assert text(g, r1, ui.C_TOTAL) == "$2,875.00"
    ed.commit_text(r1, i, "2,900")
    ed.commit_text(r2, i, "(500)")
    assert text(g, r2, i) == "($500.00)"
    assert sh["lines"][1]["bids"][sh["bidders"][0]["id"]]["amount"] == -50000
    assert text(g, ed.row_total(), i) == "$2,400.00"
    assert text(g, ed.row_check(), i) == "$0.00"
    ok_bg = g.item(ed.row_check(), i).background().color()
    # the price no longer matches the lines: math check turns red
    ed.commit_text(ui.R_PRICE, h, "2,500")
    assert text(g, ed.row_check(), i) == "$100.00"
    bad_bg = g.item(ed.row_check(), i).background().color()
    assert bad_bg == ui.BAD_BG and bad_bg != ok_bg
    assert "don't add up" in ed.summary.text()
    # unreadable input is refused and the cell keeps its value
    assert ed.commit_text(r1, i, "twenty") != ""
    assert text(g, r1, i) == "$2,900.00"
    # blank is "not priced", 0 is $0.00
    ed.commit_text(r1, i, "0")
    assert text(g, r1, i) == "$0.00"
    ed.commit_text(r1, i, "")
    assert text(g, r1, i) == ""
    # saved to the project
    store.flush()
    rec = ss.list_sheets(store)[0]
    assert rec["bidders"][0]["company"] == "Example Drywall LLC"
    assert rec["bidders"][0]["price"] == 250000


def test_typing_in_the_grid(qtbot, dlg):
    p = dlg.panel
    p.new_sheet("09 29 00", "Drywall & framing")
    ed = p.editor
    g = ed.grid
    ed.commit_text(ed.row_new(), ui.C_DESC, "Gypsum board")
    _h, i = ui._bidder_col(0)
    g.setFocus()
    g.setCurrentCell(ui.R_LINE0, i)
    g.edit(g.currentIndex())
    w = g.indexWidget(g.currentIndex()) or QApplication.focusWidget()
    assert w is not None
    w.selectAll()
    qtbot.keyClicks(w, "(500)")
    qtbot.keyClick(w, Qt.Key_Return)
    qtbot.waitUntil(lambda: text(g, ed.row_total(), i) == "($500.00)",
                    timeout=3000)
    assert text(g, ui.R_LINE0, i) == "($500.00)"
    # Enter moved down, like a spreadsheet
    assert g.currentRow() == ui.R_LINE0 + 1


def test_paste_copy_level_award_export_delete(qtbot, dlg, store, tmp_path):
    p = dlg.panel
    sh = p.new_sheet("09 29 00", "Drywall & framing")
    ed = p.editor
    g = ed.grid
    h, i = ui._bidder_col(0)
    h2, i2 = ui._bidder_col(1)
    ed.commit_text(ui.R_COMPANY, h, "Example Drywall LLC")
    ed.commit_text(ui.R_COMPANY, h2, "Test Paving Co")
    # a block copied from Excel (B..K: desc, C, qty, unit, unit $, total,
    # then two bidder blocks), incl. accounting text and a credit
    rows = ["Gypsum board\t\t5000\tSF\t1.25\t$6,250.00\tN\t\tY\t $ 6,000.00 ",
            "Taping\t\t\t\t\t$1,000.00\tY\t750\tY\t(100)"]
    assert ed.paste("\n".join(rows) + "\n", at=(ed.row_new(), 0)) == 0
    assert [ln["desc"] for ln in sh["lines"]] == ["Gypsum board", "Taping"]
    assert sh["lines"][1]["lump"] == 100000
    assert text(g, ed.row_total(), ui.C_TOTAL) == "$7,250.00"
    assert text(g, ed.row_total(), i) == "$750.00"
    assert text(g, ed.row_total(), i2) == "$5,900.00"
    # copy back out: plain numbers, the merged C column empty
    g.setRangeSelected(
        QTableWidgetSelectionRange(ui.R_LINE0, 0, ui.R_LINE0 + 1, i), True)
    out = ed.copy_selection()
    assert out.splitlines()[0] == \
        "Gypsum board\t\t5000\tSF\t1.25\t6250.00\tN\t"
    assert QApplication.clipboard().text() == out
    # leveling: the N line is plugged with the budget, shaded, entries kept
    ed.level.setCurrentIndex(ed.level.findData("budget"))
    assert ed.row_level() is not None
    assert text(g, ed.row_level(), i) == "$7,000.00"
    assert g.item(ui.R_LINE0, i).background().color() == ui.PLUG_BG
    assert ss.bid_cell(sh["lines"][0], sh["bidders"][0]["id"]) == \
        {"flag": "N", "amount": None}
    # award defaults to the bidder's total
    ed.award.setCurrentIndex(ed.award.findData(sh["bidders"][1]["id"]))
    assert sh["award"]["bidder"] == sh["bidders"][1]["id"]
    assert ed.award_amt.placeholderText() == "$5,900.00"
    assert p.table.item(0, 4).text() == "Test Paving Co"
    # lines and bidders
    g.setCurrentCell(ui.R_LINE0 + 1, 0)
    ed.move_line(-1)
    assert sh["lines"][0]["desc"] == "Taping"
    n = len(sh["bidders"])
    ed.add_bidder("Sample Interiors Inc")
    assert len(sh["bidders"]) == n + 1
    assert g.columnCount() == ui.C_B0 + 2 * (n + 1)
    # export, then import the workbook back as a second sheet
    path = p.export_xlsx(str(tmp_path / "scope.xlsx"), open_after=False)
    assert os.path.isfile(path)
    got = p.import_xlsx(path)
    assert len(got) == 1 and p.table.rowCount() == 2
    # duplicate and delete
    p.table.selectRow(0)
    p.duplicate("Painting")
    assert p.table.rowCount() == 3
    assert p.delete() is True
    assert p.table.rowCount() == 2


def test_no_project_does_not_block(qtbot, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {})
    monkeypatch.setattr(QDialog, "exec", lambda self, *a: 0)

    class Main(QWidget):
        _path = str(tmp_path / "loose.pdf")
    m = Main()
    qtbot.addWidget(m)
    assert ui.open_for_window(m) is None


def test_open_for_the_drawings_project_and_center_page(qtbot, store, tmp_path):
    class Main(QWidget):
        _path = os.path.join(store.folder, "A-101.pdf")
    store.flush(force=True)
    m = Main()
    qtbot.addWidget(m)
    w = ui.open_for_window(m)
    assert isinstance(w, ui.ScopeSheetsDialog)
    assert w.store.folder == store.folder
    w.close()

    class Center:
        pass
    c = Center()
    c.store = store
    page = ui.ScopeSheetsPage(c)
    qtbot.addWidget(page)
    page.refresh()
    assert page.panel.table.rowCount() == 0
