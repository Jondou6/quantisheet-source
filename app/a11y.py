"""Screen readers and keyboard-only use (Venice #18-#21, Nov 4).

- name_widgets(root): every control a screen reader lands on gets a name.
  Icon-only buttons take their tool tip; a field in a form takes its
  label; anything else with only an object name gets that, tidied.
- audit(root): the controls still without a name, and ones the keyboard
  can't reach (for the tests and tools/a11y_audit).
- keyboard_audit(root): controls Tab never reaches (tools/keyboard_audit
  walks the main dialogs with it).
- install(app): names each window and dialog the first time it shows,
  so dialogs built later are covered too.
- high_contrast(): Windows High Contrast is on - the theme then leaves
  Windows' own colours alone (theme.apply).

Per-monitor DPI: Qt 6 is per-monitor aware (v2) and passes the exact
scale through (no rounding), so 150% / 200% screens and moving a window
between monitors need nothing extra here.
"""
import logging
import re
import sys

log = logging.getLogger(__name__)

_AMP = re.compile(r"&(?!&)")


def _clean(text):
    t = _AMP.sub("", str(text or "")).replace("…", "").strip()
    t = re.sub(r"<[^>]+>", "", t)               # rich-text tool tips
    return " ".join(t.split())[:120]


def _from_object_name(name):
    name = str(name or "")
    if not name or name.startswith("qt_"):
        return ""
    return " ".join(w for w in re.split(r"[_\W]+|(?<=[a-z])(?=[A-Z])", name)
                    if w).capitalize()


def _form_label(w):
    """The label beside `w` in a QFormLayout, or its buddy label."""
    from PySide6.QtWidgets import QFormLayout, QLabel
    p = w.parentWidget()
    lay = p.layout() if p is not None else None
    if isinstance(lay, QFormLayout):
        lab = lay.labelForField(w)
        if isinstance(lab, QLabel):
            return _clean(lab.text())
    if p is not None:
        for lab in p.findChildren(QLabel):
            if lab.buddy() is w:
                return _clean(lab.text())
    return ""


def name_for(w):
    """The name a screen reader should say for `w` ("" if none found)."""
    from PySide6.QtWidgets import (QAbstractButton, QComboBox, QLineEdit,
                                   QAbstractSpinBox, QPlainTextEdit,
                                   QTextEdit)
    if w.accessibleName():
        return w.accessibleName()
    if isinstance(w, QAbstractButton) and _clean(w.text()):
        return ""                         # Qt reads the button's own text
    if isinstance(w, (QLineEdit, QComboBox, QAbstractSpinBox,
                      QPlainTextEdit, QTextEdit)):
        lab = _form_label(w)
        if lab:
            return lab
        ph = getattr(w, "placeholderText", lambda: "")()
        if ph:
            return _clean(ph)
    for t in (w.toolTip(), w.statusTip(), w.whatsThis()):
        if _clean(t):
            return _clean(t)
    if isinstance(w, QAbstractButton):
        act = getattr(w, "defaultAction", lambda: None)()
        if act is not None and _clean(act.text()):
            return _clean(act.text())
    name = _from_object_name(w.objectName())
    if name:
        return name
    return _panel_title(w)


def _panel_title(w):
    """A list or table with nothing of its own takes its panel's title
    (the dock or dialog it sits in): "Takeoff list", "Markups List"."""
    from PySide6.QtWidgets import (QAbstractItemView, QDockWidget,
                                   QTabBar)
    if not isinstance(w, (QAbstractItemView, QTabBar)):
        return ""
    p = w.parentWidget()
    for _ in range(8):
        if p is None:
            break
        if isinstance(p, QDockWidget) and _clean(p.windowTitle()):
            return _clean(p.windowTitle()) + (" tabs" if isinstance(
                w, QTabBar) else " list")
        if p.isWindow() and _clean(p.windowTitle()):
            return _clean(p.windowTitle()) + (" tabs" if isinstance(
                w, QTabBar) else " list")
        p = p.parentWidget()
    return ""


def _focusable(w):
    from PySide6.QtCore import Qt
    return w.focusPolicy() != Qt.FocusPolicy.NoFocus


def _controls(root):
    from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView,
                                   QAbstractSlider, QAbstractSpinBox,
                                   QComboBox, QLineEdit, QPlainTextEdit,
                                   QTabBar, QTextEdit)
    kinds = (QAbstractButton, QLineEdit, QComboBox, QAbstractSpinBox,
             QPlainTextEdit, QTextEdit, QAbstractItemView, QAbstractSlider,
             QTabBar)
    from PySide6.QtWidgets import QHeaderView, QScrollBar, QWidget
    skip = (QScrollBar, QHeaderView)  # read as part of their list or page
    return [w for w in root.findChildren(QWidget)    # one type per call
            if isinstance(w, kinds) and not isinstance(w, skip)
            and not w.objectName().startswith("qt_")]


