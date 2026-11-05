"""Trade Takeoff dialog and the Check Takeoff review queue.

Trade Takeoff (Takeoff > Trade Takeoff…): one tab per trade. Find reads
the sheet and lists what it found with the quantities; you tick what is in
scope (rename a system by typing over its name) and Add to Takeoff - one
undoable step, every measurement editable, the method in its audit trail.

Check Takeoff (Takeoff > Check Takeoff…): every measurement made by an
automatic tool, one at a time, zoomed to: Accept, Delete or skip. Accepted
items carry the status "Accepted", so the check shows in the Markups List,
the audit trail and the takeoff report.
"""
import math

import fitz
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QHeaderView, QLabel,
                               QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout,
                               QWidget)

from . import annotate, tradetakeoff as tt


def _num(v, d=1):
    return f"{v:,.{d}f}"


class _Tab(QWidget):
    """A tab: a hint, Find, a results table, Add to Takeoff."""
    COLS = []

    def _rname(self, kind, ext):
        """Default export name - company rule, date first
        (app/reportname.py); the project is the open PDF's name."""
        import os
        from .reportname import report_file_name
        win = getattr(self.dlg, "win", None)
        proj = os.path.splitext(os.path.basename(
            getattr(win, "_path", "") or ""))[0]
        return report_file_name(kind, proj, ext=ext)

    def __init__(self, dlg, hint, find_label="Find on This Sheet"):
        super().__init__()
        self.dlg = dlg
        self.data = []
        v = QVBoxLayout(self)
        h = QLabel(hint)
        h.setWordWrap(True)
        h.setObjectName("muted")
        v.addWidget(h)
        self.form = QHBoxLayout()
        v.addLayout(self.form)
        self.find_btn = QPushButton(find_label)
        self.find_btn.setObjectName("primary")
        self.find_btn.clicked.connect(self.find)
        self.form.addWidget(self.find_btn)
        self.form.addStretch()
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        v.addWidget(self.table, 1)
        self.status = QLabel()
        self.status.setObjectName("muted")
        v.addWidget(self.status)
        row = QHBoxLayout()
        row.addStretch()
        self.add_btn = QPushButton("Add to Takeoff")
        self.add_btn.clicked.connect(self.add)
        self.add_btn.setEnabled(False)
        row.addWidget(self.add_btn)
        v.addLayout(row)

    @property
    def view(self):
        return self.dlg.win._view

    def scale(self):
        sc = self.view.scale() if self.view else None
        if not sc:
            self.status.setText("Set the scale for this page first "
                                "(Takeoff > Set Scale or Auto Scale).")
        return sc

    def _fill(self, rows, checked):
        self.table.setRowCount(len(rows))
        for i, (vals, on) in enumerate(zip(rows, checked)):
            for c, val in enumerate(vals):
                it = QTableWidgetItem(str(val))
                if c == 0:
                    it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                    it.setCheckState(Qt.Checked if on else Qt.Unchecked)
                elif c > 1:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if c not in (0, 1):
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(i, c, it)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.Stretch)
        self.add_btn.setEnabled(bool(rows))

    def chosen(self):
        out = []
        for i, d in enumerate(self.data):
            it = self.table.item(i, 0)
            if it is not None and it.checkState() == Qt.Checked:
                name = self.table.item(i, 1).text().strip() if \
                    self.table.item(i, 1) else ""
                out.append((d, name))
        return out

    def apply(self, marks, what):
        if not marks:
            self.status.setText("Nothing ticked.")
            return 0
        n = self.view.apply_marks(marks)
        self.dlg.win.qty_dock.show()
        self.status.setText(f"Added {n} measurement(s) for {what}. "
                            "Ctrl+Z takes them all off again.")
        self.dlg.added += n
        return n


class PipeTab(_Tab):
    COLS = ["Take off", "System (type to rename)", "Line style", "Length",
            "Runs"]

    def __init__(self, dlg):
        super().__init__(dlg, "Pipe, conduit, gas, sprinkler and other "
                         "single-line runs. Each line style is a system; runs "
                         "are named from the size tag printed beside them "
                         "(4\" CW, 3/4\"C). Tagged systems are ticked.")

    def find(self):
        sc = self.scale()
        if not sc:
            return []
        self.unit = sc["unit"]
        self.data = tt.mep_runs(self.view.pg, sc["ppu"], sc["unit"])
        self._fill([["", g["name"], g["style_name"] +
                     (" - check: too long for the drawing"
                      if g.get("flag") else ""),
                     f"{_num(g['length'])} {sc['unit']}", len(g["runs"])]
                    for g in self.data], [g["suggested"] for g in self.data])
        flagged = sum(1 for g in self.data if g.get("flag"))
        self.status.setText(f"{len(self.data)} system(s) found; "
                            f"{sum(g['suggested'] for g in self.data)} "
                            "tagged." + (f" {flagged} tagged system(s) "
                                         "not ticked: longer than the "
                                         "drawing can hold - check them."
                                         if flagged else ""))
        return self.data

    def add(self):
        groups = []
        for g, name in self.chosen():
            groups.append(dict(g, name=name or g["name"]))
        return self.apply(tt.run_marks(self.view.page, groups, self.unit),
                          f"{len(groups)} system(s)")


