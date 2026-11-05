"""Dark and light themes (View > Theme), following Windows by default.

One set of colour tokens per theme drives the Qt palette, the style sheet
and the icon colour, so every window and dialog matches. Saved in settings
as "theme": "system" | "dark" | "light".
"""
import logging
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

from . import settings

DARK = {
    "window": "#1b1c1f", "surface": "#232428", "surface2": "#2b2d32",
    "raised": "#33353b", "border": "#3a3c43", "border2": "#4a4d55",
    "text": "#e8e9ec", "muted": "#9a9da6", "faint": "#6b6e77",
    "accent": "#4c8dff", "accent2": "#77a8ff", "on_accent": "#ffffff",
    "accent_soft": "#25344f", "canvas": "#131416", "danger": "#f05252",
    "ok": "#3fb27f", "warn": "#e3a008", "tip": "#2b2d32",
}
LIGHT = {
    "window": "#f3f4f6", "surface": "#ffffff", "surface2": "#f5f6f8",
    "raised": "#eceef2", "border": "#e5e7eb", "border2": "#d1d5db",
    "text": "#16181d", "muted": "#5f6470", "faint": "#9aa0ab",
    "accent": "#2563eb", "accent2": "#1d4ed8", "on_accent": "#ffffff",
    "accent_soft": "#e8efff", "canvas": "#e4e7ec", "danger": "#d92d20",
    "ok": "#12865a", "warn": "#b54708", "tip": "#16181d",
}
MODES = ("system", "dark", "light")


class _Hub(QObject):
    changed = Signal(str)          # "dark" | "light"


hub = _Hub()
_current = {"name": "light", "tokens": LIGHT}


def mode():
    m = settings.get("theme", "system")
    return m if m in MODES else "system"


def system_is_dark():
    try:
        return QGuiApplication.styleHints().colorScheme() == \
            Qt.ColorScheme.Dark
    except Exception:
        return False


def resolved(m=None):
    m = m or mode()
    if m == "system":
        return "dark" if system_is_dark() else "light"
    return m


def tokens():
    return _current["tokens"]


def name():
    return _current["name"]


def color(key):
    return QColor(tokens()[key])


def is_dark():
    return name() == "dark"


def _palette(t):
    p = QPalette()
    c = QColor
    for role, key in ((QPalette.Window, "window"),
                      (QPalette.WindowText, "text"),
                      (QPalette.Base, "surface"),
                      (QPalette.AlternateBase, "surface2"),
                      (QPalette.ToolTipBase, "tip"),
                      (QPalette.ToolTipText, "on_accent"),
                      (QPalette.Text, "text"),
                      (QPalette.Button, "surface2"),
                      (QPalette.ButtonText, "text"),
                      (QPalette.BrightText, "danger"),
                      (QPalette.Highlight, "accent"),
                      (QPalette.HighlightedText, "on_accent"),
                      (QPalette.Link, "accent"),
                      (QPalette.PlaceholderText, "faint"),
                      (QPalette.Mid, "border"),
                      (QPalette.Dark, "border2"),
                      (QPalette.Light, "raised")):
        p.setColor(role, c(t[key]))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        p.setColor(QPalette.Disabled, role, c(t["faint"]))
    return p


