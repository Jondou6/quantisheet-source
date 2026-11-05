"""Empty-state copy for every dock and panel object name."""
import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (  # noqa: E402
    QApplication, QDockWidget, QLabel, QListWidget, QScrollArea,
    QVBoxLayout, QWidget,
)

from app import empty_states  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCES = ("app/docks.py", "app/panels.py", "app/main_window.py")


def _text(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def _dock_names(main):
    """Same rule as MainWindow._dock: title, lower case, spaces to _."""
    titles = re.findall(r'_dock\(\s*"([^"]+)"', main)
    return [title.lower().replace(" ", "_") for title in titles]


def test_every_empty_name_is_a_real_panel():
    files = {rel: _text(rel) for rel in SOURCES}
    main = files["app/main_window.py"]
    assert 'd.setObjectName(title.lower().replace(" ", "_"))' in main
    names = set(_dock_names(main))
    explicit = re.findall(r'setObjectName\(\s*"([^"]+)"\s*\)', main)
    assert "thumbs" in explicit
    names.add("thumbs")
    # docks.py and panels.py set no object names of their own today.
    # Any they gain have to be listed in EMPTY too.
    for rel in ("app/docks.py", "app/panels.py"):
        for name in re.findall(r'setObjectName\(\s*"([^"]+)"\s*\)',
                               files[rel]):
            names.add(name)
    assert set(empty_states.EMPTY) == names
    for name in empty_states.EMPTY:
        assert name in names


def test_copy_is_a_plain_pair():
    for name, pair in empty_states.EMPTY.items():
        assert isinstance(pair, tuple) and len(pair) == 2, name
        what, how = pair
        assert what.strip() == what and how.strip() == how
        assert what.endswith(".") and how.endswith(".")
        assert "<" not in what and "<" not in how
        assert len(what) <= 160 and len(how) <= 200
        assert empty_states.sentence(name) == f"{what} {how}"
    assert empty_states.sentence("not_a_panel") is None


def test_apply_empty_state_on_a_dock_and_a_bare_panel(qapp=None):
    app = QApplication.instance() or QApplication([])
    assert app
    dock = QDockWidget("Pages")
    dock.setObjectName("pages")
    inner = QWidget()
    QVBoxLayout(inner)
    scroll = QScrollArea()
    scroll.setObjectName("DockScroll")
    scroll.setWidget(inner)
    dock.setWidget(scroll)
    text = empty_states.apply_empty_state(dock)
    assert text == empty_states.sentence("pages")
    label = inner.findChild(QLabel, empty_states.EMPTY_LABEL)
    assert label is not None and label.text() == text
    assert dock.property("emptyState") == text
    empty_states.apply_empty_state(dock)
    labels = [c for c in inner.findChildren(QLabel, empty_states.EMPTY_LABEL)
              if c.parent() is inner]
    assert len(labels) == 1
    # the panel widget itself has no object name; the dock's name is used
    assert empty_states.apply_empty_state(inner) == text

    bare = QWidget()
    bare.setObjectName("estimate")
    QVBoxLayout(bare)
    priced = empty_states.apply_empty_state(bare)
    assert "unit cost" in priced
    assert bare.findChild(QLabel, empty_states.EMPTY_LABEL).text() == priced

    unknown = QWidget()
    unknown.setObjectName("ribbon_bar")
    QVBoxLayout(unknown)
    assert empty_states.apply_empty_state(unknown) is None
    assert unknown.findChild(QLabel, empty_states.EMPTY_LABEL) is None
    assert empty_states.apply_empty_state(None) is None
    dock.close()


def test_thumbs_keeps_the_sentence_on_the_list():
    QApplication.instance() or QApplication([])
    thumbs = QListWidget()
    thumbs.setObjectName("thumbs")
    text = empty_states.apply_empty_state(thumbs)
    assert text == empty_states.sentence("thumbs")
    assert thumbs.toolTip() == text
    assert thumbs.property("emptyState") == text
    assert thumbs.findChild(QLabel, empty_states.EMPTY_LABEL) is None


def test_unnamed_panel_uses_its_dock():
    QApplication.instance() or QApplication([])
    dock = QDockWidget("Quantities")
    dock.setObjectName("quantities")
    inner = QWidget()
    QVBoxLayout(inner)
    dock.setWidget(inner)
    text = empty_states.apply_empty_state(inner)
    assert text == empty_states.sentence("quantities")
    assert "measure" in text.lower()
    dock.close()
