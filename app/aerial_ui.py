"""Civil > Aerial Photo Page...: a scaled aerial photo of the site as a new
PDF page, so Area / Length / Count measure real feet on it (paving,
grading, clearing, sidewalks, existing conditions).

Decisions (Jon, Oct 19 2026, on the Venice aerial review):
* OK adds the page to the open plan set, right after the current sheet
  (a new tab only when no set is open).
* The page is stored at 1 ft per pixel, smoothly enlarged from the ~2 ft
  USGS photo, and its credit line says so.
* The arrows move a third of the view, as before.
The USGS service takes 20-80 s for every new view, so Preview downloads
one photo 3x the chosen area and the arrows, Wider / Closer, the mouse
wheel and dragging all work on that photo here - nothing else is
downloaded unless the view leaves it. OK crops the page from it.
"""
import math
import os
import threading
import time
import weakref

from PySide6.QtCore import (QCoreApplication, QPointF, QRectF, QSize, Qt,
                            QThreadPool, QTimer, Signal)
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout,
                               QGraphicsPixmapItem, QGraphicsScene,
                               QGraphicsView, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QMessageBox,
                               QProgressDialog, QPushButton, QTabWidget,
                               QVBoxLayout, QWidget)

from . import aerial, settings

FT_PER_DEG_LAT = 364609.0          # 111.13 km per degree of latitude
                                   # (was 364,000: Venice N6)
PREVIEW_PX = 640

# OK's whole job (find, download, crop, layers) gets this long, then a
# clear error (Oct 20 review: 122 s of nothing before an error). Read at
# OK time, so tests can shrink it.
OK_DEADLINE = 150
RETRY_ASK_S = 180      # ask before a second USGS wait this soon after

# --- the feature's own worker threads (Oct 20 review) -----------------------
# Preview's address lookup, overview and photo run 3 at a time on their own
# pool, never on the app's global one (4 Previews there held everything
# for 76 s); OK's job has a 1-thread pool of its own, so it never waits
# behind an old preview download.
_POOLS = {}
_EVENTS = weakref.WeakSet()        # cancel flags of jobs that may be running
_hooked = []


def _pool(name):
    p = _POOLS.get(name)
    if p is None:
        p = QThreadPool()
        p.setMaxThreadCount(1 if name == "ok" else 3)
        _POOLS[name] = p
        app = QCoreApplication.instance()
        if app is not None and not _hooked:
            app.aboutToQuit.connect(_stop_everything)
            _hooked.append(True)
    return p


def _event():
    """A cancel flag for one job (set for every job when the app quits, so
    a stuck download never holds up the exit)."""
    ev = threading.Event()
    _EVENTS.add(ev)
    return ev


def _stop_everything():
    for ev in list(_EVENTS):
        ev.set()
    for p in _POOLS.values():
        p.clear()                          # queued, not yet started


_GEOCODED = {}                     # address -> (lat, lon, matched)


def _geo_key(q):
    return " ".join((q or "").lower().split())


def _geocoded(q):
    """aerial.geocode, answered from this session's earlier lookups when
    it can (Preview's answer is reused by OK - no second lookup)."""
    hit = _GEOCODED.get(_geo_key(q))
    if hit is None:
        hit = aerial.geocode(q)
        _GEOCODED[_geo_key(q)] = hit
    return hit


def shifted(lat, lon, east_ft=0.0, north_ft=0.0):
    """The point east_ft / north_ft away (small moves, flat-earth)."""
    lat2 = lat + north_ft / FT_PER_DEG_LAT
    lon2 = lon + east_ft / (FT_PER_DEG_LAT * math.cos(math.radians(lat)))
    return lat2, lon2


def preview_png(lat, lon, width_ft):
    """A small photo of the area (kept for scripts; the dialog now
    downloads one larger photo and moves around in it)."""
    src = aerial.NAIPSource(width_ft=width_ft,
                            ft_per_px=width_ft / PREVIEW_PX,
                            max_px=PREVIEW_PX)
    png, _mpp = src.fetch(lat, lon, 0, 0, 0)
    return png


AREA_X = 3            # the photo covers 3x the chosen width (Venice A1)


def fetch_area(lat0, lon0, center_ft, view_ft, get_source=None):
    """Download one NAIP photo 3x the view around center_ft (feet east,
    north of lat0/lon0). Runs on a worker thread."""
    e, n = center_ft
    lat, lon = shifted(lat0, lon0, e, n)
    w_ft = view_ft * AREA_X
    src = (get_source or aerial.NAIPSource)(width_ft=w_ft,
                                            height_ft=w_ft * 0.75)
    data, mpp = src.fetch(lat, lon, 0, 0, 0)
    fpp = mpp / 0.3048
    from PySide6.QtGui import QImage
    img = QImage.fromData(data)
    w_px, h_px = img.width(), img.height()
    return {"data": data, "ft_per_px": fpp, "center_ft": (e, n),
            "lat": lat, "lon": lon, "w_px": w_px, "h_px": h_px,
            "w_ft": w_px * fpp, "h_ft": h_px * fpp, "view_ft": view_ft}


