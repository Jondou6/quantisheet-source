"""Roof Plan Takeoff wired into the markups (ROOF_PLAN_TAKEOFF_BRIEF R12-R16):
roof keys on the annotation, true quantities in takeoff_items, the
estimate, legend and claims snapshot, the aerial guard."""
import pytest

fitz = pytest.importorskip("fitz")

from app import annotate, claims_hook, estimate, legend, roof  # noqa: E402

PPU = 4.0             # points per foot


def _poly(d, w, h, x, y, roof_data, group=""):
    pts = [[x, y], [x + w * PPU, y], [x + w * PPU, y + h * PPU],
           [x, y + h * PPU]]
    p = dict(pts=pts, color=[0.5, 0, 0.5],
             measure={"type": "area", "value": w * h, "unit": "sq ft",
                      "group": group})
    if roof_data is not None:
        p["roof"] = roof_data
    annotate.apply_op(d, annotate.new_op("add_polygon", 0, **p))


def _line(d, ft, y, roof_data, color=(1, 0, 0)):
    p = dict(pts=[[50, y], [50 + ft * PPU, y]], color=list(color),
             measure={"type": "length", "value": ft, "unit": "ft",
                      "group": ""})
    if roof_data is not None:
        p["roof"] = roof_data
    annotate.apply_op(d, annotate.new_op("add_polyline", 0, **p))


def _gable(with_roof=True):
    """R5: 40 x 30 ft gable at 6/12."""
    d = fitz.open()
    d.new_page(width=1224, height=792)
    annotate.apply_op(d, annotate.new_op("set_scale", 0, ppu=PPU, unit="ft"))
    R = (lambda **k: k) if with_roof else (lambda **k: None)
    for y in (40, 110):
        _poly(d, 40, 15, 40, y, R(type="facet", pitch="6/12"))
    _line(d, 40, 300, R(type="ridge"), (1, 0, 0))
    for y in (320, 330):
        _line(d, 40, y, R(type="eave"), (0, 0.6, 0))
    for y in (340, 350, 360, 370):
        _line(d, 15, y, R(type="rake", pitch="6"), (0.5, 0, 0.5))
    return d


def test_r12_no_roof_keys_no_change():
    items = annotate.takeoff_items(_gable(with_roof=False))
    assert items
    for it in items:
        assert "roof" not in it and "plan_value" not in it
    assert sum(it["value"] for it in items if it["type"] == "area") == 1200


def test_roof_keys_round_trip_and_true_values():
    d = _gable()
    page = d[0]
    a = [x for x in page.annots()
         if (x.info or {}).get("subject", "").startswith("Takeoff:area")][0]
    assert annotate.roof_of(d, a) == {"type": "facet", "pitch": "6/12"}
    items = annotate.takeoff_items(d)
    areas = [it for it in items if it["type"] == "area"]
    assert sum(it["value"] for it in areas) == pytest.approx(1341.64, abs=0.005)
    assert sum(it["plan_value"] for it in areas) == pytest.approx(1200)
    rakes = [it for it in items if (it.get("roof") or {}).get("type") == "rake"]
    assert sum(it["value"] for it in rakes) == pytest.approx(67.08, abs=0.005)


def test_set_annot_changes_pitch_and_clears():
    d = _gable()
    it = [x for x in annotate.takeoff_items(d) if x["type"] == "area"][0]
    annotate.apply_op(d, annotate.new_op("set_annot", 0, **it["ref"],
                                         roof={"type": "facet",
                                               "pitch": "12"}))
    it2 = [x for x in annotate.takeoff_items(d)
           if x["type"] == "area" and x["ref"] == it["ref"]][0]
    assert it2["factor"] == pytest.approx(1.4142, abs=0.0001)
    annotate.apply_op(d, annotate.new_op("set_annot", 0, **it["ref"],
                                         roof={}))
    it3 = [x for x in annotate.takeoff_items(d)
           if x["type"] == "area" and x["ref"] == it["ref"]][0]
    assert "roof" not in it3 and it3["value"] == 600


def test_unpitched_facet_is_flagged_not_defaulted():
    d = fitz.open()
    d.new_page()
    annotate.apply_op(d, annotate.new_op("set_scale", 0, ppu=PPU, unit="ft"))
    _poly(d, 10, 10, 50, 50, {"type": "facet"})
    it = annotate.takeoff_items(d)[0]
    assert it["check"] == roof.CHECK and it["value"] == 100
    _poly(d, 10, 10, 150, 50, {"type": "facet", "pitch": "abc"})
    _poly(d, 10, 10, 250, 50, {"type": "facet", "pitch": "30"})
    assert all(x.get("check") == roof.CHECK
               for x in annotate.takeoff_items(d))


def test_r15_estimate_lines(monkeypatch):
    monkeypatch.setattr(estimate, "roof_waste", lambda: 10.0)
    lines = {(g["name"], g["type"]): g for g in estimate.lines(_gable())}
    assert lines[("Roof 6/12", "area")]["quantity"] == \
        pytest.approx(1341.64, abs=0.005)
    assert lines[("Roof squares (no waste)", "roof")]["quantity"] == \
        pytest.approx(13.42, abs=0.005)
    assert lines[("Roof squares with 10% waste", "roof")]["quantity"] == \
        pytest.approx(14.76, abs=0.005)
    assert lines[("Ridge", "length")]["quantity"] == pytest.approx(40)


def test_r16_legend_and_claims(monkeypatch):
    monkeypatch.setattr(estimate, "roof_waste", lambda: 10.0)
    d = _gable()
    rows = {legend.format_label(r, "takeoff"): legend.format_qty(r, "takeoff")
            for r in legend.rows(d, 0)}
    assert rows["Ridge"] == "40.0 FT"
    assert rows["Roof 6/12"] == "1,341.6 SQ FT"
    assert rows["Rake"] == "67.1 FT"
    snap = claims_hook.snapshot(d)
    items = {i["name"]: i for i in snap["items"]}
    assert items["Roof 6/12"]["qty"] == "1341.6408"
    assert "Roof squares (no waste)" in items


def test_r13_aerial_guard():
    pytest.importorskip("PySide6")
    from app import roof_ui
    d = fitz.open()
    d.new_page()
    annotate.apply_op(d, annotate.new_op(
        "set_scale", 0, ppu=2.0, unit="ft", name="aerial 0.500 ft/px",
        geo={"lat": 32.9, "lon": -80.6, "cx": 1, "cy": 1}))
    assert roof_ui.is_aerial_page(d, 0)
    d.new_page()
    annotate.apply_op(d, annotate.new_op("set_scale", 1, ppu=2.0, unit="ft"))
    assert not roof_ui.is_aerial_page(d, 1)
    for f in ("app/roof_ui.py", "app/roof.py"):
        import os
        src = open(os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), f), encoding="utf-8").read()
        assert "import aerial" not in src and "from .aerial" not in src \
            and "from . import aerial" not in src


def test_r14_pitch_required():
    pytest.importorskip("PySide6")
    from app import roof_ui
    assert roof_ui.check_data({"type": "facet"})
    assert roof_ui.check_data({"type": "facet", "pitch": "abc"})
    assert roof_ui.check_data({"type": "facet", "pitch": "30"})
    assert roof_ui.check_data({"type": "facet", "pitch": "6/12"}) == ""
    assert roof_ui.check_data({"type": "ridge", "run": "level"}) == ""
    assert roof_ui.check_data({"type": "hip", "run": "hipvalley",
                               "pitch": "6,8"}) == ""
    assert roof_ui.check_data({"type": "drain"}) == ""
