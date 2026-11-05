"""The ribbon (tabs of grouped commands) and Ctrl+K command search.

The ribbon holds the same QActions as the menus, so checked and enabled
states, shortcuts and tooltips stay in step everywhere.
"""
import re

from PySide6.QtCore import QEvent, QSize, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QKeySequence, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMenu, QScrollArea,
    QSizePolicy, QStackedWidget, QStyledItemDelegate, QToolButton,
    QVBoxLayout, QWidget)

from . import icons, settings, theme


def clean(text):
    """Menu text without &, ellipsis or trailing dots."""
    t = (text or "").replace("&&", "\0").replace("&", "").replace("\0", "&")
    return t.replace("…", "").rstrip(". ").strip()


# ---- ribbon --------------------------------------------------------------------

class RibbonButton(QToolButton):
    def __init__(self, action, large=True, label=None, parent=None):
        super().__init__(parent)
        self.setObjectName("RibbonButton")
        self.setDefaultAction(action)
        # "&" in a button's text marks a keyboard accelerator: double it so
        # "Header & Footer" shows its ampersand
        # iconText() has the menu's "&&" already turned into "&"
        self._large = large
        base = label or (action.iconText() or clean(action.text()))
        self._label = base.replace("…", "").rstrip(". ").replace("&", "&&")
        self.setText(self._label)
        if large:
            self.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            self.setIconSize(QSize(26, 26))
            self.setFixedHeight(70)
            self.setMinimumWidth(max(54, self.sizeHint().width()))
        else:
            self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            self.setIconSize(QSize(16, 16))
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.setMinimumWidth(self.sizeHint().width())
        tip = action.toolTip() or self._label
        key = action.shortcut().toString(QKeySequence.NativeText)
        if key and key not in tip:
            tip = f"{tip}  ({key})"
        self.setToolTip(tip)
        action.changed.connect(self._relabel)

    def _relabel(self):
        # setDefaultAction copies the action's text back; keep ours
        if self.text() != self._label:
            self.setText(self._label)

    def _full_width(self):
        """Width that shows the whole label in the button's current font
        and style (the theme's font, Windows text size): the width taken
        when the button was made came before the style sheet, so labels
        were cut to "Dat...ase" (Jon, Oct 22)."""
        self.ensurePolished()
        w = super().sizeHint().width()
        text = self.fontMetrics().horizontalAdvance(self.text().replace(
            "&&", "&")) + 16
        if self.toolButtonStyle() == Qt.ToolButtonTextBesideIcon:
            text += self.iconSize().width() + 8
        if self.menu() is not None:
            text += 14
        return max(54 if self._large else 0, w, text)

    def _fit(self):
        """Raise the minimum width to the whole label (never lower it)."""
        need = self._full_width()
        if self.minimumWidth() < need:
            self.setMinimumWidth(need)

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() in (QEvent.FontChange, QEvent.StyleChange):
            self._fit()

    def showEvent(self, e):
        self._fit()
        super().showEvent(e)


class RibbonGroup(QWidget):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName("RibbonGroup")
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 2, 4, 2)
        v.setSpacing(2)
        self.row = QHBoxLayout()
        self.row.setSpacing(2)
        self.row.setAlignment(Qt.AlignTop)
        v.addLayout(self.row, 1)
        lab = QLabel(title)
        lab.setObjectName("RibbonGroupLabel")
        lab.setAlignment(Qt.AlignHCenter)
        v.addWidget(lab)
        self.buttons = []

    def large(self, action, label=None, menu=None):
        b = RibbonButton(action, True, label)
        if menu is not None:
            b.setMenu(menu)
            b.setPopupMode(QToolButton.MenuButtonPopup)
        # every box sits at the top of its group, so all groups line up
        # (Jon, Oct 20: some groups' buttons sat lower than others)
        self.row.addWidget(b, 0, Qt.AlignTop)
        self.buttons.append(b)
        return b

    def small(self, actions, labels=None):
        """A column of up to three small buttons."""
        col = QVBoxLayout()
        col.setSpacing(1)
        for i, a in enumerate(actions):
            b = RibbonButton(a, False, (labels or {}).get(i))
            col.addWidget(b)
            self.buttons.append(b)
        col.addStretch(1)
        self.row.addLayout(col)

    def widget(self, w):
        self.row.addWidget(w, 0, Qt.AlignTop)
        return w


