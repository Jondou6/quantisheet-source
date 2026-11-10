"""Chief's independent user test of 4235a254 (message 17NP3T0A, Nov 6):
the click-through findings, one test each. Made-up data only."""
import glob
import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz                                                    # noqa: E402
from PySide6.QtWidgets import QDialog, QPushButton            # noqa: E402

from app.ribbon import clean                                   # noqa: E402
from test_gui import win, qapp                                 # noqa: E402,F401

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _walk(menu, path=()):
    for a in menu.actions():
        if a.isSeparator():
            continue
        name = clean(a.text()).replace("…", "").strip()
        if a.menu() is not None:
            yield from _walk(a.menu(), path + (name,))
        else:
            yield path, name, a


# ---- (g) the File menu is one column --------------------------------------

def test_file_menu_fits_one_column(win, qapp):
    f = win._file_menu
    top = [a for a in f.actions() if not a.isSeparator() and a.isVisible()]
    assert len(top) <= 26, [clean(a.text()) for a in top]
    f.ensurePolished()
    assert f.sizeHint().height() < 760, f.sizeHint()   # a 768-line laptop
    reach = {name for _p, name, _a in _walk(f)}
    for name in ("Open", "New Window", "Open Bid Download (.zip) as a Job",
                 "Close Tab", "Save", "Save As", "Work on a Local Copy",
                 "Copy Back to the Original", "AutoSave",
                 "Recover Unsaved Files", "Print", "Print Preview",
                 "New From Form Library", "Generate Set",
                 "Create PDF From File", "Combine Files",
                 "Import AutoCAD DXF", "Import Markups (PDF or XFDF)",
                 "Export Markups (XFDF)", "Word Document (.docx)",
                 "Password Protect", "Reduce File Size", "Check / Repair PDF",
                 "Open Project Folder", "Version History", "Compare",
                 "Compare Text With", "Compare Revisions (Overlay)",
                 "Quick Compare (Same Sheets)", "Document Properties",
                 "Attachments", "Sign", "Verify Signatures",
                 "Signing Timestamp Server", "Exit"):
        assert name in reach, name
    # shortcuts kept on the moved commands
    assert win.command("Compare…").shortcut().toString() == "Ctrl+Alt+C"
    names = [clean(a.text()) for a in top]
    assert names[-1] == "Exit"
    assert "Export To" in names          # the ribbon's Export button uses it


# ---- (e) every service window and the Project Center can be closed -------

def test_service_windows_have_a_close_button(qapp):
    from app.service.uiutil import Desk
    d = Desk("Example")
    d.finish()
    assert isinstance(d.close_button, QPushButton)
    assert d.close_button.text() == "Close"
    assert not d.close_button.autoDefault()
    d.show()
    qapp.processEvents()
    d.close_button.click()
    qapp.processEvents()
    assert not d.isVisible()
    subs = 0
    for p in glob.glob(os.path.join(ROOT, "app", "service", "*_ui.py")):
        src = open(p, encoding="utf-8").read()
        n = src.count("(uiutil.Desk)")
        if n:
            subs += n
            assert src.count("self.finish()") >= n, os.path.basename(p)
    assert subs >= 20


def test_project_center_picker_has_cancel(qapp, monkeypatch, tmp_path):
    from app import settings
    from app.pm import center
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    seen = {}

    def fake_exec(self):
        seen["d"] = self
        b = getattr(self, "_cancel", None)
        seen["text"] = b.text() if b else None
        if b:
            b.click()
        return self.result()

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    assert center.pick_and_open(None) is None
    assert seen["text"] == "Cancel"
    assert seen["d"].result() == QDialog.Rejected


# ---- (i) Properties names the active tool ---------------------------------

def test_properties_follow_any_tool_change(win, qapp):
    v = win._view
    win.properties.set_view(v)
    calls = []
    real = win.properties.refresh
    win.properties.refresh = lambda: (calls.append(v.tool), real())[1]
    try:
        v.set_tool("measure_length")
        qapp.processEvents()
    finally:
        win.properties.refresh = real
    assert calls and calls[-1] == "measure_length"
    assert "Select" not in win.properties.title.text()


# ---- (f) text that was cut off --------------------------------------------

