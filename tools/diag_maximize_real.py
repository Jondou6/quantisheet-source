"""Does the main window really fill the screen on THIS PC? Opens a
QuantiSheet window for ~3 seconds with Windows' real window manager
(temp settings, no file opened), the way the program starts, then closes
it. Prints the window frame against the screen's free area over time.

    python tools/diag_maximize_real.py [dark]"""
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["QT_QPA_PLATFORM"] = "windows"
tmp = tempfile.mkdtemp(prefix="qs_mx_")
from app import settings                                         # noqa: E402
# "mine": start from the window size/place QuantiSheet saved last time
# on this PC (only that one setting is read; nothing is written back)
saved = settings.get("window") if "mine" in sys.argv else None
settings.DIR = os.path.join(tmp, "cfg")
settings.PATH = os.path.join(tmp, "cfg", "s.json")
settings._cache = {"author": "Diag"}
if saved:
    settings._cache["window"] = saved
    print("using the saved window setting (maximized:",
          saved.get("maximized"), ")")
from PySide6.QtWidgets import QApplication                        # noqa: E402
app = QApplication.instance() or QApplication([])
from app import theme                                             # noqa: E402
theme.apply(app, "dark" if "dark" in sys.argv else "light")
from app.main_window import MainWindow                            # noqa: E402

w = MainWindow()
w.show_restored()
av = w.screen().availableGeometry()
print("screen free area", av.x(), av.y(), av.width(), "x", av.height(),
      "dpr", w.screen().devicePixelRatio())
t0 = time.time()
last = None
while time.time() - t0 < 3.0:
    app.processEvents()
    fr = w.frameGeometry()
    now = (fr.x(), fr.y(), fr.width(), fr.height(), w.isMaximized())
    if now != last:
        print(f"{time.time() - t0:5.2f}s frame {fr.x()},{fr.y()} "
              f"{fr.width()}x{fr.height()} maximized {w.isMaximized()} "
              f"min {w.minimumSize().width()}x{w.minimumSize().height()}")
        last = now
    time.sleep(0.02)
from app import modern_ui                                         # noqa: E402
print("fills the screen:", modern_ui.fills_screen(w))
w.close()
