import cProfile, io, os, pstats, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
tmp = tempfile.mkdtemp()
from app import settings
settings.DIR = os.path.join(tmp, "cfg"); settings.PATH = os.path.join(settings.DIR, "s.json"); settings._cache = None
from PySide6.QtWidgets import QApplication, QMessageBox
app = QApplication(sys.argv[:1])
QMessageBox.information = staticmethod(lambda *a, **k: 0)
import perf
p = os.path.join(tmp, "job.pdf"); perf.make(p, 3)
from app.main_window import MainWindow
win = MainWindow(); win.resize(1500, 900); win.show(); win.open_path(p); app.processEvents()
import time
from app import autowalls
T = {}
def wrap(obj, name):
    f = getattr(obj, name)
    def g(*a, **k):
        t = time.perf_counter()
        try:
            return f(*a, **k)
        finally:
            T[name] = T.get(name, 0) + time.perf_counter() - t
    setattr(obj, name, g)
for n in ("walls", "doors", "raster_segments", "marks"):
    wrap(autowalls, n)
v = win._view
wrap(v, "apply_marks")
def run(label):
    T.clear()
    t = time.perf_counter()
    win.auto_walls(quiet=True)
    app.processEvents()
    print(label, round(time.perf_counter() - t, 2),
          {k: round(x, 2) for k, x in T.items()})
    sys.stdout.flush()
    win.undo()
run("plain")
v.set_tool("edit_text"); run("edit tool on"); v.set_tool(None)
win.auto_takeoff_rooms() if hasattr(win, "auto_takeoff_rooms") else None
run("after rooms")
win._rotate_pages([0], 90); run("rotated")
v.go_to(2); run("page 3")
os._exit(0)