def covers(photo, center_ft, view_ft):
    """Does the photo hold the whole view box?"""
    if not photo:
        return False
    (pe, pn), (ce, cn) = photo["center_ft"], center_ft
    hw, hh = view_ft / 2, view_ft * 0.375
    return (abs(ce - pe) + hw <= photo["w_ft"] / 2 + 1e-6 and
            abs(cn - pn) + hh <= photo["h_ft"] / 2 + 1e-6)


def coming_covers(job, center_ft, view_ft):
    """Will the photo download `job` ({"center_ft", "view_ft"}) hold the
    view box once it arrives? (A hair smaller than fetch_area's photo, for
    its pixel rounding; the real photo is checked again when it lands.)"""
    if not job:
        return False
    w = job["view_ft"] * AREA_X * 0.995
    return covers({"center_ft": job["center_ft"], "w_ft": w,
                   "h_ft": w * 0.75}, center_ft, view_ft)


class AerialView(QGraphicsView):
    """The preview: the photo in feet (x east, y south of the site), the
    mouse wheel zooms at the cursor, a left-drag pans and moves the chosen
    area with it, and a dashed box shows the area that becomes the page."""
    moved = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.scene().setSceneRect(-1e6, -1e6, 2e6, 2e6)
        self.setRenderHints(QPainter.Antialiasing |
                            QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMinimumSize(360, 270)
        self.setBackgroundBrush(QColor(60, 60, 60))
        self.box_ft = 1000.0
        self.sel = QPointF(0, 0)                  # chosen centre (scene)
        self.items = {}
        self.message = "Click Preview to see the area first."
        self._dragging = False

    def sizeHint(self):
        # the scene is huge (room to drag far off the photo); without this
        # the dialog grew taller than the screen (Jon, Oct 19 screenshot)
        return QSize(560, 400)

    def minimumSizeHint(self):
        return QSize(360, 270)

    # images -------------------------------------------------------------
    def set_image(self, key, data, left_ft, top_ft, ft_per_px, z):
        img = QImage.fromData(data)
        if img.isNull():
            return
        old = self.items.pop(key, None)
        if old is not None:
            self.scene().removeItem(old)
        it = QGraphicsPixmapItem(QPixmap.fromImage(img))
        it.setTransformationMode(Qt.SmoothTransformation)
        it.setScale(ft_per_px)
        it.setPos(left_ft, top_ft)
        it.setZValue(z)
        self.scene().addItem(it)
        self.items[key] = it
        self.message = ""
        self.viewport().update()

    def clear_images(self):
        for it in self.items.values():
            self.scene().removeItem(it)
        self.items = {}
        self.message = "Click Preview to see the area first."
        self.viewport().update()

    def has_image(self):
        return bool(self.items)

    # the chosen area ----------------------------------------------------
    def set_center(self, e, n, refit=False):
        self.sel = QPointF(e, -n)
        if refit:
            self.refit()
        else:
            self.centerOn(self.sel)
        self.viewport().update()

    def center_ft(self):
        return self.sel.x(), -self.sel.y()

    def box(self):
        w, h = self.box_ft, self.box_ft * 0.75
        return QRectF(self.sel.x() - w / 2, self.sel.y() - h / 2, w, h)

    def refit(self):
        self._zoomed = False
        b = self.box()
        m = b.width() * 0.2
        self.fitInView(b.adjusted(-m, -m, m, m), Qt.KeepAspectRatio)
        self.centerOn(self.sel)

    def zoom_factor(self):
        return self.transform().m11()

    # mouse --------------------------------------------------------------
    def wheelEvent(self, ev):
        steps = ev.angleDelta().y() / 120.0
        if not steps:
            return
        k = 1.25 ** steps
        z = self.zoom_factor() * k
        if 1e-4 < z < 50:
            self.scale(k, k)
            self._zoomed = True

    def mousePressEvent(self, ev):
        self._dragging = ev.button() == Qt.LeftButton
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        super().mouseMoveEvent(ev)
        if self._dragging:
            self.sel = self.mapToScene(self.viewport().rect().center())
            self.viewport().update()
            self.moved.emit()

    def mouseReleaseEvent(self, ev):
        super().mouseReleaseEvent(ev)
        if self._dragging:
            self._dragging = False
            self.moved.emit()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if not getattr(self, "_zoomed", False):    # keep a wheel zoom
            self.refit()

    def drawForeground(self, painter, rect):
        if self.message:
            painter.save()
            painter.resetTransform()
            painter.setPen(QColor(230, 230, 230))
            painter.drawText(self.viewport().rect(), Qt.AlignCenter,
                             self.message)
            painter.restore()
            return
        pen = QPen(QColor(255, 210, 0), 0, Qt.DashLine)
        pen.setCosmetic(True)
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawRect(self.box())
        pen.setStyle(Qt.SolidLine)
        pen.setWidth(1)
        painter.setPen(pen)
        r = self.box_ft * 0.04
        painter.drawLine(QPointF(self.sel.x() - r, self.sel.y()),
                         QPointF(self.sel.x() + r, self.sel.y()))
        painter.drawLine(QPointF(self.sel.x(), self.sel.y() - r),
                         QPointF(self.sel.x(), self.sel.y() + r))


WIDTHS = [("500 ft (a building pad)", 500), ("1,000 ft (a site)", 1000),
          ("2,000 ft (a plant or campus)", 2000),
          ("4,000 ft (a corridor)", 4000)]


class AerialDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Aerial Photo Page")
        self.resize(760, 560)
        lay = QVBoxLayout(self)
        intro = QLabel(
            "Adds an aerial photo page after the current sheet of the open "
            "set, scaled so the Area, Length "
            "and Count tools read real feet. Check the scale against a "
            "known dimension before you rely on it.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.tabs = QTabWidget()
        lay.addWidget(self.tabs)

        # --- free USGS photo by address
        a = QWidget()
        fa = QFormLayout(a)
        self.address = QLineEdit(settings.get("aerial_last_address", ""))
        self.address.setPlaceholderText(
            "Street address, or latitude, longitude (33.7837, -79.0921)")
        row0 = QHBoxLayout()
        row0.addWidget(self.address)
        self.from_plans = QPushButton("From the Plans")
        self.from_plans.setToolTip("Read the project address or latitude/"
                                   "longitude off the open drawing set")
        self.from_plans.clicked.connect(lambda _c=False: self.use_plans())
        row0.addWidget(self.from_plans)
        fa.addRow("Site:", row0)
        self.site_note = QLabel("")
        self.site_note.setWordWrap(True)
        fa.addRow(self.site_note)
        self.width_box = QComboBox()
        for label, ft in WIDTHS:
            self.width_box.addItem(label, ft)
        self.width_box.setCurrentIndex(1)
        fa.addRow("Area shown:", self.width_box)
        note = QLabel("Free USGS NAIP imagery (public domain, no key). About "
                      "2 ft per pixel in most places, sharper where the "
                      "state flew high-resolution photos. Needs internet. "
                      "A street address in the country is placed only "
                      "roughly along its road - preview it and move the "
                      "photo onto the site.")
        note.setWordWrap(True)
        fa.addRow(note)
        # preview + move
        pv = QHBoxLayout()
        self.preview = AerialView()
        self.preview.moved.connect(self._dragged)
        pv.addWidget(self.preview, 1)
        moves = QGridLayout()
        self.preview_btn = QPushButton("Preview")
        self.preview_btn.clicked.connect(lambda: self.do_preview())
        moves.addWidget(self.preview_btn, 0, 0, 1, 3)
        self.move_btns = []
        for txt, r, c, dx, dy, tip in (
                ("▲", 1, 1, 0, 1, "Move north"), ("◀", 2, 0, -1, 0,
                                                   "Move west"),
                ("▶", 2, 2, 1, 0, "Move east"), ("▼", 3, 1, 0, -1,
                                                  "Move south")):
            b = QPushButton(txt)
            b.setToolTip(tip + " a third of the view")
            b.clicked.connect(lambda _c=False, dx=dx, dy=dy:
                              self.pan_by(dx, dy))
            moves.addWidget(b, r, c)
            self.move_btns.append(b)
        zo = QPushButton("− Wider")
        zo.setToolTip("Show twice the area")
        zo.clicked.connect(lambda: self.zoom(2.0))
        zi = QPushButton("+ Closer")
        zi.setToolTip("Show half the area")
        zi.clicked.connect(lambda: self.zoom(0.5))
        moves.addWidget(zo, 4, 0, 1, 3)
        moves.addWidget(zi, 5, 0, 1, 3)
        self.move_btns += [zo, zi]
        for b in self.move_btns:
            b.setEnabled(False)
        hint = QLabel("Wheel: zoom\nDrag: move")
        hint.setStyleSheet("color: gray;")
        moves.addWidget(hint, 6, 0, 1, 3)
        pv.addLayout(moves)
        fa.addRow(pv)
        lyr = QHBoxLayout()
        lyr.addWidget(QLabel("Add site layers:"))
        self.layer_boxes = {}
        saved = settings.get("aerial_layers", []) or []
        for key, (label, source, _u, _s) in aerial.SITE_LAYERS.items():
            cb = QCheckBox(f"{label} ({source})")
            cb.setChecked(key in saved)
            cb.setToolTip("Drawn over the photo as its own layer you can "
                          "switch off; free public data, for review only")
            lyr.addWidget(cb)
            self.layer_boxes[key] = cb
        lyr.addStretch(1)
        fa.addRow(lyr)
        st = QHBoxLayout()
        self.status = QLabel("")
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel_fetch)
        self.cancel_btn.hide()
        st.addWidget(self.status, 1)
        st.addWidget(self.cancel_btn)
        fa.addRow(st)
        self.center = None                 # (lat, lon, label) once found
        self.origin = None                 # (lat, lon, label): scene 0,0
        self.photo = None                  # the downloaded NAIP area
        self.view_ft = None
        self._req = 0                      # newest request; older ignored
        self._gen = 0                      # the site; bumped when it changes
        self._inflight = None              # the photo download under way:
        #   {"rid", "origin", "center_ft", "view_ft", "cancel"}
        self._geo = None                   # the address lookup under way
        self._ov_cancel = None
        self._waiters = []                 # OK waiting for the photo
        self._closed = False
        self._busy_since = None
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._show_busy)
        self._settle = QTimer(self)        # after a drag stops: fetch?
        self._settle.setSingleShot(True)
        self._settle.setInterval(600)
        self._settle.timeout.connect(lambda: self._ensure())
        self.address.textEdited.connect(self._forget)
        self.tabs.addTab(a, "Address (free USGS photo)")

        # --- a photo file you already have
        b = QWidget()
        fb = QFormLayout(b)
        row = QHBoxLayout()
        self.path = QLineEdit()
        pick = QPushButton("Browse…")
        pick.clicked.connect(self._browse)
        row.addWidget(self.path)
        row.addWidget(pick)
        fb.addRow("Photo:", row)
        self.size = QDoubleSpinBox()
        self.size.setDecimals(4)
        self.size.setRange(0.0001, 1000)
        self.size.setValue(0.5)
        self.unit = QComboBox()
        self.unit.addItems(["feet", "meters"])
        r2 = QHBoxLayout()
        r2.addWidget(self.size)
        r2.addWidget(QLabel("per pixel, in"))
        r2.addWidget(self.unit)
        fb.addRow("Ground size:", r2)
        self.found = QLabel("County GIS exports, drone maps and NAIP clips "
                            "usually come with a world file (.pgw, .jgw, "
                            ".tfw) that gives this.")
        self.found.setWordWrap(True)
        fb.addRow(self.found)
        self.tabs.addTab(b, "Photo file")

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.from_plans.setEnabled(self._doc() is not None)
        if self._doc() is not None:
            self.use_plans(quiet=True)

    def showEvent(self, ev):
        """Never taller or wider than the screen it opens on."""
        super().showEvent(ev)
        scr = self.screen() or (self.parent().screen() if self.parent()
                                else None)
        if scr is None:
            return
        av = scr.availableGeometry()
        w = min(self.width(), av.width() - 40)
        h = min(self.height(), av.height() - 60)
        if (w, h) != (self.width(), self.height()):
            self.resize(w, h)
        g = self.frameGeometry()
        x = max(av.left(), min(g.left(), av.right() - g.width()))
        y = max(av.top(), min(g.top(), av.bottom() - g.height()))
        if (x, y) != (g.left(), g.top()):
            self.move(x, y)       # (pan_by pans the photo - L2)

    def _doc(self):
        v = getattr(self.parent(), "_view", None)
        return getattr(v, "doc", None)

    def use_plans(self, quiet=False):
        """Fill the site from the open set: printed lat/long, or the
        project address (not the engineer's, which is in every title
        block)."""
        doc = self._doc()
        site = aerial.find_site(doc) if doc is not None else None
        if not site:
            if not quiet:
                self.site_note.setText(
                    "No project address or latitude/longitude found on the "
                    "first sheets - type it in.")
            return None
        self.address.setText(site["query"])
        self.tabs.setCurrentIndex(0)
        self.site_note.setText(f"From the plans ({site['found']}): "
                               f"{site['query']}. Check it's the site.")
        return site

    def _forget(self, *_):
        self._req += 1                     # anything in flight is stale
        self._gen += 1
        self._stop_jobs()
        self.center = self.origin = self.photo = None
        self.view_ft = None
        self.preview.clear_images()
        self._busy(False)
        for b in self.move_btns:
            b.setEnabled(False)

    def _width(self):
        return self.view_ft or self.width_box.currentData()

    # --- busy state -------------------------------------------------------
    def _busy(self, on, what="Getting the USGS photo"):
        self._what = what
        self._busy_since = time.monotonic() if on else None
        self.cancel_btn.setVisible(on)
        if on:
            self._tick.start()
            self._show_busy()
        else:
            self._tick.stop()
            self.status.setText("")

    def _show_busy(self):
        if self._busy_since is None:
            return
        s = int(time.monotonic() - self._busy_since)
        self.status.setText(f"{self._what}… {s} s (USGS is often slow; "
                            "you can keep moving around meanwhile)")

    def _stop_jobs(self):
        """Stop the address lookup and photo download under way (their
        worker threads are freed within a fraction of a second)."""
        if self._geo is not None:
            self._gen += 1                 # its answer is dropped
        for j in (self._inflight, self._geo):
            if j:
                j["cancel"].set()
        self._inflight = self._geo = None
        self._waiters = []

    def cancel_fetch(self):
        self._req += 1
        self._stop_jobs()
        self._busy(False)
        self.preview_btn.setText("Preview")
        self.preview_btn.setEnabled(True)

    def stop(self, keep_photo=False):
        """The dialog has closed: stop what it started. keep_photo leaves
        the address lookup and photo download running for OK to use."""
        self._closed = True
        self._settle.stop()
        if self._ov_cancel is not None:
            self._ov_cancel.set()
        if not keep_photo:
            self.cancel_fetch()

    def done(self, r):
        self._settle.stop()                # no new download after closing
        super().done(r)

    # --- OK waiting for the photo under way ----------------------------------
    def photo_coming(self, center_ft, view_ft):
        """Is a download under way (or an address lookup that starts one)
        that will cover this view box?"""
        if self.origin is not None:
            f = self._inflight
            return bool(f and f["origin"] is self.origin and
                        coming_covers(f, center_ft, view_ft))
        return bool(self._geo and
                    self._geo["q"] == self.address.text().strip())

    def wait_for_photo(self, cb):
        """cb(photo, None) when the download under way lands, or
        cb(None, message) if it (or the lookup before it) fails."""
        self._waiters.append(cb)

    def _deliver(self, photo, msg):
        ws, self._waiters = self._waiters, []
        for cb in ws:
            cb(photo, msg)

    def center_at(self, center_ft):
        """(lat, lon, label) of a point in feet east/north of the site."""
        e, n = center_ft
        lat, lon = shifted(self.origin[0], self.origin[1], e, n)
        if abs(e) < 1e-9 and abs(n) < 1e-9:
            lat, lon = self.origin[0], self.origin[1]
        return (lat, lon, self.origin[2])

    def crop_args(self, ph, center_ft, width, keys):
        """naip_crop's args: the box at center_ft out of photo ph."""
        (pe, pn), (ce, cn) = ph["center_ft"], center_ft
        px = (ph["w_px"] / 2 + (ce - pe) / ph["ft_per_px"],
              ph["h_px"] / 2 - (cn - pn) / ph["ft_per_px"])
        return (ph, px, self.center_at(center_ft), width, keys)

    # --- where we are -------------------------------------------------------
    def _set_center_ft(self, e, n, refit=False):
        self.preview.set_center(e, n, refit=refit)
        self._sync_center()

    def _sync_center(self):
        if not self.origin:
            return
        e, n = self.preview.center_ft()
        lat, lon = shifted(self.origin[0], self.origin[1], e, n)
        if abs(e) < 1e-9 and abs(n) < 1e-9:
            lat, lon = self.origin[0], self.origin[1]
        self.center = (lat, lon, self.origin[2])
        self.site_note.setText(
            f"{self.origin[2]} - {lat:.5f}, {lon:.5f}, "
            f"{self._width():,.0f} ft across. Drag or use the arrows "
            "until the site is in the yellow box, then OK.")

    def _dragged(self):
        self._sync_center()
        self._settle.start()

    # --- Preview -------------------------------------------------------------
    def do_preview(self, wait=False):
        """Find the site (address lookup the first time), then download one
        photo 3x the area and, beside it, a quick overview from map tiles
        (each its own job: the photo no longer waits for the tiles).
        wait=True runs on this thread (tests)."""
        q = self.address.text().strip()
        if not q and not self.origin:
            self.site_note.setText("Type the site's address first.")
            return
        if self.origin:                    # already found: a fresh photo
            if not coming_covers(self._inflight, self.preview.center_ft(),
                                 self._width()):
                self._fetch(wait, force=True)
            return                         # (one is already on its way)
        if self._geo is not None and self._geo["q"] == q:
            return                         # already looking it up
        self._req += 1
        self._gen += 1
        rid, gen = self._req, self._gen
        width = self._width()
        ev = _event()

        def work():
            with aerial.limits(cancel=ev):
                return _geocoded(q)

        def done(c):
            if self._geo is not None and self._geo["rid"] == rid:
                self._geo = None
            if gen != self._gen:
                return                     # the site changed meanwhile
            self.origin = c
            self.preview.box_ft = width
            self._set_center_ft(0.0, 0.0, refit=True)
            for b in self.move_btns:
                b.setEnabled(True)
            self._fetch(wait)              # the photo starts at once
            if not self._closed:           # (OK may be waiting on it)
                self._overview(wait)

        def failed(msg):
            if self._geo is not None and self._geo["rid"] == rid:
                self._geo = None
            if gen != self._gen:
                return
            self._busy(False)
            self.preview_btn.setText("Preview")
            self.site_note.setText(f"Couldn't find it: {msg}")
            self._deliver(None, msg)

        hit = _GEOCODED.get(_geo_key(q))
        if wait or hit is not None:
            try:
                c = work()
            except Exception as e:                        # noqa: BLE001
                failed(str(e))
            else:
                done(c)
            return
        from . import bg
        self._geo = {"rid": rid, "q": q, "cancel": ev}
        self._busy(True, "Finding the site")
        bg.run(work, done, failed, self, pool=_pool("preview"))

    def _overview(self, wait=False):
        """The quick, coarse picture from map tiles, dropped in under the
        photo whenever it arrives (answers for an old site are ignored)."""
        if not self.origin:
            return
        gen, c, width = self._gen, self.origin, self._width()
        if self._ov_cancel is not None:
            self._ov_cancel.set()
        ev = self._ov_cancel = _event()

        def work():
            with aerial.limits(cancel=ev):
                return aerial.overview(c[0], c[1], width * AREA_X * 1.5)

        def done(ov):
            if gen != self._gen or not ov:
                return
            data, top_lat, left_lon, fpp = ov
            e = (left_lon - c[1]) * FT_PER_DEG_LAT * math.cos(
                math.radians(c[0]))
            n = (top_lat - c[0]) * FT_PER_DEG_LAT
            self.preview.set_image("overview", data, e, -n, fpp, 0)

        if wait:
            try:
                done(work())
            except Exception:                             # noqa: BLE001
                pass                       # only a finder; the photo counts
            return
        from . import bg
        bg.run(work, done, lambda _m: None, self, pool=_pool("preview"))

    def _ensure(self, wait=False):
        """Download a new photo only when the box has left the one we
        have and isn't inside the one on its way."""
        if self.origin and not covers(self.photo, self.preview.center_ft(),
                                      self._width()):
            self._fetch(wait)

    def _fetch(self, wait=False, force=False):
        if not self.origin:
            return
        cft, width = self.preview.center_ft(), self._width()
        if not force and (covers(self.photo, cft, width) or
                          (self._inflight and
                           self._inflight["origin"] is self.origin and
                           coming_covers(self._inflight, cft, width))):
            return
        if self._inflight:                 # superseded: free its worker
            self._inflight["cancel"].set()
        self._req += 1
        rid = self._req
        origin = self.origin
        ev = _event()
        self._inflight = {"rid": rid, "origin": origin, "center_ft": cft,
                          "view_ft": width, "cancel": ev}

        def work():
            with aerial.limits(cancel=ev):
                return fetch_area(origin[0], origin[1], cft, width)

        def landed():
            if self._inflight is not None and self._inflight["rid"] == rid:
                self._inflight = None

        def done(ph):
            landed()
            if rid != self._req:
                return                     # stale: a newer one is coming
            self.photo = ph
            pe, pn = ph["center_ft"]
            self.preview.set_image("photo", ph["data"], pe - ph["w_ft"] / 2,
                                   -(pn + ph["h_ft"] / 2), ph["ft_per_px"], 1)
            self._busy(False)
            self.preview_btn.setText("Preview")
            self._sync_center()
            self._deliver(ph, None)

        def failed(msg):
            landed()
            if "didn't answer" in str(msg):    # remember USGS was silent
                self.last_timeout = time.monotonic()
            if rid != self._req:
                return
            self._busy(False)
            self.preview_btn.setText("Preview")
            self.site_note.setText(f"Couldn't get the photo: {msg}")
            self._deliver(None, msg)

        if wait:
            try:
                ph = work()
            except Exception as e:                        # noqa: BLE001
                failed(str(e))
            else:
                done(ph)
            return
        from . import bg
        self._busy(True)
        bg.run(work, done, failed, self, pool=_pool("preview"))

    def pan_by(self, dx, dy, wait=False):
        if not self.origin:
            return
        step = self._width() / 3.0
        e, n = self.preview.center_ft()
        self._set_center_ft(e + dx * step, n + dy * step)
        self._ensure(wait)

    def zoom(self, k, wait=False):
        self.view_ft = max(250.0, min(8000.0, self._width() * k))
        self.preview.box_ft = self.view_ft
        e, n = self.preview.center_ft()
        self._set_center_ft(e, n, refit=True)
        self._ensure(wait)

    def _browse(self):
        p, _ = QFileDialog.getOpenFileName(
            self, "Aerial Photo", "", "Images (*.png *.jpg *.jpeg *.tif "
            "*.tiff)")
        if not p:
            return
        self.path.setText(p)
        px, why = aerial.world_file_info(p)
        if px:
            self.size.setValue(px)
            self.found.setText(f"World file found: {px:g} units per pixel. "
                               "Pick feet or meters to match the map's "
                               "coordinate system (SC State Plane is feet).")
        elif why:
            self.found.setText(why)

    def layers(self):
        keys = [k for k, cb in self.layer_boxes.items() if cb.isChecked()]
        settings.set("aerial_layers", keys)
        return keys

    def source(self):
        """(kind, args) for the job."""
        if self.tabs.currentIndex() == 0:
            width = self._width()
            cft = self.preview.center_ft()
            if self.center and covers(self.photo, cft, width):
                # crop the page out of the photo already downloaded
                return "naip_crop", self.crop_args(self.photo, cft, width,
                                                   self.layers())
            if self.photo_coming(cft, width):
                # OK during the download: wait for that one, don't start
                # a second (Oct 20 review: 60 s became 2 x 60 s)
                return "naip_wait", (cft, width, self.layers())
            if self.center:                # previewed, nothing on its way
                return "naip_at", (self.center, width, self.layers())
            return "naip", (self.address.text().strip(),
                            self.width_box.currentData(), self.layers())
        fpp = self.size.value() * (1 / 0.3048 if self.unit.currentIndex()
                                   else 1.0)
        return "file", (self.path.text().strip(), fpp)


