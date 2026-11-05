"""Scope Sheets (app/pm/scope_sheet.py): accounting parse/format, cents-exact
totals, math check, leveling plugs, low bidder, award default, the stored
record (schema version, round trip), the Excel export (live formulas,
accounting format, merged header, one tab per trade + Summary), the Excel
import (export -> import is the same sheet; a SUB LIST tab is never read)
and the PDF. Made-up companies and numbers only."""
import json
from decimal import Decimal

import pytest

from app import settings
from app.pm import scope_sheet as ss

P = ss.parse_money


@pytest.fixture(autouse=True)
def _cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache",
                        {"author": "Pat Example",
                         "company": {"name": "Example Builders"}})


def sample():
    """Budget + three bidders over three lines (one a credit)."""
    sh = ss.new_sheet("09 29 00", "Drywall & framing",
                      header={"project": "Harbor Example",
                              "project_no": "26-101", "bid_date": "2026-11-03",
                              "bid_time": "2:00 PM", "estimator": "Pat",
                              "addenda_from": "1", "addenda_to": "2"})
    a, b, c = sh["bidders"][:3]
    a.update(company="Example Drywall LLC", phone="555-0100",
             contact="Estimating", price=P("2,500"))
    b.update(company="Test Paving Co", price=P("7,000.10"))
    c.update(company="Sample Interiors Inc", price=P("9,000"))
    a["checklist"]["bonded"]["ans"] = "YES"
    b["checklist"]["tax"] = {"ans": "NO", "note": "tax excluded"}
    l1 = ss.add_line(sh, "Metal stud framing")
    l1.update(qty="1000", unit="SF", unit_price="2.875")
    l2 = ss.add_line(sh, "Gypsum board")
    l2["lump"] = P("5,000")
    l3 = ss.add_line(sh, "Credit: owner-furnished doors")
    ss.set_bid(sh, l1["id"], a["id"], "Y", P("2,900"))
    ss.set_bid(sh, l2["id"], a["id"], "N", None)
    ss.set_bid(sh, l3["id"], a["id"], "", P("(500)"))
    ss.set_bid(sh, l1["id"], b["id"], "Y", P("3,000.10"))
    ss.set_bid(sh, l2["id"], b["id"], "y", P("4,000"))
    return sh, (a, b, c), (l1, l2, l3)


# ------------------------------------------------------------ numbers
@pytest.mark.parametrize("text,cents", [
    ("1,250", 125000), ("$1,250.00", 125000), ("(500)", -50000),
    ("-500", -50000), ("500-", -50000), (" $ (500.00) ", -50000),
    ("($1,234.56)", -123456), ("$ -", 0), ("0", 0), ("12.345", 1235),
    ("0.005", 1), ("-0.005", -1), (1250, 125000), (0.1, 10),
    (Decimal("2.50"), 250), ("", None), (None, None), ("   ", None)])
def test_parse_money(text, cents):
    assert P(text) == cents


@pytest.mark.parametrize("text", ["abc", "(-500)", "1.2.3", "(", "$",
                                  "12a", "()", True])
def test_parse_money_rejects(text):
    with pytest.raises(ss.ScopeError):
        P(text)


def test_format_accounting():
    assert ss.fmt_money(-50000) == "($500.00)"
    assert ss.fmt_money(123456789) == "$1,234,567.89"
    assert ss.fmt_money(0) == "$0.00"
    assert ss.fmt_money(None) == ""                  # blank: not priced
    assert ss.fmt_money(-5, dollar=False) == "(0.05)"
    assert ss.parse_qty("1,250.50") == "1250.5"
    assert ss.parse_unit_price("$2.875") == "2.875"
    assert ss.parse_unit_price("3") == "3.00"
    assert ss.fmt_unit_price("2.875") == "$2.875"
    assert ss.parse_flag("yes") == "Y" and ss.parse_flag("n") == "N"
    assert ss.parse_flag("Allow") == "Allow" and ss.parse_flag(" ") == ""
    assert ss.median_cents([100, 300]) == 200
    assert ss.median_cents([1, 2]) == 2              # 1.5 cents, half up


def test_no_float_drift():
    sh = ss.new_sheet()
    b = sh["bidders"][0]
    for _ in range(10):
        ln = ss.add_line(sh, "x")
        ss.set_bid(sh, ln["id"], b["id"], amount=P("0.10"))
        ln.update(qty="3", unit_price="0.1")
    assert ss.line_sum(sh, b) == 100                 # exactly $1.00
    assert ss.budget_total(sh) == 300                # 10 x 3 x $0.10


