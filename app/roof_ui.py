"""Roof Plan Takeoff dialog: tag the areas, lengths and counts you drew on
a scaled roof plan with a roof type and pitch, then see the true (sloped)
quantities, squares and the roof summary.

Plans only: this never reads aerial or satellite images, and it is turned
off on aerial pages (see roof.PLANS_ONLY). QuantiSheet does the math; you
draw every facet and line."""
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout,
                               QWidget, QAbstractItemView)

from . import annotate, estimate, roof, settings

WASTE = {"Simple": 10, "Moderate": 12, "Complex": 15}


def is_aerial_page(doc, pno):
    """True on a page made from an aerial / satellite image (its scale
    record has a geo key or an 'aerial' name)."""
    try:
        sc = (annotate.read_scales(doc) or {}).get(pno) or {}
    except Exception:
        return False
    if not isinstance(sc, dict):
        return False
    return "geo" in sc or str(sc.get("name", "")).lower().startswith("aerial")


def waste_presets():
    w = settings.get("roof_waste_pct") or {}
    out = dict(WASTE)
    if isinstance(w, dict):
        for k, v in w.items():
            if k in out and isinstance(v, (int, float)) and 0 <= v <= 50:
                out[k] = v
    return out


def roof_marks(pno, items, data):
    """set_annot marks that put roof `data` on takeoff `items`."""
    return [(pno, "set_annot", {**it["ref"], "roof": dict(data)})
            for it in items if it.get("ref")]


def check_data(data):
    """Why `data` can't be saved, or ''."""
    t = data.get("type")
    if t not in roof.ROOF_TYPES:
        return "Pick what this is on the roof."
    needs = t in roof.AREA_TYPES or (
        t in roof.LINE_TYPES and roof.run_of(data) != "level")
    if needs:
        if roof.run_of(data) == "hipvalley" and t not in roof.AREA_TYPES:
            ok = roof.parse_pitch2(data.get("pitch")) is not None
        else:
            ok = roof.parse_pitch(data.get("pitch")) is not None
        if not ok:
            return (f"Type the pitch (rise in 12, 0 to {roof.MAX_PITCH:g}; "
                    "steeper than 12:12 is out of range), e.g. 6 or 6/12"
                    + (", or 6,8 for a hip between two pitches"
                       if t in ("hip", "valley") else "") + ".")
    return ""


