"""P1 'estimate -> budget -> commitments': the priced estimate becomes the
job's budget by cost code (totals tie to the cent) and one draft
subcontract per division for the subcontract part (made-up data)."""
from decimal import Decimal

import pytest

from app import settings
from app.pm import award
from app.pm.store import ProjectStore


def _lines():
    D = Decimal
    return [
        {"code": "03 30 00", "division": "03", "title": "Concrete",
         "desc": "Slab", "by_type": {"Material": D("1200.00"),
                                     "Labor": D("800.00")}},
        {"code": "03 30 00", "division": "03", "title": "Concrete",
         "desc": "Footings", "by_type": {"Subcontract": D("5000.55")}},
        {"code": "09 65 00", "division": "09", "title": "Finishes",
         "desc": "Carpet", "by_type": {"Subcontract": D("2500.00")}},
    ]


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Test PM"})
    from app import estimate_export
    monkeypatch.setattr(estimate_export, "collect", lambda doc: _lines())
    return ProjectStore(str(tmp_path / "job"))


def test_budget_ties_and_draft_subcontracts(store):
    p = award.award(None, store)
    assert p["total"] == Decimal("9500.55")
    budget = store.list("budget")
    assert round(sum(b["original"] for b in budget), 2) == 9500.55
    assert {(b["cost_code"], b["category"]) for b in budget} == {
        ("03 30 00", "Material"), ("03 30 00", "Labor"),
        ("03 30 00", "Subcontractor"), ("09 65 00", "Subcontractor")}
    subs = store.list("commitment")
    assert len(subs) == 2 and all(c["status"] == "Draft" and
                                  not c.get("vendor") for c in subs)
    assert round(sum(x["amount"] for c in subs for x in c["lines"]),
                 2) == 7500.55


def test_award_twice_is_refused(store):
    award.award(None, store)
    with pytest.raises(award.AwardError, match="already has budget"):
        award.award(None, store)
