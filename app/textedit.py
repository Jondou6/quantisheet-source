"""Edit PDF mode, Acrobat-style.

With the Edit Text tool on, every paragraph and picture on the page gets a
light outline. Click in a paragraph and type right there: the text is
edited in place, in the paragraph's own font and size, wrapping to its
box, with a small bar for font, size, bold, italic, colour and alignment
(applied to the selection, or to the whole paragraph). Click outside or
press Ctrl+Enter to keep it, Esc to cancel. Double-click empty space to add
new text. Click a picture to select it; drag to move, drag a corner to
resize, Delete to remove, right-click to replace it.

Edits go through the normal op pipeline (replace_block / move_image ...),
so Undo, collaboration and history work as for any other change.
"""
import base64
import html as _html
import logging

import fitz
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QPainter, QPalette,
                           QPen,
                           QTextBlockFormat, QTextCharFormat, QTextCursor,
                           QTextOption)
from PySide6.QtWidgets import (QColorDialog, QComboBox, QDoubleSpinBox,
                               QFileDialog, QFrame, QHBoxLayout, QMenu,
                               QPushButton, QTextEdit, QToolButton, QWidget)

from . import annotate, theme

log = logging.getLogger(__name__)
HANDLE = 7                                   # handle size, screen px
FAMILIES = [("Helvetica", "Arial", "sans-serif"),
            ("Times", "Times New Roman", "serif"),
            ("Courier", "Courier New", "monospace")]
_loaded_fonts = {}


def screen_family(doc, page, font_name):
    """(Qt family to show, css family to write, label) for a PDF font."""
    f = (font_name or "").lower()
    if font_name:
        key = font_name
        if key not in _loaded_fonts:
            fam = None
            buf = annotate._embedded_font(doc, page, font_name, "")
            if buf:
                fid = QFontDatabase.addApplicationFontFromData(buf)
                fams = QFontDatabase.applicationFontFamilies(fid) \
                    if fid >= 0 else []
                fam = fams[0] if fams else None
            _loaded_fonts[key] = fam
        if _loaded_fonts[key]:
            return (_loaded_fonts[key], "psorig",
                    font_name.split("+")[-1])
    if any(k in f for k in annotate._MONO):
        return "Courier New", "monospace", "Courier"
    if any(k in f for k in annotate._SERIF):
        return "Times New Roman", "serif", "Times"
    return "Arial", "sans-serif", "Helvetica"


def to_html(document, zoom, family_css):
    """QTextDocument -> simple HTML for page.insert_htmlbox. family_css
    maps the Qt families in use to the css family names."""
    out = []
    block = document.begin()
    while block.isValid():
        align = {Qt.AlignHCenter: "center", Qt.AlignRight: "right",
                 Qt.AlignJustify: "justify"}.get(
            block.blockFormat().alignment() & Qt.AlignHorizontal_Mask,
            "left")
        parts = []
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid():
                cf = frag.charFormat()
                fnt = cf.font()
                px = fnt.pixelSize() if fnt.pixelSize() > 0 else \
                    fnt.pointSizeF() * 96 / 72
                size = px / zoom
                css = [f"font-size:{size:.2f}pt"]
                fam = family_css.get(fnt.family(), "sans-serif")
                css.append(f"font-family:{fam}")
                if fnt.weight() >= QFont.DemiBold:
                    css.append("font-weight:bold")
                if fnt.italic():
                    css.append("font-style:italic")
                col = cf.foreground().color()
                if col.isValid():
                    css.append(f"color:{col.name()}")
                text = _html.escape(frag.text()).replace(" ", "<br>")
                parts.append(f'<span style="{";".join(css)}">{text}</span>')
            it += 1
        body = "".join(parts) or "&nbsp;"
        out.append(f'<p style="margin:0;text-align:{align}">{body}</p>')
        block = block.next()
    return "".join(out)


