import os, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox
from app import settings, theme, practice
TMP = tempfile.mkdtemp()
settings.DIR = os.path.join(TMP, "cfg"); settings.PATH = os.path.join(settings.DIR, "s.json"); settings._cache = None
QDialog.exec = lambda self, *a: 0
QMessageBox.information = staticmethod(lambda *a, **k: 0)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Discard)
out = os.path.join(ROOT, ".run", "navshots"); os.makedirs(out, exist_ok=True)
app = QApplication(sys.argv[:1])
from app.main_window import MainWindow
for mode in ("light", "dark"):
    theme.apply(app, mode)
    win = MainWindow(); win.resize(1500, 950); win.show()
    win.open_path(practice.make(os.path.join(TMP, f"p-{mode}.pdf"))); app.processEvents(); win.fit_page()
    win.page_nav.next(); app.processEvents()
    if mode == "light":
        win.page_nav.first(); win.auto_takeoff_rooms(); app.processEvents()
    win.grab().save(os.path.join(out, f"{mode}.png"))
    for i in range(win.tabs.count()):
        t = win.tabs.widget(i)
        if hasattr(t, "view"): t.view.dirty = False
    win.hide()
print("ok"); sys.stdout.flush(); os._exit(0)
