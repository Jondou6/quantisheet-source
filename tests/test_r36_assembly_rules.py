"""r36 v2 step 7 (G1.1, G1.5): Assembly Rules - YOUR rules file maps
takeoff group names (exact, a * pattern or re:regex) and a takeoff type
to an assembly (a library assembly, an assembly written in the rule, or
the wall-type legend's), with property overrides and a Waste % per part.
Apply shows a preview, skips groups something already prices, lists the
groups no rule matched for review, and writes once (one Undo). A
built-in or shipped assembly is copied with every price and labor hour
at 0 (G1.5); your own library assemblies keep theirs. The price database
is never made or changed. Made-up data only."""
import json
import math
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import annotate, assemblies, embfiles, estimate, pricedb, settings  # noqa
from app.estimating import _io, assembly_rules as AR, wall_legends as WL  # noqa
from estimate_helpers import area, blank_doc                        # noqa: E402
from test_r36_wall_legend_assemblies import DESCS                   # noqa: E402


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    os.makedirs(settings.DIR, exist_ok=True)
    from app import assembly_csv
    monkeypatch.setattr(assembly_csv, "_CACHE", {})


def _line(d, name, ft, y):
    annotate.apply_op(d, annotate.new_op(
        "add_line", 0, pts=[[100, y], [100 + ft * 10, y]],
        measure={"type": "length", "value": ft, "unit": "ft", "group": name}))


def _doc():
    d = blank_doc()
    area(d, "Floor LVT-1", 10, 10)
    area(d, "Office ACT ceiling", 10, 10, x0=200)
    _line(d, "Wall Type 1A", 20, 500)
    _line(d, "Corridor partition", 30, 550)
    _line(d, "Thing 7", 5, 600)
    area(d, "Floor LVT-2 priced", 5, 5, x0=400)
    estimate.set_price(d, "Floor LVT-2 priced", "area", "sq ft",
                       unit_cost=3, cost_type="Material")
    return d


RULES = {"version": 1, "rules": [
    {"group": "Wall Type *", "type": "length", "assembly": "wall legend",
     "waste": {"Board": 10}},
    {"group": "re:\\blvt\\b", "type": "area",
     "assembly": "Flooring - Resilient (LVT/VCT)", "props": {"Waste": 12}},
    {"group": "*ceiling*", "type": "area", "assembly": {
        "measure": "area", "parts": [
            {"name": "Tile", "unit": "ea", "qty": "ceil(Area/4)",
             "cost": 2.5}]}, "waste": {"Tile": 5}},
    {"group": "*partition*", "type": "length",
     "assembly": "Interior Wall - 3-5/8\" Metal Stud",
     "waste": {"Track": 20}},
]}


def _legend():
    return WL.build({"1A": DESCS[0]}, heights={"1A": 10})


def _rows(pv):
    return {r["group"]: r for r in pv["rows"]}


def test_preview_matches_rules_in_order_and_lists_the_rest():
    d = _doc()
    pv = AR.preview(d, AR.validate(RULES), legend=_legend())
    by = _rows(pv)
    assert by["Wall Type 1A"]["status"] == "apply"
    assert by["Wall Type 1A"]["rule"] == 1
    assert by["Floor LVT-1"]["assembly"] == "Flooring - Resilient (LVT/VCT)"
    assert by["Office ACT ceiling"]["rule"] == 3
    assert by["Corridor partition"]["rule"] == 4
    assert by["Floor LVT-2 priced"]["status"] == "priced"
    assert by["Thing 7"]["status"] == "needs review"
    assert pv["counts"] == {"apply": 4, "priced": 1, "needs review": 1,
                            "error": 0}


