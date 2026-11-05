"""Nov 3: after the window froze, the next start offers Report This (once
per freeze; can be turned off)."""
import os

import pytest


@pytest.fixture
def logs(tmp_path, monkeypatch):
    import app.main as main_mod
    from app import settings
    d = tmp_path / "logs"
    d.mkdir()
    (d / "quantisheet.log").write_text("INFO start\n", encoding="utf-8")
    monkeypatch.setattr(main_mod, "log_folder", lambda: str(d))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    return d


FREEZE = ("Timeout (0:00:10)!\nThread 0x1 (most recent call first):\n"
          "  File \"app/viewer.py\", line 9 in paint\n"
          "--- above: window frozen 37 s, ended 2026-11-03 10:00:00 ---\n")


def test_freeze_offered_once(logs):
    from app import crashreport
    crash = logs / "crash.log"
    crash.write_text("--- start ---\n", encoding="utf-8")
    assert crashreport.check_previous_run(str(crash)) is None   # first run
    with open(crash, "a", encoding="utf-8") as f:
        f.write(FREEZE)
    p = crashreport.check_previous_run(str(crash))
    assert p and crashreport.last_kind[0] == "freeze"
    assert "froze in the previous session" in open(p, encoding="utf-8").read()
    assert crashreport.freeze_seconds(p) == 37
    assert crashreport.check_previous_run(str(crash)) is None   # once


def test_crash_wins_over_freeze_and_off_switch(logs):
    from app import crashreport, settings
    crash = logs / "crash.log"
    crash.write_text("--- start ---\n", encoding="utf-8")
    crashreport.check_previous_run(str(crash))
    with open(crash, "a", encoding="utf-8") as f:
        f.write(FREEZE + "Windows fatal exception: access violation\n")
    assert crashreport.check_previous_run(str(crash))
    assert crashreport.last_kind[0] == "crash"
    settings.set(crashreport.S_ASK_FREEZE, False)
    with open(crash, "a", encoding="utf-8") as f:
        f.write(FREEZE.replace("37", "41"))
    assert crashreport.check_previous_run(str(crash)) is None


def test_freeze_notice_buttons(logs, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication, QMessageBox, QWidget
    from app import crashreport, settings
    app = QApplication.instance() or QApplication([])
    p = crashreport.write("the window froze in the previous session",
                          FREEZE)
    seen = []

    class Top(QWidget):
        def report_issue(self, text=""):
            seen.append(text)
    top = Top()
    boxes = []
    orig = QMessageBox.open
    monkeypatch.setattr(QMessageBox, "open",
                        lambda self: (boxes.append(self), orig(self)))
    monkeypatch.setattr(crashreport, "_last_notice", [-1e9])
    holder = {"w": top}
    monkeypatch.setattr(QApplication, "activeWindow",
                        staticmethod(lambda: holder.get("w")))
    crashreport._notify(p, previous=True, kind="freeze")
    for _ in range(5):
        app.processEvents()
    b = boxes[-1]
    assert "stopped responding" in b.text() and "37" in b.text()
    names = {x.text(): x for x in b.buttons()}
    names["Report This…"].click()
    assert seen[-1].startswith("QuantiSheet stopped responding")
    names["Don't Ask About Freezes"].click()
    assert settings.get(crashreport.S_ASK_FREEZE) is False
    b.close()
    top.deleteLater()
