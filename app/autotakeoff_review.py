"""Auto Takeoff, run and review.

1. Pick what to take off: Rooms (floor areas), Walls (LF by type),
   Doors (by width), Wall paint (LF x height x sides). The page must have
   a scale (NeedScale otherwise).
2. collect() runs Claude's engines through their public functions only:
   autotakeoff.all_rooms, autowalls.walls / raster_segments / doors.
   Each result becomes a candidate with a confidence. Room tags with no
   room found are listed too (conf 0) so a missed room is never silent.
3. ReviewDialog: lowest confidence first. A / Space accept, X / Delete
   reject, U undecided, Enter apply; each row's item name is a combo to
   reassign it (e.g. "Room" -> "Office Carpet"). Double-click jumps.
4. marks() / commit(): only accepted candidates become measurements,
   tagged "auto takeoff (reviewed)", in one undo step via the viewer.
"""
import logging
import fitz

from . import annotate

TYPES = {"rooms": "Rooms (floor area)", "walls": "Walls (LF by type)",
         "doors": "Doors (count by width)", "paint": "Wall paint (SF)"}
COLORS = {"rooms": (0.1, 0.45, 0.85), "walls": (0.85, 0.1, 0.1),
          "doors": (0.9, 0.5, 0.0), "paint": (0.55, 0.2, 0.75)}


class NeedScale(RuntimeError):
    pass


def _room_conf(r):
    if r.get("per_tag"):
        return 0.7
    tag = r.get("tag_sf")
    if tag:
        err = abs(r["sqft"] - tag) / max(tag, 1)
        return round(max(0.3, 0.98 - 2 * err), 3)
    return 0.65


def _wall_conf(w):
    t, L = w.get("thickness", 0), w.get("length", 0)
    c = 0.9 if 3.5 <= t <= 8.5 else 0.75
    if L < 2:
        c -= 0.35
    return round(c, 3)


def collect(doc, pno, scale, types=("rooms", "walls", "doors"),
            wall_height=None, paint_sides=2):
    """Candidates [{id, type, group, value, unit, conf, page, kind,
    payload, state, rect, missing}] for page `pno`."""
    if not scale or not scale.get("ppu"):
        raise NeedScale("Set and check the page scale first (Auto Scale).")
    types = set(types)
    page = doc[pno]
    unit = scale.get("unit", "ft")
    out = []

    def add(t, group, value, u, conf, kind, payload, rect, missing=False):
        out.append({"id": len(out), "type": t, "group": group, "value": value,
                    "unit": u, "conf": conf, "page": pno, "kind": kind,
                    "payload": payload, "state": "pending", "rect": rect,
                    "missing": missing})

    if "rooms" in types:
        from . import autotakeoff
        found, missed = autotakeoff.all_rooms(page, scale)
        for r in found:
            pts = [annotate.to_page(page, q) for q in r["pts"]]
            rect = list(fitz.Rect(min(p.x for p in pts), min(p.y for p in pts),
                                  max(p.x for p in pts), max(p.y for p in pts)))
            add("rooms", r.get("name") or "Room", r["value"], r["unit"],
                _room_conf(r), "add_polygon",
                {"pts": [[q.x, q.y] for q in pts], "opacity": 0.25,
                 "fill": list(COLORS["rooms"])}, rect)
        for t in missed:
            pt = t.get("pt")
            rect = [pt[0] - 10, pt[1] - 10, pt[0] + 10, pt[1] + 10] if pt else None
            add("rooms", f"{t.get('name') or 'Room'} (NOT FOUND - draw it)", 0.0,
                f"sq {unit}", 0.0, None, None, rect, missing=True)
    if types & {"walls", "doors", "paint"}:
        from . import autowalls
        ws, ds = [], []
        if types & {"walls", "paint"}:
            try:
                ws = autowalls.walls(page, scale["ppu"], unit)
            except Exception:
                ws = []
            if len(ws) < 2 and len(autowalls.segments(page)) < 200:
                segs = autowalls.raster_segments(page, scale["ppu"], unit)
                ws = autowalls.walls(page, scale["ppu"], unit, segs=segs)
        if "doors" in types:
            ds = autowalls.doors(page, scale["ppu"], unit,
                                 include_narrow=True)
        for w in ws:
            t = autowalls.wall_type(w["thickness"])
            pts = [list(w["p0"]), list(w["p1"])]
            rect = list(fitz.Rect(fitz.Point(*w["p0"]), fitz.Point(*w["p1"])).normalize()
                        + (-6, -6, 6, 6))
            if "walls" in types:
                add("walls", t, w["length"], unit, _wall_conf(w), "add_line",
                    {"pts": pts, "width": 3, "opacity": 0.6}, rect)
            if "paint" in types and wall_height:
                add("paint", f"Paint {t} ({paint_sides} side, {wall_height:g} ft)",
                    w["length"] * float(wall_height) * int(paint_sides),
                    f"sq {unit}", _wall_conf(w), "add_line",
                    {"pts": pts, "width": 2, "opacity": 0.4}, rect)
        for d in ds:
            h = d["hinge"]
            name = autowalls.door_type(d["width"])
            if d.get("narrow"):       # partition / shower door? (NW-17)
                name += " (narrow - toilet partition or shower?)"
            add("doors", name, 1, "ea", 0.4 if d.get("narrow") else 0.85,
                "add_count",
                {"pt": list(h)}, [h[0] - 12, h[1] - 12, h[0] + 12, h[1] + 12])
    return out


