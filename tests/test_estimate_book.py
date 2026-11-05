"""AI Takeoff -> estimate workbook by CSI division (SUMMARY, BASE BID,
UNITS & WASTAGE): quantities filled in, rates left blank, lines to check
shaded with their reason."""
import pytest


def _res():
    return {
        "marks": [
            (0, "count", {"measure": {"method": "AI takeoff: schedules",
                                      "type": "count",
                                      "group": "P-1 EXAMPLE LAVATORY",
                                      "csi": "22 40 00"}}),
            (0, "count", {"measure": {"method": "AI takeoff: schedules",
                                      "type": "count",
                                      "group": "P-1 EXAMPLE LAVATORY",
                                      "csi": "22 40 00"}}),
            (1, "line", {"measure": {"method": "AI takeoff: pipe runs",
                                     "type": "length", "value": 120.5,
                                     "group": '2" W'}})],
        "quantities": [{"engine": "roof", "name": "Roof area (plan)",
                        "qty": 5000.0, "unit": "SF", "status": "taken off",
                        "page": 2, "sheet": "A-301", "csi": "07 41 00"}],
        "review": [{"engine": "schedules", "name": "FD EXAMPLE", "qty": None,
                    "unit": "ea", "page": 0,
                    "why": "no tags found on the plans"}]}


ROWS = [{"page": 0, "number": "P-101", "discipline": "plumbing"},
        {"page": 1, "number": "P-201", "discipline": "plumbing"},
        {"page": 2, "number": "A-301", "discipline": "architectural"}]


def test_lines_are_grouped_by_division_and_counted():
    from app import estimate_book as eb
    ls = eb.collect(ROWS, _res())
    by = {l["description"]: l for l in ls}
    assert by["P-1 EXAMPLE LAVATORY"]["qty"] == 2.0
    assert by["P-1 EXAMPLE LAVATORY"]["div"] == "22"
    assert by['2" Waste pipe']["unit"] == "LF"
    assert by["Roof area (plan)"]["div"] == "07"
    assert by["FD EXAMPLE"]["status"] == "review"
    assert by["FD EXAMPLE"]["qty"] is None


def test_workbook_has_the_estimate_layout_and_no_prices(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    from app import estimate_book as eb
    p = tmp_path / "est.xlsx"
    info = eb.write(str(p), eb.collect(ROWS, _res()),
                    project="Example Clinic", gsf=4000.0)
    assert info["review"] == 1
    wb = openpyxl.load_workbook(p)
    assert wb.sheetnames == ["SUMMARY", "BASE BID", "UNITS & WASTAGE"]
    ws = wb["BASE BID"]
    assert [ws.cell(10, c).value for c in range(1, 8)] == [
        "SR #", "REF", "DESCRIPTION", "QUANTITY", "UNIT", "WASTAGE",
        "QUANTITY W/ WASTAGE"]
    rows = {ws.cell(r, 3).value: r for r in range(11, ws.max_row + 1)}
    r = rows['2" Waste pipe']
    assert ws.cell(r, 4).value == 120.5 and ws.cell(r, 5).value == "LF"
    assert str(ws.cell(r, 16).value).startswith("=")
    # every rate cell is empty: no prices
    for rr in range(11, ws.max_row + 1):
        for c in (8, 9, 12, 14):
            assert ws.cell(rr, c).value is None
    rf = rows["FD EXAMPLE"]
    assert str(ws.cell(rf, 18).value).startswith("CHECK")
    assert any("22. PLUMBING" == ws.cell(rr, 7).value
               for rr in range(11, ws.max_row + 1))


def test_general_requirements_are_listed_to_price(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    from app import estimate_book as eb
    p = tmp_path / "g.xlsx"
    eb.write(str(p), eb.collect(ROWS, _res()))
    ws = openpyxl.load_workbook(p)["BASE BID"]
    descs = [ws.cell(r, 3).value for r in range(11, ws.max_row + 1)]
    assert "Supervision and coordination" in descs
    r = descs.index("Mobilization") + 11
    assert ws.cell(r, 4).value == 1.0 and ws.cell(r, 5).value == "LS"
    assert ws.cell(r, 9).value is None          # no price


def test_a_device_drawn_again_is_not_added_to_the_workbook():
    from app import estimate_book as eb
    res = _res()
    res["review"].append({
        "engine": "devices", "name": "EXAMPLE PANEL", "qty": 1, "unit": "ea",
        "page": 1, "why": "the same symbol is drawn on another plan of the "
                          "same floor - counted once"})
    by = {l["description"]: l for l in eb.collect(ROWS, res)}
    assert by["EXAMPLE PANEL"]["qty"] is None
    assert "1 more found here, not added" in by["EXAMPLE PANEL"]["note"]
