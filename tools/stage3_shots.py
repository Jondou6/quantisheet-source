"""Pictures of the Stage 3 look: start page and a drawing, light and dark.

    python tools/stage3_shots.py [OUT_DIR]
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["QUANTISHEET_NO_OPEN"] = "1"
if os.path.isdir(r"C:\\Windows\\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\\Windows\\Fonts")

from PySide6.QtWidgets import QApplication, QDialog, QMessageBox   # noqa

from app import settings, theme                                     # noqa

TMP = tempfile.mkdtemp(prefix="quantisheet-stage3-")
settings.DIR = os.path.join(TMP, "cfg")
settings.PATH = os.path.join(settings.DIR, "settings.json")
settings._cache = {"author": "Tester", "autosave_mode": "off"}
QMessageBox.information = staticmethod(lambda *a, **k: 0)
QDialog.exec = lambda self, *a: 0


def main(argv):
    out = argv[0] if argv else os.path.join(ROOT, ".run", "stage3")
    os.makedirs(out, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    import make_sample
    # Recent leaves out temp folders on purpose, so the samples live here
    jobs = os.path.join(ROOT, ".run", "stage3", "Jobs",
                        "32410 Bucksport WWTP")
    os.makedirs(jobs, exist_ok=True)
    recent = []
    for n in ("32410-004-IFC-Plant Drawings.pdf", "C-101 Site Plan.pdf",
              "Addendum 3 - Specs.pdf", "A-101 Floor Plan.pdf",
              "Lift Station Upgrades.pdf"):
        p = os.path.join(jobs, n)
        make_sample.make(p)
        recent.append(p)
    settings.set("recent", recent)
    theme.apply(app, "light")
    from app.main_window import MainWindow
    w = MainWindow()
    w.resize(1600, 950)
    w.show()

    def shot(name):
        for _ in range(4):
            app.processEvents()
        p = os.path.join(out, name)
        w.grab().save(p)
        print("saved", p, flush=True)

    from PySide6.QtGui import QPixmap
    from app import main as app_main
    sp = QPixmap(os.path.join(ROOT, "splash.png"))
    if not sp.isNull():
        app_main._stamp_version(sp).save(os.path.join(out, "0_splash.png"))
        print("saved splash", flush=True)
    w.start_page.refresh()
    shot("1_start_light.png")
    theme.apply(app, "dark")
    shot("2_start_dark.png")
    print("recent rows:", w.start_page.recent.count(), flush=True)
    theme.apply(app, "light")
    w.open_path(recent[3])
    app.processEvents()
    w.set_tool("measure_length")
    shot("3_drawing_light.png")
    theme.apply(app, "dark")
    shot("4_drawing_dark.png")
    theme.apply(app, "light")
    os._exit(0)


if __name__ == "__main__":
    main(sys.argv[1:])