def test_local_ai_chip_is_wide_enough(win, qapp):
    from app.ribbon import ModelStatus
    m = ModelStatus(win)
    m._text = "Local AI: running · example-model-name-13b-instruct"
    m._fit()
    fm = m.fontMetrics()
    longest = max(fm.horizontalAdvance(x) for x in
                  ("Local AI", "running · example-model-name-13b-instruct"))
    assert m.minimumWidth() >= longest + 28
    m.resize(m.minimumWidth(), 74)
    assert all(fm.horizontalAdvance(x) <= m.width() - 20
               for x in m._lines())


def test_help_center_tree_shows_whole_titles(win, qapp):
    from app.helpcenter import HelpCenter, T
    h = HelpCenter(win)
    try:
        fm = h.tree.fontMetrics()
        longest = max(fm.horizontalAdvance(t["title"]) for t in T)
        h.show()
        qapp.processEvents()
        left = h.tree.width()
        assert left >= min(longest + 40, 440) - 24     # less the handle
        it = next(iter(h.items.values()), None)
        if it is not None and hasattr(it, "toolTip"):
            assert it.toolTip(0)
    finally:
        h.close()


def test_price_database_text_is_not_cut(qapp, monkeypatch, tmp_path):
    from app import pricedb, settings
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    if hasattr(pricedb, "DEFAULT_DIR"):
        monkeypatch.setattr(pricedb, "DEFAULT_DIR", str(tmp_path / "db"))
    from app.pricedb_ui import DatabaseDialog
    d = DatabaseDialog()
    try:
        d.show()
        qapp.processEvents()
        need = d.info.heightForWidth(d.info.width())
        assert d.info.height() >= need - 2, (d.info.height(), need)
        assert d.width() >= 640
    finally:
        d.close()


# ---- (a) Organize Pages draws every page ----------------------------------

def test_organize_pages_shows_thumbnails(qapp):
    from app.organize import OrganizeDialog
    doc = fitz.open()
    for i in range(9):
        p = doc.new_page(width=612 if i % 2 else 792,
                         height=792 if i % 2 else 612)
        p.insert_text((72, 120), f"Example page {i + 1}", fontsize=36)
    d = OrganizeDialog(doc)
    d.show()
    # every cell has a page-shaped picture at once, before any rendering
    assert all(not it.icon().isNull() for it in d.items())
    for _ in range(40):
        qapp.processEvents()
        if not d._queue:
            break
    qapp.processEvents()
    assert not d._queue
    assert set(d._thumbs) == set(range(9))
    for it in d.items():
        assert not it.icon().isNull()
        assert it.sizeHint().width() >= d.list.iconSize().width()
        rect = d.list.visualItemRect(it)
        assert rect.height() >= d.list.iconSize().height() // 2
    # the plan compares equal to an untouched document (tuples, not lists)
    assert d.plan() == [(i, 0) for i in range(9)]
    assert "not applied" not in d.info.text()
    d.list.setCurrentRow(0)
    d.rotate(90)
    assert d.plan()[0] == (0, 90)
    d.close()


# ---- (h) dark mode repaints and the caption follows -----------------------

def test_theme_switch_repaints_and_sets_caption(win, qapp, monkeypatch):
    from app import theme
    win.show()
    qapp.processEvents()
    calls = []
    monkeypatch.setattr(theme, "title_bar",
                        lambda w, dark, again=True:
                        calls.append((w, dark)) or True)
    try:
        theme.apply(qapp, "dark")
        assert (win, True) in calls
        calls.clear()
        theme.apply(qapp, "light")
        assert (win, False) in calls
    finally:
        theme.apply(qapp, "light")


@pytest.mark.skipif(sys.platform == "win32", reason="off Windows only")
def test_title_bar_is_a_no_op_off_windows(win):
    from app import theme
    assert theme.title_bar(win, True) is False


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_title_bar_on_windows(win, qapp):
    from app import theme
    win.show()
    qapp.processEvents()
    assert theme.title_bar(win, True) in (True, False)   # never raises
    assert win.property("qs_dark_caption") in (True, None)
    theme.title_bar(win, False)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_dark_caption_reads_back_dark(win, qapp):
    """Chief's re-test, Nov 7 (F7): attribute 20 read back 0."""
    import time
    from app import theme
    win.show()
    qapp.processEvents()
    try:
        theme.apply(qapp, "dark")
        end = time.time() + 2
        while time.time() < end:
            qapp.processEvents()
            time.sleep(0.02)
        got = theme.caption_is_dark(win)
        if got is None:
            pytest.skip("this Windows can't report the caption")
        assert got is True
    finally:
        theme.apply(qapp, "light")
