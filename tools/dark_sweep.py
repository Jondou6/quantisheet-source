"""Dark-mode sweep (Jon, Oct 28: the black text-edit box). Runs the GUI
tests with the DARK theme and records every style sheet or label text
that Qt can't use because a Python object (a QColor...) was formatted
into it - Qt drops such a sheet silently, so the dark theme shows through
(black boxes, unreadable text). Made-up test data only; settings go to
pytest's temp folders as usual.

    python tools/dark_sweep.py [test files...]

Prints each bad sheet once with the code line that set it."""
import os
import sys
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

BAD = ("PySide6.", "<PySide6", "QColor(", "object at 0x")
FOUND = {}


def _where():
    for fr in reversed(traceback.extract_stack()[:-2]):
        f = fr.filename.replace("\\", "/")
        if "/app/" in f or "/quantisheet_" in f:
            return f"{f.split('/app/')[-1] if '/app/' in f else f}:" \
                   f"{fr.lineno}"
    return "?"


def _check(kind, text):
    t = str(text or "")
    if any(b in t for b in BAD):
        key = (_where(), kind)
        FOUND.setdefault(key, t[:200])


class Plugin:
    def pytest_sessionstart(self, session):
        from PySide6.QtWidgets import QApplication, QLabel, QWidget
        app = QApplication.instance() or QApplication([])
        orig_ss = QWidget.setStyleSheet
        orig_app_ss = QApplication.setStyleSheet
        orig_txt = QLabel.setText

        def ss(self, s):
            _check("style sheet", s)
            return orig_ss(self, s)

        def app_ss(self, s):
            _check("app style sheet", s)
            return orig_app_ss(self, s)

        def txt(self, s):
            _check("label text", s)
            return orig_txt(self, s)
        QWidget.setStyleSheet = ss
        QApplication.setStyleSheet = app_ss
        QLabel.setText = txt
        from app import theme
        self._apply = theme.apply

        def dark(app_=None, m=None, save=False):
            return self._apply(app_, "dark", False)
        theme.apply = dark
        dark(app)

    def pytest_sessionfinish(self, session, exitstatus):
        print("\n\n=== DARK SWEEP ===")
        if not FOUND:
            print("no bad style sheets or label texts")
        for (where, kind), text in sorted(FOUND.items()):
            print(f"{where}  [{kind}]\n    {text}")
        print(f"=== {len(FOUND)} place(s) ===")


if __name__ == "__main__":
    import pytest
    args = sys.argv[1:] or ["tests"]
    rc = pytest.main(["-q", "-p", "no:cacheprovider", "-x" if False else
                      "--maxfail=10000", *args], plugins=[Plugin()])
    sys.exit(0)
