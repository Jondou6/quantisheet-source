"""Measurement bar (bottom of the viewer), ported from the Takeoff Studio
mockup with its bugs fixed:

- live length / area / count while drawing, from the page's real scale
  calibration (Set Scale) - nothing is shown as a length until there is one;
- type an exact value (12'6, 12'-6", 150", 12.5, 3 m) to set the current
  segment; Enter commits, Esc cancels; "Add to takeoff" button;
- the job total is summed from the document's takeoff (annotate.
  takeoff_items), not a hard-coded number.
"""
import math
import re

import fitz

from . import annotate, takeoff

_FT_BARE_IN = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*'\s*-?\s*(\d+(?:\.\d+)?)(?:\s+(\d+)\s*/\s*(\d+))?\s*$")
UNITS = {"length": None, "area": "sq", "count": "ea"}


def parse_entry(text, unit="ft"):
    """Typed value -> number in `unit` (the calibration unit), or None.
    Bare numbers are taken as `unit`."""
    t = (text or "").translate(takeoff._QUOTES).strip()
    if not t or t.startswith("-"):
        return None
    m = _FT_BARE_IN.match(t)                     # 12'6 / 12'-6 / 12' 6 1/2
    if m:
        inches = float(m.group(2))
        if m.group(3) and m.group(4) and float(m.group(4)):
            inches += float(m.group(3)) / float(m.group(4))
        return takeoff.convert(float(m.group(1)) + inches / 12, "ft", unit)
    r = takeoff.parse_length(t)
    if not r:
        return None
    v, u = r
    if v <= 0 or not math.isfinite(v):
        return None
    return takeoff.convert(v, u or unit, unit)


_ANGLE = re.compile(r"^(.*?)\s*[<@]\s*(-?\d+(?:\.\d+)?)\s*°?\s*$")


def split_angle(text):
    """("24'-6\"", 45.0) from "24'-6\"<45" or "24'-6\" @ 45" (degrees,
    0 = right, counter-clockwise, as on a drawing); (text, None) without
    one (Nov 4 takeoff list #12)."""
    m = _ANGLE.match(text or "")
    if not m or not m.group(1).strip():
        return text, None
    return m.group(1).strip(), float(m.group(2)) % 360


def live(pts, cal, mode="length"):
    """Current measurement in calibration units (area in units^2); counts
    need no scale. None when a length/area has no calibration."""
    if mode == "count":
        return len(pts)
    if cal is None:
        return None
    if mode == "area":
        return takeoff.area(cal, pts)
    return sum(takeoff.distance(cal, a, b) for a, b in zip(pts, pts[1:]))


def set_segment(pts, value, cal, angle=None):
    """Copy of pts with the last segment set to `value` (calibration units),
    keeping its direction (or +x if it has none) - or at `angle` degrees
    (0 = right, counter-clockwise on screen)."""
    if cal is None:
        raise ValueError("set the scale first (Set Scale)")
    if len(pts) < 2:
        raise ValueError("need a segment")
    a, b = pts[-2], pts[-1]
    dx, dy = b.x - a.x, b.y - a.y
    d = math.hypot(dx, dy)
    ux, uy = (dx / d, dy / d) if d else (1.0, 0.0)
    if angle is not None:
        r = math.radians(angle)
        ux, uy = math.cos(r), -math.sin(r)        # screen y points down
    L = value * cal.points_per_unit
    return list(pts[:-1]) + [fitz.Point(a.x + ux * L, a.y + uy * L)]


def job_total(doc, mtype, unit=None, group=None):
    """Sum of the document's takeoff of one type (length/area/count),
    optionally one group / unit. Counts honour multipliers."""
    total = 0.0
    for it in annotate.totals_items(doc):
        if it["type"] != mtype:
            continue
        if group is not None and it.get("group") != group:
            continue
        if unit is not None and (it.get("unit") or "") != unit:
            continue
        total += (it.get("multiplier") or 1) if mtype == "count" else \
            (it.get("value") or 0)
    return total


def fmt_value(mode, v, unit):
    if v is None:
        return ""
    if mode == "count":
        return f"{int(v):,} ea"
    if mode == "area":
        return f"{v:,.1f} {unit}\u00b2" if unit != "ft" else f"{v:,.1f} SF"
    if unit == "ft":
        ft = int(v)
        inch = round((v - ft) * 12)
        if inch == 12:
            ft, inch = ft + 1, 0
        return f"{ft:,}'-{inch}\""
    return f"{v:,.2f} {unit}"


try:
    from PySide6.QtCore import Qt, Signal, QEvent
    from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit,
                                   QPushButton, QWidget)
except ImportError:          # pragma: no cover
    QWidget = None

if QWidget is not None:
    class MeasureBar(QWidget):
        committed = Signal(float)      # typed value, calibration units
        cancelled = Signal()
        add_requested = Signal()

        def __init__(self, parent=None):
            super().__init__(parent)
            lay = QHBoxLayout(self)
            lay.setContentsMargins(6, 2, 6, 2)
            self.readout = QLabel("")
            self.entry = QLineEdit()
            self.entry.setPlaceholderText("Type a length: 12'6, 150\", "
                                          "12.5 - or 12'6<45 for an angle")
            self.angle = None
            self.entry.setMaximumWidth(220)
            self.add_btn = QPushButton("Add to takeoff")
            # F8 takeoff keys shown here too, where you're looking while
            # measuring (review 2, Nov 4)
            self.keys = QLabel("")
            self.keys.setObjectName("StatusChipAccent")
            self.keys.setVisible(False)
            lay.addWidget(self.keys)
            lay.addWidget(self.readout, 1)
            lay.addWidget(self.entry)
            lay.addWidget(self.add_btn)
            self.unit = "ft"
            self.entry.returnPressed.connect(self._enter)
            self.entry.installEventFilter(self)
            self.add_btn.clicked.connect(self.add_requested)

        def eventFilter(self, obj, ev):
            if obj is self.entry and ev.type() == QEvent.KeyPress and \
                    ev.key() == Qt.Key_Escape:
                self.entry.clear()
                self.cancelled.emit()
                return True
            return super().eventFilter(obj, ev)

        def _enter(self):
            text, self.angle = split_angle(self.entry.text())
            v = parse_entry(text, self.unit)
            if v is None:
                self.entry.setStyleSheet("border: 1px solid #d93a2b")
                return
            self.entry.setStyleSheet("")
            self.entry.clear()
            self.committed.emit(float(v))

        def set_keys_on(self, on):
            self.keys.setText("Takeoff keys ON (F8)" if on else "")
            self.keys.setVisible(bool(on))

        def set_live(self, mode, value, unit="ft", job_total=None):
            self.unit = unit or "ft"
            if value is None and mode != "count":
                self.readout.setText("No scale on this page - use Set Scale")
                return
            txt = f"{mode.title()}: {fmt_value(mode, value, self.unit)}"
            if job_total is not None:
                txt += f"   |   Job total: {fmt_value(mode, job_total, self.unit)}"
            self.readout.setText(txt)
