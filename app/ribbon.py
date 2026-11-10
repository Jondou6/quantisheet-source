"""The ribbon (tabs of grouped commands) and Ctrl+K command search.

The ribbon holds the same QActions as the menus, so checked and enabled
states, shortcuts and tooltips stay in step everywhere.
"""
import re

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import (QAction, QActionGroup, QColor, QFont, QKeySequence,
                           QLinearGradient, QPainter, QPen)
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
# One tile colour: a solid teal-green square, lighter at the top, white
# glyph. The fill does not change between light and dark mode. Labels sit
# on the frosted panel (CAPTION_INK / DISABLED_INK).

GREEN_FILL = "#0E6A60"
GLYPH = "#FFFFFF"
GLYPH_STROKE = 3.0          # heavier than the 1.7 menu-icon stroke
# How far the top of the tile lifts toward white. Small enough that a
# white glyph stays at 4.5:1, including after a light hover.
GRADIENT_LIFT = 0.06
HOVER_LIFT = 0.07
FAMILIES = frozenset({
    "file", "edit", "tools", "view", "compare", "markup", "measure",
    "estimate", "civil", "review", "ai", "project", "field", "schedule",
    "ada", "energy", "billing", "pages", "document", "sign", "protect",
    "help", "service",
})
TAB_FAMILY = {
    "Home": "file", "Markup": "markup", "Takeoff": "measure",
    "Estimate": "estimate", "Review": "review", "AI": "ai",
    "Project": "project", "Billing": "billing", "Pages": "pages",
    "Document": "document", "Tools": "tools", "Help": "help",
    "Service": "service", "Module": "project", "Civil": "civil",
    "PDF Management": "document",
}
# group title -> family, when the title means the same thing on every tab
TITLE_FAMILY = {
    "File": "file", "Edit": "edit", "View": "view", "Compare": "compare",
    "Text": "markup", "Shapes": "markup", "Notes": "markup",
    "Style": "markup", "Organize": "markup",
    "Scale": "measure", "Measure": "measure", "Count": "measure",
    "Automatic": "measure", "Site": "measure", "Plan Set": "measure",
    "Roof": "measure", "Selected": "measure",
    "Assemblies": "estimate", "Pricing": "estimate",
    "Calculators": "estimate", "Bidding": "estimate",
    "Contract": "billing", "Changes": "billing", "Payment": "billing",
    "Pages": "pages", "Page Marks": "pages",
    "Content": "document", "Forms": "document", "Standards": "document",
    "Sign": "sign", "E-Sign": "sign", "Protect": "protect",
    "Collaborate": "tools", "Convert": "tools", "Settings": "tools",
    "Learn": "help", "About": "help",
    "Manage": "project", "Sets": "project", "Documents": "project",
    "Check": "project", "Office": "project",
    "Calls": "service", "Agreements": "service", "Logs & Tests": "service",
    "Records": "service", "Quotes": "service",
    "Voice": "ai", "Model": "ai",
}
# (tab, title) wins over TITLE_FAMILY when one title is two kinds of work
EXACT_FAMILY = {
    ("Takeoff", "Output"): "measure",
    ("Estimate", "Output"): "estimate",
    ("Review", "Automate"): "review",
    ("Tools", "Automate"): "tools",
    ("Review", "AI"): "ai",
    ("Review", "AI Review"): "ai",
    ("Review", "RFIs"): "review",
    ("Takeoff", "AI Takeoff"): "ai",
    ("Project", "Field"): "field",
    ("Project", "Schedule"): "schedule",
    ("Project", "ADA"): "ada",
    ("Project", "Energy Code"): "energy",
    ("Tools", "Voice"): "ai",
    ("Home", "Tools"): "tools",
    ("AI", "Takeoff"): "ai",
    ("AI", "Schedule"): "ai",
    ("AI", "Review"): "ai",
    ("Service", "Pricing"): "service",
}


