"""Nov 11, bidding phase C: each bidder line by line against our own
estimate. Made-up numbers only."""
import os
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import settings, variance as V                          # noqa: E402
from app.pm import scope_sheet as ss                             # noqa: E402

ROWS = [
    {"id": "1", "desc": "Pipe", "ours": 5400000, "cells": {
        "A": (V.PRICED, 6300000), "B": (V.PRICED, 5000000),
        "C": (V.NA, None)}},
    {"id": "2", "desc": "Manholes", "ours": 2520000, "cells": {
        "A": (V.MISSING, None), "B": (V.PRICED, 0), "C": (V.NA, None)}},
    {"id": "3", "desc": "Extra", "ours": None, "cells": {
        "A": (V.PRICED, 100001), "B": (V.MISSING, None),
        "C": (V.NA, None)}},
    {"id": "4", "desc": "Testing", "ours": 333333, "cells": {
        "A": (V.INCLUDED, None), "B": (V.PRICED, 333333),
        "C": (V.NA, None)}}]


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {})


def _b(res, name):
    return next(b for b in res["bidders"] if b["name"] == name)


def test_rows_add_up_to_the_total_to_the_cent():
    res = V.compare(ROWS, ["A", "B", "C"], 15)
    assert res["ours"] == 8253333
    a = _b(res, "A")
    assert a["leveled"] == 6400001 + 2520000
    assert a["var_total"] == a["leveled"] - res["ours"] == 666668
    assert a["var_total"] == a["var_rows"] + a["no_estimate"] - a["included"]
    b = _b(res, "B")
    assert b["var_total"] == b["var_rows"] == -2920000
    assert _b(res, "C")["breakdown"] is False and \
        _b(res, "C")["var_total"] is None


def test_blank_is_missing_scope_and_zero_is_a_price():
    res = V.compare(ROWS, ["A", "B", "C"], 15)
    man = res["rows"][1]["cells"]
    assert man["A"] == {"state": V.MISSING, "amount": 2520000, "var": 0,
                        "pct": None, "flag": ""}
    assert man["B"]["amount"] == 0 and man["B"]["var"] == -2520000 and \
        man["B"]["pct"] == -100.0 and man["B"]["flag"] == V.LOW
    a = _b(res, "A")
    assert a["missing"] == 2520000 and a["missing_rows"] == [
        ("Manholes", 2520000)]
    assert _b(res, "B")["unplugged"] == ["Extra"]


def test_no_estimate_is_not_zero_percent_and_the_threshold():
    res = V.compare(ROWS, ["A", "B", "C"], 15)
    extra = res["rows"][2]
    assert extra["ours"] is None and extra["cells"]["A"]["pct"] is None
    assert V.cell_text(extra, extra["cells"]["A"]) == (
        "$1,000.01", "", "no estimate")
    pipe = res["rows"][0]["cells"]
    assert pipe["A"]["pct"] == 16.7 and pipe["A"]["flag"] == V.HIGH
    assert pipe["B"]["pct"] == -7.4 and pipe["B"]["flag"] == ""
    assert V.compare(ROWS, ["A"], 20)["rows"][0]["cells"]["A"]["flag"] == ""
    assert V.compare(ROWS, ["B"], 5)["rows"][0]["cells"]["B"]["flag"] == V.LOW
    assert V.pct_of(1, 0) is None
    assert V.pct_of(5, 1000) == 0.5 and V.pct_of(-25, 10000) == -0.3


def test_threshold_is_a_setting(cfg):
    assert V.threshold() == 15.0
    V.set_threshold(10)
    assert V.threshold() == 10.0
    with pytest.raises(ValueError):
        V.set_threshold(0)
    settings.set(V.SETTING, "junk")
    assert V.threshold() == 15.0


def test_cents_round_half_up():
    assert V.cents(Decimal("2.675")) == 268 and V.cents("0.005") == 1
    assert V.cents(None) is None
    assert V.money(-150) == "($1.50)" and V.signed(-150) == "-$1.50"
    assert V.signed(0) == "$0.00" and V.money(123456789) == "$1,234,567.89"


def test_report_tables_and_files(tmp_path):
    res = V.compare(ROWS, ["A", "B", "C"], 15)
    t = dict(V.tables(res))
    assert t["Variance"][1][:5] == ["Pipe", "$54,000.00", "$63,000.00",
                                    "+$9,000.00 (+16.7%)", "HIGH"]
    assert t["Variance"][3][1] == "no estimate"
    assert ["A", "Total missing scope", "$25,200.00"] in t["Missing Scope"]
    tot = t["Totals"][1]
    assert tot[3:6] == ["$89,200.01", "$82,533.33", "+$6,666.68"]
    assert t["Totals"][3][:2] == ["C", "no breakdown"]
    x = V.export_xlsx(res, str(tmp_path / "v.xlsx"), "33 Utilities")
    import openpyxl
    wb = openpyxl.load_workbook(x)
    assert wb.sheetnames == ["Variance", "Missing Scope", "Totals"]
    p = V.export_pdf(res, str(tmp_path / "v.pdf"), "33 Utilities",
                     "Example Builders")
    import fitz
    text = "".join(pg.get_text() for pg in fitz.open(p))
    assert "Variance Against Our Estimate" in text and "HIGH" in text and \
        "$89,200.01" in text


