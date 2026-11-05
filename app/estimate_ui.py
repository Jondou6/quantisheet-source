"""Estimate panel dialogs: Add From Cost Book (CSI tree picker), Export My
Estimate (by division / cost type, to PDF, Excel or CSV) and the quick
$/SF estimate from your own past jobs.

Every dialog works with no document open (nothing to add to: its add
button stays off) so the click-everything sweep never blocks on one.
"""
import logging
import os
from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QFileDialog,
    QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QListWidget, QMessageBox, QPushButton, QSpinBox, QSplitter,
    QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget)

from . import assemblies, costbook, csi, dmoney, estimate, estimate_lines

log = logging.getLogger(__name__)

ROLE_DIV = Qt.UserRole
ROLE_CODE = Qt.UserRole + 1


def _ro(text, right=False):
    it = QTableWidgetItem(str(text))
    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
    if right:
        it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return it


def _money(v, places=2):
    d = dmoney.D(v)
    if places > 2 and d == d.quantize(Decimal("0.01")):
        places = 2
    q = d.quantize(Decimal(1).scaleb(-places))
    return f"{'-' if q < 0 else ''}${abs(q):,.{places}f}"


def takeoff_groups(doc):
    """[(label, link)] of the document's takeoff groups."""
    if doc is None:
        return []
    out = []
    try:
        for g in estimate.lines(doc):
            out.append((f"{g['name']} ({g['type']}, {g['unit']})",
                        {"name": g["name"], "type": g["type"],
                         "unit": g["unit"]}))
    except Exception:                                     # noqa: BLE001
        log.warning("takeoff groups unavailable", exc_info=True)
    return out


def header_aligned(table):
    """True when every column's header section sits exactly over the
    column (same left edge and width)."""
    h = table.horizontalHeader()
    for c in range(table.columnCount()):
        if table.isColumnHidden(c):
            continue
        if h.sectionViewportPosition(c) != table.columnViewportPosition(c) \
                or h.sectionSize(c) != table.columnWidth(c):
            return False
    return True


def header_fits(table):
    """True when every header label (and every cell's text) fits inside
    its own column, so no label spills over a neighbour. Stretched
    columns take what's left and aren't checked."""
    h = table.horizontalHeader()
    fm = QFontMetrics(h.font())
    cell_fm = QFontMetrics(table.font())
    for c in range(table.columnCount()):
        if table.isColumnHidden(c) or \
                h.sectionResizeMode(c) == QHeaderView.Stretch:
            continue
        hi = table.horizontalHeaderItem(c)
        if hi is not None and fm.horizontalAdvance(hi.text()) > \
                h.sectionSize(c):
            return False
        for r in range(min(table.rowCount(), 200)):
            it = table.item(r, c)
            if it is not None and it.text() and \
                    cell_fm.horizontalAdvance(it.text()) > \
                    table.columnWidth(c):
                return False
    return True


# ---- Add From Cost Book --------------------------------------------------------

