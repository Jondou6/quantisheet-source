"""File > Print Preview (Nov 3): see what will print before it goes to
the printer - each page as it sits on the paper (size, orientation,
margins, with your markups), one page at a time so a big set opens at
once, then Print.

Pages are drawn the way print_to() prints them: the whole sheet, fitted
to the paper's printable area, keeping its proportions."""
from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QDialog, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QRadioButton,
                               QSizePolicy, QVBoxLayout, QWidget)

PREVIEW_LONG_PX = 1400          # a page is drawn this big, at most


def paper_layout(printer):
    """(paper w, paper h, printable rect) in points, from the printer."""
    from PySide6.QtGui import QPageLayout
    lay = printer.pageLayout()
    full = lay.fullRect(QPageLayout.Point)
    paint = lay.paintRect(QPageLayout.Point)
    return full.width(), full.height(), paint


def fit(sheet_w, sheet_h, area):
    """The sheet fitted into `area` (QRectF), keeping its proportions:
    (x, y, w, h) - the same fit print_to() uses."""
    if sheet_w <= 0 or sheet_h <= 0:
        return area.x(), area.y(), 0.0, 0.0
    s = min(area.width() / sheet_w, area.height() / sheet_h)
    w, h = sheet_w * s, sheet_h * s
    return area.x(), area.y(), w, h


def render_sheet(page, long_px=PREVIEW_LONG_PX):
    """The page with its markups as a QImage, long side `long_px`."""
    import fitz
    r = page.rect
    z = long_px / max(r.width, r.height, 1)
    pix = page.get_pixmap(matrix=fitz.Matrix(z, z), alpha=False)
    return QImage(pix.samples, pix.width, pix.height, pix.stride,
                  QImage.Format_RGB888).copy()


def preview_image(page, printer, long_px=900):
    """The paper with the sheet on it, as the preview shows it."""
    pw, ph, paint = paper_layout(printer)
    z = long_px / max(pw, ph, 1)
    img = QImage(int(pw * z), int(ph * z), QImage.Format_RGB32)
    img.fill(QColor(255, 255, 255))
    sheet = render_sheet(page, long_px)
    x, y, w, h = fit(sheet.width(), sheet.height(),
                     QRectF(paint.x() * z, paint.y() * z,
                            paint.width() * z, paint.height() * z))
    p = QPainter(img)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.drawImage(QRectF(x, y, w, h), sheet)
    p.setPen(QColor(200, 200, 200))
    p.drawRect(QRectF(paint.x() * z, paint.y() * z, paint.width() * z,
                      paint.height() * z))   # the printable area
    p.end()
    return img


class PrintPreview(QDialog):
    """One page at a time on its paper; choose the pages and the paper,
    then Print. `pages()` is what was chosen (0-based)."""

    def __init__(self, doc, printer, current=0, parent=None):
        super().__init__(parent)
        self.doc, self.printer = doc, printer
        self.setWindowTitle("Print Preview")
        self.resize(980, 760)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.prev_btn = QPushButton("◀ Previous")
        self.prev_btn.clicked.connect(lambda: self.step(-1))
        self.next_btn = QPushButton("Next ▶")
        self.next_btn.clicked.connect(lambda: self.step(1))
        self.where = QLabel("")
        top.addWidget(self.prev_btn)
        top.addWidget(self.next_btn)
        top.addWidget(self.where)
        top.addStretch(1)
        setup = QPushButton("Paper && Orientation…")
        setup.clicked.connect(lambda: self.page_setup())
        top.addWidget(setup)
        lay.addLayout(top)
        self.view = QLabel()
        self.view.setAlignment(Qt.AlignCenter)
        self.view.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.view.setStyleSheet("background:#6b6b6b")
        lay.addWidget(self.view, 1)
        rng = QWidget()
        rl = QHBoxLayout(rng)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(QLabel("Print:"))
        self.group = QButtonGroup(self)
        self.all_rb = QRadioButton(f"All {doc.page_count} pages")
        self.cur_rb = QRadioButton("This page")
        self.some_rb = QRadioButton("Pages:")
        for i, b in enumerate((self.all_rb, self.cur_rb, self.some_rb)):
            self.group.addButton(b, i)
            rl.addWidget(b)
        self.range = QLineEdit()
        self.range.setPlaceholderText("e.g. 1-4, 7")
        self.range.setMaximumWidth(140)
        self.range.textEdited.connect(lambda _t: self.some_rb.setChecked(True))
        rl.addWidget(self.range)
        rl.addStretch(1)
        self.note = QLabel("")
        rl.addWidget(self.note)
        cancel = QPushButton("Close")
        cancel.clicked.connect(self.reject)
        self.print_btn = QPushButton("Print…")
        self.print_btn.setDefault(True)
        self.print_btn.clicked.connect(lambda: self._print())
        rl.addWidget(cancel)
        rl.addWidget(self.print_btn)
        lay.addWidget(rng)
        self.all_rb.setChecked(True)
        self.page = max(0, min(current, doc.page_count - 1))
        self.show_page()

    # ---- pages -----------------------------------------------------------
    def step(self, d):
        self.page = max(0, min(self.doc.page_count - 1, self.page + d))
        self.show_page()

    def show_page(self):
        n = self.doc.page_count
        self.where.setText(f"Page {self.page + 1} of {n}")
        self.prev_btn.setEnabled(self.page > 0)
        self.next_btn.setEnabled(self.page < n - 1)
        img = preview_image(self.doc[self.page], self.printer)
        self.image = img
        self._place()
        from PySide6.QtGui import QPageLayout
        lay = self.printer.pageLayout()
        size = lay.pageSize().name()
        orient = "landscape" if lay.orientation() == \
            QPageLayout.Landscape else "portrait"
        self.note.setText(f"{size}, {orient}, fitted to the paper")

    def _place(self):
        img = getattr(self, "image", None)
        if img is None:
            return
        room = self.view.size() - QSize(24, 24)
        pm = QPixmap.fromImage(img)
        if room.width() > 50 and room.height() > 50:
            pm = pm.scaled(room, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.view.setPixmap(pm)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place()

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_PageDown, Qt.Key_Right):
            self.step(1)
        elif e.key() in (Qt.Key_PageUp, Qt.Key_Left):
            self.step(-1)
        else:
            super().keyPressEvent(e)

    def page_setup(self):
        from PySide6.QtPrintSupport import QPageSetupDialog
        if QPageSetupDialog(self.printer, self).exec():
            self.show_page()

    def pages(self):
        """0-based pages to print, or None if the range can't be read."""
        n = self.doc.page_count
        i = self.group.checkedId()
        if i == 0:
            return list(range(n))
        if i == 1:
            return [self.page]
        from .scale_guard import parse_pages
        return parse_pages(self.range.text(), n)

    def _print(self):
        if not self.pages():
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Print Preview",
                                    "Type pages like 1-4, 7")
            return
        self.accept()
