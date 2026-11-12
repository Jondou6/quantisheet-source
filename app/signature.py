"""Fill & Sign: a drawn signature / initials, saved once and reused.

(These are handwritten-style signatures, not certificate-based digital
signatures.) Strokes are stored normalised to 0..1, encrypted for your
Windows account (sigstore.py; before Nov 11 they sat in settings.json).
"""
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel,
                               QPushButton, QVBoxLayout, QWidget)

from . import settings


class _Pad(QWidget):
    def __init__(self):
        super().__init__()
        self.strokes = []
        self.setMinimumSize(520, 180)
        self.setCursor(Qt.CrossCursor)

    def mousePressEvent(self, e):
        self.strokes.append([e.position()])
        self.update()

    def mouseMoveEvent(self, e):
        if self.strokes and e.buttons() & Qt.LeftButton:
            self.strokes[-1].append(e.position())
            self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(255, 255, 255))
        p.setPen(QPen(QColor(200, 200, 200), 1, Qt.DashLine))
        y = self.height() * 0.75
        p.drawLine(20, int(y), self.width() - 20, int(y))
        p.setPen(QPen(QColor(10, 30, 120), 2.5, Qt.SolidLine, Qt.RoundCap,
                      Qt.RoundJoin))
        for s in self.strokes:
            if len(s) > 1:
                path = QPainterPath(s[0])
                for q in s[1:]:
                    path.lineTo(q)
                p.drawPath(path)

    def normalised(self):
        pts = [q for s in self.strokes for q in s]
        if len(pts) < 2:
            return []
        x0 = min(q.x() for q in pts)
        y0 = min(q.y() for q in pts)
        w = max(1, max(q.x() for q in pts) - x0)
        h = max(1, max(q.y() for q in pts) - y0)
        scale = max(w, h)
        return {"w": w / scale, "h": h / scale,
                "strokes": [[[round((q.x() - x0) / scale, 4),
                              round((q.y() - y0) / scale, 4)] for q in s]
                            for s in self.strokes if len(s) > 1]}


class SignaturePad(QDialog):
    def __init__(self, kind="signature", parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setWindowTitle("Draw your " + kind)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(f"Draw your {kind} with the mouse (or a pen). "
                             "It's saved so you can reuse it."))
        self.pad = _Pad()
        lay.addWidget(self.pad)
        clear = QPushButton("Clear")
        clear.clicked.connect(lambda: (self.pad.strokes.clear(),
                                       self.pad.update()))
        lay.addWidget(clear)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _save(self):
        data = self.pad.normalised()
        if not data:
            return
        from . import sigstore
        if self.kind in sigstore.KINDS:
            sigstore.save(self.kind, data)       # encrypted for your account
        else:
            settings.set(self.kind, data)
        self.accept()


def saved(kind):
    from . import sigstore
    if kind in sigstore.KINDS:
        return sigstore.load(kind)
    data = settings.get(kind)
    return data if isinstance(data, dict) and data.get("strokes") else None


def strokes_in(data, rect):
    """Scale saved strokes to fit `rect` (keeping their shape), centred."""
    s = min(rect.width / max(data["w"], 1e-3),
            rect.height / max(data["h"], 1e-3))
    ox = rect.x0 + (rect.width - data["w"] * s) / 2
    oy = rect.y0 + (rect.height - data["h"] * s) / 2
    return [[[ox + x * s, oy + y * s] for x, y in st]
            for st in data["strokes"]]
