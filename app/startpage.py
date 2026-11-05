"""The start page shown when no document is open.

Stage 3 (Oct 19): same content, restyled - cards with an icon tile, a bold
title and a quiet subtitle; recent files with the name first and the
folder after it in grey.
"""
import os

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QPushButton,
                               QScrollArea,
                               QSizePolicy,
                               QStyle, QStyledItemDelegate, QToolButton,
                               QVBoxLayout, QWidget)

from . import icons, settings, theme


RECENT_SHOWN = 5          # recent files on the start page (Jon, Oct 18)
CARD_HEIGHT = 72
ROW_HEIGHT = 40


class StartCard(QToolButton):
    """A quick-start card: icon tile, bold title, grey subtitle. The labels
    let clicks through, so the whole card is one button."""

    def __init__(self, label, subtitle, icon, parent=None):
        super().__init__(parent)
        self.setObjectName("StartCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName(f"{label}: {subtitle}")
        self.setToolTip(f"{label}: {subtitle}")
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 10, 14, 10)
        row.setSpacing(12)
        tile = QLabel()
        tile.setObjectName("StartCardIcon")
        tile.setFixedSize(40, 40)
        tile.setAlignment(Qt.AlignCenter)
        tile.setPixmap(icons.icon(icon).pixmap(22, 22))
        self.tile = tile
        self._icon = icon
        text = QVBoxLayout()
        text.setSpacing(1)
        self.title = QLabel(label)
        self.title.setObjectName("StartCardTitle")
        self.sub = QLabel(subtitle)
        self.sub.setObjectName("StartCardSub")
        self.sub.setMinimumWidth(10)        # long subtitles elide, not grow
        self._sub_full = subtitle
        text.addStretch(1)
        text.addWidget(self.title)
        text.addWidget(self.sub)
        text.addStretch(1)
        row.addWidget(tile)
        row.addLayout(text, 1)
        for w in (tile, self.title, self.sub):
            w.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        theme.hub.changed.connect(self._retint)

    def fit(self):
        """Tall enough for both lines at the size Windows actually draws
        them (Jon, Oct 30: with larger text the bottoms of g, p and y were
        cut off). Every card has the same fonts, so the same height."""
        for lab in (self.title, self.sub):
            lab.ensurePolished()
            lab.setMinimumHeight(lab.fontMetrics().height() + 2)
        m = self.layout().contentsMargins()
        text = self.title.minimumHeight() + 1 + self.sub.minimumHeight()
        need = m.top() + m.bottom() + max(text, self.tile.height()) + 4
        self.setFixedHeight(max(CARD_HEIGHT, need))
        return self.height()

    def showEvent(self, e):
        self.fit()                   # the style sheet's fonts are in now
        super().showEvent(e)

    def changeEvent(self, e):
        super().changeEvent(e)
        from PySide6.QtCore import QEvent
        if e.type() in (QEvent.FontChange, QEvent.StyleChange):
            self.fit()

    def text(self):                          # what the old cards returned
        return f"{self.title.text()}\n{self._sub_full}"

    def _retint(self, *_):
        try:
            self.tile.setPixmap(icons.icon(self._icon).pixmap(22, 22))
        except RuntimeError:                 # card already deleted
            pass

    def resizeEvent(self, e):
        super().resizeEvent(e)
        room = max(10, self.width() - 14 - 40 - 12 - 14)
        fm = QFontMetrics(self.sub.font())
        self.sub.setText(fm.elidedText(self._sub_full, Qt.ElideRight, room))


class RecentDelegate(QStyledItemDelegate):
    """File name in the text colour, its folder after it in grey."""

    def sizeHint(self, option, index):
        s = super().sizeHint(option, index)
        return QSize(s.width(), ROW_HEIGHT)

    def paint(self, p, option, index):
        path = index.data(Qt.UserRole)
        if not path:
            return super().paint(p, option, index)
        p.save()
        r = option.rect.adjusted(4, 2, -4, -2)
        if option.state & QStyle.State_MouseOver:
            p.setPen(Qt.NoPen)
            p.setBrush(theme.color("surface2"))
            p.drawRoundedRect(r, 8, 8)
        icon = index.data(Qt.DecorationRole)
        x = r.left() + 10
        if icon is not None:
            icon.paint(p, QRect(x, r.center().y() - 9, 18, 18))
            x += 30
        name = os.path.basename(path)
        folder = os.path.dirname(path)
        f = QFont(option.font)
        f.setWeight(QFont.DemiBold)
        fm = QFontMetrics(f)
        room = r.right() - 10 - x
        name_txt = fm.elidedText(name, Qt.ElideMiddle, int(room * 0.6))
        p.setFont(f)
        p.setPen(theme.color("text"))
        nr = QRect(x, r.top(), fm.horizontalAdvance(name_txt) + 2, r.height())
        p.drawText(nr, Qt.AlignVCenter | Qt.AlignLeft, name_txt)
        f2 = QFont(option.font)
        fm2 = QFontMetrics(f2)
        x2 = nr.right() + 14
        folder_txt = fm2.elidedText(folder, Qt.ElideMiddle,
                                    max(0, r.right() - 10 - x2))
        p.setFont(f2)
        p.setPen(theme.color("faint" if theme.is_dark() else "muted"))
        p.drawText(QRect(x2, r.top(), r.right() - 10 - x2, r.height()),
                   Qt.AlignVCenter | Qt.AlignLeft, folder_txt)
        p.restore()


