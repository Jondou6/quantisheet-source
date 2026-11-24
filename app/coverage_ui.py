"""Estimate > Coverage Map…: every sheet as a thumbnail tinted green
(reviewed), amber (taken off, not reviewed or waiting for its second
check) or red (nothing), with the taken-off areas shaded on it, its
coverage %, who reviewed it and who checked it."""
import fitz
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QDialog, QDoubleSpinBox,
                               QHBoxLayout, QLabel, QListView, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton,
                               QVBoxLayout)

from . import coverage, prebid, settings

COLORS = {"green": QColor(46, 160, 67), "amber": QColor(230, 160, 20),
          "red": QColor(210, 50, 50)}
THUMB = 170


def _thumb(page, rects, color, title_frac):
    """Page picture with the taken-off boxes shaded and a status border."""
    z = THUMB / max(page.rect.width, page.rect.height)
    pix = page.get_pixmap(matrix=fitz.Matrix(z, z), alpha=False)
    img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                 QImage.Format_RGB888).copy()
    p = QPainter(img)
    p.setPen(Qt.NoPen)
    shade = QColor(46, 160, 67, 110)
    for r in rects:
        p.fillRect(int(r.x0 * z) - 1, int(r.y0 * z) - 1,
                   max(3, int(r.width * z) + 2),
                   max(3, int(r.height * z) + 2), shade)
    # title block strip (left out of the coverage %)
    tb = page.rect.width * (1 - title_frac) * z
    p.fillRect(int(tb), 0, img.width() - int(tb), img.height(),
               QColor(0, 0, 0, 25))
    pen = QPen(COLORS[color])
    pen.setWidth(6)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawRect(3, 3, img.width() - 6, img.height() - 6)
    p.end()
    return QPixmap.fromImage(img)


class CoverageDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Coverage Map")
        self.resize(1100, 760)
        lay = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        key = QLabel("<span style='color:#2ea043'>■</span> reviewed &nbsp; "
                     "<span style='color:#e6a014'>■</span> taken off, not "
                     "reviewed or not checked &nbsp; "
                     "<span style='color:#d23232'>■</span> nothing yet. "
                     "Shaded = taken off. Double-click a sheet to go to it.")
        lay.addWidget(key)
        self.grid = QListWidget()
        self.grid.setViewMode(QListView.IconMode)
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setIconSize(QSize(THUMB, THUMB))
        self.grid.setGridSize(QSize(THUMB + 24, THUMB + 56))
        self.grid.setSelectionMode(QListWidget.ExtendedSelection)
        self.grid.setWordWrap(True)
        self.grid.itemDoubleClicked.connect(self._go)
        lay.addWidget(self.grid, 1)

        row = QHBoxLayout()
        self.rev_btn = QPushButton("Mark Reviewed")
        self.rev_btn.clicked.connect(lambda _c=False: self.mark_reviewed())
        self.chk_btn = QPushButton("Second Check ✓")
        self.chk_btn.setToolTip("Check sheets someone else reviewed")
        self.chk_btn.clicked.connect(lambda _c=False: self.mark_checked())
        row.addWidget(self.rev_btn)
        row.addWidget(self.chk_btn)
        row.addStretch(1)
        self.required = QCheckBox("Second check required to lock the bid")
        self.required.setChecked(bool(settings.get("second_check_required",
                                                   False)))
        self.required.toggled.connect(self._save_settings)
        row.addWidget(self.required)
        row.addWidget(QLabel("for bids over $"))
        self.over = QDoubleSpinBox()
        self.over.setRange(0, 1e9)
        self.over.setDecimals(0)
        self.over.setSingleStep(50000)
        self.over.setSpecialValueText("any amount")
        self.over.setValue(float(settings.get("second_check_over", 0) or 0))
        self.over.valueChanged.connect(self._save_settings)
        row.addWidget(self.over)
        lay.addLayout(row)
        self._queue = []
        self._timer = QTimer(self)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._draw_some)
        self.refresh()

    @property
    def doc(self):
        v = self.win._view
        return v.doc if v else None

    def _save_settings(self):
        settings.set("second_check_required", self.required.isChecked())
        settings.set("second_check_over", self.over.value())
        self.refresh()

    def refresh(self):
        doc = self.doc
        self.grid.clear()
        if doc is None:
            return
        self.rows = coverage.status(doc)
        rects = {}
        from . import annotate
        for it in annotate.takeoff_items(doc):
            rects.setdefault(it["page"], []).append(fitz.Rect(it["rect"]))
        self._rects = rects
        n = {c: sum(1 for r in self.rows if r["color"] == c)
             for c in COLORS}
        need = coverage.second_check_required()
        left = sum(1 for r in self.rows if r["reviewed"] and
                   not r["checked"])
        self.summary.setText(
            f"<b>{len(self.rows)} sheets:</b> {n['green']} done, "
            f"{n['amber']} in progress, {n['red']} with nothing taken off."
            + (f" Second check is required: {left} reviewed sheet(s) "
               "still need it." if need else ""))
        for r in self.rows:
            it = QListWidgetItem(self._text(r))
            it.setData(Qt.UserRole, r["page"])
            it.setToolTip(self._tip(r))
            it.setTextAlignment(Qt.AlignHCenter)
            self.grid.addItem(it)
        self._queue = list(range(len(self.rows)))
        self._timer.start()

    def _draw_some(self):
        doc = self.doc
        if doc is None or not self._queue:
            self._timer.stop()
            return
        for _ in range(4):                    # a few per tick: stays live
            if not self._queue:
                break
            i = self._queue.pop(0)
            r = self.rows[i]
            try:
                pm = _thumb(doc[r["page"]], self._rects.get(r["page"], []),
                            r["color"], coverage.TITLE_BLOCK)
                self.grid.item(i).setIcon(QIcon(pm))
            except Exception:
                pass

    @staticmethod
    def _text(r):
        s = f"{r['sheet']}\n{r['coverage']:.0%} covered"
        if r["checked"]:
            s += " · ✓✓"
        elif r["reviewed"]:
            s += " · ✓"
        return s

    @staticmethod
    def _tip(r):
        out = [f"{r['sheet']} (page {r['page'] + 1})",
               f"{r['takeoff']} takeoff mark(s), {r['coverage']:.0%} of the "
               "drawing area"]
        out.append(f"Reviewed by {r['by']}" if r["reviewed"]
                   else "Not reviewed")
        if r["checked"]:
            out.append(f"Second check by {r['checked_by']}")
        return "\n".join(out)

    def _pages(self):
        return [it.data(Qt.UserRole) for it in self.grid.selectedItems()]

    def _go(self, item):
        self.win._view.go_to(item.data(Qt.UserRole))

    def mark_reviewed(self, pages=None):
        pages = self._pages() if pages is None else pages
        for p in pages:
            prebid.set_reviewed(self.doc, p)
        if pages:
            self.win._view.mark_dirty()
            self.refresh()
        return len(pages)

    def mark_checked(self, pages=None, by=None):
        pages = self._pages() if pages is None else pages
        done, refused = 0, []
        for p in pages:
            try:
                coverage.set_checked(self.doc, p, by=by)
                done += 1
            except coverage.CheckError as e:
                refused.append(str(e))
        if done:
            self.win._view.mark_dirty()
            self.refresh()
        if refused:
            QMessageBox.information(self, "Second Check",
                                    "\n".join(refused[:10]))
        return done


def show(win, show=True):
    if not win._view:
        return None
    dlg = CoverageDialog(win)
    if show:
        dlg.show()
    return dlg
