"""The page bar floating over the bottom of the drawing, as in Acrobat:
first, previous, the page number (type one and press Enter), next, last;
zoom out, the zoom, zoom in; fit width and fit page."""
from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (QFrame, QGraphicsOpacityEffect, QHBoxLayout,
                               QLabel, QLineEdit, QToolButton)

from . import icons, theme


class PageNav(QFrame):
    MARGIN = 24

    def __init__(self, win, host):
        super().__init__(host)
        self.win = win
        self.host = host
        self.setObjectName("PageNav")
        self.setAttribute(Qt.WA_StyledBackground, True)
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 4, 8, 4)
        h.setSpacing(2)

        def btn(text, tip, fn, icon=None):
            b = QToolButton()
            b.setObjectName("PageNavButton")
            b.setAutoRaise(True)
            if icon and icons.has(icon):
                b.setIcon(icons.icon(icon))
                b.setIconSize(QSize(18, 18))
            else:
                b.setText(text)
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.NoFocus)
            b.setAutoRepeat(fn in (self.prev, self.next))
            b.clicked.connect(fn)
            h.addWidget(b)
            return b
        self.first_b = btn("⏮", "First page (Ctrl+Home)", self.first)
        self.prev_b = btn("▲", "Previous page (Page Up)", self.prev)
        self.page_box = QLineEdit()
        self.page_box.setObjectName("PageNavBox")
        self.page_box.setFixedWidth(44)
        self.page_box.setAlignment(Qt.AlignCenter)
        self.page_box.setValidator(QIntValidator(1, 99999))
        self.page_box.returnPressed.connect(self._typed)
        h.addWidget(self.page_box)
        self.count = QLabel("/ 1")
        self.count.setObjectName("PageNavText")
        h.addWidget(self.count)
        self.next_b = btn("▼", "Next page (Page Down)", self.next)
        self.last_b = btn("⏭", "Last page (Ctrl+End)", self.last)
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setObjectName("PageNavSep")
        h.addSpacing(6)
        h.addWidget(sep)
        h.addSpacing(6)
        btn("−", "Zoom out (Ctrl+-)", lambda: win._zoom(0.8), "zoom_out")
        self.zoom_lbl = QLabel("100%")
        self.zoom_lbl.setObjectName("PageNavText")
        self.zoom_lbl.setFixedWidth(46)
        self.zoom_lbl.setAlignment(Qt.AlignCenter)
        h.addWidget(self.zoom_lbl)
        btn("+", "Zoom in (Ctrl++)", lambda: win._zoom(1.25), "zoom")
        btn("↔", "Fit width (Ctrl+2)", win.fit_width, "fit_width")
        btn("▭", "Fit page (Ctrl+0)", win.fit_page, "fit_page")
        self.fx = QGraphicsOpacityEffect(self)
        self.fx.setOpacity(0.94)
        self.setGraphicsEffect(self.fx)
        self.restyle()
        theme.hub.changed.connect(self.restyle)
        host.installEventFilter(self)
        self.hide()

    def restyle(self, *_):
        t = theme.tokens()
        self.setStyleSheet(
            f"#PageNav{{background:{t['raised']};border:1px solid "
            f"{t['border2']};border-radius:10px}}"
            f"#PageNavButton{{border:none;padding:4px 6px;color:{t['text']};"
            f"font-size:13px;border-radius:6px}}"
            f"#PageNavButton:hover{{background:{t['border']}}}"
            f"#PageNavButton:disabled{{color:{t['faint']}}}"
            f"#PageNavText{{color:{t['muted']}}}"
            f"#PageNavBox{{background:{t['surface']};color:{t['text']};"
            f"border:1px solid {t['border2']};border-radius:5px;"
            "padding:2px}"
            f"#PageNavSep{{color:{t['border2']}}}")

    # ------------------------------------------------------------ moves
    @property
    def view(self):
        return self.win._view

    def go(self, n):
        v = self.view
        if v is None or v.doc.page_count == 0:
            return
        n = max(0, min(v.doc.page_count - 1, n))
        down = n > v.page
        if n != v.page:
            v.go_to(n)
        bar = self.win._scroll.verticalScrollBar() if self.win._scroll \
            else None
        if bar is not None:
            bar.setValue(bar.minimum() if down or n == 0 else bar.minimum())
        self.sync()

    def first(self):
        self.go(0)

    def prev(self):
        if self.view:
            self.go(self.view.page - 1)

    def next(self):
        if self.view:
            self.go(self.view.page + 1)

    def last(self):
        if self.view:
            self.go(self.view.doc.page_count - 1)

    def _typed(self):
        try:
            self.go(int(self.page_box.text()) - 1)
        except ValueError:
            self.sync()
        if self.view:
            self.view.setFocus()

    # ------------------------------------------------------------ state
    def sync(self):
        v = self.view
        if v is None or v.doc.page_count == 0:
            self.hide()
            return
        n = v.doc.page_count
        if not self.page_box.hasFocus():
            self.page_box.setText(str(v.page + 1))
        self.count.setText(f"/ {n}")
        self.zoom_lbl.setText(f"{v.zoom * 100:.0f}%")
        for b, on in ((self.first_b, v.page > 0), (self.prev_b, v.page > 0),
                      (self.next_b, v.page < n - 1),
                      (self.last_b, v.page < n - 1)):
            b.setEnabled(on)
        self.show()
        self.place()

    def reserve(self):
        """Height of drawing the bar covers at the bottom (0 when hidden),
        for Fit Page to keep the whole sheet above it."""
        if not self.isVisible():
            return 0
        return self.height() + self.MARGIN

    def place(self):
        self.adjustSize()
        r = self.host.rect()
        x = (r.width() - self.width()) // 2
        y = r.height() - self.height() - self.MARGIN
        self.move(max(0, x), max(0, y))
        self.raise_()

    def eventFilter(self, obj, e):
        if obj is self.host and e.type() == QEvent.Resize:
            self.place()
        return False
