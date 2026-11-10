"""Compare Revisions window (File > Compare Revisions / Overlay)."""
import os

import fitz
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QGraphicsScene, QGraphicsView, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QProgressDialog,
    QPushButton, QRadioButton, QSplitter, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget)

from . import overlay
from .dmoney import c2 as _c2


def describe(m):
    s, tx, ty = m[0], m[1], m[2]
    rot = m[4] if len(m) > 4 else 0.0
    if overlay.is_identity(m):
        return "as is"
    out = f"moved {tx:+.0f}, {ty:+.0f} pt"
    if abs(s - 1) > 0.0005:
        out += f", scale {s:.3f}"
    if abs(rot) >= 0.01:
        out += f", turned {_c2(rot):+.2f}°"
    return out


def _qc(rgb):
    return QColor(*[int(c * 255) for c in rgb])


class CompareRevisionsDialog(QDialog):
    def __init__(self, window, other=None):
        super().__init__(window)
        self.win = window
        self.view = window._view
        self.setWindowTitle("Compare Revisions")
        self.resize(980, 620)
        self.results = None
        self.other_doc = None
        lay = QVBoxLayout(self)
        form = QFormLayout()
        row = QHBoxLayout()
        self.path = QLineEdit(other or "")
        self.path.setPlaceholderText("The other revision (PDF)")
        b = QPushButton("Browse…")
        b.clicked.connect(self._browse)
        row.addWidget(self.path, 1)
        row.addWidget(b)
        form.addRow("Compare with:", row)
        row = QHBoxLayout()
        self.is_older = QRadioButton("older revision")
        self.is_newer = QRadioButton("newer revision")
        self.is_newer.setChecked(True)
        row.addWidget(QLabel("That file is the"))
        row.addWidget(self.is_older)
        row.addWidget(self.is_newer)
        row.addStretch()
        form.addRow("", row)
        row = QHBoxLayout()
        self.by_number = QCheckBox("Match sheets by sheet number")
        self.by_number.setChecked(True)
        self.auto = QCheckBox("Line up automatically")
        self.auto.setChecked(True)
        self.only_new = QCheckBox("Cloud only changes not taken off yet")
        self.only_new.setChecked(True)
        self.only_new.setToolTip("Changes your markups or takeoff already "
                                 "cover aren't clouded; the rest show up "
                                 "on the Pre-bid Checklist")
        row.addWidget(self.by_number)
        row.addWidget(self.auto)
        row.addWidget(self.only_new)
        self.old_color, self.new_color = overlay.OLD_COLOR, overlay.NEW_COLOR
        self.old_btn = QPushButton("Older color")
        self.new_btn = QPushButton("Newer color")
        self.old_btn.clicked.connect(lambda: self._pick("old"))
        self.new_btn.clicked.connect(lambda: self._pick("new"))
        row.addWidget(self.old_btn)
        row.addWidget(self.new_btn)
        row.addStretch()
        self._paint_buttons()
        form.addRow("Options:", row)
        lay.addLayout(form)
        go = QPushButton("Compare")
        go.setDefault(True)
        go.clicked.connect(self.run)
        lay.addWidget(go)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Sheet", "This document", "Other", "Lined up", "Overlap",
             "Changes", "Linework changed"])
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.Stretch)
        self.table.cellDoubleClicked.connect(self._go)
        lay.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.b_manual = QPushButton("Align Manually…")
        self.b_manual.setToolTip("Click the same 2 (or more) points on both "
                                 "sheets - for scans, rotated plots or when "
                                 "the automatic line-up is off")
        self.b_manual.setEnabled(False)
        self.b_manual.clicked.connect(lambda: self.align_manually())
        row.addWidget(self.b_manual)
        row.addStretch()
        lay.addLayout(row)
        self.summary = QLabel("Pick the other revision and click Compare.")
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        row = QHBoxLayout()
        self.b_overlay = QPushButton("Open Overlay")
        self.b_overlay.setToolTip("A new document: older in red, newer in "
                                  "green, each on its own layer, changes "
                                  "clouded")
        self.b_clouds = QPushButton("Cloud Changes on This Document")
        self.b_slip = QPushButton("Slip Sheet: Update This Set to the Newer "
                                  "Revision")
        self.b_slip.setToolTip(
            "Put the newer drawings into this document, lined up with the "
            "old ones, keeping your markups and takeoffs. The old drawings "
            "stay as a hidden layer; takeoffs on changed areas are marked "
            "\"Check - drawing revised\".")
        self.b_carry = QPushButton("Carry Takeoff From the Older Set")
        self.b_carry.setToolTip(
            "This document is the newer set: copy every takeoff and markup "
            "from the older set onto it, lined up sheet by sheet, with the "
            "scales. Takeoffs on changed areas come across marked "
            "\"Check - drawing revised\".")
        for b, fn in ((self.b_overlay, self.make_overlay),
                      (self.b_clouds, self.cloud),
                      (self.b_slip, self.slip),
                      (self.b_carry, self.carry)):
            b.clicked.connect(fn)
            b.setEnabled(False)
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.is_older.toggled.connect(self._enable)

    # ---- setup ------------------------------------------------------------------
    def _browse(self):
        p, _ = QFileDialog.getOpenFileName(self, "Other Revision", "",
                                           "PDF (*.pdf)")
        if p:
            self.path.setText(p)

    def _pick(self, which):
        cur = self.old_color if which == "old" else self.new_color
        c = QColorDialog.getColor(_qc(cur), self)
        if c.isValid():
            rgb = (c.redF(), c.greenF(), c.blueF())
            if which == "old":
                self.old_color = rgb
            else:
                self.new_color = rgb
            self._paint_buttons()

    def _paint_buttons(self):
        for b, c in ((self.old_btn, self.old_color),
                     (self.new_btn, self.new_color)):
            q = _qc(c)
            b.setStyleSheet(f"color: {q.name()}; font-weight: bold")

    def _enable(self):
        done = self.results is not None
        this_newer = self.is_older.isChecked()
        self.b_overlay.setEnabled(done)
        self.b_clouds.setEnabled(done and any(r["changes"]
                                              for r in self.results or []))
        self.b_slip.setEnabled(done and not this_newer)
        self.b_carry.setEnabled(done and this_newer)
        self.b_manual.setEnabled(done)

    def sides(self):
        """(older doc, newer doc, side of this document)."""
        if self.is_older.isChecked():          # other is older
            return self.other_doc, self.view.doc, "new"
        return self.view.doc, self.other_doc, "old"

    # ---- compare -------------------------------------------------------------------
    def run(self):
        p = self.path.text().strip()
        if not p or not os.path.exists(p):
            QMessageBox.warning(self, "Compare Revisions", "Pick the other "
                                "revision's PDF.")
            return None
        try:
            if self.other_doc is not None:
                self.other_doc.close()
            self.other_doc = fitz.open(p)
        except Exception as e:
            QMessageBox.warning(self, "Compare Revisions", str(e))
            return None
        old, new, side = self.sides()
        dlg = QProgressDialog("Comparing sheets…", "Stop", 0, 1, self)
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(400)

        def progress(k, n, sheet):
            dlg.setMaximum(n)
            dlg.setValue(k)
            dlg.setLabelText(f"Comparing {sheet or f'page {k + 1}'} "
                             f"({k + 1} of {n})…")
            QApplication.processEvents()
            return dlg.wasCanceled()

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.results = overlay.compare(
                old, new, self.by_number.isChecked(),
                self.auto.isChecked(), True, progress)
        finally:
            QApplication.restoreOverrideCursor()
            dlg.close()
        self.fill()
        self._enable()
        return self.results

    def fill(self):
        side = self.sides()[2]
        other = "old" if side == "new" else "new"
        rs = self.results or []
        self.table.setRowCount(len(rs))
        for r, x in enumerate(rs):
            score = x["align"][3]
            moved = "-" if x["old"] is None or x["new"] is None else \
                describe(x["align"]) + (" (by hand)" if x.get("manual")
                                        else "")
            state = ("only in the newer set" if x["old"] is None else
                     "only in the older set" if x["new"] is None else
                     f"{len(x['changes'])}")
            vals = [x["sheet"] or "",
                    "" if x[side] is None else f"page {x[side] + 1}",
                    "" if x[other] is None else f"page {x[other] + 1}",
                    moved, f"{score * 100:.0f}%" if score else "",
                    state, f"{x['changed_pct']:g}%"
                    if x["old"] is not None and x["new"] is not None else ""]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.table.setItem(r, c, it)
        n = sum(len(x["changes"]) for x in rs)
        changed = sum(1 for x in rs if x["changes"])
        added = sum(1 for x in rs if x["old"] is None)
        removed = sum(1 for x in rs if x["new"] is None)
        self.summary.setText(
            f"{len(rs)} sheet(s): {changed} changed ({n} change area(s)), "
            f"{added} new, {removed} dropped. Double-click a row to go to "
            "that page.")

    def current_row(self):
        r = self.table.currentRow()
        rs = self.results or []
        if 0 <= r < len(rs) and rs[r]["old"] is not None and \
                rs[r]["new"] is not None:
            return r
        return next((k for k, x in enumerate(rs) if x["old"] is not None
                     and x["new"] is not None), None)

    def align_manually(self, row=None, points=None, apply_all=None):
        """Pick matching points on both sheets of a pair. `points` =
        (old points, new points) skips the window (for scripts/tests)."""
        old, new, _side = self.sides()
        row = self.current_row() if row is None else row
        if row is None:
            return None
        x = self.results[row]
        op, np_ = old[x["old"]], new[x["new"]]
        if points is None:
            dlg = PointAlignDialog(op, np_, x["sheet"], self)
            if dlg.exec() != QDialog.Accepted:
                return None
            points = (dlg.points["old"], dlg.points["new"])
        try:
            m = overlay.align_points(points[0], points[1], op, np_)
        except ValueError as e:
            QMessageBox.warning(self, "Align Manually", str(e))
            return None
        targets = [row]
        others = [k for k, y in enumerate(self.results) if k != row and
                  y["old"] is not None and y["new"] is not None]
        if others:
            if apply_all is None:
                apply_all = QMessageBox.question(
                    self, "Align Manually",
                    f"Use this line-up ({describe(m)}) for the other "
                    f"{len(others)} sheet(s) too? (Yes when the whole set "
                    "was plotted the same way.)") == QMessageBox.Yes
            if apply_all:
                targets += others
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for k in targets:
                y = self.results[k]
                o, n = old[y["old"]], new[y["new"]]
                mm = m if k == row else m[:3] + (overlay.score(o, n, m),) + \
                    m[4:]
                y["align"], y["manual"] = mm, True
                y["changes"], y["changed_pct"] = overlay.changes(o, n, mm)
        finally:
            QApplication.restoreOverrideCursor()
        self.fill()
        self._enable()
        return m

    def _go(self, row, _col):
        x = (self.results or [])[row]
        pno = x[self.sides()[2]]
        if pno is not None:
            self.view.go_to(pno)

    # ---- outputs -------------------------------------------------------------------
    def _labels(self):
        other = os.path.basename(self.path.text())
        this = os.path.basename(self.win._path or "this document")
        return (other, this) if self.is_older.isChecked() else (this, other)

    def make_overlay(self):
        old, new, _ = self.sides()
        lo, ln = self._labels()
        doc = overlay.overlay_document(old, new, self.results,
                                       f"Older: {lo}", f"Newer: {ln}",
                                       self.old_color, self.new_color)
        v = self.win.open_document(doc, f"Overlay: {lo} vs {ln}")
        return v

    def cloud(self):
        side = self.sides()[2]
        if side == "new" and self.only_new.isChecked():
            from . import prebid
            marks = prebid.uncovered_change_marks(
                self.view.doc, self.results,
                f"Changed since {self._labels()[0]} - not taken off yet")
            n = self.view.apply_marks(marks) if marks else 0
            self.win._flash(f"Clouded {n} change(s) not covered by your "
                            "takeoff or markups")
            return n
        marks = overlay.cloud_ops(self.results, side,
                                  f"Changed since {self._labels()[0]}"
                                  if side == "new" else
                                  f"Changed in {self._labels()[1]}")
        n = self.view.apply_marks(marks) if marks else 0
        self.win._flash(f"Clouded {n} change(s) (layer "
                        f"\"{overlay.CHANGE_LAYER}\")")
        return n

    def slip(self):
        old, new, side = self.sides()
        if side != "old":
            return None
        if self.win._collab_blocked("Slip sheeting"):
            return None
        label = os.path.splitext(os.path.basename(
            self.win._path or "previous"))[0]
        if QMessageBox.question(
                self, "Slip Sheet",
                "Put the newer drawings into this document? Your markups and "
                "takeoffs stay; the old drawings are kept as the hidden "
                f"layer \"Previous drawing ({label})\". You can undo "
                "this.") != QMessageBox.Yes:
            return None
        from . import revisions
        before = revisions.snapshot(self.view.doc)

        def run():
            out = overlay.slip_sheet(self.view.doc, new, self.results, label)
            # reopen so the hidden "previous drawing" layer takes effect
            self.view.replace_document(overlay.reopen(self.view.doc),
                                       keep_history=True)
            return out

        res = self.win._page_change(run, "Slip sheeted the newer revision")
        if res is None:
            return None
        flags = overlay.flag_ops(self.view.doc, self.results, "old")
        n = self.view.apply_marks(flags) if flags else 0
        clouds = overlay.cloud_ops(self.results, "old",
                                   "Changed in " + self._labels()[1])
        self.view.apply_marks(clouds) if clouds else 0
        res["flagged"] = n
        entry = self._record(before, [dict(p[2]) if isinstance(p[2], dict)
                                      else p[2] for p in flags])
        risk = f" They carry ${entry['at_risk']:,.0f} of the bid." \
            if entry and entry.get("at_risk") else ""
        QMessageBox.information(
            self, "Slip Sheet",
            f"Updated {res['replaced']} sheet(s), added {res['added']} new "
            f"sheet(s). {n} takeoff(s) sit on changed areas and are marked "
            f"\"{overlay.REVIEW_STATUS}\".{risk} Re-measure them, then see "
            "the dollar change in Review > Revision Log.")
        self.b_slip.setEnabled(False)
        return res

    def _record(self, before, flagged_refs):
        from . import revisions
        other = os.path.splitext(os.path.basename(self.path.text()))[0]
        sheets = [r["sheet"] or f"page {(r['new'] or 0) + 1}"
                  for r in self.results or []
                  if r["changes"] or r["old"] is None]
        refs = []
        for p in flagged_refs:
            ref = {k: v for k, v in p.items() if k != "status"} \
                if isinstance(p, dict) else p
            refs.append(ref)
        try:
            entry = revisions.record(self.view.doc, other or "Revision",
                                     sheets, refs, before)
        except Exception:
            import logging
            logging.getLogger(__name__).warning("revision log",
                                                exc_info=True)
            return None
        self.win._doc_edited()
        return entry

    def carry(self):
        """This document is the newer set: bring the older set's takeoff
        and markups across."""
        from . import revisions
        old, new, side = self.sides()
        if side != "new":
            return None
        if self.win._collab_blocked("Carrying takeoff"):
            return None
        marks, summary = revisions.carry_ops(old, new, self.results)
        if not marks:
            QMessageBox.information(self, "Carry Takeoff", "The older set "
                                    "has no markups or takeoffs to carry.")
            return summary
        before = revisions.snapshot(old)
        revisions.copy_job_data(old, new)
        self.view.apply_marks(marks)
        flags = revisions.flagged_refs(self.view.doc)
        entry = self._record(before, flags)
        risk = f" (${entry['at_risk']:,.0f} of the bid)" \
            if entry and entry.get("at_risk") else ""
        QMessageBox.information(
            self, "Carry Takeoff",
            f"Carried {summary['carried']} takeoff(s) onto "
            f"{summary['sheets']} sheet(s), with their scales. "
            f"{summary['flagged']} sit on changed areas and are marked "
            f"\"{overlay.REVIEW_STATUS}\"{risk}. Re-measure those; Review > "
            "Revision Log shows the dollar change.")
        self.b_carry.setEnabled(False)
        return summary

    def done(self, r):
        if self.other_doc is not None:
            self.other_doc.close()
            self.other_doc = None
        super().done(r)


