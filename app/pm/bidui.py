"""Bidding pages in Project Center: the Bid Calendar, and making bid
packages for many trades at once."""
import datetime as _dt
import os

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QBrush, QColor, QTextCharFormat
from PySide6.QtWidgets import (QAbstractItemView, QCalendarWidget,
                               QCheckBox, QComboBox, QDateEdit, QDialog,
                               QDialogButtonBox, QFileDialog, QFrame,
                               QHBoxLayout, QHeaderView, QLabel,
                               QListWidget, QListWidgetItem, QPushButton,
                               QSplitter, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from .. import icons
from . import bidforms

# (CSI section, trade, bid form template)
TRADES = [
    ("01 50 00", "Temporary facilities", "General - lump sum"),
    ("02 41 00", "Demolition", "General - lump sum"),
    ("03 30 00", "Cast-in-place concrete", "Concrete"),
    ("04 20 00", "Masonry", "General - lump sum"),
    ("05 12 00", "Structural steel", "General - lump sum"),
    ("05 50 00", "Metal fabrications", "General - lump sum"),
    ("06 10 00", "Rough carpentry", "General - lump sum"),
    ("06 40 00", "Architectural woodwork", "General - lump sum"),
    ("07 21 00", "Insulation", "General - lump sum"),
    ("07 50 00", "Roofing", "General - lump sum"),
    ("07 92 00", "Joint sealants", "General - lump sum"),
    ("08 11 00", "Doors, frames & hardware", "General - lump sum"),
    ("08 80 00", "Glazing & storefront", "General - lump sum"),
    ("09 29 00", "Drywall & framing", "General - lump sum"),
    ("09 51 00", "Acoustical ceilings", "General - lump sum"),
    ("09 65 00", "Resilient flooring", "General - lump sum"),
    ("09 91 00", "Painting", "General - lump sum"),
    ("10 00 00", "Specialties", "General - lump sum"),
    ("21 00 00", "Fire suppression", "General - lump sum"),
    ("22 00 00", "Plumbing", "Plumbing"),
    ("23 00 00", "HVAC", "Mechanical / HVAC"),
    ("26 00 00", "Electrical", "Electrical"),
    ("27 00 00", "Communications", "General - lump sum"),
    ("28 31 00", "Fire alarm", "General - lump sum"),
    ("31 00 00", "Earthwork", "Earthwork & paving"),
    ("31 23 19", "Dewatering", "General - lump sum"),
    ("32 12 00", "Asphalt paving", "Earthwork & paving"),
    ("32 16 00", "Curbs & sidewalks", "Earthwork & paving"),
    ("32 31 00", "Fencing", "General - lump sum"),
    ("32 90 00", "Landscaping", "General - lump sum"),
    ("33 10 00", "Water utilities", "Site utilities"),
    ("33 30 00", "Sanitary sewer", "Site utilities"),
    ("33 40 00", "Storm drainage", "Site utilities"),
    ("40 00 00", "Process piping", "General - lump sum"),
    ("43 00 00", "Process equipment", "General - lump sum"),
    ("46 00 00", "Water & wastewater equipment", "General - lump sum"),
]


def make_packages(store, picks):
    """One bid package per pick {csi, trade, form, due, scope}. Returns the
    saved records."""
    lib = bidforms.library()
    made = []
    for p in picks:
        trade = p.get("trade") or "Trade"
        csi = p.get("csi") or ""
        rec = {"title": trade,
               "trades": f"{csi} {trade}".strip(),
               "status": "Draft",
               "specs": csi,
               "scope": p.get("scope") or (
                   f"Furnish and install all {trade.lower()} work shown on "
                   "the drawings and specified"
                   + (f" in Section {csi}" if csi else "") +
                   ", complete, including all labor, material, equipment, "
                   "taxes, permits and cleanup.")}
        if p.get("due"):
            rec["due"] = p["due"]
        if p.get("form") and p["form"] in lib:
            rec["form"] = bidforms.clean(lib[p["form"]])
        made.append(store.save_record("bidpkg", rec))
    return made


class TradesDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Bid Packages from Trades")
        self.resize(560, 640)
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Tick the trades to bid. Each becomes a package "
                           "with its spec section, a standard scope and a "
                           "bid form to suit the trade - edit them after."))
        self.list = QListWidget()
        for csi, trade, form in TRADES:
            it = QListWidgetItem(f"{csi}   {trade}")
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Unchecked)
            it.setData(Qt.UserRole, (csi, trade, form))
            self.list.addItem(it)
        v.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.addWidget(QLabel("Bids due:"))
        self.due = QDateEdit(QDate.currentDate().addDays(14))
        self.due.setCalendarPopup(True)
        row.addWidget(self.due)
        self.forms = QCheckBox("Add each trade's bid form")
        self.forms.setChecked(True)
        row.addWidget(self.forms)
        row.addStretch()
        v.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Make Packages")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def check(self, trades):
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(Qt.UserRole)[1] in trades:
                it.setCheckState(Qt.Checked)

    def chosen(self):
        out = []
        due = self.due.date().toString("yyyy-MM-dd")
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.checkState() == Qt.Checked:
                csi, trade, form = it.data(Qt.UserRole)
                out.append({"csi": csi, "trade": trade, "due": due,
                            "form": form if self.forms.isChecked() else
                            None})
        return out


KIND_COLOR = {"Bids due": "#d92d20", "Pre-bid meeting": "#2563eb",
              "Questions due": "#b54708", "Site visit": "#12865a"}


