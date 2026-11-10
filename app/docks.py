"""Bluebeam-style panels: Markups List, Properties, Tool Chest, Estimate,
Documents (project folder) and Bookmarks."""
import html
import logging
import os

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QColorDialog, QComboBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
    QMenu, QMessageBox, QPushButton, QSlider, QStyledItemDelegate,
    QTableWidget, QTableWidgetItem,
    QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
    QCheckBox, QTabWidget
)

from . import safecell
from . import annotate, estimate, toolchest
from .viewer import TOOLS
from .dmoney import c2 as _c2


def _report_name(kind, doc, ext):
    """Company rule, date first (app/reportname.py); the project is the
    open PDF's name."""
    from .reportname import report_file_name
    proj = os.path.splitext(os.path.basename(
        getattr(doc, "name", "") or ""))[0]
    return report_file_name(kind, proj, ext=ext)


log = logging.getLogger(__name__)


def _qc(c):
    if not c:
        return None
    c = list(c)
    if len(c) == 1:
        c = c * 3
    return QColor(int(c[0] * 255), int(c[1] * 255), int(c[2] * 255))


def swatch(c, size=14):
    pm = QPixmap(size, size)
    q = _qc(c)
    pm.fill(q if q else Qt.transparent)
    return QIcon(pm)


class _NumItem(QTableWidgetItem):
    """Table cell that sorts by number."""

    def __init__(self, text, value):
        super().__init__(text)
        self.value = value
        self.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def __lt__(self, other):
        try:
            return self.value < other.value
        except AttributeError:
            return super().__lt__(other)


# ---- Markups List ---------------------------------------------------------------

class MarkupsPanel(QWidget):
    """Every markup in the document: sort, filter, jump to, set status,
    delete, export."""

    go_to = Signal(int, object)                  # page, annotation ref
    change = Signal(int, object, dict)           # page, ref, changes
    delete = Signal(list)                        # [(page, ref)]
    column_edit = Signal(str, str, object)       # markup key, column, value
    manage_columns = Signal()

    COLS = ["Page", "Type", "Subject", "Comment", "Measurement", "Author",
            "Date", "Status", "Origin"]

    def __init__(self):
        super().__init__()
        self.doc = None
        self.items = []
        self.custom = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        bar = QHBoxLayout()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter (subject, comment, author…)")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._fill)
        self.status_filter = QComboBox()
        self.status_filter.addItems(["All statuses"] +
                                    [s or "None" for s in annotate.statuses()])
        self.status_filter.currentIndexChanged.connect(self._fill)
        self.page_only = QCheckBox("This page")
        self.page_only.toggled.connect(self._page_only_toggled)
        self.group_by = QComboBox()
        self.group_by.setToolTip("Group the list by a column, with each "
                                 "group's total")
        self.group_by.addItems(self._group_choices())
        self.group_by.currentIndexChanged.connect(self._fill)
        bar.addWidget(self.filter, 1)
        bar.addWidget(self.status_filter)
        bar.addWidget(self.group_by)
        bar.addWidget(self.page_only)
        lay.addLayout(bar)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.Interactive)
        h.setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setSortingEnabled(True)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked |
                                   QAbstractItemView.EditKeyPressed)
        self.table.itemChanged.connect(self._cell_edited)
        self.custom = []
        self.values = {}
        self._loading = False
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.cellDoubleClicked.connect(self._open)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.table)
        self.groups = QLabel("")
        self.groups.setWordWrap(True)
        self.groups.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.groups.hide()
        lay.addWidget(self.groups)
        bottom = QHBoxLayout()
        self.count = QLabel("")
        export = QPushButton("Export Summary…")
        export.clicked.connect(self._export_dialog)
        cols = QPushButton("Columns && Statuses…")
        cols.clicked.connect(self.manage_columns.emit)
        bottom.addWidget(self.count)
        bottom.addStretch()
        bottom.addWidget(cols)
        bottom.addWidget(export)
        lay.addLayout(bottom)
        self.current_page = 0

    def set_doc(self, doc):
        self.doc = doc
        self.refresh()

    # a drawing with more markups than this lists one page at a time to
    # start with (Nov 3: 31,580 markups took 40 s to list, on open)
    BIG = 4000

    def big(self):
        doc = self.doc
        if doc is None or doc.is_closed:
            return False
        if getattr(self, "_big_doc", (None,))[0] is not doc:
            self._big_doc = (doc, annotate.annot_count(doc) > self.BIG)
            want = None
            if self._big_doc[1] and not self.page_only.isChecked():
                want, self._auto_page = True, True
            elif not self._big_doc[1] and getattr(self, "_auto_page", False):
                want, self._auto_page = False, False   # (we ticked it)
            if want is not None:
                self.page_only.blockSignals(True)
                self.page_only.setChecked(want)
                self.page_only.blockSignals(False)
        return self._big_doc[1]

    def refresh(self):
        if self.doc is None or self.doc.is_closed:
            return
        from . import columns
        if self.big() and self.page_only.isChecked():
            self.items = annotate.markup_items(self.doc, [self.current_page])
        else:
            self.items = annotate.markup_items(self.doc)
        data = columns.read(self.doc)
        self.custom = data["columns"]
        self.values = columns.values_for(self.doc, self.items, data)
        cur = self.status_filter.currentIndex()
        self.status_filter.blockSignals(True)
        self.status_filter.clear()
        self.status_filter.addItems(["All statuses"] + [
            s or "None" for s in annotate.statuses()])
        self.status_filter.setCurrentIndex(max(0, min(
            cur, self.status_filter.count() - 1)))
        self.status_filter.blockSignals(False)
        g = self.group_by.currentText()
        self.group_by.blockSignals(True)
        self.group_by.clear()
        self.group_by.addItems(self._group_choices())
        i = self.group_by.findText(g)
        self.group_by.setCurrentIndex(max(0, i))
        self.group_by.blockSignals(False)
        self._fill()

    def _page_only_toggled(self, on):
        if self.big():               # the list holds one page: read again
            self.refresh()
        else:
            self._fill()

    def all_cols(self):
        return self.COLS + [c["name"] for c in self.custom]

    def _group_choices(self):
        from . import columns
        return ["No grouping"] + [f"Group by {k}" for k in columns.BUILT_IN] \
            + [f"Group by {c['name']}" for c in self.custom]

    def grouped_by(self):
        t = self.group_by.currentText()
        return t[len("Group by "):] if t.startswith("Group by ") else None

    def visible_items(self):
        text = self.filter.text().lower().strip()
        st = self.status_filter.currentIndex() - 1
        out = []
        for it in self.items:
            if self.page_only.isChecked() and it["page"] != self.current_page:
                continue
            sts = annotate.statuses()
            if 0 <= st < len(sts) and it["status"] != sts[st]:
                continue
            if text and text not in " ".join(
                    str(it[k]) for k in ("type", "subject", "comment",
                                         "author", "status")).lower():
                continue
            out.append(it)
        return out

    def _fill(self, *_):
        from . import columns
        self._loading = True
        self.table.setSortingEnabled(False)
        self.table.setUpdatesEnabled(False)
        self.table.setRowCount(0)
        cols = self.all_cols()
        if self.table.columnCount() != len(cols) or [
                self.table.horizontalHeaderItem(i).text()
                if self.table.horizontalHeaderItem(i) else ""
                for i in range(self.table.columnCount())] != cols:
            self.table.setColumnCount(len(cols))
            self.table.setHorizontalHeaderLabels(cols)
        shown = self.visible_items()
        index = {id(x): i for i, x in enumerate(self.items)}
        self.table.setRowCount(len(shown))      # (one insert per row was
        for idx, it in enumerate(shown):        # most of 17 s, Nov 3)
            r = idx
            page = _NumItem(str(it["page"] + 1), it["page"])
            page.setData(Qt.UserRole, index[id(it)])
            self.table.setItem(r, 0, page)
            typ = QTableWidgetItem(it["type"])
            typ.setIcon(swatch(_hexrgb(it["color"])))
            self.table.setItem(r, 1, typ)
            for col, key in ((2, "subject"), (3, "comment"),
                             (4, "measure"), (5, "author"), (6, "date"),
                             (7, "status"), (8, "origin")):
                cell = QTableWidgetItem(str(it.get(key, "")).replace(
                    "\n", " "))
                cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(r, col, cell)
            page.setFlags(page.flags() & ~Qt.ItemIsEditable)
            typ.setFlags(typ.flags() & ~Qt.ItemIsEditable)
            vals = self.values.get(columns.key_of(it), {})
            for j, c in enumerate(self.custom):
                text = vals.get(c["name"], "")
                try:
                    cell = _NumItem(text, float(str(text).replace(",", ""))) \
                        if c["type"] in ("number", "formula") and text \
                        else QTableWidgetItem(text)
                except ValueError:
                    cell = QTableWidgetItem(text)
                if c["type"] == "formula":
                    cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                    cell.setToolTip(c.get("formula", ""))
                elif c["type"] == "choice":
                    cell.setToolTip("Choices: " + ", ".join(
                        columns.choice_labels(c)))
                self.table.setItem(r, len(self.COLS) + j, cell)
        self.table.setSortingEnabled(True)
        self.table.setUpdatesEnabled(True)
        by = self.grouped_by()
        if by:
            cols = self.all_cols()
            if by in cols:
                self.table.sortItems(cols.index(by))
            summary = columns.group_summary(shown, by, self.values)
            parts = []
            for name, n, tot in summary[:40]:
                q = ", ".join(f"{_c2(v):,.2f} {u}" for u, v in tot.items())
                parts.append(f"<b>{html.escape(name)}</b>: {n}" +
                             (f" ({q})" if q else ""))
            self.groups.setText(f"By {html.escape(by)}: " +
                                " · ".join(parts))
            self.groups.show()
        else:
            self.groups.hide()
        self._loading = False
        if self.big() and self.page_only.isChecked():
            self.count.setText(f"{len(shown)} on this page (a large set: "
                               "untick This page to list every markup)")
        else:
            self.count.setText(f"{len(shown)} of {len(self.items)} "
                               "markups")

    def _cell_edited(self, cell):
        if self._loading:
            return
        j = cell.column() - len(self.COLS)
        if not 0 <= j < len(self.custom):
            return
        it = self._item_at(cell.row())
        if it is None:
            return
        from . import columns
        c = self.custom[j]
        text = cell.text().strip()
        value = text
        if c["type"] == "number" and text:
            try:
                value = float(text.replace(",", "").replace("$", ""))
            except ValueError:
                QMessageBox.information(self, "Markups List",
                                        f"{c['name']} takes a number.")
                self.refresh()
                return
        if c["type"] == "choice" and text and c.get("choices") and \
                text not in columns.choice_labels(c):
            QMessageBox.information(
                self, "Markups List", f"{c['name']} must be one of: " +
                ", ".join(columns.choice_labels(c)))
            self.refresh()
            return
        self.column_edit.emit(columns.key_of(it), c["name"], value)

    def _item_at(self, row):
        cell = self.table.item(row, 0)
        if cell is None:
            return None
        return self.items[cell.data(Qt.UserRole)]

    def selected(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [it for it in (self._item_at(r) for r in rows) if it]

    def _open(self, row, _col):
        it = self._item_at(row)
        if it:
            self.go_to.emit(it["page"], it["ref"])

    def _menu(self, pos):
        items = self.selected()
        if not items:
            return
        m = QMenu(self)
        st = m.addMenu("Set Status")
        for name in annotate.statuses():
            st.addAction(name or "None", lambda n=name: [
                self.change.emit(it["page"], it["ref"], {"status": n})
                for it in items])
        if len(items) == 1:
            m.addAction("Edit Comment…", lambda: self._comment(items[0]))
            m.addAction("Go To", lambda: self.go_to.emit(items[0]["page"],
                                                          items[0]["ref"]))
        m.addSeparator()
        m.addAction(f"Delete {len(items)} markup(s)", lambda: self.delete.emit(
            [(it["page"], it["ref"]) for it in items]))
        m.exec(self.table.viewport().mapToGlobal(pos))

    def _comment(self, it):
        text, ok = QInputDialog.getMultiLineText(self, "Comment", "Comment:",
                                                 it["comment"])
        if ok:
            self.change.emit(it["page"], it["ref"], {"note": text})

    def _export_dialog(self):
        path, flt = QFileDialog.getSaveFileName(
            self, "Export Markup Summary",
            _report_name("Markup Summary", self.doc, ".csv"),
            "CSV (*.csv);;Excel (*.xlsx);;XML (*.xml)")
        if path:
            ext = {"Excel": ".xlsx", "XML": ".xml"}.get(
                (flt or "").split(" ")[0], ".csv")
            if not os.path.splitext(path)[1]:
                path += ext
            self.export(path)

    def export(self, path):
        """The list as shown (filters applied) to CSV, Excel or XML, by
        the file's extension."""
        from . import columns
        ext = os.path.splitext(path)[1].lower()
        if ext in (".xlsx", ".xml"):
            rows = columns.rows_for_export(self.visible_items(), self.COLS,
                                           self.custom, self.values)
            if ext == ".xlsx":
                by = self.grouped_by()
                if by:
                    head, body = rows[0], rows[1:]
                    keyed = sorted(zip(self.visible_items(), body),
                                   key=lambda x: columns.group_key(
                                       x[0], by, self.values))
                    rows = [head] + [r for _i, r in keyed]
                return columns.write_xlsx(path, rows)
            return columns.write_xml(path, rows)
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = safecell.writer(f)
            w.writerow(self.COLS + ["Color"] +
                       [c["name"] for c in self.custom])
            for it in self.visible_items():
                vals = self.values.get(columns.key_of(it), {})
                w.writerow([it["page"] + 1, it["type"], it["subject"],
                            it["comment"], it["measure"], it["author"],
                            it["date"], it["status"], it.get("origin", ""),
                            it["color"]] +
                           [vals.get(c["name"], "") for c in self.custom])
        return path


def _hexrgb(h):
    if not h or len(h) != 7:
        return None
    return [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]


# ---- Properties -------------------------------------------------------------------

class ColorButton(QToolButton):
    changed = Signal(object)

    def __init__(self, allow_none=False):
        super().__init__()
        self.color = None
        self.allow_none = allow_none
        self.setFixedWidth(60)
        self.clicked.connect(self._pick)
        self.set(None)

    def set(self, c):
        self.color = list(c)[:3] if c else None
        self.setIcon(swatch(self.color, 16))
        self.setText("" if self.color else "None")
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)

    def _pick(self):
        if self.allow_none:
            m = QMenu(self)
            m.addAction("Choose…", self._choose)
            m.addAction("None", lambda: (self.set(None), self.changed.emit(None)))
            m.exec(self.mapToGlobal(self.rect().bottomLeft()))
        else:
            self._choose()

    def _choose(self):
        c = QColorDialog.getColor(_qc(self.color) or QColor(255, 0, 0), self)
        if c.isValid():
            self.set([c.redF(), c.greenF(), c.blueF()])
            self.changed.emit(self.color)