# ------------------------------------------------------------ math
def test_totals_and_math_check():
    sh, (a, b, c), (l1, l2, l3) = sample()
    assert ss.budget_line_total(l1) == 287500        # 1000 x 2.875
    assert ss.budget_total(sh) == 787500
    assert ss.budget_math_check(sh) is None          # no budget price
    assert ss.bidder_total(sh, a) == 240000          # 2900 - 500
    assert ss.math_check(sh, a) == 10000             # 2500 - 2400: flag
    assert not ss.math_ok(sh, a)
    assert ss.math_check(sh, b) == 0 and ss.math_ok(sh, b)
    # no breakdown: the total is the stated price, no math check
    assert ss.bidder_total(sh, c) == 900000
    assert ss.math_check(sh, c) is None
    # an unused bidder block is blank, not $0
    assert ss.bidder_total(sh, sh["bidders"][3]) is None
    assert not ss.active(sh, sh["bidders"][3])
    # $0.00 is priced; blank is not
    ss.set_bid(sh, l3["id"], b["id"], amount=0)
    assert ss.bid_cell(l3, b["id"])["amount"] == 0
    assert not ss.excluded(sh, l3, b)


def test_leveling_plugs_and_low_bidder():
    sh, (a, b, c), (l1, l2, l3) = sample()
    assert ss.low_bidder(sh, "none") == a["id"]
    # budget plugs: A excluded gypsum (N) -> +$5,000; B left the credit
    # blank but has no budget for it -> nothing to plug
    lv = ss.leveled(sh, "budget")
    assert lv[a["id"]]["plugs"] == {l2["id"]: (500000, "budget")}
    assert lv[a["id"]]["total"] == 740000
    assert lv[b["id"]]["total"] == 700010 and not lv[b["id"]]["plugs"]
    assert lv[c["id"]]["plugs"] == {}        # lump sum only: not plugged
    assert ss.low_bidder(sh, "budget") == b["id"]
    # median plugs: the others' median for the line
    lv = ss.leveled(sh, "median")
    assert lv[a["id"]]["plugs"][l2["id"]] == (400000, "median")
    assert lv[b["id"]]["plugs"][l3["id"]] == (-50000, "median")
    assert lv[b["id"]]["total"] == 650010
    # a Y flag with no amount is "in the lump sum", never plugged
    ss.set_bid(sh, l3["id"], b["id"], flag="Y")
    assert not ss.excluded(sh, l3, b)
    # the sheet's own setting is the default
    sh["level"] = "budget"
    assert ss.low_bidder(sh) == b["id"]
    # entries never change when leveling
    assert ss.bid_cell(l2, a["id"]) == {"flag": "N", "amount": None}


def test_spread_award_and_summary():
    sh, (a, b, c), _l = sample()
    d, pct = ss.spread(sh, ss.bidder_total(sh, a))
    assert d == 240000 - 787500 and pct == Decimal("-69.5")
    assert ss.award_amount(sh) is None
    sh["award"]["bidder"] = b["id"]
    assert ss.award_amount(sh) == 700010             # defaults to total
    sh["award"]["amount"] = P("6,900")
    assert ss.award_amount(sh) == 690000
    s = ss.summary(sh)
    assert s["low_bidder"] == "Example Drywall LLC" and s["low_bid"] == 240000
    assert s["award_bidder"] == "Test Paving Co"
    assert s["variance"] == 690000 - 787500 and s["math_errors"] == 1
    assert s["bids"] == 3
    ss.remove_bidder(sh, b["id"])
    assert sh["award"]["bidder"] == "" and ss.award_amount(sh) is None


def test_lines_and_bidders_edit():
    sh = ss.new_sheet()
    assert len(sh["bidders"]) == ss.DEFAULT_BIDDERS
    for _ in range(4):
        ss.add_bidder(sh)
    assert len(sh["bidders"]) == 10                  # no hard max
    x, y, z = (ss.add_line(sh, n) for n in "xyz")
    assert ss.move_line(sh, z["id"], -5) == 0
    assert [ln["desc"] for ln in sh["lines"]] == ["z", "x", "y"]
    ss.add_line(sh, "w", index=1)
    ss.remove_line(sh, x["id"])
    assert [ln["desc"] for ln in sh["lines"]] == ["z", "w", "y"]


