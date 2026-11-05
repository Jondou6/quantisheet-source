"""Count Several Symbols: box two or more sample symbols, name each one
("Toilet", "Chair", "Exit sign"), and count all of them in one run.

- Every sample is searched for with the same engine as Count Symbol
  (autocount.find: any angle, 90-110% size, stroke check), sharing
  one render of each page between the samples.
- A spot matched by two samples is kept for the better-scoring one only
  (the other is dropped), so nothing is counted twice.
- Nothing is counted until the hits are reviewed: one list per sample,
  with a check box per hit. Accepted hits become count markups, one
  takeoff group per sample, in one undoable step.

The pure parts (resolve_overlaps, plan_marks, parse_pages) have no Qt.
"""
import logging

log = logging.getLogger(__name__)

CLASS_COLORS = [(0.85, 0.15, 0.15), (0.10, 0.45, 0.85), (0.10, 0.60, 0.30),
                (0.85, 0.45, 0.00), (0.55, 0.25, 0.75), (0.00, 0.55, 0.60),
                (0.70, 0.55, 0.00), (0.80, 0.20, 0.55)]
OVERLAP = 0.5          # centers closer than this share of the smaller size


def _center(r):
    return (r[0] + r[2]) / 2.0, (r[1] + r[3]) / 2.0


def _size(r):
    return max(abs(r[2] - r[0]), abs(r[3] - r[1]))


def same_spot(a, b, share=OVERLAP):
    """Two hit rects mark the same spot: centers within `share` of the
    smaller symbol's size of each other (the rule Count Symbol uses to
    merge its own variants)."""
    ca, cb = _center(a), _center(b)
    lim = share * min(_size(a), _size(b))
    return abs(ca[0] - cb[0]) < lim and abs(ca[1] - cb[1]) < lim


def resolve_overlaps(results):
    """results: {class name: [hit {page, rect, score, ...}]}. Where hits
    of different classes mark the same spot, only the best-scoring one
    stays. Returns (kept {name: [hits]}, dropped [(hit, name, won by)])."""
    flat = []
    for name, hits in results.items():
        for h in hits:
            flat.append((float(h.get("score") or 0.0), name, h))
    flat.sort(key=lambda t: -t[0])
    kept = {name: [] for name in results}
    placed = {}                                   # page -> [(rect, name)]
    dropped = []
    for sc, name, h in flat:
        r = [float(v) for v in h["rect"]]
        here = placed.setdefault(h["page"], [])
        win = next((n for rr, n in here if n != name and same_spot(r, rr)),
                   None)
        if win is not None:
            dropped.append((h, name, win))
            continue
        here.append((r, name))
        kept[name].append(h)
    for name in kept:
        kept[name].sort(key=lambda h: (h["page"], h["rect"][1],
                                       h["rect"][0]))
    return kept, dropped


def parse_pages(text, page_count):
    """'1-3, 5' -> {0, 1, 2, 4} (pages counted from 1; out-of-range
    pages are ignored). Empty or unreadable -> None."""
    out = set()
    for part in (text or "").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if "-" in part:
                a, b = (int(x) for x in part.split("-", 1))
                if a > b:
                    a, b = b, a
                out.update(range(a - 1, b))
            else:
                out.add(int(part) - 1)
        except ValueError:
            return None
    out = {p for p in out if 0 <= p < page_count}
    return out or None


def unique_name(name, taken):
    name = (name or "").strip() or "Symbol"
    base, n = name, 2
    while name.lower() in {t.lower() for t in taken}:
        name = f"{base} ({n})"
        n += 1
    return name


def find_all(doc, samples, pages=None, finder=None, progress=None):
    """Search for every sample: samples [{name, template (PNG bytes)}].
    Returns (kept, dropped) as resolve_overlaps gives them. `finder`
    defaults to autocount.find; all samples share one page render
    cache."""
    if finder is None:
        from . import autocount
        finder = autocount.find
    cache = {}
    results = {}
    for i, s in enumerate(samples):
        if progress is not None and progress(i, len(samples), s["name"]) \
                is False:
            break
        hits = finder(doc, s["template"], pages=pages, cache=cache)
        for h in hits:
            h["class"] = s["name"]
        results[s["name"]] = hits
    return resolve_overlaps(results)


