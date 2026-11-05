"""Diagnostic only: which widget in the ribbon toolbar asks for width."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from test_gui import win, qapp                     # noqa: E402,F401


def test_diag(win):
    from PySide6.QtWidgets import QWidget
    bar = win._ribbon_bar
    print("\nbar min", bar.minimumSizeHint().width(), "hint",
          bar.sizeHint().width())
    rows = []
    for w in bar.findChildren(QWidget):
        try:
            m = w.minimumSizeHint().width()
            mn = w.minimumWidth()
        except Exception:
            continue
        if max(m, mn) > 400:
            rows.append((max(m, mn), m, mn, type(w).__name__, w.objectName(),
                         w.parent().objectName() if w.parent() else ""))
    for r in sorted(rows, reverse=True)[:25]:
        print(r)
