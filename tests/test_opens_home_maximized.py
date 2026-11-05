"""QuantiSheet opens maximized and on the Home ribbon tab every time,
whatever tab and window size were used last (Jon, 0.13.11)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest                                                    # noqa: E402

pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtWidgets import QApplication                       # noqa: E402


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    from app import settings
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    return settings


def test_opens_on_home_tab_and_maximized(cfg):
    from app.main_window import MainWindow
    w = MainWindow()
    others = [n for n in w.ribbon.pages if n != "Home"]
    assert others
    w.ribbon.show_page(others[-1])          # the last tab used ...
    cfg.set("window", {"geometry": "", "maximized": False})  # ... restored
    w.close()
    w2 = MainWindow()
    assert w2.ribbon.current() == "Home"
    w2.show_restored()
    QApplication.instance().processEvents()
    assert w2.isMaximized() or w2.windowState() & 0x2   # Qt.WindowMaximized
    w2.close()


def test_master_schedule_button_on_module_tab(cfg):
    """Jon, Oct 28: 'I do not see Master Schedule' - the ribbon hides the
    menu bar, so it needs its own button on the Module tab."""
    from app.main_window import MainWindow
    w = MainWindow()
    # Nov 4: the Module tab's groups live on Project now (fewer tabs)
    from app import quickaccess
    tab, grp = quickaccess.fold("Module", "Schedule")
    g = w.ribbon.page(tab).group(grp)
    texts = [b.defaultAction().text() for b in g.buttons
             if b.defaultAction() is not None]
    assert any("Master Schedule" in t for t in texts), texts
    w.close()


def test_maximized_window_that_does_not_fill_is_put_right(cfg,
                                                          monkeypatch):
    """Jon, Oct 28: 'maximized' (restore button showing) but smaller than
    the screen - the check goes normal and maximizes again."""
    import time
    from app import modern_ui
    from PySide6.QtWidgets import QMainWindow
    w = QMainWindow()
    calls = []
    monkeypatch.setattr(w, "showNormal", lambda: calls.append("normal"))
    monkeypatch.setattr(modern_ui, "fills_screen", lambda win, slack=8: False)
    modern_ui.ensure_maximized(w, checks=(0,))
    t = time.time()
    while not calls and time.time() - t < 2:
        QApplication.instance().processEvents()
    assert calls == ["normal"]
    w.close()