def review_order(cands):
    return sorted(cands, key=lambda c: (c["conf"], c["type"], c["group"]))


def marks(cands):
    """Viewer marks [(page, kind, payload)] for accepted candidates."""
    out, n = [], {}
    for c in cands:
        if c["state"] != "accepted" or c.get("missing") or not c["kind"]:
            continue
        p = dict(c["payload"])
        p.setdefault("color", list(COLORS.get(c["type"], (1, 0, 0))))
        if c["kind"] == "add_count":
            n[c["group"]] = n.get(c["group"], 0) + 1
            p["n"] = n[c["group"]]
        mtype = {"rooms": "area", "walls": "length", "paint": "area",
                 "doors": "count"}[c["type"]]
        p["measure"] = {"type": mtype, "value": round(float(c["value"]), 4),
                        "unit": c["unit"], "group": c["group"],
                        "method": f"auto takeoff (reviewed): {c['type']}",
                        "confidence": c["conf"]}
        out.append((c["page"], c["kind"], p))
    return out


def commit(doc, cands):
    """Apply accepted candidates directly (CLI / tests). Returns count."""
    k = 0
    for page, kind, p in marks(cands):
        if annotate.apply_op(doc, annotate.new_op(kind, page, **p)):
            k += 1
    return k


class AutoTakeoffFailed(RuntimeError):
    """collect() failed on the worker thread (its message for the user)."""


def collect_in_background(parent, doc, pno, scale, types, height, sides,
                          timeout=None):
    """collect() on a worker thread, on a copy of the drawing, while the
    window keeps running (a busy box with Stop is shown when `parent` is
    given). Returns the candidates; raises AutoTakeoffFailed with the
    worker's message (NeedScale's too), or TimeoutError. Stop returns [] (nothing added)."""
    import time
    from PySide6.QtWidgets import QApplication, QProgressDialog
    from . import bg
    work = fitz.open("pdf", doc.tobytes())
    state = {"done": False, "res": None, "err": None, "stop": False}

    def job():
        try:
            return collect(work, pno, scale, types, height, sides)
        finally:
            try:
                work.close()
            except Exception:                            # noqa: BLE001
                pass

    def ok(res):
        state.update(done=True, res=res)

    def bad(msg):
        state.update(done=True, err=msg or "Auto takeoff couldn't run.")
    box = None
    if parent is not None:
        box = QProgressDialog("Finding rooms and walls on this sheet…",
                              "Stop", 0, 0, parent)
        box.setWindowTitle("Auto Takeoff")
        box.setMinimumDuration(300)
        box.canceled.connect(lambda: state.__setitem__("stop", True))
    owner = parent if parent is not None else QApplication.instance()
    bg.run(job, ok, bad, owner)
    t0 = time.time()
    try:
        while not state["done"] and not state["stop"]:
            if timeout is not None and time.time() - t0 > timeout:
                raise TimeoutError(
                    f"Auto Takeoff still running after {timeout:.0f} s")
            QApplication.processEvents()
            time.sleep(0.02)
    finally:
        if box is not None:
            box.close()
    if state["stop"] and not state["done"]:
        return []
    if state["err"] is not None:
        raise AutoTakeoffFailed(state["err"])
    return state["res"] or []


