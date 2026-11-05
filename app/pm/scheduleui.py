"""Gantt chart page in Project Center.

Bars come from the critical path calculation (schedule.compute): red is
critical, blue has float, the dark part is % complete, a thin grey bar
under each is the baseline. Drag a bar to move its start, drag its right
end to change the duration, double-click to open the activity. Lines show
the logic (finish-to-start etc.).
"""
import datetime as _dt
import logging
import os

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFrame,
                               QHBoxLayout, QInputDialog, QLabel, QMenu,
                               QMessageBox, QPushButton, QScrollArea,
                               QToolButton, QVBoxLayout, QWidget)

from .. import icons, theme
from ..reportname import report_file_name
from . import schedule

ROW = 26
HEAD = 44
COLS = [("ID", 64), ("Activity", 230), ("Dur", 44), ("Start", 74),
        ("Finish", 74)]
LEFT = sum(w for _n, w in COLS)
SCALES = {"Days": 22.0, "Weeks": 9.0, "Months": 3.0}


class GanttChart(QWidget):
    opened = Signal(str)                 # activity id
    changed = Signal(str, dict)          # activity id, fields to save
    linked = Signal(str, str)            # predecessor id, successor id
    selected = Signal(str)               # activity id clicked

    def __init__(self, table=True):
        super().__init__()
        # table=False: bars only (the Scheduler shows its own editable
        # grid beside the chart, row for row)
        self.left = LEFT if table else 0
        self.link_from = None            # (row, cursor point) while linking
        self.cpm = {"rows": []}
        self.rows = []
        self.px = SCALES["Weeks"]
        self.start = _dt.date.today()
        self.sel = None
        self.drag = None                 # (mode, row, x0, original es/dur)
        self.ghost = None                # (row id, es date, dur)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    # ------------------------------------------------------------ data
    def set_data(self, cpm, rows):
        self.cpm = cpm
        self.rows = rows
        if rows:
            s = min(r["es"] for r in rows)
            e = max(r["ef"] for r in rows)
        else:
            s = e = _dt.date.today()
        s -= _dt.timedelta(days=s.weekday() + 7)
        self.start = s
        days = (e - s).days + 42
        self.setMinimumSize(int(self.left + days * self.px) + 20,
                            HEAD + ROW * max(1, len(rows)) + 30)
        self.resize(self.minimumSize())
        self.update()

    def x(self, d):
        return self.left + (d - self.start).days * self.px

    def date_at(self, x):
        return self.start + _dt.timedelta(days=int((x - self.left) //
                                                   self.px))

    def row_at(self, y):
        i = int((y - HEAD) // ROW)
        return self.rows[i] if 0 <= i < len(self.rows) else None

    def bar(self, i, r):
        y = HEAD + i * ROW
        es, ef = r["es"], r["ef"]
        if self.ghost and self.ghost[0] == r["_id"]:
            es, ef = self.ghost[1], self.ghost[2]
        x0 = self.x(es)
        x1 = self.x(ef) + self.px
        return QRectF(x0, y + 6, max(2.0, x1 - x0), ROW - 13)

    # ------------------------------------------------------------ paint
    def paintEvent(self, e):
        t = theme.tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(t["surface"]))
        fg, muted = QColor(t["text"]), QColor(t["muted"])
        border = QColor(t["border"])
        crit, blue = QColor("#d32f2f"), QColor(t["accent"])
        f = QFont(self.font())
        f.setPointSizeF(max(7.5, f.pointSizeF() - 0.5))
        p.setFont(f)
        clip = e.rect()
        # time scale
        d = self.start
        end = self.date_at(self.width())
        last_m = None
        while d <= end:
            xx = self.x(d)
            if xx > clip.right() + 40:
                break
            if d.weekday() >= 5 and self.px >= 8:
                p.fillRect(QRectF(xx, HEAD, self.px, self.height()),
                           QColor(t["surface2"]))
            if d.weekday() == 0:
                p.setPen(QPen(border, 1))
                p.drawLine(QPointF(xx, 22), QPointF(xx, self.height()))
                if self.px * 7 >= 30:
                    p.setPen(muted)
                    p.drawText(QPointF(xx + 3, 38), f"{d:%d}")
            if d.month != last_m:
                p.setPen(fg)
                p.drawText(QPointF(xx + 3, 16), f"{d:%b %Y}")
                last_m = d.month
            d += _dt.timedelta(days=1)
        today = _dt.date.today()
        tx = self.x(today)
        p.setPen(QPen(QColor("#f08c00"), 1.5, Qt.DashLine))
        p.drawLine(QPointF(tx, 22), QPointF(tx, self.height()))
        # rows
        index = {r["_id"]: i for i, r in enumerate(self.rows)}
        for i, r in enumerate(self.rows):
            y = HEAD + i * ROW
            if y > clip.bottom() or y + ROW < clip.top():
                continue
            if r["_id"] == self.sel:
                sel = QColor(t["accent"])
                sel.setAlpha(45)
                p.fillRect(QRectF(0, y, self.width(), ROW), sel)
            elif i % 2 and self.left:
                p.fillRect(QRectF(0, y, self.left, ROW),
                           QColor(t["surface2"]))
            c = crit if r["critical"] else blue
            bs = schedule._d(r.get("baseline_start"))
            bf = schedule._d(r.get("baseline_finish"))
            if bs and bf:
                p.fillRect(QRectF(self.x(bs), y + ROW - 6,
                                  self.x(bf) + self.px - self.x(bs), 3),
                           QColor("#9e9e9e"))
            b = self.bar(i, r)
            if r.get("summary"):
                # a summary: a dark bar with pointed ends over its work
                sc = QColor(t["text"])
                p.setPen(Qt.NoPen)
                p.setBrush(sc)
                top = b.top() + 2
                p.drawRect(QRectF(b.left(), top, b.width(), 5))
                for xx in (b.left(), b.right()):
                    tri = QPainterPath()
                    tri.moveTo(xx - 4, top)
                    tri.lineTo(xx + 4, top)
                    tri.lineTo(xx, top + 10)
                    tri.closeSubpath()
                    p.drawPath(tri)
                p.setBrush(Qt.NoBrush)
                continue
            if r["milestone"]:
                cx, cy = b.left(), b.center().y()
                path = QPainterPath()
                path.moveTo(cx, cy - 7)
                path.lineTo(cx + 7, cy)
                path.lineTo(cx, cy + 7)
                path.lineTo(cx - 7, cy)
                path.closeSubpath()
                p.setPen(QPen(fg, 1))
                p.setBrush(c)
                p.drawPath(path)
                p.setPen(muted)
                p.drawText(QPointF(cx + 10, cy + 4), f"{r['es']:%b %d}")
            else:
                p.setPen(QPen(c, 1))
                fill = QColor(c)
                fill.setAlpha(95)
                p.setBrush(fill)
                p.drawRoundedRect(b, 3, 3)
                pc = max(0.0, min(100.0, schedule._num(r.get("percent"))))
                if pc:
                    p.setBrush(c)
                    p.drawRoundedRect(QRectF(b.left(), b.top(),
                                             b.width() * pc / 100,
                                             b.height()), 3, 3)
                if r.get("responsible"):
                    p.setPen(muted)
                    p.drawText(QPointF(b.right() + 6, b.bottom() - 2),
                               str(r["responsible"])[:30])
            # logic lines
            p.setPen(QPen(muted, 1))
            p.setBrush(Qt.NoBrush)
            for pid, typ, _lag in r.get("links", []):
                j = index.get(pid)
                if j is None:
                    continue
                pb = self.bar(j, self.rows[j])
                sx = pb.right() if typ in ("FS", "FF") else pb.left()
                ex = b.left() if typ in ("FS", "SS") else b.right()
                sy, ey = pb.center().y(), b.center().y()
                path = QPainterPath(QPointF(sx, sy))
                mx = sx + 6 if typ in ("FS", "FF") else sx - 6
                path.lineTo(mx, sy)
                path.lineTo(mx, ey)
                path.lineTo(ex, ey)
                p.drawPath(path)
                dirn = 1 if typ in ("FS", "SS") else -1
                p.drawLine(QPointF(ex, ey), QPointF(ex - 4 * dirn, ey - 3))
                p.drawLine(QPointF(ex, ey), QPointF(ex - 4 * dirn, ey + 3))
        if self.link_from is not None:
            fr, pt = self.link_from
            j = index.get(fr["_id"])
            if j is not None:
                fb = self.bar(j, fr)
                p.setPen(QPen(QColor(t["accent"]), 1.5, Qt.DashLine))
                p.drawLine(QPointF(fb.right(), fb.center().y()), pt)
        if not self.left:
            p.setPen(QPen(border, 1))
            p.drawLine(QPointF(0, HEAD - 1), QPointF(self.width(), HEAD - 1))
            if not self.rows:
                p.setPen(muted)
                p.drawText(QRectF(20, HEAD + 10, 520, 60), Qt.TextWordWrap,
                           "Type the first activity in the grid on the left "
                           "(Enter adds the next one).")
            return
        # the table on the left, drawn over the bars when scrolled
        p.fillRect(QRectF(0, 0, LEFT, HEAD), QColor(t["surface"]))
        p.setPen(QPen(border, 1))
        p.drawLine(QPointF(0, HEAD - 1), QPointF(self.width(), HEAD - 1))
        p.drawLine(QPointF(LEFT, 0), QPointF(LEFT, self.height()))
        bold = QFont(f)
        bold.setBold(True)
        p.setFont(bold)
        p.setPen(muted)
        cx = 0
        for name, w in COLS:
            p.drawText(QRectF(cx + 6, 22, w - 8, 20), Qt.AlignVCenter, name)
            cx += w
        p.setFont(f)
        for i, r in enumerate(self.rows):
            y = HEAD + i * ROW
            if y > clip.bottom() or y + ROW < clip.top():
                continue
            vals = [str(r.get("_no") or ""), str(r.get("name") or ""),
                    f"{r['dur']}d", f"{r['es']:%m/%d/%y}",
                    f"{r['ef']:%m/%d/%y}"]
            cx = 0
            for (name, w), val in zip(COLS, vals):
                p.setPen(crit if r["critical"] and name == "Activity"
                         else fg)
                p.drawText(QRectF(cx + 6, y, w - 10, ROW),
                           Qt.AlignVCenter | Qt.AlignLeft,
                           p.fontMetrics().elidedText(val, Qt.ElideRight,
                                                      w - 10))
                cx += w
        if not self.rows:
            p.setPen(muted)
            p.drawText(QRectF(LEFT + 20, HEAD + 10, 600, 60),
                       Qt.TextWordWrap,
                       "No activities yet. Add one with + Activity, or "
                       "import a schedule from Microsoft Project (XML) or "
                       "Primavera P6 (XER).")

    # ------------------------------------------------------------ mouse
    def _hit(self, pos):
        r = self.row_at(pos.y())
        if r is None or pos.x() < self.left:
            return r, None
        if r.get("summary"):
            return r, None
        i = self.rows.index(r)
        b = self.bar(i, r)
        if r["milestone"]:
            b = QRectF(b.left() - 8, b.top() - 4, 16, b.height() + 8)
        if abs(pos.x() - b.right()) <= 5 and not r["milestone"]:
            return r, "end"
        if b.adjusted(-2, -2, 2, 2).contains(pos):
            return r, "move"
        return r, None

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self.link_from is not None:
            self.link_from = (self.link_from[0], pos)
            self.update()
            return
        if self.drag:
            mode, r, x0, es0, dur0 = self.drag
            days = int(round((pos.x() - x0) / self.px))
            cal = self.cpm["cal"]
            if mode == "move":
                es = es0 + _dt.timedelta(days=days)
                while not cal.is_work(es):
                    es += _dt.timedelta(days=1 if days >= 0 else -1)
                n = dur0
            else:
                es = es0
                end = r["ef"] + _dt.timedelta(days=days)
                n = max(1, cal.index(end) - cal.index(es) + 1)
            ef = cal.date(cal.index(es) + max(0, n - 1))
            self.ghost = (r["_id"], es, ef)
            self._ghost_dur = n
            self.update()
            return
        _r, part = self._hit(pos)
        self.setCursor(Qt.SizeHorCursor if part == "end" else
                       Qt.OpenHandCursor if part == "move" else
                       Qt.ArrowCursor)

    def mousePressEvent(self, e):
        r, part = self._hit(e.position())
        self.sel = r["_id"] if r else None
        if r:
            self.selected.emit(r["_id"])
        self.update()
        if e.button() == Qt.LeftButton and r and part and \
                e.modifiers() & Qt.ShiftModifier:
            # Shift + drag from one bar to another links them (FS)
            self.link_from = (r, e.position())
            return
        if e.button() == Qt.LeftButton and r and part and \
                r.get("status") != "Complete":
            self.drag = (part, r, e.position().x(), r["es"], r["dur"])

    def mouseReleaseEvent(self, e):
        if self.link_from is not None:
            fr = self.link_from[0]
            self.link_from = None
            to, part = self._hit(e.position())
            if to is not None and part and to["_id"] != fr["_id"]:
                self.linked.emit(fr["_id"], to["_id"])
            self.update()
            return
        if not self.drag:
            return
        mode, r, _x0, es0, dur0 = self.drag
        self.drag = None
        g, self.ghost = self.ghost, None
        if not g:
            return
        n = getattr(self, "_ghost_dur", dur0)
        if mode == "move" and g[1] != es0:
            self.changed.emit(r["_id"], {"start": g[1].isoformat()})
        elif mode == "end" and n != dur0:
            self.changed.emit(r["_id"], {"duration": n})
        self.update()

    def mouseDoubleClickEvent(self, e):
        r = self.row_at(e.position().y())
        if r:
            self.opened.emit(r["_id"])