class _Overlay(QWidget):
    """Outlines of paragraphs and pictures, drawn over the page."""

    def __init__(self, ctl):
        super().__init__(ctl.view)
        self.ctl = ctl
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)

    def paintEvent(self, e):
        c = self.ctl
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        acc = QColor(theme.color("accent"))
        faint = QColor(acc)
        faint.setAlpha(70)
        for b in c.blocks:
            r = c.q(b["rect"])
            if b is c.hover or (c.sel_image is b):
                continue
            p.setPen(QPen(faint, 1, Qt.DashLine if b["kind"] == "text"
                          else Qt.DotLine))
            p.drawRect(r)
        if c.hover is not None and c.hover is not c.sel_image:
            p.setPen(QPen(acc, 1.5))
            p.drawRect(c.q(c.hover["rect"]))
        if c.sel_image is not None:
            r = c.q(c.ghost or c.sel_image["rect"])
            p.setPen(QPen(acc, 1.5))
            p.drawRect(r)
            p.setBrush(QColor("white"))
            for h in c.handles(r).values():
                p.drawRect(h)


class _FormatBar(QFrame):
    def __init__(self, ctl):
        super().__init__(ctl.view)
        self.ctl = ctl
        self.setObjectName("EditBar")
        t = theme.tokens()
        self.setStyleSheet(
            f"#EditBar{{background:{t['surface']};border:1px solid "
            f"{t['border2']};border-radius:8px}}"
            f"QToolButton{{padding:3px 6px;border-radius:4px}}"
            f"QToolButton:checked{{background:{t['accent_soft']}}}")
        h = QHBoxLayout(self)
        h.setContentsMargins(6, 4, 6, 4)
        h.setSpacing(4)
        self.family = QComboBox()
        self.family.setMinimumWidth(130)
        h.addWidget(self.family)
        self.size = QDoubleSpinBox()
        self.size.setRange(4, 144)
        self.size.setDecimals(1)
        self.size.setSuffix(" pt")
        self.size.setFixedWidth(78)
        h.addWidget(self.size)
        self.bold = self._btn("B", "Bold (Ctrl+B)", True)
        f = self.bold.font()
        f.setBold(True)
        self.bold.setFont(f)
        self.italic = self._btn("I", "Italic (Ctrl+I)", True)
        f = self.italic.font()
        f.setItalic(True)
        self.italic.setFont(f)
        h.addWidget(self.bold)
        h.addWidget(self.italic)
        self.color = self._btn("A", "Text colour", False)
        h.addWidget(self.color)
        self.aligns = {}
        for key, label, tip in (("left", "⟸", "Align left"),
                                ("center", "≡", "Center"),
                                ("right", "⟹", "Align right"),
                                ("justify", "☰", "Justify")):
            b = self._btn(label, tip, True)
            self.aligns[key] = b
            h.addWidget(b)
        done = QPushButton("Done")
        done.setStyleSheet(f"background:{t['accent']};color:white;"
                           "font-weight:600;padding:3px 12px;"
                           "border-radius:5px")
        done.clicked.connect(lambda: ctl.commit())
        h.addWidget(done)
        cancel = QToolButton()
        cancel.setText("✕")
        cancel.setToolTip("Cancel (Esc)")
        cancel.clicked.connect(lambda: ctl.cancel())
        h.addWidget(cancel)
        self.family.activated.connect(lambda _i: ctl.set_family(
            self.family.currentData()))
        self.size.editingFinished.connect(lambda: ctl.set_size(
            self.size.value()))
        self.bold.clicked.connect(lambda on: ctl.set_bold(on))
        self.italic.clicked.connect(lambda on: ctl.set_italic(on))
        self.color.clicked.connect(ctl.pick_color)
        for key, b in self.aligns.items():
            b.clicked.connect(lambda _c=False, k=key: ctl.set_align(k))
        self.adjustSize()

    def _btn(self, text, tip, checkable):
        b = QToolButton()
        b.setText(text)
        b.setToolTip(tip)
        b.setCheckable(checkable)
        b.setAutoRaise(True)
        return b