def _assets(t, n):
    """Small SVGs the style sheet points at (check marks, arrows, close)."""
    import os
    import tempfile
    d = os.path.join(tempfile.gettempdir(), f"quantisheet-theme-{n}")
    os.makedirs(d, exist_ok=True)
    head = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
            'fill="none" stroke-linecap="round" stroke-linejoin="round" ')
    files = {
        "check": f'{head}stroke="#ffffff" stroke-width="3.2"><path d="m5 12 5 5 9-10"/></svg>',
        "close": f'{head}stroke="{t["muted"]}" stroke-width="2.2"><path d="M7 7l10 10M17 7 7 17"/></svg>',
        "close_hot": f'{head}stroke="{t["text"]}" stroke-width="2.4"><path d="M7 7l10 10M17 7 7 17"/></svg>',
        "float": f'{head}stroke="{t["muted"]}" stroke-width="2"><rect x="5" y="7" width="12" height="12" rx="2"/><path d="M9 4h10a1 1 0 0 1 1 1v10"/></svg>',
        "down": f'{head}stroke="{t["muted"]}" stroke-width="2.4"><path d="m6 9 6 6 6-6"/></svg>',
        "up": f'{head}stroke="{t["muted"]}" stroke-width="2.4"><path d="m6 15 6-6 6 6"/></svg>',
        "dot": f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><circle cx="12" cy="12" r="5" fill="#ffffff"/></svg>',
    }
    out = {}
    for k, svg in files.items():
        p = os.path.join(d, k + ".svg")
        try:
            with open(p, "w", encoding="utf-8") as f:
                f.write(svg)
        except OSError:
            pass
        out[k] = p.replace("\\", "/")
    return out


