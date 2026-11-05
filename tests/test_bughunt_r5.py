"""Grok's bug hunt round 5 (Oct 18): each fix with its acceptance check."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz                                                   # noqa: E402
import pytest                                                 # noqa: E402

from test_gui import win, qapp                                # noqa: E402,F401


ZERO_PAGES = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
              b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\n"
              b"trailer<</Root 1 0 R>>\n%%EOF\n")


def _warnings(monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(
        lambda *a, **k: shown.append(a[2] if len(a) > 2 else "") or 0))
    return shown


def test_zero_page_pdf_says_so(win, tmp_path, monkeypatch):
    """#1: a PDF with no pages gets a message, never silence."""
    p = tmp_path / "zero.pdf"
    p.write_bytes(ZERO_PAGES)
    shown = _warnings(monkeypatch)
    n = win.tabs.count()
    assert win.open_path(str(p)) is False
    assert win.tabs.count() == n and shown and "no pages" in shown[-1]


def test_damaged_pdf_that_fails_in_the_viewer_says_so(win, tmp_path,
                                                      monkeypatch):
    """#1: anything failing while the drawing view is built ("cannot save",
    "invalid key in dict"...) is reported and the file closed."""
    from app import main_window
    p = tmp_path / "bad.pdf"
    d = fitz.open()
    d.new_page()
    d.save(str(p))

    def boom(*a, **k):
        raise RuntimeError("invalid key in dict")
    monkeypatch.setattr(main_window, "PdfView", boom)
    shown = _warnings(monkeypatch)
    n = win.tabs.count()
    assert win.open_path(str(p)) is False
    assert win.tabs.count() == n
    assert shown and "damaged" in shown[-1] and "invalid key" in shown[-1]


def test_far_off_coordinate_cannot_blow_up_snapping():
    """#3: a line out to x = 1e9 is clipped to the page."""
    import time
    from app import snap
    t = time.perf_counter()
    idx = snap.SnapIndex([((0, 0), (1e9, 5)), ((10, 10), (100, 10))],
                         clip=(-612, -792, 1224, 1584))
    assert time.perf_counter() - t < 0.5
    assert len(idx.grid) < 500
    assert snap.clip_segment((0, 0), (100, 0), (200, -1, 300, 1)) is None
    a, b = snap.clip_segment((0, 0), (100, 0), (10, -1, 50, 1))
    assert a == (10.0, 0.0) and b == (50.0, 0.0)
    nan = snap.SnapIndex([((0, 0), (float("nan"), 5))], clip=(0, 0, 9, 9))
    assert nan.segs == []


def test_closing_a_tab_stops_its_timers(win):
    """#5: no prefetch or tile render runs on a closed document."""
    from PySide6.QtCore import QTimer
    v = win._view
    v._pf_timer.start(10)
    v._tile_timer.start(10)
    v._view_dirty = False
    v.dirty = False
    win.close_tab(win.tabs.currentIndex())
    assert not any(t.isActive() for t in v.findChildren(QTimer))
    v._prefetch()                          # document closed: no error
    v._render_tiles()


def test_auto_takeoff_scale_too_small_is_shown(win, monkeypatch):
    """#6: AutoTakeoffError ("scale too small") is shown, not swallowed."""
    from PySide6.QtWidgets import QDialog, QMessageBox
    from app import autotakeoff, autotakeoff_review as ar

    class Pick:
        def __init__(self, *a):
            pass

        def exec(self):
            return QDialog.Accepted

        def choice(self):
            return (["rooms"], 9.0, 1)
    monkeypatch.setattr(ar, "PickDialog", Pick)

    def collect(*a, **k):
        raise autotakeoff.AutoTakeoffError(
            "This sheet's scale is too small for auto takeoff.")
    monkeypatch.setattr(ar, "collect", collect)
    shown = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(
        lambda *a, **k: shown.append(a[2]) or 0))
    assert ar.run_dialog(win) == 0
    assert shown and "too small" in shown[-1]


def test_redline_ignores_tiny_and_scattered_text():
    """#10: "8" struck 286 places; now short or scattered text is skipped,
    and scope-changing edits start unticked."""
    from app.ai import review
    d = fitz.open()
    for i in range(4):                       # PIPE on 4 pages: > 3, skipped
        p = d.new_page()
        p.insert_text((72, 72), "8 8 8 PIPE 8 IN. STEEL CASING")
        if i == 0:
            p.insert_text((72, 100), "UNIQUE PHRASE HERE")
        if i < 3:                            # 3 places: still allowed
            p.insert_text((72, 130), "SEE NOTE 4")
    marks = review.redline_marks(d, [{"old": "8", "new": "10"},
                                     {"old": "PIPE", "new": "DUCT"},
                                     {"old": "UNIQUE PHRASE", "new": "X"},
                                     {"old": "SEE NOTE 4", "new": "Y"}])
    notes = [m[2]["note"] for m in marks]
    assert not any("10" in n or "DUCT" in n for n in notes)
    assert notes.count("Replace with: X") == 1
    assert notes.count("Replace with: Y") == 3
    assert review.risky({"old": "BY OWNER", "new": "BY OTHERS"})
    assert not review.risky({"old": "PIPE", "new": "DUCT"})


def test_cut_off_ai_reply_is_reported():
    """#13: a reply cut off mid-string is an error, not "no suggestions"."""
    from app.ai import review
    with pytest.raises(review.AIError):
        review._items('{"edits": [{"old": "8" PIPE', "edits")
    assert review._items("", "edits") == []
    assert review._items('{"edits": []}', "edits") == []


def test_open_set_with_a_non_set_file_says_so(win, tmp_path, monkeypatch):
    """#11: opening a PDF as a set shows a message."""
    from PySide6.QtWidgets import QMessageBox
    from app import sets
    bad = tmp_path / "not_a_set.pdfset"
    bad.write_bytes(b"%PDF-1.4\n\xff\xfe binary")
    with pytest.raises(sets.SetError):
        sets.load(str(bad))
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(
        lambda *a, **k: shown.append(a[2]) or 0))
    assert win.sets.open_set(str(bad)) is None
    assert shown and "isn't a QuantiSheet set" in shown[-1]


def test_home_and_end_keys_go_to_first_and_last_page(win):
    """Small item: Home/End."""
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent
    v = win._view
    v.go_to(1)
    v.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_End, Qt.NoModifier))
    assert v.page == v.doc.page_count - 1
    v.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Home, Qt.NoModifier))
    assert v.page == 0


def test_esign_button_style_is_valid():
    from app import theme
    assert theme.color("accent").name().startswith("#")
