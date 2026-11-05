"""Takeoff > Try the Count Library: pick saved symbols and pages, find
them, and add what's found as counts in review (Nov 1). The logic is in
count_library.py; this is the window."""
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog,
                               QDialogButtonBox, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QProgressDialog, QPushButton,
                               QVBoxLayout)

from . import count_library

TITLE = "Count Library"


def _icon(png):
    img = QImage.fromData(png)
    return QIcon(QPixmap.fromImage(img)) if not img.isNull() else QIcon()


class CountLibraryDialog(QDialog):
    def __init__(self, view, parent=None):
        super().__init__(parent)
        self.view = view
        self.result = None                  # (kept, info) after a search
        self.setWindowTitle(TITLE)
        lay = QVBoxLayout(self)
        where = count_library.path()
        self.info = QLabel(
            "Symbols your company counts on every job. Tick the ones to "
            "look for: what's found comes in as counts in review (dashed, "
            "with the AI badge), out of every total until you accept them "
            "in the Review Queue. Add a symbol from a count's right-click "
            "menu (Add … to the Count Library).\n"
            f"Library: {where}" + (" (shared)" if count_library.is_shared()
                                    else ""))
        self.info.setWordWrap(True)
        lay.addWidget(self.info)
        self.list = QListWidget()
        self.list.setIconSize(QSize(48, 48))
        lay.addWidget(self.list)
        row = QHBoxLayout()
        self.all_btn = QPushButton("Tick All")
        self.all_btn.clicked.connect(lambda: self._tick_all(True))
        self.none_btn = QPushButton("Tick None")
        self.none_btn.clicked.connect(lambda: self._tick_all(False))
        self.remove_btn = QPushButton("Remove From Library…")
        self.remove_btn.clicked.connect(lambda: self.remove_selected())
        self.color_btn = QPushButton("Change Color…")
        self.color_btn.setToolTip("The color its counts come in on the "
                                  "next job")
        self.color_btn.clicked.connect(lambda: self.recolor_selected())
        for b in (self.all_btn, self.none_btn, self.color_btn,
                  self.remove_btn):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        prow = QHBoxLayout()
        prow.addWidget(QLabel("Look on:"))
        self.where = QComboBox()
        self.where.addItems(["This page", "All pages", "Pages…"])
        self.where.setCurrentIndex(1)
        self.pages_edit = QLineEdit()
        self.pages_edit.setPlaceholderText("e.g. 3-7, 9")
        self.pages_edit.setEnabled(False)
        self.where.currentIndexChanged.connect(
            lambda i: self.pages_edit.setEnabled(i == 2))
        prow.addWidget(self.where)
        prow.addWidget(self.pages_edit, 1)
        lay.addLayout(prow)
        bb = QDialogButtonBox()
        self.find_btn = bb.addButton("Find", QDialogButtonBox.AcceptRole)
        bb.addButton(QDialogButtonBox.Close)
        self.find_btn.clicked.connect(lambda: self.run())
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.resize(520, 520)
        self.fill()

    # ---- list -------------------------------------------------------------
    def fill(self):
        self.list.clear()
        for e in count_library.entries():
            it = QListWidgetItem(_icon(e["png"]), e["name"])
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            if e.get("color"):
                from PySide6.QtGui import QBrush, QColor
                it.setForeground(QBrush(QColor.fromRgbF(*e["color"])))
            bits = [b for b in (e.get("added"), e.get("by")) if b]
            if bits:
                it.setToolTip("Added " + ", ".join(bits))
            self.list.addItem(it)
        empty = self.list.count() == 0
        self.find_btn.setEnabled(not empty)
        if empty:
            it = QListWidgetItem("The library is empty. Count a symbol with "
                                 "Count Symbol, then right-click one of its "
                                 "counts > Add … to the Count Library.")
            it.setFlags(Qt.NoItemFlags)
            self.list.addItem(it)

    def recolor_selected(self, color=None):
        """The selected entry's count color (asked when not given)."""
        it = self.list.currentItem()
        if it is None or not it.flags() & Qt.ItemIsUserCheckable:
            return False
        if color is None:
            from PySide6.QtWidgets import QColorDialog
            c = QColorDialog.getColor(parent=self)
            if not c.isValid():
                return False
            color = [c.redF(), c.greenF(), c.blueF()]
        ok = count_library.set_color(it.text(), color)
        self.fill()
        return ok

    def _tick_all(self, on):
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.flags() & Qt.ItemIsUserCheckable:
                it.setCheckState(Qt.Checked if on else Qt.Unchecked)

    def chosen(self):
        return [self.list.item(i).text() for i in range(self.list.count())
                if self.list.item(i).flags() & Qt.ItemIsUserCheckable and
                self.list.item(i).checkState() == Qt.Checked]

    def remove_selected(self, ask=True):
        it = self.list.currentItem()
        if it is None or not it.flags() & Qt.ItemIsUserCheckable:
            return False
        name = it.text()
        if ask and QMessageBox.question(
                self, TITLE, f"Remove {name} from the count library?"
                + (" Everyone using the shared library loses it."
                   if count_library.is_shared() else "")) != \
                QMessageBox.Yes:
            return False
        count_library.remove(name)
        self.fill()
        return True

    def pages(self):
        from .count_several import parse_pages
        i = self.where.currentIndex()
        if i == 0:
            return {self.view.page}
        if i == 1:
            return None
        got = parse_pages(self.pages_edit.text(), self.view.doc.page_count)
        return got if got else {self.view.page}

    # ---- search -----------------------------------------------------------
    def run(self, quiet=False):
        """Find the ticked symbols and add them as counts in review.
        Returns the number of counts added."""
        names = self.chosen()
        if not names:
            if not quiet:
                QMessageBox.information(self, TITLE, "Tick a symbol first.")
            return 0
        prog = QProgressDialog("Looking…", "Stop", 0, len(names), self)
        prog.setWindowTitle(TITLE)
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(400)

        def step(i, n, name):
            prog.setValue(i)
            prog.setLabelText(f"Looking for {name} ({i + 1} of {n})")
            QApplication.processEvents()
            return not prog.wasCanceled()
        try:
            kept, info = count_library.try_on(self.view.doc, self.pages(),
                                              names, progress=step)
        except RuntimeError as e:
            prog.close()
            if not quiet:
                QMessageBox.warning(self, TITLE, str(e))
            return 0
        prog.close()
        self.result = (kept, info)
        marks = count_library.review_marks(kept, self.view.doc)
        n = self.view.apply_marks(marks) if marks else 0
        found = [(name, len(h)) for name, h in kept.items() if h]
        lines = [f"{c} × {name}" for name, c in found]
        if info.get("already"):
            lines.append(f"{info['already']} already counted - left as "
                         "they are")
        if info.get("stopped"):
            lines.append("Stopped before every symbol was looked for.")
        msg = ("Found, as counts in review (not in the totals until "
               "accepted in AI Takeoff > Review Queue):\n" +
               "\n".join(lines)) if found else \
            "None of the ticked symbols were found (or every copy is " \
            "already counted).\n" + "\n".join(lines)
        self.view.status.emit(f"Count library: {n} count(s) added for "
                              "review" if n else "Count library: nothing "
                              "new found")
        if not quiet:
            QMessageBox.information(self, TITLE, msg)
        if n:
            self.accept()
        return n


def open_dialog(win, show=True):
    v = getattr(win, "_view", None)
    if not v:
        return None
    dlg = CountLibraryDialog(v, win)
    if show:
        dlg.exec()
    return dlg