class BidCalendarPage(QWidget):
    """Bid dates - bids due, pre-bid meetings, question cutoffs, site
    visits - for this project or every project on this PC."""

    def __init__(self, center):
        super().__init__()
        self.center = center
        self.store = center.store
        self.events = []
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        head = QFrame()
        head.setObjectName("pcPageHead")
        h = QHBoxLayout(head)
        h.setContentsMargins(18, 14, 18, 12)
        ic = QLabel()
        ic.setPixmap(icons.icon("calendar").pixmap(22, 22))
        h.addWidget(ic)
        t = QLabel("Bid Calendar")
        t.setObjectName("pcH1")
        h.addWidget(t)
        self.note = QLabel()
        self.note.setObjectName("muted")
        h.addWidget(self.note)
        h.addStretch()
        self.scope = QComboBox()
        self.scope.addItems(["This project", "All my projects"])
        self.scope.currentIndexChanged.connect(lambda _i: self.refresh())
        h.addWidget(self.scope)
        for label, icon, fn in (("Add to Outlook / phone (.ics)…", "export",
                                 self.export_ics),
                                ("Today", "calendar", self.today),
                                ("Refresh", "sync", self.refresh)):
            b = QPushButton(label)
            b.setIcon(icons.icon(icon))
            b.clicked.connect(lambda _=False, f=fn: f())
            h.addWidget(b)
        v.addWidget(head)
        split = QSplitter(Qt.Horizontal)
        self.cal = QCalendarWidget()
        self.cal.setGridVisible(True)
        self.cal.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)
        self.cal.selectionChanged.connect(self._fill)
        self.cal.currentPageChanged.connect(lambda *_: self._fill())
        split.addWidget(self.cal)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(8, 8, 8, 8)
        self.title = QLabel()
        self.title.setObjectName("pcH2")
        rv.addWidget(self.title)
        self.table = QTableWidget(0, 6)
        self.table.setObjectName("pcList")
        self.table.setHorizontalHeaderLabels(
            ["Date", "Time", "What", "Package", "Project", "Status"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch)
        self.table.doubleClicked.connect(self._open)
        rv.addWidget(self.table, 1)
        legend = QLabel("  ".join(
            f"<span style='color:{c}'>■</span> {k}"
            for k, c in KIND_COLOR.items()))
        rv.addWidget(legend)
        split.addWidget(right)
        split.setSizes([520, 700])
        v.addWidget(split, 1)
        self._marked = []

    def today(self):
        self.cal.setSelectedDate(QDate.currentDate())
        self.cal.showToday()

    def refresh(self):
        if self.scope.currentIndex() == 1:
            self.events = bidforms.all_events([self.store.folder])
        else:
            self.events = sorted(
                bidforms.events(self.store),
                key=lambda e: (e["date"], e["time"] or _dt.time(0, 0)))
        for d in self._marked:
            self.cal.setDateTextFormat(d, QTextCharFormat())
        self._marked = []
        by = {}
        for e in self.events:
            by.setdefault(e["date"], []).append(e)
        for d, es in by.items():
            fmt = QTextCharFormat()
            kinds = [e["kind"] for e in es]
            col = KIND_COLOR["Bids due"] if "Bids due" in kinds else \
                KIND_COLOR.get(kinds[0], "#2563eb")
            fmt.setForeground(QBrush(QColor("white")))
            fmt.setBackground(QBrush(QColor(col)))
            fmt.setFontWeight(700)
            qd = QDate(d.year, d.month, d.day)
            self.cal.setDateTextFormat(qd, fmt)
            self._marked.append(qd)
        up = [e for e in self.events if e["date"] >= _dt.date.today()]
        due = [e for e in up if e["kind"] == "Bids due"]
        self.note.setText(f"{len(due)} bid date(s) ahead"
                          + (f" - next {due[0]['date']:%b %d}: "
                             f"{due[0]['title'][10:]}" if due else ""))
        self._fill()
        return self.events

    def _fill(self):
        sel = self.cal.selectedDate()
        start = _dt.date(sel.year(), sel.month(), sel.day())
        rows = [e for e in self.events if e["date"] >= start][:200]
        self.title.setText(f"From {start:%A, %B %d, %Y}")
        self.table.setRowCount(len(rows))
        self.rows = rows
        for i, e in enumerate(rows):
            vals = [f"{e['date']:%a %b %d}",
                    e["time"].strftime("%I:%M %p").lstrip("0")
                    if e["time"] else "", e["title"], e["package"],
                    e["project"], e["status"]]
            for c, val in enumerate(vals):
                it = QTableWidgetItem(val)
                if c == 2:
                    it.setForeground(QBrush(QColor(
                        KIND_COLOR.get(e["kind"], "#2563eb"))))
                self.table.setItem(i, c, it)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.Stretch)

    def _open(self, index):
        e = self.rows[index.row()]
        if os.path.normcase(e.get("folder") or "") == \
                os.path.normcase(self.store.folder):
            self.center.open_record("bidpkg", e["record"])

    def export_ics(self, path=None):
        if not path:
            path, _ = QFileDialog.getSaveFileName(
                self, "Bid Calendar", "Bid calendar.ics",
                "Calendar (*.ics)")
        if not path:
            return None
        bidforms.to_ics([e for e in self.events
                         if e["date"] >= _dt.date.today() -
                         _dt.timedelta(days=7)], path)
        self.center.toast("Saved - open it to add the dates to Outlook or "
                          "your phone.")
        return path