class EditController(QObject):
    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self.active = False
        self.blocks = []
        self.hover = None
        self.sel_image = None
        self.ghost = None              # image rect while dragging
        self.drag = None               # (mode, start screen pt, start rect)
        self.editor = None
        self.bar = None
        self.edit = None               # the block being edited
        self.overlay = _Overlay(self)
        self.overlay.hide()
        self.done_btn = None

    # ---------------------------------------------------------- coords
    def q(self, rect):
        z = self.view.zoom
        r = fitz.Rect(rect)
        return QRectF(r.x0 * z, r.y0 * z, r.width * z, r.height * z)

    def handles(self, r):
        s = HANDLE
        pts = {"tl": r.topLeft(), "tr": r.topRight(), "bl": r.bottomLeft(),
               "br": r.bottomRight()}
        return {k: QRectF(p.x() - s / 2, p.y() - s / 2, s, s)
                for k, p in pts.items()}

    # ---------------------------------------------------------- on / off
    def supported(self):
        return self.view.pg.rotation == 0

    def activate(self):
        if self.active:
            self.refresh()
            return
        self.active = True
        self.view.installEventFilter(self)
        self.view.setMouseTracking(True)
        self.refresh()
        self.overlay.show()
        self._show_done()
        self.view.status.emit("Click text to edit it in place · Double-"
                              "click empty space to add text · Click a "
                              "picture to move, resize or replace it · "
                              "Done Editing (or Esc) to finish")

    def deactivate(self):
        if not self.active:
            return
        self.commit()
        self.active = False
        self.view.removeEventFilter(self)
        self.overlay.hide()
        if self.done_btn is not None:
            self.done_btn.hide()
        self.sel_image = self.hover = None

    # ---------------------------------------------------------- way out
    def _show_done(self):
        """A "Done Editing" button pinned to the top-right of the visible
        area, so there's always a way back to normal selecting."""
        host = self.view.parentWidget() or self.view
        if self.done_btn is None:
            b = QPushButton("\u2713  Done Editing  (Esc)", host)
            b.setObjectName("DoneEditing")
            b.setCursor(Qt.ArrowCursor)
            b.setStyleSheet(
                "QPushButton#DoneEditing{background:%s;color:white;"
                "border:none;border-radius:6px;padding:6px 14px;"
                "font-weight:600}" % theme.color("accent").name())
            b.clicked.connect(self.finish)
            self.done_btn = b
            host.installEventFilter(self)
        self._place_done()
        self.done_btn.show()
        self.done_btn.raise_()

    def _place_done(self):
        b = self.done_btn
        if b is None:
            return
        host = b.parentWidget()
        b.adjustSize()
        b.move(max(8, host.width() - b.width() - 16), 12)

    def finish(self):
        """Leave edit mode: keep any open edit and go back to Select."""
        self.commit()
        win = self.view.window()
        if hasattr(win, "set_tool") and getattr(win, "_view", None) is \
                self.view:
            win.set_tool(None)
        else:
            self.view.set_tool(None)
        self.view.setFocus()

    def refresh(self):
        """Page changed or redrawn: reload outlines."""
        if not self.active:
            return
        if self.editor is not None and getattr(self, "_page_key", None) != \
                (id(self.view.doc), self.view.page):
            self.cancel()
        elif self.editor is not None and \
                abs(getattr(self, "_zoom", self.view.zoom) -
                    self.view.zoom) > 1e-6:
            QTimer.singleShot(0, self.commit)     # zoomed while typing
        self._page_key = (id(self.view.doc), self.view.page)
        self.overlay.setGeometry(0, 0, self.view.width(), self.view.height())
        self.overlay.raise_()
        if self.editor is not None:
            self.editor.raise_()
            self.bar.raise_()
        self.blocks = []
        if not self.supported():
            self.overlay.update()
            return
        pg = self.view.pg
        try:
            d = pg.get_text("dict")
        except Exception:
            d = {"blocks": []}
        for b in d.get("blocks", []):
            if b.get("type", 0) != 0:
                continue
            if not "".join(s["text"] for ln in b.get("lines", [])
                           for s in ln["spans"]).strip():
                continue
            self.blocks.append({"kind": "text", "rect": annotate.from_page(
                pg, fitz.Rect(b["bbox"]))})
        try:
            infos = pg.get_image_info(xrefs=True)
        except Exception:
            infos = []
        counts = {}
        for i in infos:
            counts[i.get("xref")] = counts.get(i.get("xref"), 0) + 1
        for i in infos:
            r = fitz.Rect(i["bbox"])
            if r.is_empty or r.width < 3 or r.height < 3 or \
                    not i.get("xref"):
                continue
            if r.width * r.height > pg.rect.width * pg.rect.height * 0.9:
                continue                 # a scanned page, not a picture
            self.blocks.append({"kind": "image", "rect": r,
                                "xref": i["xref"],
                                "shared": counts[i["xref"]] > 1})
        if self.sel_image is not None:
            self.sel_image = next((b for b in self.blocks
                                   if b["kind"] == "image" and
                                   b.get("xref") == self.sel_image["xref"]),
                                  None)
        self.overlay.update()

    # ---------------------------------------------------------- events
    def _hit(self, pt):
        img = [b for b in self.blocks if b["kind"] == "image" and
               fitz.Rect(b["rect"]).contains(pt)]
        txt = [b for b in self.blocks if b["kind"] == "text" and
               fitz.Rect(b["rect"]).contains(pt)]
        return (txt or img or [None])[0]

    def eventFilter(self, obj, e):
        if self.done_btn is not None and obj is self.done_btn.parentWidget() \
                and e.type() == QEvent.Resize:
            self._place_done()
            return False
        if obj is not self.view or not self.active:
            return False
        t = e.type()
        if t == QEvent.Resize:
            self.overlay.setGeometry(0, 0, self.view.width(),
                                     self.view.height())
            return False
        if not self.supported():
            return False                    # rotated page: classic editing
        if t == QEvent.MouseMove:
            return self._move(e)
        if t == QEvent.MouseButtonPress:
            return self._press(e)
        if t == QEvent.MouseButtonRelease:
            return self._release(e)
        if t == QEvent.MouseButtonDblClick:
            return self._double(e)
        if t == QEvent.KeyPress:
            return self._key(e)
        return False

    def _move(self, e):
        pos = e.position()
        pt = self.view._sp(pos)
        if self.drag:
            mode, start, r0 = self.drag
            z = self.view.zoom
            dx, dy = (pos.x() - start.x()) / z, (pos.y() - start.y()) / z
            r = fitz.Rect(r0)
            if mode == "move":
                r = r + (dx, dy, dx, dy)
            else:
                keep = not (e.modifiers() & Qt.ShiftModifier)
                if "l" in mode:
                    r.x0 += dx
                else:
                    r.x1 += dx
                if "t" in mode:
                    r.y0 += dy
                else:
                    r.y1 += dy
                r.normalize()
                if keep and r0.width and r0.height:      # keep proportions
                    k = max(r.width / r0.width, r.height / r0.height)
                    w, h = r0.width * k, r0.height * k
                    if "l" in mode:
                        r.x0 = r.x1 - w
                    else:
                        r.x1 = r.x0 + w
                    if "t" in mode:
                        r.y0 = r.y1 - h
                    else:
                        r.y1 = r.y0 + h
            self.ghost = r
            self.overlay.update()
            return True
        hit = self._hit(pt)
        cursor = Qt.ArrowCursor
        if self.sel_image is not None:
            for k, h in self.handles(self.q(self.sel_image["rect"])).items():
                if h.adjusted(-3, -3, 3, 3).contains(pos):
                    cursor = Qt.SizeFDiagCursor if k in ("tl", "br") else \
                        Qt.SizeBDiagCursor
                    break
        if cursor == Qt.ArrowCursor:
            cursor = Qt.IBeamCursor if hit and hit["kind"] == "text" else \
                Qt.SizeAllCursor if hit else Qt.ArrowCursor
        self.view.setCursor(cursor)
        if hit is not self.hover:
            self.hover = hit
            self.overlay.update()
        return False

    def _press(self, e):
        pos = e.position()
        pt = self.view._sp(pos)
        if self.editor is not None:
            self.commit()
        if e.button() == Qt.RightButton:
            hit = self._hit(pt)
            if hit and hit["kind"] == "image":
                self.sel_image = hit
                self.overlay.update()
                self._image_menu(e.globalPosition().toPoint())
                return True
            return False                       # zoom / page menu as usual
        if e.button() != Qt.LeftButton:
            return False
        self.view.setFocus()
        if self.sel_image is not None:
            for k, h in self.handles(self.q(self.sel_image["rect"])).items():
                if h.adjusted(-3, -3, 3, 3).contains(pos):
                    self.drag = (k, pos, fitz.Rect(self.sel_image["rect"]))
                    return True
        hit = self._hit(pt)
        if hit and hit["kind"] == "image":
            self.sel_image = hit
            self.drag = ("move", pos, fitz.Rect(hit["rect"]))
            self.overlay.update()
            return True
        self.sel_image = None
        if hit and hit["kind"] == "text":
            self.open(pt, pos)
        self.overlay.update()
        return True

    def _release(self, e):
        if not self.drag:
            return e.button() == Qt.LeftButton
        mode, start, r0 = self.drag
        self.drag = None
        r = self.ghost
        self.ghost = None
        moved = r is not None and (abs(r.x0 - r0.x0) > 0.5 or
                                   abs(r.y0 - r0.y0) > 0.5 or
                                   abs(r.width - r0.width) > 0.5 or
                                   abs(r.height - r0.height) > 0.5)
        if moved:
            self.image_op("move_image", rect=r)
        self.overlay.update()
        return True

    def _double(self, e):
        pt = self.view._sp(e.position())
        if self._hit(pt) is None and e.button() == Qt.LeftButton:
            self.open(pt, e.position(), new=True)
        return True

    def _key(self, e):
        if self.sel_image is None:
            if e.key() == Qt.Key_Escape and self.editor is None:
                self.finish()
                return True
            return False
        k = e.key()
        if k in (Qt.Key_Delete, Qt.Key_Backspace):
            self.image_op("delete_image")
            return True
        step = 10 if e.modifiers() & Qt.ShiftModifier else 1
        d = {Qt.Key_Left: (-step, 0), Qt.Key_Right: (step, 0),
             Qt.Key_Up: (0, -step), Qt.Key_Down: (0, step)}.get(k)
        if d:
            r = fitz.Rect(self.sel_image["rect"]) + (d[0], d[1], d[0], d[1])
            self.image_op("move_image", rect=r)
            return True
        if k == Qt.Key_Escape:
            self.sel_image = None
            self.overlay.update()
            return True
        return False

    # ---------------------------------------------------------- images
    def _image_menu(self, gpos):
        m = QMenu(self.view)
        m.addAction("Replace Image…", self.replace_image)
        m.addAction("Delete Image", lambda: self.image_op("delete_image"))
        m.exec(gpos)

    def replace_image(self):
        path, _ = QFileDialog.getOpenFileName(
            self.view, "Replace Image", "",
            "Images (*.png *.jpg *.jpeg *.gif *.bmp *.tif *.tiff)")
        if not path:
            return 0
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode("ascii")
        return self.image_op("replace_image", data=data)

    def image_op(self, kind, rect=None, **extra):
        b = self.sel_image
        if b is None:
            return 0
        if b.get("shared") and kind != "replace_image":
            self.view.status.emit("This picture is used more than once on "
                                  "the page, so it can only be replaced.")
            return 0
        pg = self.view.pg
        r = annotate.to_page(pg, fitz.Rect(rect or b["rect"]))
        payload = {"rect": list(r), "xref": b["xref"], **extra}
        if kind != "delete_image" and rect is not None:
            payload["from"] = list(annotate.to_page(pg, fitz.Rect(
                b["rect"])))
        n = self.view.apply_marks([(self.view.page, kind, payload)])
        if kind == "delete_image":
            self.sel_image = None
        elif n:
            self.sel_image = {"kind": "image", "rect": fitz.Rect(
                rect or b["rect"]), "xref": None}
            QTimer.singleShot(0, self._reselect(rect or b["rect"]))
        return n

    def _reselect(self, rect):
        def go():
            self.refresh()
            want = fitz.Rect(rect)
            best = None
            for b in self.blocks:
                if b["kind"] == "image" and \
                        abs(b["rect"].x0 - want.x0) < 2 and \
                        abs(b["rect"].y0 - want.y0) < 2:
                    best = b
            self.sel_image = best
            self.overlay.update()
        return go

    # ---------------------------------------------------------- text
    def open(self, pt, pos=None, new=False):
        v = self.view
        if new:
            blk = {"rect": [pt.x, pt.y - 2, min(pt.x + 220, v.pg.rect.x1 -
                                                   4), pt.y + 14],
                   "text": "", "size": 11.0, "color": [0, 0, 0],
                   "font": "Helvetica", "bold": False, "italic": False,
                   "lines": 1, "align": "left", "line_height": None}
        else:
            blk = v.block_at(pt)
            if blk is None:
                return
        z = v.zoom
        fam, css, label = screen_family(v.doc, v.pg, blk.get("font"))
        self.family_css = {f[1]: f[2] for f in FAMILIES}
        self.family_css[fam] = css
        self.edit = dict(blk, new=new)
        self._zoom = z
        r = fitz.Rect(blk["rect"])
        ed = QTextEdit(v)
        ed.setFrameShape(QFrame.NoFrame)
        ed.setAcceptRichText(False)
        ed.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        ed.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        ed.document().setDocumentMargin(0)
        ed.setLineWrapMode(QTextEdit.FixedPixelWidth)
        ed.setLineWrapColumnOrWidth(max(20, int(r.width * z)))
        ed.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        acc = theme.color("accent").name()   # a QColor isn't CSS
        ed.setObjectName("PdfTextEditor")
        pal = ed.palette()              # the page is white in either theme
        for role in (QPalette.Base, QPalette.Window):
            pal.setColor(role, QColor("white"))
        pal.setColor(QPalette.Text, QColor("black"))
        ed.setPalette(pal)
        ed.viewport().setPalette(pal)
        ed.viewport().setAutoFillBackground(True)
        ed.setStyleSheet(f"QTextEdit{{background:white;color:black;"
                         f"border:1px solid {acc};"
                         f"selection-background-color:#b3d1ff;"
                         f"selection-color:black}}")
        font = QFont(fam)
        font.setPixelSize(max(4, round(blk["size"] * z)))
        font.setBold(bool(blk.get("bold")))
        font.setItalic(bool(blk.get("italic")))
        ed.document().setDefaultFont(font)
        ed.setPlainText(blk.get("rich_text") or blk["text"])
        cur = QTextCursor(ed.document())
        cur.select(QTextCursor.Document)
        cf = QTextCharFormat()
        cf.setFont(font)
        c = blk.get("color") or [0, 0, 0]
        cf.setForeground(QColor.fromRgbF(*[max(0, min(1, x)) for x in c]))
        cur.mergeCharFormat(cf)
        bf = QTextBlockFormat()
        bf.setAlignment({"center": Qt.AlignHCenter, "right": Qt.AlignRight,
                         "justify": Qt.AlignJustify}.get(blk.get("align"),
                                                         Qt.AlignLeft))
        if blk.get("line_height"):
            fixed = QTextBlockFormat.LineHeightTypes.FixedHeight
            bf.setLineHeight(blk["line_height"] * z,
                             int(getattr(fixed, "value", fixed)))
        cur.mergeBlockFormat(bf)
        ed.setCurrentCharFormat(cf)
        self.editor = ed
        self._start_html = to_html(ed.document(), z, self.family_css)
        ed.textChanged.connect(self._fit)
        ed.cursorPositionChanged.connect(self._sync_bar)
        ed.installEventFilter(self._EdKeys(self))
        ed.setContentsMargins(3, 3, 3, 3)     # text sits where it was
        ed.setGeometry(int(r.x0 * z) - 4, int(r.y0 * z) - 4,
                       max(28, int(r.width * z) + 16), int(r.height * z) + 12)
        ed.show()
        self._fit()
        ed.setFocus()
        if pos is not None and not new:
            ed.setTextCursor(ed.cursorForPosition(
                ed.viewport().mapFrom(v, pos.toPoint())))
        self.bar = _FormatBar(self)
        self.bar.family.addItem(label, fam)
        for name, qtfam, _css in FAMILIES:
            if qtfam != fam:
                self.bar.family.addItem(name, qtfam)
        self.bar.show()
        self._place_bar()
        self._sync_bar()
        self.overlay.update()

    class _EdKeys(QObject):
        def __init__(self, ctl):
            super().__init__(ctl)
            self.ctl = ctl

        def eventFilter(self, obj, e):
            if e.type() == QEvent.KeyPress:
                if e.key() == Qt.Key_Escape:
                    self.ctl.cancel()
                    return True
                if e.key() in (Qt.Key_Return, Qt.Key_Enter) and \
                        e.modifiers() & Qt.ControlModifier:
                    self.ctl.commit()
                    return True
                if e.modifiers() & Qt.ControlModifier and \
                        e.key() == Qt.Key_B:
                    self.ctl.set_bold(not self.ctl.bar.bold.isChecked())
                    return True
                if e.modifiers() & Qt.ControlModifier and \
                        e.key() == Qt.Key_I:
                    self.ctl.set_italic(not self.ctl.bar.italic.isChecked())
                    return True
            return False

    def _fit(self):
        ed = self.editor
        if ed is None:
            return
        h = int(ed.document().size().height()) + 14
        r = fitz.Rect(self.edit["rect"])
        h = max(h, int(r.height * self.view.zoom) + 12)
        ed.resize(ed.width(), h)
        self._place_bar()

    def _place_bar(self):
        if self.bar is None or self.editor is None:
            return
        g = self.editor.geometry()
        self.bar.adjustSize()
        y = g.top() - self.bar.height() - 6
        if y < 0:
            y = g.bottom() + 6
        x = max(0, min(g.left(), self.view.width() - self.bar.width()))
        self.bar.move(x, y)
        self.bar.raise_()

    def _sync_bar(self):
        if self.editor is None or self.bar is None:
            return
        cf = self.editor.currentCharFormat()
        f = cf.font()
        b = self.bar
        for w in (b.size, b.bold, b.italic, b.family):
            w.blockSignals(True)
        px = f.pixelSize() if f.pixelSize() > 0 else 12
        b.size.setValue(px / self.view.zoom)
        b.bold.setChecked(f.weight() >= QFont.DemiBold)
        b.italic.setChecked(f.italic())
        i = b.family.findData(f.family())
        if i >= 0:
            b.family.setCurrentIndex(i)
        al = self.editor.alignment() & Qt.AlignHorizontal_Mask
        cur = {Qt.AlignHCenter: "center", Qt.AlignRight: "right",
               Qt.AlignJustify: "justify"}.get(al, "left")
        for k, btn in b.aligns.items():
            btn.setChecked(k == cur)
        col = cf.foreground().color()
        b.color.setStyleSheet(f"color:{col.name()};font-weight:700;"
                              f"border-bottom:3px solid {col.name()}")
        for w in (b.size, b.bold, b.italic, b.family):
            w.blockSignals(False)

    def _fmt(self, cf):
        """Apply to the selection, or the whole paragraph if none."""
        ed = self.editor
        cur = ed.textCursor()
        if not cur.hasSelection():
            cur = QTextCursor(ed.document())
            cur.select(QTextCursor.Document)
        cur.mergeCharFormat(cf)
        ed.mergeCurrentCharFormat(cf)
        self._fit()
        self._sync_bar()
        ed.setFocus()

    def set_family(self, qtfam):
        if self.editor is None or not qtfam:
            return
        cf = QTextCharFormat()
        cf.setFontFamilies([qtfam])
        self._fmt(cf)

    def set_size(self, pt):
        if self.editor is None:
            return
        cf = QTextCharFormat()
        f = QFont()
        f.setPixelSize(max(4, round(pt * self.view.zoom)))
        cf.setFont(f, QTextCharFormat.FontPropertiesSpecifiedOnly)
        self._fmt(cf)

    def set_bold(self, on):
        if self.editor is None:
            return
        cf = QTextCharFormat()
        cf.setFontWeight(QFont.Bold if on else QFont.Normal)
        self._fmt(cf)

    def set_italic(self, on):
        if self.editor is None:
            return
        cf = QTextCharFormat()
        cf.setFontItalic(bool(on))
        self._fmt(cf)

    def pick_color(self):
        if self.editor is None:
            return
        c = QColorDialog.getColor(self.editor.currentCharFormat()
                                  .foreground().color(), self.view)
        if c.isValid():
            cf = QTextCharFormat()
            cf.setForeground(c)
            self._fmt(cf)

    def set_align(self, key):
        if self.editor is None:
            return
        cur = self.editor.textCursor()
        if not cur.hasSelection():
            cur = QTextCursor(self.editor.document())
            cur.select(QTextCursor.Document)
        bf = QTextBlockFormat()
        bf.setAlignment({"center": Qt.AlignHCenter, "right": Qt.AlignRight,
                         "justify": Qt.AlignJustify}.get(key, Qt.AlignLeft))
        cur.mergeBlockFormat(bf)
        self._sync_bar()
        self.editor.setFocus()

    def _close(self):
        for w in (self.editor, self.bar):
            if w is not None:
                w.hide()
                w.deleteLater()
        self.editor = self.bar = None
        self.edit = None
        self.overlay.update()

    def cancel(self):
        self._close()
        self.view.setFocus()

    def commit(self):
        """Write the edit into the page (one undoable step)."""
        ed = self.editor
        if ed is None:
            return 0
        z = getattr(self, "_zoom", self.view.zoom)
        text = ed.toPlainText()
        html = to_html(ed.document(), z, self.family_css)
        blk = self.edit
        self._close()
        if html == self._start_html:
            return 0
        if blk.get("new") and not text.strip():
            return 0
        r = fitz.Rect(blk["rect"])
        payload = {"rect": list(r), "text": text, "html": html,
                   "size": round(blk["size"], 2), "color": blk["color"],
                   "font": blk.get("font", ""), "bold": blk.get("bold"),
                   "italic": blk.get("italic"), "align": blk.get("align"),
                   "line_height": blk.get("line_height"),
                   "new": bool(blk.get("new"))}
        n = self.view.apply_marks([(self.view.page, "replace_block",
                                    payload)])
        QTimer.singleShot(0, self.refresh)
        self.view.setFocus()
        return n