class CivilTab(_Tab):
    COLS = ["Take off", "Pipe / structure (type to rename)", "Quantity",
            "Depth", "Check"]

    def __init__(self, dlg):
        super().__init__(dlg, "Sewer, storm, force main and water plans: "
                         "pipe LF by size and material from the pipe labels "
                         "('8\" PVC SDR-35 @ 0.40%'), manholes, cleanouts, "
                         "inlets and valves counted once by their tags, and "
                         "depth from the RIM / INV callouts - so each pipe "
                         "size is priced by depth band with trench "
                         "excavation, bedding, backfill and shoring. "
                         "Profiles are left out. Existing pipe isn't ticked.",
                         "Find on This Sheet")
        self.whole = QCheckBox("Every sheet with a scale")
        self.form.insertWidget(1, self.whole)
        self.result = None

    def find(self):
        from . import civiltakeoff as ct
        v = self.view
        if v is None:
            return []
        scales = annotate.read_scales(v.doc)
        if self.whole.isChecked():
            pages = sorted(scales)
            if not pages:
                self.status.setText("No sheet has a scale yet (Takeoff > "
                                    "Auto Scale).")
                return []
        else:
            if not self.scale():
                return []
            pages = [v.page]
        sc = {p: (scales[p]["ppu"], scales[p]["unit"]) for p in pages
              if p in scales}
        self.unit = scales[pages[0]]["unit"] if pages[0] in scales else "ft"
        self.result = res = ct.takeoff(v.doc, pages, sc)
        rows, on, self.data = [], [], []
        for p in res["pipes"]:
            for band, ln in sorted(p["bands"].items(),
                                   key=lambda kv: (kv[0] or (99, 99))):
                check = ""
                if p["label_length"]:
                    diff = (p["length"] - p["label_length"]) / max(
                        1e-9, p["label_length"])
                    check = (f"labels say {_num(p['label_length'], 0)} LF "
                             f"({diff:+.1%})")
                rows.append(["", ct.group_name(p, band),
                             f"{_num(ln)} {self.unit}",
                             ct.band_name(band), check])
                on.append(not p["existing"])
                self.data.append(("pipe", p, band))
        summ = ct.structure_summary(res["structures"])
        for (kind, band), rec in sorted(summ.items(), key=lambda kv: (
                kv[0][0], kv[0][1] or (99, 99))):
            ids = ", ".join(rec["ids"][:6]) + (" …" if len(rec["ids"]) > 6
                                               else "")
            name = f"{ct._struct_base_name(kind)}, {ct.band_name(band)}"
            rows.append(["", name, f"{rec['count']} ea",
                         f"avg {rec['avg_depth']:.1f} ft" if
                         rec["avg_depth"] else "", ids])
            on.append(True)
            self.data.append(("struct", (kind, band), rec))
        self._fill(rows, on)
        n_mh = sum(r["count"] for (k, _), r in summ.items()
                   if k.startswith("manhole"))
        self.status.setText(
            f"{len(res['pipes'])} pipe size(s), "
            f"{sum(r['count'] for r in summ.values())} structure(s) "
            f"({n_mh} manholes) on {len(pages)} sheet(s).")
        return self.data

    def add(self):
        from . import assemblies, civiltakeoff as ct
        if not self.result:
            return 0
        chosen = self.chosen()
        if not chosen:
            return self.apply([], "civil")
        res = self.result
        groups, kinds = {}, set()
        pipes = []
        for (what, a, b), name in chosen:
            if what == "pipe":
                default = ct.group_name(a, b)
                runs = [r for r in a["runs"] if ct.band_of(r["depth"]) == b]
                pipes.append((a, b, runs, name or default, default))
            else:
                kinds.add(a)
                groups[a] = name
        # assemblies for what's ticked, under the names in the table
        lib = ct.assemblies_for(res)
        for a, b, runs, name, default in pipes:
            if default in lib:
                asm = dict(lib[default], name=name)
                assemblies.set_job_assembly(self.view.doc, asm)
        marks = []
        for i, (a, b, runs, name, default) in enumerate(pipes):
            sub = dict(a, runs=runs, name=name)
            for m in ct.marks({"pipes": [sub], "structures": []},
                              self.unit, structs=[]):
                m[2]["measure"]["group"] = name
                marks.append(m)
        sts = [s for s in res["structures"] if not s["existing"] and
               (s["kind"], ct.band_of(s["depth"])) in kinds]
        for key, asm in lib.items():
            for (kind, band) in kinds:
                if key == f"{ct._struct_base_name(kind)}, " \
                        f"{ct.band_name(band)}":
                    asm = dict(asm, name=groups[(kind, band)] or key)
                    assemblies.set_job_assembly(self.view.doc, asm)
        smarks = ct.marks(res, self.unit, pipes=[], structs=sts)
        for m in smarks:
            s = next(x for x in sts if x["id"] == m[2]["measure"]["label"])
            k = (s["kind"], ct.band_of(s["depth"]))
            if groups.get(k):
                m[2]["measure"]["group"] = groups[k]
        marks += smarks
        return self.apply(marks, "civil takeoff (pipe by size and depth, "
                          "structures)")


