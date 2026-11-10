"""Side panels: page thumbnails, takeoff quantities, and the search bar."""

import fitz
from PySide6.QtCore import QPoint, Qt, QSize, QTimer, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QListView, QListWidget, QListWidgetItem, QMenu, QPushButton,
    QTableWidget, QTableWidgetItem, QToolButton, QVBoxLayout, QWidget,
    QCheckBox
)

from . import safecell
from . import annotate, takeoff
from .dmoney import c2 as _c2

THUMB_W = 120


def page_pixmap(page, width):
    zoom = width / max(1, page.rect.width)
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                 QImage.Format_RGB888).copy()
    return QPixmap.fromImage(img)


_busy_until = [0.0]


def mark_busy(seconds=0.35):
    """The user is drawing, dragging or scrolling: background work
    (thumbnails) waits so it doesn't make the pointer stutter."""
    import time
    _busy_until[0] = time.monotonic() + seconds


class ThumbList(QListWidget):
    """Page thumbnails. Click to go to a page, drag to reorder, right-click
    for page actions. Thumbnails render a few at a time so big documents
    open quickly."""

    page_clicked = Signal(int)
    page_moved = Signal(int, int)        # from index, to index
    action = Signal(str, list)           # page action name, page indexes
    files_dropped = Signal(list, int)    # PDFs dropped in, before this page

    def __init__(self):
        super().__init__()
        self.doc = None
        self.setViewMode(QListView.IconMode)
        self.setFlow(QListView.TopToBottom)
        self.setWrapping(False)
        self.setResizeMode(QListView.Adjust)
        self.setIconSize(QSize(THUMB_W, int(THUMB_W * 1.4)))
        self.setSpacing(6)
        self.setMovement(QListView.Snap)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setMinimumWidth(THUMB_W + 40)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.itemClicked.connect(lambda it: self.page_clicked.emit(self.row(it)))
        self.model().rowsMoved.connect(self._moved)
        self._pending = []
        self._timer = QTimer(self)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self._render_some)
        self._quiet = False

    def set_doc(self, doc, current=0):
        self._quiet = True
        self.doc = doc
        self.clear()
        blank = QPixmap(THUMB_W, int(THUMB_W * 1.3))
        blank.fill(Qt.white)
        for i in range(doc.page_count):
            it = QListWidgetItem(QIcon(blank), str(i + 1))
            it.setTextAlignment(Qt.AlignHCenter)
            self.addItem(it)
        self._pending = list(range(doc.page_count))
        self._timer.start()
        self._quiet = False
        self.set_current(current)

    def _visible_rows(self):
        vp = self.viewport().rect()
        first = self.indexAt(vp.topLeft() + QPoint(4, 4)).row()
        last = self.indexAt(vp.bottomLeft() + QPoint(4, -4)).row()
        if first < 0:
            return set()
        last = last if last >= 0 else min(self.count() - 1, first + 8)
        return set(range(max(0, first - 1), min(self.count(), last + 2)))

    def _render_some(self):
        """One thumbnail per tick, the ones on screen first, and none while
        the user is busy on the page."""
        import time
        if time.monotonic() < _busy_until[0]:
            self._timer.start(120)
            return
        if not self._pending or self.doc is None:
            self._timer.stop()
            return
        vis = self._visible_rows()
        k = next((n for n, i in enumerate(self._pending) if i in vis), 0)
        i = self._pending.pop(k)
        if i < self.count() and i < self.doc.page_count:
            self.item(i).setIcon(QIcon(page_pixmap(self.doc[i], THUMB_W)))
        self._timer.start(10 if any(p in vis for p in self._pending)
                          else 40)

    def refresh_page(self, i):
        if self.doc is not None and 0 <= i < min(self.count(),
                                                 self.doc.page_count):
            if i not in self._pending:
                self._pending.insert(0, i)
            self._timer.start()

    def set_current(self, i):
        if 0 <= i < self.count():
            self._quiet = True
            self.setCurrentRow(i)
            self.scrollToItem(self.item(i))
            self._quiet = False

    def selected_pages(self):
        rows = sorted(self.row(it) for it in self.selectedItems())
        return rows or ([self.currentRow()] if self.currentRow() >= 0 else [])

    # ---- drag a PDF in, drag a page out (Nov 4, fewer clicks) ---------------
    @staticmethod
    def _pdf_urls(md):
        return [u.toLocalFile() for u in md.urls() if u.isLocalFile() and
                u.toLocalFile().lower().endswith(".pdf")] if md.hasUrls() \
            else []

    def drop_row(self, pos):
        """The page a drop at `pos` goes before (count = at the end)."""
        it = self.itemAt(pos)
        if it is None:
            return self.count()
        r = self.visualItemRect(it)
        row = self.row(it)
        return row + 1 if pos.y() > r.center().y() else row

    def dragEnterEvent(self, e):
        if e.source() is not self and self._pdf_urls(e.mimeData()):
            e.setDropAction(Qt.CopyAction)
            e.accept()
            return
        super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.source() is not self and self._pdf_urls(e.mimeData()):
            e.setDropAction(Qt.CopyAction)
            e.accept()
            return
        super().dragMoveEvent(e)

    def dropEvent(self, e):
        paths = self._pdf_urls(e.mimeData()) if e.source() is not self \
            else []
        if paths:
            e.setDropAction(Qt.CopyAction)
            e.accept()
            self.files_dropped.emit(paths, self.drop_row(
                e.position().toPoint()))
            return
        super().dropEvent(e)

    def mimeData(self, items):
        """Dragging pages also carries them as a PDF file, so dropping
        them in File Explorer (or an email) extracts them."""
        md = super().mimeData(items)
        try:
            from PySide6.QtCore import QUrl
            path = self.drag_out_file(sorted(self.row(i) for i in items))
            if path:
                md.setUrls([QUrl.fromLocalFile(path)])
        except Exception:                                 # noqa: BLE001
            pass
        return md

    def drag_out_file(self, rows):
        import os
        import tempfile
        from . import pagetools
        if self.doc is None or not rows or len(rows) > 50:
            return None
        base = os.path.splitext(os.path.basename(self.doc.name or
                                                 "document"))[0] or "pages"
        pages = (f"page {rows[0] + 1}" if len(rows) == 1 else
                 f"pages {rows[0] + 1}-{rows[-1] + 1}" if rows[-1] - rows[0]
                 == len(rows) - 1 else f"{len(rows)} pages")
        out = os.path.join(tempfile.mkdtemp(prefix="qs-pages-"),
                           f"{base} - {pages}.pdf")
        pagetools.extract(self.doc, rows, out)
        return out

    def startDrag(self, actions):
        super().startDrag(actions)
        # dropped outside (Explorer): the list must not lose the rows
        if self.doc is not None and self.count() != self.doc.page_count:
            self.set_doc(self.doc, max(0, self.currentRow()))

    def _moved(self, _parent, start, end, _dest, row):
        if self._quiet:
            return
        to = row if row < start else row - 1
        if to != start:
            self.page_moved.emit(start, to)

    def _menu(self, pos):
        pages = self.selected_pages()
        if not pages:
            return
        n = len(pages)
        label = f"{n} pages" if n > 1 else f"page {pages[0] + 1}"
        m = QMenu(self)
        for text, name in (("Rotate Right", "rotate_right"),
                           ("Rotate Left", "rotate_left"),
                           (None, None),
                           ("Insert Blank Page After", "insert_blank"),
                           ("Insert Pages From PDF…", "insert_pdf"),
                           (None, None),
                           (f"Extract {label}…", "extract"),
                           (f"Delete {label}", "delete")):
            if text is None:
                m.addSeparator()
            else:
                m.addAction(text, lambda name=name: self.action.emit(name, pages))
        m.exec(self.mapToGlobal(pos))


