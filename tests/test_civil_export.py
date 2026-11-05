"""v22: trench volumes by depth band (box or OSHA slopes), structure
counts, cut/fill, and a HeavyBid import file."""
import csv
import math

import pytest

from app import civil_export as ce


def _result():
    return {"pipes": [
        {"name": '8" PVC SDR-35', "size": 8, "system": "sanitary",
         "existing": False, "length": 300.0,
         "runs": [{"length": 200.0, "depth": 7.0},
                  {"length": 100.0, "depth": 12.0}]},
        {"name": '12" RCP', "size": 12, "system": "storm", "existing": False,
         "length": 50.0, "runs": [{"length": 50.0, "depth": None}]},
        {"name": '6" DIP (existing)', "size": 6, "system": "water",
         "existing": True, "length": 80.0,
         "runs": [{"length": 80.0, "depth": 5.0}]}],
        "structures": [
            {"id": "MH-1", "kind": "manhole", "depth": 7.5, "existing": False},
            {"id": "MH-2", "kind": "manhole", "depth": 11.0,
             "existing": False},
            {"id": "MH-3", "kind": "manhole", "depth": 8.0, "existing": False},
            {"id": "CB-1", "kind": "catch basin", "depth": None,
             "existing": False},
            {"id": "MH-9", "kind": "manhole", "depth": 9.0,
             "existing": True}]}


def test_section_matches_catalog_assembly_for_trench_box():
    s = ce.section(8, 8.0, soil="box")
    w = 8 / 12 + 2
    assert s["excavation"] == pytest.approx(w * 8.5)
    assert s["bedding"] == pytest.approx(w * (0.5 + 8 / 24))
    assert s["initial"] == pytest.approx(w * (8 / 24 + 1) - 0.3927 * (8 / 12) ** 2)
    assert s["spoil"] == pytest.approx(w * (8 / 12 + 1.5) * 1.25)


def test_osha_slopes_add_area_only_over_5_ft():
    box = ce.section(8, 8.0, soil="box")
    c = ce.section(8, 8.0, soil="C")                 # 1.5H:1V each side
    assert c["excavation"] - box["excavation"] == pytest.approx(1.5 * 8.5 ** 2)
    assert ce.section(8, 4.0, soil="C")["excavation"] == \
        pytest.approx(ce.section(8, 4.0, soil="box")["excavation"])


def test_volumes_by_pipe_and_depth_band():
    rows = ce.trench_volumes(_result(), soil="box")
    names = [(r["pipe"], r["band"]) for r in rows]
    assert names == [('8" PVC SDR-35', "6-10 ft deep"),
                     ('8" PVC SDR-35', "10-14 ft deep"),
                     ('12" RCP', "depth unknown")]   # existing left out
    r0 = rows[0]
    assert r0["length"] == 200 and r0["depth"] == 7.0
    assert r0["excavation_cy"] == pytest.approx(
        200 * ce.section(8, 7.0)["excavation"] / 27, rel=1e-3)
    assert rows[2]["depth"] == ce.DEFAULT_DEPTH and rows[2]["assumed"]
    tot = ce.totals(rows)
    assert tot["length"] == 350
    assert tot["excavation_cy"] == pytest.approx(
        sum(r["excavation_cy"] for r in rows))


def test_structure_counts_by_kind_and_band():
    rows = ce.structure_counts(_result())
    got = {(r["kind"], r["band"]): r["count"] for r in rows}
    assert got == {("manhole", "6-10 ft deep"): 2,
                   ("manhole", "10-14 ft deep"): 1,
                   ("catch basin", "depth unknown"): 1}


