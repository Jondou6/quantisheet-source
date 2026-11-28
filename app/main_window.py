import logging
import os
import re
import tempfile
import time

import fitz
from PySide6.QtCore import Qt, QEvent, QPoint, QSize, QTimer
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QPainter
from PySide6.QtWidgets import (
    QApplication, QColorDialog, QDockWidget, QFileDialog, QInputDialog,
    QComboBox, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox,
    QScrollArea, QTabWidget, QToolBar,
    QVBoxLayout, QWidget
)

from . import (__version__, annotate, columns, icons, pagetools, settings,
               styles, takeoff, toolchest, rules as rules_mod)
from .docks import (BookmarksPanel, DocumentsPanel, EstimatePanel,
                    MarkupsPanel, PropertiesPanel, ToolChestPanel)
from .panels import QuantitiesPanel, SearchBar, ThumbList
from .assembly_ui import AssembliesPanel, chest_item
from .viewer import PdfView, TOOLS
from .dmoney import c2 as _c2

log = logging.getLogger(__name__)

UNLOCKED_BID_WARNING = ("This bid isn't locked yet. Run Estimate > Pre-bid "
                        "Checklist to make sure every sheet, markup and "
                        "revision is accounted for before it goes out.")

# (menu, label, tool id, shortcut, on toolbar)
TOOL_MENU = [
    ("Markup", "Select", None, "V", True),
    ("Edit", "Select Text", "select_text", "I", True),
    ("View", "Marquee Zoom", "zoom", "Z", True),
    ("Markup", "Highlight", "add_highlight", "H", True),
    ("Markup", "Underline", "add_underline", "U", False),
    ("Markup", "Strikeout", "add_strike", "K", False),
    ("Markup", None, None, None, False),
    ("Markup", "Rectangle", "add_rect", "R", True),
    ("Markup", "Ellipse", "add_ellipse", "E", True),
    ("Markup", "Cloud", "add_cloud", "C", True),
    ("Markup", "Line", "add_line", "L", True),
    ("Markup", "Arrow", "arrow", "A", True),
    ("Markup", "Polyline", "add_polyline", None, False),
    ("Markup", "Polygon", "add_polygon", None, True),
    ("Markup", "Pen", "add_ink", "P", True),
    ("Markup", None, None, None, False),
    ("Markup", "Sticky Note", "add_note", "N", True),
    ("Markup", "Text Box", "add_textbox", "T", True),
    ("Markup", "Stamp", "add_stamp", "S", True),
    ("Markup", "Date Stamp", "date_stamp", None, False),
    ("Markup", "Callout", "callout", "Q", True),
    ("Markup", "Legend", "legend", None, False),
    ("Markup", "Redact", "add_redact", None, False),
    ("Edit", "Snapshot", "snapshot", "G", True),
    ("Edit", "Edit Text", "edit_text", "Ctrl+E", True),
    ("Edit", "Add Image", "add_image", None, False),
    ("Edit", "Add Text Field", "field_text", None, False),
    ("Edit", "Add Checkbox", "field_checkbox", None, False),
    ("Edit", "Add Dropdown", "field_combo", None, False),
    ("Edit", "Crop Pages", "crop", None, False),
    ("Fill & Sign", "Signature", "fs_signature", None, True),
    ("Fill & Sign", "Initials", "fs_initials", None, False),
    ("Fill & Sign", "Fill Text", "fs_text", None, True),
    ("Fill & Sign", "Check Mark", "fs_check", None, True),
    ("Fill & Sign", "Date", "fs_date", None, True),
    ("Takeoff", "Calibrate (Set Scale)", "calibrate", "Shift+S", True),
    ("Takeoff", "Length", "measure_length", "Shift+L", True),
    ("Takeoff", "Polylength", "measure_polylength", "Shift+P", True),
    ("Takeoff", "Wall Area (Length x Height)", "measure_wall", "Shift+W",
     True),
    ("Takeoff", "Area", "measure_area", "Shift+A", True),
    ("Takeoff", "Cutout (Deduct)", "measure_cutout", "Shift+X", True),
    ("Takeoff", "Volume", "measure_volume", "Shift+V", True),
    ("Takeoff", "Angle", "measure_angle", None, False),
    ("Takeoff", "Radius", "measure_radius", None, False),
    ("Takeoff", "Diameter", "measure_diameter", None, False),
    ("Takeoff", "Auto Area (Click a Room)", "auto_area", "Shift+R", True),
    ("Takeoff", "Trace Length (Click a Line)", "trace_length", "Shift+T",
     True),
    ("Takeoff", "Trace Outline (Snap to Drawing)", "trace_outline",
     "Shift+O", False),
    ("Takeoff", "Viewport (Scale Region)", "viewport", None, False),
    ("Takeoff", "Count", "count", "Shift+C", True),
    ("Takeoff", "Count Symbol", "symbol", None, True),
]

# annotation type -> tool, for "Add to Tool Chest"
TYPE_TOOL = {"Highlight": "add_highlight", "Underline": "add_underline",
             "StrikeOut": "add_strike", "Square": "add_rect",
             "Circle": "add_ellipse", "Line": "add_line",
             "PolyLine": "add_polyline", "Polygon": "add_polygon",
             "Ink": "add_ink", "Text": "add_note", "FreeText": "add_textbox"}
TAKEOFF_TOOL = {"Line": "measure_length", "PolyLine": "measure_polylength",
                "Polygon": "measure_area", "FreeText": "count"}
# Tool Chest follows takeoff work: the Takeoff tab, or one of these tools
# (a Length on the quick bar counts, even from another tab). Zone tools
# are left out; they mark a sheet for AI Takeoff and are not a measurement.
TAKEOFF_MODE_TOOLS = frozenset({
    "calibrate", "measure_length", "measure_polylength", "measure_wall",
    "measure_area", "measure_cutout", "measure_volume", "measure_angle",
    "measure_radius", "measure_diameter", "viewport", "auto_area",
    "trace_length", "trace_outline", "count", "symbol", "symbol_sample",
    "missed_example",
})


def _replace_in_place(tmp, path):
    """os.replace(tmp, path); when Windows refuses it because the file is
    still open somewhere (PyMuPDF 2.0 can keep a closed document's file
    handle until its pages are freed), copy the saved bytes over the file
    instead and remove `tmp`. The copy kept by backup_before_incremental
    covers a failure half-way."""
    import gc
    import shutil
    import time
    for attempt in range(3):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            gc.collect()
            time.sleep(0.05 * (attempt + 1))
    log.warning("could not replace %s (in use); copying over it", path)
    with open(tmp, "rb") as src, open(path, "r+b") as dst:
        shutil.copyfileobj(src, dst, 1 << 20)
        dst.truncate()
        dst.flush()
        os.fsync(dst.fileno())
    os.remove(tmp)


class DocTab(QScrollArea):
    """One open document: its scrolling page view."""

    def __init__(self, view, path):
        super().__init__()
        self.view = view
        self.path = path
        self.setObjectName("docTab")
        self.setAlignment(Qt.AlignHCenter)
        self.setWidgetResizable(False)
        self.setWidget(view)



# ---- links and document protection (0.13.5 security fixes) ---------------

# a link in a PDF may only open the web or an email: never file:, a
# program's own scheme (ms-..., search-ms:, javascript: ...) or a share
LINK_SCHEMES = ("http", "https", "mailto")


# measure tools that ask what is being measured (r42 F08): title, prompt
MEASURE_NAMED = {
    "measure_area": ("Area", "What are you measuring? (e.g. Carpet, "
                             "Slab, Drywall) - blank for a plain Area"),
    "trace_outline": ("Area", "What are you measuring? (e.g. Carpet, "
                              "Slab) - blank for a plain Area"),
    "measure_length": ("Length", "What are you measuring? (e.g. Base, "
                                 "Curb, Pipe) - blank for a plain Length"),
    "measure_polylength": ("Length", "What are you measuring? (e.g. Base, "
                                     "Wall, Pipe) - blank for a plain "
                                     "Length"),
    "measure_wall": ("Wall Area", "What are you measuring? (e.g. Drywall, "
                                  "Paint, Wall Tile) - blank for a plain "
                                  "Wall Area"),
}


def user_writable(folder):
    """Can this (not elevated) user create a file in `folder`? A real try,
    not os.access (which ignores Windows permissions)."""
    import tempfile
    try:
        fd, p = tempfile.mkstemp(prefix=".qs-wtest-", dir=folder)
        os.close(fd)
        os.remove(p)
        return True
    except OSError:
        return False


def file_link_target(raw, doc_path=None):
    """(path, reason refused) for a PDF's link to another file. Refused:
    network paths (\\\\server\\share, //server, file:// or any URL - opening
    one can send this user's Windows sign-in to that server) and anything
    but a PDF. A relative link is taken from the open file's folder. Pure
    text: the file system is not touched (threat model T-003)."""
    t = str(raw or "").strip()
    if t.lower().startswith("file:"):
        rest = t[5:]
        if rest.startswith("//"):                    # file://HOST/path
            host, _s, path = rest[2:].partition("/")
            if host and host.lower() != "localhost":
                return "", "Links to network locations are blocked."
            t = path
        else:
            t = rest.lstrip("/")
        from urllib.parse import unquote
        t = unquote(t)
    norm = t.replace("/", "\\")
    if norm.startswith("\\\\") or "://" in t or \
            (len(t) > 1 and t[1] == ":" and t[0] == "\\"):
        return "", "Links to network locations are blocked."
    if "\\\\?\\" in norm or norm.startswith("\\??"):
        return "", "This kind of path is blocked."
    if not norm.lower().endswith(".pdf"):
        return "", "Only links to other PDF files can be opened."
    if not os.path.isabs(t) and doc_path:
        t = os.path.join(os.path.dirname(doc_path), t)
    t = os.path.normpath(t)
    if t.replace("/", "\\").startswith("\\\\"):
        return "", "Links to network locations are blocked."
    return t, ""


def link_scheme(uri):
    """The lower-case scheme of `uri` when it may be opened, else None."""
    u = str(uri or "").strip()
    if not u or any(ord(c) < 32 or ord(c) == 127 for c in u):
        return None
    m = re.match(r"^([A-Za-z][A-Za-z0-9+.\-]*):", u)
    if not m:
        return None
    scheme = m.group(1).lower()
    if scheme not in LINK_SCHEMES:
        return None
    if scheme in ("http", "https") and not re.match(
            r"^[A-Za-z]+://[^/\\?#@\s]", u):
        return None
    return scheme


class DocProtection:
    """How an open document was protected, so a full save (Save As, or a
    save that can't append) writes it with the same encryption method and
    permissions instead of dropping them. The passwords are kept in memory
    only: never logged, never written anywhere but into the saved PDF's
    own encryption. Removing protection is only done by Remove Security
    (acrobat.save_unprotected)."""

    __slots__ = ("method", "permissions", "user_pw", "owner_pw", "open_pw")

    def __init__(self, method, permissions, user_pw=None, owner_pw=None,
                 open_pw=None):
        self.method = method
        self.permissions = permissions
        self.user_pw = user_pw
        self.owner_pw = owner_pw
        self.open_pw = open_pw

    def __repr__(self):                     # never show the passwords
        return (f"DocProtection(method={self.method}, "
                f"permissions={self.permissions}, passwords=<hidden>)")

    __str__ = __repr__

    def save_args(self):
        """Keyword arguments for fitz.Document.save."""
        return {"encryption": self.method,
                "user_pw": self.user_pw or None,
                "owner_pw": self.owner_pw,
                "permissions": self.permissions}

    def reopen(self, doc):
        """Unlock `doc` (this document, reopened after a save)."""
        if doc.needs_pass:
            for pw in (self.open_pw, self.user_pw, self.owner_pw):
                if pw and doc.authenticate(pw):
                    break
        return doc


def _encryption_method(text):
    """fitz encryption constant for MuPDF's description of a document's
    encryption ("Standard V5 R6 256-bit AES" ...). Unknown: AES-256."""
    t = str(text or "").upper()
    aes256 = getattr(fitz, "PDF_ENCRYPT_AES_256", 5)
    if "AES" in t:
        return aes256 if "256" in t else getattr(fitz,
                                                 "PDF_ENCRYPT_AES_128", 4)
    if "RC4" in t:
        return getattr(fitz, "PDF_ENCRYPT_RC4_40", 2) if re.search(
            r"\b40\b", t) else getattr(fitz, "PDF_ENCRYPT_RC4_128", 3)
    return aes256


def protection_on_open(doc, password=None, code=0, needed_pass=False):
    """A DocProtection for an encrypted document just opened (and, when it
    needed one, authenticated with `password`; `code` is what
    doc.authenticate returned). None when it isn't encrypted.
    - The password typed is kept as the user (open) password when it is
      one; typing the owner password of a file that needs a password to
      open keeps it needing that password.
    - The owner (permissions) password is the one typed when that was it,
      else a new random one held in memory only: the file stays
      protected with the same permissions."""
    import secrets
    try:
        enc = (doc.metadata or {}).get("encryption")
    except Exception:
        enc = None
    if not enc:
        return None
    try:
        perms = int(doc.permissions)
    except Exception:
        perms = -1
    code = int(code or 0)
    user = owner = None
    if password:
        if code & 2:
            user = password
        if code & 4:
            owner = password
        if user is None and needed_pass:
            user = password
    if owner is None:
        owner = secrets.token_urlsafe(24)
    return DocProtection(_encryption_method(enc), perms, user, owner,
                         password or None)


def save_keeping_protection(doc, path, prot=None, **kw):
    """doc.save(path, **kw) keeping a protected document's own encryption
    (both passwords, method and permissions: PDF_ENCRYPT_KEEP). Falls back
    to re-encrypting from `prot` (a DocProtection) only when KEEP raises or
    the saved file isn't encrypted. Returns None / "keep" / "fallback"."""
    from . import safeio
    if not safeio.is_encrypted(doc):
        doc.save(path, **dict(kw, **(prot.save_args() if prot else {})))
        return None if prot is None else "fallback"
    return safeio.save_keeping_encryption(
        doc, path, prot.save_args() if prot is not None else None, **kw)


def confirm_unprotected_copy(parent, title, why=""):
    """Ask before writing a copy of a password-protected document that
    will NOT be protected. True = the user said yes."""
    text = ((why + "\n\n") if why else "") + (
        "This document is password-protected, but this copy would be "
        "saved WITHOUT a password or any restrictions: anyone could open, "
        "print, copy or change it.\n\nSave the unprotected copy anyway?")
    return QMessageBox.question(
        parent, title, text, QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No) == QMessageBox.Yes


def encryption_save_args(view):
    """fitz save() keywords that keep `view`'s document protection ({}
    for an unprotected document)."""
    prot = getattr(view, "protection", None)
    return prot.save_args() if prot is not None else {}


def backup_before_incremental(path):
    """Copy `path` to `path`.bak once per session before it is saved in
    place (see safeio.backup_once)."""
    from . import safeio
    return safeio.backup_once(path)


def repaired_notice(path):
    """The status-bar notice for a file that had to be repaired when it
    was opened (item 5, 0.13.5)."""
    return (f"{os.path.basename(path)} was damaged and was repaired when "
            "it opened - some pages or objects may be missing. Use File > "
            "Protect & Repair > Check / Repair PDF… to check it and save a repaired copy.")


# the window's methods, by part (Nov 25)
from .mw_menus import MenusMixin            # noqa: E402
from .mw_ai import AiCommandsMixin          # noqa: E402
from .mw_exchange import ExchangeMixin      # noqa: E402


