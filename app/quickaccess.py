"""Fewer clicks (Nov 4, Jon: "QuantiSheet makes people click around too
much to find and use features"; the 10 fixes from Chief's review).

  1. Quick bar under the ribbon in every layout: the pinned tools (the
     same list as Simple Menus' Pinned group), right-click any ribbon
     button > Pin to Quick Bar, drag to reorder, right-click to unpin.
  2. Right-click on empty paper: Set Scale, Length / Area / Count, Edit
     Text Here, Redact Area, Snapshot, New RFI Here, Paste.
  3. Ctrl+K also finds sheets ("A2.1"), takeoff items, Tool Chest tools
     and RFIs, and "Show Me Where" lights up a command's ribbon button.
  4. Auto scale when a set opens (title-block scales that read cleanly);
     the scale chip in the status bar is a button (calibrate, presets).
  5. Number keys 1-9 pick the first nine Tool Chest tools.
  6. One Export button that remembers the last export.
  7. One Compare window: Overlay / Changes / Text, newest revision picked.
  8. Double-click PDF text with the Select tool to edit it in place.
  9. (panels.ThumbList) drop a PDF on Pages to insert it there; drag a
     page out to Explorer to extract it.
 10. Fewer ribbon tabs (Module, Billing, Civil and AI fold into the tabs
     they belong to), tabs follow the open file, a first-run choice
     (Estimator / Project Manager / Office) and editable shortcuts.

Nothing here makes a command - it places existing ones (found by name
with MainWindow.command), so a renamed command is skipped and logged.
"""
import logging
import json
import os
import re

from PySide6.QtCore import QMimeData, QObject, QPoint, Qt, QTimer
from PySide6.QtGui import QAction, QDrag, QKeySequence, QShortcut
from PySide6.QtWidgets import (QButtonGroup, QDialog, QDialogButtonBox,
                               QFileDialog, QHBoxLayout, QHeaderView,
                               QKeySequenceEdit, QLabel, QLineEdit, QMenu,
                               QMessageBox, QPushButton, QRadioButton,
                               QTableWidget, QTableWidgetItem, QToolBar,
                               QToolButton, QVBoxLayout)

from . import settings

log = logging.getLogger(__name__)

# ---- 10. fewer tabs ----------------------------------------------------------------

# (tab, group or None for every group) -> (new tab, new group name)
PDF_TAB = "PDF Management"
FOLD = [
    (("Module", None), ("Project", "{g}")),
    # Nov 5: Billing is its own tab again, right after Project - with it
    # folded in, Project held twelve groups and scrolled off the screen
    (("Civil", None), ("Estimate", "Civil {g}")),
    (("AI", "Takeoff"), ("Takeoff", "AI Takeoff")),
    # Nov 5: one Schedule group (Schedule From Plans + Master Schedule) and
    # the Submittal Log beside the other documents - Project had 12 groups
    (("AI", "Schedule"), ("Project", "Schedule")),
    (("Project", "Submittals"), ("Project", "Documents")),
    (("AI", "Voice"), ("Tools", "Voice")),
    # (AI > Review stays on the AI tab - Chief's user test, Nov 6: it was
    # on both the AI and the Review tabs)
    # Nov 6 (Jon): every PDF tool on one "PDF Management" tab - create,
    # combine, export, organize pages, edit, forms, sign, protect
    (("Pages", None), (PDF_TAB, "{g}")),
    (("Document", None), (PDF_TAB, "{g}")),
    (("Tools", "Convert"), (PDF_TAB, "Create & Convert")),
]
# left to right on the PDF Management tab
PDF_GROUPS = ("Create & Convert", "Pages", "Page Marks", "Content", "Forms",
              "Sign", "E-Sign", "Protect", "Standards")
# left to right (Nov 5); the classic tabs fit in where they used to be
TAB_ORDER = ("Home", "PDF Management", "Markup", "Takeoff", "Estimate",
             "Civil", "Review", "AI", "Project", "Module", "Billing",
             "Service", "Pages", "Document", "Tools", "Help")
S_CLASSIC = "classic_tabs"          # all 14 tabs, as before
S_FOLLOW = "tabs_follow_file"
S_ROLE = "role"
S_SHOW_ALL = "show_all_tabs"


def fold(tab, group):
    """Where a ribbon group goes now (tab, group)."""
    if settings.get(S_CLASSIC, False):
        return tab, group
    for (t, g), (nt, ng) in FOLD:
        if t == tab and (g is None or g == group):
            return nt, ng.format(g=group)
    return tab, group


# tabs a role doesn't need (Show All Tabs brings them back)
ROLES = {
    "estimator": {"label": "Estimator",
                  "about": "Takeoff, pricing and bids",
                  "hide": set(),
                  "pins": ["Calibrate (Set Scale)", "Length", "Area", "Count",
                           "Cloud", "Text Box", "Compare", "Show Unpriced Markups"]},
    "pm": {"label": "Project Manager",
           "about": "RFIs, submittals, changes and billing",
           "hide": {"Estimate"},
           "pins": ["New RFI", "RFI / Submittal Log", "Submittal Log",
                    "Compare", "Cloud", "Text Box", "Punch List",
                    "Project Center"]},
    "service": {"label": "Service",
                "about": "Service calls, equipment records and quotes",
                "hide": {"Takeoff"},
                # the service desk first (reviews 1 + 2, Nov 4)
                "pins": ["Service Work Order", "Dispatch Board", "T&M Tag",
                         "Backflow Test Report", "Service Agreements",
                         "Equipment & Service Records",
                         "Customer Quote With Options", "Print"]},
    "office": {"label": "Office",
               "about": "Combining, signing and sending documents",
               "hide": {"Takeoff", "Estimate"},
               # approvals live in Back Office: its button comes first
               # (skipped when Back Office isn't installed)
               "pins": ["QuantiSheet Back Office", "Open", "Combine Files",
                        "Edit Text", "Signature", "Request Signatures",
                        "Organize Pages", "Print"]},
}
# with no file open, these tabs have nothing to work on
# (Nov 6, Jon: Takeoff stays on the top ribbon, file or not)
NO_FILE_HIDE = {"Markup", "Review", "Pages", "Document",
                "Billing"}                 # billing lives in the open PDF
# a document (letters, specs, contracts - nothing bigger than legal size)
DOC_HIDE = set()                 # Takeoff stays (Jon, Nov 6)
LEGAL = (8.5 * 72 + 2, 14 * 72 + 2)


def is_text_document(doc, sample=12):
    """True when every page (of the first `sample`) is letter / legal
    size, either way round - a spec book or contract, not drawings."""
    try:
        n = min(doc.page_count, sample)
        if not n:
            return False
        for i in range(n):
            r = doc[i].rect
            a, b = sorted((r.width, r.height))
            if a > LEGAL[0] or b > LEGAL[1]:
                return False
        return True
    except Exception:                                     # noqa: BLE001
        return False


def hidden_tabs(doc):
    if settings.get(S_SHOW_ALL, False):
        return set()
    hide = set(ROLES.get(settings.get(S_ROLE) or "", {}).get("hide", ()))
    if settings.get(S_FOLLOW, True):
        if doc is None:
            hide |= NO_FILE_HIDE
        elif is_text_document(doc):
            hide |= DOC_HIDE
    return hide


def update_tabs(win):
    """Show the ribbon tabs that fit the open file and role."""
    try:
        rb = getattr(win, "ribbon", None)
        if rb is None:
            return set()
        v = getattr(win, "_view", None)
    except RuntimeError:                  # the window is gone (closing)
        return set()
    hide = hidden_tabs(v.doc if v is not None else None)
    # never pull the tab you're on out from under you, and never jump to
    # Home (review 2, Nov 4): it hides once you've moved to another tab
    cur = rb.current()
    for name, p in rb.pages.items():
        p.tab_button.setVisible(name not in hide or name in ("Home", cur))
    return hide


# ---- 1. quick bar ----------------------------------------------------------------

DEFAULT_PINS = ["Calibrate (Set Scale)", "Length", "Area", "Count", "Cloud",
                "Text Box", "Compare", "Show Unpriced Markups"]
MIME = "application/x-quantisheet-pin"


def _key(text):
    from .ribbon import clean
    return clean(text).replace("…", "").rstrip(". ").strip().lower()


def pins():
    p = settings.get("pinned_tools")
    return list(p) if p else list(DEFAULT_PINS)


def set_pins(names):
    out, seen = [], set()
    for n in names:
        if _key(n) not in seen:
            seen.add(_key(n))
            out.append(n)
    settings.set("pinned_tools", out)
    return out


def is_pinned(name):
    return _key(name) in {_key(p) for p in pins()}


def pin(win, name, on=True):
    p = [x for x in pins() if _key(x) != _key(name)]
    if on:
        p.append(name)
    set_pins(p)
    refresh(win)
    return pins()


def move_pin(win, name, to):
    p = [x for x in pins() if _key(x) != _key(name)]
    p.insert(max(0, min(len(p), to)), name)
    set_pins(p)
    refresh(win)
    return pins()


