"""r36 v2 step 4: applying a starter to a drawing. Placeholders are
suggested from the takeoff group names (generic trade words in the
template, never a job's names), a placeholder can take several groups
(one line per group), groups already priced are left alone, the blank
prices are shown by the error check (never a silent $0), and the
quantities follow the takeoff. Civil: the starter pay items, each
activity from the takeoff on its pay item, and pipe / structure material
(price blank) on the order list. Made-up drawing, no prices."""
import os
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import (annotate, assemblies, estimate, estimate_lines as EL,  # noqa
                 heavy, settings)
from app.estimating import (checks, crewhours, materials, starters,  # noqa
                            templates)
from estimate_helpers import area, blank_doc                  # noqa: E402

D = Decimal
LIB = {"equipment": {}, "labor": {},
       "crews": {"PIPE": {"labor": [], "equipment": []},
                 "MH": {"labor": [], "equipment": []}},
       "settings": {"fuel": 0}}


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


def _line(d, group, ft, y):
    annotate.apply_op(d, annotate.new_op(
        "add_line", 0, pts=[[100, y], [200, y]],
        measure={"type": "length", "value": ft, "unit": "ft",
                 "group": group}))


def _count(d, group, x, y):
    annotate.apply_op(d, annotate.new_op(
        "add_count", 0, pt=[x, y], n=1, color=[0.8, 0.2, 0.1],
        measure={"type": "count", "value": 1, "unit": "ea",
                 "group": group}))


def _drawing():
    d = blank_doc()
    area(d, "Test OFFICE 101", 10, 12)                   # 120 sq ft
    area(d, "Test LOBBY 102", 20, 10, x0=300)            # 200 sq ft
    area(d, "Test roof", 30, 20, y0=400)                 # 600 sq ft
    _line(d, "Test interior partition", 80, 300)
    _count(d, "Test door type A", 700, 300)
    _count(d, "Test door type A", 720, 300)
    return d


def _gc():
    return next(t for t in starters.estimate_templates()
                if "commercial" in t["name"].lower())


def test_suggest_binds_groups_by_trade_words_and_skips_priced():
    d = _drawing()
    estimate.set_price(d, "Test roof", "area", "sq ft", unit_cost=4,
                       cost_type="Subcontract")
    b = starters.suggest_bindings(d, _gc())
    names = {ph: sorted(g[0] for g in gs) for ph, gs in b.items()}
    assert names["Floor area"] == ["Test LOBBY 102", "Test OFFICE 101"]
    assert names["Interior wall length"] == ["Test interior partition"]
    assert names["Doors"] == ["Test door type A"]
    assert "Roof area" not in names                  # already priced
    used = [g for gs in b.values() for g in gs]
    assert len(used) == len(set(used))               # one placeholder each


def test_apply_starter_links_lines_with_blank_prices_that_follow_takeoff():
    d = _drawing()
    tpl = _gc()
    ids = templates.apply(d, tpl, starters.suggest_bindings(d, tpl))
    lines = {ln["id"]: ln for ln in EL.read(d)}
    assert ids and set(ids) <= set(lines)
    linked = [lines[i] for i in ids if lines[i].get("link")]
    groups = {ln["link"]["name"] for ln in linked}
    assert {"Test OFFICE 101", "Test LOBBY 102", "Test interior partition",
            "Test door type A"} <= groups
    assert all(D(ln[k]) == 0 for ln in linked for k in
               ("mat", "lab", "eqp", "sub"))
    per_group = [ln for ln in linked if ln["link"]["name"] ==
                 "Test OFFICE 101"]
    assert all(ln["desc"].endswith(" - Test OFFICE 101") for ln in per_group)
    found = checks.run(d)
    assert {f["rule"] for f in found} >= {"no_cost"}
    blank = [f for f in found if f["rule"] == "no_cost"]
    assert len(blank) >= len([ln for ln in linked])  - 2
    pr = {p["id"]: p for p in EL.priced(d)}
    door = next(i for i in ids if lines[i]["link"] and
                lines[i]["link"]["name"] == "Test door type A")
    before = pr[door]["quantity"]
    _count(d, "Test door type A", 740, 300)
    assert {p["id"]: p for p in EL.priced(d)}[door]["quantity"] == \
        before * 3 / 2


def test_civil_fill_puts_activities_on_pay_items_with_pipe_material():
    d = blank_doc()
    _line(d, 'Test 8" PVC sanitary sewer, 6-10 ft deep', 400, 300)
    _line(d, 'Test 2" water, depth unknown', 250, 340)
    _count(d, "Test manhole", 700, 300)
    _count(d, "Test manhole", 720, 300)
    job = heavy.blank()
    heavy.activities_from_takeoff(d, job, LIB)
    assert crewhours.by_pay_item(job, LIB)["unassigned"]["activities"] == 3
    r = starters.civil_fill(job)
    assert r["pay_items_added"] == len(starters.civil_pay_items()["items"])
    assert r["assigned"] == 3 and r["materials_added"] == 3
    by = {a["name"]: a for a in job["activities"]}
    pays = {p["no"]: p["desc"].lower() for p in job["pay_items"]}
    assert "sanitary" in pays[by['Test 8" PVC sanitary sewer, 6-10 ft deep']
                              ["pay_item"]]
    assert "water" in pays[by['Test 2" water, depth unknown']["pay_item"]]
    assert "manhole" in pays[by["Test manhole"]["pay_item"]]
    ch = crewhours.by_pay_item(job, LIB)
    assert ch["unassigned"]["activities"] == 0
    rows = {r["desc"]: r for r in materials.collect(None, job, LIB)}
    pipe = rows['Test 8" PVC sanitary sewer pipe']
    assert pipe["qty"] == D(400) and pipe["unit"] == "LF"
    assert pipe["cost"] == D("0.00")
    assert rows['Test 2" water pipe']["qty"] == D(250)
    assert rows["Test manhole"]["qty"] == D(2)
    again = starters.civil_fill(job)
    assert again == {"pay_items_added": 0, "assigned": 0,
                     "materials_added": 0, "not_matched": []}


def test_apply_can_leave_out_items_whose_placeholder_has_no_group():
    # real-job finding (step 4): a starter on a job without, say, storm
    # pipe added dozens of 0-quantity lines; skip_unlinked leaves the
    # unlinked placeholder items out (typed items without a placeholder
    # still go in)
    d = _drawing()
    tpl = _gc()
    b = starters.suggest_bindings(d, tpl)
    ids = templates.apply(d, tpl, b, skip_unlinked=True)
    lines = [ln for ln in EL.read(d) if ln["id"] in ids]
    typed = [it for it in tpl["items"] if not it["placeholder"]]
    linked = [ln for ln in lines if ln.get("link")]
    assert len(lines) - len(linked) == len(typed)
    assert {ln["desc"] for ln in lines if not ln.get("link")} == {
        it["desc"] for it in typed}
    assert not any(ln["desc"].startswith("Windows") for ln in lines)