class PropertiesPanel(QWidget):
    """Edit the selected markup, or (with nothing selected) the style the
    current tool will draw with."""

    def __init__(self):
        super().__init__()
        self.view = None
        self._loading = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        self.title = QLabel("")
        self.title.setWordWrap(True)
        lay.addWidget(self.title)
        form = QFormLayout()
        self.color = ColorButton()
        self.color.changed.connect(lambda c: self._set("color", c))
        self.fill = ColorButton(allow_none=True)
        self.fill.changed.connect(lambda c: self._set("fill", c))
        self.width = QDoubleSpinBox()
        self.width.setRange(0.5, 20)
        self.width.setSingleStep(0.5)
        self.width.valueChanged.connect(lambda v: self._set("width", v))
        self.opacity = QSlider(Qt.Horizontal)
        self.opacity.setRange(5, 100)
        self.opacity.sliderReleased.connect(
            lambda: self._set("opacity", self.opacity.value() / 100))
        self.subject = QLineEdit()
        self.subject.setPlaceholderText("e.g. Interior Wall, Revision")
        self.subject.editingFinished.connect(
            lambda: self._set("subject", self.subject.text().strip()))
        self.status = QComboBox()
        self.status.addItems([s or "None" for s in annotate.statuses()])
        self.status.activated.connect(
            lambda i: self._set("status", annotate.statuses()[i]))
        self.line_style = QComboBox()
        self.line_style.activated.connect(
            lambda i: self._set("line_style", self.line_style.itemText(i)))
        self.hatch = QComboBox()
        self.hatch.activated.connect(
            lambda i: self._set("hatch", self.hatch.itemText(i)))
        self.layer = QComboBox()
        self.layer.activated.connect(
            lambda i: self._set("layer", self.layer.itemData(i) or ""))
        self.comment = QLineEdit()
        self.comment.editingFinished.connect(
            lambda: self._set("note", self.comment.text()))
        self.author = QLabel("")
        form.addRow("Color", self.color)
        form.addRow("Fill", self.fill)
        form.addRow("Line width", self.width)
        form.addRow("Opacity", self.opacity)
        form.addRow("Line style", self.line_style)
        form.addRow("Hatch", self.hatch)
        form.addRow("Layer", self.layer)
        form.addRow("Subject", self.subject)
        form.addRow("Status", self.status)
        form.addRow("Comment", self.comment)
        form.addRow("Author", self.author)
        self._selection_only = [self.status, self.comment]
        lay.addLayout(form)
        lay.addStretch()

    def set_view(self, view):
        self.view = view
        self.refresh()

    def refresh(self):
        v = self.view
        self._loading = True
        try:
            if v is None:
                self.title.setText("No document open")
                self.setEnabled(False)
                return
            self.setEnabled(True)
            self._fill_lists(v)
            props = v.selected_props()
            if props:
                kind = "Measurement" if props["takeoff"] else props["type"]
                self.title.setText(f"<b>Selected: {kind}</b>")
                self.color.set(props["color"])
                self.fill.set(props["fill"])
                self.width.setValue(props["width"] if props["width"] > 0 else 1)
                self.opacity.setValue(int(props["opacity"] * 100))
                self.subject.setText(props["subject"])
                sts = annotate.statuses()
                self.status.setCurrentIndex(
                    sts.index(props["status"]) if props["status"] in sts
                    else 0)
                self._show_line_style(props.get("dashes"))
                self._show_hatch(props.get("hatch"))
                self._show_layer(props.get("layer", ""))
                self.comment.setText(props["comment"])
                self.author.setText(props["author"])
                for w in self._selection_only:
                    w.setEnabled(True)
            else:
                label = TOOLS.get(v.tool, ("Select", ""))[0]
                self.title.setText(f"<b>Tool: {label}</b><br>"
                                   "<small>New markups use these settings."
                                   "</small>")
                st = v.style
                self.color.set(st.get("color") or v._color(v.tool or ""))
                self.fill.set(st.get("fill"))
                self.width.setValue(st.get("width") or 1.5)
                self.opacity.setValue(int((st.get("opacity") or 1) * 100))
                self.subject.setText(st.get("subject") or "")
                self.line_style.setCurrentText(st.get("line_style") or "Solid")
                self.hatch.setCurrentText(st.get("hatch") or "None")
                self._show_layer(st.get("layer") or "")
                self.comment.setText("")
                self.author.setText("")
                for w in self._selection_only:
                    w.setEnabled(False)
        finally:
            self._loading = False

    def _fill_lists(self, v):
        from . import styles
        for combo, names in ((self.line_style, list(styles.line_styles())),
                             (self.hatch, list(styles.hatches()))):
            have = [combo.itemText(i) for i in range(combo.count())]
            if have != names:
                cur = combo.currentText()
                combo.clear()
                combo.addItems(names)
                combo.setCurrentText(cur)
        try:
            layers = sorted({i.get("name", "") for i in
                             (v.doc.get_ocgs() or {}).values()} - {""})
        except Exception:
            layers = []
        have = [self.layer.itemData(i) for i in range(self.layer.count())]
        if have != [""] + layers:
            self.layer.clear()
            self.layer.addItem("(none)", "")
            for n in layers:
                self.layer.addItem(n, n)

    def _show_line_style(self, dashes):
        from . import styles
        name = "Solid"
        if dashes:
            for n, d in styles.line_styles().items():
                if d and [_c2(x) for x in d] == \
                        [_c2(float(x)) for x in dashes]:
                    name = n
                    break
            else:
                name = "Dashed"
        self.line_style.setCurrentText(name)

    def _show_hatch(self, raw):
        import json
        from . import styles
        name = "None"
        if raw:
            try:
                fams = [tuple(float(x) for x in f) for f in json.loads(raw)]
            except (ValueError, TypeError):
                fams = []
            for n, h in styles.hatches().items():
                if h and [tuple(float(x) for x in f) for f in h] == fams:
                    name = n
                    break
        self.hatch.setCurrentText(name)

    def _show_layer(self, name):
        i = self.layer.findData(name or "")
        self.layer.setCurrentIndex(max(0, i))

    def _set(self, key, value):
        if self._loading or self.view is None:
            return
        v = self.view
        if v.selected and key in ("line_style", "hatch"):
            from . import styles
            if key == "line_style":
                v.change_selected(dashes=styles.line_styles().get(value)
                                  or [])
            else:
                fams = styles.hatches().get(value) or []
                v.change_selected(hatch=[list(f) for f in fams])
            return
        if v.selected:
            v.change_selected(**{key: value})
        else:
            if value in (None, "") and key in ("fill", "subject"):
                v.style.pop(key, None)
            else:
                v.style[key] = value
            if key == "subject" and value and v.tool == "count":
                v.count_group = value


