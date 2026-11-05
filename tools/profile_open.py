"""Where does opening a big set spend its time?

    python tools/profile_open.py PLANS.pdf
"""
import cProfile
import os
import pstats
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from app import settings                                      # noqa: E402

TMP = tempfile.mkdtemp(prefix="quantisheet-prof-")
settings.DIR = os.path.join(TMP, "cfg")
settings.PATH = os.path.join(settings.DIR, "s.json")
settings._cache = {"author": "Probe"}


def main(argv):
    path = argv[0].strip('"')
    from PySide6.QtWidgets import QApplication, QMessageBox
    app = QApplication.instance() or QApplication([])
    for n in ("information", "warning", "critical"):
        setattr(QMessageBox, n, staticmethod(lambda *a, **k: 0))
    from app.main_window import MainWindow
    w = MainWindow()
    w.resize(1600, 950)
    w.show()
    app.processEvents()
    prof = cProfile.Profile()
    prof.enable()
    w.open_path(path)
    for _ in range(5):
        app.processEvents()
    prof.disable()
    import io
    buf = io.StringIO()
    st = pstats.Stats(prof, stream=buf)
    st.sort_stats("cumulative").print_stats(35)
    st.sort_stats("tottime").print_stats(15)
    print(buf.getvalue(), flush=True)
    sys.stdout.flush()
    w._view.dirty = False
    os._exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
