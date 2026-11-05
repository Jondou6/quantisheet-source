"""Help > Welcome Tour is a guided walk around the window; the Help
Center's tutorials are step-by-step lessons - they are different (Jon,
Oct 19)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import helpcenter, tour                               # noqa: E402
from test_gui import win, qapp                                 # noqa: E402,F401


def test_welcome_tour_walks_the_window(qapp, win):
    win.show()
    t = win.welcome_tour()
    assert t.isVisible() and t.i == 0
    outlined = 0
    for i in range(len(tour.STOPS)):
        t.go(i)
        qapp.processEvents()
        assert t.step.text() == f"Tour · {i + 1} of {len(tour.STOPS)}"
        assert t.title.text() and t.text.text()
        assert win.rect().contains(t.card.geometry())
        outlined += not t.target.isNull()
    assert outlined >= len(tour.STOPS) // 2     # points at real parts
    t.go(len(tour.STOPS))                       # Finish
    qapp.processEvents()
    assert getattr(win, "_tour", None) is None


def test_tutorials_are_not_the_tour(qapp, win):
    ids = [t["id"] for t in helpcenter.T]
    assert len(ids) == len(set(ids)) and len(ids) >= 30
    assert "tour" not in ids and ids[0] == "first"
    tour_titles = {s[1] for s in tour.STOPS}
    assert not tour_titles & {t["title"] for t in helpcenter.T}
    for t in helpcenter.T:
        assert len(t["steps"]) >= 3 and t["tips"], t["id"]
    dlg = win.help_center(show=False)
    assert dlg.open_tutorial("aerial") and dlg.open_tutorial("bigsets")
