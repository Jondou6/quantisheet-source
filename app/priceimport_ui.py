"""Import Your Own Price List window (priceimport.py), and the warning
shown before a licensed (local-only) book is exported or shared."""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QFormLayout,
                               QGridLayout, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from . import pricedb, priceimport

NONE = -1
PREVIEW_COLS = ["Row", "Code", "Description", "Unit", "Material $",
                "Labor $", "Equipment $", "Hours/unit", "Status"]


def _cell(text, editable=False, right=False):
    it = QTableWidgetItem("" if text is None else str(text))
    if not editable:
        it.setFlags(it.flags() & ~Qt.ItemIsEditable)
    if right:
        it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    return it


def share_warning_box(parent, name, action="export"):
    """The question shown before a local-only book leaves this PC: Cancel
    is the default button. Returned unopened (tests check it)."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Warning)
    box.setWindowTitle("Licensed price data")
    box.setText(f"\"{name}\" is licensed price data, kept only in this PC's "
                "price database.")
    box.setInformativeText(
        f"Before you {action} it, make sure the licence holder has said "
        "it's OK to share. Continue?")
    go = box.addButton(f"{action.title()} Anyway", QMessageBox.AcceptRole)
    cancel = box.addButton(QMessageBox.Cancel)
    box.setDefaultButton(cancel)
    box.setEscapeButton(cancel)
    box._go = go
    return box


def confirm_share(parent, book_or_data, action="export"):
    """True to go ahead: always for an ordinary book; for a local-only
    one only when the user picks '<Action> Anyway' (Cancel is the
    default)."""
    data = book_or_data.to_dict() if hasattr(book_or_data, "to_dict") \
        else (book_or_data or {})
    if not pricedb.book_is_local_only(data):
        return True
    box = share_warning_box(parent, data.get("name", "This book"), action)
    box.exec()
    return box.clickedButton() is box._go


class ImportPriceListDialog(QDialog):
    """Pick a file, map its columns, check 20 rows, name the book and its
    source / edition, fix or skip the rows that need a code, import."""

    def __init__(self, parent=None, path=None):
        super().__init__(parent)
        self.setWindowTitle("Import Your Own Price List")
        self.resize(1100, 760)
        self.head, self.rows, self.result = [], [], None
        self.fixes, self.skip = {}, set()
        lay = QVBoxLayout(self)
        intro = QLabel(
            "Bring in a price list or cost data export you're licensed to "
            "use (Excel .xlsx or CSV). It becomes a cost book kept only in "
            "this PC's price database; it is not part of QuantiSheet and "
            "location factors are not imported.")
        intro.setWordWrap(True)
        lay.addWidget(intro)
        self.where = QLabel("")
        self.where.setWordWrap(True)
        lay.addWidget(self.where)
        row = QHBoxLayout()
        self.file = QLineEdit(path or "")
        self.file.setPlaceholderText("my price list.xlsx")
        self.file.editingFinished.connect(lambda: self.load(
            self.file.text().strip()))
        b = QPushButton("Browse…")
        b.clicked.connect(lambda: self.browse())
        row.addWidget(QLabel("File:"))
        row.addWidget(self.file, 1)
        row.addWidget(b)
        lay.addLayout(row)

        box = QGroupBox("Columns")
        grid = QGridLayout(box)
        self.combos = {}
        for i, (field, label) in enumerate(priceimport.FIELDS):
            c = QComboBox()
            c.currentIndexChanged.connect(lambda *_: self.refresh())
            self.combos[field] = c
            grid.addWidget(QLabel(label + ":"), i // 3, (i % 3) * 2)
            grid.addWidget(c, i // 3, (i % 3) * 2 + 1)
        lay.addWidget(box)
        row = QHBoxLayout()
        self.crew = QDoubleSpinBox()
        self.crew.setRange(0.5, 100)
        self.crew.setDecimals(1)
        self.crew.setValue(1)
        self.crew.setSuffix(" workers")
        self.hpd = QDoubleSpinBox()
        self.hpd.setRange(1, 24)
        self.hpd.setDecimals(1)
        self.hpd.setValue(8)
        self.hpd.setSuffix(" h/day")
        self.rate = QDoubleSpinBox()
        self.rate.setRange(0, 1000)
        self.rate.setDecimals(2)
        self.rate.setPrefix("$")
        self.rate.setSuffix("/h")
        self.rate.setToolTip("Only to turn a Labor $ column into hours when "
                             "there's no Hours or Labor Output column")
        for label, w in (("Labor Output crew:", self.crew),
                         ("working", self.hpd),
                         ("Labor $ to hours at:", self.rate)):
            row.addWidget(QLabel(label))
            w.valueChanged.connect(lambda *_: self.refresh())
            row.addWidget(w)
        row.addStretch()
        lay.addLayout(row)

        lay.addWidget(QLabel(f"<b>Preview</b> (first "
                             f"{priceimport.PREVIEW_ROWS} rows)"))
        self.preview = QTableWidget(0, len(PREVIEW_COLS))
        self.preview.setHorizontalHeaderLabels(PREVIEW_COLS)
        self.preview.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch)
        lay.addWidget(self.preview, 2)
        self.needs_label = QLabel("<b>Needs code</b>")
        lay.addWidget(self.needs_label)
        self.needs = QTableWidget(0, 4)
        self.needs.setHorizontalHeaderLabels(["Row", "Code as read",
                                              "Description", "New code"])
        self.needs.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch)
        self.needs.itemChanged.connect(self._fixed)
        lay.addWidget(self.needs, 1)
        row = QHBoxLayout()
        b = QPushButton("Skip Selected")
        b.clicked.connect(lambda: self.skip_selected())
        row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)

        form = QFormLayout()
        self.name = QLineEdit()
        self.source = QLineEdit()
        self.source.setPlaceholderText("where the prices came from, as you "
                                       "would cite it")
        self.edition = QLineEdit()
        self.edition.setPlaceholderText("e.g. 2026")
        self.date_label = QLabel(priceimport.today())
        form.addRow("Book name:", self.name)
        form.addRow("Source:", self.source)
        form.addRow("Edition:", self.edition)
        form.addRow("Imported:", self.date_label)
        lay.addLayout(form)
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        bb = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.import_btn = bb.addButton("Import", QDialogButtonBox.AcceptRole)
        self.import_btn.clicked.connect(lambda: self.do_import())
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._show_where()
        if path:
            self.load(path)

    def _show_where(self):
        why = priceimport.can_save_here()
        self.where.setText(f"<span style='color:#b00'>{why}</span>" if why
                           else f"<small>Saved in this PC's price database: "
                           f"{pricedb.path()}</small>")

    # ---- file and mapping ---------------------------------------------------
    def browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Your Own Price List", "",
            "Price list (*.xlsx *.csv);;All files (*)")
        if path:
            self.file.setText(path)
            self.load(path)
        return path or None

    def load(self, path):
        if not path:
            return False
        try:
            self.head, self.rows = priceimport.read(path)
        except Exception as e:                            # noqa: BLE001
            self.head, self.rows = [], []
            self.summary.setText(f"<span style='color:#b00'>Can't read "
                                 f"{os.path.basename(path)}: {e}</span>")
            self._fill_combos({})
            return False
        self.path = path
        self.fixes, self.skip = {}, set()
        if not self.name.text().strip():
            self.name.setText(os.path.splitext(os.path.basename(path))[0])
        self._fill_combos(priceimport.guess_mapping(self.head))
        self.refresh()
        return True

    def _fill_combos(self, guess):
        for field, c in self.combos.items():
            c.blockSignals(True)
            c.clear()
            c.addItem("(none)", NONE)
            for i, h in enumerate(self.head):
                c.addItem(h or f"Column {i + 1}", i)
            c.setCurrentIndex(max(0, c.findData(guess.get(field, NONE))))
            c.blockSignals(False)

    def mapping(self):
        return {f: c.currentData() for f, c in self.combos.items()
                if c.currentData() not in (None, NONE)}

    def set_mapping(self, mapping):
        """{field: column header or index} (for scripts and tests)."""
        for field, col in mapping.items():
            if isinstance(col, str):
                col = self.head.index(col) if col in self.head else NONE
            c = self.combos[field]
            c.setCurrentIndex(max(0, c.findData(col)))
        self.refresh()

    def opts(self):
        return {"crew_size": self.crew.value(),
                "hours_per_day": self.hpd.value(),
                "labor_rate": self.rate.value() or None}

    # ---- preview ----------------------------------------------------------------
    def refresh(self):
        m = self.mapping()
        rows = priceimport.preview(self.head, self.rows, m, **self.opts()) \
            if self.rows else []
        t = self.preview
        t.setRowCount(len(rows))
        for r, x in enumerate(rows):
            vals = [x["row"], x["code"] or x["raw_code"], x["desc"],
                    x["unit"], x["material"], x["labor"], x["equipment"],
                    x["hours"], x["status"]]
            for c, v in enumerate(vals):
                t.setItem(r, c, _cell(v, right=c in (0, 4, 5, 6, 7)))
        self._fill_needs()
        return rows

    def _build(self):
        return priceimport.build(
            self.head, self.rows, self.mapping(), self.name.text(),
            self.source.text(), self.edition.text(), fixes=self.fixes,
            skip=self.skip, file_name=os.path.basename(
                getattr(self, "path", "") or ""), **self.opts())

    def _fill_needs(self):
        if not self.rows or "code" not in self.mapping():
            self.needs.setRowCount(0)
            self.needs_rows = []
            return []
        try:
            res = priceimport.build(
                self.head, self.rows, self.mapping(), "x", "x", fixes=
                self.fixes, skip=self.skip, **self.opts())
        except ValueError:
            res = {"needs_code": [], "imported": []}
        self.needs_rows = res["needs_code"]
        t = self.needs
        t.blockSignals(True)
        t.setRowCount(len(self.needs_rows))
        for r, x in enumerate(self.needs_rows):
            for c, v in enumerate((x["row"], x["code"], x["desc"])):
                t.setItem(r, c, _cell(v))
            t.setItem(r, 3, _cell("", editable=True))
        t.blockSignals(False)
        self.needs_label.setText(f"<b>Needs code</b> ({len(self.needs_rows)}"
                                 " row(s) - type a code or skip them)")
        self.summary.setText(f"{len(res['imported'])} row(s) ready to "
                             "import" + (f", {len(self.needs_rows)} need a "
                                         "code" if self.needs_rows else ""))
        return self.needs_rows

    def _fixed(self, cell):
        if cell.column() != 3 or cell.row() >= len(self.needs_rows):
            return
        r, text = cell.row(), cell.text().strip()
        if text:
            # rebuild the table after this edit has finished
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self.fix_code(r, text))

    def fix_code(self, row, text):
        """Give row `row` of the Needs code list the code `text`. False
        (with a message) when it isn't a CSI code."""
        if row >= len(self.needs_rows):
            return False
        if not priceimport.normalize_code(text):
            QMessageBox.warning(self, "Needs code", f"{text!r} isn't a CSI "
                                "code (e.g. 03 31 13 or 03 31 13.35).")
            return False
        self.fixes[self.needs_rows[row]["index"]] = text
        self.refresh()
        return True

    def skip_selected(self, rows=None):
        rows = rows if rows is not None else sorted(
            {i.row() for i in self.needs.selectedItems()})
        for r in rows:
            if r < len(self.needs_rows):
                self.skip.add(self.needs_rows[r]["index"])
        self.refresh()
        return len(rows)

    # ---- import -----------------------------------------------------------------
    def do_import(self):
        """Import and save the book. Returns the result, or None (with a
        message) when it can't be done."""
        why = priceimport.can_save_here()
        if why:
            QMessageBox.warning(self, "Import Your Own Price List", why)
            return None
        if not self.rows:
            QMessageBox.information(self, "Import Your Own Price List",
                                    "Pick a file first.")
            return None
        try:
            res = self._build()
        except ValueError as e:
            QMessageBox.information(self, "Import Your Own Price List",
                                    str(e))
            return None
        if not res["imported"]:
            QMessageBox.information(self, "Import Your Own Price List",
                                    "No rows with a readable code.")
            return None
        name = res["book"].name
        try:
            exists = name in pricedb.book_names()
        except pricedb.PriceDBError:
            exists = False
        if exists and QMessageBox.question(
                self, "Import Your Own Price List",
                f"Replace the cost book \"{name}\"?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != \
                QMessageBox.Yes:
            return None
        try:
            res["saved"] = priceimport.save(res["book"])
        except pricedb.PriceDBError as e:
            QMessageBox.warning(self, "Import Your Own Price List", str(e))
            return None
        self.result = res
        msg = f"Imported {len(res['imported'])} item(s) into \"{name}\"."
        if res["needs_code"]:
            msg += (f"\n{len(res['needs_code'])} row(s) still need a code "
                    "and were not imported.")
        if res["warnings"]:
            msg += "\n\n" + "\n".join(res["warnings"][:8])
        QMessageBox.information(self, "Import Your Own Price List", msg)
        self.accept()
        return res
