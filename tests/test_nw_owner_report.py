"""PM review NW-04, NW-05, NW-06: the weekly owner report fills weather
days and progress from the week's Daily Logs, and fits a long company
name (made-up job, no network)."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import settings                                        # noqa: E402
from app.pm import owner_report as OR                           # noqa: E402
from app.pm.store import ProjectStore                           # noqa: E402


@pytest.fixture
def s(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Test PM"})
    st = ProjectStore(str(tmp_path / "job"))
    st.set_setting("project_start", "2026-09-07")
    man = [{"company": "Example Sitework", "trade": "Sitework",
            "workers": 6, "hours": 8}]
    st.save_record("daily", {"date": "2026-09-21", "work": "Clear and grub",
                             "manpower": man, "status": "Submitted",
                             "weather": {"conditions": "Clear",
                                         "precip": "0"}})
    st.save_record("daily", {"date": "2026-09-22", "work": "Strip topsoil",
                             "manpower": man, "status": "Submitted",
                             "weather": {"precip": "0.0 in"}})
    st.save_record("daily", {"date": "2026-09-23", "work": "Toolbox talk; "
                             "rain stopped work", "manpower": man,
                             "status": "Submitted",
                             "weather": {"conditions": "Rain",
                                         "precip": "0.6 in"},
                             "delays": [{"cause": "Weather", "hours": 4,
                                         "description": "Rain"}]})
    return st


def test_weather_day_counted_from_the_daily_log(s):
    rep = OR.new_report(s, "2026-09-25", from_previous=False, online=False,
                        save_it=False)
    assert rep["weather"]["impacted"] == 1


def test_progress_and_site_work_from_dailies(s):
    rep = OR.new_report(s, "2026-09-25", from_previous=False, online=False,
                        save_it=False)
    text = " | ".join(b["text"] for b in rep["progress"])
    assert "Clear and grub" in text and "Strip topsoil" in text
    assert "Example Sitework" in text
    assert "Site Work" in rep["trades"]


def test_long_company_name_fits_without_cutting():
    name = "Ridgeview Constructors (fictional)"
    t, size = OR.fit_size(name, 14, OR._tlen(name, 14, True) * 0.85, True)
    assert t == name and size < 14
