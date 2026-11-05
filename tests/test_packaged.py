"""The Store (MSIX) version: packaged detection, the one-time offer to
remove an older setup copy, and the print helper's sign-in entry left to
Windows' Startup settings. No real package or uninstall is touched."""
from app import packaged, printer_setup, settings


def _cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {})


def test_not_packaged_in_tests():
    packaged._CACHE.clear()
    assert packaged.is_packaged() is False
    packaged._CACHE.clear()


def test_old_copy_offered_once(tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch)
    monkeypatch.setattr(packaged, "is_packaged", lambda: True)
    monkeypatch.setattr(packaged, "old_install", lambda: r"C:\x\unins000.exe")
    ran = []
    assert packaged.offer_remove_old(None, ask=lambda: True,
                                     run=ran.append) == "removed"
    assert ran == [r"C:\x\unins000.exe"]
    assert packaged.offer_remove_old(None, ask=lambda: True,
                                     run=ran.append) is None   # asked once
    assert len(ran) == 1


def test_nothing_asked_when_not_packaged(tmp_path, monkeypatch):
    _cfg(tmp_path, monkeypatch)
    monkeypatch.setattr(packaged, "is_packaged", lambda: False)
    assert packaged.offer_remove_old(None, ask=lambda: 1 / 0) is None


def test_packaged_print_helper_uses_startup_settings(monkeypatch):
    monkeypatch.setattr(packaged, "is_packaged", lambda: True)
    opened, wrote = [], []
    monkeypatch.setattr(packaged, "open_startup_settings",
                        lambda: opened.append(1) or True)
    monkeypatch.setattr(printer_setup, "_set_run",
                        lambda *a: wrote.append(a))
    monkeypatch.setattr(printer_setup.ph, "ensure_running", lambda: None)
    monkeypatch.setattr(printer_setup, "status", lambda: [])
    said = []
    printer_setup.user_on(log=said.append)
    printer_setup.user_off(log=said.append)
    assert wrote == [] and len(opened) == 2
    assert "Settings > Apps > Startup" in said[0]