def refresh(win):
    qb = getattr(win, "quick_bar", None)
    if qb is not None:
        qb.rebuild()
    sm = getattr(win, "simple_menu", None)
    if sm is not None:
        try:
            sm.build()
        except Exception:                                 # noqa: BLE001
            log.debug("simple menus rebuild", exc_info=True)


def find(win, name):
    a = win.command(name)
    if a is None:
        sm = getattr(win, "simple_menu", None)
        if sm is not None:
            a = sm._find(name)
    return a


class PinButton(QToolButton):
    """A quick bar button: click runs it, drag reorders, right-click to
    unpin or move."""

    def __init__(self, bar, name, action):
        super().__init__(bar)
        self.bar, self.name = bar, name
        self.setDefaultAction(action)
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        from .ribbon import clean
        self.setText(clean(action.iconText() or action.text())
                     .replace("…", "").replace("&", "&&"))
        self.setObjectName("QuickButton")
        self._press = None

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._press = e.position().toPoint()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._press is not None and (e.position().toPoint() -
                                        self._press).manhattanLength() > 12:
            self._press = None
            self.setDown(False)
            md = QMimeData()
            md.setData(MIME, self.name.encode("utf-8"))
            d = QDrag(self)
            d.setMimeData(md)
            d.setPixmap(self.grab())
            d.exec(Qt.MoveAction)
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._press = None
        super().mouseReleaseEvent(e)

    def contextMenuEvent(self, e):
        m = QMenu(self)
        i = self.bar.names().index(self.name)
        m.addAction("Unpin From Quick Bar",
                    lambda: pin(self.bar.win, self.name, False))
        m.addAction("Move Left", lambda: move_pin(self.bar.win, self.name,
                                                  i - 1)).setEnabled(i > 0)
        m.addAction("Move Right", lambda: move_pin(self.bar.win, self.name,
                                                   i + 1)).setEnabled(
            i < len(self.bar.names()) - 1)
        m.addSeparator()
        m.addAction("Restore Default Pins", lambda: (set_pins(DEFAULT_PINS),
                                                     refresh(self.bar.win)))
        m.exec(e.globalPos())


class QuickBar(QToolBar):
    def __init__(self, win):
        super().__init__("Quick Bar", win)
        self.win = win
        self.setObjectName("quick_bar")
        self.setMovable(False)
        self.setFloatable(False)
        self.setAcceptDrops(True)
        self.setContextMenuPolicy(Qt.PreventContextMenu)
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.buttons = []
        self.export_button = None
        self.rebuild()

    def names(self):
        return [b.name for b in self.buttons]

    def rebuild(self):
        self.clear()
        self.buttons = []
        lab = QLabel("  Quick  ")
        lab.setObjectName("QuickLabel")
        lab.setToolTip("Your pinned tools. Right-click any ribbon button > "
                       "Pin to Quick Bar; drag these to reorder.")
        self.addWidget(lab)
        for n in pins():
            a = find(self.win, n)
            if a is None:
                log.info("quick bar: no command named %s", n)
                continue
            b = PinButton(self, n, a)
            self.addWidget(b)
            self.buttons.append(b)
        self.addSeparator()
        self.export_button = export_button(self.win, self)
        self.addWidget(self.export_button)

    def _index_at(self, x):
        for i, b in enumerate(self.buttons):
            g = b.geometry()
            if x < g.center().x():
                return i
        return len(self.buttons)

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(MIME):
            e.acceptProposedAction()

    dragMoveEvent = dragEnterEvent

    def dropEvent(self, e):
        if not e.mimeData().hasFormat(MIME):
            return
        name = bytes(e.mimeData().data(MIME)).decode("utf-8")
        to = self._index_at(e.position().toPoint().x())
        old = self.names().index(name) if name in self.names() else None
        if old is not None and old < to:
            to -= 1
        e.acceptProposedAction()
        QTimer.singleShot(0, lambda: move_pin(self.win, name, to))


def install_quick_bar(win):
    win.addToolBarBreak(Qt.TopToolBarArea)
    bar = QuickBar(win)
    win.addToolBar(Qt.TopToolBarArea, bar)
    win.quick_bar = bar
    app = win.window()
    _PinMenu(win).install(app)
    return bar


class _PinMenu:
    """Right-click a ribbon button: Pin to / Unpin From Quick Bar."""

    def __init__(self, win):
        self.win = win

    def install(self, _w):
        from PySide6.QtCore import QObject
        from PySide6.QtWidgets import QApplication

        class F(QObject):
            def eventFilter(f, obj, ev):                  # noqa: N805
                return self.filter(obj, ev)
        self._f = F(self.win)
        QApplication.instance().installEventFilter(self._f)

    def filter(self, obj, ev):
        from PySide6.QtCore import QEvent
        from .ribbon import RibbonButton
        if ev.type() != QEvent.ContextMenu or not isinstance(obj,
                                                             RibbonButton):
            return False
        if obj.window() is not self.win:
            return False
        a = obj.defaultAction()
        if a is None:
            return False
        menu_for_button(self.win, a).exec(ev.globalPos())
        return True


def menu_for_button(win, a):
    from .ribbon import clean
    name = clean(a.text()).replace("…", "").rstrip(". ").strip()
    m = QMenu(win)
    if is_pinned(name):
        m.addAction("Unpin From Quick Bar", lambda: pin(win, name, False))
    else:
        m.addAction("Pin to Quick Bar", lambda: pin(win, name, True))
    return m


# ---- 2. right-click on empty paper -----------------------------------------------------

def page_menu_items(win, page_pt=None):
    """(label, callable) rows added to the paper's right-click menu."""
    v = win._view
    rows = []

    def cmd(label, name):
        a = find(win, name)
        if a is not None and a.isEnabled():
            rows.append((label, a.trigger))
    cmd("Set Scale…", "Calibrate (Set Scale)")
    cmd("Length", "Length")
    cmd("Area", "Area")
    cmd("Count", "Count")
    if v is not None and page_pt is not None:
        try:
            blk = v.block_at(page_pt)
        except Exception:                                 # noqa: BLE001
            blk = None
        if blk is not None:
            rows.append(("Edit Text Here", lambda: v.edit_text_here(page_pt)))
    cmd("Redact Area", "Redact")
    cmd("Snapshot", "Snapshot")
    if v is not None and page_pt is not None:
        rows.append(("New RFI Here…", lambda: win.new_rfi_at(page_pt)))
    # the last tools used (review QS-035)
    from .viewer import TOOLS
    for tool in list(getattr(win, "_recent_tools", []))[:3]:
        label = TOOLS.get(tool, (tool,))[0] if tool in TOOLS else tool
        rows.append((f"Again: {label}",
                     lambda t=tool: win.set_tool(t, ask=False)))
    if v is not None:
        rows.append(("Rotate This Page",
                     lambda: win._page_action("rotate_right", [v.page])))
        rows.append(("Insert Pages From PDF Here…",
                     lambda: win._page_action("insert_pdf", [v.page])))
    from . import takeoffclip
    if v is not None and takeoffclip.ready():
        from . import annotate
        at = annotate.to_page(v.pg, page_pt) if page_pt is not None else None
        rows.append(("Paste Here", lambda: takeoffclip.paste(v, at)))
        rows.append(("Paste in Place", lambda: takeoffclip.paste(v)))
    else:
        pa = find(win, "Paste")
        if pa is not None and pa.isEnabled():
            rows.append(("Paste", pa.trigger))
    return rows


def add_page_menu(win, menu, page_pt=None):
    rows = page_menu_items(win, page_pt)
    if rows:
        first = menu.actions()[0] if menu.actions() else None
        for label, fn in rows:
            a = QAction(label, menu)
            a.triggered.connect(lambda _c=False, f=fn: f())
            menu.insertAction(first, a)
        menu.insertSeparator(first)
    return [r[0] for r in rows]


# ---- 3. a wider Ctrl+K ------------------------------------------------------------------

def _open_service(win, what, rid):
    """Ctrl+K service hit: Equipment & Service Records on that record."""
    from .estimating import ui as est_ui
    return est_ui.open_tools(win, "service", focus=(what, rid))