# ---- Scope Sheets ------------------------------------------------------------

def _sheet():
    sh = ss.new_sheet("33 00 00", "Utilities", bidders=3)
    a, b, c = sh["bidders"]
    a["company"], b["company"], c["company"] = "Example Pipe", \
        "Sample Utilities", "Demo Excavating"
    c["price"] = ss.parse_money("80,000")          # one price, no lines
    for desc, qty, up, lump in (("Pipe", "1200", "45", None),
                                ("Manholes", None, None, "25,200"),
                                ("Testing", None, None, None)):
        ln = ss.add_line(sh, desc)
        if qty:
            ln["qty"], ln["unit_price"] = ss.parse_qty(qty), \
                ss.parse_unit_price(up)
        if lump:
            ln["lump"] = ss.parse_money(lump)
    lines = sh["lines"][-3:]
    ss.set_bid(sh, lines[0]["id"], a["id"], amount=ss.parse_money("63,000"))
    ss.set_bid(sh, lines[1]["id"], a["id"], flag="N")
    ss.set_bid(sh, lines[2]["id"], a["id"], flag="Y")
    ss.set_bid(sh, lines[0]["id"], b["id"], amount=ss.parse_money("50,000"))
    ss.set_bid(sh, lines[1]["id"], b["id"], amount=0)
    ss.set_bid(sh, lines[2]["id"], b["id"], amount=ss.parse_money("900"))
    sh["lines"] = lines
    return sh, a, b, c


def test_scope_sheet_variance_matches_the_sheet(cfg):
    sh, a, b, c = _sheet()
    rows, names = V.from_scope_sheet(sh)
    assert names == ["Example Pipe", "Sample Utilities", "Demo Excavating"]
    res = V.compare(rows, names, 15)
    assert res["ours"] == ss.budget_total(sh) == 7920000
    lv = ss.leveled(sh, "budget", adjust=False)
    ea = _b(res, "Example Pipe")
    # missing-scope dollars are the sheet's own plugs
    assert ea["missing"] == lv[a["id"]]["plugged"] == 2520000
    assert ea["leveled"] == lv[a["id"]]["total"]
    # ... and the difference is the sheet's "vs budget", to the cent
    v, _p = ss.spread(sh, lv[a["id"]]["total"])
    assert ea["var_total"] == v
    sb = _b(res, "Sample Utilities")
    assert sb["no_estimate"] == 90000 and sb["var_total"] == \
        lv[b["id"]]["total"] - ss.budget_total(sh)
    assert rows[2]["ours"] is None                  # Testing: no budget
    assert res["rows"][2]["cells"]["Example Pipe"]["state"] == V.INCLUDED
    assert _b(res, "Demo Excavating")["breakdown"] is False


@pytest.fixture
def qt(cfg):
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])


def test_scope_sheet_variance_window(qt, tmp_path):
    from app.pm import scope_sheet_ui as ui
    ed = ui.ScopeSheetEditor(None)
    sh, a, b, c = _sheet()
    ed.set_sheet(sh)
    dlg = ed.variance(show=False)
    t = dlg.table
    assert t.rowCount() == 4 and t.columnCount() == 2 + 3 * 3
    assert t.item(0, 4).text() == "HIGH"
    assert "MISSING SCOPE" in t.item(1, 4).text()
    assert t.item(2, 1).text() == "no estimate"
    assert t.item(3, 0).text() == "LEVELED TOTAL"
    assert "Example Pipe" in dlg.missing.text() and "$25,200.00" in \
        dlg.missing.text()
    dlg.pct.setValue(20.0)
    assert V.threshold() == 20.0 and t.item(0, 4).text() == ""
    assert dlg.export_xlsx(str(tmp_path / "v.xlsx"))
    assert dlg.export_pdf(str(tmp_path / "v.pdf"))


def test_leveling_board_variance(qt, monkeypatch):
    import fitz
    from app import estimate
    from app.estimating import levelboard as LB, levelboard_ui
    monkeypatch.setattr(estimate, "lines", lambda d, page=None: [
        {"name": "Gypsum board walls", "unit": "sf", "type": "area",
         "quantity": 1000, "code": "09 21 16", "unit_cost": 2.5},
        {"name": "Acoustic ceiling", "unit": "sf", "type": "area",
         "quantity": 400, "code": "09 51 13", "unit_cost": 4.0}])
    doc = fitz.open()
    doc.new_page()
    w = levelboard_ui.LevelBoard(doc)
    w.new_from_trade("09", ask=False)
    LB.import_quote(doc, w.package(), parsed={
        "bidder": "Example Drywall", "lines": [
            {"desc": "Gypsum board walls", "amount": 3000.0}],
        "exclusions": []})
    w.refresh()
    board = LB.board(doc, w.package())
    rows, names = V.from_board(board)
    res = V.compare(rows, names, 15)
    b = res["bidders"][0]
    tot = board["bidders"][0]
    # the board's own plugs and total
    assert b["missing"] == V.cents(tot["plugs"]) == 160000
    assert b["leveled"] == V.cents(tot["total"]) == 460000
    assert res["rows"][0]["cells"]["Example Drywall"]["flag"] == V.HIGH
    assert b["var_total"] == 50000 == b["var_rows"]
    dlg = w.variance(show=False)
    assert dlg.table.rowCount() == 3
