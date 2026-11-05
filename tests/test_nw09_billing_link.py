"""PM review NW-09: with the drawing in a Project Center job, Contract &
Billing says the job's billing is in Project Center and links there."""
import pytest

from app import settings
from app.billing_ui import project_note
from app.pm.store import ProjectStore


def test_note_names_the_job_and_its_pay_apps(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "T"})
    st = ProjectStore(str(tmp_path / "Example Job"))
    for i in range(10):
        st.save_record("contract", {"item": str(i + 1), "scheduled": 1})
    for p in ("2026-11-30", "2026-12-31", "2027-01-31", "2027-02-28"):
        st.save_record("payapp", {"period_to": p})
    t = project_note(st)
    assert "10 contract line(s)" in t and "4 pay application(s)" in t
    assert "separate ledger" in t
    assert project_note(None) == ""