class GanttPage(QWidget):
    def __init__(self, center):
        super().__init__()
        self.center = center
        self.store = center.store
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        head = QFrame()
        head.setObjectName("pcPageHead")
        h = QHBoxLayout(head)
        h.setContentsMargins(18, 14, 18, 12)
        ic = QLabel()
        ic.setPixmap(icons.icon("gantt").pixmap(22, 22))
        h.addWidget(ic)
        t = QLabel("Schedule")
        t.setObjectName("pcH1")
        h.addWidget(t)
        self.summary = QLabel()
        self.summary.setObjectName("muted")
        h.addWidget(self.summary)
        h.addStretch()
        add = QPushButton("+ Activity")
        add.clicked.connect(self.add)
        h.addWidget(add)
        ed = QPushButton("Edit in Scheduler…")
        ed.setObjectName("primary")
        ed.setToolTip("Build the schedule in a grid beside the Gantt chart: "
                      "type activities, durations and links, indent into "
                      "summaries")
        ed.clicked.connect(self.edit_in_scheduler)
        h.addWidget(ed)
        self.scale = QComboBox()
        self.scale.addItems(list(SCALES))
        self.scale.setCurrentText("Weeks")
        self.scale.currentTextChanged.connect(self.refresh)
        h.addWidget(self.scale)
        self.crit = QCheckBox("Critical only")
        self.crit.toggled.connect(self.refresh)
        h.addWidget(self.crit)
        la = QPushButton("Look-Ahead…")
        la.setIcon(icons.icon("print"))
        la.setToolTip("The activities working in the next 2 weeks (or 1-4), "
                      "day by day, with a Notes column - for the weekly "
                      "superintendent meeting. PDF or Excel")
        la.clicked.connect(lambda: self.look_ahead())
        h.addWidget(la)
        self.la_button = la
        more = QToolButton()
        more.setText("More")
        more.setPopupMode(QToolButton.InstantPopup)
        m = QMenu(more)
        m.addAction("Save Gantt Chart as PDF…", self.pdf)
        m.addAction("3-Week Gantt Lookahead (PDF)…",
                    lambda: self.pdf(lookahead=True))
        m.addSeparator()
        m.addAction("Recovery Schedule…", self.recovery)
        m.addSeparator()
        m.addAction("Save Schedule Update…", lambda: self.save_update())
        m.addAction("Schedule Quality Check (PDF)…",
                    lambda: self.quality_check())
        m.addAction("Claim Package (PDF)…", lambda: self.claim_package())
        m.addSeparator()
        m.addAction("Import from Microsoft Project (XML)…",
                    lambda: self.import_file("xml"))
        m.addAction("Import from Primavera P6 (XER)…",
                    lambda: self.import_file("xer"))
        m.addAction("Export to Microsoft Project (XML)…", self.export)
        m.addSeparator()
        m.addAction("Set Baseline (save today's dates)", self.baseline)
        m.addAction("Holidays…", self.holidays)
        more.setMenu(m)
        h.addWidget(more)
        v.addWidget(head)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setObjectName("muted")
        self.note.setContentsMargins(18, 6, 18, 6)
        self.note.setVisible(False)
        v.addWidget(self.note)
        self.chart = GanttChart()
        self.chart.opened.connect(
            lambda rid: self.center.open_record("activity", rid))
        self.chart.changed.connect(self._changed)
        sc = QScrollArea()
        sc.setFrameShape(QFrame.NoFrame)
        sc.setWidget(self.chart)
        sc.setWidgetResizable(False)
        self.scroll = sc
        v.addWidget(sc, 1)

    def refresh(self, *_):
        self.chart.px = SCALES.get(self.scale.currentText(), 9.0)
        cpm = schedule.cached(self.store)
        rows = [r for r in cpm["rows"] if r["critical"]] \
            if self.crit.isChecked() else cpm["rows"]
        self.chart.set_data(cpm, rows)
        if cpm["rows"]:
            late = [r for r in cpm["rows"]
                    if (schedule.variance(r, cpm.get("cal")) or 0) > 0]
            txt = (f"  ·  {len(cpm['rows'])} activities  ·  finish "
                   f"{cpm['finish']:%b %d, %Y}  ·  {len(cpm['critical'])} "
                   "critical")
            if late:
                txt += f"  ·  {len(late)} behind baseline"
            self.summary.setText(txt)
        else:
            self.summary.setText("")
        self.note.setVisible(bool(cpm["problems"]))
        self.note.setText("  ".join(cpm["problems"][:4]))

    def _changed(self, rid, fields):
        a = self.store.get("activity", rid)
        if not a:
            return
        a.update(fields)
        self.store.save_record("activity", a)
        self.refresh()
        self.center.toast("Schedule updated")

    def add(self):
        p = self.center.show_tool("activity")
        p.new()

    def edit_in_scheduler(self):
        from .scheduler import open_scheduler
        return open_scheduler(self.store, getattr(self.center, "main", None))

    def _save_path(self, title, name, filt):
        path, _ = QFileDialog.getSaveFileName(self, title, name, filt)
        return path

    def recovery(self):
        """The recovery schedule for a job that's behind (recovery_ui)."""
        from .recovery_ui import RecoveryDialog
        d = RecoveryDialog(self.store, self, self.center)
        d.finished.connect(lambda *_: self.refresh())
        d.show()
        self._recovery = d
        return d

    def look_ahead(self, weeks=None, path=None):
        """The meeting look-ahead (activity_lookahead) as PDF or Excel."""
        from . import activity_lookahead, report
        if weeks is None:
            w, ok = QInputDialog.getItem(
                self, "Look-Ahead", "Weeks ahead:",
                ["1 week", "2 weeks", "3 weeks", "4 weeks"], 1, False)
            if not ok:
                return None
            weeks = int(w.split()[0])
        if path is None:
            name = report_file_name(f"{weeks}-Week Look-Ahead",
                                    self.store.name)
            path = self._save_path(
                "Save Look-Ahead",
                os.path.join(self.store.folder, name),
                "PDF (*.pdf);;Excel (*.xlsx)")
        if not path:
            return None
        activity_lookahead.export(self.store, path, weeks)
        main = getattr(self.center, "main", None)
        if main is not None and path.lower().endswith(".pdf") and \
                not os.environ.get("QUANTISHEET_NO_OPEN"):
            main.open_path(path)
        self.center.toast(f"Saved {os.path.basename(path)}")
        return path

    def pdf(self, lookahead=False, path=None):
        name = report_file_name("Lookahead" if lookahead else "Schedule",
                                self.store.name)
        path = path or self._save_path("Save PDF", name, "PDF (*.pdf)")
        if not path:
            return None
        if lookahead:
            schedule.lookahead_pdf(self.store, path)
        else:
            schedule.gantt_pdf(self.store, path, title="Project Schedule")
        main = getattr(self.center, "main", None)
        if main is not None and not os.environ.get("QUANTISHEET_NO_OPEN"):
            main.open_path(path)
        self.center.toast(f"Saved {os.path.basename(path)}")
        return path

    def import_file(self, kind, path=None):
        if path is None:
            filt = "Microsoft Project XML (*.xml)" if kind == "xml" else \
                "Primavera P6 (*.xer)"
            path, _ = QFileDialog.getOpenFileName(self, "Import Schedule",
                                                  "", filt)
        if not path:
            return 0
        try:
            n = (schedule.import_msproject if kind == "xml" else
                 schedule.import_xer)(self.store, path)
        except Exception as ex:
            QMessageBox.warning(self, "Import Schedule",
                                f"Couldn't read that file: {ex}")
            return 0
        self.refresh()
        self.center.toast(f"Imported {n} activities")
        return n

    def export(self, path=None):
        path = path or self._save_path("Export Schedule",
                                       f"{self.store.name}.xml",
                                       "Microsoft Project XML (*.xml)")
        if not path:
            return None
        schedule.export_msproject(self.store, path)
        self.center.toast(f"Exported {os.path.basename(path)}")
        return path

    def save_update(self, note=None):
        """Save a dated, fingerprinted copy of the schedule as it stands
        (the update record a claim relies on)."""
        from . import schedule_record
        if note is None:
            note, ok = QInputDialog.getText(
                self, "Save Schedule Update",
                "Note for this update (e.g. \"October update\"):")
            if not ok:
                return None
        e = schedule_record.snapshot(self.store, "update", note or "")
        self.center.toast(f"Schedule update {e['n']} saved")
        return e

    def quality_check(self, path=None):
        from . import report, schedule_check
        if path is None:
            name = report_file_name("Schedule Quality Check",
                                    self.store.name)
            path = self._save_path("Schedule Quality Check",
                                   os.path.join(self.store.folder, name),
                                   "PDF (*.pdf)")
        if not path:
            return None
        schedule_check.export_pdf(self.store, path)
        self._open(path)
        return path

    def claim_package(self, path=None):
        from . import claim_package, report
        if path is None:
            name = report_file_name("Schedule Claim Package",
                                    self.store.name)
            path = self._save_path("Claim Package",
                                   os.path.join(self.store.folder, name),
                                   "PDF (*.pdf)")
        if not path:
            return None
        claim_package.export_pdf(self.store, path)
        self._open(path)
        return path

    def _open(self, path):
        main = getattr(self.center, "main", None)
        if main is not None and not os.environ.get("QUANTISHEET_NO_OPEN"):
            main.open_path(path)
        self.center.toast(f"Saved {os.path.basename(path)}")

    def baseline(self):
        try:
            n = schedule.set_baseline(self.store)
        except schedule.BaselineLocked as ex:       # Master Schedule lock
            self.last_baseline_message = str(ex)
            self.center.toast(self.last_baseline_message)
            return 0
        try:                       # the baseline is part of the record
            from . import schedule_record
            schedule_record.snapshot(self.store, "baseline",
                                     f"Baseline set for {n} activities")
        except Exception as ex:                     # noqa: BLE001
            # the baseline itself is saved; say the record wasn't updated
            # (review 0.12.38 #10 - this used to be swallowed)
            logging.getLogger(__name__).exception(
                "Set Baseline: schedule record snapshot failed")
            self.last_baseline_message = (
                "Baseline saved, but the schedule record could not be "
                f"updated: {ex}")
            self.refresh()
            self.center.toast(self.last_baseline_message)
            return n
        self.last_baseline_message = f"Baseline set for {n} activities"
        self.refresh()
        self.center.toast(self.last_baseline_message)
        return n

    def holidays(self):
        from PySide6.QtWidgets import QInputDialog
        cur = ", ".join(self.store.setting("holidays") or [])
        text, ok = QInputDialog.getMultiLineText(
            self, "Holidays", "Non-work days (YYYY-MM-DD), separated by "
            "commas or lines:", cur)
        if not ok:
            return
        import re
        days = sorted(set(re.findall(r"\d{4}-\d{2}-\d{2}", text)))
        self.store.set_setting("holidays", days)
        self.refresh()
