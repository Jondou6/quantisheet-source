"""Nov 12: the Microsoft Store copy's About line. It asks the Store on
this PC whether an update is waiting; it must not say "Up to date" as
if it had checked for the newest QuantiSheet anywhere."""
import time

from app import legal, settings, updatecheck


def _set(monkeypatch, store, team, waiting, last=None):
    monkeypatch.setattr(legal, "_store", lambda: store)
    monkeypatch.setattr(updatecheck, "team_build", lambda: team)
    monkeypatch.setattr(updatecheck, "waiting", lambda: waiting)
    monkeypatch.setattr(updatecheck, "enabled", lambda: True)
    stamp = time.time() if last is None else last
    monkeypatch.setattr(settings, "get",
                        lambda k, d=None: stamp if k == updatecheck.S_LAST
                        else d)


def test_store_copy_never_says_up_to_date(monkeypatch):
    _set(monkeypatch, store=True, team=False, waiting=None)
    s = legal.update_status()
    assert "Up to date" not in s
    assert "No update is waiting in the Microsoft Store" in s
    assert "updates come through the Store" in s and "last checked" in s
    _set(monkeypatch, store=True, team=False, waiting={"version": "9.9.9"})
    s = legal.update_status()
    assert "an update is ready in the Microsoft Store" in s
    assert "Up to date" not in s


def test_team_copy_keeps_its_wording(monkeypatch):
    _set(monkeypatch, store=False, team=True, waiting=None)
    assert " · Up to date · last checked " in legal.update_status()
    _set(monkeypatch, store=False, team=True, waiting={"version": "9.9.9"})
    assert "version 9.9.9 is ready to install" in legal.update_status()


def test_not_checked_yet_and_copies_that_do_not_check(monkeypatch):
    _set(monkeypatch, store=True, team=False, waiting=None, last=0)
    assert "not checked yet" in legal.update_status()
    _set(monkeypatch, store=False, team=False, waiting=None)
    assert legal.update_status() == ""