# ---- Tool Chest ------------------------------------------------------------------

class ToolChestPanel(QWidget):
    """Saved tools in sets. Click one to draw with it; it stays on until
    Esc. Sets can be saved as a file and opened on another computer, so a
    whole team draws with the same tools."""

    use = Signal(dict)
    imported = Signal(dict)            # {"statuses", "columns"} from a file

    def __init__(self):
        super().__init__()
        self.chest = toolchest.load()
        self.get_columns = lambda: []   # the open drawing's columns (window)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        top = QHBoxLayout()
        sets = QToolButton()
        sets.setText("Tool Sets")
        sets.setPopupMode(QToolButton.InstantPopup)
        sm = QMenu(sets)
        sm.addAction("New Set…", lambda: self.new_set())
        sm.addAction("Open a Tool Set File…", lambda: self.import_dialog())
        sm.addAction("Save Sets as a File…", lambda: self.export_dialog())
        sm.addSeparator()
        sm.addAction("Restore Default Tools", lambda: self._restore())
        sets.setMenu(sm)
        top.addWidget(sets)
        top.addStretch(1)
        lay.addLayout(top)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemClicked.connect(self._clicked)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.tree)
        hint = QLabel("<small>Click a tool to use it (Esc to stop). To save "
                      "your own, right-click a markup on the page and "
                      "choose <i>Add to Tool Chest</i>. Right-click a tool "
                      "to set its unit cost, columns, wall height or "
                      "rise/drop.</small>")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self.refresh()

    def refresh(self):
        self.tree.clear()
        n = 0                 # keys 1-9 pick the first nine tools (Nov 4)
        for group, items in self.chest.items():
            g = QTreeWidgetItem([group])
            g.setFlags(Qt.ItemIsEnabled)
            g.setData(0, Qt.UserRole + 1, group)
            self.tree.addTopLevelItem(g)
            for i, it in enumerate(items):
                label = TOOLS.get(it.get("tool"), ("?", ""))[0]
                more = []
                if it.get("unit"):
                    more.append(it["unit"])
                if it.get("unit_cost") not in (None, ""):
                    more.append(f"${_c2(float(it['unit_cost'])):,.2f}")
                if it.get("height"):
                    more.append(f"h {it['height']}")
                if it.get("rise"):
                    more.append(f"rise {it['rise']}")
                extra = f" · {', '.join(more)}" if more else ""
                key = ""
                if it.get("tool"):
                    n += 1
                    key = f"{n}  " if n <= 9 else ""
                c = QTreeWidgetItem([f"{key}{it['name']}  ({label}{extra})"])
                if key:
                    c.setToolTip(0, f"Press {n} on the drawing to use it")
                c.setIcon(0, swatch(it.get("color")))
                c.setData(0, Qt.UserRole, (group, i))
                g.addChild(c)
            g.setExpanded(True)

    def _clicked(self, item, _col):
        data = item.data(0, Qt.UserRole)
        if data:
            group, i = data
            self.use.emit(self.chest[group][i])

    def add(self, item, group=None):
        if group is None:
            groups = list(self.chest) or ["My Tools"]
            group, ok = QInputDialog.getItem(self, "Tool Chest", "Set:",
                                             groups + ["My Tools"], 0, True)
            if not ok or not group.strip():
                return False
        toolchest.add(self.chest, group.strip(), item)
        self.refresh()
        return True

    def _menu(self, pos):
        item = self.tree.itemAt(pos)
        data = item.data(0, Qt.UserRole) if item else None
        set_name = item.data(0, Qt.UserRole + 1) if item else None
        m = QMenu(self)
        if data:
            group, i = data
            m.addAction("Edit…", lambda: self.edit_tool(group, i))
            m.addAction("Rename…", lambda: self._rename(group, i))
            m.addAction("Move to Set…", lambda: self.move_tool(group, i))
            m.addAction("Remove", lambda: (toolchest.remove(self.chest,
                                                            group, i),
                                           self.refresh()))
            set_name = group
        if set_name:
            m.addSeparator()
            m.addAction(f"Save '{set_name}' as a File…",
                        lambda g=set_name: self.export_dialog([g]))
            m.addAction(f"Rename Set '{set_name}'…",
                        lambda g=set_name: self.rename_set(g))
        m.addSeparator()
        m.addAction("New Set…", lambda: self.new_set())
        m.addAction("Open a Tool Set File…", lambda: self.import_dialog())
        m.addAction("Restore Default Tools", self._restore)
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def _rename(self, group, i):
        it = self.chest[group][i]
        name, ok = QInputDialog.getText(self, "Rename", "Name:",
                                        text=it["name"])
        if ok and name.strip():
            it["name"] = name.strip()
            toolchest.save(self.chest)
            self.refresh()

    def new_set(self, name=None):
        if name is None:
            name, ok = QInputDialog.getText(self, "New Tool Set",
                                            "Set name:")
            if not ok:
                return False
        name = (name or "").strip()[:60]
        if not name or name in self.chest:
            return False
        self.chest[name] = []
        toolchest.save(self.chest)
        self.refresh()
        return True

    def rename_set(self, group, name=None):
        if name is None:
            name, ok = QInputDialog.getText(self, "Rename Set", "Set name:",
                                            text=group)
            if not ok:
                return False
        name = (name or "").strip()[:60]
        if not name or name in self.chest or group not in self.chest:
            return False
        self.chest = {(name if k == group else k): v
                      for k, v in self.chest.items()}
        toolchest.save(self.chest)
        self.refresh()
        return True

    def move_tool(self, group, i, to=None):
        if to is None:
            others = [g for g in self.chest if g != group]
            to, ok = QInputDialog.getItem(self, "Move to Set", "Set:",
                                          others + ["My Tools"], 0, True)
            if not ok:
                return False
        to = (to or "").strip()
        if not to or to == group:
            return False
        it = self.chest[group][i]
        toolchest.remove(self.chest, group, i)
        toolchest.add(self.chest, to, it)
        self.refresh()
        return True

    def edit_tool(self, group, i, values=None):
        """A tool's name, item, unit and the values its markups carry.
        `values` (tests) skips the dialog."""
        it = self.chest[group][i]
        if values is None:
            dlg = ToolEditDialog(it, self)
            if dlg.exec() != ToolEditDialog.Accepted:
                return False
            values = dlg.values()
        new = toolchest.clean_tool(dict(values, tool=it["tool"],
                                        color=it.get("color"),
                                        fill=it.get("fill"),
                                        width=it.get("width"),
                                        opacity=it.get("opacity")))
        if not new:
            return False
        self.chest[group][i] = new
        toolchest.save(self.chest)
        self.refresh()
        return True

    def export_dialog(self, groups=None, path=None):
        if groups is None:
            names = list(self.chest)
            if not names:
                return None
            groups, ok = _pick_sets(self, names)
            if not ok or not groups:
                return None
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Save Tool Sets", (groups[0] if len(groups) == 1 else
                                         "Tool Sets") + toolchest.FILE_EXT,
                f"QuantiSheet tool sets (*{toolchest.FILE_EXT})")
            if not path:
                return None
            if not path.lower().endswith(toolchest.FILE_EXT):
                path += toolchest.FILE_EXT
        from . import annotate as _an
        statuses = [x for x in _an.statuses() if x and x not in
                    _an.STATUSES]
        return toolchest.export_sets(self.chest, groups, path,
                                     statuses=statuses,
                                     columns=self.get_columns())

    def import_dialog(self, path=None):
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Open a Tool Set File", "",
                f"QuantiSheet tool sets (*{toolchest.FILE_EXT})")
            if not path:
                return None
        return self.import_file(path)

    def import_file(self, path, ask=True):
        """Add the sets in a .qstools file (a set of the same name is
        replaced). Returns the set names, or None."""
        try:
            data = toolchest.read_sets(path, known=set(TOOLS))
        except toolchest.ToolSetError as e:
            QMessageBox.information(self, "Tool Sets", str(e))
            return None
        same = [n for n in data["sets"] if n in self.chest]
        if ask and same and QMessageBox.question(
                self, "Tool Sets", "Replace your set(s) " +
                ", ".join(f"'{n}'" for n in same) + " with the ones in "
                "this file?") != QMessageBox.Yes:
            return None
        names = toolchest.merge(self.chest, data["sets"])
        self.refresh()
        if data.get("statuses") or data.get("columns"):
            self.imported.emit({"statuses": data.get("statuses") or [],
                                "columns": data.get("columns") or []})
        return names

    def _restore(self):
        import copy
        for g, items in toolchest.DEFAULT.items():
            have = {i["name"] for i in self.chest.get(g, [])}
            for it in items:
                if it["name"] not in have:
                    self.chest.setdefault(g, []).append(copy.deepcopy(it))
        toolchest.save(self.chest)
        self.refresh()