class DuctTab(_Tab):
    COLS = ["Take off", "Duct size", "Length", "Sheet metal",
            "Weight", "Gauge"]

    def __init__(self, dlg):
        super().__init__(dlg, "Double-line ductwork: pairs of lines 4\" to "
                         "72\" apart. Sized from tags (24x12, 14\"Ø); sheet "
                         "metal area and weight by SMACNA gauge.")

    def find(self):
        sc = self.scale()
        if not sc:
            return []
        self.unit = sc["unit"]
        self.data = tt.ducts(self.view.pg, sc["ppu"], sc["unit"])
        self._fill([["", g["name"], f"{_num(g['length'])} {sc['unit']}",
                     f"{_num(g['sf'], 0)} SF", f"{_num(g['lb'], 0)} lb",
                     f"{g['gauge']} ga"] for g in self.data],
                   [g["tagged"] for g in self.data])
        tot = sum(g["lb"] for g in self.data if g["tagged"])
        self.status.setText(f"{len(self.data)} size(s); tagged ductwork "
                            f"{_num(tot, 0)} lb.")
        return self.data

    def add(self):
        gs = [dict(g, name=name or g["name"]) for g, name in self.chosen()]
        return self.apply(tt.duct_marks(self.view.page, gs, self.unit),
                          f"{len(gs)} duct size(s)")


class LegendTab(_Tab):
    COLS = ["Take off", "Device / fixture (from the legend)", "Count",
            "Sheets"]

    def __init__(self, dlg):
        super().__init__(dlg, "Every symbol in the drawings' legends is cut "
                         "out and counted on every sheet (turned copies "
                         "too), named by its description.",
                         "Count Legend Symbols")

    def find(self):
        doc = self.view.doc
        # a whole set can take minutes: show progress with Cancel (PM
        # review NW-18: 229 s with no sign of life)
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication, QProgressDialog
        dlg = QProgressDialog("Counting legend symbols...", "Cancel", 0, 0,
                              self)
        dlg.setWindowTitle("Count Legend Symbols")
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(400)

        def progress(k, n, name):
            dlg.setMaximum(max(n, 1))
            dlg.setValue(k)
            dlg.setLabelText(f"Counting {name or 'symbols'} ({k + 1} of "
                             f"{n})...")
            QApplication.processEvents()
            return not dlg.wasCanceled()
        rep = {}
        try:
            self.data = tt.legend_counts(doc, progress=progress, report=rep)
        finally:
            stopped = dlg.wasCanceled()
            dlg.close()
        self._fill([["", f["name"], len(f["hits"]),
                     len({h["page"] for h in f["hits"]})]
                    for f in self.data], [True] * len(self.data))
        if not self.data:
            self.status.setText("No legend with symbols found (a heading "
                                "LEGEND or SYMBOLS with a picture left of "
                                "each description).")
        else:
            self.status.setText(f"{len(self.data)} symbol(s), "
                                f"{sum(len(f['hits']) for f in self.data)} "
                                "found in all." +
                                (" Stopped - the rest weren't counted."
                                 if stopped else ""))
        return self.data

    def add(self):
        from . import autocount
        marks = []
        for f, name in self.chosen():
            marks += autocount.count_marks(f["hits"], name or f["name"],
                                           self.view.doc)
        return self.apply(marks, "the legend symbols")