def test_heavybid_export_biditems_and_activities(tmp_path):
    res = _result()
    out = ce.heavybid_csv(str(tmp_path / "hb.csv"), res, soil="B",
                          cut_fill={"cut": 1250.4, "fill": 980.2},
                          job="2611")
    rows = list(csv.DictReader(open(out, encoding="utf-8")))
    assert list(rows[0])[:6] == ["Biditem", "Biditem Description",
                                 "Biditem Quantity", "Biditem Units",
                                 "Activity", "Activity Description"]
    items = {r["Biditem Description"] for r in rows}
    assert '8" PVC SDR-35, 6-10 ft deep' in items
    assert "Manhole, 6-10 ft deep" in items
    assert "Earthwork - cut" in items and "Earthwork - fill" in items
    pipe = [r for r in rows
            if r["Biditem Description"] == '8" PVC SDR-35, 6-10 ft deep']
    acts = {r["Activity Description"]: float(r["Activity Quantity"])
            for r in pipe}
    assert pipe[0]["Biditem Quantity"] == "200.0" and \
        pipe[0]["Biditem Units"] == "LF"
    assert acts["Trench excavation"] == pytest.approx(
        200 * ce.section(8, 7.0, soil="B")["excavation"] / 27, rel=1e-3)
    assert {"Bedding", "Initial backfill", "Final backfill",
            "Haul off spoil"} <= set(acts)
    numbers = [r["Biditem"] for r in rows]
    assert numbers[0] == "10" and all(n.isdigit() for n in numbers)


def test_from_doc_runs_civiltakeoff(monkeypatch):
    from app import civiltakeoff
    monkeypatch.setattr(civiltakeoff, "takeoff", lambda doc, **k: _result())
    rep = ce.report(object())
    assert rep["trench"] and rep["structures"] and rep["totals"]["length"] == 350
    assert math.isfinite(rep["totals"]["excavation_cy"])


JON_ROWS = [
    {"code": "00100", "desc": "CLEARING AND GRUBBING", "unit": "ACRE",
     "qty": 12.5, "client": "1006001", "taxable": False,
     "notes": "Includes haul off site"},
    {"code": "00202", "desc": "UNCLASSIFIED EXCAVATION", "unit": "CY",
     "qty": 4820, "client": "1006002", "taxable": "N",
     "notes": "On-site borrow allowed"},
    {"code": "00403", "desc": "HOT MIX ASPHALT TYPE C", "unit": "TON",
     "qty": "1,875", "client": "1006003", "taxable": "Y",
     "notes": "State spec 403"},
    {"code": "00601", "desc": "RCP 24 IN CL III", "unit": "LF", "qty": "340",
     "client": "1006004", "taxable": True},
    {"code": "00618", "desc": "MOBILIZATION", "unit": "LS", "qty": 1.0,
     "client": "1006005", "taxable": False},
]
JON_CSV = (
    "Biditem Code,Description,Unit,Quantity,Bid Quantity,Type,Client Number,"
    "Sort Code,Summary Sort 1,Parent Biditem,Taxable,WBS Code,Bid Notes\r\n"
    "00100,CLEARING AND GRUBBING,ACRE,12.5,12.5,D,1006001,00100,,,N,,"
    "Includes haul off site\r\n"
    "00202,UNCLASSIFIED EXCAVATION,CY,4820,4820,D,1006002,00202,,,N,,"
    "On-site borrow allowed\r\n"
    "00403,HOT MIX ASPHALT TYPE C,TON,1875,1875,D,1006003,00403,,,Y,,"
    "State spec 403\r\n"
    "00601,RCP 24 IN CL III,LF,340,340,D,1006004,00601,,,Y,,\r\n"
    "00618,MOBILIZATION,LS,1,1,D,1006005,00618,,,N,,\r\n")


def test_heavybid_biditem_csv_matches_jons_header_byte_for_byte(tmp_path):
    p = ce.write_biditems_csv(str(tmp_path / "b.csv"), JON_ROWS)
    assert open(p, "rb").read() == JON_CSV.encode("utf-8")


def test_heavybid_biditem_xlsx_single_sheet_text_codes(tmp_path):
    import openpyxl
    p = ce.write_biditems_xlsx(str(tmp_path / "b.xlsx"), JON_ROWS)
    wb = openpyxl.load_workbook(p)
    assert len(wb.sheetnames) == 1
    rows = [["" if v is None else v for v in r]
            for r in wb.active.iter_rows(values_only=True)]
    assert rows[0] == ce.BID_HEAD
    assert rows[1] == ["00100", "CLEARING AND GRUBBING", "ACRE", 12.5, 12.5,
                       "D", "1006001", "00100", "", "", "N", "",
                       "Includes haul off site"]
    assert len(rows) == 6
    assert rows[4][0] == "00601" and rows[4][3] == 340 and rows[4][10] == "Y"
    assert rows[5][0] == "00618" and rows[5][3] == 1


