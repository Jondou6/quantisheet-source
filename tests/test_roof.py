"""Roof plan takeoff math (app/roof.py): slope and hip/valley factors,
pitch parsing, apply() on hand-built takeoff items, derived rows, the
summary table and its export. Numbers from the brief (roof_calc.py)."""
import csv
import math
import os

import pytest

from app import roof

A = dict(abs=0.005)


def item(mtype, value, rtype, pitch=None, page=0, group="", unit=None,
         **extra):
    """A takeoff item as annotate.takeoff_items gives it, run through
    roof.apply with the given roof data."""
    unit = unit or {"area": "sq ft", "length": "ft", "count": "ea"}[mtype]
    r = {"type": rtype, "pitch": pitch, "sheet": "plan"}
    r.update(extra)
    it = {"page": page, "type": mtype, "value": float(value), "unit": unit,
          "group": group, "multiplier": 1.0, "tag": "", "label": ""}
    return roof.apply(it, r)


def total(items, rtype):
    return sum(i["value"] for i in items if i["roof"]["type"] == rtype)


def derived(items, **kw):
    return {d["name"]: d["value"] for d in roof.derived_items(items, **kw)}


# R1
def test_r1_facet_squares_and_waste():
    it = item("area", 1000, "facet", "6")
    assert it["factor"] == pytest.approx(1.118034, abs=1e-6)
    assert it["plan_value"] == 1000
    assert it["value"] == pytest.approx(1118.03, **A)
    d = derived([it], waste_pct=10)
    assert d["Roof squares (no waste)"] == pytest.approx(11.18, **A)
    assert d["Roof squares with 10% waste"] == pytest.approx(12.30, **A)
    assert roof.squares(1118.034) == pytest.approx(11.18, **A)
    assert roof.squares(roof.with_waste(1118.034, 10)) == \
        pytest.approx(12.30, **A)


# R2
@pytest.mark.parametrize("rise,f", [(3, 1.0308), (4, 1.0541), (6, 1.118),
                                    (8, 1.2019), (10, 1.3017),
                                    (12, 1.4142), (0, 1.0)])
def test_r2_slope_factors(rise, f):
    assert roof.slope_factor(rise) == pytest.approx(f, abs=0.0005)


# R3
@pytest.mark.parametrize("rise,f", [(4, 1.0274), (6, 1.0607),
                                    (8, 1.1055), (12, 1.2247)])
def test_r3_hip_valley_equal(rise, f):
    assert roof.hip_valley_factor(rise) == pytest.approx(f, abs=0.0005)
    assert roof.hip_valley_factor(rise, rise) == \
        pytest.approx(math.sqrt(1 + (rise / 12) ** 2 / 2))


def test_r3_hip_lengths():
    assert item("length", 20, "hip", "6")["value"] == \
        pytest.approx(21.21, **A)
    assert item("length", 20, "valley", "6,8")["value"] == \
        pytest.approx(21.54, **A)
    assert roof.hip_valley_factor(0, 6) == 1.0


# R4
def test_r4_rake():
    it = item("length", 15, "rake", "6")
    assert roof.run_of(it["roof"]) == "slope"
    assert it["value"] == pytest.approx(16.77, **A)


def gable():
    """40 x 30 ft gable at 6/12: two 40 x 15 facets, ridge 40, two
    eaves 40, four rakes 15 (plan), drip edge on eaves and rakes."""
    its = [item("area", 600, "facet", "6"), item("area", 600, "facet", "6"),
           item("length", 40, "ridge", "6")]
    its += [item("length", 40, "eave", "6") for _ in range(2)]
    its += [item("length", 15, "rake", "6") for _ in range(4)]
    its += [item("length", 80, "drip", "6", run="level"),
            item("length", 60, "drip", "6")]
    return its


# R5
def test_r5_gable():
    its = gable()
    assert sum(i["plan_value"] for i in its if i["type"] == "area") == \
        pytest.approx(1200.0, **A)
    assert total(its, "facet") == pytest.approx(1341.64, **A)
    assert total(its, "ridge") == pytest.approx(40.0, **A)
    assert total(its, "eave") == pytest.approx(80.0, **A)
    assert total(its, "rake") == pytest.approx(67.08, **A)
    assert total(its, "drip") == pytest.approx(147.08, **A)
    assert total(its, "eave") + total(its, "rake") == \
        pytest.approx(147.08, **A)
    d = derived(its, waste_pct=10)
    assert d["Roof squares (no waste)"] == pytest.approx(13.42, **A)
    assert d["Roof squares with 10% waste"] == pytest.approx(14.76, **A)


