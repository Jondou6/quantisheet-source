"""Organize Pages (as in Acrobat): every page as a big thumbnail. Drag to
reorder, select several with Ctrl/Shift, rotate, duplicate or delete
them, then Apply - one undoable step.

The dialog only edits a plan, [(source page, extra rotation)], so Cancel
leaves the document untouched; apply_plan() makes it so.
"""
import fitz
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QImage, QPixmap, QTransform
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox,
                               QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QSlider,
                               QVBoxLayout)

from . import icons, jobdata

ROLE = Qt.UserRole


def apply_plan(doc, plan):
    """plan: [(source page index, extra rotation in degrees)] in the new
    order. Pages left out are deleted; a page listed twice is copied."""
    if not plan:
        raise ValueError("A document needs at least one page.")
    seen = set()
    order = []
    with jobdata.keep_scales(doc):           # scales stay with their pages
        for src, _rot in plan:
            if src in seen:
                doc.fullcopy_page(src, -1)       # a real copy at the end
                order.append(doc.page_count - 1)
            else:
                seen.add(src)
                order.append(src)
        doc.select(order)
    for i, (_src, rot) in enumerate(plan):
        if rot % 360:
            p = doc[i]
            p.set_rotation((p.rotation + rot) % 360)
    return len(plan)


class OrganizeDialog(QDialog):
    def __init__(self, doc, parent=None, current=0):
        super().__init__(parent)
        self.setWindowTitle("Organize Pages")
        self.doc = doc
        self.resize(1100, 760)
        self._thumbs = {}
        v = QVBoxLayout(self)
        bar = QHBoxLayout()
        for label, icon, fn, tip in (
                ("Rotate Left", "rotate_left", lambda: self.rotate(-90),
                 "Ctrl+["),
                ("Rotate Right", "rotate", lambda: self.rotate(90), "Ctrl+]"),
                ("Duplicate", "duplicate", self.duplicate, "Ctrl+D"),
                ("Delete", "page_delete", self.delete, "Delete"),
                ("Reverse", "redo", self.reverse, "")):
            b = QPushButton(label)
            b.setIcon(icons.icon(icon))
            b.setToolTip(f"{label} the selected pages" +
                         (f" ({tip})" if tip else ""))
            if tip:
                b.setShortcut(tip)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        self.info = QLabel()
        self.info.setObjectName("muted")
        bar.addWidget(self.info)
        bar.addWidget(QLabel("Size"))
        self.size = QSlider(Qt.Horizontal)
        self.size.setRange(90, 320)
        self.size.setValue(170)
        self.size.setFixedWidth(140)
        self.size.valueChanged.connect(self._resize)
        bar.addWidget(self.size)
        v.addLayout(bar)
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setMovement(QListWidget.Snap)
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.setDefaultDropAction(Qt.MoveAction)
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setSpacing(12)
        self.list.setWordWrap(True)
        self.list.setUniformItemSizes(True)
        self.list.model().rowsMoved.connect(self._renumber)
        self.list.itemSelectionChanged.connect(self._status)
        v.addWidget(self.list, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Apply")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        for i in range(doc.page_count):
            self.list.addItem(self._item(i, 0))
        self._resize(self.size.value())
        if 0 <= current < self.list.count():
            self.list.setCurrentRow(current)
        self._renumber()
        self._queue = list(range(doc.page_count))
        QTimer.singleShot(0, self._load_some)

    # ------------------------------------------------------------ items
    def _item(self, src, rot):
        it = QListWidgetItem()
        it.setData(ROLE, (src, rot))
        it.setFlags(it.flags() | Qt.ItemIsDragEnabled)
        it.setFlags(it.flags() & ~Qt.ItemIsDropEnabled)
        it.setTextAlignment(Qt.AlignHCenter)
        self._paint(it)
        return it

    def _thumb(self, src):
        pm = self._thumbs.get(src)
        if pm is None:
            page = self.doc[src]
            z = 260 / max(page.rect.width, page.rect.height, 1)
            pix = page.get_pixmap(matrix=fitz.Matrix(z, z), alpha=False)
            img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                         QImage.Format_RGB888).copy()
            pm = self._thumbs[src] = QPixmap.fromImage(img)
        return pm

    def _paint(self, it, load=False):
        src, rot = it.data(ROLE)
        if load or src in self._thumbs:
            pm = self._thumb(src)
            if rot % 360:
                pm = pm.transformed(QTransform().rotate(rot))
            it.setIcon(QIcon(pm))

    def _load_some(self):
        """Render thumbnails a few at a time so big sets open at once."""
        for _ in range(6):
            if not self._queue:
                return
            src = self._queue.pop(0)
            for it in self.items():
                if it.data(ROLE)[0] == src:
                    self._paint(it, load=True)
        QTimer.singleShot(0, self._load_some)

    def items(self):
        return [self.list.item(i) for i in range(self.list.count())]

    def plan(self):
        return [it.data(ROLE) for it in self.items()]

    def _resize(self, px):
        self.list.setIconSize(QSize(px, px))
        self.list.setGridSize(QSize(px + 26, px + 52))

    def _renumber(self, *_):
        for n, it in enumerate(self.items()):
            src, rot = it.data(ROLE)
            moved = "" if src == n else f"  (was {src + 1})"
            it.setText(f"{n + 1}{moved}")
        self._status()

    def _status(self):
        sel = len(self.list.selectedItems())
        changed = self.plan() != [(i, 0) for i in range(self.doc.page_count)]
        self.info.setText(f"{self.list.count()} pages" +
                          (f" · {sel} selected" if sel > 1 else "") +
                          (" · not applied yet" if changed else ""))

    def _selected(self):
        return sorted(self.list.row(it) for it in self.list.selectedItems())

    # ------------------------------------------------------------ actions
    def rotate(self, deg):
        for r in self._selected():
            it = self.list.item(r)
            src, rot = it.data(ROLE)
            it.setData(ROLE, (src, (rot + deg) % 360))
            self._paint(it, load=True)
        self._status()

    def duplicate(self):
        rows = self._selected()
        for k, r in enumerate(rows):
            src, rot = self.list.item(r + k).data(ROLE)
            self.list.insertItem(r + k + 1, self._item(src, rot))
        self._renumber()

    def delete(self):
        rows = self._selected()
        if len(rows) >= self.list.count():
            self.info.setText("A document needs at least one page.")
            return
        for r in reversed(rows):
            self.list.takeItem(r)
        self._renumber()

    def reverse(self):
        rows = self._selected() or list(range(self.list.count()))
        data = [self.list.item(r).data(ROLE) for r in rows]
        for r, d in zip(rows, reversed(data)):
            it = self.list.item(r)
            it.setData(ROLE, d)
            self._paint(it, load=d[0] in self._thumbs)
        self._renumber()

    def move(self, row, to):
        """Move one page (what a drag does)."""
        it = self.list.takeItem(row)
        self.list.insertItem(to, it)
        self._renumber()