def _work(kind, args):
    """Runs on a worker thread: returns (pdf bytes, title, note)."""
    src = aerial.NAIPSource
    if kind == "naip_crop":
        ph, px, (lat, lon, matched), width, keys = (list(args) + [[]])[:5]
        data = aerial.crop(ph["data"], ph["ft_per_px"], px, width,
                           width * 0.75)
        fpp = ph["ft_per_px"]
        title = f"Aerial - {matched}"[:60]
    elif kind in ("naip", "naip_at"):
        if kind == "naip":
            address, width, keys = (list(args) + [[]])[:3]
            lat, lon, matched = _geocoded(address)
        else:
            (lat, lon, matched), width, keys = (list(args) + [[]])[:3]
            address = matched
        data, mpp = src(width_ft=width).fetch(lat, lon, 0, 0, 0)
        fpp = mpp / 0.3048
        title = f"Aerial - {matched or address}"[:60]
    if kind in ("naip_crop", "naip", "naip_at"):
        aerial.check()                     # cancelled / out of time?
        w_px, h_px = _image_size(data)
        layers = aerial.site_layers(keys or [], lat, lon, w_px * fpp,
                                    h_px * fpp, w_px, h_px)
        doc = aerial.aerial_document_from(
            data, fpp * 0.3048, lat, lon, src.name, src.credit,
            note=src.note_for(fpp), layers=layers)
        return doc.tobytes(), title, matched
    path, fpp = args
    if not os.path.isfile(path):
        raise FileNotFoundError("Pick a photo file.")
    doc = aerial.aerial_document(aerial.FileSource(path, fpp), 0, 0)
    return doc.tobytes(), "Aerial - " + os.path.basename(path), ""


