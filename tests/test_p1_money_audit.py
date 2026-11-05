"""P1 'audit trail on all money records': editing a money record leaves
who / when / before / after; the history is chained so an edited or
removed entry shows (made-up job)."""
import pytest

from app import settings
from app.pm.store import ProjectStore


@pytest.fixture
def s(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Test PM"})
    return ProjectStore(str(tmp_path / "job"))


def test_edit_leaves_before_and_after(s):
    a = s.save_record("payapp", {"period_to": "2026-11-30",
                                 "retainage_work": 10})
    a["retainage_work"] = 5
    s.save_record("payapp", a)
    log = s.audit_log("payapp", a["_id"])
    assert [e["action"] for e in log] == ["create", "change"]
    ch = log[-1]
    assert ch["before"]["retainage_work"] == "10" and \
        ch["after"]["retainage_work"] == "5" and ch["by"]
    assert s.audit_ok()


def test_non_money_records_are_not_logged_and_deletes_are(s):
    s.save_record("rfi", {"subject": "x"})
    assert s.audit_log() == []
    c = s.save_record("cost", {"vendor": "Example Co", "amount": 100})
    s.delete("cost", c["_id"])
    assert [e["action"] for e in s.audit_log("cost")] == ["create",
                                                          "delete"]


def test_tampering_with_the_history_shows(s):
    a = s.save_record("contract", {"item": "1", "scheduled": 100})
    a["scheduled"] = 200
    s.save_record("contract", a)
    s.data["audit"][0]["after"]["scheduled"] = "999"
    assert not s.audit_ok()
