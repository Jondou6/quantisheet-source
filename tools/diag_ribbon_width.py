"""How wide does the ribbon insist on being, light vs dark? (Oct 28 dark
sweep: 2292 px minimum in dark.) Temp settings; nothing of Jon's touched.

    python tools/diag_ribbon_width.py"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
if "real" in sys.argv:          # Windows' own fonts; the window is never shown
    os.environ["QT_QPA_PLATFORM"] = "windows"
else:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
tmp = tempfile.mkdtemp(prefix="qs_rw_")
from app import settings                                         # noqa: E402
settings.DIR = os.path.join(tmp, "cfg")
settings.PATH = os.path.join(tmp, "cfg", "s.json")
settings._cache = {"author": "Diag"}
from PySide6.QtWidgets import QApplication                        # noqa: E402
app = QApplication.instance() or QApplication([])
from app import theme                                             # noqa: E402
from app.main_window import MainWindow                            # noqa: E402

for mode in ("light", "dark"):
    theme.apply(app, mode)
    w = MainWindow()
    w.resize(1400, 900)
    if "real" not in sys.argv:
        w.show()
    app.processEvents()
    scr = app.primaryScreen()
    print("screen", scr.availableGeometry().width(), "x",
          scr.availableGeometry().height(), "dpr", scr.devicePixelRatio())
    rb = w.ribbon
    print(f"--- {mode}: window min {w.minimumSizeHint().width()}, ribbon "
          f"bar min {w._ribbon_bar.minimumSizeHint().width()}, ribbon min "
          f"{rb.minimumSizeHint().width()} hint {rb.sizeHint().width()}")
    for i in range(rb.head.count()):
        it = rb.head.itemAt(i)
        wd = it.widget()
        lay = it.layout()
        if wd is not None:
            print(f"  head widget {wd.objectName() or type(wd).__name__} "
                  f"min {wd.minimumSizeHint().width()}")
        elif lay is not None:
            print(f"  head layout min {lay.minimumSize().width()} "
                  f"({lay.count()} items)")
    for name in list(rb.pages)[:1]:
        pg = rb.page(name)
        print(f"  {name:10s} min {pg.minimumSizeHint().width():5d} "
              f"hint {pg.sizeHint().width():5d}")
    for k in ("tabs", "tabbar", "bar", "_tabs"):
        t = getattr(rb, k, None)
        if t is not None and hasattr(t, "minimumSizeHint"):
            print(f"  [{k}] min {t.minimumSizeHint().width()} "
                  f"hint {t.sizeHint().width()}")
    for ch in rb.children():
        if hasattr(ch, "minimumSizeHint"):
            print(f"  child {type(ch).__name__} {ch.objectName()!r} min "
                  f"{ch.minimumSizeHint().width()}")
    w.close()