class StartPage(QWidget):
    open_path = Signal(str)

    def __init__(self, actions, parent=None):
        """actions: [(label, subtitle, icon, QAction)]"""
        super().__init__(parent)
        self.setObjectName("StartPage")
        self.setAttribute(Qt.WA_StyledBackground, True)
        # the page scrolls inside the window instead of making the window
        # taller than the screen (Stage 3 cards are taller)
        wrap = QVBoxLayout(self)
        wrap.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setObjectName("StartScroll")
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName("StartBody")
        body.setAttribute(Qt.WA_StyledBackground, True)
        scroll.setWidget(body)
        wrap.addWidget(scroll)
        self.scroll = scroll
        outer = QHBoxLayout(body)
        outer.addStretch(1)
        col = QVBoxLayout()
        col.setSpacing(10)
        col.addStretch(1)
        title = QLabel("QuantiSheet")
        title.setObjectName("StartTitle")
        sub = QLabel("Drawings, takeoff, estimating and project control "
                     "in one place.")
        sub.setObjectName("StartSub")
        col.addWidget(title)
        col.addWidget(sub)
        self._heads = (title, sub)
        # a newer team build waiting (Nov 2, updatecheck_ui): one line
        self.update_line = QPushButton()
        self.update_line.setObjectName("StartUpdate")
        self.update_line.setCursor(Qt.PointingHandCursor)
        self.update_line.setFlat(True)
        self.update_line.setStyleSheet(
            "QPushButton#StartUpdate{text-align:left;padding:6px 10px;"
            "border:1px solid #2f6fdf;border-radius:6px;color:#2f6fdf;}")
        self.update_line.setVisible(False)
        self._update_click = None
        self.update_line.clicked.connect(self._update_clicked)
        col.addWidget(self.update_line)
        col.addSpacing(12)
        col.addWidget(self._section("Get started"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        self.cards = []
        for i, (label, subtitle, icon, action) in enumerate(actions):
            b = StartCard(label, subtitle, icon)
            # every card the same size, whatever its text (Jon, Oct 18)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.setMinimumWidth(300)
            b.fit()                   # at least CARD_HEIGHT, more for big text
            b.clicked.connect(action.trigger)
            grid.addWidget(b, i // 2, i % 2)
            self.cards.append(b)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        col.addLayout(grid)
        col.addSpacing(14)
        col.addWidget(self._section("Recent files"))
        self.recent = QListWidget()
        self.recent.setObjectName("StartRecent")
        self.recent.setItemDelegate(RecentDelegate(self.recent))
        self.recent.setMouseTracking(True)
        self.recent.setCursor(Qt.PointingHandCursor)
        self.recent.setIconSize(QSize(18, 18))
        self.recent.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.recent.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # a click opens it; Enter too. A double-click sends both signals
        # (and a second click), so the same file within a second is ignored
        self._last_open = (None, 0.0)
        self.recent.itemActivated.connect(self._open_item)
        self.recent.itemClicked.connect(self._open_item)
        col.addWidget(self.recent)
        col.addSpacing(6)
        tip = QLabel("Tip: press <b>Ctrl+K</b> and type to find any command. "
                     "New here? Press <b>F1</b> for tutorials.")
        tip.setObjectName("StartTip")
        tip.setWordWrap(True)          # large text: wrap, never cut
        col.addWidget(tip)
        col.addStretch(2)
        w = QWidget()
        w.setLayout(col)
        w.setMaximumWidth(780)
        outer.addWidget(w, 3)
        outer.addStretch(1)
        self.refresh()

    def showEvent(self, e):
        # the big title and the line under it: never shorter than their
        # text (Jon, Oct 30: the top of "QuantiSheet" was cut off)
        for lab in self._heads:
            lab.ensurePolished()
            lab.setMinimumHeight(lab.fontMetrics().height() + 4)
        super().showEvent(e)

    def set_update(self, text, on_click=None):
        """Show the 'update available' line (text), or hide it (None)."""
        self._update_click = on_click
        self.update_line.setText(text or "")
        self.update_line.setVisible(bool(text))

    def _update_clicked(self):
        if self._update_click:
            self._update_click()

    @staticmethod
    def _section(text):
        lab = QLabel(text.upper())
        lab.setObjectName("StartSection")
        return lab

    def _open_item(self, it):
        import time
        path = it.data(Qt.UserRole)
        if not path:
            return False
        last, when = self._last_open
        now = time.monotonic()
        if path == last and now - when < 1.0:
            return False
        self._last_open = (path, now)
        self.open_path.emit(path)
        return True

    def refresh(self):
        self.recent.clear()
        items = settings.recent(RECENT_SHOWN)
        for p in items:
            it = QListWidgetItem(icons.icon("open"), f"{os.path.basename(p)}"
                                 f"    —    {os.path.dirname(p)}")
            it.setData(Qt.UserRole, p)
            it.setToolTip(p)
            self.recent.addItem(it)
        if not items:
            it = QListWidgetItem("Files you open will appear here.")
            it.setFlags(Qt.NoItemFlags)
            self.recent.addItem(it)
        # tall enough for every row shown - no scroll bar, no empty space
        rows = max(1, self.recent.count())
        f = self.recent.frameWidth() * 2
        self.recent.setFixedHeight(rows * ROW_HEIGHT + f + 12)
