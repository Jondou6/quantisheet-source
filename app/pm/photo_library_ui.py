"""Project > Photos: the job's photos in albums (by date, area or tag),
with tags, area and a pin on a sheet (photo_library)."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QPushButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout)

from . import photo_library as pl


class PhotoLibraryDialog(QDialog):
    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Project Photos")
        self.resize(760, 520)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Albums by"))
        self.by = QComboBox()
        self.by.addItems(["Date", "Area", "Tag"])
        self.by.currentTextChanged.connect(lambda _t: self.refresh())
        top.addWidget(self.by)
        top.addWidget(QLabel("Show tag"))
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("any")
        self.filter.textChanged.connect(lambda _t: self.refresh())
        top.addWidget(self.filter, 1)
        lay.addLayout(top)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Photo", "Taken", "Area", "Tags", "Pin",
                                   "From"])
        lay.addWidget(self.tree, 1)
        row = QHBoxLayout()
        for text, fn in (("Tags…", self.edit_tags), ("Area…", self.edit_area),
                         ("Pin on a sheet…", self.edit_pin),
                         ("Remove pin", self.remove_pin)):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, f=fn: f())
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.note = QLabel("Location data inside the photos is never read "
                           "out or sent anywhere.")
        self.note.setObjectName("muted")
        lay.addWidget(self.note)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.refresh()

    def refresh(self):
        self.tree.clear()
        tag = self.filter.text().strip()
        keep = {p["key"] for p in (pl.with_tag(self.store, tag) if tag
                                   else pl.photos(self.store))}
        for name, ps in pl.albums(self.store,
                                  self.by.currentText().lower()).items():
            ps = [p for p in ps if p["key"] in keep]
            if not ps:
                continue
            top = QTreeWidgetItem([f"{name} ({len(ps)})"])
            self.tree.addTopLevelItem(top)
            for p in ps:
                pin = p["pin"] or {}
                it = QTreeWidgetItem([
                    p["ref"].get("name") or p["key"][:12], p["date"],
                    p["area"], ", ".join(p["tags"]),
                    pin.get("sheet", ""), f"{p['coll']} {p['no'] or ''}"])
                it.setData(0, Qt.UserRole, p["key"])
                top.addChild(it)
            top.setExpanded(True)

    def _key(self):
        it = self.tree.currentItem()
        return it.data(0, Qt.UserRole) if it is not None else None

    def _photo(self, key):
        return next((p for p in pl.photos(self.store) if p["key"] == key),
                    None)

    def edit_tags(self, key=None, text=None):
        key = key or self._key()
        if not key:
            return None
        if text is None:
            p = self._photo(key) or {}
            text, ok = QInputDialog.getText(
                self, "Tags", "Tags (comma between):",
                text=", ".join(p.get("tags") or []))
            if not ok:
                return None
        got = pl.set_tags(self.store, key, text.split(","))
        self.refresh()
        return got

    def edit_area(self, key=None, text=None):
        key = key or self._key()
        if not key:
            return
        if text is None:
            p = self._photo(key) or {}
            text, ok = QInputDialog.getText(self, "Area", "Area / room:",
                                            text=p.get("area") or "")
            if not ok:
                return
        pl.set_area(self.store, key, text)
        self.refresh()

    def edit_pin(self, key=None, sheet=None, page=0, x=None, y=None,
                 drawing=None):
        """Pin on a sheet: the sheet number, then where on it - a click on
        the drawing when its PDF is picked (else the middle of the sheet;
        the owner report's key plan shows it)."""
        key = key or self._key()
        if not key:
            return
        if sheet is None:
            sheet, ok = QInputDialog.getText(self, "Pin on a sheet",
                                             "Sheet number (e.g. A-102):")
            if not ok or not sheet.strip():
                return
        if x is None and drawing is None:
            from PySide6.QtWidgets import QFileDialog
            drawing, _ = QFileDialog.getOpenFileName(
                self, f"The drawing with {sheet.strip().upper()} - click "
                "where the photo was taken (Cancel = the middle)", "",
                "PDF (*.pdf)")
        if x is None and drawing:
            dlg = PinPickDialog(drawing, page, self)
            if dlg.exec() != QDialog.Accepted or dlg.point is None:
                return
            x, y = dlg.point
        pl.pin(self.store, key, sheet.strip().upper(), page,
               306.0 if x is None else x, 396.0 if y is None else y)
        self.refresh()

    def remove_pin(self, key=None):
        key = key or self._key()
        if key:
            pl.unpin(self.store, key)
            self.refresh()


class PinPickDialog(QDialog):
    """The sheet as a picture: a click sets the pin (in PDF points)."""
    MAX = 900

    def __init__(self, path, page=0, parent=None):
        super().__init__(parent)
        import fitz
        from PySide6.QtGui import QImage, QPixmap
        self.setWindowTitle("Click where the photo was taken")
        self.point = None
        with fitz.open(path) as d:
            pg = d[min(max(int(page), 0), d.page_count - 1)]
            r = pg.rect
            self.scale = min(self.MAX / max(r.width, r.height), 2.0)
            pix = pg.get_pixmap(matrix=fitz.Matrix(self.scale, self.scale),
                                alpha=False)
            self.rect = (r.x0, r.y0)
        img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                     QImage.Format_RGB888).copy()
        lay = QVBoxLayout(self)
        self.view = QLabel()
        self.view.setPixmap(QPixmap.fromImage(img))
        self.view.mousePressEvent = lambda e: self.pick_at(
            e.position().x(), e.position().y())
        lay.addWidget(self.view)
        self.where = QLabel("Click the drawing.")
        lay.addWidget(self.where)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def pick_at(self, px, py):
        """A click at (px, py) on the picture -> the point on the sheet."""
        self.point = (round(self.rect[0] + px / self.scale, 1),
                      round(self.rect[1] + py / self.scale, 1))
        self.where.setText(f"Pin at {self.point[0]:.0f}, "
                           f"{self.point[1]:.0f} - OK to keep it.")
        return self.point
