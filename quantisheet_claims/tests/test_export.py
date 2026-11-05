"""E1-E3: CSV, XLSX and PDF export of the C8 claim."""
import dataclasses

import pymupdf as fitz
from openpyxl import load_workbook

from quantisheet_claims import model as m
from quantisheet_claims.cents import fmt
from quantisheet_claims.export import build_model, to_csv, to_pdf, to_xlsx
from .helpers import c8_claim, line


def _claim():
    c = c8_claim()
    zero = line(0, structure="B1", description="=SUM(A1)", item_code="NOTE")
    return dataclasses.replace(c, lines=c.lines + (zero,))


def _model(c=None):
    return build_model(c or _claim(), printed="2026-10-20 12:00", author="Jon")


def test_e1_csv(tmp_path):
    p = to_csv(_model(), str(tmp_path / "c8.csv"))
    raw = open(p, "rb").read()
    assert raw.startswith(b"\xef\xbb\xbf") and b"\r\n" in raw
    assert b"\n" not in raw.replace(b"\r\n", b"")
    text = raw.decode("utf-8-sig")
    assert "\r\nPaid now,139722.22\r\n" in text
    assert "'=SUM(A1)" in text and ",=SUM(A1)" not in text
    credit = dataclasses.replace(_claim(), lines=_claim().lines + (
        line(-123_450, structure="B1", description="Credit: salvage"),))
    t2 = open(to_csv(_model(credit), str(tmp_path / "cr.csv")),
              encoding="utf-8-sig").read()
    assert ",-1234.50," in t2 and ",'-1234.50" not in t2


def test_e2_xlsx(tmp_path):
    md = _model()
    p = to_xlsx(md, str(tmp_path / "c8.xlsx"))
    wb = load_workbook(p)
    assert wb.sheetnames == ["Summary", "Line Items", "Settlement", "Supplements"]
    se = wb["Settlement"]
    row = [r for r in se.iter_rows(min_row=2) if r[0].value == "Paid now"][0]
    assert row[1].value == 139722.22 and row[1].number_format == "#,##0.00"
    want = dict(md.settlement)
    for r in se.iter_rows(min_row=2):
        if r[0].value in want:
            assert int((r[1].value * 100) + (0.5 if r[1].value >= 0 else -0.5)) \
                == want[r[0].value]
    for ws in wb.worksheets:
        for r in ws.iter_rows():
            for c in r:
                assert not (isinstance(c.value, str) and c.value.startswith("=")), \
                    (ws.title, c.coordinate)
    assert wb["Line Items"]["E3"].value == "'=SUM(A1)"


def test_e3_pdf(tmp_path):
    many = dataclasses.replace(_claim(), lines=_claim().lines + tuple(
        line(1000 + i, structure="B1", description=f"Item {i}") for i in range(90)))
    md = _model(many)
    p = to_pdf(md, str(tmp_path / "c8.pdf"))
    doc = fitz.open(p)
    n = doc.page_count
    assert n >= 2
    t1 = doc[0].get_text()
    assert fmt(md.paid_now) in t1
    assert "C-2026-0008" in t1 and f"Page 1 of {n}" in t1
    assert f"Page {n} of {n}" in doc[n - 1].get_text()
    assert "Item" in doc[1].get_text() and "Description" in doc[1].get_text()
    p1 = to_pdf(_model(), str(tmp_path / "c8b.pdf"))
    d1 = fitz.open(p1)
    assert "$139,722.22" in d1[0].get_text()
    assert d1.page_count == 1 and "Page 1 of 1" in d1[0].get_text()
