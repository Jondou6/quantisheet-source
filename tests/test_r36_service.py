"""r36 D2 + D3: equipment and warranty records per property / job (make,
model, serial, install date, warranty end, service reminders) and a
recurring service schedule with next-due dates. Your own file. Made-up
records only."""
import datetime as dt
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import settings                               # noqa: E402
from app.estimating import _io, service                # noqa: E402

T = dt.date(2026, 10, 27)


@pytest.fixture(autouse=True)
def _cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "_cache", {})


def _store():
    s = service.blank()
    p = service.add_property(s, "Test Smith house", "1 Test St",
                             customer="Test Smith")
    e = service.add_equipment(s, p, "Furnace", make="TestCo",
                              model="TF-80", serial="SN123",
                              installed="2024-01-31", warranty_months=36)
    service.add_service(s, p, "Furnace tune-up", every=12, unit="months",
                        start="2025-10-15", equipment=e)
    service.add_service(s, p, "Filter change", every=90, unit="days",
                        start="2026-08-01", last_done="2026-09-01")
    return s, p, e


def test_warranty_end_and_status():
    s, p, e = _store()
    eq = service.find(s, e)
    assert service.warranty_end(eq) == dt.date(2027, 1, 31)
    assert service.warranty_status(eq, T) == "active"
    assert service.warranty_status(eq, dt.date(2026, 12, 15),
                                   warn_days=60) == "expiring"
    assert service.warranty_status(eq, dt.date(2027, 2, 1)) == "expired"
    eq2 = dict(eq, warranty_months=None, warranty_end="2026-01-01")
    assert service.warranty_end(eq2) == dt.date(2026, 1, 1)


def test_next_due_month_ends_and_days():
    assert service.add_interval(dt.date(2026, 1, 31), 1, "months") == \
        dt.date(2026, 2, 28)
    assert service.add_interval(dt.date(2024, 2, 29), 1, "years") == \
        dt.date(2025, 2, 28)
    s, p, e = _store()
    due = {x["title"]: x for x in service.due_list(s, T, within_days=400)}
    # tune-up: started 2025-10-15, never done -> due then (overdue now)
    assert due["Furnace tune-up"]["next_due"] == dt.date(2025, 10, 15)
    assert due["Furnace tune-up"]["overdue"]
    # filter: last done 2026-09-01 + 90 days
    assert due["Filter change"]["next_due"] == dt.date(2026, 11, 30)
    assert due["Filter change"]["days_left"] == 34
    service.mark_done(s, due["Furnace tune-up"]["id"], "2026-10-20")
    due = {x["title"]: x for x in service.due_list(s, T, within_days=400)}
    assert due["Furnace tune-up"]["next_due"] == dt.date(2027, 10, 20)


def test_reminders_combine_service_and_warranty():
    s, p, e = _store()
    r = service.reminders(s, dt.date(2027, 1, 5), within_days=30)
    kinds = sorted(x["kind"] for x in r)
    assert kinds == ["service", "service", "warranty"]


def test_save_load_default_file_and_export(tmp_path):
    s, p, e = _store()
    path = service.save(s)
    assert path == os.path.join(settings.DIR, "service_records.json")
    assert service.load() == s
    other = str(tmp_path / "mine.json")
    service.save(s, other)
    assert service.load(other) == s
    with pytest.raises(_io.PathError):
        service.save(s, os.path.join(_io.APP_DIR, "x.json"))
    out = service.export(s, str(tmp_path / "eq.csv"), T)
    text = open(out, encoding="utf-8").read()
    assert "SN123" in text and "2027-01-31" in text


def test_bad_input_refused():
    s, p, e = _store()
    with pytest.raises(service.ServiceError):
        service.add_service(s, p, "x", every=0, unit="days", start="2026-1-1")
    with pytest.raises(service.ServiceError):
        service.add_service(s, p, "x", every=1, unit="fortnights",
                            start="2026-01-01")
    with pytest.raises(service.ServiceError):
        service.add_equipment(s, "nope", "x")
    with pytest.raises(service.ServiceError):
        service.add_equipment(s, p, "x", installed="31/01/2024")
    assert service.load(os.path.join(settings.DIR, "none.json")) == \
        service.blank()