# ---- picking points ------------------------------------------------------------

class _PickView(QGraphicsView):
    """A sheet you can zoom (wheel), pan (drag) and click points on."""

    def __init__(self, page, side, owner):
        super().__init__()
        self.page, self.side, self.owner = page, side, owner
        self.dpi = 96 if max(page.rect.width, page.rect.height) < 2600 \
            else 72
        pix = page.get_pixmap(dpi=self.dpi, annots=False)
        img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                     QImage.Format_RGB888).copy()
        self.scene_ = QGraphicsScene(self)
        self.scene_.addPixmap(QPixmap.fromImage(img))
        self.setScene(self.scene_)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setRenderHints(QPainter.Antialiasing |
                            QPainter.SmoothPixmapTransform)
        self.marks = []
        self._press = None
        self._snap = None

    def snap_points(self):
        """Line ends and corners on the sheet (points), for snapping."""
        if self._snap is None:
            pts = []
            try:
                for d in self.page.get_drawings():
                    for it in d.get("items", []):
                        if it[0] == "l":
                            pts += [it[1], it[2]]
                        elif it[0] == "re":
                            r = it[1]
                            pts += [r.tl, r.tr, r.bl, r.br]
                        elif it[0] == "c":
                            pts += [it[1], it[4]]
            except Exception:
                pts = []
            self._snap = pts[:200000]
        return self._snap

    def to_points(self, scene_pt):
        f = 72.0 / self.dpi
        return fitz.Point(scene_pt.x() * f, scene_pt.y() * f)

    def snap(self, pt):
        """The nearest line end/corner within 8 screen pixels, else pt."""
        lim = 8 / max(self.transform().m11(), 1e-6) * 72.0 / self.dpi
        best, bd = pt, lim
        for q in self.snap_points():
            d = abs(q.x - pt.x) + abs(q.y - pt.y)
            if d < bd:
                best, bd = fitz.Point(q), d
        return best

    def wheelEvent(self, e):
        f = 1.25 if e.angleDelta().y() > 0 else 0.8
        self.scale(f, f)

    def mousePressEvent(self, e):
        self._press = e.position().toPoint()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        if self._press is None or e.button() != Qt.LeftButton:
            return
        moved = (e.position().toPoint() - self._press).manhattanLength()
        self._press = None
        if moved <= 4:
            pt = self.to_points(self.mapToScene(e.position().toPoint()))
            if self.owner.snap.isChecked():
                pt = self.snap(pt)
            self.owner.add_point(self.side, (pt.x, pt.y))

    def draw_marks(self, pts):
        for m in self.marks:
            self.scene_.removeItem(m)
        self.marks = []
        f = self.dpi / 72.0
        pen = QPen(QColor(220, 0, 120))
        pen.setWidth(2)
        pen.setCosmetic(True)
        for n, (x, y) in enumerate(pts, 1):
            cx, cy = x * f, y * f
            r = 9
            c = self.scene_.addEllipse(cx - r, cy - r, 2 * r, 2 * r, pen)
            c.setFlag(c.GraphicsItemFlag.ItemIgnoresTransformations, False)
            h = self.scene_.addLine(cx - 2 * r, cy, cx + 2 * r, cy, pen)
            v = self.scene_.addLine(cx, cy - 2 * r, cx, cy + 2 * r, pen)
            t = self.scene_.addSimpleText(str(n))
            t.setBrush(QColor(220, 0, 120))
            t.setPos(cx + r, cy - 2.4 * r)
            self.marks += [c, h, v, t]


