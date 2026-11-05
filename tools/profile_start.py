"""Where does start-up go? Times the imports and building the main window.

    python tools/profile_start.py [real]

"real" uses the real screen (not Qt's off-screen mode) and the theme, like
the program itself, and profiles only building the main window.
"""
import cProfile
import io
import os
import pstats
import sys
import tempfile
import time

T0 = time.perf_counter()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
REAL = "real" in sys.argv[1:]
if REAL:
    for k in [k for k in os.environ if k.startswith("QT_")]:
        del os.environ[k]
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")


def main():
    prof = cProfile.Profile()
    prof.enable()
    from app import settings
    if "mine" not in sys.argv[1:]:       # "mine": use your real settings
        tmp = tempfile.mkdtemp(prefix="quantisheet-start-")
        settings.DIR = os.path.join(tmp, "cfg")
        settings.PATH = os.path.join(settings.DIR, "s.json")
        settings._cache = {"author": "Probe"}
    t1 = time.perf_counter()
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from app import main_window
    if REAL:
        from app import theme
        theme.apply(app)
        prof.disable()
        prof = cProfile.Profile()
        prof.enable()
    t2 = time.perf_counter()
    w = main_window.MainWindow()
    w.resize(1600, 950)
    w.show()
    app.processEvents()
    t3 = time.perf_counter()
    prof.disable()
    print(f"python + settings     {t1 - T0:6.2f} s")
    print(f"imports (main_window) {t2 - t1:6.2f} s")
    print(f"build window + show   {t3 - t2:6.2f} s")
    print(f"TOTAL                 {t3 - T0:6.2f} s\n", flush=True)
    mods = sorted(((k, v) for k, v in sys.modules.items()
                   if k.startswith("app.")), key=lambda kv: kv[0])
    print(f"{len(mods)} app modules loaded at start-up", flush=True)
    buf = io.StringIO()
    st = pstats.Stats(prof, stream=buf)
    st.sort_stats("cumulative").print_stats(r"app[\\/]", 60)
    st.sort_stats("tottime").print_stats(20)
    print(buf.getvalue(), flush=True)
    w.close()
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