class SteelTab(_Tab):
    COLS = ["Take off", "Shape", "Members", "Length", "lb/ft", "Weight"]

    def __init__(self, dlg):
        super().__init__(dlg, "Structural framing: every member tagged with "
                         "its shape (W12X26, HSS6X6X1/4, L4X4X1/2) takes the "
                         "line drawn beside its tag; weight from the shape.")

    def find(self):
        sc = self.scale()
        if not sc:
            return []
        self.unit = sc["unit"]
        self.data = tt.steel_members(self.view.pg, sc["ppu"], sc["unit"])
        self._fill([["", g["name"], g["count"],
                     f"{_num(g['length'])} {sc['unit']}",
                     f"{g['lb_ft']:g}", f"{_num(g['lb'], 0)} lb"]
                    for g in self.data], [True] * len(self.data))
        lb = sum(g["lb"] for g in self.data)
        self.status.setText(f"{sum(g['count'] for g in self.data)} "
                            f"member(s), {_num(lb, 0)} lb "
                            f"({_num(lb / 2000, 2)} tons)." if self.data
                            else "No shape tags (W12X26 ...) found.")
        return self.data

    def add(self):
        gs = [dict(g, name=name or g["name"]) for g, name in self.chosen()]
        return self.apply(tt.run_marks(self.view.page, gs, self.unit,
                                       method="auto steel"),
                          f"{len(gs)} steel shape(s)")


class FinishTab(_Tab):
    COLS = ["Use", "Wall type (from your takeoff)", "Length", "Height",
            "Area"]

    def __init__(self, dlg):
        super().__init__(dlg, "Drywall, paint, studs and base from the "
                         "walls you took off (Auto Walls & Doors or by "
                         "hand): wall length x height x faces.",
                         "Calculate")
        self.form.insertWidget(1, QLabel("Height (ft)"))
        self.height = QDoubleSpinBox()
        self.height.setRange(1, 60)
        self.height.setValue(9)
        self.form.insertWidget(2, self.height)
        self.faces = QCheckBox("Both faces")
        self.faces.setChecked(True)
        self.form.insertWidget(3, self.faces)
        self.add_btn.setVisible(False)
        self.export_btn = QPushButton("Export to Excel…")
        self.export_btn.clicked.connect(lambda _c=False: self.export())
        self.form.addWidget(self.export_btn)

    def find(self):
        items = annotate.takeoff_items(self.view.doc)
        by = {}
        for it in items:
            if it["type"] == "length" and it["group"].lower().startswith(
                    "wall"):
                by[it["group"]] = by.get(it["group"], 0.0) + \
                    it["value"] * (it.get("multiplier") or 1)
        h = self.height.value()
        faces = 2 if self.faces.isChecked() else 1
        self.data = []
        for g, L in sorted(by.items()):
            sf = L * h * faces
            self.data.append({"group": g, "lf": L, "sf": sf,
                              "studs": math.ceil(L * 12 / 16) + 1,
                              "boards": math.ceil(sf / 32 * 1.1)})
        rows = []
        for d in self.data:
            rows.append(["Drywall / paint", d["group"], f"{_num(d['lf'])} LF",
                         f"{h:g} ft", f"{_num(d['sf'], 0)} SF "
                         f"({d['boards']} 4x8 sheets, {d['studs']} studs "
                         "@16\")"])
        self.table.setRowCount(len(rows))
        for i, vals in enumerate(rows):
            for c, val in enumerate(vals):
                it = QTableWidgetItem(val)
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(i, c, it)
        self.status.setText(f"{len(self.data)} wall type(s), "
                            f"{_num(sum(d['sf'] for d in self.data), 0)} SF "
                            "of finish." if self.data else
                            "Take off walls first (Auto Walls & Doors).")
        return self.data

    def export(self, path=None):
        if not self.data:
            self.find()
        if not self.data:
            return None
        if not path:
            path, _ = QFileDialog.getSaveFileName(
                self, "Wall Finishes", self._rname("Wall Finishes", ".xlsx"),
                "Excel (*.xlsx)")
        if not path:
            return None
        from .acrobat import write_xlsx
        rows = [["Wall type", "Length (LF)", "Height (ft)", "Area (SF)",
                 "4x8 sheets (10% waste)", "Studs @ 16 in"]]
        for d in self.data:
            rows.append([d["group"], round(d["lf"], 1), self.height.value(),
                         round(d["sf"]), d["boards"], d["studs"]])
        write_xlsx(path, [("Wall finishes", rows)])
        self.status.setText(f"Saved {path}")
        return path

    def add(self):
        return 0


