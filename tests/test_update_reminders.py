"""Nov 2 (Jon): an update waiting is shown in the status bar and on the
Start page until it is installed or skipped; What's New shows once after
an update; and the Store copy asks the Microsoft Store (the Store
installs - QuantiSheet never downloads into a packaged app)."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import settings, storeupdate, updatecheck  # noqa: E402


@pytest.fixture(autouse=True)
def _cfg(monkeypatch):
    store = {}
    monkeypatch.setattr(settings, "get", lambda k, d=None: store.get(k, d))
    monkeypatch.setattr(settings, "set",
                        lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(settings, "recent", lambda n=12: [])
    monkeypatch.setattr(updatecheck, "current_version", lambda: "1.0.2")
    yield store


# ---- what is waiting -------------------------------------------------------
def test_waiting_until_installed_or_skipped():
    assert updatecheck.waiting() is None
    updatecheck.remember({"version": "1.0.3", "notes": "Faster rooms."})
    assert updatecheck.waiting() == {"version": "1.0.3",
                                     "notes": "Faster rooms."}
    assert updatecheck.waiting(local_version="1.0.3") is None   # installed
    updatecheck.skip("1.0.3")
    assert updatecheck.waiting() is None
    updatecheck.remember({"version": "1.0.4"})
    updatecheck.forget()
    assert updatecheck.waiting() is None


def test_bad_versions_are_never_waiting(_cfg):
    updatecheck.remember({"version": "1.0.x"})
    updatecheck.remember({})
    assert updatecheck.waiting() is None
    _cfg[updatecheck.S_WAITING] = {"version": "<b>9</b>"}
    assert updatecheck.waiting() is None


# ---- What's New ------------------------------------------------------------
def test_whats_new_once_after_an_update(_cfg):
    assert updatecheck.whats_new(local_version="1.0.2") is None  # first run
    assert _cfg[updatecheck.S_SEEN] == "1.0.2"
    updatecheck.remember({"version": "1.0.3", "notes": "Zones."})
    got = updatecheck.whats_new(local_version="1.0.3")
    assert got == {"version": "1.0.3", "notes": "Zones."}
    assert updatecheck.whats_new(local_version="1.0.3") is None   # once
    assert _cfg.get(updatecheck.S_WAITING) is None


def test_shipped_notes_after_a_store_update(_cfg):
    _cfg[updatecheck.S_SEEN] = "1.0.1"
    got = updatecheck.whats_new(local_version="1.0.2.0")   # Store numbering
    assert got and "Count Library" in got["notes"]


def test_first_install_of_this_version_on_a_used_pc(monkeypatch):
    monkeypatch.setattr(settings, "recent", lambda n=12: ["C:/job.pdf"])
    got = updatecheck.whats_new(local_version="1.0.2")       # from 1.0.1
    assert got and got["version"] == "1.0.2"


def test_brand_new_pc_gets_no_whats_new():
    assert updatecheck.whats_new(local_version="1.0.2") is None


def test_bundled_notes():
    assert "A (accept)" in updatecheck.bundled_notes("1.0.2")
    assert updatecheck.bundled_notes("1.0.2.0") == \
        updatecheck.bundled_notes("1.0.2")
    assert updatecheck.bundled_notes("0.0.1") == ""
    assert updatecheck.bundled_notes("x") == ""


# ---- the Store copy asks the Store -----------------------------------------
@pytest.fixture
def store_copy(monkeypatch):
    monkeypatch.setattr(storeupdate, "store_copy", lambda: True)
    monkeypatch.setattr(updatecheck, "allowed_by_it", lambda: True)


def test_parse():
    assert storeupdate.parse("UPDATES 1 1.0.3.0\r\n") == (1, "1.0.3.0")
    assert storeupdate.parse("UPDATES 0 ") == (0, "")
    assert storeupdate.parse("Exception: something") is None


def test_store_check_available(store_copy, _cfg):
    st, info = storeupdate.check(run=lambda s: "UPDATES 1 1.0.3.0")
    assert st == "available" and info["version"] == "1.0.3.0"
    assert _cfg[updatecheck.S_LAST]                 # once a day, like team
    assert storeupdate.check(run=lambda s: "x")[0] == "not_due"


@pytest.mark.parametrize("out,want", [("UPDATES 0 ", "current"),
                                      ("UPDATES 1 1.0.2.0", "current"),
                                      ("garbage", "error")])
def test_store_check_other_answers(store_copy, out, want):
    assert storeupdate.check(manual=True, run=lambda s: out)[0] == want


def test_store_check_never_runs_outside_the_store_copy(monkeypatch):
    monkeypatch.setattr(storeupdate, "store_copy", lambda: False)
    ran = []
    st, _ = storeupdate.check(manual=True, run=lambda s: ran.append(1))
    assert st == "ineligible" and ran == []


def test_store_check_honours_setting_and_it(store_copy, monkeypatch, _cfg):
    _cfg[updatecheck.S_ENABLED] = False
    assert storeupdate.check(run=lambda s: "UPDATES 1 9")[0] == "ineligible"
    assert storeupdate.check(manual=True, run=lambda s: "UPDATES 0 ")[0] \
        == "current"                                # asked by hand
    monkeypatch.setattr(updatecheck, "allowed_by_it", lambda: False)
    assert storeupdate.check(manual=True, run=lambda s: "")[0] == \
        "ineligible"


def test_store_script_only_asks():
    s = storeupdate.PS_SCRIPT
    assert "GetAppAndOptionalStorePackageUpdatesAsync" in s
    assert "RequestDownload" not in s and "Invoke-WebRequest" not in s


def test_open_store(monkeypatch):
    opened = []
    monkeypatch.setattr(storeupdate, "family_name", lambda: "Jon.QS_abc")
    assert storeupdate.open_store(opener=opened.append) == \
        "ms-windows-store://pdp/?PFN=Jon.QS_abc"
    monkeypatch.setattr(storeupdate, "family_name", lambda: "")
    assert storeupdate.open_store(opener=opened.append) == \
        storeupdate.STORE_FALLBACK


# ---- the window ------------------------------------------------------------
class _Start:
    def __init__(self):
        self.calls = []

    def set_update(self, text, on_click=None):
        self.calls.append((text, on_click))


def _win(qtbot):
    from PySide6.QtWidgets import QMainWindow
    w = QMainWindow()
    qtbot.addWidget(w)
    w.start_page = _Start()
    return w


def test_reminders_team_copy(qtbot, monkeypatch):
    from app import updatecheck_ui as ui
    w = _win(qtbot)
    assert ui.refresh_reminders(w) is None
    assert not w._update_chip.isVisibleTo(w) and w.start_page.calls[-1][0] \
        is None
    updatecheck.remember({"version": "1.0.3", "notes": "n"})
    assert ui.refresh_reminders(w) == "1.0.3"
    assert w._update_chip.text() == "Update available: 1.0.3"
    assert w._update_chip.isVisibleTo(w)
    assert "1.0.3 is available" in w.start_page.calls[-1][0]
    ran = []
    monkeypatch.setattr(ui, "run_check", lambda win, manual=False:
                        ran.append(manual))
    w._update_chip.click()
    w.start_page.calls[-1][1]()
    assert ran == [True, True]                      # both check again


def test_reminders_store_copy(qtbot, monkeypatch):
    from app import updatecheck_ui as ui
    w = _win(qtbot)
    w._update_mode = "store"
    opened = []
    monkeypatch.setattr(storeupdate, "open_store", lambda: opened.append(1))
    ui._show_store(w, "available", {"version": "1.0.3.0", "notes": ""},
                   False)
    assert w._update_chip.text() == "Update available"
    assert "Microsoft Store" in w.start_page.calls[-1][0]
    w._update_chip.click()
    assert opened == [1]                            # the Store installs
    ui._show_store(w, "current", None, False)
    assert not w._update_chip.isVisibleTo(w)


def test_install_wires_the_store_copy(qtbot, monkeypatch):
    from PySide6.QtWidgets import QMenu
    from app import updatecheck_ui as ui
    monkeypatch.setenv("QUANTISHEET_SMOKE", "1")
    monkeypatch.setattr(updatecheck, "team_build", lambda: False)
    monkeypatch.setattr(storeupdate, "store_copy", lambda: True)
    w = _win(qtbot)
    m = QMenu(w)
    m.addAction("About QuantiSheet")
    assert ui.install(w, m) == "store"
    texts = [a.text() for a in m.actions() if not a.isSeparator()]
    assert texts[:2] == ["Check for Updates Now…",
                         "Check for Updates Automatically"]


def test_public_copy_gets_nothing(qtbot, monkeypatch):
    from app import updatecheck_ui as ui
    monkeypatch.setattr(updatecheck, "team_build", lambda: False)
    monkeypatch.setattr(storeupdate, "store_copy", lambda: False)
    assert ui.install(_win(qtbot)) is False


def test_whats_new_dialog_text(qtbot, _cfg):
    from app import updatecheck_ui as ui
    w = _win(qtbot)
    _cfg[updatecheck.S_SEEN] = "1.0.1"
    _cfg[updatecheck.S_WAITING] = {"version": "1.0.2", "notes": "<b>x</b>"}
    text = ui.show_whats_new(w, show=False)
    assert text.startswith("QuantiSheet is now version 1.0.2")
    assert "<b>x</b>" in text                 # shown as plain text, not HTML
    assert ui.show_whats_new(w, show=False) is None


def test_start_page_line(qtbot):
    from app.startpage import StartPage
    sp = StartPage([])
    qtbot.addWidget(sp)
    hit = []
    sp.set_update("QuantiSheet 1.0.3 is available", lambda: hit.append(1))
    assert sp.update_line.isVisibleTo(sp)
    sp.update_line.click()
    assert hit == [1]
    sp.set_update(None)
    assert not sp.update_line.isVisibleTo(sp)
