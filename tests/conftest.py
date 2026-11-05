"""Shared test setup: quiet PyMuPDF's old 'fitz' name (see app/__init__)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

os.environ.setdefault("QUANTISHEET_DRAW_PROCESS", "0")   # see test_draw_process

# The whole test run gets its own throwaway home folder, set BEFORE the
# program is imported (settings.DIR, the price database and every path
# built from the home folder point inside it). Tests patch settings.DIR
# too, but those patches are undone before the end of the run, and the
# windows closed at the very end (pytest_sessionfinish) then saved their
# size into the REAL ~/.quantisheet/settings.json and opened the real
# prices.db (GUI user test r42, Oct 29: both changed as a run finished).
# QS_TESTS_REAL_HOME=1 turns this off.
if os.environ.get("QS_TESTS_REAL_HOME") != "1":
    import tempfile
    _TEST_HOME = tempfile.mkdtemp(prefix="qs_test_home_")
    os.environ["USERPROFILE"] = _TEST_HOME
    os.environ["HOME"] = _TEST_HOME
    # and the per-user app-data folders (Code Library, print-helper log,
    # ClaimIT, license clock) - Chief review Q5
    for _k in ("APPDATA", "LOCALAPPDATA"):
        os.environ[_k] = os.path.join(_TEST_HOME, _k)
        os.makedirs(os.environ[_k], exist_ok=True)

import app  # noqa: E402,F401  (sets sys.modules["fitz"] = pymupdf)
from app import oldnames as _oldnames  # noqa: E402
_oldnames.install()      # as the program does: old-named files convert


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_real_registry(monkeypatch):
    """Tests never touch the real Windows registry: the sign-in and license
    copies kept there live in memory for each test."""
    from app import betalicense
    try:            # the sign-in gate isn't in the public source (Nov 4)
        from app import onboard
    except ImportError:
        onboard = None
    mem = {}
    if onboard is not None:
        monkeypatch.setattr(onboard, "_reg_read",
                            lambda name="t": mem.get(("o", name), ""))
        monkeypatch.setattr(onboard, "_reg_write",
                            lambda text, name="t": mem.__setitem__(
                                ("o", name), text))

    def reg(name, value=None):
        if value is None:
            return mem.get(("b", name), "")
        mem[("b", name)] = value
        return value
    monkeypatch.setattr(betalicense, "_reg", reg)
    # nor the real Group Policy: no IT settings unless a test sets some
    from app import policy
    monkeypatch.setattr(policy, "_from_registry", lambda: {})
    # nor the machine's ProgramData (policy.json, relay, print spool): a
    # throwaway folder per test (Q5); policy.json above points nowhere, so
    # no PriceDatabasePath / shared price DB from IT either
    _pd = os.path.join(os.environ.get("HOME") or "", "ProgramData")
    os.makedirs(_pd, exist_ok=True)
    if not hasattr(policy, "_real_program_data"):
        policy._real_program_data = policy._program_data
    monkeypatch.setattr(policy, "_program_data", lambda: _pd)
    monkeypatch.setenv("QUANTISHEET_POLICY_FILE",
                       os.path.join(os.path.dirname(__file__),
                                    "_no_such_policy.json"))
    policy.reload()
    yield mem
    policy.reload()


def pytest_sessionfinish(session, exitstatus):
    """Close every window the tests left open before Python shuts down.
    Otherwise PySide deletes them during interpreter exit, in no fixed
    order, and Qt can crash after the summary (Windows: 0xC0000409 in
    ucrtbase / "pure virtual function call"; Linux: SIGSEGV in
    QObject::~QObject or SIGABRT) - the run then has no clean exit code."""
    try:
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return
    app = QApplication.instance()
    if app is None:
        return
    for w in QApplication.topLevelWidgets():
        # no "Save changes?" box while shutting down: a test left a tab
        # edited, and asking then crashed (0xC0000374) in _confirm_discard
        tabs = getattr(w, "tabs", None)
        try:
            for i in range(tabs.count() if tabs is not None else 0):
                view = getattr(tabs.widget(i), "view", None)
                if view is not None:
                    view.dirty = False
        except (RuntimeError, AttributeError, TypeError):
            pass
    for w in QApplication.topLevelWidgets():
        try:
            w.close()
            w.deleteLater()
        except RuntimeError:                 # already deleted on the C++ side
            pass
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    app.processEvents()