class RoofTab(_Tab):
    COLS = ["Take off", "Roof area (from your takeoff)", "Plan", "Pitch",
            "Sloped", "Squares"]

    def __init__(self, dlg):
        super().__init__(dlg, "Draw the roof planes as areas (or use Auto "
                         "Area), then Find: each area takes the pitch printed "
                         "on it (6:12) and becomes the true sloped area.",
                         "Find Roof Areas")
        self.form.insertWidget(1, QLabel("Waste %"))
        self.waste = QSpinBox()
        self.waste.setRange(0, 50)
        self.waste.setValue(10)
        self.form.insertWidget(2, self.waste)
        self.form.insertWidget(3, QLabel("Pitch if none printed"))
        self.default = QDoubleSpinBox()
        from .calculators import MAX_PITCH
        self.default.setRange(0, MAX_PITCH)
        self.default.setValue(4)
        self.form.insertWidget(4, self.default)

    def find(self):
        v = self.view
        from .roof_ui import is_aerial_page
        from . import roof
        if is_aerial_page(v.doc, v.page):    # plans only (roof brief 2)
            self.data = []
            self._fill([], [])
            self.status.setText(roof.PLANS_ONLY)
            return self.data
        pg = v.pg
        pitches = tt.pitch_labels(pg)
        steep = tt.steep_pitch_labels_at(pg)
        items = [it for it in annotate.takeoff_items(v.doc)
                 if it["page"] == v.page and it["type"] == "area"]
        roofy = [it for it in items if "roof" in it["group"].lower()]
        items = roofy or items
        self.data = []
        rows, on, flagged = [], [], []
        for it in items:
            found = annotate.find_annots(pg, it["ref"])
            if not found:
                continue
            pts = [(p[0], p[1]) for p in (found[0].vertices or [])] \
                if found[0].vertices else []
            if len(pts) < 3:
                continue
            pitch, note = tt.roof_pitch(pts, pitches, steep,
                                        self.default.value())
            name = it["group"] or "Area"
            if pitch is None:
                # H3: an over-12:12 label - for review, never the default
                self.data.append(dict(item=it, pts=pts, pitch=None,
                                      review=note, squares=0.0))
                rows.append(["", name, f"{_num(it['value'], 0)} "
                             f"{it['unit']}", "check", "-", note])
                on.append(False)
                flagged.append(name)
                continue
            r = tt.roof_area(it["value"], pitch, self.waste.value() / 100)
            self.data.append(dict(r, item=it, pts=pts))
            rows.append(["", name,
                         f"{_num(r['plan'], 0)} {it['unit']}",
                         f"{pitch:g}:12", f"{_num(r['sloped'], 0)}",
                         f"{_num(r['squares'])} sq"])
            on.append(True)
        self._fill(rows, on)
        ok = [d for d in self.data if d.get("pitch") is not None]
        self.status.setText(tt.roof_status(
            len(ok), sum(d["squares"] for d in ok), flagged,
            [t for t, _v, _c in steep], bool(pitches or steep),
            self.default.value()))
        return self.data

    def add(self):
        marks = []
        for d, _name in self.chosen():
            if d.get("pitch") is None:
                continue                  # sent to review (H3)
            it = d["item"]
            grp = f"Roof {d['pitch']:g}:12"
            unit = it["unit"]
            marks.append((self.view.page, "add_polygon", {
                "pts": [list(p) for p in d["pts"]],
                "color": [0.55, 0.25, 0.75], "fill": [0.55, 0.25, 0.75],
                "opacity": 0.25,
                "label": f"{_num(d['sloped'], 0)} {unit} sloped "
                         f"({d['pitch']:g}:12)",
                "measure": {"type": "area", "value": round(d["sloped"], 2),
                            "unit": unit, "group": grp,
                            "method": "roof pitch"}}))
            marks.append((self.view.page, "delete_annot", dict(it["ref"])))
        return self.apply(marks, "the roof")