class CostBookPicker(QDialog):
    """A cost book's items by CSI division (tree on the left), searchable,
    filtered by basis, with a checkbox on every row. 'Add N item(s) to
    Estimate' makes estimate lines of the ticked items, optionally linked
    to a takeoff group so their quantity follows the markups."""

    COLS = ["", "Code", "Description", "Unit", "Mat $", "Lab $", "Eqp $",
            "Sub $", "Unit Cost", "Basis"]

    def __init__(self, doc, parent=None, book=None, region=None):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle("Add From Cost Book")
        self.resize(1000, 620)
        self.added_ids = []
        self.checked = set()
        self.book = None
        self.priced = {}
        self._filling = False
        self.job = assemblies.read_job(doc) if doc is not None else {}
        self._region_hint = region
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Cost book:"))
        self.book_box = QComboBox()
        self.book_box.setMinimumWidth(260)
        top.addWidget(self.book_box)
        self.region_label = QLabel("")
        top.addWidget(self.region_label, 1)
        lay.addLayout(top)

        split = QSplitter(Qt.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["CSI division", "Items"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setStretchLastSection(False)
        self.tree.currentItemChanged.connect(lambda *_: self.fill())
        split.addWidget(self.tree)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search code or description")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(lambda *_: self.fill())
        row.addWidget(self.search, 1)
        row.addWidget(QLabel("Basis:"))
        self.basis = QComboBox()
        self.basis.currentIndexChanged.connect(lambda *_: self.fill())
        row.addWidget(self.basis)
        rl.addLayout(row)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.itemChanged.connect(self._ticked)
        self.table.cellDoubleClicked.connect(self._toggle_row)
        rl.addWidget(self.table)
        split.addWidget(right)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 3)
        split.setSizes([250, 750])
        lay.addWidget(split, 1)

        row = QHBoxLayout()
        row.addWidget(QLabel("Link to takeoff group:"))
        self.link = QComboBox()
        self.link.addItem("(none - type the quantity)", None)
        for label, link in takeoff_groups(doc):
            self.link.addItem(label, link)
        self.link.setToolTip("The added lines take their quantity from this "
                             "group's markups and follow them as you draw")
        row.addWidget(self.link, 1)
        lay.addLayout(row)
        self.note = QLabel("" if doc is not None else
                           "Open a PDF to add items to its estimate.")
        self.note.setWordWrap(True)
        self.note.setStyleSheet("color: #b00;")
        lay.addWidget(self.note)
        btns = QHBoxLayout()
        btns.addStretch()
        self.add_button = QPushButton()
        self.add_button.setDefault(True)
        self.add_button.clicked.connect(self.add_to_estimate)
        close = QPushButton("Cancel")
        close.clicked.connect(self.reject)
        btns.addWidget(self.add_button)
        btns.addWidget(close)
        lay.addLayout(btns)

        self._fill_books(book)
        self.book_box.currentIndexChanged.connect(self._book_picked)
        self._book_picked()

    # ---- books -------------------------------------------------------------
    def _fill_books(self, book):
        self._books = []
        names = set()
        if book is not None:
            self._books.append((book.name, book))
            names.add(book.name)
        try:
            jb, _r, _a = assemblies.job_costbook(self.job)
        except Exception:                                 # noqa: BLE001
            log.warning("job cost book unreadable", exc_info=True)
            jb = None
        if jb is not None and jb.name not in names:
            self._books.append((jb.name, jb))
            names.add(jb.name)
        try:
            for n, path in costbook.list_books().items():
                if n not in names:
                    self._books.append((n, path))
                    names.add(n)
        except Exception as e:                            # noqa: BLE001
            log.warning("price database unavailable", exc_info=True)
            self.note.setText(f"Price database: {e}")
        self.book_box.blockSignals(True)
        for n, _b in self._books:
            label = costbook.display_name(n) + (
                "  (this job)" if jb is not None and n == jb.name else "")
            self.book_box.addItem(label, n)
        self.book_box.blockSignals(False)

    def _book_picked(self, *_):
        i = self.book_box.currentIndex()
        self.book, self.priced = None, {}
        self.checked.clear()
        if 0 <= i < len(self._books):
            name, b = self._books[i]
            if isinstance(b, str):
                try:
                    b = costbook.load(b)
                except Exception as e:                    # noqa: BLE001
                    self.note.setText(f"Can't read {name}: {e}")
                    b = None
            self.book = b
        self._price_book()
        self._fill_tree()
        self._fill_basis()
        self.fill()

    def region(self):
        b = self.book
        if b is None:
            return None
        cb = self.job.get("costbook") or {}
        want = self._region_hint or (cb.get("region") if cb.get("name") ==
                                     b.name else None)
        if not want:
            dflt = assemblies.default_costbook()
            if dflt[0] is not None and dflt[0].name == b.name:
                want = dflt[1]
        return b.resolve_region(want) if want else b.region

    def _price_book(self):
        b = self.book
        if b is None:
            self.region_label.setText("")
            return
        reg = self.region() or b.region
        cb = self.job.get("costbook") or {}
        as_of = cb.get("as_of") if cb.get("name") == b.name else None
        for code in b.items:
            try:
                self.priced[code] = estimate_lines.from_book(
                    b, code, reg, as_of or None, self.job)
            except Exception:                             # noqa: BLE001
                log.warning("cost book item %s not priced", code,
                            exc_info=True)
        self.region_label.setText(
            f"  {len(b.items)} items, priced for {reg}"
            + (f" as of {as_of}" if as_of else ""))

    # ---- tree / filters ------------------------------------------------------
    def _div(self, code):
        d = costbook.division_of(code)
        return d if d else ""

    def _fill_tree(self):
        self.tree.blockSignals(True)
        self.tree.clear()
        b = self.book
        items = b.items if b is not None else {}
        allnode = QTreeWidgetItem([f"All items", str(len(items))])
        allnode.setData(0, ROLE_DIV, None)
        self.tree.addTopLevelItem(allnode)
        divs = {}
        for code in items:
            d = self._div(code)
            sec = csi.parse_code(code)[:8] if csi.parse_code(code) else ""
            divs.setdefault(d, {}).setdefault(sec, []).append(code)
        for d in sorted(divs, key=lambda x: (x == "", x)):
            secs = divs[d]
            n = sum(len(v) for v in secs.values())
            title = csi.DIVISIONS.get(d, "")
            label = f"{d} {title[:1].upper()}{title[1:]}" if d else \
                "Uncoded"
            node = QTreeWidgetItem([label, str(n)])
            node.setData(0, ROLE_DIV, ("div", d))
            self.tree.addTopLevelItem(node)
            for sec in sorted(secs):
                if not sec:
                    continue
                ch = QTreeWidgetItem([sec, str(len(secs[sec]))])
                ch.setData(0, ROLE_DIV, ("sec", sec))
                node.addChild(ch)
        self.tree.setCurrentItem(allnode)
        self.tree.blockSignals(False)
        self.tree.resizeColumnToContents(1)

    def division_counts(self):
        """{division: item count} as the tree shows it."""
        out = {}
        for i in range(self.tree.topLevelItemCount()):
            node = self.tree.topLevelItem(i)
            key = node.data(0, ROLE_DIV)
            if key:
                out[key[1]] = int(node.text(1))
        return out

    def select_division(self, div):
        for i in range(self.tree.topLevelItemCount()):
            node = self.tree.topLevelItem(i)
            key = node.data(0, ROLE_DIV)
            if (key is None and div is None) or (key and key[1] == div):
                self.tree.setCurrentItem(node)
                return True
        return False

    def _fill_basis(self):
        self.basis.blockSignals(True)
        self.basis.clear()
        self.basis.addItem("All", None)
        kinds = sorted({str(it.get("basis") or "") for it in
                        (self.book.items.values() if self.book else [])})
        for k in kinds:
            self.basis.addItem(k or "(unmarked)", k)
        self.basis.blockSignals(False)

    def visible_codes(self):
        out = []
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it is not None:
                out.append(it.data(ROLE_CODE))
        return out

    def _match(self, code, item):
        cur = self.tree.currentItem()
        key = cur.data(0, ROLE_DIV) if cur is not None else None
        if key:
            kind, val = key
            if kind == "div" and self._div(code) != val:
                return False
            if kind == "sec" and not (csi.parse_code(code) or "").startswith(
                    val):
                return False
        b = self.basis.currentData()
        if b is not None and str(item.get("basis") or "") != b:
            return False
        q = self.search.text().strip().lower()
        if q:
            hay = " ".join([code, csi.parse_code(code), item.get("desc", ""),
                            item.get("crew", ""), item.get("source", "")])
            if not all(w in hay.lower() for w in q.split()):
                return False
        return True

    def fill(self):
        self._filling = True
        try:
            self.table.setRowCount(0)
            b = self.book
            if b is None:
                return
            codes = [c for c, it in sorted(b.items.items())
                     if self._match(c, it)]
            self.table.setRowCount(len(codes))
            for r, code in enumerate(codes):
                it = b.items[code]
                ln = self.priced.get(code) or {}
                chk = QTableWidgetItem("")
                chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled |
                             Qt.ItemIsSelectable)
                chk.setCheckState(Qt.Checked if code in self.checked
                                  else Qt.Unchecked)
                chk.setData(ROLE_CODE, code)
                self.table.setItem(r, 0, chk)
                up = {k: ln.get(k, "0") for k in estimate_lines.PARTS}
                uc = sum((Decimal(v) for v in up.values()), Decimal(0))
                vals = [code, it.get("desc", ""), it.get("unit", ""),
                        _money(up["mat"], 4), _money(up["lab"], 4),
                        _money(up["eqp"], 4), _money(up["sub"], 4),
                        _money(uc, 4), it.get("basis", "")]
                for c, v in enumerate(vals, 1):
                    self.table.setItem(r, c, _ro(v, right=4 <= c <= 8))
                if it.get("labor") or it.get("crew"):
                    self.table.item(r, 5).setToolTip(
                        f"{it.get('labor') or 0:g} hrs/{it.get('unit', '')}"
                        + (f", crew {it['crew']}" if it.get("crew") else ""))
            for c in range(self.table.columnCount()):
                if c != 2:
                    self.table.resizeColumnToContents(c)
        finally:
            self._filling = False
            self._update_button()

    # ---- ticking -------------------------------------------------------------
    def _ticked(self, item):
        if self._filling or item.column() != 0:
            return
        code = item.data(ROLE_CODE)
        if item.checkState() == Qt.Checked:
            self.checked.add(code)
        else:
            self.checked.discard(code)
        self._update_button()

    def _toggle_row(self, row, _col):
        it = self.table.item(row, 0)
        if it is not None:
            it.setCheckState(Qt.Unchecked if it.checkState() == Qt.Checked
                             else Qt.Checked)

    def set_checked(self, code, on=True):
        """Tick or untick an item (it needn't be showing)."""
        key = csi.parse_code(code) or str(code).strip()
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it is not None and it.data(ROLE_CODE) == key:
                it.setCheckState(Qt.Checked if on else Qt.Unchecked)
                return
        if on and self.book is not None and key in self.book.items:
            self.checked.add(key)
        else:
            self.checked.discard(key)
        self._update_button()

    def _update_button(self):
        n = len(self.checked)
        self.add_button.setText(f"Add {n} item(s) to Estimate")
        self.add_button.setEnabled(bool(n) and self.doc is not None)

    def set_link(self, name):
        """Pick the takeoff group to link to by its name (None: no link)."""
        for i in range(self.link.count()):
            d = self.link.itemData(i)
            if (d is None and name is None) or (d and d["name"] == name):
                self.link.setCurrentIndex(i)
                return True
        return False

    # ---- add -----------------------------------------------------------------
    def lines(self):
        """The estimate lines the ticked items would make."""
        link = self.link.currentData()
        out = []
        for code in sorted(self.checked):
            ln = dict(self.priced.get(code) or {})
            if not ln:
                continue
            if link:
                ln["link"] = dict(link)
            out.append(ln)
        return out

    def add_to_estimate(self):
        if self.doc is None or not self.checked:
            return []
        lines = self.lines()
        link = self.link.currentData()
        if link:
            bad = [p for p in (estimate_lines.link_problem(link, ln["unit"])
                               for ln in lines) if p]
            if bad:
                self.note.setText("Can't link: " + bad[0] + (
                    f" (and {len(bad) - 1} more)" if len(bad) > 1 else ""))
                return []
        try:
            self.added_ids = estimate_lines.add(self.doc, lines)
        except estimate_lines.LineError as e:
            self.note.setText(str(e))
            return []
        self.accept()
        return self.added_ids


