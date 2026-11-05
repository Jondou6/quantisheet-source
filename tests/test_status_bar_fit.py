"""On a narrow window the zoom buttons stay on screen in the bottom bar."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from test_gui import win, qapp                                # noqa: E402,F401


def test_zoom_buttons_stay_visible_when_narrow(win, qapp):
    from PySide6.QtWidgets import QToolButton
    sb = win.statusBar()
    # crowd the bar like a real job: job data, unpriced, keys, measuring
    win.chip_job.setText("$ Job data")
    win.chip_job.setVisible(True)
    win.measure_bar.setVisible(True)
    win.chip_snap.setVisible(True)
    win.resize(760, 600)
    win.show()
    for _ in range(5):
        qapp.processEvents()
    zoom = [w for w in win._chip_widgets if isinstance(w, QToolButton)]
    assert zoom and all(w.isVisible() for w in zoom)
    for w in zoom + [win.chip_zoom]:
        right = w.mapTo(sb, w.rect().topRight()).x()
        assert right <= sb.width(), (w.toolTip(), right, sb.width())
        assert w.width() >= 12
    win.measure_bar.setVisible(False)
    win.chip_snap.setVisible(False)
