"""ClaimIT 0.2 screens (Jon, Oct 31: "make it better and easier to use"):
the start page, the new-claim wizard, the room editor, line kits, the
before-you-send checklist and Getting started.

Every dialog can be filled and read in code, so it runs headless under
QT_QPA_PLATFORM=offscreen (tests) as well as on screen.
"""
from __future__ import annotations

import datetime as _dt
import os

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDateEdit, QDialog, QDialogButtonBox,
    QFormLayout, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
    QTextBrowser, QVBoxLayout, QWidget)

from .. import checklist, kits, library, rooms, settings
from ..cents import MoneyError, parse_money

NO_DATE = QDate(1900, 1, 1)
PERILS = ("Water", "Wind", "Hail", "Fire", "Smoke", "Theft", "Vandalism",
          "Lightning", "Collapse", "Freeze", "Other")


# ------------------------------------------------------------------ start
class StartPage(QWidget):
    """What the window shows when no claim is open."""
    new_residential = Signal()
    new_commercial = Signal()
    open_file = Signal()
    open_recent = Signal(str)
    practice = Signal()
    from_takeoff = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(48, 36, 48, 36)
        t = QLabel("ClaimIT")
        f = t.font()
        f.setPointSize(26)
        f.setBold(True)
        t.setFont(f)
        lay.addWidget(t)
        sub = QLabel("Property claim estimates: rooms, line items, coverage, "
                     "settlement and supplements in one place.")
        sub.setWordWrap(True)
        lay.addWidget(sub)
        grid = QGridLayout()
        grid.setSpacing(10)
        self.buttons = {}
        for i, (key, title, line, sig) in enumerate((
                ("res", "New residential claim", "Home, other structures, ALE",
                 self.new_residential),
                ("com", "New commercial claim",
                 "Buildings, coinsurance, business income",
                 self.new_commercial),
                ("open", "Open a claim", "A .claim.json file",
                 self.open_file),
                ("practice", "Practice claim",
                 "A made-up claim to try every tab on", self.practice),
                ("takeoff", "Start from QuantiSheet takeoff",
                 "New claim with the quantities QuantiSheet sent",
                 self.from_takeoff))):
            b = QPushButton(f"{title}\n{line}")
            b.setMinimumHeight(64)
            b.setStyleSheet("text-align: left; padding: 8px 14px;")
            b.clicked.connect(sig.emit)
            grid.addWidget(b, i // 2, i % 2)
            self.buttons[key] = b
        lay.addLayout(grid)
        lay.addWidget(QLabel("Recent claims"))
        self.recent = QListWidget()
        # one signal only: on some systems one click also "activates"
        self.recent.itemActivated.connect(
            lambda it: it.data(Qt.UserRole) and
            self.open_recent.emit(it.data(Qt.UserRole)))
        lay.addWidget(self.recent, 1)
        tip = QLabel("Tip: Ctrl+N starts a claim, Ctrl+S saves, Ctrl+Z "
                     "undoes. Help > Getting started walks through a claim.")
        tip.setWordWrap(True)
        lay.addWidget(tip)
        self.refresh()

    def refresh(self, takeoff_waiting=False) -> int:
        self.buttons["takeoff"].setVisible(bool(takeoff_waiting))
        self.recent.clear()
        n = 0
        for p in settings.get("recent") or []:
            if not isinstance(p, str) or not os.path.exists(p):
                continue
            it = QListWidgetItem(os.path.basename(p).replace(".claim.json", "")
                                 + "    " + os.path.dirname(p))
            it.setData(Qt.UserRole, p)
            self.recent.addItem(it)
            n += 1
        if not n:
            self.recent.addItem("No recent claims yet")
            self.recent.item(0).setFlags(Qt.NoItemFlags)
        return n


# ------------------------------------------------------------- new claim
class NewClaimDialog(QDialog):
    """The basics in one step, so a new claim starts complete."""

    def __init__(self, claim_type="residential", parent=None):
        super().__init__(parent)
        self.setWindowTitle("New " + claim_type + " claim")
        self.claim_type = claim_type
        form = QFormLayout(self)
        self.f = {}
        for key, label, tip in (
                ("claim_number", "Claim number *", "As the carrier writes it"),
                ("insured", "Insured *", ""),
                ("carrier", "Carrier", ""),
                ("loss_address", "Loss address", "")):
            e = QLineEdit()
            e.setPlaceholderText(tip)
            self.f[key] = e
            form.addRow(label, e)
        self.loss_date = QDateEdit()
        self.loss_date.setCalendarPopup(True)
        self.loss_date.setDisplayFormat("yyyy-MM-dd")
        # no date until one is picked (r47 #4: a default of today was
        # saved as the date of loss when nobody changed it)
        self.loss_date.setMinimumDate(NO_DATE)
        self.loss_date.setSpecialValueText("Pick the date")
        self.loss_date.setMaximumDate(QDate.currentDate())
        self.loss_date.setDate(NO_DATE)
        form.addRow("Date of loss *", self.loss_date)
        self.peril = QComboBox()
        self.peril.setEditable(True)
        self.peril.addItems(PERILS)
        form.addRow("Peril", self.peril)
        self.limit = QLineEdit()
        self.limit.setPlaceholderText("$")
        form.addRow("Coverage A limit" if claim_type == "residential"
                    else "Building limit", self.limit)
        self.deductible = QLineEdit()
        self.deductible.setPlaceholderText("$")
        form.addRow("Deductible", self.deductible)
        self.msg = QLabel("* needed. Everything can be changed later.")
        self.msg.setWordWrap(True)
        form.addRow(self.msg)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Create claim")
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def fill(self, **v) -> "NewClaimDialog":
        for k, e in self.f.items():
            if k in v:
                e.setText(v[k])
        if "loss_date" in v:
            d = QDate.fromString(v["loss_date"], "yyyy-MM-dd")
            self.loss_date.setDate(d if d.isValid() else NO_DATE)
        if "peril" in v:
            self.peril.setCurrentText(v["peril"])
        if "limit" in v:
            self.limit.setText(v["limit"])
        if "deductible" in v:
            self.deductible.setText(v["deductible"])
        return self

    def values(self) -> dict:
        """Checked values, or raises ValueError with what to fix."""
        out = {k: e.text().strip() for k, e in self.f.items()}
        if not out["claim_number"]:
            raise ValueError("Enter the claim number")
        if not out["insured"]:
            raise ValueError("Enter the insured's name")
        if self.loss_date.date() == NO_DATE:
            raise ValueError("Pick the date of loss")
        out["loss_date"] = self.loss_date.date().toString("yyyy-MM-dd")
        out["peril"] = self.peril.currentText().strip()
        try:
            t = self.limit.text().strip()
            out["limit_cents"] = parse_money(t) if t else None
            t = self.deductible.text().strip()
            out["deductible_cents"] = parse_money(t) if t else 0
        except MoneyError as e:
            raise ValueError(str(e)) from e
        return out

    def _ok(self):
        try:
            self.values()
        except ValueError as e:
            self.msg.setText("⚠ " + str(e))
            return
        self.accept()


# ------------------------------------------------------------------ room
class RoomDialog(QDialog):
    """A room by its size; the measurements show as you type."""

    def __init__(self, room=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit room" if room else "Add room")
        form = QFormLayout(self)
        self.name = QLineEdit(room.name if room else "")
        self.length = QLineEdit(str(room.length_ft) if room else "")
        self.width = QLineEdit(str(room.width_ft) if room else "")
        self.height = QLineEdit(str(room.height_ft) if room else "8")
        for e, ph in ((self.length, "feet, e.g. 12.5 or 12'6\""),
                      (self.width, "feet"), (self.height, "feet")):
            e.setPlaceholderText(ph)
        self.doors = QSpinBox()
        self.windows = QSpinBox()
        for s in (self.doors, self.windows):
            s.setRange(0, 50)
        if room:
            self.doors.setValue(rooms.count(room, "door"))
            self.windows.setValue(rooms.count(room, "window"))
        form.addRow("Room name *", self.name)
        form.addRow("Length (ft)", self.length)
        form.addRow("Width (ft)", self.width)
        form.addRow("Ceiling height (ft)", self.height)
        form.addRow("Doors (3 x 6'8\")", self.doors)
        form.addRow("Windows (3 x 4 ft)", self.windows)
        # 0.2.2: not a plain rectangle - an alcove / other leg of an L, or
        # a corner taken out
        self.parts = {}
        for kind, label in (("bump", "Alcove or extra leg (ft)"),
                            ("cut", "Corner cut out (ft)")):
            p = rooms.part(room, kind) if room else None
            a = QLineEdit(str(p.along_ft) if p else "")
            d = QLineEdit(str(p.depth_ft) if p else "")
            a.setPlaceholderText("along the wall")
            d.setPlaceholderText("depth")
            row = QHBoxLayout()
            row.addWidget(a)
            row.addWidget(QLabel("x"))
            row.addWidget(d)
            form.addRow(label, row)
            self.parts[kind] = (a, d)
            for e in (a, d):
                e.textChanged.connect(lambda _t: self.update_preview())
        self.preview = QLabel("")
        self.preview.setWordWrap(True)
        form.addRow(self.preview)
        for e in (self.name, self.length, self.width, self.height):
            e.textChanged.connect(lambda _t: self.update_preview())
        for s in (self.doors, self.windows):
            s.valueChanged.connect(lambda _v: self.update_preview())
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        form.addRow(bb)
        self._base = room
        self.update_preview()

    def room(self):
        """The room as typed (raises rooms.RoomError)."""
        import dataclasses
        r = rooms.new_room(self.name.text(), self.length.text() or "0",
                           self.width.text() or "0",
                           self.height.text() or "0",
                           self.doors.value(), self.windows.value())
        if self._base is not None:
            # keep any other openings the room had (only doors and
            # windows are set here)
            other = tuple(o for o in self._base.openings
                          if o.kind not in ("door", "window"))
            r = dataclasses.replace(r, id=self._base.id,
                                    structure_id=self._base.structure_id,
                                    openings=other + r.openings,
                                    parts=self._base.parts)
        for kind, (a, d) in self.parts.items():
            r = rooms.set_part(r, kind, a.text().strip() or "0",
                               d.text().strip() or "0")
        return r

    def update_preview(self) -> str:
        try:
            if self.name.text().strip():
                ms = rooms.measure(self.room())
            else:
                r = rooms.new_room(
                    "x", self.length.text() or "0", self.width.text() or "0",
                    self.height.text() or "0", self.doors.value(),
                    self.windows.value())
                for kind, (a, d) in self.parts.items():
                    r = rooms.set_part(r, kind, a.text().strip() or "0",
                                       d.text().strip() or "0")
                ms = rooms.measure(r)
            txt = (f"Floor {ms.floor} SF · Walls {ms.walls} SF (less "
                   f"{ms.openings} SF of openings) · Ceiling {ms.ceiling} SF "
                   f"· Perimeter {ms.perimeter} LF")
        except rooms.RoomError as e:
            txt = "⚠ " + str(e)
        self.preview.setText(txt)
        return txt

    def _ok(self):
        try:
            self.room()
        except rooms.RoomError as e:
            self.preview.setText("⚠ " + str(e))
            return
        self.accept()


# ------------------------------------------------------------------ kits
class KitsDialog(QDialog):
    """File > My line kits: groups of your own library items, each taking
    its quantity from a room measurement."""
    COLS = ("Code", "Quantity from", "Times")

    def __init__(self, parent=None, pick=False):
        super().__init__(parent)
        self.setWindowTitle("Add a kit to the room" if pick else "My line kits")
        self.resize(640, 440)
        lay = QHBoxLayout(self)
        left = QVBoxLayout()
        self.list = QListWidget()
        self.list.currentTextChanged.connect(self._show)
        left.addWidget(QLabel("Kits"))
        left.addWidget(self.list, 1)
        lay.addLayout(left, 1)
        right = QVBoxLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("Kit name, e.g. Water - 2 ft flood cut")
        right.addWidget(self.name)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(list(self.COLS))
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        right.addWidget(self.table, 1)
        self.msg = QLabel("Kits hold codes from your own library only.")
        self.msg.setWordWrap(True)
        right.addWidget(self.msg)
        row = QHBoxLayout()
        self.pick = pick
        if not pick:
            for text, fn in (("Add item", self.add_row),
                             ("Remove item", self.remove_row),
                             ("Save kit", self.save),
                             ("Delete kit", self.delete)):
                b = QPushButton(text)
                b.clicked.connect(lambda _c=False, f=fn: f())
                row.addWidget(b)
        right.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel
                              if pick else QDialogButtonBox.Close)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        right.addWidget(bb)
        lay.addLayout(right, 2)
        self.fill()

    def fill(self):
        self.list.clear()
        self.list.addItems(sorted(kits.all_kits()))
        if self.list.count():
            self.list.setCurrentRow(0)

    def chosen(self) -> str:
        it = self.list.currentItem()
        return it.text() if it else ""

    def _measure_box(self, key="floor"):
        box = QComboBox()
        for k, (label, unit) in rooms.MEASURES.items():
            box.addItem(f"{label} ({unit})", k)
        box.setCurrentIndex(max(0, box.findData(key)))
        return box

    def _code_box(self, code=""):
        box = QComboBox()
        box.setEditable(True)
        box.addItems(sorted(library.items()))
        box.setCurrentText(code)
        return box

    def _show(self, name):
        self.name.setText(name)
        rows = kits.all_kits().get(name, [])
        self.table.setRowCount(0)
        for r in rows:
            self.add_row(r["code"], r["measure"], r["factor"])

    def add_row(self, code="", measure="floor", factor="1"):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setCellWidget(r, 0, self._code_box(code))
        self.table.setCellWidget(r, 1, self._measure_box(measure))
        self.table.setItem(r, 2, QTableWidgetItem(str(factor)))
        return r

    def remove_row(self):
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r)

    def rows(self):
        out = []
        for r in range(self.table.rowCount()):
            code = self.table.cellWidget(r, 0).currentText()
            meas = self.table.cellWidget(r, 1).currentData()
            fac = self.table.item(r, 2).text() if self.table.item(r, 2) else "1"
            out.append((code, meas, fac))
        return out

    def save(self) -> bool:
        try:
            kits.save_kit(self.name.text(), self.rows())
        except kits.KitError as e:
            self.msg.setText("⚠ " + str(e))
            return False
        name = self.name.text().strip()
        self.fill()
        items = self.list.findItems(name, Qt.MatchExactly)
        if items:
            self.list.setCurrentItem(items[0])
        self.msg.setText(f"Saved kit {name}.")
        return True

    def delete(self):
        if self.chosen():
            kits.remove_kit(self.chosen())
            self.fill()


