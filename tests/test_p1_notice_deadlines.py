"""P1 'notice deadline tracker': a delay event's written-notice deadline
from the owner contract's notice days; overdue flagged, a late notice
noted (made-up job)."""
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
    ct.set_prime(st, {"delay_notice_days": "7"})
    return st


def test_due_date_and_overdue(s):
    r = s.save_record("delay", {"title": "Example rain delay",
                                "cause": "Weather",
                                "event_start": "2027-11-20"})
    assert r["notice_due"] == "2027-11-27" and r["due"] == "2027-11-27"
    assert ct.notice_list(s, "2027-11-25")[0]["status"] == "Due in 2 days"
    assert ct.notice_list(s, "2027-11-28")[0]["status"] == "OVERDUE"
    assert schema.is_overdue("delay", r, "2027-11-28")


def test_notice_given_on_time_or_late(s):
    r = s.save_record("delay", {"title": "Example owner hold",
                                "event_start": "2027-11-20",
                                "notice_date": "2027-11-26"})
    assert "due" not in r and r["notice_late"] is False
    r["notice_date"] = "2027-12-01"
    r = s.save_record("delay", r)
    assert r["notice_late"] is True
    assert ct.notice_list(s, "2027-12-05")[0]["status"].startswith("Late")


def test_no_contract_days_no_deadline(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Test PM"})
    st = ProjectStore(str(tmp_path / "job2"))
    r = st.save_record("delay", {"title": "x", "event_start": "2027-11-20"})
    assert "due" not in r and ct.notice_list(st) == []
