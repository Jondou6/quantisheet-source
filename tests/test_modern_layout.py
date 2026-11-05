"""Stage 2: the Acrobat-style layout - top bar, tool rail, tool strip and
the All Tools panel - with the ribbon and simple menus one click away."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import modern_ui, settings                          # noqa: E402
from app.ribbon import all_actions, clean                    # noqa: E402
import pytest                                                  # noqa: E402

from test_gui import win as _win, qapp                         # noqa: E402,F401


@pytest.fixture
def win(_win):
    """The window in the modern layout (the default is now the ribbon with
    the tool rail - see test_ribbon_with_rail_is_the_default)."""
    _win.layouts.set_layout("modern", save=False)
    return _win


def test_ribbon_with_rail_is_the_default(_win):
    """Jon, Oct 18 evening: the full ribbon back on top, the tool rail kept
    on the left (with All Tools and the tool strip)."""
    w = _win
    lay = w.layouts
    assert lay.name == "ribbon"
    assert w._ribbon_bar.isVisibleTo(w) and not lay.top.isVisibleTo(w)
    assert lay.rail.isVisibleTo(w)
    assert not lay.dock.isHidden()                   # All Tools open
    w.set_tool("add_cloud")
    assert lay.strip.isVisibleTo(w)                  # tool strip too
    w.set_tool(None)
    assert not lay.strip.isVisibleTo(w)
    assert w.active_ribbon_bar() is w._ribbon_bar


def test_modern_layout_still_works(win):
    lay = win.layouts
    assert lay.name == "modern"
    assert lay.top.isVisibleTo(win) and lay.rail.isVisibleTo(win)
    assert not win._ribbon_bar.isVisibleTo(win)
    assert win.simple_menu is None                 # removed in 1.1.1
    assert not win.menuBar().isVisible()
    assert win.active_ribbon_bar() is lay.top
    # the Menu button holds every menu
    lay._fill_main_menu()
    titles = [a.text() for a in lay.main_menu.actions()]
    for a in win.menuBar().actions():
        if a.menu() is not None and a.isVisible():
            assert a.text() in titles
    # Layout is reached through File and View, not repeated at the end
    assert "Layout" not in titles
    assert win.layouts.menu in [a.menu() for a in win._file_menu.actions()]


def test_every_command_is_in_all_tools(win):
    pane = win.layouts.panel
    listed = {id(a) for a in pane.actions_listed()}
    missing = [clean(a.text()) for _p, a in all_actions(win.menuBar())
               if clean(a.text()) and id(a) not in listed]
    assert not missing, missing
    assert len(listed) == len(pane.actions_listed())      # each one once


def test_filter_finds_tools_and_categories(win):
    pane = win.layouts.panel
    pane.fill()
    pane.search.setText("length")
    names = [clean(a.text()) for a in pane.visible_actions()]
    assert "Length" in names and "Area" not in names
    pane.search.setText("takeoff")         # a category name shows it all
    names = [clean(a.text()) for a in pane.visible_actions()]
    assert "Area" in names and "Count" in names
    pane.search.setText("zzzz no such tool")
    assert pane.visible_actions() == []
    pane.search.clear()
    assert len(pane.visible_actions()) == len(pane.actions_listed())


def test_click_runs_a_tool(win):
    pane = win.layouts.panel
    pane.fill()
    pane.search.setText("cloud")
    it = next(i for i in pane._items() if i.text(0) == "Cloud")
    pane._clicked(it, 0)
    assert win._view.tool == "add_cloud"


def test_pin_to_rail_and_back(win):
    lay = win.layouts
    a = lay._find("Watermark")
    assert a is not None and a not in lay.rail_actions
    lay.set_pinned(a, True)
    assert a in lay.rail_actions and lay.is_pinned(a)
    assert any("watermark" in p.lower() for p in settings.get("pinned_tools"))
    lay.set_pinned(a, False)
    assert a not in lay.rail_actions and not lay.is_pinned(a)
    # Select and Zoom are always first
    assert clean(lay.rail_actions[0].text()) == "Select"


def test_rail_labels_stay_short(win):
    for a in win.layouts.rail_actions:
        assert len(modern_ui.rail_label(a)) <= 11, a.text()
    b = win.layouts.rail.findChildren(modern_ui.RailButton)[0]
    b.defaultAction().setChecked(not b.defaultAction().isChecked())
    assert b.text() == b._label


def test_tool_strip_shows_only_while_a_tool_is_on(win):
    lay = win.layouts
    win.set_tool(None)
    assert not lay.strip.isVisibleTo(win)
    win.set_tool("add_cloud")
    assert lay.strip.isVisibleTo(win)
    texts = [w.text() for w in lay.strip.findChildren(modern_ui.QLabel)]
    assert any("Cloud" in t for t in texts)
    buttons = [b.text() for b in lay.strip.findChildren(modern_ui.QPushButton)]
    assert any(t.startswith("Done") for t in buttons)
    opts = [clean(b.text()) for b in lay.strip.findChildren(
        modern_ui.QToolButton)]
    assert "Markup Color" in opts
    # the tool ending by itself (Esc in the viewer) hides it too
    win._view.set_tool(None)
    lay.tool_changed()
    assert not lay.strip.isVisibleTo(win)


def test_switch_layouts_and_remember(win):
    lay = win.layouts
    lay.set_layout("ribbon")
    assert settings.get("layout") == "ribbon"
    assert win._ribbon_bar.isVisibleTo(win) and not lay.top.isVisibleTo(win)
    assert lay.rail.isVisibleTo(win)           # the ribbon keeps the rail
    assert "simple" not in lay.layout_actions    # Simple Menus removed
    lay.layout_actions["modern"].trigger()
    assert lay.top.isVisibleTo(win)
    assert settings.get("layout") == "modern"


def test_all_tools_starts_open_and_remembers_closing(win):
    lay = win.layouts
    win.resize(1400, 900)
    win.show()
    assert not lay.dock.isHidden() and lay.all_tools_button.isChecked()
    assert lay.panel.actions_listed()               # filled, ready to use
    assert lay.toggle_all_tools() is False and lay.dock.isHidden()
    assert settings.get("all_tools_open") is False
    # closed stays closed after switching layouts and back
    lay.set_layout("ribbon")
    lay.set_layout("modern")
    assert lay.dock.isHidden()
    assert lay.toggle_all_tools() is True and not lay.dock.isHidden()
    assert settings.get("all_tools_open") is True


def test_starting_with_all_tools_open_leaves_keys_on_the_drawing(win):
    """The panel's filter box must not take the keyboard at start-up, or
    tool keys (V, L, A...) would type into it."""
    win.show()
    assert win.focusWidget() is not win.layouts.panel.search


def test_everyone_moves_to_the_ribbon_once_then_keeps_their_pick(
        monkeypatch):
    """The new default (ribbon + rail) is applied once to everyone - even
    someone on Modern or the simple menus - and after that a layout picked
    under View › Layout is kept."""
    store = {"simple_menus": True, "layout": "modern"}
    monkeypatch.setattr(settings, "get", lambda k, d=None: store.get(k, d))
    monkeypatch.setattr(settings, "set",
                        lambda k, v: store.__setitem__(k, v))
    assert modern_ui.initial_layout() == "ribbon"
    assert store["layout"] == "ribbon"
    store["layout"] = "modern"                 # then they pick Modern
    assert modern_ui.initial_layout() == "modern"
    store["layout"] = "simple"                 # Simple Menus is gone
    assert modern_ui.initial_layout() == "ribbon"


def test_closed_panel_stacks_leave_no_tab_strip(win):
    from PySide6.QtWidgets import QTabBar
    win.show()
    win.toggle_bottom_panels(False)
    qapp_ = __import__("PySide6.QtWidgets", fromlist=["QApplication"]
                       ).QApplication.instance()
    qapp_.processEvents()
    win.layouts.hide_orphan_tab_bars()

    def strips(name):
        return [b for b in win.findChildren(QTabBar)
                if b.parent() is win and b.isVisible()
                and name in [b.tabText(i) for i in range(b.count())]]
    assert strips("Markups List") == []
    assert strips("Takeoff")                    # the left stack keeps its tabs
    win.toggle_bottom_panels(True)               # F9 brings them back
    qapp_.processEvents()
    assert strips("Markups List")


# ---- from the Oct 18 code review (Venice) --------------------------------

def test_tools_grey_in_step_with_the_drawing(win):
    """All Tools is filled at start-up, before a drawing is open; rows must
    follow their action's enabled state afterwards."""
    pane = win.layouts.panel
    pane.fill()
    a = next(a for a in pane.actions_listed() if clean(a.text()) == "Cloud")
    rows = pane._items_of[a]
    a.setEnabled(False)
    assert all(r.isDisabled() for r in rows)
    a.setEnabled(True)
    assert not any(r.isDisabled() for r in rows)