def palette_extras(win):
    """[(path, QAction)] for the open set's sheets, takeoff items, Tool
    Chest tools, RFIs and submittals, punch items and changes, and
    service records - found by typing in Ctrl+K."""
    out = []
    v = win._view

    def act(text, fn, tip=""):
        a = QAction(text, win)
        a.triggered.connect(lambda _c=False, f=fn: f())
        a.setToolTip(tip)
        a.setProperty("palette_extra", True)
        return a
    if v is not None:
        try:
            from . import sheets
            for i in range(min(v.doc.page_count, 600)):
                try:
                    lab = sheets.label_for(v.doc[i]) or ""
                except Exception:                         # noqa: BLE001
                    lab = ""
                lab = lab or (v.doc[i].get_label() or "")
                text = f"Sheet {lab}" if lab else f"Page {i + 1}"
                if lab:
                    text += f"  (page {i + 1})"
                out.append(("Go to sheet", act(text, lambda i=i:
                                               win._go_page(i))))
        except Exception:                                 # noqa: BLE001
            log.debug("palette sheets", exc_info=True)
        try:
            from . import annotate
            seen = set()
            for it in annotate.totals_items(v.doc):
                name = it.get("group") or ""
                if not name or name in seen:
                    continue
                seen.add(name)
                out.append(("Takeoff item", act(
                    f"{name}  ({it['type']})",
                    lambda it=it: win._go_annot(it["page"], it["ref"]))))
        except Exception:                                 # noqa: BLE001
            log.debug("palette takeoff", exc_info=True)
        try:
            from . import rfilog
            for r in rfilog.items(v.doc):
                label = f"{r.get('kind') or 'RFI'} {r.get('number') or ''}: " \
                        f"{r.get('title') or ''}".replace("  ", " ")
                page = r.get("page")
                out.append(("RFI", act(label, lambda r=r: _go_rfi(win, r))))
        except Exception:                                 # noqa: BLE001
            log.debug("palette rfis", exc_info=True)
        try:             # punch items and changes (review 2, Nov 4)
            from . import qa
            for p in qa.punch(v.doc)[:1000]:
                label = f"Punch {p.get('id') or ''}: " \
                        f"{p.get('description') or ''}"
                if p.get("page") is not None:
                    go = (lambda p=p: win._go_page(int(p["page"])))
                else:
                    go = (lambda: win.quality(0))
                out.append(("Punch item", act(label, go)))
        except Exception:                                 # noqa: BLE001
            log.debug("palette punch", exc_info=True)
        try:
            from . import money
            for c in money.changes(v.doc)[:1000]:
                num = c.get("co_no") or c.get("cor_no") or c.get("id") or ""
                out.append(("Change", act(
                    f"Change {num}: {c.get('title') or ''}",
                    lambda: win.billing("Change Orders"))))
        except Exception:                                 # noqa: BLE001
            log.debug("palette changes", exc_info=True)
    try:                 # service records: properties and their equipment
        from .estimating import service
        store = service.load()
        svc = win.command("Equipment & Service Records")
        for pr in store.get("properties", [])[:500]:
            name = " ".join(x for x in (pr.get("name"), pr.get("address"))
                            if x)
            if svc is not None and name:        # opens on that record
                out.append(("Service record", act(
                    f"Service: {name}",
                    lambda pid=pr.get("id"): _open_service(
                        win, "property", pid))))
        for eq in store.get("equipment", [])[:1000]:
            label = " ".join(x for x in (eq.get("kind"), eq.get("make"),
                                         eq.get("model"), eq.get("serial"))
                             if x)
            if svc is not None and label:
                out.append(("Service record", act(
                    f"Equipment: {label}",
                    lambda eid=eq.get("id"): _open_service(
                        win, "equipment", eid))))
    except Exception:                                     # noqa: BLE001
        log.debug("palette service records", exc_info=True)
    try:
        for k, item in enumerate(chest_tools(win)):
            out.append(("Tool Chest", act(
                f"{item.get('name')}" + (f"   key {k + 1}" if k < 9 else ""),
                lambda item=item: win.use_chest_tool(item))))
    except Exception:                                     # noqa: BLE001
        log.debug("palette chest", exc_info=True)
    return out


def _go_rfi(win, r):
    page, ref = r.get("page"), r.get("markup")
    if page is None:
        dock = getattr(win, "rfi_dock", None)
        if dock is not None:
            dock.show()
            dock.raise_()
        return
    if ref:
        win._go_annot(int(page), ref)
    else:
        win._go_page(int(page))


def where_is(win, a):
    """The ribbon tab and button for an action (or None)."""
    from .ribbon import RibbonButton
    rbs = [r for r in (getattr(win, "ribbon", None),
                       getattr(getattr(win, "simple_menu", None), "ribbon",
                               None)) if r is not None]
    rbs.sort(key=lambda r: not r.isVisible())      # the one on screen first
    for rb in rbs:
        for name, p in rb.pages.items():
            for b in p.findChildren(RibbonButton):
                if b.defaultAction() is a:
                    return rb, name, b
    return None


def reveal(win, a, ms=2200):
    """Show me where: open the tab and light up the button. Returns the
    tab's name or None."""
    hit = where_is(win, a)
    if hit is None:
        return None
    rb, name, b = hit
    rb.page(name).tab_button.setVisible(True)
    rb.show_page(name)
    old = b.styleSheet()
    b.setStyleSheet("QToolButton { border: 2px solid #f5a623; "
                    "border-radius: 4px; background: rgba(245,166,35,60); }")
    # the button as the timer's context: if the ribbon is rebuilt and the
    # button goes first, the timer is dropped instead of touching it
    QTimer.singleShot(ms, b, lambda: b.setStyleSheet(old))
    return name


# ---- 5. number keys for the Tool Chest -----------------------------------------------

def chest_tools(win):
    """Tool Chest tools in the order the panel shows them."""
    chest = getattr(getattr(win, "chest", None), "chest", None)
    if chest is None:
        from . import toolchest
        chest = toolchest.load()
    out = []
    for _group, items in chest.items():
        out += [i for i in items if isinstance(i, dict) and i.get("tool")]
    return out


def number_key(win, n):
    tools = chest_tools(win)
    if 1 <= n <= min(9, len(tools)):
        win.use_chest_tool(tools[n - 1])
        return tools[n - 1]
    return None


# ---- 6. one Export -----------------------------------------------------------------

EXPORT = re.compile(r"\bexport\b|to excel|\bcsv\b|link quantities", re.I)
S_LAST_EXPORT = "last_export"


def export_actions(win):
    """[(label, action)] of every export command, once each."""
    from .ribbon import all_actions, clean
    seen, out = set(), []
    for _path, a in all_actions(win.menuBar()):
        t = clean(a.text()).replace("…", "").strip()
        if EXPORT.search(t) and t not in seen and not a.menu():
            seen.add(t)
            out.append((t, a))
    out.sort(key=lambda r: r[0].lower())
    return out


def run_export(win, label):
    for t, a in export_actions(win):
        if t == label:
            settings.set(S_LAST_EXPORT, t)
            b = getattr(getattr(win, "quick_bar", None), "export_button",
                        None)
            if b is not None:
                b.setText(f"Export: {t}"[:34])
            a.trigger()
            return a
    return None


def export_button(win, parent):
    b = QToolButton(parent)
    b.setObjectName("ExportButton")
    b.setPopupMode(QToolButton.MenuButtonPopup)
    last = settings.get(S_LAST_EXPORT) or ""
    b.setText(f"Export: {last}"[:34] if last else "Export")
    b.setToolTip("Export - click to repeat the last one, or pick from the "
                 "list")
    m = QMenu(b)

    def fill():
        m.clear()
        for t, a in export_actions(win):
            x = m.addAction(t, lambda t=t: run_export(win, t))
            x.setEnabled(a.isEnabled())
    m.aboutToShow.connect(fill)
    b.setMenu(m)

    def main():
        last = settings.get(S_LAST_EXPORT)
        if last and run_export(win, last):
            return
        b.showMenu()
    b.clicked.connect(main)
    return b


# ---- 7. one Compare ---------------------------------------------------------------

MODES = [("overlay", "Overlay", "Old in red, new in green, on top of each "
          "other (sheet by sheet, lined up)"),
         ("changes", "Changes", "Changed areas outlined on the new set"),
         ("text", "Text", "Words added and removed, as a report")]


def newest_revision(path):
    """The most likely other revision of `path`: the newest PDF in its
    folder (and its parent's subfolders one level down) whose name shares
    the first word, else the newest PDF there. None when there is none."""
    if not path:
        return None
    folder = os.path.dirname(os.path.abspath(path))
    me = os.path.normcase(os.path.abspath(path))
    stem = re.split(r"[\s_\-.]+", os.path.splitext(os.path.basename(path))[0]
                    .lower())[0]
    cands = []
    try:
        for f in os.listdir(folder):
            p = os.path.join(folder, f)
            if f.lower().endswith(".pdf") and \
                    os.path.normcase(os.path.abspath(p)) != me and \
                    os.path.isfile(p):
                cands.append(p)
    except OSError:
        return None
    if not cands:
        return None
    alike = [p for p in cands if stem and
             os.path.basename(p).lower().startswith(stem)]
    pool = alike or cands
    return max(pool, key=lambda p: os.path.getmtime(p))


