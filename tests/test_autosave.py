"""AutoSave: saves changed documents to their files, keeps recovery
copies when it can't (or when asked to), and offers them after a crash."""
import json
import os
import stat

import fitz

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import autosave, settings                            # noqa: E402
from test_gui import win, qapp, ANSWERS                       # noqa: E402,F401


def _mark(win):
    win._view.apply_marks([(0, "add_rect", {"rect": [100, 100, 200, 160]})])
    assert win._view.dirty


def _annots(path):
    d = fitz.open(path)
    n = sum(len(list(p.annots())) for p in d)
    d.close()
    return n


def test_autosave_to_the_file(qapp, win):
    path = win._path
    before = _annots(path)
    settings.set("autosave_mode", "file")
    win.autosaver.restart()
    assert "AutoSave On" in win.chip_autosave.text()
    _mark(win)
    assert win.autosaver.tick(force=True) == 1
    assert not win._view.dirty
    assert _annots(path) == before + 1
    assert not autosave.pending()
    assert ":" in win.chip_autosave.text()              # shows the time
    assert win.autosaver.tick(force=True) == 0          # nothing to save


def test_recovery_copies_and_crash_recovery(qapp, win, tmp_path):
    path = win._path
    before = _annots(path)
    win.set_autosave("recovery")
    _mark(win)
    assert win.autosaver.tick(force=True) == 1
    assert win._view.dirty                               # file untouched
    assert _annots(path) == before
    pdf, meta = autosave.recovery_paths(win._view, path)
    assert os.path.exists(pdf)
    assert not autosave.pending()                        # ours, still open
    m = json.load(open(meta))
    m["pid"] = 1                                         # "crashed" session
    m["session"] = "crashed"
    json.dump(m, open(meta, "w"))
    os.utime(pdf, (os.path.getmtime(path) + 60,) * 2)
    items = autosave.pending()
    assert len(items) == 1 and items[0]["original"] == os.path.abspath(path)
    tab = win.open_recovered(items[0])
    assert tab.path is None and tab.suggest == os.path.abspath(path)
    assert win._view.dirty and "(recovered)" in tab.title
    assert _annots(win._view.doc.name) == before + 1
    assert not os.path.exists(pdf)
    out = str(tmp_path / "saved.pdf")
    ANSWERS["save"] = out
    assert win.save_file()
    assert win._path == out and _annots(out) == before + 1
    settings.set("autosave_mode", "file")


def test_read_only_file_keeps_a_recovery_copy(qapp, win):
    path = win._path
    win.set_autosave("file")
    _mark(win)
    os.chmod(path, stat.S_IREAD)
    try:
        assert win.autosaver.tick(force=True) == 1
        assert "read-only" in win.autosaver.problem
        assert "⚠" in win.chip_autosave.text()
        pdf, _m = autosave.recovery_paths(win._view, path)
        assert os.path.exists(pdf)
    finally:
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
    # closing without saving, on purpose, removes the copy
    from PySide6.QtWidgets import QMessageBox
    import test_gui
    orig = QMessageBox.question
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Discard)
    try:
        assert win.close_tab(win.tabs.currentIndex())
    finally:
        QMessageBox.question = orig
    assert not os.path.exists(pdf)
    win.open_path(path)                     # the fixture expects a document


def test_toggle_from_the_menu(qapp, win):
    settings.set("autosave_mode", "file")
    win.autosaver.restart()
    win.toggle_autosave()
    assert autosave.mode() == "off" and not win.autosaver.timer.isActive()
    assert "Off" in win.chip_autosave.text()
    win.toggle_autosave()
    assert autosave.mode() == "file" and win.autosaver.timer.isActive()
    assert win.command("AutoSave") is not None