class TagTab(QWidget):
    COLS = ["Measurement", "Type", "Plan qty", "Roof", "Pitch", "True qty"]

    def __init__(self, dlg):
        super().__init__()
        self.dlg = dlg
        self.items = []
        v = QVBoxLayout(self)
        h = QLabel("Draw roof facets as areas, ridges, hips, valleys, eaves "
                   "and flashing as lengths, and drains, curbs and vents as "
                   "counts. Then pick them here, say what they are and type "
                   "the pitch. There is no default pitch: a facet without "
                   "one is flagged 'check pitch'.")
        h.setWordWrap(True)
        h.setObjectName("muted")
        v.addWidget(h)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        v.addWidget(self.table, 1)
        f = QFormLayout()
        self.kind = QComboBox()
        for t in roof.ROOF_TYPES:
            self.kind.addItem(roof.NAMES.get(t, t.title()), t)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self.pitch = QLineEdit()
        self.pitch.setPlaceholderText("6  or  6/12  or  1/4:12  (hip: 6,8)")
        self.run = QComboBox()
        for r, text in (("level", "Level (ridge, eave)"),
                        ("slope", "Up the slope (rake)"),
                        ("hipvalley", "Hip / valley")):
            self.run.addItem(text, r)
        self.sheet = QComboBox()
        self.sheet.addItem("Roof plan (measure from above)", "plan")
        self.sheet.addItem("Elevation (already true length)", "elevation")
        self.parapet = QSpinBox()
        self.parapet.setRange(0, 240)
        self.parapet.setSuffix(" in wall flashing")
        self.curb = QLineEdit()
        self.curb.setPlaceholderText("W x L ft, e.g. 4x6")
        self.membrane = QComboBox()
        self.membrane.addItem("", "")
        for m in roof.MEMBRANES:
            self.membrane.addItem(m, m)
        f.addRow("This is", self.kind)
        f.addRow("Pitch (x/12)", self.pitch)
        f.addRow("Runs", self.run)
        f.addRow("Drawn on", self.sheet)
        f.addRow("Parapet", self.parapet)
        f.addRow("Curb / RTU size", self.curb)
        f.addRow("Membrane", self.membrane)
        v.addLayout(f)
        self.status = QLabel()
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        row = QHBoxLayout()
        self.clear_btn = QPushButton("Clear Roof Data")
        self.clear_btn.clicked.connect(self.clear)
        row.addWidget(self.clear_btn)
        row.addStretch()
        self.apply_btn = QPushButton("Apply to Selected")
        self.apply_btn.setObjectName("primary")
        self.apply_btn.clicked.connect(self.apply)
        row.addWidget(self.apply_btn)
        v.addLayout(row)
        self._kind_changed()

    @property
    def view(self):
        return self.dlg.win._view

    def _kind_changed(self, *_):
        t = self.kind.currentData()
        i = self.run.findData(roof.DEFAULT_RUN.get(t, "level"))
        if i >= 0:
            self.run.setCurrentIndex(i)
        self.parapet.setEnabled(t == "parapet")
        self.curb.setEnabled(t in ("curb", "rtu"))
        self.membrane.setEnabled(t == "lowslope")
        line = t in roof.LINE_TYPES
        self.run.setEnabled(line)

    def data(self):
        t = self.kind.currentData()
        d = {"type": t, "sheet": self.sheet.currentData()}
        if t in roof.LINE_TYPES:
            d["run"] = self.run.currentData()
        p = self.pitch.text().strip()
        if p and t not in roof.COUNT_TYPES:
            d["pitch"] = p
        if t == "parapet" and self.parapet.value():
            d["parapet_in"] = self.parapet.value()
        if t in ("curb", "rtu") and self.curb.text().strip():
            d["curb"] = self.curb.text().strip()
        if t == "lowslope" and self.membrane.currentData():
            d["membrane"] = self.membrane.currentData()
        return d

    def refresh(self):
        v = self.view
        self.items = []
        self.table.setRowCount(0)
        if v is None or v.doc is None:
            return
        if is_aerial_page(v.doc, v.page):
            self.status.setText(roof.PLANS_ONLY)
            self.apply_btn.setEnabled(False)
            return
        self.apply_btn.setEnabled(True)
        for it in annotate.totals_items(v.doc):
            if it["page"] != v.page or it["type"] not in (
                    "area", "length", "count"):
                continue
            self.items.append(it)
            r = it.get("roof") or {}
            plan = it.get("plan_value", it["value"])
            true = "" if not r else (
                roof.CHECK if it.get("check") else
                f"{it['value']:,.2f} {it['unit']}")
            cells = [it["group"] or it["label"] or it["type"].title(),
                     it["type"].title(), f"{plan:,.2f} {it['unit']}",
                     roof.NAMES.get(r.get("type"), "") if r else "",
                     roof.pitch_text(r) if r else "", true]
            n = self.table.rowCount()
            self.table.insertRow(n)
            for c, text in enumerate(cells):
                self.table.setItem(n, c, QTableWidgetItem(str(text)))
        self.status.setText(f"{len(self.items)} measurement(s) on this page."
                            if self.items else
                            "No measurements on this page yet. Calibrate the "
                            "sheet and draw the roof first.")

    def chosen(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self.items[r] for r in rows if r < len(self.items)]

    def apply(self):
        v = self.view
        if is_aerial_page(v.doc, v.page):
            self.status.setText(roof.PLANS_ONLY)
            return 0
        its = self.chosen()
        if not its:
            self.status.setText("Select one or more measurements first.")
            return 0
        d = self.data()
        why = check_data(d)
        if why:
            self.status.setText(why)
            return 0
        n = v.apply_marks(roof_marks(v.page, its, d))
        self.refresh()
        self.dlg.summary.refresh()
        return n

    def clear(self):
        its = self.chosen()
        if not its:
            return 0
        n = self.view.apply_marks(roof_marks(self.view.page, its, {}))
        self.refresh()
        self.dlg.summary.refresh()
        return n