def stylesheet(t, a=None):
    a = a or _assets(t, "x")
    return f"""
* {{ outline: none; }}
QMainWindow, QDialog {{ background: {t['window']}; }}
QWidget {{ color: {t['text']}; }}
QToolTip {{ background: {t['tip']}; color: #ffffff; border: none;
    padding: 5px 8px; border-radius: 6px; }}

/* ribbon */
#Ribbon {{ background: {t['surface']}; border-bottom: 1px solid {t['border']}; }}
#RibbonHeader {{ background: {t['surface']}; }}
#RibbonBody {{ background: {t['surface']}; }}
#RibbonMore {{ background: {t['surface2']}; color: {t['accent']};
    border: 1px solid {t['border2']}; border-radius: 6px; }}
#RibbonMore:hover {{ background: {t['accent_soft']}; }}
#AppButton {{ background: {t['accent']}; color: {t['on_accent']};
    border: none; border-radius: 6px; padding: 5px 14px; font-weight: 600; }}
#AppButton:hover {{ background: {t['accent2']}; }}
#AppButton::menu-indicator {{ image: none; width: 0; }}
#RibbonTab {{ background: transparent; border: none;
    border-bottom: 2px solid transparent; color: {t['muted']};
    padding: 6px 12px 5px 12px; border-radius: 0; font-weight: 500; }}
#RibbonTab:hover {{ color: {t['text']}; border-bottom-color: {t['border2']}; }}
#RibbonTab:checked {{ color: {t['accent']}; background: transparent;
    border-bottom-color: {t['accent']}; font-weight: 600; }}
#RibbonGroup {{ background: transparent; }}
#RibbonGroupLabel {{ color: {t['faint']}; font-size: 8pt; }}
#RibbonSep {{ background: {t['border']}; }}
#RibbonButton {{ background: transparent; border: 1px solid transparent;
    border-radius: 8px; padding: 3px 4px; color: {t['text']}; }}
#RibbonButton:hover {{ background: {t['surface2']}; border-color: {t['border']}; }}
#RibbonButton:pressed {{ background: {t['raised']}; }}
#RibbonButton:checked {{ background: {t['accent_soft']};
    border-color: {t['accent']}; color: {t['accent']}; }}
#RibbonButton:disabled {{ color: {t['faint']}; }}
#RibbonButton::menu-indicator {{ image: none; width: 0; }}
#CommandSearch {{ background: {t['surface2']}; border: 1px solid {t['border']};
    border-radius: 8px; padding: 5px 10px; color: {t['muted']};
    text-align: left; }}
#CommandSearch:hover {{ border-color: {t['border2']}; color: {t['text']}; }}
#IconButton {{ background: transparent; border: none; border-radius: 6px;
    padding: 5px; }}
#IconButton:hover {{ background: {t['surface2']}; }}

/* modern layout: top bar, tool rail, tool strip, All Tools */
#modern_top_bar {{ background: {t['surface']}; border: none;
    border-bottom: 1px solid {t['border']}; padding: 4px 8px; spacing: 4px; }}
#modern_top_bar QToolButton {{ background: transparent; border: none;
    border-radius: 6px; padding: 5px 7px; }}
#modern_top_bar QToolButton:hover {{ background: {t['surface2']}; }}
#modern_top_bar QToolButton:checked {{ background: {t['accent_soft']};
    color: {t['accent']}; font-weight: 600; }}
#modern_top_bar QToolButton::menu-indicator {{ image: none; width: 0; }}
#modern_tool_rail {{ background: {t['surface']}; border: none;
    border-right: 1px solid {t['border']}; padding: 6px 3px; spacing: 2px; }}
#RailButton {{ background: transparent; border: 1px solid transparent;
    border-radius: 8px; padding: 4px 1px; min-width: 56px; max-width: 66px;
    font-size: 8pt; color: {t['muted']}; }}
#RailButton:hover {{ background: {t['surface2']}; color: {t['text']}; }}
#RailButton:checked {{ background: {t['accent_soft']};
    border: 1px solid transparent; border-left: 3px solid {t['accent']};
    color: {t['accent']}; font-weight: 600; }}
#RailButton:disabled {{ color: {t['faint']}; }}
#RailSep {{ color: {t['border']}; background: {t['border']}; max-height: 1px;
    margin: 4px 6px; border: none; }}
#modern_tool_strip {{ background: {t['accent_soft']}; border: none;
    border-bottom: 1px solid {t['border']}; padding: 3px 10px; spacing: 8px; }}
#modern_tool_strip QToolButton {{ background: {t['surface']};
    border: 1px solid {t['border']}; border-radius: 6px; padding: 3px 8px; }}
#modern_tool_strip QToolButton:hover {{ border-color: {t['accent']}; }}
#modern_tool_strip QToolButton:checked {{ border-color: {t['accent']};
    color: {t['accent']}; }}
#StripTitle {{ color: {t['text']}; padding: 0 4px; }}
#StripHint {{ color: {t['muted']}; }}
#StripWarn {{ color: {t['warn']}; font-weight: 600; }}
#StripDone {{ background: {t['accent']}; color: {t['on_accent']}; border: none;
    border-radius: 6px; padding: 4px 14px; font-weight: 600; }}
#StripDone:hover {{ background: {t['accent2']}; }}
#AllToolsSearch {{ background: {t['surface2']}; border: 1px solid {t['border']};
    border-radius: 8px; padding: 6px 10px; }}
#AllToolsSearch:focus {{ border-color: {t['accent']}; }}
#AllToolsTree {{ background: transparent; border: none; }}
#AllToolsTree::item {{ padding: 5px 4px; border-radius: 6px; }}
#AllToolsTree::item:hover {{ background: {t['surface2']}; }}
#AllToolsTree::item:selected {{ background: {t['accent_soft']}; color: {t['text']}; }}

/* command palette */
#Palette {{ background: {t['surface']}; border: 1px solid {t['border2']};
    border-radius: 12px; }}
#PaletteInput {{ background: transparent; border: none;
    border-bottom: 1px solid {t['border']}; padding: 12px 14px;
    font-size: 12pt; }}
#PaletteList {{ background: transparent; border: none; padding: 6px; }}
#PaletteList::item {{ padding: 7px 10px; border-radius: 6px; }}
#PaletteList::item:selected {{ background: {t['accent_soft']};
    color: {t['text']}; }}

/* document tabs */
QTabWidget::pane {{ border: none; }}
QTabBar {{ background: {t['window']}; }}
QTabBar::tab {{ background: transparent; color: {t['muted']};
    padding: 7px 14px; border: none; border-bottom: 2px solid transparent;
    margin-right: 2px; }}
QTabBar::tab:hover {{ color: {t['text']}; }}
QTabBar::tab:selected {{ color: {t['text']}; border-bottom-color: {t['accent']}; }}
#docTab, #docTab > QWidget > QWidget {{ background: {t['canvas']}; }}

/* docks */
QDockWidget {{ color: {t['muted']}; font-weight: 600; font-size: 9pt; }}
QDockWidget::title {{ background: {t['surface']}; padding: 8px 12px 6px 12px;
    border-bottom: 1px solid {t['border']}; text-align: left; }}
QDockWidget > QWidget {{ background: {t['surface']}; }}
QMainWindow::separator {{ background: {t['border']}; width: 1px; height: 1px; }}
QMainWindow::separator:hover {{ background: {t['accent']}; }}

/* inputs */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QDateEdit,
QComboBox {{ background: {t['surface']}; border: 1px solid {t['border2']};
    border-radius: 7px; padding: 4px 8px;
    selection-background-color: {t['accent']}; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus,
QDoubleSpinBox:focus, QDateEdit:focus, QComboBox:focus {{
    border-color: {t['accent']}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox QAbstractItemView {{ background: {t['surface']};
    border: 1px solid {t['border2']}; selection-background-color: {t['accent_soft']};
    selection-color: {t['text']}; outline: none; }}
QPushButton {{ background: {t['surface']}; border: 1px solid {t['border2']};
    border-radius: 7px; padding: 5px 14px; min-height: 18px; }}
QPushButton:hover {{ background: {t['raised']}; }}
QPushButton:default {{ background: {t['accent']}; color: {t['on_accent']};
    border-color: {t['accent']}; }}
QPushButton:default:hover {{ background: {t['accent2']}; }}
QPushButton:disabled {{ color: {t['faint']}; }}
QCheckBox, QRadioButton {{ spacing: 7px; }}
QGroupBox {{ border: 1px solid {t['border']}; border-radius: 8px;
    margin-top: 12px; padding-top: 8px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px;
    color: {t['muted']}; }}

/* tables and lists */
QTableView, QTreeView, QListView, QTableWidget, QTreeWidget, QListWidget {{
    background: {t['surface']}; alternate-background-color: {t['surface2']};
    border: 1px solid {t['border']}; border-radius: 6px;
    gridline-color: {t['border']};
    selection-background-color: {t['accent_soft']};
    selection-color: {t['text']}; }}
QHeaderView::section {{ background: {t['surface2']}; color: {t['muted']};
    border: none; border-bottom: 1px solid {t['border']};
    border-right: 1px solid {t['border']}; padding: 5px 7px;
    font-weight: 600; }}
QTableCornerButton::section {{ background: {t['surface2']}; border: none; }}

/* menus */
QMenuBar {{ background: {t['surface']}; }}
QMenu {{ background: {t['surface']}; border: 1px solid {t['border2']};
    border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 6px 26px 6px 22px; border-radius: 6px; }}
QMenu::item:selected {{ background: {t['accent_soft']}; color: {t['text']}; }}
QMenu::item:disabled {{ color: {t['faint']}; }}
QMenu::separator {{ height: 1px; background: {t['border']}; margin: 5px 8px; }}

/* scroll bars: slim, rounded */
QScrollBar:vertical {{ background: transparent; width: 11px; margin: 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 11px; margin: 2px; }}
QScrollBar::handle {{ background: {t['border2']}; border-radius: 4px;
    min-height: 28px; min-width: 28px; }}
QScrollBar::handle:hover {{ background: {t['faint']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* status bar */
QStatusBar {{ background: {t['surface']}; border-top: 1px solid {t['border']};
    color: {t['muted']}; }}
QStatusBar::item {{ border: none; }}
#StatusChip {{ color: {t['muted']}; padding: 0 8px; }}
#StatusChipAccent {{ color: {t['accent']}; padding: 0 8px; font-weight: 600; }}

#StartPage {{ background: {t['window']}; }}
#StartScroll, #StartBody {{ background: {t['window']}; border: none; }}
#StartTitle {{ font-size: 28pt; font-weight: 700; color: {t['text']}; }}
#StartSub {{ color: {t['muted']}; font-size: 11pt; }}
#StartSection {{ color: {t['faint']}; font-size: 8.5pt; font-weight: 700;
    padding-left: 2px; }}
#StartTip {{ color: {t['muted']}; }}
#StartHead {{ color: {t['muted']}; font-weight: 600; margin-top: 10px; }}
#StartCard {{ background: {t['surface']}; border: 1px solid {t['border']};
    border-radius: 12px; padding: 0; }}
#StartCard:hover {{ border-color: {t['accent']}; background: {t['surface']}; }}
#StartCard:pressed {{ background: {t['accent_soft']}; }}
#StartCard QLabel {{ background: transparent; }}
#StartCardIcon {{ background: {t['accent_soft']}; border-radius: 10px; }}
#StartCardTitle {{ font-size: 10.5pt; font-weight: 600; color: {t['text']}; }}
#StartCardSub {{ color: {t['muted']}; }}
#StartRecent {{ background: {t['surface']}; border: 1px solid {t['border']};
    border-radius: 12px; padding: 6px; }}
#StartRecent::item {{ border: none; }}
QTabBar::close-button {{ image: url({a['close']}); subcontrol-position: right;
    border-radius: 4px; margin: 2px; width: 14px; height: 14px; }}
QTabBar::close-button:hover {{ image: url({a['close_hot']});
    background: {t['raised']}; }}
QDockWidget {{ titlebar-close-icon: url({a['close']});
    titlebar-normal-icon: url({a['float']}); }}
QDockWidget::close-button, QDockWidget::float-button {{ border: none;
    background: transparent; padding: 2px; border-radius: 4px; }}
QDockWidget::close-button:hover, QDockWidget::float-button:hover {{
    background: {t['raised']}; }}
QCheckBox::indicator, QTableView::indicator, QListView::indicator,
QTreeView::indicator {{ width: 15px; height: 15px;
    border: 1px solid {t['border2']}; border-radius: 4px;
    background: {t['surface']}; }}
QCheckBox::indicator:hover {{ border-color: {t['accent']}; }}
QCheckBox::indicator:checked, QTableView::indicator:checked,
QListView::indicator:checked, QTreeView::indicator:checked {{
    background: {t['accent']}; border-color: {t['accent']};
    image: url({a['check']}); }}
QRadioButton::indicator {{ width: 15px; height: 15px; border-radius: 8px;
    border: 1px solid {t['border2']}; background: {t['surface']}; }}
QRadioButton::indicator:checked {{ background: {t['accent']};
    border-color: {t['accent']}; image: url({a['dot']}); }}
QComboBox::down-arrow {{ image: url({a['down']}); width: 11px; height: 11px; }}
QSpinBox::up-button, QDoubleSpinBox::up-button, QDateEdit::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button, QDateEdit::down-button {{
    subcontrol-origin: border; width: 16px; border: none;
    background: transparent; }}
QSpinBox::up-button, QDoubleSpinBox::up-button, QDateEdit::up-button {{
    subcontrol-position: top right; }}
QSpinBox::down-button, QDoubleSpinBox::down-button, QDateEdit::down-button {{
    subcontrol-position: bottom right; }}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {t['raised']}; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow, QDateEdit::up-arrow {{
    image: url({a['up']}); width: 9px; height: 9px; }}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow, QDateEdit::down-arrow {{
    image: url({a['down']}); width: 9px; height: 9px; }}
QSlider::groove:horizontal {{ height: 4px; background: {t['border2']};
    border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {t['accent']}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {t['surface']};
    border: 2px solid {t['accent']}; width: 12px; height: 12px;
    margin: -6px 0; border-radius: 8px; }}
#thumbs {{ background: {t['canvas']}; border: none; }}
#thumbs::item {{ color: {t['muted']}; border-radius: 6px; padding: 4px; }}
#thumbs::item:selected {{ background: {t['accent_soft']}; color: {t['text']}; }}
QMainWindow > QTabBar::tab {{ padding: 5px 7px; min-width: 28px;
    font-size: 9pt; margin-right: 0px; }}
QSplitter::handle {{ background: {t['border']}; }}
QProgressBar {{ background: {t['surface2']}; border: none; border-radius: 4px;
    text-align: center; height: 8px; }}
QProgressBar::chunk {{ background: {t['accent']}; border-radius: 4px; }}
QToolBar {{ background: {t['surface']}; border: none; spacing: 2px; }}
QToolButton {{ border-radius: 6px; padding: 3px; }}
QToolButton:hover {{ background: {t['surface2']}; }}
QToolButton:checked {{ background: {t['accent_soft']}; }}
"""


