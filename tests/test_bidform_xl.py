"""Bid form workbook, calculating bid form PDF, addendum bid form check,
builder's risk quote request (Nov 4). Made-up forms only."""
import os
from decimal import Decimal

import pytest

FORM = """BID FORM
Project: Made-Up Fire Station
The undersigned acknowledges receipt of Addendum No. 1 and Addendum No. 2.
1. Mobilization LS $________
2. Concrete sidewalk 1,250 SF $________
3. Storm pipe 18 inch 340 LF $________
4. Topsoil 85 CY $________
Alternate No. 1: Add metal canopy at apparatus bay $________
Deduct Alternate No. 2: Delete irrigation $________
"""

ADDENDUM = """ADDENDUM NO. 3
Item 4: Replace the bid form with the revised bid form attached.
REVISED BID FORM
1. Mobilization LS $________
2. Concrete sidewalk 1,400 SF $________
3. Storm pipe 18 inch 340 LF $________
5. Rip rap 40 TON $________
Alternate No. 1: Add metal canopy at apparatus bay $________
"""


def test_parse_reads_items_alternates_and_addenda():
    from app import bidform_xl as BX
    f = BX.parse([FORM])
    assert [i["no"] for i in f["items"]] == ["1", "2", "3", "4"]
    assert f["items"][0]["qty"] == 1
    assert f["items"][1]["qty"] == Decimal("1250")
    assert f["items"][2]["unit"] in ("LF", "L.F.")
    assert [(a["no"], a["kind"]) for a in f["alternates"]] == \
        [("1", "add"), ("2", "deduct")]
    assert f["addenda"] == [1, 2]


def _book(tmp_path):
    from app import bidform_xl as BX
    f = BX.parse([FORM])
    f["pages"] = [0]
    p = str(tmp_path / "Made-Up - Bid Form Workbook.xlsx")
    BX.workbook(f, p, "Made-Up Fire Station", [1, 2])
    return BX, f, p


def _type_prices(path, prices, alts):
    from openpyxl import load_workbook
    from app import bidform_xl as BX
    wb = load_workbook(path)
    ws = wb["Bid Form"]
    meta = {r[0]: int(r[1]) for r in wb["QuantiSheet"].iter_rows(
        values_only=True) if r and r[0]}
    for r in range(meta.get("first", BX.FIRST), meta["last"] + 1):
        no = str(ws.cell(row=r, column=1).value or "")
        if no in prices:
            ws.cell(row=r, column=5, value=prices[no])
    for r in range(meta["alt_first"], meta["alt_last"] + 1):
        no = str(ws.cell(row=r, column=1).value or "")
        if no in alts:
            ws.cell(row=r, column=5, value=alts[no])
    wb.save(path)


def test_workbook_has_formulas_not_numbers(tmp_path):
    from openpyxl import load_workbook
    BX, _f, p = _book(tmp_path)
    ws = load_workbook(p)["Bid Form"]
    formulas = [c.value for row in ws.iter_rows() for c in row
                if isinstance(c.value, str) and c.value.startswith("=")]
    assert any("ROUND(" in x for x in formulas)          # line totals
    assert any("SUM(" in x for x in formulas)            # subtotal
    assert any("Deduct" in x for x in formulas)          # signed alternates


def test_totals_add_and_subtract(tmp_path):
    BX, _f, p = _book(tmp_path)
    _type_prices(p, {"1": 25000, "2": 6.5, "3": 48.25, "4": 32},
                 {"1": 18000, "2": 4200})
    book = BX.read_workbook(p)
    t = BX.totals(book)
    # 25000 + 1250*6.50 + 340*48.25 + 85*32
    assert t["subtotal"] == Decimal("25000") + Decimal("8125.00") + \
        Decimal("16405.00") + Decimal("2720.00")
    assert t["base"] == Decimal("52250.00")
    signed = {a["no"]: a["signed"] for a in t["alternates"]}
    assert signed["1"] == Decimal("18000") and signed["2"] == Decimal("-4200")
    assert t["with_alternates"] == Decimal("66050.00")
    assert t["missing"] == []


