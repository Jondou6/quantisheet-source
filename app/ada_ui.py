"""ADA window: the 2010 Standards to search and read, and the commercial
scoping checker. Works without a drawing open; with one, the checker's
answers are saved in the PDF."""
import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QSplitter, QTabWidget, QTableWidget,
    QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget)

from . import ada_check, ada_ref, ada_takeoff

log = logging.getLogger(__name__)
STATUS = {"ok": ("OK", QColor(222, 244, 222)),
          "short": ("Short", QColor(255, 220, 220)),
          "check": ("Check", QColor(255, 244, 214)),
          "info": ("Need", None)}


def _esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


class ReferenceTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.q = QLineEdit()
        self.q.setPlaceholderText("Section number (404.2.3) or words "
                                  "(door maneuvering, van parking, grab "
                                  "bars)")
        self.q.setClearButtonEnabled(True)
        self.q.textChanged.connect(self.search)
        row.addWidget(self.q, 1)
        self.chap = QComboBox()
        self.chap.addItem("All chapters", None)
        self.chap.addItem("DOJ rules (28 CFR 35.151, 36.401-406)", 0)
        for n in range(1, 11):
            self.chap.addItem(f"Chapter {n}: {ada_ref.chapter_name(n)}", n)
        self.chap.currentIndexChanged.connect(self.search)
        row.addWidget(self.chap)
        lay.addLayout(row)
        split = QSplitter(Qt.Horizontal)
        self.hits = QListWidget()
        self.hits.currentItemChanged.connect(self._show)
        split.addWidget(self.hits)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        self.view = QTextBrowser()
        self.view.setOpenLinks(False)
        self.view.anchorClicked.connect(lambda u: self.open(u.toString()))
        rv.addWidget(self.view, 1)
        btns = QHBoxLayout()
        self.up = QPushButton("Up a level")
        self.up.clicked.connect(self._up)
        btns.addWidget(self.up)
        cp = QPushButton("Copy Section")
        cp.clicked.connect(self._copy)
        btns.addWidget(cp)
        cc = QPushButton("Copy Citation")
        cc.clicked.connect(self._copy_cite)
        btns.addWidget(cc)
        self.pdf_btn = QPushButton("Show in the PDF (with figures)")
        self.pdf_btn.clicked.connect(self._show_pdf)
        btns.addWidget(self.pdf_btn)
        btns.addStretch()
        rv.addLayout(btns)
        split.addWidget(right)
        split.setSizes([380, 760])
        lay.addWidget(split, 1)
        src = QLabel(f"{ada_ref.data()['title']} - "
                     f"{ada_ref.data()['source']}. Text taken from the "
                     "PDF; the figures are in the original.")
        src.setWordWrap(True)
        src.setStyleSheet("color: #777;")
        lay.addWidget(src)
        self.cur = None
        self.search()

    def search(self, *_):
        q = self.q.text().strip()
        chap = self.chap.currentData()
        if q:
            found = ada_ref.search(q, limit=300)
        else:                       # nothing typed: the chapter-level list
            found = [s for s in ada_ref.sections()
                     if "." not in s["id"] or s["id"].startswith("DOJ")]
        if chap is not None:
            found = [s for s in found if s["chapter"] == chap]
        self.hits.clear()
        for s in found:
            it = QListWidgetItem(f"{s['id']}  {s['title']}")
            it.setData(Qt.UserRole, s["id"])
            it.setToolTip(ada_ref.snippet(s, q) if q else s["title"])
            self.hits.addItem(it)
        if found:
            self.hits.setCurrentRow(0)
        else:
            self.view.setHtml("<p>No section matches.</p>")

    def _show(self, it, _old=None):
        if it is not None:
            self.open(it.data(Qt.UserRole), select=False)

    def open(self, sid, select=True):
        s = ada_ref.find(sid)
        if not s:
            return
        self.cur = s
        words = [w for w in self.q.text().lower().split() if len(w) > 2]

        def mark(t):
            t = _esc(t)
            for w in words:
                lo = t.lower()
                i = lo.find(w)
                if i >= 0:
                    t = t[:i] + "<b>" + t[i:i + len(w)] + "</b>" + \
                        t[i + len(w):]
            return t.replace("\n", "<br>")
        par = ada_ref.parent(s["id"])
        html = [f"<h2>{_esc(s['id'])} {_esc(s['title'])}</h2>"]
        if par:
            html.append(f"<p>In <a href='{par['id']}'>{par['id']} "
                        f"{_esc(par['title'])}</a></p>")
        chap = ada_ref.chapter_name(s["chapter"])
        html.append(f"<p style='color:#777'>{_esc(chap)} - page "
                    f"{s['page']} of the DOJ PDF</p>")
        html.append(f"<p>{mark(s['text'])}</p>")
        if s.get("advisory"):
            html.append("<div style='background:#f3f3f3; padding:6px'>"
                        f"<p><i>{mark(s['advisory'])}</i></p>"
                        "<p style='color:#777'>Advisories explain; they "
                        "are not requirements.</p></div>")
        kids = ada_ref.children(s["id"])
        if kids:
            html.append("<p><b>In this section:</b><br>" + "<br>".join(
                f"<a href='{k['id']}'>{k['id']} {_esc(k['title'])}</a>"
                for k in kids) + "</p>")
        self.view.setHtml("".join(html))
        self.up.setEnabled(par is not None)
        if select:
            for i in range(self.hits.count()):
                if self.hits.item(i).data(Qt.UserRole) == s["id"]:
                    self.hits.blockSignals(True)
                    self.hits.setCurrentRow(i)
                    self.hits.blockSignals(False)
                    break

    def _show_pdf(self):
        win = self.window().parent()
        if self.cur and win is not None and hasattr(win, "ada_pdf"):
            win.ada_pdf(self.cur["page"])

    def _up(self):
        if self.cur:
            p = ada_ref.parent(self.cur["id"])
            if p:
                self.open(p["id"])

    def _copy(self):
        if self.cur:
            s = self.cur
            QGuiApplication.clipboard().setText(
                f"{s['id']} {s['title']}. {s['text']}\n"
                f"({ada_ref.cite(s['id'])})")

    def _copy_cite(self):
        if self.cur:
            QGuiApplication.clipboard().setText(ada_ref.cite(self.cur["id"]))