def test_heavybid_from_takeoff_clean(tmp_path):
    res = _result()
    p = ce.heavybid_xlsx(str(tmp_path / "hb.xlsx"), res, soil="B",
                         cut_fill={"cut": "1,250.4 ", "fill": 980.2})
    import openpyxl
    rows = list(openpyxl.load_workbook(p).active.iter_rows(values_only=True))
    body = rows[1:]
    assert all(isinstance(r[0], str) and len(r[0]) == 5 for r in body)
    assert all(isinstance(r[3], (int, float)) and r[3] == r[4] for r in body)
    assert all(r[5] == "D" and r[10] in ("Y", "N") for r in body)
    d = {r[1]: r for r in body}
    assert d['8" PVC SDR-35, 6-10 ft deep'][3] == 200
    assert d["Earthwork - cut"][3] == 1250.4
    c = ce.heavybid_csv2(str(tmp_path / "hb.csv"), res, soil="B")
    txt = open(c, encoding="utf-8").read()
    assert txt.startswith("Biditem Code,") and "$" not in txt


def test_activity_and_resource_files_share_codes(tmp_path):
    import openpyxl
    out = ce.heavybid_export(str(tmp_path), _result(), soil="B", fmt="xlsx",
                             include=("biditems", "activities", "resources"))
    assert out["check"]["ok"], out["check"]
    rd = lambda k: list(openpyxl.load_workbook(out[k]).active.iter_rows(values_only=True))
    for k in ("biditems", "activities", "resources"):
        assert len(openpyxl.load_workbook(out[k]).sheetnames) == 1
    b, a, r = rd("biditems"), rd("activities"), rd("resources")
    assert list(a[0]) == ce.ACT_HEAD and list(r[0]) == ce.RES_HEAD
    bcodes = {x[0] for x in b[1:]}
    assert {x[0] for x in a[1:]} <= bcodes
    acodes = {(x[0], x[1]) for x in a[1:]}
    assert {(x[0], x[1]) for x in r[1:]} <= acodes
    assert all(isinstance(x[1], str) and x[1].startswith(x[0] + ".") for x in a[1:])
    assert all(isinstance(x[3], (int, float)) for x in a[1:])
    assert any(x[2] == "Trench excavation" for x in a[1:])
    assert all(x[0].startswith("0") for x in a[1:])


def test_orphan_check_flags_all_three_kinds():
    bids = [{"code": "00010"}, {"code": "00020"}]
    acts = [{"biditem": "00010", "code": "00010.01"},
            {"biditem": "00099", "code": "00099.01"}]
    res = [{"biditem": "00010", "activity": "00010.01", "code": "PIPE8"},
           {"biditem": "00010", "activity": "00010.07", "code": "X"}]
    c = ce.check_codes(bids, acts, res)
    assert not c["ok"]
    assert c["activities_without_biditem"] == ["00099.01"]
    assert c["resources_without_activity"] == ["X (00010.07)"]
    assert c["biditems_without_activities"] == ["00020"]


def test_export_refuses_orphans_unless_forced(tmp_path):
    with pytest.raises(ValueError):
        ce.heavybid_export(str(tmp_path), _result(), fmt="csv",
                           extra_resources=[{"biditem": "00010",
                                             "activity": "00010.99",
                                             "code": "ZZ", "qty": 1}])
    out = ce.heavybid_export(str(tmp_path), _result(), fmt="csv", force=True,
                             extra_resources=[{"biditem": "00010",
                                               "activity": "00010.99",
                                               "code": "ZZ", "qty": "1,000"}])
    assert not out["check"]["ok"]
    txt = open(out["resources"], encoding="utf-8").read()
    assert ",1000," in txt and "$" not in txt


def test_heavybid_xlsx_activities_level(tmp_path):
    import openpyxl
    p = ce.heavybid_xlsx(str(tmp_path / "a.xlsx"), _result(), soil="B",
                         level="activities")
    ws = openpyxl.load_workbook(p).active
    rows = list(ws.iter_rows(values_only=True))
    assert list(rows[0]) == ce.ACT_HEAD
    assert any(r[2] == "Trench excavation" for r in rows[1:])
    assert all(isinstance(r[3], (int, float)) for r in rows[1:])
