"""Energy Code window (Module tab): climate zone by county, the Code
Library (your own code books, searchable) and where to read the code."""
import html
import logging

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QApplication, QComboBox, QCompleter, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSplitter,
    QTabWidget, QTextBrowser, QVBoxLayout, QWidget)

from . import codelib, energy

log = logging.getLogger(__name__)


class ClimateTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        f = QFormLayout()
        self.state = QComboBox()
        for s in energy.states():
            self.state.addItem(f"{energy.STATE_NAMES.get(s, s)} ({s})", s)
        self.county = QComboBox()
        self.county.setEditable(True)
        self.county.setInsertPolicy(QComboBox.NoInsert)
        f.addRow("State:", self.state)
        f.addRow("County:", self.county)
        v.addLayout(f)
        self.out = QLabel("")
        self.out.setWordWrap(True)
        self.out.setTextFormat(Qt.RichText)
        self.out.setStyleSheet("font-size: 12pt; padding: 10px 0;")
        v.addWidget(self.out)
        src = QLabel(energy.data()["source"] + ". The zone sets the "
                     "insulation, window and air-sealing requirements in "
                     "the IECC tables - look them up in the Code Library.")
        src.setWordWrap(True)
        src.setStyleSheet("color: #777;")
        v.addWidget(src)
        v.addStretch()
        self.state.currentIndexChanged.connect(self._fill)
        self.county.currentTextChanged.connect(self.lookup)
        i = self.state.findData("PA")
        self.state.setCurrentIndex(max(i, 0))
        self._fill()

    def _fill(self, *_):
        st = self.state.currentData()
        self.county.blockSignals(True)
        self.county.clear()
        names = energy.counties(st)
        self.county.addItems(names)
        c = QCompleter(names, self.county)
        c.setCaseSensitivity(Qt.CaseInsensitive)
        c.setFilterMode(Qt.MatchContains)
        self.county.setCompleter(c)
        self.county.blockSignals(False)
        self.lookup()

    def lookup(self, *_):
        z = energy.zone(self.state.currentData(), self.county.currentText())
        if not z:
            self.out.setText("<i>Pick a county.</i>")
            return None
        txt = f"<b>{html.escape(z['county'])}, {z['state']}: climate " \
              f"zone {html.escape(z['zone'])}</b>"
        if z["moisture"]:
            txt += f" ({z['moisture'].lower()})"
        txt += f"<br>Building America zone: {html.escape(z['ba'])}"
        if z["was"] and z["was"] != z["zone"]:
            txt += f"<br>Was {html.escape(z['was'])} before the 2021 IECC " \
                   "(check which edition your jurisdiction adopted)."
        if z["note"]:
            txt += f"<br><span style='color:#b36b00'>" \
                   f"{html.escape(z['note'])}</span>"
        self.out.setText(txt)
        return z


