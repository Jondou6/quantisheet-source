"""r36 v2 step 4: a takeoff group priced with no cost type is no longer
counted as material. It stays in the estimate total, but it isn't on the
material order list or in any cost-type part, and the error check names
it so a cost type can be picked. Made-up data only."""
import os
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import assemblies, estimate, settings                # noqa: E402
from app.estimating import checks, items, materials           # noqa: E402
from estimate_helpers import area, blank_doc                  # noqa: E402

D = Decimal


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


def _doc():
    d = blank_doc()
    area(d, "Test tile", 10, 10)
    area(d, "Test carpet", 10, 10, x0=300)
    estimate.set_price(d, "Test tile", "area", "sq ft", unit_cost=3)
    estimate.set_price(d, "Test carpet", "area", "sq ft", unit_cost=2,
                       cost_type="Material")
    return d


def test_blank_cost_type_is_not_material_but_stays_in_total():
    d = _doc()
    est = items.collect(d)
    tile = next(i for i in est["items"] if i["desc"] == "Test tile")
    assert tile["total"] == D("300.00") and tile["no_cost_type"] is True
    assert tile["materials"] == []
    assert all(v == 0 for v in tile["parts"].values())
    assert est["total"] == D("500.00")
    rows = materials.collect(d)
    assert [r["desc"] for r in rows] == ["Test carpet"]
    assert rows[0]["sources"] == ["takeoff group"]
    assert [i["desc"] for i in materials.no_cost_type(d)] == ["Test tile"]


def test_error_check_names_the_group_without_cost_type():
    found = checks.run(_doc())
    hits = [f for f in found if f["rule"] == "no_cost_type"]
    assert [f["item"] for f in hits] == ["Test tile"]
    assert hits[0]["severity"] == "warning"
    assert "material" in hits[0]["message"].lower()
