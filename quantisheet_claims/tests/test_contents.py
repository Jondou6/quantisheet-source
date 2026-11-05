"""ClaimIT 0.2.2: the contents list (Coverage C / business personal
property). Made-up data only."""
import csv
import dataclasses
import json

import pytest

from quantisheet_claims import checklist, contents as ct, diary, practice, \
    settle, store
from quantisheet_claims import model as m
from quantisheet_claims.export import build_model, to_csv, to_pdf, to_xlsx


def _items():
    return (ct.make_item("Example TV", "1", "800.00", "25"),      # 800 / 600
            ct.make_item("Example chairs", "4", "50", "50"),      # 200 / 100
            ct.make_item("Example lamp", "2", "$19.99", "0", age="2 yrs"))


def test_item_math():
    tv, chairs, lamp = _items()
    assert ct.item_rcv(tv) == 80_000 and ct.item_dep(tv) == 20_000
    assert ct.item_acv(tv) == 60_000
    assert ct.item_rcv(chairs) == 20_000 and ct.item_acv(chairs) == 10_000
    assert ct.item_rcv(lamp) == 3_998 and lamp.age == "2 yrs"


def test_bad_items_are_refused():
    for args in (("", "1", "10"), ("X", "0", "10"), ("X", "1.5", "10"),
                 ("X", "1", "-5"), ("X", "1", "ten"), ("X", "1", "10", "150"),
                 ("X", "1", "10", "-1")):
        with pytest.raises(ct.ContentsError):
            ct.make_item(*args)


def test_totals_rc_policy_holds_back_depreciation():
    c = dataclasses.replace(practice.claim(), contents=_items())
    t = ct.totals(c)
    assert t["rcv"] == 103_998 and t["dep"] == 30_000
    assert t["acv"] == 73_998 and t["now"] == 73_998
    assert t["full"] == 103_998 and t["holdback"] == 30_000


def test_acv_policy_limit_and_deductible():
    c = dataclasses.replace(practice.claim(), contents=_items(),
                            contents_cov=ct.coverage("500", "acv", "100"))
    t = ct.totals(c)
    assert t["deductible"] == 10_000
    assert t["now"] == 50_000 and t["full"] == 50_000 and t["holdback"] == 0
    assert t["over_limit"] == 73_998 - 10_000 - 50_000
    s = settle.settle_claim(c)
    assert any(w.code == "contents_limit_reached" for w in s.warnings)


def test_settlement_includes_contents():
    base = practice.claim()
    s0 = settle.settle_claim(base)
    c = dataclasses.replace(base, contents=_items())
    s = settle.settle_claim(c)
    assert s.contents_now == 73_998 and s.contents_holdback == 30_000
    assert s.total_indemnity == s0.total_indemnity + 73_998
    assert s.holdback_total == s0.recoverable_holdback + 30_000
    assert s.net == s0.net                       # property side unchanged
    b = diary.balance(c, s)
    assert b["recoverable_later"] == s.holdback_total


def test_no_contents_changes_nothing():
    c = practice.claim()
    s = settle.settle_claim(c)
    assert s.contents_rcv == s.contents_now == s.contents_holdback == 0
    assert s.holdback_total == s.recoverable_holdback


def test_coverage_input_checks():
    assert ct.coverage("", "rc", "").limit_cents is None
    with pytest.raises(ct.ContentsError):
        ct.coverage("10", "new", "")
    with pytest.raises(ct.ContentsError):
        ct.coverage("-10", "rc", "")


def test_checklist_contents_rules():
    zero = ct.make_item("Example rug", "1", "0")
    c = dataclasses.replace(practice.claim(), contents=(zero,))
    texts = [i.text for i in checklist.check(c)]
    assert any("no replacement cost" in t for t in texts)
    assert "Enter the contents limit" in texts
    only = dataclasses.replace(practice.claim(), lines=(), contents=_items())
    assert "No line items yet" not in [i.text for i in checklist.check(only)]
    assert checklist.TAB["contents"] == 8 and checklist.TAB["export"] == 9


def test_file_version_3_with_contents(tmp_path):
    c = dataclasses.replace(practice.claim(), contents=_items())
    p = store.save(c, folder=str(tmp_path))
    assert json.load(open(p))["schema_version"] == 3
    back, _ = store.load(p)
    assert back.contents == c.contents
    c2 = dataclasses.replace(practice.claim(),
                             contents_cov=ct.coverage("1000", "rc", ""))
    p2 = store.save(c2, folder=str(tmp_path / "b"))
    assert json.load(open(p2))["schema_version"] == 3
    assert store.load(p2)[0].contents_cov.limit_cents == 100_000


def test_exports_list_the_contents(tmp_path):
    import pymupdf as fitz
    from openpyxl import load_workbook
    c = dataclasses.replace(practice.claim(), contents=_items())
    md = build_model(c, printed="2026-11-01", author="Example")
    assert len(md.contents) == 3 and md.contents_label.startswith("Contents")
    assert ("Contents (Coverage C) paid now", 73_998) in md.settlement
    rows = list(csv.reader(open(to_csv(md, str(tmp_path / "c.csv")),
                                encoding="utf-8-sig")))
    i = rows.index(list(("Item", "Room", "Qty", "Each (RC)", "RCV", "Dep %",
                         "Dep", "ACV", "Age")))
    assert rows[i + 1][0] == "Example TV" and rows[i + 1][4] == "800.00"
    wb = load_workbook(to_xlsx(md, str(tmp_path / "c.xlsx")))
    assert wb["Contents"]["A3"].value == "Example chairs"
    txt = " ".join(pg.get_text() for pg in fitz.open(
        to_pdf(md, str(tmp_path / "c.pdf"))))
    assert "Example TV" in txt and "Contents (Coverage C)" in txt


def test_commercial_label():
    c = dataclasses.replace(practice.claim(), claim_type="commercial")
    assert ct.label(c) == "Business personal property"


def test_contents_frozen_after_submit():
    c = dataclasses.replace(practice.claim(), status="submitted")
    with pytest.raises(m.FrozenClaimError):
        m.edit(c, "Example", "x", contents=_items())


# ---- window -------------------------------------------------------------
@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_contents_tab_add_remove_and_coverage(qapp):
    from quantisheet_claims.ui.workspace import ClaimsWindow, TAB_NAMES
    win = ClaimsWindow()
    win.open_practice()
    assert TAB_NAMES[8] == "Contents"
    assert win.add_contents_item("Example TV", "1", "800", "25")
    assert win.add_contents_item("Example lamp", "2", "20", "0", age="new")
    assert len(win.claim.contents) == 2
    assert win.contents_table.rowCount() == 2
    assert "$600.00" in win.contents_table.item(0, 7).text()
    assert win.add_contents_item("", "1", "5") is False      # no description
    assert win.set_contents_coverage("5,000", "acv", "50")
    assert win.claim.contents_cov.valuation == "acv"
    assert win.claim.contents_cov.limit_cents == 500_000
    win.contents_table.selectRow(0)
    assert win.remove_contents_item()
    assert [i.description for i in win.claim.contents] == ["Example lamp"]
    assert win.undo() and len(win.claim.contents) == 2
    win.status_box.setCurrentText("submitted")
    assert win.apply_claim_tab()
    assert win.add_contents_item("Example rug", "1", "100") is False
    assert "supplement" in win.last_error
    win.close()
