"""3D Model Quantities from an IFC model (Nov 23, Jon: its own 3D Model tab
after AI, and in the Takeoff menu). Made-up model text only."""
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import ifcmodel as im  # noqa: E402

try:
    from test_gui import win, qapp  # noqa: F401,E402
except Exception:                                         # noqa: BLE001
    pass

MODEL = r"""ISO-10303-21;
HEADER;
FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');
FILE_NAME('example.ifc','2026-11-23T00:00:00',('Pat'),('Example'),'','','');
FILE_SCHEMA(('IFC4'));
ENDSEC;
DATA;
#1=IFCPROJECT('0a',$,'Example Clinic',$,$,$,$,(#10),#20);
#20=IFCUNITASSIGNMENT((#21,#22));
#21=IFCSIUNIT(*,.LENGTHUNIT.,.MILLI.,.METRE.);
#22=IFCSIUNIT(*,.AREAUNIT.,$,.SQUARE_METRE.);
#30=IFCBUILDINGSTOREY('0b',$,'Level 1',$,$,$,$,$,.ELEMENT.,0.);
#31=IFCBUILDINGSTOREY('0c',$,'Level 2',$,$,$,$,$,.ELEMENT.,3000.);
#100=IFCWALLSTANDARDCASE('w1',$,'Wall-1',$,'Basic Wall:Interior',$,$,'W1',$);
#101=IFCWALLSTANDARDCASE('w2',$,'Wall-2',$,'Basic Wall:Interior',$,$,'W2',$);
#102=IFCDOOR('d1',$,'Door 3''-0" x 7''-0"',$,$,$,$,'D1',2134.,914.,$,$,$);
#103=IFCSLAB('s1',$,'Floor; slab',$,'Slab 4"',$,$,'S1',.FLOOR.);
#104=IFCBEAM('b1',$,'W12X26',$,'W12X26',$,$,'B1',$);
#200=IFCQUANTITYLENGTH('Length',$,$,3048.,$);
#201=IFCQUANTITYAREA('NetSideArea',$,$,9.290304,$);
#202=IFCQUANTITYVOLUME('NetVolume',$,$,0.5,$);
#203=IFCELEMENTQUANTITY('q1',$,'Qto_WallBaseQuantities',$,$,(#200,#201,#202));
#204=IFCRELDEFINESBYPROPERTIES('r1',$,$,$,(#100,#101),#203);
#210=IFCQUANTITYAREA('NetArea',$,$,92.90304,$);
#211=IFCQUANTITYVOLUME('NetVolume',$,$,
  9.4387,$);
#212=IFCELEMENTQUANTITY('q2',$,'Qto_SlabBaseQuantities',$,$,(#210,#211));
#213=IFCRELDEFINESBYPROPERTIES('r2',$,$,$,(#103),#212);
#220=IFCQUANTITYLENGTH('Length',$,$,IFCLENGTHMEASURE(6096.),$);
#221=IFCELEMENTQUANTITY('q3',$,'Qto_BeamBaseQuantities',$,$,(#220));
#222=IFCRELDEFINESBYPROPERTIES('r3',$,$,$,(#104),#221);
#300=IFCRELCONTAINEDINSPATIALSTRUCTURE('c1',$,$,$,(#100,#101,#102,#103),#30);
#301=IFCRELCONTAINEDINSPATIALSTRUCTURE('c2',$,$,$,(#104),#31);
#310=IFCWALLTYPE('t1',$,'Interior - 4 7/8\X2\00A0\X0\in',$,$,$,$,$,$,.STANDARD.);
#311=IFCRELDEFINESBYTYPE('rt',$,$,$,(#100,#101),#310);
/* a comment; with a semicolon */
ENDSEC;
END-ISO-10303-21;
"""


