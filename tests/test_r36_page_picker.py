"""r36 v2 step 4 (Jon): the Estimating Tools window picks its page from a
drop-down instead of a tab bar (10 tabs didn't fit and scrolled with
arrows on Windows at 150 %, step-3 test). The drop-down lists the 10
pages in menu order; picking one shows that page; each Takeoff >
Estimating Tools command opens the window on its own page with that page
picked; Ctrl+PgDown / Ctrl+PgUp still step through the pages."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt                                    # noqa: E402
from PySide6.QtGui import QKeySequence, QShortcut                # noqa: E402
from PySide6.QtWidgets import QComboBox, QDialog, QTabBar        # noqa: E402

from app import assemblies                                       # noqa: E402
from app.estimating import ui                                    # noqa: E402
from test_gui import ANSWERS, win, qapp                          # noqa: E402,F401

KEYS = [k for k, _l in ui.PAGES]
LABELS = [label.replace("…", "").replace("&&", "&") for _k, label in ui.PAGES]


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(QDialog, "exec", lambda self, *a: 0)


def test_dropdown_lists_the_ten_pages_in_menu_order(qapp):
    dlg = ui.EstimatingTools(None, None, "check")
    assert isinstance(dlg.picker, QComboBox)
    assert [dlg.picker.itemText(i) for i in range(dlg.picker.count())] \
        == LABELS
    # v2 step 7: Match Rates and Assembly Rules pages added (was 10)
    assert dlg.picker.count() == len(KEYS) == dlg.stack.count()
    assert [b for b in dlg.findChildren(QTabBar) if b.isVisible()] == []
    dlg.close()


def test_picking_an_item_switches_the_page(qapp):
    dlg = ui.EstimatingTools(None, None, "check")
    seen = []
    for k in KEYS:
        p = dlg.page(k)
        p.refresh = (lambda kk=k: seen.append(kk))
    for i, k in enumerate(KEYS):
        dlg.picker.setCurrentIndex(i)
        qapp.processEvents()
        assert dlg.stack.currentWidget() is dlg.page(k)
        assert dlg.current_key() == k
    assert seen[-(len(KEYS) - 1):] == KEYS[1:]                # each page refreshed when shown
    dlg.close()


def test_ctrl_page_keys_step_through_pages(qapp):
    dlg = ui.EstimatingTools(None, None, "check")
    keys = {s.key().toString(): s for s in dlg.findChildren(QShortcut)}
    nxt = keys[QKeySequence("Ctrl+PgDown").toString()]
    prv = keys[QKeySequence("Ctrl+PgUp").toString()]
    nxt.activated.emit()
    assert dlg.current_key() == KEYS[1] and dlg.picker.currentIndex() == 1
    prv.activated.emit()
    prv.activated.emit()                        # wraps to the last page
    assert dlg.current_key() == KEYS[-1]
    assert dlg.picker.focusPolicy() & Qt.TabFocus   # arrow keys in the combo
    dlg.close()


def test_each_menu_command_opens_its_own_page_picked(win, qapp):
    m = None
    for a in win.menuBar().actions():
        for b in (a.menu().actions() if a.menu() else []):
            if b.menu() is not None and b.text() == ui.MENU_TITLE:
                m = b.menu()
    acts = [a for a in m.actions() if a.text()]
    assert len(acts) == len(KEYS)            # v2 step 7: was 10
    for i, a in enumerate(acts):
        a.trigger()
        qapp.processEvents()
        dlg = ui.LAST
        assert dlg.picker.currentIndex() == i
        assert dlg.picker.currentText() == LABELS[i]
        assert dlg.stack.currentWidget() is dlg.page(KEYS[i])