SCROLL_H = 8


class RibbonPage(QScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setObjectName("RibbonBody")
        self.lay = QHBoxLayout(inner)
        self.lay.setContentsMargins(6, 4, 6, 2)
        self.lay.setSpacing(4)
        self.lay.addStretch(1)
        self.setWidget(inner)
        self.groups = {}
        # a slim scrollbar in its own reserved strip, so a wide tab (the
        # Takeoff tab on a laptop screen) scrolls instead of having its
        # group labels cut off underneath the bar (open item)
        self.horizontalScrollBar().setFixedHeight(SCROLL_H)
        # and arrows at the edges say there's more (GUI user test r42 F04:
        # the Estimate tab's export buttons were cut off at the right and
        # the slim scrollbar wasn't noticed)
        self.more_left = self._arrow("‹", -1)
        self.more_right = self._arrow("›", 1)
        sb = self.horizontalScrollBar()
        sb.rangeChanged.connect(lambda *_a: self._place_arrows())
        sb.valueChanged.connect(lambda *_a: self._place_arrows())

    def _arrow(self, text, way):
        b = QToolButton(self)
        b.setObjectName("RibbonMore")
        b.setText(text)
        b.setToolTip("More buttons on this tab" if way > 0 else
                     "Back to the start of this tab")
        b.setAutoRaise(True)
        f = b.font()
        f.setPointSizeF(f.pointSizeF() + 6)
        f.setBold(True)
        b.setFont(f)
        b.clicked.connect(lambda _c=False, w=way: self.scroll_by_page(w))
        b.hide()
        return b

    def scroll_by_page(self, way):
        sb = self.horizontalScrollBar()
        sb.setValue(sb.value() + way * max(80, int(self.viewport().width()
                                                      * 0.8)))

    def _place_arrows(self):
        sb = self.horizontalScrollBar()
        h = max(24, self.viewport().height() - 4)
        w = 26
        self.more_left.setGeometry(0, 2, w, h)
        self.more_right.setGeometry(self.width() - w, 2, w, h)
        self.more_left.setVisible(sb.maximum() > 0 and sb.value() > 0)
        self.more_right.setVisible(sb.maximum() > 0 and
                                   sb.value() < sb.maximum())
        self.more_left.raise_()
        self.more_right.raise_()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._place_arrows()

    def minimumSizeHint(self):
        """A wide tab scrolls (the strip below) instead of making the
        window wider: Qt's scroll area otherwise asks for its contents'
        width, so each new ribbon group raised the window's minimum."""
        h = super().minimumSizeHint()
        return QSize(160, h.height())

    def sizeHint(self):
        """Not the whole tab's width either: the ribbon's toolbar takes its
        widgets' size hints as the window's minimum, so full-width labels
        (Oct 22) would have made the window ~2,000 px wide. The page fills
        whatever width the window has and scrolls the rest."""
        h = super().sizeHint()
        return QSize(min(h.width(), 640), h.height())

    def wheelEvent(self, ev):
        """The mouse wheel scrolls a wide tab sideways."""
        sb = self.horizontalScrollBar()
        if sb.maximum() > 0:
            d = ev.angleDelta()
            step = d.y() if abs(d.y()) >= abs(d.x()) else d.x()
            sb.setValue(sb.value() - step)
            ev.accept()
            return
        super().wheelEvent(ev)

    def group(self, title):
        if title in self.groups:
            return self.groups[title]
        if self.groups:
            sep = QFrame()
            sep.setObjectName("RibbonSep")
            sep.setFixedWidth(1)
            self.lay.insertWidget(self.lay.count() - 1, sep)
        g = RibbonGroup(title)
        self.lay.insertWidget(self.lay.count() - 1, g)
        self.groups[title] = g
        return g


class _TabStrip(QScrollArea):
    """The row of ribbon tabs: as wide as the tabs when there's room,
    scrollable (wheel) when there isn't."""

    def __init__(self):
        super().__init__()
        self.setObjectName("RibbonTabs")
        self.setFrameShape(QFrame.NoFrame)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setObjectName("RibbonHeader")
        self.row = QHBoxLayout(inner)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(2)
        self.row.addStretch(1)
        self.setWidget(inner)

    def minimumSizeHint(self):
        h = self.widget().sizeHint().height()
        return QSize(160, h)

    def sizeHint(self):
        return self.widget().sizeHint()

    def wheelEvent(self, ev):
        sb = self.horizontalScrollBar()
        if sb.maximum() > 0:
            d = ev.angleDelta()
            sb.setValue(sb.value() - (d.y() if abs(d.y()) >= abs(d.x())
                                      else d.x()))
            ev.accept()
            return
        super().wheelEvent(ev)


class Ribbon(QWidget):
    search_requested = Signal()
    theme_picked = Signal(str)

    HEIGHT = 114

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Ribbon")
        self.setAttribute(Qt.WA_StyledBackground, True)
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 6, 8, 0)
        v.setSpacing(4)
        head = QWidget()
        head.setObjectName("RibbonHeader")
        self.head = QHBoxLayout(head)
        self.head.setContentsMargins(0, 0, 0, 0)
        self.head.setSpacing(2)
        self.app_button = QToolButton()
        self.app_button.setObjectName("AppButton")
        self.app_button.setText("File")
        self.app_button.setPopupMode(QToolButton.InstantPopup)
        self.head.addWidget(self.app_button)
        self.head.addSpacing(8)
        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)
        # the tabs sit in a strip that can get narrower than all of them:
        # on a small screen (or with large fonts) the strip scrolls with
        # the mouse wheel instead of making the whole window wider
        self.tab_strip = _TabStrip()
        self.tab_row = self.tab_strip.row
        self.head.addWidget(self.tab_strip, 1)
        self.search = QToolButton()
        self.search.setObjectName("CommandSearch")
        self.search.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.search.setIcon(icons.icon("find"))
        self.search.setText("Search commands…   Ctrl+K")
        self.search.setMinimumWidth(200)      # room for the Module tab
        self.search.clicked.connect(self.search_requested)
        self.head.addWidget(self.search)
        self.help_button = QToolButton()
        self.help_button.setObjectName("IconButton")
        self.help_button.setText("?")
        self.help_button.setToolTip("Help: tutorials, shortcuts, about (F1)")
        self.help_button.setPopupMode(QToolButton.InstantPopup)
        f = self.help_button.font()
        f.setBold(True)
        f.setPointSizeF(f.pointSizeF() + 2)
        self.help_button.setFont(f)
        self.head.addWidget(self.help_button)
        self.theme_button = QToolButton()
        self.theme_button.setObjectName("IconButton")
        self.theme_button.setToolTip("Theme: System, Dark or Light")
        self.theme_button.setPopupMode(QToolButton.InstantPopup)
        self.theme_button.setIconSize(QSize(18, 18))
        m = QMenu(self.theme_button)
        grp = QActionGroup(m)
        self.theme_actions = {}
        for key, label in (("system", "Follow Windows"), ("dark", "Dark"),
                           ("light", "Light")):
            a = m.addAction(label)
            a.setCheckable(True)
            a.setChecked(theme.mode() == key)
            a.triggered.connect(lambda _c=False, k=key: self.theme_picked.emit(k))
            grp.addAction(a)
            self.theme_actions[key] = a
        self.theme_button.setMenu(m)
        self.head.addWidget(self.theme_button)
        self.collapse = QToolButton()
        self.collapse.setObjectName("IconButton")
        self.collapse.setToolTip("Collapse or expand the ribbon "
                                 "(or double-click a tab)")
        self.collapse.setText("⌃")
        self.collapse.clicked.connect(lambda: self.set_collapsed(
            not self.collapsed))
        self.head.addWidget(self.collapse)
        v.addWidget(head)
        self.stack = QStackedWidget()
        self.stack.setFixedHeight(self.HEIGHT + SCROLL_H)
        v.addWidget(self.stack)
        self.pages = {}
        self.collapsed = False
        self.retint()
        theme.hub.changed.connect(self.retint)

    def retint(self, *_):
        self.theme_button.setIcon(icons.icon("moon" if theme.is_dark()
                                             else "sun"))
        for k, a in self.theme_actions.items():
            a.setChecked(theme.mode() == k)
        # icons draw in the theme colours of the moment: the style sheet
        # change repaints every button, nothing to reset here

    def page(self, name):
        if name in self.pages:
            return self.pages[name]
        p = RibbonPage()
        self.stack.addWidget(p)
        self.pages[name] = p
        b = QToolButton()
        b.setObjectName("RibbonTab")
        b.setText(name.replace("&", "&&"))      # "Markup & Review", not "_R"
        b.setCheckable(True)
        b.installEventFilter(self)
        b.clicked.connect(lambda _c=False, n=name: self.show_page(n))
        self.tab_group.addButton(b)
        self.tab_row.insertWidget(self.tab_row.count() - 1, b)
        p.tab_button = b
        if len(self.pages) == 1:
            b.setChecked(True)
        return p

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.MouseButtonDblClick:
            self.set_collapsed(not self.collapsed)
            return True
        return super().eventFilter(obj, ev)

    def show_page(self, name):
        p = self.pages[name]
        p.tab_button.setChecked(True)
        self.tab_strip.ensureWidgetVisible(p.tab_button, 8, 0)
        self.stack.setCurrentWidget(p)
        if self.collapsed:
            self.set_collapsed(False)
        settings.set("ribbon_tab", name)

    def current(self):
        w = self.stack.currentWidget()
        return next((n for n, p in self.pages.items() if p is w), None)

    def set_collapsed(self, on):
        self.collapsed = bool(on)
        self.stack.setVisible(not on)
        self.collapse.setText("⌄" if on else "⌃")
        settings.set("ribbon_collapsed", self.collapsed)