class QuantitiesPanel(QWidget):
    """Every takeoff measurement in the document, with totals and export."""

    go_to = Signal(int, object)          # page, annotation ref

    def __init__(self):
        super().__init__()
        self.doc = None
        self.items = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Page", "Type", "Name", "Quantity", "Unit"])
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.cellDoubleClicked.connect(self._open)
        lay.addWidget(self.table)
        self.totals = QLabel("")
        self.totals.setWordWrap(True)
        lay.addWidget(self.totals)
        row = QHBoxLayout()
        self.only_page = QCheckBox("This page only")
        self.only_page.toggled.connect(lambda _: self.refresh())
        export = QPushButton("Export CSV…")
        export.clicked.connect(self._export_dialog)
        row.addWidget(self.only_page)
        row.addStretch()
        row.addWidget(export)
        lay.addLayout(row)
        self.current_page = 0

    def set_doc(self, doc):
        self.doc = doc
        self.refresh()

    def refresh(self):
        if self.doc is None:
            return
        items = annotate.totals_items(self.doc)
        if self.only_page.isChecked():
            items = [i for i in items if i["page"] == self.current_page]
        self.items = items
        self.table.setRowCount(0)
        for it in items:
            r = self.table.rowCount()
            self.table.insertRow(r)
            name = it["group"] or (it["type"].title() if it["type"] in
                                   ("area", "length", "count")
                                   else it["label"])
            if it.get("cutouts"):
                n = it["cutouts"]
                name += (f"  ({_c2(it['gross']):,.2f} gross, less {n} "
                         f"cutout{'s' if n > 1 else ''})")
            if it.get("segments", 0) > 1:     # a run with bends
                name += (f"  ({it['segments']} segments, "
                         f"{it['corners']} corners)")
            value = f"{_c2(it['value']):,.2f}" if it["type"] != "count" else "1"
            for col, text in enumerate((str(it["page"] + 1),
                                        it["type"].title(), name, value,
                                        it["unit"])):
                cell = QTableWidgetItem(text)
                if col in (0, 3):
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, col, cell)
        from . import buyqty
        try:
            buys = buyqty.summary(self.doc, self.summary())
        except Exception:                                 # noqa: BLE001
            buys = {}
        lines = [(f"{k[1].title()} {k[0] or ''}: {_c2(v):,.2f} {k[2]}" +
                  (f" - buy {buys[k[0]][0]:,} {buys[k[0]][1]}"
                   if k[0] in buys else "")).replace("  ", " ")
                 for k, v in sorted(self.summary().items())]
        self.totals.setText("<b>Totals</b><br>" + "<br>".join(lines)
                            if lines else "No measurements yet.")

    def summary(self):
        """{(name, type, unit): total}"""
        out = {}
        for it in self.items:
            key = (it["group"], it["type"], it["unit"])
            out[key] = out.get(key, 0) + it["value"]
        return out

    def _open(self, row, _col):
        if 0 <= row < len(self.items):
            it = self.items[row]
            self.go_to.emit(it["page"], it["ref"])

    def _export_dialog(self):
        from PySide6.QtWidgets import QFileDialog
        import os
        from .reportname import report_file_name
        proj = os.path.splitext(os.path.basename(
            getattr(self.doc, "name", "") or ""))[0]
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Quantities",
            report_file_name("Quantities", proj, ext=".csv"), "CSV (*.csv)")
        if path:
            self.export(path)

    def export(self, path):
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = safecell.writer(f)
            w.writerow(["Page", "Type", "Name", "Quantity", "Unit", "Label"])
            for it in self.items:
                w.writerow([it["page"] + 1, it["type"], it["group"],
                            round(it["value"], 4), it["unit"], it["label"]])
            w.writerow([])
            w.writerow(["Totals"])
            for (name, mtype, unit), v in sorted(self.summary().items()):
                w.writerow(["", mtype, name, round(v, 4), unit])
        return path