# ---------------------------------------------------------------- dialogs
try:
    from PySide6.QtCore import QEvent, Qt, Signal
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                                   QDoubleSpinBox, QFormLayout, QLabel, QSpinBox,
                                   QTableWidget, QTableWidgetItem, QVBoxLayout)
except ImportError:
    QDialog = None

if QDialog is not None:
    class PickDialog(QDialog):
        """What to take off on this page."""

        def __init__(self, parent=None):
            super().__init__(parent)
            self.setWindowTitle("Auto Takeoff - what to take off")
            lay = QFormLayout(self)
            self.boxes = {}
            for k, label in TYPES.items():
                b = QCheckBox(label)
                b.setChecked(k != "paint")
                self.boxes[k] = b
                lay.addRow(b)
            self.height = QDoubleSpinBox()
            self.height.setRange(1, 60)
            self.height.setValue(9.0)
            self.height.setSuffix(" ft")
            self.sides = QSpinBox()
            self.sides.setRange(1, 2)
            self.sides.setValue(2)
            lay.addRow("Wall height", self.height)
            lay.addRow("Paint sides", self.sides)
            bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            bb.accepted.connect(self.accept)
            bb.rejected.connect(self.reject)
            lay.addRow(bb)

        def choice(self):
            return ({k for k, b in self.boxes.items() if b.isChecked()},
                    self.height.value(), self.sides.value())

    class ReviewDialog(QDialog):
        """Lowest confidence first. A/Space accept, X/Del reject, U undo,
        Enter apply. Item name combo = reassign."""
        go_to = Signal(int, object)
        COLS = ["State", "Type", "Item (reassign)", "Qty", "Unit", "Conf."]
        MARK = {"pending": "?", "accepted": "✓", "rejected": "✗"}

        def __init__(self, doc, cands, groups=(), parent=None):
            super().__init__(parent)
            self.doc = doc
            self.items = review_order(cands)
            self.setWindowTitle("Auto Takeoff - review (lowest confidence first)")
            lay = QVBoxLayout(self)
            self.info = QLabel("")
            lay.addWidget(self.info)
            t = self.table = QTableWidget(len(self.items), len(self.COLS))
            t.setHorizontalHeaderLabels(self.COLS)
            t.setSelectionBehavior(QTableWidget.SelectRows)
            t.setEditTriggers(QTableWidget.NoEditTriggers)
            names = sorted({c["group"] for c in self.items if not c.get("missing")}
                           | set(groups))
            self.combos = []
            for i, c in enumerate(self.items):
                vals = [self.MARK[c["state"]], c["type"], None,
                        f"{c['value']:,.2f}" if c["type"] != "doors" else "1",
                        c["unit"], f"{c['conf']:.2f}"]
                for col, v in enumerate(vals):
                    if v is not None:
                        t.setItem(i, col, QTableWidgetItem(v))
                cb = QComboBox()
                cb.setEditable(True)
                cb.addItems(names if not c.get("missing") else [c["group"]])
                cb.setCurrentText(c["group"])
                cb.setEnabled(not c.get("missing"))
                cb.currentTextChanged.connect(lambda txt, r=i: self.reassign(r, txt))
                t.setCellWidget(i, 2, cb)
                self.combos.append(cb)
                if c["conf"] < 0.8:
                    for col in (0, 1, 3, 4, 5):
                        t.item(i, col).setBackground(
                            QColor("#f8d7da") if c.get("missing") else QColor("#fff3cd"))
            t.installEventFilter(self)
            t.cellDoubleClicked.connect(
                lambda r, _c: self.go_to.emit(self.items[r]["page"], self.items[r]["rect"]))
            lay.addWidget(t)
            bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            bb.button(QDialogButtonBox.Ok).setText("Add accepted to takeoff")
            bb.accepted.connect(self.accept)
            bb.rejected.connect(self.reject)
            lay.addWidget(bb)
            self.resize(820, 520)
            self._count()

        def eventFilter(self, obj, ev):
            if obj is self.table and ev.type() == QEvent.KeyPress:
                k = ev.key()
                st = {Qt.Key_A: "accepted", Qt.Key_Space: "accepted",
                      Qt.Key_X: "rejected", Qt.Key_Delete: "rejected",
                      Qt.Key_U: "pending"}.get(k)
                if st:
                    self.set_state(self.table.currentRow(), st, advance=True)
                    return True
                if k in (Qt.Key_Return, Qt.Key_Enter):
                    self.accept()
                    return True
            return super().eventFilter(obj, ev)

        def set_state(self, row, state, advance=False):
            if not (0 <= row < len(self.items)):
                return
            c = self.items[row]
            if c.get("missing") and state == "accepted":
                state = "pending"            # nothing to add: draw it by hand
            c["state"] = state
            self.table.item(row, 0).setText(self.MARK[state])
            if advance and row + 1 < len(self.items):
                self.table.setCurrentCell(row + 1, 0)
            self._count()

        def reassign(self, row, name):
            name = (name or "").strip()
            if name and not self.items[row].get("missing"):
                self.items[row]["group"] = name
                if self.combos[row].currentText() != name:
                    self.combos[row].setCurrentText(name)

        def accepted(self):
            return [c for c in self.items if c["state"] == "accepted"]

        def _count(self):
            a = len(self.accepted())
            p = sum(1 for c in self.items if c["state"] == "pending")
            m = sum(1 for c in self.items if c.get("missing"))
            self.info.setText(f"{a} accepted, {p} to decide, {m} room tags with no "
                              "room found (draw those by hand). A/Space accept · "
                              "X reject · U undo · Enter add")

    def run_dialog(win):
        """Pick, run, review, add (one undo step through the viewer)."""
        from PySide6.QtWidgets import QMessageBox
        v = getattr(win, "_view", None)
        if v is None:
            return 0
        pick = PickDialog(win)
        if pick.exec() != QDialog.Accepted:
            return 0
        types, height, sides = pick.choice()
        try:
            # on a worker thread: the window stays live (Oct 31)
            cands = collect_in_background(win, v.doc, v.page, v.scale(),
                                          types, height, sides)
        except NeedScale as e:
            QMessageBox.information(win, "Auto Takeoff", str(e))
            return 0
        except AutoTakeoffFailed as e:
            QMessageBox.information(win, "Auto Takeoff",
                                    str(e) or "Auto takeoff couldn't run on "
                                    "this sheet.")
            return 0
        except Exception as e:      # AutoTakeoffError ("scale too small"),
            from . import autotakeoff     # or anything else: say so, never
            if not isinstance(e, autotakeoff.AutoTakeoffError):   # silence
                logging.getLogger(__name__).warning(
                    "auto takeoff failed", exc_info=True)
            QMessageBox.information(win, "Auto Takeoff",
                                    str(e) or "Auto takeoff couldn't run on "
                                    "this sheet.")
            return 0
        groups = sorted({i["group"] for i in annotate.takeoff_items(v.doc) if i["group"]})
        dlg = ReviewDialog(v.doc, cands, groups, win)
        if hasattr(win, "_go_annot"):
            dlg.go_to.connect(lambda p, r: v.go_to(p))
        if dlg.exec() != QDialog.Accepted:
            return 0
        mk = marks(dlg.accepted())
        if mk:
            v.apply_marks(mk)
        return len(mk)