# ---- Export My Estimate --------------------------------------------------------

class ExportEstimateDialog(QDialog):
    """The grand total, totals by CSI division and by cost type, and Save
    to PDF / Excel / CSV - or the estimate in one of your saved layouts
    (estimate_layouts.py), saved the same three ways."""

    STANDARD = "Standard summary"

    def __init__(self, doc, parent=None, layout=None):
        super().__init__(parent)
        from . import estimate_export
        self.doc = doc
        self.view = None
        self._base = None
        self.setWindowTitle("Export My Estimate")
        self.resize(760, 600)
        self.summary = estimate_export.summary(doc) if doc is not None \
            else estimate_export.summary(None, lines=[])
        lay = QVBoxLayout(self)
        pick = QHBoxLayout()
        pick.addWidget(QLabel("Layout:"))
        self.layout_box = QComboBox()
        self.layout_box.setToolTip("Show and save the same estimate grouped "
                                   "another way; every layout adds up to "
                                   "the same grand total")
        pick.addWidget(self.layout_box, 1)
        self.manage_btn = QPushButton("Manage Layouts…")
        self.manage_btn.clicked.connect(lambda: self.manage_layouts())
        pick.addWidget(self.manage_btn)
        lay.addLayout(pick)
        self.layout_note = QLabel("")
        self.layout_note.setWordWrap(True)
        lay.addWidget(self.layout_note)
        self.view_table = QTableWidget(0, 1)
        self.view_table.verticalHeader().setVisible(False)
        self.view_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.view_table.hide()
        lay.addWidget(self.view_table, 3)
        self.std = QWidget()
        std = QVBoxLayout(self.std)
        std.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.std, 3)
        std.addWidget(QLabel("<b>By CSI division</b>"))
        self.divs = QTableWidget(0, 3)
        self.divs.setHorizontalHeaderLabels(["Division", "Lines", "Total"])
        self.divs.verticalHeader().setVisible(False)
        self.divs.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        for d in self.summary["divisions"]:
            r = self.divs.rowCount()
            self.divs.insertRow(r)
            self.divs.setItem(r, 0, _ro(d["label"]))
            self.divs.setItem(r, 1, _ro(d["count"], True))
            self.divs.setItem(r, 2, _ro(dmoney.fmt(d["total"]), True))
        std.addWidget(self.divs, 2)
        std.addWidget(QLabel("<b>By cost type</b>"))
        self.types = QTableWidget(0, 2)
        self.types.setHorizontalHeaderLabels(["Cost Type", "Total"])
        self.types.verticalHeader().setVisible(False)
        self.types.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        for k, v in self.summary["types"].items():
            r = self.types.rowCount()
            self.types.insertRow(r)
            self.types.setItem(r, 0, _ro(k))
            self.types.setItem(r, 1, _ro(dmoney.fmt(v), True))
        std.addWidget(self.types, 1)
        self.total = QLabel("")
        self._standard_total()
        lay.addWidget(self.total)
        if doc is None:
            lay.addWidget(QLabel("Open a PDF to export its estimate."))
        elif not self.summary["lines"] and \
                not self.summary.get("unpriced"):
            lay.addWidget(QLabel("Nothing priced yet: add lines in the "
                                 "Estimate panel or price the takeoff."))
        note = estimate_export.unpriced_note(self.summary)
        if doc is not None and note:
            # review r41 F01: say so, instead of an empty $0.00 export
            self.unpriced_label = QLabel(note)
            self.unpriced_label.setWordWrap(True)
            lay.addWidget(self.unpriced_label)
        btns = QHBoxLayout()
        self.pdf_btn = QPushButton("Save to PDF…")
        self.xlsx_btn = QPushButton("Save to Excel…")
        self.csv_btn = QPushButton("Save to CSV…")
        for b, fn in ((self.pdf_btn, self.save_pdf),
                      (self.xlsx_btn, self.save_xlsx),
                      (self.csv_btn, self.save_csv)):
            b.clicked.connect(lambda _c=False, f=fn: f())
            b.setEnabled(doc is not None)
            btns.addWidget(b)
        btns.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        btns.addWidget(close)
        lay.addLayout(btns)
        self.fill_layouts(layout)
        self.layout_box.currentTextChanged.connect(
            lambda t: self.set_layout(t) if t else None)

    # ---- layouts --------------------------------------------------------
    def _standard_total(self):
        rows = self.summary["location"] or [("Grand total",
                                              self.summary["total"])]
        self.total.setText("<br>".join(
            (f"<b>{lb}: {dmoney.fmt(v)}</b>" if i in (0, len(rows) - 1)
             else f"{lb}: {dmoney.fmt(v)}") for i, (lb, v) in
            enumerate(rows)))

    def layout_names(self):
        return [self.layout_box.itemText(i)
                for i in range(self.layout_box.count())]

    def fill_layouts(self, select=None):
        from . import estimate_layouts
        cur = select or self.layout_box.currentText() or self.STANDARD
        self.layout_box.blockSignals(True)
        self.layout_box.clear()
        self.layout_box.addItem(self.STANDARD)
        try:
            names = [x["name"] for x in estimate_layouts.layouts(self.doc)]
        except Exception:                                 # noqa: BLE001
            log.warning("estimate layouts unavailable", exc_info=True)
            names = list(estimate_layouts.BUILTIN_NAMES)
        self.layout_box.addItems(names)
        self.layout_box.setCurrentText(cur if cur in names else
                                       self.STANDARD)
        self.layout_box.blockSignals(False)
        self.set_layout(self.layout_box.currentText())

    def set_layout(self, name):
        """Show the estimate in the layout called `name` (the standard
        summary for STANDARD); returns the view (None for STANDARD)."""
        from . import estimate_layouts as L
        if self.layout_box.currentText() != name:
            self.layout_box.blockSignals(True)
            self.layout_box.setCurrentText(name)
            self.layout_box.blockSignals(False)
        lay = None if name == self.STANDARD else L.find(self.doc, name)
        if lay is None:
            self.view = None
            self.view_table.hide()
            self.std.show()
            self.layout_note.setText("")
            self._standard_total()
            return None
        try:
            if self._base is None:
                self._base = L.base(self.doc) if self.doc is not None \
                    else L.base(None, lines=[])
            self.view = L.view(self.doc, lay, self._base)
        except Exception as e:                            # noqa: BLE001
            log.warning("estimate layout failed", exc_info=True)
            self.layout_note.setText(f"Couldn't show {name}: {e}")
            self.view = None
            return None
        self._fill_view()
        self.std.hide()
        self.view_table.show()
        bits = [lay.get("note") or ""] + self.view["notes"]
        self.layout_note.setText(" ".join(b for b in bits if b))
        self.total.setText(f"Direct cost: {dmoney.fmt(self.view['direct'])}"
                           f"<br><b>Grand total: "
                           f"{dmoney.fmt(self.view['total'])}</b>")
        return self.view

    def _fill_view(self):
        from PySide6.QtGui import QFont
        from . import estimate_layouts as L
        v = self.view
        keys = [k for k, _l in v["columns"]]
        t = self.view_table
        t.clear()
        t.setColumnCount(1 + len(keys))
        t.setHorizontalHeaderLabels(["Description"] +
                                    [lb for _k, lb in v["columns"]])
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        t.setRowCount(0)
        bold = QFont()
        bold.setBold(True)
        for kind, label, cells in L.flat_rows(v):
            r = t.rowCount()
            t.insertRow(r)
            it = _ro(("    " if kind == "line" else "") + label)
            if kind in ("group", "subtotal", "total"):
                it.setFont(bold)
            t.setItem(r, 0, it)
            for c, k in enumerate(keys, 1):
                txt = cells.get(k, "")
                if not txt and k == keys[-1] and "total" not in keys:
                    txt = cells.get("total", "")
                cit = _ro(txt, k in L.MONEY or k in ("qty", "unit_cost"))
                if kind in ("subtotal", "total"):
                    cit.setFont(bold)
                t.setItem(r, c, cit)

    def view_rows(self):
        """The layout table's text, row by row (for the tests)."""
        t = self.view_table
        return [[t.item(r, c).text() if t.item(r, c) else ""
                 for c in range(t.columnCount())]
                for r in range(t.rowCount())]

    def manage_layouts(self, show=True):
        cur = self.layout_box.currentText()
        dlg = LayoutsDialog(self.doc, self, current=None
                            if cur == self.STANDARD else cur)
        if show:
            dlg.exec()
            self._base = None
            self.fill_layouts(dlg.picked or cur)
        return dlg

    def division_rows(self):
        return [(self.divs.item(r, 0).text(), self.divs.item(r, 2).text())
                for r in range(self.divs.rowCount())]

    def _path(self, path, title, default, flt):
        if path:
            return path
        base = os.path.splitext(os.path.basename(getattr(self.doc, "name",
                                                         "") or ""))[0]
        from .reportname import report_file_name
        stem, ext = os.path.splitext(default)
        path, _ = QFileDialog.getSaveFileName(
            self, title, report_file_name(stem.title(), base, ext=ext), flt)
        return path or None

    def _save(self, fn, path):
        from . import estimate_export
        try:
            if self.view is not None:
                getattr(estimate_export, fn.replace("save_", "save_view_"))(
                    self.doc, path, self.view)
            else:
                getattr(estimate_export, fn)(self.doc, path, self.summary)
        except Exception as e:                            # noqa: BLE001
            log.warning("estimate export failed", exc_info=True)
            QMessageBox.warning(self, "Export My Estimate",
                                f"Couldn't save {os.path.basename(path)}: "
                                f"{e}")
            return None
        return path

    def save_pdf(self, path=None):
        if self.doc is None:
            return None
        path = self._path(path, "Save Estimate PDF", "estimate.pdf",
                          "PDF (*.pdf)")
        return self._save("save_pdf", path) if path else None

    def save_xlsx(self, path=None):
        if self.doc is None:
            return None
        path = self._path(path, "Save Estimate to Excel", "estimate.xlsx",
                          "Excel (*.xlsx)")
        return self._save("save_xlsx", path) if path else None

    def save_csv(self, path=None):
        if self.doc is None:
            return None
        path = self._path(path, "Save Estimate to CSV", "estimate.csv",
                          "CSV (*.csv)")
        return self._save("save_csv", path) if path else None


