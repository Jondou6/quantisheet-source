"""Diagnostic only: widths inside the ribbon header."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from test_gui import win, qapp                     # noqa: E402,F401


def test_diag(win):
    from PySide6.QtWidgets import QWidget
    rb = win.ribbon if hasattr(win, "ribbon") else None
    head = win._ribbon_bar.findChild(QWidget, "RibbonHeader")
    print("\nhead min", head.minimumSizeHint().width(), "font",
          head.font().pointSizeF(), head.font().family())
    for w in head.findChildren(QWidget):
        print(type(w).__name__, w.objectName(), repr(getattr(w, "text",
              lambda: "")()), w.minimumSizeHint().width(),
              w.sizeHint().width(), w.minimumWidth(), w.isVisibleTo(head))
