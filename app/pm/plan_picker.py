"""Plan sheet picker for the Weekly Owner Report (key plan pins, work
areas and the printed part of the sheet).

The sheet page is rendered with PyMuPDF at ZOOM x the zoom slider and shown
in a scroll area. Everything is stored in UNROTATED page points (the op
coordinates annotate.apply_op uses), so a click goes:

    canvas pixel / zoom          -> point on the page as displayed (rotated)
    * page.derotation_matrix     -> unrotated page point

and drawing goes back with page.rotation_matrix (annotate.to_page /
from_page do the same in the main viewer). The print area (key_plan
"clip") is kept in the page's displayed coordinates (page.rect space), the
space get_pixmap(clip=) and show_pdf_page(clip=) take.

Modes:
  "pin"   - click places the selected photo's pin (photo["pin"] =
            {"sheet", "page", "x", "y"}); existing pins are numbered dots
            (the photo numbers), last week's pins are grey rings.
  "areas" - click points, double-click or Enter closes the polygon, then a
            label is asked; the colour is the next of AREA_COLORS.
            Backspace removes the last point, Esc drops the polygon.
"Set Print Area" (both modes): drag a box = rep["key_plan"]["clip"].
Changes go into rep at once; changed() is called after each."""
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QImage, QPainter, QPen,
                           QPixmap, QPolygonF)
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from . import owner_report as orp
from ..dmoney import c2 as _c2

ZOOM = 1.5
STEPS = (0.5, 0.67, 0.8, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0)


def _qc(rgb, alpha=255):
    r, g, b = (list(rgb or (0.5, 0.5, 0.5)) + [0, 0, 0])[:3]
    return QColor(int(r * 255), int(g * 255), int(b * 255), alpha)


class _Canvas(QWidget):
    """The rendered page; mouse events go to the dialog in canvas
    (= view) pixels."""
    pressed = Signal(float, float)
    dragged = Signal(float, float)
    released = Signal(float, float)
    double = Signal(float, float)

    def __init__(self, dlg):
        super().__init__()
        self.dlg = dlg
        self.pix = QPixmap()
        self.setMouseTracking(False)
        self.setCursor(Qt.CrossCursor)

    def set_pixmap(self, pm):
        self.pix = pm
        self.setFixedSize(pm.size())
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if not self.pix.isNull():
            p.drawPixmap(0, 0, self.pix)
        self.dlg.paint_overlay(p)
        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.pressed.emit(e.position().x(), e.position().y())

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            self.dragged.emit(e.position().x(), e.position().y())

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.released.emit(e.position().x(), e.position().y())

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.double.emit(e.position().x(), e.position().y())