# R6
def test_r6_hip_roof():
    # 40 x 30 at 6/12: ridge from (15,15) to (25,15), hips to corners
    trap = (40 + 10) / 2 * 15                 # 375 plan sq ft each
    tri = 30 * 15 / 2                         # 225 plan sq ft each
    its = [item("area", a, "facet", "6") for a in (trap, trap, tri, tri)]
    assert sum(i["plan_value"] for i in its) == pytest.approx(1200.0)
    hip_plan = math.hypot(15, 15)
    its += [item("length", hip_plan, "hip", "6") for _ in range(4)]
    its += [item("length", 10, "ridge", "6")]
    its += [item("length", n, "eave", "6") for n in (40, 40, 30, 30)]
    assert total(its, "facet") == pytest.approx(1341.64, **A)
    assert total(its, "ridge") == pytest.approx(10.0, **A)
    hips = [i for i in its if i["roof"]["type"] == "hip"]
    assert hips[0]["plan_value"] == pytest.approx(21.21, **A)
    assert hips[0]["value"] == pytest.approx(22.50, **A)
    # 3D check: eave corner (0,0,0) to ridge end (15,15,7.5)
    z = 15 * 6 / 12
    assert math.dist((0, 0, 0), (15, 15, z)) == pytest.approx(22.50, **A)
    assert total(its, "hip") == pytest.approx(90.0, **A)
    assert total(its, "eave") == pytest.approx(140.0, **A)
    assert derived(its)["Roof squares (no waste)"] == \
        pytest.approx(13.42, **A)


# R7
def test_r7_low_slope_membrane():
    its = [item("area", 6000, "lowslope", "1/4:12", membrane="TPO"),
           item("length", 320, "parapet", None, parapet_in=24)]
    assert its[0]["factor"] == pytest.approx(1.000217, abs=1e-6)
    assert its[0]["value"] == pytest.approx(6001.30, **A)
    assert "check" not in its[1]               # parapet is level
    d = derived(its, waste_pct=5)
    assert d["Parapet wall flashing"] == pytest.approx(640.0, **A)
    assert d["Low-slope membrane total"] == pytest.approx(6641.30, **A)
    assert d["Low-slope membrane with 5% waste"] == \
        pytest.approx(6973.37, **A)
    assert d["Roof squares with 5% waste"] == pytest.approx(69.73, **A)


def test_r7_parapet_default_height():
    its = [item("length", 100, "parapet")]
    assert "Parapet wall flashing" not in derived(its)
    assert derived(its, parapet_default_in=18)["Parapet wall flashing"] \
        == pytest.approx(150.0)


# R8
def test_r8_counts_and_curbs():
    its = [item("count", 3, "rtu", curb="4x6"),
           item("count", 2, "curb", curb="3 x 3"),
           item("count", 4, "drain"), item("count", 2, "scupper"),
           item("count", 6, "boot"), item("count", 3, "vent")]
    assert all(i["factor"] == 1.0 for i in its)
    assert total(its, "rtu") == 3
    assert total(its, "rtu") + total(its, "curb") == 5
    assert (total(its, "drain"), total(its, "scupper"), total(its, "boot"),
            total(its, "vent")) == (4, 2, 6, 3)
    assert derived(its)["Curb perimeter"] == pytest.approx(84.0)
    rows = roof.summary_rows(its)
    counts = {r[2]: r[6] for r in rows if r[1] == "Count"}
    assert counts["Drain"] == 4 and counts["Curbs (incl. RTU)"] == 5


# R9
def test_r9_cutout_netted_before_factor():
    net = 1200 - 4 * 4                       # annotate nets cutouts first
    it = item("area", net, "facet", "6")
    assert it["plan_value"] == pytest.approx(1184.0)
    assert it["value"] == pytest.approx(1323.75, **A)


# R10
def test_r10_multiplier_already_in_value():
    base = {"page": 0, "type": "area", "value": 3000.0, "unit": "sq ft",
            "group": "", "multiplier": 3.0, "unit_value": 1000.0}
    it = roof.apply(base, {"type": "facet", "pitch": "6"})
    assert it["value"] == pytest.approx(3354.10, **A)
    assert it["unit_value"] == pytest.approx(1118.03, **A)
    assert base["value"] == 3000.0           # input left alone


# R11
def test_r11_tradetakeoff_unchanged():
    pytest.importorskip("fitz")
    from app import tradetakeoff as tt
    assert tt.slope_factor(6) == pytest.approx(1.118034, abs=1e-6)
    assert tt.roof_area(1000, 6, 0.10)["squares"] == \
        pytest.approx(12.2984, abs=1e-4)
    assert roof.slope_factor(6) == tt.slope_factor(6)
    d = derived([item("area", 1000, "facet", "6")], waste_pct=10)
    assert d["Roof squares (no waste)"] == pytest.approx(11.18, **A)
    assert d["Roof squares with 10% waste"] == pytest.approx(12.30, **A)


