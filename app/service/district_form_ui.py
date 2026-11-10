"""Map the form… (1.2, #5): show the district's form page, pick an
entry, click where it goes. open_window(parent) shows it."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDoubleSpinBox, QFileDialog, QHBoxLayout,
                               QLabel, QListWidget, QListWidgetItem,
                               QScrollArea)

from . import district_form as DF
from . import files, uiutil


class _Page(QLabel):
    """The form page; a click is passed on as a signal (no reference back
    to the window - a Python cycle between Qt widgets can crash when it
    is cleaned up)."""
    clicked = Signal(float, float)

    def __init__(self):
        super().__init__()
        self.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.setAccessibleName("Form page")

    def mousePressEvent(self, ev):                        # noqa: N802
        p = ev.position()
        self.clicked.emit(p.x(), p.y())


class MapFormWindow(uiutil.Desk):
    def __init__(self, parent=None):
        super().__init__("Map the District Form", parent)
        self.t = DF.load_template()
        self.zoom = 1.5
        self.root.addWidget(QLabel(
            "Pick an entry on the left, then click the top-left corner of "
            "its box on the form. Use your own copy of the form; it stays "
            "where it is and is never changed. Print the calibration page "
            "at actual size to check the fit."))
        row = QHBoxLayout()
        self.list = QListWidget()
        self.list.setAccessibleName("Entries")
        self.list.setMaximumWidth(300)
        row.addWidget(self.list)
        self.scroll = QScrollArea()
        self.page = _Page()
        self.page.clicked.connect(self.click_at)
        self.scroll.setWidget(self.page)
        self.scroll.setWidgetResizable(False)
        row.addWidget(self.scroll, 1)
        self.root.addLayout(row, 1)
        nud = QHBoxLayout()
        self.dx, self.dy = QDoubleSpinBox(), QDoubleSpinBox()
        for s, lab in ((self.dx, "Nudge right (pt)"),
                       (self.dy, "Nudge down (pt)")):
            s.setRange(-72, 72)
            s.setSingleStep(0.5)
            s.setAccessibleName(lab)
            nud.addWidget(QLabel(lab))
            nud.addWidget(s)
        nud.addStretch(1)
        self.root.addLayout(nud)
        self.dx.setValue((self.t.get("nudge") or [0, 0])[0])
        self.dy.setValue((self.t.get("nudge") or [0, 0])[1])
        self.buttons(("Pick the form PDF…", self.pick_clicked),
                     ("Save mapping", self.save_clicked),
                     ("Calibration print…", self.calib_clicked))
        self.finish()
        self.fill_list()
        self.show_page()

    def fill_list(self):
        cur = self.list.currentRow()
        self.list.clear()
        for key in DF.KEYS:
            mark = "✓ " if key in self.t["fields"] else "   "
            it = QListWidgetItem(mark + DF.LABELS[key])
            it.setData(Qt.UserRole, key)
            self.list.addItem(it)
        self.list.setCurrentRow(max(cur, 0))
        left = DF.missing(self.t)
        self.msg.setText(f"{len(DF.KEYS) - len(left)} of {len(DF.KEYS)} "
                         "entries placed." if self.t.get("form_path") else
                         "Pick your copy of the form to start.")

    def show_page(self):
        if not self.t.get("form_path"):
            self.page.setText("No form picked yet.")
            return False
        try:
            png, self.zoom = DF.page_image(self.t, self.zoom)
        except DF.FormError as e:
            self.page.setText(str(e))
            return False
        pm = QPixmap()
        pm.loadFromData(png)
        self.page.setPixmap(pm)
        self.page.resize(pm.size())
        return True

    def pick_clicked(self, _checked=False, path=None):
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Your copy of the district's form", files.path_for(""),
                "PDF (*.pdf)")
        if not path:
            return None
        if self.guard(lambda: DF.set_form(self.t, path)) is None:
            return None
        self.show_page()
        self.fill_list()
        return self.t

    def click_at(self, px, py):
        it = self.list.currentItem()
        if it is None or not self.t.get("form_path"):
            return None
        key = it.data(Qt.UserRole)
        box = DF.place(self.t, key, px / self.zoom, py / self.zoom)
        self.list.setCurrentRow(min(self.list.currentRow() + 1,
                                    self.list.count() - 1))
        self.fill_list()
        return box

    def save_clicked(self):
        self.t["nudge"] = [self.dx.value(), self.dy.value()]
        DF.save_template(self.t)
        try:
            DF.save_beside(self.t)
        except OSError:
            pass
        self.msg.setText("Mapping saved. " + (
            f"Not placed yet: {', '.join(DF.missing(self.t)[:6])}"
            + ("…" if len(DF.missing(self.t)) > 6 else "")
            if DF.missing(self.t) else "Every entry is placed."))
        return True

    def calib_clicked(self, _checked=False, path=None):
        self.t["nudge"] = [self.dx.value(), self.dy.value()]
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Calibration print", files.path_for(
                    "District form calibration.pdf"), "PDF (*.pdf)")
        if not path:
            return None
        out = self.guard(lambda: DF.calibration(path, self.t))
        if out:
            self.msg.setText(f"Saved {out} - print at actual size.")
        return out


def open_window(parent=None):
    return uiutil.show(MapFormWindow(parent))
