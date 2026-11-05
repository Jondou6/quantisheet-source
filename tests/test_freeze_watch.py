"""The freeze recorder writes the stuck stack to crash.log."""
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication                    # noqa: E402

from app import freeze_watch                                   # noqa: E402


def test_a_freeze_is_written_down(tmp_path):
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "crash.log"
    f = open(path, "w", encoding="utf-8")
    w = freeze_watch.FreezeWatch(f, seconds=1)
    w.start()
    try:
        app.processEvents()

        def stuck_here():
            time.sleep(1.8)                # the window not answering
        stuck_here()
        deadline = time.monotonic() + 3
        while not w.freezes and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.05)
    finally:
        w.stop()
        f.close()
    text = path.read_text(encoding="utf-8")
    assert "Timeout" in text and "stuck_here" in text, text[:500]
    assert w.freezes and w.freezes[0][1] >= 1
    assert "window frozen" in text


def test_no_file_no_watch():
    app = QApplication.instance() or QApplication([])
    assert freeze_watch.install(app, None) is None
