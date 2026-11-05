"""Help > Welcome Tour: a guided walk around the real window.

Each stop dims the window, outlines the part being explained (the ribbon,
the tool rail, the search box, a panel, the status bar...) and shows a
callout beside it with Back / Next. It is different from the Help
Center's tutorials, which teach a whole job step by step (Jon, Oct 19:
"the Tour and Tutorials is the same thing")."""
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QDockWidget, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

# (how to find it, title, text). The finder gets the main window and
# returns a widget, or None (the callout then sits in the middle).
STOPS = [
    (lambda w: None, "Welcome to QuantiSheet",
     "This short tour points at each part of the window and says what "
     "it is for. Use <b>Next</b> and <b>Back</b>, or <b>Esc</b> to stop. "
     "For step-by-step lessons on a whole job (a takeoff, an estimate, an "
     "RFI), open <b>Help &gt; Help Center &amp; Tutorials</b> (F1)."),
    (lambda w: w.ribbon, "The ribbon",
     "Every command, grouped by job: <b>Home</b> (open, save, print), "
     "<b>Markup</b>, <b>Takeoff</b>, <b>Estimate</b> (civil too), "
     "<b>Review</b>, <b>Project</b> (billing, codes and modules), "
     "<b>Pages</b>, <b>Document</b>, <b>Tools</b> and <b>Help</b>. Tabs "
     "that don't fit the open file step aside (View &gt; Ribbon Tabs &gt; "
     "Show All Tabs brings them back). Double-click a tab to fold the "
     "ribbon away."),
    (lambda w: getattr(w, "quick_bar", None), "The quick bar",
     "Your most-used tools, one click away on every tab. Right-click any "
     "ribbon button and choose <b>Pin to Quick Bar</b>; drag these to "
     "reorder; right-click one to unpin it. <b>Export</b> repeats your "
     "last export."),
    (lambda w: w.findChild(QWidget, "CommandSearch"), "Search every command",
     "Can't find something? Press <b>Ctrl+K</b> (or click here) and type a "
     "few letters - <i>area</i>, <i>rfi</i>, <i>overlay</i>, <i>aerial</i> - "
     "then Enter. It searches every menu, ribbon button and panel, so you "
     "never have to remember where a command lives."),
    (lambda w: getattr(getattr(w, "layouts", None), "rail", None),
     "The tool rail",
     "Your everyday tools, always one click away: Select, Zoom, Set Scale, "
     "Length, Area, Count, Cloud, Text Box and the rest you pin. The tool "
     "you're using is marked with a blue edge. Right-click a tool in "
     "<b>All Tools</b> to pin or unpin it here."),
    (lambda w: w.findChild(QWidget, "all_tools"), "All Tools",
     "Every tool in one searchable list (<b>Ctrl+Shift+T</b>). Type to "
     "filter, double-click to use, right-click to pin to the rail."),
    (lambda w: _dock(w, "thumb_dock"), "Pages",
     "Thumbnails of every sheet. Drag to reorder, right-click to rotate, "
     "insert, extract or delete pages. Next to it are <b>Bookmarks</b>, "
     "<b>Documents</b> (every PDF in a project folder), <b>Sets</b> and the "
     "<b>Takeoff</b> list - click their tabs at the bottom of the panel."),
    (lambda w: w.tabs, "Your drawings",
     "Each PDF opens in its own tab. Scroll to move, <b>Ctrl+wheel</b> to "
     "zoom, <b>PgUp/PgDn</b> to turn sheets, <b>Ctrl+G</b> to jump to a "
     "page. Big sets stay smooth: sheets are drawn ahead of you in the "
     "background."),
    (lambda w: _dock(w, "markups_dock"), "Markups, Properties and Estimate",
     "The right side holds the <b>Markups List</b> (every cloud, note and "
     "measurement, with status and filters), <b>Properties</b> of what you "
     "selected, the <b>Tool Chest</b>, <b>Quantities</b>, <b>Assemblies</b> "
     "and the <b>Estimate</b>. Click a row to jump to it on the drawing. "
     "The Markups List's <b>Origin</b> column shows what was drawn by hand, "
     "found by AI, accepted, or <i>AI, edited</i> by a person."),
    (lambda w: _tab_of(w, "Takeoff"), "Takeoff tools",
     "Measure, count and trace. On the drawing: select an outline and "
     "<b>drag its corners</b> to fix it; <b>drag a box</b> or Ctrl+click to "
     "select several and right-click to move or delete them together. "
     "<b>Count by Label</b> finds tag families with wildcards (P-#), and "
     "the <b>Count Library</b> keeps the symbols you count on every job. "
     "<b>Wall Area</b> (Shift+W) gives length x height less openings; "
     "right-click a measurement to add a rise/drop, convert it or copy it "
     "several times. Tool sets in the Tool Chest can be saved as a file "
     "for the whole team."),
    (lambda w: getattr(w, "chip_scale", None), "Scale",
     "The scale of the sheet you're on. Takeoff tools measure in real feet "
     "once a scale is set: use Set Scale, a preset from the ribbon, or "
     "<b>Auto Scale</b> to read it off every sheet."),
    (lambda w: getattr(w, "chip_autosave", None), "AutoSave",
     "Your work is saved every couple of minutes. Click here to change how "
     "often, turn it off, or see earlier versions. If QuantiSheet ever "
     "closes unexpectedly, the next start offers to recover your work."),
    (lambda w: _tab_of(w, "AI"), "AI tools",
     "AI Takeoff reads a whole set; what it finds is dashed with an "
     "<b>AI</b> badge and stays out of the totals until you accept it - in "
     "the Review Queue, or by selecting it and pressing <b>A</b> (accept) "
     "or <b>D</b> (deny). Draw <b>zones</b> to say where it works, and it "
     "remembers the names you give its items. AI Redline checks drawings "
     "and Generate Set turns a brief into a starter set. It all runs on "
     "your own computer - drawings never leave it."),
    (lambda w: _tab_of(w, "Home"), "Copy text, report a problem",
     "<b>Home &gt; Select Text</b> (I) copies words off a drawing - box a "
     "schedule and press <b>Ctrl+Shift+C</b> to paste it into Excel. If "
     "something goes wrong, <b>Help &gt; Report an Issue</b> emails support "
     "with a screenshot. Deliveries? <b>Tools &gt; Package Tracker</b>."),
    (lambda w: _tab_of(w, "Help"), "Where to learn more",
     "<b>Help Center &amp; Tutorials</b> (F1) has step-by-step lessons for "
     "every job, with <b>Show Me</b> buttons that open the right tool, a "
     "shortcut list, and <b>Practice Drawings</b> you can mark up freely. "
     "That's the tour - enjoy QuantiSheet!"),
]


