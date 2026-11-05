"""Export My Estimate: totals by CSI division and cost type; Save to PDF
(by CSI division), Excel ('By Division' with SUM formulas) and CSV; and
'By CSI division' in the proposal's detail options. Made-up job."""
import csv
import os
from decimal import Decimal

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import (assemblies, estimate, estimate_export as EX,    # noqa: E402
                 estimate_lines as EL, proposal, settings)
from estimate_helpers import area, blank_doc                     # noqa: E402
from test_gui import win, qapp                                   # noqa: E402,F401


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


WANT = [("Division 01 - General requirements", Decimal("300.00")),
        ("Division 03 - Concrete", Decimal("2500.00")),
        ("Division 09 - Finishes", Decimal("1320.00"))]


def _job():
    d = blank_doc()
    EL.add(d, [EL.new_line("Test slab", 1000, "sf", code="03 31 13",
                           mat="2.50"),
               EL.new_line("Test gyp", 2400, "sf", code="09 29 10",
                           mat="0.30", lab="0.25"),
               EL.new_line("Test scaffold", 1, "mo", code="01 54 33",
                           eqp=300)])
    return d


def test_totals_by_division_and_cost_type():
    s = EX.summary(_job())
    assert [(x["label"], x["total"]) for x in s["divisions"]] == WANT
    assert s["total"] == Decimal("4120.00")
    assert s["types"] == {"Material": Decimal("3220.00"),
                          "Labor": Decimal("600.00"),
                          "Equipment": Decimal("300.00")}
    assert sum(s["types"].values()) == s["total"]


def test_uncoded_line_is_counted():
    d = _job()
    EL.add(d, [EL.new_line("Test cleanup", 1, "ls", sub=80)])
    s = EX.summary(d)
    assert s["divisions"][-1]["label"] == "Uncoded"
    assert s["divisions"][-1]["total"] == Decimal("80.00")
    assert s["total"] == Decimal("4200.00")


def test_takeoff_lines_and_their_codes_are_in_it():
    d = blank_doc()
    area(d, "Test slab", 50, 20)
    estimate.set_price(d, "Test slab", "area", "sq ft", unit_cost=2.5,
                       code="03 31 13", cost_type="Material")
    area(d, "Test misc", 10, 10, x0=700)
    estimate.set_price(d, "Test misc", "area", "sq ft", unit_cost=1)
    s = EX.summary(d)
    assert [(x["label"], x["total"]) for x in s["divisions"]] == [
        ("Division 03 - Concrete", Decimal("2500.00")),
        ("Uncoded", Decimal("100.00"))]
    assert s["types"] == {"Material": Decimal("2500.00"),
                          "Other": Decimal("100.00")}


def test_save_pdf_by_division(tmp_path):
    d = _job()
    path = EX.save_pdf(d, str(tmp_path / "est.pdf"))
    out = fitz.open(path)
    text = "".join(pg.get_text() for pg in out)
    pos = [text.index(label) for label, _ in WANT]
    assert pos == sorted(pos)                              # 01, 03, 09
    for _label, amount in WANT:
        assert f"${amount:,.2f}" in text
    assert "$4,120.00" in text


def test_save_excel_by_division_with_sum(tmp_path):
    import openpyxl
    path = EX.save_xlsx(_job(), str(tmp_path / "est.xlsx"))
    wb = openpyxl.load_workbook(path)
    assert {"By Division", "By Cost Type", "Lines"} <= set(wb.sheetnames)
    ws = wb["By Division"]
    rows = list(ws.iter_rows(values_only=True))
    head = rows[0]
    tcol = head.index("Total")
    body = [r for r in rows[1:] if r[0] not in ("Total", None)]
    assert [(r[0], Decimal(str(r[tcol]))) for r in body] == [
        ("01", Decimal("300")), ("03", Decimal("2500")),
        ("09", Decimal("1320"))]
    total_row = [r for r in rows if r[0] == "Total"][0]
    letter = "ABCDEFGHIJ"[tcol]
    assert total_row[tcol] == f"=SUM({letter}2:{letter}4)"
    assert sum(Decimal(str(r[tcol])) for r in body) == Decimal("4120.00")


