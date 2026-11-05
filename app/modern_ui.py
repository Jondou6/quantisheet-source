"""Modern layout (stage 2): an Acrobat-style window.

    top bar     Menu (every menu) · All tools · Open Save Print Undo Redo ·
                search box (Ctrl+K) · Help
    tool rail   a slim column on the left: Select, Zoom and your pinned
                tools, each with a short label under its icon
    tool strip  a thin bar under the top bar that shows only while a tool
                is active: what it does, its options (color, style, snap,
                scale) and Done (Esc)
    All Tools   a panel on the left listing every command by category,
                with a filter box; click to run, right-click to pin

It only places the QActions the menus already have, so shortcuts, checked
and enabled states stay in step with the ribbon and menus. The full
ribbon and the simple menus are still there: View › Layout (also on the
File menu) switches between the three (setting "layout").

Hook (main_window.py, at the end of __init__):
    from . import modern_ui
    modern_ui.install(self)
"""
import logging

from PySide6.QtCore import QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QFont, QKeySequence
from PySide6.QtWidgets import (QDockWidget, QFrame, QHBoxLayout, QLabel,
                               QLineEdit, QMenu, QPushButton, QScrollArea,
                               QSizePolicy,
                               QToolBar, QToolButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from . import icons, settings
from .ribbon import clean

log = logging.getLogger(__name__)

# "simple" (Simple Menus) was removed in 1.1.1 (Jon's scope, Nov 4); a
# saved "simple" opens the ribbon
LAYOUTS = ("modern", "ribbon")
# layouts with the left side: tool rail, All Tools panel, tool strip
WITH_RAIL = ("modern", "ribbon")
LAYOUT_NAMES = {"modern": "Modern",
                "ribbon": "Full Ribbon + Tool Rail"}

# always at the top of the tool rail, before the pinned tools
RAIL_BASICS = ["Select", "Marquee Zoom"]
RAIL_ICONS = {"show unpriced markups": "dollar", "pre-bid checklist":
              "checklist", "check takeoff": "audit", "compare revisions "
              "(overlay)": "overlay", "watermark": "watermark"}

# All Tools categories after the simple-menu tabs: the menu each one takes
# its leftover commands from, and its icon
CATEGORY_ICONS = {"Takeoff": "measure_length",
                  "Markup & Review": "add_cloud", "Estimate": "estimate",
                  "Reports": "proposal", "Project": "folder",
                  "Home": "home", "File": "open", "Edit": "edit_text",
                  "View": "zoom", "Fill & Sign": "sign", "Pages": "page_add",
                  "Document": "export", "Tools": "settings", "Civil": "truck",
                  "Billing": "pay_app", "AI": "ai", "Help": "info",
                  "Review": "compare", "Markup": "add_cloud",
                  "Panels": "panels"}
# menus whose leftover commands belong with a category above
MERGE = {"Markup": "Markup & Review", "Review": "Markup & Review",
         "Takeoff": "Takeoff", "Estimate": "Estimate", "Project": "Project"}

# what to do with each kind of tool (viewer.TOOLS kinds)
HINTS = {"rect": "Drag a box on the page.",
         "line": "Click the start, then the end.",
         "points": "Click each point; double-click to finish.",
         "click": "Click on the page.",
         "pen": "Draw with the mouse."}
MARKUP_OPTIONS = ["Markup Color", "Default Style", "Line Styles"]
AREA_OPTIONS = ["Hatch Patterns"]
MEASURE_OPTIONS = ["Calibrate (Set Scale)", "Snap to Content"]


def _key(text):
    return clean(text).replace("…", "").rstrip(". ").strip().lower()


LAYOUT_VERSION = 2      # bump to move everyone to a new default once


def initial_layout():
    """The layout picked under View › Layout. Jon, Oct 18 (evening): the
    full ribbon back on top, keeping the tool rail on the left - the new
    default, applied once to everyone (the modern-only default lasted a
    day and no one had picked it on purpose yet). After that, whatever
    someone picks is kept."""
    if settings.get("layout_version") != LAYOUT_VERSION:
        settings.set("layout_version", LAYOUT_VERSION)
        settings.set("layout", "ribbon")
        return "ribbon"
    stored = settings.get("layout")
    return stored if stored in LAYOUTS else "ribbon"


def rail_label(a, limit=9):
    """A short word or two for under a rail icon."""
    from .simple_menu import SHORT
    full = clean(a.text())
    t = SHORT.get(full) or a.iconText() or full
    t = t.split("(")[0].strip() or t
    if len(t) > limit:
        words = t.split()
        t = words[0] if len(words[0]) <= limit + 2 else t[:limit]
    return t


class RailButton(QToolButton):
    """A tool rail button: icon with a short label under it (the label
    stays short when the action changes, e.g. on check)."""

    def __init__(self, action, parent=None):
        super().__init__(parent)
        self.setObjectName("RailButton")
        self.setDefaultAction(action)
        self._label = rail_label(action)
        self._icon = None
        if action.icon().isNull():        # the button's own icon (F15):
            tool = action.data() if isinstance(action.data(), str) else None
            name = RAIL_ICONS.get(clean(action.text()).lower())
            for n in (tool, name, "list"):
                if n and icons.has(n):
                    self._icon = icons.icon(n)
                    self.setIcon(self._icon)
                    break
        self.setText(self._label)
        self.setIconSize(QSize(22, 22))
        self.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        tip = clean(action.text())
        key = action.shortcut().toString(QKeySequence.NativeText)
        self._tip = f"{tip}  ({key})" if key else tip
        self.setToolTip(self._tip)
        action.changed.connect(self._relabel)

    RAIL_TEXT_W = 60          # px for the label inside the 66 px button

    def _fit_label(self):
        """Large Windows text sizes cut "Preflight" and "Request" off at the
        rail's edge: shrink this button's label until it fits. (A widget
        style sheet - the app's #RailButton rule would undo setFont.)"""
        from PySide6.QtGui import QFontMetrics
        self.ensurePolished()
        f = self.font()
        size = f.pointSizeF() if f.pointSizeF() > 0 else 8.0
        start = size
        while size > 6.0 and QFontMetrics(f).horizontalAdvance(
                self._label) > self.RAIL_TEXT_W:
            size -= 0.5
            f.setPointSizeF(size)
        if size < start:
            self.setStyleSheet(f"font-size: {size:g}pt;")

    def showEvent(self, e):
        super().showEvent(e)
        if not getattr(self, "_fitted", False):
            self._fitted = True
            self._fit_label()

    def _relabel(self):
        # Qt copies the action's own text and tooltip back on every change
        if self.text() != self._label:
            self.setText(self._label)
        if self.toolTip() != self._tip:
            self.setToolTip(self._tip)
        if self._icon is not None and self.defaultAction().icon().isNull():
            self.setIcon(self._icon)

class StripButton(QToolButton):
    """A tool-strip button for a shared menu action: its name beside its
    icon, kept when the action changes."""

    def __init__(self, action, parent=None):
        super().__init__(parent)
        self.setObjectName("StripOption")
        self.setDefaultAction(action)
        self._label = clean(action.text())
        self.setText(self._label)
        self.setIconSize(QSize(16, 16))
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        action.changed.connect(self._relabel)

    def _relabel(self):
        if self.text() != self._label:
            self.setText(self._label)


def _maximized(win):
    """Maximized as asked, even before Windows has finished maximizing
    (isMaximized() can still be False right after showMaximized())."""
    from PySide6.QtCore import Qt
    try:
        return bool(win.isMaximized() or
                    win.windowState() & Qt.WindowMaximized)
    except RuntimeError:
        return False


def fills_screen(win, slack=8):
    """True when the window covers its screen's free area (the screen
    minus the taskbar), give or take a few pixels."""
    scr = win.screen()
    if scr is None:
        return True
    av = scr.availableGeometry()
    fr = win.frameGeometry()
    return fr.width() >= av.width() - slack and \
        fr.height() >= av.height() - slack


def ensure_maximized(win, checks=(0, 400, 1500)):
    """Show maximized and make sure it really fills the screen (Jon, Oct
    28: 0.13.13 opened 'maximized' - the restore button showing - but
    smaller than the screen). Windows can be left that way when the size
    changes while it maximizes (a high-DPI screen, panels laid out while
    showing); each check puts it right by going normal and maximizing
    again. Checks stop once the person un-maximizes it themselves."""
    from PySide6.QtCore import QTimer
    win.showMaximized()
    win._qs_want_max = True

    def check():
        try:
            if not getattr(win, "_qs_want_max", False) or \
                    win.isMinimized() or not win.isVisible():
                return
            if not _maximized(win):
                return                  # the person un-maximized it
            if not fills_screen(win):
                win.showNormal()
                win.setGeometry(win.screen().availableGeometry())
                win.showMaximized()
        except RuntimeError:            # window already gone
            pass
    for ms in checks:
        QTimer.singleShot(ms, check)
    QTimer.singleShot(max(checks) + 100,
                      lambda: setattr(win, "_qs_want_max", False))


def fit_on_screen(win, was_max=False):
    """Keep the window on its screen: a maximized window stays maximized,
    and one wider or taller than the screen is brought back inside it.
    Returns True if the window was changed."""
    if not win.isVisible():
        return False
    if was_max:
        if not win.isMaximized():
            win.showMaximized()
            return True
        return False
    scr = win.screen()
    if scr is None:
        return False
    avail = scr.availableGeometry()
    frame = win.frameGeometry()
    extra_w = frame.width() - win.width()       # title bar and borders
    extra_h = frame.height() - win.height()
    w = min(win.width(), max(win.minimumWidth(), avail.width() - extra_w))
    h = min(win.height(), max(win.minimumHeight(), avail.height() - extra_h))
    changed = (w, h) != (win.width(), win.height())
    if changed:
        win.resize(w, h)
    fr = win.frameGeometry()
    x = min(max(fr.x(), avail.x()), max(avail.x(), avail.right() - fr.width() + 1))
    y = min(max(fr.y(), avail.y()), max(avail.y(), avail.bottom() - fr.height() + 1))
    if (x, y) != (fr.x(), fr.y()):
        win.move(x, y)
        changed = True
    return changed


class Layouts:
    def __init__(self, win):
        self.win = win
        self.name = None
        self.before_simple = "modern"
        self._switching = False
        self._last_tool = object()
        self.top = self._build_top()
        self.rail = self._build_rail_bar()
        self.strip = self._build_strip()
        self.dock = self._build_dock()
        self.menu = self._build_layout_menu()
        self.fill_rail()
        self._poll = QTimer(win)                 # a tool can end on its own
        self._poll.setInterval(300)
        self._poll.timeout.connect(self.tool_changed)
        self.set_layout(initial_layout(), save=False)
        QTimer.singleShot(0, self.hide_orphan_tab_bars)

    # ---- the three bars ---------------------------------------------------
    def _bar(self, title, name):
        b = QToolBar(title)
        b.setObjectName(name)
        b.setMovable(False)
        b.setFloatable(False)
        b.toggleViewAction().setVisible(False)
        b.setContextMenuPolicy(Qt.PreventContextMenu)
        return b

    def _icon_button(self, icon, tip, menu=None, text=None, obj="TopButton"):
        b = QToolButton()
        b.setObjectName(obj)
        if icon and icons.has(icon):
            b.setIcon(icons.icon(icon))
        b.setIconSize(QSize(18, 18))
        if text:
            b.setText(text)
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        b.setToolTip(tip)
        b.setAutoRaise(True)
        if menu is not None:
            b.setMenu(menu)
            b.setPopupMode(QToolButton.InstantPopup)
        return b

    def _build_top(self):
        w = self.win
        bar = self._bar("Top Bar", "modern_top_bar")
        bar.setIconSize(QSize(18, 18))
        # every menu, in one button (the menu bar itself stays hidden)
        self.main_menu = QMenu("Menu", w)
        self.menu_button = self._icon_button("menu", "Menu: every command",
                                             self.main_menu, "Menu")
        self.main_menu.aboutToShow.connect(self._fill_main_menu)
        bar.addWidget(self.menu_button)
        self.all_tools_button = self._icon_button(
            "tools", "All tools: every command by category (Ctrl+Shift+T)",
            text="All tools")
        self.all_tools_button.setCheckable(True)
        self.all_tools_button.clicked.connect(self.toggle_all_tools)
        bar.addWidget(self.all_tools_button)
        bar.addSeparator()
        self.quick = []
        for name in ("Open", "Save", "Print", "Undo", "Redo"):
            a = w.command(name)
            if a is not None:
                bar.addAction(a)
                self.quick.append(a)
        left = QWidget()
        left.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        bar.addWidget(left)
        key = QKeySequence("Ctrl+K").toString(QKeySequence.NativeText)
        self.search = QPushButton(f"  Search tools and commands     {key}")
        self.search.setObjectName("CommandSearch")
        if icons.has("find"):
            self.search.setIcon(icons.icon("find"))
        self.search.setMinimumWidth(300)
        self.search.setCursor(Qt.PointingHandCursor)
        self.search.setToolTip("Find any command by typing part of its name")
        self.search.clicked.connect(lambda: w.command_search())
        bar.addWidget(self.search)
        right = QWidget()
        right.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        bar.addWidget(right)
        if getattr(w, "_help_menu", None) is not None:
            bar.addWidget(self._icon_button("info", "Help", w._help_menu))
        w.addToolBar(Qt.TopToolBarArea, bar)
        return bar

    def _fill_main_menu(self):
        """Every visible menu-bar menu, in order. Rebuilt only when that
        list changes, by removing entries (QMenu.clear() could delete or
        invalidate the shared submenus). Layout is inside File and View."""
        want = [a.menu() for a in self.win.menuBar().actions()
                if a.menu() is not None and a.isVisible()]
        have = getattr(self, "_main_menus", None)
        if have == want:
            return
        for act in list(self.main_menu.actions()):
            self.main_menu.removeAction(act)
        for sub in want:
            self.main_menu.addMenu(sub)
        self._main_menus = want

    def _build_rail_bar(self):
        """The tool rail: a vertical toolbar with one entry per button, so
        Qt moves the ones that don't fit behind a >> button and the window
        never grows with the pins (Grok N1; one big block of buttons showed
        only the first one, or made the window taller)."""
        bar = self._bar("Tool Rail", "modern_tool_rail")
        bar.setOrientation(Qt.Vertical)
        bar.setIconSize(QSize(22, 22))
        bar.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.win.addToolBar(Qt.LeftToolBarArea, bar)
        self._rail_entries = []
        return bar

    def _build_strip(self):
        w = self.win
        w.addToolBarBreak(Qt.TopToolBarArea)
        bar = self._bar("Tool Options", "modern_tool_strip")
        bar.setIconSize(QSize(16, 16))
        w.addToolBar(Qt.TopToolBarArea, bar)
        bar.hide()
        return bar

    # ---- All Tools panel ------------------------------------------------------
    def _build_dock(self):
        w = self.win
        self.panel = AllToolsPane(self)
        d = QDockWidget("All Tools", w)
        d.setObjectName("all_tools")
        d.setWidget(self.panel)
        w.addDockWidget(Qt.LeftDockWidgetArea, d)
        first = getattr(w, "thumb_dock", None)
        if first is not None:
            w.tabifyDockWidget(first, d)
        d.visibilityChanged.connect(self._dock_shown)
        front = getattr(w, "takeoff_dock", None)
        if front is not None:
            front.raise_()
        self.dock_action = d.toggleViewAction()
        self.dock_action.setText("All Tools")
        # Ctrl+Shift+T does what the All tools button does: brings the
        # panel to the front when it's behind another tab (Grok F7)
        self.all_tools_action = QAction("All Tools", w)
        self.all_tools_action.setShortcut(QKeySequence("Ctrl+Shift+T"))
        self.all_tools_action.triggered.connect(self.toggle_all_tools)
        w.addAction(self.all_tools_action)
        d.hide()
        return d

    def _dock_shown(self, vis):
        try:
            self._dock_shown_(vis)
        except RuntimeError:
            # the window is being destroyed (app closing): nothing to keep
            pass

    def _dock_shown_(self, vis):
        self.all_tools_button.setChecked(bool(vis))
        if vis and not self.panel._filled:
            self.panel.fill_soon()
        # remember open or closed (not just sent behind another tab, and
        # not hidden because another layout was picked); written only when
        # it changes, not on every tab switch
        if self.name in WITH_RAIL and not self._switching \
                and self.win.isVisible():     # not while the window hides
            now = not self.dock.isHidden()
            if settings.get("all_tools_open", True) != now:
                settings.set("all_tools_open", now)

    def show_all_tools(self, focus=False):
        """The All Tools panel open and in front of its stack."""
        self.dock.show()
        self.dock.raise_()
        if not self.panel._filled:
            if focus:
                self.panel.fill()
            else:
                self.panel.fill_soon()          # not during start-up
        if focus:
            self.panel.search.setFocus()

    def toggle_all_tools(self):
        """Open the All Tools panel (in front of its stack), or close it."""
        d = self.dock
        if d.isVisible() and not d.visibleRegion().isEmpty():
            d.hide()
        else:
            self.show_all_tools(focus=True)
        self.all_tools_button.setChecked(d.isVisible())
        return d.isVisible()

    # ---- pins on the rail ----------------------------------------------------
    def _find(self, name):
        sm = getattr(self.win, "simple_menu", None)
        if sm is not None:
            return sm._find(name)
        return self.win.command(name)

    def pins(self):
        from .simple_menu import DEFAULT_PINS
        return list(settings.get("pinned_tools") or DEFAULT_PINS)

    def is_pinned(self, a):
        k = _key(a.text())
        return any(_key(p) == k for p in self.pins())

    def set_pinned(self, a, on):
        """Pin a command to the rail (and the simple menus' Home tab)."""
        name = clean(a.text())
        k = _key(name)
        pins = [p for p in self.pins() if _key(p) != k]
        if on:
            pins.append(name)
        settings.set("pinned_tools", pins)
        sm = getattr(self.win, "simple_menu", None)
        if sm is not None:
            sm.build()
        self.fill_rail()

    def fill_rail(self):
        bar = self.rail
        for act in getattr(self, "_rail_entries", []):   # never clear():
            w_ = act.defaultWidget() if hasattr(act, "defaultWidget") \
                else None                               # see _swap
            bar.removeAction(act)
            act.deleteLater()
            if w_ is not None:
                w_.hide()
                w_.deleteLater()
        self._rail_entries = []
        self.rail_actions = []
        seen = set()

        def put(widget):
            self._rail_entries.append(bar.addWidget(widget))

        def sep():
            line = QFrame()
            line.setObjectName("RailSep")
            line.setFrameShape(QFrame.HLine)
            put(line)

        def add(a):
            if a is None or id(a) in seen:
                return
            seen.add(id(a))
            put(RailButton(a))
            self.rail_actions.append(a)

        for n in RAIL_BASICS:
            add(self._find(n))
        sep()
        for n in self.pins():
            add(self._find(n))
        sep()
        more = QToolButton()
        more.setObjectName("RailButton")
        more.setText("More")
        if icons.has("tools"):
            more.setIcon(icons.icon("tools"))
        more.setIconSize(QSize(22, 22))
        more.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        more.setToolTip("All tools: pin more to this bar with a right-click")
        more.clicked.connect(lambda: self.show_all_tools(focus=True))
        put(more)
        return self.rail_actions

    # ---- tool strip ------------------------------------------------------------
    def tool_changed(self, *_):
        if self.name not in WITH_RAIL:
            return
        v = getattr(self.win, "_view", None)
        tool = getattr(v, "tool", None) if v is not None else None
        key = (id(v), tool, getattr(v, "count_group", None))
        if key == self._last_tool:
            return
        self._last_tool = key
        self.fill_strip(tool, v)

    def _swap(self, bar, attr, new):
        """Put a freshly built widget in a bar in place of the old one.
        Never QToolBar.clear(): in PySide it also invalidates the Python
        side of shared menu actions that were on the bar (Grok F3), and it
        leaves the old widgets and actions alive (F2)."""
        old_act = getattr(self, attr + "_act", None)
        old = getattr(self, attr, None)
        if old_act is not None:
            bar.removeAction(old_act)
            old_act.deleteLater()        # removeAction alone leaves it alive
        if old is not None:
            old.hide()
            old.deleteLater()
        setattr(self, attr, new)
        setattr(self, attr + "_act", bar.addWidget(new) if new else None)

    def _hold_page(self):
        """The drawing must not jump when the strip comes or goes: note
        where the page sits on screen now, and scroll it back there once
        the window has re-laid out (open item: "page jump when the tool
        strip appears")."""
        tab = self.win.tabs.currentWidget() if hasattr(self.win, "tabs") \
            else None
        sb = getattr(tab, "verticalScrollBar", lambda: None)()
        view = getattr(tab, "view", None)
        if sb is None or view is None:
            return lambda: None
        y0 = view.mapToGlobal(QPoint(0, 0)).y()

        def restore():
            try:
                dy = view.mapToGlobal(QPoint(0, 0)).y() - y0
                if dy:
                    sb.setValue(sb.value() + dy)
            except RuntimeError:
                pass                         # the tab closed meanwhile
        return restore

    def _strip_visible(self, on):
        if (not self.strip.isHidden()) == on:
            return
        restore = self._hold_page()
        self.strip.setVisible(on)
        lay = self.win.layout()
        if lay is not None:
            lay.activate()               # re-lay out now, not later
        restore()
        QTimer.singleShot(0, restore)    # and again after Qt settles

    def fill_strip(self, tool, view=None):
        from .viewer import TOOLS
        bar = self.strip
        if tool is None or tool not in TOOLS:
            self._swap(bar, "_strip_box", None)
            self._strip_visible(False)
            return False
        name, kind = TOOLS[tool]
        box = QWidget()
        box.setObjectName("StripBox")
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        if icons.has(tool):
            ic = QLabel()
            ic.setPixmap(icons.icon(tool).pixmap(16, 16))
            row.addWidget(ic)
        title = QLabel(f"<b>{name}</b>")
        title.setObjectName("StripTitle")
        row.addWidget(title)
        hint = HINTS.get(kind, "")
        if tool == "count" and view is not None and view.count_group:
            hint = f"Counting <b>{view.count_group}</b>: click each one."
        if hint:
            h = QLabel(hint)
            h.setObjectName("StripHint")
            row.addWidget(h)
        opts = []
        if tool.startswith("measure_") or tool in ("count", "trace_length",
                                                  "auto_area", "calibrate",
                                                  "trace_outline"):
            opts += [n for n in MEASURE_OPTIONS
                     if not (tool == "calibrate" and n.startswith("Calibrate"))]
            if tool == "trace_outline":
                opts.append("Trace Outline: Follow Drawn Lines")
            if view is not None and tool != "calibrate":
                try:
                    sc = view.scale()
                except Exception:
                    sc = None
                lab = QLabel("Scale set" if sc else "No scale on this page")
                lab.setObjectName("StripHint" if sc else "StripWarn")
                row.addWidget(lab)
        if tool.startswith("add_") or tool in ("arrow", "legend"):
            opts += MARKUP_OPTIONS
            if tool in ("add_rect", "add_ellipse", "add_cloud", "add_polygon"):
                opts += AREA_OPTIONS
        if tool == "count":
            again = QToolButton()
            again.setObjectName("StripOption")
            again.setText("Change What I'm Counting…")
            again.clicked.connect(lambda: self.win.set_tool("count"))
            row.addWidget(again)
        for n in opts:
            a = self._find(n)
            if a is not None:            # a button for the shared action;
                b = StripButton(a)       # the action itself stays put
                row.addWidget(b)
        row.addStretch(1)
        done = QPushButton("Done  (Esc)")
        done.setObjectName("StripDone")
        done.clicked.connect(lambda: self.win.set_tool(None))
        row.addWidget(done)
        box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._swap(bar, "_strip_box", box)
        self._strip_visible(True)
        return True

    # ---- switching -------------------------------------------------------------
    def _build_layout_menu(self):
        m = QMenu("Layout", self.win)
        g = QActionGroup(m)
        self.layout_actions = {}
        for n in LAYOUTS:
            a = m.addAction(LAYOUT_NAMES[n])
            a.setCheckable(True)
            a.triggered.connect(lambda _c=False, n=n: self.set_layout(n))
            g.addAction(a)
            self.layout_actions[n] = a
        for host in (getattr(self.win, "_view_menu_bar", None),
                     getattr(self.win, "_file_menu", None)):
            if host is not None:
                host.addMenu(m)
        return m

    def bars(self):
        return {"ribbon": getattr(self.win, "_ribbon_bar", None),
                "simple": getattr(getattr(self.win, "simple_menu", None),
                                  "holder", None)}

    def set_layout(self, name, save=True):
        if name not in LAYOUTS:
            raise ValueError(f"no layout {name!r}")
        before, came_from = self.name, self.before_simple
        if name == "simple" and before in ("modern", "ribbon"):
            self.before_simple = before        # Simple Menus off goes back
        self.name = name
        self._switching = True
        win = self.win
        was_max = _maximized(win)
        was_size = win.size()
        try:
            modern = name == "modern"
            left = name in WITH_RAIL           # rail, All Tools, tool strip
            sm = getattr(self.win, "simple_menu", None)
            rb = self.bars()["ribbon"]
            # hide the outgoing bar before showing the new one: for a moment
            # both shared the top row and Qt widened the window to fit them
            # side by side (2,529 px) and never shrank it back (Oct 18)
            if rb is not None and name != "ribbon":
                rb.hide()
            if not modern:
                self.top.hide()
            if not left:
                self.rail.hide()
                self.dock.hide()
                self.strip.hide()
            if sm is not None and name != "simple":
                sm.set_on(False, _from_layouts=True)
            if sm is not None and name == "simple":
                sm.set_on(True, _from_layouts=True)
            if rb is not None and name == "ribbon":
                rb.show()
            if modern:
                self.top.show()
            self.rail.setVisible(left)
            self.dock_action.setVisible(left)
            self.all_tools_action.setEnabled(left)
            if not left:
                self.dock.hide()
                self.strip.hide()
                self._poll.stop()
            else:
                self._last_tool = object()
                self.tool_changed()
                self._poll.start()
                # the All Tools panel starts open, in front (Jon, Oct 18),
                # until it's closed
                if settings.get("all_tools_open", True):
                    self.show_all_tools()
            self.layout_actions[name].setChecked(True)
        except Exception:
            # what's on screen is still the old layout: say so (Grok N6)
            self.name, self.before_simple = before, came_from
            raise
        finally:
            self._switching = False
        if not was_max and win.isVisible():
            # bars and panels showing for a moment can push the window
            # wider; once the switch is done, go back to the size it was
            lay_ = win.layout()
            if lay_ is not None:
                lay_.activate()
            need = win.minimumSizeHint()
            w = max(was_size.width(), need.width())
            h = max(was_size.height(), need.height())
            if win.width() > w or win.height() > h:
                win.resize(min(win.width(), w), min(win.height(), h))
        fit_on_screen(win, was_max)
        if save:                       # only once the switch has happened
            settings.set("layout", name)
        return name

    def hide_orphan_tab_bars(self):
        """Qt can leave the tab strip of a panel stack on screen after
        every panel in it is closed (the bottom panels start closed), where
        it sits over the left panel's own tabs. Hide those; Qt shows a
        strip again when one of its panels opens."""
        from PySide6.QtWidgets import QTabBar
        w = self.win
        shown = {d.windowTitle() for d in w.findChildren(QDockWidget)
                 if d.isVisible()}
        hidden = 0
        for bar in w.findChildren(QTabBar):
            if bar.parent() is not w or not bar.isVisible():
                continue
            titles = [bar.tabText(i) for i in range(bar.count())]
            if not any(t in shown for t in titles):
                bar.hide()
                hidden += 1
        return hidden

    def active_bar(self):
        if self.name == "modern":
            return self.top
        return self.bars().get(self.name)


class AllToolsPane(QWidget):
    """Every command by category, Acrobat-style: type to filter, click to
    run, right-click to pin to the tool rail."""

    def __init__(self, lay):
        super().__init__()
        self.lay = lay
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(6)
        self.search = QLineEdit()
        self.search.setObjectName("AllToolsSearch")
        self.search.setPlaceholderText("Find a tool…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._run_first)
        self.search.installEventFilter(self)
        v.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setObjectName("AllToolsTree")
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(10)
        self.tree.setUniformRowHeights(True)     # fast to lay out and restyle
        self.tree.setIconSize(QSize(18, 18))
        self.tree.setFrameShape(QFrame.NoFrame)
        self.tree.itemClicked.connect(self._clicked)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        v.addWidget(self.tree, 1)
        tip = QLabel("Click a tool to use it. Right-click to pin it to "
                     "the bar on the left.")
        tip.setObjectName("StripHint")
        tip.setWordWrap(True)
        v.addWidget(tip)
        self._acts = []
        self._items_of = {}
        self._watched = set()
        self._filled = False

    def eventFilter(self, obj, e):
        """Esc in the filter box: clear it, then hand the keyboard back to
        the drawing (so tool keys work again)."""
        from PySide6.QtCore import QEvent
        if obj is self.search and e.type() == QEvent.KeyPress \
                and e.key() == Qt.Key_Escape:
            if self.search.text():
                self.search.clear()
            else:
                self.give_back_keyboard()
            return True
        return super().eventFilter(obj, e)

    def give_back_keyboard(self):
        v = getattr(self.lay.win, "_view", None)
        (v if v is not None else self.lay.win).setFocus()

    def categories(self):
        """[(category, icon, [(group, [actions])])], every command once:
        the simple-menu tree first, then what's left by menu."""
        from .simple_menu import TABS, TREE
        lay = self.lay
        seen = set()
        out = []
        for tab in TABS:
            groups = []
            for t, group, names, _flag in TREE:
                if t != tab:
                    continue
                acts = []
                for n in names:
                    a = lay._find(n)
                    if a is not None and id(a) not in seen:
                        seen.add(id(a))
                        acts.append(a)
                if acts:
                    groups.append((group, acts))
            if groups:
                out.append((tab, CATEGORY_ICONS.get(tab), groups))
        from .ribbon import all_actions
        rest = {}
        order = []
        for path, a in all_actions(lay.win.menuBar()):
            if id(a) in seen or not clean(a.text()):
                continue
            seen.add(id(a))
            parts = path.split(" › ")
            top = parts[0]
            sub = parts[1] if len(parts) > 2 else ""
            if top not in rest:
                rest[top] = {}
                order.append(top)
            rest[top].setdefault(sub, []).append(a)
        # every side/bottom panel (the ribbon has some, e.g. Sets, that no
        # menu lists - round-2 review)
        panels = []
        for d in lay.win.findChildren(QDockWidget):
            a = d.toggleViewAction()
            if id(a) in seen or not clean(a.text()):
                continue
            seen.add(id(a))
            panels.append(a)
        if panels:
            rest["Panels"] = {"": sorted(panels,
                                         key=lambda a: clean(a.text()))}
            order.append("Panels")
        cats = {name: groups for name, _icon, groups in out}
        for top in order:
            groups = [(sub or "More", acts) for sub, acts in rest[top].items()]
            home = MERGE.get(top)
            if home in cats:                  # no second "Takeoff" heading
                cats[home].extend((f"More {top.lower()}" if g == "More"
                                   else g, acts) for g, acts in groups)
                continue
            groups = [("" if g == "More" else g, acts) for g, acts in groups]
            icon = CATEGORY_ICONS.get(top)
            if icon is None:
                first = next((a for _g, acts in groups for a in acts
                              if isinstance(a.data(), str)
                              and icons.has(a.data())), None)
                icon = first.data() if first is not None else "list"
            out.append((top, icon, groups))
        return out

    def _sync_enabled(self, a):
        """An action was enabled or disabled (a drawing opened or closed):
        grey its rows to match, without rebuilding the list."""
        for it in self._items_of.get(a, []):
            try:
                if it.isDisabled() == a.isEnabled():
                    it.setDisabled(not a.isEnabled())
            except RuntimeError:          # row deleted by a refill
                pass

    def fill(self):
        self.tree.clear()
        self._acts = []
        self._items_of = {}
        bold = QFont()
        bold.setBold(True)
        small = QFont()
        small.setPointSizeF(max(7.0, small.pointSizeF() - 1))
        for cat, icon, groups in self.categories():
            c = QTreeWidgetItem([cat])
            c.setFont(0, bold)
            c.setFlags(Qt.ItemIsEnabled)
            if icon and icons.has(icon):
                c.setIcon(0, icons.icon(icon))
            self.tree.addTopLevelItem(c)
            for group, acts in groups:
                parent = c
                if group and len(groups) > 1:
                    g = QTreeWidgetItem([group.upper()])
                    g.setFont(0, small)
                    g.setFlags(Qt.ItemIsEnabled)
                    g.setForeground(0, self.palette().placeholderText())
                    c.addChild(g)
                    parent = g
                for a in acts:
                    it = QTreeWidgetItem([clean(a.text())])
                    it.setData(0, Qt.UserRole, len(self._acts))
                    self._acts.append(a)
                    if not a.icon().isNull():
                        it.setIcon(0, a.icon())
                    it.setToolTip(0, self._tip(a))
                    it.setDisabled(not a.isEnabled())
                    self._items_of.setdefault(a, []).append(it)
                    if a not in self._watched:          # greys in step
                        self._watched.add(a)        # (the action, not id():
                        #                             an id can be reused)
                        a.changed.connect(
                            lambda a=a: self._sync_enabled(a))
                    parent.addChild(it)
                    if parent is not c:
                        parent.setExpanded(True)
        self._filled = True
        self._filter(self.search.text())

    def _tip(self, a):
        key = a.shortcut().toString(QKeySequence.NativeText)
        pin = "  · pinned" if self.lay.is_pinned(a) else ""
        return (a.toolTip() or clean(a.text())) + \
            (f"  ({key})" if key else "") + pin

    def refresh_pins(self, a=None):
        """After a pin or unpin: update the tooltips in place, keeping the
        list's scroll position, open categories and selection (no 600-row
        rebuild for a right-click)."""
        for act, rows in self._items_of.items():
            if a is not None and act is not a:
                continue
            for it in rows:
                try:
                    it.setToolTip(0, self._tip(act))
                except RuntimeError:
                    pass

    def fill_soon(self):
        """Fill once the window is up (start-up opens the panel; building
        ~600 rows shouldn't delay the first paint)."""
        if not self._filled and not getattr(self, "_fill_queued", False):
            self._fill_queued = True
            QTimer.singleShot(50, self._fill_queued_now)   # after 1st paint

    def _fill_queued_now(self):
        self._fill_queued = False
        if not self._filled:
            self.fill()

    def actions_listed(self):
        if not self._filled:
            self.fill()
        return list(self._acts)

    def _items(self, item=None):
        root = item or self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            c = root.child(i)
            yield c
            yield from self._items(c)

    def _filter(self, text):
        t = text.lower().strip()
        for i in range(self.tree.topLevelItemCount()):
            self._filter_item(self.tree.topLevelItem(i), t)

    def _filter_item(self, item, t):
        """Hide what doesn't match; a matching category or group shows all
        its tools. Returns whether anything under it shows."""
        if item.data(0, Qt.UserRole) is not None:          # a command
            show = not t or t in item.text(0).lower()
            item.setHidden(not show)
            return show
        whole = bool(t) and t in item.text(0).lower()
        any_ = False
        for j in range(item.childCount()):
            c = item.child(j)
            if whole:
                self._filter_item(c, "")
                any_ = True
            else:
                any_ |= self._filter_item(c, t)
        item.setHidden(bool(t) and not any_)
        if t:
            item.setExpanded(any_)
        elif item.parent() is None:
            item.setExpanded(False)
        return any_ or not t

    def visible_actions(self):
        return [self._acts[it.data(0, Qt.UserRole)] for it in self._items()
                if it.data(0, Qt.UserRole) is not None and not it.isHidden()
                and not (it.parent() and it.parent().isHidden())]

    def _run(self, a):
        if a is not None and a.isEnabled():
            a.trigger()
            return True
        return False

    def _clicked(self, item, _col):
        i = item.data(0, Qt.UserRole)
        if i is None:
            item.setExpanded(not item.isExpanded())
            return
        self._run(self._acts[i])

    def _run_first(self):
        acts = [a for a in self.visible_actions() if a.isEnabled()]
        if self.search.text().strip() and acts:
            self._run(acts[0])

    def _menu(self, pos):
        item = self.tree.itemAt(pos)
        i = item.data(0, Qt.UserRole) if item is not None else None
        if i is None:
            return
        a = self._acts[i]
        m = QMenu(self)
        if self.lay.is_pinned(a):
            m.addAction("Unpin From the Tool Bar",
                        lambda: (self.lay.set_pinned(a, False),
                                 self.refresh_pins(a)))
        else:
            m.addAction("Pin to the Tool Bar",
                        lambda: (self.lay.set_pinned(a, True),
                                 self.refresh_pins(a)))
        m.exec(self.tree.viewport().mapToGlobal(pos))


def install(win):
    win.layouts = Layouts(win)
    return win.layouts
