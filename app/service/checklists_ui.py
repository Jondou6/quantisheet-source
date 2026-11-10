"""Maintenance Checklist window (1.2, #8). open_window(parent,
work_order_id="") shows it."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QLabel,
                               QLineEdit)

from ..estimating import service as records_api
from . import checklists, files, uiutil, workorder


class ChecklistWindow(uiutil.Desk):
    def __init__(self, parent=None, work_order_id=""):
        super().__init__("Maintenance Checklist", parent)
        self.path = checklists.default_path()
        self.wo_id = work_order_id
        row = QHBoxLayout()
        self.unit = QComboBox()
        self.unit.setAccessibleName("Unit")
        self.template = QComboBox()
        self.template.setAccessibleName("Checklist")
        self.tech = QLineEdit()
        self.tech.setPlaceholderText("Technician")
        self.when = QLineEdit()
        self.when.setPlaceholderText("Date (today if blank)")
        for w in (QLabel("Unit"), self.unit, QLabel("Checklist"),
                  self.template, self.tech, self.when):
            row.addWidget(w)
        self.root.addLayout(row)
        self.table = uiutil.table(["Step / reading", "Value", "Unit",
                                   "Earlier", "Watch"])
        self.table.setAccessibleName("Checklist items")
        from PySide6.QtWidgets import QAbstractItemView
        self.table.setEditTriggers(QAbstractItemView.AllEditTriggers)
        self.root.addWidget(self.table, 1)
        self.trend = QLabel("")
        self.trend.setWordWrap(True)
        self.root.addWidget(self.trend)
        self.buttons(("Save checklist", self.save_clicked),
                     ("Print paper checklist…", self.print_clicked))
        self.finish()
        self.template.currentIndexChanged.connect(lambda _i: self.fill())
        self.unit.currentIndexChanged.connect(lambda _i: self.fill())
        self.table.currentCellChanged.connect(
            lambda r, *_: self.show_trend(r))
        self.reload()

    def reload(self):
        self.store = checklists.load(self.path)
        self.tpls = checklists.templates()
        self.records = records_api.load()
        self.unit.blockSignals(True)
        self.unit.clear()
        self.unit.addItem("(no unit)", "")
        for eq in self.records.get("equipment", []):
            self.unit.addItem(" ".join(p for p in (
                eq.get("kind"), eq.get("make"), eq.get("model"),
                eq.get("serial")) if p), eq["id"])
        if self.wo_id:
            wo = workorder.get(workorder.load(), self.wo_id)
            i = self.unit.findData(wo.get("equipment_id") or "")
            if i >= 0:
                self.unit.setCurrentIndex(i)
            self.tech.setText(wo.get("tech") or "")
        self.unit.blockSignals(False)
        self.template.blockSignals(True)
        self.template.clear()
        for key, t in self.tpls.items():
            self.template.addItem(t["name"], key)
        self.template.blockSignals(False)
        self.fill()

    def items(self):
        return self.tpls[self.template.currentData()]["items"]

    def fill(self):
        eq = self.unit.currentData()
        rows = []
        for it in self.items():
            earlier = ""
            if it["kind"] == "reading" and eq:
                pts = checklists.trend(self.store, eq, it["key"])
                if pts:
                    earlier = f"{pts[-1][1]} on {pts[-1][0]}"
            rows.append([it["label"], "", it.get("unit", "")
                         if it["kind"] == "reading" else "done / not done / "
                         "n/a", earlier, ""])
        uiutil.fill(self.table, rows)
        for r in range(self.table.rowCount()):
            for c in (0, 2, 3, 4):
                it = self.table.item(r, c)
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)

    def values(self):
        out = {}
        for r, it in enumerate(self.items()):
            cell = self.table.item(r, 1)
            out[it["key"]] = cell.text().strip() if cell else ""
        return out

    def show_trend(self, row):
        eq = self.unit.currentData()
        if row < 0 or row >= len(self.items()) or not eq:
            self.trend.setText("")
            return ""
        it = self.items()[row]
        if it["kind"] != "reading":
            self.trend.setText("")
            return ""
        pts = checklists.trend(self.store, eq, it["key"])
        txt = (f"{it['label']}: " + ", ".join(f"{d} {v}" for d, v, _u, _w
                                              in pts[-6:])
               + (f" ({checklists.change_text(pts)})" if len(pts) > 1
                  else "")) if pts else f"{it['label']}: no earlier readings."
        self.trend.setText(txt)
        return txt

    def save_clicked(self):
        cid = self.guard(lambda: checklists.record(
            self.store, self.template.currentData(), self.values(),
            equipment_id=self.unit.currentData() or "",
            work_order_id=self.wo_id, when=self.when.text().strip() or None,
            tech=self.tech.text(), tpls=self.tpls))
        if not cid:
            return None
        checklists.save(self.store, self.path)
        row = next(c for c in self.store["done"] if c["id"] == cid)
        flagged = [i["label"] for i in row["items"] if i.get("watch")]
        self.fill()
        self.msg.setText("Checklist saved." + (
            " Readings to look at: " + ", ".join(flagged) if flagged else ""))
        return cid

    def print_clicked(self, _checked=False, path=None):
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Paper checklist", files.path_for(
                    f"{self.template.currentText()}.pdf"), "PDF (*.pdf)")
        if not path:
            return None
        wo = workorder.get(workorder.load(), self.wo_id) if self.wo_id \
            else None
        out = self.guard(lambda: checklists.printable_pdf(
            self.template.currentData(), path, wo=wo, tpls=self.tpls))
        if out:
            self.msg.setText(f"Saved {out}")
        return out


def open_window(parent=None, work_order_id=""):
    return uiutil.show(ChecklistWindow(parent, work_order_id))
