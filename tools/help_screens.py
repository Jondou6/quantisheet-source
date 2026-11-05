import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
from app import settings, theme
TMP = tempfile.mkdtemp()
settings.DIR = os.path.join(TMP, "cfg"); settings.PATH = os.path.join(settings.DIR, "s.json"); settings._cache = None
QDialog.exec = lambda self, *a: 0
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Discard)
out = os.path.join(ROOT, ".run", "helpshots"); os.makedirs(out, exist_ok=True)
app = QApplication(sys.argv[:1]); theme.apply(app, "light")
from app.main_window import MainWindow
win = MainWindow(); win.resize(1500, 950); win.show(); app.processEvents()
def grab(w, n):
    app.processEvents(); w.grab().save(os.path.join(out, n + ".png"))
grab(win, "start")
win.ribbon.show_page("Help"); grab(win, "ribbon-help")
dlg = win.help_center("trades"); dlg.resize(1000, 700); grab(dlg, "help-center")
a = win.about(show=False); a.show(); grab(a, "about"); a.show_page("Terms of Service"); grab(a, "terms")
print("ok"); sys.stdout.flush(); os._exit(0)
