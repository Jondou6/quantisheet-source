"""Automatic error reports (Jon, Nov 25): team copy only, off until the
tester turns it on in the Help menu, and nothing of the user's leaves -
no paths, file names, prices, emails or log. Made-up text, fake receiver."""
import json
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import errorreports as er, policy                  # noqa: E402

REPORT = '''QuantiSheet crash report
What: error: ValueError
When: 2026-11-25T10:00:00
Version: 9.9.9
Windows: Windows 11 Pro build 26100
Thread: MainThread

Traceback (most recent call last):
  File "<HOME>\\AppData\\Local\\Programs\\QuantiSheet\\_internal\\app\\takeoff.py", line 10, in run
    go()
  File "C:\\Python312\\Lib\\json\\decoder.py", line 5, in decode
    raise ValueError
ValueError: can't read 'C:\\Jobs\\Made-up Clinic\\A-101 Plan.pdf' for someone@example.com at $12,500.00 (see Bid Tab.xlsx)

--- last lines of the log ---
2026-11-25 opened C:\\Jobs\\Made-up Clinic\\A-101 Plan.pdf
'''.replace(
    # put together here so the source itself holds no user-folder path
    "<HOME>", "C:" + "\\Us" + "ers\\made-up")


@pytest.fixture
def own(tmp_path, monkeypatch):
    from app import settings
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    monkeypatch.setattr(policy, "_from_registry", lambda: {})
    monkeypatch.delenv("QUANTISHEET_POLICY_FILE", raising=False)
    policy.reload()
    p = tmp_path / "crash-1.txt"
    p.write_text(REPORT, encoding="utf-8")
    yield str(p)
    policy.reload()


def test_nothing_of_the_users_is_in_what_is_sent():
    body = er.body_of(REPORT)
    for bad in ("Made-up Clinic", "A-101", "Jobs", "made-up", "example.com",
                "12,500", "Bid Tab", "last lines of the log", "opened",
                "C:\\", "Users"):
        assert bad not in body, bad
    # what helps fix it stays: the error, the version, the program's file
    assert "ValueError" in body and "Version: 9.9.9" in body
    assert 'File "app/takeoff.py", line 10, in run' in body
    assert 'File "decoder.py", line 5' in body
    assert "ValueError: [message removed: it named a file]" in body
    assert "Bid" not in body and "Tab" not in body
    assert er.scrub("KeyError: 'ppu'") == "KeyError: 'ppu'"
    assert er.scrub("total was $1,250.50") == "total was $[amount]"


def test_off_by_default_and_team_copy_only(own, monkeypatch):
    from app import updatecheck
    sent = []
    monkeypatch.setattr(er, "_post", lambda payload, opener=None,
                        timeout=20: sent.append(payload) or 204)
    monkeypatch.setattr(updatecheck, "team_build", lambda: True)
    assert er.available() and not er.is_on()
    assert er.maybe_send(own, wait=True) is None and sent == []   # off
    er.set_on(True)
    assert er.maybe_send(own, wait=True) == 204
    assert sent[0]["app"] == "quantisheet" and "ValueError" in \
        sent[0]["report"]
    assert set(sent[0]) == {"app", "version", "report"}   # no ids, no name
    monkeypatch.setattr(updatecheck, "team_build", lambda: False)
    assert er.maybe_send(own, wait=True) is None          # not the team copy
    assert len(sent) == 1


def test_at_most_five_a_day_and_it_can_turn_it_off(own, monkeypatch):
    from app import updatecheck
    sent = []
    monkeypatch.setattr(er, "_post", lambda payload, opener=None,
                        timeout=20: sent.append(1) or 204)
    monkeypatch.setattr(updatecheck, "team_build", lambda: True)
    er.set_on(True)
    for _ in range(8):
        er.maybe_send(own, wait=True)
    assert len(sent) == er.PER_DAY
    monkeypatch.setattr(policy, "_from_registry",
                        lambda: {"DisableErrorReports": 1})
    policy.reload()
    assert not er.available()
    monkeypatch.setattr(policy, "_from_registry", lambda: {"OfflineMode": 1})
    policy.reload()
    assert not er.available()


def test_a_failed_send_is_silent_and_host_matches_policy(own, monkeypatch):
    from app import updatecheck
    monkeypatch.setattr(updatecheck, "team_build", lambda: True)
    er.set_on(True)

    def boom(req, timeout=0):
        raise OSError("no network")
    assert er.maybe_send(own, opener=boom, wait=True) is None
    assert policy.NETWORK["errorreports"] == ("DisableErrorReports",
                                              [er.REPORT_HOST])
    assert er.REPORT_URL.startswith("https://")


def test_real_post_shape(own, monkeypatch):
    from app import updatecheck
    monkeypatch.setattr(updatecheck, "team_build", lambda: True)
    er.set_on(True)
    seen = {}

    class R:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def opener(req, timeout=0):
        seen["url"] = req.full_url
        seen["h"] = dict(req.header_items())
        seen["body"] = json.loads(req.data)
        return R()
    assert er.maybe_send(own, opener=opener, wait=True) == 204
    assert seen["url"] == er.REPORT_URL
    assert seen["h"]["X-quantisheet-report"] == "1"
    assert seen["h"]["User-agent"].startswith("QuantiSheet/")
    assert "Made-up" not in json.dumps(seen["body"])


def test_help_menu_switch_only_in_the_team_copy(qapp, own, monkeypatch):
    from PySide6.QtWidgets import QMainWindow, QMenu, QMessageBox
    from app import updatecheck
    w = QMainWindow()
    m = QMenu("Help", w)
    assert er.install(w, m) is None and not m.actions()   # a source run
    monkeypatch.setattr(updatecheck, "team_build", lambda: True)
    a = er.install(w, m)
    assert a.text() == er.MENU_TEXT and a.isCheckable() and not a.isChecked()
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.Cancel)
    a.setChecked(True)                        # asked, said no: stays off
    assert not a.isChecked() and not er.is_on()
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.Ok)
    a.setChecked(True)
    assert er.is_on()
    a.setChecked(False)                       # off needs no question
    assert not er.is_on()


from test_gui import qapp                                   # noqa: E402,F401
