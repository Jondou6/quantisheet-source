"""Review 2 (Nov 4): license end - warn, then read-only, then refuse."""
import datetime as dt

from app import betalicense as B


def _with_end(monkeypatch, end):
    monkeypatch.setattr(B, "_all_keys", lambda: ["k"])
    monkeypatch.setattr(B, "parse", lambda key, pub=None: {
        "n": "Example Tester", "x": end.isoformat()})


def test_phases(monkeypatch):
    today = dt.date(2026, 11, 4)
    for days, want in ((60, "ok"), (10, "warn"), (0, "warn"), (-1, "readonly"),
                       (-14, "readonly"), (-15, "expired")):
        _with_end(monkeypatch, today + dt.timedelta(days=days))
        assert B.phase(now=today)[0] == want, days
    monkeypatch.setattr(B, "_all_keys", lambda: [])
    assert B.phase(now=today)[0] == "none"


def test_read_only_days_open_but_never_save(monkeypatch):
    _with_end(monkeypatch, B.today() - dt.timedelta(days=3))
    monkeypatch.setattr(B, "required", lambda: True)
    monkeypatch.setattr(B, "current", lambda: None)
    monkeypatch.setitem(B._READ_ONLY, "on", False)
    assert B.gate() is True and B.read_only()
    assert "saving is turned off" in B.READ_ONLY_MESSAGE