def _pick_sets(parent, names):
    """Which sets to save: ([names], ok)."""
    from PySide6.QtWidgets import QDialog, QDialogButtonBox, QListWidget
    dlg = QDialog(parent)
    dlg.setWindowTitle("Save Tool Sets")
    lay = QVBoxLayout(dlg)
    lay.addWidget(QLabel("Sets to put in the file:"))
    lst = QListWidget()
    for n in names:
        from PySide6.QtWidgets import QListWidgetItem
        it = QListWidgetItem(n)
        it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
        it.setCheckState(Qt.Checked)
        lst.addItem(it)
    lay.addWidget(lst)
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    bb.accepted.connect(dlg.accept)
    bb.rejected.connect(dlg.reject)
    lay.addWidget(bb)
    ok = dlg.exec() == QDialog.Accepted
    return [lst.item(i).text() for i in range(lst.count())
            if lst.item(i).checkState() == Qt.Checked], ok


from PySide6.QtWidgets import QDialog as _QDialog  # noqa: E402


class ToolEditDialog(_QDialog):
    """Edit a Tool Chest tool: its name and item, the unit it keeps, and
    what its markups carry (unit cost, column values, rise/drop, wall
    height and openings, volume depth)."""

    UNITS = ["(the sheet's)", "ft", "in", "yd", "m", "cm", "mm"]

    def __init__(self, item, parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QDialogButtonBox, QPlainTextEdit
        self.setWindowTitle(f"Tool: {item.get('name', '')}")
        form = QFormLayout(self)
        self.name = QLineEdit(item.get("name", ""))
        self.subject = QLineEdit(item.get("subject", ""))
        self.subject.setPlaceholderText("What it takes off, e.g. Drywall")
        self.unit = QComboBox()
        self.unit.addItems(self.UNITS)
        if item.get("unit") in self.UNITS:
            self.unit.setCurrentText(item["unit"])
        self.cost = QLineEdit("" if item.get("unit_cost") in (None, "")
                              else f"{float(item['unit_cost']):g}")
        self.cost.setPlaceholderText("e.g. 2.35 (per unit measured)")
        self.rise = QLineEdit(str(item.get("rise", "") or ""))
        self.rise.setPlaceholderText("e.g. 8' (added to each run)")
        self.height = QLineEdit(str(item.get("height", "") or ""))
        self.height.setPlaceholderText("e.g. 9' (makes runs wall areas)")
        self.openings = QLineEdit(str(item.get("openings", "") or ""))
        self.openings.setPlaceholderText("e.g. 3x7 x2")
        self.depth = QLineEdit(str(item.get("depth", "") or ""))
        self.depth.setPlaceholderText("e.g. 4\" (volumes)")
        self.fields = QPlainTextEdit("\n".join(
            f"{k} = {v}" for k, v in (item.get("fields") or {}).items()))
        self.fields.setPlaceholderText("Column = value, one per line\n"
                                       "e.g. Product = Type X 5/8")
        self.fields.setMaximumHeight(90)
        form.addRow("Name:", self.name)
        form.addRow("Takes off:", self.subject)
        form.addRow("Keep quantities in:", self.unit)
        form.addRow("Unit cost ($):", self.cost)
        form.addRow("Rise / drop:", self.rise)
        form.addRow("Wall height:", self.height)
        form.addRow("Openings:", self.openings)
        form.addRow("Volume depth:", self.depth)
        form.addRow("Column values:", self.fields)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def values(self):
        out = {"name": self.name.text().strip(),
               "subject": self.subject.text().strip()}
        if self.unit.currentIndex() > 0:
            out["unit"] = self.unit.currentText()
        try:
            out["unit_cost"] = float(self.cost.text().replace("$", "")
                                     .replace(",", ""))
        except ValueError:
            pass
        for k, w in (("rise", self.rise), ("height", self.height),
                     ("openings", self.openings), ("depth", self.depth)):
            if w.text().strip():
                out[k] = w.text().strip()
        fields = {}
        for line in self.fields.toPlainText().splitlines():
            k, sep, v = line.partition("=")
            if sep and k.strip():
                v = v.strip()
                try:
                    fields[k.strip()] = float(v.replace(",", ""))
                except ValueError:
                    fields[k.strip()] = v
        if fields:
            out["fields"] = fields
        return out


# ---- Estimate -------------------------------------------------------------------

class _LineTable(QTableWidget):
    """The estimate table: Delete / Backspace deletes the selected lines
    here (never the selected markup - the window's Delete shortcut is
    kept out while the table has the keyboard)."""

    delete_pressed = Signal()

    def event(self, e):
        if e.type() == QEvent.ShortcutOverride and \
                e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and \
                self.state() != QAbstractItemView.EditingState:
            e.accept()
            return True
        return super().event(e)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and \
                self.state() != QAbstractItemView.EditingState:
            self.delete_pressed.emit()
            e.accept()
            return
        super().keyPressEvent(e)


class _CostTypeDelegate(QStyledItemDelegate):
    """A drop-down of the cost types for the Cost Type column."""

    def createEditor(self, parent, option, index):
        from . import estimate_lines
        box = QComboBox(parent)
        for t in estimate_lines.COST_TYPES:
            box.addItem(t or "(auto)", t)
        return box

    def setEditorData(self, editor, index):
        i = editor.findText(index.data() or "")
        editor.setCurrentIndex(max(0, i))

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentData() or "")