def plan_marks(accepted, doc=None, colors=None):
    """Count marks for the accepted hits: {name: [hits]} -> marks, each
    class its own group and color."""
    from . import autocount
    marks = []
    for i, (name, hits) in enumerate(accepted.items()):
        if not hits:
            continue
        col = (colors or {}).get(name) or CLASS_COLORS[i % len(CLASS_COLORS)]
        marks += autocount.review_marks(list(hits), group=name,
                                              doc=doc, color=col)
    return marks


# ---------------------------------------------------------------- the UI
try:
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtGui import QColor, QIcon, QImage, QPixmap
    from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                                   QHBoxLayout, QLabel, QLineEdit,
                                   QListWidget, QListWidgetItem,
                                   QPushButton, QTableWidget,
                                   QTableWidgetItem, QTabWidget,
                                   QVBoxLayout, QWidget)
except ImportError:                                     # pragma: no cover
    QDialog = None


def _thumb(doc, page, rect, pad=1.0, zoom=3):
    import fitz
    try:
        r = fitz.Rect(rect)
        r = fitz.Rect(r.x0 - r.width * pad, r.y0 - r.height * pad,
                      r.x1 + r.width * pad, r.y1 + r.height * pad)
        pix = doc[page].get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=r,
                                   alpha=False)
        img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                     QImage.Format_RGB888).copy()
        return QIcon(QPixmap.fromImage(img))
    except Exception:
        return QIcon()


