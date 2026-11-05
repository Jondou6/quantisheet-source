"""PM review NW-13 (term fields) and NW-14 (owner vs sub conflicts),
made-up job."""
import pytest

from app import settings
from app.pm import contract_terms as ct, schema
from app.pm.store import ProjectStore


@pytest.fixture
def s(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Test PM"})
    st = ProjectStore(str(tmp_path / "job"))
    ct.set_prime(st, {"claim_notice_days": "21", "delay_notice_days": "7",
                      "ld_per_day": "1500", "pay_when_paid": "No",
                      "pay_days": "30", "retainage_pct": "10",
                      "warranty_months": "24", "umbrella_limit": "5000000",
                      "flow_down": "Yes"})
    return st


def test_term_fields_saved_and_reopened(s):
    keys = {f["key"] for f in schema.fields_of("commitment")}
    for k in ("claim_notice_days", "delay_notice_days", "ld_per_day",
              "pay_when_paid", "pay_days", "warranty_months",
              "umbrella_limit", "flow_down"):
        assert k in keys
    c = s.save_record("commitment", {"title": "Steel", "vendor": "Ex Steel",
                                     "claim_notice_days": 10,
                                     "flow_down": "Yes"})
    s.flush()
    again = ProjectStore(s.folder)
    assert again.get("commitment", c["_id"])["claim_notice_days"] == 10
    assert ct.prime(again)["ld_per_day"] == "1500"


def test_every_kind_of_conflict_is_listed(s):
    s.save_record("commitment", {
        "title": "Sitework", "vendor": "Example Sitework", "type":
        "Subcontract", "retainage": 5, "claim_notice_days": 21,
        "delay_notice_days": 10, "pay_when_paid": "No", "pay_days": 15,
        "warranty_months": 12, "umbrella_limit": 1_000_000,
        "flow_down": "No", "insurance_expires": "2027-03-31"})
    s.save_record("commitment", {
        "title": "Paint", "vendor": "Example Paint", "type": "Subcontract",
        "retainage": 10, "claim_notice_days": 7, "delay_notice_days": 3,
        "ld_per_day": 500, "pay_when_paid": "Yes", "pay_days": 45,
        "warranty_months": 24, "umbrella_limit": 5_000_000,
        "flow_down": "Yes", "insurance_expires": "2027-12-31"})
    rows = ct.conflicts(s, today="2027-04-15")
    site = {r["term"]: r["severity"] for r in rows
            if r["sub"] == "Example Sitework"}
    assert site == {"claim_notice_days": "High", "delay_notice_days": "High",
                    "ld_per_day": "High", "retainage_pct": "Medium",
                    "pay_days": "Medium", "warranty_months": "High",
                    "umbrella_limit": "Medium", "flow_down": "High",
                    "insurance_expires": "High"}
    assert not [r for r in rows if r["sub"] == "Example Paint"]
    assert [r["severity"] for r in rows] == sorted(
        [r["severity"] for r in rows], key=["High", "Medium",
                                            "Low"].index)


def test_unentered_owner_terms_are_not_checked(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "T"})
    st = ProjectStore(str(tmp_path / "j2"))
    st.save_record("commitment", {"title": "X", "vendor": "Y"})
    assert ct.conflicts(st, today="2027-01-01") == []