# ------------------------------------------------------------ dict / store
def test_round_trip_and_schema():
    sh, _b, _l = sample()
    sh["level"] = "median"
    d = ss.to_dict(sh)
    assert d["schema"] == ss.SCHEMA_VERSION
    back = ss.from_dict(json.loads(json.dumps(d)))
    assert ss.content(back) == ss.content(sh)
    assert back["lines"][0]["bids"] == sh["lines"][0]["bids"]
    with pytest.raises(ss.ScopeError, match="newer version"):
        ss.from_dict(dict(d, schema=ss.SCHEMA_VERSION + 1))
    # junk is cleaned, not trusted
    junk = ss.from_dict({"bidders": [{"id": "b1", "price": "$1,000"}],
                         "lines": [{"desc": "x", "bids": {
                             "b1": {"flag": "yes", "amount": "(5)"},
                             "nobody": {"amount": 1}}}],
                         "award": {"bidder": "nobody"}, "level": "bogus"})
    assert junk["bidders"][0]["price"] == 100000
    assert junk["lines"][0]["bids"] == {"b1": {"flag": "Y",
                                               "amount": -500}}
    assert junk["award"]["bidder"] == "" and junk["level"] == "none"


def test_store_and_prefill(tmp_path):
    from app.pm.store import ProjectStore
    st = ProjectStore(str(tmp_path / "Job"))
    st.data["name"] = "Harbor Example"
    st.set_setting("number", "26-101")
    st.save_record("bidpkg", {"title": "Drywall", "trades": "09 29 00 Drywall",
                              "due": "2026-11-03", "due_time": "2:00 PM",
                              "bidders": [{"company": "Example Drywall LLC",
                                           "contact": "Estimating",
                                           "amount": 12500}]})
    h = ss.prefill_header(st, "09 29 00", "Drywall")
    assert h["project"] == "Harbor Example" and h["project_no"] == "26-101"
    assert h["bid_date"] == "2026-11-03" and h["bid_time"] == "2:00 PM"
    assert h["estimator"] == "Pat Example"
    sh = ss.new_sheet("09 29 00", "Drywall", header=h)
    assert ss.bidders_from_package(st, sh) == 1
    assert sh["bidders"][0]["company"] == "Example Drywall LLC"
    assert sh["bidders"][0]["price"] == 1250000
    assert len(sh["bidders"]) == ss.DEFAULT_BIDDERS  # filled a blank block
    ss.save_sheet(st, sh)
    assert sh["_id"]
    ss.save_sheet(st, ss.duplicate(sh, "Painting"))
    got = ss.list_sheets(st)
    assert [s["trade"] for s in got] == ["Drywall", "Painting"]
    assert got[1]["bidders"][0]["id"] != sh["bidders"][0]["id"]
    ss.delete_sheet(st, got[1])
    assert len(ss.list_sheets(st)) == 1
    assert ss.company_info(st)["name"] == "Example Builders"
    assert ss.budget_label(sh, ss.company_info(st)) == \
        "Example Builders Budget"
    assert ss.budget_label(sh, {"name": ""}) == "Budget"


def test_directory_matches():
    cs = [{"company": "Example Drywall LLC", "division": "09"},
          {"company": "Test Paving Co", "division": "32"},
          {"company": "Sample Gypsum", "trade": "Drywall"},
          {"company": ""}]
    first, rest = ss.directory_matches(cs, "09 29 00", "Drywall")
    assert [c["company"] for c in first] == ["Example Drywall LLC",
                                             "Sample Gypsum"]
    assert [c["company"] for c in rest] == ["Test Paving Co"]


# ------------------------------------------------------------ Excel
def _export(tmp_path, sheets, name="out.xlsx"):
    path = str(tmp_path / name)
    ss.export_xlsx(sheets, path, {"name": "Example Builders", "logo": ""},
                   "Harbor Example")
    return path