class CompareDialog(QDialog):
    def __init__(self, win, other=None):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Compare")
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("<b>Compare this set with another revision</b>"))
        row = QHBoxLayout()
        self.other = QLineEdit(other or newest_revision(win._path) or "")
        self.other.setPlaceholderText("The other revision (PDF)")
        pick = QPushButton("Browse…")
        pick.clicked.connect(self._browse)
        row.addWidget(self.other, 1)
        row.addWidget(pick)
        lay.addLayout(row)
        self.group = QButtonGroup(self)
        last = settings.get("compare_mode") or "overlay"
        for i, (key, label, about) in enumerate(MODES):
            rb = QRadioButton(f"{label} - {about}")
            rb.setProperty("mode", key)
            rb.setChecked(key == last)
            self.group.addButton(rb, i)
            lay.addWidget(rb)
        note = QLabel("<small>Newest revision in the same folder is picked "
                      "for you. Revision Log (Review tab) keeps the history."
                      "</small>")
        note.setWordWrap(True)
        lay.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Compare")
        bb.accepted.connect(self.go)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _browse(self):
        p, _ = QFileDialog.getOpenFileName(self, "Compare With",
                                           os.path.dirname(self.other.text()),
                                           "PDF (*.pdf)")
        if p:
            self.other.setText(p)

    def mode(self):
        b = self.group.checkedButton()
        return b.property("mode") if b is not None else "overlay"

    def go(self):
        other = self.other.text().strip().strip('"')
        if not other or not os.path.isfile(other):
            QMessageBox.information(self, "Compare",
                                    "Pick the other revision first.")
            return None
        mode = self.mode()
        settings.set("compare_mode", mode)
        self.accept()
        w = self.win
        if mode == "overlay":
            return w.compare_revisions(other)
        if mode == "changes":
            return w.compare_visual(other)
        return w.compare_with(other)


# ---- 10. first run: who uses this copy ----------------------------------------------

S_WELCOME = "welcome_done"


def needs_welcome():
    if settings.get(S_WELCOME):
        return False
    try:
        used = bool(settings.recent())     # been using it already
    except Exception:                                     # noqa: BLE001
        used = False
    if used:
        settings.set(S_WELCOME, True)
        return False
    return True


def apply_role(win, role):
    r = ROLES.get(role)
    if r is None:
        return None
    settings.set(S_ROLE, role)
    set_pins(r["pins"])
    refresh(win)
    update_tabs(win)
    return role


class WelcomeDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.role = None
        self.setWindowTitle("Welcome to QuantiSheet")
        lay = QVBoxLayout(self)
        t = QLabel("<h3>What do you mostly do?</h3>QuantiSheet sets up your "
                   "quick bar and tabs to match. You can change this any time "
                   "(View > Ribbon Tabs > Show All Tabs, or right-click a button > "
                   "Pin to Quick Bar).")
        t.setWordWrap(True)
        lay.addWidget(t)
        for key, r in ROLES.items():
            b = QPushButton(f"{r['label']}  -  {r['about']}")
            b.setMinimumHeight(40)
            b.clicked.connect(lambda _c=False, k=key: self.pick(k))
            lay.addWidget(b)
        skip = QPushButton("Skip")
        skip.clicked.connect(lambda: self.pick(None))
        lay.addWidget(skip)
        # QS-038: the other first-day questions, on the same screen
        from PySide6.QtWidgets import QCheckBox
        self.tour = QCheckBox("Show me around after this (about a minute)")
        self.tour.setChecked(True)
        lay.addWidget(self.tour)
        more = QHBoxLayout()
        bring = QPushButton("Bring My Data From Another PC…")
        bring.setToolTip("Restore a QuantiSheet data backup (Tools > Back "
                         "Up My QuantiSheet Data on the old PC).")
        bring.clicked.connect(lambda: self.bring_data())
        keys = QPushButton("Keyboard Shortcuts…")
        keys.clicked.connect(lambda: self.show_keys())
        more.addWidget(bring)
        more.addWidget(keys)
        lay.addLayout(more)

    def bring_data(self):
        try:
            self.win.restore_data()
        except Exception:                                 # noqa: BLE001
            log.warning("restore from welcome", exc_info=True)

    def show_keys(self):
        try:
            ShortcutsDialog(self.win).exec()
        except Exception:                                 # noqa: BLE001
            log.warning("shortcuts from welcome", exc_info=True)

    def pick(self, role):
        self.role = role
        if role:
            apply_role(self.win, role)
        settings.set(S_WELCOME, True)
        self.accept()


S_UPGRADE_CARD = "ribbon_changed_card_111"


def needs_upgrade_card():
    """Someone who used an earlier version and hasn't picked a role or
    seen the card: the ribbon looks different to them (reviews 1 + 2)."""
    if settings.get(S_UPGRADE_CARD) or settings.get(S_ROLE):
        return False
    try:
        return bool(settings.recent())
    except Exception:                                     # noqa: BLE001
        return False


class UpgradeCard(QDialog):
    """Once, after updating: what changed on the ribbon, a role, and a
    way back to the old layout."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.choice = None
        self.setWindowTitle("The Ribbon Changed")
        lay = QVBoxLayout(self)
        t = QLabel(
            "<h3>QuantiSheet 1.1.1 has fewer tabs</h3>"
            "Module, Billing, Civil and AI moved onto the tabs where they're "
            "used (Project, Estimate, Takeoff, Tools and Review). Your "
            "favourite commands are on the <b>quick bar</b> under the "
            "ribbon, and <b>Ctrl+K</b> finds any command and shows where it "
            "lives.<br><br>Pick what you mostly do to set up the quick bar, "
            "or keep everything as it is now.")
        t.setWordWrap(True)
        lay.addWidget(t)
        for key, r in ROLES.items():
            b = QPushButton(f"{r['label']}  -  {r['about']}")
            b.clicked.connect(lambda _c=False, k=key: self.pick(k))
            lay.addWidget(b)
        row = QHBoxLayout()
        keep = QPushButton("Keep the New Layout")
        keep.setDefault(True)
        keep.clicked.connect(lambda: self.pick(None))
        back = QPushButton("Put It Back How It Was")
        back.setToolTip("All 14 tabs, as in 1.0.x (from the next start). "
                        "View > Ribbon Tabs changes it again.")
        back.clicked.connect(lambda: self.classic())
        row.addWidget(keep)
        row.addWidget(back)
        lay.addLayout(row)

    def pick(self, role):
        self.choice = role or "keep"
        if role:
            apply_role(self.win, role)
        settings.set(S_UPGRADE_CARD, True)
        self.accept()

    def classic(self):
        self.choice = "classic"
        settings.set(S_CLASSIC, True)
        settings.set(S_UPGRADE_CARD, True)
        try:
            self.win._flash("The old tabs come back the next time "
                            "QuantiSheet starts", 8000)
        except Exception:                                 # noqa: BLE001
            pass
        self.accept()


def first_run(win, show=True, tour=True):
    if needs_upgrade_card():
        card = UpgradeCard(win)
        if show:
            card.exec()
        return card
    if not needs_welcome():
        return None
    dlg = WelcomeDialog(win)
    if not show:
        return dlg
    dlg.exec()
    if tour and dlg.tour.isChecked():
        QTimer.singleShot(300, win.welcome_tour)
    return dlg


# ---- 10. editable shortcuts ---------------------------------------------------------

S_KEYS = "custom_shortcuts"


def apply_shortcuts(win):
    """The person's own shortcuts on top of the built-in ones."""
    n = 0
    for name, seq in (settings.get(S_KEYS) or {}).items():
        a = win.command(name)
        if a is not None:
            a.setShortcut(QKeySequence(seq))
            n += 1
    return n


def set_shortcut(win, name, seq):
    """Give a command a shortcut ('' clears it). Returns the command that
    had it before (now cleared), or None."""
    from .ribbon import clean
    a = win.command(name)
    if a is None:
        raise KeyError(name)
    keys = dict(settings.get(S_KEYS) or {})
    taken = None
    if seq:
        ks = QKeySequence(seq)
        for other in set(win._cmd.values()):
            if other is not a and not other.shortcut().isEmpty() and \
                    other.shortcut().matches(ks) == QKeySequence.ExactMatch:
                taken = other
                other.setShortcut(QKeySequence())
                keys[_key(clean(other.text()))] = ""
    a.setShortcut(QKeySequence(seq))
    keys[_key(clean(a.text()))] = seq
    settings.set(S_KEYS, keys)
    return taken


