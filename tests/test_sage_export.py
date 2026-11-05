"""Sage 300 CRE Job Cost budget export: estimate lines to Job / Extra /
Cost Code / Category rows, with the lines that can't go in reported."""
from decimal import Decimal

import pytest

from app import sage_export as sage


def plain(name="Slab on grade", code="03 30 00", cat="Material",
          qty=1200.0, unit="SF", total=8400.0, **kw):
    """A line like estimate.lines() gives, with a code and category."""
    ln = {"name": name, "type": "area", "unit": unit, "count": 3,
          "quantity": qty, "waste": 0.0, "multiplier": 1.0,
          "unit_cost": total / qty if qty else 0.0, "adjusted": qty,
          "total": total, "pages": "1, 2", "cost_code": code,
          "category": cat}
    ln.update(kw)
    return ln


def coded(code="033000", desc="Footings", qty="40", unit="CY",
          L="1000.00", M="2500.50", E="0.00", **kw):
    """A line like assembly_codes.priced_lines() gives."""
    ln = {"code": code, "desc": desc, "trade": "Concrete", "unit": unit,
          "qty": Decimal(qty), "L": Decimal(L), "M": Decimal(M),
          "E": Decimal(E), "total": Decimal(L) + Decimal(M) + Decimal(E),
          "unpriced": [], "group": "F1", "source": "takeoff"}
    ln.update(kw)
    return ln


def test_categories_and_codes():
    assert [sage.category(c) for c in
            ("Labor", "Labour", "Material", "Subcontract", "Subcontractor",
             "Equipment", "Other", "L", "eq", "X", "Overhead")] == \
        ["L", "L", "M", "S", "S", "E", "O", "L", "E", "O", "O"]
    assert sage.category("Bananas") == ""
    assert sage.cost_code("03 30 00") == "03-3000"
    assert sage.cost_code("092116") == "09-2116"
    assert sage.cost_code("9.21.16.13") == "09-2116"
    assert sage.cost_code("9.21.16.13", "{div}{a}{b}.{ext}") == \
        "092116.13"
    assert sage.cost_code("Footings") == ""


def test_plain_line_is_one_row():
    rows, problems = sage.job_cost_rows([plain()], job="2417")
    assert problems == []
    assert rows == [{"Job": "2417", "Extra": "", "Cost Code": "03-3000",
                     "Category": "M", "Description": "Slab on grade",
                     "Units": Decimal("1200.0000"), "Unit of Measure": "SF",
                     "Amount": Decimal("8400.00")}]


def test_coded_line_splits_into_categories():
    rows, problems = sage.job_cost_rows([coded()], job="2417")
    assert problems == []
    assert [(r["Cost Code"], r["Category"], r["Amount"]) for r in rows] == \
        [("03-3000", "L", Decimal("1000.00")),
         ("03-3000", "M", Decimal("2500.50"))]      # no $0 E row
    assert all(r["Units"] == 40 for r in rows)


def test_code_passed_through():
    rows, problems = sage.job_cost_rows([coded(code="CONC-100")],
                                        phase_from="code")
    assert problems == []
    assert {r["Cost Code"] for r in rows} == {"CONC-100"}
    rows, problems = sage.job_cost_rows([coded(code="CONC-100")])
    assert rows == [] and problems[0]["reason"] == "no CSI cost code"
    with pytest.raises(ValueError):
        sage.job_cost_rows([], phase_from="uniformat")


@pytest.mark.parametrize("line, reason", [
    (plain(qty=0.0), "quantity is 0"),
    (plain(qty=-5.0, adjusted=-5.0), "quantity is -5"),
    (plain(adjusted=float("nan")), "quantity is blank or not a number"),
    (plain(adjusted=float("inf")), "quantity is blank or not a number"),
    (plain(adjusted="lots"), "quantity is blank or not a number"),
    (plain(total=0.0), "M amount is 0"),
    (plain(total=-10.0), "M amount is -10"),
    (plain(total=float("nan")), "amount is blank or not a number"),
    (plain(code=""), "no CSI cost code"),
    (plain(cat=""), "no cost category"),
    (plain(cat="Bananas"), "unknown cost category 'Bananas'"),
    (coded(L="0", M="0"), "amount is 0"),
    (coded(L="-1"), "L amount is -1"),
    (coded(unpriced=["R100 Rebar"]), "unpriced components: R100 Rebar"),
])
def test_problems_are_reported_not_exported(line, reason):
    rows, problems = sage.job_cost_rows([plain(name="Good"), line])
    assert [r["Description"] for r in rows] == ["Good"]
    assert len(problems) == 1
    assert problems[0]["line"] == 2
    assert problems[0]["reason"].startswith(reason)


def test_default_category_for_lines_without_one():
    rows, problems = sage.job_cost_rows([plain(cat="")],
                                        default_category="Subcontract")
    assert problems == [] and rows[0]["Category"] == "S"


def test_same_code_and_category_add_up():
    rows, problems = sage.job_cost_rows([
        plain("Slab A", qty=100.0, total=700.0),
        plain("Slab B", qty=50.5, total=353.5),
        plain("Slab labor", cat="Labor", qty=150.5, total=900.0)])
    assert problems == []
    assert [(r["Category"], r["Units"], r["Amount"]) for r in rows] == \
        [("L", Decimal("150.5000"), Decimal("900.00")),
         ("M", Decimal("150.5000"), Decimal("1053.50"))]
    assert rows[1]["Description"] == "Slab A"


def test_two_units_on_one_budget_is_a_problem():
    rows, problems = sage.job_cost_rows([
        plain("Slab", unit="SF"), plain("Slab CY", unit="CY", qty=40.0,
                                        total=6000.0),
        plain("Walls", code="04 22 00")])
    assert [r["Cost Code"] for r in rows] == ["04-2200"]
    assert "more than one unit" in problems[0]["reason"]


def test_export_csv(tmp_path):
    rows, _ = sage.job_cost_rows([coded(), plain("Rebar", "03 21 00",
                                                 qty=2.5, unit="TON",
                                                 total=4250.0)], job="2417")
    path = str(tmp_path / "budget.csv")
    assert sage.export_csv(path, rows) == path
    raw = open(path, "rb").read()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert raw.count(b"\r\n") == 4 and b"\n\n" not in raw
    lines = raw.decode("utf-8-sig").split("\r\n")
    assert lines[0] == ("Job,Extra,Cost Code,Category,Description,Units,"
                        "Unit of Measure,Amount")
    assert lines[1] == "2417,,03-2100,M,Rebar,2.5,TON,4250.00"
    assert lines[2] == "2417,,03-3000,L,Footings,40,CY,1000.00"
    assert lines[3] == "2417,,03-3000,M,Footings,40,CY,2500.50"