class RebarTab(_Tab):
    COLS = ["Use", "Bar", "Bars", "Laps", "Length", "Weight"]

    def __init__(self, dlg):
        super().__init__(dlg, "Reinforcing from your footing (length) or "
                         "slab (area) takeoff: bars, lap splices, 20 ft "
                         "stock pieces and weight.", "Calculate")
        f = QFormLayout()
        self.group = QComboBox()
        self.bar = QComboBox()
        self.bar.addItems([f"#{b}" for b in tt.BARS])
        self.bar.setCurrentText("#4")
        self.count = QSpinBox()
        self.count.setRange(1, 20)
        self.count.setValue(3)
        self.spacing = QSpinBox()
        self.spacing.setRange(3, 48)
        self.spacing.setValue(12)
        self.both = QCheckBox("Both ways")
        self.both.setChecked(True)
        f.addRow("From takeoff group", self.group)
        f.addRow("Bar size", self.bar)
        f.addRow("Bars along a footing", self.count)
        f.addRow("Slab spacing (in)", self.spacing)
        f.addRow("", self.both)
        lay = self.layout()
        lay.insertLayout(1, f)
        self.export_btn = QPushButton("Export to Excel…")
        self.export_btn.clicked.connect(lambda _c=False: self.export())
        self.add_btn.setVisible(False)
        self.form.addWidget(self.export_btn)
        self.refresh_groups()

    def refresh_groups(self):
        items = annotate.takeoff_items(self.view.doc) if self.view else []
        self._items = items
        groups = sorted({(it["group"] or "(no group)", it["type"])
                         for it in items if it["type"] in ("length",
                                                           "area")})
        self.group.clear()
        for g, t in groups:
            self.group.addItem(f"{g}  ({'footing' if t == 'length' else 'slab'})",
                               (g, t))

    def find(self):
        data = self.group.currentData()
        if not data:
            self.status.setText("Take off footings (lengths) or slabs "
                                "(areas) first.")
            return []
        g, t = data
        bar = int(self.bar.currentText()[1:])
        items = [it for it in self._items
                 if (it["group"] or "(no group)") == g and it["type"] == t]
        rows = []
        for it in items:
            if t == "length":
                rows += tt.rebar_linear(it["value"], bar, self.count.value())
            else:
                per = 4 * math.sqrt(max(it["value"], 0))   # as a square
                rows += tt.rebar_slab(it["value"], per, bar,
                                      self.spacing.value(),
                                      self.both.isChecked())
        self.rows = rows
        tot = tt.rebar_totals(rows)
        self.data = tot
        self.table.setRowCount(len(tot))
        for i, r in enumerate(tot):
            for c, val in enumerate(["Total", f"#{r['bar']}",
                                     f"{r['pieces']} x 20 ft", "",
                                     f"{_num(r['lf'], 0)} LF",
                                     f"{_num(r['lb'], 0)} lb"]):
                it = QTableWidgetItem(val)
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(i, c, it)
        lb = sum(r["lb"] for r in tot)
        self.status.setText(f"{len(items)} item(s) of {g}: {_num(lb, 0)} lb "
                            f"({_num(lb / 2000, 2)} tons).")
        return tot

    def export(self, path=None):
        if not getattr(self, "rows", None):
            self.find()
        if not getattr(self, "rows", None):
            return None
        if not path:
            path, _ = QFileDialog.getSaveFileName(
                self, "Rebar Schedule", self._rname("Rebar Schedule", ".xlsx"),
                "Excel (*.xlsx)")
        if not path:
            return None
        from .acrobat import write_xlsx
        rows = [["Use", "Bar", "Bars", "Lap splices", "Length (LF)",
                 "Stock pieces (20 ft)", "Weight (lb)"]]
        for r in self.rows:
            rows.append([r["use"], f"#{r['bar']}", r["count"], r["laps"],
                         round(r["lf"], 1), r["pieces"], round(r["lb"], 1)])
        rows.append([])
        for r in tt.rebar_totals(self.rows):
            rows.append(["Total", f"#{r['bar']}", "", "", round(r["lf"], 1),
                         r["pieces"], round(r["lb"], 1)])
        write_xlsx(path, [("Rebar", rows)])
        self.status.setText(f"Saved {path}")
        return path

    def add(self):
        return 0