class MainWindow(MenusMixin, AiCommandsMixin, ExchangeMixin, QMainWindow):
    def setWindowTitle(self, title):
        """Beta copies carry who they're licensed to in the title bar."""
        if not hasattr(self, "_beta_label"):
            try:
                from . import betalicense
                self._beta_label = betalicense.label()
            except Exception:
                self._beta_label = ""
        if self._beta_label:
            title = f"{title}   [{self._beta_label}]"
        super().setWindowTitle(title)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("QuantiSheet")
        self.resize(1400, 900)
        self._relay = None
        self._collab_status = ""
        self._windows = []

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._tab_switched)
        self.setAcceptDrops(True)      # drag PDFs from Explorer to open them
        self.search = SearchBar()
        self.search.hide()
        self.search.show_hit.connect(self._show_hit)
        self.search.closed.connect(self._clear_search)
        center = QWidget()
        lay = QVBoxLayout(center)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.search)
        lay.addWidget(self.tabs, 1)
        self._center_lay = lay
        self.setCentralWidget(center)

        # ---- docks ----
        self.thumbs = ThumbList()
        self.thumbs.setObjectName("thumbs")
        self.thumbs.page_clicked.connect(self._go_page)
        self.thumbs.page_moved.connect(self._move_page)
        self.thumbs.action.connect(self._page_action)
        self.thumbs.files_dropped.connect(
            lambda paths, at: self.insert_pdfs_at(paths, at))
        self.bookmarks = BookmarksPanel()
        self.bookmarks.go_page.connect(self._go_page)
        self.bookmarks.go_spot.connect(self._go_spot)
        self.bookmarks.edited.connect(self._doc_edited)
        self.documents = DocumentsPanel(settings.get("project_folder"))
        self.documents.open_file.connect(self.open_path)
        self.markups = MarkupsPanel()
        self.markups.go_to.connect(self._go_annot)
        self.markups.change.connect(self._markup_change)
        self.markups.delete.connect(self._markup_delete)
        self.markups.column_edit.connect(self._column_edit)
        self.markups.manage_columns.connect(self.manage_columns)
        self.properties = PropertiesPanel()
        self.chest = ToolChestPanel()
        self.chest.use.connect(self.use_chest_tool)
        self.chest.imported.connect(self._tool_sets_imported)
        self.chest.get_columns = lambda: (
            columns.read(self._view.doc)["columns"] if self._view else [])
        self.quantities = QuantitiesPanel()
        self.quantities.go_to.connect(self._go_annot)
        from .takeoff_tree import TakeoffTree
        self.takeoff_tree = TakeoffTree()
        self.takeoff_tree.go_to.connect(self._go_takeoff)
        self.takeoff_tree.changed.connect(self._takeoff_visibility)
        self.takeoff_tree.activate.connect(self.take_off_item)
        self.takeoff_tree.edited.connect(self._doc_edited)
        self.takeoff_tree.view_for = lambda: self._view
        self.estimate = EstimatePanel()
        self.estimate.changed.connect(self._doc_edited)
        self.assemblies = AssembliesPanel()
        self.assemblies.changed.connect(self._doc_edited)
        self.assemblies.take_off.connect(self.use_assembly)
        from .rfi_ui import RfiPanel
        self.rfis = RfiPanel()
        self.rfis.go_to.connect(self._go_rfi)
        self.rfis.edited.connect(self._doc_edited)

        self.thumb_dock = self._dock("Pages", self.thumbs, Qt.LeftDockWidgetArea)
        self.bm_dock = self._dock("Bookmarks", self.bookmarks,
                                  Qt.LeftDockWidgetArea)
        self.docs_dock = self._dock("Documents", self.documents,
                                    Qt.LeftDockWidgetArea)
        from .sets_ui import SetsPanel
        self.sets = SetsPanel()
        self.sets.open_sheet.connect(self.open_sheet)
        self.sets.batch_requested.connect(lambda: self.batch_slip_sheet())
        self.sets_dock = self._dock("Sets", self.sets, Qt.LeftDockWidgetArea)
        self.takeoff_dock = self._dock("Takeoff", self.takeoff_tree,
                                       Qt.LeftDockWidgetArea)
        self.tabifyDockWidget(self.thumb_dock, self.takeoff_dock)
        self.tabifyDockWidget(self.takeoff_dock, self.bm_dock)
        self.tabifyDockWidget(self.bm_dock, self.docs_dock)
        self.tabifyDockWidget(self.docs_dock, self.sets_dock)
        self.takeoff_dock.raise_()       # what's taken off
        self.chest_dock = self._dock("Tool Chest", self.chest,
                                     Qt.RightDockWidgetArea)
        self.props_dock = self._dock("Properties", self.properties,
                                     Qt.RightDockWidgetArea)
        self.markups_dock = self._dock("Markups List", self.markups,
                                       Qt.BottomDockWidgetArea)
        self.est_dock = self._dock("Estimate", self.estimate,
                                   Qt.BottomDockWidgetArea)
        self.qty_dock = self._dock("Quantities", self.quantities,
                                   Qt.BottomDockWidgetArea)
        self.asm_dock = self._dock("Assemblies", self.assemblies,
                                   Qt.BottomDockWidgetArea)
        self.tabifyDockWidget(self.markups_dock, self.asm_dock)
        self.tabifyDockWidget(self.asm_dock, self.est_dock)
        self.tabifyDockWidget(self.est_dock, self.qty_dock)
        self.rfi_dock = self._dock("RFI / Submittal Log", self.rfis,
                                   Qt.BottomDockWidgetArea)
        self.tabifyDockWidget(self.qty_dock, self.rfi_dock)
        self.markups_dock.raise_()
        # the bottom panels start closed - they took a third of the screen;
        # View > Bottom Panels (F9) or anything that needs one opens them
        if not settings.get("bottom_panels", False):
            for d in self._bottom_docks():
                d.hide()
        for panel, dock in ((self.markups, self.markups_dock),
                            (self.takeoff_tree, self.takeoff_dock),
                            (self.quantities, self.qty_dock),
                            (self.estimate, self.est_dock),
                            (self.assemblies, self.asm_dock)):
            dock.visibilityChanged.connect(
                lambda vis, pn=panel: self._panel_shown(pn, vis))
        self.resizeDocks([self.markups_dock], [220], Qt.Vertical)
        self.resizeDocks([self.thumb_dock, self.chest_dock], [260, 250],
                         Qt.Horizontal)

        self._panel_timer = QTimer(self)
        self._panel_timer.setSingleShot(True)
        self._panel_timer.setInterval(250)
        self._panel_timer.timeout.connect(self._refresh_panels)
        self._qty_timer = self._panel_timer          # older name
        # Nov 19: the job's watched plan folder is looked at once a minute
        self._plan_timer = QTimer(self)
        self._plan_timer.setInterval(60_000)
        self._plan_timer.timeout.connect(
            lambda: self.check_plan_folder(quiet=True))
        if not os.environ.get("QUANTISHEET_SMOKE"):
            self._plan_timer.start()
        self._plan_offered = {}

        self.statusBar().showMessage("Open a PDF to begin (File > Open)")
        self._tools = QActionGroup(self)
        self._tool_actions = {}
        self._doc_actions = []
        self._build_menus()
        self._install_boosts()
        self._build_toolbar()
        self.simple_menu = None    # Simple Menus removed in 1.1.1 (Nov 4)
        from . import quickaccess          # quick bar, fewer tabs (Nov 4)
        quickaccess.install(self)
        from .pagenav import PageNav
        self.page_nav = PageNav(self, self.tabs)
        self._build_status()
        quickaccess.install_takeoff_keys(self)   # F8 takeoff keys, unpriced chip
        self._install_studio()
        self._fit_status_bar()
        self._build_start_page()
        from . import modern_ui            # the modern layout (stage 2)
        modern_ui.install(self)
        self._empty_state_tips()
        self._enable_doc_actions(False)
        self.properties.set_view(None)
        from .autosave import AutoSaver
        self.autosaver = AutoSaver(self)
        if not os.environ.get("QUANTISHEET_SMOKE"):     # no dialog in checks
            QTimer.singleShot(700, self.recover_unsaved)

    @staticmethod
    def _scrollable(widget):
        """A panel inside a scroll area, so a tall panel (Properties, Tool
        Chest) scrolls instead of making the window taller than the screen.
        On a big TV or a laptop with display scaling the window otherwise
        ran past the bottom of the screen and hid the status bar (zoom,
        page, scale). Panels that already scroll are left as they are."""
        from PySide6.QtWidgets import QAbstractScrollArea, QFrame, QScrollArea
        if isinstance(widget, QAbstractScrollArea):
            return widget
        sc = QScrollArea()
        sc.setObjectName("DockScroll")
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        sc.setWidget(widget)
        return sc

    def _empty_state_tips(self):
        """PR 10 (Nov 4): each panel's View-menu item and What's This say
        what goes in it and how to fill it (empty_states.py). No tool tip
        over the whole panel (it would cover every row) and no extra
        label; panels keep their own empty-list text."""
        from . import empty_states
        done = []
        for d in self.findChildren(QDockWidget):
            text = empty_states.sentence(d.objectName())
            if not text:
                continue
            d.setProperty("emptyState", text)
            d.setWhatsThis(text)
            a = d.toggleViewAction()
            a.setToolTip(text)
            a.setStatusTip(text)
            done.append(d.objectName())
        return done

    def _dock(self, title, widget, area):
        d = QDockWidget(title, self)
        d.setObjectName(title.lower().replace(" ", "_"))
        d.setWidget(self._scrollable(widget))
        self.addDockWidget(area, d)
        return d

    # ---- current document ---------------------------------------------------------
    @property
    def _tab(self):
        w = self.tabs.currentWidget()
        return w if isinstance(w, DocTab) else None

    @property
    def _view(self):
        t = self._tab
        return t.view if t else None

    @property
    def _scroll(self):
        return self._tab

    @property
    def _path(self):
        t = self._tab
        return t.path if t else None

    @_path.setter
    def _path(self, value):
        if self._tab:
            self._tab.path = value
            self._tab.view._path = value
            self.tabs.setTabText(self.tabs.currentIndex(),
                                 os.path.basename(value))

    def _tab_switched(self, _i):
        v = self._view
        self.search.close_bar() if self.search.isVisible() else None
        self._enable_doc_actions(v is not None)
        self.properties.set_view(v)
        if v is None:
            if hasattr(self, "page_nav"):
                self.page_nav.hide()
            for panel in (self.thumbs, self.markups, self.quantities,
                          self.estimate, self.bookmarks, self.assemblies):
                panel.doc = None
            self.takeoff_tree.set_doc(None)
            self.assemblies.tree.clear()
            self.thumbs.clear()
            self.markups.table.setRowCount(0)
            self.estimate.table.setRowCount(0)
            self.bookmarks.tree.clear()
            self.setWindowTitle("QuantiSheet")
            self.statusBar().showMessage("Open a PDF to begin (File > Open)")
            self._set_chips(None, None)
            self._show_start(self.tabs.count() == 0)
            return
        self._show_start(False)
        # opening a tab used to run this twice (addTab switches to it, then
        # open_path called it again), and every panel read the whole
        # document on its own - 100 s on a set with 31,580 markups (Nov 3)
        key = (id(v), id(v.doc))
        if key == getattr(self, "_switched_to", None) and \
                getattr(self, "_switch_done", False):
            self._update_status()
            return
        self._switched_to, self._switch_done = key, False
        self.thumbs.set_doc(v.doc, v.page)
        self.bookmarks.set_doc(v.doc)
        with annotate.scan_cache():          # one scan, shared by all
            for panel, dock in self._panel_docks():
                if self._dock_showing(dock) or not self.isVisible():
                    panel.set_doc(v.doc)
                    panel._stale = False
                else:                        # caught up when it's shown
                    if getattr(panel, "doc", None) is not v.doc and \
                            hasattr(panel, "_labels"):
                        panel._labels = {}   # (the takeoff tree's sheets)
                    panel.doc = v.doc
                    panel._stale = True
            self.rfis.set_doc(v.doc)
        self._switch_done = True
        a = self._tool_actions.get(v.tool)
        if a:
            a.setChecked(True)
        self._update_status()

    # ---- menus ----------------------------------------------------------------
    def _act(self, parent, text, shortcut, slot, needs_doc=True):
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(shortcut)
        # call with no arguments: triggered(checked) would otherwise arrive
        # as the first parameter (a file path, a page...) and break it
        a.triggered.connect(lambda _checked=False, s=slot: s())
        parent.addAction(a)
        if needs_doc:
            self._doc_actions.append(a)
        return a

    # ---- ribbon -----------------------------------------------------------------
    # (tab, group, [items]); an item is "Command text" (a large button), a
    # list of up to 3 texts (a column of small buttons), or a (text, label,
    # icon) tuple. Texts are the menu commands' names.
    RIBBON = [
        ("Home", "File", [("Open", "Open", "open"), ("Save", "Save", "save"),
                          ("Print", "Print", "print")]),
        ("Home", "Edit", [["Undo", "Redo", "Find"], ["Undo History"]]),
        ("Home", "Tools", [("Select", "Select", "select"),
                           ("Select Text", "Text", "select_text"),
                           ("Marquee Zoom", "Zoom", "zoom"),
                           ("Snapshot", "Snapshot", "snapshot")]),
        ("Home", "View", [("Fit Width", "Fit Width", "fit_width"),
                          ("Fit Page", "Fit Page", "fit_page"),
                          ["Zoom In", "Zoom Out", "Previous View"],
                          ("Snap to Content", "Snap", "snap"),
                          ("Field Mode", "Field Mode", "photo")]),
        # one Compare window (overlay / changes / text) - reviews 1 + 2,
        # Nov 4: the separate compare buttons are on the File menu only
        # Nov 20 (Jon): one click on the specs answers the bid questions
        ("Home", "Specs", [("Project Analysis", "Project Analysis",
                            "checklist")]),
        ("Home", "Compare", [("Compare", "Compare", "overlay"),
                             ("Revision Log", "Revisions", "trend")]),
        ("AI", "Takeoff", [("AI Takeoff (Whole Set)", "AI Takeoff",
                            "ai_takeoff"),
                           ("Trade Takeoff (Pipe, Duct, Devices, Roof, "
                            "Rebar, Earthwork)", "Trades", "assembly"),
                           ("Check Takeoff", "Check", "checklist"),
                           ("Auto Takeoff (Review)", "Review Takeoff",
                            "checklist"),
                           ["Auto Scale (Read Sheets)",
                            "Auto Takeoff Rooms on This Sheet",
                            "Count by Label"]]),
        ("AI", "Schedule", [("Build Schedule From Plans",
                              "Schedule From Plans", "gantt")]),
        ("AI", "Voice", [("Voice Commands", "Voice", "mic")]),
        # Nov 23 (Jon): project assistants
        ("AI", "Project", [("Ask the Project", "Ask", "ai"),
                           ("Draft Daily Log From Notes", "Daily Log",
                            "calendar"),
                           ("Check Submittal Against Spec", "Submittal "
                            "Check", "checklist"),
                           ("Project Risk Flags", "Risk Flags", "flag")]),
        ("AI", "Review", [("AI: Find RFIs & Questions", "Find RFIs", "ai"),
                          ["AI: Summarize", "AI: Spec-Check",
                           "AI: Redline"],
                          ["AI: Translate Markups", "Make Searchable (OCR)"]]),
        ("Markup", "Text", [["Highlight", "Underline", "Strikeout"]]),
        ("Markup", "Shapes", [("Rectangle", "Rectangle", "add_rect"),
                              ("Ellipse", "Ellipse", "add_ellipse"),
                              ("Cloud", "Cloud", "add_cloud"),
                              ["Line", "Arrow", "Polyline"],
                              ["Polygon", "Pen"]]),
        ("Markup", "Notes", [("Text Box", "Text Box", "add_textbox"),
                             ("Callout", "Callout", "callout"),
                             ["Sticky Note", "Stamp", "Date Stamp"]]),
        ("Markup", "Style", [("Markup Color", "Color", "color"),
                             ["Line Styles", "Hatch Patterns",
                              "Default Style"],
                             ("Layers", "Layers", "layers")]),
        ("Markup", "Organize", [("Legend", "Legend", "legend"),
                                ["Refresh Legends",
                                 "Add Selected Markup to Tool Chest",
                                 "Redact"]]),
        ("Takeoff", "Scale", ["@scale",
                              ["Calibrate (Set Scale)",
                               "Auto Scale (Read Sheets)",
                               "Viewport (Scale Region)"],
                              ["Auto Scale (Check Against Dimensions)"]]),
        ("Takeoff", "Measure", [("Length", "Length", "measure_length"),
                                ("Polylength", "Polylength",
                                 "measure_polylength"),
                                ("Area", "Area", "measure_area"),
                                ("Cutout (Deduct)", "Cutout",
                                 "measure_cutout"),
                                ("Volume", "Volume", "measure_volume"),
                                ["Wall Area (Length x Height)", "Angle",
                                 "Radius", "Diameter"]]),
        ("Takeoff", "Count", [("Count", "Count", "count"),
                              ("Count Symbol", "Symbol", "symbol"),
                              ("Count From a Picture", "From Picture",
                               "symbol"),
                              ("Count Several Symbols", "Several",
                               "count_several"),
                              ("Try the Count Library", "Library",
                               "count_several"),
                              ("Count by Label", "By Label",
                               "count_label")]),
        ("Takeoff", "Automatic", [("Auto Area (Click a Room)", "Auto Area",
                                   "auto_area"),
                                  ("Trace Length (Click a Line)", "Trace",
                                   "trace_length"),
                                  ("Trace Outline (Snap to Drawing)",
                                   "Outline", "trace_outline"),
                                  ("Auto Takeoff Rooms on This Sheet",
                                   "All Rooms", "auto_rooms"),
                                  ("Auto Takeoff Walls & Doors on This "
                                   "Sheet", "Walls & Doors", "walls"),
                                  ("Walls by Role", "Wall Roles",
                                   "wall_roles"),
                                  ("Trade Takeoff (Pipe, Duct, Devices, "
                                   "Roof, Rebar, Earthwork)", "Trades",
                                   "assembly"),
                                  ("Check Takeoff", "Check", "checklist")]),
        # sitework from a free aerial photo - was hard to find (Jon, Oct 19)
        ("Takeoff", "Site", [("Aerial Photo Page", "Aerial Photo", "photo")]),
        # the 1.1.1 takeoff additions, on the ribbon instead of menu-only
        # (reviews 1 + 2, Nov 4)
        ("Takeoff", "Plan Set", [("Buy Quantities (Sheets, Boxes, Rolls)",
                                  "Buy Qty", "quantities"),
                                 ("Typical Sheet (Count This Sheet N "
                                  "Times)", "Typical Sheet",
                                  "count_several"),
                                 ("Carry Takeoff Forward to a Revised Set",
                                  "Carry Forward", "slipsheet"),
                                 ("Tags vs Schedule Check", "Tags Check",
                                  "checklist")]),
        ("Takeoff", "Output", [("Quantities", "Quantities", "quantities"),
                               ["Export Quantities (CSV)",
                                "Link Quantities to Excel",
                                "Show Scale"]]),
        ("Estimate", "Assemblies", [("Assembly Library", "Library",
                                     "assembly"),
                                    ("Assemblies", "Panel", "panels"),
                                    ["Take Off Into Assembly"]]),
        ("Estimate", "Pricing", [("Cost Books", "Cost Books", "book"),
                                 ("Labor Rates & Crews", "Labor", "crew"),
                                 ("Price Database", "Database",
                                  "database"),
                                 ["Add From Cost Book",
                                  "Quick $/SF Estimate"]]),
        ("Estimate", "Calculators", [("Concrete Calculator", "Concrete",
                                      "measure_volume"),
                                     ("Brick and Block Calculator",
                                      "Brick & Block", "brick"),
                                     ("Roofing Calculator", "Roofing",
                                      "home"),
                                     ("Rebar Calculator", "Rebar",
                                      "measure_polylength"),
                                     ("Beam and Header Calculator", "Beam",
                                      "measure_length"),
                                     ("Column and Post Calculator",
                                      "Column", "walls"),
                                     ("Footing Size Calculator", "Footing",
                                      "measure_area"),
                                     ("Metal Stud Framing Calculator",
                                      "Metal Studs", "walls"),
                                     ("Structural Steel Calculator",
                                      "Steel", "assembly"),
                                     ("Earthwork Calculator", "Earthwork",
                                      "measure_volume"),
                                     ("Aggregate and Asphalt Calculator",
                                      "Aggregate", "measure_area"),
                                     ("Drywall Calculator", "Drywall",
                                      "walls"),
                                     ("Paint Calculator", "Paint",
                                      "color"),
                                     ("Date and Time Calculators",
                                      "Dates", "calendar")]),
        ("Estimate", "Bidding", [("Bid Tabs", "Bid Tabs", "bidtabs"),
                                 ("Leveling Board", "Board", "leveling"),
                                 ("Bid Leveling", "Leveling", "leveling"),
                                 ("Scope Sheets", "Scope Sheets",
                                  "scopesheet"),
                                 ("Bid Build-up", "Build-up", "buildup"),
                                 ("Pre-bid Checklist", "Checklist",
                                  "checklist"),
                                 ("Lock Bid Set", "Lock Bid", "lock"),
                                 ["Revision Changes (Old → New)",
                                  "Placeholders & Allowances",
                                  "Escalation to Buy Date"]]),
        ("Estimate", "Output", [("Price These", "Price", "dollar"),
                                ("Create Proposal", "Proposal", "proposal"),
                                ("Bid Form Autopilot", "Bid Form", "form"),
                                # where Help says they are (review, Nov 4)
                                ("Bid Form Workbook", "Workbook", "book"),
                                ("Builder's Risk Quote Request",
                                 "Builder's Risk", "proposal"),
                                ["Export Assembly Estimate (Excel)",
                                 "Export Estimate (CSV)", "Estimate"],
                                ["Export My Estimate"]]),
        ("Civil", "Takeoff", [("Civil Takeoff (Trades)", "Takeoff",
                               "measure_volume"),
                              ("Work Notes Takeoff", "Notes", "list"),
                              ("Haul Calculator", "Haul", "truck"),
                              # was only in the Civil menu (Jon, Oct 19)
                              ("Aerial Photo Page", "Aerial", "photo"),
                              ("Export to CivilBid (Excel)", "CivilBid",
                               "excel")]),
        ("Civil", "Estimate", [("Crew Estimate (Activities)", "Estimate",
                                "estimate"),
                               ("Crews", "Crews", "crew"),
                               ("Equipment Rates", "Equipment", "dollar"),
                               ("Add From Activity Library", "Library",
                                "book"),
                               ["Estimate From Takeoff (All Groups)",
                                "Start From Master Estimate",
                                "Labor Burden & Wages"],
                               ["Import Prevailing Wages (Davis-Bacon)"]]),
        ("Civil", "Plan", [("Material & Sub Quotes", "Quotes", "inbox"),
                           ("Crew Schedule", "Schedule", "gantt"),
                           ("Resources (Hours by Class & Equipment)",
                            "Resources", "people"),
                           ["Export Cash Flow"]]),
        ("Civil", "Bid", [("Owner Bid Schedule", "Bid Schedule", "list"),
                          ("Indirects", "Indirects", "budget"),
                          ("Bid Versions", "Versions", "history"),
                          ["Import Owner Bid Schedule",
                           "Export Priced Bid Schedule",
                           "Save Bid Version"]]),
        ("Civil", "Field", [("Time Cards", "Time Cards", "calendar"),
                            ("Production History", "Production", "trend"),
                            ("Cost to Complete (Forecast)", "Forecast",
                             "budget"),
                            ("Civil Job Cost (Bid vs Actual)", "Job Cost",
                             "forecast")]),
        ("Review", "Compare", [("Compare", "Compare", "overlay"),
                               ("Revision Log", "Revision Log", "trend"),
                               ("Batch Slip Sheet", "Batch Slip",
                                "slipsheet"),
                               ("Measurement Audit", "Audit", "audit"),
                               ["Version History"]]),
        ("Review", "Automate", [("Auto-Markup by Rules", "Auto-Markup",
                                 "rules"),
                                ["Edit Auto-Markup Rules"]]),
        ("Review", "AI", [("AI: Find RFIs & Questions", "Find RFIs", "ai"),
                          ["AI: Summarize", "AI: Spec-Check",
                           "AI: Redline"],
                          ["AI: Translate Markups"]]),
        ("Review", "RFIs", [("New RFI", "New RFI", "rfi"),
                            ("New Submittal", "Submittal", "submittal"),
                            ["Submittal Review Stamp",
                             "RFI / Submittal Log"]]),
        ("Project", "Manage", [("Project Center", "Project Center",
                                "home"),
                               ("Scheduler (Gantt)", "Scheduler", "gantt"),
                               # Jon couldn't find it (Oct 21)
                               ("Weekly Owner Report", "Owner Report",
                                "photo"),
                               ("Company Directory", "Directory",
                                "people")]),
        ("Project", "Sets", [("Sets", "Sets", "sets"),
                             ("Batch Slip Sheet", "Batch Slip", "slipsheet"),
                             ["New Set From Files", "Open Set"]]),
        ("Project", "Documents", [("Drawing Register", "Register",
                                   "register"),
                                  ("Transmittals", "Transmittals",
                                   "transmittal"),
                                  ("Addenda", "Addenda", "addenda"),
                                  ["New Transmittal",
                                   "Open Project Folder"]]),
        ("Project", "Field", [("Punch List", "Punch List", "punch"),
                              ("Three-Phase Inspections", "Inspections",
                               "inspect"),
                              ["New Punch Item"]]),
        ("Project", "Submittals", [("Submittal Log", "Submittals",
                                    "submittal")]),
        ("Project", "Check", [("Code Check", "Code Check", "code"),
                              ("Project Risk Flags", "Risk Flags", "flag"),
                              ("Search Takeoff Across Jobs", "All Jobs",
                               "database")]),
        ("Module", "ADA", [("ADA Standards PDF", "ADA PDF", "book"),
                           ("ADA Standards (2010)", "Look Up", "find"),
                           ("ADA Checker", "ADA Checker", "ada")]),
        ("Module", "Energy Code", [("Climate Zone by County", "Climate Zone",
                                    "sun"),
                                   ("Code Library", "Code Library", "book"),
                                   ["Read the Energy Code Online"]]),

        ("Billing", "Contract", [("Contract & Billing", "Contract",
                                  "contract"),
                                 ("Schedule of Values", "SOV", "sov")]),
        ("Billing", "Changes", [("Change Orders", "Change Orders",
                                 "change_order"),
                                ["Change Order From Selected Markup"]]),
        ("Billing", "Payment", [("Pay Applications",
                                 "Pay Apps", "pay_app"),
                                ("Lien Waivers", "Waivers", "waiver")]),
        ("Pages", "Pages", [("Organize Pages", "Organize", "panels"),
                            ("Insert Pages From PDF", "Insert",
                                "page_add"),
                               ("Replace Pages", "Replace", "replace"),
                               ["Rotate Right", "Rotate Left",
                                "Insert Blank Page"],
                               ["Duplicate Page", "Extract Pages",
                                "Delete Pages"],
                               ["Split Document", "Crop Pages"]]),
        ("Pages", "Page Marks", [["Header & Footer", "Page Numbers",
                                     "Bates Numbering"],
                                    ["Watermark", "Auto Bookmark Sheets",
                                     "Spec Book Sections"],
                                    ("Link Sheet References", "Link Sheets",
                                     "link")]),
        ("Document", "Content", [("Edit Text", "Edit Text", "edit_text"),
                                 ("Make Searchable (OCR)", "OCR", "ocr"),
                                 ["Add Image", "Search & Redact"]]),
        ("Document", "Forms", [("Prepare Form (detect fields)", "Prepare",
                                "form"),
                               ["Add Text Field", "Add Checkbox",
                                "Add Dropdown"],
                               ["Clear Form", "Fill Form From Job",
                                "Flatten Markups & Fields"]]),
        ("Document", "Sign", [("Signature", "Signature", "fs_signature"),
                              ["Initials", "Fill Text", "Check Mark"],
                              ["Date", "Sign", "Verify Signatures"]]),
        ("Document", "E-Sign", [("Request Signatures", "Request",
                                 "sign"),
                                ("Signature Requests", "Track", "inbox")]),
        ("Document", "Standards", [("Accessibility Check", "Accessibility",
                                    "accessibility"),
                                   ("PDF/A (archival)", "PDF/A", "shield"),
                                   ("Preflight / PDF/X", "Preflight",
                                    "print")]),
        ("Document", "Protect", [("Password Protect", "Protect", "lock"),
                                 ["Remove Security",
                                  "Remove Hidden Information",
                                  "Reduce File Size"]]),
        ("Tools", "Automate", [("Action Wizard (Batch Process)", "Batch",
                                "batch"),
                               ("Macros", "Macros", "macro"),
                               ("Package Tracker", "Packages", "package")]),
        ("Tools", "Collaborate", [("Live Collaboration", "Live", "collab"),
                                  ("Start Relay (host on this computer)",
                                   "Relay", "relay")]),
        ("Tools", "Convert", [("Create PDF From File", "Create PDF", "new"),
                              ("Combine Files", "Combine", "combine"),
                              ["Import AutoCAD DXF",
                               "Import Markups (PDF or XFDF)",
                               "Export Markups (XFDF)"]]),
        # Nov 23 (Jon): a 3D Model tab after AI
        ("3D Model", "IFC Model",
         [("3D Model Quantities (IFC)", "Model Quantities", "assembly")]),
        # Nov 20 (Jon): a Project Analysis tab after Tools
        ("Project Analysis", "Project Analysis",
         [("Project Analysis", "Project Analysis", "checklist"),
          ("Find Bid Terms", "Bid Terms", "find"),
          ("Manufacturers in Specs", "Manufacturers", "list"),
          ("Bid Submittal Checklist", "Bid Checklist", "checklist"),
          ("Ask the Project", "Ask the Project", "ai")]),
        ("Tools", "Settings", [("Command Search", "Commands", "command"),
                               ["Author Name", "Keyboard Shortcuts",
                                "Document Properties"]]),
        ("Help", "Learn", [("Help Center & Tutorials", "Tutorials", "info"),
                           ("Features & How-To Guide (PDF)", "Guide",
                            "book"),
                           ("Video Tutorials", "Videos", "info"),
                           ("Welcome Tour", "Tour", "home"),
                           ("Open Practice Drawings", "Practice", "open"),
                           ("Keyboard Shortcuts", "Shortcuts",
                            "keyboard")]),
        ("Help", "About", [("About QuantiSheet", "About", "info"),
                           ("Report an Issue", "Report Issue", "info"),
                           ["Terms of Service", "Privacy",
                            "Third-Party Licenses"]]),
    ]

    # icons for commands that aren't tools (menus and small ribbon buttons)
    ICON_OF = {
        "open": "open", "save": "save", "save as": "save", "print": "print",
        "close tab": "close", "undo": "undo", "redo": "redo", "find": "find",
        "zoom in": "zoom", "zoom out": "zoom_out", "previous view":
        "page_prev", "next page": "page_next", "previous page": "page_prev",
        "go to page": "numbers", "actual size": "fit_page",
        "new from form library": "form", "create pdf from file": "new",
        "combine files": "combine", "import autocad dxf": "dxf",
        "import markups (pdf or xfdf)": "import",
        "export markups (xfdf)": "export", "password protect": "lock",
        "remove security": "lock", "remove hidden information": "shield",
        "reduce file size": "compress", "open project folder": "folder",
        "version history": "history", "compare text with": "compare",
        "quick compare (same sheets)": "compare",
        "document properties": "info", "sign": "sign",
        "verify signatures": "shield", "paste image": "add_image",
        "delete selected markup": "close",
        "add selected markup to tool chest": "chest",
        "author name": "crew", "markup color": "color",
        "default style": "palette", "refresh legends": "legend",
        "line styles": "line_style", "hatch patterns": "hatch",
        "change signature": "fs_signature", "change initials": "fs_initials",
        "auto scale (read sheets)": "auto_scale", "show scale": "scale",
        "viewports on this page": "viewport", "count by label": "count_label",
        "export quantities (csv)": "csv", "link quantities to excel": "excel",
        "export assembly estimate (excel)": "excel",
        "export estimate (csv)": "csv", "rotate right": "rotate",
        "rotate left": "rotate_left", "rotate all pages right": "rotate",
        "insert blank page": "page_add", "duplicate page": "duplicate",
        "split document": "split", "extract pages": "extract",
        "delete pages": "page_delete", "header & footer": "header_footer",
        "auto bookmark sheets": "bookmark", "page numbers": "numbers",
        "bates numbering": "numbers", "watermark": "watermark",
        "search & redact": "redact_search", "clear form": "form",
        "fill form from job": "form", "flatten markups & fields": "flatten",
        "edit auto-markup rules": "rules", "ai: summarize": "ai",
        "ai: redline": "ai", "ai: spec-check": "ai",
        "ai: translate markups": "ai", "submittal review stamp": "add_stamp",
        "new transmittal": "transmittal", "new punch item": "punch",
        "change order from selected markup": "change_order",
        "keyboard shortcuts": "keyboard", "about": "info",
        "command search": "command", "show ribbon": "panels",
        "rfi / submittal log": "list", "estimate": "estimate",
        "markups list": "list", "pages": "panels", "bookmarks": "bookmark",
        "documents": "folder", "tool chest": "chest",
        "properties": "settings", "exit": "close",
        "new set from files": "sets", "open set": "open",
        "spec book sections": "book", "search takeoff across jobs":
        "database", "revision log": "trend", "measurement audit": "audit",
        "batch slip sheet": "slipsheet", "accessibility check":
        "accessibility", "pdf/a (archival)": "shield", "theme": "palette",
        "sets": "sets",
    }

    def _index_actions(self):
        from .ribbon import all_actions, clean
        self._cmd = {}
        for _path, a in all_actions(self.menuBar()):
            self._cmd.setdefault(clean(a.text()).lower(), a)
        for d in self.findChildren(QDockWidget):
            a = d.toggleViewAction()
            self._cmd.setdefault(clean(a.text()).lower(), a)
        for a in self._ribbon_only_actions():
            self._cmd.setdefault(clean(a.text()).lower(), a)
        for key, a in self._cmd.items():
            name = self.ICON_OF.get(key)
            if name and a.icon().isNull():
                a.setIcon(icons.icon(name))
            if name and not a.property("qs_icon"):
                data = a.data()
                if not (isinstance(data, str) and icons.has(data)):
                    a.setProperty("qs_icon", name)
        return self._cmd

    def command(self, text):
        """The QAction for a menu command, by its name."""
        return self._cmd.get(text.replace("…", "").rstrip(". ").strip()
                             .lower())

    def _preload(self):
        try:
            from . import acrobat, qlink, revisions  # noqa: F401
        except Exception:
            logging.getLogger(__name__).debug("ignored error", exc_info=True)

    def _tidy_dock_tabs(self):
        """Full names on the tabs of stacked panels (no "Pa...")."""
        from PySide6.QtWidgets import QTabBar
        for bar in self.findChildren(QTabBar):
            if bar.parent() is self and bar.isVisible():
                bar.setElideMode(Qt.ElideNone)
                bar.setExpanding(False)
                bar.setUsesScrollButtons(True)

    def _retheme(self, *_):
        from . import theme
        for v in self._all_views():
            v.update()
        self.update()
        return theme.name()

    def _all_views(self):
        return [self.tabs.widget(i).view for i in range(self.tabs.count())
                if isinstance(self.tabs.widget(i), DocTab)]

    def set_theme(self, mode):
        """mode: system, dark or light (saved)."""
        from . import theme
        QApplication.setOverrideCursor(Qt.WaitCursor)   # restyling takes ~3 s
        try:
            return theme.apply(QApplication.instance(), mode, save=True)
        finally:
            QApplication.restoreOverrideCursor()

    def command_search(self, show=True):
        """Ctrl+K: find and run any command by typing its name."""
        from .ribbon import CommandPalette
        from . import quickaccess
        dlg = CommandPalette(self.menuBar(), self,
                             extra=quickaccess.palette_extras(self),
                             reveal=lambda a: quickaccess.reveal(self, a))
        if show:
            dlg.popup(self)
        return dlg

    def _in_takeoff_mode(self):
        """Takeoff tab, or a measurement / count tool in use."""
        rb = getattr(self, "ribbon", None)
        if rb is not None and rb.current() == "Takeoff":
            return True
        v = getattr(self, "_view", None)
        tool = getattr(v, "tool", None) if v is not None else None
        return tool in TAKEOFF_MODE_TOOLS

    def _sync_tool_chest(self, force=False, tab_change=False):
        """Show the Tool Chest in takeoff work, hide it otherwise.

        Every tab change closes it unless the new tab is Takeoff - even
        with a takeoff tool still active (Jon, Nov 6). Picking a takeoff
        tool on another tab opens it again. A hand-opened chest stays up
        until the next tab change. Properties is its own dock.
        """
        dock = getattr(self, "chest_dock", None)
        if dock is None:
            return False
        mode = self._in_takeoff_mode()
        if tab_change:
            rb = getattr(self, "ribbon", None)
            on = rb is not None and rb.current() == "Takeoff"
            self._chest_mode = mode          # a tool change shows it again
            if on:
                dock.show()
            else:
                dock.hide()
            return on
        on = mode
        if not force and on == getattr(self, "_chest_mode", None):
            return on
        self._chest_mode = on
        if on:
            dock.show()
        else:
            dock.hide()
        return on

    # AI tab: every AI command, in addition to wherever else it already sits.
    _AI_TAB = (
        ("Takeoff", (
            ("AI Takeoff (Whole Set)", "AI Takeoff", "ai_takeoff"),
            ("Draw a Zone: Only Here", "Only Here", "zone_in"),
            ("Draw a Zone: Leave Out", "Leave Out", "zone_out"),
            ("Clear Zones on This Page", "Clear Zones", "close"),
            ("Auto Takeoff (Review)", "Review Takeoff", "checklist"),
            ("Check Takeoff", "Check", "audit"),
            ("Trade Takeoff (Pipe, Duct, Devices, Roof, Rebar, Earthwork)",
             "Trades", "assembly"),
            ("Auto Takeoff Rooms on This Sheet", "All Rooms", "auto_rooms"),
            ("Auto Takeoff Walls & Doors on This Sheet", "Walls & Doors",
             "walls"),
            ("Item Names Learned", "Names Learned", "list"),
        )),
        ("Schedule", (
            ("Build Schedule From Plans", "Schedule From Plans", "gantt"),
        )),
        ("Review", (
            ("AI: Find RFIs & Questions", "Find RFIs", "rfi"),
            ("AI: Summarize", "Summarize", "ai"),
            ("AI: Spec-Check", "Spec-Check", "checklist"),
            ("AI: Redline", "Redline", "edit_text"),
            ("AI: Translate Markups", "Translate", "sign"),
            ("Spec Book Risk Scanner", "Spec Risk", "shield"),
            ("Make Searchable (OCR)", "OCR", "ocr"),
        )),
        ("Voice", (
            ("Voice Commands", "Voice", "mic"),
        )),
        ("Model", (
            ("Local AI Models", "Models", "database"),
        )),
    )

    def _fill_ai_tab(self):
        """The AI tab lists every AI command. Folded copies on other tabs
        stay, so nothing that was already on the ribbon is removed."""
        from .ribbon import ModelStatus
        page = self.ribbon.page("AI")
        missing = []
        for title, items in self._AI_TAB:
            g = page.group(title)
            have = {id(b.defaultAction()) for b in g.buttons
                    if b.defaultAction() is not None}
            for text, label, icon in items:
                a = self.command(text)
                if a is None:
                    missing.append(text)
                    continue
                if not a.property("qs_icon"):
                    a.setProperty("qs_icon", icon)
                if a.icon().isNull() and icons.has(icon):
                    a.setIcon(icons.icon(icon))
                if id(a) in have:
                    continue
                g.large(a, label)
                have.add(id(a))
        if missing:
            log.warning("AI tab: no command named %s", ", ".join(missing))
        self._ai_tab_missing = missing
        page.group("Model").widget(ModelStatus(self))
        return missing

    def _ribbon_put(self, tab, group, items):
        """Add tiles that were menu-only. Skips a command already in the
        group, and a command this build does not have."""
        from . import quickaccess
        tab, group = quickaccess.fold(tab, group)
        g = self.ribbon.page(tab).group(group)
        have = {id(b.defaultAction()) for b in g.buttons
                if b.defaultAction() is not None}
        missing = []
        for text, label, icon in items:
            a = self.command(text)
            if a is None:
                missing.append(text)
                continue
            a.setProperty("qs_icon", icon)
            if a.icon().isNull() and icons.has(icon):
                a.setIcon(icons.icon(icon))
            if id(a) in have:
                continue
            g.large(a, label)
            have.add(id(a))
        return missing

    def _fill_pdf_tab(self, exp_menu=None):
        """PDF Management (Jon, Nov 6): the Pages and Document groups and
        Create PDF / Combine fold in by themselves; this adds Export (to
        Word, Excel, images...), Compare and Print, and puts the groups in
        working order. The old Pages and Document tabs (and Tools >
        Convert) are part of it now; Classic Tabs brings them back."""
        from PySide6.QtWidgets import QToolButton

        from . import quickaccess
        tab = quickaccess.PDF_TAB
        if quickaccess.fold("Pages", "Pages")[0] != tab:
            return []                       # classic tabs: no PDF tab
        missing = self._ribbon_put(tab, "Create & Convert", (
            ("Create PDF From File", "Create PDF", "new"),
            ("Combine Files", "Combine", "combine"),
        ))
        g = self.ribbon.page(tab).group("Create & Convert")
        if exp_menu is not None:
            first = next((a for a in exp_menu.actions()
                          if not a.isSeparator() and a.text()), None)
            if first is not None:
                b = g.large(first, "Export PDF", menu=exp_menu)
                b.setPopupMode(QToolButton.InstantPopup)
        missing += self._ribbon_put(tab, "Create & Convert", (
            ("Compare", "Compare", "overlay"),
            ("Print", "Print", "print"),
        ))
        missing += self._edit_pdf_tile(g)
        self.ribbon.page(tab).arrange_groups(quickaccess.PDF_GROUPS)
        return missing

    # Edit PDF (Jon, Nov 6): one of the first buttons on PDF Management.
    # The tile turns on page editing (text and images); its arrow has the
    # rest of the editing tools.
    EDIT_PDF_MENU = ("Edit Text", "Add Image", "Search & Redact",
                     "Organize Pages", "Crop Pages", "Header & Footer",
                     "Watermark", "Add Text Field", "Add Checkbox",
                     "Add Dropdown")

    def _edit_pdf_tile(self, group):
        from PySide6.QtWidgets import QMenu

        from .ribbon import clean
        base = self.command("Edit Text")
        if base is None:
            return ["Edit Text"]
        a = self.command("Edit PDF")
        if a is None:
            a = QAction(icons.icon("edit_text"), "Edit PDF", self)
            a.setToolTip("Edit PDF: change the text and images on the page "
                         "(" + (base.shortcut().toString() or "Ctrl+E") +
                         "). The arrow has the other editing tools.")
            a.setProperty("qs_icon", "edit_text")
            a.triggered.connect(lambda _c=False: base.trigger())
            self.addAction(a)
            self._cmd[clean(a.text()).lower()] = a
            # in the Document menu too, so All Tools and Ctrl+K list it
            mb = self.menuBar()
            dm = next((x.menu() for x in mb.actions() if x.menu() is not None
                       and clean(x.text()) == "Document"), None)
            if dm is not None:
                first = next(iter(dm.actions()), None)
                dm.insertAction(first, a)
        menu = QMenu(self)
        for name in self.EDIT_PDF_MENU:
            c = self.command(name)
            if c is not None:
                menu.addAction(c)
        self._edit_pdf_menu = menu
        b = group.large(a, "Edit PDF", menu=menu)
        group.place(b, 0)
        return []

    def _place_roof_tile(self):
        """Takeoff > Roof. Hidden unless Show Roof Plan Tools is on."""
        rf = self.command("Roof Plan Takeoff")
        if rf is None:
            return None
        rf.setIcon(icons.icon("assembly"))
        rf.setProperty("qs_icon", "assembly")
        rf.setIconText("Roof Plan")
        rf.setVisible(bool(settings.get("roof_takeoff", False)))
        g = self.ribbon.page("Takeoff").group("Roof")
        b = g.large(rf, "Roof Plan")

        def sync(*_a):
            show = rf.isVisible()
            b.setVisible(show)
            g.setVisible(show)
        rf.changed.connect(sync)
        sync()
        return b

    # ---- scale presets on the Takeoff ribbon ---------------------------------------
    def _build_scale_box(self, group):
        from PySide6.QtGui import QStandardItem
        from PySide6.QtWidgets import QCheckBox
        box = QComboBox()
        box.setObjectName("scale_presets")
        box.setToolTip("Scale presets: set the scale of this page (or every "
                       "page with All Pages)")
        box.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        box.setMinimumContentsLength(14)
        model = box.model()
        box.addItem("(not set)", None)
        box.addItem("", "custom")              # a calibrated scale
        for family, items in takeoff.PRESETS.items():
            head = QStandardItem(f"— {family} —")
            head.setEnabled(False)
            model.appendRow(head)
            for name, (ppu, unit) in items:
                box.addItem("   " + name, (name, ppu, unit))
        box.insertSeparator(box.count())
        box.addItem("Calibrate…", "calibrate")
        box.addItem("Auto Scale (Read Sheets)…", "auto")
        box.activated.connect(self._scale_box_picked)
        self.scale_box = box
        self.scale_all = QAction("All Pages", self)
        self.scale_all.setCheckable(True)
        self.scale_all.setToolTip("Scale presets set every page of the "
                                  "document, not just this one")
        self._doc_actions.append(self.scale_all)
        col = QWidget()
        lay = QVBoxLayout(col)
        lay.setContentsMargins(2, 6, 2, 0)
        lay.setSpacing(4)
        lay.addWidget(QLabel("Page scale"))
        lay.addWidget(box)
        cb = QCheckBox("All pages")
        cb.toggled.connect(self.scale_all.setChecked)
        self.scale_all.toggled.connect(
            lambda on: cb.isChecked() != on and cb.setChecked(on))
        lay.addWidget(cb)
        lay.addStretch(1)
        group.widget(col)

    def _scale_box_picked(self, i):
        data = self.scale_box.itemData(i)
        if data == "calibrate":
            self._tool_actions["calibrate"].trigger()
        elif data == "auto":
            self.sheet_setup(scales=True, bookmarks=False)
        elif isinstance(data, tuple):
            name, ppu, unit = data
            self.apply_scale_preset(name, ppu, unit,
                                    all_pages=self.scale_all.isChecked())
        self._sync_scale_box()

    def _sync_scale_box(self):
        """Show the current page's scale in the toolbar box."""
        box = getattr(self, "scale_box", None)
        if box is None:
            return
        v = self._view
        sc = v.scale() if v else None
        name = (sc or {}).get("name") or ""
        idx = 0
        if sc:
            idx = next((i for i in range(box.count())
                        if isinstance(box.itemData(i), tuple) and
                        box.itemData(i)[0] == name), 1)
        box.blockSignals(True)
        box.setItemText(1, name or (f"Custom ({sc['unit']})" if sc else ""))
        box.view().setRowHidden(1, idx != 1)
        box.setCurrentIndex(idx)
        box.blockSignals(False)

    def _enable_doc_actions(self, on):
        for a in self._doc_actions:
            a.setEnabled(on)

    def open_claims_module(self):
        """Start ClaimIT (a separate program), with the open drawing's
        takeoff when there is one - it works without a PDF too."""
        from . import claims_hook
        doc = self._view.doc if self._view is not None else None
        try:
            claims_hook.launch(doc)
        except Exception as e:                            # noqa: BLE001
            log.warning("could not start ClaimIT", exc_info=True)
            QMessageBox.warning(self, "ClaimIT",
                                f"Could not start ClaimIT:\n{e}")

    # ---- helpers ---------------------------------------------------------------
    def _doc(self):
        return self._view.doc

    def _sel_pages(self, ask=False):
        pages = self.thumbs.selected_pages() if self.thumbs.hasFocus() \
            or len(self.thumbs.selectedItems()) > 1 else []
        return pages or [self._view.page]

    def _collab_blocked(self, what):
        if self._view and self._view.session:
            QMessageBox.information(
                self, what, f"{what} is off during live collaboration, "
                "because it would put your copy out of step with everyone "
                "else's. Disconnect first (Tools > Live Collaboration).")
            return True
        return False

    def _build_start_page(self):
        from .startpage import StartPage
        cards = []
        for text, label, sub, icon in (
                ("Open", "Open a PDF", "Drawings, specs or any PDF", "open"),
                ("Open Project Folder", "Open a project folder",
                 "Every sheet of a job in one list", "folder"),
                ("Compare", "Compare revisions",
                 "Overlay, changes and text in one window", "overlay"),
                # the service desk and Back Office belong on the first
                # screen too (review 2, Nov 4); each shows only when there
                ("Service Work Order", "Service desk",
                 "Calls, dispatch, agreements, backflow tests", "crew"),
                ("QuantiSheet Back Office", "Back Office",
                 "Time, payables, job cost, payroll", "dollar"),
                ("New From Form Library", "New from a form",
                 "RFIs, transmittals, daily reports", "form"),
                ("Aerial Photo Page", "Aerial photo of a site",
                 "Free USGS photo, scaled for takeoff", "photo"),
                ("Generate Set", "Generate a starter set",
                 "A brief in, ten sheets out", "layers"),
                ("Scheduler (Gantt)", "Build a schedule",
                 "Gantt chart and critical path - no PDF needed", "gantt"),
                ("Bid Tabs", "Bid tabs and pricing",
                 "Unit prices from public bids", "bidtabs"),
                ("Command Search", "Find a command",
                 "Ctrl+K, then type", "command"),
                ("Help Center & Tutorials", "Tutorials",
                 "Step-by-step, with Show Me (F1)", "info"),
                ("Open Practice Drawings", "Practice drawings",
                 "A safe set to try every tool on", "layers")):
            a = self.command(text)
            if a is not None:
                cards.append((label, sub, icon, a))
        self.start_page = StartPage(cards)
        self.start_page.open_path.connect(self.open_path)
        self._center_lay.addWidget(self.start_page, 1)
        self._show_start(True)

    def _show_start(self, on):
        if not hasattr(self, "start_page"):
            return
        if on:
            self.start_page.refresh()
        self.start_page.setVisible(on)
        self.tabs.setVisible(not on)

    def _build_status(self):
        """Page, zoom and scale chips on the right of the status bar."""
        from PySide6.QtWidgets import QToolButton
        sb = self.statusBar()
        sb.setSizeGripEnabled(False)
        self.chip_scale = QLabel("")
        self.chip_job = QLabel("")
        self.chip_page = QLabel("")
        self.chip_zoom = QLabel("")
        zo, zi = QToolButton(), QToolButton()
        for b, name, slot, tip in ((zo, "zoom_out", lambda: self._zoom(0.8),
                                    "Zoom out"),
                                   (zi, "zoom", lambda: self._zoom(1.25),
                                    "Zoom in")):
            b.setObjectName("IconButton")
            b.setIcon(icons.icon(name))
            b.setIconSize(QSize(14, 14))
            b.setToolTip(tip)
            b.clicked.connect(slot)
        self.chip_autosave = QToolButton()
        self.chip_autosave.setObjectName("StatusChipButton")
        self.chip_autosave.setAutoRaise(True)
        self.chip_autosave.setPopupMode(QToolButton.InstantPopup)
        self.chip_autosave.setIcon(icons.icon("save"))
        self.chip_autosave.setIconSize(QSize(14, 14))
        self.chip_autosave.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.chip_autosave.setMenu(self._autosave_menu())
        sb.addPermanentWidget(self.chip_autosave)
        for w in (self.chip_job, self.chip_scale, self.chip_page, zo,
                  self.chip_zoom, zi):
            if isinstance(w, QLabel):
                w.setObjectName("StatusChip")
            sb.addPermanentWidget(w)
        self._chip_widgets = (self.chip_scale, self.chip_page, zo,
                              self.chip_zoom, zi)
        for w in self._chip_widgets:
            w.setVisible(False)

    def _fit_status_bar(self):
        """On a narrow window (a laptop) the bottom bar ran out of room and
        pushed the zoom buttons off the right edge. Page, zoom and the
        scale keep their size; the other tags (keys, unpriced, autosave,
        job data, the length box) give up width first."""
        from PySide6.QtWidgets import QSizePolicy, QToolButton
        keep = [getattr(self, n, None) for n in
                ("chip_page", "chip_zoom", "chip_scale")]
        keep += [w for w in self._chip_widgets if isinstance(w, QToolButton)]
        sb = self.statusBar()
        for w in sb.findChildren(QWidget, options=Qt.FindDirectChildrenOnly):
            if w in keep:
                w.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
            elif w is getattr(self, "measure_bar", None):
                w.setMinimumWidth(160)
            elif isinstance(w, (QLabel, QToolButton)):
                w.setMinimumWidth(24)
                w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

    def _set_chips(self, v, sc):
        if not hasattr(self, "chip_page"):
            return
        for w in self._chip_widgets:
            w.setVisible(v is not None)
        if v is None:
            self.chip_job.setVisible(False)
            self._studio_status(None)
            return
        self.chip_page.setText(f"Page {v.page + 1} / {v.doc.page_count}")
        self.chip_zoom.setText(f"{v.zoom * 100:.0f}%")
        name = (sc or {}).get("name") or (sc or {}).get("unit")
        other = ""
        if not sc:
            # GUI user test r42 F11: after reopening on another sheet,
            # "No scale" read as if the scale was lost
            try:
                n = len(annotate.read_scales(v.doc))
            except Exception:                             # noqa: BLE001
                n = 0
            if n:
                other = f" here ({n} of {v.doc.page_count} pages scaled)"
        check = " (read from title block - click to confirm)" if sc and \
            v.page in getattr(v, "_auto_scaled", ()) else ""
        self.chip_scale.setText(f"⟷  {name}{check}" if sc else
                                f"⟷  No scale{other}")
        self.chip_scale.setObjectName("StatusChipAccent" if sc else
                                      "StatusChip")
        self.chip_scale.setToolTip("This page's takeoff scale" if sc else
                                   "Set a scale on the Takeoff tab before "
                                   "measuring")
        self.chip_scale.style().unpolish(self.chip_scale)
        self.chip_scale.style().polish(self.chip_scale)
        self._set_job_chip(v)

    def _set_job_chip(self, v):
        """Visible warning when the open PDF carries QuantiSheet job data
        (it goes out with the file unless you use External Issue)."""
        from . import jobdata
        chip = getattr(self, "chip_job", None)
        if chip is None:
            return
        info = jobdata.describe(v.doc) if v is not None else []
        chip.setVisible(bool(info))
        if not info:
            return
        priced = jobdata.has_pricing(v.doc)
        chip.setText("$ Job data" if priced else "Job data")
        chip.setObjectName("StatusChipAccent" if priced else "StatusChip")
        chip.setToolTip(
            "This PDF carries QuantiSheet job data: "
            + ", ".join(l for _, l in info) + ".\nAnyone you send the file "
            "to can read it. Use File > Export > External Issue (strip "
            "pricing) for subs and owners.")
        chip.style().unpolish(chip)
        chip.style().polish(chip)

    def _update_status(self):
        v = self._view
        if not v:
            return
        self._undo_names()
        name = os.path.basename(self._path) if self._path else \
            getattr(self._tab, "title", "Untitled")
        self.setWindowTitle(f"QuantiSheet — {name}{' *' if v.dirty else ''}")
        i = self.tabs.currentIndex()
        tab_text = name + (" *" if v.dirty else "")
        if self.tabs.tabText(i) != tab_text:
            self.tabs.setTabText(i, tab_text)
        a = self._tool_actions.get(v.tool)
        if a and not a.isChecked():
            a.setChecked(True)
        parts = []
        label = TOOLS.get(v.tool, ("Select", ""))[0]
        subject = v.style.get("subject")
        item = self._takeoff_item_live(v)
        if item:
            label = f"Taking off: {item['name']} ({item['type']})"
        elif v.tool == "count":
            label += f" ({v.count_group})"
        elif subject and v.tool:
            label += f" ({subject})"
        parts.append(f"{label}: {v.hint()}")
        sc = v.scale()
        self._sync_scale_box()
        self._set_chips(v, sc)
        self._studio_status(v)
        if v.selected:
            parts.append(f"Selected: {v.selected.get('type', 'markup')}")
        if v.session:
            parts.append(f"Collab: {self._collab_status}")
        import time as _t
        if _t.monotonic() >= getattr(self, "_sticky_until", 0.0):
            # a message we flashed stays readable; the tool hint waits
            # (Generate Set's warning count vanished in under a second)
            self.statusBar().showMessage("   |   ".join(parts))
        if self.thumbs.currentRow() != v.page:
            self.thumbs.set_current(v.page)
        for panel in (self.quantities, self.markups, self.estimate,
                      self.assemblies, self.takeoff_tree):
            if panel.current_page != v.page:
                panel.current_page = v.page
                self._panel_timer.start()
        self.bookmarks.current_page = v.page
        if hasattr(self, "page_nav"):
            self.page_nav.sync()

    def _on_collab_status(self, text):
        self._collab_status = text
        self._update_status()

    def _snapshot_toast(self, w, h, dpi):
        """PM review NW-01: a snapshot showed only a status-bar line, so it
        could look like nothing happened. A small note over the drawing
        says it's copied and offers Save as PNG; it goes by itself."""
        from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton
        old = getattr(self, "_snap_toast", None)
        if old is not None:
            try:
                old.deleteLater()
            except RuntimeError:
                pass
        host = self.centralWidget() or self
        box = QFrame(host)
        box.setObjectName("SnapToast")
        box.setStyleSheet(
            "#SnapToast { background: rgba(32,33,36,235); border-radius: "
            "8px; } #SnapToast QLabel { color: white; } #SnapToast "
            "QPushButton { padding: 3px 10px; }")
        lay = QHBoxLayout(box)
        lay.setContentsMargins(12, 8, 8, 8)
        lay.addWidget(QLabel(f"Snapshot copied - {w} x {h} px. Paste with "
                             "Ctrl+V."))
        b = QPushButton("Save as PNG…")
        b.clicked.connect(lambda _c=False: self.save_snapshot_png())
        lay.addWidget(b)
        box.adjustSize()
        box.move(max(0, (host.width() - box.width()) // 2),
                 max(0, host.height() - box.height() - 48))
        box.show()
        box.raise_()
        self._snap_toast = box
        # tied to the note, so a note already replaced or closed is skipped
        QTimer.singleShot(8000, box, box.hide)
        return box

    def save_snapshot_png(self, path=None):
        v = self._view
        if not v or not getattr(v, "_snapshot_png", None):
            self._flash("No snapshot yet: pick Snapshot (G) and drag a box.")
            return None
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Save snapshot as PNG", "snapshot.png", "PNG (*.png)")
            if not path:
                return None
        out = v.save_snapshot_png(path)
        if out:
            self._flash(f"Saved {os.path.basename(out)}")
        return out

    def _flash(self, text, ms=6000):
        """Show `text` in the status bar for `ms`; the tool hint doesn't
        overwrite it meanwhile."""
        import time as _t
        self._sticky_until = _t.monotonic() + ms / 1000.0
        self.statusBar().showMessage(text, ms)

    def set_tool(self, tool, ask=True):
        if not self._view:
            return
        v = self._view
        if tool == "count" and ask:
            item = getattr(v, "takeoff_item", None) or {}
            group, ok = QInputDialog.getText(
                self, "Count", "What are you counting? (e.g. Outlets, Doors)",
                text=item.get("name") or v.count_group)
            if not ok or not group.strip():
                # cancelled: put the check back on the tool still in use
                # (some tools have no button, so .get)
                act = self._tool_actions.get(v.tool)
                if act is not None:
                    act.setChecked(True)
                else:
                    for a in self._tool_actions.values():
                        a.setChecked(False)
                return
            v.count_group = group.strip()
        if tool in ("measure_length", "measure_polylength", "measure_area",
                    "measure_wall", "trace_outline") and not v.scale():
            QMessageBox.information(
                self, "Takeoff", "This page has no scale yet. Choose a "
                "standard scale from Takeoff > Scale Presets, or drag along "
                "a dimension you know and type its length.")
            tool = "calibrate"
        from . import quickaccess
        if ask and tool in quickaccess.MEASURING:
            # a scale read from the title block is checked before the
            # first measurement on that sheet (reviews 1 and 2, Nov 4)
            tool = quickaccess.scale_gate(self, v, tool)
            if tool is None:
                return
        if tool == "calibrate":
            self._flash("Calibrate: drag along a known dimension")
        if ask and tool != v.tool:
            v.style = {k: val for k, val in v.style.items()
                       if k == "color" and val is not None}
        if ask and tool in MEASURE_NAMED and \
                not getattr(v, "takeoff_item", None) and \
                not v.style.get("subject"):
            # GUI user test r42 F08: areas and lengths were all called
            # "Area" / "Length" in the exports. Ask what it is (as Count
            # does) - suggesting the last name used; blank keeps it plain
            names = getattr(v, "measure_names", None)
            if names is None:
                names = v.measure_names = {}
            name, ok = QInputDialog.getText(
                self, MEASURE_NAMED[tool][0], MEASURE_NAMED[tool][1],
                text=names.get(tool, ""))
            if ok and name.strip():
                names[tool] = name.strip()
                v.style["subject"] = name.strip()
        v.set_tool(tool)
        if tool and tool not in ("zoom", "select_text", "edit_text"):
            # Space repeats it with the same item (Nov 4 takeoff list #13)
            self._last_tool = (tool, dict(v.style),
                               getattr(v, "count_group", None))
            rec = [t for t in getattr(self, "_recent_tools", []) if t != tool]
            self._recent_tools = [tool] + rec[:4]      # last 5 (QS-035)
        act = self._tool_actions.get(tool)
        if act:
            act.setChecked(True)
        else:                                   # a tool with no button
            for a in self._tool_actions.values():
                a.setChecked(False)
        self.properties.refresh()
        lay = getattr(self, "layouts", None)
        if lay is not None:
            lay.tool_changed()
        v.setFocus()

    def _takeoff_item_live(self, v):
        """The Takeoff-panel item `v` is taking off, or None - picking
        another tool, another count name or Esc ends it."""
        from . import takeoff_items
        item = getattr(v, "takeoff_item", None)
        if item:
            tool = takeoff_items.TOOL.get(item["type"])
            name = v.count_group if item["type"] == "count" else \
                v.style.get("subject")
            if v.tool != tool or name != item["name"]:
                v.takeoff_item = item = None
        if v is self._view:
            self.takeoff_tree.set_active(
                (item["name"], item["type"]) if item else None)
        return item

    def take_off_item(self, item):
        """Takeoff panel: click an item and each click on the drawing adds
        to it, in its color - no "What are you counting?" question."""
        v = self._view
        if not v:
            return
        if item is None:
            v.takeoff_item = None
            self._update_status()
            return
        from . import takeoff_items
        tool = takeoff_items.TOOL.get(item.get("type"))
        if tool is None:
            return
        kind = "add_count" if tool == "count" else (
            "add_line" if item["type"] == "length" else "add_polygon")
        style = {"color": list(item.get("color") or v._color(kind))}
        if tool == "count":
            v.count_group = item["name"]
        else:
            style["subject"] = item["name"]
        v.style = style
        v.takeoff_item = {"name": item["name"], "type": item["type"]}
        self.set_tool(tool, ask=False)      # no scale: says so, calibrates
        if v.tool != tool:
            v.takeoff_item = None
            self._update_status()
            return
        self.properties.refresh()
        self._update_status()
        self._flash(f"Taking off: {item['name']} ({item['type']})")

    def takeoff_standard(self):
        """Takeoff > Takeoff Standard: the office's workflow, ticked off
        for this drawing (standard.py)."""
        v = self._view
        if not v:
            QMessageBox.information(self, "Takeoff Standard",
                                    "Open a drawing first.")
            return None
        from .standard_ui import StandardDialog
        dlg = StandardDialog(v.doc, self, changed=v.mark_dirty)
        dlg.exec()
        return dlg

    def report_issue(self, text=""):
        """Help > Report an Issue: describe it, check the screenshot, an
        email to support opens ready to send (issue_report.py)."""
        from . import issue_report_ui
        return issue_report_ui.open_dialog(self, text)

    def set_side_lengths(self, mode):
        """Takeoff > Show Side Lengths: on screen only, nothing is added
        to the drawing."""
        settings.set("side_lengths", mode)
        if self._view:
            self._view.update()

    def set_captions(self, mode):
        """Takeoff > Captions: what measurement labels say, on every page
        of this drawing and on new measurements. One undo step."""
        from . import measure_extra
        settings.set("caption", mode)
        v = self._view
        if not v:
            return 0
        n = v.apply_marks([(i, "set_captions", {"mode": mode})
                           for i in range(v.doc.page_count)])
        self._flash(f"Captions: {measure_extra.CAPTIONS[mode]}")
        return n

    def _count_resumed(self, group):
        """Right-click a count > Add More to it: the Count tool, checked."""
        v = self._view
        if not v:
            return
        self.set_tool("count", ask=False)
        v.count_group = group
        self._update_status()

    def _tool_sets_imported(self, extra):
        """A tool set file brought statuses and Markups List columns: the
        statuses are added to yours; the columns are added to the open
        drawing if you say so."""
        sts = [x for x in extra.get("statuses") or []
               if x not in annotate.statuses()]
        if sts:
            styles.set_custom_statuses(
                (settings.get("statuses") or []) + sts)
        cols = extra.get("columns") or []
        v = self._view
        if cols and v:
            have = {c["name"].lower() for c in columns.read(v.doc)["columns"]}
            new = [c for c in cols if str(c.get("name", "")).lower()
                   not in have]
            if new and QMessageBox.question(
                    self, "Tool Sets", "Add the set's Markups List "
                    "columns (" + ", ".join(str(c.get("name")) for c in
                                             new[:8]) +
                    ") to this drawing?") == QMessageBox.Yes:
                columns.set_columns(v.doc, columns.read(v.doc)["columns"] +
                                    new)
                v.mark_dirty()
                self.markups.refresh()

    def _ensure_tool_columns(self, item):
        """A tool with a unit cost or column values: the drawing gets those
        Markups List columns (and Total Cost = Value x Unit Cost)."""
        v = self._view
        fields = toolchest.style_of(item).get("fields") or {}
        if not v or not fields:
            return 0
        cols = columns.read(v.doc)["columns"]
        have = {c["name"].lower() for c in cols}
        add = []
        for k, val in fields.items():
            if k.lower() not in have:
                add.append({"name": k, "type": "number" if isinstance(
                    val, (int, float)) else "text"})
                have.add(k.lower())
        if "unit cost" in have and "total cost" not in have:
            add.append({"name": "Total Cost", "type": "formula",
                        "formula": "Value * Unit_Cost"})
        if add:
            columns.set_columns(v.doc, cols + add)
            v.mark_dirty()
            self.markups.refresh()
        return len(add)

    def use_chest_tool(self, item):
        """Draw with a saved Tool Chest tool."""
        v = self._view
        if not v:
            return
        tool = item.get("tool")
        if tool not in TOOLS:
            return
        self._ensure_tool_columns(item)
        if tool == "count":
            v.count_group = item.get("subject") or item.get("name")
        self.set_tool(tool, ask=False)
        if v.tool == tool:
            v.style = toolchest.style_of(item)
            self.properties.refresh()
            self._update_status()
            self._flash(f"Tool Chest: {item['name']}")

    def use_assembly(self, a):
        """Take off with an assembly: measure with the right tool, named
        after the assembly so its parts and costs fill in."""
        if not self._view:
            return
        self.use_chest_tool(chest_item(a))
        self.asm_dock.show()
        self.asm_dock.raise_()
        what = {"length": "Click along the walls; double-click to finish",
                "area": "Click around the area; double-click to finish",
                "count": "Click each item"}.get(a.get("measure"), "")
        self._flash(f"Taking off: {a['name']}. {what}")
        if self._view and not self._view.scale() and \
                a.get("measure") in ("length", "area"):
            QMessageBox.information(
                self, "Takeoff", "This page has no scale yet. Choose one from "
                "Takeoff > Scale Presets, or Calibrate, before measuring.")

    def add_selected_to_chest(self):
        v = self._view
        props = v.selected_props() if v else None
        if not props:
            QMessageBox.information(self, "Tool Chest",
                                    "Select a markup first.")
            return
        tool = (TAKEOFF_TOOL if props["takeoff"] else TYPE_TOOL).get(
            props["type"])
        if not tool:
            QMessageBox.information(self, "Tool Chest",
                                    "That kind of markup can't be saved.")
            return
        found = annotate.find_annots(v.pg, v.selected["ref"])
        if found:
            ftype = annotate.friendly_type(found[0], "", v.doc)
            if tool == "add_rect" and ftype == "Cloud":
                tool = "add_cloud"
            elif tool == "add_line" and ftype == "Arrow":
                tool = "arrow"
            elif ftype == "Stamp":
                tool = "add_stamp"
        name, ok = QInputDialog.getText(self, "Add to Tool Chest", "Name:",
                                        text=props["subject"] or
                                        TOOLS[tool][0])
        if not ok or not name.strip():
            return
        item = {"name": name.strip(), "tool": tool,
                "color": list(props["color"])[:3] if props["color"] else None,
                "fill": list(props["fill"])[:3] if props["fill"] else None,
                "width": props["width"] if props["width"] > 0 else None,
                "opacity": _c2(props["opacity"])
                if props["opacity"] < 1 else None,
                "subject": props["subject"] or name.strip()}
        if found and props["takeoff"]:
            from . import measure_extra
            ex = measure_extra.read(v.doc, found[0])
            if ex.get("to"):
                item["unit"] = ex["to"]
            for k in ("rise", "height", "openings"):
                if ex.get(k):
                    item[k] = ex[k]
            f = annotate.fields_of(v.doc, found[0])
            if f:
                item["fields"] = f
        item = {k: val for k, val in item.items() if val is not None}
        if self.chest.add(item):
            self.chest_dock.show()
            self.chest_dock.raise_()
            self._flash(f"Added '{item['name']}' to the Tool Chest")

    def set_author(self):
        name, ok = QInputDialog.getText(self, "Author Name",
                                        "Name shown on your markups:",
                                        text=settings.author())
        if ok and name.strip():
            settings.set("author", name.strip())

    def pick_color(self):
        if not self._view:
            return
        c = QColorDialog.getColor(parent=self)
        if c.isValid():
            self._view.color = (c.redF(), c.greenF(), c.blueF())
            self.properties.refresh()

    def reset_color(self):
        if self._view:
            self._view.style = {}
            self.properties.refresh()

    def _zoom_from_view(self, factor, view_pos):
        v = self._view
        if v is not None:
            self._zoom_at(factor, v.mapTo(self._scroll.viewport(), view_pos))

    def _zoom_at(self, factor, vp_pos):
        """Zoom keeping the spot under viewport position `vp_pos` still."""
        v = self._view
        vp = self._scroll.viewport()
        old = v.mapFrom(vp, vp_pos)
        self._push_view()
        before = v.zoom
        v.set_zoom(before * factor)
        ratio = v.zoom / before if before else 1
        target = QPoint(int(old.x() * ratio), int(old.y() * ratio))

        def keep():
            now = v.mapTo(vp, target)
            h = self._scroll.horizontalScrollBar()
            b = self._scroll.verticalScrollBar()
            h.setValue(h.value() + now.x() - vp_pos.x())
            b.setValue(b.value() + now.y() - vp_pos.y())
        keep()
        QTimer.singleShot(0, keep)          # again once the layout settles

    def _zoom(self, factor):
        if self._view:
            self._push_view()
            self._view.set_zoom(self._view.zoom * factor)

    # ---- marquee zoom and previous view -------------------------------------------
    def _view_state(self):
        v = self._view
        return (v.page, v.zoom, self._scroll.horizontalScrollBar().value(),
                self._scroll.verticalScrollBar().value())

    def _push_view(self, force=False):
        """Remember where we are, for Previous View. Wheel zooming calls
        this many times a second; only the first of a burst is kept."""
        import time
        v = self._view
        if v is None:
            return
        stack = v.__dict__.setdefault("_views", [])
        now = time.monotonic()
        if not force and stack and now - v.__dict__.get("_view_t", 0) < 1.0:
            v._view_t = now
            return
        v._view_t = now
        st = self._view_state()
        if not stack or stack[-1] != st:
            stack.append(st)
            del stack[:-50]

    def previous_view(self):
        v = self._view
        stack = v.__dict__.get("_views") if v else None
        if not stack:
            self._flash("No previous view")
            return False
        page, zoom, hx, vy = stack.pop()
        v._view_t = 0
        if page != v.page:
            v.go_to(page)
        v.set_zoom(zoom)

        def scroll():
            self._scroll.horizontalScrollBar().setValue(hx)
            self._scroll.verticalScrollBar().setValue(vy)
        scroll()
        QTimer.singleShot(0, scroll)
        return True

    def zoom_to_rect(self, r):
        """Zoom so screen rect `r` (page units) fills the window."""
        v = self._view
        if not v or r.width <= 0 or r.height <= 0:
            return
        self._push_view(force=True)
        vp = self._scroll.viewport()
        v.set_zoom(min((vp.width() - 24) / r.width,
                       (vp.height() - 24) / r.height))
        cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2

        def center():
            p = v.mapTo(self._scroll.widget(),
                        QPoint(int(cx * v.zoom), int(cy * v.zoom)))
            self._scroll.horizontalScrollBar().setValue(
                p.x() - vp.width() // 2)
            self._scroll.verticalScrollBar().setValue(
                p.y() - vp.height() // 2)
        center()
        QTimer.singleShot(0, center)
        if v.tool == "zoom":
            self.set_tool(None)

    def _view_menu(self, global_pos):
        """Right-click on the page (not on a markup): tools that work right
        there (Nov 4), then view options."""
        m = QMenu(self)
        m.addAction("Marquee Zoom")       # anchor; the tools go above it
        anchor = m.actions()[0]
        anchor.triggered.connect(lambda: self.set_tool("zoom"))
        from . import quickaccess
        v_ = self._view
        quickaccess.add_page_menu(self, m, getattr(v_, "_menu_pt", None)
                                  if v_ is not None else None)
        m.addAction("Zoom In", lambda: self._zoom(1.25))
        m.addAction("Zoom Out", lambda: self._zoom(0.8))
        m.addAction("Fit Width", self.fit_width)
        m.addAction("Fit Page", self.fit_page)
        prev = m.addAction("Previous View", self.previous_view)
        v = self._view
        prev.setEnabled(bool(v and v.__dict__.get("_views")))
        m.addSeparator()
        if v is not None and v.selected_text():
            m.addAction("Copy Text", self.copy_text)
            m.addAction("Copy as Table (for Excel)", self.copy_table)
        m.addAction("Select All Text on Page", self.select_all_text)
        m.addAction("Copy All Text on This Page",
                    lambda: self.copy_text(page=True))
        m.addAction("Select Text Tool", lambda: self.set_tool("select_text"))
        m.addAction("Select Tool", lambda: self.set_tool(None))
        self._last_view_menu = m
        if getattr(self, "_menu_no_exec", False):         # tests
            return m
        m.exec(global_pos)
        return m

    def _key_to_field(self, seq):
        """Ctrl+C / Ctrl+A belong to the list or text box that has the
        keyboard (Markups List, a table, a search box), not the drawing:
        hand the key to it. True when it went there."""
        from PySide6.QtGui import QKeyEvent
        fw = QApplication.focusWidget()
        v = self._view
        if fw is None or fw is v or (v is not None and v.isAncestorOf(fw)) \
                or not (fw is self or self.isAncestorOf(fw)):
            return False
        from PySide6.QtWidgets import (QAbstractItemView, QLineEdit,
                                       QPlainTextEdit, QTextEdit)
        if not isinstance(fw, (QAbstractItemView, QLineEdit, QTextEdit,
                               QPlainTextEdit)):
            return False
        if seq == QKeySequence.Copy:
            # copy from the field only when something is selected in it;
            # otherwise Ctrl+C is for the drawing's selected text
            if isinstance(fw, QLineEdit):
                has = fw.hasSelectedText()
            elif isinstance(fw, (QTextEdit, QPlainTextEdit)):
                has = fw.textCursor().hasSelection()
            else:
                sm = fw.selectionModel()
                has = bool(sm and sm.hasSelection())
            if not has:
                return False
        key = Qt.Key_C if seq == QKeySequence.Copy else Qt.Key_A
        for t in (QEvent.KeyPress, QEvent.KeyRelease):
            QApplication.sendEvent(fw, QKeyEvent(t, key,
                                                 Qt.ControlModifier))
        return True

    def open_bid_zip(self, zip_path=None, folder=None, setup=True,
                     project=True):
        """File > Open Bid Download as a Job: unzip a plan room download
        into a job folder sorted into Drawings / Specs / Addenda / Other,
        combine the drawings, open them, read sheet names and scales, and
        make the folder a Project Center job (bidzip.py)."""
        from . import bidzip
        if zip_path is None:
            zip_path, _ = QFileDialog.getOpenFileName(
                self, "Bid Download", "", "Zip files (*.zip)")
            if not zip_path:
                return None
        if folder is None:
            base = os.path.splitext(zip_path)[0]
            folder = QFileDialog.getExistingDirectory(
                self, "Folder for the job (a new one next to the zip is "
                "suggested)", os.path.dirname(zip_path))
            if not folder:
                return None
            if os.listdir(folder):
                folder = os.path.join(folder, os.path.basename(base))
        os.makedirs(folder, exist_ok=True)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            rep = bidzip.unpack(zip_path, folder)
            name = os.path.basename(os.path.splitext(zip_path)[0])
            combined, pages = bidzip.combine(
                rep["files"]["Drawings"],
                os.path.join(folder, "Drawings", f"{name} - Combined Set.pdf"))
        except bidzip.ZipJobError as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Open Bid Download", str(e))
            return None
        finally:
            if QApplication.overrideCursor() is not None:
                QApplication.restoreOverrideCursor()
        rep["combined"], rep["folder"] = combined, folder
        if combined:
            self.open_path(combined)
        if project:
            try:
                from .pm.center import open_center
                rep["center"] = open_center(folder, self, create=True)
            except Exception:                             # noqa: BLE001
                log.warning("job not made in Project Center", exc_info=True)
        QMessageBox.information(
            self, "Open Bid Download",
            f"Unpacked into {folder}\n\n" + bidzip.report_text(rep) +
            (f"\n\nThe drawings are combined into one set ({pages} "
             "pages). Next: check the sheet names and scales." if combined
             else "\n\nNo drawings were found to combine."))
        if combined and setup:
            self.sheet_setup(scales=True, bookmarks=True)
        return rep

    def count_from_picture(self, path=None, group=None, all_pages=None):
        """Takeoff > Count From a Picture (picsearch.py)."""
        if not self._view:
            return 0
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Picture of the symbol", "",
                "Pictures (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.gif)")
            if not path:
                return 0
        with open(path, "rb") as f:
            data = f.read()
        return self._view.count_from_picture(data, group, all_pages)

    def time_log(self, show=True):
        """Tools > Time Log: active time per job and sheet (timelog.py)."""
        from .timelog_ui import TimeLogDialog
        dlg = TimeLogDialog(self)
        if show:
            dlg.exec()
        return dlg

    def package_tracker(self):
        """Tools > Package Tracker: FedEx, UPS, USPS and DHL numbers in one
        list; Track opens the carrier's page (packages.py)."""
        from . import packages_ui
        return packages_ui.show(self)

    def copy_text(self, page=False):
        """Edit > Copy Text (Ctrl+C): the words selected with Select Text
        (or double-clicked), or all of this page's text."""
        if not page and self._key_to_field(QKeySequence.Copy):
            return ""                 # Ctrl+C in a list or a text box
        v = self._view
        if v is None:
            return ""
        if not page and not v.selected_text() and v.selected:
            # markups selected, no text: copy the markups (takeoff list #2)
            from . import takeoffclip
            n = takeoffclip.copy(v)
            if n:
                self._flash(f"Copied {n} markup(s) - Ctrl+V pastes them on "
                            "any sheet (measurements use that sheet's "
                            "scale)", 5000)
                return n
        return v.copy_text(page=page)

    def spec_risk(self, show=True, path=None):
        """Review > Spec Book Risk Scanner: bonds, liquidated damages,
        prevailing wage, insurance, warranties and testing on one page.
        Scans the open document when it is a spec book, else asks."""
        from .specrisk_ui import SpecRiskDialog
        doc, title = None, ""
        v = self._view
        if path:
            doc = fitz.open(path)
            title = os.path.splitext(os.path.basename(path))[0]
        elif v is not None:
            try:
                from .ai import rfi_finder
                pages = [(i, "", "", v.doc[i].get_text("text"))
                         for i in range(min(40, v.doc.page_count))]
                if rfi_finder.is_spec_book(pages):
                    doc = v.doc
                    title = os.path.splitext(os.path.basename(
                        self._path or ""))[0]
            except Exception:                             # noqa: BLE001
                doc = None
        dlg = SpecRiskDialog(self, doc, title=title,
                             open_result=lambda p: self.open_path(p),
                             src_path=(self._path if doc is not None and
                                       not path else path))
        if show:
            dlg.show()
            if doc is None:
                dlg.pick()
        return dlg

    def change_from_revision(self, show=True):
        """Billing > Change Order From Revision: the revised sheet's
        takeoff change priced, with clouded backup (co_delta.py)."""
        if not self._view:
            return None
        from .co_delta_ui import CODialog
        dlg = CODialog(self._view, self,
                       open_result=lambda p: self.open_document(
                           fitz.open(p), "Change Order Proposal"))
        if show:
            dlg.show()
        return dlg

    def backup_data(self, path=None, password=None, ask=None):
        """Tools > Back Up My QuantiSheet Data (review QS-006; reviews 1 +
        2, Nov 4: keys, sign-ins and Back Office data only with a
        password, AES-encrypted; every backup is checked after it's
        made). `ask(title, text)` -> password or "" (tests pass one)."""
        from . import databackup
        if password is None:
            if ask is None:
                def ask(title, text):
                    from PySide6.QtWidgets import QLineEdit as LE
                    pw, ok = QInputDialog.getText(self, title, text,
                                                  LE.EchoMode.Password)
                    return pw if ok else None
            password = ask(
                "Back Up My QuantiSheet Data",
                "Backup password (10 or more characters).\n\nWith a "
                "password the backup also holds your signing key, carrier "
                "keys, sign-ins and the Back Office data, encrypted.\n"
                "Leave it empty to back up without those.")
            if password is None:
                return None
            if password:
                again = ask("Back Up My QuantiSheet Data",
                            "Type the backup password again:")
                if again != password:
                    QMessageBox.warning(self, "Back Up", "The passwords "
                                        "didn't match - nothing was saved.")
                    return None
        ext = ".qsbackup" if password else ".zip"
        if path is None:
            d = databackup.default_dir()
            os.makedirs(d, exist_ok=True)
            path, _ = QFileDialog.getSaveFileName(
                self, "Back Up My QuantiSheet Data", os.path.join(
                    d, __import__("datetime").date.today().strftime(
                        "QuantiSheet data %Y-%m-%d") + ext),
                "QuantiSheet backup (*.qsbackup)" if password else
                "Zip (*.zip)")
            if not path:
                return None
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            r = databackup.make(path, password=password or None)
        except Exception as ex:                           # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Back Up", f"Couldn't make the "
                                f"backup - nothing usable was saved:\n{ex}")
            return None
        QApplication.restoreOverrideCursor()
        held = ("It's encrypted with your backup password and holds your "
                "keys and Back Office data too - without the password it "
                "can't be opened." if password else
                "It has no keys, sign-ins or Back Office data (no password "
                "was set) - see LEFT OUT.txt inside.")
        synced = ("\n\nThis folder is synced to the cloud." if
                  databackup.is_synced(path) else "")
        QMessageBox.information(
            self, "Back Up",
            f"Saved and checked: {r['files']} file(s), "
            f"{r['verified']['databases_checked']} database(s) OK.\n{path}"
            f"\n\n{held}{synced}")
        return r

    def restore_data(self, path=None, confirm=None, password=None):
        from . import databackup
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Restore QuantiSheet Data", databackup.default_dir(),
                "QuantiSheet backups (*.qsbackup *.zip)")
            if not path:
                return None
        if databackup.is_encrypted(path) and password is None:
            from PySide6.QtWidgets import QLineEdit as LE
            password, ok = QInputDialog.getText(
                self, "Restore", "This backup has a password:",
                LE.EchoMode.Password)
            if not ok:
                return None
        try:
            meta = databackup.contents(path, password)
        except databackup.BackupError as ex:
            QMessageBox.warning(self, "Restore", str(ex))
            return None
        except Exception:                                 # noqa: BLE001
            QMessageBox.warning(self, "Restore", "That isn't a QuantiSheet "
                                "data backup.")
            return None
        confirm = confirm or (lambda text: QMessageBox.question(
            self, "Restore", text) == QMessageBox.Yes)
        if not confirm(f"Put back {meta['count']} file(s) from the backup "
                       f"made {meta.get('made', '')[:16].replace('T', ' ')}"
                       " (QuantiSheet " + str(meta.get("app", "")) + ")?\n\n"
                       "What's there now is saved first, and QuantiSheet "
                       "should be restarted after."):
            return None
        safety = databackup.restore(path, password=password)
        QMessageBox.information(
            self, "Restore", "Restored. Close QuantiSheet and open it again."
            f"\n\nYour data from before is in:\n{safety}")
        return safety

    def compare(self, other=None, show=True):
        """One Compare (Nov 4): Overlay / Changes / Text in one window,
        newest revision picked for you."""
        from .quickaccess import CompareDialog
        if not self._view:
            return None
        dlg = CompareDialog(self, other)
        if show:
            dlg.show()
        return dlg

    def _tab_option(self, key, on):
        from . import quickaccess
        settings.set(key, bool(on))
        if key == "classic_tabs":
            self._flash("The ribbon changes the next time QuantiSheet "
                        "starts", 6000)
        return quickaccess.update_tabs(self)

    def _choose_role(self):
        from . import quickaccess
        settings.set(quickaccess.S_WELCOME, False)
        dlg = quickaccess.WelcomeDialog(self)
        dlg.exec()
        return dlg.role

    def customize_shortcuts(self, show=True):
        from .quickaccess import ShortcutsDialog
        dlg = ShortcutsDialog(self)
        if show:
            dlg.show()
        return dlg

    def paste(self, at=None):
        """Ctrl+V: markups copied in QuantiSheet (in place, or at `at`),
        else a picture from the clipboard."""
        from . import takeoffclip
        v = self._view
        if v is None:
            return 0
        if takeoffclip.ready():
            return takeoffclip.paste(v, at)
        return v.paste_image()

    def carry_forward(self, other=None):
        """Takeoff > Carry Takeoff Forward (takeoff list #1): Compare
        Revisions' Slip Sheet - the newer drawings go in under this set's
        takeoff, lined up sheet by sheet; the old drawing stays as a hidden
        layer, and takeoff in changed areas is flagged Revised."""
        dlg = self.compare_revisions(other)
        if dlg is not None:
            self._flash("Pick the newer set, Compare, then 'Slip Sheet: "
                        "Update This Set to the Newer Revision' - your takeoff stays and anything "
                        "in a changed area is flagged Revised.", 15000)
        return dlg

    def color_by(self, mode):
        v = self._view
        if v is None:
            return None
        return v.set_color_by(mode)

    def sheathing_helper(self, show=True):
        """Takeoff > Wood Sheathing Helper (Nov 19): the APA span rating
        and thickness for a roof, floor or wall at its framing spacing,
        and the 4x8 sheets for an area takeoff - added to the estimate as
        a line that follows the area."""
        from .sheathing_ui import SheathingDialog
        v = self._view
        if v is None:
            return None
        dlg = SheathingDialog(v.doc, self)
        if show:
            dlg.exec()
            if dlg.added:
                self._doc_edited()
                self.estimate.refresh()
        return dlg

    def page_multiplier(self, n=None):
        """Takeoff > Typical Sheet: everything on this sheet counts N
        times in the totals (a typical floor). 1 clears it."""
        v = self._view
        if v is None:
            return None
        cur = annotate.page_multiplier(v.doc, v.page)
        if n is None:
            n, ok = QInputDialog.getInt(
                self, "Typical Sheet", "How many times does this sheet's "
                "takeoff count? (e.g. 5 for floors 2-6; 1 = just once)",
                int(cur), 1, 999)
            if not ok:
                return None
        annotate.set_page_multiplier(v.doc, v.page, n)
        v.history.snapshot()
        v.mark_dirty()
        v.update()
        self._refresh_panels()
        self._flash(f"This sheet counts x{n} in the totals" if n > 1 else
                    "This sheet counts once")
        return n

    def repeat_last_tool(self):
        """Space: the last takeoff or markup tool again, with the same item
        (name, colour, Tool Chest settings)."""
        last = getattr(self, "_last_tool", None)
        v = self._view
        if not last or v is None:
            return None
        tool, style, group = last
        if group:
            v.count_group = group
        self.set_tool(tool, ask=False)
        if v.tool == tool:
            v.style = dict(style)
            self.properties.refresh()
            self._flash(f"Again: {style.get('subject') or tool}", 2500)
        return v.tool

    def _number_key(self, n):
        from . import quickaccess
        it = quickaccess.number_key(self, n)
        if it is None:
            self._flash(f"No Tool Chest tool {n} yet - the first nine tools "
                        "in the Tool Chest take keys 1-9", 4000)
        return it

    def new_rfi_at(self, pt):
        """Right-click > New RFI Here: an RFI on this sheet, where you
        clicked."""
        v = self._view
        if not v:
            return None
        from . import sheets
        try:
            sheet = sheets.label_for(v.doc[v.page]) or f"Page {v.page + 1}"
        except Exception:                                 # noqa: BLE001
            sheet = f"Page {v.page + 1}"
        self.rfi_dock.show()
        self.rfi_dock.raise_()
        return self.rfis.new("RFI", {"title": "Question", "sheet": sheet,
                                     "page": v.page})

    def new_window(self, popen=None):
        """File > New Window: a second QuantiSheet on purpose (a plain start
        brings the running one forward - singleinstance.py)."""
        import subprocess
        import sys
        from . import singleinstance
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, singleinstance.NEW_WINDOW]
        else:
            cmd = [sys.executable, os.path.join(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))), "quantisheet.py"),
                singleinstance.NEW_WINDOW]
        try:
            return (popen or subprocess.Popen)(cmd, close_fds=True)
        except OSError as e:
            QMessageBox.warning(self, "New Window",
                                f"A new window couldn't be started: {e}")
            return None

    def bid_form_workbook(self, source=None, show=True):
        """Estimate > Bid Form Workbook: the estimator's Excel file from the
        owner's bid form, and the calculating bid form PDF filled from it
        (bidform_xl.py)."""
        from .bidform_xl_ui import BidFormWorkbook
        project = ""
        if self._view is not None:
            try:
                from . import proposal
                project = proposal.read(self._view.doc).get("project", "")
            except Exception:                             # noqa: BLE001
                project = ""
        dlg = BidFormWorkbook(self, source, project,
                              open_result=lambda p: self.open_path(p))
        if show:
            dlg.show()
        return dlg

    def builders_risk(self, spec_doc=None, spec_items=None, show=True):
        """Estimate > Builder's Risk Quote Request: the project summary for
        the insurance company, emailed from here (builders_risk.py)."""
        if not self._view:
            return None
        from .bidform_xl_ui import BuildersRiskRequest
        dlg = BuildersRiskRequest(
            self._view.doc, self, spec_doc, spec_items,
            folder=os.path.dirname(self._path) if self._path else None,
            open_result=lambda p: self.open_path(p))
        if show:
            dlg.show()
        return dlg

    def bid_form_autopilot(self, show=True):
        """Estimate > Bid Form Autopilot: the owner's bid form filled from
        the estimate, then a check for bond, signature and deadline."""
        if not self._view:
            return None
        from .bidform_auto_ui import BidFormDialog
        dlg = BidFormDialog(self._view.doc, self,
                            open_result=lambda p: self.open_path(p))
        if show:
            dlg.show()
        return dlg

    def leveling_board(self, show=True):
        """Estimate > Leveling Board: scope rows x sub quotes, gaps plugged
        from our takeoff, the leveled low into the estimate."""
        if not self._view:
            return None
        from .estimating.levelboard_ui import LevelBoard
        dlg = LevelBoard(self._view.doc, self,
                         on_change=lambda: self._doc_edited())
        if show:
            dlg.show()
        return dlg

    def placeholders(self, show=True):
        """Estimate > Placeholders & Allowances: what is still a
        placeholder, plug or allowance in the bid."""
        if not self._view:
            return None
        from .estimating.bidgate_ui import PlaceholdersDialog
        dlg = PlaceholdersDialog(self._view.doc, self)
        if show:
            dlg.exec()
        return dlg

    def escalation(self, show=True):
        """Estimate > Escalation to Buy Date."""
        if not self._view:
            return None
        from .estimating.bidgate_ui import EscalationDialog
        dlg = EscalationDialog(self._view.doc, self,
                               on_added=lambda: self._doc_edited())
        if show:
            dlg.exec()
        return dlg

    def bid_gate_settings(self, show=True):
        from .estimating.bidgate_ui import SettingsDialog
        dlg = SettingsDialog(self)
        if show:
            dlg.exec()
        return dlg

    def copy_table(self):
        """Edit > Copy as Table: the selected schedule with its columns
        kept, so it pastes into Excel cell by cell."""
        v = self._view
        return v.copy_table() if v is not None else ""

    def select_all_text(self):
        """Edit > Select All Text on Page (Ctrl+A)."""
        if self._key_to_field(QKeySequence.SelectAll):
            return 0                  # Ctrl+A in a list or a text box
        v = self._view
        if v is None:
            return 0
        if v.tool != "select_text":
            self.set_tool("select_text")
        return v.select_all_text()

    def fit_width(self):
        if self._view:
            self._push_view(force=True)
            w = self._scroll.viewport().width() - 24
            self._view.set_zoom(w / max(1, self._view.pg.rect.width))

    def fit_page(self):
        if self._view:
            self._push_view(force=True)
            vp = self._scroll.viewport()
            r = self._view.pg.rect
            # the floating page bar covers the bottom of the drawing: fit
            # the sheet above it (GUI user test r42 F12 - the title block
            # was hidden behind the bar at Fit Page)
            nav = getattr(self, "page_nav", None)
            under = nav.reserve() if nav is not None else 0
            self._view.set_zoom(min((vp.width() - 24) / r.width,
                                    (vp.height() - 24 - under) / r.height))
            bar = self._scroll.verticalScrollBar()
            bar.setValue(bar.minimum())

    def go_to_page(self):
        if not self._view:
            return
        n, ok = QInputDialog.getInt(self, "Go to Page", "Page:",
                                    self._view.page + 1, 1,
                                    self._view.doc.page_count)
        if ok:
            self._go_page(n - 1)

    def _go_page(self, i):
        if self._view:
            self._view.go_to(i)
            self._scroll.verticalScrollBar().setValue(0)

    def set_snap(self, on):
        for i in range(self.tabs.count()):
            t = self.tabs.widget(i)
            view = getattr(t, "_view", None) or getattr(t, "view", None)
            if view is not None and hasattr(view, "set_snap"):
                view.set_snap(on)
        settings.set("snap", bool(on))
        self._flash("Snap to content " + ("on" if on else "off"))

    def _go_spot(self, i, y):
        """Go to page `i` and scroll so height `y` (PDF units from the
        top of the unrotated page) is near the top of the window."""
        if not self._view:
            return
        self._go_page(i)
        v = self._view
        try:
            pt = annotate.from_page(v.pg, fitz.Point(36, y))
            top = max(0, int(v._q(fitz.Rect(pt, pt)).top()) - 90)
        except Exception:
            return
        bar = self._scroll.verticalScrollBar()
        bar.setValue(top)
        # the page may still be resizing; set it again once laid out
        QTimer.singleShot(0, lambda: bar.setValue(top))

    def eventFilter(self, obj, ev):
        """Ctrl + wheel zooms at the cursor (as PDF readers do);
        scrolling past the top/bottom of a page turns the page."""
        if (ev.type() == QEvent.Wheel and self._view and self._tab
                and obj is self._tab.viewport()
                and ev.modifiers() & Qt.ControlModifier):
            dy = ev.angleDelta().y()
            if dy:
                self._zoom_at(1.15 ** (dy / 120), ev.position().toPoint())
            return True
        if (ev.type() == QEvent.Wheel and self._view and self._tab
                and obj is self._tab.viewport()
                and not ev.modifiers() & Qt.ControlModifier):
            bar = self._scroll.verticalScrollBar()
            dy = ev.angleDelta().y()
            if dy < 0 and bar.value() >= bar.maximum() \
                    and self._view.page < self._view.doc.page_count - 1:
                self._view.next_page()
                bar.setValue(0)
                return True
            if dy > 0 and bar.value() <= bar.minimum() and self._view.page > 0:
                self._view.prev_page()
                bar.setValue(bar.maximum())
                return True
        return super().eventFilter(obj, ev)

    # ---- takeoff scale -----------------------------------------------------------
    def sheet_setup(self, scales=True, bookmarks=True):
        """Auto Scale / Auto Bookmark: read every sheet's scale and number +
        title, let the user check them, then apply."""
        from PySide6.QtWidgets import QDialog
        from . import sheets
        from .sheets_dialog import SheetSetupDialog, scan_with_progress
        v = self._view
        if not v or self._collab_blocked("Sheet setup"):
            return None
        rows = scan_with_progress(v.doc, self)
        if not rows:
            return None
        dlg = SheetSetupDialog(rows, self, scales=scales, bookmarks=bookmarks)
        if dlg.exec() != QDialog.Accepted:
            return None
        done = []
        if dlg.do_scales.isChecked():
            sc = dlg.scales()
            marks = [(pg, "set_scale", {"ppu": s[1], "unit": s[2],
                                        "name": s[0]})
                     for pg, s in sorted(sc.items())]
            if marks and v.apply_marks(marks):
                done.append(f"scales on {len(marks)} page(s)")
        if dlg.do_bookmarks.isChecked():
            labels = dlg.labels()
            replace = dlg.replace.isChecked()
            n = self._page_change(
                lambda: sheets.apply_bookmarks(v.doc, labels, replace),
                "Sheet bookmarks added")
            if n:
                done.append(f"{n} sheet bookmark(s)")
                self.bm_dock.show()
                self.bm_dock.raise_()
        self._update_status()
        if done:
            self._flash("Sheet Setup: " + ", ".join(done))
        return done

    def apply_scale_preset(self, name, ppu, unit, all_pages=None):
        v = self._view
        if not v:
            return 0
        if all_pages is None:
            pages = self._ask_scale_pages(name)
            if pages is None:
                return 0
        elif isinstance(all_pages, (list, tuple)):
            pages = [int(i) for i in all_pages]
        else:
            pages = list(range(v.doc.page_count)) if all_pages else \
                [v.page]
        payload = {"ppu": ppu, "unit": unit, "name": name}
        if pages != [v.page]:
            payload["pages"] = sorted(set(pages))
        n = v.apply_marks([(v.page, "set_scale", payload)])
        msg = f"Scale set to {name}" + (f" on {len(pages)} pages"
                                        if len(pages) > 1 else "")
        if all_pages is not None:          # (the dialog already warned)
            from . import scale_guard
            try:
                warn = scale_guard.check(v.doc, v.page, name)
            except Exception:
                warn = []
            if warn:
                msg += ". Check it: " + warn[0]
        self._flash(v.noted(msg) if hasattr(v, "noted") else msg)
        self._update_status()
        return n

    def _ask_scale_pages(self, name):
        """Which pages a written scale goes on - this page, all, the pages
        this size, or a list - with the reduced-print warnings for this
        page (scale_guard). None when cancelled."""
        from PySide6.QtWidgets import (QButtonGroup, QDialog,
                                       QDialogButtonBox, QLabel, QLineEdit,
                                       QRadioButton, QVBoxLayout)
        from . import scale_guard
        v = self._view
        doc, cur = v.doc, v.page
        warn = scale_guard.check(doc, cur, name)
        if doc.page_count == 1 and not warn:
            return [cur]
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Scale {name}")
        lay = QVBoxLayout(dlg)
        if warn:
            w = QLabel("<b>Check this scale.</b><br>" + "<br>".join(warn))
            w.setWordWrap(True)
            w.setObjectName("warn")
            lay.addWidget(w)
        like = scale_guard.pages_like(doc, cur)
        opts = [("This page only", [cur])]
        if doc.page_count > 1:
            opts.append((f"Every page ({doc.page_count})",
                         list(range(doc.page_count))))
            if 1 < len(like) < doc.page_count:
                opts.append((f"The {len(like)} pages this size "
                             f"({scale_guard.size_in(doc[cur])[0]:g}x"
                             f"{scale_guard.size_in(doc[cur])[1]:g} in)",
                             like))
        group = QButtonGroup(dlg)
        # default: every page drawn at the same size (Nov 4, fewer
        # clicks) - the size-alike option, or every page when they all are
        default = 0
        if len(like) == doc.page_count and len(opts) > 1:
            default = 1
        elif len(opts) > 2:
            default = 2
        if warn:
            default = 0             # a doubtful scale: this page only
        for i, (text, _p) in enumerate(opts):
            rb = QRadioButton(text)
            rb.setChecked(i == default)
            group.addButton(rb, i)
            lay.addWidget(rb)
        listed = None
        if doc.page_count > 1:
            rb = QRadioButton("These pages:")
            group.addButton(rb, len(opts))
            lay.addWidget(rb)
            listed = QLineEdit()
            listed.setPlaceholderText("e.g. 1-4, 7, 9-")
            listed.textEdited.connect(lambda _t: rb.setChecked(True))
            lay.addWidget(listed)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        while True:
            if dlg.exec() != QDialog.Accepted:
                return None
            i = group.checkedId()
            if i < len(opts):
                return opts[i][1]
            got = scale_guard.parse_pages(listed.text(), doc.page_count)
            if got:
                return got
            QMessageBox.information(self, "Scale", "Type pages like "
                                    "1-4, 7, 9-")

    # ---- panels ------------------------------------------------------------------
    def _panel_docks(self):
        return ((self.markups, self.markups_dock),
                (self.takeoff_tree, self.takeoff_dock),
                (self.quantities, self.qty_dock),
                (self.estimate, self.est_dock),
                (self.assemblies, self.asm_dock))

    @staticmethod
    def _dock_showing(dock):
        return dock.isVisible() and not dock.visibleRegion().isEmpty()

    def _refresh_panels(self):
        """Refresh the panels you can see; the others are marked stale and
        catch up when their tab is brought forward (refreshing all four
        after every edit took half a second on a busy sheet)."""
        if not self._view:
            return
        with annotate.scan_cache():          # one scan, shared by all
            for panel, dock in self._panel_docks():
                if self._dock_showing(dock) or not self.isVisible():
                    panel.refresh()
                    panel._stale = False
                else:
                    panel._stale = True
            self._update_qlink()

    def _panel_shown(self, panel, visible):
        if visible and getattr(panel, "_stale", False) and self._view:
            panel._stale = False
            QTimer.singleShot(0, panel.refresh)

    def scan_quality(self, show=True, languages=None):
        """Document > Check Scan Quality: which scanned pages will OCR
        badly (coarse, tilted, blank) before anyone trusts their text."""
        from . import scan_check_ui
        return scan_check_ui.open_dialog(self, show=show,
                                         languages=languages)

    def billing(self, tab=None):
        """The Contract & Billing window for this document (non-modal)."""
        from .billing_ui import BillingDialog
        v = self._view
        if not v:
            return None
        dlg = getattr(self, "_billing_dlg", None)
        if dlg is None or dlg.doc is not v.doc:
            if dlg is not None:
                dlg.close()
            from . import master_hook
            proj = master_hook.store_for(self)

            def open_pay_apps(proj=proj):
                from .pm import center
                w = center.open_center(proj.folder, self)
                w.show_tool("payapp")
            if proj is not None and \
                    proj.setting("billing_ledger") == "project":
                # one billing ledger (P1): this job's billing lives in
                # Project Center now - go straight there
                open_pay_apps()
                return None
            dlg = BillingDialog(
                v.doc, self, selected_refs=lambda: [
                    self._view.selected["ref"]] if self._view and
                self._view.selected else [], project=proj,
                open_project=open_pay_apps if proj is not None else None)
            dlg.edited.connect(self._doc_edited)
            self._billing_dlg = dlg
        else:
            dlg.refresh()
        if tab:
            for i in range(dlg.tabs.count()):
                if dlg.tabs.tabText(i) == tab:
                    dlg.tabs.setCurrentIndex(i)
        dlg.show()
        dlg.raise_()
        return dlg

    def _project_window(self, attr, make, tab):
        v = self._view
        if not v:
            return None
        dlg = getattr(self, attr, None)
        if dlg is None or dlg.doc is not v.doc:
            if dlg is not None:
                dlg.close()
            dlg = make(v)
            dlg.edited.connect(self._project_edited)
            dlg.go_to.connect(self._go_rfi)
            setattr(self, attr, dlg)
        else:
            dlg.refresh()
        if tab is not None:
            dlg.tabs.setCurrentIndex(tab)
        dlg.show()
        dlg.raise_()
        return dlg

    def _project_edited(self):
        self._doc_edited()
        if self._view:
            self._view._render()

    def doc_control(self, tab=None):
        """Drawing register, transmittals and addenda (non-modal)."""
        from .project_ui import DocControlDialog
        return self._project_window(
            "_doccontrol_dlg", lambda v: DocControlDialog(v.doc, self), tab)

    def _view_center(self):
        """(page, unrotated point) in the middle of what's on screen."""
        v = self._view
        if not v:
            return None
        vp = self._scroll.viewport()
        w = v.mapFrom(vp, QPoint(vp.width() // 2, vp.height() // 2))
        sp = v._sp(w)
        r = v.pg.rect
        sp = fitz.Point(min(max(sp.x, 10), r.width - 10),
                        min(max(sp.y, 10), r.height - 10))
        pt = annotate.to_page(v.pg, sp)
        return v.page, (pt.x, pt.y)

    def _selected_markup(self):
        v = self._view
        if v and v.selected:
            return v.page, v.selected["ref"]
        return None

    def code_check(self):
        """Occupant load, egress, accessibility and plumbing checks."""
        from .codecheck_ui import CodeCheckDialog
        return self._project_window(
            "_codecheck_dlg", lambda v: CodeCheckDialog(v.doc, self), None)

    def ada_pdf(self, page=None):
        """The Justice Department's 2010 ADA Standards PDF (public domain,
        ships with QuantiSheet), open in a tab - search it with Ctrl+F, figures
        and all. `page`: 1-based page to show."""
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "data", "ada", "2010-design-standards.pdf")
        if not os.path.isfile(path):
            QMessageBox.warning(self, "ADA Standards PDF",
                                "The ADA Standards PDF isn't installed.")
            return False
        if not self.open_path(path):
            return False
        if page:
            self._go_page(int(page) - 1)
        return True

    def energy_code(self, tab=0):
        """Climate zone by county, the Code Library (your own code books)
        and where to read the energy code (Module tab)."""
        from .energy_ui import EnergyDialog
        dlg = getattr(self, "_energy_dlg", None)
        if dlg is None:
            dlg = self._energy_dlg = EnergyDialog(self)
        dlg.tabs.setCurrentIndex(tab)
        dlg.show()
        dlg.raise_()
        return dlg

    def submittal_log(self):
        """Project Center's Submittals: the log by spec section, packages
        for the architect and engineers, and From Spec Book."""
        w = self.project_center()
        if w is not None and hasattr(w, "show_tool"):
            w.show_tool("submittal")
        return w

    def ada(self, tab=0):
        """The 2010 ADA Standards (searchable) and the commercial ADA
        checker. Opens without a drawing; with one, the checker's counts
        are saved in the PDF."""
        from .ada_ui import AdaDialog
        v = self._view
        doc = v.doc if v else None
        dlg = getattr(self, "_ada_dlg", None)
        if dlg is None or dlg.doc is not doc:
            if dlg is not None:
                dlg.close()
            dlg = AdaDialog(doc, self)
            dlg.checker.blocked = self._collab_blocked
            if v is not None:
                dlg.checker.apply = lambda proj, view=v: self._ada_apply(
                    view, proj)
            if doc is not None:
                dlg.edited.connect(self._project_edited)
            self._ada_dlg = dlg
        dlg.tabs.setCurrentIndex(tab)
        dlg.show()
        dlg.raise_()
        return dlg

    def _ada_apply(self, view, project):
        """The ADA checker's counts saved as a set_jobdata op: one undo
        step, sent to everyone in live collaboration (outside review,
        Nov 7 - H4)."""
        import json
        from . import ada_check
        if getattr(view, "doc", None) is None or view.doc.is_closed:
            return False
        return bool(view.apply_marks([(0, "set_jobdata", {
            "file": ada_check.FILE,
            "data": json.dumps(project, indent=1)})]))

    def quality(self, tab=None):
        """Punch list and three-phase inspections (non-modal)."""
        from .project_ui import QualityDialog
        return self._project_window(
            "_quality_dlg", lambda v: QualityDialog(
                v.doc, self, where=self._view_center,
                selected=self._selected_markup), tab)

    def change_from_markup(self):
        dlg = self.billing("Change Orders")
        return dlg and dlg._co_from_markups()

    def labor_settings(self):
        from PySide6.QtWidgets import QDialog
        from .estimating_ui import LaborDialog
        v = self._view
        if not v:
            return None
        dlg = LaborDialog(v.doc, self)
        if dlg.exec() == QDialog.Accepted:
            self._doc_edited()
            self.assemblies.refresh()
        return dlg

    def bid_tabs(self):
        from .pricedb_ui import BidTabDialog
        dlg = BidTabDialog(self._view.doc if self._view else None, self)
        self._bidtab_dlg = dlg
        dlg.show()
        return dlg

    def bid_leveling(self, project=None):
        from .leveling_ui import LevelingDialog
        dlg = LevelingDialog(self, project)
        self._level_dlg = dlg
        dlg.show()
        return dlg

    def scope_sheets(self, store=None):
        """Estimate > Scope Sheets: one bid comparison sheet per trade for
        the open drawing's project (else asks which project)."""
        from .pm import scope_sheet_ui
        return scope_sheet_ui.open_for_window(self, store)

    def take_into_assembly(self, show=True):
        """Takeoff > Take Off Into Assembly: division, then assembly, then
        measure into a group bound to it (take_into_assembly.py)."""
        from . import take_into_assembly
        return take_into_assembly.run(self, show)

    def price_database(self):
        from .pricedb_ui import DatabaseDialog
        dlg = DatabaseDialog(self)
        self._pricedb_dlg = dlg
        dlg.show()
        return dlg

    def location_factors(self):
        """Estimate > Location Factors: your regions and factors (with a
        drawing open, Use for This Job picks the job's region)."""
        from .location_ui import LocationFactorsDialog
        v = self._view
        dlg = LocationFactorsDialog(self, v.doc if v else None)
        self._location_dlg = dlg
        dlg.exec()
        return dlg

    def cost_books(self):
        from PySide6.QtWidgets import QDialog
        from .estimating_ui import CostBookDialog
        v = self._view
        if not v:
            return None
        dlg = CostBookDialog(v.doc, self)
        if dlg.exec() == QDialog.Accepted:
            self._doc_edited()
            self.assemblies.refresh()
        return dlg

    # ---- estimate lines (Estimate panel) ---------------------------------------
    def _show_estimate(self):
        if self._view:
            self.est_dock.show()
            self.est_dock.raise_()

    def add_from_cost_book(self, show=True):
        """Tick cost book items by CSI division; they become Estimate
        panel lines (optionally linked to a takeoff group)."""
        self._show_estimate()
        return self.estimate.add_from_cost_book(show)

    def quick_sf_estimate(self, show=True):
        """A building priced from your own past jobs' $/SF, as allowance
        lines by division."""
        self._show_estimate()
        return self.estimate.quick_sf(show)

    def award_estimate(self, ask=True):
        """Estimate > Award: the estimate becomes the Project Center job's
        budget by cost code, and draft commitments (P1)."""
        v = self._view
        if not v:
            return None
        from . import master_hook
        from .pm import award
        store = master_hook.store_for(self)
        if store is None:
            QMessageBox.information(
                self, "Award", "This drawing isn't in a Project Center job "
                "yet. Open Project Center and make a job in this drawing's "
                "folder first.")
            return None
        p = award.plan(v.doc)
        if ask and QMessageBox.question(
                self, "Award", f"Put the estimate (${_c2(p['total']):,.2f}) into "
                f"the job \u201c{store.name}\u201d as "
                f"{len(p['budget'])} budget line(s) and "
                f"{len(p['commitments'])} draft subcontract(s)?") != \
                QMessageBox.Yes:
            return None
        try:
            got = award.award(v.doc, store)
        except award.AwardError as e:
            QMessageBox.warning(self, "Award", str(e))
            return None
        self._flash(f"Budget made: {len(got['budget'])} line(s), "
                    f"${_c2(got['total']):,.2f}")
        return got

    def price_these(self, show=True):
        """Estimate > Price These...: every takeoff line with a quantity but
        no price, in one list to price (GUI user test r42 F03)."""
        v = self._view
        if not v:
            return None
        from . import price_these as pt
        if not pt.unpriced_lines(v.doc):
            self._flash("Every takeoff line has a price.")
            return None
        dlg = pt.PriceTheseDialog(v.doc, self)
        if not show:
            return dlg
        if dlg.exec():
            n = dlg.save()
            if n:
                self._doc_edited()
                try:
                    self.estimate.refresh()
                except Exception:                         # noqa: BLE001
                    log.debug("estimate panel not refreshed", exc_info=True)
                self._flash(f"Priced {n} line(s)")
        return dlg

    def model_estimate(self, show=True):
        """A building priced from its type, SF and options: from your job
        history and from a Generate Set plan's quantities, side by side;
        allowance lines by division."""
        self._show_estimate()
        return self.estimate.model_estimate(show)

    def _doc_edited(self):
        """A panel changed the document directly (estimate, bookmarks)."""
        v = self._view
        if v:
            v.history.snapshot()
            v.mark_dirty()

    # ---- markup and layer features ---------------------------------------------------
    def _column_edit(self, key, column, value):
        from . import columns
        v = self._view
        if not v:
            return
        columns.set_value(v.doc, key, column, value)
        self._doc_edited()
        self.markups.refresh()

    def manage_columns(self):
        from . import columns, styles
        from .gap_dialogs import ColumnsDialog
        v = self._view
        if not v:
            return
        dlg = ColumnsDialog(v.doc, self)
        if not dlg.exec():
            return
        cols, sts = dlg.values()
        columns.set_columns(v.doc, cols)
        styles.set_custom_statuses(sts)
        self._doc_edited()
        self.markups.refresh()
        self.properties.refresh()

    def line_styles(self):
        from .gap_dialogs import LineStylesDialog
        LineStylesDialog(self).exec()
        self.properties.refresh()

    def hatch_patterns(self):
        from .gap_dialogs import HatchDialog
        HatchDialog(self).exec()
        self.properties.refresh()

    def layers(self):
        from .gap_dialogs import LayersDialog
        if self._view:
            LayersDialog(self._view, self).exec()
            self.properties.refresh()

    def refresh_legends(self):
        v = self._view
        if not v:
            return
        n = v.refresh_legends()
        self._flash("Legends updated" if n else
                    "No legends on this page (Markup > Legend draws one)")

    def manage_viewports(self):
        v = self._view
        if not v:
            return
        vps = annotate.read_viewports(v.doc, v.page)
        if not vps:
            QMessageBox.information(
                self, "Viewports", "No viewports on this page. Use Takeoff > "
                "Viewport and drag a box around a detail drawn at another "
                "scale.")
            return
        names = [f"{vp['name']}  ({vp.get('label') or vp['unit']})"
                 for vp in vps]
        pick, ok = QInputDialog.getItem(
            self, "Viewports", "Viewports on this page. Choose one to "
            "remove:", names, 0, False)
        if ok and pick:
            v.remove_viewport(vps[names.index(pick)]["name"])
            v.update()

    @staticmethod
    def _ai_limit():
        from .ai import dialogs
        return dialogs.PART_LIMIT

    @staticmethod
    def _minutes(seconds):
        """"5 minutes", "1 minute", "45 seconds" - never "0 minutes"."""
        if seconds < 90:
            return f"{seconds:.0f} seconds"
        m = round(seconds / 60)
        return f"{m} minute" + ("" if m == 1 else "s")

    def watch_plan_folder(self, folder=None):
        """Project > Watch Plan Folder (Nov 19): the folder this job's plan
        sets and addenda are downloaded into, from any plan room. New PDFs
        there are offered: log an addendum in the Addenda Gate, compare
        with this set (then Slip Sheet), or open. Choosing the same folder
        again, or Cancel with one set, offers to stop watching."""
        from . import planwatch
        v = self._view
        if not v:
            return None
        cur = planwatch.folder_of(v.doc)
        if folder is None:
            start = cur or os.path.dirname(self._path or "") or \
                os.path.expanduser("~")
            folder = QFileDialog.getExistingDirectory(
                self, "Plan Folder to Watch (where this job's sets and "
                "addenda are downloaded)", start)
            if not folder:
                if cur and QMessageBox.question(
                        self, "Watch Plan Folder",
                        f"Stop watching {cur}?") == QMessageBox.Yes:
                    planwatch.stop(v.doc)
                    self._doc_edited()
                    self._flash("Stopped watching the plan folder")
                return None
        try:
            n = planwatch.watch(v.doc, folder)
        except ValueError as e:
            QMessageBox.warning(self, "Watch Plan Folder", str(e))
            return None
        self._doc_edited()
        self._plan_offered.pop(id(v.doc), None)
        self._flash(f"Watching {os.path.basename(folder)} for new sheets "
                    f"and addenda ({n} PDF(s) there now)", 10000)
        return n

    def check_plan_folder(self, quiet=True, show=True):
        """Look in the job's watched plan folder now. New files are offered
        once (quiet: say nothing when there are none). Returns the new
        files."""
        from . import planwatch
        v = self._view
        if not v or not getattr(v, "doc", None):
            return []
        try:
            if not planwatch.folder_of(v.doc):
                if not quiet:
                    self._flash("No plan folder is watched for this job "
                                "(Project > Watch Plan Folder)")
                return []
            items = planwatch.new_files(v.doc)
        except Exception:                                 # noqa: BLE001
            log.info("plan folder check", exc_info=True)
            return []
        offered = self._plan_offered.setdefault(id(v.doc), set())
        fresh = [it for it in items
                 if (it["rel"], it["mtime"]) not in offered] if quiet \
            else items
        if not fresh:
            if not quiet:
                self._flash("Nothing new in the plan folder")
            return []
        offered |= {(it["rel"], it["mtime"]) for it in fresh}
        if show:
            from .planwatch_ui import NewPlansDialog
            dlg = NewPlansDialog(self, v.doc, items)
            self._plan_dlg = dlg
            dlg.show()
        return items

    def bid_submittal(self, show=True):
        """Estimate > Bid Submittal Checklist (Nov 19): signed bid forms,
        bid bond, license, insurance and the bid reference number, ticked
        off and attached; saved with the job."""
        from .bidsubmittal_ui import SubmittalDialog
        v = self._view
        if not v:
            return None
        dlg = SubmittalDialog(v.doc, self)
        if show:
            ok = dlg.exec()
            self._doc_edited()
            return ok
        return dlg

    # ---- project assistants (Nov 23, Jon) ------------------------------
    def _job_store(self, pick=False, title="Project"):
        """The open drawing's Project Center job (its folder or the one
        above it); with pick, ask which job when there isn't one."""
        from .pm.store import ProjectStore, open_store
        if self._path:
            d = os.path.dirname(os.path.abspath(self._path))
            for folder in (d, os.path.dirname(d)):
                try:
                    if ProjectStore.exists(folder):
                        return open_store(folder)
                except Exception:                         # noqa: BLE001
                    continue
        if pick:
            from .pm import scheduler as sch
            return sch.choose_schedule(
                self, title, "Which project? Pick one or open its folder:",
                "New Project…")
        return None

    def send_quantilink(self, store=None, show=True, opener=None):
        """Home > Send with QuantiLink (quantilink_ui.py): the job of the
        open drawing, or pick one."""
        from . import quantilink_ui
        store = store if store is not None else self._job_store()
        return quantilink_ui.open_send(self, store, show=show, opener=opener)

    def ask_project(self, store=None, show=True):
        """Ask the Project: a question answered from the open PDF and the
        job's RFIs, submittals, daily logs, meetings and issues
        (askproject_ui.py)."""
        from . import askproject_ui
        doc = self._view.doc if self._view is not None else None
        store = store if store is not None else self._job_store()
        dlg = askproject_ui.AskDialog(self, doc, store)
        if show:
            dlg.setAttribute(Qt.WA_DeleteOnClose)
            dlg.show()
        return dlg

    def daily_draft(self, store=None, show=True):
        """Draft a daily log from the day's notes and photos."""
        from . import pmassist_ui
        store = store if store is not None else self._job_store(
            True, "Draft Daily Log")
        if store is None:
            return None
        dlg = pmassist_ui.DailyDraftDialog(self, store)
        return pmassist_ui._show(dlg) if show else dlg

    def submittal_check(self, store=None, show=True):
        """Check a submittal against its spec section (the open PDF is
        taken as the spec book)."""
        from . import pmassist_ui
        store = store if store is not None else self._job_store(
            True, "Check Submittal")
        doc = self._view.doc if self._view is not None else None
        dlg = pmassist_ui.SubmittalCheckDialog(self, store, doc)
        return pmassist_ui._show(dlg) if show else dlg

    def risk_flags(self, store=None, show=True):
        """Project Risk Flags: what in the job looks likely to cost time
        or money, with the reason."""
        from . import pmassist_ui
        store = store if store is not None else self._job_store(
            True, "Project Risk Flags")
        if store is None:
            return None
        dlg = pmassist_ui.RiskFlagsDialog(self, store)
        return pmassist_ui._show(dlg) if show else dlg

    def model_quantities(self, path=None, show=True):
        """3D Model Quantities (Nov 23): an IFC model's elements by kind,
        type and storey with the quantities it carries; ticked rows go on
        the open drawing's estimate (ifcmodel_ui.py). Works with no PDF
        open."""
        from . import ifcmodel_ui
        if show:
            return ifcmodel_ui.show(self, path)
        return ifcmodel_ui.IfcDialog(self, path)

    def project_analysis(self, show=True):
        """Project Analysis (Nov 20, Jon): open the specs and click it -
        project name, address, budget, substantial and final completion,
        liquidated damages, summary, bid date, pre-bid meeting and
        retainage, each with its page, then the other bid terms."""
        from .bidterms_ui import ProjectAnalysisDialog
        if not self._view:
            self._flash("Open the project manual (specifications) first, "
                        "then click Project Analysis.")
            return None
        dlg = ProjectAnalysisDialog(self)
        if show:
            dlg.show()
        return dlg

    def bid_terms(self, show=True):
        """Estimate > Find Bid Terms (Nov 19): bid bond, hold days,
        prevailing wage, liquidated damages, pre-bid, goals, retainage,
        contract time and alternates read from the documents, with
        pages."""
        from .bidterms_ui import BidTermsDialog
        if not self._view:
            return None
        dlg = BidTermsDialog(self)
        if show:
            dlg.show()
        return dlg

    def spec_manufacturers(self, show=True):
        """Estimate > Manufacturers in Specs (Nov 20): each section's
        listed manufacturers and basis-of-design products, with pages,
        for a quote-request list."""
        from .specmfrs_ui import SpecMfrsDialog
        if not self._view:
            return None
        dlg = SpecMfrsDialog(self)
        if show:
            dlg.show()
        return dlg

    def video_tutorials(self, open_url=None):
        """Help > Video Tutorials: QuantiSheet's YouTube channel in the
        browser (Nov 17). Returns the address."""
        from . import helpcenter
        url = helpcenter.VIDEO_URL
        if open_url is None:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            open_url = (lambda u: QDesktopServices.openUrl(QUrl(u)))
        open_url(url)
        self._flash("Opening QuantiSheet's video tutorials in your browser")
        return url

    def _open_file_external(self, path):
        try:
            os.startfile(path)                    # noqa: S606 (Windows)
        except (AttributeError, OSError):
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def _update_qlink(self):
        from . import qlink
        tab, v = self._tab, self._view
        if not v or not tab or not tab.path:
            return
        path = qlink.link_for(tab.path)
        if not path:
            return
        msg = qlink.update(v.doc, path)
        if msg:
            self._flash(msg)

    def _markup_change(self, page, ref, changes):
        self._view.apply_marks([(page, "set_annot", {**ref, **changes})])

    def _markup_delete(self, items):
        self._view.apply_marks([(page, "delete_annot", ref)
                                for page, ref in items])

    def _choose_project(self):
        self.docs_dock.show()
        self.docs_dock.raise_()
        self.documents._choose()

    # ---- files -----------------------------------------------------------------
    def _confirm_discard(self, tab=None):
        tab = tab or self._tab
        if not tab or not tab.view.dirty:
            return True
        self.tabs.setCurrentWidget(tab)
        r = QMessageBox.question(
            self, "Unsaved changes",
            f"Save changes to {os.path.basename(tab.path or 'Untitled')}?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            return self.save_file()
        return r == QMessageBox.Discard

    def close_tab(self, index):
        tab = self.tabs.widget(index)
        if not isinstance(tab, DocTab):
            return True
        if not self._confirm_discard(tab):
            return False
        if hasattr(self, "autosaver"):          # saved or let go on purpose
            self.autosaver.closed(tab.view, None)
            self.autosaver.closed(tab.view, tab.path)
        if tab.view.session:
            tab.view.session.stop()
        tab.view.stop_timers()     # nothing may run on a closed document
        lf = getattr(tab.view, "_lock_file", None)
        if lf:
            from . import jobsafe
            jobsafe.drop_lock(lf)
        self.tabs.removeTab(self.tabs.indexOf(tab))
        tab.view.doc.close()
        if tab.path:              # the drawing process lets go of it too
            from . import render_worker
            render_worker.release(tab.path)
        tab.deleteLater()
        return True

    def closeEvent(self, e):
        for i in reversed(range(self.tabs.count())):
            if not self.close_tab(i):
                e.ignore()
                return
        self._save_window_state()
        if getattr(self, "voice", None) is not None:
            self.voice.listener.stop()
        e.accept()
        # let the window go: the theme hub would otherwise keep it (and
        # every widget in it) alive after it's closed
        from . import theme
        for slot in (self._retheme, getattr(getattr(self, "ribbon", None),
                                            "retint", None)):
            try:
                if slot:
                    theme.hub.changed.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self.deleteLater()

    def _save_window_state(self):
        try:
            settings.set("window", {
                "geometry": bytes(self.saveGeometry().toBase64()).decode(),
                "maximized": self.isMaximized()})
        except Exception:
            logging.getLogger(__name__).debug("ignored error", exc_info=True)

    def show_restored(self):
        """Show the window maximized - always (Jon, 0.13.11). The saved
        geometry is still restored first, so un-maximizing it goes back to
        the size it had last time."""
        from PySide6.QtCore import QByteArray
        w = settings.get("window") or {}
        try:
            if w.get("geometry"):
                self.restoreGeometry(
                    QByteArray.fromBase64(w["geometry"].encode()))
        except Exception:
            logging.getLogger(__name__).debug("ignored error", exc_info=True)
        from . import modern_ui
        modern_ui.ensure_maximized(self)

    # ---- recent files --------------------------------------------------------
    def _remember_recent(self, path):
        settings.remember_recent(path)

    def _fill_recent(self):
        m = self.recent_menu
        m.clear()
        items = settings.recent()
        if not items:
            a = m.addAction("(none yet)")
            a.setEnabled(False)
            return
        for n, p in enumerate(items, 1):
            label = f"&{n % 10}  {os.path.basename(p)}" if n <= 10 else \
                os.path.basename(p)
            a = m.addAction(label)
            a.setToolTip(p)
            a.setStatusTip(p)
            a.triggered.connect(lambda _=False, p=p: self.open_path(p))
        m.addSeparator()
        m.addAction("Clear List", lambda: settings.set("recent", []))

    def open_file(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Open PDF", "",
                                                "PDF (*.pdf)")
        for path in paths:
            self.open_path(path)

    # ---- drag and drop: PDFs from Explorer open in tabs ----------------------
    @staticmethod
    def _dropped_pdfs(mime):
        if not mime.hasUrls():
            return []
        return [u.toLocalFile() for u in mime.urls() if u.isLocalFile() and
                u.toLocalFile().lower().endswith(".pdf")]

    @staticmethod
    def _mail_pdfs(mime):
        """PDF attachments being dragged out of a mail program (Nov 27)."""
        try:
            from . import outlookdrop
            return outlookdrop.wanted(mime)
        except Exception:                                 # noqa: BLE001
            return []

    def dragEnterEvent(self, ev):
        m = ev.mimeData()
        if self._dropped_pdfs(m) or self._mail_pdfs(m):
            ev.acceptProposedAction()
        else:
            ev.ignore()

    def dragMoveEvent(self, ev):
        m = ev.mimeData()
        if self._dropped_pdfs(m) or self._mail_pdfs(m):
            ev.acceptProposedAction()
        else:
            ev.ignore()

    def _drop_from_mail(self, mime):
        """Attachments dragged from Outlook: save the PDFs in
        Downloads\\QuantiSheet and open them. Those Outlook has to be
        asked for are fetched just after the drop (it can't answer while
        its own drag is still going)."""
        from . import outlookdrop
        try:
            paths, wait = outlookdrop.save(mime)
        except Exception:                                 # noqa: BLE001
            log.warning("mail drop", exc_info=True)
            return False
        for p in paths:
            self.open_path(p)
        if wait:
            whole = list(wait) == [outlookdrop.WHOLE]
            self._flash("Getting the PDF from Outlook...", 4000)

            def fetch(names=list(wait)):
                got = outlookdrop.later(names)
                for p in got:
                    self.open_path(p)
                if not got and whole:
                    self._flash(
                        "No PDF came across from that email. Open the "
                        "email and drag the PDF itself onto QuantiSheet.",
                        12000)
                elif not got:
                    self._flash(
                        "That attachment didn't come across. Save it from "
                        "the email (right-click > Save As), then open it "
                        "here.", 12000)
            QTimer.singleShot(250, fetch)
        return bool(paths or wait)

    def dropEvent(self, ev):
        paths = self._dropped_pdfs(ev.mimeData())
        if not paths:
            if self._mail_pdfs(ev.mimeData()) and \
                    self._drop_from_mail(ev.mimeData()):
                ev.acceptProposedAction()
                return
            ev.ignore()
            return
        ev.acceptProposedAction()
        for p in paths[:20]:
            self.open_path(p)
        # say what didn't open (review 0.12.32 #11)
        m = ev.mimeData()
        others = [os.path.basename(u.toLocalFile()) for u in m.urls()
                  if u.isLocalFile() and
                  not u.toLocalFile().lower().endswith(".pdf")]
        notes = []
        if len(paths) > 20:
            notes.append(f"Opened 20 of {len(paths)} PDFs (20 at a time).")
        if others:
            notes.append("Not PDFs, skipped: " + ", ".join(others[:5]) +
                         (f" and {len(others) - 5} more" if len(others) > 5
                          else ""))
        if notes:
            self._flash("  ".join(notes), 8000)

    def _open_failed(self, path, exc, kind=None, ask=None, show=None):
        """Venice #9/#10 (Nov 4): say why a file didn't open and what to
        do next, with the technical text under Details. For a damaged PDF,
        offer to repair a copy; the original is never changed. If kept job
        data matches the drawings, the usual on-open check offers it back
        for the repaired copy."""
        from . import openerrors
        kind = kind or openerrors.classify(exc, path)
        head, step = openerrors.message(kind, path)
        log.warning("open failed (%s) %s: %s", kind, path, exc)
        if kind == "damaged" and "(repaired" not in os.path.basename(path):
            if ask is None:
                # the static warning (not a custom box): what the program
                # always used here, and what the tests stand in for
                def ask(text):
                    return QMessageBox.warning(
                        self, "Open", text + "\n\nRepair a copy now?\n\n"
                        f"Details: {type(exc).__name__}: {str(exc)[:200]}",
                        QMessageBox.Yes | QMessageBox.Cancel) == \
                        QMessageBox.Yes
            if not ask(f"{head}\n\n{step}"):
                return False
            try:
                out = openerrors.repair(path)
            except Exception as ex2:                      # noqa: BLE001
                log.warning("repair failed for %s", path, exc_info=True)
                (show or self._open_error_box)(
                    f"{os.path.basename(path)}: QuantiSheet couldn't repair "
                    "this PDF.", "Ask for a new copy of the file.",
                    f"{type(ex2).__name__}: {ex2}")
                return False
            self._flash(f"Repaired copy saved: {os.path.basename(out)} "
                        "(your original wasn't changed)")
            return self.open_path(out)
        (show or self._open_error_box)(head, step,
                                       f"{type(exc).__name__}: {exc}")
        return False

    def _open_error_box(self, head, step, details):
        b = QMessageBox(self)
        b.setIcon(QMessageBox.Icon.Warning)
        b.setWindowTitle("Open")
        b.setText(f"{head}\n\n{step}")
        b.setDetailedText(details)
        b.setModal(False)
        b.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        b.show()

    def open_path(self, path):
        path = os.path.abspath(path)
        if path.lower().endswith(toolchest.FILE_EXT):   # a tool set file
            names = self.chest.import_file(path)
            if names:
                self.chest_dock.show()
                self.chest_dock.raise_()
                self._flash("Tool Chest: added " + ", ".join(names))
            return bool(names)
        for i in range(self.tabs.count()):
            t = self.tabs.widget(i)
            if isinstance(t, DocTab) and t.path and \
                    os.path.normcase(t.path) == os.path.normcase(path):
                self.tabs.setCurrentIndex(i)
                return True
        try:
            doc = fitz.open(path)
        except Exception as ex:
            return self._open_failed(path, ex)
        if not doc.is_pdf:
            doc.close()
            return self._open_failed(path, ValueError("not a pdf"), "not_pdf")
        needed_pass = bool(doc.needs_pass)
        typed_pw, auth_code = None, 0
        if doc.needs_pass:
            prompt = (f"{os.path.basename(path)} is password-protected. "
                      "Password:")
            while True:
                pw, ok = QInputDialog.getText(
                    self, "Password", prompt,
                    echo=QLineEdit.EchoMode.Password)
                prompt = ("Wrong password - try again. Password for "
                          f"{os.path.basename(path)}:")
                if not ok:
                    doc.close()
                    return False
                auth_code = doc.authenticate(pw)
                if auth_code:
                    typed_pw = pw
                    break
        if doc.page_count == 0:
            doc.close()
            return self._open_failed(path, ValueError("no pages"), "damaged")
        protection = protection_on_open(doc, typed_pw, auth_code,
                                        needed_pass)
        typed_pw = None
        try:
            view = PdfView(doc, path)
        except Exception as ex:             # a damaged PDF must never fail
            log.warning("could not open %s", path, exc_info=True)   # quietly
            try:
                doc.close()
            except Exception:
                pass
            return self._open_failed(path, ex, "damaged")
        view.protection = protection
        self._remember_recent(path)
        view.on_change = self._update_status
        view.status.connect(self._flash)
        view.snapshot_taken.connect(self._snapshot_toast)
        view.page_changed.connect(self._page_edited)
        view.zoom_requested.connect(self._zoom_from_view)
        view.marquee_zoom.connect(self.zoom_to_rect)
        view.rfi_requested.connect(
            lambda: self.new_rfi("RFI", from_selection=True))
        view.view_menu.connect(self._view_menu)
        view.want_tool.connect(lambda t: self.set_tool(t, ask=False))
        view.repeat_tool.connect(self.repeat_last_tool)
        view.number_key.connect(self._number_key)
        view.selection_changed.connect(self.properties.refresh)
        view.add_to_chest.connect(self.add_selected_to_chest)
        view.count_resumed.connect(self._count_resumed)
        view.crop_requested.connect(self.crop_pages)
        view.link_clicked.connect(self.follow_link)
        view.redaction_failed.connect(
            lambda msg, v=view: self._redaction_failed(v, msg))
        tab = DocTab(view, path)
        tab.viewport().installEventFilter(self)
        i = self.tabs.addTab(tab, os.path.basename(path))
        self.tabs.setTabToolTip(i, path)
        self.tabs.setCurrentIndex(i)
        self._tab_switched(i)
        view.setFocus()
        QTimer.singleShot(0, self.fit_width)
        self._job_safety_on_open(view, path)
        if not os.environ.get("QUANTISHEET_SMOKE"):
            try:                       # scales from the title blocks (Nov 4)
                from . import quickaccess
                quickaccess.auto_scale_on_open(self, view, path)
            except Exception:                             # noqa: BLE001
                log.debug("auto scale on open", exc_info=True)
            try:                       # Ctrl+K sheet names (Nov 16)
                from . import quickaccess
                quickaccess.labels_on_open(view, path)
            except Exception:                             # noqa: BLE001
                log.debug("sheet names on open", exc_info=True)
        try:          # takeoff clicked out in the browser add-on's viewer
            from . import webmarks
            got = webmarks.take(view, path)
            if got:
                added, left = got
                log.info("browser takeoff: %d added, %d left out", added,
                         left)
                text = (f"{added} takeoff measurement"
                        f"{'' if added == 1 else 's'} from the browser "
                        "viewer added (Ctrl+Z undoes them).")
                if left:
                    text += (f" {left} left out: set the scale on that "
                             "page and measure again.")
                QTimer.singleShot(0, lambda t=text: self._flash(t, 15000))
        except Exception:                                 # noqa: BLE001
            log.warning("browser takeoff marks not added", exc_info=True)
        if getattr(doc, "is_repaired", False):
            # a non-blocking notice: the file opens as usual
            note = repaired_notice(path)
            self.tabs.setTabToolTip(i, f"{path}\n{note}")
            QTimer.singleShot(0, lambda n=note: self._flash(n, 20000))
            log.info("%s was repaired when it was opened", path)
        elif getattr(doc, "is_form_pdf", 0):
            # Nov 17: say a form can be filled, and how
            QTimer.singleShot(0, lambda: self._flash(
                "This document has fillable form fields (tinted blue) - "
                "click a field to type in it; Tab goes to the next one.",
                12000))
        return True

    def bid_buildup(self, show=True):
        """Markups, margin by trade and front-loading for the job; saved
        with the job's proposal details (used by proposals and the SOV)."""
        from . import proposal
        from .bidbuild_ui import BidBuildDialog
        v = self._view
        dlg = BidBuildDialog(v.doc if v else None, self,
                             proposal.read(v.doc) if v else {})
        if show and dlg.exec() and v:
            proposal.write(v.doc, dlg.data)
            self._doc_edited()
        return dlg

    def create_proposal(self, data=None, comp=None):
        """Build a client proposal PDF from the assembly estimate and open
        it in a new tab (a priced bid). Returns the new document."""
        from . import proposal
        v = self._view
        if not v:
            return None
        if data is None:
            from . import prebid
            warning = None
            if not prebid.lock_state(v.doc):
                # shown inside the proposal dialog rather than as a modal
                # box of its own first (review 0.12.35 #20)
                warning = UNLOCKED_BID_WARNING
                self._flash(warning, 10000)
            from .estimating import bidgate_ui
            gate = bidgate_ui.gate_text(v.doc)    # Addenda Gate (Nov 3)
            if gate:
                warning = (warning + "\n\n" if warning else "") + gate
            from .proposal_ui import ProposalDialog
            dlg = ProposalDialog(v.doc, self, warning=warning)
            if not dlg.exec():
                return None
            data, comp = dlg.result_data, dlg.company_values()
            proposal.save_company(comp)
        comp = comp if comp is not None else proposal.company()
        try:
            out = proposal.make_pdf(v.doc, data, comp)
        except Exception as ex:
            log.exception("proposal")
            QMessageBox.warning(self, "Proposal",
                                f"Could not create the proposal:\n{ex}")
            return None
        proposal.write(v.doc, data)          # remembered with the job
        self._doc_edited()
        src = self._path
        self.open_document(out, f"Proposal {data.get('number', '')}")
        if self._tab is not None:            # Save As default: company rule
            from .reportname import report_file_name
            name = report_file_name("Proposal", data.get("project") or "",
                                    data.get("number") or None,
                                    data.get("date"))
            self._tab.suggest = os.path.join(os.path.dirname(src), name) \
                if src else name
        self._flash("Proposal created - use File > Save As to keep it")
        return out

    def open_document(self, doc, title):
        """Show an in-memory document (e.g. combined files) in a new tab.
        It has no file yet, so Save asks where to put it."""
        view = PdfView(doc, None)
        view.on_change = self._update_status
        view.status.connect(self._flash)
        view.snapshot_taken.connect(self._snapshot_toast)
        view.page_changed.connect(self._page_edited)
        view.zoom_requested.connect(self._zoom_from_view)
        view.marquee_zoom.connect(self.zoom_to_rect)
        view.rfi_requested.connect(
            lambda: self.new_rfi("RFI", from_selection=True))
        view.view_menu.connect(self._view_menu)
        view.want_tool.connect(lambda t: self.set_tool(t, ask=False))
        view.repeat_tool.connect(self.repeat_last_tool)
        view.number_key.connect(self._number_key)
        view.selection_changed.connect(self.properties.refresh)
        view.add_to_chest.connect(self.add_selected_to_chest)
        view.count_resumed.connect(self._count_resumed)
        view.crop_requested.connect(self.crop_pages)
        view.redaction_failed.connect(
            lambda msg, v=view: self._redaction_failed(v, msg))
        view.dirty = True
        tab = DocTab(view, None)
        tab.title = title
        tab.viewport().installEventFilter(self)
        i = self.tabs.addTab(tab, title)
        self.tabs.setCurrentIndex(i)
        self._tab_switched(i)
        QTimer.singleShot(0, self.fit_width)
        return view

    def _page_edited(self, page):
        self.thumbs.refresh_page(page)
        self._panel_timer.start()

    def _doc_reloaded(self):
        """After undo or a page operation: refresh everything."""
        self._view.reset_page_cache()
        self._view.selected = None
        self._view._render()
        self.thumbs.set_doc(self._view.doc, self._view.page)
        self.bookmarks.set_doc(self._view.doc)
        with annotate.scan_cache():
            self.markups.set_doc(self._view.doc)
            self.quantities.set_doc(self._view.doc)
            self.takeoff_tree.set_doc(self._view.doc)
            self.estimate.set_doc(self._view.doc)
            self.assemblies.set_doc(self._view.doc)
        self.rfis.set_doc(self._view.doc)
        self.properties.refresh()

    def _write(self, path, view=None):
        """Save to `path`, incrementally when possible so existing
        signatures stay valid. `view` = a background tab (AutoSave)."""
        view = view or self._view
        blocked = getattr(view, "save_blocked", None)
        if blocked:                 # a redaction that failed its proof
            raise RuntimeError(f"Saving is blocked: {blocked}")
        doc = view.doc
        try:                        # the version stamp (QS-004)
            from . import jobsafe
            jobsafe.stamp(doc)
        except Exception:                                 # noqa: BLE001
            log.debug("job data stamp", exc_info=True)
        same = bool(doc.name) and os.path.abspath(doc.name) == os.path.abspath(path)
        # after a redaction the file is always rewritten whole: a save that
        # adds to it keeps the old page contents, redacted words and all,
        # in the earlier revision (QS-002, Nov 4)
        full = bool(getattr(view, "needs_full_save", False))
        if same and not full and doc.can_save_incrementally():
            # an in-place save appends to the live file; keep a copy of it
            # from before the first one this session (review M-1)
            backup_before_incremental(path)
            from . import embfiles
            snap = embfiles.snapshot(doc)
            doc.save(path, incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
            # PyMuPDF 2.0 was seen writing job data (takeoff items...) that
            # could not be read back from the saved file ("object is not a
            # stream"): check it, and save the whole file when it's lost
            bad = embfiles.saved_mismatches(path, snap)
            if not bad:
                return
            log.warning("incremental save lost job data %s; saving the "
                        "whole file", bad)
            for n in bad:
                try:
                    embfiles.put(doc, n, snap[n])
                except Exception:
                    log.warning("could not rewrite %s", n, exc_info=True)
        tmp = path + ".quantisheet-tmp"
        # garbage=1 drops unused objects only. Higher levels also merge
        # duplicate objects, which took minutes on a 687-page spec book
        # with 22,000 bookmarks. A protected document keeps its encryption
        # exactly - both passwords and the permissions (PDF_ENCRYPT_KEEP,
        # S7); re-encrypting from the DocProtection is only the fallback
        # when KEEP fails or the saved file comes back unencrypted. Only
        # Remove Security saves one without.
        prot = getattr(view, "protection", None)
        # garbage=3 after a redaction: every object the page no longer uses
        # (the old contents) is dropped from the file, not just unlisted
        save_keeping_protection(doc, tmp, prot, garbage=3 if full else 1,
                                deflate=True)
        if same:
            page = view.page
            doc.close()
            _replace_in_place(tmp, path)
            view.doc = fitz.open(path)
            if prot is not None:
                prot.reopen(view.doc)
            view.page = page
            if view is self._view:
                self._doc_reloaded()
            else:
                view._render() if hasattr(view, "_render") else None
        else:
            os.replace(tmp, path)

    # ---- AutoSave ---------------------------------------------------------
    def _autosave_menu(self):
        from PySide6.QtWidgets import QMenu
        from . import autosave
        m = QMenu(self)

        def fill():
            m.clear()
            cur = autosave.mode()
            for key, label in (("file", "AutoSave to the file"),
                               ("recovery", "Recovery copies only"),
                               ("off", "Off")):
                a = m.addAction(label, lambda k=key: self.set_autosave(k))
                a.setCheckable(True)
                a.setChecked(cur == key)
            m.addSeparator()
            every = m.addMenu("Every")
            for n in (1, 2, 5, 10):
                a = every.addAction(f"{n} minute{'s' if n > 1 else ''}",
                                    lambda n=n: self.set_autosave(
                                        minutes=n))
                a.setCheckable(True)
                a.setChecked(autosave.minutes() == n)
            m.addSeparator()
            m.addAction("Save changes now", lambda: self.autosaver.tick(
                force=True))
            m.addAction("Recover unsaved files…",
                        lambda: self.recover_unsaved(ask_if_none=True))
        m.aboutToShow.connect(fill)
        return m

    def set_thin_lines(self, on):
        from . import viewer as _viewer
        settings.set("thin_lines", bool(on))
        _viewer.apply_line_setting()
        for i in range(self.tabs.count()):
            t = self.tabs.widget(i)
            if isinstance(t, DocTab):
                t.view._tiles.clear()
                t.view._preview = None
                t.view._content_raster = None
                t.view._pf_forget()
        if self._view:
            self._view._render()

    def set_autosave(self, mode=None, minutes=None):
        if mode:
            settings.set("autosave_mode", mode)
        if minutes:
            settings.set("autosave_minutes", int(minutes))
        self.autosaver.restart()
        from . import autosave
        self._flash({"file": "AutoSave is on", "recovery":
                     "AutoSave keeps recovery copies only",
                     "off": "AutoSave is off"}[autosave.mode()])

    def toggle_autosave(self):
        from . import autosave
        self.set_autosave("off" if autosave.mode() != "off" else "file")

    def _autosave_status(self):
        from . import autosave
        if not hasattr(self, "chip_autosave"):
            return
        mode = autosave.mode()
        a = getattr(self, "autosave_action", None)
        if a is not None:
            a.setChecked(mode != "off")
        sv = getattr(self, "autosaver", None)
        text = {"file": "AutoSave On", "recovery": "AutoSave: recovery",
                "off": "AutoSave Off"}[mode]
        tip = {"file": f"Changes are saved to the file every "
                       f"{autosave.minutes()} min",
               "recovery": "Recovery copies every "
                           f"{autosave.minutes()} min; the file is saved "
                           "only when you save",
               "off": "Click to turn AutoSave on"}[mode]
        if sv and sv.last and mode != "off":
            text += f" · {sv.last:%H:%M}"
        if sv and sv.problem:
            text = "AutoSave ⚠"
            tip = sv.problem
        self.chip_autosave.setText(text)
        self.chip_autosave.setToolTip(tip)

    def recover_unsaved(self, ask_if_none=False):
        """Offer documents left unsaved by a session that didn't close
        normally."""
        from . import autosave
        items = autosave.pending()
        if not items:
            if ask_if_none:
                QMessageBox.information(self, "Recover Unsaved Files",
                                        "Nothing to recover.")
            return []
        from PySide6.QtWidgets import (QDialog, QDialogButtonBox,
                                       QListWidget, QListWidgetItem)
        d = QDialog(self)
        d.setWindowTitle("Recover Unsaved Files")
        d.resize(620, 340)
        lay = QVBoxLayout(d)
        lab = QLabel("QuantiSheet closed before these changes were saved. "
                     "Open them to keep the work, then save.")
        lab.setWordWrap(True)
        lay.addWidget(lab)
        lw = QListWidget()
        for it in items:
            when = it.get("saved", "").replace("T", " ")[:16]
            src = it.get("original") or "never saved"
            row = QListWidgetItem(f"{it.get('title') or 'Untitled'}   —   "
                                  f"{when}   ({src})")
            row.setFlags(row.flags() | Qt.ItemIsUserCheckable)
            row.setCheckState(Qt.Checked)
            lw.addItem(row)
        lay.addWidget(lw)
        bb = QDialogButtonBox()
        bopen = bb.addButton("Open Checked", QDialogButtonBox.AcceptRole)
        bdel = bb.addButton("Discard Checked", QDialogButtonBox.DestructiveRole)
        bb.addButton("Later", QDialogButtonBox.RejectRole)
        lay.addWidget(bb)
        choice = {}
        bopen.clicked.connect(lambda: (choice.update(a="open"), d.accept()))
        bdel.clicked.connect(lambda: (choice.update(a="discard"),
                                      d.accept()))
        bb.rejected.connect(d.reject)
        if not d.exec():
            return []
        picked = [items[i] for i in range(lw.count())
                  if lw.item(i).checkState() == Qt.Checked]
        opened = []
        for it in picked:
            if choice.get("a") == "open":
                opened.append(self.open_recovered(it))
            autosave.discard(it) if choice.get("a") == "discard" else None
        return opened

    def open_recovered(self, item):
        """Open a recovery copy as an unsaved document; Save offers the
        original location."""
        import shutil
        import tempfile
        from . import autosave
        tmp = os.path.join(tempfile.mkdtemp(prefix="quantisheet-recover-"),
                           os.path.basename(item.get("original") or
                                            "Recovered.pdf"))
        shutil.copyfile(item["pdf"], tmp)
        self.open_path(tmp)
        tab = self._tab
        title = os.path.splitext(os.path.basename(
            item.get("original") or item.get("title") or "Untitled"))[0]
        tab.title = f"{title} (recovered)"
        tab.suggest = item.get("original") or ""
        tab.path = None
        self._view._path = None
        self._view.dirty = True
        autosave.discard(item)
        self._update_status()
        return tab

    def save_file(self):
        if not self._view:
            return False
        if not self._path:
            return self.save_as()
        if not self._save_guards(self._path):
            return False
        if not self._changed_on_disk(self._path):
            return False
        try:
            self._write(self._path)
        except Exception as ex:
            QMessageBox.warning(self, "Save", f"Could not save:\n{ex}")
            return False
        self._after_write(self._path)
        self._job_saved(self._path)
        self._saved()
        return True

    def _job_saved(self, path):
        from . import jobsafe
        v = self._view
        try:
            jobsafe.keep_copy(v.doc, path)
        except Exception:                                 # noqa: BLE001
            log.warning("could not keep a copy of the job data",
                        exc_info=True)
        v._seen = jobsafe.fingerprint(path)
        if getattr(v, "_lock_file", None):
            jobsafe.touch_lock(path)       # still here: keep the lock fresh

    # ---- save guards (QS-001 signed PDFs, QS-002 redaction, Nov 4) -----
    def _save_guards(self, path, ask=None):
        """Before saving: a signed PDF says what the save does to its
        signatures. False = don't save."""
        from . import betalicense
        if betalicense.read_only():          # license ended: say so, once
            self._flash(betalicense.READ_ONLY_MESSAGE, 15000)
            return False
        from . import savecheck
        v = self._view
        ask = ask or (lambda title, text, buttons, default:
                      QMessageBox.question(self, title, text, buttons,
                                           default))
        if v is None or not savecheck.is_signed(v.doc):
            return True
        same = bool(v.doc.name) and \
            os.path.abspath(v.doc.name) == os.path.abspath(path)
        rewrite = (not same or getattr(v, "needs_full_save", False) or
                   not v.doc.can_save_incrementally())
        if rewrite:
            if same:
                backup_before_incremental(path)       # the signed original
            r = ask("Signed PDF",
                    "This PDF is signed. Saving it this way rewrites the "
                    "whole file, so the signatures will NOT be valid in the "
                    "saved file." + ("" if not same else
                                     " A copy of the signed original is "
                                     "kept in QuantiSheet's backups.") +
                    "\n\nSave anyway?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            return r == QMessageBox.Yes
        if getattr(v, "_signed_ok", False):
            return True
        r = ask("Signed PDF",
                "This PDF is signed. Your changes are added after the "
                "signatures: they stay valid, but a signature check will "
                "show the document was changed after it was signed.\n\n"
                "Save the changes into this file? (No: use Save As for a "
                "working copy.)",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r == QMessageBox.Yes:
            v._signed_ok = True
            return True
        return False

    def _job_safety_on_open(self, view, path, ask=None):
        """Newer-version stamp, lost job data, someone else has it open
        (jobsafe.py, review QS-003/004/005). Returns what it found."""
        from . import jobsafe
        found = {}
        try:
            info = jobsafe.check_open(view.doc)
            if info["newer"]:
                view.save_blocked = jobsafe.newer_message(info)
                found["newer"] = info
                QTimer.singleShot(0, lambda m=view.save_blocked:
                                  self._flash(m, 20000))
            view._seen = jobsafe.fingerprint(path)
            from . import savecheck
            if savecheck.is_signed(view.doc):          # QS-001: say so
                found["signed"] = True
                QTimer.singleShot(0, lambda: self._flash(
                    "Signed PDF: Document > Verify Signatures checks them. "
                    "Changes you save are added after the signatures.",
                    15000))
            from . import activecontent     # Venice #1 (Nov 4)
            note = activecontent.note_on_open(view.doc, path)
            if note:
                found["active"] = note
                QTimer.singleShot(0, lambda n=note: self._flash(n, 15000))
            if jobsafe.is_synced_folder(path):
                seen = set(settings.get("synced_warned") or [])
                key = jobsafe.unc(path).lower()
                if key not in seen:            # once per file (review 2)
                    found["synced"] = True
                    seen.add(key)
                    settings.set("synced_warned", sorted(seen)[-200:])
                    QTimer.singleShot(0, lambda: self._flash(
                        jobsafe.SYNCED_WARNING, 20000))
            if jobsafe.is_shared(path):
                other = jobsafe.who_has(path)
                if other:
                    found["other"] = other
                    if other.get("you"):
                        msg = ("You already have this file open in another "
                               "QuantiSheet window. Save there first, or "
                               "close that window, so one doesn't overwrite "
                               "the other.")
                    else:
                        msg = (f"{other.get('user')} on "
                               f"{other.get('machine')} has this file open "
                               f"(since {other.get('since', '')[11:16]}). "
                               "Save a copy so neither of you loses work.")
                    QTimer.singleShot(0, lambda m=msg: self._flash(m, 20000))
                elif jobsafe.take_lock(path):
                    view._lock_file = path
            rec = jobsafe.lost_data(view.doc, path)
            if rec is not None:
                found["lost"] = rec
                when = str(rec.get("saved", ""))[:16].replace("T", " ")
                src = rec.get("file") or rec.get("name") or ""
                text = ("This PDF has no QuantiSheet data (takeoff, scales, "
                        "estimate), but this computer kept a copy from the "
                        f"last save ({when}). Email and some PDF tools strip "
                        "it out.\n\nThe copy was saved from:\n"
                        f"{src}\nIt matches {rec.get('match') or 'this file'}"
                        ".\n\nPut the data back into this file?")

                def restore(v=view, r=rec):
                    found["restored"] = jobsafe.put_back(v.doc, r)
                    v.mark_dirty()
                    self._update_status()
                    self._flash("QuantiSheet data put back - save to keep "
                                "it in the file")
                if ask is not None:
                    if ask(text):
                        restore()
                else:            # never blocks the open (non-modal)
                    box = QMessageBox(QMessageBox.Question,
                                      "QuantiSheet Data", text,
                                      QMessageBox.Yes | QMessageBox.No, self)
                    box.setModal(False)
                    box.button(QMessageBox.Yes).clicked.connect(restore)
                    box.show()
                    view._lost_data_box = box
        except Exception:                                 # noqa: BLE001
            log.warning("job safety checks on open", exc_info=True)
        return found

    def _changed_on_disk(self, path, ask=None):
        """Someone else saved this file since we opened it. True = go on
        and overwrite; False = don't (Save a Copy was offered)."""
        from . import jobsafe
        v = self._view
        if v is None or not jobsafe.changed_since(path,
                                                  getattr(v, "_seen", None)):
            return True
        box_answer = ask
        if box_answer is None:
            box = QMessageBox(self)
            box.setWindowTitle("Save")
            box.setText(f"{os.path.basename(path)} was changed by someone "
                        "else after you opened it. Saving now would "
                        "overwrite their changes.")
            b_copy = box.addButton("Save a Copy…", QMessageBox.AcceptRole)
            b_over = box.addButton("Overwrite", QMessageBox.DestructiveRole)
            box.addButton(QMessageBox.Cancel)
            box.setDefaultButton(b_copy)
            box.exec()
            hit = box.clickedButton()
            box_answer = "copy" if hit is b_copy else \
                "overwrite" if hit is b_over else "cancel"
        if box_answer == "overwrite":
            return True
        if box_answer == "copy":
            QTimer.singleShot(0, self.save_as)
        return False

    def _after_write(self, path):
        """After a save that followed a redaction: look for the redacted
        words anywhere in the saved file."""
        from . import redaction
        v = self._view
        if v is None or not getattr(v, "needs_full_save", False):
            return {}
        words = set(getattr(v, "redacted_words", ()) or ())
        try:
            res = redaction.check(path, words, redaction.visible_words(v.doc))
        except Exception:                                 # noqa: BLE001
            log.warning("redaction leak check", exc_info=True)
            res = {"leaks": {}, "elsewhere": [],
                   "unchecked": ["the check itself (it failed - see the log)"]}
        leaks = res["leaks"]
        v.needs_full_save = False
        v.redacted_words = frozenset()
        self._last_leaks = leaks
        self._last_redaction_check = res
        # graded, never one green line (review 1, Nov 4)
        extra = ""
        if res["elsewhere"]:
            extra += ("\n\nStill showing on the pages (outside the redacted "
                      "areas, not redacted): " +
                      ", ".join(res["elsewhere"][:8]) + ".")
        if res["unchecked"]:
            extra += "\n\nNot checked: " + "; ".join(res["unchecked"]) + "."
        if leaks:
            where = "\n".join(f"  {k}: {', '.join(w[:6])}"
                               for k, w in list(leaks.items())[:10])
            QMessageBox.warning(
                self, "Redaction",
                "Saved, but words that were redacted can still be found in "
                f"the file:\n{where}\n\nUse PDF Management > Remove "
                "Hidden Information, or delete them from the markups or job data, "
                "then save again." + extra + "\n\n(Redaction removes what's "
                "on the page; it is not a legal-sufficiency review.)")
        elif extra:
            box = QMessageBox(QMessageBox.Information, "Redaction",
                              "Saved. The redacted words are gone from the "
                              "redacted areas and from the file's hidden "
                              "text." + extra, QMessageBox.Ok, self)
            box.setModal(False)          # never blocks the save
            box.show()
            self._redaction_box = box
        else:
            self._flash("Saved. The redacted words are nowhere in the file.",
                        8000)
        return leaks

    # Save As > Reduced Size PDF (Nov 19, Jon): a smaller copy straight
    # from Save As - the document stays open as it is
    REDUCED_KINDS = (("high quality", 200), ("balanced", 150),
                     ("smallest", 96))
    _PLAIN_FILTER = "PDF (*.pdf)"

    def _reduced_filter(self, kind):
        return f"Reduced Size PDF - {kind} (*.pdf)"

    def save_as(self, path=None, kind=None, show=True):
        """File > Save As. `kind` (or the Reduced Size PDF choice in the
        dialog's file type list) saves a smaller copy instead and leaves
        this document as it is. Returns True when saved."""
        if not self._view:
            return False
        if path is None:
            filters = [self._PLAIN_FILTER] + [self._reduced_filter(k)
                                              for k, _ in self.REDUCED_KINDS]
            path, chosen = QFileDialog.getSaveFileName(
                self, "Save As", self._path or getattr(self._tab, "suggest",
                                                       "") or "",
                ";;".join(filters))
            if not path:
                return False
            kind = next((k for k, _ in self.REDUCED_KINDS
                         if chosen == self._reduced_filter(k)), None)
        if kind:
            if not path.lower().endswith(".pdf"):
                path += ".pdf"
            if self._path and os.path.abspath(path) == \
                    os.path.abspath(self._path):
                QMessageBox.information(
                    self, "Reduced Size PDF", "A reduced copy can't be "
                    "saved over the file it is made from - pick another "
                    "name.") if show else None
                return False
            dpi = dict(self.REDUCED_KINDS)[kind]
            return self._write_reduced(path, dpi, "Reduced Size PDF",
                                       show=show) is not None
        if not self._save_guards(path):
            return False
        try:
            self._write(path)
        except Exception as ex:
            QMessageBox.warning(self, "Save", f"Could not save:\n{ex}")
            return False
        self._after_write(path)
        self._job_saved(path)
        self._path = path
        self._view._path = path
        self._saved()
        return True

    def _saved(self):
        self._view.dirty = False
        if hasattr(self, "autosaver"):
            self.autosaver.saved(self._view, None)
            self.autosaver.saved(self._view, self._path)
            self._autosave_status()
        self._autosnap()
        self._update_status()
        self._flash("Saved")
        if settings.get("mirror_on_save"):
            QTimer.singleShot(0, self._mirror_takeoff)

    def _mirror_takeoff(self):
        from . import audit
        try:
            if self._view and self._path:
                audit.mirror(self._view.doc, file=self._path)
        except Exception:
            log.warning("takeoff not sent to the shared database",
                        exc_info=True)

    def spec_sections(self, show=True):
        from .specs_ui import SpecSectionsDialog
        if not self._view:
            return None
        dlg = SpecSectionsDialog(self)
        if show:
            dlg.show()
        return dlg

    def accessibility_check(self, show=True):
        from .accessibility_ui import AccessibilityDialog
        if not self._view:
            return None
        dlg = AccessibilityDialog(self)
        if show:
            dlg.show()
        return dlg

    def civil(self, tab=0, show=True):
        """Civil tab: crew-and-production estimate, libraries, bid
        schedule, indirects, haul, versions and field production."""
        from .heavy_ui import HeavyDialog
        dlg = getattr(self, "_civil_dlg", None)
        doc = self._view.doc if self._view else None
        if dlg is None or dlg.doc is not doc or not dlg.isVisible():
            dlg = self._civil_dlg = HeavyDialog(self, tab)
        dlg.tabs.setCurrentIndex(tab)
        if show:
            dlg.show()
            dlg.raise_()
        return dlg

    SOILS = [("Trench box (vertical walls)", "box"),
             ("OSHA Type A - 3/4:1 slopes over 5 ft", "A"),
             ("OSHA Type B - 1:1 slopes over 5 ft", "B"),
             ("OSHA Type C - 1.5:1 slopes over 5 ft", "C")]

    @staticmethod
    def _heavybid_pages(doc, scales):
        """Utility plan sheets with a scale (title blocks read only on the
        scaled sheets first; the whole set only if none of those match)."""
        from . import heavy
        scaled = sorted(scales)
        pages = heavy.pipe_plan_pages(doc, scaled)
        if not pages:
            pages = [p for p in heavy.pipe_plan_pages(
                doc, heavy.civil_pages(doc), loose=True) if p in scales]
        return pages

    def _heavybid_in_background(self, v, pages, scales, folder, soil):
        """The civil takeoff behind the HeavyBid export reads every pipe
        sheet and can take minutes on a big set, so it runs on a worker
        thread (on its own copy of the PDF) while the window stays usable;
        the export carries on when it's done."""
        import fitz
        from PySide6.QtWidgets import QProgressDialog
        from . import bg, civiltakeoff
        data = v.doc.tobytes()
        dlg = QProgressDialog(
            "Finding and reading the civil sheets for CivilBid... "
            "You can keep working; this window closes when it's done.",
            "Hide", 0, 0, self)
        dlg.setWindowTitle("Export to CivilBid")
        dlg.setMinimumDuration(0)
        dlg.setWindowModality(Qt.NonModal)
        dlg.show()
        self._hb_progress = dlg

        def work():
            doc = fitz.open("pdf", data)
            try:
                found = pages if pages is not None else \
                    self._heavybid_pages(doc, scales)
                if not found:
                    return None
                return civiltakeoff.takeoff(doc, found, scales)
            finally:
                doc.close()

        def done(result):
            dlg.close()
            self._hb_progress = None
            if result is None:
                QMessageBox.information(
                    self, "Export to CivilBid",
                    "No civil plan sheet with a scale was found. Set the "
                    "scale on the utility plans (Takeoff > Auto Scale) and "
                    "try again.")
                return
            self.export_heavybid(folder, soil, result=result)

        def failed(msg):
            dlg.close()
            self._hb_progress = None
            QMessageBox.warning(self, "Export to CivilBid",
                                f"The civil takeoff failed:\n{msg}")
        self._flash("CivilBid export: reading the civil sheets in the "
                    "background...")
        bg.run(work, done, failed, self)
        return None

    def bid_invite_sender(self, name=None, email=None):
        """Project > Bid Invites Send As: the mailbox invitations and
        follow-ups go out from (default: the company bid mailbox).
        It must be set up in Outlook on this computer; nothing is sent
        from anyone's own mailbox instead."""
        from . import bid_followup as invite_boost, mail
        cur = invite_boost.live_sender()
        if email is None:
            email, ok = QInputDialog.getText(
                self, "Bid Invites Send As", "Mailbox to send bid "
                "invitations from (must be in Outlook here):",
                text=cur["email"])
            if not ok:
                return None
            name, ok = QInputDialog.getText(
                self, "Bid Invites Send As", "Name shown on the "
                "invitations:", text=cur["name"])
            if not ok:
                return None
        email = (email or "").strip()
        if not mail.valid(email):
            QMessageBox.warning(self, "Bid Invites Send As",
                                f"Not an email address: {email}")
            return None
        rec = {"name": (name or "").strip() or cur["name"], "email": email}
        settings.set("bid_invite_sender", rec)
        return rec

    def job_cost_feedback(self, show=True):
        from .pricehistory_ui import JobCostDialog
        dlg = JobCostDialog(self)
        if show:
            dlg.show()
        return dlg

    def estimating_dashboard(self, folders=None):
        """Cost per SF, hit rate, margin and sub prices across every job
        (dashboard_ui.py); opens empty with a hint when there's no data."""
        from . import dashboard_ui
        return dashboard_ui.show(self, folders)

    def work_notes_takeoff(self, modal=True):
        """Civil > Work Notes Takeoff: quantities a retrofit set states
        in its notes, summary table and specification (callouts_ui.py)."""
        from . import callouts_ui
        return callouts_ui.show(self, modal)

    def bid_board(self):
        """Invitations to bid that came to us: dates, who is pricing
        them, go / no-go and results (bidboard_ui.py)."""
        from . import bidboard_ui
        return bidboard_ui.show(self)

    def toggle_unpriced(self, on=None):
        """Outline in red every markup and revision cloud that isn't
        priced, excluded or sent as an RFI yet."""
        if not self._view:
            return None
        if on is None:
            on = self.unpriced_act.isChecked()
        self.unpriced_act.setChecked(bool(on))
        self._view.set_show_unpriced(on)
        return on

    def prebid_checklist(self, show=True):
        """Estimate > Pre-bid Checklist: sheets reviewed, markups priced or
        excluded, revision clouds accounted for - then lock the bid."""
        if not self._view:
            return None
        from .prebid_ui import PrebidDialog
        dlg = PrebidDialog(self)
        if show:
            dlg.show()
        return dlg

    def measurement_audit(self, tab=0, show=True):
        from .audit_ui import AuditDialog
        dlg = AuditDialog(self, tab)
        if show:
            dlg.show()
        return dlg

    def _autosnap(self):
        if getattr(self._view, "protection", None) is not None:
            return          # never an unencrypted copy of a protected file
        try:
            from . import versions
            versions.auto_revision(self._path, self._view.doc.tobytes())
            versions.prune_auto(self._path)
        except Exception:
            log.exception("could not save automatic revision")

    def print_doc(self):
        if not self._view:
            return
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter
        printer = QPrinter(QPrinter.HighResolution)
        printer.setFromTo(1, self._view.doc.page_count)
        dlg = QPrintDialog(printer, self)
        dlg.setOption(QPrintDialog.PrintPageRange, True)
        dlg.setMinMax(1, self._view.doc.page_count)
        if dlg.exec() != QPrintDialog.Accepted:
            return
        first, last = printer.fromPage(), printer.toPage()
        if first == 0:
            first, last = 1, self._view.doc.page_count
        return self._send_to_printer(printer, list(range(first - 1, last)))

    def print_preview(self, dialog=None):
        """File > Print Preview: each page on its paper, then Print (asks
        which printer, then prints the pages chosen in the preview).
        `dialog` (tests) is used instead of showing a new one."""
        v = self._view
        if not v:
            return None
        from PySide6.QtPrintSupport import QPrintDialog, QPrinter
        from .print_preview import PrintPreview
        printer = QPrinter(QPrinter.HighResolution)
        dlg = dialog or PrintPreview(v.doc, printer, v.page, self)
        if dialog is None and dlg.exec() != PrintPreview.Accepted:
            return None
        pages = dlg.pages()
        if not pages:
            return None
        if dialog is None:
            pd = QPrintDialog(dlg.printer, self)
            pd.setOption(QPrintDialog.PrintPageRange, False)
            if pd.exec() != QPrintDialog.Accepted:
                return None
        return self._send_to_printer(dlg.printer, pages)

    def _send_to_printer(self, printer, pages):
        """Print `pages` (0-based) - or, for a PDF printer, offer a sharp
        PDF copy instead."""
        from PySide6.QtPrintSupport import QPrinter
        if printer.outputFormat() == QPrinter.NativeFormat and \
                "pdf" in (printer.printerName() or "").lower():
            # "Microsoft Print to PDF" etc. makes a picture of every page
            # (review r41 F02: ~10 MB a sheet); a saved copy keeps the
            # drawing as lines and text - sharp and small
            ans = QMessageBox.question(
                self, "Print to PDF",
                "Save a PDF copy instead?\n\nPrinting to a PDF printer turns "
                "every page into a picture (about 10 MB a sheet). Saving a "
                "copy keeps the drawings sharp and the file small, with "
                "your markups.",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel,
                QMessageBox.Yes)
            if ans == QMessageBox.Cancel:
                return
            if ans == QMessageBox.Yes:
                path, _ = QFileDialog.getSaveFileName(
                    self, "Save PDF copy", "", "PDF (*.pdf)")
                if path:
                    self.save_pages_pdf(path, pages=pages)
                return
        return self.print_to(printer, pages)

    def save_pages_pdf(self, path, first=0, last=0, pages=None):
        """Pages first..last (1-based; 0 = all), or the 0-based `pages`,
        of the open drawing with their markups, as a vector PDF."""
        doc = self._view.doc
        if pages is None:
            if not first:
                first, last = 1, doc.page_count
            pages = list(range(first - 1, last))
        out = fitz.open()
        try:
            for i in pages:
                out.insert_pdf(doc, from_page=i, to_page=i)
            out.save(path, garbage=3, deflate=True)
        finally:
            out.close()
        self._flash(f"Saved {os.path.basename(path)}")
        return path

    def _print_progress(self, total):
        """"Printing page 13 of 60" with Cancel, while pages go to the
        printer (Nov 3: only a spinning cursor before)."""
        from PySide6.QtWidgets import QProgressDialog
        try:
            prog = QProgressDialog("Getting ready to print…", "Cancel", 0,
                                   total, self)
        except Exception:
            return None
        prog.setWindowTitle("Printing")
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)
        prog.setAutoClose(False)
        prog.setAutoReset(False)
        prog.setMinimumWidth(360)
        prog.setValue(0)
        prog.show()
        QApplication.processEvents()
        return prog

    # ---- undo ------------------------------------------------------------------
    def _restore(self, data):
        page = self._view.page
        self._view.replace_document(fitz.open(stream=data, filetype="pdf"),
                                    keep_history=True)
        self._view.page = min(page, self._view.doc.page_count - 1)
        self._view.mark_dirty()
        self._doc_reloaded()

    def _history_result(self, res):
        if isinstance(res, (bytes, bytearray)):
            self._restore(res)                  # whole document
        elif res:
            self._view.pages_restored(res)      # markups, done in place

    def undo(self):
        if self._view and not self._collab_blocked("Undo"):
            name = self._view.history.undo_label()
            self._history_result(self._view.history.undo(self._view.doc))
            if name:
                self._flash(f"Undid {name}")
            self._undo_names()

    def redo(self):
        if self._view and not self._collab_blocked("Redo"):
            name = self._view.history.redo_label()
            self._history_result(self._view.history.redo(self._view.doc))
            if name:
                self._flash(f"Redid {name}")
            self._undo_names()

    def _undo_names(self):
        """Venice #17: the Undo / Redo tips name the step ("Undo Bulk Edit
        (412 items)"). The menu text stays "Undo" so the ribbon and
        shortcuts that look for it keep working."""
        v = self._view
        h = getattr(v, "history", None) if v else None
        for act, word, name in (
                (getattr(self, "_undo_act", None), "Undo",
                 h.undo_label() if h else None),
                (getattr(self, "_redo_act", None), "Redo",
                 h.redo_label() if h else None)):
            if act is None:
                continue
            tip = f"{word} {name}" if name else word
            act.setToolTip(tip)
            act.setStatusTip(tip)
        return h.undo_label() if h else None

    # ---- search ------------------------------------------------------------------
    def find(self):
        if self._view:
            self.search.open_bar(self._view.doc)

    def _show_hit(self, page, rect, hits):
        v = self._view
        if not v:
            return
        if page < 0:
            v.search_hits, v.search_current = [], None
            v.update()
            return
        v.go_to(page)
        # text extraction gives unrotated page coordinates; the view
        # paints in screen (rotated) coordinates
        pg = v.pg
        hits = [annotate.from_page(pg, fitz.Rect(h)) for h in hits]
        rect = annotate.from_page(pg, fitz.Rect(rect))
        v.search_hits, v.search_current = hits, rect
        v.update()
        q = v._q(rect)
        self._scroll.ensureVisible(int(q.center().x()), int(q.center().y()),
                                   100, 150)

    def _clear_search(self):
        if self._view:
            self._view.search_hits, self._view.search_current = [], None
            self._view.update()
            self._view.setFocus()

    # ---- pages -------------------------------------------------------------------
    def organize_pages(self, dialog=None):
        """Organize Pages: big thumbnails to drag into order,
        rotate, duplicate and delete; applied as one undoable step."""
        from .organize import OrganizeDialog, apply_plan
        v = self._view
        if not v or self._collab_blocked("Organizing pages"):
            return 0
        dlg = dialog or OrganizeDialog(v.doc, self, v.page)
        from PySide6.QtWidgets import QDialog
        if dialog is None and dlg.exec() != QDialog.Accepted:
            return 0
        plan = dlg.plan()
        if plan == [(i, 0) for i in range(v.doc.page_count)]:
            return 0
        v.page = 0
        n = self._page_change(lambda: apply_plan(v.doc, plan),
                              "Pages organized")
        return n or 0

    def batch_link(self, remove=False):
        """Hyperlink every sheet reference (A-501, 3/A-501 ...) in the set
        to its sheet. One undoable step."""
        from . import batchlink
        v = self._view
        if not v or self._collab_blocked("Linking sheets"):
            return 0
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            smap = batchlink.sheet_map(v.doc)
            refs = batchlink.find_refs(v.doc, smap)
        finally:
            QApplication.restoreOverrideCursor()
        if not remove and len(smap) < 2:
            self._flash("Link Sheets: couldn't read sheet numbers from the "
                        "title blocks (scans need OCR first)")
            return 0
        fn = batchlink.remove_all if remove else batchlink.link_all
        n = self._page_change(lambda: fn(v.doc, refs),
                              "Sheet links removed" if remove else
                              "Sheet links added")
        if n is None:
            return 0
        v.reset_page_cache()
        self._flash(f"Removed {n} sheet link(s)" if remove else
                    f"Linked {n} sheet reference(s) across "
                    f"{len(smap)} sheets · click one to jump, Alt+Left "
                    "to come back")
        return n

    def follow_link(self, ln):
        """A link in the document was clicked."""
        v = self._view
        if not v:
            return False
        kind = ln.get("kind")
        if kind in (fitz.LINK_GOTO, fitz.LINK_NAMED) and \
                ln.get("page", -1) is not None and ln.get("page", -1) >= 0:
            self._push_view(force=True)
            v._view_t = 0
            v.go_to(int(ln["page"]))
            return True
        if kind == fitz.LINK_URI and ln.get("uri"):
            uri = str(ln["uri"])
            from PySide6.QtCore import QUrl
            url = QUrl(uri.strip())
            scheme = link_scheme(uri)
            # only web and email links (0.13.5): a PDF can't start a
            # program, open a local file or a network share
            if scheme is None or not url.isValid() or \
                    url.scheme().lower() != scheme:
                QMessageBox.warning(
                    self, "Open Link", "This link was not opened. Only web "
                    "(http, https) and email (mailto) links can be opened "
                    f"from a PDF.\n\n{uri[:300]}")
                return False
            if QMessageBox.question(
                    self, "Open Link", f"Open this address?\n\n{uri[:300]}") \
                    != QMessageBox.Yes:
                return False
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(url)
            return True
        if kind == fitz.LINK_GOTOR and ln.get("file"):
            # threat model T-003: never followed without asking, never to
            # a network path, only to a PDF - and nothing touches the path
            # (not even "does it exist?") until the user says yes
            path, why = file_link_target(ln["file"], getattr(v, "_path", None)
                                         or v.doc.name)
            if why:
                QMessageBox.warning(self, "Open Linked File",
                                    f"This link was not opened. {why}\n\n"
                                    f"{str(ln['file'])[:300]}")
                return False
            if QMessageBox.question(
                    self, "Open Linked File", "This PDF links to another "
                    f"file. Open it?\n\n{path[:300]}") != QMessageBox.Yes:
                return False
            if os.path.exists(path):
                self.open_path(path)
                return True
            QMessageBox.information(self, "Open Linked File",
                                    f"The linked file isn't there:\n\n"
                                    f"{path[:300]}")
        return False

    def _page_change(self, fn, message):
        """Run a page operation as one undoable step."""
        try:
            result = fn()
        except Exception as ex:
            QMessageBox.warning(self, "Pages", str(ex))
            return None
        self._view.history.snapshot()
        self._view.mark_dirty()
        self._doc_reloaded()
        self._flash(message)
        return result

    def _move_page(self, frm, to):
        if self._collab_blocked("Reordering pages"):
            self.thumbs.set_doc(self._view.doc, self._view.page)
            return
        self._view.page = to
        self._page_change(lambda: pagetools.move(self._view.doc, frm, to),
                          f"Moved page {frm + 1} to position {to + 1}")

    def _rotate_pages(self, pages, deg, label=""):
        """Rotate is a page-level change: undo keeps just those pages (not
        a copy of the whole file) and only they are redrawn."""
        v = self._view
        doc = v.doc
        before = v.history.begin_pages(doc, pages)
        try:
            pagetools.rotate(doc, pages, deg)
        except Exception as ex:
            QMessageBox.warning(self, "Pages", str(ex))
            return None
        v.history.commit_pages(doc, before)
        v.selected = None
        v.reset_page_cache()
        if v.page in pages:
            v._render()
            # the page changed shape: show all of it, not whatever blank
            # corner the old scroll position lands on (hands-on pass,
            # Nov 10: Rotate Right looked like it had emptied the page)
            try:
                self.fit_page()
            except Exception:                             # noqa: BLE001
                log.debug("fit after rotate", exc_info=True)
        for p in pages:
            self.thumbs.refresh_page(p)
        v.mark_dirty()
        self._flash(f"Rotated page(s) {label or len(pages)}")
        return True

    def _page_action(self, name, pages):
        if not self._view or not pages:
            return
        doc = self._view.doc
        label = ", ".join(str(p + 1) for p in pages[:8]) + \
            ("…" if len(pages) > 8 else "")
        if name == "extract":
            base = os.path.splitext(self._path or "document")[0]
            out, _ = QFileDialog.getSaveFileName(
                self, "Extract Pages", f"{base}_pages.pdf", "PDF (*.pdf)")
            if out:
                pagetools.extract(doc, pages, out)
                self._flash(f"Saved page(s) {label} to {os.path.basename(out)}")
            return
        if self._collab_blocked("Changing pages"):
            return
        if name in ("rotate_right", "rotate_left"):
            deg = 90 if name == "rotate_right" else -90
            self._rotate_pages(pages, deg, label)
        elif name == "delete":
            if QMessageBox.question(self, "Delete Pages",
                                    f"Delete page(s) {label}?") \
                    != QMessageBox.Yes:
                return
            self._page_change(lambda: pagetools.delete(doc, pages),
                              f"Deleted page(s) {label}")
        elif name == "insert_blank":
            after = max(pages)
            self._view.page = after + 1
            self._page_change(lambda: pagetools.insert_blank(doc, after),
                              "Inserted a blank page")
        elif name == "insert_pdf":
            path, _ = QFileDialog.getOpenFileName(self, "Insert Pages From",
                                                  "", "PDF (*.pdf)")
            if path:
                after = max(pages)
                n = self._page_change(
                    lambda: pagetools.insert_pdf(doc, path, after),
                    "Inserted pages")
                if n:
                    self._view.go_to(after + 1)

    def insert_pdfs_at(self, paths, at):
        """PDFs dropped on the Pages panel go in before page `at`."""
        if not self._view or not paths or \
                self._collab_blocked("Changing pages"):
            return 0
        doc = self._view.doc
        total = 0
        after = at - 1
        for p in paths:
            n = self._page_change(
                lambda p=p, a=after: pagetools.insert_pdf(doc, p, a),
                f"Inserted {os.path.basename(p)}")
            if not n:
                break
            total += n
            after += n
        if total:
            self._view.go_to(max(0, at))
        return total

    def bates(self):
        if not self._view or self._collab_blocked("Bates numbering"):
            return
        prefix, ok = QInputDialog.getText(self, "Bates Numbering", "Prefix:",
                                          text="DOC")
        if not ok:
            return
        start, ok = QInputDialog.getInt(self, "Bates Numbering",
                                        "Start number:", 1, 0, 10 ** 9)
        if not ok:
            return
        from . import page_ops
        self._page_change(lambda: page_ops.bates_number(self._view.doc,
                                                        prefix, start),
                          "Added Bates numbers")

    def watermark(self):
        if not self._view or self._collab_blocked("Watermarks"):
            return
        text, ok = QInputDialog.getText(self, "Watermark", "Text:",
                                        text="DRAFT")
        if not ok or not text.strip():
            return
        opacity, ok = QInputDialog.getInt(self, "Watermark",
                                          "Opacity (%):", 25, 5, 100)
        if not ok:
            return
        from . import page_ops
        self._page_change(lambda: page_ops.add_watermark(
            self._view.doc, text, opacity / 100), "Added watermark")

    def compare_with(self, other=None):
        if not self._view:
            return
        if not other:
            other, _ = QFileDialog.getOpenFileName(self, "Compare With", "",
                                                   "PDF (*.pdf)")
        if not other:
            return
        from . import versions
        tmpdir = tempfile.mkdtemp(prefix="quantisheet-compare-")
        cur = os.path.join(tmpdir, "current.pdf")
        out = os.path.join(tmpdir, "comparison.pdf")
        self._view.doc.save(cur)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            versions.compare(cur, other, out)
        except Exception as ex:
            QMessageBox.warning(self, "Compare", str(ex))
            return
        finally:
            QApplication.restoreOverrideCursor()
        if self.open_path(out):
            self.tabs.setTabText(self.tabs.currentIndex(),
                                 f"Compare: {os.path.basename(other)}")

    # ---- takeoff -----------------------------------------------------------------
    def show_scale(self):
        if not self._view:
            return
        sc = self._view.scale()
        if not sc:
            QMessageBox.information(self, "Scale", "No scale set on this page."
                                    " Use Takeoff > Set Scale.")
            return
        inch = 72 / sc["ppu"]
        QMessageBox.information(
            self, "Scale", (f"{sc['name']}\n" if sc.get("name") else "") +
            f"1 inch on paper = {inch:,.3g} {sc['unit']}\n"
            f"({sc['ppu']:.3f} points per {sc['unit']})")

    def new_rfi(self, kind="RFI", from_selection=False):
        """A new log item; from the selected markup if asked."""
        v = self._view
        if not v:
            return None
        fields = None
        if from_selection and v.selected:
            from . import rfilog
            found = annotate.find_annots(v.pg, v.selected["ref"])
            if found:
                fields = rfilog.from_markup(v.doc, v.page, found[0])
        self.rfi_dock.show()
        self.rfi_dock.raise_()
        return self.rfis.new(kind, fields)

    def _find_rfis_in_specs(self, specs, ask=None, wait=False, dialog=None):
        """Find RFIs with a spec book / project manual open: every page
        gets the rule checks (TBD / by others, sections cited but not in
        the book); the AI reads as much as SPEC_CHUNKS allows and says
        how much that was."""
        from .ai import rfi_finder
        from . import bg
        found = rfi_finder.checks([], specs) + rfi_finder.spec_checks(specs)
        read, total = rfi_finder.coverage(specs)
        note = (f"Specification book: all {total} pages were checked for "
                "open scope and missing sections")
        note += (f"; the AI read pages 1-{read} of {total}." if read < total
                 else "; the AI read every page.")

        def show(ai_items, extra=""):
            skipped = getattr(ai_items, "skipped", None) or []
            if skipped:                 # some parts failed: say which
                extra = "\n".join(([extra] if extra else []) + skipped)
            items = rfi_finder.dedupe(found + list(ai_items or []))
            msg = note + (f"\n{extra}" if extra else "")
            if not items:
                QMessageBox.information(self, "Find RFIs & Questions",
                                        "No questions found.\n\n" + msg)
                return []
            from .rfi_ui import AiRfiDialog
            dlg = dialog(items, msg) if dialog else \
                AiRfiDialog(items, msg, self)
            if not dlg.exec():
                return []
            # the spec book is the open PDF: cloud each quote right here
            return self.create_rfis([dict(f, doc="plans")
                                     for f in dlg.selected()])

        self._flash(f"Finding RFIs in the spec book ({total} pages): the "
                    "local AI is reading it in the background - a big book "
                    "can take a while; keep working.")
        if wait:
            try:
                return show(rfi_finder.ai_review_specs(specs, ask))
            except Exception as ex:
                return show([], f"AI review unavailable: {ex}")
        result = {}
        bg.run(lambda: rfi_finder.ai_review_specs(specs, ask),
               lambda items: result.setdefault("rfis", show(items)),
               lambda err: result.setdefault(
                   "rfis", show([], f"AI review unavailable ({err}); "
                                "showing the rule checks only.")), self)
        return result

    def create_rfis(self, findings, spec_path=None):
        """Numbered draft RFIs for accepted findings, each with a cloud on
        the drawing where its quote is."""
        from .ai import rfi_finder, rfi_rules
        from . import rfilog
        v = self._view
        if not v or not findings:
            return []
        placed, marks = [], []
        for f in findings:
            pg, r = (None, None)
            if f.get("doc", "plans") == "plans":
                pg, r = rfi_finder.locate(v.doc, f)
            placed.append((f, pg, r))
            if r is not None:
                box = fitz.Rect(r) + (-6, -6, 6, 6)
                marks.append((pg, "add_cloud", v._styled("add_cloud", {
                    "rect": list(box), "color": [1, 0, 0],
                    "note": f["question"], "subject": "RFI"})))
        if marks:
            v.apply_marks(marks)
        out = []
        for f, pg, r in placed:
            ref = None
            if r is not None:
                for a in annotate.iter_annots(v.doc[pg]):
                    if (a.info or {}).get("content") == f["question"] and \
                            a.type[0] == fitz.PDF_ANNOT_SQUARE:
                        ref = annotate.ref(a)
            q = f["question"]
            title = (f.get("title") or
                     re.split(r"(?<=[.?!])\s", q, 1)[0])[:100]
            # v36 findings carry citations: the RFI is the full CSI-style
            # draft (references, both quotes, proposal, impacts)
            body = f.get("draft") or (
                rfi_rules.draft(f) if f.get("cites") else q +
                (f"\n\nReason: {f['reason']}" if f.get("reason") else ""))
            if f.get("doc") == "specs" and spec_path:
                body += f"\n\nSource: {os.path.basename(spec_path)}, " \
                        f"page {(f.get('page') or 0) + 1}"
            out.append(rfilog.add(
                v.doc, "RFI", title=title, question=body,
                sheet=f.get("reference", ""),
                page=pg if f.get("doc", "plans") == "plans" else None,
                markup=ref, status="Draft",
                source="AI" if f.get("source") == "AI" else "Check"))
        self._doc_edited()
        self.rfis.refresh()
        self.rfi_dock.show()
        self.rfi_dock.raise_()
        self._flash(f"Created {len(out)} draft RFI(s)")
        return out

    def _go_rfi(self, page, ref):
        if ref:
            self._go_annot(page, ref)
        elif self._view:
            self._view.go_to(page)

    def _install_boosts(self):
        """Chief of Staff's v13-v15 add-ons: undo one point at a time and
        an undo history, Lock Bid Set, item defaults (depth, MH-1 labels).
        Their actions go in the menus so the ribbon can find them."""
        from . import bidlock, history, item_defaults
        history.install(win=self)
        item_defaults.install(self)
        bidlock.install(self)
        for m in self.menuBar().findChildren(type(self._file_menu)):
            t = m.title().replace("&", "")
            if t == "Edit":
                m.addAction(self._ub_history_action)
                m.addAction("Undo Steps…", lambda: self.set_undo_steps())
            elif t == "Takeoff":
                m.addAction(self._bl_action)

    def _install_studio(self):
        """Chief's v23-v26 (Takeoff Studio ideas): the measurement bar and a
        snap chip in the status bar (shown only while measuring - no new
        strip under the drawing), and Field Mode's remembered state."""
        from PySide6.QtWidgets import QToolButton
        from . import field_mode, measure_bar, snap_indicator
        sb = self.statusBar()
        self.measure_bar = measure_bar.MeasureBar(self)
        self.measure_bar.setObjectName("MeasureBar")
        self.measure_bar.setMinimumWidth(300)
        self.measure_bar.committed.connect(
            lambda v: self._view and self._view.bar_commit(v))
        self.measure_bar.add_requested.connect(
            lambda: self._view and self._view.bar_add())
        self.measure_bar.cancelled.connect(
            lambda: self._view and self._view.bar_cancel())
        sb.insertPermanentWidget(0, self.measure_bar, 1)
        self.measure_bar.setVisible(False)
        self.chip_snap = QToolButton()
        self.chip_snap.setObjectName("StatusChipButton")
        self.chip_snap.setAutoRaise(True)
        self.chip_snap.setPopupMode(QToolButton.InstantPopup)
        sm = next((m for m in self._view_menu_bar.findChildren(type(
            self._view_menu_bar)) if m.title() == "Snap Modes"), None)
        if sm is not None:
            self.chip_snap.setMenu(sm)
        sb.insertPermanentWidget(1, self.chip_snap)
        self.chip_snap.setVisible(False)
        self._snap_chip_text()
        self.field_mode = field_mode.FieldMode(self)
        self.field_mode.action = self._field_action
        d = settings.get("density")
        if d in field_mode.DENSITY and d != "comfortable":
            self.field_mode.set_density(d, save=False)
        if settings.get("field_mode") is True:
            self.field_mode.set(True)

    def _snap_chip_text(self):
        from . import snap_indicator
        if not hasattr(self, "chip_snap"):
            return
        modes = snap_indicator.load_modes()
        on = [m for m in snap_indicator.ORDER if m in modes]
        self.chip_snap.setText("Snap: " + (" ".join(on) if on else "off"))
        self.chip_snap.setToolTip(snap_indicator.status_text(modes) +
                                  "\nClick to choose the snap modes.")

    def _set_snap_modes(self):
        from . import snap_indicator
        modes = {m for m, a in self._snap_mode_actions.items()
                 if a.isChecked()}
        snap_indicator.save_modes(modes)
        for i in range(self.tabs.count()):
            t = self.tabs.widget(i)
            v = getattr(t, "view", None)
            if v is not None:
                v._snap_modes = set(modes)
        self._snap_chip_text()

    def _studio_status(self, v):
        """Show the measure bar and snap chip only while they apply."""
        if not hasattr(self, "measure_bar"):
            return
        tool = getattr(v, "tool", None) if v is not None else None
        measuring = v is not None and tool in v.BAR_TOOLS
        if v is not None:
            v.measure_bar = self.measure_bar
        self.measure_bar.setVisible(measuring)
        if measuring:
            v.update_measure_bar()
        from .viewer import SNAP_TOOLS
        self.chip_snap.setVisible(v is not None and tool in SNAP_TOOLS and
                                  v.snap_enabled)

    def active_ribbon(self):
        """The ribbon on screen: the simple menus' when they're on."""
        sm = getattr(self, "simple_menu", None)
        return sm.ribbon if sm is not None and sm.on else self.ribbon

    def active_ribbon_bar(self):
        lay = getattr(self, "layouts", None)
        if lay is not None and lay.active_bar() is not None:
            return lay.active_bar()
        sm = getattr(self, "simple_menu", None)
        return sm.holder if sm is not None and sm.on else \
            getattr(self, "_ribbon_bar", self.ribbon)

    def toggle_field_mode(self):
        fm = getattr(self, "field_mode", None)
        if fm is not None:
            fm.toggle()
        return fm.on if fm is not None else False

    def set_density(self, name):
        fm = getattr(self, "field_mode", None)
        if fm is not None:
            fm.set_density(name)

    def set_undo_steps(self, n=None):
        """Edit > Undo Steps: how many steps Undo keeps (0 = no step limit;
        memory still caps it)."""
        from . import count_triage
        if n is None:
            n, ok = QInputDialog.getInt(
                self, "Undo Steps", "Undo steps to keep (0 = unlimited):",
                int(settings.get("undo_limit", 200) or 0), 0, 100000)
            if not ok:
                return None
        settings.set("undo_limit", int(n))
        for i in range(self.tabs.count()):
            v = getattr(self.tabs.widget(i), "view", None)
            if v is not None:
                count_triage.apply_undo_limit(v.history, int(n))
        return int(n)

    def _boost(self, which):
        """Run one of the review-first tools on the open document."""
        v = self._view
        if v is None:
            return None
        if which == "autoscale":
            from . import autoscale
            n = autoscale.run_dialog(self, v.doc)
            if n:
                v.mark_dirty()
                v._render()
                self._refresh_panels()
            return n
        if which == "autobookmark":
            from . import autobookmark
            n = autobookmark.run_dialog(self, v.doc)
            if n:
                v.mark_dirty()
                self.bookmarks.set_doc(v.doc)
            return n
        if which == "autotakeoff_review":
            from . import autotakeoff_review
            n = autotakeoff_review.run_dialog(self)
            self._refresh_panels()
            return n
        if which == "revdelta":
            from . import revdelta
            dlg = revdelta.RevisionDeltaDialog(
                self, v.doc, on_change=lambda: (v.mark_dirty(),
                                                self._refresh_panels()))
            dlg.exec()
            return dlg
        return None

    def _bottom_docks(self):
        return (self.markups_dock, self.asm_dock, self.est_dock,
                self.qty_dock, self.rfi_dock)

    def toggle_bottom_panels(self, on=None):
        docks = self._bottom_docks()
        if on is None:
            on = not any(d.isVisible() for d in docks)
        for d in docks:
            d.setVisible(bool(on))
        if on:
            self.markups_dock.raise_()
        self.bottom_act.setChecked(bool(on))
        settings.set("bottom_panels", bool(on))
        return bool(on)

    def _show_takeoff_panel(self):
        """New takeoff shows up in the Takeoff panel on the left."""
        self.takeoff_dock.show()
        self.takeoff_dock.raise_()

    def _go_takeoff(self, page, ref):
        if ref is None:
            if self._view:
                self._view.go_to(page)
            return
        self._go_annot(page, ref)

    def _takeoff_visibility(self, page):
        v = self._view
        if v is None:
            return
        try:
            v.mark_dirty()
        except Exception:
            pass
        v._render()

    def _go_annot(self, page, ref):
        v = self._view
        v.go_to(page)
        found = annotate.find_annots(v.pg, ref)
        if found:
            v.set_tool(None)
            v.select(found[0])
            q = v._q(annotate.from_page(v.pg, fitz.Rect(found[0].rect)))
            self._scroll.ensureVisible(int(q.center().x()),
                                       int(q.center().y()), 100, 150)

    def auto_walls(self, quiet=False):
        """Walls (centerline length by thickness) and doors (by width)
        on this sheet, from its linework, as one undoable step."""
        from . import autowalls
        v = self._view
        if not v:
            return None
        sc = v.scale()
        if not sc:
            QMessageBox.information(
                self, "Auto Walls & Doors", "Set the scale for this page "
                "first (Takeoff > Set Scale or Auto Scale).")
            return None
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            try:
                ws = autowalls.walls(v.pg, sc["ppu"], sc["unit"])
            except autowalls.AutoWallsError:
                ws = []
            if len(ws) < 2 and len(autowalls.segments(v.pg)) < 200:
                # hardly any linework: a scan - read the walls in the picture
                segs = autowalls.raster_segments(v.pg, sc["ppu"],
                                                 sc["unit"])
                ws = autowalls.walls(v.pg, sc["ppu"], sc["unit"],
                                     segs=segs)
            ds = autowalls.doors(v.pg, sc["ppu"], sc["unit"])
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.information(self, "Auto Walls & Doors", str(e))
            return None
        finally:
            if QApplication.overrideCursor():
                QApplication.restoreOverrideCursor()
        if not ws and not ds:
            QMessageBox.information(
                self, "Auto Walls & Doors", "No walls or door swings found "
                "on this page's linework.")
            return None
        v.apply_marks(autowalls.marks(v.page, ws, ds, sc))
        self._show_takeoff_panel()
        sm = autowalls.summary(ws, ds)
        unit = sc["unit"]
        lines = [f"{t}: {n:,.1f} {unit}" for t, n in
                 sorted(sm["walls"].items())]
        lines += [f"{t}: {n} ea" for t, n in sorted(sm["doors"].items())]
        msg = "Took off " + "; ".join(lines)
        self._flash(msg)
        if not quiet:
            QMessageBox.information(
                self, "Auto Walls & Doors", "\n".join(
                    ["Found on this sheet:", ""] + lines +
                    ["", "Each wall type and door size is its own group in "
                     "Quantities. Check them over: delete any that aren't "
                     "walls (Ctrl+Z undoes the whole takeoff)."]))
        return sm

    def company_directory(self, show=True):
        """Your subcontractor contacts (kept on this computer only)."""
        from .subdir_ui import DirectoryDialog
        dlg = DirectoryDialog(self)
        if show:
            dlg.show()
        self._dir_dlg = dlg
        return dlg

    def voice_commands(self):
        """Turn listening for voice commands on or off."""
        if getattr(self, "voice", None) is None:
            from .voice_ui import VoiceControl
            self.voice = VoiceControl(self)
        return self.voice.toggle()

    def calculators(self, tab=0, show=True):
        """Concrete (0), Brick & Block (1), Roofing (2), Rebar (3), Beam
        and Header (4), Column and Post (5), Footing Size (6), Metal Stud
        Framing (7), Structural Steel (8), Earthwork (9), Aggregate and
        Asphalt (10), Drywall (11) and Paint (12) calculators; a drawing's takeoff can fill the sizes, but none is
        needed."""
        from .calculators_ui import CalculatorDialog
        doc = self._view.doc if self._view is not None else None
        dlg = CalculatorDialog(self, doc, tab)
        if show:
            dlg.exec()
        return dlg

    def date_calculators(self, tab=0, show=True):
        """Date and Time Calculators (Jon, Oct 21): days between dates,
        date + time duration, add / subtract (days or workdays), weekday,
        week number. Workdays skip the open drawing's project holidays
        when it has a project."""
        from .datecalc_ui import DateCalcDialog
        hol = ()
        try:
            from .pm.store import ProjectStore, open_store
            if self._path:
                d = os.path.dirname(os.path.abspath(self._path))
                for folder in (d, os.path.dirname(d)):
                    if ProjectStore.exists(folder):
                        hol = open_store(folder).setting("holidays") or ()
                        break
        except Exception:                            # noqa: BLE001
            hol = ()
        dlg = DateCalcDialog(self, hol, tab)
        if show:
            dlg.exec()
        return dlg

    def _show_roof_tools(self, on):
        settings.set("roof_takeoff", bool(on))
        self.roof_act.setVisible(bool(on))

    def roof_takeoff(self, show=True):
        """Roof Plan Takeoff: pitch, true quantities and squares from the
        roof you drew on a scaled plan (never from aerial images)."""
        from .roof_ui import RoofDialog
        if not self._view:
            return None
        dlg = RoofDialog(self)
        if show:
            dlg.exec()
        return dlg

    def trade_takeoff(self, show=True):
        """Pipe, duct, legend devices, roofing, rebar and earthwork."""
        from .tradetakeoff_ui import TradeTakeoffDialog
        if not self._view:
            return None
        dlg = TradeTakeoffDialog(self)
        if show:
            dlg.exec()
        return dlg

    def check_takeoff(self, show=True):
        """Step through automatic measurements to accept or delete each."""
        from .tradetakeoff_ui import CheckTakeoffDialog
        if not self._view:
            return None
        dlg = CheckTakeoffDialog(self)
        if show:
            dlg.show()
        self._check_dlg = dlg
        return dlg

    def toggle_room_tag_area(self, on=None):
        if on is None:
            on = self.room_tag_act.isChecked()
        self.room_tag_act.setChecked(bool(on))
        settings.set("rooms_use_tag_area", bool(on))
        return bool(on)

    def auto_takeoff_rooms(self):
        """Every tagged room on the page becomes an area measurement."""
        if not self._view:
            return
        got = self._view.auto_takeoff_rooms()
        if got is None:
            return
        found, missed = got
        self._show_takeoff_panel()
        if not found and not missed:
            QMessageBox.information(
                self, "Auto Takeoff",
                "No room tags found on this page (a room name with its "
                "area, like \"LOBBY  245 SF\").\n\nUse Auto Area "
                "(Shift+R) and click inside each room instead.")
            return
        from . import autotakeoff
        tagged = [r for r in found if r.get("tag_sf")]
        named = [r for r in found if not r.get("tag_sf")]
        per_tag = [r for r in found if r.get("per_tag")]
        close = [r for r in tagged if not r.get("per_tag") and
                 abs(r["sqft"] - r["tag_sf"]) <= 0.05 * r["tag_sf"]]
        check = [r for r in tagged if r not in close and r not in per_tag]
        lines = [f"Took off {len(found)} of {len(found) + len(missed)} "
                 f"rooms; {len(close)} traced within 5% of their area "
                 "tags."]
        k = autotakeoff.scale_ratio(found)
        if autotakeoff.scale_looks_wrong(found):
            lines.insert(0, f"⚠ THE PAGE SCALE LOOKS WRONG: rooms measure "
                         f"about {_c2(k):.2f}× the areas printed in their tags. "
                         "Check Takeoff > Set Scale (an architectural "
                         "plan is usually 1/4\" = 1'-0\" or 1/8\" = "
                         "1'-0\"), then run this again.\n")
        if per_tag:
            lines.append(f"{len(per_tag)} room(s) used the area printed in "
                         "the room tag because the trace was more than 5% "
                         "off (marked \"per tag\"; turn this off under "
                         "Takeoff > Rooms: Use Tag Area):")
            lines += [f"   {r['name'] or 'Room'}: tag {r['tag_sf']:,.0f} "
                      f"SF, traced {r['traced_sf']:,.0f}" for r in per_tag]
        if named:
            lines.append(f"{len(named)} room(s) had a name but no area tag "
                         "- look these over (Takeoff > Check Takeoff).")
        if check:
            lines.append("\nCheck these (traced area vs. tag):")
            lines += [f"   {r['name'] or 'Room'}: {r['sqft']:,.0f} vs "
                      f"{r['tag_sf']:,.0f} SF" for r in check]
        if missed:
            lines.append("\nNot found - draw these by hand or click them "
                         "with Auto Area (Shift+R):")
            lines += [f"   {t['name'] or 'Room'}" +
                      (f" ({t['sf']:,.0f} SF)" if t.get("sf") else "")
                      for t in missed]
        QMessageBox.information(self, "Auto Takeoff", "\n".join(lines))

    def auto_count_label(self, show=True, text=""):
        """Takeoff > Count by Label (Nov 1: a hit list to check first, and
        wildcards for tag families - label_search_ui)."""
        if not self._view:
            return None
        from . import label_search_ui
        dlg = label_search_ui.open_dialog(self, show=show, text=text)
        if dlg is not None and dlg.counted:
            self._show_takeoff_panel()
        return dlg

    def item_names_learned(self, show=True):
        """Takeoff > Item Names Learned (Nov 1, name_memory)."""
        from . import name_memory_ui
        return name_memory_ui.open_dialog(self, show=show)

    def try_count_library(self, show=True):
        """Takeoff > Try the Count Library (Nov 1)."""
        if not self._view:
            return None
        from . import count_library_ui
        dlg = count_library_ui.open_dialog(self, show=show)
        if show and dlg is not None and dlg.result:
            self._show_takeoff_panel()
        return dlg

    # ---- versions / signing ----------------------------------------------------
    def show_versions(self):
        if not self._path:
            QMessageBox.information(self, "Versions",
                                    "Save the document first.")
            return

        def load(data):
            self._restore(data)
            self._view.history.snapshot()
            self._flash("Opened revision — save to keep it")

        from .versions_dialog import VersionsDialog
        VersionsDialog(self._path, get_bytes=self._view.doc.tobytes,
                       on_load=load, parent=self).exec()

    def sign(self):
        if not self._view:
            return
        if self._view.dirty or not self._path:
            QMessageBox.information(self, "Sign",
                                    "Save the document before signing.")
            if not self.save_file():
                return
        reason, ok = QInputDialog.getText(self, "Sign", "Reason:",
                                          text="Approved")
        if not ok:
            return
        base, _ = os.path.splitext(self._path)
        out, _ = QFileDialog.getSaveFileName(self, "Save Signed Copy",
                                             base + "_signed.pdf",
                                             "PDF (*.pdf)")
        if not out:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            from .sign import signer
            signer.sign_pdf(self._path, out, reason=reason)
        except Exception as ex:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Sign", f"Signing failed:\n{ex}")
            return
        QApplication.restoreOverrideCursor()
        QMessageBox.information(
            self, "Sign", f"Signed copy saved:\n{out}\n\nIt was signed with "
            "your personal self-signed certificate (in ~/.quantisheet). Other "
            "people will see the signer as not verified unless they trust it."
            "\n\nA self-signed signature "
            "proves this QuantiSheet install signed it"
            " and the file hasn't changed since - not who you are.")
        self.open_path(out)

    def timestamp_server(self, ask=None):
        """File > Signing Timestamp Server (Venice #3): off until a server
        is set. With one, each signature gets a trusted time from it (the
        only time signing goes online). Blank turns it off."""
        from .sign import timestamp
        cur = timestamp.timestamp_url()
        if ask is None:
            def ask(text, value):
                v, ok = QInputDialog.getText(self, "Signing Timestamp Server",
                                             text, text=value)
                return v if ok else None
        got = ask("Timestamp server address (RFC 3161). Leave blank for no "
                  "timestamp - then a signature's time is this PC's clock."
                  f"\nA common free one: {timestamp.SUGGESTED_TIMESTAMP_URL}",
                  cur)
        if got is None:
            return cur
        got = got.strip()
        if got and not got.lower().startswith(("http://", "https://")):
            QMessageBox.warning(self, "Signing Timestamp Server",
                                "The address must start with http:// or "
                                "https://")
            return cur
        settings.set(timestamp.SETTING, got)
        self._flash("Signatures will be timestamped by " + got if got else
                    "Signatures won't be timestamped")
        return got

    def verify(self):
        if not self._path:
            return
        try:
            from .sign import verify
            res = verify.verify_document(self._path)
        except Exception as ex:
            QMessageBox.warning(self, "Verify", f"Could not check:\n{ex}")
            return
        lines = []
        for r in res:
            if "field" in r:
                if r.get("error"):
                    lines.append(f"✗ {r['field']}: error — {r['error']}")
                    continue
                state = "✓" if r.get("valid") else "✗"
                # one plain line per signature (Venice #4, Nov 4)
                lines.append(f"{state} {r['field']}: " + (r.get("message") or
                             ("intact" if r.get("valid") else "BROKEN")))
            elif "audit_entries" in r:
                ok = "intact" if r["audit_chain_valid"] else "TAMPERED"
                lines.append(f"Audit trail: {r['audit_entries']} entries, {ok}")
        QMessageBox.information(self, "Signatures",
                                "\n".join(lines) or "This PDF has no signatures.")

    # ---- review / tools -------------------------------------------------------
    BIG_SET = 60        # pages: above this, slow whole-set jobs go background

    def _in_background(self, title, text, work, done):
        """Run work(copy_of_the_pdf) on a worker thread, with a progress box,
        while the window stays usable; then done(result) here. The worker
        gets its own copy of the document (PyMuPDF documents aren't safe
        to share between threads)."""
        import fitz
        from PySide6.QtWidgets import QProgressDialog
        from . import bg
        data = self._view.doc.tobytes()
        dlg = QProgressDialog(text + " You can keep working.", "Hide", 0, 0,
                              self)
        dlg.setWindowTitle(title)
        dlg.setMinimumDuration(0)
        dlg.setWindowModality(Qt.NonModal)
        dlg.show()

        def job():
            d = fitz.open("pdf", data)
            try:
                return work(d)
            finally:
                d.close()

        def ok(r):
            dlg.close()
            done(r)

        def failed(msg):
            dlg.close()
            QMessageBox.warning(self, title, f"{title} failed:\n{msg}")
        bg.run(job, ok, failed, self)
        return dlg

    def auto_markup(self):
        if not self._view:
            return
        v = self._view
        if v.doc.page_count <= self.BIG_SET:
            n = v.apply_marks(rules_mod.find_marks(v.doc))
            QMessageBox.information(self, "Auto-Markup", f"{n} marks applied")
            return

        def done(marks):
            if self._view is not v:
                return
            n = v.apply_marks(marks)
            QMessageBox.information(self, "Auto-Markup", f"{n} marks applied")
        self._in_background(
            "Auto-Markup", f"Reading {v.doc.page_count} pages for the "
            "markup rules...", rules_mod.find_marks, done)

    def edit_rules(self):
        if self._view:
            from .rules_dialog import RulesDialog
            RulesDialog(self._view, self).exec()

    def open_macros(self):
        if self._view:
            from .macro_dialog import MacroDialog
            MacroDialog(self._view, self).exec()

    def start_relay(self):
        if self._relay:
            ws_url, web_url = self._relay.urls()
            QMessageBox.information(self, "Relay", "The relay is already "
                                    f"running.\n\n{ws_url}\nPhones: {web_url}")
            return
        try:
            from .collab import relay
            # reachable from the network only with a token (review H-3):
            # one random token per computer, kept so links stay valid
            tok = settings.get("relay_host_token")
            if not tok:
                import secrets
                tok = secrets.token_urlsafe(12)
                settings.set("relay_host_token", tok)
            if relay.tls_context() is None and \
                    not settings.get("collab_allow_plain_lan"):
                if QMessageBox.question(
                        self, "Relay",
                        "No certificate is set, so the relay would be "
                        "unencrypted on your network (ws://): anyone on it "
                        "could read the relay token, room passwords and "
                        "drawings.\n\nStart it anyway for a trusted in-house "
                        "network? (You can turn this off in Live "
                        "Collaboration.)") != QMessageBox.Yes:
                    return
                settings.set("collab_allow_plain_lan", True)
            self._relay = relay.start_background(token=tok)
            # this computer's own project sharing uses it too
            if not settings.get("hub_token"):
                settings.set("hub_token", tok)
        except Exception as ex:
            QMessageBox.warning(self, "Relay", f"Could not start the relay:\n{ex}"
                                "\n\n(Is another copy already running?)")
            return
        ws_url, web_url = self._relay.urls()
        QMessageBox.information(
            self, "Relay",
            f"Relay running.\n\nDesktop peers connect to: {ws_url}\n"
            f"Relay token: {self._relay.token}\n"
            f"Phones/tablets open: {web_url}\n\n"
            "Give the token only to people you invite - without it nobody "
            "else on the network can use the relay. The phone link "
            "contains the token, so it lets anyone who has it join and "
            "edit: share it like a password.\n\n"
            "Now use Tools > Live Collaboration to join as host. Your "
            "firewall may ask to allow QuantiSheet on the network.")

    def open_collab(self):
        if not self._view:
            return
        from .collab_dialog import CollabDialog
        CollabDialog(self._view, self, relay=self._relay,
                     on_status=self._on_collab_status).exec()
        self._update_status()

    def shortcuts(self):
        dlg = self.help_center(show=False)
        dlg.show_shortcuts()
        dlg.show()
        return dlg

    def help_center(self, tutorial="first", show=True):
        """Help Center: tutorials with Show Me, shortcuts, practice set."""
        from .helpcenter import HelpCenter
        dlg = getattr(self, "_help_dlg", None)
        if dlg is None:
            dlg = self._help_dlg = HelpCenter(self, tutorial)
        else:
            dlg.open_tutorial(tutorial)
        if show:
            dlg.show()
            dlg.raise_()
        return dlg

    def support_bundle(self, path=None):
        """Help > Support Bundle: a zip for the help desk - versions,
        Windows edition, IT policy, what's working, the logs. No keys,
        passwords or email addresses."""
        import datetime
        from . import diagnostics
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Save Support Bundle", os.path.join(
                    os.path.expanduser("~"), "Desktop",
                    f"QuantiSheet-support-{datetime.date.today():%Y%m%d}.zip"),
                "Zip files (*.zip)")
            if not path:
                return None
        try:
            diagnostics.bundle(path)
        except Exception as e:                            # noqa: BLE001
            QMessageBox.warning(self, "Support Bundle",
                                f"The bundle wasn't made: {e}")
            return None
        self.statusBar().showMessage(f"Support bundle saved: {path}", 8000)
        return path

    def work_on_local_copy(self, ask=None):
        """File > Work on a Local Copy (Venice #14): for a file on a share
        or in OneDrive - save it, copy it to this PC and keep working on
        the copy. Copy Back to the Original puts it back, refused if
        someone changed the original meanwhile."""
        from . import jobsafe
        v = self._view
        if v is None or not self._path:
            return None
        if jobsafe.local_copy_info(self._path):
            self._flash("This is already your local copy - use File > "
                        "Copies & Cloud > Copy Back to the Original when "
                        "you're done")
            return self._path
        if v.dirty and not self.save_file():
            return None
        orig = self._path
        try:
            local = jobsafe.make_local_copy(orig)
        except OSError as e:
            QMessageBox.warning(self, "Local Copy",
                                f"The copy couldn't be made: {e}")
            return None
        i = self.tabs.currentIndex()
        if self.open_path(local):
            try:
                jobsafe.drop_lock(orig)
            except Exception:                             # noqa: BLE001
                pass
            for j in range(self.tabs.count()):        # close the original
                t = self.tabs.widget(j)
                if j == i and getattr(t, "path", None) and \
                        os.path.normcase(t.path) == os.path.normcase(orig):
                    t.view.dirty = False
                    self.close_tab(j)
                    break
            self._flash("Working on a copy on this PC. File > Copies "
                        "& Cloud > Copy Back to the Original when you're done.", 12000)
        return local

    def copy_back_original(self, ask=None):
        from . import jobsafe
        v = self._view
        if v is None or not self._path:
            return None
        if not jobsafe.local_copy_info(self._path):
            self._flash("This file isn't a local copy")
            return None
        if v.dirty and not self.save_file():
            return None
        # the original open in another tab holds the file on Windows
        # (WinError 5): close those tabs first, or stop if one has unsaved
        # work (Chief's estimator test, Nov 7)
        orig = jobsafe.local_copy_info(self._path).get("original") or ""
        if orig and not self._release_tabs_of(orig):
            return None
        # the drawing process keeps the last few files it drew open, the
        # original among them - the real cause of "Access denied" on a
        # plain Copy Back (Chief's re-test, Nov 7)
        from . import render_worker
        if orig:
            render_worker.release(orig, wait=3.0)
        try:
            out = jobsafe.copy_back(self._path)
        except jobsafe.CopyBackError as e:
            if ask is None:
                ask = lambda t: QMessageBox.question(      # noqa: E731
                    self, "Copy Back", t) == QMessageBox.Yes
            if "changed the original" not in str(e) or not ask(
                    f"{e}\n\nSave yours beside it as \"(mine)\" instead, "
                    "so neither is lost?"):
                self._copy_back_failed()
                if "changed the original" not in str(e):
                    QMessageBox.warning(self, "Copy Back", str(e))
                return None
            try:
                out = jobsafe.copy_back(self._path, force=True)
            except jobsafe.CopyBackError as e2:
                self._copy_back_failed()
                QMessageBox.warning(self, "Copy Back", str(e2))
                return None
        self._flash("Copied back: " + out, 10000)
        return out

    def _copy_back_failed(self):
        """The status bar never says "Saved" after a Copy Back that didn't
        happen (Chief's re-test, Nov 7)."""
        msg = "Copy Back didn't happen - the original is unchanged"
        try:
            self.statusBar().showMessage(msg, 0)
            self._flash(msg, 15000)
        except Exception:                                 # noqa: BLE001
            pass

    def _release_tabs_of(self, path):
        """Close every clean tab showing `path`, in this window and any
        other QuantiSheet window. False (and nothing closed) when one has
        unsaved changes."""
        want = os.path.normcase(os.path.abspath(path))
        wins = [self] + [w for w in QApplication.topLevelWidgets()
                         if w is not self and isinstance(w, MainWindow)]
        hits = []
        for w in wins:
            for j in range(w.tabs.count()):
                t = w.tabs.widget(j)
                p = getattr(t, "path", None)
                if p and os.path.normcase(os.path.abspath(p)) == want:
                    hits.append((w, t))
        for _w, t in hits:
            if getattr(getattr(t, "view", None), "dirty", False):
                QMessageBox.warning(
                    self, "Copy Back",
                    "The original is open in another tab with unsaved "
                    "changes. Save or close that tab, then Copy Back.")
                return False
        for w, t in hits:
            j = w.tabs.indexOf(t)
            if j >= 0:
                w.close_tab(j)
        if hits:
            self._flash("Closed the original's tab so it can be replaced")
        return True

    def attachments(self, pick=None, save_to=None):
        """Document > Attachments: save a file attached to this PDF. It is
        written out first by safe_extract (allowed types only, never
        opened or run), then copied where you choose (PR 15)."""
        import shutil
        from . import safe_extract
        v = self._view
        if v is None:
            return None
        found = safe_extract.listing(v.doc)
        if not found:
            self._flash("This PDF has no attachments")
            return None
        names = [n for n, _k in found]
        if pick is None:
            name, ok = QInputDialog.getItem(
                self, "Attachments", "Save a copy of:", names, 0, False)
            if not ok:
                return None
        else:
            name = pick
        try:
            tmp = safe_extract.extract(v.doc, name, safe_extract.SAVE_EXT)
        except safe_extract.ExtractError as e:
            QMessageBox.warning(self, "Attachments", f"{name}: {e}")
            return None
        if save_to is None:
            save_to, _ = QFileDialog.getSaveFileName(
                self, "Save Attachment", os.path.join(
                    os.path.expanduser("~"), "Documents",
                    os.path.basename(tmp)))
            if not save_to:
                shutil.rmtree(os.path.dirname(tmp), ignore_errors=True)
                return None
        shutil.copyfile(tmp, save_to)
        shutil.rmtree(os.path.dirname(tmp), ignore_errors=True)
        self._flash("Saved (not opened): " + save_to)
        return save_to

    def recent_problems(self, show=True):
        """Help > Recent Problems: the last warnings and errors from the
        log, with Copy (log_view.py, PR 11)."""
        from . import log_view
        dlg = log_view.LogViewer(self)
        if show:
            dlg.show()
        return dlg

    def welcome_tour(self):
        """A guided walk around the window (different from the Help
        Center's step-by-step tutorials)."""
        from . import tour
        return tour.start(self)

    def practice_job(self, show=True):
        """Help > Practice Job: open, scale, measure, price, export on a
        made-up plan in its own folder (practice_job.py)."""
        from . import practice_job_ui
        self._practice_job = practice_job_ui.open_window(self, show)
        return self._practice_job

    def open_guide(self, show=True):
        """Help > Features & How-To Guide (PDF): every feature and how to
        use it, opened in a tab from a read-only copy."""
        from .helpcenter import guide_copy
        try:
            path = guide_copy()
        except OSError as e:
            path, why = None, str(e)
        else:
            why = "This install doesn't have the guide."
        if not path:
            if show:
                QMessageBox.information(
                    self, "Features & How-To Guide",
                    "Couldn't open the guide. " + why)
            return None
        self.open_path(path)
        return path

    def open_practice(self):
        from . import practice
        from .helpcenter import practice_path
        path = practice.make(practice_path())
        self.open_path(path)
        return path

    def enter_license(self, show=True):
        """Paste a new beta key (e.g. when the old one ends)."""
        from . import betalicense
        dlg = betalicense.LicenseDialog(self)
        if not show:
            return dlg
        if dlg.exec() == 1:
            self._beta_label = betalicense.label()
            self.setWindowTitle(self.windowTitle().split("   [")[0])
        return dlg

    def about(self, page="About", show=True):
        from .legal import LegalDialog
        dlg = LegalDialog(self, page)
        if show:
            dlg.exec()
        return dlg

    # ---- PDF tools ------------------------------------------------------
    def _ask_save(self, title, suffix, filt):
        base = os.path.splitext(self._path or "document")[0]
        path, _ = QFileDialog.getSaveFileName(self, title, base + suffix, filt)
        from . import safeio
        if path and self._view and safeio.same_file(self._view.doc, path):
            # a copy can't replace the file that is open in this tab
            # (Windows refuses; review 3b B8)
            QMessageBox.information(
                self, title, "That's the file you have open. Save the copy "
                "under a different name.")
            return ""
        return path

    def combine_files(self):
        from . import acrobat
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Combine Files", "",
            "PDFs and images (*.pdf *.png *.jpg *.jpeg *.tif *.tiff *.bmp)")
        if not paths:
            return None
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            doc = acrobat.combine(paths)
        except Exception as ex:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Combine", str(ex))
            return None
        QApplication.restoreOverrideCursor()
        self._flash(f"Combined {len(paths)} files ({doc.page_count} pages). "
                    "Save to keep it.")
        return self.open_document(doc, "Combined.pdf")

    def _export_big(self, fmt, target):
        """export_as for a big set: the same exports, on a worker thread."""
        from . import acrobat, acrobat2
        jobs = {
            "png": lambda d: acrobat.export_images(d, target, "png", dpi=150),
            "jpg": lambda d: acrobat.export_images(d, target, "jpg", dpi=150),
            "docx": lambda d: acrobat.export_word(d, target),
            "pptx": lambda d: acrobat2.export_powerpoint(d, target),
            "html": lambda d: acrobat2.export_html(d, target),
            "xlsx": lambda d: acrobat.export_excel(d, target),
            "txt": lambda d: acrobat.export_text(d, target)}

        def done(out):
            # pick the message first: Excel returns a count, not a list,
            # and len() on it raised before (Grok r5 #4)
            if fmt == "docx":
                msg = "Exported to Word (text; tables from pages up to 11x17)"
            elif fmt in ("png", "jpg"):
                n_img = len(out) if isinstance(out, (list, tuple)) else out
                msg = f"Saved {n_img or 0} images"
            else:
                msg = f"Exported {os.path.basename(str(target))}"
            self._flash(msg)
        n = self._view.doc.page_count
        self._in_background("Export", f"Exporting {n} pages...", jobs[fmt],
                            done)
        return target

    def protect(self):
        from . import acrobat
        from .acrobat_dialogs import ProtectDialog
        if not self._view:
            return None
        dlg = ProtectDialog(self)
        if not dlg.exec():
            return None
        path = self._ask_save("Save Protected Copy", "_protected.pdf",
                              "PDF (*.pdf)")
        if not path:
            return None
        try:
            acrobat.save_protected(self._view.doc, path, **dlg.values())
        except Exception as ex:
            QMessageBox.warning(self, "Protect", str(ex))
            return None
        self._flash(f"Saved protected copy: {os.path.basename(path)}")
        return path

    def unprotect(self):
        from . import acrobat
        if not self._view:
            return None
        if not self._view.doc.metadata.get("encryption"):
            QMessageBox.information(self, "Remove Security",
                                    "This document isn't protected.")
            return None
        path = self._ask_save("Save Unprotected Copy", "_unlocked.pdf",
                              "PDF (*.pdf)")
        if path:
            try:
                acrobat.save_unprotected(self._view.doc, path)
            except OSError as ex:            # e.g. open in another program
                QMessageBox.warning(self, "Remove Security", str(ex))
                return None
            self._flash("Saved a copy without a password")
        return path

    def reduce_size(self):
        if not self._view:
            return None
        path = self._ask_save("Save Smaller Copy", "_reduced.pdf",
                              "PDF (*.pdf)")
        if not path:
            return None
        return self._write_reduced(path, 150, "Reduce File Size")

    def _write_reduced(self, path, image_dpi=150, title="Reduce File Size",
                       show=True):
        """A smaller copy of this document at `path` (images down to
        `image_dpi`); this document is not changed. Returns the new size,
        or None when nothing was written."""
        from . import acrobat, safeio
        prot = getattr(self._view, "protection", None)
        not_smaller = None
        unprotected = False
        while True:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                # compare with the file as it is (or, with unsaved changes,
                # as a normal save would write it); keep the copy only if
                # smaller. A protected document's copy keeps its passwords
                # and permissions (it is copied with its own encryption).
                before = acrobat.baseline_size(self._view.doc, self._path,
                                               edited=self._view.dirty)
                if unprotected:
                    tmp = fitz.open(stream=self._view.doc.tobytes(),
                                    filetype="pdf")
                else:
                    tmp = safeio.protected_copy(
                        self._view.doc, prot.open_pw if prot else None)
                try:
                    after = acrobat.reduce_size(tmp, path, original=before,
                                                   in_place=True,
                                                   image_dpi=image_dpi)
                except acrobat.NotSmaller as e:
                    not_smaller = e
                finally:
                    tmp.close()
            except safeio.UnprotectedCopyError as e:
                failed = e
            else:
                failed = None
            finally:
                QApplication.restoreOverrideCursor()
            if failed is None:
                break
            if not show or unprotected or not confirm_unprotected_copy(
                    self, title, str(failed)):
                return None
            unprotected = True
        if not_smaller is not None:
            self._last_reduced = str(not_smaller)
            if show:
                QMessageBox.information(self, title, str(not_smaller))
            return None
        self._last_reduced = (f"Saved {os.path.basename(path)}\n"
                              f"{before / 1024:,.0f} KB → "
                              f"{after / 1024:,.0f} KB")
        if show:
            QMessageBox.information(self, title, self._last_reduced)
        return after

    def check_repair(self):
        """File > Check / Repair PDF…: check the file on disk page by page
        and, when it has problems, save '<name> (repaired).pdf' next to it.
        The original is never changed."""
        from . import acrobat2
        if not self._view:
            return None
        path = self._path
        if not path or not os.path.isfile(path):
            QMessageBox.information(
                self, "Check / Repair PDF", "This document has no file yet: "
                "save it first, then check it.")
            return None
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            rep = acrobat2.check_and_repair(path)
        finally:
            QApplication.restoreOverrideCursor()
        text = rep.text()
        if self._view.dirty:
            text += ("\n\n(The file on disk was checked; your unsaved "
                     "changes were not.)")
        if rep.ok:
            QMessageBox.information(self, "Check / Repair PDF", text)
        elif rep.out:
            if QMessageBox.question(
                    self, "Check / Repair PDF",
                    text + "\n\nOpen the repaired copy?") == QMessageBox.Yes:
                self.open_path(rep.out)
        else:
            QMessageBox.warning(self, "Check / Repair PDF", text)
        return rep

    def booklet_nup(self):
        """Pages > Booklet / N-up…: lay the pages out for printing in a
        new PDF (the open document isn't changed)."""
        from . import booklet
        from .booklet_ui import BookletDialog
        v = self._view
        if not v:
            return None
        dlg = BookletDialog(self, v.doc.page_count)
        if not dlg.exec():
            return None
        opts = dlg.values()
        from . import safeio
        # the layout is a new PDF built from the pages: it can't carry the
        # original's password protection, so say so and ask first
        if safeio.is_encrypted(v.doc) and not confirm_unprotected_copy(
                self, "Booklet / N-up", "The booklet / N-up layout is a new "
                "PDF and can't keep this document's password protection."):
            return None
        suffix = "_booklet.pdf" if opts["mode"] == "booklet" else \
            f"_{opts['mode']}.pdf"
        out = self._ask_save("Booklet / N-up", suffix, "PDF (*.pdf)")
        if not out:
            return None
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            sides = booklet.write(v.doc, out, mode=opts["mode"],
                                  paper=opts["paper"],
                                  gutter=opts["gutter"],
                                  creep=opts["creep"],
                                  flip_back=opts["flip_back"],
                                  markups=opts["markups"])
        except Exception as ex:
            QApplication.restoreOverrideCursor()
            log.warning("booklet / n-up failed", exc_info=True)
            QMessageBox.warning(self, "Booklet / N-up",
                                f"Could not make the layout:\n{ex}")
            return None
        QApplication.restoreOverrideCursor()
        what = f"{sides // 2} sheet(s), both sides" \
            if opts["mode"] == "booklet" else f"{sides} sheet(s)"
        self._flash(f"Saved {os.path.basename(out)}: {what}")
        return out

    def header_footer(self, page_numbers=False):
        from . import acrobat
        from .acrobat_dialogs import HeaderFooterDialog
        if not self._view or self._collab_blocked("Headers and footers"):
            return
        dlg = HeaderFooterDialog(self, page_numbers_only=page_numbers)
        if not dlg.exec():
            return
        v = dlg.values()
        if not v["texts"]:
            return
        self._page_change(lambda: acrobat.header_footer(
            self._view.doc, v["texts"], size=v["size"], margin=v["margin"],
            start=v["start"]), "Added header/footer")

    def crop_pages(self, rect, all_pages=None):
        from . import acrobat
        if not self._view or self._collab_blocked("Cropping"):
            return
        v = self._view
        if all_pages is None:
            all_pages = v.doc.page_count > 1 and QMessageBox.question(
                self, "Crop", "Crop every page the same way? "
                "(No = this page only)") == QMessageBox.Yes
        pages = list(range(v.doc.page_count)) if all_pages else [v.page]
        v.set_tool(None)
        self._page_change(lambda: acrobat.crop(v.doc, pages, rect),
                          f"Cropped {len(pages)} page(s)")

    def make_searchable(self):
        from . import acrobat
        from PySide6.QtWidgets import QProgressDialog
        if not self._view or self._collab_blocked("OCR"):
            return 0
        doc = self._view.doc
        pages = acrobat.pages_needing_ocr(doc)
        if not pages:
            QMessageBox.information(self, "OCR", "Every page already has "
                                    "searchable text.")
            return 0
        if not acrobat.tessdata_dir():
            QMessageBox.warning(
                self, "OCR", "Tesseract is not installed, so OCR isn't "
                "available. Install it from https://github.com/UB-Mannheim/"
                "tesseract/wiki and restart QuantiSheet.")
            return 0
        prog = QProgressDialog("Recognising text…", "Stop", 0, len(pages),
                               self)
        prog.setWindowTitle("Make Searchable")
        prog.setMinimumDuration(0)

        def step(n, total):
            prog.setValue(n)
            prog.setLabelText(f"Recognising text: page {n + 1} of {total}")
            QApplication.processEvents()
            return not prog.wasCanceled()

        skipped = []
        n = self._page_change(lambda: acrobat.make_searchable(
            doc, pages, progress=step, skipped=skipped),
            "Made scanned pages searchable")
        prog.close()
        if skipped:
            QMessageBox.information(
                self, "OCR", f"{len(skipped)} page(s) look like photos, not "
                "scanned drawings or text, and were left as they are (OCR "
                "would only add junk): page(s) " +
                ", ".join(str(p + 1) for p in skipped[:20]))
        return n or 0

    def search_redact(self):
        from .acrobat_dialogs import RedactDialog
        if not self._view:
            return 0
        dlg = RedactDialog(self._view.doc, self)
        if not dlg.exec():
            return 0
        n = self._view.apply_marks(dlg.marks())
        self._doc_reloaded()
        if self._view.last_redaction_error:
            self._flash("Redaction failed and was rolled back")
            return 0                # the warning was shown already
        self._flash(f"Redacted {n} item(s) - checked: nothing is left "
                    "under the boxes")
        return n

    def _redaction_failed(self, view, msg):
        """A redaction batch failed its proof and was rolled back (the
        document was reloaded from before the batch)."""
        if view is self._view:
            self._doc_reloaded()
        QMessageBox.warning(self, "Redact", msg)

    def prepare_form(self):
        from . import acrobat
        if not self._view:
            return 0
        marks = acrobat.detect_fields(self._view.doc)
        if not marks:
            QMessageBox.information(
                self, "Prepare Form", "No blanks or checkboxes were found. "
                "Use Edit > Add Text Field / Checkbox to place fields.")
            return 0
        n = self._view.apply_marks(marks)
        QMessageBox.information(self, "Prepare Form",
                                f"Added {n} form field(s). Double-click a "
                                "field to fill it in.")
        return n

    def clear_form(self):
        v = self._view
        if not v:
            return 0
        boxes = (fitz.PDF_WIDGET_TYPE_CHECKBOX, fitz.PDF_WIDGET_TYPE_RADIOBUTTON)
        marks = []
        for pno, page in enumerate(v.doc):
            for w in page.widgets():
                if w.field_value not in ("", None, "Off", False):
                    marks.append((pno, "set_field", {
                        "name": w.field_name,
                        "value": False if w.field_type in boxes else ""}))
        return v.apply_marks(marks)

    def flatten(self):
        from . import acrobat
        if not self._view or self._collab_blocked("Flattening"):
            return
        n_take = 0
        try:
            n_take = len(annotate.totals_items(self._view.doc))
        except Exception:                                 # noqa: BLE001
            n_take = 0
        warn = (f"\n\nThis includes {n_take} takeoff measurement(s): they "
                "become plain drawing and drop out of Quantities and the "
                "estimate. Use Save As first to keep a working copy."
                if n_take else "")
        if QMessageBox.question(
                self, "Flatten",
                "Burn all markups and form fields into the pages? They will "
                "no longer be editable. (Undo works until you save.)" + warn) \
                != QMessageBox.Yes:
            return
        self._page_change(lambda: acrobat.flatten(self._view.doc),
                          "Flattened markups and fields")


    # ---- more PDF tools ---------------------------------------------------------
    def new_from_form(self, choice=None):
        """Open a copy of a form from the Form Library (the blank stays
        blank), optionally cleared and filled from the current job."""
        from PySide6.QtWidgets import QDialog
        from . import formlib
        job = self._view.doc if self._view else None
        job_name = os.path.basename(self._path) if (job and self._path) \
            else ""
        if choice is None:
            from .formlib_ui import FormLibraryDialog
            dlg = FormLibraryDialog(self, job_name)
            if dlg.exec() != QDialog.Accepted or not dlg.chosen:
                return None
            choice = dlg.chosen
        entry, clear, fill = choice
        doc = formlib.open_copy(entry, clear=clear)
        filled = formlib.fill_from_job(doc, job if fill else None) \
            if fill else {}
        self.open_document(doc, entry["name"] + ".pdf")
        msg = f"New copy of {entry['name']}"
        if filled:
            msg += f" - filled {len(filled)} field(s) from the job"
        self.statusBar().showMessage(msg, 10000)
        return doc, filled

    def generate_set(self, request=None, out=None, wait=False):
        """File > Generate Set: a brief in, a ten-sheet starter set
        (FOR REVIEW - NOT FOR SEALING) out, opened when it is done."""
        from PySide6.QtWidgets import QDialog
        from . import bg, genset_ui
        if request is None:
            dlg = genset_ui.GenerateSetDialog(self)
            if dlg.exec() != QDialog.Accepted or not dlg.request:
                return None
            request = dlg.request
        if out is None:
            start = os.path.join(os.path.dirname(self._path) if
                                 self._path else os.path.expanduser("~"),
                                 genset_ui.default_name(request))
            out, _ = QFileDialog.getSaveFileName(self, "Save Generated Set",
                                                 start, "PDF (*.pdf)")
            if not out:
                return None
        if wait:                       # tests and scripts
            res = genset_ui.generate(request, out)
            self.open_path(res["path"])
            return res
        self.statusBar().showMessage("Generating the set…")
        QApplication.setOverrideCursor(Qt.WaitCursor)

        def done(res):
            QApplication.restoreOverrideCursor()
            self.open_path(res["path"])
            w = res.get("warnings") or []
            if res.get("dxf"):
                w = list(w)
                self._flash("The floor plan was also saved for CAD: "
                            + os.path.basename(res["dxf"]))
            self._flash(
                f"Generated {res['pages']} sheets - FOR REVIEW, NOT FOR "
                f"SEALING" + (f" - {len(w)} warning(s) on the cover"
                              if w else ""), 15000)

        def failed(msg):
            QApplication.restoreOverrideCursor()
            self.statusBar().clearMessage()
            if "modulor" in str(msg).lower():
                msg = "No set was made.\n\n" + str(msg)
            QMessageBox.warning(self, "Generate Set", msg)
        bg.run(lambda: genset_ui.generate(request, out), done, failed, self)
        return out

    def fill_form(self, job=None):
        """Fill this form's Project / Owner / Contractor... fields from the
        job (Billing > Contract details) and your company details."""
        from . import formlib
        v = self._view
        if not v:
            return None
        done = formlib.fill_from_job(v.doc, job or v.doc)
        if done:
            self._doc_edited()
            v._render()
        self.statusBar().showMessage(
            f"Filled {len(done)} field(s)." if done else
            "No empty fields here that match the job details (Billing > "
            "Contract & Billing holds project, owner and architect; "
            "company details come from Create Proposal).", 10000)
        return done

    def create_pdf(self):
        from . import acrobat2
        paths, _ = QFileDialog.getOpenFileNames(self, "Create PDF From", "",
                                                acrobat2.CREATE_FILTER)
        made = []
        for path in paths:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                doc = acrobat2.create_pdf(path)
            except Exception as ex:
                QApplication.restoreOverrideCursor()
                QMessageBox.warning(self, "Create PDF",
                                    f"{os.path.basename(path)}:\n{ex}")
                continue
            QApplication.restoreOverrideCursor()
            made.append(self.open_document(
                doc, os.path.splitext(os.path.basename(path))[0] + ".pdf"))
        return made

    def fill_from_job_and_sign(self, path=None, show=True):
        """Fill a form's fields from what QuantiSheet knows (each value
        shown with where it comes from), then sign it on request. Works
        on the open PDF as saved on disk, or a picked file; the result is
        a new file (fillsign_ui.py)."""
        from . import fillsign_ui, subdir
        tab = self.tabs.currentWidget()
        job_doc = self._view.doc if self._view else None
        if path is None:
            cur = getattr(tab, "path", None) if isinstance(tab, DocTab) \
                else None
            if cur and os.path.isfile(cur) and self._view is not None \
                    and not self._view.dirty:
                path = cur
            else:
                if cur and self._view is not None and self._view.dirty:
                    QMessageBox.information(
                        self, "Fill From the Job and Sign",
                        "Save this PDF first, or pick the form's file: the "
                        "form is filled from the file on disk into a new "
                        "file.")
                path, _f = QFileDialog.getOpenFileName(
                    self, "Form to Fill and Sign", "", "PDF (*.pdf)")
                if not path:
                    return None
        try:
            contacts = subdir.load()
        except Exception:                                 # noqa: BLE001
            contacts = []
        dlg = fillsign_ui.FillSignDialog(
            path, self, job_doc, contacts, on_open=self.open_path)
        if show:
            dlg.setAttribute(Qt.WA_DeleteOnClose)
            dlg.show()
        return dlg

    def _redraw_signature(self, kind):
        from .signature import SignaturePad
        SignaturePad(kind, self).exec()

    def doc_properties(self):
        from . import acrobat2
        from .acrobat2_dialogs import PropertiesDialog
        if not self._view:
            return
        dlg = PropertiesDialog(self._view.doc, self)
        if dlg.exec():
            acrobat2.set_properties(self._view.doc, **dlg.values())
            self._doc_edited()

    def sanitize(self):
        from . import acrobat2
        if not self._view or self._collab_blocked("Removing hidden data"):
            return
        if QMessageBox.question(
                self, "Remove Hidden Information",
                "Remove metadata, attached files, scripts, hidden text, links "
                "and thumbnails? Markups and form entries are kept.\n\n"
                "QuantiSheet's job data (estimate, prices, margins) is also "
                "kept. To send the file outside, use File > Export > "
                "External Issue (strip pricing).") \
                != QMessageBox.Yes:
            return
        doc = self._view.doc
        hid = acrobat2._has_hidden_text(doc)
        failed = self._page_change(lambda: acrobat2.sanitize(doc,
                                                             hidden_text=hid),
                                   "Removed hidden information")
        if failed is None:
            return
        # proof: check the cleaned file item by item (Venice, Oct 19)
        rows = acrobat2.verify_clean(doc, hidden_text=hid)
        bad = [r for r in rows if r[0] != "PASS"]

        def line(st, item, det):
            return (("✔  " if st == "PASS" else "✖  ") + item +
                    (f"  ({det})" if det else ""))
        proof = [r for r in rows if r[1].startswith("Redaction proof")]
        text = "\n".join(line(*r) for r in rows if r not in proof)
        if proof:
            # its own section: every box redacted here, checked again
            text += "\n\nRedaction proof:\n" + "\n".join(line(*r)
                                                         for r in proof)
        text += ("\n\nMarkups, form entries and QuantiSheet's job data "
                 "(scales, takeoff, prices) were kept. Save the file to "
                 "keep the clean copy.")
        if any(r[0] != "PASS" for r in proof):
            QMessageBox.warning(self, "Remove Hidden Information",
                                "Something is still left under a redaction "
                                "box. Don't send this file outside: redact "
                                "that area again and check it.\n\n" + text)
        elif bad or failed:
            QMessageBox.warning(self, "Remove Hidden Information",
                                "Not everything could be removed from this "
                                "file (it looks damaged). Check before "
                                "sending it outside.\n\n" + text)
        else:
            QMessageBox.information(self, "Remove Hidden Information",
                                    "Checked after cleaning:\n\n" + text)

    def duplicate_page(self):
        from . import acrobat2
        if not self._view or self._collab_blocked("Changing pages"):
            return
        v = self._view
        i = v.page
        if self._page_change(lambda: acrobat2.duplicate_page(v.doc, i),
                             f"Duplicated page {i + 1}") is not None:
            v.go_to(i + 1)

    def replace_pages(self):
        from . import acrobat2
        v = self._view
        if not v or self._collab_blocked("Changing pages"):
            return
        src, _ = QFileDialog.getOpenFileName(self, "Replace With Pages From",
                                             "", "PDF (*.pdf)")
        if not src:
            return
        first, ok = QInputDialog.getInt(self, "Replace Pages",
                                        "Replace starting at page:",
                                        v.page + 1, 1, v.doc.page_count)
        if not ok:
            return
        count, ok = QInputDialog.getInt(self, "Replace Pages",
                                        "How many pages:", 1, 1,
                                        v.doc.page_count - first + 1)
        if not ok:
            return
        self._page_change(lambda: acrobat2.replace_pages(
            v.doc, first - 1, count, src), f"Replaced {count} page(s)")

    def split_doc(self):
        from . import acrobat2
        v = self._view
        if not v:
            return None
        modes = ["Every N pages", "At each top-level bookmark"]
        mode, ok = QInputDialog.getItem(self, "Split Document", "Split:",
                                        modes, 0, False)
        if not ok:
            return None
        every = None
        if mode == modes[0]:
            every, ok = QInputDialog.getInt(self, "Split Document",
                                            "Pages per file:", 1, 1,
                                            max(1, v.doc.page_count))
            if not ok:
                return None
        folder = QFileDialog.getExistingDirectory(self, "Save Parts To")
        if not folder:
            return None
        base = os.path.splitext(os.path.basename(self._path or "document"))[0]
        try:
            out = acrobat2.split(v.doc, folder, every=every,
                                 by_bookmarks=mode == modes[1], base=base)
        except Exception as ex:
            QMessageBox.warning(self, "Split", str(ex))
            return None
        QMessageBox.information(self, "Split",
                                f"Saved {len(out)} files to:\n{folder}")
        return out

    def _sets_do(self, what):
        self.sets_dock.show()
        self.sets_dock.raise_()
        return getattr(self.sets, what)()

    def open_sheet(self, path, page):
        """Open a set's file (or switch to it) at a page."""
        self.open_path(path)
        if self._view and self._path and \
                os.path.normcase(self._path) == os.path.normcase(path):
            self._go_page(page)
        return self._view

    def preflight(self):
        """Check the PDF for print (fonts, resolution, colour, boxes) and
        export PDF/X."""
        if not self._view:
            return
        from .preflight_ui import PreflightDialog
        PreflightDialog(self).exec()

    def request_signatures(self):
        """Send this PDF out for e-signature (QuantiSheet relay or
        DocuSign)."""
        if not self._view:
            return
        from .esign_ui import RequestDialog
        d = getattr(self, "_esign_dlg", None)
        if d is None or not d.isVisible():
            d = self._esign_dlg = RequestDialog(self)
        d.show()
        d.raise_()

    def signature_requests(self):
        from .esign_ui import TrackerDialog
        d = TrackerDialog(self)
        d.refresh_all() if d.envs else None
        d.exec()

    def scheduler(self, new=False, store=None):
        """Project > Scheduler (Gantt): build the project's schedule in a
        grid + Gantt chart. Works with no PDF open. Opens the schedule of
        the open drawing's project folder when there is one."""
        from .pm import scheduler as sch
        from .pm.store import ProjectStore, open_store
        if store is None and not new and self._path:
            d = os.path.dirname(os.path.abspath(self._path))
            for folder in (d, os.path.dirname(d)):
                if ProjectStore.exists(folder):
                    store = open_store(folder)
                    break
        if store is None:
            store = sch.new_schedule_dialog(self) if new else \
                sch.choose_schedule(self)
        if store is None:
            return None
        return sch.open_scheduler(store, self)

    def weekly_owner_report(self, store=None):
        """Project > Weekly Owner Report: page 1, photos, RFI, submittal
        and weather logs as one PDF for the owner, filled from the job's
        Project Center (owner_report_ui). Opens the open drawing's project
        when there is one, else asks which project."""
        from .pm import owner_report_ui
        from .pm import scheduler as sch
        from .pm.store import ProjectStore, open_store
        if store is None and self._path:
            d = os.path.dirname(os.path.abspath(self._path))
            for folder in (d, os.path.dirname(d)):
                if ProjectStore.exists(folder):
                    store = open_store(folder)
                    break
        if store is None:
            store = sch.choose_schedule(
                self, "Weekly Owner Report",
                "Which project is this report for? Pick one, open its "
                "folder, or start a new project:", "New Project…")
        if store is None:
            return None
        return owner_report_ui.open_report(store, self)

    def project_center(self):
        """RFIs, submittals, punch, daily logs, meetings... for the job.
        Opens the project of the current file's folder when it has one."""
        from .pm import center
        from .pm.store import ProjectStore
        path = self._path
        if path:
            d = os.path.dirname(os.path.abspath(path))
            for folder in (d, os.path.dirname(d)):
                if ProjectStore.exists(folder):
                    return center.open_center(folder, self)
        return center.pick_and_open(self)

    def batch_slip_sheet(self, show=True):
        from .sets_ui import BatchSlipDialog
        if not self.sets.set:
            QMessageBox.information(
                self, "Batch Slip Sheet", "Make a set first (Project > New "
                "Set From Files): the files of the drawing set you've marked "
                "up and taken off.")
            return None
        dlg = BatchSlipDialog(self, self.sets.set)
        if show:
            dlg.exec()
            self.sets.use(self.sets.set)
        return dlg

    def revision_log(self, show=True):
        """What each drawing revision did to the bid."""
        from .revisions_ui import RevisionLogDialog
        if not self._view:
            return None
        dlg = RevisionLogDialog(self)
        if show:
            dlg.show()
        return dlg

    def compare_revisions(self, other=None):
        from .overlay_ui import CompareRevisionsDialog
        if not self._view:
            return None
        dlg = CompareRevisionsDialog(self, other)
        self._compare_dlg = dlg
        dlg.show()
        return dlg

    def compare_visual(self, other=None):
        from . import acrobat2
        if not self._view:
            return None
        if not other:
            other, _ = QFileDialog.getOpenFileName(
                self, "Compare With (older or newer revision)", "",
                "PDF (*.pdf)")
        if not other:
            return None
        cur = os.path.join(tempfile.mkdtemp(prefix="quantisheet-cmp-"),
                           "current.pdf")
        self._view.doc.save(cur)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            doc, stats = acrobat2.visual_compare(other, cur)
        except Exception as ex:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Compare", str(ex))
            return None
        QApplication.restoreOverrideCursor()
        v = self.open_document(
            doc, f"Overlay: {os.path.basename(other)} vs current")
        changed = [f"p{i + 1}: {s}%" for i, s in enumerate(stats) if s > 0]
        self._flash("Changed: " + (", ".join(changed[:12]) or "no changes"))
        return v, stats

    def batch(self):
        from .acrobat2_dialogs import BatchDialog, run_with_progress
        dlg = BatchDialog(self)
        if not dlg.exec():
            return None
        paths, actions, out_dir, options = dlg.job()
        results = run_with_progress(self, paths, actions, out_dir, options)
        bad = [f"{os.path.basename(s)}: {r}" for s, r in results
               if str(r).startswith("ERROR")]
        skipped = [f"{os.path.basename(s)}: {str(r)[len('SKIPPED: '):]}"
                   for s, r in results if str(r).startswith("SKIPPED")]
        done = len(results) - len(bad) - len(skipped)
        QMessageBox.information(
            self, "Action Wizard",
            f"Processed {done} of {len(paths)} file(s) "
            f"into:\n{out_dir}" +
            ("\n\nSkipped (no file written):\n" + "\n".join(skipped[:10])
             if skipped else "") +
            ("\n\nProblems:\n" + "\n".join(bad[:10]) if bad else ""))
        return results
