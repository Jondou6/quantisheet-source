"""Load Report window (1.2, #12): takeoff inputs out to the outside
designer, the designer's report in. QuantiSheet doesn't calculate loads.

"Get rooms from the drawing" reads the open drawing's takeoff (areas
named for rooms, "<room> window E", "<room> exterior wall"); anything
typed is marked entered; blanks stay missing and are listed before an
export. open_window(parent).
"""
import datetime as dt

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QTableWidget,
                               QTableWidgetItem)

from . import files, loadcalc, uiutil

# (key, header): numbers; windows / doors by facing
COLS = (("name", "Room"), ("floor_sf", "Floor SF"),
        ("ceiling_ft", "Ceiling ft"), ("ext_wall_lf", "Ext wall LF"),
        ("wall_height_ft", "Wall ht ft"),
        ("windows:N", "Win N SF"), ("windows:E", "Win E SF"),
        ("windows:S", "Win S SF"), ("windows:W", "Win W SF"),
        ("windows:unknown", "Win ? SF"),
        ("doors:N", "Door N SF"), ("doors:E", "Door E SF"),
        ("doors:S", "Door S SF"), ("doors:W", "Door W SF"),
        ("doors:unknown", "Door ? SF"))
MEASURED = QColor("#d8efe9")


class LoadReportWindow(uiutil.Desk):
    def __init__(self, parent=None, today=None):
        super().__init__("Load Report (Outside Designer)", parent)
        self.host = parent
        self.today = today or dt.date.today()
        self.path = loadcalc.default_path()
        self.current = None
        self._filling = False
        note = QLabel(loadcalc.NOTE + " Green cells were measured from the "
                      "drawing; typed values are marked entered.")
        note.setWordWrap(True)
        self.root.addWidget(note)
        top = QHBoxLayout()
        self.customer = QLineEdit()
        self.customer.setPlaceholderText("Customer")
        self.customer.setAccessibleName("Customer")
        self.site = QLineEdit()
        self.site.setPlaceholderText("Site")
        self.site.setAccessibleName("Site")
        top.addWidget(self.customer)
        top.addWidget(self.site)
        self.root.addLayout(top)
        self.rooms = QTableWidget(0, len(COLS))
        self.rooms.setHorizontalHeaderLabels([c[1] for c in COLS])
        self.rooms.setAccessibleName("Rooms")
        self.rooms.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.rooms.cellChanged.connect(self._typed)
        self.root.addWidget(self.rooms, 2)
        self.buttons(("Get rooms from the drawing", self.takeoff_clicked),
                     ("Add room", self.add_room),
                     ("Remove room", self.remove_room),
                     ("Save", self.save_clicked),
                     ("Export PDF…", self.pdf_clicked),
                     ("Export CSV…", self.csv_clicked))
        form = QFormLayout()
        self.designer = QLineEdit()
        self.designer.setAccessibleName("Designer")
        self.rdate = QLineEdit(self.today.isoformat())
        self.rdate.setAccessibleName("Report date")
        self.heat = QLineEdit()
        self.heat.setAccessibleName("Heating load BTU/h")
        self.cool = QLineEdit()
        self.cool.setAccessibleName("Cooling load BTU/h")
        self.rec = QLineEdit()
        self.rec.setPlaceholderText("e.g. 7.5-ton RTU, gas heat")
        self.rec.setAccessibleName("Recommended equipment")
        for lbl, w in (("Designer", self.designer),
                       ("Report date", self.rdate),
                       ("Heating load (BTU/h)", self.heat),
                       ("Cooling load (BTU/h)", self.cool),
                       ("Recommended equipment", self.rec)):
            form.addRow(lbl, w)
        self.root.addLayout(form)
        self.buttons(("Attach designer's report…", self.attach_clicked),)
        self.table = uiutil.table(["Number", "Date", "Customer", "Site",
                                   "Report"])
        self.table.setAccessibleName("Load report jobs")
        self.root.addWidget(self.table, 1)
        self.buttons(("Open selected", self.open_clicked),)
        self.finish()
        self.reload()

    # ---- table <-> rooms --------------------------------------------------
    def reload(self):
        self.store = loadcalc.load(self.path)
        uiutil.fill(self.table, [
            [j["number"], j["date"], j["customer"], j["site"],
             loadcalc.status(j)] for j in self.store["jobs"]],
            [j["id"] for j in self.store["jobs"]])

    def _get(self, r, key):
        if ":" in key:
            kind, o = key.split(":")
            return (r.get(kind) or {}).get(o) or {"value": None,
                                                  "source": "missing"}
        return r[key]

    def add_room(self, r=None):
        self._filling = True
        row = self.rooms.rowCount()
        self.rooms.insertRow(row)
        for c, (key, _h) in enumerate(COLS):
            if key == "name":
                it = QTableWidgetItem((r or {}).get("name", ""))
            else:
                v = self._get(r, key) if r else {"value": None,
                                                 "source": "missing"}
                it = QTableWidgetItem("" if v["value"] is None
                                      else f"{v['value']:g}")
                it.setData(Qt.UserRole, v["source"])
                if v["source"] == "measured":
                    it.setBackground(QBrush(MEASURED))
                    it.setToolTip("Measured from the drawing")
            self.rooms.setItem(row, c, it)
        self._filling = False
        return row

    def _typed(self, row, col):
        if self._filling or COLS[col][0] == "name":
            return
        it = self.rooms.item(row, col)
        if it is None:
            return
        self._filling = True
        it.setData(Qt.UserRole, "entered" if it.text().strip() else
                   "missing")
        it.setBackground(QBrush())
        it.setToolTip("")
        self._filling = False

    def remove_room(self):
        r = self.rooms.currentRow()
        if r >= 0:
            self.rooms.removeRow(r)

    def room_rows(self):
        out = []
        for row in range(self.rooms.rowCount()):
            it = self.rooms.item(row, 0)
            name = it.text().strip() if it else ""
            if not name:
                continue
            kw = {"windows": {}, "doors": {}}
            for c, (key, _h) in enumerate(COLS[1:], 1):
                it = self.rooms.item(row, c)
                text = it.text().strip() if it else ""
                src = (it.data(Qt.UserRole) if it else None) or "entered"
                v = loadcalc.val(text, "measured" if src == "measured"
                                 else "entered") if text else loadcalc.val()
                if ":" in key:
                    kind, o = key.split(":")
                    if text:
                        kw[kind][o] = v
                else:
                    kw[key] = v
            out.append(loadcalc.room(name, **kw))
        return out

    def _show(self, rooms):
        self.rooms.setRowCount(0)
        for r in rooms:
            self.add_room(r)

    # ---- actions ----------------------------------------------------------
    def takeoff_clicked(self, _checked=False, items=None):
        if items is None:
            doc = getattr(getattr(self.host, "_view", None), "doc", None)
            if doc is None:
                self.msg.setText("Open the drawing with the room takeoff "
                                 "first.")
                return None
            from .. import annotate
            items = annotate.takeoff_items(doc)
        got = loadcalc.from_takeoff(items)
        if not got:
            self.msg.setText("No room areas in the takeoff. Name each room's "
                             "area markup with the room name.")
            return []
        cur = self.guard(self.room_rows)
        if cur is None:
            return None
        self._show(loadcalc.merge_rooms(cur, got))
        self.msg.setText(f"{len(got)} room(s) from the drawing. Fill in what "
                         "the drawing doesn't show.")
        return got

    def save_clicked(self):
        rows = self.guard(self.room_rows)
        if rows is None:
            return None
        if self.current:
            job = loadcalc.get(self.store, self.current)
            job["rooms"] = rows
            rid = self.current
        else:
            rid = self.guard(lambda: loadcalc.add(
                self.store, self.customer.text(), self.site.text(), rows,
                when=self.today))
            if not rid:
                return None
        loadcalc.save(self.store, self.path)
        self.current = rid
        self.reload()
        gaps = loadcalc.missing(loadcalc.get(self.store, rid))
        self.msg.setText("Saved." + (f" {len(gaps)} value(s) still missing."
                                     if gaps else ""))
        return rid

    def _job(self):
        rid = self.save_clicked()
        return loadcalc.get(self.store, rid) if rid else None

    def pdf_clicked(self, _checked=False, path=None):
        job = self._job()
        if not job:
            return None
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Inputs for the designer", files.path_for(
                    f"{job['number']} load inputs.pdf"), "PDF (*.pdf)")
        if not path:
            return None
        got = self.guard(lambda: loadcalc.export_pdf(job, path))
        if got is not None:
            loadcalc.save(self.store, self.path)
            self.msg.setText(f"Saved {path}")
        return got

    def csv_clicked(self, _checked=False, path=None):
        job = self._job()
        if not job:
            return None
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Inputs for the designer", files.path_for(
                    f"{job['number']} load inputs.csv"), "CSV (*.csv)")
        if not path:
            return None
        got = self.guard(lambda: loadcalc.export_csv(job, path))
        if got is not None:
            loadcalc.save(self.store, self.path)
            self.msg.setText(f"Saved {path}")
        return got

    def attach_clicked(self, _checked=False, path=None):
        job = self._job()
        if not job:
            return None
        if path is None:
            path, _ = QFileDialog.getOpenFileName(
                self, "Designer's report", "", "PDF (*.pdf)")
        if not path:
            return None
        got = self.guard(lambda: loadcalc.attach_report(
            self.store, job["id"], path, self.designer.text(),
            self.rdate.text(), self.heat.text(), self.cool.text(),
            self.rec.text()))
        if got is None:
            return None
        loadcalc.save(self.store, self.path)
        self.reload()
        self.msg.setText(loadcalc.status(job))
        return got

    def open_clicked(self):
        rid = uiutil.selected_id(self.table)
        if not rid:
            self.msg.setText("Pick a job in the list.")
            return None
        job = loadcalc.get(self.store, rid)
        self.current = rid
        self.customer.setText(job["customer"])
        self.site.setText(job["site"])
        self._show(job["rooms"])
        r = job.get("report") or {}
        self.designer.setText(r.get("designer", ""))
        self.rdate.setText(r.get("date") or self.today.isoformat())
        self.heat.setText(str(r.get("heating_btuh") or ""))
        self.cool.setText(str(r.get("cooling_btuh") or ""))
        self.rec.setText(r.get("recommended", ""))
        self.msg.setText(loadcalc.status(job))
        return job


def open_window(parent=None):
    return uiutil.show(LoadReportWindow(parent))
