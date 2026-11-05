"""Dialogs for line styles, hatch patterns, layers, and Markups List
columns and statuses."""
import fitz
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView,
    QInputDialog, QLabel, QListWidget, QListWidgetItem, QMessageBox,
    QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from . import annotate, columns, styles


class _NamedList(QDialog):
    """A list of built-in and custom entries with Add and Remove."""

    def __init__(self, title, intro, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(460, 380)
        lay = QVBoxLayout(self)
        lab = QLabel(intro)
        lab.setWordWrap(True)
        lay.addWidget(lab)
        self.list = QListWidget()
        lay.addWidget(self.list)
        row = QHBoxLayout()
        add = QPushButton("Add…")
        add.clicked.connect(self.add)
        rem = QPushButton("Remove")
        rem.clicked.connect(self.remove)
        row.addWidget(add)
        row.addWidget(rem)
        row.addStretch()
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.fill()

    def selected_name(self):
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it else None


class LineStylesDialog(_NamedList):
    def __init__(self, parent=None):
        super().__init__(
            "Line Styles",
            "Dash patterns for lines and shape outlines, in points: dash, "
            "gap, dash, gap... Pick one in the Properties panel.", parent)

    def fill(self):
        from . import settings
        self.list.clear()
        custom = set(settings.get("line_styles") or {})
        for name, d in styles.line_styles().items():
            text = f"{name}   ({' '.join(f'{x:g}' for x in d) if d else 'solid'})"
            if name in custom:
                text += "   - yours"
            it = QListWidgetItem(text)
            it.setData(Qt.UserRole, name)
            self.list.addItem(it)

    def add(self):
        name, ok = QInputDialog.getText(self, "New Line Style", "Name:")
        if not ok or not name.strip():
            return
        pat, ok = QInputDialog.getText(
            self, "New Line Style", "Dash pattern in points (e.g. 8 3 2 3):",
            text="8 3 2 3")
        if not ok:
            return
        d = styles.parse_dashes(pat)
        if not d:
            QMessageBox.information(self, "Line Styles",
                                    "Type numbers like 8 3 2 3.")
            return
        styles.save_line_style(name.strip(), d)
        self.fill()

    def remove(self):
        name = self.selected_name()
        if name in styles.LINE_STYLES:
            QMessageBox.information(self, "Line Styles",
                                    "Built-in styles can't be removed.")
            return
        if name:
            styles.delete_line_style(name)
            self.fill()


class HatchDialog(_NamedList):
    def __init__(self, parent=None):
        super().__init__(
            "Hatch Patterns",
            "Hatches fill rectangles, ellipses, clouds and areas with lines. "
            "Each pattern is one or more angle/spacing pairs (degrees / "
            "points). Pick one in the Properties panel.", parent)

    def fill(self):
        from . import settings
        self.list.clear()
        custom = set(settings.get("hatches") or {})
        for name, h in styles.hatches().items():
            desc = ", ".join(f"{a:g}°/{s:g}" for a, s in h) if h else "none"
            text = f"{name}   ({desc})" + ("   - yours" if name in custom
                                           else "")
            it = QListWidgetItem(text)
            it.setData(Qt.UserRole, name)
            self.list.addItem(it)

    def add(self):
        name, ok = QInputDialog.getText(self, "New Hatch", "Name:")
        if not ok or not name.strip():
            return
        pat, ok = QInputDialog.getText(
            self, "New Hatch", "Angle/spacing pairs, e.g. 45/8, 135/8:",
            text="45/8, 135/8")
        if not ok:
            return
        fams = styles.parse_hatch(pat)
        if not fams:
            QMessageBox.information(self, "Hatch Patterns",
                                    "Type pairs like 45/8, 135/8.")
            return
        styles.save_hatch(name.strip(), fams)
        self.fill()

    def remove(self):
        name = self.selected_name()
        if name in styles.HATCHES:
            QMessageBox.information(self, "Hatch Patterns",
                                    "Built-in patterns can't be removed.")
            return
        if name:
            styles.delete_hatch(name)
            self.fill()


class LayersDialog(QDialog):
    """Show/hide layers, add one, pick the layer new markups go on, and
    move the selected markup to a layer."""

    def __init__(self, view, parent=None):
        super().__init__(parent)
        self.view = view
        self.setWindowTitle("Layers")
        self.resize(420, 400)
        lay = QVBoxLayout(self)
        lab = QLabel("Tick a layer to show it. New markups go on the "
                     "active layer.")
        lab.setWordWrap(True)
        lay.addWidget(lab)
        self.list = QListWidget()
        self.list.itemChanged.connect(self._toggled)
        lay.addWidget(self.list)
        row = QHBoxLayout()
        for text, slot in (("New Layer…", self.new_layer),
                           ("Make Active", self.make_active),
                           ("No Active Layer", self.clear_active),
                           ("Move Selected Markup Here", self.move_selected)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        lay.addLayout(row)
        self.active = QLabel("")
        lay.addWidget(self.active)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._loading = False
        self.fill()

    def fill(self):
        self._loading = True
        self.list.clear()
        for xref, info in sorted((self.view.doc.get_ocgs() or {}).items(),
                                 key=lambda kv: kv[1].get("name", "")):
            it = QListWidgetItem(info.get("name", f"Layer {xref}"))
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if info.get("on", True)
                             else Qt.Unchecked)
            it.setData(Qt.UserRole, xref)
            self.list.addItem(it)
        act = self.view.style.get("layer") or ""
        self.active.setText(f"Active layer: <b>{act or '(none)'}</b>")
        self._loading = False

    def _toggled(self, it):
        if self._loading:
            return
        set_layer_visible(self.view, it.data(Qt.UserRole),
                          it.checkState() == Qt.Checked)

    def new_layer(self):
        name, ok = QInputDialog.getText(self, "New Layer", "Layer name:")
        if ok and name.strip():
            annotate.ocg_xref(self.view.doc, name.strip()[:60])
            self.view.history.snapshot()
            self.view.mark_dirty()
            self.view.style["layer"] = name.strip()[:60]
            self.fill()

    def _current_name(self):
        it = self.list.currentItem()
        return it.text() if it else None

    def make_active(self):
        name = self._current_name()
        if name:
            self.view.style["layer"] = name
            self.fill()

    def clear_active(self):
        self.view.style.pop("layer", None)
        self.fill()

    def move_selected(self):
        name = self._current_name()
        if not name:
            return
        if not self.view.selected:
            QMessageBox.information(self, "Layers",
                                    "Select a markup on the page first.")
            return
        self.view.change_selected(layer=name)


def set_layer_visible(view, xref, on):
    doc = view.doc
    ocgs = doc.get_ocgs() or {}
    on_list = [x for x, i in ocgs.items() if i.get("on", True) and x != xref]
    off_list = [x for x, i in ocgs.items() if not i.get("on", True)
                and x != xref]
    (on_list if on else off_list).append(xref)
    doc.set_layer(-1, on=on_list, off=off_list)       # saved with the file
    # ...and the state in use now (what get_ocgs and rendering read)
    name = ocgs.get(xref, {}).get("name")
    for ui in doc.layer_ui_configs() or []:
        if ui.get("text") == name and bool(ui.get("on")) != bool(on):
            doc.set_layer_ui_config(ui["number"],
                                    getattr(fitz, "PDF_OC_ON", 0) if on
                                    else getattr(fitz, "PDF_OC_OFF", 2))
    view.history.snapshot()
    view.mark_dirty()
    view.reset_page_cache()
    view._render()


class ColumnsDialog(QDialog):
    """Custom Markups List columns (saved in the PDF) and custom statuses
    (saved for you)."""

    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle("Markups List Columns && Statuses")
        self.resize(720, 460)
        lay = QVBoxLayout(self)
        lab = QLabel(
            "Columns: Text, Number, Choice (list the choices, separated by "
            "commas; give a choice a hidden number with =, e.g. "
            "Carpet = 4.50, Tile = 9.25) or Formula. Formulas can use "
            "Value, Length, Area, Count, Volume, Radius, Diameter, Angle, "
            "Wall_Area, Height, Openings, Rise, Number columns and Choice "
            "columns (their hidden number) by name (spaces become _), e.g. "
            " Area * Unit_Price  or  Value * Floor_Finish")
        lab.setWordWrap(True)
        lay.addWidget(lab)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Name", "Type",
                                              "Choices / Formula"])
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch)
        lay.addWidget(self.table)
        row = QHBoxLayout()
        add = QPushButton("Add Column")
        add.clicked.connect(lambda: self._add_row({"name": "", "type": "text"}))
        rem = QPushButton("Remove Column")
        rem.clicked.connect(lambda: self.table.removeRow(
            self.table.currentRow()) if self.table.currentRow() >= 0 else None)
        row.addWidget(add)
        row.addWidget(rem)
        row.addStretch()
        lay.addLayout(row)
        lay.addWidget(QLabel("Your statuses (one per line, added to "
                             "Accepted, Rejected, Completed...):"))
        from . import settings
        self.statuses = QPlainTextEdit("\n".join(settings.get("statuses")
                                                 or []))
        self.statuses.setMaximumHeight(90)
        lay.addWidget(self.statuses)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        for c in columns.read(doc)["columns"]:
            self._add_row(c)

    def _add_row(self, c):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(c.get("name", "")))
        combo = QComboBox()
        combo.addItems([t.title() for t in columns.TYPES])
        combo.setCurrentIndex(columns.TYPES.index(c.get("type", "text")))
        self.table.setCellWidget(r, 1, combo)
        extra = ", ".join(c.get("choices") or []) if c.get("type") == \
            "choice" else c.get("formula", "")
        self.table.setItem(r, 2, QTableWidgetItem(extra))

    def values(self):
        cols = []
        for r in range(self.table.rowCount()):
            name = (self.table.item(r, 0).text()
                    if self.table.item(r, 0) else "").strip()
            typ = columns.TYPES[self.table.cellWidget(r, 1).currentIndex()]
            extra = (self.table.item(r, 2).text()
                     if self.table.item(r, 2) else "").strip()
            c = {"name": name, "type": typ}
            if typ == "choice":
                c["choices"] = [x.strip() for x in extra.split(",")]
            if typ == "formula":
                c["formula"] = extra
            cols.append(c)
        sts = [s.strip() for s in self.statuses.toPlainText().splitlines()]
        return cols, [s for s in sts if s]