def test_closing_the_window_keeps_all_tools_open_next_time(win):
    lay = win.layouts
    win.show()
    lay.show_all_tools()
    assert settings.get("all_tools_open", True) is True
    win.hide()                      # what closing the program does
    assert settings.get("all_tools_open", True) is True


def test_layout_menu_reachable_in_every_layout(win):
    lay = win.layouts
    for name in ("ribbon", "modern"):
        lay.set_layout(name)
        lay.set_pinned(lay._find("Watermark"), True)     # rebuilds menus
        lay.set_pinned(lay._find("Watermark"), False)
        in_file = [a.menu() for a in win._file_menu.actions()]
        assert lay.menu in in_file, name
        assert all(a.isVisible() for a in lay.menu.actions())


def test_simple_menus_are_gone(win):
    """Removed in 1.1.1 (Jon's scope, Nov 4): no layout, no toggle."""
    import pytest
    lay = win.layouts
    with pytest.raises(ValueError):
        lay.set_layout("simple")
    texts = [a.text() for a in win.findChildren(
        __import__("PySide6.QtGui", fromlist=["QAction"]).QAction)]
    assert "Simple Menus" not in texts


def test_cancelling_count_with_no_tool_on(win, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    monkeypatch.setattr(QInputDialog, "getText",
                        staticmethod(lambda *a, **k: ("", False)))
    win.set_tool(None)
    win.set_tool("count")                  # must not raise
    assert win._view.tool is None
    assert win._tool_actions[None].isChecked()
    assert not win._tool_actions["count"].isChecked()


def test_rail_button_keeps_its_tooltip(win):
    b = win.layouts.rail.findChildren(modern_ui.RailButton)[0]
    tip = b.toolTip()
    a = b.defaultAction()
    a.setEnabled(False)
    a.setEnabled(True)
    assert b.toolTip() == tip


# ---- from the Oct 18 code review (Grok) ----------------------------------

def test_tool_strip_does_not_grow(win):
    """F2: 100 tool changes leave one strip, not 100 strips' worth."""
    from PySide6.QtWidgets import QApplication
    lay = win.layouts
    for _ in range(50):
        win.set_tool("add_cloud")
        win.set_tool("count")
        win.set_tool(None)
    QApplication.instance().processEvents()
    from PySide6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    boxes = [b for b in lay.strip.findChildren(modern_ui.QWidget,
                                               "StripBox")]
    assert len(boxes) <= 1
    assert len(lay.strip.actions()) <= 2


def test_pinning_never_breaks_a_command(win):
    """F3: rebuilding the rail must not delete or invalidate the shared
    menu actions it shows."""
    lay = win.layouts
    for name in ("Previous View", "Marquee Zoom", "Watermark"):
        a = lay._find(name)
        if a is None:
            continue
        lay.set_pinned(a, True)
        lay.set_pinned(a, False)
        lay.set_pinned(a, True)
        assert a.text()                      # still a live QAction
        assert a in lay.rail_actions
        lay.set_pinned(a, False)
    assert clean(lay.rail_actions[0].text()) == "Select"
    pv = win.command("Previous View")
    assert pv is None or pv.text()


def test_ctrl_shift_t_brings_the_panel_forward(win):
    """F7: behind another tab, the shortcut brings it to the front (like
    the button) and does not close it."""
    lay = win.layouts
    win.resize(1400, 900)
    win.show()
    lay.show_all_tools()
    win.takeoff_dock.raise_()                 # All Tools now behind a tab
    __import__("PySide6.QtWidgets", fromlist=["QApplication"]
               ).QApplication.instance().processEvents()
    lay.all_tools_action.trigger()
    assert not lay.dock.isHidden()
    assert settings.get("all_tools_open", True) is True


def test_layout_listed_once_under_menu(win):
    """F9: Layout is inside File and View; not a third time at the end."""
    lay = win.layouts
    lay._fill_main_menu()
    subs = [a.menu() for a in lay.main_menu.actions() if a.menu()]
    assert lay.menu not in subs
    lay._fill_main_menu()                    # again: no duplicates
    assert len([a for a in lay.main_menu.actions() if a.menu()]) == len(subs)


def test_tab_switches_do_not_rewrite_settings(win, monkeypatch):
    """F10: only a real open/close is written."""
    lay = win.layouts
    win.show()
    lay.show_all_tools()
    writes = []
    real = settings.set
    monkeypatch.setattr(settings, "set",
                        lambda k, v: (writes.append(k), real(k, v)))
    for _ in range(5):
        win.takeoff_dock.raise_()
        lay.dock.raise_()
    assert "all_tools_open" not in writes


def test_rail_icons_do_not_change_the_menu_icon(win):
    """F15: the rail gives an icon to its own button, not to the shared
    action every menu shows."""
    lay = win.layouts
    a = lay._find("Show Unpriced Markups")
    if a is None:
        return
    before = a.icon().isNull()
    lay.fill_rail()
    assert a.icon().isNull() == before



# ---- round 2 (Venice + Grok) ---------------------------------------------

def test_pins_never_make_the_window_taller(win):
    """Grok N1: the rail scrolls; 20 pins still fit a laptop at 150 %."""
    lay = win.layouts
    names = [clean(a.text()) for a in lay.panel.actions_listed()
             if clean(a.text())][:20]
    settings.set("pinned_tools", names)
    lay.fill_rail()
    assert win.minimumSizeHint().height() <= 640


def test_rebuilds_leave_nothing_behind(win):
    """Grok N4 / Venice M5: 300 tool changes and 100 pin changes leave the
    strip and rail with their one container action."""
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtGui import QAction
    lay = win.layouts
    for _ in range(100):
        win.set_tool("add_cloud")
        win.set_tool("count")
        win.set_tool(None)
    a = lay._find("Watermark")
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    rail_before = len(lay.rail.findChildren(QAction))
    for _ in range(50):
        lay.set_pinned(a, True)
        lay.set_pinned(a, False)
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    assert len(lay.strip.findChildren(QAction)) <= 2
    assert len(lay.rail.findChildren(QAction)) == rail_before


def test_theme_commands_survive_pinning(win):
    """Grok N5: View > Theme > Dark kept working after pins/unpins."""
    lay = win.layouts
    a = lay._find("Watermark")
    for _ in range(40):
        lay.set_pinned(a, True)
        lay.set_pinned(a, False)
        lay.set_layout("ribbon")
        lay.set_layout("modern")
    dark = win.command("Dark")
    assert dark is not None and dark.text() == "Dark"


def test_failed_layout_switch_changes_nothing(win, monkeypatch):
    """Grok N6 / Venice M5: on an error the name, the saved setting and
    the guard are all as before."""
    import pytest
    lay = win.layouts
    lay.set_layout("modern")
    saved = settings.get("layout")

    def boom(*a, **k):
        raise RuntimeError("injected")
    monkeypatch.setattr(lay, "tool_changed", boom)
    with pytest.raises(RuntimeError):
        lay.set_layout("ribbon")
    assert lay.name == "modern" and lay._switching is False
    assert settings.get("layout") == saved


def test_pinning_keeps_your_place_in_all_tools(win):
    """Venice M1: a pin updates in place - open categories stay open."""
    lay = win.layouts
    pane = lay.panel
    pane.fill()
    cat = pane.tree.topLevelItem(1)
    cat.setExpanded(True)
    a = next(x for x in pane.actions_listed() if clean(x.text()) == "Watermark")
    lay.set_pinned(a, True)
    pane.refresh_pins(a)
    assert pane.tree.topLevelItem(1) is cat and cat.isExpanded()
    assert any("pinned" in r.toolTip(0) for r in pane._items_of[a])
    lay.set_pinned(a, False)
    pane.refresh_pins(a)
    assert not any("pinned" in r.toolTip(0) for r in pane._items_of[a])


def test_esc_in_the_filter_gives_the_keyboard_back(win):
    """Venice M4: opening All Tools on purpose lets you type to filter;
    Esc clears the filter, a second Esc returns keys to the drawing."""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    lay = win.layouts
    win.show()
    lay.show_all_tools(focus=True)
    pane = lay.panel
    pane.search.setText("cloud")
    esc = QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier)
    assert pane.eventFilter(pane.search, esc) is True
    assert pane.search.text() == ""
    calls = []
    import types
    pane.give_back_keyboard = types.MethodType(
        lambda self: calls.append(1), pane)
    pane.eventFilter(pane.search, esc)
    assert calls == [1]


