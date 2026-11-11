"""Show where a number came from (Nov 11): the page of the sub's quote
with the words it was read from boxed.

A source is {"file", "page", "rect": [x0, y0, x1, y1]} in PDF points
(proposal_level.source_of). The file is opened read-only and never
changed. Pictures of a quote (a phone photo) open the same way.
"""
import os

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel,
                               QMessageBox, QScrollArea, QVBoxLayout)

ZOOM = 2.0
PAD = 3.0                 # points around the words


def problem(src):
    """Why this source can't be shown ('' when it can)."""
    if not src or not src.get("rect"):
        return ("There is no place in the file to show for this value "
                "(it was typed in, or the scan gave text without "
                "positions).")
    if not src.get("file") or not os.path.isfile(src["file"]):
        return ("The quote file isn't where it was when it was read:\n"
                f"{src.get('file') or '(no file)'}")
    return ""


def render(src, zoom=ZOOM):
    """(QImage of the page, QRectF of the words on it in pixels)."""
    import fitz
    from . import proposal_level
    with proposal_level._open(src["file"]) as d:
        n = int(src.get("page") or 0)
        if not 0 <= n < len(d):
            raise ValueError("That page isn't in the file any more.")
        page = d[n]
        pm = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        img = QImage(pm.samples, pm.width, pm.height, pm.stride,
                     QImage.Format_RGB888).copy()
        r = fitz.Rect(src["rect"]) * page.rotation_matrix
        r.normalize()
    box = QRectF((r.x0 - PAD) * zoom, (r.y0 - PAD) * zoom,
                 (r.width + 2 * PAD) * zoom, (r.height + 2 * PAD) * zoom)
    return img, box


def words_at(src):
    """The text inside the source rectangle (text PDFs; '' for a scan),
    for checking that the box is on the right words."""
    import fitz
    from . import proposal_level
    with proposal_level._open(src["file"]) as d:
        page = d[int(src.get("page") or 0)]
        r = fitz.Rect(src["rect"]) + (-1, -1, 1, 1)
        return " ".join(w[4] for w in page.get_text("words")
                        if fitz.Rect(w[:4]).intersects(r) and
                        r.contains(fitz.Point((w[0] + w[2]) / 2,
                                              (w[1] + w[3]) / 2)))


class SourceDialog(QDialog):
    def __init__(self, src, parent=None, what=""):
        super().__init__(parent)
        self.setWindowTitle("Source - " + os.path.basename(src["file"]))
        self.resize(900, 700)
        v = QVBoxLayout(self)
        v.addWidget(QLabel(
            (f"<b>{what}</b> - " if what else "") +
            f"{os.path.basename(src['file'])}, page "
            f"{int(src.get('page') or 0) + 1}. The red box is where it was "
            "read. The file is not changed."))
        img, self.box = render(src)
        pm = QPixmap.fromImage(img)
        p = QPainter(pm)
        p.fillRect(self.box, QColor(255, 235, 59, 70))
        pen = QPen(QColor(200, 0, 0))
        pen.setWidth(3)
        p.setPen(pen)
        p.drawRect(self.box)
        p.end()
        self.label = QLabel()
        self.label.setPixmap(pm)
        self.area = QScrollArea()
        self.area.setWidget(self.label)
        self.area.setAlignment(Qt.AlignCenter)
        v.addWidget(self.area, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        QTimer.singleShot(0, self._center)

    def _center(self):
        c = self.box.center()
        self.area.ensureVisible(int(c.x()), int(c.y()),
                                self.area.viewport().width() // 2,
                                self.area.viewport().height() // 2)


def show(parent, src, what="", modal=True):
    """Open the source, or say why it can't be shown. Returns the dialog
    (None when it couldn't be opened)."""
    why = problem(src)
    if not why:
        try:
            dlg = SourceDialog(src, parent, what)
        except Exception as e:                            # noqa: BLE001
            why = f"The quote couldn't be opened: {e}"
    if why:
        QMessageBox.information(parent, "Source", why)
        return None
    if modal:
        dlg.exec()
    else:
        dlg.show()
    return dlg