# ---- command search ---------------------------------------------------------------

def all_actions(menubar):
    """[(path, action)] for every command in the menus, e.g.
    ("Takeoff › Bid Leveling", action)."""
    out, seen = [], set()

    def walk(menu, path):
        for a in menu.actions():
            if a.isSeparator():
                continue
            if a.menu():
                walk(a.menu(), path + [clean(a.text())])
                continue
            if id(a) in seen or not a.text() or a.property("palette_hide"):
                continue                 # (a second copy of a command)
            seen.add(id(a))
            out.append((" › ".join(path), a))

    for top in menubar.actions():
        if top.menu():
            walk(top.menu(), [clean(top.text())])
    return out


def score(query, label, path=""):
    """0 = no match. Every word must appear in the name (a word start
    scores higher) or the menu path (scores less); last resort, the
    letters in order in the name."""
    q = query.lower().split()
    lab, pth = label.lower(), path.lower()
    if not q:
        return 1
    s = 0.0
    for w in q:
        i = lab.find(w)
        if i >= 0:
            s += 4 if i == 0 else 3 if not lab[i - 1].isalnum() else 1.5
            continue
        j = pth.find(w)
        if j >= 0 and (j == 0 or not pth[j - 1].isalnum()):
            s += 0.7
            continue
        return 0
    if lab.startswith(query.lower()):
        s += 3
    return s + 1