# ---- Quick $/SF estimate -------------------------------------------------------

class QuickSFDialog(QDialog):
    """Pick a building type and SF; priced from your own past jobs (Job
    Cost Feedback), as one allowance line per CSI division."""

    JOB_COLS = ["Job", "Name", "Type", "Building SF", "Cost", "From",
                "$/SF"]

    def __init__(self, doc, parent=None):
        super().__init__(parent)
        from . import quick_sf
        self.doc = doc
        self.res = None
        self.added_ids = []
        self._filling = False
        self.setWindowTitle("Quick $/SF Estimate")
        self.resize(760, 600)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(
            "Prices a building from <b>your own past jobs</b> of the same "
            "type (Job Cost Feedback: actual cost, else contract, else bid, "
            "divided by the job's building SF). No outside cost data."))
        row = QHBoxLayout()
        row.addWidget(QLabel("Building type:"))
        self.btype = QComboBox()
        self.btype.setEditable(True)
        try:
            self.btype.addItems(quick_sf.building_types())
        except Exception:                                 # noqa: BLE001
            log.warning("building types unavailable", exc_info=True)
        self.btype.setCurrentText("")
        row.addWidget(self.btype, 1)
        row.addWidget(QLabel("Building SF:"))
        self.sf = QLineEdit()
        self.sf.setPlaceholderText("e.g. 1000")
        self.sf.setMaximumWidth(120)
        row.addWidget(self.sf)
        go = QPushButton("Price It")
        go.clicked.connect(lambda: self.price_it())
        row.addWidget(go)
        lay.addLayout(row)
        self.result = QLabel("")
        self.result.setWordWrap(True)
        lay.addWidget(self.result)
        self.lines_table = QTableWidget(0, 2)
        self.lines_table.setHorizontalHeaderLabels(["Allowance line",
                                                    "Amount"])
        self.lines_table.verticalHeader().setVisible(False)
        self.lines_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        lay.addWidget(self.lines_table, 1)
        lay.addWidget(QLabel("<b>Your past jobs</b> - enter a job's type and "
                             "building SF here to use it:"))
        self.jobs = QTableWidget(0, len(self.JOB_COLS))
        self.jobs.setHorizontalHeaderLabels(self.JOB_COLS)
        self.jobs.verticalHeader().setVisible(False)
        self.jobs.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self.jobs.itemChanged.connect(self._job_edited)
        lay.addWidget(self.jobs, 1)
        self.msg = QLabel("")
        self.msg.setStyleSheet("color: #b00;")
        self.msg.setWordWrap(True)
        lay.addWidget(self.msg)
        btns = QHBoxLayout()
        self.model_button = QPushButton("Model Estimate…")
        self.model_button.setToolTip(
            "Price it with options (stories, structure, exterior, roof, "
            "site, sprinklers) from your history and from a Generate Set "
            "plan's quantities, side by side")
        self.model_button.clicked.connect(lambda: self.open_model())
        btns.addWidget(self.model_button)
        btns.addStretch()
        self.add_button = QPushButton("Add Allowance Lines to Estimate")
        self.add_button.setEnabled(False)
        self.add_button.clicked.connect(lambda: self.add_to_estimate())
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        btns.addWidget(self.add_button)
        btns.addWidget(close)
        lay.addLayout(btns)
        self.fill_jobs()

    def fill_jobs(self):
        from . import pricehistory, quick_sf
        self._filling = True
        try:
            self.jobs.setRowCount(0)
            try:
                jobs = pricehistory.jobs()
            except Exception as e:                        # noqa: BLE001
                self.msg.setText(f"Price database: {e}")
                return
            for j in jobs:
                r = self.jobs.rowCount()
                self.jobs.insertRow(r)
                sf = quick_sf.job_sf(j["id"])
                lines = pricehistory.lines(j["id"])
                cost, basis = quick_sf._job_cost(j, lines)
                vals = [j.get("number", ""), j.get("name", ""),
                        j.get("type", "") or "",
                        f"{float(sf):,.0f}" if sf else "",
                        dmoney.fmt(cost) if cost is not None else "",
                        basis,
                        dmoney.fmt(cost / sf) if cost and sf else ""]
                for c, v in enumerate(vals):
                    it = QTableWidgetItem(str(v))
                    if c not in (2, 3):
                        it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                    if c >= 3:
                        it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    it.setData(Qt.UserRole, j["id"])
                    self.jobs.setItem(r, c, it)
        finally:
            self._filling = False

    def _job_edited(self, item):
        if self._filling:
            return
        from . import quick_sf
        jid = item.data(Qt.UserRole)
        try:
            if item.column() == 3:
                quick_sf.set_job_sf(jid, item.text().replace(",", "").strip())
            elif item.column() == 2:
                quick_sf.set_job_type(jid, item.text())
            self.msg.setText("")
        except Exception as e:                            # noqa: BLE001
            self.msg.setText(str(e))
        self.fill_jobs()

    def price_it(self, btype=None, sf=None):
        from . import quick_sf
        if btype is not None:
            self.btype.setCurrentText(btype)
        if sf is not None:
            self.sf.setText(str(sf))
        bt = self.btype.currentText().strip()
        self.res = None
        self.lines_table.setRowCount(0)
        self.add_button.setEnabled(False)
        try:
            res = quick_sf.estimate(bt, self.sf.text().replace(",", ""))
        except quick_sf.QuickSFError as e:
            self.result.setText(str(e))
            return None
        except Exception as e:                            # noqa: BLE001
            log.warning("quick estimate failed", exc_info=True)
            self.result.setText(f"Couldn't read your job history: {e}")
            return None
        self.result.setText(quick_sf.describe(res, bt))
        if res is None:
            return None
        self.res = res
        for ln in quick_sf.to_lines(res):
            r = self.lines_table.rowCount()
            self.lines_table.insertRow(r)
            self.lines_table.setItem(r, 0, _ro(ln["desc"]))
            self.lines_table.setItem(r, 1, _ro(dmoney.fmt(ln["sub"]), True))
        n = self.lines_table.rowCount()
        self.add_button.setText(f"Add {n} Allowance Line(s) to Estimate")
        self.add_button.setEnabled(self.doc is not None and n > 0)
        if self.doc is None:
            self.msg.setText("Open a PDF to add the lines to its estimate.")
        return res

    def open_model(self, show=True):
        """Model Estimate with this dialog's type and SF filled in; lines
        it adds count as this dialog's."""
        dlg = ModelEstimateDialog(self.doc, self)
        bt = self.btype.currentText().strip()
        if bt:
            dlg.btype.setCurrentText(bt)
        dlg.sf.setText(self.sf.text())
        if show:
            dlg.exec()
            if dlg.added_ids:
                self.added_ids = dlg.added_ids
                self.accept()
        return dlg

    def add_to_estimate(self):
        from . import quick_sf
        if self.doc is None or self.res is None:
            return []
        self.added_ids = estimate_lines.add(self.doc,
                                            quick_sf.to_lines(self.res))
        self.accept()
        return self.added_ids