class ShortcutsDialog(QDialog):
    """Tools > Customize Shortcuts: every command, its keys, editable."""

    def __init__(self, win):
        super().__init__(win)
        from .ribbon import clean
        self.win = win
        self.setWindowTitle("Customize Shortcuts")
        self.resize(640, 560)
        lay = QVBoxLayout(self)
        self.find = QLineEdit()
        self.find.setPlaceholderText("Find a command")
        self.find.textChanged.connect(self._filter)
        lay.addWidget(self.find)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Command", "Shortcut"])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        self.table.verticalHeader().hide()
        lay.addWidget(self.table, 1)
        self.rows = sorted({clean(a.text()).replace("…", "").strip(): a
                            for a in set(win._cmd.values())
                            if clean(a.text()).strip()}.items())
        self.table.setRowCount(len(self.rows))
        self.edits = {}
        for r, (name, a) in enumerate(self.rows):
            self.table.setItem(r, 0, QTableWidgetItem(name))
            e = QKeySequenceEdit(a.shortcut())
            e.editingFinished.connect(lambda n=name, e=e: self._set(n, e))
            self.table.setCellWidget(r, 1, e)
            self.edits[name] = e
        self.note = QLabel("Click a shortcut and press the new keys. A key "
                           "another command had moves here (that one is "
                           "cleared).")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        reset = bb.addButton("Reset All", QDialogButtonBox.ResetRole)
        reset.clicked.connect(self.reset)
        bb.rejected.connect(self.accept)
        lay.addWidget(bb)

    def _filter(self, text):
        t = text.lower()
        for r, (name, _a) in enumerate(self.rows):
            self.table.setRowHidden(r, bool(t) and t not in name.lower())

    def _set(self, name, edit):
        seq = edit.keySequence().toString()
        taken = set_shortcut(self.win, name, seq)
        if taken is not None:
            from .ribbon import clean
            tn = clean(taken.text()).replace("…", "").strip()
            if tn in self.edits:
                self.edits[tn].setKeySequence(QKeySequence())
            self.note.setText(f"{seq} moved here from {tn}.")
        return taken

    def reset(self):
        settings.set(S_KEYS, {})
        self.note.setText("Shortcuts go back to the built-in ones the next "
                          "time QuantiSheet starts.")


# ---- hidden commands on the ribbon (review QS-037, Chief's lists) ------------------

def _need_selection(win):
    v = win._view
    if v is None or not v.selected:
        win._flash("Select a takeoff measurement on the drawing first", 5000)
        return None
    return v


def _sel_cmd(win, fn):
    def run():
        v = _need_selection(win)
        if v is not None:
            return fn(v)
        return None
    return run


def _count_group(v):
    g = v._selected_count_group()
    if not g:
        v.status.emit("Select a count marker first")
    return g


def _convert_menu(win, button):
    from . import measure_tools
    m = QMenu(button)

    def fill():
        m.clear()
        v = win._view
        sel = measure_tools.selected_measure(v) if v is not None else None
        ch = measure_tools.convert_choices(sel) if sel else []
        if not ch:
            m.addAction("Select a length or area to convert").setEnabled(
                False)
        for k in ch:
            m.addAction(measure_tools.CONVERT[k],
                        lambda x=k: win._view.convert_selected(x))
    m.aboutToShow.connect(fill)
    return m


SELECTED = [
    ("Show Only This Item", "Only This", lambda v: v.isolate_selected()),
    ("Set Typical Count…", "Typical x", lambda v: v.ask_typical_count()),
    ("Bulk Edit Selected…", "Bulk Edit", lambda v: v.bulk_edit_dialog()),
    ("Copy Several Times…", "Copy N", lambda v: v.multiply_dialog()),
    ("Add More to This Count", "Add More",
     lambda v: (_count_group(v) and v.resume_count(_count_group(v)))),
    ("Show Uncounted Copies", "Uncounted",
     lambda v: (_count_group(v) and v.show_uncounted(_count_group(v)))),
    ("Add This Count to the Count Library", "To Library",
     lambda v: (_count_group(v) and
                v.add_to_count_library(_count_group(v)))),
]


SERVICE_LABELS = {"Service Work Order": "Work Order",
                  "Service Agreements": "Agreements",
                  "Agreement Visit Calendar": "Visit Calendar",
                  "Maintenance Checklist": "Checklist",
                  "Refrigerant Log": "Refrigerant",
                  "Backflow Test Report": "Backflow",
                  "Flat-Rate Pricebook": "Pricebook",
                  "Truck Stock": "Truck Stock",
                  "Tech Recommendations": "Recommend",
                  "T&M Tag": "T&M Tag",
                  "Build-to-Service Handover": "Handover",
                  "Dispatch Board": "Dispatch",
                  "Customer History": "History",
                  "Good / Better / Best Quotes": "GBB Quote",
                  "Tune-up Planner": "Tune-ups",
                  "Warranty Registrations": "Warranty",
                  "Changeout Proposal": "Changeout",
                  "Load Report": "Load Report"}
SERVICE_ICONS = {"Service Work Order": "workorder",
                 "Service Agreements": "contract",
                 "Agreement Visit Calendar": "calendar",
                 "Maintenance Checklist": "checklist",
                 "Refrigerant Log": "refrigerant",
                 "Backflow Test Report": "valve",
                 "Flat-Rate Pricebook": "book",
                 "Truck Stock": "truck",
                 "Tech Recommendations": "bulb",
                 "T&M Tag": "tag",
                 "Build-to-Service Handover": "handover",
                 "Dispatch Board": "dispatch",
                 "Customer History": "history",
                 "Good / Better / Best Quotes": "proposal",
                 "Tune-up Planner": "gantt",
                 "Warranty Registrations": "shield",
                 "Changeout Proposal": "replace",
                 "Load Report": "attach"}


def add_service_commands(win):
    """A Service menu with the service desk's windows (app.service.menu
    ENTRIES), each opened on first use."""
    import importlib
    try:
        from .service import menu as svc_menu
    except Exception:                                     # noqa: BLE001
        log.warning("service desk not available", exc_info=True)
        return []
    mb = win.menuBar()
    menu = next((a.menu() for a in mb.actions() if a.menu() is not None and
                 a.text().replace("&", "") == "Service"), None)
    if menu is None:
        menu = mb.addMenu("&Service")
    made = []
    for e in svc_menu.ENTRIES:
        label = e["label"]
        name = label.replace("…", "").strip()
        if win.command(name) is not None:
            made.append(win.command(name))
            continue
        mod, fn = e["call"].rsplit(".", 1)

        def run(_c=False, mod=mod, fn=fn, name=name):
            try:
                m = importlib.import_module(mod)
                w = getattr(m, fn)(win)
                win._service_windows = getattr(win, "_service_windows", [])
                win._service_windows.append(w)
                return w
            except Exception as ex:                       # noqa: BLE001
                log.warning("%s failed", name, exc_info=True)
                QMessageBox.warning(win, name, f"{name} couldn't open:\n{ex}")
                return None
        a = QAction(label.replace("&", "&&"), win)
        a.setIconText(SERVICE_LABELS.get(name, name))
        from . import icons
        glyph = SERVICE_ICONS.get(name, "info")
        a.setProperty("qs_icon", glyph)
        a.setIcon(icons.icon(glyph))
        a.triggered.connect(run)
        menu.addAction(a)
        from .ribbon import clean
        win._cmd[clean(a.text()).lower()] = a      # "t&m tag"
        made.append(a)
    return made


def add_hidden_commands(win):
    """Takeoff > Selected (what the right-click menu of a measurement
    has), and a Service tab (Equipment & Service Records, Customer Quote
    With Options; the service features join it). Returns the actions."""
    from .ribbon import RibbonButton
    rb = getattr(win, "ribbon", None)
    if rb is None:
        return []
    made = []
    menu = getattr(win, "_takeoff_selected_menu", None)
    if menu is None:
        tm = next((a.menu() for a in win.menuBar().actions()
                   if a.menu() is not None and
                   a.text().replace("&", "") == "Takeoff"), None)
        menu = tm.addMenu("Selected Measurement") if tm is not None else None
        win._takeoff_selected_menu = menu
    t, g = fold("Takeoff", "Selected")
    grp = rb.page(t).group(g)
    acts = []
    for text, label, fn in SELECTED:
        a = win.command(text)
        if a is None:
            a = QAction(text, win)
            a.setIconText(label)
            a.triggered.connect(lambda _c=False, f=fn: _sel_cmd(win, f)())
            if menu is not None:
                menu.addAction(a)
            win._cmd[_key(text)] = a
        acts.append(a)
        made.append(a)
    for a in acts[:3]:
        grp.large(a, a.iconText())
    grp.small(acts[3:])
    conv = win.command("Convert Selected To")
    if conv is None:
        conv = QAction("Convert Selected To", win)
        conv.setIconText("Convert To")
        win._cmd[_key("Convert Selected To")] = conv
    b = grp.large(conv, "Convert To", menu=_convert_menu(win, grp))
    if b is not None:
        b.setPopupMode(QToolButton.InstantPopup)
    made.append(conv)
    # also on the Takeoff menu (F10, All Tools), so the ribbon button
    # isn't the only way in
    try:
        from .ribbon import clean
        tm = next((a.menu() for a in win.menuBar().actions()
                   if a.menu() is not None and
                   clean(a.text()).lower() == "takeoff"), None)
        if tm is not None and conv not in tm.actions():
            # a plain command (All Tools lists commands, not submenus) that
            # opens the same choices where the mouse is
            from PySide6.QtGui import QCursor
            pop = _convert_menu(win, tm)
            conv.triggered.connect(
                lambda _c=False, m=pop: m.exec(QCursor.pos()))
            tm.addAction(conv)
    except Exception:                                     # noqa: BLE001
        log.debug("Convert To on the Takeoff menu", exc_info=True)
    # Service tab: the service desk (app/service, 1.1.1) plus Records and
    # option quotes. A Service menu holds the same commands (Ctrl+K, F10).
    made += add_service_commands(win)
    sv = rb.page("Service")
    groups = {"Calls": ["Service Work Order", "Dispatch Board",
                        "T&M Tag", "Customer History"],
              "Agreements": ["Service Agreements",
                             "Agreement Visit Calendar", "Tune-up Planner",
                             "Build-to-Service Handover",
                             "Warranty Registrations"],
              "Logs & Tests": ["Refrigerant Log", "Backflow Test Report",
                               "Maintenance Checklist"],
              "Pricing": ["Flat-Rate Pricebook",
                          "Good / Better / Best Quotes",
                          "Tech Recommendations", "Truck Stock"],
              "Replacement": ["Changeout Proposal", "Load Report"],
              "Settings": ["Service Settings"]}
    for title, names in groups.items():
        g3 = sv.group(title)
        acts3 = [win.command(n) for n in names]
        acts3 = [a for a in acts3 if a is not None]
        for a in acts3[:2]:
            g3.large(a, a.iconText())
        if acts3[2:]:
            g3.small(acts3[2:])
    for title, names in (("Records", ["Equipment & Service Records"]),
                         ("Quotes", ["Customer Quote With Options"])):
        g2 = sv.group(title)
        for n in names:
            a = win.command(n)
            if a is not None:
                from . import icons
                glyph = ("records" if "Service Records" in n else "proposal")
                a.setProperty("qs_icon", glyph)
                if a.icon().isNull():
                    a.setIcon(icons.icon(glyph))
                g2.large(a, n.split(" With")[0].replace(
                    "Equipment & ", ""))
                made.append(a)
    bo = win.command("QuantiSheet Back Office")
    if bo is not None:
        from . import icons
        bo.setProperty("qs_icon", "dollar")
        if bo.icon().isNull():
            bo.setIcon(icons.icon("dollar"))
        rb.page("Project").group("Office").large(bo, "Back Office")
        made.append(bo)
    return made


