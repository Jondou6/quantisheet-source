"""The page view: renders one page and turns mouse/keyboard input into edits.

Everything the person draws becomes an "op" applied through
annotate.apply_op(), so it is undoable, recorded by macros and shared with
collaborators. The commit_* methods take *screen* coordinates (points on
the page as displayed, before zoom) and are what tests call directly.
"""
import base64
import logging
import os
import time
import uuid

from collections import OrderedDict

import fitz
import threading

from PySide6.QtCore import (Qt, QEvent, QObject, QRect, QRectF, QPointF,
                            QTimer, Signal)
from PySide6.QtGui import (QColor, QImage, QPainter, QPainterPath, QPen,
                           QPixmap, QBrush)
from PySide6.QtWidgets import (QApplication, QColorDialog, QFileDialog,
                               QInputDialog, QMenu, QMessageBox, QWidget)

from . import annotate, settings, snap, takeoff
from .collab.oplog import _plain
from .history import History
from .macros import Recorder
from .dmoney import c2 as _c2

log = logging.getLogger(__name__)
# GUI user test r42 F07: Enter makes a new line in these boxes
TEXT_PROMPT = "Text (Enter starts a new line - click OK to place it):"


def _mark_busy():
    try:
        from .panels import mark_busy
        mark_busy()
    except Exception:
        logging.getLogger(__name__).debug("ignored error", exc_info=True)

def apply_line_setting():
    """Acrobat's "Enhance thin lines": hairlines are drawn at least about
    one screen pixel wide, so faint 0-width CAD lines don't break up or
    vanish when a sheet is zoomed out."""
    from . import render_opts, settings
    # applied only while the viewer draws (render_opts.screen), so the
    # automatic tools and exports see the drawing as it really is
    render_opts.set_thin_lines(settings.get("thin_lines", True) is not False)
    try:
        fitz.TOOLS.set_aa_level(8)
    except Exception:
        logging.getLogger(__name__).debug("ignored error", exc_info=True)


apply_line_setting()


# tool id -> (label, kind of input)
TOOLS = {
    None: ("Select", "select"),
    "add_highlight": ("Highlight", "rect"),
    "add_underline": ("Underline", "rect"),
    "add_strike": ("Strikeout", "rect"),
    "add_rect": ("Rectangle", "rect"),
    "add_ellipse": ("Ellipse", "rect"),
    "add_cloud": ("Cloud", "rect"),
    "add_line": ("Line", "line"),
    "arrow": ("Arrow", "line"),
    "add_polyline": ("Polyline", "points"),
    "add_polygon": ("Polygon", "points"),
    "add_ink": ("Pen", "pen"),
    "add_note": ("Sticky Note", "click"),
    "add_textbox": ("Text Box", "rect"),
    "add_redact": ("Redact", "rect"),
    "edit_text": ("Edit Text", "click"),
    "select_text": ("Select Text", "text"),
    "add_image": ("Image", "rect"),
    "field_text": ("Text Field", "rect"),
    "field_checkbox": ("Checkbox", "rect"),
    "field_combo": ("Dropdown", "rect"),
    "calibrate": ("Set Scale", "line"),
    "measure_length": ("Length", "line"),
    "measure_polylength": ("Polylength", "points"),
    "measure_wall": ("Wall Area", "points"),
    "measure_area": ("Area", "points"),
    "measure_cutout": ("Cutout", "points"),
    "measure_volume": ("Volume", "points"),
    "measure_angle": ("Angle", "points"),
    "measure_radius": ("Radius", "line"),
    "measure_diameter": ("Diameter", "line"),
    "viewport": ("Viewport", "rect"),
    "zoom": ("Marquee Zoom", "rect"),
    "review_stamp": ("Submittal Review Stamp", "rect"),
    "legend": ("Legend", "rect"),
    "auto_area": ("Auto Area", "click"),
    "trace_length": ("Trace Length", "click"),
    "trace_outline": ("Trace Outline", "points"),
    "count": ("Count", "click"),
    "symbol": ("Count Symbol", "rect"),
    "symbol_sample": ("Box a Sample Symbol", "rect"),
    "missed_example": ("Box a Missed Copy", "rect"),
    "zone_include": ("AI Takeoff Zone: Only Here", "rect"),
    "zone_exclude": ("AI Takeoff Zone: Leave Out", "rect"),
    "snapshot": ("Snapshot", "rect"),
    "add_stamp": ("Stamp", "rect"),
    "crop": ("Crop Pages", "rect"),
    "callout": ("Callout", "line"),
    "date_stamp": ("Date Stamp", "click"),
    "fs_signature": ("Signature", "rect"),
    "fs_initials": ("Initials", "rect"),
    "fs_text": ("Fill Text", "click"),
    "fs_check": ("Check Mark", "click"),
    "fs_date": ("Date", "click"),
    "esign_field": ("Signature Request Field", "rect"),
}

# tools whose points snap to the drawing (Bluebeam's "Snap to Content")
SNAP_TOOLS = {"add_rect", "add_ellipse", "add_cloud", "add_line", "arrow",
              "add_polyline", "add_polygon", "calibrate", "measure_length",
              "measure_polylength", "measure_wall", "measure_area",
              "measure_cutout",
              "measure_volume", "measure_angle", "measure_radius",
              "measure_diameter", "viewport", "callout", "crop",
              "trace_outline"}
SNAP_PX = 10                 # snap distance, screen pixels

HINTS = {
    "select": "Click a markup to select it; drag to move; Delete removes; "
              "double-click to edit; right-click for options",
    "rect": "Drag a box",
    "line": "Drag from start to end (snaps to the drawing; Shift = "
            "straight; hold Alt to place freely)",
    "points": "Click each point; double-click or Enter to finish, "
              "Backspace removes the last point (Shift = straight, "
              "Alt = no snap)",
    "pen": "Draw with the mouse",
    "click": "Click on the page",
    "text": "Drag across the words to select them (start off the text to "
            "box an area); double-click a word; Ctrl+C copies, Ctrl+A "
            "selects all the text on the page",
}

TEXT_MARKUP = {"add_highlight", "add_underline", "add_strike"}


def _qcolor(c, alpha=255):
    return QColor(int(c[0] * 255), int(c[1] * 255), int(c[2] * 255), alpha)


def _circle(tool, a, b):
    """Center and radius (screen units) of the radius/diameter preview."""
    d = abs(b - a)
    if tool == "measure_radius":
        return a, d
    return fitz.Point((a.x + b.x) / 2, (a.y + b.y) / 2), d / 2


def takeoff_angle(pts):
    return takeoff.angle(pts)


def _inside(pt, verts):
    """Point-in-polygon (ray casting)."""
    x, y, inside = pt.x, pt.y, False
    j = len(verts) - 1
    for i in range(len(verts)):
        xi, yi, xj, yj = verts[i].x, verts[i].y, verts[j].x, verts[j].y
        if (yi > y) != (yj > y) and \
                x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi:
            inside = not inside
        j = i
    return inside



class _SnapRelay(QObject):
    """Carries a snap lookup built on a background thread to the window."""
    ready = Signal(object)


# Venice #17 (Nov 4): undo steps carry a name ("Undo Bulk Edit (412 items)")
_UNDO_WORDS = (("delete_annot", "Delete"), ("add_redact", "Redaction"),
               ("set_measure", "Edit Measurements"), ("move_annot", "Move"),
               ("set_vertices", "Reshape"), ("set_annot", "Edit"),
               ("import_annots", "Import Markups"))


def undo_name(kinds, n, given=None):
    """A short name for an undo step: the caller's, or one from the kinds
    of change, with the count when it's more than one."""
    if given:
        name = given
    else:
        name = next((w for k, w in _UNDO_WORDS if k in kinds), None)
        if name is None:
            name = "Add Markup" if any(str(k).startswith("add_")
                                       for k in kinds) else "Edit"
    return f"{name} ({n} items)" if n > 1 and "(" not in name else name