def _write(tmp_path, text=MODEL, name="example.ifc"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def _by(rows):
    return {r["category"]: r for r in rows}


def test_elements_by_kind_type_and_storey(tmp_path):
    rows = im.read(_write(tmp_path))
    by = _by(rows)
    w = by["Walls"]
    assert w["type"] == "Interior - 4 7/8 in" and w["count"] == 2
    assert w["storey"] == "Level 1"
    assert abs(w["length"] - Decimal(20)) < Decimal("0.001")      # 2 x 10 ft
    assert abs(w["area"] - Decimal(200)) < Decimal("0.001")       # 2 x 100 sf
    assert abs(w["volume"] - Decimal("1.3080")) < Decimal("0.001")  # 1 m3
    s = by["Slabs and floors"]
    assert abs(s["area"] - Decimal(1000)) < Decimal("0.001")
    assert s["length"] == 0                       # a slab's length isn't used
    assert abs(s["volume"] - Decimal("12.3454")) < Decimal("0.001")
    d = by["Doors"]
    assert d["count"] == 1 and d["type"] == "Door 3'-0\" x 7'-0\""
    assert not d["has_qty"]
    b = by["Beams"]
    assert b["storey"] == "Level 2"
    assert abs(b["length"] - Decimal(20)) < Decimal("0.001")       # typed value


def test_summary_and_estimate_rows(tmp_path):
    p = _write(tmp_path)
    info = im.summary(p)
    assert info == {"schema": "IFC4", "units": "mm", "elements": 5,
                    "with_qty": 4, "project": "Example Clinic"}
    er = {d: (q, u, c) for d, q, u, c in im.estimate_rows(im.read(p))}
    assert er["Walls - Interior - 4 7/8 in (Level 1)"][1:] == ("sf",
                                                                  "09 21 16")
    assert er["Doors - Door 3'-0\" x 7'-0\" (Level 1)"] == (Decimal(1), "ea",
                                                         "08 10 00")
    assert er["Beams - W12X26 (Level 2)"][1] == "lf"


def test_imperial_model(tmp_path):
    text = MODEL.replace(
        "#20=IFCUNITASSIGNMENT((#21,#22));\n#21=IFCSIUNIT(*,.LENGTHUNIT.,"
        ".MILLI.,.METRE.);\n#22=IFCSIUNIT(*,.AREAUNIT.,$,.SQUARE_METRE.);",
        "#20=IFCUNITASSIGNMENT((#21));\n#21=IFCCONVERSIONBASEDUNIT(#9,"
        ".LENGTHUNIT.,'FOOT',#8);")
    text = text.replace("3048.", "10.").replace("9.290304", "100.") \
        .replace("0.5,$", "27.,$").replace("6096.", "20.")
    by = _by(im.read(_write(tmp_path, text)))
    assert abs(by["Walls"]["length"] - Decimal(20)) < Decimal("0.001")
    assert abs(by["Walls"]["area"] - Decimal(200)) < Decimal("0.001")
    assert abs(by["Walls"]["volume"] - Decimal(2)) < Decimal("0.001")
    assert im.summary(_write(tmp_path, text, "b.ifc"))["units"] == "ft"


def test_a_wall_width_is_not_its_length():
    q = {"Width": ("length", Decimal("0.2")), "Height": ("length", Decimal(3))}
    assert im._pick(q, ("Length",), "length") == Decimal(3)
    assert im._pick({"Width": ("length", Decimal("0.2"))}, ("Length",),
                    "length") is None


def test_a_wall_without_length_gets_none_from_its_height(tmp_path):
    text = MODEL.replace("#200=IFCQUANTITYLENGTH('Length',$,$,3048.,$);",
                         "#200=IFCQUANTITYLENGTH('Height',$,$,3048.,$);")
    w = _by(im.read(_write(tmp_path, text)))["Walls"]
    assert w["length"] == 0 and w["area"] > 0


def test_refuses_what_isnt_a_model(tmp_path):
    import pytest
    p = tmp_path / "x.ifc"
    p.write_text("hello", encoding="utf-8")
    with pytest.raises(im.IfcError):
        im.read(str(p))
    z = tmp_path / "z.ifc"
    z.write_bytes(b"PK\x03\x04rest")
    with pytest.raises(im.IfcError, match="zipped"):
        im.read(str(z))


def test_csv(tmp_path):
    out = im.to_csv(im.read(_write(tmp_path)), str(tmp_path / "q.csv"))
    text = open(out, encoding="utf-8").read()
    assert text.startswith("Category,Type,Storey,IFC class,Count")
    assert "Walls" in text and "200.0" in text


def test_window_tab_menu_and_estimate(win, tmp_path):
    from app import estimate_lines as el, quickaccess as qa
    i = qa.TAB_ORDER.index("AI")
    assert qa.TAB_ORDER[i + 1] == "3D Model"
    act = win.command("3D Model Quantities (IFC)…")
    assert act is not None
    g = win.ribbon.page("3D Model").group("IFC Model")
    assert any(b.defaultAction() is act for b in g.buttons)
    tm = next(a.menu() for a in win.menuBar().actions()
              if a.text().replace("&", "") == "Takeoff")
    assert act in tm.actions()
    dlg = win.model_quantities(_write(tmp_path), show=False)
    assert dlg.table.rowCount() == 4
    assert "Example Clinic" in dlg.intro.text()
    assert "have no quantity set" in dlg.intro.text()
    dlg.storey.setCurrentIndex(dlg.storey.findText("Level 2"))
    assert dlg.table.rowCount() == 1
    dlg.storey.setCurrentIndex(0)
    added, updated = dlg.add_to_estimate()
    assert (added, updated) == (4, 0)
    lines = [ln for ln in el.read(win._view.doc) if ln["source"] == "3D Model"]
    assert len(lines) == 4
    wall = next(ln for ln in lines if ln["desc"].startswith("Walls"))
    assert wall["unit"] == "sf" and Decimal(wall["qty"]) == Decimal("200")
    el.set_unit_cost(win._view.doc, wall["id"], "2")
    assert dlg.add_to_estimate() == (0, 4)          # updated, not doubled
    again = next(ln for ln in el.read(win._view.doc) if ln["id"] == wall["id"])
    assert Decimal(again["mat"]) + Decimal(again["sub"]) + \
        Decimal(again["lab"]) + Decimal(again["eqp"]) > 0  # price kept
    dlg.close()
