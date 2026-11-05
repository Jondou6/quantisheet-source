"""Speed test on a scanned drawing set (every sheet one big picture).

    python tools/scanset.py [SHEETS] [--json OUT]

Builds SHEETS (default 40) 36 x 24 in sheets, each a 200 dpi grayscale
scan (7,200 x 4,800 px, slightly different per sheet so nothing is shared),
then times opening, previews, deep zoom, and the app opening and paging
through it. Synthetic - never anyone's real drawings.
"""
import os
import random
import statistics
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

import fitz                                                   # noqa: E402

W, H = 2592, 1728
DPI = 200


def build(path, n):
    import bigset
    rnd = random.Random(11)
    src = fitz.open()
    bigset.sheet(src, 0, rnd)
    base = src[0].get_pixmap(matrix=fitz.Matrix(DPI / 72, DPI / 72),
                             colorspace=fitz.csGRAY)
    src.close()
    doc = fitz.open()
    for i in range(n):
        pix = fitz.Pixmap(base)               # a copy, made a bit different
        for _ in range(400):                  # specks, like a real scan
            x, y = rnd.randrange(pix.width), rnd.randrange(pix.height)
            pix.set_pixel(x, y, (rnd.randrange(0, 120),))
        pg = doc.new_page(width=W, height=H)
        pg.insert_image(pg.rect, stream=pix.tobytes("png"))
        pg.insert_text((W - 310, H - 70), f"S-{100 + i}", fontsize=1,
                       render_mode=3)         # invisible, like OCR'd text
    doc.save(path, garbage=1, deflate=True)
    doc.close()


def main(argv):
    n = int(argv[0]) if argv and argv[0].isdigit() else 40
    tmp = tempfile.mkdtemp(prefix="quantisheet-scanset-")
    path = os.path.join(tmp, f"scanset-{n}.pdf")
    rows = []

    def timed(label, fn, k=1):
        t = time.perf_counter()
        out = fn()
        dt = (time.perf_counter() - t) / k
        rows.append((label, dt))
        print(f"  {label:<46} {dt * 1000:9.0f} ms")
        sys.stdout.flush()
        return out
    print(f"Building {n} scanned sheets...")
    timed(f"build {n}-sheet scanned set", lambda: build(path, n))
    print(f"File: {os.path.getsize(path) / 1e6:.0f} MB")
    doc = timed("open scanned set", lambda: fitz.open(path))
    rnd = random.Random(2)
    picks = [rnd.randrange(doc.page_count) for _ in range(10)]
    ds = []
    for i in picks:
        t = time.perf_counter()
        doc[i].get_pixmap(matrix=fitz.Matrix(2200 / W, 2200 / W))
        ds.append(time.perf_counter() - t)
    rows.append(("scanned page preview (2200 px), median",
                 statistics.median(ds)))
    print(f"  {'scanned page preview (2200 px), median':<46} "
          f"{statistics.median(ds) * 1000:9.0f} ms")
    dl = doc[picks[0]].get_displaylist()
    ts = []
    for _ in range(12):
        cx, cy = rnd.uniform(0, W - 90), rnd.uniform(0, H - 90)
        t = time.perf_counter()
        dl.get_pixmap(matrix=fitz.Matrix(6, 6),
                      clip=fitz.Rect(cx, cy, cx + 85, cy + 85))
        ts.append(time.perf_counter() - t)
    rows.append(("scanned 512 px tile at 600 %, median",
                 statistics.median(ts)))
    print(f"  {'scanned 512 px tile at 600 %, median':<46} "
          f"{statistics.median(ts) * 1000:9.0f} ms")
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv[:1])
    from app import settings
    settings.DIR = os.path.join(tmp, "cfg")
    settings.PATH = os.path.join(settings.DIR, "s.json")
    settings._cache = None
    from app.main_window import MainWindow
    win = MainWindow()
    win.resize(1600, 960)
    win.show()
    app.processEvents()
    timed("open scanned set in QuantiSheet",
          lambda: (win.open_path(path), app.processEvents()))
    v = win._view

    def flip():
        for i in picks:
            v.go_to(i)
            v.repaint()
        app.processEvents()
    timed("go to a scanned sheet and paint it, average", flip, len(picks))
    v.dirty = False
    win.close()
    doc.close()
    if "--json" in argv:
        import json
        with open(argv[argv.index("--json") + 1].strip('"'), "w",
                  encoding="utf-8") as f:
            json.dump({r[0]: r[1] for r in rows}, f, indent=1)
    try:
        os.remove(path)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
