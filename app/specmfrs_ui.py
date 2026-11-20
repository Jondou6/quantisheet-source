"""Estimate > Manufacturers in Specs (Nov 20)."""
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog,
                               QHeaderView, QLabel, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from . import specmfrs


class SpecMfrsDialog(QDialog):
    """Each spec section's listed manufacturers and basis-of-design
    products, with pages (double-click to go there); Export CSV makes the
    quote-request list."""

    def __init__(self, win, rows=None):
        super().__init__(win)
        self.win = win
        self.doc = win._view.doc
        self.rows = specmfrs.find(self.doc) if rows is None else rows
        self.setWindowTitle("Manufacturers in Specs")
        self.resize(820, 460)
        v = QVBoxLayout(self)
        sections = len({r["section"] for r in self.rows})
        intro = QLabel(
            f"{len(self.rows)} manufacturer(s) and product(s) in {sections} "
            "section(s), read from this document's text - check each on its "
            "page (double-click a row). Use Export CSV for a quote-request "
            "list by trade." if self.rows else
            "No listed manufacturers were found. Open the project manual "
            "(specifications); scanned pages need Make Searchable first.")
        intro.setWordWrap(True)
        v.addWidget(intro)
        t = self.table = QTableWidget(len(self.rows), 5)
        t.setHorizontalHeaderLabels(["Section", "Title", "Manufacturer / "
                                     "product", "Listed as", "Page"])
        for i, r in enumerate(self.rows):
            kind = "basis of design" if r["kind"] == "basis" else "listed"
            if r["no_subs"]:
                kind += " - no substitutions"
            for c, val in enumerate((r["section"], r["title"],
                                     r["manufacturer"], kind,
                                     str(r["page"] + 1))):
                t.setItem(i, c, QTableWidgetItem(val))
        t.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        t.setSortingEnabled(True)
        t.sortItems(0)
        t.cellDoubleClicked.connect(lambda r, _c: self.go(r))
        v.addWidget(t)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        self.csv_btn = bb.addButton("Export CSV…", QDialogButtonBox.ActionRole)
        self.csv_btn.setEnabled(bool(self.rows))
        self.csv_btn.clicked.connect(lambda: self.export())
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def go(self, row):
        page = int(self.table.item(row, 4).text()) - 1
        self.win._go_page(page)

    def export(self, path=None):
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Export CSV", "manufacturers_by_section.csv",
                "CSV (*.csv)")
            if not path:
                return None
        return specmfrs.to_csv(self.rows, path)
