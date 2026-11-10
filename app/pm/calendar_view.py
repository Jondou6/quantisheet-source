"""A month / week calendar of all-day items (activities, meetings,
inspections, deliveries), painted in the look of the Kargul calendar design
prototype (MIT, see THIRD_PARTY_NOTICES.txt). Our own Qt code; no web view.
The same widget, kept in step, is in Back Office (which never imports the
host app).

    view = CalendarView(source)        source(start, end) -> (items, hours)
    items: [{kind, start, end, title, ...}]   ISO dates, end inclusive
    hours: {iso date: {"work": h, "pto": h}} (hundredths), may be {}

Signals: rangeSelected(date, date) when a range of days is dragged (or a
day double-clicked), itemActivated(dict) when a bar is clicked,
itemMoved(dict, days) when a bar marked "movable" is dragged to another
day, dateChanged(date) when the shown period moves.
"""
from __future__ import annotations

import calendar as _cal
from datetime import date, timedelta

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QButtonGroup, QHBoxLayout, QLabel,
                               QPushButton, QSizePolicy, QVBoxLayout,
                               QWidget)
from ..dmoney import c2 as _c2

# colours from the design's tokens
INK = QColor("#1d1d1d")
INK_2 = QColor("#757575")
DIM = QColor("#a1a1a1")
DAYNAME = QColor("#9e9e9e")
LINE = QColor("#e5e7e1")
OUT_BG = QColor("#f8f8f8")
BRAND = QColor("#8965de")
BRAND_TINT = QColor(137, 101, 222, 26)
KIND_COLORS = {                    # (background, text)
    "holiday": (QColor("#e3daf7"), QColor("#594290")),
    "timeoff": (QColor("#bde7db"), QColor("#005c42")),
    "pending": (QColor("#fdd8b8"), QColor("#774317")),
    "event": (QColor("#c5e2f9"), QColor("#0e5289")),
    "milestone": (QColor("#fdd4e6"), QColor("#813455")),
    "activity": (QColor("#aee9f4"), QColor("#28555d")),
    "inspection": (QColor("#bde7db"), QColor("#005c42")),
    "meeting": (QColor("#e3daf7"), QColor("#594290")),
    "delivery": (QColor("#fdd8b8"), QColor("#774317")),
}
WORK = QColor("#178be8")
PTO = QColor("#00a475")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MAX_LANES_MONTH = 3
MAX_LANES_WEEK = 8


def week_start(d: date, starts_on: int = 0) -> date:
    return d - timedelta(days=(d.weekday() - starts_on) % 7)


def month_weeks(d: date, starts_on: int = 0) -> list[list[date]]:
    first = d.replace(day=1)
    s = week_start(first, starts_on)
    out = []
    while True:
        out.append([s + timedelta(days=i) for i in range(7)])
        s += timedelta(days=7)
        if (s.year, s.month) != (d.year, d.month) and s > first:
            break
    return out


def lanes(items, days):
    """[(item, lane, first col, last col)]: each item in the lowest lane
    free across its whole span within these days."""
    ds = [x.isoformat() for x in days]
    out, busy = [], []
    for it in sorted(items, key=lambda x: (x["start"], x["end"],
                                           x.get("title", ""))):
        if it["end"] < ds[0] or it["start"] > ds[-1]:
            continue
        c0 = next(i for i, x in enumerate(ds) if x >= it["start"]) \
            if it["start"] > ds[0] else 0
        c1 = max(i for i, x in enumerate(ds) if x <= it["end"])
        lane = 0
        while any(ln == lane and not (c1 < a or c0 > b)
                  for ln, a, b in busy):
            lane += 1
        busy.append((lane, c0, c1))
        out.append((it, lane, c0, c1))
    return out


def _hours(h) -> str:
    v = (h or 0) / 100
    return f"{_c2(v):.2f}".rstrip("0").rstrip(".") + " h"