def _dock(w, name):
    d = getattr(w, name, None)
    return d if isinstance(d, QDockWidget) and d.isVisible() else None


def _tab_of(w, label):
    rib = getattr(w, "ribbon", None)
    if rib is None:
        return None
    for b in rib.findChildren(QWidget, "RibbonTab"):
        txt = getattr(b, "text", lambda: "")()
        if txt.replace("&", "").strip().lower() == label.lower():
            return b
    return rib


class Tour(QWidget):
    """The dimmed overlay and its callout, on top of the main window."""

    def __init__(self, mw):
        super().__init__(mw)
        self.mw = mw
        self.i = 0
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.StrongFocus)
        self.card = QWidget(self)
        self.card.setObjectName("TourCard")
        self.card.setStyleSheet(
            "QWidget#TourCard{background:#ffffff;border:1px solid #2f6fdf;"
            "border-radius:8px;} QLabel{color:#1d2433;background:transparent;}"
            " QLabel#TourStep{color:#6b7280;}")
        lay = QVBoxLayout(self.card)
        lay.setContentsMargins(16, 14, 16, 12)
        self.step = QLabel()
        self.step.setObjectName("TourStep")
        self.title = QLabel()
        self.title.setStyleSheet("font-size:15px;font-weight:600;")
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setTextFormat(Qt.RichText)
        row = QHBoxLayout()
        self.skip = QPushButton("End tour")
        self.back = QPushButton("Back")
        self.next = QPushButton("Next")
        self.next.setDefault(True)
        self.skip.clicked.connect(self.finish)
        self.back.clicked.connect(lambda: self.go(self.i - 1))
        self.next.clicked.connect(lambda: self.go(self.i + 1))
        row.addWidget(self.skip)
        row.addStretch(1)
        row.addWidget(self.back)
        row.addWidget(self.next)
        for wdg in (self.step, self.title, self.text):
            lay.addWidget(wdg)
        lay.addLayout(row)
        self.card.setFixedWidth(380)
        mw.installEventFilter(self)
        self.target = QRect()

    # --- moving through the stops ----------------------------------------
    def start(self):
        self.setGeometry(self.mw.rect())
        self.show()
        self.raise_()
        self.go(0)
        self.setFocus()
        return self

    def go(self, i):
        if i >= len(STOPS):
            self.finish()
            return
        self.i = max(0, i)
        find, title, text = STOPS[self.i]
        try:
            w = find(self.mw)
        except Exception:                                 # noqa: BLE001
            w = None
        if w is not None and w.isVisible() and w.width() > 0:
            tl = w.mapTo(self.mw, QPoint(0, 0))
            self.target = QRect(tl, w.size()).adjusted(-4, -4, 4, 4)
        else:
            self.target = QRect()
        self.step.setText(f"Tour · {self.i + 1} of {len(STOPS)}")
        self.title.setText(title)
        self.text.setText(text)
        self.back.setEnabled(self.i > 0)
        self.next.setText("Finish" if self.i == len(STOPS) - 1 else "Next")
        self.card.adjustSize()
        self._place()
        self.update()

    def _place(self):
        r, c = self.rect(), self.card
        cw, ch = c.width(), c.sizeHint().height()
        t = self.target
        if t.isNull():
            x, y = (r.width() - cw) // 2, (r.height() - ch) // 2
        else:
            # beside the target where there is room: below, right, left,
            # then above
            if t.bottom() + 12 + ch < r.height():
                x, y = t.left(), t.bottom() + 12
            elif t.right() + 12 + cw < r.width():
                x, y = t.right() + 12, t.top()
            elif t.left() - 12 - cw > 0:
                x, y = t.left() - 12 - cw, t.top()
            else:
                x, y = t.left(), t.top() - 12 - ch
        x = max(8, min(r.width() - cw - 8, x))
        y = max(8, min(r.height() - ch - 8, y))
        c.setGeometry(x, y, cw, ch)

    def finish(self):
        self.mw.removeEventFilter(self)
        self.hide()
        self.deleteLater()
        if getattr(self.mw, "_tour", None) is self:
            self.mw._tour = None

    # --- drawing and keys -------------------------------------------------
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        shade = QPainterPath()
        shade.addRect(self.rect())
        if not self.target.isNull():
            hole = QPainterPath()
            hole.addRoundedRect(self.target, 6, 6)
            shade = shade.subtracted(hole)
        p.fillPath(shade, QColor(0, 0, 0, 120))
        if not self.target.isNull():
            p.setPen(QPen(QColor(47, 111, 223), 3))
            p.drawRoundedRect(self.target, 6, 6)

    def keyPressEvent(self, ev):
        k = ev.key()
        if k == Qt.Key_Escape:
            self.finish()
        elif k in (Qt.Key_Right, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.go(self.i + 1)
        elif k == Qt.Key_Left:
            self.go(self.i - 1)
        else:
            super().keyPressEvent(ev)

    def mousePressEvent(self, ev):
        ev.accept()                    # the window stays still underneath

    def eventFilter(self, obj, ev):
        if obj is self.mw and ev.type() == QEvent.Resize:
            self.setGeometry(self.mw.rect())
            self.go(self.i)
        return QObject.eventFilter(self, obj, ev)


def start(mw):
    """Help > Welcome Tour."""
    old = getattr(mw, "_tour", None)
    if old is not None:
        try:
            old.finish()
        except RuntimeError:
            pass
    mw._tour = Tour(mw).start()
    return mw._tour