def _font():
    f = QFont()
    for fam in ("Segoe UI Variable Text", "Segoe UI", "Inter",
                "Helvetica Neue", "Arial"):
        f.setFamily(fam)
        if f.exactMatch() or fam == "Arial":
            break
    f.setPointSizeF(9.5)
    return f


def apply(app=None, m=None, save=False):
    """Apply a theme mode ("system", "dark" or "light"). Returns the name
    actually shown ("dark" or "light")."""
    app = app or QApplication.instance()
    if m is not None and save:
        settings.set("theme", m)
    n = resolved(m)
    t = DARK if n == "dark" else LIGHT
    _current.update(name=n, tokens=t)
    if app is None:
        return n
    # Venice #20 (Nov 4): Windows High Contrast on - leave Windows' own
    # colours and borders alone (our palette and style sheet would hide
    # them). The setting high_contrast = "off" ignores it.
    try:
        from . import a11y
        hc = a11y.high_contrast() and \
            settings.get("high_contrast", "auto") != "off"
    except Exception:                                     # noqa: BLE001
        hc = False
    if hc:
        _current.update(high_contrast=True)
        if not _current.get("font_set"):
            app.setFont(_font())
            _current["font_set"] = True
        app.setStyleSheet("")
        hub.changed.emit(n)
        return n
    # once: with a style sheet on, style().name() no longer says "fusion",
    # and setting the style again re-polished every widget (~1 s a switch)
    if _current.get("style_app") is not app:
        if app.style().name().lower() != "fusion":
            app.setStyle("Fusion")
        _current["style_app"] = app
    if not _current.get("font_set"):
        app.setFont(_font())
        _current["font_set"] = True
    app.setPalette(_palette(t))
    app.setStyleSheet(stylesheet(t, _assets(t, n)))
    hub.changed.emit(n)
    return n