class EstimatePanel(QWidget):
    """The estimate: takeoff lines (one per measured group, priced with a
    unit cost, waste and multiplier) and added lines (typed in, from a
    cost book or the quick $/SF estimate, optionally linked to a takeoff
    group) with a CSI code, cost type and Mat / Lab / Eqp / Sub split.
    Everything is saved inside the PDF."""

    changed = Signal()
    COLS = ["Code", "Description", "Cost Type", "Type", "Count", "Quantity",
            "Unit", "Waste %", "Multiplier", "Adjusted", "Mat", "Lab", "Eqp",
            "Sub", "Unit Cost", "Total"]
    (C_CODE, C_DESC, C_CTYPE, C_TYPE, C_COUNT, C_QTY, C_UNIT, C_WASTE,
     C_MULT, C_ADJ, C_MAT, C_LAB, C_EQP, C_SUB, C_UC, C_TOTAL) = range(16)
    # takeoff lines: what a cell edits (estimate.set_price)
    EDITABLE = {0: "code", 2: "cost_type", 7: "waste", 8: "multiplier",
                14: "unit_cost"}
    # added lines (estimate_lines.update)
    ADDED_EDIT = {0: "code", 1: "desc", 2: "cost_type", 5: "qty", 6: "unit",
                  10: "mat", 11: "lab", 12: "eqp", 13: "sub",
                  14: "unit_cost"}

    def __init__(self):
        super().__init__()
        self.doc = None
        self.rows = []          # takeoff lines (estimate.lines)
        self.added = []         # added lines, priced (estimate_lines)
        self.kinds = []         # per table row: ("takeoff"|"added", line)
        self._loading = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.table = _LineTable(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        hh.setSectionResizeMode(self.C_DESC, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setItemDelegateForColumn(self.C_CTYPE,
                                            _CostTypeDelegate(self.table))
        self.table.itemChanged.connect(self._edited)
        self.table.delete_pressed.connect(lambda: self.delete_selected())
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.table)
        self.total = QLabel("")
        self.total.setWordWrap(True)
        lay.addWidget(self.total)
        self.msg = QLabel("")
        self.msg.setStyleSheet("color: #b00;")
        self.msg.setWordWrap(True)
        self.msg.hide()
        lay.addWidget(self.msg)
        row = QHBoxLayout()
        self.page_only = QCheckBox("This page only")
        self.page_only.toggled.connect(lambda _: self.refresh())
        row.addWidget(self.page_only)
        row.addStretch()
        add = QPushButton("Add Line")
        add.setToolTip("Add a line with a typed quantity (permit, allowance, "
                       "anything not measured)")
        add.clicked.connect(lambda: self.add_line(edit=True))
        book = QPushButton("Add From Cost Book…")
        book.setToolTip("Tick cost book items by CSI division and add them "
                        "as lines")
        book.clicked.connect(lambda: self.add_from_cost_book())
        self.delete_btn = QPushButton("Delete")
        self.delete_btn.setToolTip("Delete the selected added lines (never "
                                   "a markup)")
        self.delete_btn.clicked.connect(lambda: self.delete_selected())
        more = QToolButton()
        more.setText("More")
        more.setPopupMode(QToolButton.InstantPopup)
        m = QMenu(more)
        m.addAction("Link Selected Line to Takeoff Group…",
                    lambda: self.link_selected())
        m.addAction("Unlink Selected Lines (Keep Quantity)",
                    lambda: self.unlink_selected())
        m.addSeparator()
        m.addAction("Quick $/SF Estimate…", lambda: self.quick_sf())
        m.addAction("Model Estimate…", lambda: self.model_estimate())
        m.addAction("Export My Estimate…", lambda: self.export_my_estimate())
        m.addAction("Estimate Layouts…", lambda: self.estimate_layouts())
        more.setMenu(m)
        export = QPushButton("Export Estimate (CSV)…")
        export.clicked.connect(self._export_dialog)
        for w in (add, book, self.delete_btn, more, export):
            row.addWidget(w)
        lay.addLayout(row)
        tip = QLabel("<small>Double-click a cell to edit: Code, Cost Type, "
                     "Waste %, Multiplier and Unit Cost on takeoff lines; "
                     "every white cell on added lines. Saved inside the "
                     "PDF.</small>")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        self.current_page = 0

    def set_doc(self, doc):
        self.doc = doc
        self.refresh()

    def _say(self, text=""):
        self.msg.setText(text)
        self.msg.setVisible(bool(text))

    # ---- table -------------------------------------------------------------
    def refresh(self):
        if self.doc is None or self.doc.is_closed:
            return
        from . import estimate_lines
        self._loading = True
        try:
            page = self.current_page if self.page_only.isChecked() else None
            self.rows = estimate.lines(self.doc, page)
            self.added = estimate_lines.priced(self.doc, page)
            self.kinds = [("takeoff", g) for g in self.rows] + \
                [("added", p) for p in self.added]
            self.table.setRowCount(len(self.kinds))
            for r, (kind, g) in enumerate(self.kinds):
                if kind == "takeoff":
                    self._takeoff_row(r, g)
                else:
                    self._added_row(r, g)
            if len(self.kinds) < 400:
                for c in range(len(self.COLS)):
                    if c != self.C_DESC:
                        self.table.resizeColumnToContents(c)
            self._totals()
        finally:
            self._loading = False

    def _cell(self, r, col, text, editable, right=False, tip=""):
        it = QTableWidgetItem(text)
        if right:
            it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        if not editable:
            it.setFlags(it.flags() & ~Qt.ItemIsEditable)
        if tip:
            it.setToolTip(tip)
        self.table.setItem(r, col, it)
        return it

    def _takeoff_row(self, r, g):
        vals = {self.C_CODE: g.get("code", ""), self.C_DESC: g["name"],
                self.C_CTYPE: g.get("cost_type", ""),
                self.C_TYPE: g["type"].title(), self.C_COUNT: str(g["count"]),
                self.C_QTY: f"{_c2(g['quantity']):,.2f}", self.C_UNIT: g["unit"],
                self.C_WASTE: f"{g['waste']:g}",
                self.C_MULT: f"{g['multiplier']:g}",
                self.C_ADJ: f"{_c2(g['adjusted']):,.2f}", self.C_MAT: "",
                self.C_LAB: "", self.C_EQP: "", self.C_SUB: "",
                # as typed, up to 4 places - 4.125 isn't shown as 4.13
                # (hands-on pass, Nov 10), like the lines added below
                self.C_UC: _dec(repr(round(float(g['unit_cost'] or 0), 4))),
                self.C_TOTAL: f"{_c2(g['total']):,.2f}"}
        for col, text in vals.items():
            self._cell(r, col, text, col in self.EDITABLE,
                       right=col >= self.C_COUNT and col != self.C_UNIT,
                       tip=f"Pages {g['pages']}" if col == self.C_DESC and
                       g.get("pages") else "")

    def _added_row(self, r, p):
        up, link = p["unit_price"], p.get("link")
        qty_tip = ""
        if link:
            qty_tip = (f"Linked to takeoff group '{link['name']}' "
                       f"({link['type']}, {link['unit']}) - the quantity "
                       "follows its markups")
        typ = "Linked" if link else "Added"
        vals = {self.C_CODE: p["code"], self.C_DESC: p["desc"],
                self.C_CTYPE: p["cost_type"] or p["kind"],
                self.C_TYPE: typ,
                self.C_COUNT: str(p["count"]) if p.get("count") else "",
                # a typed quantity as typed (it is priced exactly);
                # a measured one to the 2 places it is priced at
                self.C_QTY: (f"{_c2(p['quantity']):,.2f}" if link
                             else _dec(p["quantity"])),
                self.C_UNIT: p["unit"] or p["unit_label"], self.C_WASTE: "",
                self.C_MULT: "", self.C_ADJ: "",
                self.C_MAT: _dec(up["mat"]), self.C_LAB: _dec(up["lab"]),
                self.C_EQP: _dec(up["eqp"]), self.C_SUB: _dec(up["sub"]),
                self.C_UC: _dec(p["unit_cost"]),
                self.C_TOTAL: f"{_c2(p['total']):,.2f}"}
        for col, text in vals.items():
            editable = col in self.ADDED_EDIT and not (
                col == self.C_QTY and link)
            tip = ""
            if col == self.C_QTY and link:
                tip = qty_tip
            elif col == self.C_TYPE:
                tip = qty_tip or "Added line (quantity typed in)"
                if p.get("problem"):
                    tip += "\n" + p["problem"]
            elif col == self.C_DESC and p.get("source"):
                tip = f"From {p['source']}"
                if p.get("note"):
                    tip += f"\n{p['note']}"
            elif col == self.C_TOTAL:
                e = p["ext"]
                tip = (f"Mat ${_c2(e['mat']):,.2f} + Lab ${_c2(e['lab']):,.2f} + Eqp "
                       f"${_c2(e['eqp']):,.2f} + Sub ${_c2(e['sub']):,.2f}")
            it = self._cell(r, col, text, editable,
                            right=col >= self.C_COUNT and col != self.C_UNIT,
                            tip=tip)
            if col == self.C_TYPE and p.get("problem"):
                it.setForeground(QColor(176, 0, 0))

    def _totals(self):
        from . import estimate_export, estimate_lines
        from .dmoney import cents, fmt
        take = sum((cents(g["total"]) for g in self.rows), cents(0))
        added = estimate_lines.total(self.added)
        grand = take + added
        types = estimate_lines.by_type(self.added)
        for g in self.rows:
            k = estimate_export._type_of(g.get("cost_type"))
            types[k] = types.get(k, cents(0)) + cents(g["total"])
        loc = []
        if self.kinds:
            try:
                loc = estimate_lines.location_lines(
                    grand, types.get("Material", 0), types.get("Labor", 0),
                    types.get("Equipment", 0),
                    estimate_lines.job_region(self.doc))
            except Exception:                             # noqa: BLE001
                log.warning("location adjustment left off", exc_info=True)
        self.grand_total = loc[-1][1] if loc else grand
        if not self.kinds:
            self.total.setText("No lines yet. Use the Takeoff tools or the "
                               "Tool Chest, Add Line, or Add From Cost Book.")
            return
        split = (f" &nbsp; <small>(takeoff {fmt(take)} + added lines "
                 f"{fmt(added)})</small>" if self.rows and self.added
                 else "")
        if loc:
            self.total.setText(
                f"<b>{loc[0][0]}: {fmt(loc[0][1])}</b>{split}<br>"
                f"{loc[1][0]}: {fmt(loc[1][1])}<br>"
                f"<b>{loc[2][0]}: {fmt(loc[2][1])}</b>")
        else:
            self.total.setText(f"<b>Estimate total: {fmt(grand)}</b>{split}")
        from . import rounding          # Venice #16: shown with every job
        self.total.setText(self.total.text() +
                           f"<br><small>{rounding.SHORT}</small>")
        self.total.setToolTip(rounding.POLICY)

    # ---- editing -----------------------------------------------------------
    def _edited(self, item):
        if self._loading or self.doc is None:
            return
        from . import estimate_lines
        r, col = item.row(), item.column()
        if r >= len(self.kinds):
            return
        kind, g = self.kinds[r]
        text = item.text()
        try:
            if kind == "takeoff":
                key = self.EDITABLE.get(col)
                if key is None:
                    return
                if key == "cost_type":
                    value = estimate_lines.cost_type(text)
                elif key == "code":
                    value = text
                else:
                    try:
                        value = float(text.replace(",", "").replace("$", ""))
                    except ValueError:
                        self._say(f"Can't read {text!r} as a number.")
                        self.refresh()
                        return
                self._say()
                self.set_price(g["name"], g["type"], g["unit"],
                               **{key: value})
                return
            key = self.ADDED_EDIT.get(col)
            if key is None:
                return
            if key == "unit_cost":
                estimate_lines.set_unit_cost(self.doc, g["id"], text)
            else:
                estimate_lines.update(self.doc, g["id"], **{key: text})
        except estimate_lines.LineError as e:
            self._say(str(e))
            self.refresh()
            return
        self._say()
        self.changed.emit()
        self.refresh()

    def set_price(self, name, mtype, unit, **values):
        estimate.set_price(self.doc, name, mtype, unit, **values)
        self.changed.emit()
        self.refresh()

    def _row_of(self, line_id):
        for r, (kind, g) in enumerate(self.kinds):
            if kind == "added" and g["id"] == line_id:
                return r
        return -1

    def add_line(self, edit=False, **values):
        """Add a typed-quantity line (desc, qty, unit, code, cost_type,
        mat, lab, eqp, sub...); returns its id."""
        from . import estimate_lines
        if self.doc is None:
            return None
        values.setdefault("desc", "New line")
        try:
            ids = estimate_lines.add(self.doc,
                                     [estimate_lines.new_line(**values)])
        except estimate_lines.LineError as e:
            self._say(str(e))
            return None
        self._say()
        self.changed.emit()
        self.refresh()
        r = self._row_of(ids[0])
        if r >= 0:
            self.table.selectRow(r)
            if edit:
                self.table.setCurrentCell(r, self.C_DESC)
                self.table.editItem(self.table.item(r, self.C_DESC))
        return ids[0]

    def selected_added(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self.kinds[r][1] for r in rows if r < len(self.kinds) and
                self.kinds[r][0] == "added"]

    def select_lines(self, ids):
        from PySide6.QtCore import QItemSelectionModel
        sm = self.table.selectionModel()
        sm.clearSelection()
        for i in ids:
            r = self._row_of(i)
            if r >= 0:
                sm.select(self.table.model().index(r, 0),
                          QItemSelectionModel.Select |
                          QItemSelectionModel.Rows)

    def delete_selected(self, confirm=True):
        """Delete the selected added lines after 'Delete N line(s)?'.
        Takeoff lines come from markups and are never deleted here."""
        from . import estimate_lines
        if self.doc is None:
            return 0
        rows = {i.row() for i in self.table.selectedIndexes()}
        lines = self.selected_added()
        if not lines:
            if rows:
                self._say("Takeoff lines come from the markups; delete or "
                          "regroup the markups to remove them.")
            return 0
        if confirm:
            ans = QMessageBox.question(
                self, "Delete Lines", f"Delete {len(lines)} line(s)?",
                QMessageBox.Ok | QMessageBox.Cancel, QMessageBox.Cancel)
            if ans not in (QMessageBox.Ok, QMessageBox.Yes):
                return 0
        n = estimate_lines.delete(self.doc, [g["id"] for g in lines])
        if n:
            self._say("Takeoff lines were kept (they come from the markups)."
                      if len(rows) > len(lines) else "")
            self.changed.emit()
            self.refresh()
        return n

    def link_selected(self, group=None):
        """Link the selected added line(s) to a takeoff group (picked by
        name, or asked for)."""
        from . import estimate_lines, estimate_ui
        lines = self.selected_added()
        if self.doc is None or not lines:
            self._say("Select an added line first.")
            return False
        groups = estimate_ui.takeoff_groups(self.doc)
        if not groups:
            self._say("There are no takeoff groups to link to yet.")
            return False
        if group is None:
            label, ok = QInputDialog.getItem(
                self, "Link to Takeoff Group", "Quantity from:",
                [lb for lb, _ in groups], 0, False)
            if not ok:
                return False
            link = dict(groups)[label] if label in dict(groups) else None
        else:
            link = next((lk for _lb, lk in groups if lk["name"] == group),
                        None)
        if link is None:
            self._say(f"No takeoff group {group!r}.")
            return False
        for g in lines:
            unit = g["unit"] or link["unit"]
            why = estimate_lines.link_problem(link, unit)
            if why:
                self._say("Can't link: " + why)
                return False
        for g in lines:
            estimate_lines.update(self.doc, g["id"], link=link,
                                  unit=g["unit"] or link["unit"])
        self._say()
        self.changed.emit()
        self.refresh()
        return True

    def unlink_selected(self):
        from . import estimate_lines
        lines = [g for g in self.selected_added() if g.get("link")]
        if self.doc is None or not lines:
            return False
        for g in lines:
            estimate_lines.update(self.doc, g["id"], link=None,
                                  qty=g["quantity"])
        self.changed.emit()
        self.refresh()
        return True

    def _menu(self, pos):
        m = QMenu(self)
        m.addAction("Add Line", lambda: self.add_line(edit=True))
        m.addAction("Add From Cost Book…", lambda: self.add_from_cost_book())
        if self.selected_added():
            m.addSeparator()
            m.addAction("Link to Takeoff Group…", lambda: self.link_selected())
            if any(g.get("link") for g in self.selected_added()):
                m.addAction("Unlink (Keep Quantity)",
                            lambda: self.unlink_selected())
            m.addAction("Price Still Good (Today)",
                        lambda: self.confirm_prices())
            m.addAction("Delete Selected Lines…",
                        lambda: self.delete_selected())
        m.exec(self.table.viewport().mapToGlobal(pos))

    def confirm_prices(self):
        """Nov 3 (stale price warning): the selected lines' prices were
        checked today - the age count starts again."""
        from . import estimate_lines
        lines = self.selected_added()
        if self.doc is None or not lines:
            return 0
        for g in lines:
            estimate_lines.update(self.doc, g["id"],
                                  priced_on=estimate_lines.today())
        self._say(f"{len(lines)} price(s) marked checked today.")
        self.changed.emit()
        self.refresh()
        return len(lines)

    # ---- dialogs -----------------------------------------------------------
    def add_from_cost_book(self, show=True, book=None):
        from .estimate_ui import CostBookPicker
        dlg = CostBookPicker(self.doc, self.window(), book=book)
        if show:
            dlg.exec()
            self.picked(dlg)
        return dlg

    def picked(self, dlg):
        """After a dialog added lines: save the step and show them."""
        if getattr(dlg, "added_ids", None):
            self.changed.emit()
            self.refresh()
            self.select_lines(dlg.added_ids)

    def quick_sf(self, show=True):
        from .estimate_ui import QuickSFDialog
        dlg = QuickSFDialog(self.doc, self.window())
        if show:
            dlg.exec()
            self.picked(dlg)
        return dlg

    def export_my_estimate(self, show=True, layout=None):
        from .estimate_ui import ExportEstimateDialog
        dlg = ExportEstimateDialog(self.doc, self.window(), layout=layout)
        if show:
            before = self._layouts_raw()
            dlg.exec()
            if self._layouts_raw() != before:
                self.changed.emit()        # layouts / tags saved in the PDF
        return dlg

    def model_estimate(self, show=True):
        """Model Estimate: a building priced from its type, SF and options,
        from your job history and from a Generate Set plan's quantities."""
        from .estimate_ui import ModelEstimateDialog
        dlg = ModelEstimateDialog(self.doc, self.window())
        if show:
            dlg.exec()
            self.picked(dlg)
        return dlg

    def estimate_layouts(self, show=True):
        """Your saved estimate layouts; Use This Layout opens Export My
        Estimate in it."""
        from .estimate_ui import LayoutsDialog
        dlg = LayoutsDialog(self.doc, self.window())
        if show:
            before = self._layouts_raw()
            dlg.exec()
            if self._layouts_raw() != before:
                self.changed.emit()
            if dlg.picked:
                self.export_my_estimate(layout=dlg.picked)
        return dlg

    def _layouts_raw(self):
        """The PDF's saved layouts and tags (bytes), to tell whether a
        dialog changed them."""
        from . import embfiles, estimate_layouts
        if self.doc is None:
            return b""
        try:
            if estimate_layouts.FILE not in embfiles.names(self.doc):
                return b""
            return embfiles.get(self.doc, estimate_layouts.FILE)
        except Exception:                                 # noqa: BLE001
            return b""

    def _export_dialog(self):
        if self.doc is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Estimate",
            _report_name("Estimate", self.doc, ".csv"), "CSV (*.csv)")
        if path:
            page = self.current_page if self.page_only.isChecked() else None
            estimate.export_csv(self.doc, path, page)