def _image_size(data):
    import fitz
    pix = fitz.Pixmap(data)
    return pix.width, pix.height


def _tab_index(mw, view):
    """The tab showing this view, or -1 if it was closed."""
    for i in range(mw.tabs.count()):
        if getattr(mw.tabs.widget(i), "view", None) is view:
            return i
    return -1


def add_to_set(mw, data, title, view=None, after=None):
    """Put the aerial page in the open set right after the current sheet
    (Jon, Oct 19); a new tab when no set is open. With view / after (the
    set and sheet showing when OK was clicked) it goes there even if
    another tab is in front now; if that tab was closed, into a new tab.
    Returns where it went: "set", "tab" or "new tab" (the set was
    closed)."""
    import fitz
    from . import pagetools
    src = fitz.open("pdf", data)
    if view is not None:
        i = _tab_index(mw, view)
        if i < 0:
            mw.open_document(src, title)
            return "new tab"
        if mw.tabs.currentIndex() != i:
            mw.tabs.setCurrentIndex(i)     # _page_change works on the front
    v = getattr(mw, "_view", None)
    if v is None or getattr(v, "doc", None) is None or \
            mw._collab_blocked("Adding an aerial page"):
        mw.open_document(src, title)
        return "tab"
    if after is None or view is None:
        after = v.page
    after = max(0, min(int(after), v.doc.page_count - 1))
    try:
        n = mw._page_change(lambda: pagetools.insert_doc(v.doc, src, after),
                            "Added the aerial photo page after sheet "
                            f"{after + 1}")
    finally:
        src.close()                          # Venice N7
    if n:
        v.go_to(after + 1)
    return "set"