if QDialog is not None:
    class SamplesDialog(QDialog):
        """Collects the samples. Stays open (not modal) while you box
        symbols on the drawing; each box adds a row you can name."""

        def __init__(self, view, parent=None):
            super().__init__(parent)
            self.view = view
            self.samples = []               # {name, template, page, rect}
            self.result = None              # (kept, dropped) after a run
            self.setWindowTitle("Count Several Symbols")
            self.setModal(False)
            lay = QVBoxLayout(self)
            self.info = QLabel(
                "Drag a box around one sample of each symbol on the drawing "
                "and name it here - double-click a name to change it (two "
                "or more samples). Then Find All: each is counted in its own "
                "group after you check the hits.")
            self.info.setWordWrap(True)
            lay.addWidget(self.info)
            self.table = QTableWidget(0, 3)
            self.table.setHorizontalHeaderLabels(["Sample", "Name", "Page"])
            self.table.verticalHeader().setVisible(False)
            self.table.horizontalHeader().setStretchLastSection(False)
            self.table.setColumnWidth(0, 70)
            self.table.setColumnWidth(1, 200)
            self.table.setColumnWidth(2, 50)
            self.table.itemChanged.connect(self._renamed)
            lay.addWidget(self.table)
            row = QHBoxLayout()
            self.box_btn = QPushButton("Box a Sample")
            self.box_btn.clicked.connect(self.arm)
            self.remove_btn = QPushButton("Remove")
            self.remove_btn.clicked.connect(self.remove_selected)
            row.addWidget(self.box_btn)
            row.addWidget(self.remove_btn)
            row.addStretch()
            lay.addLayout(row)
            prow = QHBoxLayout()
            prow.addWidget(QLabel("Search:"))
            self.where = QComboBox()
            self.where.addItems(["This page", "All pages", "Pages…"])
            self.pages_edit = QLineEdit()
            self.pages_edit.setPlaceholderText("e.g. 1-3, 5")
            self.pages_edit.setEnabled(False)
            self.where.currentIndexChanged.connect(
                lambda i: self.pages_edit.setEnabled(i == 2))
            prow.addWidget(self.where)
            prow.addWidget(self.pages_edit)
            lay.addLayout(prow)
            bb = QDialogButtonBox()
            self.find_btn = bb.addButton("Find All", QDialogButtonBox.AcceptRole)
            bb.addButton(QDialogButtonBox.Cancel)
            self.find_btn.clicked.connect(self.run)
            bb.rejected.connect(self.reject)
            lay.addWidget(bb)
            self.finished.connect(lambda _r: self.disarm())
            self.resize(420, 380)
            self._refresh()

        # ---- boxing samples on the drawing
        def arm(self):
            v = self.view
            if v is None:
                return
            v.symbol_sample_cb = self.add_sample
            v.set_tool("symbol_sample")
            try:
                v.status.emit("Drag a box around one sample symbol")
            except Exception:
                pass

        def disarm(self):
            v = self.view
            if v is None:
                return
            try:
                if getattr(v, "symbol_sample_cb", None) == self.add_sample:
                    v.symbol_sample_cb = None
                if v.tool == "symbol_sample":
                    v.set_tool(None)
            except RuntimeError:
                pass

        def _alive(self):
            try:
                return self.view is not None and \
                    not getattr(self.view.doc, "is_closed", False)
            except RuntimeError:                  # the view was closed
                return False

        def add_sample(self, rect, name=None):
            """A sample boxed at screen rect `rect` on the view's page."""
            from . import autocount
            v = self.view
            if not self._alive() or rect.width < 4 or rect.height < 4:
                return 0
            try:
                tpl = autocount.symbol_template(v.pg, rect)
            except Exception:
                log.warning("sample template", exc_info=True)
                return 0
            from . import annotate
            pr = annotate.to_page(v.pg, rect)
            name = unique_name(name or f"Symbol {len(self.samples) + 1}",
                               [s["name"] for s in self.samples])
            self.samples.append({"name": name, "template": tpl,
                                 "page": v.page, "rect": list(pr)})
            self._refresh()
            self.table.setCurrentCell(len(self.samples) - 1, 1)
            return 1

        def remove_selected(self):
            r = self.table.currentRow()
            if 0 <= r < len(self.samples):
                del self.samples[r]
                self._refresh()

        def _renamed(self, item):
            if item.column() != 1 or self._filling:
                return
            r = item.row()
            if 0 <= r < len(self.samples):
                others = [s["name"] for i, s in enumerate(self.samples)
                          if i != r]
                self.samples[r]["name"] = unique_name(item.text(), others)
                if item.text() != self.samples[r]["name"]:
                    self._filling = True
                    item.setText(self.samples[r]["name"])
                    self._filling = False

        def _refresh(self):
            self._filling = True
            self.table.setRowCount(len(self.samples))
            for i, s in enumerate(self.samples):
                th = QTableWidgetItem()
                th.setIcon(_thumb(self.view.doc, s["page"], s["rect"],
                                  pad=0.1, zoom=2))
                th.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self.table.setItem(i, 0, th)
                self.table.setItem(i, 1, QTableWidgetItem(s["name"]))
                pg = QTableWidgetItem(str(s["page"] + 1))
                pg.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self.table.setItem(i, 2, pg)
            self._filling = False
            self.find_btn.setEnabled(len(self.samples) >= 2)
            self.find_btn.setToolTip("" if len(self.samples) >= 2 else
                                     "Box at least two samples first")

        def pages(self):
            i = self.where.currentIndex()
            if i == 0:
                return {self.view.page}
            if i == 1:
                return None
            got = parse_pages(self.pages_edit.text(),
                              self.view.doc.page_count)
            return got if got else {self.view.page}

        def run(self):
            """Search, review, count. Returns marks added (0 if cancelled)."""
            from PySide6.QtWidgets import QApplication, QMessageBox
            if len(self.samples) < 2:
                return 0
            if not self._alive():
                self.reject()
                return 0
            self.disarm()
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                kept, dropped = find_all(self.view.doc, self.samples,
                                         pages=self.pages())
            except Exception as e:
                QApplication.restoreOverrideCursor()
                QMessageBox.warning(self, "Count Several Symbols", str(e))
                return 0
            QApplication.restoreOverrideCursor()
            self.result = (kept, dropped)
            if not any(kept.values()):
                QMessageBox.information(self, "Count Several Symbols",
                                        "None of the samples were found.")
                return 0
            dlg = ReviewDialog(self.view.doc, kept, dropped, self)
            dlg.go_to.connect(lambda p, r: self.view.go_to(p))
            if not dlg.exec():
                return 0
            acc = dlg.accepted()
            n = self.view.apply_marks(plan_marks(acc, self.view.doc))
            total = sum(len(h) for h in acc.values())
            parts = ", ".join(f"{len(h)} × {name}"
                              for name, h in acc.items() if h)
            self.view.status.emit(f"Counted {parts}" if total else
                                  "Nothing accepted - nothing counted")
            self.accept()
            return n

    class ReviewDialog(QDialog):
        """One list per class, a check box on every hit (lowest score
        first; sure hits start checked)."""
        go_to = Signal(int, object)

        def __init__(self, doc, kept, dropped=(), parent=None):
            super().__init__(parent)
            self.doc = doc
            self.setWindowTitle("Count Several Symbols - review")
            lay = QVBoxLayout(self)
            nd = len(dropped)
            self.info = QLabel(
                "Check the hits to count; only checked ones are added. "
                "Double-click a hit to see it on the drawing." +
                (f" {nd} spot(s) matched two samples and were kept for the "
                 "better match only." if nd else ""))
            self.info.setWordWrap(True)
            lay.addWidget(self.info)
            self.tabs = QTabWidget()
            lay.addWidget(self.tabs)
            self.lists = {}
            for name, hits in kept.items():
                hs = sorted(hits, key=lambda h: h.get("score") or 0)
                lst = QListWidget()
                lst.setViewMode(QListWidget.IconMode)
                lst.setIconSize(lst.iconSize() * 3)
                lst.setResizeMode(QListWidget.Adjust)
                for h in hs:
                    it = QListWidgetItem(
                        _thumb(doc, h["page"], h["rect"]),
                        f"p{h['page'] + 1} {float(h.get('score') or 0):.2f}")
                    it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                    sure = h.get("band", "high") == "high"
                    it.setCheckState(Qt.Checked if sure else Qt.Unchecked)
                    if not sure:
                        it.setBackground(QColor("#fff3cd"))
                    lst.addItem(it)
                lst.itemDoubleClicked.connect(
                    lambda it, l=lst, hs=hs: self.go_to.emit(
                        hs[l.row(it)]["page"], hs[l.row(it)]["rect"]))
                lst.itemChanged.connect(lambda _it: self._titles())
                page = QWidget()
                pl = QVBoxLayout(page)
                pl.addWidget(lst)
                row = QHBoxLayout()
                for text, on in (("Accept all", True), ("Reject all", False)):
                    b = QPushButton(text)
                    b.clicked.connect(lambda _=False, l=lst, v=on:
                                      self._set_all(l, v))
                    row.addWidget(b)
                row.addStretch()
                pl.addLayout(row)
                self.tabs.addTab(page, name)
                self.lists[name] = (lst, hs)
            bb = QDialogButtonBox(QDialogButtonBox.Ok |
                                  QDialogButtonBox.Cancel)
            bb.accepted.connect(self.accept)
            bb.rejected.connect(self.reject)
            lay.addWidget(bb)
            self.resize(860, 600)
            self._titles()

        def _set_all(self, lst, on):
            for i in range(lst.count()):
                lst.item(i).setCheckState(Qt.Checked if on else Qt.Unchecked)

        def set_checked(self, name, i, on):
            lst, _hs = self.lists[name]
            lst.item(i).setCheckState(Qt.Checked if on else Qt.Unchecked)

        def _titles(self):
            for i, (name, (lst, hs)) in enumerate(self.lists.items()):
                n = sum(1 for k in range(lst.count())
                        if lst.item(k).checkState() == Qt.Checked)
                self.tabs.setTabText(i, f"{name} ({n}/{len(hs)})")

        def accepted(self):
            """{name: [accepted hits]}"""
            out = {}
            for name, (lst, hs) in self.lists.items():
                out[name] = [hs[k] for k in range(lst.count())
                             if lst.item(k).checkState() == Qt.Checked]
            return out