# ---- saved estimate layouts --------------------------------------------------

class LayoutsDialog(QDialog):
    """Your estimate layouts: make, change and delete them, tag lines, and
    save them to / load them from a small JSON file to use on another job.
    The built-in layouts can be copied (give the copy a new name), not
    changed. Without a document only the built-ins show and nothing can
    be saved."""

    def __init__(self, doc, parent=None, current=None):
        super().__init__(parent)
        from . import estimate_layouts as L
        self.doc = doc
        self.picked = None
        self.setWindowTitle("Estimate Layouts")
        self.resize(820, 560)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(
            "Named views of the same estimate lines: regrouped and "
            "re-totalled, always to the same grand total. Saved inside the "
            "PDF."))
        body = QHBoxLayout()
        self.list = QListWidget()
        self.list.setMaximumWidth(260)
        self.list.currentTextChanged.connect(self._picked)
        body.addWidget(self.list)
        form = QGridLayout()
        r = 0
        form.addWidget(QLabel("Name:"), r, 0)
        self.name = QLineEdit()
        form.addWidget(self.name, r, 1, 1, 3)
        r += 1
        form.addWidget(QLabel("Group by:"), r, 0)
        self.group_by = QComboBox()
        for k, v in L.GROUP_BY.items():
            self.group_by.addItem(v, k)
        form.addWidget(self.group_by, r, 1)
        form.addWidget(QLabel("Sort:"), r, 2)
        self.sort = QComboBox()
        for k, v in L.SORTS.items():
            self.sort.addItem(v, k)
        form.addWidget(self.sort, r, 3)
        r += 1
        self.detail = QCheckBox("Show each line")
        self.subtotals = QCheckBox("Subtotals")
        form.addWidget(self.detail, r, 1)
        form.addWidget(self.subtotals, r, 3)
        r += 1
        form.addWidget(QLabel("Markups, tax, location:"), r, 0)
        self.adjust = QComboBox()
        for k, v in L.ADJUST.items():
            self.adjust.addItem(v, k)
        form.addWidget(self.adjust, r, 1, 1, 3)
        r += 1
        cols = QGroupBox("Columns")
        cg = QGridLayout(cols)
        self.col_boxes = {}
        for i, (k, v) in enumerate(L.COLUMNS.items()):
            b = QCheckBox(v)
            self.col_boxes[k] = b
            cg.addWidget(b, i // 4, i % 4)
        form.addWidget(cols, r, 0, 1, 4)
        r += 1
        filt = QGroupBox("Filters (what they hide is one 'Not shown' line)")
        fg = QGridLayout(filt)
        fg.addWidget(QLabel("Divisions from"), 0, 0)
        self.div_from = QLineEdit()
        self.div_from.setPlaceholderText("e.g. 03")
        self.div_from.setMaximumWidth(70)
        fg.addWidget(self.div_from, 0, 1)
        fg.addWidget(QLabel("to"), 0, 2)
        self.div_to = QLineEdit()
        self.div_to.setPlaceholderText("e.g. 09")
        self.div_to.setMaximumWidth(70)
        fg.addWidget(self.div_to, 0, 3)
        self.type_boxes = {}
        for i, t in enumerate(L.TYPES):
            b = QCheckBox(t)
            self.type_boxes[t] = b
            fg.addWidget(b, 1 + i // 3, i % 3)
        fg.addWidget(QLabel("(no cost type ticked: all)"), 3, 0, 1, 3)
        form.addWidget(filt, r, 0, 1, 4)
        r += 1
        self.note = QLabel("")
        self.note.setWordWrap(True)
        form.addWidget(self.note, r, 0, 1, 4)
        right = QWidget()
        right.setLayout(form)
        body.addWidget(right, 1)
        lay.addLayout(body, 1)
        self.msg = QLabel("")
        self.msg.setWordWrap(True)
        lay.addWidget(self.msg)
        btns = QHBoxLayout()
        self.new_btn = QPushButton("New")
        self.save_btn = QPushButton("Save Layout")
        self.delete_btn = QPushButton("Delete")
        self.tags_btn = QPushButton("Tag Lines…")
        self.import_btn = QPushButton("Load From File…")
        self.export_btn = QPushButton("Save to File…")
        for b, fn in ((self.new_btn, self.new), (self.save_btn,
                                                 self.save_current),
                      (self.delete_btn, self.delete_current),
                      (self.tags_btn, self.tag_lines),
                      (self.import_btn, self.import_from),
                      (self.export_btn, self.export_to)):
            b.clicked.connect(lambda _c=False, f=fn: f())
            btns.addWidget(b)
        btns.addStretch()
        use = QPushButton("Use This Layout")
        use.clicked.connect(self._use)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        btns.addWidget(use)
        btns.addWidget(close)
        lay.addLayout(btns)
        for b in (self.new_btn, self.save_btn, self.delete_btn,
                  self.tags_btn, self.import_btn):
            b.setEnabled(doc is not None)
        if doc is None:
            self.msg.setText("Open a PDF to make, change or load layouts "
                             "(the built-in ones are shown).")
        self.refresh(current)

    def refresh(self, select=None):
        from . import estimate_layouts as L
        self.items = L.layouts(self.doc)
        self.list.blockSignals(True)
        self.list.clear()
        for x in self.items:
            self.list.addItem(x["name"])
        self.list.blockSignals(False)
        names = [x["name"] for x in self.items]
        row = names.index(select) if select in names else 0
        self.list.setCurrentRow(row)
        self._picked(names[row] if names else "")

    def _picked(self, name):
        lay = next((x for x in self.items if x["name"] == name), None)
        if lay is not None:
            self.set_form(lay)

    def set_form(self, lay):
        self.name.setText(lay["name"])
        self.group_by.setCurrentIndex(self.group_by.findData(
            lay["group_by"]))
        self.sort.setCurrentIndex(self.sort.findData(lay["sort"]))
        self.adjust.setCurrentIndex(self.adjust.findData(
            lay["adjustments"]))
        self.detail.setChecked(lay["detail"])
        self.subtotals.setChecked(lay["subtotals"])
        for k, b in self.col_boxes.items():
            b.setChecked(k in lay["columns"])
        self.div_from.setText(lay["filters"]["div_from"])
        self.div_to.setText(lay["filters"]["div_to"])
        for t, b in self.type_boxes.items():
            b.setChecked(t in lay["filters"]["cost_types"])
        self.note.setText((lay.get("note") or "") + (
            "  (Built in: change it and save it under a new name.)"
            if lay.get("builtin") else ""))

    def form_layout(self):
        """The layout the form describes."""
        from . import estimate_layouts as L
        cols = [k for k in L.COLUMNS if self.col_boxes[k].isChecked()]
        return L.normalize({
            "name": self.name.text(), "group_by": self.group_by.currentData(),
            "sort": self.sort.currentData(),
            "adjustments": self.adjust.currentData(),
            "detail": self.detail.isChecked(),
            "subtotals": self.subtotals.isChecked(), "columns": cols,
            "filters": {"div_from": self.div_from.text(),
                        "div_to": self.div_to.text(),
                        "cost_types": [t for t, b in self.type_boxes.items()
                                       if b.isChecked()]}})

    def new(self):
        from . import estimate_layouts as L
        names = {x["name"] for x in self.items}
        n, name = 1, "My layout"
        while name in names:
            n += 1
            name = f"My layout {n}"
        self.set_form(L.new_layout(name))
        self.list.clearSelection()
        self.msg.setText("Set it up, then Save Layout.")

    def save_current(self):
        from . import estimate_layouts as L
        if self.doc is None:
            return None
        try:
            lay = L.save_layout(self.doc, self.form_layout())
        except L.LayoutError as e:
            self.msg.setText(str(e))
            return None
        except Exception as e:                            # noqa: BLE001
            log.warning("layout not saved", exc_info=True)
            self.msg.setText(f"Couldn't save the layout: {e}")
            return None
        self.msg.setText(f"Saved {lay['name']!r} in this PDF (save the PDF "
                         "to keep it).")
        self.refresh(lay["name"])
        return lay

    def delete_current(self):
        from . import estimate_layouts as L
        name = self.name.text().strip()
        if self.doc is None:
            return False
        if name in L.BUILTIN_NAMES:
            self.msg.setText("Built-in layouts can't be deleted.")
            return False
        try:
            ok = L.delete_layout(self.doc, name)
        except L.LayoutError as e:
            self.msg.setText(str(e))
            return False
        self.msg.setText(f"Deleted {name!r}." if ok else
                         f"{name!r} isn't one of this job's layouts.")
        self.refresh()
        return ok

    def export_to(self, path=None):
        """Save this job's own layouts (or, with none, the one shown) to a
        layouts file; returns the path."""
        from . import estimate_layouts as L
        own = [x for x in self.items if not x.get("builtin")]
        items = own or [L.copy_layout(self.form_layout(),
                                      self.name.text())]
        if not path:
            path, _ = QFileDialog.getSaveFileName(
                self, "Save Layouts", "estimate layouts.json",
                "Layouts (*.json)")
        if not path:
            return None
        try:
            L.export_file(path, items)
        except OSError as e:
            self.msg.setText(f"Couldn't save {os.path.basename(path)}: {e}")
            return None
        self.msg.setText(f"Saved {len(items)} layout(s) to "
                         f"{os.path.basename(path)}.")
        return path

    def import_from(self, path=None):
        from . import estimate_layouts as L
        if self.doc is None:
            return []
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self, "Load Layouts", "", "Layouts (*.json)")
        if not path:
            return []
        try:
            names = L.import_file(self.doc, path)
        except (OSError, L.LayoutError) as e:
            self.msg.setText(f"Couldn't load {os.path.basename(path)}: {e}")
            return []
        self.msg.setText(f"Loaded {len(names)} layout(s): "
                         f"{', '.join(names)}.")
        self.refresh(names[0] if names else None)
        return names

    def tag_lines(self, show=True):
        dlg = TagsDialog(self.doc, self)
        if show:
            dlg.exec()
        return dlg

    def _use(self):
        self.picked = self.name.text().strip() or None
        self.accept()


class TagsDialog(QDialog):
    """A tag of your own on estimate lines (phase, area, alternate...),
    for layouts grouped by custom tag."""

    COLS = ["Description", "Source", "Total", "Tag"]

    def __init__(self, doc, parent=None):
        super().__init__(parent)
        from . import estimate_export, estimate_layouts as L
        self.doc = doc
        self.setWindowTitle("Tag Estimate Lines")
        self.resize(640, 480)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Type a tag on a line (blank clears it). "
                             "Layouts grouped by 'Custom tag' use it."))
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        lay.addWidget(self.table, 1)
        lines = estimate_export.collect(doc) if doc is not None else []
        tags = L.tags(doc) if doc is not None else {}
        self._filling = True
        for ln in lines:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, _ro(ln["desc"]))
            self.table.setItem(r, 1, _ro(L.SOURCE_LABEL.get(
                ln["source"], ln["source"])))
            self.table.setItem(r, 2, _ro(dmoney.fmt(ln["total"]), True))
            it = QTableWidgetItem(tags.get(ln["key"], ""))
            it.setData(Qt.UserRole, ln["key"])
            if doc is None:
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(r, 3, it)
        self._filling = False
        self.table.itemChanged.connect(self._edited)
        self.msg = QLabel("" if lines else "No priced lines yet.")
        lay.addWidget(self.msg)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        lay.addWidget(close, 0, Qt.AlignRight)

    def _edited(self, item):
        from . import estimate_layouts as L
        if self._filling or item.column() != 3 or self.doc is None:
            return
        try:
            L.set_tag(self.doc, item.data(Qt.UserRole), item.text())
            self.msg.setText("")
        except Exception as e:                            # noqa: BLE001
            self.msg.setText(str(e))

    def set_tag(self, row, text):
        self.table.item(row, 3).setText(text)


