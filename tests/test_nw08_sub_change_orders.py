"""PM review NW-08: an approved change event's cost line typed with the
sub's COMPANY name reaches that sub's commitment (made-up job)."""
import pytest

from app import settings
from app.pm import cost
from app.pm.store import ProjectStore


@pytest.fixture
def s(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Test PM"})
    st = ProjectStore(str(tmp_path / "job"))
    st.save_record("member", {"name": "Sam Grader",
                              "company": "Example Sitework LLC"})
    return st


def test_company_name_reaches_the_commitment(s):
    c = s.save_record("commitment", {
        "title": "Sitework", "vendor": "Sam Grader", "type": "Subcontract",
        "status": "Executed", "lines": [{"cost_code": "31 00 00",
                                         "amount": 702_000}]})
    s.save_record("event", {
        "title": "Extra rock", "status": "Approved",
        "commitments_approved": "Yes",
        "lines": [{"cost_code": "31 00 00", "vendor": "example sitework, "
                   "L.L.C.", "cost": 38_500, "price": 42_350}]})
    n = cost.commitment_numbers(s, c)
    assert n["approved"] == 38_500 and n["revised"] == 740_500


def test_unknown_vendor_is_pointed_out(s):
    s.save_record("commitment", {"title": "Sitework", "vendor": "Sam Grader",
                                 "lines": [{"amount": 1}]})
    e = s.save_record("event", {"title": "X", "lines": [
        {"vendor": "Example Sitework"}, {"vendor": "Nobody Paving"}]})
    assert cost.unmatched_vendors(s, e) == ["Nobody Paving"]