def test_save_csv(tmp_path):
    path = EX.save_csv(_job(), str(tmp_path / "est.csv"))
    rows = list(csv.reader(open(path, encoding="utf-8-sig")))
    assert ["Grand total", "4120.00"] in rows
    i = rows.index(["By CSI division"])
    divs = [(r[0], r[-1]) for r in rows[i + 1:i + 4]]
    assert divs == [("01", "300.00"), ("03", "2500.00"), ("09", "1320.00")]


def test_proposal_by_csi_division(tmp_path):
    d = _job()
    assert "csi" in proposal.DETAIL
    data = dict(proposal.defaults(d), detail="csi", tax=0, overhead=0,
                profit=0, client="Test Client", project="Test Garage")
    pr = proposal.price(d, data)
    assert pr["total"] == pytest.approx(4120.0)
    assert [ln["division"] for ln in pr["lines"]] == ["01", "03", "09"]
    out = proposal.make_pdf(d, data, {"name": "Test Builders"})
    text = "".join(pg.get_text() for pg in out)
    pos = [text.index(label) for label, _ in WANT]
    assert pos == sorted(pos)
    for _label, amount in WANT:
        assert f"${amount:,.2f}" in text
    assert "$4,120.00" in text


def test_dialog_shows_divisions_and_saves(win, tmp_path, monkeypatch):
    from app.estimate_ui import ExportEstimateDialog
    doc = win._view.doc
    EL.add(doc, [EL.new_line("Test slab", 1000, "sf", code="03 31 13",
                             mat="2.50"),
                 EL.new_line("Test gyp", 2400, "sf", code="09 29 10",
                             mat="0.55"),
                 EL.new_line("Test scaffold", 1, "mo", code="01 54 33",
                             eqp=300)])
    win.estimate.refresh()
    dlg = win.export_my_estimate(show=False)
    assert isinstance(dlg, ExportEstimateDialog)
    assert dlg.division_rows() == [(lb, f"${v:,.2f}") for lb, v in WANT]
    assert "$4,120.00" in dlg.total.text()
    for fn, ext in ((dlg.save_pdf, "pdf"), (dlg.save_xlsx, "xlsx"),
                    (dlg.save_csv, "csv")):
        p = str(tmp_path / f"mine.{ext}")
        assert fn(p) == p and os.path.getsize(p) > 0


def test_dialog_without_a_document(qapp):
    from app.estimate_ui import ExportEstimateDialog
    dlg = ExportEstimateDialog(None)
    assert not dlg.pdf_btn.isEnabled() and dlg.save_pdf() is None
    dlg.close()


def test_unpriced_takeoff_is_listed_not_dropped(tmp_path):
    """Review r41 F01: measured takeoffs with no price made an empty $0.00
    export. They're listed with quantity and a blank price, not totalled,
    with a note saying so."""
    import openpyxl
    d = blank_doc()
    area(d, "Test flooring", 50, 30)
    s = EX.summary(d)
    assert s["total"] == Decimal("0.00")
    assert [(u["desc"], float(u["qty"]), u["unit"]) for u in s["unpriced"]] \
        == [("Test flooring", 1500.0, "sq ft")]
    assert "1 takeoff item has no price" in EX.unpriced_note(s)
    assert "Price These" in EX.unpriced_note(s)   # r45: say where to price
    x = EX.save_xlsx(d, str(tmp_path / "e.xlsx"), s)
    rows = [r for r in openpyxl.load_workbook(x)["Lines"].iter_rows(
        values_only=True)]
    hit = [r for r in rows if r[2] == "Test flooring"]
    assert hit and hit[0][3] == "takeoff (no price)" and hit[0][4] == 1500
    assert any(r[0] and "no price yet" in str(r[0]) for r in rows)
    c = EX.save_csv(d, str(tmp_path / "e.csv"), s)
    assert "Test flooring" in open(c, encoding="utf-8-sig").read()
    p = EX.save_pdf(d, str(tmp_path / "e.pdf"), s)
    text = fitz.open(p)[0].get_text()
    assert "Not priced yet" in text and "Test flooring" in text


def test_priced_takeoff_is_not_listed_as_unpriced():
    s = EX.summary(_job())
    assert s["unpriced"] == []
    assert EX.unpriced_note(s) == ""