class PdfView(QWidget):
    """Shows one page and turns mouse drags into edits ("ops")."""

    page_changed = Signal(int)          # page edited (for thumbnails)
    status = Signal(str)                # short message for the status bar
    snapshot_taken = Signal(int, int, int)   # width, height px, dpi
    selection_changed = Signal()
    add_to_chest = Signal()             # "Add to Tool Chest" chosen
    count_resumed = Signal(str)         # "Add More to <count>" chosen
    crop_requested = Signal(object)     # rect in op coordinates
    zoom_requested = Signal(float, object)   # factor, widget point
    marquee_zoom = Signal(object)       # screen rect to zoom to
    rfi_requested = Signal()            # "Create RFI" on a markup
    view_menu = Signal(object)          # global point: right-click on paper
    want_tool = Signal(str)             # ask the window for a tool
    repeat_tool = Signal()              # Space: the last tool and item again
    number_key = Signal(int)            # 1-9: a Tool Chest tool (Nov 4)
    link_clicked = Signal(object)       # a link dict from page.get_links()
    redaction_failed = Signal(str)      # a redaction batch was rolled back

    def __init__(self, doc, path=None):
        super().__init__()
        self.doc = doc
        self._path = path
        self.page = 0
        self.zoom = 1.5
        self.rendered = None
        # tiled rendering: a light preview of the whole page, sharp tiles
        # for what's on screen (rendered from the page's display list)
        self._gen = 0
        self._dl = None
        self._full = True
        self._tiles = OrderedDict()
        self._size = (0, 0)
        self._want = []
        self._prefetched = OrderedDict()
        self._pf_pending = {}            # prefetch key -> drawing request
        self._tile_pending = set()       # tile keys asked of the process
        self._edits = 0
        self._pf_timer = QTimer(self)
        self._pf_timer.setSingleShot(True)
        self._pf_timer.timeout.connect(self._prefetch)
        self._tile_timer = QTimer(self)
        self._tile_timer.setSingleShot(True)
        self._tile_timer.timeout.connect(self._render_tiles)
        self.tool = None
        # current tool style; empty = each tool's defaults (Properties panel
        # and Tool Chest fill this in)
        self.style = {}
        self.count_group = "Count"
        self.dirty = False
        self.session = None
        self.on_change = None           # set by MainWindow
        self.recorder = Recorder()
        self.history = History(lambda: self.doc.tobytes(),
                               initial=self._base_bytes())
        from . import count_triage, snap_indicator
        count_triage.apply_undo_limit(self.history,
                                      settings.get("undo_limit", 200))
        self._snap_modes = snap_indicator.load_modes()
        self.measure_bar = None          # set by MainWindow (status bar)
        self._job_total = (None, 0.0)
        # interaction state (screen coordinates)
        self._drag = None               # (start, current)
        self._click_line = False        # first click of click-click line
        self._pts = []                  # points for polyline/area
        self._stroke = []               # pen stroke in progress
        self._mouse = None
        self._move = None               # (annot ref, original rect, start pt)
        self.selected = None            # {"ref":..., "rect": page Rect}
        # Nov 1: corners of the selected outline dragged to reshape it
        # ({"i", "mid", "pts" (screen), "cur"}), several markups selected
        # at once (refs; the last one is also self.selected) and the box
        # being dragged to select them
        self._vdrag = None
        self.multi = []
        self._band = None
        self.ghosts = []                 # copies previewed (measure_tools)
        self.isolate = None              # Show Only This Item: its group
        self.color_by = None             # "item" / "status" / "priced"
        self._mpan = None                # wheel-button pan in progress
        # copies of a count's symbol not counted yet, drawn as orange
        # boxes: {"page", "group", "hits"}; the missed copy being searched
        self.uncounted = None
        self.missed_group = None
        self.search_hits = []           # screen rects on this page
        self.text_sel = None            # {"page", "idx"}: selected words
        self._tdrag = None              # (start point, start word) dragging
        self._twords = None             # ((doc id, page), words) cache
        # pre-bid: outline markups that aren't priced, excluded or RFI'd
        self.show_unpriced = False
        self._unpriced = None           # (page, version) -> [page rects]
        self.search_current = None
        self._remote = None
        self._last_cursor = 0.0
        self._pg_cache = None
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.snap_enabled = settings.get("snap", True) is not False
        self._snap_cache = None          # ((doc id, page, rotation), index)
        self._snap_marks = None          # markup vertices on this page
        self._snap_hit = None            # (point, kind) under the cursor
        self._rzoom = None               # right-drag zoom box (start, end)
        self._render()

    @property
    def color(self):
        return self.style.get("color")

    @color.setter
    def color(self, value):
        if value is None:
            self.style.pop("color", None)
        else:
            self.style["color"] = list(value)

    # ---- basics ---------------------------------------------------------------
    @property
    def pg(self):
        """The current page. Cached, because annotations become unusable
        once the Page object they came from is garbage-collected."""
        c = self._pg_cache
        if c is None or c[0] is not self.doc or c[1] != self.page:
            c = self._pg_cache = (self.doc, self.page, self.doc[self.page])
        return c[2]

    def links(self):
        """This page's links (cached until the page is redrawn)."""
        c = getattr(self, "_links", None)
        if c is None or c[0] != (id(self.doc), self.page, self._gen):
            try:
                lst = self.pg.get_links()
            except Exception:
                lst = []
            c = self._links = ((id(self.doc), self.page, self._gen), lst)
        return c[1]

    def link_at(self, pt):
        for ln in self.links():
            if (fitz.Rect(ln["from"]) + (-1, -1, 1, 1)).contains(pt):
                return ln
        return None

    def reset_page_cache(self):
        if hasattr(self, "_prefetched"):
            self._pf_forget()
        self._links = None
        self._pg_cache = None
        self._snap_cache = None
        self._snap_local = None
        self._trace_cache = None
        self._content = None
        self._content_raster = None

    # ---- snapping ---------------------------------------------------------------
    def set_snap(self, on):
        self.snap_enabled = bool(on)
        settings.set("snap", self.snap_enabled)
        self._snap_hit = None
        self.update()

    def _warm_snap(self):
        """Build the page's snap index while the user is looking, not at
        their first click (it takes a moment on a dense sheet)."""
        import time
        from .panels import _busy_until
        try:
            if self._snap_cache is not None or not self.snap_enabled or \
                    not self.isVisible():
                return
        except RuntimeError:              # the view is gone
            return
        if time.monotonic() < _busy_until[0]:
            QTimer.singleShot(400, self._warm_snap)
            return
        self.snap_index()

    def _snap_from_process(self, key):
        """Read the page's lines in the drawing process and build the snap
        lookup on a background thread: on the heaviest sheets this took
        3.5 s in the window (sheet 215 of the plant set, 250,000 lines).
        True if it was handed off."""
        drawer = self._drawer()
        if drawer is None:
            return False
        from . import render_worker
        try:
            sig = render_worker.page_sig(self.doc, self.page)
            clip = snap.page_clip(self.pg)
        except Exception:
            return False
        rid = drawer.segments(self._path, self.page, sig,
                              lambda m, k=key, c=clip: self._snap_segs(m, k, c))
        if rid is None:
            return False
        self._snap_building = key
        return True

    def _snap_segs(self, msg, key, clip):
        if not self._doc_open() or msg is None or msg[0] != "segs" or \
                (msg[3] == 0 and not self._sig_ok(key[1], msg)):
            # the process can't help with this page (unsaved page edits,
            # an error): build it here, as before
            self._snap_building = None
            self._snap_local = key
            return
        data = msg[4]
        relay = _SnapRelay()
        relay.ready.connect(lambda idx, k=key, r=relay:
                            self._snap_ready(k, idx, r))
        self._snap_relays = getattr(self, "_snap_relays", set())
        self._snap_relays.add(relay)

        def work():
            from array import array
            a = array("d")
            a.frombytes(data)
            segs = [((a[i], a[i + 1]), (a[i + 2], a[i + 3]))
                    for i in range(0, len(a), 4)]
            try:
                idx = snap.SnapIndex(segs, clip=clip)
            except Exception:
                snap.log.exception("snap index (background)")
                idx = snap.SnapIndex([])
            try:
                relay.ready.emit(idx)
            except RuntimeError:
                pass
        threading.Thread(target=work, name="snap-index", daemon=True).start()

    def _snap_ready(self, key, idx, relay):
        getattr(self, "_snap_relays", set()).discard(relay)
        if getattr(self, "_snap_building", None) == key:
            self._snap_building = None
        try:
            cur = (id(self.doc), self.page, self.pg.rotation)
        except Exception:
            return
        if key == cur:
            self._snap_cache = (key, idx)
            self._snap_marks = None
            self.update()

    def snap_index(self):
        key = (id(self.doc), self.page, self.pg.rotation)
        if (self._snap_cache is None or self._snap_cache[0] != key) and \
                getattr(self, "_snap_building", None) == key:
            # being built in the background: measure without snapping for
            # the moment rather than freezing the window
            idx = snap.SnapIndex([])
            if self._snap_marks is None:
                try:
                    self._snap_marks = snap.markup_points(self.pg)
                except Exception:
                    self._snap_marks = []
            idx.points = self._snap_marks
            return idx
        if (self._snap_cache is None or self._snap_cache[0] != key) and \
                getattr(self, "_snap_local", None) != key and \
                self._snap_from_process(key):
            return self.snap_index()
        if self._snap_cache is None or self._snap_cache[0] != key:
            try:
                idx = snap.SnapIndex(snap.page_segments(self.pg),
                                     clip=snap.page_clip(self.pg))
            except Exception:
                snap.log.exception("snap index for page %d", self.page)
                idx = snap.SnapIndex([])
            self._snap_cache = (key, idx)
            self._snap_marks = None
        idx = self._snap_cache[1]
        if self._snap_marks is None:
            try:
                self._snap_marks = snap.markup_points(self.pg)
            except Exception:
                self._snap_marks = []
        idx.points = self._snap_marks
        return idx

    def snap_point(self, pt, anchor=None, shift=False, alt=False):
        """Where a click at screen point `pt` lands for the current tool:
        Shift = straight line (0/45/90 degrees) from `anchor`, otherwise
        snapped to the drawing unless snapping is off or Alt is held."""
        self._snap_hit = None
        if self.tool not in SNAP_TOOLS:
            return pt
        if self.tool == "trace_outline":
            return self._trace_snap(pt, anchor, shift, alt)
        if shift and anchor is not None:
            return snap.ortho(anchor, pt)
        if self.snap_enabled and not alt:
            from . import snap_indicator
            idx = self.snap_index()
            r = SNAP_PX / self.zoom
            segs = None
            if anchor is not None and "PERP" in self._snap_modes:
                segs = [idx.segs[i] for i in
                        list(idx.near(pt.x, pt.y, r))[:600]]
            q, kind = snap_indicator.resolve(pt, anchor, idx, r,
                                             self._snap_modes, segs=segs)
            if kind:
                self._snap_hit = (q, kind)
                return q
        return pt

    def _event_point(self, e):
        anchor = self._drag[0] if self._drag else (
            self._pts[-1] if self._pts else None)
        mods = e.modifiers()
        return self.snap_point(self._sp(e.position()), anchor,
                               bool(mods & Qt.ShiftModifier),
                               bool(mods & Qt.AltModifier))

    def wheelEvent(self, e):
        """Ctrl + wheel zooms at the cursor; plain wheel scrolls (the
        scroll area does that)."""
        if e.modifiers() & Qt.ControlModifier:
            dy = e.angleDelta().y()
            if dy:
                self.zoom_requested.emit(1.15 ** (dy / 120),
                                         e.position().toPoint())
            e.accept()
            return
        e.ignore()

    def leaveEvent(self, e):
        if self._snap_hit:
            self._snap_hit = None
            self.update()
        super().leaveEvent(e)

    def _paint_snap(self, p):
        """A coloured box with END / MID / EDGE / INT / PERP / GRID where
        the cursor snapped (snap_indicator)."""
        if not self._snap_hit or self.tool not in SNAP_TOOLS:
            return
        from . import snap_indicator
        pt, kind = self._snap_hit
        snap_indicator.paint(p, self._q(pt), kind)

    # ---- measurement bar (status bar; measure_bar) ------------------------------
    BAR_TOOLS = {"measure_length": "length", "measure_polylength": "length",
                 "measure_wall": "length",
                 "measure_area": "area", "measure_cutout": "area",
                 "measure_volume": "area", "count": "count",
                 "trace_outline": "area"}

    def _bar_cal(self, ppts):
        sc = self.scale(at=ppts or None) if ppts else self.scale()
        if not sc or not sc.get("ppu"):
            return None, None
        cal = takeoff.Calibration.__new__(takeoff.Calibration)
        cal.points_per_unit, cal.unit = sc["ppu"], sc.get("unit", "ft")
        return cal, cal.unit

    def _bar_points(self):
        """The measurement in progress, screen points: a click-click or
        dragged line, or the placed points plus the cursor."""
        if self._drag:
            return [self._drag[0], self._drag[1]]
        return list(self._pts) + ([self._mouse] if self._mouse and
                                  self._pts else [])

    def update_measure_bar(self):
        bar = self.measure_bar
        mode = self.BAR_TOOLS.get(self.tool)
        if bar is None or mode is None:
            return
        from . import measure_bar
        pts = self._bar_points()
        ppts = [annotate.to_page(self.pg, q) for q in pts]
        cal, unit = self._bar_cal(ppts)
        key = (id(self.doc), self._gen, mode, unit)
        if self._job_total[0] != key:
            try:
                tot = measure_bar.job_total(self.doc, mode, None)
            except Exception:
                tot = None
            self._job_total = (key, tot)
        tot = self._job_total[1]
        if mode == "count":
            val = len(ppts)
        else:
            val = measure_bar.live(ppts, cal, mode)
        bar.set_live(mode, val, unit or "ft", tot)

    def bar_commit(self, value):
        """A length typed in the bar: the segment being drawn ends that far
        along the cursor's direction."""
        pts = self._bar_points()
        if len(pts) < 2:
            self.status.emit("Click the start point first, then type the "
                             "length.")
            return False
        ppts = [annotate.to_page(self.pg, q) for q in pts]
        cal, _unit = self._bar_cal(ppts)
        if cal is None:
            self.status.emit("No scale on this page - use Set Scale first.")
            return False
        from . import measure_bar
        bar = getattr(self, "measure_bar", None)
        angle = getattr(bar, "angle", None) if bar is not None else None
        if bar is not None:
            bar.angle = None
        end = measure_bar.set_segment(pts, value, cal, angle)[-1]
        if self._drag:
            a = self._drag[0]
            self._drag, self._click_line = None, False
            self.commit_line(self.tool, a, end)
        else:
            self._pts.append(end)
            self._mouse = end
        self.update()
        self.update_measure_bar()
        return True

    def bar_add(self):
        """"Add to takeoff": finish what is being drawn."""
        if self._pts:
            self._finish_points()
        elif self._drag and self._click_line:
            a, b = self._drag
            self._drag, self._click_line = None, False
            self.commit_line(self.tool, a, b)
        self.update()

    def bar_cancel(self):
        self._pts, self._drag, self._stroke = [], None, []
        self._click_line = False
        self.update()
        self.setFocus()

    def _with_markups(self, pg, base, z):
        """`base` (the page's drawing, no markups) with the markups and form
        fields drawn on a copy - what get_pixmap gives, without redrawing
        the drawing."""
        mu = fitz.mupdf
        out = fitz.Pixmap(base, 0)
        dev = mu.fz_new_draw_device(mu.FzMatrix(), out.this)
        try:
            ctm = mu.FzMatrix(z, 0, 0, z, 0, 0)
            fzpage = pg.this if isinstance(pg.this, mu.FzPage) else \
                mu.FzPage(pg.this)
            mu.fz_run_page_annots(fzpage, dev, ctm, mu.FzCookie())
            mu.fz_run_page_widgets(fzpage, dev, ctm, mu.FzCookie())
        finally:
            mu.fz_close_device(dev)
        return out

    def _page_pixmap(self, pg, pz, annots_only):
        from .render_opts import screen
        with screen():
            return self._page_pixmap_raw(pg, pz, annots_only)

    def _page_pixmap_raw(self, pg, pz, annots_only):
        """The page at zoom `pz`. After a markup-only change the drawing
        underneath is reused from the last render and only the markups are
        redrawn."""
        key = (id(self.doc), self.page, pg.rotation, round(pz, 6))
        cr = getattr(self, "_content_raster", None)
        if annots_only and cr is not None and cr[0] == key:
            try:
                return self._with_markups(pg, cr[1], pz)
            except Exception:
                log.debug("layered render failed", exc_info=True)
        try:
            base = pg.get_pixmap(matrix=fitz.Matrix(pz, pz), alpha=False,
                                 annots=False)
            self._content_raster = (key, base)
            return self._with_markups(pg, base, pz)
        except Exception:
            log.debug("layered render failed", exc_info=True)
            self._content_raster = None
            return pg.get_pixmap(matrix=fitz.Matrix(pz, pz), alpha=False)

    def _render(self, zoom_only=False, annots_only=False):
        self._pg_cache = None
        self._snap_marks = None
        if self.doc.page_count == 0:
            self.rendered = None
            self.update()
            return
        self.page = max(0, min(self.page, self.doc.page_count - 1))
        pg = self.pg
        key = (id(self.doc), self.page, pg.rotation)
        same = zoom_only and getattr(self, "_content", None) == \
            (key, self._gen)
        if not same:
            self._gen += 1
            self._dl = None
            self._tile_pending.clear()
            self._tiles.clear()           # zoom-only: tiles of other zooms
                                          # stay for zooming back
        full = (pg.rect * fitz.Matrix(self.zoom, self.zoom)).irect
        W, H = max(1, full.width), max(1, full.height)
        side = max(pg.rect.width, pg.rect.height) or 1
        # Render in device pixels: with Windows display scaling at 125 or
        # 150% a logical-pixel image would be stretched by the system and
        # drawings would look soft and jagged.
        dpr = self._dpr()
        pz = min(self.zoom * dpr, self.PREVIEW_PX * dpr / side)
        self._full = pz >= self.zoom * dpr - 1e-9
        prev = getattr(self, "_preview", None)
        if prev is not None and prev[1] is None:
            # the sheet is still blank, waiting for the drawing process:
            # nothing to scale, so draw (or ask) at this zoom (review
            # 0.12.12 S1: zooming then crashed on None.width())
            prev = self._preview = None
        if same and prev is not None and abs(prev[0] - pz) < 1e-9:
            pix_w = round(prev[1].width() / dpr)
            pix_h = round(prev[1].height() / dpr)
            self.rendered = prev[1]       # zooming past the preview size:
        elif same and prev is not None:   # keep it, only tiles change
            # zoomed below the preview size: show the preview scaled at
            # once and let sharp tiles come in (no full redraw per step)
            self.rendered = prev[1]
            self._full = False
            pix_w, pix_h = W, H
        else:
            hit = None if annots_only else \
                self._prefetched.get(self._pf_key(self.page, pz))
            if hit is not None:
                # the page was drawn ahead of time while you were reading
                # the one before: turning to it is instant
                self.rendered, pw, ph = hit
                self._content_raster = None
            elif not annots_only and self._page_async(pz, dpr):
                # a page that wasn't drawn ahead (a jump, a zoom change):
                # show the blank sheet at once, the drawing process fills
                # it in - the window doesn't wait (up to 1.2 s on the
                # plant set)
                self.rendered = None
                self._content_raster = None
                pw, ph = round(W * dpr), round(H * dpr)
            else:
                pix = self._page_pixmap(pg, pz, annots_only)
                img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                             QImage.Format_RGB888).copy()
                self.rendered = QPixmap.fromImage(img)
                self.rendered.setDevicePixelRatio(dpr)
                pw, ph = pix.width, pix.height
                self._pf_store(self._pf_key(self.page, pz),
                               (self.rendered, pw, ph))
            pix_w, pix_h = round(pw / dpr), round(ph / dpr)
            self._preview = (pz, self.rendered) if self.rendered is not None \
                else None
            self._pf_timer.start(120)
        self._content = (key, self._gen)
        self._size = (W, H) if not self._full else (pix_w, pix_h)
        self.setFixedSize(*self._size)
        if self.snap_enabled and self._snap_cache is None:
            QTimer.singleShot(400, self._warm_snap)
        self._refresh_selection()
        ctl = getattr(self, "editctl", None)
        if ctl is not None:
            ctl.refresh()
        self.update()
        self._changed()

    # ---- pages drawn ahead (page turns without waiting) ----------------
    PREFETCH_KEEP = 6

    def _pf_key(self, page, pz):
        try:
            rot = self.doc[page].rotation
        except Exception:
            rot = 0
        return (id(self.doc), page, rot, round(pz, 5), self._edits)

    def _pf_store(self, key, val):
        self._prefetched[key] = val
        self._prefetched.move_to_end(key)
        while len(self._prefetched) > self.PREFETCH_KEEP:
            self._prefetched.popitem(last=False)

    def _pf_forget(self):
        """Something changed: pages drawn ahead may be out of date."""
        self._edits += 1
        self._prefetched.clear()
        self._drop_pending()

    def _drop_pending(self, keep=None):
        """Tell the drawing process we no longer want these (review M2,
        Grok M10). `keep(key)` spares the ones still wanted."""
        drop = {k: rid for k, rid in self._pf_pending.items()
                if keep is None or not keep(k)}
        if drop:
            try:
                from . import render_worker
                w = render_worker._worker
                if w is not None:
                    w.forget_many(list(drop.values()))
            except Exception:
                pass
        for k in drop:
            self._pf_pending.pop(k, None)

    def stop_timers(self):
        """Stop every timer of this view (closing the tab): a prefetch or
        tile render firing after the document closed raised "document
        closed" (Grok r5 #5)."""
        from PySide6.QtCore import QTimer as _T
        for t in self.findChildren(_T):
            t.stop()
        self._drop_pending()           # the tab is closing: draw nothing

    def _doc_open(self):
        return self.doc is not None and not getattr(self.doc, "is_closed",
                                                    False)

    # ---- the drawing process (Stage 4) -----------------------------------
    def _drawer(self):
        """The drawing process, when this tab can use it: the document came
        from a file (the process opens the same file)."""
        if not self._path or not self._doc_open():
            return None
        from . import render_worker
        if not render_worker.ENABLED:
            return None
        w = render_worker.get()
        return w if w.start() else None

    def _base_from(self, msg):
        """The sheet the drawing process sent, as a pixmap (or None)."""
        if not msg or msg[0] != "img" or not msg[5]:
            return None
        _, _, _, x, y, w, h, stride, data = msg
        if stride != w * 3:
            return None
        base = fitz.Pixmap(fitz.csRGB, w, h, data, 0)
        base.set_origin(x, y)
        return base

    def _sig_ok(self, p, msg):
        from . import render_worker
        try:
            return tuple(msg[2]) == render_worker.page_sig(self.doc, p)
        except Exception:
            return False

    def _page_async(self, pz, dpr):
        """Ask the drawing process for the page on screen. True if it will
        come (the page shows blank until then)."""
        if getattr(self, "_local_page", None) == self._pf_key(self.page, pz):
            return False                 # it couldn't: draw it here
        key = self._pf_key(self.page, pz)
        if key in self._pf_pending:
            return True                  # already on its way (drawn ahead)
        drawer = self._drawer()
        if drawer is None:
            return False
        from . import render_opts, render_worker
        try:
            sig = render_worker.page_sig(self.doc, self.page)
        except Exception:
            return False
        p = self.page
        rid = drawer.render(self._path, p, pz, None,
                            render_opts.STATE["thin_lines"], sig,
                            lambda m, k=key, p=p, pz=pz, d=dpr:
                                self._pf_reply(m, k, p, pz, d))
        if rid is None:
            return False
        self._pf_pending[key] = rid
        return True

    def _waiting_here(self, key, p):
        """The page on screen is blank, waiting for this reply."""
        try:
            return self.rendered is None and p == self.page and \
                self._doc_open()
        except RuntimeError:
            return False

    def _pf_reply(self, msg, key, p, pz, dpr):
        self._pf_pending.pop(key, None)
        if not self._doc_open() or key != self._pf_key(p, pz):
            if self._waiting_here(key, p):
                self._render()           # edited meanwhile: ask again
            return                       # page edited or rotated since
        base = self._base_from(msg)
        if base is None or not self._sig_ok(p, msg):
            if self._waiting_here(key, p):
                self._local_page = key   # draw this one in the window
                self._render()
            return                       # the page turn draws it itself
        try:
            pix = self._with_markups(self.doc[p], base, pz)
        except Exception:
            log.debug("markups on a drawn-ahead page failed", exc_info=True)
            return
        img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                     QImage.Format_RGB888).copy()
        qp = QPixmap.fromImage(img)
        qp.setDevicePixelRatio(dpr)
        self._pf_store(key, (qp, pix.width, pix.height))
        if self._waiting_here(key, p):
            self._render()               # the blank sheet: show it now

    def _prefetch(self):
        """Draw the next (then the previous) page while idle - in the
        drawing process when there is one, so the window never waits."""
        if not self._doc_open():
            return
        if self.doc.page_count < 2 or QApplication.mouseButtons():
            return
        dpr = self._dpr()
        drawer = self._drawer()
        for p in (self.page + 1, self.page - 1):
            if not 0 <= p < self.doc.page_count:
                continue
            pg = self.doc[p]
            side = max(pg.rect.width, pg.rect.height) or 1
            pz = min(self.zoom * dpr, self.PREVIEW_PX * dpr / side)
            key = self._pf_key(p, pz)
            if key in self._prefetched or key in self._pf_pending:
                continue
            if drawer is not None:
                from . import render_opts, render_worker
                try:
                    sig = render_worker.page_sig(self.doc, p)
                except Exception:
                    sig = None
                rid = drawer.render(
                    self._path, p, pz, None,
                    render_opts.STATE["thin_lines"], sig,
                    lambda m, k=key, p=p, pz=pz, d=dpr:
                        self._pf_reply(m, k, p, pz, d))
                if rid is not None:
                    self._pf_pending[key] = rid
                    continue             # both neighbours go at once
            from .render_opts import screen
            try:
                with screen():
                    base = pg.get_pixmap(matrix=fitz.Matrix(pz, pz),
                                         alpha=False, annots=False)
                    pix = self._with_markups(pg, base, pz)
            except Exception:
                try:
                    pix = pg.get_pixmap(matrix=fitz.Matrix(pz, pz),
                                        alpha=False)
                except Exception:
                    return
            img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                         QImage.Format_RGB888).copy()
            qp = QPixmap.fromImage(img)
            qp.setDevicePixelRatio(dpr)
            self._pf_store(key, (qp, pix.width, pix.height))
            self._pf_timer.start(30)         # one page per idle moment
            return

    def _dpr(self):
        try:
            d = float(self.devicePixelRatioF())
        except Exception:
            d = 1.0
        return d if d > 0 else 1.0

    def event(self, e):
        # Tab while drawing a run or an area: the next segment is an arc
        # (Nov 4 takeoff list #5). Tab would otherwise move the focus.
        if e.type() == QEvent.KeyPress and e.key() == Qt.Key_Tab and \
                self._pts and TOOLS.get(self.tool, ("", ""))[1] == "points":
            self.toggle_arc()
            return True
        # A / D on a selected AI markup accept / deny it (Nov 1): take the
        # key before the window's single-key tool shortcuts do
        if e.type() == QEvent.ShortcutOverride and \
                e.key() in (Qt.Key_A, Qt.Key_D) and \
                not (e.modifiers() & ~Qt.KeypadModifier) and \
                not self._pts and self.ai_open_refs():
            e.accept()
            return True
        # moved to a screen with different scaling: redraw at its pixels
        if e.type() == QEvent.DevicePixelRatioChange:
            self._tiles.clear()
            self._preview = None
            QTimer.singleShot(0, self._render)
        return super().event(e)

    def _changed(self):
        annotate.bump_edits(self.doc)
        if self.on_change:
            self.on_change()

    def _sp(self, pos):
        """Widget position -> point on the page as displayed (screen)."""
        return fitz.Point(pos.x() / self.zoom, pos.y() / self.zoom)

    def _q(self, obj):
        """Screen coordinates -> widget coordinates."""
        z = self.zoom
        if isinstance(obj, fitz.Rect):
            return QRectF(obj.x0 * z, obj.y0 * z, obj.width * z,
                          obj.height * z)
        return QPointF(obj.x * z, obj.y * z)

    def paint_remote_cursor(self, page, x, y):
        self._remote = (page, x, y)
        self.update()

    # tools whose half-drawn shape is kept on a tool switch (r42 F01). Not
    # cut-outs (they subtract from an area), angles, traces of other kinds
    # or any non-drawing mode; Escape still throws a shape away (Chief Q3)
    KEEP_ON_SWITCH = {"add_polyline": 2, "measure_polylength": 2,
                      "measure_wall": 2,
                      "add_polygon": 3, "measure_area": 3,
                      "measure_volume": 3, "trace_outline": 3}

    def set_tool(self, tool):
        need = self.KEEP_ON_SWITCH.get(self.tool)
        if tool != self.tool and need and len(self._pts) >= need:
            # a shape drawn but not yet added (no double-click / Enter /
            # "Add to takeoff") is added, not thrown away, when another
            # tool is picked (GUI user test r42 F01: a finished-looking
            # area vanished on switching to Count)
            try:
                self._finish_points()
            except Exception:                             # noqa: BLE001
                log.warning("pending shape not added", exc_info=True)
        self.tool = tool
        self._drag = None
        self._pts = []
        self._stroke = []
        if tool is not None:
            self.select(None)
        if tool != "select_text":
            self.clear_text_selection(quiet=True)
        self._twords = None             # the text may have been edited
        self.setCursor(Qt.ArrowCursor if tool is None else
                       Qt.IBeamCursor if tool == "select_text" else
                       Qt.CrossCursor)
        # Edit Text works in place, Acrobat-style (app/textedit.py)
        ctl = getattr(self, "editctl", None)
        if tool == "edit_text":
            if ctl is None:
                from .textedit import EditController
                ctl = self.editctl = EditController(self)
            ctl.activate()
        elif ctl is not None:
            ctl.deactivate()
        self.update()
        self._changed()
        win = self.window()
        sync = getattr(win, "_sync_tool_chest", None)
        if sync is not None and win is not self:
            sync()
        # Properties names the tool at once, whoever picked it (Chief's
        # user test, Nov 6: it said "Tool: Select" with Length active)
        props = getattr(win, "properties", None) if win is not self else None
        if props is not None and getattr(props, "view", None) is self:
            try:
                props.refresh()
            except Exception:                             # noqa: BLE001
                log.warning("properties refresh failed", exc_info=True)

    def set_mode(self, mode):            # older name
        self.set_tool(mode)

    @property
    def _mode(self):                     # older name
        return self.tool

    def hint(self):
        if self.tool == "auto_area":
            return ("Click inside a room: its floor area is traced along "
                    "the walls (Takeoff > Auto Takeoff Rooms does the "
                    "whole sheet)")
        if self.tool == "trace_outline":
            return ("Click along the drawn outline: clicks land on its "
                    "corners and edges, and a click further along the same "
                    "line adds the corners in between (Ctrl+click = "
                    "straight, Alt = free point); click the first point, "
                    "double-click or Enter to finish")
        if self.tool == "trace_length":
            return ("Click a drawn line: its whole connected run is "
                    "measured, through corners, to where it ends or "
                    "branches")
        special = {
            "measure_angle": "Click three points: one end, the corner, "
                             "the other end",
            "measure_radius": "Drag from the center to the edge",
            "measure_diameter": "Drag across the circle",
            "measure_volume": "Click the outline, double-click to finish, "
                              "then enter the depth",
            "measure_wall": "Click along the wall, double-click to finish, "
                            "then enter its height and any openings",
            "viewport": "Drag a box around a detail drawn at a different "
                        "scale",
            "legend": "Drag a box where the legend goes",
            "symbol_sample": "Drag a box around one sample symbol, then "
                             "name it in Count Several Symbols",
            "zoom": "Drag a box to zoom to it (or right-drag with any "
                    "tool); Alt+Left goes back"}
        if self.tool == "edit_text":
            return ("Click text to edit it in place · double-click empty "
                    "space to add text · click a picture to move, resize, "
                    "replace or delete it")
        if self.tool in special:
            return special[self.tool]
        return HINTS[TOOLS.get(self.tool, ("", "select"))[1]]

    # ---- painting --------------------------------------------------------------
    PREVIEW_PX = 2200            # longest side of the whole-page preview
    TILE = 512
    MAX_TILES = 120              # about 120 MB of sharp tiles

    def _tile(self, tx, ty):
        key = (self._gen, round(self.zoom, 4), tx, ty)
        pm = self._tiles.get(key)
        if pm is not None:
            self._tiles.move_to_end(key)
            return pm
        if self._dl is None:
            self._dl = self.pg.get_displaylist()
        z, t = self.zoom, self.TILE
        dpr = self._dpr()
        clip = fitz.Rect(tx * t / z, ty * t / z, (tx + 1) * t / z,
                         (ty + 1) * t / z) & self.pg.rect
        if clip.is_empty:
            return None
        from .render_opts import screen
        with screen():
            pix = self._dl.get_pixmap(matrix=fitz.Matrix(z * dpr, z * dpr),
                                      alpha=False, clip=clip)
        img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                     QImage.Format_RGB888).copy()
        qp = QPixmap.fromImage(img)
        qp.setDevicePixelRatio(dpr)
        # placed in widget (logical) pixels where the clip starts
        pm = (int(round(clip.x0 * z)), int(round(clip.y0 * z)), qp)
        self._tiles[key] = pm
        while len(self._tiles) > self.MAX_TILES:
            self._tiles.popitem(last=False)
        return pm

    def _paint_page(self, p, area):
        """The page under `area` (widget pixels): the preview, then sharp
        tiles when zoomed in past it."""
        if not self.rendered:
            if self._pf_pending:          # on its way from the drawing process
                p.setPen(QColor(150, 150, 150))
                vis = self.visibleRegion().boundingRect()
                p.drawText(vis if not vis.isEmpty() else self.rect(),
                           Qt.AlignCenter, "Drawing sheet…")
            return
        if self._full:
            d = self.rendered.devicePixelRatio() or 1.0
            p.drawPixmap(QRectF(area), self.rendered,
                         QRectF(area.x() * d, area.y() * d, area.width() * d,
                                area.height() * d))
            return
        W, H = self._size
        sx = self.rendered.width() / W
        sy = self.rendered.height() / H
        src = QRectF(area.x() * sx, area.y() * sy, area.width() * sx,
                     area.height() * sy)
        p.drawPixmap(QRectF(area), self.rendered, src)
        t = self.TILE
        missing = []
        for ty in range(max(0, area.top() // t), area.bottom() // t + 1):
            for tx in range(max(0, area.left() // t), area.right() // t + 1):
                tile = self._tiles.get((self._gen, round(self.zoom, 4), tx, ty))
                if tile is None:
                    missing.append((tx, ty))
                    continue
                self._tiles.move_to_end((self._gen, round(self.zoom, 4),
                                         tx, ty))
                p.drawPixmap(QPointF(tile[0], tile[1]), tile[2])
        if missing:
            # sharp tiles come in a moment later; the preview (scaled)
            # shows meanwhile, so zooming and panning never wait
            self._want = [(self._gen, round(self.zoom, 4), tx, ty)
                          for tx, ty in missing]
            if not self._tile_timer.isActive():
                self._tile_timer.start(0)

    def _tile_clip(self, tx, ty):
        z, t = self.zoom, self.TILE
        return fitz.Rect(tx * t / z, ty * t / z, (tx + 1) * t / z,
                         (ty + 1) * t / z) & self.pg.rect

    def _tile_reply(self, msg, key):
        self._tile_pending.discard(key)
        if not self._doc_open() or key[0] != self._gen or \
                key[1] != round(self.zoom, 4):
            return
        base = self._base_from(msg)
        if base is None or not self._sig_ok(self.page, msg):
            # drawing differs from the file (unsaved page edits): this
            # page's tiles are drawn in the window, as before
            self._tiles_here = self._gen
            self._want.append(key)
            if not self._tile_timer.isActive():
                self._tile_timer.start(0)
            return
        z, dpr = self.zoom, self._dpr()
        try:
            pix = self._with_markups(self.pg, base, z * dpr)
        except Exception:
            log.debug("markups on a tile failed", exc_info=True)
            pix = base
        img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                     QImage.Format_RGB888).copy()
        qp = QPixmap.fromImage(img)
        qp.setDevicePixelRatio(dpr)
        clip = self._tile_clip(key[2], key[3])
        pm = (int(round(clip.x0 * z)), int(round(clip.y0 * z)), qp)
        self._tiles[key] = pm
        while len(self._tiles) > self.MAX_TILES:
            self._tiles.popitem(last=False)
        self.update(QRect(pm[0], pm[1], int(qp.width() / dpr) + 1,
                          int(qp.height() / dpr) + 1))

    def _send_tiles(self):
        """Hand waiting tiles to the drawing process. False: draw here."""
        if getattr(self, "_tiles_here", None) == self._gen:
            return False
        drawer = self._drawer()
        if drawer is None:
            return False
        from . import render_opts, render_worker
        try:
            sig = render_worker.page_sig(self.doc, self.page)
        except Exception:
            return False
        z, dpr = self.zoom, self._dpr()
        while self._want:
            key = self._want.pop(0)
            if key[0] != self._gen or key[1] != round(z, 4) or \
                    key in self._tile_pending or key in self._tiles:
                continue
            clip = self._tile_clip(key[2], key[3])
            if clip.is_empty:
                continue
            rid = drawer.render(self._path, self.page, z * dpr,
                                tuple(clip), render_opts.STATE["thin_lines"],
                                sig, lambda m, k=key: self._tile_reply(m, k))
            if rid is None:
                self._want.insert(0, key)
                return False
            self._tile_pending.add(key)
        return True

    def _render_tiles(self):
        """Render waiting tiles for ~12 ms, then let the UI breathe."""
        import time
        if not self._doc_open():
            return
        if self._send_tiles():
            return
        end = time.perf_counter() + 0.012
        done = []
        while self._want and time.perf_counter() < end:
            key = self._want.pop(0)
            if key[0] != self._gen or key[1] != round(self.zoom, 4):
                continue
            try:
                tile = self._tile(key[2], key[3])
            except Exception:
                log.debug("tile render failed", exc_info=True)
                tile = None
            if tile:
                d = tile[2].devicePixelRatio() or 1.0
                done.append(QRect(tile[0], tile[1],
                                  int(tile[2].width() / d) + 1,
                                  int(tile[2].height() / d) + 1))
        for r in done:
            self.update(r)
        if self._want:
            self._tile_timer.start(0)

    # ---- selecting and copying the drawing's text (app/textsel.py) ----------
    def page_words(self):
        from . import textsel
        key = (id(self.doc), self.page)
        if self._twords is None or self._twords[0] != key:
            self._twords = (key, textsel.words(self.pg))
        return self._twords[1]

    def text_rects(self):
        """Screen rects of the selected text on this page."""
        ts = self.text_sel
        if not ts or ts.get("page") != self.page or not ts.get("idx"):
            return []
        from . import textsel
        ws = self.page_words()
        try:
            return [annotate.from_page(self.pg, r)
                    for r in textsel.rects(ws, ts["idx"])]
        except IndexError:
            return []

    def _text_press(self, pt, extend=False):
        from . import textsel
        ws = self.page_words()
        a = annotate.to_page(self.pg, pt)
        if not ws:
            self.text_sel = None
            self.status.emit("This page has no text to select - it is a "
                             "scan or a picture. Document > Make Searchable "
                             "(OCR) adds text you can copy.")
            self.update()
            return
        ts = self.text_sel
        if extend and ts and ts.get("page") == self.page and ts.get("idx") \
                and ts.get("start") is not None:
            self._tdrag = (ts["anchor"], ts["start"])     # Shift+click
        else:
            self._tdrag = (a, textsel.word_at(ws, a))
        self._text_drag(pt)

    def _text_drag(self, pt):
        from . import textsel
        a, start = self._tdrag
        b = annotate.to_page(self.pg, pt)
        ws = self.page_words()
        if start is None and abs(b - a) * self.zoom < 3:
            idx = []                         # a click off the text: clear
        else:
            idx = textsel.pick(ws, a, b, start)
        self.text_sel = {"page": self.page, "idx": idx, "anchor": a,
                         "start": start}
        self.update()

    def _text_status(self):
        n = len((self.text_sel or {}).get("idx") or [])
        if n:
            self.status.emit(f"{n} word{'s' if n != 1 else ''} selected - "
                             "Ctrl+C copies them.")

    def select_word_at(self, pt, switch=False):
        """Double-click on a word: select it. With `switch` (the Select
        tool) it also changes to Select Text. True when there was a word."""
        from . import textsel
        ws = self.page_words()
        i = textsel.word_at(ws, annotate.to_page(self.pg, pt), near=1.5)
        if i is None:
            return False
        if switch and self.tool != "select_text":
            self.set_tool("select_text")
        self.text_sel = {"page": self.page, "idx": [i],
                         "anchor": fitz.Point(ws[i][0], ws[i][1]),
                         "start": i}
        self._text_status()
        self.update()
        return True

    def select_all_text(self):
        ws = self.page_words()
        if not ws:
            self.status.emit("This page has no text to select - it is a "
                             "scan or a picture. Document > Make Searchable "
                             "(OCR) adds text you can copy.")
            return 0
        self.text_sel = {"page": self.page, "idx": list(range(len(ws))),
                         "anchor": fitz.Point(ws[0][0], ws[0][1]),
                         "start": 0}
        self._text_status()
        self.update()
        return len(ws)

    def selected_text(self):
        from . import textsel
        ts = self.text_sel
        if not ts or ts.get("page") != self.page or not ts.get("idx"):
            return ""
        try:
            return textsel.text_of(self.page_words(), ts["idx"])
        except IndexError:
            return ""

    def copy_text(self, page=False):
        """Copy the selected text (or, with `page`, all of this page's
        text) to the clipboard. Returns the text copied ("" = nothing)."""
        from . import textsel
        if page:
            ws = self.page_words()
            text = textsel.text_of(ws, range(len(ws)))
        else:
            text = self.selected_text() or self.selected_markup_text()
        if not text:
            if page or not self.page_words():
                self.status.emit("This page has no text to copy - it is a "
                                 "scan or a picture. Document > Make "
                                 "Searchable (OCR) adds text you can copy.")
            else:
                self.status.emit("Nothing selected: pick Select Text and "
                                 "drag across the words first.")
            return ""
        QApplication.clipboard().setText(text)
        self.status.emit(f"Copied {len(text.split())} words.")
        return text

    def selected_markup_text(self):
        """The words in the selected markup (a callout, text box or note),
        for Ctrl+C with a markup selected and no text selected."""
        if not self.selected or self.multi or self.text_sel:
            return ""
        try:
            for a in annotate.find_annots(self.pg, self.selected["ref"])[:1]:
                return (a.info.get("content") or "").strip()
        except Exception:                                 # noqa: BLE001
            return ""
        return ""

    def copy_table(self):
        """Copy the selected text as a table (tabs between columns, a line
        per row) so a schedule pastes into Excel cell by cell."""
        from . import textsel
        ts = self.text_sel
        if not ts or ts.get("page") != self.page or not ts.get("idx"):
            self.status.emit("Nothing selected: pick Select Text and box "
                             "the schedule first.")
            return ""
        rows = textsel.table(self.page_words(), ts["idx"])
        text = textsel.table_text(rows)
        if not text.strip():
            return ""
        QApplication.clipboard().setText(text)
        cols = max((len(r) for r in rows), default=0)
        self.status.emit(f"Copied a table: {len(rows)} rows x {cols} "
                         "columns - paste it into Excel.")
        return text

    def clear_text_selection(self, quiet=False):
        had = bool(self.text_sel)
        self.text_sel = None
        self._tdrag = None
        if had and not quiet:
            self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(e.rect(), QColor(255, 255, 255))
        self._paint_page(p, e.rect())
        # search results
        for r in self.search_hits:
            p.fillRect(self._q(r), QColor(255, 200, 0, 90))
        for r in self.text_rects():
            p.fillRect(self._q(r).adjusted(-1, -1, 1, 1),
                       QColor(0, 120, 215, 80))
        if self.show_unpriced:
            p.setPen(QPen(QColor(220, 0, 0), 2.5))
            p.setBrush(Qt.NoBrush)
            for r in self.unpriced_rects():
                q = annotate.from_page(self.pg, fitz.Rect(r))
                p.drawRect(self._q(q).adjusted(-4, -4, 4, 4))
        flash = getattr(self, "_snap_flash", None)
        if flash is not None:                  # a snapshot was just taken
            p.setPen(QPen(QColor(0, 120, 215), 3))
            p.setBrush(QColor(0, 120, 215, 60))
            p.drawRect(self._q(flash))
        if self.search_current is not None:
            p.setPen(QPen(QColor(255, 120, 0), 2))
            p.drawRect(self._q(self.search_current).adjusted(-2, -2, 2, 2))
        # selection
        uc = self.uncounted
        if uc and uc["page"] == self.page and uc["hits"]:
            p.setPen(QPen(QColor(255, 120, 0), 2))
            p.setBrush(QBrush(QColor(255, 140, 0, 50)))
            for h in uc["hits"]:
                r = annotate.from_page(self.pg, fitz.Rect(h["rect"]))
                p.drawRect(self._q(r).adjusted(-3, -3, 3, 3))
            p.setBrush(Qt.NoBrush)
        try:
            pm = annotate.page_multiplier(self.doc, self.page)
        except Exception:                                 # noqa: BLE001
            pm = 1
        if pm != 1:                           # a typical sheet: say so
            badge = f"  Typical sheet x{pm:g}  "
            p.setPen(QPen(QColor(255, 255, 255)))
            p.setBrush(QColor(0, 120, 215, 220))
            fm = p.fontMetrics()
            br = QRect(8, 8, fm.horizontalAdvance(badge) + 4, fm.height() + 6)
            p.drawRoundedRect(br, 4, 4)
            p.drawText(br, Qt.AlignCenter, badge)
            p.setBrush(Qt.NoBrush)
        if self.color_by:                     # Color Takeoff By (list #6)
            self._paint_color_by(p)
        if self.isolate is not None:          # Show Only This Item
            keep = self.isolate_rects()
            veil = QPainterPath()
            veil.addRect(QRectF(self.rect()))
            for r in keep:
                q = self._q(annotate.from_page(self.pg, fitz.Rect(r)))
                veil.addRect(QRectF(q.adjusted(-4, -4, 4, 4)))
            veil.setFillRule(Qt.OddEvenFill)
            p.fillPath(veil, QColor(255, 255, 255, 190))
            p.setPen(QPen(QColor(0, 120, 215), 2))
            p.setBrush(Qt.NoBrush)
            for r in keep:
                q = self._q(annotate.from_page(self.pg, fitz.Rect(r)))
                p.drawRect(q.adjusted(-4, -4, 4, 4))
        if getattr(self, "ghosts", None):     # copies about to be made
            p.setPen(QPen(QColor(0, 150, 80), 1.5, Qt.DashLine))
            p.setBrush(QBrush(QColor(0, 150, 80, 30)))
            for r in self.ghosts:
                p.drawRect(self._q(r))
            p.setBrush(Qt.NoBrush)
        self._paint_side_lengths(p)
        if self.multi:
            p.setPen(QPen(QColor(0, 120, 215), 1, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            for ref in self.multi:
                for a in annotate.find_annots(self.pg, ref)[:1]:
                    p.drawRect(self._q(annotate.from_page(
                        self.pg, fitz.Rect(a.rect))).adjusted(-3, -3, 3, 3))
        elif self.selected:
            r = annotate.from_page(self.pg, fitz.Rect(self.selected["rect"]))
            if self._move and self._mouse:
                d = self._mouse - self._move[2]
                r = r + (d.x, d.y, d.x, d.y)
            p.setPen(QPen(QColor(0, 120, 215), 1, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(self._q(r).adjusted(-3, -3, 3, 3))
            self._paint_handles(p)
        if self._band is not None:
            p.setPen(QPen(QColor(0, 120, 215), 1, Qt.DashLine))
            p.setBrush(QBrush(QColor(0, 120, 215, 25)))
            p.drawRect(self._q(fitz.Rect(*self._band).normalize()))
            p.setBrush(Qt.NoBrush)
        # previews
        pen = QPen(QColor(0, 120, 215), 1.5, Qt.DashLine)
        p.setPen(pen)
        kind = TOOLS.get(self.tool, ("", "select"))[1]
        self._paint_viewports(p)
        if self._rzoom is not None:
            p.setPen(QPen(QColor(0, 150, 80), 1.5, Qt.DashLine))
            p.setBrush(QBrush(QColor(0, 150, 80, 30)))
            p.drawRect(self._q(fitz.Rect(*self._rzoom).normalize()))
            p.setBrush(Qt.NoBrush)
        p.setPen(pen)
        if self._drag:
            a, b = self._drag
            if kind == "line":
                p.drawLine(self._q(a), self._q(b))
                if self.tool in ("measure_radius", "measure_diameter"):
                    c, r = _circle(self.tool, a, b)
                    p.drawEllipse(self._q(c), r * self.zoom, r * self.zoom)
                if self.tool in ("measure_length", "measure_radius",
                                 "measure_diameter"):
                    self._draw_live_value(p, b, [a, b])
            else:
                p.drawRect(self._q(fitz.Rect(a, b).normalize()))
        if self._pts:
            pts = self._pts + ([self._mouse] if self._mouse else [])
            path = QPainterPath(self._q(pts[0]))
            for q in pts[1:]:
                path.lineTo(self._q(q))
            if self.tool in ("measure_area", "measure_cutout",
                             "measure_volume", "add_polygon",
                             "trace_outline") and len(pts) > 2:
                path.closeSubpath()
                p.setBrush(QBrush(QColor(0, 120, 215, 40)))
            p.drawPath(path)
            p.setBrush(Qt.NoBrush)
            if self.tool in ("measure_polylength", "measure_wall",
                             "measure_area",
                             "measure_cutout", "measure_volume",
                             "measure_angle", "trace_outline") and \
                    self._mouse:
                self._draw_live_value(p, self._mouse, pts)
        if self._stroke:
            p.setPen(QPen(_qcolor(self._color("add_ink")), 2))
            path = QPainterPath(self._q(self._stroke[0]))
            for q in self._stroke[1:]:
                path.lineTo(self._q(q))
            p.drawPath(path)
        self._paint_snap(p)
        # collaborator's cursor
        if self._remote and self._remote[0] == self.page:
            _, rx, ry = self._remote
            p.setPen(QPen(QColor(255, 140, 0), 2))
            p.drawEllipse(QPointF(rx * self.zoom, ry * self.zoom), 5, 5)

    def _paint_side_lengths(self, p):
        """Each side's length on measurement outlines (Takeoff > Show Side
        Lengths: off / selected / all on the page). On screen only."""
        mode = settings.get("side_lengths", "off")
        if mode not in ("selected", "all") or self.doc is None:
            return
        from . import measure_tools
        try:
            shapes = measure_tools.shapes_for_sides(self, mode)
        except Exception:
            return
        f = p.font()
        f.setPointSizeF(7.5)
        p.setFont(f)
        fm = p.fontMetrics()
        for a in shapes:
            for mid, text in measure_tools.side_lengths(self, a):
                q = self._q(mid)
                br = fm.boundingRect(text)
                box = QRectF(q.x() - br.width() / 2 - 2,
                             q.y() - br.height() / 2 - 1,
                             br.width() + 4, br.height() + 2)
                p.fillRect(box, QColor(255, 255, 235, 230))
                p.setPen(QPen(QColor(60, 60, 60)))
                p.drawText(box, Qt.AlignCenter, text)

    def _paint_viewports(self, p):
        key = (self._gen, self.page)
        if getattr(self, "_vps", (None,))[0] != key:
            self._vps = (key, annotate.read_viewports(self.doc, self.page)
                         if self._vp_cache_ok() else [])
        vps = self._vps[1]
        if not vps:
            return
        p.setPen(QPen(QColor(140, 0, 200), 1, Qt.DashLine))
        p.setBrush(Qt.NoBrush)
        for vp in vps:
            r = self._q(annotate.from_page(self.pg, fitz.Rect(vp["rect"])))
            p.drawRect(r)
            text = f"{vp.get('name', '')}  {vp.get('label') or ''}".strip()
            p.drawText(r.topLeft() + QPointF(4, 12), text)

    def _vp_cache_ok(self):
        try:
            return self.doc.embfile_count() > 0
        except Exception:
            return False

    def _draw_live_value(self, painter, at, pts):
        ppts = [annotate.to_page(self.pg, q) for q in pts]
        if self.tool == "measure_angle":
            if len(ppts) < 3:
                return
            text = f"{takeoff_angle(ppts[:3]):.1f}\u00b0"
            scale = True
        else:
            scale = self.scale(at=ppts)
        if not scale:
            return
        if self.tool == "measure_angle":
            pass
        elif self.tool == "trace_outline":
            from . import trace_outline
            text = trace_outline.readout(ppts, scale["ppu"], scale["unit"],
                                         takeoff.fmt)
        elif self.tool in ("measure_area", "measure_cutout",
                           "measure_volume"):
            v = takeoff.polygon_area(ppts) / scale["ppu"] ** 2
            text = f"{_c2(v):,.2f} sq {scale['unit']}"
        elif self.tool in ("measure_radius", "measure_diameter"):
            v = takeoff.path_length(ppts) / scale["ppu"]
            text = ("R " if self.tool == "measure_radius" else "\u2300 ") + \
                takeoff.fmt(v, scale["unit"])
        else:
            v = takeoff.path_length(ppts) / scale["ppu"]
            text = takeoff.fmt(v, scale["unit"])
        painter.setPen(QPen(QColor(0, 0, 0)))
        pos = self._q(at) + QPointF(12, -8)
        rect = painter.fontMetrics().boundingRect(text)
        painter.fillRect(QRectF(pos.x() - 3, pos.y() - rect.height(),
                                rect.width() + 6, rect.height() + 4),
                         QColor(255, 255, 220))
        painter.drawText(pos, text)

    # ---- mouse --------------------------------------------------------------------
    # ---- pan with the wheel button (Nov 3, Jon) ------------------------------
    def _scroller(self):
        """The scroll area the page sits in, or None."""
        from PySide6.QtWidgets import QAbstractScrollArea
        w = self.parentWidget()
        while w is not None and not isinstance(w, QAbstractScrollArea):
            w = w.parentWidget()
        return w

    def _pan_start(self, e):
        sa = self._scroller()
        if sa is None:
            return False
        self._mpan = (e.globalPosition(), sa.horizontalScrollBar().value(),
                      sa.verticalScrollBar().value(), sa)
        self.setCursor(Qt.ClosedHandCursor)
        return True

    def _pan_move(self, e):
        start, h, v, sa = self._mpan
        d = e.globalPosition() - start
        sa.horizontalScrollBar().setValue(int(h - d.x()))
        sa.verticalScrollBar().setValue(int(v - d.y()))

    def _pan_end(self):
        self._mpan = None
        self.setCursor(Qt.ArrowCursor if self.tool is None else
                       Qt.CrossCursor)        # the tool's own cursor back

    def mousePressEvent(self, e):
        _mark_busy()
        if e.button() == Qt.MiddleButton:     # hold the wheel and drag: pan
            if self._pan_start(e):
                e.accept()
                return
        pt = self._sp(e.position())
        kind = TOOLS.get(self.tool, ("", "select"))[1]
        if e.button() == Qt.LeftButton and kind in ("rect", "line", "points"):
            pt = self._event_point(e)
        if e.button() == Qt.RightButton:
            if kind == "points" and self._pts:
                self._finish_points()
                return
            # right-drag = marquee zoom; a plain right-click opens a menu
            # when the button comes up (see mouseReleaseEvent)
            self._rzoom = (pt, pt)
            return
        if e.button() != Qt.LeftButton:
            return
        self.setFocus()
        if kind == "text":
            self._text_press(pt, extend=bool(e.modifiers() &
                                              Qt.ShiftModifier))
            return
        if kind == "select":
            ctrl = bool(e.modifiers() & Qt.ControlModifier)
            h = self.handle_at(pt) if self.selected and not self.multi \
                else None
            if h is not None:
                i, mid = h
                if ctrl and not mid:             # Ctrl+click a corner: drop it
                    self.remove_vertex(i)
                    return
                self._vdrag = {"i": i, "mid": mid, "cur": pt,
                               "pts": self._shape_points()}
                self.update()
                return
            a = self.annot_at(pt)
            ln = self.link_at(pt) if a is None else None
            if ln is not None and not ctrl:
                self.select(None)
                self.link_clicked.emit(ln)     # Ctrl+click selects instead
                return
            if ctrl and a is not None:
                self.select(a, add=True)        # add to / take out of a set
                return
            if a is None:
                self.select(None)
                self._band = (pt, pt)           # drag a box to select
                return
            if self.multi and any(annotate.ref(a) == r for r in self.multi):
                self.selected = {"ref": annotate.ref(a),
                                 "rect": list(a.rect), "type": a.type[1]}
            else:
                self.select(a)
            if a is not None and a.type[0] in annotate.MOVABLE \
                    and not self.multi:
                self._move = (self.selected["ref"], fitz.Rect(a.rect), pt)
        elif kind in ("rect", "line"):
            if kind == "line" and self._drag and self._click_line:
                # second click of a click-click measurement
                a = self._drag[0]
                self._drag, self._click_line = None, False
                self.commit_line(self.tool, a, pt)
                self.update()
                return
            self._drag = (pt, pt)
            self._click_line = False
        elif kind == "points":
            if self.tool == "trace_outline":
                self.trace_click(pt, follow=not (e.modifiers() &
                                                 Qt.ControlModifier))
            elif getattr(self, "arc_mode", False) and self._pts:
                self.arc_click(pt)
            else:
                self._pts.append(pt)
            if self.tool == "measure_angle" and len(self._pts) >= 3:
                self._finish_points()
                return
        elif kind == "pen":
            self._stroke = [pt]
        self.update()

    def mouseMoveEvent(self, e):
        if e.buttons():
            _mark_busy()
        if getattr(self, "_mpan", None) is not None:
            self._pan_move(e)
            return
        if self._rzoom is not None:
            self._rzoom = (self._rzoom[0], self._sp(e.position()))
            self.update()
            return
        if self._tdrag is not None:
            self._text_drag(self._sp(e.position()))
            return
        had_snap = self._snap_hit is not None
        pt = self._event_point(e) if self.tool in SNAP_TOOLS \
            else self._sp(e.position())
        self._mouse = pt
        if self.tool is None and not e.buttons():
            on = self.link_at(pt) is not None
            if on != getattr(self, "_on_link", False):
                self._on_link = on
                self.setCursor(Qt.PointingHandCursor if on else
                               Qt.ArrowCursor)
        if self._vdrag is not None:
            self._vdrag["cur"] = pt
        elif self._band is not None:
            self._band = (self._band[0], pt)
        if self._drag:
            self._drag = (self._drag[0], pt)
        elif self._stroke:
            self._stroke.append(pt)
        if self._drag or self._stroke or self._pts or self._move \
                or had_snap or self._snap_hit or self._vdrag is not None \
                or self._band is not None:
            self.update()
        if self.measure_bar is not None and self.tool in self.BAR_TOOLS:
            self.update_measure_bar()
        now = time.monotonic()
        if self.session and now - self._last_cursor > 0.05:
            self._last_cursor = now
            self.session.send_cursor(self.page, pt.x, pt.y)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MiddleButton and \
                getattr(self, "_mpan", None) is not None:
            self._pan_end()
            return
        if e.button() == Qt.RightButton and self._rzoom is not None:
            a, b = self._rzoom[0], self._sp(e.position())
            self._rzoom = None
            self.update()
            r = fitz.Rect(a, b).normalize()
            if r.width * self.zoom > 8 or r.height * self.zoom > 8:
                self.marquee_zoom.emit(r)
                return
            hit = self.annot_at(a)
            if hit is not None:
                if not (self.multi and annotate.ref(hit) in self.multi):
                    self.select(hit)            # keep a set when it's in it
                self._menu_pt = a               # where: Split Run here
                self._context_menu(e.globalPosition().toPoint())
            else:
                self._menu_pt = a           # where: Edit Text Here, RFI here
                self.view_menu.emit(e.globalPosition().toPoint())
            return
        if e.button() != Qt.LeftButton:
            return
        if self._tdrag is not None:
            self._text_drag(self._sp(e.position()))
            self._tdrag = None
            self._text_status()
            return
        kind = TOOLS.get(self.tool, ("", "select"))[1]
        pt = self._event_point(e) if self._drag and kind in ("rect", "line") \
            else self._sp(e.position())
        if self._vdrag is not None:
            vd, self._vdrag = self._vdrag, None
            d = pt - vd["pts"][vd["i"]] if not vd["mid"] else None
            if vd["mid"]:
                a, b = vd["pts"][vd["i"]], vd["pts"][(vd["i"] + 1) %
                                                     len(vd["pts"])]
                moved = abs(pt - (a + b) / 2) * self.zoom >= 3
            else:
                moved = abs(d) * self.zoom >= 2
            if moved:
                self.drag_vertex(vd["i"], pt, mid=vd["mid"])
            self.update()
            return
        if self._band is not None:
            a, b = self._band[0], pt
            self._band = None
            r = fitz.Rect(a, b).normalize()
            if r.width * self.zoom > 4 and r.height * self.zoom > 4:
                self.select_in_rect(r)
            self.update()
            return
        if self._move:
            ref, orig, start = self._move
            self._move = None
            d = annotate.to_page(self.pg, pt) - annotate.to_page(self.pg, start)
            if abs(d.x) > 1 or abs(d.y) > 1:
                self.move_selected(d.x, d.y)
            self.update()
            return
        if self._drag:
            a, b = self._drag
            if kind == "line" and not self._click_line and \
                    abs(b - a) * self.zoom < 4:
                # a click, not a drag: the next click sets the end point
                # (the way Bluebeam measures)
                self._click_line = True
                self._drag = (a, pt)
                self.status.emit("Click the end point (Esc to cancel).")
                self.update()
                return
            self._drag = None
            self.update()
            if kind == "rect":
                self.commit_rect(self.tool, fitz.Rect(a, b).normalize())
            elif kind == "line":
                self.commit_line(self.tool, a, b)
        elif self._stroke:
            stroke, self._stroke = self._stroke, []
            self.commit_stroke(stroke)
        elif kind == "click":
            self.commit_click(self.tool, pt)

    def mouseDoubleClickEvent(self, e):
        pt = self._sp(e.position())
        kind = TOOLS.get(self.tool, ("", "select"))[1]
        if kind == "points":
            self._finish_points()
            return
        if kind == "text":
            self.select_word_at(pt)
            return
        if kind != "select":
            return
        w = self.widget_at(pt)
        if w is not None:
            self.fill_field(w)
            return
        a = self.annot_at(pt)
        # double-click PDF text to edit it in place (Nov 4, fewer clicks);
        # with the Select Text tool (I) a double-click still picks a word
        if a is None and settings.get("dblclick_edits_text", True) and \
                self.edit_text_here(pt):
            return
        if a is None and self.select_word_at(pt, switch=True):
            return                  # double-click a word: select its text
        if a is not None:
            self.select(a)
            if a.type[0] == fitz.PDF_ANNOT_FREE_TEXT:
                self.edit_selected_text()
            else:
                self.edit_selected_comment()

    def keyPressEvent(self, e):
        k = e.key()
        bar = self.measure_bar
        if bar is not None and self.tool in self.BAR_TOOLS and \
                self.tool != "count" and e.text() and \
                (e.text().isdigit() or e.text() == ".") and \
                (self._pts or self._drag):
            bar.entry.setFocus()
            bar.entry.setText(e.text())
            return
        if k in (Qt.Key_A, Qt.Key_D) and not (e.modifiers() &
                                              ~Qt.KeypadModifier) and \
                not self._pts and self.ai_open_refs():
            self.decide_selected(k == Qt.Key_A)
        elif k in (Qt.Key_Delete, Qt.Key_Backspace) and self.selected \
                and not self._pts:
            self.delete_selected()
        elif k == Qt.Key_Backspace and self._pts:
            self._pts.pop()
            self.update()
        elif k in (Qt.Key_Return, Qt.Key_Enter) and self._pts:
            self._finish_points()
        elif k == Qt.Key_Escape and self.text_sel:
            self.clear_text_selection()
        elif k == Qt.Key_Escape:
            if self._vdrag is not None or self._band is not None:
                self._vdrag = self._band = None
                self.update()
            elif self.uncounted is not None:
                self.clear_uncounted()
            elif self.isolate is not None:
                self.set_isolate(None)
            elif self._pts or self._drag or self._stroke:
                self._pts, self._drag, self._stroke = [], None, []
                self.update()
            else:
                self.set_tool(None)
                self.select(None)
        elif k in (Qt.Key_PageDown,):
            self.next_page()
        elif k in (Qt.Key_PageUp,):
            self.prev_page()
        elif k == Qt.Key_Home and not e.modifiers():     # first page
            self.go_to(0)
        elif k == Qt.Key_End and not e.modifiers():      # last page
            self.go_to(self.doc.page_count - 1)
        elif Qt.Key_1 <= k <= Qt.Key_9 and \
                e.modifiers() & Qt.AltModifier and self.selected and \
                not self._pts:
            # Alt+1..9: the selected markup's status (Nov 4 takeoff list #8)
            sts = annotate.statuses()
            n = k - Qt.Key_1
            if n < len(sts):
                if self.multi:
                    self.apply_marks([(self.page, "set_annot",
                                       {**r, "status": sts[n]})
                                      for r in self.selected_refs()])
                else:
                    self._selected_op(status=sts[n])
                self.status.emit(f"Status: {sts[n] or 'None'}")
        elif Qt.Key_1 <= k <= Qt.Key_9 and not (e.modifiers() &
                                                ~Qt.KeypadModifier) and \
                not self._pts and not self._drag:
            self.number_key.emit(k - Qt.Key_0)       # Tool Chest tool n
        elif k == Qt.Key_Space and not e.modifiers() and not self._pts and \
                not self._drag and self.tool is None:
            self.repeat_tool.emit()                  # takeoff list #13
        else:
            super().keyPressEvent(e)

    def _finish_points(self):
        pts, self._pts = self._pts, []
        # a double-click adds the same point twice; drop near-duplicates
        clean = []
        for q in pts:
            if not clean or abs(q.x - clean[-1].x) + abs(q.y - clean[-1].y) > 1:
                clean.append(q)
        self.update()
        self.commit_points(self.tool, clean)

    # ---- hit testing / selection -----------------------------------------------------
    def annot_at(self, pt):
        """Topmost annotation under a screen point, or None."""
        p = annotate.to_page(self.pg, pt)
        hidden = self._hidden_layers()
        annots = [a for a in annotate.iter_annots(self.pg)
                  if not (hidden and a.get_oc() in hidden)]
        hits = [a for a in annots
                if (fitz.Rect(a.rect) + (-3, -3, 3, 3)).contains(p)]
        if not hits:
            return None
        a = hits[-1]
        # a hatch or a legend row belongs to its shape or legend frame
        if annotate.is_hatch(self.doc, a) or (
                annotate.is_label(self.doc, a) and any(
                    annotate.is_legend(self.doc, x) for x in annots
                    if annotate.tag_of(x) == annotate.tag_of(a))):
            tag = annotate.tag_of(a)
            owner = [x for x in annots if tag and annotate.tag_of(x) == tag
                     and not annotate.is_hatch(self.doc, x)
                     and not annotate.is_label(self.doc, x)]
            if owner:
                return owner[0]
        return a

    def _hidden_layers(self):
        try:
            return {x for x, info in (self.doc.get_ocgs() or {}).items()
                    if not info.get("on", True)}
        except Exception:
            return set()

    def widget_at(self, pt):
        p = annotate.to_page(self.pg, pt)
        for w in self.pg.widgets():
            if fitz.Rect(w.rect).contains(p):
                return w
        return None

    def select(self, annot, add=False):
        """Select `annot` (None: nothing). add=True (Ctrl+click) adds it to
        the set of selected markups, or takes it out if it's in already."""
        if add and annot is not None:
            if not self.multi and self.selected:
                self.multi = [self.selected["ref"]]
            r = annotate.ref(annot)
            if r in self.multi:
                self.multi.remove(r)
            else:
                self.multi.append(r)
            last = self.multi[-1] if self.multi else None
            found = annotate.find_annots(self.pg, last) if last else []
            self.selected = {"ref": last, "rect": list(found[0].rect),
                             "type": found[0].type[1]} if found else None
            if len(self.multi) <= 1:
                self.multi = []
            self.status.emit(self.multi_summary())
        elif annot is None:
            self.selected = None
            self.multi = []
        else:
            self.multi = []
            self.selected = {"ref": annotate.ref(annot),
                             "rect": list(annot.rect),
                             "type": annot.type[1]}
        self.update()
        self._changed()
        self.selection_changed.emit()

    # ---- several markups at once (Nov 1) ------------------------------
    def _selectable(self, a):
        return not (annotate.is_label(self.doc, a) or
                    annotate.is_hatch(self.doc, a) or
                    annotate.is_badge(self.doc, a) or
                    annotate.is_legend(self.doc, a))

    def select_in_rect(self, r):
        """Select every markup drawn wholly inside screen rect `r` (a box
        dragged on the page). Returns how many."""
        box = annotate.to_page(self.pg, fitz.Rect(r))
        hidden = self._hidden_layers()
        refs, seen = [], set()
        for a in annotate.iter_annots(self.pg):
            if hidden and a.get_oc() in hidden:
                continue
            if not self._selectable(a) or not box.contains(fitz.Rect(a.rect)):
                continue
            ref = annotate.ref(a)
            key = str(sorted(ref.items()))
            if key not in seen:
                seen.add(key)
                refs.append(ref)
        if not refs:
            self.select(None)
            return 0
        found = annotate.find_annots(self.pg, refs[-1])
        self.selected = {"ref": refs[-1], "rect": list(found[0].rect),
                         "type": found[0].type[1]} if found else None
        self.multi = refs if len(refs) > 1 else []
        self.update()
        self._changed()
        self.selection_changed.emit()
        self.status.emit(self.multi_summary())
        return len(refs)

    def selected_refs(self):
        """Refs of every selected markup (one, several or none)."""
        if self.multi:
            return list(self.multi)
        return [self.selected["ref"]] if self.selected else []

    def multi_totals(self):
        """{(type, unit): (count, total)} of the selected measurements and
        how many other markups: (totals, others)."""
        tot, others = {}, 0
        for ref in self.selected_refs():
            found = [a for a in annotate.find_annots(self.pg, ref)
                     if self._selectable(a)]
            if not found:
                continue
            subj = (found[0].info or {}).get("subject", "")
            if not subj.startswith(annotate.TAKEOFF + ":"):
                others += 1
                continue
            parts = (subj.split(":", 5) + [""] * 6)
            mtype, unit = parts[1], parts[3]
            try:
                v = float(parts[2]) * annotate.multiplier_of(self.doc,
                                                             found[0])
            except ValueError:
                v = 0.0
            if mtype == "count":
                v, unit = 1.0, "ea"
            if mtype == annotate.CUTOUT:
                v = -v
            n, t = tot.get((mtype, unit), (0, 0.0))
            tot[(mtype, unit)] = (n + 1, t + v)
        return tot, others

    def multi_summary(self):
        refs = self.selected_refs()
        if not refs:
            return ""
        tot, others = self.multi_totals()
        bits = [f"{len(refs)} selected"]
        for (mtype, unit), (n, t) in sorted(tot.items()):
            name = "Cutouts" if mtype == annotate.CUTOUT else \
                mtype.title()
            bits.append(f"{name}: {_c2(t):,.2f} {unit}" if mtype != "count"
                        else f"Count: {n:g}")
        if others:
            bits.append(f"{others} other markup(s)")
        return " · ".join(bits)

    def _split_run(self, at=None):
        from . import measure_tools
        p = annotate.to_page(self.pg, at) if at is not None else None
        n = measure_tools.split_run(self, p)
        self.status.emit("Split into 2 runs" if n else
                         "Pick a run with a corner to split it at")
        return n

    def _join_runs(self):
        from . import measure_tools
        n = measure_tools.join_runs(self)
        self.status.emit("Joined into one run" if n else
                         "Select runs of the same item whose ends meet")
        return n

    def bulk_edit_dialog(self, values=None):
        """Height / rise-drop / status / item name for every selected
        measurement at once. `values` (tests): the dialog's answers."""
        from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                                       QFormLayout, QLineEdit)
        from . import measure_tools
        if not self.selected_refs():
            return 0
        unit = (self.scale() or {}).get("unit", "ft")
        if values is None:
            dlg = QDialog(self)
            dlg.setWindowTitle(f"Bulk Edit {len(self.selected_refs())} "
                               "Markups")
            f = QFormLayout(dlg)
            h, r, g = QLineEdit(), QLineEdit(), QLineEdit()
            for e in (h, r, g):
                e.setPlaceholderText("leave blank to keep")
            st = QComboBox()
            st.addItem("(keep)", None)
            for n in annotate.statuses():
                st.addItem(n or "None", n)
            f.addRow(f"Wall height (runs; 0 = none; {unit}):", h)
            f.addRow(f"Rise / drop (runs; {unit}):", r)
            f.addRow("Status:", st)
            f.addRow("Item name:", g)
            bb = QDialogButtonBox(QDialogButtonBox.Ok |
                                  QDialogButtonBox.Cancel)
            bb.accepted.connect(dlg.accept)
            bb.rejected.connect(dlg.reject)
            f.addRow(bb)
            if dlg.exec() != QDialog.Accepted:
                return 0
            values = {"height": h.text(), "rise": r.text(),
                      "status": st.currentData(), "group": g.text()}

        def length(text):
            text = (text or "").strip()
            if not text:
                return None
            got = takeoff.parse_length(text)
            return takeoff.convert(got[0], got[1], unit) if got else None
        n = measure_tools.bulk_edit(
            self, height=length(values.get("height")),
            rise=length(values.get("rise")), status=values.get("status"),
            group=(values.get("group") or "").strip() or None)
        if n:
            self.status.emit(f"Changed {n} measurement(s)")
        return n

    def reassign_selected(self, group=None):
        """Put every selected measurement under another takeoff item (its
        name), as one undoable step."""
        refs = [r for r in self.selected_refs()
                if any((a.info or {}).get("subject", "").startswith(
                    annotate.TAKEOFF + ":")
                    for a in annotate.find_annots(self.pg, r))]
        if not refs:
            return 0
        if group is None:
            names = sorted({it["group"] for it in
                            annotate.takeoff_items(self.doc) if it["group"]})
            group, ok = QInputDialog.getItem(
                self, "Move to Item", f"Put the {len(refs)} selected "
                "measurement(s) under:", names, 0, True)
            if not ok or not str(group).strip():
                return 0
        group = str(group).strip()
        learned = {}
        for r in refs:                        # what AI names they had
            for a in annotate.find_annots(self.pg, r):
                # takeoff:type:value:unit:group[:parent]
                parts = (a.info or {}).get("subject", "").split(":", 4)
                old = parts[4].split(":")[0] if len(parts) == 5 else ""
                if old and old != group:
                    meth = str(annotate.audit_of(self.doc, a).get("method")
                               or "")
                    learned.setdefault((old, parts[1]), []).append(meth)
        n = self.apply_marks([(self.page, "set_annot", {**r, "group": group})
                              for r in refs])
        if n:
            from . import name_memory      # the next AI Takeoff uses it
            for (old, mtype), meths in learned.items():
                name_memory.learn(old, group, mtype, meths)
        return n

    # ---- reshaping an outline by its corners (Nov 1) -------------------
    HANDLE_PX = 6

    def _selected_shape(self):
        if not self.selected or self.multi:
            return None
        for a in annotate.find_annots(self.pg, self.selected["ref"]):
            if annotate.reshapable(self.doc, a):
                return a
        return None

    def _shape_points(self):
        a = self._selected_shape()
        if a is None:
            return []
        return [annotate.from_page(self.pg, fitz.Point(q))
                for q in (a.vertices or [])]

    def _shape_closed(self):
        a = self._selected_shape()
        return a is not None and a.type[0] == fitz.PDF_ANNOT_POLYGON

    def vertex_handles(self):
        """[(screen point, index, is_mid)]: a square on every corner and a
        dot in the middle of every side (drag it to add a corner)."""
        a = self._selected_shape()
        if a is None:
            return []
        v = self._shape_points()
        out = [(q, i, False) for i, q in enumerate(v)]
        if a.type[0] != fitz.PDF_ANNOT_LINE:
            n = len(v)
            for i in range(n if self._shape_closed() else n - 1):
                out.append(((v[i] + v[(i + 1) % n]) / 2, i, True))
        return out

    def handle_at(self, pt):
        """(index, is_mid) of the handle under screen point `pt`, or None;
        corners win over side dots."""
        tol = self.HANDLE_PX / max(self.zoom, 1e-6)
        best = None
        for q, i, mid in self.vertex_handles():
            d = abs(q - pt)
            if d <= tol and (best is None or (not mid, -d) >
                             (not best[2], -best[0])):
                best = (d, i, mid)
        return None if best is None else (best[1], best[2])

    def _paint_handles(self, p):
        hs = self.vertex_handles()
        if not hs:
            return
        vd = self._vdrag
        if vd is not None:                      # the outline as it will be
            pts = list(vd["pts"])
            if vd["mid"]:
                pts.insert(vd["i"] + 1, vd["cur"])
            else:
                pts[vd["i"]] = vd["cur"]
            path = QPainterPath(self._q(pts[0]))
            for q in pts[1:]:
                path.lineTo(self._q(q))
            if self._shape_closed():
                path.closeSubpath()
            p.setPen(QPen(QColor(0, 120, 215), 1.5, Qt.DashLine))
            p.drawPath(path)
        k = self.HANDLE_PX / 2
        p.setPen(QPen(QColor(0, 120, 215), 1))
        for q, _i, mid in hs:
            c = self._q(q)
            if mid:
                p.setBrush(QBrush(QColor(255, 255, 255)))
                p.drawEllipse(c, k * 0.7, k * 0.7)
            else:
                p.setBrush(QBrush(QColor(0, 120, 215)))
                p.drawRect(QRectF(c.x() - k, c.y() - k, 2 * k, 2 * k))
        p.setBrush(Qt.NoBrush)

    def reshape_selected(self, screen_pts):
        """The selected outline with new corners (screen points): its
        quantity follows, as one undoable step."""
        if not self.selected:
            return 0
        ppts = [annotate.to_page(self.pg, q) for q in screen_pts]
        sc = self.scale(at=ppts)
        payload = {**self.selected["ref"], "pts": [[q.x, q.y] for q in ppts]}
        if sc:
            payload["ppu"] = sc["ppu"]
        n = self.apply_marks([(self.page, "set_vertices", payload)])
        if n:
            if "target" in self.selected["ref"]:
                self._refresh_selection()
            else:                                # an untagged markup
                self.select(None)
            self.status.emit("Outline reshaped - its quantity was "
                             "measured again")
        return n

    def drag_vertex(self, i, to, mid=False):
        """Move corner `i` to screen point `to`; mid=True adds a corner
        after corner `i` (a side's middle dot was dragged)."""
        pts = self._shape_points()
        if not pts or not 0 <= i < len(pts):
            return 0
        if mid:
            pts.insert(i + 1, fitz.Point(to))
        else:
            pts[i] = fitz.Point(to)
        return self.reshape_selected(pts)

    def remove_vertex(self, i):
        """Take corner `i` out (Ctrl+click it); an area keeps 3 at least,
        a run 2."""
        pts = self._shape_points()
        least = 3 if self._shape_closed() else 2
        a = self._selected_shape()
        if a is None or a.type[0] == fitz.PDF_ANNOT_LINE or \
                len(pts) <= least or not 0 <= i < len(pts):
            return 0
        del pts[i]
        return self.reshape_selected(pts)

    # ---- counts: copies not counted yet (Nov 1) -----------------------
    def _selected_count_group(self):
        if not self.selected:
            return None
        for a in annotate.find_annots(self.pg, self.selected["ref"]):
            subj = (a.info or {}).get("subject", "")
            if subj.startswith(annotate.TAKEOFF + ":count:"):
                return (subj.split(":", 5) + [""] * 6)[4] or None
        return None

    def show_uncounted(self, group=None):
        """Box in orange the copies of count `group`'s symbol on this page
        that have no count mark (default: the selected count's name).
        Returns how many, or None when it can't look."""
        from . import uncounted
        group = group or self._selected_count_group()
        if not group:
            self.status.emit("Select a count first.")
            return None
        self.setCursor(Qt.WaitCursor)
        try:
            hits = uncounted.uncounted(self.doc, group, [self.page])
        except (LookupError, RuntimeError) as e:
            self.status.emit(str(e))
            return None
        finally:
            self.unsetCursor()
        self.uncounted = {"page": self.page, "group": group, "hits": hits}
        self.update()
        self.status.emit(
            f"{len(hits)} cop{'y' if len(hits) == 1 else 'ies'} of "
            f"{group} not counted on this page (orange)" if hits else
            f"Every copy of {group} on this page is counted")
        return len(hits)

    def count_uncounted(self):
        """Count the orange copies (show_uncounted) as one undoable step."""
        from . import uncounted
        uc = self.uncounted
        if not uc or not uc["hits"]:
            return 0
        marks = uncounted.count_marks(uc["hits"], uc["group"], self.doc,
                                      self._color("add_count"))
        n = self.apply_marks(marks)
        self.uncounted = None
        self.update()
        self.status.emit(f"Counted {n} more × {uc['group']}")
        return n

    def add_to_count_library(self, group=None):
        """Keep count `group`'s sample in the count library (tried on new
        plan sets with Takeoff > Try the Count Library). Returns the name
        kept, or None."""
        from . import count_library
        group = group or self._selected_count_group()
        if not group:
            self.status.emit("Select a count first.")
            return None
        try:
            name = count_library.add_from_drawing(self.doc, group)
        except (LookupError, ValueError, OSError) as e:
            self.status.emit(str(e))
            return None
        self.status.emit(f"{name} added to the count library - try it on "
                         "other plan sets with Takeoff > Try the Count "
                         "Library")
        return name

    def clear_uncounted(self):
        self.uncounted = None
        self.update()

    def ask_missed_example(self, group):
        """Report Missed: the next box drawn on the drawing is a copy the
        takeoff missed - more like it are looked for (search_from_example)."""
        self.missed_group = (group or "").strip() or "Missed symbol"
        self.set_tool("missed_example")
        self.status.emit(f"Draw a box around one {self.missed_group} the "
                         "takeoff missed - more like it are looked for "
                         "(Esc to cancel).")

    def search_from_example(self, rect, group=None):
        """`rect` (screen) holds a copy the takeoff missed: it becomes the
        count's sample, and every copy like it on this page that isn't
        counted is added as a count in review (badged, out of the totals
        until accepted). Returns how many."""
        from . import uncounted
        group = group or self.missed_group or "Missed symbol"
        if rect.width < 4 or rect.height < 4:
            return 0
        self.setCursor(Qt.WaitCursor)
        try:
            hits = uncounted.from_example(self.doc, self.page, rect, group)
        except (LookupError, RuntimeError) as e:
            self.status.emit(str(e))
            return 0
        finally:
            self.unsetCursor()
        self.set_tool(None)
        self.missed_group = None
        if not hits:
            self.status.emit(f"No uncounted copies of {group} found like "
                             "that one - count it by hand")
            return 0
        marks = uncounted.count_marks(hits, group, self.doc,
                                      self._color("add_count"), review=True)
        n = self.apply_marks(marks)
        self.status.emit(f"Found {n} uncounted {group} like that one - in "
                         "review: accept them in AI Takeoff > Review Queue")
        return n

    def selected_props(self):
        """Style of the selected markup, for the Properties panel."""
        if not self.selected:
            return None
        found = annotate.find_annots(self.pg, self.selected["ref"])
        if not found:
            return None
        a = found[0]
        info = a.info or {}
        colors = a.colors or {}
        subj = info.get("subject", "")
        is_takeoff = subj.startswith(annotate.TAKEOFF + ":")
        if is_takeoff:
            subj = (subj.split(":", 5) + [""] * 6)[4]
        border = a.border or {}
        layer = ""
        try:
            x = a.get_oc()
            if x:
                layer = (self.doc.get_ocgs() or {}).get(x, {}).get("name", "")
        except Exception:
            logging.getLogger(__name__).debug("ignored error", exc_info=True)
        hatch = ""
        tag = annotate.tag_of(a)
        if tag:
            for h in annotate.iter_annots(self.pg):
                if annotate.tag_of(h) == tag and annotate.is_hatch(self.doc, h):
                    hatch = self.doc.xref_get_key(h.xref, "PSHatch")[1]
                    break
        return {"dashes": list(border.get("dashes") or []),
                "hatch": hatch, "layer": layer,
                "type": a.type[1], "color": colors.get("stroke"),
                "fill": colors.get("fill"),
                "width": border.get("width", -1),
                "opacity": a.opacity if a.opacity >= 0 else 1.0,
                "subject": subj, "takeoff": is_takeoff,
                "comment": info.get("content", ""),
                "author": info.get("title", ""),
                "status": annotate.status_of(self.doc, a)}

    REVIEW_ACTIONS = [
        ("REVIEWED - NO EXCEPTIONS TAKEN", (0, 0.5, 0)),
        ("MAKE CORRECTIONS NOTED", (0, 0.35, 0.8)),
        ("REVISE AND RESUBMIT", (0.85, 0.45, 0)),
        ("REJECTED", (0.85, 0, 0)),
        ("SUBMIT SPECIFIED ITEM", (0.85, 0, 0)),
        ("FOR RECORD ONLY", (0.3, 0.3, 0.3)),
    ]
    REVIEW_NOTE = ("Review is only for general conformance with the design "
                   "concept and the contract documents. The contractor is "
                   "responsible for dimensions, quantities, fabrication, "
                   "means and methods, and coordination of all trades.")

    def review_stamp(self, pr, action=None, reviewer=None):
        """A submittal review stamp (AIA G712 style): the action taken,
        who reviewed it and when, and the usual limitation of review."""
        import datetime
        names = [a for a, _ in self.REVIEW_ACTIONS]
        if action is None:
            action, ok = QInputDialog.getItem(self, "Submittal Review",
                                              "Action taken:", names, 0,
                                              False)
            if not ok:
                return 0
        color = dict(self.REVIEW_ACTIONS).get(action, (0.85, 0, 0))
        who = reviewer or settings.author() or ""
        text = (f"{action}\nReviewed by: {who}   Date: "
                f"{datetime.date.today():%m/%d/%Y}\n{self.REVIEW_NOTE}")
        r = fitz.Rect(pr)
        r.x1 = max(r.x1, r.x0 + 230)
        r.y1 = max(r.y1, r.y0 + 78)
        return self.apply_marks([(self.page, "add_textbox", {
            "rect": list(r), "text": text, "size": 8, "border": True,
            "color": list(color), "subject": "Submittal Review",
            "author": who})])

    def _measure_menu(self, m):
        """Right-click items for the selected measurement (Nov 2)."""
        from . import measure_extra, measure_tools
        sel = measure_tools.selected_measure(self)
        if sel and sel["run"] and sel["type"] in ("length", "area"):
            m.addAction("Rise / Drop…", self.ask_rise)
            m.addAction("Wall Height and Openings…", self.ask_wall_selected)
        if sel and sel["type"] == "volume":
            vm = m.addMenu("Show Volume In")
            for u in measure_extra.volume_choices(sel["unit"]):
                act = vm.addAction(u, lambda x=u: measure_tools.show_volume_in(
                    self, x))
                act.setCheckable(True)
                act.setChecked(u == sel["unit"])
        choices = measure_tools.convert_choices(sel)
        if choices:
            cm = m.addMenu("Convert To")
            for k in choices:
                cm.addAction(measure_tools.CONVERT[k],
                             lambda x=k: self.convert_selected(x))
        if self.selected and not self.multi:
            m.addAction("Copy Several Times…", self.multiply_dialog)
        if sel and sel["run"] and len(sel["annot"].vertices or []) >= 3:
            at = getattr(self, "_menu_pt", None)
            m.addAction("Split Run at This Corner",
                        lambda a=at: self._split_run(a))

    def ask_rise(self):
        from . import measure_tools
        sel = measure_tools.selected_measure(self)
        if not sel:
            return 0
        unit = (self.scale() or {}).get("unit", "ft")
        cur = sel["extra"].get("rise") or 0
        text, ok = QInputDialog.getText(
            self, "Rise / Drop", "Vertical length to add to this run "
            f"(e.g. 8' drop to a switch; 0 for none; plain numbers are "
            f"{unit}):", text=takeoff.fmt(cur, unit) if cur else "")
        if not ok:
            return 0
        got = takeoff.parse_length(text or "0")
        if not got:
            QMessageBox.information(self, "Rise / Drop",
                                    "Enter a length, for example 8'.")
            return 0
        return measure_tools.set_rise(
            self, takeoff.convert(got[0], got[1], unit))

    def ask_wall_selected(self):
        from . import measure_tools
        sel = measure_tools.selected_measure(self)
        if not sel:
            return 0
        wall = self.ask_wall(sel["extra"])
        if wall is None:
            return 0
        return measure_tools.set_wall(self, wall["height"],
                                      wall["openings"])

    def convert_selected(self, to):
        from . import measure_tools
        n = measure_tools.convert(self, to)
        if n == -1:
            QMessageBox.information(
                self, "Convert To", "This area has cutouts taken out of it. "
                "Delete the cutouts first, then convert it.")
            return 0
        if n:
            self.status.emit(f"Converted to {measure_tools.CONVERT[to]}")
        return n

    def resume_count(self, group):
        from . import measure_tools
        color = None
        if self.selected:
            for a in annotate.find_annots(self.pg, self.selected["ref"]):
                color = annotate.markup_color(self.doc, a)
                break
        self.count_resumed.emit(group)       # the window checks the tool
        measure_tools.resume_count(self, group, color)
        self.status.emit(f"Counting {group}: click each one (Esc to stop)")
        return True

    def multiply_dialog(self):
        """Copy the selected markup several times, a set distance apart,
        with the copies previewed on the page while you choose."""
        from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                                       QFormLayout, QLineEdit, QSpinBox)
        from . import measure_tools
        if not self.selected:
            return 0
        sc = self.scale() or {}
        unit = sc.get("unit", "ft")
        dlg = QDialog(self)
        dlg.setWindowTitle("Copy Several Times")
        form = QFormLayout(dlg)
        count = QSpinBox()
        count.setRange(1, 500)
        count.setValue(int(self.style.get("copy_n", 3)))
        spacing = QLineEdit(self.style.get("copy_space", "10'" if
                                           unit == "ft" else "3"))
        direction = QComboBox()
        direction.addItems(list(measure_tools.DIRECTIONS))
        direction.setEditable(True)
        direction.setCurrentText(self.style.get("copy_dir", "Right"))
        form.addRow("Copies:", count)
        form.addRow(f"Spacing (plain numbers are "
                    f"{unit if sc else 'points'}):", spacing)
        form.addRow("Direction (or an angle):", direction)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        form.addRow(bb)

        def pts():
            text = spacing.text().strip()
            if not sc:
                try:
                    return float(text)
                except ValueError:
                    return None
            got = takeoff.parse_length(text)
            if not got or got[0] <= 0:
                return None
            return takeoff.convert(got[0], got[1], unit) * sc["ppu"]

        def show(*_):
            d = pts()
            try:
                measure_tools.preview(self, count.value(), d or 0,
                                      direction.currentText())
            except ValueError:
                self.ghosts = []
                self.update()
        for sig in (count.valueChanged, spacing.textChanged,
                    direction.currentTextChanged):
            sig.connect(show)
        show()
        ok = dlg.exec() == QDialog.Accepted
        d = pts()
        self.ghosts = []
        self.update()
        if not ok or not d:
            return 0
        self.style["copy_n"] = count.value()
        self.style["copy_space"] = spacing.text()
        self.style["copy_dir"] = direction.currentText()
        try:
            n = measure_tools.multiply(self, count.value(), d,
                                       direction.currentText())
        except ValueError:
            n = 0
        if not n:
            QMessageBox.information(
                self, "Copy Several Times", "This kind of markup can't be "
                "copied that way. Measurements, counts and shapes can.")
        else:
            self.status.emit(f"Added {n} copies")
        return n

    def ask_typical_count(self):
        """A typical area/room/unit: this measurement counts N times."""
        if not self.selected:
            return 0
        found = annotate.find_annots(self.pg, self.selected["ref"])
        shape = [a for a in found if (a.info or {}).get("subject", "")
                 .startswith(annotate.TAKEOFF + ":")]
        if not shape:
            return 0
        cur = annotate.multiplier_of(self.doc, shape[0])
        n, ok = QInputDialog.getDouble(
            self, "Typical Count", "How many identical units does this "
            "measurement stand for?\n(e.g. one typical hotel room x 200)",
            cur, 1, 1000000, 0)
        if not ok:
            return 0
        return self._selected_op(multiplier=n)

    def change_selected(self, **changes):
        """Properties panel edits; "subject" renames a measurement."""
        props = self.selected_props()
        if props is None:
            return 0
        if "subject" in changes and props["takeoff"]:
            changes["group"] = changes.pop("subject")
        return self._selected_op(**changes)

    def _refresh_selection(self):
        if not self.selected:
            return
        found = annotate.find_annots(self.pg, self.selected["ref"])
        if found:
            self.selected["rect"] = list(found[0].rect)
        else:
            self.selected = None

    def unpriced_rects(self):
        """Page rects of this page's open markups and clouds (cached until
        the next edit)."""
        key = (self.page, getattr(self, "_edits", 0), id(self.doc))
        if self._unpriced and self._unpriced[0] == key:
            return self._unpriced[1]
        from . import prebid
        try:
            rep = prebid.check(self.doc, sheets=False)
            rects = [it["rect"] for it in rep.open_markups +
                     rep.unaccounted_clouds if it["page"] == self.page]
        except Exception:
            rects = []
        self._unpriced = (key, rects)
        return rects

    def set_show_unpriced(self, on):
        self.show_unpriced = bool(on)
        self._unpriced = None
        self.update()

    def scope_selected(self, status, reason=None, line=None):
        """Pre-bid scope of the selected markup: priced / excluded / rfi /
        open, or linked to an estimate line ("line" = assembly or code)."""
        from . import prebid
        found = annotate.find_annots(self.pg, self.selected["ref"]) \
            if self.selected else []
        if not found:
            return 0
        a = found[0]
        kw = {}
        if status == "excluded":
            if reason is None:
                reason, ok = QInputDialog.getText(
                    self, "Excluded", "Why is it excluded? (By owner, NIC, "
                    "by others...)")
                if not ok:
                    return 0
            kw["reason"] = reason
        if status == "link":
            if line is None:
                est = prebid.estimate_lines(self.doc)
                opts = sorted(est["lines"]) + sorted(est["codes"])
                if not opts:
                    QMessageBox.information(
                        self, "Link to Estimate", "The estimate has no "
                        "lines yet - add an assembly first.")
                    return 0
                line, ok = QInputDialog.getItem(
                    self, "Link to Estimate", "Priced in:", opts, 0, True)
                if not ok or not line:
                    return 0
            est = prebid.estimate_lines(self.doc)
            status = "priced"
            if line in est["lines"]:
                kw["line_id"] = line
            else:
                kw["cost_code"] = line
        if status == "rfi":
            from . import rfilog
            sc = prebid.scope_of(self.doc, a)
            num = sc.get("rfi")
            if not num:
                it = rfilog.add(self.doc, "RFI",
                                **rfilog.from_markup(self.doc, self.page, a))
                num = it["number"]
            kw["rfi"] = num
        try:
            mark = prebid.scope_mark(self.doc, self.page, a, status, **kw)
        except prebid.PrebidError as e:
            QMessageBox.warning(self, "Pre-bid", str(e))
            return 0
        self._unpriced = None
        return self.apply_marks([mark])

    def _context_menu(self, global_pos):
        m = QMenu(self)
        a = self.selected
        if not a:
            return
        if self.multi:
            m.addAction(self.multi_summary()).setEnabled(False)
            m.addSeparator()
            m.addAction("Move Selected to Item…",
                        lambda: self.reassign_selected())
            m.addAction("Bulk Edit Selected…", lambda: self.bulk_edit_dialog())
            m.addAction("Join Runs Into One", lambda: self._join_runs())
            ai = self.ai_open_refs()
            if ai:
                m.addAction(f"Accept AI Takeoff ({len(ai)})\tA",
                            lambda: self.decide_selected(True))
                m.addAction(f"Deny AI Takeoff ({len(ai)})\tD",
                            lambda: self.decide_selected(False))
            st = m.addMenu("Status")
            for name in annotate.statuses():
                st.addAction(name or "None", lambda n=name: self.apply_marks(
                    [(self.page, "set_annot", {**r, "status": n})
                     for r in self.selected_refs()]))
            m.addSeparator()
            m.addAction(f"Delete {len(self.multi)} Markups",
                        self.delete_selected)
            m.exec(global_pos)
            return
        if a["type"] == "FreeText":
            m.addAction("Edit Text…", self.edit_selected_text)
        m.addAction("Edit Comment…", self.edit_selected_comment)
        m.addAction("Change Color…", self.recolor_selected)
        st = m.addMenu("Status")
        for name in annotate.statuses():
            st.addAction(name or "None",
                         lambda n=name: self._selected_op(status=n))
        sc = m.addMenu("Pre-bid Scope")
        sc.addAction("Priced", lambda: self.scope_selected("priced"))
        sc.addAction("Link to Estimate Line…",
                     lambda: self.scope_selected("link"))
        sc.addAction("Excluded…", lambda: self.scope_selected("excluded"))
        sc.addAction("Sent as an RFI", lambda: self.scope_selected("rfi"))
        sc.addAction("Open", lambda: self.scope_selected("open"))
        ai = self.ai_open_refs()
        if ai:
            m.addSeparator()
            m.addAction(f"Accept AI Takeoff ({len(ai)})\tA",
                        lambda: self.decide_selected(True))
            m.addAction(f"Deny AI Takeoff ({len(ai)})\tD",
                        lambda: self.decide_selected(False))
            m.addSeparator()
        m.addAction("Show Only This Item\tEsc to stop", self.isolate_selected)
        m.addAction("Add to Tool Chest…", self.add_to_chest.emit)
        m.addAction("Create RFI From This Markup…", self.rfi_requested.emit)
        props = self.selected_props()
        if props and props["takeoff"]:
            m.addAction("Set Typical Count…", self.ask_typical_count)
        self._measure_menu(m)
        cg = self._selected_count_group()
        if cg:
            m.addAction(f"Add More to {cg}",
                        lambda g=cg: self.resume_count(g))
            m.addAction(f"Show Uncounted Copies of {cg}",
                        lambda g=cg: self.show_uncounted(g))
            uc = self.uncounted
            if uc and uc["group"] == cg and uc["hits"] and \
                    uc["page"] == self.page:
                m.addAction(f"Count the {len(uc['hits'])} Uncounted "
                            "Copies", self.count_uncounted)
            m.addAction(f"Add {cg} to the Count Library",
                        lambda g=cg: self.add_to_count_library(g))
        if self._selected_shape() is not None:
            m.addAction("Reshape: drag a corner; drag a side's dot to add "
                        "one; Ctrl+click a corner to remove it").setEnabled(
                False)
        m.addSeparator()
        m.addAction("Delete", self.delete_selected)
        m.exec(global_pos)

    # ---- edits ------------------------------------------------------------------------
    def do_op(self, kind, page, **payload):
        """Apply one edit locally, share it, record it."""
        payload = _plain(payload)
        session = self.session
        if session and hasattr(session, "prepare_op"):
            op = session.prepare_op(kind, page, **payload)
        elif session:
            op = session.local_op(kind, page, **payload)
            session = None                  # already sent (older session)
        else:
            op = {"id": uuid.uuid4().hex, "kind": kind, "page": page,
                  "payload": payload}
        # apply first, share only what applied (review 3b B2)
        try:
            changed = annotate.apply_op(self.doc, op, fresh=True)
        except Exception:
            if session:
                session.discard_op(op)
            raise
        hold = getattr(self, "_held_ops", None)
        if hold is not None:
            # a redaction batch: shared and recorded only once it is proven
            # (or discarded when it is rolled back)
            hold.append((session, op, {"kind": kind, "page": page,
                                       **payload} if changed else None))
            if changed:
                self._pf_forget()
            return changed
        if session:
            session.publish_op(op)
        if changed:
            self._pf_forget()
        if changed:
            self.recorder.record({"kind": kind, "page": page, **payload})
        return changed

    def _base_bytes(self):
        """Starting point for undo. Reading the unchanged file is much
        faster than re-serialising a big document."""
        d = self.doc
        try:
            if (d.name and os.path.isfile(d.name) and not d.is_dirty
                    and not d.is_encrypted and not d.needs_pass
                    and not getattr(d, "is_repaired", False)):
                with open(d.name, "rb") as f:
                    return f.read()
        except Exception:
            logging.getLogger(__name__).debug("ignored error", exc_info=True)
        return None

    method_hint = None          # "auto area", "trace", ... for the audit
    _held_ops = None            # set while a redaction batch is applied
    last_redaction_error = None     # why the last redaction batch failed
    save_blocked = None         # reason saving is refused (see _redact_marks)
    # after a redaction the next save rewrites the whole file, and the words
    # that were under the boxes are looked for in it (QS-002, Nov 4)
    needs_full_save = False
    redacted_words = frozenset()

    def apply_marks(self, marks):
        """Apply (page, kind, payload) marks as one undoable step."""
        marks = list(marks)
        if any(k == "add_redact" for _p, k, _pl in marks):
            return self._redact_marks(marks)
        if self.method_hint:
            for _p, _k, payload in marks:
                m = payload.get("measure") if isinstance(payload, dict) \
                    else None
                if isinstance(m, dict) and not m.get("method"):
                    m["method"] = self.method_hint
        kinds = {k for _, k, _ in marks}
        touched = {p for p, _, _ in marks
                   if isinstance(p, int) and 0 <= p < self.doc.page_count}
        if kinds & {"add_legend", "delete_annot", "import_annots"}:
            self._live_legends = None
        live = self._legend_pages(touched, kinds)
        touched |= live
        before = None
        if not kinds & annotate.FULL_UNDO_KINDS and len(touched) <= 400:
            try:
                before = self.history.begin_pages(self.doc, touched)
            except Exception:
                before = None
        pages = set()
        n = 0
        failed = 0
        for page, kind, payload in marks:
            try:                 # one bad mark mustn't drop the rest
                ok = self.do_op(kind, page, **payload)
            except Exception:
                log.exception("applying %s on page %s", kind, page)
                failed += 1
                continue
            if ok:
                n += 1
                pages.add(page)
        self.last_failed = failed
        if n and live:                     # live legends follow the edit
            from . import legend
            for pg in sorted(live):
                try:
                    for p2, k2, pl2 in legend.refresh_marks(self.doc, pg,
                                                            live_only=True):
                        if annotate.apply_op(self.doc, annotate.new_op(
                                k2, p2, **pl2)):
                            pages.add(pg)
                except Exception:
                    log.exception("refreshing a live legend")
        if n and kinds & {"add_polygon", "delete_annot", "set_annot",
                          "set_vertices"}:
            for pg in pages:                 # net areas after cutouts
                try:
                    if annotate.refresh_area_labels(self.doc, pg):
                        self._pg_cache = None
                except Exception:
                    log.exception("refreshing area labels")
        if n:
            label = undo_name(kinds, n, getattr(self, "undo_label", None))
            self.undo_label = None          # one-shot, set by the caller
            if before is not None:
                self.history.commit_pages(self.doc, before, label=label)
            else:
                self.history.snapshot(label=label)
            self.mark_dirty()
            self._render(annots_only=not (kinds & annotate.CONTENT_KINDS
                                          or kinds & annotate.FULL_UNDO_KINDS))
            for pg in pages:
                self.page_changed.emit(pg)
        if "set_scale" in kinds:
            note = annotate.take_scale_notice(self.doc)
            if note:                    # damaged scale file was replaced
                self.scale_notice = note
                self.status.emit(note)
        return n

    def _redact_marks(self, marks):
        """Apply a batch with redactions, fail closed: every box is then
        checked on a freshly written copy (app/redaction.proof). If any box
        could not be applied, or anything is left inside one, the whole
        batch is rolled back, nothing is shared or recorded, and
        last_redaction_error says which page and box failed."""
        from . import redaction
        self.last_redaction_error = None
        before = self.doc.tobytes()
        held = self._held_ops = []
        areas, problem = [], None
        under = set()
        for page, kind, payload in marks:
            if kind == "add_redact" and isinstance(page, int):
                try:
                    r = fitz.Rect((payload or {}).get("rect") or
                                  (0, 0, 0, 0)).normalize()
                    under |= redaction.words_under(self.doc[page], r)
                except Exception:                         # noqa: BLE001
                    pass
        n, pages = 0, set()
        try:
            for page, kind, payload in marks:
                try:
                    ok = self.do_op(kind, page, **payload)
                except Exception:
                    log.exception("applying %s on page %s", kind, page)
                    ok = False
                if kind == "add_redact":
                    r = fitz.Rect((payload or {}).get("rect") or
                                  (0, 0, 0, 0)).normalize()
                    if not ok:
                        res = redaction.Result(
                            page if isinstance(page, int) else -1, r)
                        res.error = "the redaction could not be applied"
                        problem = [res]
                        break
                    areas.append((page, r))
                if ok:
                    n += 1
                    pages.add(page)
            if problem is None and areas:
                try:
                    problem = redaction.failures(
                        redaction.proof(self.doc, areas)) or None
                except Exception as e:
                    log.exception("redaction proof")
                    res = redaction.Result(areas[0][0], areas[0][1])
                    res.error = f"the check could not be run ({e})"
                    problem = [res]
        finally:
            self._held_ops = None
        if problem:
            for session, op, _rec in held:
                if session:
                    session.discard_op(op)
            msg = ("Redaction failed - " + problem[0].describe() + "." +
                   (f" ({len(problem) - 1} more box(es) also failed.)"
                    if len(problem) > 1 else ""))
            try:
                self.replace_document(fitz.open(stream=before,
                                                filetype="pdf"),
                                      keep_history=True)
                self.reset_page_cache()
                msg += ("\n\nNothing was redacted: the whole batch was "
                        "rolled back and nothing was saved.")
            except Exception:
                log.exception("rolling back a failed redaction")
                self.save_blocked = (
                    "a redaction could not be proven and the document "
                    "could not be rolled back. Close it without saving "
                    "and open the file again.")
                msg += ("\n\nThe document could not be rolled back, so "
                        "saving it is blocked. Close it without saving.")
            self.last_failed = len(marks)
            self.last_redaction_error = msg
            log.warning("redaction batch rolled back: %s",
                        problem[0].describe())
            self.redaction_failed.emit(msg)
            return 0
        for session, op, rec in held:
            if session:
                session.publish_op(op)
            if rec:
                self.recorder.record(rec)
        self.last_failed = 0
        if areas:
            self.needs_full_save = True
            self.redacted_words = frozenset(set(self.redacted_words) | under)
        if n:
            # Venice #17: named, and undoable until the file is saved
            self.history.snapshot(label=(
                f"Redaction ({len(areas)} areas)" if len(areas) > 1 else
                "Redaction") if areas else undo_name(
                    {k for _p, k, _pl in marks}, n))
            self.mark_dirty()
            self._render()
            for pg in pages:
                self.page_changed.emit(pg)
            if areas:
                self.status.emit(
                    f"Redacted {len(areas)} area(s). Undo (Ctrl+Z) brings "
                    "them back until you save - once saved, it's permanent.")
        return n

    def noted(self, msg):
        """`msg`, led by the one-time damaged-scales note if there is one
        (so a later status message doesn't hide it)."""
        note = getattr(self, "scale_notice", None)
        self.scale_notice = None
        return f"{note}  {msg}" if note else msg

    def pages_restored(self, pages):
        """Undo/redo rewrote the annotations of `pages` in place."""
        self.selected = None
        self._pg_cache = None
        for p in pages:
            if 0 <= p < self.doc.page_count:
                try:
                    self.doc.reload_page(self.doc[p])
                except Exception:
                    logging.getLogger(__name__).debug("ignored error", exc_info=True)
        self.mark_dirty()
        self._render(annots_only=True)    # rotation is part of the key
        for p in pages:
            self.page_changed.emit(p)
        self.selection_changed.emit()

    def mark_dirty(self):
        self._pf_forget()
        self.dirty = True
        self._changed()

    def replace_document(self, doc, keep_history=False):
        old = self.doc
        self.doc = doc
        if old is not doc:
            old.close()
        self.selected = None
        self._snap_cache = None
        if not keep_history:
            self.history.reset(self._base_bytes())
        self._render()

    def _color(self, kind):
        return self.color or annotate.DEFAULT_COLORS.get(kind, (1, 0, 0))

    def _styled(self, kind, payload):
        """Add the current tool style and author to a new markup."""
        payload.setdefault("color", list(self._color(kind)))
        for k in ("width", "opacity"):
            if self.style.get(k) is not None:
                payload.setdefault(k, self.style[k])
        if self.style.get("fill") is not None and kind in (
                "add_rect", "add_ellipse", "add_polygon", "add_cloud"):
            payload.setdefault("fill", self.style["fill"])
        if self.style.get("subject") and "measure" not in payload:
            payload.setdefault("subject", self.style["subject"])
        ls = self.style.get("line_style")
        if ls and ls != "Solid" and kind in (
                "add_rect", "add_ellipse", "add_polygon", "add_cloud",
                "add_line", "add_polyline", "add_ink"):
            from . import styles
            d = styles.line_styles().get(ls)
            if d:
                payload.setdefault("dashes", d)
        hatch = self.style.get("hatch")
        if hatch and hatch != "None" and kind in (
                "add_rect", "add_ellipse", "add_polygon", "add_cloud") \
                and (payload.get("measure") or {}).get("type") != \
                annotate.CUTOUT:
            from . import styles
            fams = styles.hatches().get(hatch)
            if fams:
                payload.setdefault("hatch", [list(f) for f in fams])
        if self.style.get("layer"):
            payload.setdefault("layer", self.style["layer"])
        if isinstance(self.style.get("fields"), dict) and \
                isinstance(payload.get("measure"), dict):
            payload.setdefault("fields", dict(self.style["fields"]))
        payload.setdefault("author", settings.author())
        return payload

    def _mark(self, kind, **payload):
        return self.apply_marks([(self.page, kind,
                                  self._styled(kind, payload))])

    # ---- commit: rectangles ---------------------------------------------------------------
    def commit_rect(self, tool, rect):
        """`rect` in screen coordinates."""
        if rect.width < 2 or rect.height < 2:
            return 0
        pr = annotate.to_page(self.pg, rect)
        if tool in TEXT_MARKUP:
            lines = [annotate.to_page(self.pg, r)
                     for r in annotate.text_rects(self.pg, rect)]
            payload = {"rect": list(pr)}
            if lines:
                u = fitz.Rect(lines[0])
                for r in lines[1:]:
                    u |= r
                payload = {"rect": list(u), "rects": [list(r) for r in lines]}
            return self._mark(tool, **payload)
        if tool in ("add_rect", "add_ellipse", "add_cloud"):
            return self._mark(tool, rect=list(pr))
        if tool == "add_redact":
            if QMessageBox.question(
                    self, "Redact",
                    "Permanently remove everything inside this box?\n"
                    "(Undo works until you save.)") != QMessageBox.Yes:
                return 0
            return self.apply_marks([(self.page, "add_redact",
                                      {"rect": list(pr)})])
        if tool == "add_textbox":
            text, ok = QInputDialog.getMultiLineText(self, "Text Box",
                TEXT_PROMPT)
            if not ok or not text.strip():
                return 0
            return self._mark("add_textbox", rect=list(pr), text=text, size=12)
        if tool == "add_image":
            return self._insert_image(pr)
        if tool in ("field_text", "field_checkbox", "field_combo"):
            return self._add_field(tool, pr)
        if tool == "symbol":
            return self.count_symbol(rect, review=True)
        if tool == "symbol_sample":            # Count Several Symbols
            cb = getattr(self, "symbol_sample_cb", None)
            return cb(rect) if cb else 0
        if tool == "missed_example":           # Report Missed > Search
            return self.search_from_example(rect)
        if tool in ("zone_include", "zone_exclude"):
            return self.add_zone(pr, tool[5:])
        if tool == "zoom":
            self.marquee_zoom.emit(rect)
            return 0
        if tool == "review_stamp":
            return self.review_stamp(pr)
        if tool == "viewport":
            return self.add_viewport(pr)
        if tool == "legend":
            return self.add_legend(pr, ask=True)
        if tool == "snapshot":
            return self.snapshot(rect)
        if tool == "add_stamp":
            from .acrobat import STAMPS
            names = [n for n, _ in STAMPS]
            name, ok = QInputDialog.getItem(self, "Stamp", "Stamp:", names,
                                            0, False)
            if not ok:
                return 0
            return self._mark("add_stamp", rect=list(pr),
                              stamp=dict(STAMPS)[name], subject=name)
        if tool == "crop":
            self.crop_requested.emit(pr)
            return 1
        if tool in ("fs_signature", "fs_initials"):
            return self.place_signature(tool[3:], pr)
        if tool == "esign_field":
            from . import esign
            kind, signer = getattr(self, "esign_spec", ("signature", 0))
            if kind in ("signature", "initials") and pr.height < 20:
                pr.y0 = pr.y1 - 24
            return self.apply_marks([(self.page, "add_rect",
                                      esign.field_payload(kind, signer,
                                                          pr))])
        return 0

    def place_signature(self, kind, pr, data=None):
        """Put your saved signature/initials in the box (asks you to draw
        it the first time)."""
        from . import signature
        data = data or signature.saved(kind)
        if data is None:
            if not signature.SignaturePad(kind, self).exec():
                return 0
            data = signature.saved(kind)
            if data is None:
                return 0
        strokes = signature.strokes_in(data, fitz.Rect(pr))
        return self._mark("add_ink", strokes=strokes,
                          color=list(self.style.get("color") or
                                     (0.05, 0.12, 0.47)),
                          width=1.8, subject=kind.title())

    def _insert_image(self, pr):
        path, _ = QFileDialog.getOpenFileName(
            self, "Insert Image", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff)")
        if not path:
            return 0
        if os.path.getsize(path) > 15 * 1024 * 1024:
            QMessageBox.warning(self, "Image", "That image is over 15 MB. "
                                "Please use a smaller one.")
            return 0
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode("ascii")
        return self.apply_marks([(self.page, "add_image",
                                  {"rect": list(pr), "data": data})])

    def _add_field(self, tool, pr):
        ftype = {"field_text": "text", "field_checkbox": "checkbox",
                 "field_combo": "combo"}[tool]
        existing = {w.field_name for pg in self.doc for w in pg.widgets()}
        n = 1
        while f"{ftype.title()}{n}" in existing:
            n += 1
        name, ok = QInputDialog.getText(self, "Form Field", "Field name:",
                                        text=f"{ftype.title()}{n}")
        if not ok or not name.strip():
            return 0
        if name.strip() in existing:
            QMessageBox.warning(self, "Form Field",
                                "A field with that name already exists.")
            return 0
        payload = {"rect": list(pr), "ftype": ftype, "name": name.strip()}
        if ftype == "combo":
            text, ok = QInputDialog.getText(
                self, "Dropdown", "Choices (separated by commas):",
                text="Yes, No, N/A")
            if not ok:
                return 0
            payload["choices"] = [c.strip() for c in text.split(",")
                                  if c.strip()]
        return self.apply_marks([(self.page, "add_field", payload)])

    # ---- commit: lines and points --------------------------------------------------
    def scale(self, page=None, at=None):
        """The scale for `page` (default: this one); with `at` (op points),
        the scale of the viewport they're in, if any."""
        pno = self.page if page is None else page
        if at:
            return annotate.scale_at(self.doc, pno,
                                     [(q.x, q.y) if hasattr(q, "x") else q
                                      for q in at])
        return annotate.read_scales(self.doc).get(pno)

    def commit_line(self, tool, a, b):
        pa, pb = annotate.to_page(self.pg, a), annotate.to_page(self.pg, b)
        dist = takeoff.path_length([pa, pb])
        if dist < 2:
            return 0
        if tool in ("add_line", "arrow"):
            return self._mark("add_line", pts=[[pa.x, pa.y], [pb.x, pb.y]],
                              arrow=tool == "arrow")
        if tool == "callout":
            text, ok = QInputDialog.getMultiLineText(self, "Callout",
                TEXT_PROMPT)
            if not ok or not text.strip():
                return 0
            w = max(90, min(260, 7 * max(len(t) for t in text.splitlines())))
            h = 16 * (text.count("\n") + 1) + 8
            box = fitz.Rect(pb.x, pb.y - h / 2, pb.x + w, pb.y + h / 2)
            if pb.x < pa.x:
                box = fitz.Rect(pb.x - w, pb.y - h / 2, pb.x, pb.y + h / 2)
            return self._mark("add_callout", rect=list(box),
                              tip=[pa.x, pa.y], text=text)
        if tool == "calibrate":
            return self.calibrate(dist)
        if tool == "measure_length":
            return self._measure("length", [pa, pb])
        if tool in ("measure_radius", "measure_diameter"):
            return self._measure_circle(tool, pa, pb)
        return 0

    def commit_points(self, tool, pts):
        need = 3 if tool in ("measure_area", "measure_cutout",
                             "measure_volume", "measure_angle",
                             "add_polygon", "trace_outline") else 2
        if len(pts) < need:
            self.status.emit(f"Need at least {need} points.")
            return 0
        ppts = [annotate.to_page(self.pg, q) for q in pts]
        if tool == "add_polyline":
            return self._mark("add_polyline", pts=[[q.x, q.y] for q in ppts])
        if tool == "add_polygon":
            return self._mark("add_polygon", pts=[[q.x, q.y] for q in ppts])
        if tool == "measure_polylength":
            return self._measure("length", ppts)
        if tool == "measure_wall":
            wall = self.ask_wall()
            if wall is None:
                return 0
            return self._measure("length", ppts, extra=wall)
        if tool == "measure_area":
            return self._measure("area", ppts)
        if tool == "trace_outline":
            self.method_hint = "trace outline"
            try:
                return self._measure("area", ppts)
            finally:
                self.method_hint = None
                self._trace_refs = []
        if tool == "measure_cutout":
            return self.cutout(ppts)
        if tool == "measure_volume":
            return self._measure("volume", ppts)
        if tool == "measure_angle":
            return self._measure_angle(ppts[:3])
        return 0

    def area_at(self, ppt):
        """The smallest area measurement on this page containing page point
        `ppt` (unrotated), as (annotation, group, unit), or None."""
        best = None
        for a in annotate.iter_annots(self.pg):
            subj = (a.info or {}).get("subject", "")
            if not subj.startswith(annotate.TAKEOFF + ":area:") or \
                    a.type[0] != fitz.PDF_ANNOT_POLYGON:
                continue                  # (a wall area is a run)
            verts = [fitz.Point(v) for v in (a.vertices or [])]
            if len(verts) < 3 or not _inside(ppt, verts):
                continue
            size = takeoff.polygon_area(verts)
            if best is None or size < best[0]:
                parts = (subj.split(":", 5) + [""] * 6)
                best = (size, a, parts[4], parts[3])
        return best[1:] if best else None

    def cutout(self, ppts):
        """Take an opening out of the area it's drawn in (PlanSwift-style
        cutout): the area's quantity becomes the net area."""
        sc = self.scale(at=ppts)
        if not sc:
            QMessageBox.information(self, "Cutout",
                                    "Set the scale for this page first.")
            return 0
        cx = sum(q.x for q in ppts) / len(ppts)
        cy = sum(q.y for q in ppts) / len(ppts)
        hit = self.area_at(fitz.Point(cx, cy))
        if hit is None:
            QMessageBox.information(
                self, "Cutout", "Draw the cutout inside an area you've "
                "measured (Takeoff > Area). It's taken off that area.")
            return 0
        parent, group, unit = hit
        tag = annotate.tag_of(parent)
        if not tag:
            return 0
        value = takeoff.polygon_area(ppts) / sc["ppu"] ** 2
        color = list(parent.colors.get("stroke") or self._color("add_polygon"))
        payload = {"pts": [[q.x, q.y] for q in ppts], "color": color,
                   "fill": [1, 1, 1], "dashes": True, "width": 1.2,
                   "label": f"Cutout -{_c2(value):,.2f} {unit}",
                   "measure": {"type": annotate.CUTOUT,
                               "value": round(value, 4), "unit": unit,
                               "group": group, "parent": tag}}
        n = self.apply_marks([(self.page, "add_polygon", payload)])
        if n:
            self.status.emit(f"Cutout {_c2(value):,.2f} {unit} taken off "
                             f"{group or 'the area'}")
        return n

    def calibrate(self, dist_points, real=None, unit=None, all_pages=None):
        """Set the drawing scale from a line of known length."""
        if real is None:
            from . import calibrate_dialog
            got = calibrate_dialog.ask_calibration(self, dist_points,
                                                   self.doc.page_count)
            if not got:
                return 0
            real, dlg_unit, dlg_all = got
            unit = unit or dlg_unit
            all_pages = dlg_all if all_pages is None else all_pages
        unit = unit or "ft"
        all_pages = bool(all_pages)
        if real <= 0:
            return 0
        payload = {"ppu": dist_points / real, "unit": unit}
        if all_pages:
            payload["pages"] = list(range(self.doc.page_count))
        n = self.apply_marks([(self.page, "set_scale", payload)])
        self.status.emit(self.noted(f"Scale set: {real:g} {unit} = "
                                    f"{dist_points:.1f} pt"))
        return n

    def _measure(self, mtype, ppts, extra=None):
        sc = self.scale(at=ppts)
        if not sc:
            QMessageBox.information(
                self, "Takeoff", "Set the scale for this page first "
                "(Takeoff > Set Scale, then drag along a known dimension).")
            return 0
        payload = self._measure_payload(mtype, ppts, sc, extra)
        if payload is None:
            return 0
        kind = payload.pop("_kind")
        n = self.apply_marks([(self.page, kind,
                               self._styled(kind, payload))])
        if n:
            self.status.emit(f"Measured {payload['label']}")
        return n

    def tool_extra(self):
        """Settings the current tool (a Tool Chest tool) adds to what it
        measures: rise/drop, wall height and openings, the unit kept."""
        from . import measure_extra
        ex = {}
        for k in ("rise", "height", "openings"):
            v = self.style.get(k)
            if v in (None, ""):
                continue
            if isinstance(v, (int, float)):
                ex[k] = float(v)
                continue
            if k == "openings":
                got = measure_extra.parse_openings(str(v))
                if got:
                    ex[k] = got
                continue
            got = takeoff.parse_length(str(v))
            if got and got[0]:
                ex[k] = got[0] if not got[1] else takeoff.convert(
                    got[0], got[1], (self.scale() or {}).get("unit", "ft"))
        if self.style.get("unit") in measure_extra.LENGTH_UNITS:
            ex["to"] = self.style["unit"]
        return measure_extra.clean(ex)

    def _measure_payload(self, mtype, ppts, sc, extra=None, depth=None):
        """The add_* payload (with "_kind") for a measurement of `mtype`
        (length, area, volume) over page points `ppts`, or None."""
        from . import measure_extra
        unit = sc["unit"]
        extra = measure_extra.clean(dict(self.tool_extra(),
                                         **(extra or {})))
        color = list(self._color("add_line" if mtype == "length"
                                 else "add_polygon"))
        group = self.style.get("subject") or ""
        pts = [[q.x, q.y] for q in ppts]
        if mtype == "length":
            plan = takeoff.path_length(ppts) / sc["ppu"]
            mtype, value = measure_extra.run_value(plan, extra)
            kind = "add_line" if len(ppts) == 2 and mtype == "length" \
                else "add_polyline"
            fill = None
        elif mtype == "volume":
            if depth is None:
                depth = self.ask_depth(unit)
            if depth is None:
                return None
            extra = {k: v for k, v in extra.items() if k == "to"}
            value = takeoff.polygon_area(ppts) / sc["ppu"] ** 2 * depth
            kind = "add_polygon"
            fill = self.style.get("fill") or color
        else:
            extra = {k: v for k, v in extra.items() if k == "to"}
            value = takeoff.polygon_area(ppts) / sc["ppu"] ** 2
            kind = "add_polygon"
            fill = self.style.get("fill") or color
        value, unit_text = measure_extra.to_units(mtype, value, unit, extra)
        label = measure_extra.label_text(mtype, value, unit_text, group,
                                         extra, takeoff.fmt)
        payload = {"pts": pts, "color": color, "label": label,
                   "measure": {"type": mtype, "value": round(value, 4),
                               "unit": unit_text, "group": group},
                   "_kind": kind}
        if fill is not None:
            payload["fill"] = fill
        if extra:
            payload["extra"] = extra
        return payload

    def ask_wall(self, current=None):
        """Height and openings for a wall area, as measurement settings
        ({"height", "openings"}), or None if cancelled."""
        from .measure_extra import parse_openings
        sc = self.scale() or {}
        unit = sc.get("unit", "ft")
        cur = current or {}
        h0 = cur.get("height") or self.style.get("height") or \
            self.style.get("wall_height_text", "")
        text, ok = QInputDialog.getText(
            self, "Wall Area", f"Wall height (e.g. 9', 8'-6\", 2.7 m; "
            f"plain numbers are {unit}):",
            text=takeoff.fmt(h0, unit) if isinstance(h0, (int, float))
            else str(h0))
        if not ok:
            return None
        got = takeoff.parse_length(text)
        if not got or got[0] <= 0:
            QMessageBox.information(self, "Wall Area",
                                    "Enter a height, for example 9'.")
            return None
        height = takeoff.convert(got[0], got[1], unit)
        self.style["wall_height_text"] = text
        o0 = cur.get("openings")
        otext, ok = QInputDialog.getText(
            self, "Wall Area", "Openings to take out (sizes, e.g. "
            "\"3x7 x2, 6x4\", or an area; blank for none):",
            text=f"{o0:g}" if o0 else self.style.get("openings_text", ""))
        if not ok:
            return None
        openings = parse_openings(otext, unit)
        if openings is None:
            QMessageBox.information(
                self, "Wall Area", "Type openings as sizes, for example "
                "3x7 x2, 6x4 - or a plain area.")
            return None
        self.style["openings_text"] = otext
        return {"height": height, "openings": openings}

    def ask_depth(self, unit):
        """Depth (in drawing units) for a volume, or None if cancelled."""
        text, ok = QInputDialog.getText(
            self, "Volume", f"Depth or height (e.g. 4\", 0.5, 8'-0\"; "
            f"plain numbers are {unit}):", text=self.style.get("depth", ""))
        if not ok:
            return None
        got = takeoff.parse_length(text)
        if not got or got[0] <= 0:
            QMessageBox.information(self, "Volume",
                                    "Enter a depth, for example 4\".")
            return None
        self.style["depth"] = text
        return takeoff.convert(got[0], got[1], unit)

    def _measure_angle(self, ppts):
        if len(ppts) < 3:
            return 0
        deg = takeoff.angle(ppts)
        group = self.style.get("subject") or ""
        label = f"{deg:.1f}\u00b0"
        if group:
            label = f"{group}: {label}"
        payload = {"pts": [[q.x, q.y] for q in ppts],
                   "color": list(self._color("add_line")), "label": label,
                   "measure": {"type": "angle", "value": round(deg, 3),
                               "unit": "deg", "group": group}}
        n = self.apply_marks([(self.page, "add_polyline",
                               self._styled("add_polyline", payload))])
        if n:
            self.status.emit(f"Angle {deg:.1f}\u00b0")
        return n

    def _measure_circle(self, tool, pa, pb):
        """Radius (drag center to edge) or diameter (drag across)."""
        sc = self.scale(at=[pa])
        if not sc:
            QMessageBox.information(
                self, "Takeoff", "Set the scale for this page first.")
            return 0
        d = abs(pb - pa)
        if d < 2:
            return 0
        if tool == "measure_radius":
            c, r = pa, d
            mtype, value = "radius", d / sc["ppu"]
            label = "R " + takeoff.fmt(value, sc["unit"])
        else:
            c, r = fitz.Point((pa.x + pb.x) / 2, (pa.y + pb.y) / 2), d / 2
            mtype, value = "diameter", d / sc["ppu"]
            label = "\u2300 " + takeoff.fmt(value, sc["unit"])
        group = self.style.get("subject") or ""
        if group:
            label = f"{group}: {label}"
        payload = {"rect": [c.x - r, c.y - r, c.x + r, c.y + r],
                   "color": list(self._color("add_ellipse")), "label": label,
                   "measure": {"type": mtype, "value": round(value, 4),
                               "unit": sc["unit"], "group": group}}
        n = self.apply_marks([(self.page, "add_ellipse",
                               self._styled("add_ellipse", payload))])
        if n:
            self.status.emit(label)
        return n

    # ---- viewports and legends ---------------------------------------------------
    def add_viewport(self, pr, scale=None, name=None):
        """A region of the page with its own scale. `scale` is (label,
        ppu, unit); without it the user picks one."""
        if scale is None:
            presets = [(n, ppu, u) for fam in takeoff.PRESETS.values()
                       for n, (ppu, u) in fam]
            names = [n for n, _, _ in presets]
            text, ok = QInputDialog.getItem(
                self, "Viewport Scale", "Scale of the drawing in this box "
                "(pick one or type e.g. 3/4\" = 1'-0\"):", names, 4, True)
            if not ok or not text.strip():
                return 0
            found = takeoff.find_scales(text)
            hit = next((x for x in presets if x[0] == text), None)
            if hit:
                scale = hit
            elif found:
                scale = found[0]
            else:
                QMessageBox.information(self, "Viewport",
                                        "That isn't a scale I can read.")
                return 0
        if name is None:
            n = len(annotate.read_viewports(self.doc, self.page)) + 1
            name, ok = QInputDialog.getText(self, "Viewport", "Name:",
                                            text=f"Detail {n}")
            if not ok or not name.strip():
                return 0
        label, ppu, unit = scale
        n = self.apply_marks([(self.page, "set_scale", {
            "viewport": {"name": name.strip(), "rect": list(pr), "ppu": ppu,
                         "unit": unit, "label": label}})])
        if n:
            self.status.emit(self.noted(f"Viewport {name.strip()}: {label}"))
        return n

    def remove_viewport(self, name):
        return self.apply_marks([(self.page, "set_scale",
                                  {"delete_viewport": name})])

    def add_legend(self, pr, title="Legend", opts=None, ask=False):
        """A legend in page rect `pr`. `opts` (legend.clean_opts): all
        pages, tool sets, live, markup counts - asked with `ask` (the
        Legend tool)."""
        from . import legend
        if ask and opts is None:
            opts = self.ask_legend_opts()
            if opts is None:
                return 0
        opts = legend.clean_opts(opts)
        rows = legend.rows_for(self.doc, self.page, opts)
        if not rows:
            QMessageBox.information(self, "Legend",
                                    "There are no markups on this page yet.")
            return 0
        payload = {"rect": list(pr), "title": title, "rows": rows,
                   "author": settings.author(),
                   "style": settings.get("legend_style", "takeoff")}
        if opts:
            payload["opts"] = opts
        if self.style.get("layer"):
            payload["layer"] = self.style["layer"]
        self._live_legends = None
        return self.apply_marks([(self.page, "add_legend", payload)])

    def ask_legend_opts(self):
        """What a new legend shows: this page or the whole set, which tool
        sets, kept up to date, markup counts. None if cancelled."""
        from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox,
                                       QLabel, QListWidget, QListWidgetItem,
                                       QRadioButton, QVBoxLayout)
        from . import legend, toolchest
        chest = toolchest.load()
        dlg = QDialog(self)
        dlg.setWindowTitle("Legend")
        lay = QVBoxLayout(dlg)
        page = QRadioButton("This page's markups")
        whole = QRadioButton("Every page (totals for the whole set)")
        page.setChecked(not settings.get("legend_all_pages", False))
        whole.setChecked(bool(settings.get("legend_all_pages", False)))
        lay.addWidget(page)
        lay.addWidget(whole)
        lay.addWidget(QLabel("Only these tool sets (none ticked: every "
                             "markup):"))
        lst = QListWidget()
        last = set(settings.get("legend_sets") or [])
        for g in chest:
            it = QListWidgetItem(g)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if g in last else Qt.Unchecked)
            lst.addItem(it)
        lst.setMaximumHeight(110)
        lay.addWidget(lst)
        live = QCheckBox("Keep it up to date as markups are added")
        live.setChecked(settings.get("legend_live", True))
        count = QCheckBox("Show how many markups")
        count.setChecked(bool(settings.get("legend_count", False)))
        lay.addWidget(live)
        lay.addWidget(count)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec() != QDialog.Accepted:
            return None
        sets = [lst.item(i).text() for i in range(lst.count())
                if lst.item(i).checkState() == Qt.Checked]
        settings.set("legend_all_pages", whole.isChecked())
        settings.set("legend_sets", sets)
        settings.set("legend_live", live.isChecked())
        settings.set("legend_count", count.isChecked())
        opts = {"scope": "all" if whole.isChecked() else "page",
                "live": live.isChecked(), "count": count.isChecked()}
        if sets:
            opts["sets"] = sets
            opts["tools"] = legend.set_tools(chest, sets)
        return opts

    def _legend_pages(self, touched, kinds):
        """Pages whose live legends an edit on `touched` pages changes."""
        if not touched or kinds <= {"add_legend", "delete_annot"} and \
                "add_legend" in kinds:
            return set()                      # a legend redrawing itself
        from . import legend
        if getattr(self, "_live_legends", None) is None or \
                self._live_legends[0] is not self.doc:
            try:
                self._live_legends = (self.doc, legend.live_pages(self.doc))
            except Exception:
                return set()
        out = set()
        for pno, scopes in self._live_legends[1].items():
            if "all" in scopes or pno in touched:
                out.add(pno)
        return out

    def refresh_legends(self):
        from . import legend
        marks = legend.refresh_marks(self.doc, self.page)
        return self.apply_marks(marks) if marks else 0

    # ---- auto takeoff ---------------------------------------------------------------
    def _room_payload(self, room):
        """An area measurement for a room found by autotakeoff."""
        color = list(self._color("add_polygon"))
        group = self.style.get("subject") or room["name"] or ""
        value, unit = room["value"], room["unit"]
        label = f"{_c2(value):,.2f} {unit}"
        if room.get("per_tag"):
            label += f" (per tag; traced {room['traced_value']:,.0f})"
        if room.get("detail_scale"):
            label += f" (at detail scale {room['detail_scale']})"
        if room["name"] and room["name"] != group:
            label = f"{room['name']}: {label}"
        if group:
            label = f"{group}: {label}"
        ppts = [annotate.to_page(self.pg, q) for q in room["pts"]]
        payload = {"pts": [[q.x, q.y] for q in ppts], "color": color,
                   "fill": self.style.get("fill") or color, "label": label,
                   "measure": {"type": "area", "value": round(value, 4),
                               "unit": unit, "group": group,
                               "method": "auto area (tag area)" if
                               room.get("per_tag") else "auto area"}}
        return self._styled("add_polygon", payload)

    def trace_length(self, pt):
        """Trace Length tool: measure the drawn line run at screen point
        `pt`."""
        from . import vector
        pts, closed = vector.trace(self.snap_index(), (pt.x, pt.y),
                                   tol=8.0 / max(self.zoom, 0.05))
        if not pts:
            self.status.emit("No drawn line there - click right on a line.")
            return 0
        ppts = [annotate.to_page(self.pg, fitz.Point(p)) for p in pts]
        self.method_hint = "trace length"
        try:
            n = self._measure("length", ppts)
        finally:
            self.method_hint = None
        if n:
            self.status.emit(f"Traced {len(pts) - 1} segment(s)" +
                             (" (closed loop)" if closed else ""))
        return n

    # ---- Trace Outline (app/trace_outline.py) ----------------------------------
    def trace_index(self):
        """The page's drawn paths for Trace Outline, built once per page."""
        from . import trace_outline
        key = (id(self.doc), self.page, self.pg.rotation)
        cache = getattr(self, "_trace_cache", None)
        if cache is None or cache[0] != key:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                idx = trace_outline.TraceIndex.from_page(self.pg)
            except Exception:
                log.exception("trace outline index for page %d", self.page)
                idx = trace_outline.TraceIndex([])
            finally:
                QApplication.restoreOverrideCursor()
            cache = self._trace_cache = (key, idx)
            self._trace_refs = []
        return cache[1]

    def _trace_snap(self, pt, anchor=None, shift=False, alt=False):
        """Trace Outline: the click lands on the nearest drawn corner, or
        else on the nearest drawn edge (Shift = straight, Alt = free)."""
        if shift and anchor is not None:
            return snap.ortho(anchor, pt)
        if alt:
            return pt
        s = self.trace_index().snap((pt.x, pt.y),
                                    SNAP_PX * 1.2 / max(self.zoom, 0.05))
        if s is None:
            return pt
        from . import trace_outline
        q = fitz.Point(s.x, s.y)
        self._snap_hit = (q, snap.ENDPOINT if s.kind == trace_outline.VERTEX
                          else snap.ONLINE)
        return q

    def trace_click(self, pt, follow=True):
        """Add a Trace Outline point at screen point `pt` (already
        snapped). With `follow`, when the last point and this one are on
        the same drawn line, the line's corners between them go in too.
        Returns how many points were added."""
        from . import trace_outline
        idx = self.trace_index()
        refs = getattr(self, "_trace_refs", None)
        if refs is None or not self._pts:
            refs = self._trace_refs = []
        here = idx.snap((pt.x, pt.y), 0.05)
        added = 0
        if follow and self._pts and settings.get("trace_follow", True) \
                is not False:
            last = self._pts[-1]
            prev = next((r for x, y, r in reversed(refs)
                         if abs(x - last.x) < 1e-6 and abs(y - last.y) < 1e-6),
                        None)
            mids = idx.between(prev, here) if prev and here else None
            for q in mids or ():
                self._pts.append(fitz.Point(q[0], q[1]))
                added += 1
        first = self._pts[0] if self._pts else None
        if first is not None and len(self._pts) >= 3 and \
                abs(first.x - pt.x) + abs(first.y - pt.y) < 0.5:
            # back on the first point: the outline is closed - finish it
            self._finish_points()
            return added
        self._pts.append(pt)
        added += 1
        if here is not None:
            refs.append((pt.x, pt.y, here))
        ppts = [annotate.to_page(self.pg, q) for q in self._pts]
        sc = self.scale(at=ppts)
        if sc and len(self._pts) >= 2:
            self.status.emit(trace_outline.readout(ppts, sc["ppu"],
                                                   sc["unit"], takeoff.fmt))
        return added

    def auto_area(self, pt):
        """Auto Area tool: trace the room clicked at screen point `pt`."""
        from . import autotakeoff
        sc = self.scale(at=[annotate.to_page(self.pg, pt)])
        if not sc:
            QMessageBox.information(
                self, "Auto Area", "Set the scale for this page first "
                "(Takeoff > Set Scale or Auto Scale).")
            return 0
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            room = autotakeoff.room_at(self.pg, sc, pt)
        except autotakeoff.AutoTakeoffError as e:
            QApplication.restoreOverrideCursor()
            self.status.emit(str(e))
            QMessageBox.information(self, "Auto Area", str(e))
            return 0
        except Exception:
            QApplication.restoreOverrideCursor()
            log.exception("auto area failed")
            QMessageBox.warning(self, "Auto Area",
                                "Couldn't trace that room.")
            return 0
        QApplication.restoreOverrideCursor()
        n = self.apply_marks([(self.page, "add_polygon",
                               self._room_payload(room))])
        if n:
            msg = f"{room['name'] or 'Auto Area'}: " \
                  f"{_c2(room['value']):,.2f} {room['unit']}"
            if room["tag_sf"]:
                msg += f" (tag says {room['tag_sf']:,.0f} SF)"
            self.status.emit(msg)
        return n

    def auto_takeoff_rooms(self):
        """Take off every tagged room on this page. Returns
        (found, missed) as autotakeoff.all_rooms gives them, or None."""
        from . import autotakeoff
        from PySide6.QtWidgets import QProgressDialog
        sc = self.scale()
        if not sc:
            QMessageBox.information(
                self, "Auto Takeoff", "Set the scale for this page first "
                "(Takeoff > Set Scale or Auto Scale).")
            return None
        dlg = QProgressDialog("Finding rooms…", "Cancel", 0, 100, self)
        dlg.setWindowTitle("Auto Takeoff")
        dlg.setMinimumDuration(300)

        def progress(i, total):
            dlg.setMaximum(max(1, total))
            dlg.setValue(i)
            QApplication.processEvents()
            return not dlg.wasCanceled()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            found, missed = autotakeoff.all_rooms(self.pg, sc, progress)
        except autotakeoff.AutoTakeoffError as e:
            QApplication.restoreOverrideCursor()
            dlg.close()
            QMessageBox.information(self, "Auto Takeoff", str(e))
            return None
        QApplication.restoreOverrideCursor()
        canceled = dlg.wasCanceled()
        dlg.close()
        if canceled:
            return None
        from . import settings
        if found and settings.get("rooms_use_tag_area", True):
            autotakeoff.prefer_tags(found)
        if found:
            self.apply_marks([(self.page, "add_polygon",
                               self._room_payload(r)) for r in found])
        return found, missed

    # ---- commit: clicks and pen -----------------------------------------------------------
    def commit_click(self, tool, pt):
        pp = annotate.to_page(self.pg, pt)
        if tool == "add_note":
            text, ok = QInputDialog.getMultiLineText(self, "Sticky Note",
                                                     "Note:")
            if not ok or not text.strip():
                return 0
            return self._mark("add_note", pt=[pp.x, pp.y], text=text)
        if tool == "count":
            n = 1 + sum(1 for it in annotate.takeoff_items(self.doc)
                        if it["type"] == "count" and it["page"] == self.page
                        and it["group"] == self.count_group)
            return self._mark("add_count", pt=[pp.x, pp.y], n=n,
                              measure={"type": "count", "value": 1,
                                       "unit": "ea",
                                       "group": self.count_group})
        if tool == "auto_area":
            return self.auto_area(pt)
        if tool == "trace_length":
            return self.trace_length(pt)
        if tool == "edit_text":
            return self.edit_text_at(pt)
        if tool == "fs_text":
            text, ok = QInputDialog.getText(self, "Fill Text", "Text:")
            if not ok or not text.strip():
                return 0
            return self._mark("add_text", pt=[pp.x, pp.y + 4], text=text,
                              size=self.style.get("size") or 11,
                              color=list(self.style.get("color") or (0, 0, 0)))
        if tool == "fs_date":
            import datetime
            text = datetime.date.today().strftime("%m/%d/%Y")
            return self._mark("add_text", pt=[pp.x, pp.y + 4], text=text,
                              size=11, color=[0, 0, 0])
        if tool == "fs_check":
            s = 6
            return self._mark("add_ink", strokes=[[
                [pp.x - s, pp.y], [pp.x - s / 3, pp.y + s * 0.8],
                [pp.x + s, pp.y - s]]], width=2,
                color=list(self.style.get("color") or (0, 0, 0)),
                subject="Check")
        if tool == "date_stamp":
            import datetime
            text = (f"{(self.style.get('subject') or 'RECEIVED').upper()}\n"
                    f"{datetime.datetime.now():%b %d, %Y %I:%M %p}\n"
                    f"{settings.author()}")
            r = fitz.Rect(pp.x, pp.y, pp.x + 150, pp.y + 50)
            return self._mark("add_textbox", rect=list(r), text=text,
                              size=10, border=True, width=1.5,
                              color=list(self.style.get("color") or
                                         (0.8, 0, 0)),
                              subject="Date Stamp")
        return 0

    def commit_stroke(self, stroke):
        if len(stroke) < 2:
            return 0
        pts = [annotate.to_page(self.pg, q) for q in stroke[::2] + stroke[-1:]]
        return self._mark("add_ink", strokes=[[[q.x, q.y] for q in pts]],
                          width=2)

    # ---- editing existing content ----------------------------------------------------
    def span_at(self, pt):
        """The text span under a screen point: (bbox, text, size, rgb)."""
        for b in self.pg.get_text("dict")["blocks"]:
            for line in b.get("lines", []):
                for s in line["spans"]:
                    # extraction is unrotated; pt and the result are screen
                    r = annotate.from_page(self.pg, fitz.Rect(s["bbox"]))
                    if r.contains(pt) and s["text"].strip():
                        c = s.get("color", 0)
                        rgb = [((c >> 16) & 255) / 255, ((c >> 8) & 255) / 255,
                               (c & 255) / 255]
                        return r, s["text"], s["size"], rgb
        return None

    # ---- Color Takeoff By (Nov 4 takeoff list #6) ------------------------------
    PALETTE = [(0, 114, 178), (230, 159, 0), (0, 158, 115), (204, 121, 167),
               (86, 180, 233), (213, 94, 0), (240, 228, 66), (90, 90, 90)]

    def color_by_rows(self):
        """[(rect, key)] for this page's takeoff, by the color-by setting."""
        if not self.color_by:
            return []
        rows = []
        unpriced = None
        if self.color_by == "priced":
            unpriced = {tuple(round(c, 1) for c in r)
                        for r in self.unpriced_rects()}
        for it in annotate.takeoff_items(self.doc):
            if it["page"] != self.page:
                continue
            for a in annotate.find_annots(self.pg, it["ref"])[:1]:
                if self.color_by == "item":
                    key = it.get("group") or it["type"].title()
                elif self.color_by == "status":
                    key = annotate.status_of(self.doc, a) or "No status"
                else:
                    r = tuple(round(c, 1) for c in a.rect)
                    key = "Not priced" if r in unpriced else "Priced"
                rows.append((tuple(a.rect), key))
        return rows

    def color_by_legend(self):
        """[(key, (r, g, b))] in a stable order."""
        keys = sorted({k for _r, k in self.color_by_rows()})
        fixed = {"Priced": (0, 158, 115), "Not priced": (213, 94, 0),
                 "No status": (150, 150, 150)}
        return [(k, fixed.get(k, self.PALETTE[i % len(self.PALETTE)]))
                for i, k in enumerate(keys)]

    def set_color_by(self, mode):
        self.color_by = mode or None
        self.update()
        return self.color_by

    def _paint_color_by(self, p):
        legend = self.color_by_legend()
        col = dict(legend)
        for r, key in self.color_by_rows():
            c = col.get(key, (0, 0, 0))
            q = self._q(annotate.from_page(self.pg, fitz.Rect(r)))
            p.setPen(QPen(QColor(*c), 3))
            p.setBrush(QColor(c[0], c[1], c[2], 45))
            p.drawRect(q.adjusted(-3, -3, 3, 3))
        p.setBrush(Qt.NoBrush)
        if not legend:
            return
        fm = p.fontMetrics()
        h = fm.height() + 4
        w = max(fm.horizontalAdvance(k) for k, _c in legend) + 34
        vis = self.visibleRegion().boundingRect()
        x, y = vis.left() + 10, vis.bottom() - 10 - h * len(legend) - 8
        p.setPen(QPen(QColor(120, 120, 120)))
        p.setBrush(QColor(255, 255, 255, 235))
        p.drawRoundedRect(QRect(x, y, w, h * len(legend) + 8), 4, 4)
        for i, (k, c) in enumerate(legend):
            yy = y + 4 + i * h
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(*c))
            p.drawRect(QRect(x + 8, yy + 3, 14, h - 6))
            p.setPen(QPen(QColor(30, 30, 30)))
            p.drawText(QRect(x + 28, yy, w - 30, h), Qt.AlignVCenter, k)
        p.setBrush(Qt.NoBrush)

    # ---- Show Only This Item (Nov 4 takeoff list #7) ---------------------------
    def set_isolate(self, group):
        """Dim everything but one takeoff item's markups (Esc stops)."""
        self.isolate = group or None
        self.update()
        if group:
            self.status.emit(f"Showing only {group} - Esc shows everything")
        return self.isolate

    def isolate_rects(self):
        if not self.isolate:
            return []
        out = []
        for it in annotate.takeoff_items(self.doc):
            if it["page"] == self.page and it.get("group") == self.isolate:
                for a in annotate.find_annots(self.pg, it["ref"])[:1]:
                    out.append(tuple(a.rect))
        return out

    def isolate_selected(self):
        from . import measure_tools
        sel = measure_tools.selected_measure(self) if self.selected else None
        group = (sel or {}).get("group") or (
            self._selected_count_group() if self.selected else None)
        if not group:
            self.status.emit("Select a takeoff measurement first")
            return None
        return self.set_isolate(group)

    # ---- arcs while drawing (Nov 4 takeoff list #5) ---------------------------
    ARC_STEPS = 16

    def toggle_arc(self):
        self.arc_mode = not getattr(self, "arc_mode", False)
        self._arc_mid = None
        self.status.emit("Arc: click a point on the curve, then its end "
                         "(Tab: straight again)" if self.arc_mode else
                         "Straight segments")
        return self.arc_mode

    def arc_click(self, pt):
        """Arc mode: first click = a point on the curve, second = its end;
        the arc goes in as short straight pieces (measured exactly enough:
        16 pieces are within 0.2 % of a true arc's length)."""
        if self._arc_mid is None:
            self._arc_mid = pt
            self.update()
            return 0
        pts = arc_points(self._pts[-1], self._arc_mid, pt, self.ARC_STEPS)
        self._arc_mid = None
        self._pts.extend(pts[1:])
        self.update()
        return len(pts) - 1

    def edit_text_here(self, pt):
        """Edit the PDF text under `pt` in place (Edit Text tool). False
        when there's no text there."""
        try:
            if self.block_at(pt) is None:
                return False
        except Exception:                                 # noqa: BLE001
            return False
        self.want_tool.emit("edit_text")
        if self.tool != "edit_text":
            self.set_tool("edit_text")
        ctl = getattr(self, "editctl", None)
        if ctl is None or self.tool != "edit_text":
            return False
        ctl.open(pt)
        return True

    def block_at(self, pt):
        """The paragraph under a screen point: {rect (page coords), text,
        size, color, font, bold, italic, lines, align, line_height} or
        None. Lines are joined into running text (a hyphen at a line end
        joins the word)."""
        for b in self.pg.get_text("dict")["blocks"]:
            if b.get("type", 0) != 0:
                continue
            r = annotate.from_page(self.pg, fitz.Rect(b["bbox"]))
            if not r.contains(pt):
                continue
            lines = [ln for ln in b.get("lines", [])
                     if "".join(s["text"] for s in ln["spans"]).strip()]
            if not lines:
                return None
            parts = []
            rich = ""
            right = b["bbox"][2]
            for k, ln in enumerate(lines):
                t = "".join(s["text"] for s in ln["spans"]).strip()
                if parts and parts[-1].endswith("-"):
                    parts[-1] = parts[-1][:-1] + t
                else:
                    parts.append(t)
                # a line that ends well short of the paragraph's right
                # edge, though the next word would have fitted, ended with
                # a hard return (a heading, a list item)
                if k + 1 < len(lines):
                    nxt = "".join(s["text"] for s in lines[k + 1]["spans"])
                    first = (nxt.strip().split() or [""])[0]
                    sz = lines[k + 1]["spans"][0]["size"] if \
                        lines[k + 1]["spans"] else 10
                    room = right - ln["bbox"][2]
                    need = (len(first) + 1) * sz * 0.5
                    if t.endswith("-") and room < need:
                        rich += t[:-1]
                    else:
                        rich += t + ("\n" if room > need + sz else " ")
                else:
                    rich += t
            spans = [s for ln in lines for s in ln["spans"]
                     if s["text"].strip()]
            main = max(spans, key=lambda s: len(s["text"]))
            c = main.get("color", 0)
            flags = main.get("flags", 0)
            ys = [ln["bbox"][1] for ln in lines]
            lh = (ys[-1] - ys[0]) / (len(ys) - 1) if len(ys) > 1 else None
            x0s = [ln["bbox"][0] for ln in lines]
            x1s = [ln["bbox"][2] for ln in lines]
            bw = b["bbox"][2] - b["bbox"][0]
            centered = all(abs((a + z) / 2 - (b["bbox"][0] + b["bbox"][2])
                               / 2) < 2 for a, z in zip(x0s, x1s)) and \
                len(lines) > 1 and min(z - a for a, z in zip(x0s, x1s)) < \
                bw * 0.9
            justified = len(lines) > 2 and all(
                abs(z - b["bbox"][2]) < 1.5 for z in x1s[:-1])
            return {"rect": list(b["bbox"]), "text": " ".join(parts),
                    "rich_text": rich,
                    "size": main["size"],
                    "color": [((c >> 16) & 255) / 255, ((c >> 8) & 255) / 255,
                              (c & 255) / 255],
                    "font": main.get("font", ""), "bold": bool(flags & 16),
                    "italic": bool(flags & 2), "lines": len(lines),
                    "align": "center" if centered else
                    "justify" if justified else "left",
                    "line_height": lh}
        return None

    def edit_text_at(self, pt, new_text=None, paragraph=None):
        """Edit Text tool. A click in a paragraph (two or more lines) edits
        the whole paragraph, rewrapped to its box in its own font where
        possible; a single line edits just that text."""
        blk = self.block_at(pt) if paragraph is not False else None
        if blk and (blk["lines"] > 1 or paragraph):
            if new_text is None:
                new_text, ok = QInputDialog.getMultiLineText(
                    self, "Edit Paragraph", "Text (rewrapped to the "
                    "paragraph's width):", blk["text"])
                if not ok or new_text == blk["text"]:
                    return 0
            return self.apply_marks([(self.page, "replace_block", {
                "rect": blk["rect"], "text": new_text,
                "size": _c2(blk["size"]), "color": blk["color"],
                "font": blk["font"], "bold": blk["bold"],
                "italic": blk["italic"], "align": blk["align"],
                "line_height": blk["line_height"]})])
        span = self.span_at(pt)
        if span is None:
            self.status.emit("No text there. Click directly on a word.")
            return 0
        r, text, size, rgb = span
        if new_text is None:
            new_text, ok = QInputDialog.getText(
                self, "Edit Text",
                "New text (it is rewritten in a standard font):", text=text)
            if not ok or new_text == text:
                return 0
        return self.apply_marks([(self.page, "replace_span", {
            "rect": list(annotate.to_page(self.pg, r)), "text": new_text,
            "size": _c2(size), "color": rgb})])

    def _selected_op(self, **changes):
        if not self.selected:
            return 0
        return self.apply_marks([(self.page, "set_annot",
                                  {**self.selected["ref"], **changes})])

    # ---- AI Takeoff zones (Nov 1) -------------------------------------------
    def add_zone(self, rect, kind):
        """Draw an AI Takeoff zone ("include": only here, "exclude": leave
        out) on this page. Returns 1 when added."""
        from . import zones
        r = fitz.Rect(rect).normalize()
        if r.width < 4 or r.height < 4:
            return 0
        n = self.apply_marks([zones.mark(self.page, r, kind)])
        if n:
            self.status.emit(
                "Zone added - AI Takeoff keeps only what it finds inside the "
                "green boxes on this sheet" if kind == "include" else
                "Zone added - AI Takeoff leaves out what it finds inside "
                "the red boxes on this sheet")
        return n

    def clear_zones(self):
        from . import zones
        refs = zones.refs_on_page(self.doc, self.page)
        if not refs:
            self.status.emit("No AI Takeoff zones on this page.")
            return 0
        return self.apply_marks([(self.page, "delete_annot", r)
                                 for r in refs])

    # ---- accept / deny AI takeoff on the drawing (Nov 1) ---------------------
    def ai_open_refs(self):
        """Refs of the selected markups that AI Takeoff (or a count search)
        found and nobody has accepted yet - what A / D decide."""
        if self.doc is None:
            return []
        out = []
        for ref in self.selected_refs():
            for a in annotate.find_annots(self.pg, ref):
                m = str(annotate.audit_of(self.doc, a).get("method") or "")
                if m.startswith(("AI takeoff", "auto")) and \
                        "(reviewed)" not in m and \
                        annotate.status_of(self.doc, a) != "Accepted":
                    out.append(ref)
                    break
        return out

    def _review_session(self):
        """The AI Takeoff run's review session when its result is here
        (so a room's CHECK item is decided with its outline), else None."""
        win = self.window()
        dlg = getattr(win, "_ai_dlg", None)
        res = getattr(dlg, "result", None) if dlg is not None else None
        if not res or getattr(getattr(win, "_view", None), "doc",
                              None) is not self.doc:
            return None, None
        rq = getattr(dlg, "_review_dlg", None)
        sess = getattr(rq, "session", None) if rq is not None else None
        if sess is None or sess.res is not res:
            from . import review_queue
            from . import settings
            sess = getattr(dlg, "_drawing_session", None)
            if sess is None or sess.res is not res or sess.doc is not self.doc:
                sess = review_queue.Session(self.doc, res, win=win,
                                            who=settings.author() or
                                            "reviewer")
                dlg._drawing_session = sess
        return sess, rq

    def decide_selected(self, accept=True):
        """Accept (solid, AI badge off, in the totals) or deny (deleted)
        the selected AI markups, as the Review Queue does. Returns how
        many were decided."""
        refs = self.ai_open_refs()
        if not refs:
            self.status.emit("Select a markup AI Takeoff found (dashed, with "
                             "the AI badge) first.")
            return 0
        sess, rq = self._review_session()
        plain = list(refs)
        n = 0
        if sess is not None:
            from . import review_queue
            entries = review_queue.build(self.doc, sess.res)
            for ref in refs:
                e = next((e for e in entries if e.get("mark") and
                          e["mark"].get("ref") == ref and
                          e["mark"].get("page") == self.page), None)
                if e is None:
                    continue
                (sess.accept if accept else sess.deny)(e)
                plain.remove(ref)
                n += 1
        if plain:
            if accept:
                ops = [(self.page, "set_annot",
                        dict(r, status="Accepted", dashes=[], badge=False))
                       for r in plain]
            else:
                ops = [(self.page, "delete_annot", dict(r)) for r in plain]
            if self.apply_marks(ops):
                n += len(plain)
        if not accept:
            self.selected = None
            self.multi = []
        if rq is not None:
            try:
                rq.refresh()
            except Exception:                             # noqa: BLE001
                pass
        self.update()
        self.status.emit(
            f"{n} AI markup(s) " + ("accepted - in the totals now" if accept
                                    else "denied - deleted (Edit > Undo "
                                    "brings them back)"))
        return n

    def delete_selected(self):
        refs = self.selected_refs()
        if not refs:
            return 0
        self.selected = None
        self.multi = []
        return self.apply_marks([(self.page, "delete_annot", r)
                                 for r in refs])

    def move_selected(self, dx, dy):
        if not self.selected:
            return 0
        r = fitz.Rect(self.selected["rect"]) + (dx, dy, dx, dy)
        return self._selected_op(rect=list(r))

    def edit_selected_comment(self):
        found = annotate.find_annots(self.pg, self.selected["ref"]) \
            if self.selected else []
        if not found:
            return 0
        current = (found[0].info or {}).get("content", "")
        text, ok = QInputDialog.getMultiLineText(self, "Comment", "Comment:",
                                                 current)
        if ok and text != current:
            return self._selected_op(note=text)
        return 0

    def edit_selected_text(self):
        found = annotate.find_annots(self.pg, self.selected["ref"]) \
            if self.selected else []
        if not found:
            return 0
        current = (found[0].info or {}).get("content", "")
        text, ok = QInputDialog.getMultiLineText(self, "Edit Text", "Text:",
                                                 current)
        if ok and text != current:
            return self._selected_op(text=text)
        return 0

    def recolor_selected(self):
        c = QColorDialog.getColor(parent=self)
        if c.isValid():
            return self._selected_op(color=[c.redF(), c.greenF(), c.blueF()])
        return 0

    def fill_field(self, w, value=None):
        """Fill in a form field (asks for the value if not given)."""
        ft = w.field_type
        if value is None:
            if ft in (fitz.PDF_WIDGET_TYPE_CHECKBOX,
                      fitz.PDF_WIDGET_TYPE_RADIOBUTTON):
                value = w.field_value in (False, "Off", "", None)
            elif ft in (fitz.PDF_WIDGET_TYPE_COMBOBOX,
                        fitz.PDF_WIDGET_TYPE_LISTBOX):
                choices = [c if isinstance(c, str) else c[-1]
                           for c in (w.choice_values or [])]
                if not choices:
                    return 0
                cur = choices.index(w.field_value) \
                    if w.field_value in choices else 0
                value, ok = QInputDialog.getItem(self, w.field_name,
                                                 "Choose:", choices, cur,
                                                 False)
                if not ok:
                    return 0
            elif ft == fitz.PDF_WIDGET_TYPE_TEXT:
                value, ok = QInputDialog.getText(self, w.field_name, "Value:",
                                                 text=str(w.field_value or ""))
                if not ok:
                    return 0
            else:
                self.status.emit("That kind of field can't be filled here.")
                return 0
        return self.apply_marks([(self.page, "set_field",
                                  {"name": w.field_name, "value": value})])

    # ---- snapshot ---------------------------------------------------------------------
    SNAPSHOT_DPI = 200
    SNAPSHOT_MAX_PX = 24_000_000      # ~72 MB as an RGB image

    @classmethod
    def snapshot_dpi(cls, rect):
        """The dpi for an area `rect` (points): 200, or less so the image
        stays under SNAPSHOT_MAX_PX (PM review NW-01: a whole 36 x 24 sheet
        at 200 dpi is ~104 MB - too big for some clipboards)."""
        w, h = abs(rect.width) / 72, abs(rect.height) / 72
        dpi = cls.SNAPSHOT_DPI
        if w * h * dpi * dpi > cls.SNAPSHOT_MAX_PX:
            dpi = int((cls.SNAPSHOT_MAX_PX / max(w * h, 1e-6)) ** 0.5)
        return max(36, dpi)

    def snapshot(self, rect):
        """Copy the area `rect` (screen coordinates) to the clipboard, show
        it was taken (the area flashes; the window offers Save as PNG) and
        keep it for Save Snapshot as PNG."""
        dpi = self.snapshot_dpi(rect)
        pix = self.pg.get_pixmap(dpi=dpi, clip=rect, alpha=False)
        img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                     QImage.Format_RGB888).copy()
        img.setDotsPerMeterX(int(dpi / 0.0254))
        img.setDotsPerMeterY(int(dpi / 0.0254))
        QApplication.clipboard().setImage(img)
        self._snapshot_png = pix.tobytes("png")
        small = " (a large area, so at {} dpi)".format(dpi) \
            if dpi < self.SNAPSHOT_DPI else ""
        self.status.emit(f"Snapshot copied: {pix.width} x {pix.height} px"
                         f"{small}. Paste with Ctrl+V here or in another "
                         "app.")
        self._snap_flash = fitz.Rect(rect)
        self.update()
        QTimer.singleShot(600, self._end_snap_flash)
        self.snapshot_taken.emit(pix.width, pix.height, dpi)
        return 1

    def _end_snap_flash(self):
        self._snap_flash = None
        self.update()

    def save_snapshot_png(self, path):
        """The last snapshot as a PNG file. Returns the path or None."""
        data = getattr(self, "_snapshot_png", None)
        if not data:
            return None
        with open(path, "wb") as f:
            f.write(data)
        return path

    def paste_image(self, at=None):
        """Paste the clipboard image onto the page (at a screen point, or
        the middle of the page). Returns 1 if something was pasted."""
        from PySide6.QtCore import QBuffer, QIODevice
        img = QApplication.clipboard().image()
        if img.isNull():
            self.status.emit("Nothing to paste: the clipboard has no image.")
            return 0
        dpm = img.dotsPerMeterX()
        dpi = dpm * 0.0254 if dpm > 0 else 96
        w, h = img.width() * 72 / dpi, img.height() * 72 / dpi
        page_r = self.pg.rect
        scale = min(1.0, 0.9 * page_r.width / w, 0.9 * page_r.height / h)
        w, h = w * scale, h * scale
        c = at or fitz.Point(page_r.width / 2, page_r.height / 2)
        r = fitz.Rect(c.x - w / 2, c.y - h / 2, c.x + w / 2, c.y + h / 2)
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        img.save(buf, "PNG")
        data = base64.b64encode(bytes(buf.data())).decode("ascii")
        return self.apply_marks([(self.page, "add_image", {
            "rect": list(annotate.to_page(self.pg, r)), "data": data})])

    # ---- takeoff: symbols ------------------------------------------------------------
    def count_symbol(self, rect, group=None, all_pages=None, review=False):
        """Count every copy of the symbol inside `rect` (screen coords).
        With `review`, copies at any angle and slightly different sizes
        are found too, and nothing is counted until you've checked them
        in the review list (lowest confidence first)."""
        from . import autocount
        if rect.width < 4 or rect.height < 4:
            return 0
        from .aitakeoff import picture_count_on
        if not picture_count_on():
            # patent design-rule switch: no picture matching (said on the
            # status bar - nothing modal, nothing blocks)
            self.status.emit("Counting by picture is turned off (setting "
                             "'picture_count'). Count by tag or label "
                             "instead.")
            return 0
        tpl = autocount.symbol_template(self.pg, rect)
        if group is None:
            group, ok = QInputDialog.getText(self, "Count Symbol",
                                             "Name for this symbol:",
                                             text=self.count_group)
            if not ok or not group.strip():
                return 0
            group = group.strip()
        try:                  # kept, so its uncounted copies can be shown
            from . import uncounted
            uncounted.save_sample(self.doc, group, tpl)
        except Exception:
            log.warning("count sample not kept", exc_info=True)
        if all_pages is None:
            all_pages = self.doc.page_count > 1 and QMessageBox.question(
                self, "Count Symbol", "Search every page? (No = this page)") \
                == QMessageBox.Yes
        pages = None if all_pages else {self.page}
        if review:
            return self._count_review(tpl, group, pages)
        self.setCursor(Qt.WaitCursor)
        try:
            hits = autocount.find_symbols(self.doc, tpl, 0.8, pages)
        finally:
            self.setCursor(Qt.CrossCursor)
        marks = autocount.count_marks(hits, group, self.doc,
                                      self._color("add_count"))
        n = self.apply_marks(marks)
        self.status.emit(f"Found {len(hits)} × {group}")
        return n

    def count_from_picture(self, image_bytes, group=None, all_pages=None,
                           exec_review=True):
        """Takeoff > Count From a Picture (picsearch.py): the picture is
        sized to this sheet's symbols, then found like Count Symbol and
        checked in the review list."""
        from . import picsearch
        from .aitakeoff import picture_count_on
        if not picture_count_on():
            self.status.emit("Counting by picture is turned off (setting "
                             "'picture_count'). Count by tag or label "
                             "instead.")
            return 0
        self.setCursor(Qt.WaitCursor)
        try:
            tpl, _px, _hits = picsearch.template_for(self.doc, image_bytes,
                                                     self.page)
        except (ValueError, RuntimeError) as e:
            self.setCursor(Qt.CrossCursor if self.tool else Qt.ArrowCursor)
            QMessageBox.information(self, "Count From a Picture", str(e))
            return 0
        self.setCursor(Qt.CrossCursor if self.tool else Qt.ArrowCursor)
        if group is None:
            group, ok = QInputDialog.getText(self, "Count From a Picture",
                                             "Name for this symbol:",
                                             text=self.count_group)
            if not ok or not group.strip():
                return 0
            group = group.strip()
        try:
            from . import uncounted
            uncounted.save_sample(self.doc, group, tpl)
        except Exception:
            log.warning("count sample not kept", exc_info=True)
        if all_pages is None:
            all_pages = self.doc.page_count > 1 and QMessageBox.question(
                self, "Count From a Picture",
                "Search every page? (No = this page)") == QMessageBox.Yes
        pages = None if all_pages else {self.page}
        return self._count_review(tpl, group, pages, exec_review)

    def _count_review(self, tpl, group, pages, exec_review=True):
        """Find copies of `tpl` and count the ones checked in the review
        list (Count Symbol with review, Count From a Picture)."""
        from . import autocount as autocount_review
        self.setCursor(Qt.WaitCursor)
        try:
            hits = autocount_review.find(self.doc, tpl, pages=pages)
        except Exception as e:
            self.setCursor(Qt.CrossCursor)
            QMessageBox.warning(self, "Count Symbol", str(e))
            return 0
        self.setCursor(Qt.CrossCursor)
        dlg = autocount_review.CountReviewDialog(self.doc, hits, group,
                                                self)
        try:
            from . import count_triage
            count_triage.attach(dlg)
        except Exception:
            log.warning("count triage controls", exc_info=True)
        try:
            from . import second_symbol
            second_symbol.wire(dlg, group)
        except Exception:
            log.warning("second symbol button", exc_info=True)
        dlg.go_to.connect(lambda p, r: self.go_to(p))
        self._last_review = dlg
        if not exec_review:
            return dlg
        if not dlg.exec():
            return 0
        marks = autocount_review.review_marks(
            dlg.accepted(), group, self.doc, self._color("add_count"))
        n = self.apply_marks(marks)
        self.status.emit(f"Counted {len(dlg.accepted())} × {group} "
                         f"(of {len(hits)} found)")
        if getattr(dlg, "second_symbol_request", None):
            from . import second_symbol
            n += second_symbol.after_review(self, dlg) or 0
        return n

    # ---- navigation -------------------------------------------------------------
    def go_to(self, page):
        if 0 <= page < self.doc.page_count and page != self.page:
            # pages left behind: don't keep drawing them (Grok M10); the
            # new page and its neighbours stay on order
            self._drop_pending(keep=lambda k: abs(k[1] - page) <= 1)
            self.page = page
            self.selected = None
            self.multi = []
            self._pts, self._drag = [], None
            self._render()

    def next_page(self):
        self.go_to(self.page + 1)

    def prev_page(self):
        self.go_to(self.page - 1)

    def set_zoom(self, zoom):
        self.zoom = max(0.2, min(8.0, zoom))
        self._render(zoom_only=True)


def arc_points(a, m, b, steps=16):
    """Points along the circular arc from a through m to b (a, ..., b);
    the straight line a-b when the three are in a line."""
    import math
    ax, ay, bx, by, cx, cy = a.x, a.y, m.x, m.y, b.x, b.y
    d = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(d) < 1e-9:
        return [a, b]
    ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) +
          (cx * cx + cy * cy) * (ay - by)) / d
    uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) +
          (cx * cx + cy * cy) * (bx - ax)) / d
    r = math.hypot(ax - ux, ay - uy)
    t0 = math.atan2(ay - uy, ax - ux)
    tm = math.atan2(by - uy, bx - ux)
    t1 = math.atan2(cy - uy, cx - ux)

    def ccw(s_, e_):
        return (e_ - s_) % (2 * math.pi)
    # go the way that passes through m
    if ccw(t0, tm) <= ccw(t0, t1):
        sweep = ccw(t0, t1)
    else:
        sweep = ccw(t0, t1) - 2 * math.pi
    return [fitz.Point(ux + r * math.cos(t0 + sweep * i / steps),
                       uy + r * math.sin(t0 + sweep * i / steps))
            for i in range(steps + 1)]
