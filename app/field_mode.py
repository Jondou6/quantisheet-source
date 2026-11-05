"""Field mode (Ctrl+5): bigger touch targets (40 px), ribbon hidden, larger
fonts, dark theme (uses theme.apply - QuantiSheet already has Dark), and a
density setting (compact / comfortable / touch) that works on its own too.
The choice is remembered in settings ("field_mode", "density")."""
from . import settings

DENSITY = {"compact": {"target": 24, "font": 9},
           "comfortable": {"target": 32, "font": 10},
           "touch": {"target": 40, "font": 13}}


def stylesheet(name):
    d = DENSITY[name]
    t, f = d["target"], d["font"]
    return (f"QPushButton, QToolButton, QLineEdit, QComboBox, QSpinBox, "
            f"QDoubleSpinBox {{ min-height: {t}px; font-size: {f}pt; }}\n"
            f"QTabBar::tab {{ min-height: {t}px; font-size: {f}pt; }}\n"
            f"QListView::item, QTreeView::item, QTableView::item "
            f"{{ min-height: {t}px; }}\n"
            f"QMenu::item {{ padding: {max(4, t // 5)}px 18px; "
            f"font-size: {f}pt; }}\n"
            f"QCheckBox::indicator, QRadioButton::indicator "
            f"{{ width: {t // 2}px; height: {t // 2}px; }}")


def _default_theme(m):
    from . import theme
    if m == "restore":
        theme.apply(m=settings.get("theme", "system"))
    else:
        theme.apply(m=m)


class FieldMode:
    def __init__(self, window, apply_theme=None):
        self.w = window
        self.on = False
        self.apply_theme = apply_theme or _default_theme
        self.action = None
        self._ribbon_was = True

    def _ribbon(self):
        # the ribbon bar on screen (the simple menus' when they're on)
        f = getattr(self.w, "active_ribbon_bar", None)
        if callable(f):
            return f()
        return getattr(self.w, "ribbon", None)

    def set_density(self, name, save=True):
        if name not in DENSITY:
            raise ValueError(f"density must be one of {list(DENSITY)}")
        # "comfortable" is the program's normal look: no extra stylesheet
        # (the app theme's own sizes), so leaving field mode puts it back
        # exactly as it was
        self.w.setStyleSheet("" if name == "comfortable" else
                             stylesheet(name))
        if save:
            settings.set("density", name)

    def set(self, on):
        r = self._ribbon()
        if on and not self.on:
            # "not hidden", not isVisible(): a window that isn't on screen
            # yet (or is minimised) still has its ribbon switched on
            self._ribbon_was = (not r.isHidden()) if r is not None else True
            if r is not None:
                r.hide()
            self._prev_density = settings.get("density", "comfortable")
            self.set_density("touch")
            self.apply_theme("dark")
        elif not on and self.on:
            if r is not None and self._ribbon_was:
                r.show()
            prev = getattr(self, "_prev_density", "comfortable")
            self.set_density(prev if prev != "touch" else "comfortable")
            self.apply_theme("restore")
        self.on = bool(on)
        settings.set("field_mode", self.on)
        if self.action is not None:
            self.action.setChecked(self.on)

    def toggle(self):
        self.set(not self.on)


def install(window, apply_theme=None):
    """Add the Ctrl+5 action and restore the remembered state."""
    from PySide6.QtGui import QAction, QKeySequence
    f = FieldMode(window, apply_theme)
    a = QAction("Field Mode", window, checkable=True)
    a.setShortcut(QKeySequence("Ctrl+5"))
    a.triggered.connect(lambda _c=False: f.toggle())
    window.addAction(a)
    f.action = a
    d = settings.get("density")
    if d in DENSITY and d != "comfortable":
        f.set_density(d, save=False)
    if settings.get("field_mode") is True:
        f._ribbon_was = True
        f.on = False
        f.set(True)
    window.field_mode = f
    return f