# ---- keyboard menus (review QS-012) ------------------------------------------------

def menus_popup(win, show=True):
    """F10 (or Alt alone): every menu from the keyboard - the menu bar is
    hidden behind the ribbon, so this is how keyboard and screen-reader
    users reach every command."""
    m = QMenu(win)
    m.setObjectName("KeyboardMenus")
    m.setAccessibleName("QuantiSheet menus")
    for a in win.menuBar().actions():
        if a.menu() is not None and a.isVisible():
            m.addMenu(a.menu())
    win._keyboard_menus = m
    if show:
        rb = getattr(win, "ribbon", None)
        at = rb.mapToGlobal(QPoint(8, 30)) if rb is not None else \
            win.mapToGlobal(QPoint(8, 8))
        m.popup(at)
        if m.actions():
            m.setActiveAction(m.actions()[0])
    return m


class _AltKey:
    """Alt pressed and let go on its own opens the menus (as Windows apps
    do); Alt with another key is left alone."""

    def __init__(self, win):
        from PySide6.QtCore import QObject

        class F(QObject):
            def eventFilter(f, obj, ev):                  # noqa: N805
                return self.filter(obj, ev)
        self.win = win
        self.alone = False
        self._f = F(win)                 # child of the window: goes with it
        from PySide6.QtWidgets import QApplication
        QApplication.instance().installEventFilter(self._f)

    def filter(self, obj, ev):
        from PySide6.QtCore import QEvent
        t = ev.type()
        if t == QEvent.KeyPress:
            self.alone = ev.key() == Qt.Key_Alt and not ev.isAutoRepeat()
        elif t == QEvent.KeyRelease and ev.key() == Qt.Key_Alt:
            try:
                active = self.win.isActiveWindow()
            except RuntimeError:                 # the window is gone
                return False
            if self.alone and active:
                self.alone = False
                QTimer.singleShot(0, lambda: menus_popup(self.win))
            self.alone = False
        elif t in (QEvent.MouseButtonPress, QEvent.Wheel):
            self.alone = False
        return False


# ---- install ---------------------------------------------------------------------

# ---- QS-039: tooltips that say what a button does -----------------------------------
# One line each, for the commands people ask about most and the ones new in
# 1.1.1. The button's own name and shortcut are added around it.
TIPS = {
    "compare": "Show what changed between two versions of a sheet: "
               "overlay, a list of changes, or the text.",
    "quick compare (same sheets)": "Overlay the same sheet from two sets "
                                   "in one click.",
    "reduce file size": "Make the PDF smaller to email. Your takeoff and "
                        "markups stay.",
    "sign": "Add a signature. Saving afterwards in a way that changes the "
            "page breaks the signature, so QuantiSheet warns you first.",
    "verify signatures": "Check who signed and whether the file changed "
                         "after signing.",
    "choose my role (estimator, pm, service, office)": "Set up tabs and the quick "
                                             "bar for the work you do most.",
    "count by label": "Find every tag like D-1 or W* on the plans and "
                      "count them.",
    "count several symbols": "Count several kinds of symbols in one pass.",
    "carry takeoff forward to a revised set": "Move your takeoff onto a "
                                             "new revision of the drawings.",
    "typical sheet (count this sheet n times)": "Count this sheet's "
                                                "takeoff more than once, "
                                                "e.g. 4 identical floors.",
    "buy quantities (sheets, boxes, rolls)": "Turn measured totals into "
                                            "what to order, with waste, "
                                            "rounded up.",
    "tags vs schedule check": "List tags drawn on the plans but not in the "
                              "schedule, and the other way round.",
    "export to sage 300 job cost (csv)": "Preview the rows, then save the "
                                         "import file and an undo "
                                         "(reversal) file next to it.",
    "insert pages from pdf": "Add pages from another PDF here.",
    "split document": "Break this PDF into smaller files.",
    "extract pages": "Save chosen pages as a new PDF.",
    "flatten markups & fields": "Burn markups into the page. Job data and "
                               "takeoff can't be edited afterwards.",
    "macros": "Run a saved list of steps. QuantiSheet checks it first and "
              "tells you what it will change.",
    "back up my quantisheet data": "Save your settings, libraries and job "
                                   "lists to one file.",
    "restore quantisheet data from a backup": "Put back a data backup. "
                                              "What you have now is saved "
                                              "first.",
    "new rfi": "Start an RFI linked to this spot on the drawing.",
    "batch slip sheet": "Swap in revised sheets across a set and keep "
                        "your takeoff.",
    "customize shortcuts": "Pick your own keys for any command.",
    "command search": "Type to find any command, sheet, takeoff item or "
                      "RFI. Shift+Enter shows where the button lives.",
    "auto scale (read sheets)": "Read each sheet's scale from its title "
                                "block. Check it before you measure.",
    "auto scale (check against dimensions)": "Check the scale against a "
                                             "dimension written on the "
                                             "sheet.",
    "link quantities to excel": "Keep an Excel workbook up to date with "
                                "your quantities.",
    "make searchable (ocr)": "Read the text on scanned pages so search "
                             "and Count by Label work.",
    "search takeoff across jobs": "Find an item in every job's takeoff.",
    "welcome tour": "A short walk around the screen.",
    "copy as table (for excel)": "Copy the selected area as rows and "
                                 "columns for Excel.",
}


def tip_text(action, label=None):
    """The tooltip for a command: name, what it does, shortcut."""
    from .ribbon import clean
    name = (label or clean(action.text())).replace("…", "").strip()
    desc = TIPS.get(name.rstrip(". ").lower())
    key = action.shortcut().toString(QKeySequence.NativeText)
    out = name + (f"  ({key})" if key else "")
    if desc:
        out += "\n" + desc
    return out


def apply_tips(win):
    """Put TIPS on the commands and on every ribbon / quick bar button.
    Returns the names in TIPS that matched a command."""
    from PySide6.QtWidgets import QToolButton
    found = []
    for name, desc in TIPS.items():
        a = win.command(name)
        if a is None:
            continue
        found.append(name)
        a.setStatusTip(desc)
        a.setToolTip(tip_text(a))
    for b in win.findChildren(QToolButton):
        a = b.defaultAction()
        if a is not None and a.statusTip() and \
                a.statusTip() in (TIPS.get(n) for n in found):
            b.setToolTip(tip_text(a))
    return found


def install(win):
    from PySide6.QtGui import QShortcut
    install_quick_bar(win)
    apply_shortcuts(win)
    try:
        add_hidden_commands(win)
    except Exception:                                     # noqa: BLE001
        log.warning("hidden commands not placed", exc_info=True)
    try:
        if getattr(win, "ribbon", None) is not None:
            win.ribbon.arrange(TAB_ORDER)
    except Exception:                                     # noqa: BLE001
        log.warning("tabs not put in order", exc_info=True)
    try:
        apply_tips(win)
    except Exception:                                     # noqa: BLE001
        log.warning("tooltips not set", exc_info=True)
    win._f10 = QShortcut(QKeySequence("F10"), win)
    win._f10.activated.connect(lambda: menus_popup(win))
    win._alt_key = _AltKey(win)
    QTimer.singleShot(0, lambda: make_chip_clickable(win))
    win.tabs.currentChanged.connect(
        lambda _i: QTimer.singleShot(0, lambda: update_tabs(win)))
    update_tabs(win)
    return win.quick_bar