class PlanPicker(QDialog):
    def __init__(self, store, rep, mode="pin", photo=None, parent=None,
                 changed=None):
        super().__init__(parent)
        import fitz
        self.store, self.mode = store, mode
        # rep may be a callable returning the current report: the window
        # swaps in the saved copy after each save
        self._rep = rep
        self.changed = changed or (lambda: None)
        kp = self.rep.get("key_plan") or {}
        if not kp.get("sheet"):
            raise ValueError("Pick the plan sheet first (Plan Sheet…).")
        self.sheet = kp["sheet"]
        self.pno = int(kp.get("page") or 0)
        self.doc = orp._open_sheet(store, self.sheet)
        if not 0 <= self.pno < self.doc.page_count:
            self.pno = 0
        self.page = self.doc[self.pno]
        self._derot = self.page.derotation_matrix
        self._rot = self.page.rotation_matrix
        self._fitz = fitz
        self.scale = 1.0
        self.zoom = ZOOM
        self.pts = []                  # the polygon being drawn (page pts)
        self.clip_mode = False
        self._drag = None              # (x0, y0, x1, y1) view px
        self.photo_list = []
        name = self.sheet.get("name") if isinstance(self.sheet, dict) \
            else str(self.sheet)
        self.setWindowTitle(("Pin Photos on the Plan" if mode == "pin" else
                             "Work Areas") + f" - {name}, page "
                            f"{self.pno + 1}")
        self.resize(1100, 760)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        root = QHBoxLayout(self)
        left = QVBoxLayout()
        bar = QHBoxLayout()
        for text, fn in (("Zoom In", lambda: self.set_scale(+1)),
                         ("Zoom Out", lambda: self.set_scale(-1)),
                         ("Fit", self.fit)):
            b = QPushButton(text)
            b.setAutoDefault(False)
            b.clicked.connect(fn)
            bar.addWidget(b)
        self.clip_btn = QPushButton("Set Print Area")
        self.clip_btn.setCheckable(True)
        self.clip_btn.setAutoDefault(False)
        self.clip_btn.setToolTip("Drag a box around the part of the sheet "
                                 "to print on the plan pages")
        self.clip_btn.toggled.connect(self._clip_toggled)
        bar.addWidget(self.clip_btn)
        b = QPushButton("Whole Sheet")
        b.setAutoDefault(False)
        b.setToolTip("Print the whole sheet")
        b.clicked.connect(self.clear_clip)
        bar.addWidget(b)
        bar.addStretch(1)
        left.addLayout(bar)
        self.canvas = _Canvas(self)
        self.canvas.pressed.connect(self._press)
        self.canvas.dragged.connect(self._move)
        self.canvas.released.connect(self._release)
        self.canvas.double.connect(self._double)
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.canvas)
        self.scroll.setAlignment(Qt.AlignCenter)
        left.addWidget(self.scroll, 1)
        self.hint = QLabel()
        self.hint.setObjectName("muted")
        self.hint.setWordWrap(True)
        left.addWidget(self.hint)
        root.addLayout(left, 1)
        side = QVBoxLayout()
        self.items = QListWidget()
        self.items.setMinimumWidth(240)
        self.items.currentRowChanged.connect(lambda *_: self.canvas.update())
        side.addWidget(QLabel("<b>Photos</b>" if mode == "pin" else
                              "<b>Work areas</b>"))
        side.addWidget(self.items, 1)
        if mode == "pin":
            self.photo_list = self._printed()
            b = QPushButton("Remove Pin")
            b.setAutoDefault(False)
            b.clicked.connect(self.remove_pin)
            side.addWidget(b)
            self.hint.setText("Pick a photo on the right, then click where "
                              "it was taken. Grey rings are last week's "
                              "photos. Numbers are the photo numbers.")
        else:
            h = QHBoxLayout()
            for text, fn in (("Label…", self.edit_label),
                             ("Note…", self.edit_note),
                             ("Delete", self.delete_selected)):
                b = QPushButton(text)
                b.setAutoDefault(False)
                b.clicked.connect(fn)
                h.addWidget(b)
            side.addLayout(h)
            self.hint.setText("Click the corners of a work area; "
                              "double-click or Enter closes it. Backspace "
                              "removes the last point, Esc drops it.")
        close = QPushButton("Done")
        close.setObjectName("primary")
        close.setAutoDefault(False)
        close.clicked.connect(self.accept)
        side.addWidget(close)
        root.addLayout(side)
        self.render_page()
        self.fill_list()
        if mode == "pin":
            if photo is None or self.select_photo(photo) < 0:
                first = next((i for i, p in enumerate(self.photo_list)
                              if not p.get("pin")), 0)
                if self.photo_list:
                    self.items.setCurrentRow(first)

    @property
    def rep(self):
        return self._rep() if callable(self._rep) else self._rep

    # ---------------------------------------------------------- geometry
    def view_to_page(self, x, y):
        """Canvas pixel -> unrotated page point (x, y)."""
        p = self._fitz.Point(x / self.zoom, y / self.zoom) * self._derot
        return (_c2(p.x), _c2(p.y))

    def page_to_view(self, x, y):
        """Unrotated page point -> canvas pixel (x, y)."""
        p = self._fitz.Point(float(x), float(y)) * self._rot
        return (p.x * self.zoom, p.y * self.zoom)

    def render_page(self):
        fitz = self._fitz
        z = self.zoom
        pix = self.page.get_pixmap(matrix=fitz.Matrix(z, z), alpha=False)
        img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                     QImage.Format_RGB888).copy()
        self.canvas.set_pixmap(QPixmap.fromImage(img))

    def set_scale(self, step):
        i = min(range(len(STEPS)), key=lambda k: abs(STEPS[k] - self.scale))
        i = max(0, min(len(STEPS) - 1, i + (1 if step > 0 else -1)))
        self._apply_scale(STEPS[i])

    def fit(self):
        vw = max(200, self.scroll.viewport().width() - 4)
        vh = max(200, self.scroll.viewport().height() - 4)
        r = self.page.rect
        self._apply_scale(max(0.2, min(4.0, min(vw / r.width, vh / r.height)
                                       / ZOOM)))

    def _apply_scale(self, s):
        self.scale = s
        self.zoom = ZOOM * s
        self.render_page()

    # ---------------------------------------------------------- data
    def _printed(self):
        return orp.printed_photos(self.rep)

    def _same_sheet(self, d):
        return d and orp._sheet_key(d.get("sheet")) == \
            orp._sheet_key(self.sheet) and \
            int(d.get("page") or 0) == self.pno

    def areas(self):
        return self.rep.setdefault("work_areas", [])

    def fill_list(self):
        self.items.blockSignals(True)
        cur = self.items.currentRow()
        self.items.clear()
        if self.mode == "pin":
            self.photo_list = self._printed()
            for i, ph in enumerate(self.photo_list, 1):
                pin = ph.get("pin")
                mark = ("pinned" if self._same_sheet(pin) else
                        "pinned on another sheet") if pin else "no pin"
                text = (ph.get("location") or ph.get("caption") or
                        (ph.get("ref") or {}).get("name") or "")
                it = QListWidgetItem(f"{i}. {text[:30]}  ({mark})")
                self.items.addItem(it)
        else:
            for i, a in enumerate(self.areas()):
                it = QListWidgetItem(a.get("label") or f"Area {i + 1}")
                it.setForeground(QBrush(_qc(a.get("color"))))
                if not self._same_sheet(a):
                    it.setText(it.text() + "  (another sheet)")
                self.items.addItem(it)
        self.items.blockSignals(False)
        if 0 <= cur < self.items.count():
            self.items.setCurrentRow(cur)
        self.canvas.update()

    def select_photo(self, photo):
        key = orp._photo_key(photo.get("ref"))
        for i, ph in enumerate(self.photo_list):
            if orp._photo_key(ph.get("ref")) == key:
                self.items.setCurrentRow(i)
                return i
        return -1

    def current_photo(self):
        r = self.items.currentRow()
        photos = self._printed()
        return photos[r] if 0 <= r < len(photos) else None

    def _done(self):
        self.fill_list()
        self.changed()

    # ---------------------------------------------------------- mouse
    def _press(self, x, y):
        if self.clip_mode:
            self._drag = (x, y, x, y)
            self.canvas.update()
            return
        self.click(x, y)

    def _move(self, x, y):
        if self.clip_mode and self._drag:
            self._drag = self._drag[:2] + (x, y)
            self.canvas.update()

    def _release(self, x, y):
        if self.clip_mode and self._drag:
            x0, y0 = self._drag[:2]
            self._drag = None
            self.set_clip_view(x0, y0, x, y)

    def _double(self, x, y):
        if self.mode == "areas" and not self.clip_mode:
            # the double-click's first press already added this corner
            self.finish_area()

    def click(self, x, y):
        """A left click at canvas pixel (x, y)."""
        px, py = self.view_to_page(x, y)
        if self.mode == "pin":
            return self.place_pin(px, py)
        if self.pts and abs(self.pts[-1][0] - px) < 0.5 and \
                abs(self.pts[-1][1] - py) < 0.5:
            return None                          # the same spot again
        self.pts.append([px, py])
        self.canvas.update()
        return (px, py)

    def place_pin(self, px, py, photo=None):
        ph = photo or self.current_photo()
        if ph is None:
            return None
        ph["pin"] = {"sheet": self.sheet, "page": self.pno,
                     "x": float(px), "y": float(py)}
        row = self.items.currentRow()
        self._done()
        # move on to the next photo without a pin
        photos = self._printed()
        nxt = next((i for i in range(row + 1, len(photos))
                    if not photos[i].get("pin")), None)
        if nxt is not None:
            self.items.setCurrentRow(nxt)
        return ph["pin"]

    def remove_pin(self):
        ph = self.current_photo()
        if ph is not None and ph.get("pin"):
            ph["pin"] = None
            self._done()

    # ---------------------------------------------------------- areas
    def next_color(self):
        used = {tuple(round(c, 3) for c in (a.get("color") or []))
                for a in self.areas()}
        for c in orp.AREA_COLORS:
            if tuple(round(v, 3) for v in c) not in used:
                return list(c)
        return list(orp.AREA_COLORS[len(self.areas()) %
                                    len(orp.AREA_COLORS)])

    def finish_area(self, label=None):
        if len(self.pts) < 3:
            return None
        if label is None:
            n = len(self.areas()) + 1
            label, ok = QInputDialog.getText(
                self, "Work Area", "Label (e.g. Bldg A slab pour):",
                QLineEdit.Normal, f"Area {n}")
            if not ok:
                label = f"Area {n}"
        a = {"sheet": self.sheet, "page": self.pno,
             "pts": [list(p) for p in self.pts], "color": self.next_color(),
             "label": (label or "").strip() or
             f"Area {len(self.areas()) + 1}", "note": ""}
        self.areas().append(a)
        self.pts = []
        self._done()
        self.items.setCurrentRow(len(self.areas()) - 1)
        return a

    def delete_area(self, i):
        if 0 <= i < len(self.areas()):
            del self.areas()[i]
            self._done()

    def delete_selected(self):
        self.delete_area(self.items.currentRow())

    def _edit(self, key, title):
        i = self.items.currentRow()
        if not 0 <= i < len(self.areas()):
            return
        a = self.areas()[i]
        text, ok = QInputDialog.getText(self, "Work Area", title,
                                        QLineEdit.Normal, a.get(key) or "")
        if ok:
            a[key] = text.strip()
            self._done()

    def edit_label(self):
        self._edit("label", "Label:")

    def edit_note(self):
        self._edit("note", "Note (printed under the label):")

    def keyPressEvent(self, e):
        if self.mode == "areas" and self.pts:
            if e.key() in (Qt.Key_Return, Qt.Key_Enter):
                self.finish_area()
                return
            if e.key() == Qt.Key_Backspace:
                self.pts.pop()
                self.canvas.update()
                return
            if e.key() == Qt.Key_Escape:
                self.pts = []
                self.canvas.update()
                return
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            return                      # Enter never closes the picker
        super().keyPressEvent(e)

    # ---------------------------------------------------------- print area
    def _clip_toggled(self, on):
        self.clip_mode = on

    def set_clip_view(self, x0, y0, x1, y1):
        """A dragged box (canvas px) -> key_plan clip in displayed page
        coordinates."""
        z = self.zoom
        r = self._fitz.Rect(min(x0, x1) / z, min(y0, y1) / z,
                            max(x0, x1) / z, max(y0, y1) / z) & \
            self.page.rect
        self.clip_btn.setChecked(False)
        if r.is_empty or r.width < 20 or r.height < 20:
            self.canvas.update()
            return None
        kp = self.rep.setdefault("key_plan", {})
        kp["clip"] = [round(r.x0, 1), round(r.y0, 1), round(r.x1, 1),
                      round(r.y1, 1)]
        self._done()
        return kp["clip"]

    def clear_clip(self):
        kp = self.rep.get("key_plan") or {}
        if kp.get("clip"):
            kp["clip"] = None
            self._done()

    # ---------------------------------------------------------- drawing
    def paint_overlay(self, p):
        z = self.zoom
        kp = self.rep.get("key_plan") or {}
        if kp.get("clip"):
            x0, y0, x1, y1 = kp["clip"]
            p.setPen(QPen(QColor(30, 110, 220), 2, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(x0 * z, y0 * z, (x1 - x0) * z, (y1 - y0) * z))
        if self._drag:
            x0, y0, x1, y1 = self._drag
            p.setPen(QPen(QColor(30, 110, 220), 1, Qt.DashLine))
            p.setBrush(QColor(30, 110, 220, 40))
            p.drawRect(QRectF(QPointF(x0, y0), QPointF(x1, y1)).normalized())
        sel = self.items.currentRow()
        for i, a in enumerate(self.areas()):
            if not self._same_sheet(a) or len(a.get("pts") or []) < 3:
                continue
            poly = QPolygonF([QPointF(*self.page_to_view(x, y))
                              for x, y in a["pts"]])
            col = _qc(a.get("color"))
            p.setPen(QPen(col.darker(130), 3 if (self.mode == "areas" and
                                                 i == sel) else 1.5))
            p.setBrush(_qc(a.get("color"), 90))
            p.drawPolygon(poly)
            c = poly.boundingRect().center()
            p.setPen(QColor(0, 0, 0))
            p.drawText(c, a.get("label") or "")
        if self.pts:
            pen = QPen(QColor(220, 60, 60), 2)
            p.setPen(pen)
            p.setBrush(_qc(self.next_color(), 60))
            poly = QPolygonF([QPointF(*self.page_to_view(x, y))
                              for x, y in self.pts])
            p.drawPolygon(poly) if len(self.pts) > 2 else \
                p.drawPolyline(poly)
            for x, y in self.pts:
                p.drawEllipse(QPointF(*self.page_to_view(x, y)), 3, 3)
        # last week's pins (grey rings), then this week's (numbered dots)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(120, 120, 120), 2))
        for c in self.rep.get("before_candidates") or []:
            pin = c.get("pin")
            if self._same_sheet(pin):
                p.drawEllipse(QPointF(*self.page_to_view(pin["x"],
                                                         pin["y"])), 8, 8)
        f = QFont(p.font())
        f.setBold(True)
        f.setPointSizeF(8)
        p.setFont(f)
        cur = self.current_photo() if self.mode == "pin" else None
        cur = orp._photo_key(cur.get("ref")) if cur is not None else None
        for i, ph in enumerate(self._printed(), 1):
            pin = ph.get("pin")
            if not self._same_sheet(pin):
                continue
            c = QPointF(*self.page_to_view(pin["x"], pin["y"]))
            hot = cur is not None and orp._photo_key(ph.get("ref")) == cur
            p.setPen(QPen(QColor(255, 255, 255), 2 if hot else 1))
            p.setBrush(QColor(255, 200, 0) if hot else _qc(orp.PIN_COLOR))
            p.drawEllipse(c, 10, 10)
            p.setPen(QColor(0, 0, 0) if hot else QColor(255, 255, 255))
            p.drawText(QRectF(c.x() - 10, c.y() - 10, 20, 20),
                       Qt.AlignCenter, str(i))

    def done(self, r):
        try:
            self.doc.close()
        except Exception:                           # noqa: BLE001
            pass
        super().done(r)
