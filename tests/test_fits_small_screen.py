"""The window fits a short screen (a 65 in TV or a laptop with display
scaling): side panels scroll instead of pushing the bottom bar off."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from test_gui import win, qapp                                # noqa: E402,F401


def test_window_minimum_height_fits_a_scaled_screen(win, qapp):
    qapp.processEvents()
    need = win.minimumSizeHint().height()
    # 1080p at 150% leaves about 680 px below the taskbar
    assert need <= 640, need


def test_panels_are_still_the_same_objects(win):
    for d, w in ((win.props_dock, win.properties),
                 (win.chest_dock, win.chest)):
        inner = d.widget()
        assert inner is w or inner.widget() is w
