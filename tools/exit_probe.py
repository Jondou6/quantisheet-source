"""Where does a test run crash at exit? (dev aid, Nov 5)

    python tools/exit_probe.py pytest-args...

Runs pytest in this process, then tears down step by step, printing each
step first, so the last line printed names the step that crashed."""
import gc
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def say(t):
    print("PROBE:", t, flush=True)


def main(argv):
    import pytest
    rc = pytest.main(argv)
    say(f"pytest returned {rc}")
    for i in range(3):
        say(f"gc pass {i}")
        n = gc.collect()
        say(f"gc pass {i} freed {n}")
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            tops = QApplication.topLevelWidgets()
            say(f"{len(tops)} top-level widgets left: " + ", ".join(
                sorted({type(w).__name__ for w in tops}))[:400])
            say("closing and deleting top-level widgets")
            for w in tops:
                w.close()
                w.deleteLater()
            from PySide6.QtCore import QCoreApplication, QEvent
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            say("processEvents")
            app.processEvents()
            from PySide6.QtGui import QGuiApplication
            cb = QGuiApplication.clipboard()
            say("clipboard formats: " + ",".join(
                cb.mimeData().formats() if cb.mimeData() else []))
    except Exception as e:                                # noqa: BLE001
        say(f"qt step error {e!r}")
    say("modules with fitz docs: checking")
    try:
        import fitz
        live = [o for o in gc.get_objects() if isinstance(o, (fitz.Document,
                                                              fitz.Page))]
        say(f"{len(live)} PyMuPDF Document/Page objects alive")
    except Exception as e:                                # noqa: BLE001
        say(f"fitz check error {e!r}")
    say("normal interpreter exit next")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
