"""r36 v2 step 1a: Estimate Error Check warns when a takeoff group has its
own unit cost and is also priced by a linked line, an assembly or a
civil activity (counted twice). Made-up data only."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import assemblies, estimate, heavy, settings         # noqa: E402
from app.estimating import checks, costlink                   # noqa: E402
from estimate_helpers import area, blank_doc                  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


def test_group_with_unit_cost_and_linked_line_is_double_priced():
    d = blank_doc()
    area(d, "Test slab", 10, 10)
    area(d, "Test walk", 5, 5, x0=400)
    estimate.set_price(d, "Test slab", "area", "sq ft", unit_cost=5)
    estimate.set_price(d, "Test walk", "area", "sq ft", unit_cost=5)
    costlink.link_item(d, {"desc": "Test slab concrete", "unit": "sf",
                           "mat": "4"}, {"name": "Test slab", "type": "area",
                                         "unit": "sq ft"})
    job = heavy.blank()
    heavy.add_activity(job, "Test walk grade", qty=25, unit="sq ft",
                       group="Test walk", sub=100)
    found = [f for f in checks.run(d, job=job) if f["rule"] ==
             "double_priced"]
    assert sorted(f["item"] for f in found) == ["Test slab", "Test walk"]
    assert "linked estimate line" in found[0]["message"] + found[1]["message"]
    assert "civil activity" in found[0]["message"] + found[1]["message"]
