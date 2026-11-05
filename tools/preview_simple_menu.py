"""Preview Chief's simple menus (v11r) WITHOUT installing them: loads the
module from .run/preview/simple_menu.py onto a throwaway window with
throwaway settings, and saves one picture per tab plus the current ribbon
for comparison. python tools/preview_simple_menu.py OUTDIR"""
import importlib.util
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

from PySide6.QtWidgets import QApplication, QMessageBox      # noqa: E402

from app import settings, theme                               # noqa: E402

TMP = tempfile.mkdtemp(prefix="quantisheet-preview-")
settings.DIR = os.path.join(TMP, "cfg")
settings.PATH = os.path.join(settings.DIR, "settings.json")
settings._cache = None
for n in ("information", "warning"):
    setattr(QMessageBox, n, staticmethod(lambda *a, **k: 0))


def main(argv):
    out = argv[0]
    os.makedirs(out, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    theme.apply(m="light")
    from app.main_window import MainWindow
    w = MainWindow()
    w.resize(1600, 900)
    w.show()
    for _ in range(3):
        app.processEvents()
    top = lambda: w.grab().copy(0, 0, 1600, 190)          # noqa: E731
    # the ribbon as it is today
    for tab in ("Home", "Takeoff"):
        w.ribbon.show_page(tab)
        app.processEvents()
        top().save(os.path.join(out, f"now_{tab}.png"))
    if getattr(w, "simple_menu", None) is not None:      # installed now
        from app import simple_menu as mod
        sm = w.simple_menu
        sm.toggle_action.trigger()                         # old ribbon
        app.processEvents()
        for tab in ("Home", "Takeoff"):
            w.ribbon.show_page(tab)
            app.processEvents()
            top().save(os.path.join(out, f"now_{tab}.png"))
        sm.toggle_action.trigger()
    else:
        src = os.path.join(ROOT, ".run", "preview", "simple_menu.py")
        spec = importlib.util.spec_from_file_location("app._simple_preview",
                                                      src)
        mod = importlib.util.module_from_spec(spec)
        mod.__package__ = "app"
        spec.loader.exec_module(mod)
        sm = mod.install(w)
    for _ in range(3):
        app.processEvents()
    for tab in mod.TABS + ["All Tools"]:
        sm.ribbon.show_page(tab)
        for _ in range(2):
            app.processEvents()
        top().save(os.path.join(out, f"simple_{tab.replace(' ', '_').replace('&', 'and')}.png"))
    p = sm.all_tools_panel()
    p.resize(700, 600)
    p.show()
    app.processEvents()
    p.grab().save(os.path.join(out, "simple_all_tools_panel.png"))
    r = mod.reachability(w)
    print("reachability:", r)
    print("written to", out)


if __name__ == "__main__":
    main(sys.argv[1:])