class SummaryTab(QWidget):
    def __init__(self, dlg):
        super().__init__()
        self.dlg = dlg
        self.rows = []
        v = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Waste"))
        self.waste = QComboBox()
        pre = waste_presets()
        for k in ("Simple", "Moderate", "Complex"):
            self.waste.addItem(f"{k} ({pre[k]:g}%)", pre[k])
        self.waste.addItem("Custom", None)
        self.custom = QSpinBox()
        self.custom.setRange(0, 50)
        self.custom.setSuffix(" %")
        cur = estimate.roof_waste()
        i = next((i for i in range(3) if self.waste.itemData(i) == cur), 3)
        self.waste.setCurrentIndex(i)
        self.custom.setValue(int(cur))
        self.custom.setEnabled(i == 3)
        self.waste.currentIndexChanged.connect(self._waste_changed)
        self.custom.valueChanged.connect(self._waste_changed)
        top.addWidget(self.waste)
        top.addWidget(self.custom)
        top.addStretch()
        exp = QPushButton("Export…")
        exp.clicked.connect(lambda _c=False: self.export())
        top.addWidget(exp)
        v.addLayout(top)
        self.table = QTableWidget(0, len(roof.HEADERS))
        self.table.setHorizontalHeaderLabels(roof.HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch)
        v.addWidget(self.table, 1)
        note = QLabel("Waste applies to area materials (squares, membrane), "
                      "not to lengths or counts. A plan takeoff: every "
                      "quantity comes from what you drew on the sheet.")
        note.setWordWrap(True)
        note.setObjectName("muted")
        v.addWidget(note)

    def pct(self):
        d = self.waste.currentData()
        return float(self.custom.value() if d is None else d)

    def _waste_changed(self, *_):
        self.custom.setEnabled(self.waste.currentData() is None)
        settings.set("roof_waste", self.pct())
        self.refresh()

    def refresh(self):
        v = self.dlg.win._view
        self.rows = []
        if v is not None and v.doc is not None:
            items = roof.roof_items(annotate.totals_items(v.doc))
            labels = {}
            try:
                labels = {i: v.doc[i].get_label() or str(i + 1)
                          for i in {it["page"] for it in items}}
            except Exception:
                pass
            self.rows = roof.summary_rows(items, self.pct(), labels) \
                if items else []
        self.table.setRowCount(0)
        for r in self.rows:
            n = self.table.rowCount()
            self.table.insertRow(n)
            for c, x in enumerate(r):
                if isinstance(x, float):
                    x = f"{x:,.4f}" if roof.HEADERS[c] == "Factor" \
                        else f"{x:,.2f}"
                self.table.setItem(n, c, QTableWidgetItem(
                    "" if x is None else str(x)))
        return self.rows

    def export(self, path=None):
        if not self.rows:
            QMessageBox.information(self, "Roof Summary",
                                    "Tag some roof measurements first.")
            return None
        if not path:
            import os
            from .reportname import report_file_name
            proj = os.path.splitext(os.path.basename(getattr(
                getattr(self.dlg, "win", None), "_path", "") or ""))[0]
            path, _ = QFileDialog.getSaveFileName(
                self, "Export Roof Summary",
                report_file_name("Roof Summary", proj, ext=".xlsx"),
                "Excel (*.xlsx);;CSV (*.csv)")
        if not path:
            return None
        roof.export_summary(path, self.rows)
        return path


class RoofDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Roof Plan Takeoff")
        self.resize(820, 620)
        v = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tag = TagTab(self)
        self.summary = SummaryTab(self)
        self.tabs.addTab(self.tag, "Roof Items")
        self.tabs.addTab(self.summary, "Summary")
        v.addWidget(self.tabs, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.tag.refresh()
        self.summary.refresh()