def family_for(tab, title):
    """Colour family for a group's tiles."""
    if title.startswith("Civil"):
        return "civil"
    if tab == "Service":
        return "service"
    if tab == "AI" or title.startswith("AI"):
        return "ai"
    hit = EXACT_FAMILY.get((tab, title))
    if hit:
        return hit
    if title in TITLE_FAMILY:
        return TITLE_FAMILY[title]
    return TAB_FAMILY.get(tab, "tools")


# commands whose menu entry has no icon of its own
GLYPH_OF = {
    "undo history": "history",
    "auto scale (check against dimensions)": "auto_scale",
    "show only this item": "eye",
    "set typical count": "count",
    "bulk edit selected": "edit_text",
    "copy several times": "duplicate",
    "add more to this count": "count",
    "show uncounted copies": "find",
    "add this count to the count library": "book",
    "convert selected to": "sync",
    "take off into assembly": "assembly",
    "add from cost book": "book",
    "quick $/sf estimate": "dollar",
    "revision changes (old → new)": "compare",
    "placeholders & allowances": "budget",
    "escalation to buy date": "trend",
    "export my estimate": "export",
    "estimate from takeoff (all groups)": "estimate",
    "start from master estimate": "book",
    "labor burden & wages": "crew",
    "import prevailing wages (davis-bacon)": "import",
    "export cash flow": "forecast",
    "import owner bid schedule": "import",
    "export priced bid schedule": "export",
    "save bid version": "save",
    "read the energy code online": "link",
    "quantisheet back office": "dollar",
    "document properties": "settings",
    "help center & tutorials": "book",
    "about quantisheet": "info",
    "report an issue": "flag",
    "terms of service": "contract",
    "privacy": "shield",
    "third-party licenses": "book",
}