def follow_system(app=None):
    """Re-apply when Windows switches between dark and light (theme
    'system' only)."""
    app = app or QApplication.instance()
    try:
        hints = QGuiApplication.styleHints()
        hints.colorSchemeChanged.connect(
            lambda *_: mode() == "system" and apply(app))
    except Exception:
        logging.getLogger(__name__).debug("ignored error", exc_info=True)


def soft(key_bg, alpha=None):
    """A QColor for a cell background that reads in both themes."""
    c = color(key_bg)
    if alpha is not None:
        c.setAlpha(alpha)
    return c


def cell_colors(bg_hex):
    """Background + readable foreground for a highlighted table cell: in
    dark mode light pastel backgrounds are toned down so white text reads."""
    bg = QColor(bg_hex)
    if is_dark():
        h, s, v, a = bg.getHsvF()
        if h < 0 or s < 0.02:
            # grey/white: no hue (Qt reports -1), keep it grey instead of
            # turning it red (review 3b C4)
            bg = QColor.fromHsvF(0.0, 0.0, 0.32, a)
        else:
            bg = QColor.fromHsvF(h, min(1.0, s * 1.6 + 0.15), 0.32, a)
        return bg, QColor(tokens()["text"])
    return bg, QColor("#16181d")


def tint(item, bg):
    """Highlight a table cell so it reads in both themes."""
    b, f = cell_colors(QColor(bg).name())
    item.setBackground(b)
    item.setForeground(f)
    return item