def _num(edit):
    t = edit.text().strip()
    return t if t else None


class ListTable(QWidget):
    """A small table of rows the user adds (parking lots, toilet rooms,
    assembly areas)."""

    def __init__(self, cols, title, parent=None):
        super().__init__(parent)
        self.cols = cols                      # [(key, header)]
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.addWidget(QLabel(f"<b>{title}</b>"))
        row.addStretch()
        for label, fn in (("Add", self.add), ("Remove", self.remove)):
            b = QPushButton(label)
            b.clicked.connect(lambda _c=False, _f=fn: _f())
            row.addWidget(b)
        v.addLayout(row)
        self.t = QTableWidget(0, len(cols))
        self.t.setHorizontalHeaderLabels([h for _k, h in cols])
        self.t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.t.setMaximumHeight(130)
        v.addWidget(self.t)

    def add(self, values=None):
        r = self.t.rowCount()
        self.t.insertRow(r)
        for c, (k, _h) in enumerate(self.cols):
            v = (values or {}).get(k, "")
            self.t.setItem(r, c, QTableWidgetItem("" if v is None else
                                                  str(v)))

    def remove(self):
        r = self.t.currentRow()
        if r >= 0:
            self.t.removeRow(r)

    def rows(self):
        out = []
        for r in range(self.t.rowCount()):
            d = {}
            for c, (k, _h) in enumerate(self.cols):
                it = self.t.item(r, c)
                v = it.text().strip() if it else ""
                if v != "":
                    d[k] = v
            if d:
                out.append(d)
        return out

    def set_rows(self, rows):
        self.t.setRowCount(0)
        for d in rows or []:
            if isinstance(d, dict):
                self.add(d)


