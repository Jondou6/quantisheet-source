"""3D Model Quantities window (Nov 23, Jon: its own "3D Model" tab after
AI, and in the Takeoff menu). Open an IFC model, see its elements by kind,
type and storey with the quantities the model carries, tick rows and add
them to the open drawing's estimate (adding again updates the quantities
and keeps the prices typed)."""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QMessageBox, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from . import ifcmodel as im
from .dmoney import c2 as _c2, half_up

SOURCE = "3D Model"
COLS = ["Category", "Type", "Storey", "Count", "Length (LF)", "Area (SF)",
        "Volume (CY)"]


class IfcDialog(QDialog):
    def __init__(self, win=None, path=None):
        super().__init__(win)
        self.win = win
        self.path = None
        self.rows = []
        self.setWindowTitle("3D Model Quantities")
        self.resize(1000, 620)
        v = QVBoxLayout(self)
        self.intro = QLabel(
            "Open an IFC model (the open building-model format most design "
            "programs export). Quantities are the ones the model carries in "
            "its quantity sets; nothing is guessed from the geometry.")
        self.intro.setWordWrap(True)
        v.addWidget(self.intro)
        h = QHBoxLayout()
        h.addWidget(QLabel("Storey:"))
        self.storey = QComboBox()
        self.storey.currentIndexChanged.connect(lambda _i: self.fill())
        h.addWidget(self.storey)
        h.addStretch(1)
        v.addLayout(h)
        t = self.table = QTableWidget(0, len(COLS))
        t.setHorizontalHeaderLabels(COLS)
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        v.addWidget(t, 1)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        self.open_btn = bb.addButton("Open Model…", QDialogButtonBox.ActionRole)
        self.open_btn.clicked.connect(lambda: self.open_model())
        self.add_btn = bb.addButton("Add Ticked to Estimate",
                                    QDialogButtonBox.ActionRole)
        self.add_btn.clicked.connect(lambda: self.add_to_estimate())
        self.csv_btn = bb.addButton("Export CSV…", QDialogButtonBox.ActionRole)
        self.csv_btn.clicked.connect(lambda: self.export_csv())
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        if path:
            self.open_model(path)
        else:
            self._enable()

    def _enable(self):
        self.add_btn.setEnabled(bool(self.rows))
        self.csv_btn.setEnabled(bool(self.rows))

    def open_model(self, path=None):
        if path is None:
            path, _f = QFileDialog.getOpenFileName(
                self, "Open IFC Model", "", "IFC model (*.ifc)")
            if not path:
                return None
        try:
            text = im.load(path)
            rows = im.read(path, text)
            info = im.summary(path, text, rows)
        except im.IfcError as e:
            QMessageBox.information(self, self.windowTitle(), str(e))
            return None
        except Exception as e:                            # noqa: BLE001
            QMessageBox.warning(self, self.windowTitle(),
                                f"That model couldn't be read: {e}")
            return None
        self.path, self.rows, self.info = path, rows, info
        self.storey.blockSignals(True)
        self.storey.clear()
        self.storey.addItem("All storeys", None)
        for s in sorted({r["storey"] for r in rows if r["storey"]}):
            self.storey.addItem(s, s)
        self.storey.blockSignals(False)
        no_q = info["elements"] - info["with_qty"]
        self.intro.setText(
            f"<b>{info['project'] or os.path.basename(path)}</b> - "
            f"{info['schema'] or 'IFC'}, lengths in {info['units']}. "
            f"{info['elements']} elements in {len(rows)} groups; "
            f"{info['with_qty']} carry quantities." + (
                f" <span style='color:#b00020'>{no_q} have no quantity set, "
                "so only their count is known - export the model with base "
                "quantities to get lengths, areas and volumes.</span>"
                if no_q else ""))
        self.fill()
        self._enable()
        return rows

    def shown(self):
        st = self.storey.currentData()
        return [r for r in self.rows if st is None or r["storey"] == st]

    def fill(self):
        rows = self.shown()
        t = self.table
        t.setRowCount(len(rows))
        for i, r in enumerate(rows):
            vals = [r["category"], r["type"], r["storey"], str(r["count"]),
                    f"{_c2(r['length']):,.2f}" if r["length"] else "",
                    f"{_c2(r['area']):,.2f}" if r["area"] else "",
                    f"{_c2(r['volume']):,.2f}" if r["volume"] else ""]
            for c, val in enumerate(vals):
                it = QTableWidgetItem(val)
                if c == 0:
                    it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                    it.setCheckState(Qt.Checked)
                if c >= 3:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if r["names"]:
                    it.setToolTip(", ".join(r["names"]))
                t.setItem(i, c, it)

    def ticked(self):
        rows = self.shown()
        return [rows[i] for i in range(self.table.rowCount())
                if self.table.item(i, 0).checkState() == Qt.Checked]

    def _doc(self):
        view = getattr(self.win, "_view", None) if self.win else None
        return getattr(view, "doc", None) if view is not None else None

    def add_to_estimate(self):
        """Ticked rows as estimate lines on the open drawing. A line this
        window added before (same description) gets the new quantity and
        keeps its price. Returns (added, updated)."""
        from . import estimate_lines as el
        doc = self._doc()
        if doc is None:
            self.status.setText("Open the drawing whose estimate these go "
                                "in first (the estimate is kept in its PDF).")
            return 0, 0
        rows = im.estimate_rows(self.ticked())
        def key(d):
            return " ".join(str(d).split()).casefold()
        old = {key(ln["desc"]): ln for ln in el.read(doc)
               if ln.get("source") == SOURCE}
        note = "From the model " + os.path.basename(self.path or "")
        new, updated = [], 0
        for desc, q, unit, code in rows:
            q = half_up(q, 2)
            k = key(desc)
            if k in old and old[k].get("unit") == unit:
                el.update(doc, old[k]["id"], qty=str(q), note=note)
                updated += 1
            else:
                new.append(el.new_line(desc=desc, qty=q, unit=unit,
                                       code=code, source=SOURCE, note=note))
        if new:
            el.add(doc, new)
        if self.win is not None and hasattr(self.win, "_doc_edited"):
            self.win._doc_edited()
        self.status.setText(f"Added {len(new)} line(s) and updated "
                            f"{updated} on the estimate - price them there.")
        return len(new), updated

    def export_csv(self, path=None):
        if path is None:
            base = os.path.splitext(self.path or "model")[0]
            path, _f = QFileDialog.getSaveFileName(
                self, "Export CSV", base + " - quantities.csv", "CSV (*.csv)")
            if not path:
                return None
        return im.to_csv(self.shown(), path)


def show(win=None, path=None, modal=False):
    dlg = IfcDialog(win, path)
    dlg.setAttribute(Qt.WA_DeleteOnClose)
    if modal:
        dlg.exec()
    else:
        dlg.show()
    return dlg