class LibraryTab(QWidget):
    def __init__(self, parent=None, open_pdf=None):
        super().__init__(parent)
        self.open_pdf = open_pdf
        v = QVBoxLayout(self)
        top = QHBoxLayout()
        self.book = QComboBox()
        top.addWidget(QLabel("Book:"))
        top.addWidget(self.book, 1)
        for label, fn in (("Add Book…", self.add), ("Remove", self.remove)):
            b = QPushButton(label)
            b.clicked.connect(lambda _c=False, _f=fn: _f())
            top.addWidget(b)
        v.addLayout(top)
        self.q = QLineEdit()
        self.q.setPlaceholderText("Section (R402.1.2, C402.4, TABLE "
                                  "R402.1.3) or words (ceiling R-value, "
                                  "fenestration U-factor)")
        self.q.setClearButtonEnabled(True)
        self.q.textChanged.connect(self.search)
        v.addWidget(self.q)
        split = QSplitter(Qt.Horizontal)
        self.hits = QListWidget()
        self.hits.currentItemChanged.connect(self._show)
        split.addWidget(self.hits)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        self.view = QTextBrowser()
        rv.addWidget(self.view, 1)
        row = QHBoxLayout()
        self.go = QPushButton("Open the Page in the Book")
        self.go.clicked.connect(self._open)
        row.addWidget(self.go)
        cp = QPushButton("Copy Section")
        cp.clicked.connect(self._copy)
        row.addWidget(cp)
        row.addStretch()
        rv.addLayout(row)
        split.addWidget(right)
        split.setSizes([380, 700])
        v.addWidget(split, 1)
        note = QLabel("Add code books you own (IECC, IBC, IRC, your state's "
                      "energy code). They stay on this PC, in your own "
                      "folder - code books are copyrighted and QuantiSheet "
                      "never shares them.")
        note.setWordWrap(True)
        note.setStyleSheet("color: #777;")
        v.addWidget(note)
        self.cur = None
        self.reload()

    def reload(self):
        self.book.blockSignals(True)
        self.book.clear()
        self.book.addItem("All books", None)
        for b in codelib.books():
            self.book.addItem(f"{b['name']} ({b['sections'] or 0} "
                              "sections)", b["name"])
        self.book.blockSignals(False)
        self.book.currentIndexChanged.connect(self.search)
        if self.book.count() == 1:
            self.view.setHtml("<p>No code books yet. Click <b>Add Book…</b> "
                              "and pick a code PDF you own (with text - "
                              "run OCR on a scan first).</p>")
        self.search()

    def add(self, path=None, name=None):
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "Add a Code Book",
                                                  "", "PDF (*.pdf)")
        if not path:
            return None
        if name is None:
            import os
            name, ok = QInputDialog.getText(
                self, "Add a Code Book", "Name it (e.g. 2021 IECC):",
                text=os.path.splitext(os.path.basename(path))[0])
            if not ok:
                return None
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            b = codelib.add_book(path, name)
        except Exception as e:                            # noqa: BLE001
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Add a Code Book", str(e))
            return None
        QApplication.restoreOverrideCursor()
        self.reload()
        QMessageBox.information(self, "Add a Code Book",
                                f"{b['name']}: {b['sections']} sections "
                                "indexed.")
        return b

    def remove(self):
        name = self.book.currentData()
        if not name:
            return
        if QMessageBox.question(self, "Remove", f"Remove {name} from the "
                                "Code Library on this PC?") != \
                QMessageBox.Yes:
            return
        codelib.remove_book(name)
        self.reload()

    def search(self, *_):
        q = self.q.text().strip()
        self.hits.clear()
        if not q:
            return
        for name, pdf, s in codelib.search(q, self.book.currentData()):
            it = QListWidgetItem(f"{s['id']}  {s['title']}   — {name}")
            it.setData(Qt.UserRole, (name, pdf, s))
            self.hits.addItem(it)
        if self.hits.count():
            self.hits.setCurrentRow(0)
        else:
            self.view.setHtml("<p>No section matches.</p>")

    def _show(self, it, _old=None):
        if it is None:
            return
        name, pdf, s = it.data(Qt.UserRole)
        self.cur = (pdf, s)
        self.view.setHtml(
            f"<h3>{html.escape(s['id'])} {html.escape(s['title'])}</h3>"
            f"<p style='color:#777'>{html.escape(name)}, page "
            f"{s['page']}</p><p>{html.escape(s['text'])}</p>"
            "<p style='color:#777'>Tables and figures read best in the "
            "book itself - Open the Page in the Book.</p>")

    def _open(self):
        if self.cur and self.open_pdf:
            self.open_pdf(*self.cur[0:1], self.cur[1]["page"])

    def _copy(self):
        if self.cur:
            s = self.cur[1]
            QGuiApplication.clipboard().setText(
                f"{s['id']} {s['title']}. {s['text']}")


class ReadTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.addWidget(QLabel("The energy code itself belongs to the ICC (IECC) "
                           "and ASHRAE (90.1). ICC lets anyone read the "
                           "I-Codes free online; the Department of Energy "
                           "shows what each state has adopted."))
        for label, url in energy.LINKS.items():
            b = QPushButton(label)
            b.setToolTip(url)
            b.clicked.connect(lambda _=False, u=url:
                              QDesktopServices.openUrl(QUrl(u)))
            v.addWidget(b)
        v.addStretch()


class EnergyDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Energy Code")
        self.resize(1050, 700)
        v = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.climate = ClimateTab()
        self.library = LibraryTab(open_pdf=self._open_pdf)
        self.tabs.addTab(self.climate, "Climate Zone")
        self.tabs.addTab(self.library, "Code Library")
        self.tabs.addTab(ReadTab(), "Read the Code Online")
        v.addWidget(self.tabs, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.close)
        v.addWidget(bb)

    def _open_pdf(self, path, page):
        win = self.parent()
        if win is not None and hasattr(win, "open_path") and \
                win.open_path(path):
            win._go_page(int(page) - 1)
