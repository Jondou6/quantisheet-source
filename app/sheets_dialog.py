"""Sheet Setup: Auto Scale and Auto Bookmark (PlanSwift's Takeoff Boost)."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QHBoxLayout, QHeaderView,
                               QLabel, QProgressDialog, QTableWidget,
                               QTableWidgetItem, QVBoxLayout)

from . import sheets

NONE = "(no scale)"


def scan_with_progress(doc, parent=None):
    prog = QProgressDialog("Reading sheets…", "Cancel", 0, doc.page_count,
                           parent)
    prog.setWindowTitle("Sheet Setup")
    prog.setMinimumDuration(400)
    out = []
    for i in range(doc.page_count):
        if prog.wasCanceled():
            break
        prog.setValue(i)
        QApplication.processEvents()
        out += sheets.scan(doc, [i], numbers=False, keep_words=True)
    prog.setValue(doc.page_count)
    if len(out) > 2:
        sheets.fix_numbers(out, doc)
    for r in out:
        r.pop("words", None)
    return out


class SheetSetupDialog(QDialog):
    """Review what was read from each sheet before applying it."""

    def __init__(self, rows, parent=None, scales=True, bookmarks=True):
        super().__init__(parent)
        self.setWindowTitle("Sheet Setup - Auto Scale & Bookmarks")
        self.resize(860, 560)
        self.rows = rows
        lay = QVBoxLayout(self)
        found_s = sum(1 for r in rows if r["scale"])
        found_b = sum(1 for r in rows if r["label"])
        odd = [r for r in rows if r.get("odd")]
        warn = ""
        if odd:
            warn = (f"<br><b style='color:#c62828'>{len(odd)} sheet(s) show "
                    "a scale that isn't a standard drawing scale (marked "
                    "⚠). It was not set - check those sheets and pick or "
                    "calibrate the scale yourself.</b>")
        self.intro = QLabel(
            f"Read {len(rows)} page(s): found a sheet name on {found_b} and a "
            f"scale on {found_s}. Check and edit below, then OK.{warn}<br>"
            "<small>"
            "Where a sheet shows several scales, the plan's (smallest) one is "
            "picked; choose another from the list. Pages printed at reduced "
            "size (half-size sets) need Calibrate instead.</small>")
        self.intro.setWordWrap(True)        # was cut off (Chief, Nov 7)
        lay.addWidget(self.intro)
        self.table = QTableWidget(len(rows), 3)
        self.table.setHorizontalHeaderLabels(["Page", "Bookmark", "Scale"])
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.combos = []
        for r, row in enumerate(rows):
            it = QTableWidgetItem(str(row["page"] + 1))
            it.setFlags(Qt.ItemIsEnabled)
            self.table.setItem(r, 0, it)
            self.table.setItem(r, 1, QTableWidgetItem(row["label"]))
            combo = QComboBox()
            combo.addItem(NONE, None)
            seen = set()
            from . import takeoff
            for sc in row["scales"]:
                if sc[0] not in seen:
                    seen.add(sc[0])
                    std = takeoff.is_standard(sc[1], sc[2])
                    combo.addItem(sc[0] if std else f"⚠ {sc[0]} (unusual)",
                                  sc)
            if row["scale"]:
                combo.setCurrentIndex(combo.findText(row["scale"][0]))
            self.table.setCellWidget(r, 2, combo)
            self.combos.append(combo)
        self.table.resizeColumnToContents(0)
        self.table.setColumnWidth(2, 170)
        lay.addWidget(self.table)
        opts = QHBoxLayout()
        self.do_scales = QCheckBox("Set page scales")
        self.do_scales.setChecked(scales)
        self.do_bookmarks = QCheckBox("Add sheet bookmarks")
        self.do_bookmarks.setChecked(bookmarks)
        self.replace = QCheckBox("Replace existing bookmarks")
        opts.addWidget(self.do_scales)
        opts.addWidget(self.do_bookmarks)
        opts.addWidget(self.replace)
        opts.addStretch()
        lay.addLayout(opts)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def scales(self):
        """{page: (label, points per unit, unit)} for pages with a scale."""
        out = {}
        for row, combo in zip(self.rows, self.combos):
            sc = combo.currentData()
            if sc:
                out[row["page"]] = sc
        return out

    def labels(self):
        out = {}
        for r, row in enumerate(self.rows):
            it = self.table.item(r, 1)
            text = it.text().strip() if it else ""
            if text:
                out[row["page"]] = text
        return out
