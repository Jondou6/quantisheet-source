"""r36 v2 step 6 (gap-check defect): Suggest Takeoff Groups bound the AI
group 'Exterior Walls' to 'Interior wall length' - the interior pattern
matches a bare 'wall' and came first. An exterior / interior qualifier
now wins over a bare 'wall'; a bare 'wall' goes to a generic wall
placeholder when the template has one, else stays unbound with a note.
Made-up drawings only."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import annotate, assemblies, settings                  # noqa: E402
from app.estimating import starters                              # noqa: E402
from estimate_helpers import blank_doc                           # noqa: E402


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


def _line(d, group, y):
    annotate.apply_op(d, annotate.new_op(
        "add_line", 0, pts=[[100, y], [300, y]],
        measure={"type": "length", "value": 20, "unit": "ft",
                 "group": group}))


def _tpl(name):
    return next(t for t in starters.estimate_templates()
                if name in t["name"].lower())


def _names(b):
    return {ph: sorted(g[0] for g in gs) for ph, gs in b.items()}


def test_exterior_walls_go_to_the_exterior_placeholder():
    d = blank_doc()
    _line(d, "Exterior Walls", 100)
    _line(d, "Interior Walls", 140)
    _line(d, "Wall Type 1A", 180)
    _line(d, "Test interior partition", 220)
    n = _names(starters.suggest_bindings(d, _tpl("commercial")))
    assert n["Exterior wall length"] == ["Exterior Walls"]
    assert n["Interior wall length"] == ["Interior Walls",
                                         "Test interior partition",
                                         "Wall Type 1A"]


def test_bare_wall_with_no_generic_placeholder_stays_unbound_with_a_note():
    d = blank_doc()
    _line(d, "Walls", 100)
    notes = []
    b = starters.suggest_bindings(d, _tpl("commercial"), notes=notes)
    assert not any(g[0] == "Walls" for gs in b.values() for g in gs)
    assert any("Walls" in n and "interior or exterior" in n.lower()
               for n in notes), notes


def test_bare_wall_goes_to_a_generic_wall_placeholder():
    d = blank_doc()
    _line(d, "Walls", 100)
    _line(d, "Exterior Walls", 140)
    tpl = {"kind": "estimate", "name": "made-up", "items": [
        dict(starters._it("Interior", "09 22 16", "ft", "Material",
                          starters._ph("Interior wall length", starters.LEN,
                                       r"interior|wall"))),
        dict(starters._it("Generic", "09 22 16", "ft", "Material",
                          starters._ph("Wall length", starters.LEN,
                                       r"wall"))),
        dict(starters._it("Exterior", "07 46 00", "ft", "Material",
                          starters._ph("Exterior wall length", starters.LEN,
                                       r"exterior")))]}
    n = _names(starters.suggest_bindings(d, tpl))
    assert n["Wall length"] == ["Walls"]
    assert n["Exterior wall length"] == ["Exterior Walls"]
    assert "Interior wall length" not in n


def test_old_callers_still_get_a_plain_dict():
    d = blank_doc()
    _line(d, "Exterior Walls", 100)
    b = starters.suggest_bindings(d, _tpl("commercial"))
    assert isinstance(b, dict)