def test_blank_price_is_reported_missing(tmp_path):
    BX, _f, p = _book(tmp_path)
    _type_prices(p, {"1": 1000, "2": 2}, {})
    t = BX.totals(BX.read_workbook(p))
    assert t["missing"] == ["3", "4"]
    assert t["base"] == Decimal("3500.00")


def test_addendum_compare_finds_changes():
    from app import bidform_xl as BX
    ch = BX.compare(BX.parse([FORM]), BX.parse([ADDENDUM]))
    assert [i["no"] for i in ch["added"]] == ["5"]
    assert [i["no"] for i in ch["removed"]] == ["4"]
    assert [a["no"] for a, _b in ch["qty"]] == ["2"]
    assert ch["alternates_removed"] == ["2"]
    txt = BX.change_text(ch)
    assert "new items 5" in txt and "1,250 -> 1,400" in txt


def test_revised_wording_is_caught():
    from app import bidform_xl as BX
    assert BX.REVISED.search(ADDENDUM)
    assert not BX.REVISED.search("Addendum 4: clarify door hardware.")


# ---- PDF parts (need PyMuPDF) ---------------------------------------------------

def _pdf(text, path):
    fitz = pytest.importorskip("fitz")
    d = fitz.open()
    pg = d.new_page()
    y = 60
    for ln in text.splitlines():
        pg.insert_text((50, y), ln, fontsize=10)
        y += 14
    d.save(path)
    return fitz.open(path)


def test_fill_pdf_makes_calculating_schedule(tmp_path):
    fitz = pytest.importorskip("fitz")
    BX, f, p = _book(tmp_path)
    doc = _pdf(FORM, str(tmp_path / "form.pdf"))
    _type_prices(p, {"1": 25000, "2": 6.5, "3": 48.25, "4": 32},
                 {"1": 18000, "2": 4200})
    out = str(tmp_path / "filled.pdf")
    t = BX.fill_pdf(doc, [0], BX.read_workbook(p), out, "Made-Up")
    assert t["base"] == Decimal("52250.00")
    d = fitz.open(out)
    assert d.page_count == 2
    names = {w.field_name: w for pg in d for w in pg.widgets()}
    assert "base_bid" in names and "subtotal" in names
    assert "52,250.00" in str(names["base_bid"].field_value)
    calc = [w.script_calc for w in names.values() if w.script_calc]
    assert any("AFSimple_Calculate" in s for s in calc)


def test_addendum_check_sees_bid_form(tmp_path):
    pytest.importorskip("fitz")
    from app import bidform_xl as BX
    add = _pdf(ADDENDUM, str(tmp_path / "add3.pdf"))
    chk = BX.addendum_check(add)
    assert chk["has_form"] and chk["revised"] and chk["pages"] == [0]
    plain = _pdf("ADDENDUM NO. 4\nClarify door hardware at 101.",
                 str(tmp_path / "add4.pdf"))
    chk = BX.addendum_check(plain)
    assert not chk["has_form"] and not chk["revised"]


def test_addendum_summary_mentions_bid_form(tmp_path):
    pytest.importorskip("fitz")
    from app import addendum_summary as AS
    old = _pdf(FORM, str(tmp_path / "old.pdf"))
    new = _pdf(ADDENDUM, str(tmp_path / "new.pdf"))
    s = AS.summarize(old, new)
    assert s["bid_form"]["has_form"]
    assert "BID FORM:" in AS.text(s)