def name_widgets(root):
    """Give every unnamed control under `root` a name. Returns how many
    were named."""
    n = 0
    for w in _controls(root):
        try:
            if w.accessibleName():
                continue
            from PySide6.QtWidgets import QAbstractButton
            if isinstance(w, QAbstractButton) and _clean(w.text()):
                continue
            name = name_for(w)
            if name:
                w.setAccessibleName(name)
                n += 1
        except RuntimeError:            # a widget deleted meanwhile
            continue
    return n


def audit(root):
    """[(widget class, object name, problem)] for controls a screen reader
    can't name, or icon buttons the keyboard can't reach."""
    from PySide6.QtWidgets import QAbstractButton, QToolButton
    out = []
    for w in _controls(root):
        try:
            named = bool(w.accessibleName()) or (
                isinstance(w, QAbstractButton) and _clean(w.text()))
            if not named:
                out.append((type(w).__name__, w.objectName(), "no name"))
            if isinstance(w, QAbstractButton) and \
                    not isinstance(w, QToolButton) and not _focusable(w):
                out.append((type(w).__name__, w.objectName(),
                            "can't be reached with Tab"))
        except RuntimeError:
            continue
    return out


def tab_chain(root):
    """The widgets Tab moves through inside `root`, in order."""
    from PySide6.QtCore import Qt
    out, seen = [], set()
    w = root.nextInFocusChain()
    while w is not None and w is not root and id(w) not in seen \
            and len(out) < 5000:
        seen.add(id(w))
        try:
            if (w.focusPolicy() & Qt.FocusPolicy.TabFocus) and \
                    w.isEnabled() and w.isVisibleTo(root) and \
                    (w is root or root.isAncestorOf(w)):
                out.append(w)
        except RuntimeError:
            pass
        w = w.nextInFocusChain()
    return out


def _reached_inside(w, chain):
    """A spin box or combo box takes focus through its own line edit."""
    for c in chain:
        # Python already reads this as A or B or (C and D); the brackets
        # only make that plain to a reader (outside review, Nov 7)
        if c is w or w.isAncestorOf(c) or \
                (c.isAncestorOf(w) and c.focusProxy() is w):
            return True
        if c.focusProxy() is w or w.focusProxy() is c:
            return True
    return False


def keyboard_audit(root):
    """Keyboard-only check (Nov 5): [(class, name, problem)] for controls
    that show and work with a mouse but that Tab never reaches. Tab bars
    are left out (Ctrl+Tab moves between tabs) and so are scroll bars and
    headers; only what shows on the current tab is checked."""
    from PySide6.QtWidgets import QTabBar
    chain = tab_chain(root)
    out = []
    for w in _controls(root):
        try:
            if isinstance(w, QTabBar) or not w.isVisibleTo(root) or \
                    not w.isEnabled():
                continue
            if _reached_inside(w, chain):
                continue
            label = w.accessibleName() or _clean(getattr(w, "text",
                                                         lambda: "")()) \
                or w.objectName()
            out.append((type(w).__name__, label, "Tab never reaches it"))
        except RuntimeError:
            continue
    return out


class _Namer:
    """Names each top-level window the first time it shows."""

    def __init__(self):
        from PySide6.QtCore import QObject, QEvent

        class F(QObject):
            def eventFilter(self, obj, ev):           # noqa: N802
                if ev.type() == QEvent.Type.Show and obj.isWidgetType() \
                        and obj.isWindow() and \
                        not obj.property("_a11y_named"):
                    try:
                        obj.setProperty("_a11y_named", True)
                        name_widgets(obj)
                    except Exception:                     # noqa: BLE001
                        log.debug("naming widgets", exc_info=True)
                return False
        self.filter = F()


_namer = None


def install(app):
    global _namer
    if _namer is None:
        _namer = _Namer()
        app.installEventFilter(_namer.filter)
    return _namer


def high_contrast():
    """True when Windows High Contrast is on (never elsewhere)."""
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes
        from ctypes import wintypes

        class HC(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT),
                        ("dwFlags", wintypes.DWORD),
                        ("lpszDefaultScheme", wintypes.LPWSTR)]
        hc = HC()
        hc.cbSize = ctypes.sizeof(HC)
        ok = ctypes.windll.user32.SystemParametersInfoW(
            0x0042, hc.cbSize, ctypes.byref(hc), 0)   # SPI_GETHIGHCONTRAST
        return bool(ok and hc.dwFlags & 0x1)          # HCF_HIGHCONTRASTON
    except Exception:                                     # noqa: BLE001
        return False