def test_excel_export_formulas_and_format(tmp_path):
    from openpyxl import load_workbook
    sh, (a, b, c), _l = sample()
    sh["award"]["bidder"] = b["id"]
    sh2 = ss.new_sheet("32 12 00", "Asphalt paving")
    path = _export(tmp_path, [sh, sh2])
    wb = load_workbook(path)
    assert wb.sheetnames == ["Summary", "09 29 00 Drywall & framing",
                             "32 12 00 Asphalt paving"]
    ws = wb["09 29 00 Drywall & framing"]
    merged = {str(m) for m in ws.merged_cells.ranges}
    for rng in ("B1:S1", "B4:C6", "D7:G8", "H7:I8", "H4:I4", "R4:S4",
                "B16:C16", "B60:C60", "H61:I61", "H62:I62", "F61:G61"):
        assert rng in merged, rng
    assert ws["B4"].value.startswith("TRADE")
    assert ws["E4"].value == "Example Builders Budget"
    assert ws["H4"].value == "Example Drywall LLC"
    assert ws["H4"].fill.fgColor.rgb == ss.YELLOW
    assert ws["B10"].value.startswith("ADDENDA") and "2" in ws["B10"].value
    # live formulas
    assert ws["G16"].value == '=IF(OR(D16="",F16=""),"",ROUND(D16*F16,2))'
    assert ws["G17"].value == Decimal("5000.00")      # a lump sum
    assert ws["H61"].value == \
        '=IF(COUNT(I16:I60)=0,IF(H7="","",H7),SUM(I16:I60))'
    assert ws["H62"].value == '=IF(OR(H7="",COUNT(I16:I60)=0),"",' \
                              'H7-SUM(I16:I60))'
    assert ws["F61"].value.startswith("=IF(COUNT(G16:G60)")
    assert ws["O63"].value == "=J61"                  # award = B's total
    assert ws["I16"].value == Decimal("2900.00")
    assert ws["I18"].value == Decimal("-500.00")
    assert ws["H17"].value == "N"
    for ref in ("I16", "H7", "D7", "F61", "H61", "H62", "G16"):
        assert ws[ref].number_format == ss.ACCOUNTING, ref
    assert ws.page_setup.orientation == "landscape"
    assert ws.page_setup.fitToWidth == 1 and ws.page_setup.fitToHeight == 0
    assert ws.sheet_properties.pageSetUpPr.fitToPage
    assert ws.column_dimensions["B"].width == pytest.approx(46.5)
    assert ws.conditional_formatting                  # math check in red
    summ = wb["Summary"]
    assert summ["D5"].value == "='09 29 00 Drywall & framing'!F61"
    assert "MIN('09 29 00 Drywall & framing'!$H$61:$S$61)" in \
        summ["E5"].value
    assert summ["F5"].value.startswith('=IF(E5="","",IFERROR(INDEX(')
    assert summ["J5"].value == "='09 29 00 Drywall & framing'!O63"
    assert summ["D7"].value == "=SUM(D5:D6)"


def test_excel_more_than_six_bidders_and_long_scope(tmp_path):
    from openpyxl import load_workbook
    sh = ss.new_sheet("32 12 00", "Asphalt paving", bidders=8,
                      header={"project": "Harbor Example"})
    for i, b in enumerate(sh["bidders"]):
        b["company"] = f"Test Paving Co {i + 1}"
    for j in range(50):
        ln = ss.add_line(sh, f"Line {j + 1}")
        ss.set_bid(sh, ln["id"], sh["bidders"][7]["id"], amount=100 + j)
    sh["award"]["bidder"] = sh["bidders"][7]["id"]
    path = _export(tmp_path, [sh])
    wb = load_workbook(path)
    assert wb.sheetnames == ["Summary", "32 12 00 Asphalt paving",
                             "32 12 00 Asphalt paving (2)"]
    p2 = wb["32 12 00 Asphalt paving (2)"]
    assert p2["H4"].value == "Test Paving Co 7"
    assert p2["J4"].value == "Test Paving Co 8"
    assert p2["L4"].value is None
    # 50 lines: the totals move down (rows 16-65, TOTAL 66)
    assert p2["B66"].value == "TOTAL PRICE"
    assert p2["J66"].value.endswith("SUM(K16:K65))")
    p1 = wb["32 12 00 Asphalt paving"]
    assert p1["O68"].value == "='32 12 00 Asphalt paving (2)'!J66"
    assert "'32 12 00 Asphalt paving (2)'!$H$66:$S$66" in \
        wb["Summary"]["E5"].value
    back, _skipped = ss.import_xlsx(path)
    assert len(back) == 1
    assert ss.content(back[0]) == ss.content(sh)


def test_excel_import_round_trip_and_sub_list(tmp_path, monkeypatch):
    from openpyxl import load_workbook
    sh, (a, b, c), _l = sample()
    sh["award"].update(bidder=c["id"], amount=P("8,750"),
                       approved_by="Owner Example", approved_on="2026-11-05")
    sh2 = ss.new_sheet("31 00 00", "Earthwork",
                       header={"project": "Harbor Example"})
    sh2["budget"]["price"] = P("12,000")
    ss.add_line(sh2, "Mass excavation")["lump"] = P("12,000")
    path = _export(tmp_path, [sh, sh2])
    back, skipped = ss.import_xlsx(path)
    assert skipped == 1                                  # the Summary
    assert [ss.title(s) for s in back] == [ss.title(sh), ss.title(sh2)]
    assert ss.content(back[0]) == ss.content(sh)
    assert ss.content(back[1]) == ss.content(sh2)
    # a SUB LIST tab is skipped without being read
    wb = load_workbook(path)
    sl = wb.create_sheet("SUB LIST")
    sl["B4"] = "TRADE: not a scope sheet"
    sl["A1"] = "contact data"
    wb.save(path)
    read = []
    from openpyxl.worksheet import _read_only
    orig = _read_only.ReadOnlyWorksheet._cells_by_row

    def spy(self, *a, **k):
        read.append(self.title)
        return orig(self, *a, **k)
    monkeypatch.setattr(_read_only.ReadOnlyWorksheet, "_cells_by_row", spy)
    back2, skipped2 = ss.import_xlsx(path)
    assert "SUB LIST" not in read and read           # others were read
    assert skipped2 == 2 and len(back2) == 2
    assert all("contact data" not in json.dumps(ss.to_dict(s))
               for s in back2)