class PointAlignDialog(QDialog):
    """Click point 1, 2 (up to 4) on the older sheet and the same places
    on the newer one."""

    MAX = 4

    def __init__(self, old_page, new_page, sheet="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Align Manually - {sheet}" if sheet else
                            "Align Manually")
        self.resize(1400, 820)
        self.points = {"old": [], "new": []}
        self.order = []
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(
            "Click the same places on both sheets - grid line crossings or "
            "building corners far apart work best (point 1 on both, then "
            "point 2 on both; up to 4). Wheel to zoom, drag to pan."))
        row = QHBoxLayout()
        self.snap = QCheckBox("Snap to line ends and corners")
        self.snap.setChecked(True)
        row.addWidget(self.snap)
        b = QPushButton("Undo Last Point")
        b.clicked.connect(self.undo)
        row.addWidget(b)
        b = QPushButton("Clear")
        b.clicked.connect(self.clear)
        row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        split = QSplitter()
        self.views = {}
        for side, page, title in (("old", old_page, "Older revision"),
                                  ("new", new_page, "Newer revision")):
            w = QWidget()
            v = QVBoxLayout(w)
            v.setContentsMargins(0, 0, 0, 0)
            v.addWidget(QLabel(f"<b>{title}</b>"))
            view = _PickView(page, side, self)
            v.addWidget(view, 1)
            split.addWidget(w)
            self.views[side] = view
        lay.addWidget(split, 1)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.ok = bb.button(QDialogButtonBox.Ok)
        self.ok.setText("Use These Points")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.old_page, self.new_page = old_page, new_page
        self.refresh()

    def showEvent(self, e):
        super().showEvent(e)
        for v in self.views.values():
            v.fitInView(v.scene_.itemsBoundingRect(), Qt.KeepAspectRatio)

    def add_point(self, side, pt):
        pts = self.points[side]
        if len(pts) >= self.MAX:
            return
        pts.append((float(pt[0]), float(pt[1])))
        self.order.append(side)
        self.refresh()

    def undo(self):
        if self.order:
            self.points[self.order.pop()].pop()
        self.refresh()

    def clear(self):
        self.points = {"old": [], "new": []}
        self.order = []
        self.refresh()

    def result(self):
        o, n = self.points["old"], self.points["new"]
        k = min(len(o), len(n))
        if k < 2:
            return None
        return overlay.align_points(o[:k], n[:k])

    def refresh(self):
        for side, v in self.views.items():
            v.draw_marks(self.points[side])
        o, n = self.points["old"], self.points["new"]
        nxt = ("older" if len(o) <= len(n) else "newer")
        k = min(len(o), len(n))
        txt = f"{len(o)} point(s) on the older sheet, {len(n)} on the newer."
        m = None
        try:
            m = self.result()
        except ValueError as e:
            txt += f" <span style='color:#b00'>{e}</span>"
        if m:
            txt += f" Line-up: {describe(m)}."
            if k > 2:
                err = max(overlay.residuals(o[:k], n[:k], m))
                txt += f" Points agree within {err:.1f} pt."
        if k < self.MAX:
            num = (len(o) if nxt == "older" else len(n)) + 1
            txt += f" Next: point {num} on the {nxt} sheet."
        self.status.setText(txt)
        self.ok.setEnabled(m is not None)