def _subseq(q, t):
    """Letters of q in order in t: tighter runs score higher (0 = none)."""
    q = q.replace(" ", "")
    best = 0
    for start in range(len(t)):
        if not q or t[start] != q[0]:
            continue
        i, pos = start, 0
        for c in q:
            i = t.find(c, i if pos == 0 else i + 1)
            if i < 0:
                break
            pos += 1
        else:
            best = max(best, 1.0 / (1 + i - start - len(q) + 1))
    return best


class _Delegate(QStyledItemDelegate):
    def paint(self, p, opt, index):
        super().paint(p, opt, index)
        right = index.data(Qt.UserRole + 1) or ""
        if right:
            p.save()
            p.setPen(theme.color("muted"))
            r = opt.rect.adjusted(0, 0, -12, 0)
            p.drawText(r, Qt.AlignRight | Qt.AlignVCenter, right)
            p.restore()

    def sizeHint(self, opt, index):
        s = super().sizeHint(opt, index)
        return QSize(s.width(), max(s.height(), 32))


class CommandPalette(QDialog):
    """Ctrl+K: type to find any command, Enter to run it."""

    def __init__(self, menubar, parent=None, extra=(), reveal=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.reveal = reveal          # Shift+Enter: show me where it lives
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.setObjectName("Palette")
        self.setMinimumSize(620, 420)
        self.items = list(extra) + all_actions(menubar)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.input = QLineEdit()
        self.input.setObjectName("PaletteInput")
        self.input.setPlaceholderText(
            "Type a command, sheet (A2.1), takeoff item, tool or RFI  ·  "
            "Shift+Enter shows where a command lives")
        self.input.textChanged.connect(self.refilter)
        self.input.installEventFilter(self)
        v.addWidget(self.input)
        self.list = QListWidget()
        self.list.setObjectName("PaletteList")
        self.list.setItemDelegate(_Delegate(self.list))
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.itemActivated.connect(self.run)
        self.list.itemClicked.connect(self.run)
        v.addWidget(self.list, 1)
        self.chosen = None
        self.refilter("")

    def refilter(self, text):
        recent = settings.get("recent_commands", []) or []
        rows = []
        for path, a in self.items:
            if not text and a.property("palette_extra"):
                continue            # sheets, items, RFIs: only when typed
            label = clean(a.text())
            words = a.property("keywords") or ""   # search words (aliases)
            s = score(text, label, f"{path} {words}".strip()) if text else (
                10 + len(recent) - recent.index(label) if label in recent
                else 1)
            if s and (a.isEnabled() or text):
                rows.append((-s, label, path, a))
        if text and not rows:            # nothing has the words: letters
            for path, a in self.items:     # in order ("ovly" -> Overlay)
                label = clean(a.text())
                s = _subseq(text.lower(), label.lower())
                if s:
                    rows.append((-s, label, path, a))
        rows.sort(key=lambda r: (r[0], r[1]))
        self.list.clear()
        for _s, label, path, a in rows[:80]:
            it = QListWidgetItem(a.icon(), label)
            key = a.shortcut().toString(QKeySequence.NativeText)
            it.setData(Qt.UserRole, a)
            it.setData(Qt.UserRole + 1, "   ".join(x for x in (path, key)
                                                    if x))
            if not a.isEnabled():
                it.setFlags(it.flags() & ~Qt.ItemIsEnabled)
            self.list.addItem(it)
        for i in range(self.list.count()):
            if self.list.item(i).flags() & Qt.ItemIsEnabled:
                self.list.setCurrentRow(i)
                break

    def eventFilter(self, obj, ev):
        if obj is self.input and ev.type() == QEvent.KeyPress:
            k = ev.key()
            if k in (Qt.Key_Down, Qt.Key_Up):
                r = self.list.currentRow() + (1 if k == Qt.Key_Down else -1)
                self.list.setCurrentRow(max(0, min(self.list.count() - 1, r)))
                return True
            if k in (Qt.Key_Return, Qt.Key_Enter):
                it = self.list.currentItem()
                if it and ev.modifiers() & Qt.ShiftModifier and \
                        self.reveal is not None:
                    self.show_where(it)
                elif it:
                    self.run(it)
                return True
            if k == Qt.Key_Escape:
                self.reject()
                return True
        return super().eventFilter(obj, ev)

    def show_where(self, item):
        """Light up the command's ribbon button instead of running it."""
        a = item.data(Qt.UserRole)
        if not a or self.reveal is None:
            return None
        self.accept()
        return self.reveal(a)

    def run(self, item):
        a = item.data(Qt.UserRole)
        if not a or not a.isEnabled():
            return
        self.chosen = a
        label = clean(a.text())
        recent = [x for x in (settings.get("recent_commands", []) or [])
                  if x != label]
        settings.set("recent_commands", [label] + recent[:9])
        self.accept()
        a.trigger()

    def popup(self, anchor):
        w = anchor.window()
        g = w.geometry()
        self.move(g.x() + (g.width() - self.width()) // 2, g.y() + 70)
        self.input.setFocus()
        return self.exec()
