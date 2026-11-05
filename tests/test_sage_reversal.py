"""Sage export preview and reversal (review QS-029). Made-up lines."""
from decimal import Decimal

from app import sage_export


def test_reversal_negates_amounts_and_units():
    rows = [{"Job": "99-1", "Cost Code": "03-3000", "Category": "M",
             "Description": "Concrete", "Units": "10", "Unit of Measure":
             "CY", "Amount": "1250.00"},
            {"Job": "99-1", "Amount": "", "Units": ""}]
    rev = sage_export.reversal(rows)
    assert rev[0]["Amount"] == "-1250.00" and rev[0]["Units"] == "-10"
    assert rev[1]["Amount"] == ""
    assert rows[0]["Amount"] == "1250.00"                 # untouched
    pv = sage_export.preview(rows, [{"line": 3}])
    assert pv["lines"] == 2 and pv["total"] == Decimal("1250.00")
    assert pv["jobs"] == ["99-1"] and pv["left_out"] == 1