class _Grid(QWidget):
    """The painted grid; CalendarView owns the navigation."""

    def __init__(self, owner):
        super().__init__(owner)
        self.o = owner
        self.setMouseTracking(True)
        self.setMinimumHeight(360)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Expanding)
        self._press = None
        self._drag = None
        self.hits = []                         # (QRectF, item) for clicks

    # geometry -------------------------------------------------------
    HEAD = 28

    def rows(self) -> list[list[date]]:
        o = self.o
        if o.mode == "week":
            return [[week_start(o.date, o.starts_on) + timedelta(days=i)
                     for i in range(7)]]
        return month_weeks(o.date, o.starts_on)

    def cell(self, r, c, nrows) -> QRectF:
        w = self.width() / 7.0
        h = (self.height() - self.HEAD) / max(nrows, 1)
        return QRectF(c * w, self.HEAD + r * h, w, h)

    def day_at(self, pos) -> date | None:
        rows = self.rows()
        if pos.y() < self.HEAD:
            return None
        c = int(pos.x() // (self.width() / 7.0))
        r = int((pos.y() - self.HEAD) //
                ((self.height() - self.HEAD) / max(len(rows), 1)))
        if 0 <= r < len(rows) and 0 <= c < 7:
            return rows[r][c]
        return None

    def item_at(self, pos):
        for rect, it in self.hits:
            if rect.contains(QPointF(pos)):
                return it
        return None

    # painting -------------------------------------------------------
    def paintEvent(self, _ev):
        o = self.o
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#ffffff"))
        rows = self.rows()
        f = QFont(self.font())
        f.setPointSizeF(max(8.0, f.pointSizeF()))
        small = QFont(f)
        small.setPointSizeF(f.pointSizeF() - 1)
        bold = QFont(f)
        bold.setBold(True)
        self.hits = []
        today = o.today
        p.setFont(small)
        for c in range(7):
            r0 = self.cell(0, c, len(rows))
            p.setPen(DAYNAME)
            name = WEEKDAYS[(c + o.starts_on) % 7]
            if o.mode == "week":
                name += f"  {rows[0][c].day}"
            p.drawText(QRectF(r0.x() + 8, 0, r0.width() - 8, self.HEAD),
                       Qt.AlignmentFlag.AlignVCenter, name)
        p.setPen(QPen(LINE, 1))
        p.drawLine(0, self.HEAD, self.width(), self.HEAD)
        sel = self._sel_range()
        if getattr(self, "_carry", None) and self._carry_to:
            sel = (self._carry_to, self._carry_to)
        lane_h = 20
        max_lanes = MAX_LANES_WEEK if o.mode == "week" else MAX_LANES_MONTH
        for r, week in enumerate(rows):
            for c, d in enumerate(week):
                rc = self.cell(r, c, len(rows))
                if o.mode == "month" and d.month != o.date.month:
                    p.fillRect(rc, OUT_BG)
                if sel and sel[0] <= d <= sel[1]:
                    p.fillRect(rc, BRAND_TINT)
                p.setPen(QPen(LINE, 1))
                p.drawRect(rc)
                # the day number: today in the accent colour
                num = QRectF(rc.x() + 6, rc.y() + 4, 26, 20)
                if d == today:
                    path = QPainterPath()
                    path.addRoundedRect(num, 7, 7)
                    p.fillPath(path, BRAND)
                    p.setPen(QColor("#ffffff"))
                    p.setFont(bold)
                else:
                    in_month = o.mode == "week" or d.month == o.date.month
                    p.setPen(INK if in_month else DIM)
                    p.setFont(f)
                if o.mode == "month" or d == today:
                    p.drawText(num, Qt.AlignmentFlag.AlignCenter, str(d.day))
                # hours worked / PTO for the day, bottom right
                h = o.hours.get(d.isoformat()) or {}
                if h.get("work") or h.get("pto"):
                    p.setFont(small)
                    txt = []
                    if h.get("work"):
                        txt.append(("work " + _hours(h["work"]), WORK))
                    if h.get("pto"):
                        txt.append(("PTO " + _hours(h["pto"]), PTO))
                    y = rc.bottom() - 6 - 15 * len(txt)
                    for t, col in txt:
                        p.setPen(col)
                        p.drawText(QRectF(rc.x() + 6, y, rc.width() - 12,
                                          15),
                                   Qt.AlignmentFlag.AlignRight, t)
                        y += 15
            # bars for this week row
            top = self.cell(r, 0, len(rows)).y() + 28
            more = {}
            for it, lane, c0, c1 in lanes(o.items, week):
                if lane >= max_lanes:
                    for c in range(c0, c1 + 1):
                        more[c] = more.get(c, 0) + 1
                    continue
                a = self.cell(r, c0, len(rows))
                b = self.cell(r, c1, len(rows))
                rect = QRectF(a.x() + 3, top + lane * (lane_h + 2),
                              b.right() - a.x() - 6, lane_h)
                bg, fg = KIND_COLORS.get(it.get("kind"),
                                         KIND_COLORS["event"])
                path = QPainterPath()
                path.addRoundedRect(rect, 6, 6)
                p.fillPath(path, bg)
                p.setPen(fg)
                p.setFont(small)
                p.drawText(rect.adjusted(6, 0, -4, 0),
                           Qt.AlignmentFlag.AlignVCenter,
                           p.fontMetrics().elidedText(
                               it.get("title", ""), Qt.TextElideMode.ElideRight,
                               int(rect.width() - 10)))
                self.hits.append((rect, it))
            for c, n in more.items():
                rc = self.cell(r, c, len(rows))
                p.setPen(INK_2)
                p.setFont(small)
                p.drawText(QRectF(rc.x() + 6, top + max_lanes * (lane_h + 2),
                                  rc.width() - 12, 16),
                           Qt.AlignmentFlag.AlignLeft, f"+{n} more")
        p.end()

    # mouse ----------------------------------------------------------
    def _sel_range(self):
        if not self._press or not self._drag:
            return None
        a, b = sorted((self._press, self._drag))
        return a, b

    def mousePressEvent(self, ev):
        if ev.button() != Qt.MouseButton.LeftButton:
            return
        it = self.item_at(ev.position())
        if it is not None:
            self._carry = (it, self.day_at(ev.position())) \
                if it.get("movable") else None
            self._carry_to = None
            if self._carry is None:
                self.o.itemActivated.emit(it)
            return
        self._press = self.day_at(ev.position())
        self._drag = self._press
        self.update()

    def mouseMoveEvent(self, ev):
        if getattr(self, "_carry", None):
            d = self.day_at(ev.position())
            if d and d != self._carry_to:
                self._carry_to = d
                self.update()
            return
        if self._press is None:
            it = self.item_at(ev.position())
            self.setToolTip(self.o.tooltip(it) if it else "")
            return
        d = self.day_at(ev.position())
        if d and d != self._drag:
            self._drag = d
            self.update()

    def mouseReleaseEvent(self, ev):
        carry = getattr(self, "_carry", None)
        if carry:
            it, frm = carry
            to = self._carry_to
            self._carry = self._carry_to = None
            self.update()
            if frm and to and to != frm:
                self.o.itemMoved.emit(it, (to - frm).days)
            else:
                self.o.itemActivated.emit(it)
            return
        rng = self._sel_range()
        self._press = self._drag = None
        self.update()
        if rng and rng[0] != rng[1]:
            self.o.rangeSelected.emit(rng[0], rng[1])

    def mouseDoubleClickEvent(self, ev):
        if self.item_at(ev.position()) is not None:
            return
        d = self.day_at(ev.position())
        self._press = self._drag = None
        if d:
            self.o.rangeSelected.emit(d, d)


class CalendarView(QWidget):
    rangeSelected = Signal(object, object)
    itemActivated = Signal(object)
    itemMoved = Signal(object, int)
    dateChanged = Signal(object)

    def __init__(self, source, parent=None, today=None, starts_on=0,
                 mode="month"):
        super().__init__(parent)
        self.source = source
        self.today = today or date.today()
        self.date = self.today
        self.starts_on = starts_on
        self.mode = mode
        self.items, self.hours = [], {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.title = QLabel()
        tf = self.title.font()
        tf.setPointSizeF(tf.pointSizeF() + 3)
        tf.setBold(True)
        self.title.setFont(tf)
        bar.addWidget(self.title)
        bar.addStretch(1)
        self.prev_btn = QPushButton("‹")
        self.today_btn = QPushButton("Today")
        self.next_btn = QPushButton("›")
        for b in (self.prev_btn, self.today_btn, self.next_btn):
            bar.addWidget(b)
        self.prev_btn.clicked.connect(lambda: self.step(-1))
        self.next_btn.clicked.connect(lambda: self.step(1))
        self.today_btn.clicked.connect(self.go_today)
        self.mode_group = QButtonGroup(self)
        self.mode_btns = {}
        for m in ("month", "week"):
            b = QPushButton(m.title())
            b.setCheckable(True)
            b.setChecked(m == mode)
            b.clicked.connect(lambda _=False, m=m: self.set_mode(m))
            self.mode_group.addButton(b)
            self.mode_btns[m] = b
            bar.addWidget(b)
        lay.addLayout(bar)
        self.grid = _Grid(self)
        lay.addWidget(self.grid, 1)
        self.reload()

    # navigation -----------------------------------------------------
    def span(self) -> tuple[date, date]:
        rows = self.grid.rows()
        return rows[0][0], rows[-1][-1]

    def set_mode(self, mode):
        self.mode = mode
        self.mode_btns[mode].setChecked(True)
        self.reload()

    def set_date(self, d):
        self.date = d
        self.reload()
        self.dateChanged.emit(d)

    def step(self, n):
        if self.mode == "week":
            self.set_date(self.date + timedelta(days=7 * n))
        else:
            m = self.date.month - 1 + n
            y, m = self.date.year + m // 12, m % 12 + 1
            self.set_date(date(y, m, min(self.date.day,
                                         _cal.monthrange(y, m)[1])))

    def go_today(self):
        self.set_date(self.today)

    def reload(self):
        a, b = self.span()
        try:
            self.items, self.hours = self.source(a, b)
        except Exception:                                 # noqa: BLE001
            self.items, self.hours = [], {}
        if self.mode == "week":
            self.title.setText(f"{a:%b %d} – {b:%b %d, %Y}")
        else:
            self.title.setText(f"{self.date:%B %Y}")
        self.grid.update()

    def tooltip(self, it) -> str:
        t = it.get("title", "")
        if it["start"] != it["end"]:
            t += f"\n{it['start']} to {it['end']}"
        else:
            t += f"\n{it['start']}"
        return t