def test_import_template_layout(tmp_path):
    """The owner's own layout: TOTAL PRICE on the 2nd of two total rows
    (B62, beside "Math Check"), lump AMOUNT text in the footer."""
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Scope Sheet"
    ws["B1"] = "Harbor Example"
    ws["D2"] = "PROJECT # 26-101"
    ws["N2"] = "ESTIMATOR: Pat"
    ws["B4"] = "TRADE:. 07 50 00 Roofing"
    ws["H4"] = "Example Roofing LLC"
    ws["J4"] = "Test Roof Co"
    ws["H7"] = 10000
    ws["J7"] = 9500
    ws["B10"] = "ADDENDA            1     TO  3"
    ws["H11"] = "YES"
    ws["B16"] = "TPO membrane"
    ws["D16"] = 100
    ws["E16"] = "SQ"
    ws["F16"] = 90
    ws["G16"] = "=D16*F16"
    ws["H16"] = "Y"
    ws["I16"] = 9000
    ws["J16"] = "ALLOW"
    ws["K16"] = 9500
    ws["B17"] = "Flashing"
    ws["H17"] = "Y"
    ws["I17"] = 1000
    ws["J17"] = "N"
    ws["C61"] = "[Your company]"
    ws["H61"] = "=SUM(I16:I60)"
    ws["B62"] = "TOTAL PRICE"
    ws["C62"] = "Math Check"
    ws["H63"] = "RECOMMENDED AWARD TO: Test Roof Co"
    ws["O63"] = "AMOUNT: $9,400"
    ws["I64"] = "OWNER APPROVAL: Owner Example"
    ws2 = wb.create_sheet("Sub List")
    ws2["B4"] = "TRADE"
    path = str(tmp_path / "theirs.xlsx")
    wb.save(path)
    (sh,), skipped = ss.import_xlsx(path)
    assert skipped == 1
    assert sh["csi"] == "07 50 00" and sh["trade"] == "Roofing"
    assert sh["header"]["project_no"] == "26-101"
    assert sh["header"]["estimator"] == "Pat"
    assert (sh["header"]["addenda_from"], sh["header"]["addenda_to"]) == \
        ("1", "3")
    assert [ln["desc"] for ln in sh["lines"]] == ["TPO membrane",
                                                  "Flashing"]
    assert ss.budget_line_total(sh["lines"][0]) == 900000
    a, b = sh["bidders"][:2]
    assert a["checklist"]["bonded"]["ans"] == "YES"
    assert ss.bidder_total(sh, a) == 1000000 and ss.math_check(sh, a) == 0
    assert ss.bid_cell(sh["lines"][0], b["id"]) == {"flag": "ALLOW",
                                                    "amount": 950000}
    assert sh["award"]["bidder"] == b["id"]
    assert ss.award_amount(sh) == 940000
    assert sh["award"]["approved_by"] == "Owner Example"


def test_pdf_export(tmp_path):
    fitz = pytest.importorskip("fitz")
    sh, (a, b, c), _l = sample()
    sh["level"] = "budget"
    sh["award"]["bidder"] = b["id"]
    big = ss.new_sheet("32 12 00", "Asphalt paving", bidders=7)
    path = str(tmp_path / "scope.pdf")
    ss.export_pdf([sh, big], path, {"name": "Example Builders", "logo": ""})
    doc = fitz.open(path)
    assert len(doc) == 3                     # 1 + 2 pages (7 bidders)
    text = doc[0].get_text()
    for s in ("Harbor Example", "Drywall & framing", "Example Drywall LLC",
              "TOTAL PRICE", "($500.00)", "LEVELED TOTAL",
              "RECOMMENDED AWARD TO: Test Paving Co", "$7,000.10"):
        assert s in text, s
    doc.close()