class EarthTab(_Tab):
    COLS = ["", "Result", "Value"]

    def __init__(self, dlg):
        super().__init__(dlg, "Cut and fill between existing and proposed "
                         "contours, each named by its elevation label, inside "
                         "the site boundary (an area named Site, Grading or "
                         "Earthwork, else the largest area on the sheet).",
                         "Find Contours")
        f = QFormLayout()
        self.existing = QComboBox()
        self.proposed = QComboBox()
        self.cell = QDoubleSpinBox()
        self.cell.setRange(1, 50)
        self.cell.setValue(5)
        f.addRow("Existing contours", self.existing)
        f.addRow("Proposed contours", self.proposed)
        f.addRow("Grid (ft)", self.cell)
        self.layout().insertLayout(1, f)
        self.calc_btn = QPushButton("Calculate Cut / Fill")
        self.calc_btn.clicked.connect(self.calculate)
        self.form.addWidget(self.calc_btn)
        self.sets = []
        self.result = None

    def find(self):
        sc = self.scale()
        if not sc:
            return []
        self.sc = sc
        self.sets = tt.contour_sets(self.view.pg, sc["ppu"], sc["unit"])
        for box in (self.existing, self.proposed):
            box.clear()
            for s in self.sets:
                zs = sorted({l["z"] for l in s["lines"]})
                box.addItem(f"{s['style_name']} ({len(s['lines'])} lines, "
                            f"{zs[0]:g}-{zs[-1]:g})", s)
        dashed = [i for i, s in enumerate(self.sets) if s["dashed"]]
        solid = [i for i, s in enumerate(self.sets) if not s["dashed"]]
        if dashed:
            self.existing.setCurrentIndex(dashed[0])
        if solid:
            self.proposed.setCurrentIndex(solid[0])
        elif len(self.sets) > 1:
            self.proposed.setCurrentIndex(1)
        self.status.setText(f"{len(self.sets)} labelled contour set(s). "
                            "Existing is usually dashed, proposed solid."
                            if self.sets else "No contours with elevation "
                            "labels found on this sheet.")
        return self.sets

    def boundary(self):
        v = self.view
        items = [it for it in annotate.takeoff_items(v.doc)
                 if it["page"] == v.page and it["type"] == "area"]
        named = [it for it in items if any(
            k in it["group"].lower() for k in ("site", "grading", "earth"))]
        pick = max(named or items, key=lambda it: it["value"], default=None)
        if pick is None:
            return None, None
        a = annotate.find_annots(v.pg, pick["ref"])
        if not a or not a[0].vertices:
            return None, None
        return [(p[0], p[1]) for p in a[0].vertices], pick

    def calculate(self):
        if not self.sets:
            self.find()
        ex, pr = self.existing.currentData(), self.proposed.currentData()
        if not ex or not pr or ex is pr:
            self.status.setText("Pick an existing and a proposed contour "
                                "set.")
            return None
        bnd, item = self.boundary()
        if not bnd:
            self.status.setText("Draw the site boundary as an area first "
                                "(name its group Site or Grading).")
            return None
        res = tt.cut_fill(ex["lines"], pr["lines"], bnd, self.sc["ppu"],
                          self.sc["unit"], self.cell.value())
        self.result, self.bnd = res, bnd
        rows = [["", "Cut", f"{_num(res['cut'])} CY"],
                ["", "Fill", f"{_num(res['fill'])} CY"],
                ["", "Net (fill - cut)", f"{_num(res['net'])} CY"],
                ["", "Area checked", f"{_num(res['area'], 0)} SF"]]
        self.data = rows
        self._fill(rows, [True] * 4)
        for i in range(4):
            self.table.item(i, 0).setFlags(Qt.ItemIsEnabled)
        self.status.setText("Add to Takeoff puts Cut and Fill on the "
                            "boundary as volume measurements.")
        return res

    def add(self):
        if not self.result:
            return 0
        marks = []
        for grp, val, col in (("Earthwork cut", self.result["cut"],
                               (0.85, 0.3, 0.1)),
                              ("Earthwork fill", self.result["fill"],
                               (0.1, 0.45, 0.8))):
            marks.append((self.view.page, "add_polygon", {
                "pts": [list(p) for p in self.bnd], "color": list(col),
                "fill": list(col), "opacity": 0.12,
                "label": f"{grp}: {_num(val)} CY",
                "measure": {"type": "volume", "value": round(val, 2),
                            "unit": "cu yd", "group": grp,
                            "method": "cut fill"}}))
        return self.apply(marks, "earthwork")


class TradeTakeoffDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.added = 0
        self.setWindowTitle("Trade Takeoff")
        self.resize(900, 620)
        v = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.pipe = PipeTab(self)
        self.civil = CivilTab(self)
        self.duct = DuctTab(self)
        self.legend = LegendTab(self)
        self.steel = SteelTab(self)
        self.finish = FinishTab(self)
        self.roof = RoofTab(self)
        self.rebar = RebarTab(self)
        self.earth = EarthTab(self)
        for t, name in ((self.civil, "Civil && Utilities"),
                        (self.pipe, "Pipe && Conduit"),
                        (self.duct, "Ductwork"),
                        (self.legend, "Fixtures && Devices"),
                        (self.steel, "Structural Steel"),
                        (self.finish, "Drywall && Paint"),
                        (self.roof, "Roofing"), (self.rebar, "Rebar"),
                        (self.earth, "Earthwork")):
            self.tabs.addTab(t, name)          # "&&" shows a single &
        v.addWidget(self.tabs, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)


