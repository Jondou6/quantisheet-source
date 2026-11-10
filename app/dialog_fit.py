"""Every dialog fits the screen and can be moved, minimized and maximized
(Jon, Oct 22: with large Windows text, boxes such as the Roofing calculator
were taller than the laptop screen. The title bar was above the top edge,
so the box couldn't be moved, and it had no minimize button).

install(app) adds one application-wide event filter. For each dialog,
the first time it is about to be shown:
  * it gets minimize and maximize buttons (and keeps its close button);
  * if it is taller or wider than the screen's free area, its contents go
    into a scroll area (the button row, if it is the last item, stays
    below the scroll area so OK / Close are always visible);
  * it is sized to fit and placed fully on the screen, title bar first.
Message boxes, file dialogs and menus are left alone.
"""
import logging

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (QBoxLayout, QDialog, QDialogButtonBox,
                               QFileDialog, QFrame, QMessageBox,
                               QProgressDialog, QScrollArea, QWidget)

log = logging.getLogger(__name__)

DONE = "_qs_fitted"
MARGIN = 24            # room around the box inside the screen's free area
TITLE = 40             # the title bar Windows draws above the client area

SKIP = (QMessageBox, QFileDialog, QProgressDialog)


def _avail(w):
    scr = w.screen() if hasattr(w, "screen") else None
    if scr is None:
        from PySide6.QtGui import QGuiApplication
        scr = QGuiApplication.primaryScreen()
    return scr.availableGeometry() if scr is not None else None


def _wrap_in_scroll(dlg):
    """Move the dialog's box layout items into a scroll area. The last
    item stays outside when it is a button box. Returns True if done."""
    lay = dlg.layout()
    if not isinstance(lay, QBoxLayout) or lay.count() == 0:
        return False
    stretch = [lay.stretch(k) for k in range(lay.count())]
    items = []
    while lay.count():
        items.append(lay.takeAt(0))
    items = list(zip(items, stretch))
    buttons = None
    last = items[-1][0] if items else None
    if last is not None and isinstance(last.widget(), QDialogButtonBox):
        buttons = items.pop()[0]
    inner = QWidget()
    inner.setObjectName("FitInner")
    box = QBoxLayout(lay.direction(), inner)
    m = lay.contentsMargins()
    box.setContentsMargins(m)
    box.setSpacing(lay.spacing())
    for n, (item, st) in enumerate(items):
        w = item.widget()
        hidden = w.isHidden() if w is not None else False
        box.addItem(item)
        box.setStretch(n, st)
        if w is not None:
            w.setParent(inner)
            if not hidden:
                w.show()
    area = QScrollArea()
    area.setObjectName("FitScroll")
    area.setFrameShape(QFrame.NoFrame)
    area.setWidgetResizable(True)
    area.setWidget(inner)
    lay.setContentsMargins(0, 0, 0, m.bottom())
    lay.addWidget(area, 1)
    if buttons is not None:
        lay.addItem(buttons)
        bw = buttons.widget()
        if bw is not None:
            if bw.parent() is not dlg:
                bw.setParent(dlg)
                bw.show()
            bw.setContentsMargins(m.left(), 0, m.right(), 0)
    return True


def fit(dlg):
    """Size and place `dlg` inside the screen's free area (see module)."""
    a = _avail(dlg)
    if a is None:
        return
    max_w = max(200, a.width() - 2 * MARGIN)
    max_h = max(200, a.height() - 2 * MARGIN - TITLE)
    hint = dlg.sizeHint().expandedTo(dlg.minimumSizeHint())
    too_big = hint.height() > max_h or hint.width() > max_w or \
        dlg.height() > max_h or dlg.width() > max_w
    if too_big and not dlg.property("_qs_scrolled"):
        try:
            if _wrap_in_scroll(dlg):
                dlg.setProperty("_qs_scrolled", True)
        except Exception:                                # noqa: BLE001
            log.debug("could not add a scroll area", exc_info=True)
    # never ask for more than the screen
    if dlg.minimumHeight() > max_h:
        dlg.setMinimumHeight(max_h)
    if dlg.minimumWidth() > max_w:
        dlg.setMinimumWidth(max_w)
    w = min(max(dlg.width(), dlg.sizeHint().width()), max_w)
    h = min(max(dlg.height(), dlg.sizeHint().height()), max_h)
    if too_big:
        dlg.resize(w, h)
    g = dlg.frameGeometry()
    x = min(max(g.x(), a.left() + MARGIN // 2),
            a.right() - dlg.width() - MARGIN // 2)
    y = min(max(g.y(), a.top() + MARGIN // 2),
            a.bottom() - dlg.height() - TITLE - MARGIN // 2)
    dlg.move(max(a.left(), x), max(a.top(), y))


def _buttons(dlg):
    """Minimize and maximize buttons next to Close."""
    f = dlg.windowFlags()
    want = f | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint \
        | Qt.WindowSystemMenuHint
    if want != f:
        dlg.setWindowFlags(want)


class _Filter(QObject):
    def eventFilter(self, obj, ev):
        t = ev.type()
        if t not in (QEvent.Polish, QEvent.Show):
            return False
        if not isinstance(obj, QDialog) or isinstance(obj, SKIP) or \
                not obj.isWindow():
            return False
        try:
            if t == QEvent.Polish and not obj.property("_qs_flags") and \
                    not obj.isVisible():
                obj.setProperty("_qs_flags", True)
                _buttons(obj)
            elif t == QEvent.Show and not obj.property(DONE):
                obj.setProperty(DONE, True)
                # a Close button where the dialog has none (Chief, Nov 7)
                from . import closebutton
                closebutton.ensure(obj)
                fit(obj)
        except Exception:                                # noqa: BLE001
            log.debug("dialog fit failed", exc_info=True)
        return False


_installed = []


def install(app):
    if _installed:
        return _installed[0]
    f = _Filter(app)
    app.installEventFilter(f)
    _installed.append(f)
    return f