# (key, label) for the plain number fields, by box
FIELDS = [
    ("Building", [("stories", "Stories"),
                  ("sf_per_story", "Sq ft per story (largest)"),
                  ("public_entrances", "Public entrances"),
                  ("accessible_entrances", "  of them accessible"),
                  ("tenant_spaces", "Tenant spaces"),
                  ("loading_zone_ft", "Passenger loading zone, ft"),
                  ("loading_accessible", "  accessible zones")]),
    ("Fixtures & rooms", [("drinking_fountains", "Drinking fountains"),
                          ("fountains_low", "  wheelchair height"),
                          ("fountains_high", "  standing height"),
                          ("single_user_toilets_cluster",
                           "Single-user toilets in a cluster"),
                          ("dressing_rooms", "Dressing/fitting rooms"),
                          ("dressing_rooms_accessible", "  accessible"),
                          ("lockers", "Lockers"),
                          ("lockers_accessible", "  accessible")]),
    ("Dining, counters", [("dining_seats", "Dining seats"),
                          ("dining_accessible", "  accessible"),
                          ("work_surfaces", "Public work surfaces"),
                          ("work_accessible", "  accessible"),
                          ("counter_types", "Sales/service counter types"),
                          ("counters_accessible", "  accessible"),
                          ("checkout_aisles", "Check-out aisles")]),
    ("Lodging, housing, medical", [
                          ("guest_rooms", "Guest rooms"),
                          ("mobility_tub", "  mobility, no roll-in"),
                          ("mobility_rollin", "  mobility, roll-in shower"),
                          ("communication_rooms", "  communication"),
                          ("dwelling_units", "Dwelling units"),
                          ("mobility_units", "  mobility"),
                          ("communication_units", "  communication"),
                          ("patient_rooms", "Patient/resident rooms"),
                          ("patient_rooms_accessible", "  mobility")]),
]


