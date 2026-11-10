"""Every window can be closed with the mouse (Chief's user tests, Nov 6-7:
about 40 windows had only the title bar's X, or Esc).

- ensure(dialog): add a Close button row at the bottom of a dialog that
  has no Close / Cancel / OK / Done style button of its own. Message
  boxes, progress boxes, file pickers and pop-ups are left alone.
- dialog_fit's show hook (installed once in main.py) runs ensure() on
  each dialog the first time it shows.
"""
import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractButton, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QGridLayout,
                               QHBoxLayout, QBoxLayout, QInputDialog,
                               QMessageBox, QProgressDialog, QPushButton)

log = logging.getLogger(__name__)

WORDS = ("close", "cancel", "ok", "done", "finish", "exit", "dismiss",
         "hide")
_DONE = "qs_close_checked"


def _clean(text):
    return text.replace("&", "").replace("…", "").strip().lower()


def has_close(w):
    """A button whose word closes the window (Close, Cancel, OK...)."""
    if w.findChild(QDialogButtonBox) is not None:
        return True
    for b in w.findChildren(QAbstractButton):
        t = _clean(b.text())
        if t and any(t == x or t.startswith(x + " ") or t.endswith(" " + x)
                     for x in WORDS):
            return True
    return False


def ensure(w):
    """Add a Close button to `w` when it needs one. Returns the button
    added, or None."""
    try:
        if w is None or not isinstance(w, QDialog) or w.property(_DONE):
            return None
        w.setProperty(_DONE, True)
        if isinstance(w, (QMessageBox, QProgressDialog, QFileDialog,
                          QInputDialog)):
            return None
        flags = w.windowFlags()
        if flags & Qt.Popup == Qt.Popup or \
                flags & Qt.FramelessWindowHint or \
                w.property("qs_no_close_button"):
            return None
        if has_close(w):
            return None
        lay = w.layout()
        if lay is None:
            return None
        b = QPushButton("Close")
        b.setObjectName("qs_close_button")
        b.setAutoDefault(False)
        b.setDefault(False)
        b.clicked.connect(w.reject)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(b)
        if isinstance(lay, QBoxLayout):
            lay.addLayout(row)
        elif isinstance(lay, QFormLayout):
            lay.addRow(row)
        elif isinstance(lay, QGridLayout):
            lay.addLayout(row, lay.rowCount(), 0, 1,
                          max(1, lay.columnCount()))
        else:
            return None
        return b
    except Exception:                                     # noqa: BLE001
        log.debug("close button not added", exc_info=True)
        return None

