"""Estimating Dashboard window (Estimate > Estimating Dashboard…, also on
the Reports tab): cost per SF by building type and CSI division, hit rate,
margin and subcontractor prices across every job the company has, with
filters, the jobs behind any number, and Excel / PDF exports. The
numbers come from dashboard.py; the charts are drawn here with QPainter.

With nothing to compare it opens empty with a hint - no message box."""
import datetime as _dt
import logging
import os

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox,
                               QDialog, QFileDialog, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QSplitter, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout,
                               QWidget)

from . import dashboard as db
from . import theme
from .dmoney import c2 as _c2

log = logging.getLogger(__name__)
ALL = "All"
FLAG_BG = "#ffe0b2"


def _m(v):
    return db._m(v)


def _p(v):
    return db._p(v)


def _d(v):
    return v.isoformat() if isinstance(v, _dt.date) else (v or "")


def _num_like(t):
    t = str(t)
    return bool(t) and (t[0] in "$-0123456789" or t.endswith("%"))


# ============================================================ charts
class BarChart(QWidget):
    """Horizontal bars (value) with an optional low-high range line; a
    click picks a bar."""
    picked = Signal(int)

    def __init__(self, unit="money"):
        super().__init__()
        self.unit = unit
        self.rows = []          # [(label, value, low, high, flagged)]
        self.empty = ""
        self.setMinimumHeight(160)
        self.setMouseTracking(True)

    def set_rows(self, rows, empty=""):
        self.rows = [r for r in rows if r[1] is not None]
        self.empty = empty
        self.setMinimumHeight(max(160, 30 + 22 * len(self.rows[:24])))
        self.update()

    def _text(self, v):
        return _m(v) if self.unit == "money" else _p(v)

    def _bar_at(self, y):
        i = int((y - 12) // 22)
        return i if 0 <= i < len(self.rows[:24]) else -1

    def mousePressEvent(self, e):
        i = self._bar_at(e.position().y())
        if i >= 0:
            self.picked.emit(i)

    def paintEvent(self, _e):
        t = theme.tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(t["surface"]))
        if not self.rows:
            p.setPen(QColor(t["muted"]))
            p.drawText(QRectF(10, 10, self.width() - 20, self.height() - 20),
                       Qt.AlignCenter | Qt.TextWordWrap,
                       self.empty or "Nothing to chart.")
            return
        rows = self.rows[:24]
        top = max(float(max(r[1], r[3] if r[3] is not None else r[1]))
                  for r in rows) or 1.0
        L = min(220, max(90, self.width() // 4))
        R = self.width() - 190
        span = max(10, R - L)
        for i, (label, v, lo, hi, flagged) in enumerate(rows):
            y = 12 + i * 22
            p.setPen(QColor(t["text"]))
            p.drawText(QRectF(4, y, L - 10, 20),
                       Qt.AlignRight | Qt.AlignVCenter,
                       p.fontMetrics().elidedText(str(label), Qt.ElideRight,
                                                  L - 12))
            w = span * float(v) / top
            col = QColor(t["warn"] if flagged else t["accent"])
            p.fillRect(QRectF(L, y + 4, max(w, 1.0), 12), col)
            if lo is not None and hi is not None:
                p.setPen(QPen(QColor(t["text"]), 1.4))
                x0, x1 = L + span * float(lo) / top, L + span * float(hi) / top
                p.drawLine(QPointF(x0, y + 10), QPointF(x1, y + 10))
                p.drawLine(QPointF(x0, y + 6), QPointF(x0, y + 14))
                p.drawLine(QPointF(x1, y + 6), QPointF(x1, y + 14))
            p.setPen(QColor(t["muted"]))
            txt = self._text(v)
            if lo is not None and hi is not None and lo != hi:
                txt += f"  ({self._text(lo)} – {self._text(hi)})"
            p.drawText(QRectF(R + 8, y, 190, 20), Qt.AlignLeft |
                       Qt.AlignVCenter, txt)


class PointChart(QWidget):
    """Values over bid date: points (flagged ones in the warning color)
    joined in date order, with a dashed reference line (the median, or 0
    for '% vs median')."""

    def __init__(self, unit="money"):
        super().__init__()
        self.unit = unit
        self.points = []        # [(date, value, flagged, label)]
        self.ref = None
        self.title = ""
        self.setMinimumHeight(170)

    def set_points(self, points, ref=None, title=""):
        self.points = sorted([x for x in points if x[0] is not None and
                              x[1] is not None], key=lambda x: x[0])
        self.ref, self.title = ref, title
        self.update()

    def _text(self, v):
        return _m(v) if self.unit == "money" else _p(v)

    def paintEvent(self, _e):
        t = theme.tokens()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(t["surface"]))
        p.setPen(QColor(t["text"]))
        p.drawText(QRectF(8, 2, self.width() - 16, 18), Qt.AlignLeft,
                   self.title)
        pts = self.points
        if not pts:
            p.setPen(QColor(t["muted"]))
            p.drawText(QRectF(10, 20, self.width() - 20, self.height() - 30),
                       Qt.AlignCenter | Qt.TextWordWrap,
                       "Pick a row with dated values to see them over time.")
            return
        L, T, R, B = 86, 26, self.width() - 16, self.height() - 26
        vals = [float(v) for _d_, v, _f, _l in pts]
        if self.ref is not None:
            vals.append(float(self.ref))
        lo, hi = min(vals), max(vals)
        if hi == lo:
            lo, hi = lo - 1, hi + 1
        pad = (hi - lo) * 0.08
        lo, hi = lo - pad, hi + pad
        d0 = pts[0][0].toordinal()
        d1 = max(pts[-1][0].toordinal(), d0 + 1)

        def X(d):
            return L + (R - L) * (d.toordinal() - d0) / (d1 - d0) \
                if len(pts) > 1 else (L + R) / 2

        def Y(v):
            return B - (B - T) * (float(v) - lo) / (hi - lo)
        p.setPen(QPen(QColor(t["border"]), 1))
        for k in range(5):
            v = lo + (hi - lo) * k / 4
            p.drawLine(QPointF(L, Y(v)), QPointF(R, Y(v)))
            p.setPen(QColor(t["muted"]))
            p.drawText(QRectF(0, Y(v) - 8, L - 6, 16),
                       Qt.AlignRight | Qt.AlignVCenter,
                       self._text(db.cents(v)) if self.unit == "money"
                       else f"{v:,.1f}%")
            p.setPen(QPen(QColor(t["border"]), 1))
        p.setPen(QColor(t["muted"]))
        p.drawText(QRectF(L - 40, B + 4, 80, 16), Qt.AlignCenter,
                   pts[0][0].strftime("%Y-%m"))
        if len(pts) > 1:
            p.drawText(QRectF(R - 60, B + 4, 80, 16), Qt.AlignCenter,
                       pts[-1][0].strftime("%Y-%m"))
        if self.ref is not None:
            p.setPen(QPen(QColor(t["muted"]), 1.2, Qt.DashLine))
            p.drawLine(QPointF(L, Y(self.ref)), QPointF(R, Y(self.ref)))
        p.setPen(QPen(QColor(t["accent"]), 1.6))
        prev = None
        for d, v, _f, _l in pts:
            pt = QPointF(X(d), Y(v))
            if prev is not None:
                p.drawLine(prev, pt)
            prev = pt
        for d, v, flagged, _l in pts:
            col = QColor(t["danger"] if flagged else t["accent"])
            p.setPen(QPen(col, 1))
            p.setBrush(col)
            p.drawEllipse(QPointF(X(d), Y(v)), 4.5, 4.5)
        p.setBrush(Qt.NoBrush)


# ============================================================ window
class EstimatingDashboard(QDialog):
    def __init__(self, win=None, folders=None, autoload=True):
        super().__init__(win)
        self.win = win
        self.folders = folders
        self.data = None
        self.report = None
        self.payload = {}               # table -> [row payload]
        self.setWindowTitle("Estimating Dashboard")
        self.resize(1280, 820)
        v = QVBoxLayout(self)
        intro = QLabel("Every estimate and bid side by side: cost per SF, "
                       "hit rate, margin and sub prices. Click a row to see "
                       "the jobs behind its numbers.")
        intro.setWordWrap(True)
        intro.setObjectName("muted")
        v.addWidget(intro)
        # ---- filters
        f = QHBoxLayout()
        self.date_from = QLineEdit()
        self.date_from.setPlaceholderText("from yyyy-mm-dd")
        self.date_to = QLineEdit()
        self.date_to.setPlaceholderText("to yyyy-mm-dd")
        for e in (self.date_from, self.date_to):
            e.setMaximumWidth(120)
            e.editingFinished.connect(self.refresh_view)
        self.type_box, self.state_box, self.est_box = (QComboBox(),
                                                       QComboBox(),
                                                       QComboBox())
        for label, w in (("Bid date", self.date_from), ("–", self.date_to),
                         ("Building type", self.type_box),
                         ("State", self.state_box),
                         ("Estimator", self.est_box)):
            f.addWidget(QLabel(label))
            f.addWidget(w)
        for b in (self.type_box, self.state_box, self.est_box):
            b.setMinimumWidth(120)
            b.addItem(ALL)
            b.currentIndexChanged.connect(lambda _i: self.refresh_view())
        clear = QPushButton("Clear Filters")
        clear.clicked.connect(self.clear_filters)
        f.addWidget(clear)
        f.addStretch()
        v.addLayout(f)
        row = QHBoxLayout()
        for label, fn in (("Reload", self.reload),
                          ("Add Project Folders…", self.add_folders),
                          ("Export to Excel…", self.export_excel),
                          ("Export to PDF…", self.export_pdf)):
            b = QPushButton(label)
            b.clicked.connect(lambda _c=False, fn=fn: fn())
            row.addWidget(b)
        self.skipped_btn = QPushButton("")
        self.skipped_btn.setFlat(True)
        self.skipped_btn.clicked.connect(self.show_skipped)
        self.skipped_btn.hide()
        row.addWidget(self.skipped_btn)
        row.addStretch()
        v.addLayout(row)
        self.status = QLabel()
        self.status.setObjectName("muted")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        self.hint = QLabel(db.EMPTY_HINT)
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("padding:10px; border:1px dashed "
                                f"{theme.tokens()['border2']};")
        v.addWidget(self.hint)
        # ---- tabs + drill-down
        split = QSplitter(Qt.Vertical)
        self.tabs = QTabWidget()
        split.addWidget(self.tabs)
        bottom = QWidget()
        bv = QVBoxLayout(bottom)
        bv.setContentsMargins(0, 4, 0, 0)
        self.drill_label = QLabel("Jobs behind the selected row")
        self.drill_label.setStyleSheet("font-weight:600")
        bv.addWidget(self.drill_label)
        self.drill = self._table()
        self.drill.itemDoubleClicked.connect(self._open_job)
        bv.addWidget(self.drill)
        split.addWidget(bottom)
        split.setSizes([520, 240])
        v.addWidget(split, 1)
        self._build_sf_tab()
        self._build_hit_tab()
        self._build_margin_tab()
        self._build_subs_tab()
        self._build_jobs_tab()
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        h = QHBoxLayout()
        h.addStretch()
        h.addWidget(close)
        v.addLayout(h)
        if autoload:
            self.reload()
        else:
            self.refresh_view()

    # ---------------------------------------------------------- helpers
    def _table(self):
        t = QTableWidget(0, 0)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectRows)
        t.setSelectionMode(QAbstractItemView.SingleSelection)
        t.verticalHeader().setVisible(False)
        t.setAlternatingRowColors(True)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        t.horizontalHeader().setStretchLastSection(True)
        return t

    def _fill(self, table, heads, rows, payload, flags=None):
        """rows: [[text]]; payload: one object per row (what a click
        drills into); flags: {(row, col)} cells to highlight."""
        table.blockSignals(True)
        table.clearContents()
        table.setColumnCount(len(heads))
        table.setHorizontalHeaderLabels(heads)
        table.setRowCount(len(rows))
        for r, cells in enumerate(rows):
            for c, val in enumerate(cells):
                it = QTableWidgetItem("" if val is None else str(val))
                if c and _num_like(it.text()):
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if flags and (r, c) in flags:
                    theme.tint(it, FLAG_BG)
                table.setItem(r, c, it)
        self.payload[id(table)] = list(payload)
        table.resizeColumnsToContents()
        for c in range(table.columnCount()):
            if table.columnWidth(c) > 320:
                table.setColumnWidth(c, 320)
        table.blockSignals(False)

    def _picked(self, table):
        rows = table.selectionModel().selectedRows() if \
            table.selectionModel() else []
        if not rows:
            return None
        items = self.payload.get(id(table), [])
        i = rows[0].row()
        return items[i] if 0 <= i < len(items) else None

    def _combo(self, items, fn):
        c = QComboBox()
        for label, data in items:
            c.addItem(label, data)
        c.currentIndexChanged.connect(lambda _i: fn())
        return c

    # ---------------------------------------------------------- tabs
    def _build_sf_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        h = QHBoxLayout()
        h.addWidget(QLabel("Group by"))
        self.sf_by = self._combo([("Building type", "type"),
                                  ("CSI division", "division")],
                                 self._fill_sf)
        h.addWidget(self.sf_by)
        h.addWidget(QLabel("Cost / building SF. Orange: outside the "
                           "outlier fences (Q1 − 1.5 IQR, Q3 + 1.5 IQR) of "
                           f"a group of {db.MIN_OUTLIER_N} or more."))
        h.addStretch()
        v.addLayout(h)
        split = QSplitter(Qt.Horizontal)
        self.sf_table = self._table()
        self.sf_table.itemSelectionChanged.connect(self._sf_selected)
        split.addWidget(self.sf_table)
        charts = QWidget()
        cv = QVBoxLayout(charts)
        cv.setContentsMargins(0, 0, 0, 0)
        self.sf_bars = BarChart("money")
        self.sf_bars.picked.connect(lambda i: self.sf_table.selectRow(i))
        self.sf_trend = PointChart("money")
        cv.addWidget(self.sf_bars, 1)
        cv.addWidget(self.sf_trend, 1)
        split.addWidget(charts)
        split.setSizes([640, 520])
        v.addWidget(split, 1)
        self.tabs.addTab(w, "Cost per SF")

    def _build_hit_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        h = QHBoxLayout()
        h.addWidget(QLabel("Group by"))
        self.hit_by = self._combo([(db.BY_LABEL[k], k) for k in db.HIT_BY],
                                  self._fill_hit)
        h.addWidget(self.hit_by)
        h.addWidget(QLabel("Hit rate = won ÷ (won + lost). Pending and "
                           "no-bid jobs are shown, not counted."))
        h.addStretch()
        v.addLayout(h)
        split = QSplitter(Qt.Horizontal)
        self.hit_table = self._table()
        self.hit_table.itemSelectionChanged.connect(
            lambda: self._drill_rows(self._picked(self.hit_table)))
        split.addWidget(self.hit_table)
        self.hit_bars = BarChart("pct")
        self.hit_bars.picked.connect(lambda i: self.hit_table.selectRow(i))
        split.addWidget(self.hit_bars)
        split.setSizes([700, 460])
        v.addWidget(split, 1)
        self.tabs.addTab(w, "Hit Rate")

    def _build_margin_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel("Our bid against the estimate cost (jobs with "
                           "both), and actual cost against the estimate "
                           "where Job Cost Feedback has actuals."))
        self.margin_table = self._table()
        self.margin_table.itemSelectionChanged.connect(
            lambda: self._drill_rows(self._picked(self.margin_table)))
        v.addWidget(self.margin_table, 1)
        self.tabs.addTab(w, "Margin")

    def _build_subs_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        h = QHBoxLayout()
        h.addWidget(QLabel("Trade"))
        self.trade_box = QComboBox()
        self.trade_box.setMinimumWidth(280)
        self.trade_box.currentIndexChanged.connect(lambda _i:
                                                   self._fill_subs())
        h.addWidget(self.trade_box)
        h.addWidget(QLabel("% vs median: each bid against the median of "
                           "all bids for that trade on that job."))
        h.addStretch()
        v.addLayout(h)
        split = QSplitter(Qt.Horizontal)
        self.sub_table = self._table()
        self.sub_table.itemSelectionChanged.connect(self._sub_selected)
        split.addWidget(self.sub_table)
        self.sub_chart = PointChart("pct")
        split.addWidget(self.sub_chart)
        split.setSizes([760, 400])
        v.addWidget(split, 1)
        self.tabs.addTab(w, "Subcontractors")

    def _build_jobs_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        h = QHBoxLayout()
        h.addWidget(QLabel("Bid result of the selected job"))
        self.result_box = QComboBox()
        self.result_box.addItems(list(db.RESULTS))
        h.addWidget(self.result_box)
        self.result_btn = QPushButton("Set Result")
        self.result_btn.clicked.connect(lambda _c=False: self.set_result())
        h.addWidget(self.result_btn)
        low = QPushButton("Low Bid…")
        low.setToolTip("The low bidder's number for the selected job - for "
                       "the gap and the bid results")
        low.clicked.connect(lambda _c=False: self.set_low_bid())
        h.addWidget(low)
        res = QPushButton("Bid Results (CSV)…")
        res.clicked.connect(lambda _c=False: self.export_bid_results())
        h.addWidget(res)
        h.addWidget(QLabel("(saved in the project's settings and its Job "
                           "Cost Feedback job)"))
        h.addStretch()
        v.addLayout(h)
        self.jobs_table = self._table()
        self.jobs_table.itemSelectionChanged.connect(self._job_selected)
        v.addWidget(self.jobs_table, 1)
        self.tabs.addTab(w, "Jobs")

    # ---------------------------------------------------------- data
    def reload(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.data = db.load(self.folders)
        except Exception as e:                            # noqa: BLE001
            log.exception("dashboard load failed")
            self.data = {"jobs": [], "tab_jobs": [], "bids": [],
                         "index": {}, "skipped": [], "warnings": [
                             f"Couldn't read the jobs: {e}"],
                         "projects_read": 0, "loaded": ""}
        finally:
            QApplication.restoreOverrideCursor()
        self._fill_options()
        self.refresh_view()

    def _fill_options(self):
        opts = db.filter_options(self.data)
        for box, key in ((self.type_box, "type"), (self.state_box, "state"),
                         (self.est_box, "estimator")):
            cur = box.currentText()
            box.blockSignals(True)
            box.clear()
            box.addItem(ALL)
            box.addItems(opts[key])
            i = box.findText(cur)
            box.setCurrentIndex(i if i >= 0 else 0)
            box.blockSignals(False)

    def filters(self):
        def pick(b):
            return "" if b.currentText() == ALL else b.currentText()
        return {"date_from": self.date_from.text().strip(),
                "date_to": self.date_to.text().strip(),
                "type": pick(self.type_box), "state": pick(self.state_box),
                "estimator": pick(self.est_box)}

    def set_filters(self, **kw):
        """For tests and callers: date_from, date_to, type, state,
        estimator ('' = all)."""
        for k, e in (("date_from", self.date_from),
                     ("date_to", self.date_to)):
            if k in kw:
                e.setText(kw[k] or "")
        for k, b in (("type", self.type_box), ("state", self.state_box),
                     ("estimator", self.est_box)):
            if k in kw:
                b.blockSignals(True)
                i = b.findText(kw[k] or ALL, Qt.MatchFixedString)
                b.setCurrentIndex(i if i >= 0 else 0)
                b.blockSignals(False)
        self.refresh_view()

    def clear_filters(self):
        self.set_filters(date_from="", date_to="", type="", state="",
                         estimator="")

    def refresh_view(self):
        if self.data is None:
            self.data = {"jobs": [], "tab_jobs": [], "bids": [],
                         "index": {}, "skipped": [], "warnings": [],
                         "projects_read": 0, "loaded": ""}
        f = self.filters()
        bad = [k for k in ("date_from", "date_to")
               if f[k] and db.parse_date(f[k]) is None]
        self.report = db.build(self.data, f)
        r = self.report
        self.hint.setVisible(r["empty"])
        msg = (f"{len(r['jobs'])} job(s) and {len(r['bids'])} sub bid(s) "
               f"({db.filters_text(f)}); "
               f"{self.data.get('projects_read', 0)} project(s) read.")
        if bad:
            msg += " Dates: use yyyy-mm-dd (ignored: " + \
                ", ".join(f[k] for k in bad) + ")."
        if r["warnings"]:
            msg += " " + " ".join(r["warnings"][:3])
            if len(r["warnings"]) > 3:
                msg += f" (+{len(r['warnings']) - 3} more)"
        self.status.setText(msg)
        n = len(r["skipped"])
        self.skipped_btn.setVisible(bool(n))
        self.skipped_btn.setText(f"{n} project(s) skipped…")
        self._fill_sf()
        self._fill_hit()
        self._fill_margin()
        self._fill_trades()
        self._fill_jobs()
        self._drill_rows(None)

    # ---------------------------------------------------------- fill
    def _sf_rows(self):
        return self.report["by_division"] if self.sf_by.currentData() == \
            "division" else self.report["by_type"]

    def _fill_sf(self):
        if self.report is None:
            return
        rows = self._sf_rows()
        flags = {(i, 8) for i, g in enumerate(rows) if g["outliers"]}
        self._fill(self.sf_table,
                   ["Group", "Jobs", "Median $/SF", "Low", "High", "Q1",
                    "Q3", "Trend / year", "Outliers"],
                   [[g["label"], g["n"], _m(g["median"]), _m(g["low"]),
                     _m(g["high"]), _m(g["q1"]), _m(g["q3"]),
                     _m(g["trend"]),
                     ", ".join(f"{d['name']} ({d['flag']})"
                               for d in g["detail"] if d["flag"])]
                    for g in rows], rows, flags)
        self.sf_bars.set_rows(
            [(g["label"], g["median"], g["low"], g["high"],
              bool(g["outliers"])) for g in rows],
            "No jobs with a building SF and a cost yet.")
        self.sf_trend.set_points([], title="")

    def _sf_selected(self):
        g = self._picked(self.sf_table)
        if g is None:
            return
        self.sf_trend.set_points(
            [(d["date"], d["value"], bool(d["flag"]), d["name"])
             for d in g["detail"]], g["median"],
            f"{g['label']}: $/SF by bid date (dashed: median"
            + (f"; trend {_m(g['trend'])}/SF per year)" if g["trend"]
               is not None else ")"))
        extra = {d["job"]: (_m(d["value"]) + "/SF",
                            d["flag"] or (_p(d["vs_median"]) + " vs median"
                                          if d["vs_median"] is not None
                                          else ""))
                 for d in g["detail"]}
        self._drill(g["jobs"], f"Jobs behind {g['label']} $/SF", extra)

    def _fill_hit(self):
        if self.report is None:
            return
        rows = self.report["hit"][self.hit_by.currentData() or "type"]
        self._fill(self.hit_table,
                   ["Group", "Won", "Lost", "Pending", "No bid", "Hit rate",
                    "Won $", "Decided $", "$ hit rate"],
                   [[g["label"], g["won"], g["lost"], g["pending"],
                     g["no_bid"], _p(g["rate"]), _m(g["won_amount"]),
                     _m(g["decided_amount"]), _p(g["dollar_rate"])]
                    for g in rows], rows)
        self.hit_bars.set_rows([(g["label"], g["rate"], None, None, False)
                                for g in rows],
                               "Record bid results (Won / Lost) to see the "
                               "hit rate: the Jobs tab, or Project Center > "
                               "Project settings.")

    def _fill_margin(self):
        rows = self.report["margin"]
        self._fill(self.margin_table,
                   ["Building type", "Jobs", "Our bids", "Estimate cost",
                    "Markup", "Margin %", "With actuals",
                    "Estimate (those)", "Actual cost", "Actual − estimate",
                    "Actual vs est. %"],
                   [[g["label"], g["n"], _m(g["bid"]), _m(g["est_cost"]),
                     _m(g["markup"]), _p(g["margin_pct"]), g["n_actual"],
                     _m(g["act_est"]), _m(g["actual"]),
                     _m(g["actual_vs_est"]), _p(g["actual_vs_est_pct"])]
                    for g in rows], rows)

    def _fill_trades(self):
        cur = self.trade_box.currentData()
        self.trade_box.blockSignals(True)
        self.trade_box.clear()
        self.trade_box.addItem("All trades", "")
        for key, label, n in self.report["trades"]:
            self.trade_box.addItem(f"{label} ({n})", key)
        i = self.trade_box.findData(cur) if cur else 0
        self.trade_box.setCurrentIndex(i if i >= 0 else 0)
        self.trade_box.blockSignals(False)
        self._fill_subs()

    def _fill_subs(self):
        if self.report is None:
            return
        key = self.trade_box.currentData() or None
        rows = db.sub_summary(self.report["bids"], key)
        self._fill(self.sub_table,
                   ["Trade", "Company", "Bids", "Times low", "Times awarded",
                    "Median vs job median", "Latest bid", "First", "Last",
                    "From"],
                   [[s["trade"], s["company"], s["bids"], s["low"],
                     s["awarded"] if s["award_known"] else "",
                     _p(s["median_pct"]), _m(s["latest"]), _d(s["first"]),
                     _d(s["last"]), ", ".join(s["sources"])]
                    for s in rows], rows)
        self.sub_chart.set_points([], title="")

    def _sub_selected(self):
        s = self._picked(self.sub_table)
        if s is None:
            return
        self.sub_chart.set_points(
            [(b["date"], b["pct"], b["low"], "") for b in s["history"]], 0,
            f"{s['company']}: % vs each job's median (dashed: the median; "
            "red: low bid)")
        extra = {}
        for b in s["history"]:
            extra[b["job"]] = (_m(b["amount"]),
                               ("low" if b["low"] else "") +
                               (" awarded" if b["awarded"] else "") +
                               (f" {_p(b['pct'])}" if b["pct"] is not None
                                else ""))
        self._drill(s["jobs"], f"Jobs {s['company']} bid ({s['trade']})",
                    extra)

    def _fill_jobs(self):
        js = self.report["jobs"]
        self._fill(self.jobs_table, *self._job_rows(js), js)

    def _job_rows(self, js, extra=None):
        heads = ["Job", "Number", "Building type", "Owner", "State",
                 "Estimator", "Bid date", "Result", "Building SF", "Cost",
                 "Cost basis", "$/SF", "Our bid", "Estimate cost",
                 "Margin %", "Actual cost", "Estimating hours", "From"]
        if extra is not None:
            heads = ["This number", "Note"] + heads
        rows = []
        for j in js:
            mg = db.job_margin(j)
            r = [j["name"], j["number"], j["type"], j["owner"], j["state"],
                 j["estimator"], _d(j["bid_date"]), j["result"],
                 f"{j['sf']:,.0f}" if j["sf"] else "", _m(j["cost"]),
                 j["cost_basis"], _m(db.per_sf(j["cost"], j["sf"])),
                 _m(j["bid"]), _m(j["est_cost"]), _p(mg["margin_pct"]),
                 _m(j["actual_cost"]),
                 f"{j['hours']['total']:,.1f}" if j.get("hours") else "",
                 ", ".join(j["sources"]) + (f" — {j['folder']}"
                                            if j["folder"] else "")]
            if extra is not None:
                r = list(extra.get(j["key"], ("", ""))) + r
            rows.append(r)
        return heads, rows

    # ---------------------------------------------------------- drill
    def _drill_rows(self, g):
        if g is None:
            self._drill([], "Jobs behind the selected row")
            return
        self._drill(g.get("jobs") or [], f"Jobs behind {g['label']}")

    def _drill(self, keys, title, extra=None):
        js = db.jobs_for(self.report, keys) if self.report else []
        self.drill_label.setText(f"{title} ({len(js)})" if keys else title)
        heads, rows = self._job_rows(js, extra)
        self._fill(self.drill, heads, rows, js)

    def _job_selected(self):
        j = self._picked(self.jobs_table)
        if j is None:
            return
        i = self.result_box.findText(j["result"] or "Pending")
        self.result_box.setCurrentIndex(max(0, i))
        self.result_btn.setEnabled(bool(j.get("can_set_result")))
        self._drill([j["key"]], f"{j['name']}")

    def _open_job(self, _item):
        j = self._picked(self.drill)
        if not j or not j.get("folder") or not os.path.isdir(j["folder"]):
            return
        try:
            from .pm import center
            center.open_center(j["folder"], self.win)
        except Exception as e:                            # noqa: BLE001
            QMessageBox.warning(self, "Estimating Dashboard",
                                f"Couldn't open the project: {e}")

    # ---------------------------------------------------------- actions
    def set_result(self, result=None):
        j = self._picked(self.jobs_table)
        if j is None:
            self.status.setText("Pick a job on the Jobs tab first.")
            return None
        result = result or self.result_box.currentText()
        try:
            where = db.set_result(j, result)
        except Exception as e:                            # noqa: BLE001
            QMessageBox.warning(self, "Estimating Dashboard", str(e))
            return None
        key = j["key"]
        self.refresh_view()
        for i, x in enumerate(self.payload.get(id(self.jobs_table), [])):
            if x["key"] == key:
                self.jobs_table.selectRow(i)
                break
        self.status.setText(f"{j['name']}: {result} (saved in "
                            f"{' and '.join(where)}).")
        return where

    def set_low_bid(self, amount=None):
        j = self._picked(self.jobs_table)
        if j is None:
            self.status.setText("Pick a job on the Jobs tab first.")
            return None
        if amount is None:
            from PySide6.QtWidgets import QInputDialog
            amount, ok = QInputDialog.getText(self, "Low Bid",
                                              f"Low bid for {j['name']}:")
            if not ok or not str(amount).strip():
                return None
        try:
            v = db.set_low_bid(j, amount)
        except Exception as e:                            # noqa: BLE001
            QMessageBox.warning(self, "Estimating Dashboard", str(e))
            return None
        gap = (j["bid"] - v) if j.get("bid") is not None else None
        self.status.setText(f"{j['name']}: low bid ${_c2(v):,.2f}" + (
            f", we were ${_c2(gap):,.2f} over" if gap and gap > 0 else
            " - we were low" if gap is not None and gap <= 0 else ""))
        self.refresh_view()
        return v

    def export_bid_results(self, path=None):
        import csv
        if path is None:
            path, _ = QFileDialog.getSaveFileName(
                self, "Bid Results", "Bid Results.csv", "CSV (*.csv)")
            if not path:
                return None
        jobs = getattr(self, "jobs", None) or self.payload.get(
            id(self.jobs_table), [])
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Job", "Bid date", "Owner", "Result", "Our bid",
                        "Low bid", "Gap", "Gap %", "Estimating hours",
                        "Bid per estimating hour"])
            for r in db.bid_results(jobs):
                w.writerow([r["name"], r["date"] or "", r["owner"],
                            r["result"], r["bid"] if r["bid"] is not None
                            else "", r["low"] if r["low"] is not None else "",
                            r["gap"] if r["gap"] is not None else "",
                            r["gap_pct"] if r["gap_pct"] is not None else "",
                            r["hours"] if r["hours"] is not None else "",
                            r["bid_per_hour"] if r["bid_per_hour"] is not None
                            else ""])
        return path

    def add_folders(self):
        f = QFileDialog.getExistingDirectory(self, "Project folder")
        if not f:
            return
        from .pm.store import ProjectStore
        if ProjectStore.exists(f):
            db.add_folders([f])
        else:
            # a folder of projects: every sub-folder that is one
            subs = [os.path.join(f, n) for n in sorted(os.listdir(f))
                    if os.path.isdir(os.path.join(f, n)) and
                    os.path.isfile(db.project_file(os.path.join(f, n)))]
            if not subs:
                QMessageBox.information(
                    self, "Estimating Dashboard",
                    "No QuantiSheet project in that folder or the folders "
                    "in it.")
                return
            db.add_folders(subs)
        if self.folders is not None:
            self.folders = list(self.folders) + [f]
        self.reload()

    def show_skipped(self):
        s = self.report["skipped"] if self.report else []
        QMessageBox.information(
            self, "Projects skipped",
            "These folders couldn't be read and were left out (nothing in "
            "them was changed):\n\n" + "\n".join(
                f"{x['folder']}: {x['reason']}" for x in s[:40]) +
            (f"\n… and {len(s) - 40} more" if len(s) > 40 else ""))

    def _save_path(self, title, ext, filt):
        from .reportname import report_file_name
        # all projects, so no project name; the date comes first
        path, _ = QFileDialog.getSaveFileName(
            self, title, report_file_name("Estimating Dashboard",
                                          ext=f".{ext}"), filt)
        if path and not path.lower().endswith("." + ext):
            path += "." + ext
        return path

    def export_excel(self, path=None):
        path = path or self._save_path("Export to Excel", "xlsx",
                                       "Excel (*.xlsx)")
        if not path:
            return None
        try:
            db.export_xlsx(self.report, path)
        except Exception as e:                            # noqa: BLE001
            QMessageBox.warning(self, "Export to Excel", str(e))
            return None
        self.status.setText(f"Saved {path}")
        return path

    def export_pdf(self, path=None):
        path = path or self._save_path("Export to PDF", "pdf", "PDF (*.pdf)")
        if not path:
            return None
        try:
            db.export_pdf(self.report, path)
        except Exception as e:                            # noqa: BLE001
            QMessageBox.warning(self, "Export to PDF", str(e))
            return None
        self.status.setText(f"Saved {path}")
        return path


def show(win=None, folders=None):
    dlg = EstimatingDashboard(win, folders)
    dlg.setAttribute(Qt.WA_DeleteOnClose)
    dlg.show()
    return dlg