def test_window_hide_does_not_mark_the_dock_hidden(win):
    """The round-2 question, settled on this Qt: hiding the window leaves
    the dock's own hidden flag alone (so All Tools stays "open")."""
    win.show()
    win.layouts.show_all_tools()
    win.hide()
    assert win.layouts.dock.isHidden() is False
    assert settings.get("all_tools_open", True) is True


def test_all_tools_covers_the_ribbon_too(win):
    """Venice M13: everything on the full ribbon is in All Tools."""
    from app.ribbon import RibbonButton
    listed = {id(a) for a in win.layouts.panel.actions_listed()}
    on_ribbon = [b.defaultAction() for p in win.ribbon.pages.values()
                 for b in p.findChildren(RibbonButton)
                 if b.defaultAction() is not None]
    missing = [clean(a.text()) for a in on_ribbon if id(a) not in listed]
    assert not missing, missing



def test_every_rail_button_is_on_screen(win):
    """The 0.12.8 user session: the rail showed only Select - the rest
    were squeezed out. With the window at a normal size, every default
    rail button is visible."""
    from PySide6.QtWidgets import QApplication
    lay = win.layouts
    win.resize(1600, 950)
    win.show()
    for _ in range(5):
        QApplication.instance().processEvents()
    buttons = [b for b in lay.rail.findChildren(modern_ui.RailButton)
               if b.defaultAction() in lay.rail_actions]
    assert len(buttons) == len(lay.rail_actions) >= 6
    hidden = [b.text() for b in buttons if not b.isVisible()]
    assert not hidden, hidden