def _dec(v):
    """A unit price: cents, or up to 4 places when it has them."""
    from decimal import Decimal
    d = Decimal(v)
    if d == d.quantize(Decimal("0.01")):
        return f"{_c2(d):,.2f}"
    return f"{d.normalize():,f}"


# ---- Documents (project folder) -----------------------------------------------------

_PAGE_COUNTS = {}      # (path, mtime, size) -> page count text


_CLOUD_ONLY = 0x400000 | 0x40000 | 0x1000   # RECALL_ON_DATA_ACCESS,
#                                            RECALL_ON_OPEN, OFFLINE


def _cloud_only(st, path=None):
    """A OneDrive (Files On-Demand) or network-offline file: opening it
    would download it, so its pages aren't counted (Grok F16)."""
    return bool(getattr(st, "st_file_attributes", 0) & _CLOUD_ONLY)


def _page_count_uncached(path):
    import fitz
    try:
        with fitz.open(path) as d:
            return str(d.page_count)
    except Exception:
        return "?"


def page_count(path, st=None):
    """Page count of a PDF, opened only when the file is new or changed."""
    try:
        st = st or os.stat(path)
    except OSError:
        return "?"
    if _cloud_only(st, path):
        return "—"
    key = (os.path.abspath(path), st.st_mtime_ns, st.st_size)
    got = _PAGE_COUNTS.get(key)
    if got is None:
        got = _PAGE_COUNTS[key] = _page_count_uncached(path)
        if len(_PAGE_COUNTS) > 5000:
            _PAGE_COUNTS.clear()
            _PAGE_COUNTS[key] = got
    return got