# ------------------------------------------------------------- review
def _solid(r):
    """An accepted AI proposal stops being pencil: its line goes solid,
    a count dot loses its dashed ring."""
    return {"dashes": []} if str(r.get("method") or "").startswith(
        ("AI takeoff", "auto")) else {}


class CheckTakeoffDialog(QDialog):
    """Step through automatic measurements and accept or delete each."""

    def __init__(self, win, include_manual=False):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Check Takeoff")
        self.setModal(False)
        self.resize(520, 260)
        self.include_manual = include_manual
        v = QVBoxLayout(self)
        self.title = QLabel()
        self.title.setWordWrap(True)
        f = self.title.font()
        f.setPointSizeF(f.pointSizeF() + 1.5)
        f.setBold(True)
        self.title.setFont(f)
        v.addWidget(self.title)
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        v.addWidget(self.detail)
        self.progress = QLabel()
        self.progress.setObjectName("muted")
        v.addWidget(self.progress)
        row = QHBoxLayout()
        for label, fn, key in (("Accept", self.accept_one, "A"),
                               ("Delete", self.delete_one, "D"),
                               ("Skip", self.next, "S"),
                               ("Accept Rest of Group", self.accept_group,
                                "")):
            b = QPushButton(label)
            if key:
                b.setShortcut(key)
                b.setToolTip(f"{label} ({key})")
            b.clicked.connect(fn)
            row.addWidget(b)
        v.addLayout(row)
        self.load()

    def load(self):
        from . import audit
        doc = self.win._view.doc
        rows = audit.trail(doc)
        self.all = rows
        self.queue = [r for r in rows
                      if r["status"] not in ("Accepted",) and
                      (self.include_manual or r["method"] not in
                       ("manual", "unknown"))]
        self.i = 0
        self.show_current()

    def counts(self):
        auto = [r for r in self.all if self.include_manual or
                r["method"] not in ("manual", "unknown")]
        done = sum(1 for r in auto if r["status"] == "Accepted")
        return done, len(auto)

    def current(self):
        return self.queue[self.i] if 0 <= self.i < len(self.queue) else None

    def show_current(self):
        done, total = self.counts()
        self.progress.setText(f"{done} of {total} automatic measurement(s) "
                              f"checked · {len(self.queue) - self.i} to go")
        r = self.current()
        if r is None:
            self.title.setText("Every automatic measurement is checked."
                               if total else "No automatic measurements "
                               "to check.")
            self.detail.setText("")
            return None
        conf = f" · confidence {r['confidence']:.0%}" \
            if isinstance(r.get("confidence"), (int, float)) else ""
        self.title.setText(f"{r['group'] or 'Measurement'}: "
                           f"{r['value']:,.2f} {r['unit']}")
        self.detail.setText(f"Sheet {r['sheet'] or r['page'] + 1} · "
                            f"{r['method']}{conf} · {r['author']}")
        self._zoom(r)
        return r

    def _zoom(self, r):
        v = self.win._view
        if v.page != r["page"]:
            v.go_to(r["page"])
        a = annotate.find_annots(v.pg, r["ref"])
        if not a:
            return
        rect = annotate.from_page(v.pg, fitz.Rect(a[0].rect))
        del a                    # zooming redraws: the page object changes
        pad = max(rect.width, rect.height) * 0.6 + 30
        self.win.zoom_to_rect(rect + (-pad, -pad, pad, pad))
        a = annotate.find_annots(v.pg, r["ref"])
        if a:
            v.select(a[0])

    def _op(self, kind, payload, page):
        v = self.win._view
        return v.apply_marks([(page, kind, payload)])

    def accept_one(self):
        r = self.current()
        if r is None:
            return 0
        n = self._op("set_annot", dict(r["ref"], status="Accepted",
                                       **_solid(r)), r["page"])
        r["status"] = "Accepted"
        self.i += 1
        self.show_current()
        return n

    def delete_one(self):
        r = self.current()
        if r is None:
            return 0
        n = self._op("delete_annot", dict(r["ref"]), r["page"])
        self.all.remove(r)
        self.queue.pop(self.i)
        self.show_current()
        return n

    def next(self):
        if self.i < len(self.queue):
            self.i += 1
        self.show_current()

    def accept_group(self):
        r = self.current()
        if r is None:
            return 0
        same = [q for q in self.queue[self.i:] if q["group"] == r["group"]]
        v = self.win._view
        n = v.apply_marks([(q["page"], "set_annot",
                            dict(q["ref"], status="Accepted", **_solid(q)))
                           for q in same])
        for q in same:
            q["status"] = "Accepted"
        self.queue = self.queue[:self.i] + [q for q in self.queue[self.i:]
                                            if q not in same]
        self.show_current()
        return n
