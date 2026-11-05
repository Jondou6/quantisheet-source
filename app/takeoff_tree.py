"""The Takeoff panel (left side): every sheet with takeoff
on it, and under it each item - its color, name and total - with an eye to
show or hide it on the drawing. Double-click an item to go to it.

Above the sheets is the item list: "+ New Item" makes an item (name, type,
color) before anything is drawn; click one and every click on the drawing
adds to it (app/takeoff_items.py keeps them in the PDF)."""
import fitz
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (QColorDialog, QComboBox, QDialog,
                               QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QHeaderView, QInputDialog, QLineEdit, QMenu,
                               QMessageBox, QPushButton, QSplitter,
                               QToolButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from . import annotate, takeoff_items

ROLE = Qt.UserRole
UNITS = {"count": "ea"}


def _rk(ref):
    """A hashable key for an annotation reference (a dict)."""
    return tuple(sorted(ref.items())) if isinstance(ref, dict) else ref


def _swatch(rgb, size=12):
    pm = QPixmap(size, size)
    c = QColor.fromRgbF(*(rgb or (0.4, 0.4, 0.4))[:3])
    pm.fill(c)
    return QIcon(pm)


def _fmt(v, unit):
    if unit in ("ea", "") and float(v).is_integer():
        return f"{int(v):,} {unit or 'ea'}"
    return f"{v:,.1f} {unit}"


def pending_text(total, pending, unit):
    """An item's total with its pending-review part beside it, not in it:
    '120 SF (+45 SF pending)'."""
    return f"{_fmt(total, unit)} (+{_fmt(pending, unit)} pending)"


def group_items(doc):
    """{page: {(group, type, unit): {"total", "n", "refs", "color",
    "hidden", "pending", "n_pending"}}} for the document's takeoff.
    "pending" / "n_pending": AI measurements flagged for review and not
    yet accepted - kept out of "total" / "n"."""
    items = annotate.takeoff_items(doc)
    info = {}                       # ref -> (color, hidden)
    for pno in sorted({it["page"] for it in items}):
        for a in annotate.iter_annots(doc[pno]):
            subj = (a.info or {}).get("subject", "")
            if not subj.startswith(annotate.TAKEOFF + ":"):
                continue            # its label shares the reference
            try:                    # a count's color is its PSColor
                c = annotate.markup_color(doc, a)
            except Exception:
                c = None
            c = c or (a.colors or {}).get("stroke") or (a.colors or {}).get(
                "fill")
            info[(pno, _rk(annotate.ref(a)))] = (
                c, bool(a.flags & fitz.PDF_ANNOT_IS_HIDDEN))
    out = {}
    for it in items:
        name = it["group"] or it["type"].title()
        key = (name, it["type"], it["unit"] or UNITS.get(it["type"], ""))
        g = out.setdefault(it["page"], {}).setdefault(
            key, {"total": 0.0, "n": 0, "refs": [], "color": None,
                  "hidden": True, "pending": 0.0, "n_pending": 0})
        v = it["value"] if it["type"] != "count" else \
            (it.get("multiplier") or 1)
        if it.get("pending"):
            # flagged for review and not accepted: its own subtotal,
            # not in the total until a person accepts it
            g["pending"] += v
            g["n_pending"] += 1
        else:
            g["total"] += v
            g["n"] += 1
        g["refs"].append(it["ref"])
        c, hid = info.get((it["page"], _rk(it["ref"])), (None, False))
        g["color"] = g["color"] or c
        g["hidden"] = g["hidden"] and hid
    return out


class NewItemDialog(QDialog):
    """Name, type and color for a new takeoff item."""

    def __init__(self, parent, color, name="", mtype="count"):
        super().__init__(parent)
        self.setWindowTitle("New Takeoff Item")
        self.color = tuple(color)
        form = QFormLayout(self)
        self.name = QLineEdit(name)
        self.name.setPlaceholderText("e.g. Outlets, Wall Type A, Carpet")
        form.addRow("Name:", self.name)
        self.type = QComboBox()
        for t in takeoff_items.TYPES:
            self.type.addItem(takeoff_items.LABEL[t], t)
        self.type.setCurrentIndex(max(0, self.type.findData(mtype)))
        form.addRow("Type:", self.type)
        self.color_btn = QPushButton()
        self.color_btn.clicked.connect(self._pick)
        self._show_color()
        form.addRow("Color:", self.color_btn)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _show_color(self):
        self.color_btn.setIcon(_swatch(self.color, 16))
        self.color_btn.setText(QColor.fromRgbF(*self.color[:3]).name())

    def _pick(self):
        c = QColorDialog.getColor(QColor.fromRgbF(*self.color[:3]), self,
                                  "Item Color")
        if c.isValid():
            self.color = (c.redF(), c.greenF(), c.blueF())
            self._show_color()

    def _ok(self):
        if self.name.text().strip():
            self.accept()

    def values(self):
        return (self.name.text().strip(), self.type.currentData(),
                self.color)


class TakeoffTree(QWidget):
    go_to = Signal(int, object)          # page, annotation ref
    changed = Signal(int)                # a page's markups were shown/hidden
    activate = Signal(object)            # an item to take off (dict) / None
    edited = Signal()                    # the saved item list changed

    def __init__(self):
        super().__init__()
        self.doc = None
        self.view_for = None             # () -> the DocView (MainWindow)
        self.active = None               # (name, type) being taken off
        self.item_list = []
        self.grand = {}
        self.current_page = 0
        self._labels = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search takeoff…")
        self.search.textChanged.connect(lambda _t: self.refresh())
        top.addWidget(self.search, 1)
        self.expand_btn = QToolButton()
        self.expand_btn.setText("±")
        self.expand_btn.setToolTip("Expand / collapse all sheets")
        self.expand_btn.clicked.connect(self._toggle_expand)
        top.addWidget(self.expand_btn)
        self.clean_btn = QToolButton()
        self.clean_btn.setText("🎨")
        self.clean_btn.setToolTip("Clean display: one color per item, "
                                  "areas see-through")
        self.clean_btn.clicked.connect(lambda: self.clean_display())
        top.addWidget(self.clean_btn)
        lay.addLayout(top)
        bar = QHBoxLayout()
        self.new_btn = QToolButton()
        self.new_btn.setText("+ New Item")
        self.new_btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.new_btn.setToolTip("Make a takeoff item (name, count / length "
                                "/ area, color), then click on the drawing")
        self.new_btn.clicked.connect(lambda: self.new_item())
        bar.addWidget(self.new_btn)
        bar.addStretch(1)
        lay.addLayout(bar)
        self.items = QTreeWidget()
        self.items.setColumnCount(2)
        self.items.setHeaderLabels(["Takeoff Items", "Total"])
        ih = self.items.header()
        ih.setSectionResizeMode(0, QHeaderView.Stretch)
        ih.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        ih.setStretchLastSection(False)
        self.items.setRootIsDecorated(False)
        self.items.setUniformRowHeights(True)
        self.items.itemClicked.connect(self._item_clicked)
        self.items.itemDoubleClicked.connect(self._item_open)
        self.items.setContextMenuPolicy(Qt.CustomContextMenu)
        self.items.customContextMenuRequested.connect(self._item_menu)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Item", "Quantity", "👁"])
        h = self.tree.header()
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        h.setStretchLastSection(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setIndentation(12)
        self.tree.itemDoubleClicked.connect(self._open)
        self.tree.itemChanged.connect(self._eye)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        split = QSplitter(Qt.Vertical)
        split.addWidget(self.items)
        split.addWidget(self.tree)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 2)
        lay.addWidget(split, 1)
        self._filling = False

    def set_doc(self, doc):
        if doc is not self.doc:
            self._labels = {}
        self.doc = doc
        self.refresh()

    def sheet_label(self, pno):
        if pno not in self._labels:
            lab = ""
            try:                     # the sheet number and title it prints
                from . import sheets
                lab = sheets.label_for(self.doc[pno])
            except Exception:
                lab = ""
            if not lab:
                try:
                    lab = self.doc[pno].get_label() or ""
                except Exception:
                    lab = ""
            self._labels[pno] = lab or f"Page {pno + 1}"
        return self._labels[pno]

    def refresh(self):
        self._filling = True
        open_pages = set()
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            d = top.data(0, ROLE) or ("",)
            if top.isExpanded():
                open_pages.add(d[1] if d[0] == "page" else d[0])
        first = self.tree.topLevelItemCount() == 0
        self.tree.clear()
        if self.doc is None:
            self.items.clear()
            self.item_list = []
            self._filling = False
            return {}
        groups = group_items(self.doc)
        self._fill_items(groups)
        words = [w.lower() for w in self.search.text().split()]
        grand, pend = {}, {}
        bold = QFont()
        bold.setBold(True)
        for pno in sorted(groups):
            label = self.sheet_label(pno)
            rows = []
            for (name, mtype, unit), g in sorted(groups[pno].items()):
                hay = f"{label} {name} {mtype}".lower()
                if words and not all(w in hay for w in words):
                    continue
                rows.append((name, mtype, unit, g))
                k = (name, mtype, unit)
                grand[k] = grand.get(k, 0.0) + g["total"]
                if g.get("n_pending"):
                    pend[k] = pend.get(k, 0.0) + g["pending"]
            if not rows:
                continue
            top = QTreeWidgetItem([label, f"{len(rows)} item"
                                   f"{'s' * (len(rows) != 1)}", ""])
            top.setData(0, ROLE, ("page", pno))
            top.setFont(0, bold)
            top.setToolTip(0, f"Page {pno + 1}: {label}")
            self.tree.addTopLevelItem(top)
            for name, mtype, unit, g in rows:
                it = QTreeWidgetItem([name, _fmt(g["total"], unit), ""])
                it.setIcon(0, _swatch(g["color"]))
                it.setData(0, ROLE, ("group", pno, g["refs"]))
                tip = (f"{name} - {mtype}, {g['n']} "
                       f"measurement{'s' * (g['n'] != 1)}")
                if g.get("n_pending"):
                    it.setText(1, pending_text(g["total"], g["pending"],
                                               unit))
                    tip += (f"; {g['n_pending']} more flagged for review "
                            f"({_fmt(g['pending'], unit)}) - not in the "
                            "total until accepted in Check Takeoff")
                it.setToolTip(0, tip)
                it.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(2, Qt.Unchecked if g["hidden"]
                                 else Qt.Checked)
                if g["hidden"]:
                    it.setForeground(0, QBrush(QColor(140, 140, 140)))
                top.addChild(it)
            top.setExpanded(first or pno in open_pages or
                            pno == self.current_page or bool(words))
        if grand and len(groups) > 1:
            tot = QTreeWidgetItem(["All sheets (totals)", "", ""])
            tot.setData(0, ROLE, ("totals",))
            tot.setFont(0, bold)
            self.tree.addTopLevelItem(tot)
            for (name, mtype, unit), v in sorted(grand.items()):
                it = QTreeWidgetItem([name, _fmt(v, unit), ""])
                it.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
                tot.addChild(it)
            tot.setExpanded("totals" in open_pages)
        if pend:
            pt = QTreeWidgetItem(["Pending review (not in totals until "
                                  "accepted)", "", ""])
            pt.setData(0, ROLE, ("pending",))
            pt.setFont(0, bold)
            pt.setForeground(0, QBrush(QColor(170, 100, 0)))
            self.tree.addTopLevelItem(pt)
            for (name, mtype, unit), v in sorted(pend.items()):
                it = QTreeWidgetItem([name, _fmt(v, unit), ""])
                it.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
                pt.addChild(it)
            pt.setExpanded(True)
        if not grand and not pend:
            empty = QTreeWidgetItem(["No takeoff yet - measure something "
                                     "and it shows up here.", "", ""])
            empty.setData(0, ROLE, ("empty",))
            empty.setForeground(0, QBrush(QColor(130, 130, 130)))
            self.tree.addTopLevelItem(empty)
        self._filling = False
        self.grand = grand
        return groups

    # ---------------------------------------------------- takeoff items
    def _fill_items(self, groups=None):
        self.item_list = takeoff_items.items(self.doc, groups)
        words = [w.lower() for w in self.search.text().split()]
        self.items.clear()
        for it in self.item_list:
            if words and not all(w in f"{it['name']} {it['type']}".lower()
                                 for w in words):
                continue
            row = QTreeWidgetItem([it["name"], takeoff_items.fmt_total(it)])
            row.setIcon(0, _swatch(it["color"]))
            row.setData(0, ROLE, ("item", it["name"], it["type"]))
            row.setToolTip(0, f"{it['name']} - {it['type']}, {it['n']} "
                           f"markup{'s' * (it['n'] != 1)}. Click to take "
                           "off; right-click to rename, recolor or delete.")
            row.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
            self.items.addTopLevelItem(row)
        self._show_active()

    def _row_key(self, row):
        d = row.data(0, ROLE) if row is not None else None
        return (d[1], d[2]) if d and d[0] == "item" else None

    def item(self, name, mtype):
        for it in self.item_list:
            if takeoff_items.key(it) == (name, mtype):
                return it
        return None

    def set_active(self, key):
        """Highlight the item being taken off (None = none)."""
        key = tuple(key) if key else None
        if key == self.active:
            return
        self.active = key
        self._show_active()

    def _show_active(self):
        bold = QFont()
        bold.setBold(True)
        hi = QBrush(QColor(255, 236, 150))
        cur = None
        for i in range(self.items.topLevelItemCount()):
            row = self.items.topLevelItem(i)
            on = self.active is not None and self._row_key(row) == \
                self.active
            for col in (0, 1):
                row.setFont(col, bold if on else QFont())
                row.setBackground(col, hi if on else QBrush())
                if on:
                    row.setForeground(col, QBrush(QColor(0, 0, 0)))
                else:
                    row.setData(col, Qt.ForegroundRole, None)
            if on:
                cur = row
        if cur is not None:
            self.items.setCurrentItem(cur)
        else:
            self.items.clearSelection()

    def _item_clicked(self, row, _col=0):
        k = self._row_key(row)
        it = self.item(*k) if k else None
        if it is not None:
            self.activate.emit(dict(it))

    def _item_open(self, row, _col=0):
        k = self._row_key(row)
        it = self.item(*k) if k else None
        if it and it["refs"]:
            pno, r = it["refs"][0]
            self.go_to.emit(pno, r)

    def _view(self):
        return self.view_for() if self.view_for else None

    def _apply(self, marks):
        """Apply marks to the markups (one undo step); the saved list was
        changed already - with no marks it is saved as its own step."""
        v = self._view()
        n = 0
        if marks and v is not None and v.doc is self.doc:
            n = v.apply_marks(marks)
        if not n:
            self.edited.emit()
        self.refresh()
        return n

    def new_item(self, name=None, mtype=None, color=None, activate=True):
        """Make an item; with no name, ask in the New Item dialog. Starts
        taking it off unless activate=False. Returns the item or None."""
        if self.doc is None:
            return None
        if name is None:
            dlg = NewItemDialog(self, color or takeoff_items.next_color(
                self.doc), mtype=mtype or "count")
            if dlg.exec() != QDialog.Accepted:
                return None
            name, mtype, color = dlg.values()
        mtype = mtype or "count"
        if not str(name).strip():
            return None
        takeoff_items.add(self.doc, name, mtype, color)
        self.edited.emit()
        self.refresh()
        it = self.item(str(name).strip()[:60], mtype)
        if it is not None and activate:
            self.activate.emit(dict(it))
        return it

    def rename_item(self, name, mtype, new=None):
        """Rename (reassign) an item and its markups. Asked from the menu,
        it first says how many pieces on how many pages will move, and
        whether they join an existing item; one Undo puts them back."""
        asked = new is None
        if asked:
            new, ok = QInputDialog.getText(self, "Rename Item", "Name:",
                                           text=name)
            if not ok:
                return 0
        new = str(new).strip()[:60]
        if not new or new == name or self.item(name, mtype) is None:
            return 0
        if asked:
            pv = takeoff_items.reassign_preview(self.doc, name, mtype, new)
            if pv["pieces"] and QMessageBox.question(
                    self, "Rename Item",
                    takeoff_items.reassign_text(pv, name, new)) != \
                    QMessageBox.Yes:
                return 0
        was = self.active == (name, mtype)
        from . import name_memory
        old_it = takeoff_items.find(self.doc, name, mtype)
        methods = name_memory.methods_of(self.doc, (old_it or {}).get(
            "refs") or [])
        marks = takeoff_items.rename(self.doc, name, mtype, new)
        try:                    # its prices and linked lines go with it
            from . import estimate
            estimate.follow_rename(self.doc, name, mtype, new)
        except Exception:                                 # noqa: BLE001
            import logging
            logging.getLogger(__name__).warning(
                "prices didn't follow the rename", exc_info=True)
        self._apply(marks)
        # an AI item renamed: the next AI Takeoff uses your name (Nov 1)
        name_memory.learn(name, new, mtype, methods)
        it = self.item(new, mtype)
        if was and it is not None:
            self.activate.emit(dict(it))      # keep taking it off
        return 1

    def recolor_item(self, name, mtype, color=None):
        it = self.item(name, mtype)
        if it is None:
            return 0
        if color is None:
            c = QColorDialog.getColor(
                QColor.fromRgbF(*(it["color"] or (1, 0, 0))[:3]), self,
                f"Color for {name}")
            if not c.isValid():
                return 0
            color = (c.redF(), c.greenF(), c.blueF())
        was = self.active == (name, mtype)
        self._apply(takeoff_items.recolor(self.doc, name, mtype, color))
        it = self.item(name, mtype)
        if was and it is not None:
            self.activate.emit(dict(it))      # new clicks get the new color
        return 1

    def duplicate_item(self, name, mtype):
        it = takeoff_items.duplicate(self.doc, name, mtype)
        if it is None:
            return None
        self.edited.emit()
        self.refresh()
        return self.item(it["name"], mtype)

    def delete_item(self, name, mtype, confirm=True):
        it = self.item(name, mtype)
        if it is None:
            return 0
        if it["n"] and confirm and QMessageBox.question(
                self, "Delete Item",
                f"Delete \"{name}\" and its {it['n']} markup"
                f"{'s' * (it['n'] != 1)}? (Edit > Undo brings them back.)") \
                != QMessageBox.Yes:
            return 0
        if self.active == (name, mtype):
            self.activate.emit(None)
        self._apply(takeoff_items.remove(self.doc, name, mtype))
        return 1

    def _item_menu(self, pos):
        row = self.items.itemAt(pos)
        k = self._row_key(row)
        if not k:
            m = QMenu(self)
            m.addAction("New Item…", lambda: self.new_item())
            m.exec(self.items.viewport().mapToGlobal(pos))
            return
        name, mtype = k
        it = self.item(name, mtype)
        m = QMenu(self)
        m.addAction("Take Off", lambda: self._item_clicked(row))
        if it and it["refs"]:
            m.addAction("Go to", lambda: self._item_open(row))
        m.addSeparator()
        m.addAction("Rename…", lambda: self.rename_item(name, mtype))
        m.addAction("Change Color…", lambda: self.recolor_item(name, mtype))
        m.addAction("Duplicate", lambda: self.duplicate_item(name, mtype))
        m.addAction("Delete", lambda: self.delete_item(name, mtype))
        m.exec(self.items.viewport().mapToGlobal(pos))

    def _toggle_expand(self):
        n = self.tree.topLevelItemCount()
        anyopen = any(self.tree.topLevelItem(i).isExpanded()
                      for i in range(n))
        for i in range(n):
            self.tree.topLevelItem(i).setExpanded(not anyopen)

    def _open(self, item, _col=0):
        d = item.data(0, ROLE)
        if not d or d[0] in ("totals", "empty", "pending"):
            return
        if d[0] == "page":
            self.go_to.emit(d[1], None)
        else:
            self.go_to.emit(d[1], d[2][0] if d[2] else None)

    # ---------------------------------------------------- show / hide
    def set_visible(self, pno, refs, visible):
        """Show or hide these markups on the drawing (they still count)."""
        page = self.doc[pno]
        n = 0
        want = {_rk(r) for r in refs}
        for a in annotate.iter_annots(page):
            if _rk(annotate.ref(a)) not in want:
                continue
            f = a.flags
            nf = (f & ~fitz.PDF_ANNOT_IS_HIDDEN) if visible else \
                (f | fitz.PDF_ANNOT_IS_HIDDEN)
            if nf != f:
                a.set_flags(nf)
                a.update()
                n += 1
        if n:
            annotate.invalidate(self.doc) if hasattr(
                annotate, "invalidate") else None
            self.changed.emit(pno)
        return n

    def _eye(self, item, col):
        if self._filling or col != 2:
            return
        d = item.data(0, ROLE)
        if not d or d[0] != "group":
            return
        self.set_visible(d[1], d[2], item.checkState(2) == Qt.Checked)
        item.setForeground(0, QBrush(QColor(140, 140, 140))
                           if item.checkState(2) != Qt.Checked
                           else self.tree.palette().text())

    def _menu(self, pos):
        item = self.tree.itemAt(pos)
        d = item.data(0, ROLE) if item else None
        if not d or d[0] in ("totals", "empty", "pending"):
            return
        m = QMenu(self)
        if d[0] == "group":
            m.addAction("Go to", lambda: self._open(item))
            m.addAction("Hide", lambda: item.setCheckState(2, Qt.Unchecked))
            m.addAction("Show", lambda: item.setCheckState(2, Qt.Checked))
            m.addSeparator()
            m.addAction("Label Prefix, Depth && Drop…",
                        lambda: self.item_settings(item.text(0)))
        else:
            m.addAction("Go to sheet", lambda: self._open(item))
            m.addAction("Hide all on this sheet",
                        lambda: self._all(item, Qt.Unchecked))
            m.addAction("Show all on this sheet",
                        lambda: self._all(item, Qt.Checked))
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def item_settings(self, group, prefix=None, depth=None, drop=None):
        """Defaults for an item: counts are labelled PREFIX-1, -2...; each
        structure gets the default depth; each run of pipe gets the drop
        added once."""
        from . import item_defaults
        if self.doc is None:
            return None
        if prefix is None:
            from PySide6.QtWidgets import QInputDialog
            try:
                cur = item_defaults._read(self.doc)["items"].get(group)
            except Exception:
                cur = None
            cur = cur or {"prefix": item_defaults.prefix_for(group),
                          "depth": None, "drop": 0.0}
            prefix, ok = QInputDialog.getText(
                self, group, "Label prefix for counts (e.g. MH):",
                text=cur.get("prefix") or "")
            if not ok:
                return None
            depth, ok = QInputDialog.getDouble(
                self, group, "Default depth, ft (0 = none):",
                float(cur.get("depth") or 0), 0, 200, 1)
            if not ok:
                return None
            drop, ok = QInputDialog.getDouble(
                self, group, "Drop added to each run, ft:",
                float(cur.get("drop") or 0), 0, 200, 1)
            if not ok:
                return None
        rec = item_defaults.set_default(self.doc, group, prefix=prefix,
                                        depth=depth or None, drop=drop)
        self.changed.emit(self.current_page)
        return rec

    # one strong color per item, areas see-through - the clean PlanSwift
    # look (Chief of Staff's v5 idea, done here on the existing markups)
    PALETTE = takeoff_items.PALETTE

    def clean_display(self):
        """Give every item its own color (the same item always gets the
        same color), fill areas at 35% and draw lines heavier."""
        if self.doc is None:
            return 0
        names = sorted({(it["group"] or it["type"].title())
                        for it in annotate.takeoff_items(self.doc)})
        color = {n: self.PALETTE[i % len(self.PALETTE)]
                 for i, n in enumerate(names)}
        saved = takeoff_items.read(self.doc)
        if any(it["name"] in color for it in saved):
            for it in saved:            # the item list keeps up
                it["color"] = color.get(it["name"], it["color"])
            takeoff_items.write(self.doc, saved)
        n = 0
        for pno in range(self.doc.page_count):
            touched = False
            for a in annotate.iter_annots(self.doc[pno]):
                subj = (a.info or {}).get("subject", "")
                if not subj.startswith(annotate.TAKEOFF + ":"):
                    continue
                parts = subj.split(":")
                mtype = parts[1] if len(parts) > 1 else ""
                group = (parts[4] if len(parts) > 4 else "") or \
                    mtype.title()
                c = color.get(group)
                if c is None:
                    continue
                try:
                    if mtype in ("area", "volume", "cutout"):
                        a.set_colors(stroke=c, fill=c)
                        a.set_opacity(0.35)
                    elif mtype == "count":
                        a.set_colors(stroke=c, fill=c)
                    else:
                        a.set_colors(stroke=c)
                        a.set_border(width=3)
                    a.update()
                    n += 1
                    touched = True
                except Exception:
                    continue
            if touched:
                self.changed.emit(pno)
        self.refresh()
        return n

    def _all(self, top, state):
        for i in range(top.childCount()):
            top.child(i).setCheckState(2, state)