# ---- 4. scale on open --------------------------------------------------------------

S_AUTO_SCALE = "auto_scale_on_open"
MAX_AUTO_PAGES = 200
# where each auto-read scale came from, kept in the file (review 1 / 2,
# Nov 4): a scale read from the title block stays "unconfirmed" after a
# save, a reopen or on another PC, until someone confirms it
SRC_FILE = "quantisheet_scale_src.json"


def scale_sources(doc):
    """{page index: {"src", "ppu", "unit", "label", "confirmed"}}."""
    from . import embfiles
    try:
        if SRC_FILE not in embfiles.names(doc):
            return {}
        d = json.loads(bytes(embfiles.get(doc, SRC_FILE)).decode("utf-8"))
        return {int(k): v for k, v in d.items() if isinstance(v, dict)}
    except Exception:                                     # noqa: BLE001
        log.debug("scale sources", exc_info=True)
        return {}


def _write_sources(doc, d):
    from . import embfiles
    embfiles.put(doc, SRC_FILE, json.dumps(
        {str(k): v for k, v in sorted(d.items())}).encode("utf-8"),
        "QuantiSheet job data")


def unconfirmed_pages(doc):
    """Pages whose scale is still the one read from the title block and
    not yet confirmed (a scale set by hand since then doesn't count)."""
    from . import annotate
    src = scale_sources(doc)
    if not src:
        return set()
    now = annotate.read_scales(doc)
    out = set()
    for pg, rec in src.items():
        cur = now.get(pg)
        if rec.get("confirmed") or not cur or not rec.get("ppu"):
            continue
        if abs(float(cur["ppu"]) - float(rec["ppu"])) <= \
                1e-6 * max(1.0, abs(float(rec["ppu"]))) and \
                cur.get("unit") == rec.get("unit"):
            out.add(pg)
    return out


def load_unconfirmed(view):
    """On open: flag the pages whose read scale was never confirmed."""
    try:
        view._auto_scaled = set(getattr(view, "_auto_scaled", set())) | \
            unconfirmed_pages(view.doc)
    except Exception:                                     # noqa: BLE001
        log.debug("unconfirmed scales on open", exc_info=True)
    return getattr(view, "_auto_scaled", set())


def scale_rows(path, pages=None):
    """Read title-block scales from a copy of the file (off the window's
    document, so it can run in the background)."""
    import fitz
    from . import autoscale
    d = fitz.open(path)
    try:
        n = min(d.page_count, MAX_AUTO_PAGES)
        return autoscale.detect(d, pages=pages if pages is not None
                                else range(n), use_ocr=False)
    finally:
        d.close()


def apply_scale_rows(win, view, rows):
    """Set the scales that read cleanly ('ok') on pages with none.
    Returns how many pages got one."""
    from . import autoscale
    if view is None or view not in win._all_views():
        return 0
    pages = {r["page"] for r in rows if r.get("ppu") and
             r["status"] == "ok" and not r.get("existing")}
    n = autoscale.apply(view.doc, rows)
    if n:
        # read, not checked: the chip says so until it's confirmed (QS-017)
        view._auto_scaled = set(getattr(view, "_auto_scaled", set())) | pages
        src = scale_sources(view.doc)
        for r in rows:
            if r["page"] in pages:
                src[r["page"]] = {"src": "titleblock", "ppu": r["ppu"],
                                  "unit": r["unit"],
                                  "label": r.get("label") or "",
                                  "confirmed": None}
        try:
            _write_sources(view.doc, src)
        except Exception:                                 # noqa: BLE001
            log.warning("scale sources not kept", exc_info=True)
        # not marked as changed: a guess alone is never auto-saved or
        # asked about on close; it is saved (still unconfirmed) with the
        # first real edit
        try:
            win._update_status()
        except Exception:                                 # noqa: BLE001
            pass
        check = sum(1 for r in rows if r["status"] == "check")
        win._flash(f"Scale read from the title block on {n} sheet(s)"
                   + (f"; {check} to check in Auto Scale" if check else "")
                   + " - click the scale in the status bar to change it",
                   9000)
    return n


def auto_scale_on_open(win, view, path, wait=False):
    """When a set opens with no scales, read them from the title blocks
    in the background and set the clean ones."""
    from . import annotate
    if view is None:
        return None
    load_unconfirmed(view)
    if not settings.get(S_AUTO_SCALE, True) or not path \
            or not os.path.isfile(path) or not path.lower().endswith(".pdf"):
        return None
    try:
        if annotate.read_scales(view.doc) or is_text_document(view.doc):
            return None
    except Exception:                                     # noqa: BLE001
        return None
    if wait:
        return apply_scale_rows(win, view, scale_rows(path))
    from . import bg
    bg.run(lambda: scale_rows(path),
           lambda rows: apply_scale_rows(win, view, rows),
           lambda e: log.info("auto scale on open: %s", e), win)
    return True


def scale_menu(win):
    """The scale chip's menu."""
    from . import takeoff
    m = QMenu(win)
    for label, name in (("Set Scale (Calibrate)…\tShift+S",
                         "Calibrate (Set Scale)"),
                        ("Read Scales From Title Blocks…",
                         "Auto Scale (Read Sheets)"),
                        ("Show Scale", "Show Scale")):
        a = find(win, name)
        if a is not None:
            m.addAction(label, a.trigger).setEnabled(a.isEnabled())
    v = win._view
    if v is not None and v.page in getattr(v, "_auto_scaled", ()):
        m.addAction("Scale Looks Right (Confirm)",
                    lambda: confirm_scale(win)).setToolTip(
            "It was read from the title block; confirm it once you've "
            "checked a known dimension")
        m.addSeparator()
    pre = m.addMenu("Standard Scales")
    for family, items in takeoff.PRESETS.items():
        sub = pre.addMenu(family)
        for name, (ppu, unit) in items:
            sub.addAction(name, lambda n=name, p=ppu, u=unit:
                          win.apply_scale_preset(n, p, u))
    pre.setEnabled(win._view is not None)
    return m


def confirm_scale(win, all_pages=True):
    """The read scales are checked: stop flagging them."""
    v = win._view
    if v is None:
        return 0
    was = set(getattr(v, "_auto_scaled", ()))
    done = was if all_pages else was & {v.page}
    n = len(done)
    v._auto_scaled = was - done
    if done:
        src = scale_sources(v.doc)
        import datetime as _dt
        stamp = {"by": os.environ.get("USERNAME") or "",
                 "at": _dt.datetime.now().isoformat(timespec="seconds")}
        for pg in done:
            if pg in src:
                src[pg]["confirmed"] = stamp
        try:
            _write_sources(v.doc, src)
            v.mark_dirty()              # a real decision: keep it
        except Exception:                                 # noqa: BLE001
            log.warning("scale confirmation not kept", exc_info=True)
    try:
        win._update_status()
    except Exception:                                     # noqa: BLE001
        pass
    return n


MEASURING = ("measure_length", "measure_polylength", "measure_area",
             "measure_wall", "trace_outline", "measure_volume")


def scale_gate(win, v, tool, ask=None):
    """Before the first measurement on a sheet whose scale was read from
    the title block and not confirmed: Confirm / Set Scale / Measure
    Anyway, once per sheet per session. Returns the tool to use
    ("calibrate" for Set Scale) or None to stop. `ask(text)` -> one of
    "confirm", "set", "anyway", None (tests pass one)."""
    if tool not in MEASURING or v is None:
        return tool
    if v.page not in getattr(v, "_auto_scaled", ()):
        return tool
    ok = getattr(v, "_scale_gate_ok", None)
    if ok is None:
        ok = v._scale_gate_ok = set()
    if v.page in ok:
        return tool
    sc = None
    try:
        sc = scale_sources(v.doc).get(v.page, {}).get("label")
    except Exception:                                     # noqa: BLE001
        pass
    text = ("The scale on this sheet" + (f" ({sc})" if sc else "") +
            " was read from the title block and hasn't been checked. "
            "Check it against a dimension you know before you measure.")
    pick = (ask or _ask_scale_gate)(win, text)
    if pick == "confirm":
        confirm_scale(win, all_pages=False)
        return tool
    if pick == "set":
        return "calibrate"
    if pick == "anyway":
        ok.add(v.page)
        return tool
    return None


def _ask_scale_gate(win, text):
    box = QMessageBox(QMessageBox.Warning, "Check the Scale", text, parent=win)
    yes = box.addButton("Scale Is Right (Confirm)", QMessageBox.AcceptRole)
    cal = box.addButton("Set Scale…", QMessageBox.ActionRole)
    any_ = box.addButton("Measure Anyway", QMessageBox.RejectRole)
    box.setDefaultButton(cal)
    box.exec()
    b = box.clickedButton()
    return {id(yes): "confirm", id(cal): "set", id(any_): "anyway"}.get(
        id(b) if b is not None else None, "anyway")