def test_apply_once_zeroes_sample_prices_and_applies_per_part_waste(
        monkeypatch):
    d = _doc()
    pv = AR.preview(d, AR.validate(RULES), legend=_legend())
    puts = []
    real = embfiles.put
    monkeypatch.setattr(embfiles, "put", lambda *a, **k: (puts.append(a[1]),
                                                          real(*a, **k)))
    n = AR.apply(d, pv)
    assert n == 4 and puts == [assemblies.JOB_FILE]
    rows, _t, _e = assemblies.rollup(d, added=False)
    by = {r["name"]: r for r in rows}
    assert set(by) == {"Wall Type 1A", "Floor LVT-1", "Office ACT ceiling",
                       "Corridor partition"}
    for name in ("Floor LVT-1", "Corridor partition"):      # built-ins
        assert by[name]["material"] == 0 and by[name]["labor_cost"] == 0
        assert by[name]["labor_hours"] == 0
    lvt = {p["name"]: p for p in by["Floor LVT-1"]["parts"]}
    assert lvt["Flooring"]["qty"] == math.ceil(100 * (1 + 12 / 100))
    part = {p["name"]: p for p in by["Corridor partition"]["parts"]}
    assert part["Track"]["qty"] == pytest.approx(30 * 2 * 1.1 * 1.2)
    ceil = {p["name"]: p for p in by["Office ACT ceiling"]["parts"]}
    assert ceil["Tile"]["qty"] == pytest.approx(25 * 1.05)
    assert by["Office ACT ceiling"]["material"] > 0       # your own price
    wall = {p["name"]: p for p in by["Wall Type 1A"]["parts"]}
    board = next(v for k, v in wall.items() if "type X gypsum board" in k)
    assert board["qty"] == pytest.approx(20 * 10 * 2 * 1.1)
    job = assemblies.read_job(d)["assemblies"]
    assert "sample prices removed" in job["Floor LVT-1"]["source"]
    # again: everything is priced now - nothing changes
    pv2 = AR.preview(d, AR.validate(RULES), legend=_legend())
    assert pv2["counts"]["apply"] == 0 and AR.apply(d, pv2) == 0


def test_your_own_library_assembly_keeps_its_prices():
    own = json.loads(json.dumps(assemblies.BUILT_IN[0]))
    own["name"] = "My wall"
    assemblies.save_to_library(own)
    d = blank_doc()
    _line(d, "Partition A", 10, 500)
    pv = AR.preview(d, AR.validate({"rules": [
        {"group": "Partition*", "assembly": "My wall"}]}))
    AR.apply(d, pv)
    rows, _t, _e = assemblies.rollup(d, added=False)
    assert rows[0]["material"] > 0


def test_bad_rules_are_refused_with_the_rule_number():
    for bad, word in (({"rules": [{"assembly": "x"}]}, "group"),
                      ({"rules": [{"group": "re:([", "assembly": "x"}]},
                       "pattern"),
                      ({"rules": [{"group": "a", "assembly": "x",
                                   "waste": {"Board": "lots"}}]}, "waste"),
                      ({"rules": [{"group": "a"}]}, "assembly"),
                      ({"rules": [{"group": "a", "assembly": "x",
                                   "type": "volume"}]}, "type"),
                      ({"nope": 1}, "rules")):
        with pytest.raises(AR.RulesError) as e:
            AR.validate(bad)
        assert word in str(e.value).lower()
        if "rules" in bad and bad["rules"]:
            assert "rule 1" in str(e.value).lower()


def test_row_errors_unknown_assembly_part_or_measure():
    d = _doc()
    pv = AR.preview(d, AR.validate({"rules": [
        {"group": "Floor LVT-1", "assembly": "No such assembly"},
        {"group": "Office ACT ceiling", "assembly": "Ceiling - 2x2 ACT",
         "waste": {"Nope": 5}},
        {"group": "Corridor partition", "assembly": "Ceiling - 2x2 ACT"},
        {"group": "Wall Type 1A", "assembly": "wall legend"}]}),
        legend=WL.build({}))
    by = _rows(pv)
    assert "no such assembly" in by["Floor LVT-1"]["why"].lower()
    # a part the assembly hasn't got: applied, waste not used, said so
    assert by["Office ACT ceiling"]["status"] == "apply"
    assert "waste not used for nope" in by["Office ACT ceiling"]["why"].lower()
    # the note lists the parts the assembly HAS, labelled as such (not as missing ones)
    assert "no such part" not in by["Office ACT ceiling"]["why"]
    assert "its parts are:" in by["Office ACT ceiling"]["why"]
    assert "area" in by["Corridor partition"]["why"]
    assert "legend" in by["Wall Type 1A"]["why"]
    assert pv["counts"]["error"] == 3
    assert AR.apply(d, pv) == 1


def test_rules_file_load_save_and_no_database(tmp_path):
    p = str(tmp_path / "my rules.json")
    AR.save(AR.example_rules(), p)
    r = AR.load(p)
    assert r["rules"] and all("EXAMPLE" in x.get("note", "")
                              for x in r["rules"])
    assert "cost" not in json.dumps(r)                  # no prices in it
    AR.save(r, p)                                        # backup kept
    assert os.listdir(os.path.join(settings.DIR, "backups"))
    with pytest.raises(_io.PathError):
        AR.save(r, os.path.join(os.path.dirname(_io.__file__), "r.json"))
    bad = tmp_path / "bad.json"
    bad.write_text("{", encoding="utf-8")
    with pytest.raises(AR.RulesError):
        AR.load(str(bad))
    d = _doc()
    AR.apply(d, AR.preview(d, r, legend=_legend()))
    assert not os.path.exists(pricedb.path())           # never made
