"""Screenshots of the main window for design review (no settings touched).

    python tools/screenshot.py OUT_DIR [--pdf FILE]

Writes start page, each ribbon tab and the command search, in dark and
light, as PNGs into OUT_DIR. Without --pdf a sample floor plan is drawn.
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

import fitz                                                   # noqa: E402
from PySide6.QtCore import QTimer                             # noqa: E402
from PySide6.QtWidgets import QApplication                    # noqa: E402

from app import settings, theme                               # noqa: E402

TMP = tempfile.mkdtemp(prefix="quantisheet-shots-")
settings.DIR = os.path.join(TMP, "cfg")
settings.PATH = os.path.join(settings.DIR, "settings.json")
settings._cache = None


def sample_plan(path):
    doc = fitz.open()
    pg = doc.new_page(width=1728, height=1152)          # 24 x 16 in sheet
    sh = pg.new_shape()
    sh.draw_rect(fitz.Rect(36, 36, 1692, 1116))
    sh.draw_rect(fitz.Rect(1440, 36, 1692, 1116))
    sh.finish(color=(0, 0, 0), width=1.5)
    walls = [(150, 150, 1300, 150), (1300, 150, 1300, 900),
             (1300, 900, 150, 900), (150, 900, 150, 150),
             (600, 150, 600, 520), (600, 620, 600, 900),
             (150, 520, 520, 520), (680, 520, 1300, 520),
             (950, 520, 950, 900)]
    for x0, y0, x1, y1 in walls:
        sh.draw_line((x0, y0), (x1, y1))
    sh.finish(color=(0, 0, 0), width=4)
    for x in range(200, 1300, 90):
        sh.draw_circle((x, 940), 6)
    sh.finish(color=(0.2, 0.2, 0.2), width=1)
    sh.commit()
    for (x, y, t) in ((330, 330, "OFFICE 101"), (900, 330, "OPEN OFFICE 102"),
                      (330, 720, "CONF 103"), (760, 720, "BREAK 104"),
                      (1100, 720, "STORAGE 105")):
        pg.insert_text((x, y), t, fontsize=14)
    pg.insert_text((1460, 1000), "SHELTER COVE CLINIC", fontsize=14)
    pg.insert_text((1460, 1030), "FLOOR PLAN", fontsize=12)
    pg.insert_text((1460, 1060), "SCALE: 1/4\" = 1'-0\"", fontsize=11)
    pg.insert_text((1460, 1095), "A-101", fontsize=26)
    for _ in range(3):
        doc.new_page(width=1728, height=1152).insert_text(
            (100, 100), "SHEET", fontsize=20)
    doc.save(path)
    return path


def main(argv):
    out = argv[0] if argv else os.path.join(ROOT, ".run", "shots")
    os.makedirs(out, exist_ok=True)
    pdf = argv[argv.index("--pdf") + 1] if "--pdf" in argv else \
        sample_plan(os.path.join(TMP, "A-101 Floor Plan.pdf"))
    app = QApplication(sys.argv[:1])
    from app.main_window import MainWindow
    shots = []

    def grab(win, name):
        app.processEvents()
        p = os.path.join(out, name + ".png")
        win.grab().save(p)
        shots.append(p)

    for mode in ("dark", "light"):
        theme.apply(app, mode)
        win = MainWindow()
        win.resize(1600, 960)
        win.show()
        app.processEvents()
        grab(win, f"{mode}-start")
        win.open_path(pdf)
        app.processEvents()
        win.fit_page()
        for tab in ("Home", "Markup", "Takeoff", "Estimate", "Review",
                    "Project", "Pages", "Document", "Tools"):
            win.ribbon.show_page(tab)
            grab(win, f"{mode}-{tab.lower()}")
        dlg = win.command_search(show=False)
        dlg.resize(640, 420)
        dlg.input.setText("area")
        dlg.show()
        app.processEvents()
        dlg.grab().save(os.path.join(out, f"{mode}-palette.png"))
        shots.append(os.path.join(out, f"{mode}-palette.png"))
        dlg.close()
        missing = getattr(win, "_ribbon_missing", [])
        print(mode, "ribbon commands not found:", missing or "none")
        win.close()
    print("\n".join(shots))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