def test_builders_risk_request_and_email(tmp_path, monkeypatch):
    fitz = pytest.importorskip("fitz")
    from app import builders_risk as BR, mail, settings
    monkeypatch.setattr(settings, "DIR", str(tmp_path), raising=False)
    store = {}
    monkeypatch.setattr(settings, "set", lambda k, v: store.__setitem__(k, v),
                        raising=False)
    monkeypatch.setattr(settings, "get", lambda k, d=None: store.get(k, d),
                        raising=False)
    v = {"project": "Made-Up Fire Station", "address": "100 Example Rd",
         "owner": "Example County", "work": "New 2-bay station.",
         "amount": Decimal("1234567.89"), "start": "Jan 2027",
         "finish": "Dec 2027", "requirements": "Section 00 72 00, page 9: "
         "all-risk form; deductible $5,000", "contractor": "Test Builder"}
    pdf = BR.request_pdf(v, str(tmp_path / BR.file_name(v)))
    text = fitz.open(pdf)[0].get_text()
    assert "Made-Up Fire Station" in text and "$1,234,567.89" in text
    assert "100 Example Rd" in text and "New 2-bay station." in text
    sent = []
    BR.email(v, pdf, "agent@example.com", "Need by Friday",
             send=lambda *a, **k: sent.append((a, k)) or "outlook")
    (to, subj, body), kw = sent[0]
    assert to == "agent@example.com" and "Made-Up Fire Station" in subj
    assert "Need by Friday" in body and kw["attachments"] == [pdf]
    assert BR.agent() == "agent@example.com"


def test_workbook_window_end_to_end(tmp_path):
    fitz = pytest.importorskip("fitz")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app.bidform_xl_ui import BidFormWorkbook
    src = str(tmp_path / "Bid Form.pdf")
    _pdf(FORM, src)
    opened = []
    dlg = BidFormWorkbook(None, src, "Made-Up", open_result=opened.append,
                          open_file=opened.append)
    assert len(dlg.form["items"]) == 4
    book = dlg.make_book(ask=False)
    assert os.path.isfile(book)
    _type_prices(book, {"1": 25000, "2": 6.5, "3": 48.25, "4": 32},
                 {"1": 18000, "2": 4200})
    t = dlg.transfer()
    assert t["base"] == Decimal("52250.00") and opened[-1].endswith(".pdf")
    assert fitz.open(opened[-1]).page_count == 2
    add = str(tmp_path / "Addendum 3.pdf")
    _pdf(ADDENDUM, add)
    chk = dlg.check_addendum(add)
    assert chk["has_form"] and "new items 5" in dlg.note.text()
    from app import bidform_xl as BX
    new = BX.read_workbook(dlg.book_path)
    prices = {i["no"]: i["price"] for i in new["items"]}
    assert prices["1"] == Decimal("25000")      # unchanged item kept
    assert prices["2"] is None                  # quantity changed: re-price
    assert prices["5"] is None                  # new item


def test_builders_risk_window(tmp_path, monkeypatch):
    pytest.importorskip("fitz")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app import builders_risk as BR
    from app.bidform_xl_ui import BuildersRiskRequest
    monkeypatch.setattr(BR, "values", lambda doc, items=None: {
        "project": "Made-Up Library", "address": "1 Test St", "owner": "",
        "work": "Renovation.", "amount": Decimal("500000"), "start": "",
        "finish": "", "requirements": "", "contractor": "Test Builder"})
    monkeypatch.setattr(BR, "agent", lambda: "")
    sent = []
    dlg = BuildersRiskRequest(None, None, folder=str(tmp_path),
                              send=lambda *a, **k: sent.append(a) or "mailto")
    assert dlg.ed["amount"].text() == "500,000.00"
    dlg.ed["amount"].setText("612,000")
    dlg.to.setText("agent@example.com")
    monkeypatch.setattr(BR, "email", lambda v, pdf, to, note, send=None:
                        sent.append((v["amount"], pdf, to)) or "mailto")
    dlg.email()
    amt, pdf, to = sent[-1]
    assert amt == Decimal("612000") and to == "agent@example.com"
    assert os.path.isfile(pdf) and pdf.startswith(str(tmp_path))
