"""Screenshots of Trade Takeoff and Check Takeoff."""
import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
import fitz
from PySide6.QtWidgets import QApplication, QMessageBox, QDialog
from app import settings, theme, annotate
TMP = tempfile.mkdtemp()
settings.DIR = os.path.join(TMP, "cfg"); settings.PATH = os.path.join(settings.DIR, "s.json")
settings._cache = {"author": "Pat Morgan"}
QMessageBox.information = staticmethod(lambda *a, **k: 0)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Discard)
QDialog.exec = lambda self, *a: 0
import test_tradetakeoff as T
out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, ".run", "tradeshots")
os.makedirs(out, exist_ok=True)
app = QApplication(sys.argv[:1])
theme.apply(app, "light")
d = T.plumbing()
p = d[0]
T._line(p, (5, 40), (35, 40)); T._line(p, (5, 42), (35, 42)); T._text(p, (18, 41.3), "24x12")
T._line(p, (45, 10), (60, 10), width=1.5); T._text(p, (50, 9.4), "W12X26")
annotate.apply_op(d, annotate.new_op("set_scale", 0, ppu=T.PPU, unit="ft", name="1/4"))
path = os.path.join(TMP, "M-101 Plumbing.pdf"); d.save(path)
from app.main_window import MainWindow
win = MainWindow(); win.resize(1500, 950); win.show(); win.open_path(path); app.processEvents(); win.fit_page()
dlg = win.trade_takeoff(show=False); dlg.show(); dlg.pipe.find(); app.processEvents()
shots = []
def grab(w, n):
    app.processEvents(); f = os.path.join(out, n + ".png"); w.grab().save(f); shots.append(f)
grab(dlg, "trade-pipe")
dlg.tabs.setCurrentWidget(dlg.duct); dlg.duct.find(); grab(dlg, "trade-duct")
dlg.tabs.setCurrentWidget(dlg.steel); dlg.steel.find(); grab(dlg, "trade-steel")
dlg.pipe.add(); dlg.duct.add(); dlg.close()
grab(win, "after-trade")
chk = win.check_takeoff(show=False); chk.show(); app.processEvents(); grab(chk, "check-takeoff"); grab(win, "check-takeoff-window")
chk.close()
for i in range(win.tabs.count()):
    t = win.tabs.widget(i)
    if hasattr(t, "view"): t.view.dirty = False
print("\n".join(shots)); sys.stdout.flush(); os._exit(0)
