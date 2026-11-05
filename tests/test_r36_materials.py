"""r36 A4: material order list grouped by supplier - the material in the
estimate (added lines and assembly parts), merged by item, each under the
supplier you set or found in your own supplier price lists. Made-up data
only."""
import csv
import os
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import assemblies, estimate_lines as EL, settings   # noqa: E402
from app.estimating import materials                          # noqa: E402
from estimate_helpers import blank_doc                        # noqa: E402

D = Decimal


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


PL = {"supplier": "Test Lumber Yard", "items": [
    {"sku": "A-100", "desc": "Test stud", "unit": "ea", "price": "3.25",
     "pack": "1"}]}


def _doc():
    d = blank_doc()
    EL.add(d, [EL.new_line("Test stud", 100, "ea", mat="3.00"),
               EL.new_line("Test stud", 20, "ea", mat="3.00"),
               EL.new_line("Test anchor bolt", 30, "ea", mat="1.10",
                           code="03 15 00"),
               EL.new_line("Test labor only", 10, "hr", lab=60),
               EL.new_line("Test roofing sub", 1, "ls", sub=9000)])
    return d


def test_only_material_and_merged_by_item():
    rows = materials.collect(_doc())
    by = {r["desc"]: r for r in rows}
    assert set(by) == {"Test stud", "Test anchor bolt"}
    assert by["Test stud"]["qty"] == D("120")
    assert by["Test stud"]["cost"] == D("360.00")


def test_grouped_by_supplier_from_your_map_or_price_list():
    d = _doc()
    materials.set_supplier(d, "Test anchor bolt", "Test Fastener Co")
    order = materials.order_list(d, pricelists=[PL])
    assert list(order) == ["Test Fastener Co", "Test Lumber Yard"]
    stud = order["Test Lumber Yard"][0]
    assert stud["sku"] == "A-100" and stud["supplier_price"] == D("3.25")
    assert materials.suppliers(d) == {"test anchor bolt": "Test Fastener Co"}
    # nothing known: "(no supplier yet)"
    order2 = materials.order_list(_doc())
    assert list(order2) == [materials.NO_SUPPLIER]


def test_export_order_list(tmp_path):
    d = _doc()
    materials.set_supplier(d, "Test stud", "Test Lumber Yard")
    p = materials.export(materials.order_list(d),
                         str(tmp_path / "order.csv"))
    rows = list(csv.reader(open(p, encoding="utf-8")))
    assert rows[0][0] == "Supplier"
    assert ["Test Lumber Yard", "", "Test stud"] == rows[1][:3]
    p2 = materials.export(materials.order_list(d),
                          str(tmp_path / "order.xlsx"))
    assert os.path.getsize(p2) > 0


def test_assembly_material_parts_are_included():
    from estimate_helpers import area
    d = blank_doc()
    asm = {"name": "Test patio", "measure": "area", "trade": "Concrete",
           "parts": [{"name": "Test pavers", "unit": "ea",
                      "qty": "Area*4", "cost": 0.5, "labor": 0}]}
    job = assemblies.read_job(d)
    job["assemblies"]["Test patio"] = asm
    assemblies.write_job(d, job)
    area(d, "Test patio", 10, 10)
    rows = {r["desc"]: r for r in materials.collect(d)}
    assert rows["Test pavers"]["qty"] == D("400")
    assert rows["Test pavers"]["cost"] == D("200.00")
