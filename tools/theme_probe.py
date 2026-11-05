"""How long does switching the theme take, per layout?
    python tools/theme_probe.py"""
import cProfile
import io
import os
import pstats
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main():
    from app import settings
    tmp = tempfile.mkdtemp(prefix="quantisheet-theme-probe-")
    settings.DIR = os.path.join(tmp, "cfg")
    settings.PATH = os.path.join(settings.DIR, "s.json")
    settings._cache = {"author": "Probe"}
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from app import theme
    from app.main_window import MainWindow
    theme.apply(app, "light")
    w = MainWindow()
    w.resize(1400, 900)
    w.show()
    app.processEvents()
    for lay in ("ribbon", "modern"):
        w.layouts.set_layout(lay)
        app.processEvents()
        for m in ("dark", "light"):
            t = time.perf_counter()
            theme.apply(app, m)
            app.processEvents()
            print(f"{lay:7} -> {m:5} {time.perf_counter() - t:6.2f} s",
                  flush=True)
    w.layouts.dock.show()
    app.processEvents()
    t = time.perf_counter()
    theme.apply(app, "dark")
    app.processEvents()
    print(f"modern + All Tools open -> dark {time.perf_counter() - t:6.2f} s",
          flush=True)
    prof = cProfile.Profile()
    prof.enable()
    theme.apply(app, "light")
    app.processEvents()
    prof.disable()
    buf = io.StringIO()
    pstats.Stats(prof, stream=buf).sort_stats("cumulative").print_stats(25)
    print(buf.getvalue(), flush=True)
    os._exit(0)


if __name__ == "__main__":
    main()