def _luminance(color):
    def chan(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    return (0.2126 * chan(color.red()) + 0.7152 * chan(color.green())
            + 0.0722 * chan(color.blue()))


def contrast_ratio(a, b):
    la, lb = _luminance(a), _luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def tile_contrast():
    """White-glyph contrast for the green tile. Same in light and dark.

    Keys: fill, top (lighter end of the gradient), hover, pressed, disabled.
    """
    fill = QColor(GREEN_FILL)
    white = QColor("#FFFFFF")
    top = _mix(fill, white, GRADIENT_LIFT)
    hover = _mix(_mix(fill, white, HOVER_LIFT), white, GRADIENT_LIFT)
    pressed = _mix(fill, QColor("#000000"), 0.16)
    disabled = _mix(fill, QColor("#9CA3AF"), 0.35)
    return {
        "fill": contrast_ratio(white, fill),
        "top": contrast_ratio(white, top),
        "hover": contrast_ratio(white, hover),
        "pressed": contrast_ratio(white, pressed),
        "disabled": contrast_ratio(white, disabled),
    }


def _mix(a, b, t):
    return QColor(int(a.red() * (1 - t) + b.red() * t),
                  int(a.green() * (1 - t) + b.green() * t),
                  int(a.blue() * (1 - t) + b.blue() * t))


# label ink on the frosted panel (checked against the panel fill)
CAPTION_INK = {"dark": "#c5c8d0", "light": "#3f4550"}
DISABLED_INK = {"dark": "#a0a6b0", "light": "#5b6472"}


def _ink(which):
    from . import theme
    key = "dark" if theme.is_dark() else "light"
    return QColor(which[key])


class RibbonButton(QToolButton):
    """Coloured rounded-square tile, label centred underneath.

    Every command is this size (the old small column sat its text higher
    than the tiles beside it). Labels wrap to two lines and share the
    bottom of that two-line slot, so a short name lines up with a long one.
    """

    TILE = 34
    STD_W = 78
    RADIUS = 0.22

    def __init__(self, action, large=True, label=None, parent=None):
        super().__init__(parent)
        self.setObjectName("RibbonButton")
        # setDefaultAction can emit changeEvent before the rest of init
        self._large = True
        self._family = "tools"
        self.preview_state = None       # screenshots force a state
        base = label or (action.iconText() or clean(action.text()))
        self._label = base.replace("…", "").rstrip(". ").replace("&", "&&")
        self.setAttribute(Qt.WA_Hover, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAutoRaise(True)
        self.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.setDefaultAction(action)
        self.setText(self._label)
        tip = action.toolTip() or self._label.replace("&&", "&")
        key = action.shortcut().toString(QKeySequence.NativeText)
        if key and key not in tip:
            tip = f"{tip}  ({key})"
        self.setToolTip(tip)
        action.changed.connect(self._relabel)
        self._apply_label_weight()
        self._apply_metrics()

    def _apply_label_weight(self):
        f = self.font()
        f.setWeight(QFont.DemiBold)
        self.setFont(f)

    def set_family(self, name):
        self._family = name if name in FAMILIES else "tools"
        self.update()

    def _relabel(self):
        if self.text() != self._label:
            self.setText(self._label)

    def _plain(self):
        return self._label.replace("&&", "&")

    def _icon_name(self):
        a = self.defaultAction()
        if a is None:
            return "info"
        data = a.data()
        if isinstance(data, str) and icons.has(data):
            return data
        key = clean(a.text()).lower()
        glyph = GLYPH_OF.get(key)
        if glyph and icons.has(glyph):
            return glyph
        named = a.property("qs_icon")
        if named and icons.has(named):
            return named
        return "info"

    def _break(self, text, inner, fm):
        words = text.split()
        if not words:
            return [""]
        lines, cur = [], ""
        for word in words:
            trial = word if not cur else cur + " " + word
            if cur and fm.horizontalAdvance(trial) > inner:
                lines.append(cur)
                cur = word
            else:
                cur = trial
        if cur:
            lines.append(cur)
        return lines

    def _layout_width(self):
        """Standard tile column, grown only until the label fits in two
        lines (nothing is cut with an ellipsis)."""
        self.ensurePolished()
        fm = self.fontMetrics()
        text = self._plain()
        pad = 10
        w = self.STD_W
        limit = max(w, fm.horizontalAdvance(text) + pad)
        while True:
            inner = w - pad
            lines = self._break(text, inner, fm)
            if len(lines) <= 2 and all(
                    fm.horizontalAdvance(line) <= inner for line in lines):
                return w
            if w >= limit:
                return w
            w = min(limit, w + 8)

    def wrapped_lines(self):
        """The one or two lines actually drawn."""
        self.ensurePolished()
        fm = self.fontMetrics()
        inner = max(8, self.width() - 10)
        lines = self._break(self._plain(), inner, fm)
        if len(lines) <= 2:
            return lines
        # a font change between sizing and paint: keep the tail on line 2
        return [lines[0], " ".join(lines[1:])]

    def label_baseline(self):
        """Y of the last label line's baseline inside this button.

        A one-line label sits in the bottom line of the two-line slot, so
        every button in a row shares this baseline."""
        self.ensurePolished()
        fm = self.fontMetrics()
        lh = fm.height()
        top = self.height() - 2 - lh * 2
        return top + lh + fm.ascent()

    def box_height(self):
        fm = self.fontMetrics()
        label = fm.height() * 2 + 2
        return max(74, 4 + self.TILE + 3 + label)

    def _apply_metrics(self):
        self.ensurePolished()
        h = self.box_height()
        w = self._layout_width()
        self.setFixedHeight(h)
        self.setMinimumWidth(w)
        self.setMaximumWidth(w)
        self.updateGeometry()

    def _fit(self):
        if not hasattr(self, "_label"):
            return
        self._apply_metrics()

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() in (QEvent.FontChange, QEvent.StyleChange,
                        QEvent.EnabledChange, QEvent.Polish):
            self._fit()
            self.update()

    def event(self, e):
        if e.type() == QEvent.Polish and getattr(self, "_label", None):
            self._fit()
        return super().event(e)

    def showEvent(self, e):
        self._fit()
        super().showEvent(e)

    def enterEvent(self, e):
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.update()
        super().leaveEvent(e)

    def _states(self):
        forced = self.preview_state
        disabled = forced == "disabled" or (
            forced is None and not self.isEnabled())
        hover = forced == "hover" or (
            forced is None and self.underMouse() and not disabled)
        pressed = forced == "pressed" or (
            forced is None and self.isDown() and not disabled)
        focus = forced == "focus" or (forced is None and self.hasFocus())
        checked = self.isChecked() and not disabled
        return disabled, hover, pressed, focus, checked

    def _colors(self, disabled, hover, pressed, checked=False):
        """(tile fill, white glyph, stroke) . Same green in light and dark."""
        base = QColor(GREEN_FILL)
        ink = QColor(GLYPH)
        if disabled:
            base = _mix(base, QColor("#9CA3AF"), 0.35)
        elif pressed or checked:
            base = _mix(base, QColor("#000000"), 0.16)
        elif hover:
            base = _mix(base, QColor("#FFFFFF"), HOVER_LIFT)
        return base, ink, GLYPH_STROKE

    def _paint_tile(self, p, rect, radius, base, dark):
        """Green fill, lighter at the top, with a thin inner highlight."""
        top = _mix(base, QColor("#FFFFFF"), GRADIENT_LIFT)
        bot = _mix(base, QColor("#000000"), 0.06)
        grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        grad.setColorAt(0, top)
        grad.setColorAt(1, bot)
        p.setPen(Qt.NoPen)
        p.setBrush(grad)
        p.drawRoundedRect(rect, radius, radius)
        shine = QColor(255, 255, 255, 110 if not dark else 70)
        p.setPen(QPen(shine, 1.2))
        p.drawLine(rect.left() + 6, rect.top() + 2,
                   rect.right() - 6, rect.top() + 2)

    def paintEvent(self, _ev):
        from . import theme
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        disabled, hover, pressed, focus, checked = self._states()
        dark = theme.is_dark()
        base, ink, stroke = self._colors(disabled, hover, pressed, checked)
        tile = self.TILE
        x = max(0, (self.width() - tile) // 2)
        y = 4
        if hover and not pressed:
            y -= 1
        rect = QRect(x, y, tile, tile)
        radius = max(4.0, tile * self.RADIUS)
        if pressed and not disabled:
            rect = rect.adjusted(1, 1, -1, -1)
        self._paint_tile(p, rect, radius, base, dark)
        gaccent = ink.name()
        if checked:
            ring = QColor("#ffffff")
            p.setPen(QPen(ring, 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(rect.adjusted(2, 2, -2, -2), radius - 1,
                              radius - 1)
        if focus:
            ring = QColor("#f8fafc") if dark else QColor("#0f172a")
            p.setPen(QPen(ring, 2))
            p.setBrush(Qt.NoBrush)
            outer = rect.adjusted(-4, -4, 4, 4)
            p.drawRoundedRect(outer, radius + 3, radius + 3)
        side = max(12, tile - 14)
        pm = icons.pixmap(self._icon_name(), side, ink.name(), gaccent,
                          stroke)
        p.drawPixmap(rect.x() + (rect.width() - side) // 2,
                     rect.y() + (rect.height() - side) // 2, pm)
        if self.menu() is not None:
            p.setPen(Qt.NoPen)
            p.setBrush(ink)
            cx, cy = rect.right() - 7, rect.bottom() - 6
            p.drawPolygon([QPoint(cx - 3, cy - 1), QPoint(cx + 3, cy - 1),
                           QPoint(cx, cy + 2)])
        fm = self.fontMetrics()
        lines = self.wrapped_lines()
        lh = fm.height()
        slot = lh * 2
        top = self.height() - 2 - slot
        p.setPen(_ink(DISABLED_INK) if disabled else theme.color("text"))
        for i, line in enumerate(lines):
            # bottom of the two-line slot, so one line sits with the
            # second line of a wrapped neighbour
            y0 = top + (2 - len(lines) + i) * lh
            p.drawText(QRect(0, y0, self.width(), lh),
                       Qt.AlignHCenter | Qt.AlignVCenter, line)
        p.end()

    def sizeHint(self):
        return QSize(self._layout_width(), self.box_height())

    def minimumSizeHint(self):
        return self.sizeHint()


class RibbonGroup(QWidget):
    """Frosted panel: tiles on one row, caption centred on the bottom edge."""

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName("RibbonGroup")
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.family = "tools"
        self._title = title
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 6, 8, 4)
        v.setSpacing(1)
        self.row = QHBoxLayout()
        self.row.setSpacing(4)
        self.row.setAlignment(Qt.AlignTop)
        v.addLayout(self.row, 1)
        self.caption = QLabel(title)
        self.caption.setObjectName("RibbonGroupLabel")
        self.caption.setAlignment(Qt.AlignHCenter | Qt.AlignBottom)
        v.addWidget(self.caption)
        self.buttons = []
        self.refresh_caption()

    def set_family(self, name):
        self.family = name if name in FAMILIES else "tools"
        for b in self.buttons:
            b.set_family(self.family)
        self.update()

    def refresh_caption(self):
        c = _ink(CAPTION_INK).name()
        self.caption.setStyleSheet(
            f"color: {c}; background: transparent; font-size: 8pt; "
            "font-weight: 600;")

    def paintEvent(self, _ev):
        from . import theme
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(1, 1, -2, -2)
        if theme.is_dark():
            fill = QColor(255, 255, 255, 18)
            border = QColor(255, 255, 255, 40)
            shine = QColor(255, 255, 255, 46)
        else:
            fill = QColor(255, 255, 255, 210)
            border = QColor(15, 23, 42, 32)
            shine = QColor(255, 255, 255, 255)
        p.setPen(QPen(border, 1))
        p.setBrush(fill)
        p.drawRoundedRect(rect, 12, 12)
        p.setPen(QPen(shine, 1))
        p.drawLine(rect.left() + 12, rect.top() + 1,
                   rect.right() - 12, rect.top() + 1)
        p.end()

    def _add(self, action, label, menu=None):
        b = RibbonButton(action, True, label)
        b.set_family(self.family)
        if menu is not None:
            b.setMenu(menu)
            b.setPopupMode(QToolButton.MenuButtonPopup)
        self.row.addWidget(b, 0, Qt.AlignTop)
        self.buttons.append(b)
        return b

    def large(self, action, label=None, menu=None):
        return self._add(action, label, menu)

    def place(self, button, index):
        """Move one of this group's buttons to `index` (0 = first)."""
        if button not in self.buttons:
            return None
        self.row.removeWidget(button)
        self.buttons.remove(button)
        index = max(0, min(index, len(self.buttons)))
        self.row.insertWidget(index, button, 0, Qt.AlignTop)
        self.buttons.insert(index, button)
        return index

    def small(self, actions, labels=None):
        """Same tiles, same row. A stacked column put some labels higher
        than the tiles beside them (the Service tab)."""
        labels = labels or {}
        for i, a in enumerate(actions):
            self._add(a, labels.get(i))

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
        self.lay.setContentsMargins(8, 4, 8, 2)
        self.lay.setSpacing(8)
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

    def arrange_groups(self, order):
        """Put the groups in this order, left to right (groups not named
        keep their place after them). Returns the titles in order."""
        names = [n for n in order if n in self.groups]
        names += [n for n in self.groups if n not in names]
        for n in names:
            self.lay.removeWidget(self.groups[n])
        for i, n in enumerate(names):
            self.lay.insertWidget(i, self.groups[n])
        self.groups = {n: self.groups[n] for n in names}
        return names

    def group(self, title):
        if title in self.groups:
            return self.groups[title]
        g = RibbonGroup(title)
        g.set_family(family_for(getattr(self, "tab_name", ""), title))
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
    page_changed = Signal(str)

    HEIGHT = 132

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
        for p in self.pages.values():
            for g in p.groups.values():
                g.refresh_caption()
                g.update()
                for b in g.buttons:
                    b.update()

    def page(self, name):
        if name in self.pages:
            return self.pages[name]
        p = RibbonPage()
        p.tab_name = name
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

    def arrange(self, order):
        """Put the tabs in this order (names not in it keep their place
        after the ones that are). Pages are made where their first command
        is listed, so a folded group (AI Schedule -> Project) could pull a
        tab ahead of its neighbours (Nov 5)."""
        names = [n for n in order if n in self.pages]
        names += [n for n in self.pages if n not in names]
        slots = sorted(self.tab_row.indexOf(self.pages[n].tab_button)
                       for n in names)
        for n in names:
            self.tab_row.removeWidget(self.pages[n].tab_button)
        for i, n in zip(slots, names):
            self.tab_row.insertWidget(i, self.pages[n].tab_button)
        self.pages = {n: self.pages[n] for n in names}
        return names

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
        self.page_changed.emit(name)

    def current(self):
        w = self.stack.currentWidget()
        return next((n for n, p in self.pages.items() if p is w), None)

    def set_collapsed(self, on):
        self.collapsed = bool(on)
        self.stack.setVisible(not on)
        self.collapse.setText("⌄" if on else "⌃")
        settings.set("ribbon_collapsed", self.collapsed)


class ModelStatus(QFrame):
    """Local-model status on the AI tab. Uses the same check the Generate
    Set window already runs. Click opens Local AI Models."""

    def __init__(self, win, parent=None):
        super().__init__(parent)
        self.win = win
        self.setObjectName("ModelStatus")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumWidth(168)
        self.setFixedHeight(74)
        self._state = "check"
        self._text = "Checking the local AI…"
        self._fit()
        self.setToolTip("Local model status. Click to open Local AI Models.")
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self.refresh)

    def refresh(self):
        from . import bg

        def work():
            from . import policy
            if not policy.allowed("ai"):
                return ("off", "Local AI: turned off")
            try:
                from .genset import brief
                up = brief.ai_up(timeout=0.6)
            except Exception:                             # noqa: BLE001
                up = False
            if not up:
                return ("down", "Local AI: not running")
            try:
                from .genset import brief
                model = brief.ai_model() or ""
            except Exception:                             # noqa: BLE001
                model = ""
            extra = f" · {model}" if model else ""
            return ("up", "Local AI: running" + extra)

        def done(pair):
            self._state, self._text = pair
            self._fit()
            self.update()

        bg.run(work, done, lambda _m: done(("down", "Local AI: not running")),
               self)

    def _lines(self, width=None):
        """The text as one line, or split after the colon onto two."""
        fm = self.fontMetrics()
        width = self.width() if width is None else width
        if fm.horizontalAdvance(self._text) <= width - 28:
            return [self._text]
        cut = self._text.find(":")
        if cut > 0:
            return [self._text[:cut], self._text[cut + 1:].strip()]
        return [self._text]

    def _fit(self):
        """Wide enough for the longest line, so nothing is cut off at the
        ribbon's edge (Chief's user test, Nov 6)."""
        fm = self.fontMetrics()
        cut = self._text.find(":")
        parts = ([self._text[:cut], self._text[cut + 1:].strip()]
                 if cut > 0 else [self._text])
        need = max(fm.horizontalAdvance(x) for x in parts) + 34
        self.setMinimumWidth(max(168, need))
        self.updateGeometry()

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(max(self.minimumWidth(), 168), 74)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            fn = getattr(self.win, "ai_models", None)
            if fn is not None:
                fn()
        super().mouseReleaseEvent(e)

    def paintEvent(self, _ev):
        from . import theme
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        dark = theme.is_dark()
        p.setPen(theme.color("text") if self._state != "check"
                 else _ink(DISABLED_INK))
        dot = {"up": "#12865a" if not dark else "#3fb27f",
               "down": "#b54708" if not dark else "#e3a008",
               "off": "#6b7280",
               "check": "#6b7280"}.get(self._state, "#6b7280")
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(dot))
        p.drawEllipse(8, self.height() // 2 - 5, 10, 10)
        p.setPen(theme.color("text"))
        # two lines, bottom-aligned in the same slot as ribbon labels
        fm = p.fontMetrics()
        # split on the colon so the state name stays on line 2 if needed
        lines = self._lines()
        lh = fm.height()
        slot_top = self.height() - 8 - lh * 2
        top = slot_top + (2 - len(lines)) * lh
        for i, line in enumerate(lines[:2]):
            p.drawText(QRect(24, top + i * lh, self.width() - 30, lh),
                       Qt.AlignLeft | Qt.AlignVCenter, line)
        p.end()


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
