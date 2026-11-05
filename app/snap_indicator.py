"""Snap indicator: a coloured box and a label (END, MID, EDGE, INT, PERP,
GRID) at the snapped point, two extra snap kinds snap.py lacks
(perpendicular from the anchor, grid), per-mode on/off saved in settings,
and the status-bar text. Alt bypasses snapping, Shift locks to straight
lines (snap.ortho) - the same keys PdfView.snap_point already uses.
"""
import math

import fitz

from . import settings, snap

PERP, GRID = "Perpendicular", "Grid"
STYLE = {snap.ENDPOINT: ("END", "#e53935"), snap.MIDPOINT: ("MID", "#1e88e5"),
         snap.ONLINE: ("EDGE", "#8e24aa"), snap.INTERSECTION: ("INT", "#fb8c00"),
         PERP: ("PERP", "#00897b"), GRID: ("GRID", "#757575")}
LABEL_KIND = {lab: k for k, (lab, _) in STYLE.items()}
ORDER = ["END", "MID", "EDGE", "INT", "PERP", "GRID"]
DEFAULT_MODES = ("END", "MID", "EDGE", "INT", "PERP")


def style(kind):
    return STYLE.get(kind, ("", "#000000"))


def load_modes():
    m = settings.get("snap_modes")
    return set(m) if isinstance(m, (list, tuple)) else set(DEFAULT_MODES)


def save_modes(modes):
    settings.set("snap_modes", [m for m in ORDER if m in modes])


def _foot(p, a, b):
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    if not L:
        return None
    t = ((p.x - ax) * dx + (p.y - ay) * dy) / L
    if t < 0 or t > 1:
        return None
    return fitz.Point(ax + t * dx, ay + t * dy)


def resolve(pt, anchor, index, radius, modes=None, shift=False, alt=False,
            segs=None, grid=24.0):
    """(point, kind or None) for a cursor at `pt`."""
    if alt:
        return pt, None
    if shift and anchor is not None:
        return snap.ortho(anchor, pt), None
    modes = set(DEFAULT_MODES) if modes is None else set(modes)
    kinds = {LABEL_KIND[m] for m in modes if m in LABEL_KIND} - {PERP, GRID}
    if kinds:
        hit = index.snap(pt, radius, kinds=kinds)
        if hit:
            return hit[0], hit[1]
    if "PERP" in modes and anchor is not None:
        best = None
        for a, b in (segs if segs is not None else getattr(index, "segs", [])):
            f = _foot(anchor, a, b)
            if f is not None:
                d = math.hypot(f.x - pt.x, f.y - pt.y)
                if d <= radius and (best is None or d < best[0]):
                    best = (d, f)
        if best:
            return best[1], PERP
    if "GRID" in modes and grid:
        g = fitz.Point(round(pt.x / grid) * grid, round(pt.y / grid) * grid)
        if math.hypot(g.x - pt.x, g.y - pt.y) <= radius:
            return g, GRID
    return pt, None


def status_text(modes):
    on = [m for m in ORDER if m in modes]
    head = "Snap: " + (" ".join(on) if on else "off")
    return head + "   (Alt = no snap, Shift = straight)"


def paint(painter, screen_pt, kind, size=10):
    """Draw the box + label at a screen point (QPointF)."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QFont, QPen
    lab, col = style(kind)
    if not lab:
        return
    c = QColor(col)
    painter.save()
    painter.setPen(QPen(c, 2))
    painter.setBrush(Qt_NoBrush())
    h = size / 2
    painter.drawRect(QRectF(screen_pt.x() - h, screen_pt.y() - h, size, size))
    f = QFont(painter.font())
    f.setPointSizeF(7.5)
    f.setBold(True)
    painter.setFont(f)
    r = QRectF(screen_pt.x() + h + 3, screen_pt.y() - h - 12, 34, 13)
    painter.fillRect(r, c)
    painter.setPen(QColor("#ffffff"))
    from PySide6.QtCore import Qt
    painter.drawText(r, Qt.AlignCenter, lab)
    painter.restore()


def Qt_NoBrush():
    from PySide6.QtCore import Qt
    return Qt.NoBrush