def cached_page_count(path, st=None):
    """The page count if it's known without opening the file, else None.
    `st`: the file's stat when the caller has it (one call per file)."""
    try:
        st = st or os.stat(path)
    except OSError:
        return "?"
    if _cloud_only(st, path):
        return "—"
    return _PAGE_COUNTS.get((os.path.abspath(path), st.st_mtime_ns,
                             st.st_size))


def _stat(entry):
    """A folder entry's stat (free on Windows: it came with the listing)."""
    return entry.stat()


class DocumentsPanel(QWidget):
    """PDFs in a project folder. Double-click to open in a new tab.

    The folder is only read when the panel is first shown (it starts behind
    other tabs), and page counts are filled in a few files at a time, so a
    big project folder never holds up start-up or freezes the window."""

    MAX_DEPTH = 8              # folder levels listed below the project folder
    COUNT_BATCH = 1            # files opened per tick while counting pages
    COUNT_GAP_MS = 15          # pause between ticks, so the window stays live

    open_file = Signal(str)

    def __init__(self, folder=None):
        super().__init__()
        self.folder = folder
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        top = QHBoxLayout()
        self.label = QLabel("")
        self.label.setWordWrap(True)
        choose = QPushButton("Choose Folder…")
        choose.clicked.connect(self._choose)
        refresh = QToolButton()
        refresh.setText("⟳")
        refresh.setToolTip("Refresh")
        refresh.clicked.connect(self.refresh)
        top.addWidget(choose)
        top.addWidget(refresh)
        top.addStretch()
        lay.addLayout(top)
        lay.addWidget(self.label)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Filter drawings")
        # typing filters after a short pause, not on every keystroke
        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(250)
        self._filter_timer.timeout.connect(lambda: self.refresh())
        self.filter.textChanged.connect(lambda *_: self._filter_timer.start())
        lay.addWidget(self.filter)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Name", "Pages", "Modified"])
        h = self.tree.header()
        # the name gets the room; pages and date only what they need (the
        # name was squeezed to "3241..." in a normal-width panel)
        h.setStretchLastSection(False)
        h.setSectionResizeMode(0, QHeaderView.Stretch)
        h.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tree.setIndentation(12)
        self.tree.setTextElideMode(Qt.ElideMiddle)   # keep sheet numbers
        self.tree.itemDoubleClicked.connect(self._open)
        lay.addWidget(self.tree)
        self._pending = []                     # items still showing "…"
        self._count_timer = QTimer(self)
        self._count_timer.setInterval(self.COUNT_GAP_MS)
        self._count_timer.timeout.connect(self._count_some)
        self._stale = True                     # read the folder when shown

    def showEvent(self, e):
        super().showEvent(e)
        if self._stale:
            QTimer.singleShot(0, self.refresh)

    COUNT_IN_FLIGHT = 4        # files the drawing process counts at once

    def _drawer(self):
        from . import render_worker
        if not render_worker.ENABLED:
            return None
        w = render_worker.get()
        return w if w.start() else None

    def _count_some(self):
        drawer = self._drawer()
        if drawer is not None:
            return self._count_in_process(drawer)
        for _ in range(self.COUNT_BATCH):
            if not self._pending:
                self._count_timer.stop()
                return
            it = self._pending.pop(0)
            try:
                it.setText(1, page_count(it.data(0, Qt.UserRole)))
            except RuntimeError:          # the tree was cleared meanwhile
                pass

    def _count_in_process(self, drawer):
        """Big files are opened by the drawing process, not the window."""
        flying = getattr(self, "_flying", None)
        if flying is None:
            flying = self._flying = {}
        while self._pending and len(flying) < self.COUNT_IN_FLIGHT:
            it = self._pending.pop(0)
            try:
                path = it.data(0, Qt.UserRole)
            except RuntimeError:
                continue
            try:
                st = os.stat(path)
            except OSError:
                self._set_count(it, "?")
                continue
            known = cached_page_count(path, st)
            if known is not None:
                self._set_count(it, known)
                continue
            key = (os.path.abspath(path), st.st_mtime_ns, st.st_size)
            rid = drawer.count(path, lambda m, it=it, key=key:
                               self._counted(m, it, key))
            if rid is None:               # gone: count here, as before
                self._set_count(it, page_count(path, st))
                continue
            flying[rid] = it
        if not self._pending and not flying:
            self._count_timer.stop()

    def _counted(self, msg, it, key):
        flying = getattr(self, "_flying", {})
        if msg is not None:
            flying.pop(msg[1], None)
        else:
            for k in [k for k, v in flying.items() if v is it]:
                flying.pop(k, None)
        if msg is None or msg[0] != "count":
            try:
                n = page_count(key[0])
            except Exception:
                n = "?"
        else:
            n = msg[2]
            if n != "?":
                _PAGE_COUNTS[key] = n
        self._set_count(it, n)
        if self._pending and not self._count_timer.isActive():
            self._count_timer.start()

    def _drop_flying(self):
        flying = getattr(self, "_flying", None)
        if not flying:
            return
        try:
            from . import render_worker
            w = render_worker._worker
            for rid in list(flying):
                if w is not None:
                    w.forget(rid)
        except Exception:
            pass
        flying.clear()

    @staticmethod
    def _set_count(it, n):
        try:
            it.setText(1, n)
        except RuntimeError:              # the tree was cleared meanwhile
            pass

    def _choose(self):
        d = QFileDialog.getExistingDirectory(self, "Project Folder",
                                             self.folder or "")
        if d:
            self.set_folder(d)

    def set_folder(self, d):
        from . import settings
        self.folder = d
        settings.set("project_folder", d)
        self.refresh()

    def _collapsed(self):
        out = set()

        def walk(item, path):
            for i in range(item.childCount()):
                c = item.child(i)
                if c.data(0, Qt.UserRole):          # a file, not a folder
                    continue
                p = path + (c.text(0),)
                if not c.isExpanded():
                    out.add(p)
                walk(c, p)
        walk(self.tree.invisibleRootItem(), ())
        return out

    def _restore_collapsed(self, closed):
        def walk(item, path):
            for i in range(item.childCount()):
                c = item.child(i)
                if c.data(0, Qt.UserRole):
                    continue
                p = path + (c.text(0),)
                if p in closed:
                    c.setExpanded(False)
                walk(c, p)
        walk(self.tree.invisibleRootItem(), ())

    def refresh(self, *_):
        import time
        closed = self._collapsed() if self.tree.topLevelItemCount() else set()
        self._pending = []
        self._drop_flying()        # counts of the old listing (review N2)
        self._count_timer.stop()
        self.tree.clear()
        if not self.folder:
            self.label.setText("<small>No project folder chosen.</small>")
            self._stale = False
            return
        if not os.path.isdir(self.folder):     # share offline, drive gone
            self.label.setText(
                f"<small>Can't reach {self.folder} right now - it's read "
                "again next time this panel opens (or click ⟳).</small>")
            self._stale = True
            return
        text = self.filter.text().strip().lower()
        nodes = {"": self.tree.invisibleRootItem()}
        self._skipped = {"deep": 0, "unreadable": 0}
        ok = False
        self.tree.setUpdatesEnabled(False)       # one repaint, not one a row
        try:
            self._fill_tree(text, nodes, time)
            self._restore_collapsed(closed)
            ok = True
        except OSError:
            log.warning("project folder not readable: %s", self.folder,
                        exc_info=True)
        finally:
            self.tree.setUpdatesEnabled(True)
            if self._pending:
                self._count_timer.start()
        notes = [self.folder]
        if not ok:
            notes.append("couldn't be read - it's read again next time "
                         "this panel opens")
        if self._skipped["unreadable"]:
            notes.append(f"{self._skipped['unreadable']} folder(s) couldn't "
                         "be read")
        if self._skipped["deep"]:
            notes.append(f"folders more than {self.MAX_DEPTH} levels down "
                         "aren't listed")
        self.label.setText("<small>" + " · ".join(notes) + "</small>")
        # read it all: done; anything unreadable is tried again when shown
        self._stale = not ok or bool(self._skipped["unreadable"])

    def _fill_tree(self, text, nodes, time):
        self._walk(self.folder, nodes[""], 0, text, time)
        self._prune_empty(nodes[""])
        self.tree.expandAll()

    def _prune_empty(self, node):
        """Drop folders with no PDFs anywhere below them (they were empty
        rows with arrows). Returns whether `node` has any PDF."""
        has = False
        for i in reversed(range(node.childCount())):
            c = node.child(i)
            if c.data(0, Qt.UserRole):            # a file
                has = True
            elif self._prune_empty(c):
                has = True
            else:
                node.removeChild(c)
        return has

    def _walk(self, folder, node, depth, text, time):
        """One folder: its PDFs, then its subfolders (os.scandir: one stat
        per file, which comes free with the listing on Windows)."""
        try:
            with os.scandir(folder) as it:
                entries = sorted(it, key=lambda e: e.name.lower())
        except OSError:
            if depth == 0:
                raise
            self._skipped["unreadable"] += 1
            return
        dirs = []
        for e in entries:
            try:
                is_dir = e.is_dir(follow_symlinks=False)
            except OSError:
                continue
            name = e.name
            if is_dir:
                if not name.startswith(".") and not name.endswith(".versions"):
                    dirs.append(e)
                continue
            if not name.lower().endswith(".pdf") or (
                    text and text not in name.lower()):
                continue
            try:                      # gone or offline since the listing
                st = _stat(e)
            except OSError:
                continue
            mod = time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))
            pages = cached_page_count(e.path, st)
            item = QTreeWidgetItem([name, pages or "…", mod])
            item.setData(0, Qt.UserRole, e.path)
            node.addChild(item)
            if pages is None:
                self._pending.append(item)
        for d in dirs:
            if depth + 1 > self.MAX_DEPTH:
                self._skipped["deep"] += 1
                continue
            child = QTreeWidgetItem([d.name, "", ""])
            node.addChild(child)
            self._walk(d.path, child, depth + 1, text, time)

    def finish_counting(self):
        """Count every page now, here (tests and anything that needs them
        all); replies still on their way from the drawing process are
        counted here too and ignored when they arrive."""
        flying = getattr(self, "_flying", {})
        rest = list(flying.values()) + list(self._pending)
        flying.clear()
        self._pending = []
        for it in rest:
            try:
                it.setText(1, page_count(it.data(0, Qt.UserRole)))
            except RuntimeError:
                pass
        self._count_timer.stop()

    def _open(self, item, _col):
        path = item.data(0, Qt.UserRole)
        if path:
            self.open_file.emit(path)