# ---- Model estimate ---------------------------------------------------------------

class ModelEstimateDialog(QDialog):
    """A conceptual estimate from a few inputs, priced two ways side by
    side: from your job history (with factors you can edit) and from a
    Generate Set plan's quantities priced with the job's assemblies and
    cost book. Either goes in as one allowance line per division."""

    QTY_COLS = ["Quantity", "Qty", "Unit", "Div", "Priced by / why not",
                "Amount"]
    FACTOR_COLS = ["Factor", "Applies to", "Kind", "Value"]

    def __init__(self, doc, parent=None):
        super().__init__(parent)
        from . import model_estimate as M
        self.doc = doc
        self.res = None
        self.added_ids = []
        self._filling = False
        self.setWindowTitle("Model Estimate")
        self.resize(1000, 760)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(
            "A building priced from a few inputs, two ways: from <b>your "
            "own past jobs</b> ($/SF by division, with the factors below) "
            "and from <b>quantities</b> of a Generate Set plan priced with "
            "this job's assemblies and cost book."))
        g = QGridLayout()
        g.addWidget(QLabel("Building type:"), 0, 0)
        self.btype = QComboBox()
        self.btype.setEditable(True)
        names = [lb for _k, lb in M.gs_types()]
        try:
            from . import quick_sf
            for t in quick_sf.building_types():
                if t not in names and M.type_key(t) == "":
                    names.append(t)
        except Exception:                                 # noqa: BLE001
            log.warning("history types unavailable", exc_info=True)
        self.btype.addItems(names)
        self.btype.currentTextChanged.connect(self._type_changed)
        g.addWidget(self.btype, 0, 1, 1, 3)
        g.addWidget(QLabel("Gross SF:"), 0, 4)
        self.sf = QLineEdit()
        self.sf.setPlaceholderText("e.g. 4500")
        g.addWidget(self.sf, 0, 5)
        g.addWidget(QLabel("Stories:"), 0, 6)
        self.stories = QSpinBox()
        self.stories.setRange(1, 60)
        g.addWidget(self.stories, 0, 7)
        g.addWidget(QLabel("Structure:"), 1, 0)
        self.structure = QComboBox()
        for k, v in M.STRUCTURES.items():
            self.structure.addItem(v, k)
        g.addWidget(self.structure, 1, 1)
        g.addWidget(QLabel("Roof:"), 1, 2)
        self.roof = QComboBox()
        for k, v in M.ROOFS.items():
            self.roof.addItem(v, k)
        g.addWidget(self.roof, 1, 3)
        g.addWidget(QLabel("Site area SF:"), 1, 4)
        self.site = QLineEdit()
        self.site.setPlaceholderText("optional")
        g.addWidget(self.site, 1, 5)
        self.sprinklered = QCheckBox("Sprinklered")
        g.addWidget(self.sprinklered, 1, 6, 1, 2)
        g.addWidget(QLabel("Exterior walls %:"), 2, 0)
        self.ext = {}
        for i, (k, v) in enumerate(M.EXTERIORS.items()):
            e = QLineEdit()
            e.setPlaceholderText(v)
            e.setToolTip(f"{v}: % of the exterior wall area (the rest is "
                         "priced as the building's usual finish)")
            self.ext[k] = e
            g.addWidget(e, 2, 1 + i)
        go = QPushButton("Price It")
        go.clicked.connect(lambda: self.price_it())
        g.addWidget(go, 2, 6, 1, 2)
        lay.addLayout(g)
        self.result = QLabel("")
        self.result.setWordWrap(True)
        lay.addWidget(self.result)
        split = QSplitter(Qt.Horizontal)
        hb = QGroupBox("From your job history")
        hl = QVBoxLayout(hb)
        self.hist_text = QLabel("")
        self.hist_text.setWordWrap(True)
        hl.addWidget(self.hist_text)
        self.hist_table = QTableWidget(0, 2)
        self.hist_table.setHorizontalHeaderLabels(["Division", "Amount"])
        self.hist_table.verticalHeader().setVisible(False)
        self.hist_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        hl.addWidget(self.hist_table, 1)
        self.effects = QLabel("")
        self.effects.setWordWrap(True)
        hl.addWidget(self.effects)
        self.add_hist = QPushButton("Add History Lines to Estimate")
        self.add_hist.setEnabled(False)
        self.add_hist.clicked.connect(lambda: self.add_history())
        hl.addWidget(self.add_hist)
        split.addWidget(hb)
        qb = QGroupBox("From quantities (Generate Set plan)")
        ql = QVBoxLayout(qb)
        self.qty_text = QLabel("")
        self.qty_text.setWordWrap(True)
        ql.addWidget(self.qty_text)
        self.qdiv_table = QTableWidget(0, 2)
        self.qdiv_table.setHorizontalHeaderLabels(["Division", "Amount"])
        self.qdiv_table.verticalHeader().setVisible(False)
        self.qdiv_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        ql.addWidget(self.qdiv_table, 1)
        self.add_qty = QPushButton("Add Quantity Lines to Estimate")
        self.add_qty.setEnabled(False)
        self.add_qty.clicked.connect(lambda: self.add_quantities())
        ql.addWidget(self.add_qty)
        split.addWidget(qb)
        lay.addWidget(split, 2)
        lay.addWidget(QLabel("<b>The plan's quantities</b> (no price: the "
                             "reason is shown)"))
        self.qty_table = QTableWidget(0, len(self.QTY_COLS))
        self.qty_table.setHorizontalHeaderLabels(self.QTY_COLS)
        self.qty_table.verticalHeader().setVisible(False)
        self.qty_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.qty_table.horizontalHeader().setSectionResizeMode(
            4, QHeaderView.Stretch)
        lay.addWidget(self.qty_table, 2)
        lay.addWidget(QLabel("<b>Factors</b> on your history (edit a Value; "
                             "your past jobs are the baseline)"))
        self.factor_table = QTableWidget(0, len(self.FACTOR_COLS))
        self.factor_table.setHorizontalHeaderLabels(self.FACTOR_COLS)
        self.factor_table.verticalHeader().setVisible(False)
        self.factor_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        self.factor_table.itemChanged.connect(self._factor_edited)
        lay.addWidget(self.factor_table, 1)
        self.msg = QLabel("")
        self.msg.setStyleSheet("color: #b00;")
        self.msg.setWordWrap(True)
        lay.addWidget(self.msg)
        btns = QHBoxLayout()
        btns.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        btns.addWidget(close)
        lay.addLayout(btns)
        self.fill_factors()
        self._type_changed(self.btype.currentText())
        if doc is None:
            self.msg.setText("Open a PDF to add the lines to its estimate "
                             "(you can still price it here).")

    def _type_changed(self, text):
        from . import model_estimate as M
        d = M.TYPE_DEFAULTS.get(M.type_key(text))
        if d:
            self.structure.setCurrentIndex(self.structure.findData(
                d["structure"]))
            self.roof.setCurrentIndex(self.roof.findData(d["roof"]))

    def fill_factors(self):
        from . import model_estimate as M
        self._filling = True
        try:
            self.factor_table.setRowCount(0)
            for f in M.factors():
                r = self.factor_table.rowCount()
                self.factor_table.insertRow(r)
                self.factor_table.setItem(r, 0, _ro(f["label"]))
                divs = f["divisions"]
                self.factor_table.setItem(r, 1, _ro(
                    "all divisions" if divs == "all" else
                    ", ".join(divs)))
                self.factor_table.setItem(r, 2, _ro(M.KIND_LABEL[f["kind"]]))
                it = QTableWidgetItem(f"{f['value'].normalize():f}")
                it.setData(Qt.UserRole, f["key"])
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.factor_table.setItem(r, 3, it)
        finally:
            self._filling = False

    def _factor_edited(self, item):
        from . import model_estimate as M
        if self._filling or item.column() != 3:
            return
        try:
            M.set_factor(item.data(Qt.UserRole), item.text().strip())
            self.msg.setText("")
        except M.ModelError as e:
            self.msg.setText(str(e))
        self.fill_factors()
        if self.res is not None:
            self.price_it()

    def set_factor(self, key, value):
        for r in range(self.factor_table.rowCount()):
            it = self.factor_table.item(r, 3)
            if it.data(Qt.UserRole) == key:
                it.setText(str(value))
                return True
        return False

    def inputs(self):
        from . import model_estimate as M
        return M.inputs(
            self.btype.currentText(), self.sf.text().replace(",", ""),
            self.stories.value(), self.structure.currentData(),
            {k: e.text().strip() for k, e in self.ext.items()},
            self.roof.currentData(), self.site.text().replace(",", ""),
            self.sprinklered.isChecked())

    def price_it(self, btype=None, sf=None, stories=None, structure=None,
                 roof=None, site_sf=None, sprinklered=None, exterior=None):
        """Price with the dialog's inputs (any given here are set first);
        returns model_estimate.run()'s result, or None when an input is
        wrong."""
        from . import model_estimate as M
        if btype is not None:
            self.btype.setCurrentText(btype)
        if sf is not None:
            self.sf.setText(str(sf))
        if stories is not None:
            self.stories.setValue(int(stories))
        if structure is not None:
            self.structure.setCurrentIndex(self.structure.findData(
                structure))
        if roof is not None:
            self.roof.setCurrentIndex(self.roof.findData(roof))
        if site_sf is not None:
            self.site.setText(str(site_sf))
        if sprinklered is not None:
            self.sprinklered.setChecked(bool(sprinklered))
        for k, v in (exterior or {}).items():
            self.ext[k].setText(str(v))
        self.res = None
        for t in (self.hist_table, self.qdiv_table, self.qty_table):
            t.setRowCount(0)
        self.add_hist.setEnabled(False)
        self.add_qty.setEnabled(False)
        self.effects.setText("")
        try:
            inp = self.inputs()
        except M.ModelError as e:
            self.result.setText(str(e))
            self.hist_text.setText("")
            self.qty_text.setText("")
            return None
        try:
            res = M.run(inp, self.doc)
        except Exception as e:                            # noqa: BLE001
            log.warning("model estimate failed", exc_info=True)
            self.result.setText(f"Couldn't price it: {e}")
            return None
        self.res = res
        h, q = res["history"], res["quantities"]
        self.hist_text.setText(M.describe_history(h, inp))
        self.qty_text.setText(M.describe_quantities(q))
        if h is not None:
            for x in h["lines"]:
                self._row(self.hist_table, x)
            bits = [f"{e['label']}: {dmoney.fmt(e['amount'])}"
                    for e in h["effects"]] + h["notes"]
            self.effects.setText("<br>".join(bits))
        for x in q["lines"]:
            self._row(self.qdiv_table, x)
        for r in q["rows"]:
            n = self.qty_table.rowCount()
            self.qty_table.insertRow(n)
            why = r.get("status") or r.get("problem") or ""
            if r.get("ext") is None and r.get("problem"):
                why = "NO PRICE: " + r["problem"]
            vals = [r["item"], f"{float(r['qty']):,.2f}", r["unit"],
                    r["division"], why,
                    dmoney.fmt(r.get("total") or 0) if r.get("ext")
                    is not None else ""]
            for c, v in enumerate(vals):
                self.qty_table.setItem(n, c, _ro(v, c in (1, 5)))
        parts = [M.describe_inputs(inp) + "."]
        if h is not None and q["lines"]:
            diff = q["total"] - h["total"]
            parts.append(f"History {dmoney.fmt(h['total'])} "
                         f"({dmoney.fmt(M.per_sf(h))}/SF) vs quantities "
                         f"{dmoney.fmt(q['total'])} "
                         f"({dmoney.fmt(M.per_sf(q))}/SF): difference "
                         f"{dmoney.fmt(diff)}.")
        parts += q["notes"]
        if res["missing"]:
            parts.append(res["missing"])
        self.result.setText(" ".join(parts))
        self.add_hist.setEnabled(self.doc is not None and h is not None
                                 and bool(h["lines"]))
        self.add_qty.setEnabled(self.doc is not None and bool(q["lines"]))
        return res

    def _row(self, table, x):
        r = table.rowCount()
        table.insertRow(r)
        table.setItem(r, 0, _ro(f"Division {x['division']} - {x['title']}"
                                if x["division"] else "Uncoded"))
        table.setItem(r, 1, _ro(dmoney.fmt(x["amount"]), True))

    def _add(self, which):
        from . import model_estimate as M
        if self.doc is None or self.res is None:
            return []
        lines = M.to_lines(self.res[which])
        if not lines:
            return []
        self.added_ids = estimate_lines.add(self.doc, lines)
        self.accept()
        return self.added_ids

    def add_history(self):
        return self._add("history")

    def add_quantities(self):
        return self._add("quantities")