# ------------------------------------------------------------- checklist
class ChecklistDialog(QDialog):
    """What to fix or check; double-click an item to go to its tab."""
    go = Signal(int)

    def __init__(self, items, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Before you send: " + checklist.summary(items))
        self.resize(560, 380)
        lay = QVBoxLayout(self)
        self.list = QListWidget()
        for i in items:
            it = QListWidgetItem(("Fix: " if i.level == "fix" else "Check: ")
                                 + i.text)
            it.setData(Qt.UserRole, checklist.TAB[i.tab])
            self.list.addItem(it)
        if not items:
            self.list.addItem("Nothing to fix or check. Ready to export.")
        self.list.itemActivated.connect(self._go)
        self.list.itemDoubleClicked.connect(self._go)
        lay.addWidget(self.list)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _go(self, it):
        tab = it.data(Qt.UserRole)
        if tab is not None:
            self.go.emit(int(tab))
            self.accept()


GETTING_STARTED = """
<h2>Getting started with ClaimIT</h2>
<ol>
<li><b>Start a claim</b>: File &gt; New claim (Ctrl+N). Type the claim
number, the insured, the date of loss and the peril. Or open the
<b>practice claim</b> from the start page to try everything first.</li>
<li><b>Coverage</b>: the Coverage &amp; deductibles tab - limits,
deductible, ALE or business income, ordinance or law.</li>
<li><b>Rooms</b>: on Rooms &amp; line items, <b>Add room</b> with its
length, width, height, doors and windows. ClaimIT works out the floor,
walls, ceiling and perimeter.</li>
<li><b>Line items</b>: add your own codes (File &gt; My line items), or
a <b>kit</b> to a room - a kit takes each quantity from the room's
measurements (File &gt; My line kits). Edit any cell; changes apply as
you type. Duplicate or copy lines to another room.</li>
<li><b>Check the numbers</b>: the bar at the bottom always shows RCV,
depreciation, ACV, deductible and what is owed now. The
<b>Settlement summary</b> tab shows every step.</li>
<li><b>Before you send</b>: click the checklist on the bottom bar - it
lists what is missing and takes you to the tab that fixes it.</li>
<li><b>Export</b> a PDF, Excel or CSV for the carrier.</li>
<li><b>After that</b>: record calls and inspections on the <b>Diary
&amp; payments</b> tab, and every payment the carrier makes - the bar
then shows what is still owed. A supplement starts with
<b>Revisions &amp; supplements</b> &gt; New revision.</li>
</ol>
<p>ClaimIT saves your claims as you work. Ctrl+Z undoes, Ctrl+Y redoes.
Nothing is sent anywhere: your claims stay in your Documents\\ClaimIT
folder.</p>
"""


class GettingStartedDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Getting started")
        self.resize(620, 520)
        lay = QVBoxLayout(self)
        b = QTextBrowser()
        b.setHtml(GETTING_STARTED)
        lay.addWidget(b)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)


def today() -> str:
    return _dt.date.today().isoformat()