def test_switching_layouts_does_not_widen_the_window(_win):
    """Jon's screen, Oct 18: Simple Menus and back left the window 2,529 px
    wide, past the right edge. The Simple bar was shown while the full
    ribbon still sat beside it in the top row."""
    w = _win
    lay = w.layouts
    w.showNormal()
    w.resize(1500, 900)
    for _ in range(3):
        w.repaint()
    seen = []

    def watch(*_a):
        bars = [b for b in (w._ribbon_bar, lay.top)
                if b.isVisibleTo(w)]
        seen.append(len(bars))
    from PySide6.QtCore import QEvent, QObject

    class Spy(QObject):
        def eventFilter(self, obj, ev):
            if ev.type() == QEvent.Show:
                watch()
            return False
    spy = Spy()
    for b in (w._ribbon_bar, lay.top):
        b.installEventFilter(spy)
    try:
        for name in ("modern", "ribbon", "modern", "ribbon"):
            lay.set_layout(name, save=False)
            need = w.minimumSizeHint().width()
            # never wider than it was, unless the layout itself needs more
            # (the test screen is small, so the window can be shrunk to fit)
            assert w.width() <= max(1500, need), (name, w.width(), need)
            if need >= 2000:                          # say what is wide
                from PySide6.QtWidgets import QDockWidget, QToolBar
                wide = [(type(c).__name__, c.objectName() or
                         getattr(c, "windowTitle", lambda: "")(),
                         c.minimumSizeHint().width())
                        for c in (w.findChildren(QToolBar) +
                                  w.findChildren(QDockWidget))
                        if c.isVisibleTo(w)]
                wide.append(("central", "", w.centralWidget()
                             .minimumSizeHint().width()))
                raise AssertionError((name, need, wide))
    finally:
        for b in (w._ribbon_bar, lay.top):
            b.removeEventFilter(spy)
    assert seen and max(seen) == 1, seen      # never two top bars at once


def test_fit_on_screen_brings_a_wide_window_back(_win):
    w = _win
    w.showNormal()
    avail = w.screen().availableGeometry()
    w.setMinimumWidth(0)
    w.resize(avail.width() + 900, 600)
    modern_ui.fit_on_screen(w)
    assert w.frameGeometry().width() <= max(avail.width(),
                                            w.minimumSizeHint().width() + 40)
    assert w.frameGeometry().right() <= avail.right() or \
        w.minimumSizeHint().width() > avail.width()
