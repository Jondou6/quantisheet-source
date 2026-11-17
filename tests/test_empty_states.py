"""Empty-state copy for every dock and panel object name."""
import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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