class CheckerTab(QWidget):
    edited = Signal()

    def __init__(self, doc=None, parent=None, open_section=None):
        super().__init__(parent)
        self.doc = doc
        self.open_section = open_section
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        form = QFormLayout()
        self.use = QComboBox()
        for k, v in ada_check.USES.items():
            self.use.addItem(v, k)
        form.addRow("Use:", self.use)
        self.title = QComboBox()
        self.title.addItem("Private - Title III (public accommodation, "
                           "commercial)", "III")
        self.title.addItem("Public - Title II (state or local "
                           "government)", "II")
        form.addRow("Owner:", self.title)
        self.elev = QComboBox()
        self.elev.addItems(["Not said", "Elevator provided",
                            "No elevator"])
        form.addRow("Elevator:", self.elev)
        self.alarm = QCheckBox("Fire alarm with audible coverage")
        self.alarm.setChecked(True)
        form.addRow(self.alarm)
        top.addLayout(form)
        how = QLabel("Type the counts from the drawings. Leave a \"have\" "
                     "box empty to just see what's required. Fractions "
                     "round up (104.2). Each line names the section - "
                     "double-click it to read it.")
        how.setWordWrap(True)
        how.setStyleSheet("color: #555;")
        top.addWidget(how, 1)
        lay.addLayout(top)
        grid = QGridLayout()
        self.ed = {}
        for col, (box, fields) in enumerate(FIELDS):
            g = QGroupBox(box)
            f = QFormLayout(g)
            for k, label in fields:
                e = QLineEdit()
                e.setMaximumWidth(80)
                f.addRow(label + ":", e)
                self.ed[k] = e
            grid.addWidget(g, 0, col)
        lay.addLayout(grid)
        lists = QHBoxLayout()
        self.parking = ListTable([("name", "Parking facility"),
                                  ("total", "Spaces"),
                                  ("accessible", "Accessible"),
                                  ("van", "Van")], "Parking")
        self.toilets = ListTable([("name", "Toilet room"),
                                  ("compartments", "Stalls"),
                                  ("urinals", "Urinals"),
                                  ("lavatories", "Lavs"),
                                  ("wheelchair_compartments", "WC stalls"),
                                  ("ambulatory_compartments", "Amb. stalls")],
                                 "Toilet rooms")
        self.assembly = ListTable([("name", "Assembly area"),
                                   ("seats", "Seats"),
                                   ("wheelchair_spaces", "W/C spaces"),
                                   ("companion_seats", "Companion"),
                                   ("aisle_seats", "Aisle seats"),
                                   ("designated_aisle", "Designated"),
                                   ("receivers", "Receivers"),
                                   ("hac_receivers", "Hearing-aid")],
                                  "Assembly seating")
        for w in (self.parking, self.toilets, self.assembly):
            lists.addWidget(w)
        lay.addLayout(lists)
        self.summary = QLabel("")
        lay.addWidget(self.summary)
        self.found = QTableWidget(0, 5)
        self.found.setHorizontalHeaderLabels(
            ["", "Requirement", "Need", "Have", "Section"])
        hh = self.found.horizontalHeader()
        hh.setSectionResizeMode(1, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.found.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.found.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.found.itemDoubleClicked.connect(self._read)
        lay.addWidget(self.found, 1)
        row = QHBoxLayout()
        for label, fn in (("Fill From Drawings", self.fill),
                          ("Run Check", self.run),
                          ("Mark Up Short Items on Drawings", self.mark_up),
                          ("Save Report…", self.report)):
            b = QPushButton(label)
            b.clicked.connect(lambda _c=False, _f=fn: _f())
            b.setEnabled(self.doc is not None or label in ("Run Check",
                                                           "Save Report…"))
            row.addWidget(b)
        row.addStretch()
        note = QLabel("2010 ADA Standards. Screening aid - alterations, "
                      "historic buildings, exceptions and your adopted "
                      "code decide.")
        note.setStyleSheet("color: #777;")
        row.addWidget(note)
        lay.addLayout(row)
        self.findings = []
        self.refresh()

    def refresh(self):
        p = ada_check.read(self.doc) if self.doc is not None else {}
        i = self.use.findData(p.get("use", "office"))
        self.use.setCurrentIndex(max(i, 0))
        self.title.setCurrentIndex(1 if str(p.get("title")) == "II" else 0)
        e = p.get("elevator")
        self.elev.setCurrentIndex(0 if e in (None, "") else 1 if e else 2)
        self.alarm.setChecked(bool(p.get("fire_alarm", True)))
        for k, ed in self.ed.items():
            v = p.get(k)
            ed.setText("" if v is None else str(v))
        self.parking.set_rows(p.get("parking"))
        self.toilets.set_rows(p.get("toilet_rooms"))
        self.assembly.set_rows(p.get("assembly_areas"))
        self.run(save=False)

    def project(self):
        p = {"use": self.use.currentData(), "title": self.title.currentData(),
             "fire_alarm": self.alarm.isChecked(),
             "parking": self.parking.rows(),
             "toilet_rooms": self.toilets.rows(),
             "assembly_areas": self.assembly.rows()}
        e = self.elev.currentIndex()
        if e:
            p["elevator"] = e == 1
        for k, ed in self.ed.items():
            v = _num(ed)
            if v is not None:
                p[k] = v
        return p

    def run(self, save=True):
        p = self.project()
        self.findings = ada_check.check(p)
        if self.doc is not None:        # measured sizes on the drawings
            try:
                self.findings += ada_takeoff.elements(self.doc)
            except Exception:                             # noqa: BLE001
                log.warning("ADA measured elements not read", exc_info=True)
        self.found.setRowCount(0)
        for f in self.findings:
            r = self.found.rowCount()
            self.found.insertRow(r)
            label, color = STATUS[f.status]
            vals = [label, f"{f.group}: {f.item}", str(f.required),
                    "" if f.provided is None else str(f.provided), f.cite]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c == 1 and f.note:
                    it.setToolTip(f.note)
                if color is not None:
                    it.setBackground(color)
                self.found.setItem(r, c, it)
        s = ada_check.summary(self.findings)
        self.summary.setText(f"<b>{s['short']}</b> short, {s['ok']} OK, "
                             f"{s['to_check']} to check on the drawings")
        if save and self.doc is not None:
            try:
                ada_check.write(self.doc, p)
                self.edited.emit()
            except Exception:                             # noqa: BLE001
                log.warning("ADA check not saved", exc_info=True)

    def fill(self):
        """The counts from the takeoff (by group name) into the boxes."""
        if self.doc is None:
            return
        got = ada_takeoff.counts(self.doc)
        if not got:
            QMessageBox.information(
                self, "Fill From Drawings",
                "No ADA counts found. Name count groups like \"Parking\", "
                "\"Accessible Parking\", \"Van Parking\", \"WC - Men\", "
                "\"Urinal - Men\", \"Lavatory - Men\", \"Seat\", "
                "\"Entrance\", \"Drinking Fountain\", \"Guest Room\" or "
                "\"Dwelling Unit\".")
            return
        filled = []
        for k, v in got.items():
            if k in self.ed:
                self.ed[k].setText(str(v))
                filled.append(k.replace("_", " "))
        for key, table in (("parking", self.parking),
                           ("toilet_rooms", self.toilets),
                           ("assembly_areas", self.assembly)):
            if key in got:
                table.set_rows(got[key])
                filled.append(f"{len(got[key])} {key.replace('_', ' ')}")
        self.run()
        QMessageBox.information(self, "Fill From Drawings",
                                "Filled from the drawings: " +
                                ", ".join(filled) + ".")

    def mark_up(self):
        if self.doc is None:
            return
        from . import settings
        n = ada_takeoff.markup(self.doc, self.findings, settings.author())
        if n:
            self.edited.emit()
        QMessageBox.information(
            self, "ADA Check", f"{n} cloud(s) added around measured items "
            "that fall short." if n else "Nothing measured falls short. "
            "Measure sizes in groups like \"Door Clear Width\", "
            "\"Accessible Route\" or \"Turning Space\" to check them.")

    def _read(self, it):
        f = self.findings[it.row()] if it.row() < len(self.findings) else None
        if f and self.open_section:
            import re
            m = re.search(r"\d{3,4}(?:\.\d+)*", f.cite)
            if m:
                self.open_section(m.group(0))

    def report(self):
        import os
        from .reportname import report_file_name
        proj = os.path.splitext(os.path.basename(
            getattr(self, "doc", None) and self.doc.name or ""))[0]
        path, _ = QFileDialog.getSaveFileName(
            self, "Save ADA Report",
            report_file_name("ADA Check", proj, ext=".txt"), "Text (*.txt)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(ada_check.report_text(self.project(),
                                               self.findings))
        except OSError as e:
            QMessageBox.warning(self, "ADA Report", f"Not saved: {e}")


class AdaDialog(QDialog):
    edited = Signal()
    go_to = Signal(int, object)

    def __init__(self, doc=None, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.setWindowTitle("ADA - 2010 Standards for Accessible Design")
        self.resize(1200, 780)
        lay = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.ref = ReferenceTab()
        self.checker = CheckerTab(doc, open_section=self.read)
        self.checker.edited.connect(self.edited)
        self.tabs.addTab(self.ref, "Reference")
        self.tabs.addTab(self.checker, "Checker (commercial)")
        lay.addWidget(self.tabs, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.close)
        lay.addWidget(bb)

    def read(self, sid):
        self.tabs.setCurrentIndex(0)
        self.ref.q.setText(sid)
        self.ref.open(sid)

    def refresh(self):
        self.checker.refresh()
