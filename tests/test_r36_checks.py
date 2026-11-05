"""r36 B6: estimate error checks - zero quantities, lines without cost,
unit mismatches, duplicates, missing crews, takeoff groups nobody priced
and unit costs far from your own history. Made-up data only."""
import os
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import assemblies, estimate_lines as EL, heavy, settings   # noqa: E402
from app.estimating import checks                                   # noqa: E402
from estimate_helpers import area, blank_doc                        # noqa: E402


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


def _rules(found, rule):
    return [f for f in found if f["rule"] == rule]


LIB = {"equipment": {}, "labor": {"LAB": {"code": "LAB", "base": 30}},
       "crews": {"PIPE": {"labor": [["LAB", 2]], "equipment": []}},
       "settings": {}}


def test_clean_estimate_has_no_findings():
    d = blank_doc()
    EL.add(d, [EL.new_line("Test footing concrete", 10, "cy", mat=150,
                           code="03 30 00")])
    found = checks.run(d)
    assert found == []
    assert checks.summary(found) == {"errors": 0, "warnings": 0}


def test_zero_quantity_and_no_cost_lines_are_flagged():
    d = blank_doc()
    EL.add(d, [EL.new_line("Test zero qty", 0, "ea", mat=5),
               EL.new_line("Test no price", 3, "ea")])
    found = checks.run(d)
    z = _rules(found, "zero_qty")
    n = _rules(found, "no_cost")
    assert [f["item"] for f in z] == ["Test zero qty"]
    assert [f["item"] for f in n] == ["Test no price"]
    assert all(f["severity"] in ("error", "warning") for f in found)
    assert checks.summary(found)["errors"] + \
        checks.summary(found)["warnings"] == len(found)


def test_unit_mismatch_on_a_linked_line():
    d = blank_doc()
    area(d, "Test slab", 10, 10)
    EL.add(d, [EL.new_line("Test slab rebar", 0, "lb", mat=1,
                           link={"name": "Test slab", "type": "area",
                                 "unit": "sq ft"})])
    found = _rules(checks.run(d), "unit_mismatch")
    assert len(found) == 1 and "Test slab" in found[0]["message"]


def test_duplicate_lines():
    d = blank_doc()
    EL.add(d, [EL.new_line("Test paint walls", 100, "sf", mat=1,
                           code="09 91 23"),
               EL.new_line("test  PAINT walls", 50, "SF", mat=1,
                           code="09 91 23")])
    dup = _rules(checks.run(d), "duplicate")
    assert len(dup) == 1 and "2" in dup[0]["message"]


def test_takeoff_group_not_priced_anywhere():
    d = blank_doc()
    area(d, "Test unpriced floor", 10, 20)
    area(d, "Test priced floor", 10, 10, x0=400)
    EL.add(d, [EL.new_line("Test floor tile", 0, "sf", mat=4,
                           link={"name": "Test priced floor", "type": "area",
                                 "unit": "sq ft"})])
    un = _rules(checks.run(d), "unpriced_takeoff")
    assert [f["item"] for f in un] == ["Test unpriced floor"]


def test_civil_activity_checks_missing_crew_zero_qty_and_unit():
    job = heavy.blank()
    job["pay_items"] = [{"no": "1", "desc": "Test sewer", "unit": "LF",
                         "owner_qty": "100", "weight": "1"}]
    heavy.add_activity(job, "Test lay pipe", qty=100, unit="LF",
                       crew="PIPE", rate=20, pay_item="1")
    heavy.add_activity(job, "Test no crew", qty=50, unit="LF", pay_item="1")
    heavy.add_activity(job, "Test unknown crew", qty=5, unit="LF",
                       crew="NOPE", rate=1, pay_item="1")
    heavy.add_activity(job, "Test zero", qty=0, unit="LF", crew="PIPE",
                       rate=10, pay_item="1")
    heavy.add_activity(job, "Test wrong unit", qty=10, unit="CY",
                       crew="PIPE", rate=10, pay_item="1")
    found = checks.run(None, job=job, lib=LIB)
    crew = {f["item"] for f in _rules(found, "missing_crew")}
    assert crew == {"Test no crew", "Test unknown crew"}
    assert {f["item"] for f in _rules(found, "zero_qty")} == {"Test zero"}
    assert {f["item"] for f in _rules(found, "unit_mismatch")} == \
        {"Test wrong unit"}
    assert not [f for f in found if f["item"] == "Test lay pipe"]


def test_outlier_against_your_history():
    d = blank_doc()
    EL.add(d, [EL.new_line("Test drywall", 100, "sf", mat="9.00",
                           code="09 29 00"),
               EL.new_line("Test tile", 100, "sf", mat="10.50",
                           code="09 30 00")])
    hist = {("09 29 00", "sf"): [Decimal("2.00"), Decimal("2.20"),
                                 Decimal("1.90")],
            ("09 30 00", "sf"): [Decimal("10"), Decimal("11")]}
    out = _rules(checks.run(d, history=hist, outlier_pct=50), "outlier")
    assert [f["item"] for f in out] == ["Test drywall"]
    assert "2.00" in out[0]["message"]           # the history median
    # no history: no outlier finding at all
    assert not _rules(checks.run(d), "outlier")


def test_every_rule_has_plain_words_and_csv_export(tmp_path):
    assert set(checks.RULES) >= {"zero_qty", "no_cost", "unit_mismatch",
                                 "duplicate", "missing_crew",
                                 "unpriced_takeoff", "outlier"}
    d = blank_doc()
    EL.add(d, [EL.new_line("=cmd|' /C calc'!A0", 0, "ea", mat=1)])
    found = checks.run(d)
    p = checks.export_csv(found, str(tmp_path / "check.csv"))
    text = open(p, encoding="utf-8").read()
    assert "Severity" in text and "zero_qty" in text
    assert "'=cmd" in text                       # never a live formula


def test_no_document_and_no_job_is_empty():
    assert checks.run(None) == []
