"""Nov 3: Bid Form Autopilot (#8). A made-up owner bid form."""
import datetime
import os
from decimal import Decimal

import fitz
import pytest

from app import bidform_auto as BA, doccontrol


def _form(path):
    d = fitz.open()
    pg = d.new_page()
    pg.insert_text((50, 40), "BID FORM - a bid bond of 5% is required",
                   fontsize=10)
    y = 70
    for name, kind in (("Base Bid", "text"), ("Base Bid in Words", "text"),
                       ("Alternate No. 1", "text"),
                       ("Addendum 1", "check"), ("Unit Price 1", "text"),
                       ("Bidder Signature", "text")):
        w = fitz.Widget()
        w.field_name = name
        w.rect = fitz.Rect(200, y, 500, y + 18)
        w.field_type = fitz.PDF_WIDGET_TYPE_CHECKBOX if kind == "check" \
            else fitz.PDF_WIDGET_TYPE_TEXT
        pg.add_widget(w)
        y += 30
    d.save(path)
    return path


def test_amount_in_words():
    assert BA.amount_in_words("1234567.89") == (
        "One Million Two Hundred Thirty-Four Thousand Five Hundred "
        "Sixty-Seven Dollars and 89/100")
    assert BA.amount_in_words(100) == "One Hundred Dollars and 00/100"


@pytest.fixture
def doc(monkeypatch):
    monkeypatch.setattr(BA, "base_bid", lambda d: Decimal("482150.00"))
    d = fitz.open()
    d.new_page()
    return d


def test_fill_and_check(doc, tmp_path):
    src = _form(str(tmp_path / "form.pdf"))
    out = str(tmp_path / "filled.pdf")
    aid = doccontrol.add_addendum(doc, "Doors", issued="2026-11-01")
    with pytest.raises(BA.GateError):            # Addenda Gate
        BA.run(doc, src, out)
    doccontrol.price_addendum(doc, aid, cost="0")
    due = datetime.datetime.now() + datetime.timedelta(hours=5)
    got = BA.run(doc, src, out, alternates={1: 12500}, unit_prices={1: 45.5},
                 deadline=due, bond_ready=False)
    f = fitz.open(out)
    vals = {w.field_name: w.field_value for pg in f for w in pg.widgets()}
    assert vals["Base Bid"] == "$482,150.00"
    assert vals["Base Bid in Words"].startswith("Four Hundred Eighty-Two "
                                                "Thousand")
    assert vals["Alternate No. 1"] == "$12,500.00"
    assert vals["Unit Price 1"] == "$45.50"
    assert vals["Addendum 1"] not in (None, "", "Off", False)
    msgs = dict((m, ok) for ok, m in got["check"])
    assert any("bid bond" in m and not ok for m, ok in msgs.items())
    assert any("Not signed" in m for m in msgs)
    assert any(m.startswith("Due in") for m in msgs)


def test_past_deadline():
    d = fitz.open()
    d.new_page()
    chk = BA.final_check(d, {}, datetime.datetime(2020, 1, 1))
    assert any("passed" in m and not ok for ok, m in chk)


def test_window(doc, tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication, QTableWidgetItem
    QApplication.instance() or QApplication([])
    from app import bidform_auto_ui
    opened = []
    w = bidform_auto_ui.BidFormDialog(doc, open_result=opened.append)
    w.form.setText(_form(str(tmp_path / "f.pdf")))
    w.alts.setItem(0, 0, QTableWidgetItem("1"))
    w.alts.setItem(0, 2, QTableWidgetItem("$1,000"))
    got = w.run(str(tmp_path / "o.pdf"))
    assert got and opened == [str(tmp_path / "o.pdf")]
    assert got["values"]["alternates"] == {1: Decimal("1000")}
