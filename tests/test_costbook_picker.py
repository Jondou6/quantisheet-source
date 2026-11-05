"""Add From Cost Book: a CSI division tree, search, the Basis filter,
checkboxes and 'Add N item(s) to Estimate'; lines can follow a takeoff
group. Made-up 'Test Book' only."""
import os
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtWidgets")

from app import assemblies, estimate_lines as EL, settings     # noqa: E402
from app.estimate_ui import (CostBookPicker, header_aligned,    # noqa: E402
                             header_fits)
from estimate_helpers import area, blank_doc, make_book          # noqa: E402
from test_gui import win, qapp                                  # noqa: E402,F401


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    os.makedirs(settings.DIR, exist_ok=True)


@pytest.fixture
def picker(qapp, qtbot):
    doc = blank_doc()
    area(doc, "Test slab", 50, 20)                       # 1,000 sf
    dlg = CostBookPicker(doc, None, book=make_book())
    qtbot.addWidget(dlg)
    return dlg


def test_tree_shows_only_the_books_divisions(picker):
    assert picker.book.name == "Test Book"
    assert picker.division_counts() == {"01": 1, "03": 1, "09": 1}
    assert len(picker.visible_codes()) == 3
    assert picker.select_division("09")
    assert picker.visible_codes() == ["09 29 10.30"]
    assert picker.select_division(None)
    assert len(picker.visible_codes()) == 3


def test_search_and_basis_filter(picker):
    picker.search.setText("gyp")
    assert picker.visible_codes() == ["09 29 10.30"]
    picker.search.setText("")
    assert len(picker.visible_codes()) == 3
    # the Basis filter is kept: only the kinds the book has, plus All
    kinds = [picker.basis.itemText(i) for i in range(picker.basis.count())]
    assert kinds[0] == "All"


def test_basis_filter_narrows(qapp, qtbot):
    b = make_book()
    b.items["09 29 10.30"]["basis"] = "allowance"
    dlg = CostBookPicker(blank_doc(), None, book=b)
    qtbot.addWidget(dlg)
    i = dlg.basis.findData("allowance")
    assert i > 0
    dlg.basis.setCurrentIndex(i)
    assert dlg.visible_codes() == ["09 29 10.30"]


def test_ticking_counts_and_adds_exactly_those_lines(picker):
    assert picker.add_button.text() == "Add 0 item(s) to Estimate"
    assert not picker.add_button.isEnabled()
    picker.set_checked("03 31 13.35")
    picker.set_checked("09 29 10.30")
    assert picker.add_button.text() == "Add 2 item(s) to Estimate"
    picker.set_checked("09 29 10.30", False)
    assert picker.add_button.text() == "Add 1 item(s) to Estimate"
    picker.set_checked("01 54 33.10")
    # ticks survive a search that hides them
    picker.search.setText("slab")
    assert picker.add_button.text() == "Add 2 item(s) to Estimate"
    picker.add_button.click()
    lines = EL.read(picker.doc)
    assert [(x["code"], x["desc"], x["unit"], Decimal(x["mat"]))
            for x in lines] == [
        ("01 54 33.10", "Test scaffold", "mo", Decimal("300")),
        ("03 31 13.35", "Test slab", "sf", Decimal("2.10"))]
    assert all(x["source"] == "Test Book" for x in lines)
    assert len(picker.added_ids) == 2


def test_linked_to_a_takeoff_group_follows_the_markups(picker):
    picker.set_checked("03 31 13.35")
    assert picker.set_link("Test slab")
    picker.add_button.click()
    p = EL.priced(picker.doc)[0]
    assert p["linked"] and p["quantity"] == Decimal("1000")
    assert p["total"] == Decimal("2100.00")
    area(picker.doc, "Test slab", 20, 10, x0=700)        # another 200 sf
    p = EL.priced(picker.doc)[0]
    assert p["quantity"] == Decimal("1200")
    assert p["total"] == Decimal("2520.00")


def test_link_refused_when_units_differ(qapp, qtbot):
    doc = blank_doc()
    from app import annotate
    annotate.apply_op(doc, annotate.new_op(
        "add_polyline", 0, pts=[[40, 40], [240, 40]],
        measure={"type": "length", "value": 20.0, "unit": "ft",
                 "group": "Test curb"}))
    dlg = CostBookPicker(doc, None, book=make_book())
    qtbot.addWidget(dlg)
    dlg.set_checked("03 31 13.35")
    assert dlg.set_link("Test curb")
    assert dlg.add_to_estimate() == []
    assert "Can't link" in dlg.note.text()
    assert EL.read(doc) == []


def test_from_the_panel_lines_show_in_the_estimate(win, monkeypatch):
    from PySide6.QtWidgets import QDialog
    e = win.estimate
    book = make_book()

    def run(dlg):
        dlg.set_checked("09 29 10.30")
        dlg.add_to_estimate()
        return QDialog.Accepted
    monkeypatch.setattr(CostBookPicker, "exec", run)
    dlg = e.add_from_cost_book(book=book)
    assert dlg.added_ids
    rows = [g for k, g in e.kinds if k == "added"]
    assert [(g["code"], g["desc"], g["unit_cost"]) for g in rows] == [
        ("09 29 10.30", "Test gyp board", Decimal("0.55"))]


def test_no_document_does_not_block(qapp, qtbot):
    dlg = CostBookPicker(None, None, book=make_book())
    qtbot.addWidget(dlg)
    dlg.set_checked("03 31 13.35")
    assert not dlg.add_button.isEnabled()
    assert dlg.add_to_estimate() == []


def test_headers_sit_over_their_columns_at_100_and_150_percent(picker,
                                                               qtbot):
    picker.resize(1200, 600)
    picker.show()
    qtbot.waitExposed(picker)
    assert header_aligned(picker.table) and header_fits(picker.table)
    f = _bigger(picker.font())
    picker.setFont(f)
    picker.table.horizontalHeader().setFont(f)
    picker.fill()
    assert header_aligned(picker.table) and header_fits(picker.table)


def _bigger(f):
    """The font at 150% (what 150% display scaling does to text)."""
    if f.pointSizeF() > 0:
        f.setPointSizeF(f.pointSizeF() * 1.5)
    else:
        f.setPixelSize(round(f.pixelSize() * 1.5))
    return f