# ---- Bookmarks -------------------------------------------------------------------

class BookmarksPanel(QWidget):
    """The document's bookmarks (outline). Click to jump."""

    go_page = Signal(int)
    go_spot = Signal(int, float)        # page, height on the page
    edited = Signal()

    def __init__(self):
        super().__init__()
        self.doc = None
        self.current_page = 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemClicked.connect(self._clicked)
        lay.addWidget(self.tree)
        row = QHBoxLayout()
        add = QPushButton("Add")
        add.setToolTip("Bookmark the current page")
        add.clicked.connect(self._add)
        rename = QPushButton("Rename")
        rename.clicked.connect(self._rename)
        remove = QPushButton("Remove")
        remove.clicked.connect(self._remove)
        for b in (add, rename, remove):
            row.addWidget(b)
        lay.addLayout(row)

    def set_doc(self, doc):
        self.doc = doc
        self.refresh()

    def refresh(self):
        self.tree.clear()
        if self.doc is None or self.doc.is_closed:
            return
        toc = self.doc.get_toc(simple=False)
        targets = bookmark_targets(toc)
        self.tree.setUpdatesEnabled(False)
        stack = [(0, self.tree.invisibleRootItem())]
        for i, (level, title, _page, *_rest) in enumerate(toc):
            page, y = targets[i]
            while stack and stack[-1][0] >= level:
                stack.pop()
            parent = stack[-1][1] if stack else self.tree.invisibleRootItem()
            it = QTreeWidgetItem([f"{title}"])
            it.setToolTip(0, f"Page {page}")
            it.setData(0, Qt.UserRole, (i, page, y))
            parent.addChild(it)
            stack.append((level, it))
        # spec books can have tens of thousands of bookmarks: open only
        # the top level of big outlines
        if len(toc) <= 300:
            self.tree.expandAll()
        else:
            self.tree.expandToDepth(0)
        self.tree.setUpdatesEnabled(True)

    def _clicked(self, item, _col):
        data = item.data(0, Qt.UserRole)
        if data and data[1] > 0:
            if len(data) > 2 and data[2] is not None:
                self.go_spot.emit(data[1] - 1, float(data[2]))
            else:
                self.go_page.emit(data[1] - 1)

    def add_bookmark(self, title, page):
        toc = self.doc.get_toc()
        toc.append([1, title, page + 1])
        toc.sort(key=lambda e: (e[2] if e[0] == 1 else 0))
        self.doc.set_toc(_fix_levels(toc))
        self.refresh()
        self.edited.emit()

    def _add(self):
        if self.doc is None:
            return
        title, ok = QInputDialog.getText(self, "Add Bookmark", "Title:",
                                         text=f"Page {self.current_page + 1}")
        if ok and title.strip():
            self.add_bookmark(title.strip(), self.current_page)

    def _selected_index(self):
        it = self.tree.currentItem()
        data = it.data(0, Qt.UserRole) if it else None
        return data[0] if data else None

    def _rename(self):
        i = self._selected_index()
        if i is None:
            return
        toc = self.doc.get_toc()
        title, ok = QInputDialog.getText(self, "Rename Bookmark", "Title:",
                                         text=toc[i][1])
        if ok and title.strip():
            toc[i][1] = title.strip()
            self.doc.set_toc(toc)
            self.refresh()
            self.edited.emit()

    def _remove(self):
        i = self._selected_index()
        if i is None:
            return
        toc = self.doc.get_toc()
        level = toc[i][0]
        j = i + 1
        while j < len(toc) and toc[j][0] > level:     # children go too
            j += 1
        del toc[i:j]
        self.doc.set_toc(_fix_levels(toc))
        self.refresh()
        self.edited.emit()


def bookmark_targets(toc):
    """(page, y) to jump to for each entry of get_toc(simple=False).

    Combined spec books often have one bookmark per original file whose
    destination is empty, so it points at page 1 (or nowhere). Those jump
    to their first child instead."""
    out = [None] * len(toc)
    for i in range(len(toc) - 1, -1, -1):
        level, _title, page = toc[i][:3]
        dest = toc[i][3] if len(toc[i]) > 3 and isinstance(toc[i][3], dict) \
            else {}
        to = dest.get("to")
        y = to.y if to is not None and dest.get("kind") == 1 else None
        empty = page <= 0 or (page == 1 and (to is None or
                                             (to.x == 0 and to.y <= 1)))
        if empty and 0 < i < len(toc) - 1 and toc[i + 1][0] > level \
                and out[i + 1][0] > 1:
            page, y = out[i + 1]
        out[i] = (page, y)
    return out


def _fix_levels(toc):
    """set_toc() rejects a level that jumps by more than one."""
    prev = 0
    out = []
    for e in toc:
        lvl = min(e[0], prev + 1) if out else 1
        out.append([lvl] + list(e[1:]))
        prev = lvl
    return out
