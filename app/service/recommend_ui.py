"""Technician recommendations window. open_window(parent) shows it.

Option quote builds the customer quote through estimating/quotes.py.
"""
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel,
                               QLineEdit)

from ..estimating import service as records_api
from . import files, pricebook, recommend, uiutil


class RecommendWindow(uiutil.Desk):
    def __init__(self, parent=None):
        super().__init__("Tech Recommendations", parent)
        self.path = recommend.default_path()
        row = QHBoxLayout()
        self.unit = QComboBox()
        self.note = QLineEdit()
        self.note.setPlaceholderText("Note")
        self.photo = QLineEdit()
        self.photo.setPlaceholderText("Photo file")
        self.price = QLineEdit()
        self.price.setPlaceholderText("Price")
        self.tier = QComboBox()
        self.tier.addItems(["option", "base", "Good", "Better", "Best"])
        self.task = QComboBox()
        for w in (self.unit, self.note, self.photo, self.price, self.tier,
                  self.task):
            row.addWidget(w)
        self.root.addLayout(row)
        self.preview = QLabel("Photo: none")
        self.root.addWidget(self.preview)
        self.buttons(("Add recommendation", self.add_clicked),
                     ("Option quote for this unit", self.quote_clicked))
        self.table = uiutil.table(
            ["Unit", "Note", "Photo", "Price", "Tier", "Task"])
        self.table.itemSelectionChanged.connect(self._show_photo)
        self.root.addWidget(self.table, 1)
        self.finish()
        self.reload()

    def reload(self):
        self.store = recommend.load(self.path)
        self.records = records_api.load()
        self.book = pricebook.load()
        self.unit.clear()
        for eq in self.records["equipment"]:
            label = " ".join(p for p in (eq.get("kind"), eq.get("model"),
                                         eq.get("serial")) if p)
            self.unit.addItem(label, eq["id"])
        self.task.clear()
        self.task.addItem("", "")
        for t in self.book["tasks"]:
            self.task.addItem(t["name"], t["id"])
        rows, ids = [], []
        for r in self.store["items"]:
            rows.append([r["unit"], r["note"], r["photo"], r["price"],
                         r["tier"], r["task_id"]])
            ids.append(r["id"])
        uiutil.fill(self.table, rows, ids)

    def _show_photo(self):
        rid = uiutil.selected_id(self.table)
        row = next((r for r in self.store["items"] if r["id"] == rid), None)
        if not row or not row.get("photo"):
            self.preview.setText("Photo: none")
            return
        self.preview.setText("Photo: " + row["photo"])

    def add_clicked(self):
        def go():
            return recommend.add(
                self.store, self.records, self.unit.currentData(),
                note=self.note.text(), photo=self.photo.text(),
                price=self.price.text(), task_id=self.task.currentData() or "",
                tier=self.tier.currentText())
        if self.guard(go):
            recommend.save(self.store, self.path)
            self.reload()
            self.msg.setText("Recommendation saved.")

    def quote_to(self, path, member=False):
        eq = self.unit.currentData()
        def go():
            quote = recommend.quote_for_unit(
                self.store, eq, pricebook=self.book, member=member)
            return recommend.save_quote(path, quote)
        out = self.guard(go)
        if out:
            self.msg.setText(f"Saved {out}")
        return out

    def quote_clicked(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Option quote", files.path_for("Recommended work.pdf"),
            "PDF (*.pdf)")
        if path:
            self.quote_to(path)


def open_window(parent=None):
    return uiutil.show(RecommendWindow(parent))
