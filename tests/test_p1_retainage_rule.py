"""P1 'retainage rules per contract': 10% until the job is 50% complete,
then 5%, applied by itself to the next draft pay app with a note; a %
typed by hand is kept (made-up job)."""
import pytest

from app import settings
from app.pm import contract_terms as ct, cost
from app.pm.store import ProjectStore


@pytest.fixture
def s(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Test PM"})
    st = ProjectStore(str(tmp_path / "job"))
    st.save_record("contract", {"item": "1", "description": "Example work",
                                "scheduled": 1_000_000})
    ct.set_prime(st, {"retainage_pct": "10", "retainage_reduce_to": "5",
                      "retainage_reduce_at": "50"})
    return st


def _app(st, period, work, certify=True):
    a = st.save_record("payapp", {"period_to": period})
    a["lines"] = cost.fill_payapp(st, a)
    a["lines"][0]["this_period"] = work
    a = st.save_record("payapp", a)
    if certify:
        a["status"] = "Certified"
        a = st.save_record("payapp", a)
    return a


def test_ten_percent_until_half_then_five(s):
    a1 = _app(s, "2026-11-30", 300_000)
    assert a1["retainage_work"] == 10
    a2 = _app(s, "2026-12-31", 250_000)             # 30% done before it
    assert a2["retainage_work"] == 10
    a3 = s.save_record("payapp", {"period_to": "2027-01-31"})
    a3["lines"] = cost.fill_payapp(s, a3)           # 55% done before it
    assert a3["retainage_work"] == 5
    assert "55% complete" in a3["retainage_note"]
    assert ct.percent_complete(s, "2027-01-31") == 55.0


def test_a_percent_typed_by_hand_is_kept(s):
    _app(s, "2026-11-30", 600_000)
    a = s.save_record("payapp", {"period_to": "2026-12-31"})
    a["lines"] = cost.fill_payapp(s, a)
    assert a["retainage_work"] == 5
    a = s.save_record("payapp", a)
    a["retainage_work"] = 7.5                        # the PM's own
    a["lines"] = cost.fill_payapp(s, a)
    assert a["retainage_work"] == 7.5 and "by hand" in a["retainage_note"]


def test_no_rule_no_change(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Test PM"})
    st = ProjectStore(str(tmp_path / "job2"))
    st.save_record("contract", {"item": "1", "scheduled": 100})
    a = st.save_record("payapp", {"period_to": "2026-11-30",
                                  "retainage_work": 10})
    cost.fill_payapp(st, a)
    assert a["retainage_work"] == 10 and not a.get("retainage_note")