class SearchBar(QWidget):
    """Find text: Enter for next, Shift+Enter for previous, Esc to close."""

    show_hit = Signal(int, object, list)     # page, current rect, page hits
    closed = Signal()

    def __init__(self):
        super().__init__()
        self.doc = None
        self.hits = []               # (page, screen rect)
        self.index = -1
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 2, 6, 2)
        lay.addWidget(QLabel("Find:"))
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Search the document")
        self.edit.setClearButtonEnabled(True)
        self.edit.returnPressed.connect(self._enter)
        self.edit.textChanged.connect(lambda _: self._mark_stale())
        lay.addWidget(self.edit, 1)
        self.case = QCheckBox("Match case")
        self.case.toggled.connect(lambda _: self._mark_stale())
        lay.addWidget(self.case)
        for text, step in (("▲", -1), ("▼", 1)):
            b = QToolButton()
            b.setText(text)
            b.clicked.connect(lambda _=False, s=step: self.step(s))
            lay.addWidget(b)
        self.count = QLabel("")
        self.count.setMinimumWidth(80)
        lay.addWidget(self.count)
        close = QToolButton()
        close.setText("✕")
        close.clicked.connect(self.close_bar)
        lay.addWidget(close)
        self._stale = True
        # big sets are searched a few sheets at a time, so the window keeps
        # answering (Find on the 309-sheet plant set froze it for 10 s)
        self._job = None
        self._pending = None
        from PySide6.QtCore import QTimer
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._tick)

    ASYNC_PAGES = 30          # bigger documents are searched in the background
    SLICE = 0.03              # seconds of searching between screen updates

    def _mark_stale(self):
        self._stale = True
        self._cancel()

    def _cancel(self):
        self._job = None
        self._pending = None
        self._timer.stop()

    def searching(self):
        return self._job is not None

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close_bar()
        else:
            super().keyPressEvent(e)

    def open_bar(self, doc):
        if doc is not self.doc:
            self._cancel()
        self.doc = doc
        self._stale = True
        self.show()
        self.edit.setFocus()
        self.edit.selectAll()

    def close_bar(self):
        self._cancel()
        self.hide()
        self.hits, self.index = [], -1
        self.closed.emit()

    def _enter(self):
        from PySide6.QtWidgets import QApplication
        back = QApplication.keyboardModifiers() & Qt.ShiftModifier
        self.step(-1 if back else 1)

    FLAGS = fitz.TEXT_PRESERVE_LIGATURES | fitz.TEXT_PRESERVE_WHITESPACE \
        | fitz.TEXT_DEHYPHENATE

    def _page_hits(self, pno, term, case):
        page = self.doc[pno]
        out = []
        for r in page.search_for(term, flags=self.FLAGS):
            if case:
                found = page.get_textbox(r + (-1, -1, 1, 1))
                if term not in found:
                    continue
            out.append((pno, r))
        return out

    def run(self):
        """Search the whole document now (and wait for it)."""
        self._cancel()
        term = self.edit.text()
        self.hits, self.index = [], -1
        self._stale = False
        if not term or self.doc is None:
            self.count.setText("")
            return
        case = self.case.isChecked()
        for pno in range(self.doc.page_count):
            self.hits.extend(self._page_hits(pno, term, case))
        self.count.setText("No matches" if not self.hits else "")

    def _start(self, direction):
        """Search a big document in the background; the first match shows
        as soon as it's found."""
        self._cancel()
        self.hits, self.index = [], -1
        self._stale = False
        self._job = {"term": self.edit.text(), "case": self.case.isChecked(),
                     "page": 0, "doc": self.doc}
        self._pending = direction
        self.count.setText("Searching…")
        self._timer.start(0)

    def _tick(self):
        import time
        job = self._job
        if job is None:
            return
        if job["doc"] is not self.doc or getattr(self.doc, "is_closed",
                                                  False):
            self._cancel()
            return
        n = self.doc.page_count
        end = time.perf_counter() + self.SLICE
        while job["page"] < n and time.perf_counter() < end:
            try:
                self.hits.extend(self._page_hits(job["page"], job["term"],
                                                 job["case"]))
            except Exception:
                pass                       # a damaged page: skip it
            job["page"] += 1
        if self._pending is not None and self.hits:
            d, self._pending = self._pending, None
            self.index = -1 if d > 0 else 0
            self._show(d)
        if job["page"] < n:
            if self.index < 0:
                self.count.setText(f"Searching… {job['page']} of {n} "
                                   f"sheets, {len(self.hits)} found")
            else:
                self.count.setText(f"{self.index + 1} of {len(self.hits)}+ "
                                   f"(searching {job['page']}/{n})")
            self._timer.start(0)
            return
        self._job = None
        if self._pending is not None:              # nothing found at all
            self._pending = None
            self.show_hit.emit(-1, None, [])
        if not self.hits:
            self.count.setText("No matches")
        elif self.index >= 0:
            self.count.setText(f"{self.index + 1} of {len(self.hits)}")
        else:
            self.count.setText(f"{len(self.hits)} found")

    def step(self, direction, from_page=0):
        if self._stale:
            if self.doc is not None and self.edit.text() and \
                    self.doc.page_count > self.ASYNC_PAGES:
                self._start(direction)
                return
            self.run()
            self.index = -1 if direction > 0 else 0
        if self._job is not None and not self.hits:
            self._pending = direction          # shows when one turns up
            return
        self._show(direction)

    def _show(self, direction):
        if not self.hits:
            self.show_hit.emit(-1, None, [])
            return
        self.index = (self.index + direction) % len(self.hits)
        pno, r = self.hits[self.index]
        more = "+" if self._job is not None else ""
        self.count.setText(f"{self.index + 1} of {len(self.hits)}{more}")
        self.show_hit.emit(pno, r, [h for p, h in self.hits if p == pno])