def _place(kind, args, dlg):
    """What the progress box says it's getting a photo of."""
    try:
        if kind == "naip":
            return args[0]
        if kind == "naip_at":
            return args[0][2]
        if kind == "naip_crop":
            return args[2][2]
        if kind == "naip_wait":
            o = getattr(dlg, "origin", None)
            return o[2] if o else dlg.address.text().strip()
    except (IndexError, TypeError, AttributeError):
        pass
    return ""


def _job(kind, args, cancel, deadline, seconds):
    """OK's job, on a worker thread: _work under Cancel and the deadline."""
    try:
        with aerial.limits(cancel=cancel, deadline=deadline):
            return _work(kind, args)
    except aerial.DeadlineExceeded as e:
        raise RuntimeError(aerial.timeout_message(seconds)) from e


def new_aerial_page(mw):
    dlg = AerialDialog(mw)
    stop = getattr(dlg, "stop", lambda **k: None)
    if dlg.exec() != QDialog.Accepted:
        stop()
        return
    kind, args = dlg.source()
    second = False
    t0 = getattr(dlg, "last_timeout", None)
    if kind == "naip_at" and t0 is not None and \
            time.monotonic() - t0 < RETRY_ASK_S:
        # Preview just waited out USGS: don't silently wait again
        # (review 0.12.30 A1: 2 x 120 s)
        r = QMessageBox.question(
            mw, "Aerial Photo Page", "The USGS imagery service didn't "
            "answer a moment ago. Try again (up to 2 minutes)?",
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Yes)
        if r != QMessageBox.Yes:
            stop()
            return
        second = True
    stop(keep_photo=kind == "naip_wait")
    if kind == "naip" and not args[0]:
        QMessageBox.information(mw, "Aerial Photo Page",
                                "Type the site's address.")
        return
    addr = getattr(getattr(dlg, "address", None), "text", lambda: "")()
    if kind == "naip":
        addr = args[0]
    if kind.startswith("naip") and addr.strip():
        settings.set("aerial_last_address", addr.strip())
    from . import bg
    # the set and sheet in front now: the page goes there even if another
    # tab is in front when the photo arrives (Oct 20 review)
    view = getattr(mw, "_view", None)
    after = getattr(view, "page", None)
    seconds = OK_DEADLINE
    started = time.monotonic()
    deadline = started + seconds
    cancel = _event()
    place = _place(kind, args, dlg)[:60]
    if second:
        place = (place + " (second try)")[:72]
    state = {"cancelled": False, "finished": False,
             "waiting": kind == "naip_wait",
             "downloading": kind in ("naip", "naip_at", "naip_wait")}

    def label():
        s = int(time.monotonic() - started)
        if state["downloading"]:
            of = f" of {place}" if place else ""
            return (f"Getting the USGS photo{of}… {s} s (USGS is often "
                    "slow)")
        return f"Making the aerial page… {s} s"

    prog = QProgressDialog(label(), "Cancel", 0, 0, mw)
    prog.setWindowTitle("Aerial Photo Page")
    # a crop is quick: its box shows only if it takes over 400 ms; a
    # download shows at once (it showed after 4.17 s: setMinimumDuration
    # doesn't restart the timer Qt starts at 4 s, and setValue(0) is a
    # no-op on a 0..0 busy bar - so we show it ourselves)
    delay = 400 if kind == "naip_crop" else 0
    prog.setMinimumDuration(delay)
    shower = QTimer(prog)
    shower.setSingleShot(True)
    shower.timeout.connect(lambda: state["finished"] or prog.show())
    if state["downloading"]:
        prog.show()
    else:
        shower.start(delay)
    tick = QTimer(prog)
    tick.timeout.connect(lambda: prog.setLabelText(label()))
    tick.start(1000)
    late = QTimer(prog)                    # the deadline, from the window's
    late.setSingleShot(True)               # side too (and for the wait)

    def finish():
        """Was it cancelled? Read that before closing the progress box:
        closing a QProgressDialog emits canceled(), which used to make
        every finished photo look cancelled - OK did nothing (Jon, Oct 20).
        Safe to call twice: after the first call it says "ignore it" (True),
        so a result landing after the deadline's error adds nothing."""
        if state["finished"]:
            return True
        state["finished"] = True
        was = state["cancelled"]
        for t in (tick, shower, late):
            t.stop()
        try:
            prog.canceled.disconnect()
        except (RuntimeError, TypeError):
            pass
        # reset() also stops the dialog's "show after minimumDuration"
        # timer; close() alone didn't, so a quick photo (a crop of the
        # preview) finished first and the box popped up afterwards and
        # stayed, spinning (Jon, Oct 20)
        prog.reset()
        prog.hide()
        prog.deleteLater()
        return was

    def done(res):
        if finish():
            return
        data, title, matched = res
        i = _tab_index(mw, view) if view is not None else -1
        other = view is not None and i >= 0 and view is not mw._view
        set_name = mw.tabs.tabText(i) if other else ""
        where = add_to_set(mw, data, title, view=view, after=after)
        what = f"Aerial photo of {matched}" if matched else "Aerial photo"
        if where == "new tab":
            mw._flash(f"{what} - the set it was for was closed, so it's in "
                      "a new tab; scale set, check it against a known "
                      "dimension")
        elif where == "set" and other:
            mw._flash(f"{what} added to {set_name} after sheet "
                      f"{(after or 0) + 1} - scale set; check it against a "
                      "known dimension")
        elif matched:
            mw._flash(f"{what} - scale set; check it against a known "
                      "dimension")

    def failed(msg):
        if not finish():
            QMessageBox.warning(mw, "Aerial Photo Page",
                                f"Couldn't get the photo:\n{msg}")

    def start(k, a):
        bg.run(lambda: _job(k, a, cancel, deadline, seconds), done, failed,
               mw, pool=_pool("ok"))

    def on_cancel():
        state["cancelled"] = True
        cancel.set()                       # the worker stops within ~0.1 s
        if state["waiting"]:
            state["waiting"] = False
            dlg.cancel_fetch()             # and the download OK waited on
        finish()                           # whatever lands now is dropped

    def out_of_time():
        if state["finished"]:
            return
        cancel.set()
        if state["waiting"]:
            state["waiting"] = False
            dlg.cancel_fetch()
        failed(aerial.timeout_message(seconds))

    prog.canceled.connect(on_cancel)
    late.timeout.connect(out_of_time)
    if kind == "naip_wait":
        # OK during Preview's download: attach to it (no second download)
        # and crop exactly as naip_crop does when it lands
        cft, width, keys = args
        late.start(int(seconds * 1000))

        def got(ph, msg):
            if not state["waiting"] or state["finished"]:
                return
            state["waiting"] = False
            if msg is not None:
                failed(msg)
                return
            state["downloading"] = False
            prog.setLabelText(label())
            if covers(ph, cft, width):
                start("naip_crop", dlg.crop_args(ph, cft, width, keys))
            else:                          # (can't happen; just in case)
                start("naip_at", (dlg.center_at(cft), width, keys))
        dlg.wait_for_photo(got)
        return
    # the job keeps its own deadline; this one is a backstop for anything
    # in it that doesn't listen
    late.start(int(seconds * 1000) + 3000)
    start(kind, args)


def add_menu(mw, parent):
    mw._act(parent, "Aerial Photo Page…", None, lambda: new_aerial_page(mw),
            False)
