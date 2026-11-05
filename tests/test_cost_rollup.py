from decimal import Decimal as D
import pytest
from app import cost_rollup as cr

LINES = [
    {"code": "00100", "trade": "Framing", "L": D("600.00"), "M": D("264.00"),
     "E": D("120.00"), "total": D("984.00")},
    {"code": "00200", "trade": "Doors", "L": D("220.00"), "M": D("900.00"),
     "E": D("0"), "total": D("1120.00")},
    {"code": "00300", "trade": "Framing", "L": D("100.00"), "M": D("0"),
     "E": D("0"), "total": D("100.00")},
]


def test_by_trade():
    t = cr.by_trade(LINES)
    assert t["Framing"]["total"] == D("1084.00") and t["Doors"]["M"] == D("900.00")


def test_cascade_compounds_in_order_and_tax_on_material_only():
    casc = [("gc", "10"), ("overhead", "5"), ("profit", "10"), ("bond", "1"),
            ("insurance", "0"), ("contingency", "0"), ("escalation", "2")]
    r = cr.summary(LINES, casc, tax_pct="8", building_sf="1000")
    assert r["direct"] == D("2204.00")
    assert r["material"] == D("1164.00")
    assert r["tax"] == D("93.12")                  # 1164 * 8%
    # by hand: 2297.12 -> gc 229.71 -> 2526.83 -> oh 126.34 -> 2653.17
    # -> profit 265.32 -> 2918.49 -> bond 29.18 -> 2947.67 -> esc 58.95 -> 3006.62
    amts = [s["amount"] for s in r["steps"]]
    assert amts == [D("229.71"), D("126.34"), D("265.32"), D("29.18"),
                    D("0.00"), D("0.00"), D("58.95")]
    assert r["total"] == D("3006.62")
    assert r["per_sf"] == D("3.01")
    assert all(isinstance(v, D) for v in (r["total"], r["tax"], r["direct"]))


def test_per_sf_missing():
    r = cr.summary(LINES, [], building_sf=None)
    assert r["per_sf"] is None and r["per_sf_text"] == "enter building SF"
    assert r["total"] == D("2204.00")


def test_user_can_edit_order_and_add_steps():
    r = cr.summary(LINES, [("profit", "10"), ("gc", "10")])
    assert [s["key"] for s in r["steps"]] == ["profit", "gc"]
    assert r["total"] == D("2666.84")             # 2204 -> 2424.40 -> 2666.84


@pytest.mark.parametrize("ext", ["csv", "xlsx"])
def test_export(tmp_path, ext):
    r = cr.summary(LINES, [("gc", "10")], tax_pct="8", building_sf="1000")
    p = cr.export(str(tmp_path / f"s.{ext}"), r)
    if ext == "csv":
        txt = open(p, encoding="utf-8").read()
        assert "Framing" in txt and "2526.83" in txt and "$" not in txt
    else:
        import openpyxl
        ws = openpyxl.load_workbook(p).active
        vals = [c for row in ws.iter_rows(values_only=True) for c in row]
        assert "Doors" in vals and 2526.83 in vals
