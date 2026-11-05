import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from app import field_mode as fm


@pytest.fixture
def store(monkeypatch):
    s = {}
    monkeypatch.setattr(fm.settings, "get", lambda k, d=None: s.get(k, d))
    monkeypatch.setattr(fm.settings, "set", lambda k, v: s.__setitem__(k, v))
    return s


def test_densities():
    assert fm.DENSITY["touch"]["target"] == 40
    assert fm.DENSITY["compact"]["target"] < fm.DENSITY["comfortable"]["target"] < 40
    q = fm.stylesheet("touch")
    assert "min-height: 40px" in q and "font-size: 13pt" in q


def test_toggle_hides_ribbon_and_remembers(store):
    from PySide6.QtWidgets import QApplication, QMainWindow, QWidget
    QApplication.instance() or QApplication([])
    w = QMainWindow(); w.ribbon = QWidget(); w.setMenuWidget(w.ribbon); w.show()
    f = fm.FieldMode(w, apply_theme=lambda m: store.__setitem__("_theme", m))
    f.set(True)
    assert not w.ribbon.isVisible() and store["field_mode"] is True
    assert store["density"] == "touch" and store["_theme"] == "dark"
    assert "min-height: 40px" in w.styleSheet()
    f.set(False)
    assert w.ribbon.isVisible() and store["field_mode"] is False
    assert store["_theme"] == "restore"
    assert w.styleSheet() == ""          # back to the normal look


def test_restore_on_start_and_shortcut(store):
    from PySide6.QtWidgets import QApplication, QMainWindow, QWidget
    QApplication.instance() or QApplication([])
    store.update(field_mode=True, density="touch")
    w = QMainWindow(); w.ribbon = QWidget(); w.show()
    f = fm.install(w, apply_theme=lambda m: None)
    assert f.on and f.action.shortcut().toString() == "Ctrl+5"
    f.action.trigger()
    assert not f.on


def test_set_density_without_field_mode(store):
    from PySide6.QtWidgets import QApplication, QMainWindow
    QApplication.instance() or QApplication([])
    w = QMainWindow()
    f = fm.FieldMode(w, apply_theme=lambda m: None)
    f.set_density("comfortable")
    assert store["density"] == "comfortable"
    with pytest.raises(ValueError):
        f.set_density("huge")
