import csv
from decimal import Decimal as D
import pytest
from app import assembly_codes as ac
from costlayer_helpers import LIB_ROWS, blank, wall, door


def lib(tmp_path, ext="csv"):
    p = tmp_path / f"lib.{ext}"
    ac.write_rows(str(p), LIB_ROWS)
    return ac.read(str(p))


@pytest.mark.parametrize("ext", ["csv", "xlsx"])
def test_read_codes_text_and_components(tmp_path, ext):
    L = lib(tmp_path, ext)
    a = L["00100"]
    assert a["code"] == "00100" and a["unit"] == "LF" and a["trade"] == "Framing"
    kinds = [c["type"] for c in a["components"]]
    assert kinds == ["L", "M", "E"]
    assert a["components"][1]["rate"] == D("4.00")
    assert a["components"][0]["activity"] == "00100.01"


def test_round_trip_through_heavybid_export(tmp_path):
    from app import civil_export as ce
    L = lib(tmp_path)
    bids, acts, res = ac.to_heavybid(L, {"00100": 40, "00200": 3})
    assert ce.check_codes(bids, acts, res)["ok"]
    out = tmp_path / "hb"
    out.mkdir()
    ce.write_biditems_xlsx(str(out / "b.xlsx"), bids)
    back = ac.from_heavybid(bids, acts, res)
    assert set(back) == {"00100", "00200"}
    a = back["00100"]
    assert [c["type"] for c in a["components"]] == ["L", "M", "E"]
    assert a["components"][1]["qty"] == D("1.5")
    assert a["components"][2]["rate"] == D("150.00")


def test_extend_with_waste_on_material_hand_checked(tmp_path):
    L = lib(tmp_path)
    x = ac.extend(L["00100"], 40, waste_pct=10)
    # L: 40*0.25*60 = 600.00; M: 40*1.5*1.10 = 66 ea * 4 = 264.00; E: 40*0.02*150 = 120.00
    assert x["L"] == D("600.00") and x["M"] == D("264.00") and x["E"] == D("120.00")
    assert x["total"] == D("984.00")


def test_unpriced_component_flagged_not_zeroed(tmp_path):
    rows = [r[:] for r in LIB_ROWS]
    rows[1][10] = ""
    p = tmp_path / "u.csv"
    ac.write_rows(str(p), rows)
    x = ac.extend(ac.read(str(p))["00100"], 10)
    assert x["unpriced"] == ["MAT01 Studs and plates"]


def test_bind_is_explicit_and_saved_in_pdf(tmp_path):
    L = lib(tmp_path)
    doc = blank()
    wall(doc, 0, 40)
    door(doc, 0, 50)
    door(doc, 0, 90)
    lines, unbound = ac.priced_lines(doc, L)
    assert lines == [] and len(unbound) == 2          # never auto-picked
    ac.bind(doc, "Interior Wall", "length", "ft", "00100", waste_pct=10)
    ac.bind(doc, "Door", "count", "ea", "00200")
    doc2 = __import__("fitz").open("pdf", doc.tobytes())
    lines, unbound = ac.priced_lines(doc2, L)
    assert unbound == []
    by = {l["code"]: l for l in lines}
    assert by["00100"]["qty"] == D("40") and by["00100"]["total"] == D("984.00")
    # door: 3? no - 2 doors: L 2*2*55=220, M 2*450=900
    assert by["00200"]["total"] == D("1120.00")
    with pytest.raises(KeyError):
        ac.bind(doc, "Door", "count", "ea", "99999", library=L)


def test_insert_assembly_with_quantity(tmp_path):
    L = lib(tmp_path)
    doc = blank()
    ac.insert(doc, "00200", 4, note="Owner add")
    lines, _ = ac.priced_lines(doc, L)
    assert lines[0]["source"] == "inserted" and lines[0]["total"] == D("2240.00")


def test_template_and_example_files_ship_no_prices():
    t = list(csv.reader(open(ac.TEMPLATE, encoding="utf-8")))
    assert t == [ac.COLS]
    ex = list(csv.reader(open(ac.EXAMPLE, encoding="utf-8")))
    assert ex[0] == ac.COLS and len(ex) > 2
    assert all(r[1].startswith("EXAMPLE") for r in ex[1:])
    assert all(r[10] == "" for r in ex[1:])            # no made-up rates