def make_chip_clickable(win):
    from PySide6.QtCore import QEvent, QObject
    chip = getattr(win, "chip_scale", None)
    if chip is None:
        return None
    chip.setCursor(Qt.PointingHandCursor)

    class F(QObject):
        def eventFilter(self, obj, ev):
            if obj is chip and ev.type() == QEvent.MouseButtonRelease and \
                    ev.button() == Qt.LeftButton:
                m = scale_menu(win)
                win._last_scale_menu = m
                m.exec(chip.mapToGlobal(QPoint(0, -m.sizeHint().height())))
                return True
            return False
    chip._qa_filter = F(chip)
    chip.installEventFilter(chip._qa_filter)
    return chip


# ======================================================================
# Fast-takeoff keys and the unpriced chip (was workflow_boost.py;
# folded Nov 4, 1.1.1)
#
# Fast-takeoff workflow helpers, added to the main window by install_takeoff_keys():
#
# - Takeoff keys: single keys for takeoff tools (L length, P polylength,
#   A area, X cutout, V volume, R auto area, T trace, C count, S set scale).
#   QuantiSheet's single keys already belong to markup tools (Bluebeam
#   style), so this is a mode: F8 or the status-bar chip flips between
#   "Keys: Markup" and "Keys: Takeoff"; the displaced markup keys are
#   parked and come back when the mode is turned off. Esc / Enter /
#   Backspace already work in the viewer (cancel / finish / last vertex).
# - Unpriced chip: "N unpriced" always in the status bar (open markups and
#   clouds not tied to a priced line, from prebid.check), click to show
#   them on the plan. Missed scope costs money, so it is never hidden.
#
# Already in v0.11.0 and left alone: the scale chip in the status bar and
# the live value drawn at the cursor while measuring (viewer
# _draw_live_value).


TAKEOFF_KEYS = {"measure_length": "L", "measure_polylength": "P",
                "measure_area": "A", "measure_cutout": "X",
                "measure_volume": "V", "auto_area": "R",
                "trace_length": "T", "count": "C", "calibrate": "S"}


class WorkflowBoost(QObject):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.takeoff_keys = False
        self._saved = {}
        self.unpriced_count = 0
        sb = win.statusBar()
        self.keys_chip = QToolButton()
        self.keys_chip.setObjectName("StatusChipButton")
        self.keys_chip.setAutoRaise(True)
        self.keys_chip.setToolTip("F8: switch single keys between markup "
                                  "tools and takeoff tools (L length, A area, "
                                  "C count, S scale...)")
        self.keys_chip.clicked.connect(lambda: self.set_takeoff_keys(not self.takeoff_keys))
        self.unpriced_chip = QToolButton()
        self.unpriced_chip.setObjectName("StatusChipButton")
        self.unpriced_chip.setAutoRaise(True)
        self.unpriced_chip.setToolTip("Markups and clouds not tied to a priced "
                                      "line - click to show them on the plan")
        self.unpriced_chip.clicked.connect(lambda: self._chip_clicked())
        sb.insertPermanentWidget(0, self.unpriced_chip)
        sb.insertPermanentWidget(0, self.keys_chip)
        self.f8 = QShortcut(QKeySequence("F8"), win)
        self.f8.activated.connect(lambda: self.set_takeoff_keys(not self.takeoff_keys))
        self._label()
        q = win.quantities
        orig = q.refresh

        def refresh(*a, **k):
            r = orig(*a, **k)
            self.refresh_unpriced()
            return r
        q.refresh = refresh
        self.refresh_unpriced()

    # ---- takeoff keys
    def set_takeoff_keys(self, on):
        acts = self.win._tool_actions
        if on == self.takeoff_keys:
            return
        if on:
            want = {k for k in TAKEOFF_KEYS.values()}
            self._saved = {t: a.shortcut() for t, a in acts.items()}
            for t, a in acts.items():                 # park clashing keys
                if a.shortcut().toString() in want and t not in TAKEOFF_KEYS:
                    a.setShortcut(QKeySequence())
            for t, key in TAKEOFF_KEYS.items():
                if t in acts:
                    acts[t].setShortcut(QKeySequence(key))
        else:
            for t, seq in self._saved.items():
                if t in acts:
                    acts[t].setShortcut(seq)
            self._saved = {}
        self.takeoff_keys = on
        self._label()
        bar = getattr(self.win, "measure_bar", None)
        if bar is not None and hasattr(bar, "set_keys_on"):
            bar.set_keys_on(on)

    def _label(self):
        on = self.takeoff_keys
        self.keys_chip.setText("Keys: Takeoff ON (F8)" if on else "Keys: Markup")
        # hard to miss when on (review QS-013): accent chip + a message
        self.keys_chip.setObjectName("StatusChipAccent" if on else
                                     "StatusChipButton")
        self.keys_chip.style().unpolish(self.keys_chip)
        self.keys_chip.style().polish(self.keys_chip)
        flash = getattr(self.win, "_flash", None)
        if flash is not None and getattr(self, "_shown_once", False):
            flash("Takeoff keys ON: L length, A area, C count, S scale... "
                  "(F8 to switch back)" if on else
                  "Markup keys back on (F8 for takeoff keys)", 5000)
        self._shown_once = True

    # ---- unpriced
    def refresh_unpriced(self, now=False):
        """The status bar's unpriced count, worked out just after the
        window has drawn (several refreshes in a row count once) - never
        while a drawing is being opened (Nov 3: a 99-sheet set with many
        markups froze on open). now=True counts straight away."""
        v = getattr(self.win, "_view", None)
        self.unpriced_chip.setVisible(v is not None)
        if v is None or getattr(v, "doc", None) is None:
            return
        if now:
            return self._count_unpriced()
        if self._big(v.doc):
            # tens of thousands of markups: counting them takes half a
            # minute, so it's done when you click (Nov 3)
            self.unpriced_chip.setText("Unpriced: click to count")
            return
        if getattr(self, "_unpriced_queued", False):
            return
        self._unpriced_queued = True
        from PySide6.QtCore import QTimer
        QTimer.singleShot(250, self._count_unpriced)

    BIG = 4000

    def _big(self, doc):
        from . import annotate
        if getattr(self, "_big_doc", (None,))[0] is not doc:
            self._big_doc = (doc, annotate.annot_count(doc) > self.BIG)
        return self._big_doc[1]

    def _count_unpriced(self):
        self._unpriced_queued = False
        v = getattr(self.win, "_view", None)
        if v is None or getattr(v, "doc", None) is None:
            return
        n = 0
        try:
            from . import prebid
            rep = prebid.check(v.doc, sheets=False)
            n = len(rep.open_markups) + len(rep.unaccounted_clouds)
        except Exception:
            n = 0
        # placeholders and allowances are priced, but not for real yet:
        # counted apart from unpriced (review QS-016)
        ph = al = 0
        try:
            from .estimating import bidgate
            for x in bidgate.placeholders(v.doc):
                if x.get("kind") == "allowance":
                    al += 1
                else:
                    ph += 1
        except Exception:                                 # noqa: BLE001
            ph = al = 0
        self.unpriced_count = n
        self.placeholder_count, self.allowance_count = ph, al
        text = f"⚠ {n} unpriced" if n else "✓ 0 unpriced"
        if ph:
            text += f" · {ph} placeholder{'s' if ph != 1 else ''}"
        if al:
            text += f" · {al} allowance{'s' if al != 1 else ''}"
        self.unpriced_chip.setText(text)
        self.unpriced_chip.setToolTip(
            "Unpriced: markups and clouds not tied to a priced line (click "
            "to show them). Placeholders: quick $/SF numbers or plugs still "
            "in the estimate. Allowances: carried amounts to replace with "
            "real prices. Estimate Error Check lists all three.")

    def _chip_clicked(self):
        if self.unpriced_chip.text().startswith("Unpriced: click"):
            from PySide6.QtCore import Qt
            from PySide6.QtWidgets import QApplication
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                self._count_unpriced()
            finally:
                QApplication.restoreOverrideCursor()
            return
        self._show_unpriced()

    def _show_unpriced(self):
        if hasattr(self.win, "toggle_unpriced"):
            self.win.toggle_unpriced(True)
        # and the takeoff lines with no price, ready to price (r42 F03)
        v = getattr(self.win, "_view", None)
        if v is not None and hasattr(self.win, "price_these"):
            from . import price_these
            if price_these.unpriced_lines(v.doc):
                self.win.price_these()


def install_takeoff_keys(win):
    """F8 takeoff keys and the unpriced chip (was workflow_boost.install).
    The window attribute keeps its old name, win.workflow_boost."""
    win.workflow_boost = WorkflowBoost(win)
    return win.workflow_boost