# R13
def test_r13_no_aerial_import():
    path = os.path.join(os.path.dirname(roof.__file__), "roof.py")
    text = open(path, encoding="utf-8").read()
    for line in text.splitlines():
        s = line.strip()
        if s.startswith(("import ", "from ")):
            assert "aerial" not in s, s
    assert "import aerial" not in text and "aerial_ui" not in text


# R14
def test_r14_pitch_required():
    assert roof.parse_pitch("abc") is None
    assert roof.parse_pitch("30") is None
    assert roof.parse_pitch("-1") is None
    assert roof.parse_pitch("") is None
    assert roof.parse_pitch(None) is None
    assert roof.factor_for({"type": "facet"}) is None
    assert roof.factor_for({"type": "rake", "pitch": "abc"}) is None
    assert roof.factor_for({"type": "hip", "pitch": "6,30"}) is None
    it = item("area", 1000, "facet", None)
    assert it["factor"] is None and it["check"] == "check pitch"
    assert it["value"] == 1000               # never 4/12
    rows = roof.summary_rows([it])
    assert rows[0][5] == "check pitch"


def test_parse_pitch_forms():
    for text, want in [("6", 6), ("6/12", 6), ("6:12", 6), ("6 in 12", 6),
                       ("0.25", 0.25), ("1/4", 0.25), ("1/4:12", 0.25),
                       ('1/4":12', 0.25), ("12/12", 12), ("12", 12),
                       (0, 0), ("1 1/2", 1.5)]:
        assert roof.parse_pitch(text) == pytest.approx(want), text
    assert roof.parse_pitch2("6,8") == (6.0, 8.0)
    assert roof.parse_pitch2("6") == (6.0, 6.0)
    assert roof.parse_pitch2("6,x") is None


def test_pitch_over_12_is_out_of_range_and_flagged():
    """12:12 is the hard cap everywhere: a steeper pitch is never used."""
    assert roof.MAX_PITCH == 12
    for text in ("12.5", "13", "14/12", "18:12", "24", 24, 12.01):
        assert roof.parse_pitch(text) is None, text
    assert roof.parse_pitch2("6,14") is None
    it = item("area", 1000, "facet", "14/12")
    assert it["factor"] is None and it["check"] == "check pitch"
    assert it["value"] == 1000


def test_level_lines_and_elevation():
    assert item("length", 40, "ridge")["value"] == 40     # no pitch needed
    assert item("length", 40, "eave", "6")["factor"] == 1.0
    it = item("length", 16.77, "rake", "6", sheet="elevation")
    assert it["factor"] == 1.0
    assert item("area", 500, "facet", None, sheet="elevation")["value"] \
        == 500
    assert roof.DEFAULT_RUN["hip"] == "hipvalley"
    assert set(roof.AREA_TYPES) == {"facet", "lowslope"}


def test_names():
    assert roof.name_of(item("area", 1, "facet", "6")) == "Roof 6/12"
    assert roof.name_of(item("length", 1, "hip", "6,8")) == "Hip"
    assert roof.pitch_text({"type": "hip", "pitch": "6,8"}) == \
        "6/12 & 8/12"
    assert roof.pitch_text({"type": "lowslope", "pitch": "0.25"}) == \
        "1/4:12"


def test_summary_and_export(tmp_path):
    its = gable()
    rows = roof.summary_rows(its, waste=10)
    facet = [r for r in rows if r[2] == "Roof 6/12"][0]
    assert facet[3] == pytest.approx(1200.0)
    assert facet[6] == pytest.approx(1341.64, **A)
    assert facet[8] == 10
    assert facet[9] == pytest.approx(1475.80, **A)
    assert facet[10] == pytest.approx(13.42, **A)
    alls = [r for r in rows if r[0] == "All" and r[7] == "sq ft"][0]
    assert alls[6] == pytest.approx(1341.64, **A)
    names = [r[2] for r in rows]
    assert "Drip edge drawn" in names and "Eave + rake" in names
    p = roof.export_summary(str(tmp_path / "roof.csv"), rows)
    raw = open(p, "rb").read()
    assert raw.startswith(b"\xef\xbb\xbf") and b"\r\n" in raw
    got = list(csv.reader(open(p, encoding="utf-8-sig")))
    assert got[0] == roof.HEADERS
    assert any(r[2] == "Roof 6/12" and r[6] == "1341.64" for r in got)
    pytest.importorskip("openpyxl")
    x = roof.export_summary(str(tmp_path / "roof.xlsx"), rows)
    import openpyxl
    ws = openpyxl.load_workbook(x).active
    assert [c.value for c in ws[1]] == roof.HEADERS
