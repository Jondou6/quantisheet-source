"""Speed test on a big drawing set.

    python tools/bigset.py [SHEETS] [--pdf FILE] [--keep]

Builds an N-sheet (default 800) 36 x 24 in vector set - each sheet has a
title block, a grid, ~4,000 wall/duct/pipe segments, hatching, door swings
and room tags - unless --pdf gives a real one, then times what an
estimator feels: opening, flipping sheets, zooming in, panning, searching,
reading sheet numbers, and the app's own page switch and paint.
"""
import math
import os
import random
import statistics
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

import fitz                                                   # noqa: E402

W, H = 2592, 1728


def sheet(doc, n, rnd):
    pg = doc.new_page(width=W, height=H)
    sh = pg.new_shape()
    sh.draw_rect(fitz.Rect(36, 36, W - 36, H - 36))
    sh.draw_rect(fitz.Rect(W - 330, 36, W - 36, H - 36))
    sh.finish(color=(0, 0, 0), width=2)
    for k in range(1, 12):                         # grid lines
        x = 120 + k * 180
        sh.draw_line((x, 80), (x, H - 120))
    for k in range(1, 8):
        y = 80 + k * 190
        sh.draw_line((80, y), (W - 400, y))
    sh.finish(color=(0.6, 0.6, 0.6), width=0.4, dashes="[8 4] 0")
    for _ in range(1300):                          # walls, double lines
        x, y = rnd.uniform(120, W - 450), rnd.uniform(120, H - 160)
        if rnd.random() < .5:
            L = rnd.uniform(40, 400)
            sh.draw_line((x, y), (x + L, y))
            sh.draw_line((x, y + 6), (x + L, y + 6))
        else:
            L = rnd.uniform(40, 300)
            sh.draw_line((x, y), (x, y + L))
            sh.draw_line((x + 6, y), (x + 6, y + L))
    sh.finish(color=(0, 0, 0), width=1.2)
    for _ in range(1400):                          # ducts / pipes / misc
        x, y = rnd.uniform(120, W - 450), rnd.uniform(120, H - 160)
        a = rnd.uniform(0, math.pi)
        L = rnd.uniform(10, 120)
        sh.draw_line((x, y), (x + L * math.cos(a), y + L * math.sin(a)))
    sh.finish(color=(0.2, 0.2, 0.2), width=0.5)
    for _ in range(120):                           # door swings
        x, y = rnd.uniform(150, W - 500), rnd.uniform(150, H - 200)
        sh.draw_line((x, y), (x + 36, y))
        sh.draw_curve((x + 36, y), (x + 36, y - 25), (x, y - 36))
    sh.finish(color=(0, 0, 0), width=0.6)
    for _ in range(25):                            # hatched areas
        x, y = rnd.uniform(150, W - 600), rnd.uniform(150, H - 300)
        for k in range(0, 120, 6):
            sh.draw_line((x + k, y), (x, y + k))
    sh.finish(color=(0.4, 0.4, 0.4), width=0.3)
    sh.commit()
    for _ in range(60):
        pg.insert_text((rnd.uniform(150, W - 600), rnd.uniform(150, H - 200)),
                       f"ROOM {rnd.randint(100, 999)}", fontsize=7)
    disc = "AMEPS"[n % 5]
    pg.insert_text((W - 310, H - 160), "PROJECT 2026-114", fontsize=11)
    pg.insert_text((W - 310, H - 130), f"SHEET TITLE {n}", fontsize=11)
    pg.insert_text((W - 310, H - 70), f"{disc}-{100 + n}", fontsize=30)


def build(path, n):
    rnd = random.Random(7)
    doc = fitz.open()
    for i in range(n):
        sheet(doc, i, rnd)
    doc.save(path, garbage=1, deflate=True)
    doc.close()


def timed(label, fn, rows, unit="s", n=1):
    t = time.perf_counter()
    out = fn()
    dt = (time.perf_counter() - t) / n
    rows.append((label, dt))
    print(f"  {label:<46} {dt * (1000 if unit == 'ms' else 1):9.1f} {unit}")
    sys.stdout.flush()
    return out


def main(argv):
    n = int(argv[0]) if argv and argv[0].isdigit() else 800
    tmp = tempfile.mkdtemp(prefix="quantisheet-bigset-")
    path = argv[argv.index("--pdf") + 1].strip('"') if "--pdf" in argv else \
        os.path.join(tmp, f"bigset-{n}.pdf")
    rows = []
    if "--pdf" not in argv:
        print(f"Building {n} sheets...")
        timed(f"build {n}-sheet set", lambda: build(path, n), rows)
    print(f"File: {os.path.getsize(path) / 1e6:.0f} MB")
    print("\nEngine")
    doc = timed("open", lambda: fitz.open(path), rows)
    pages = doc.page_count
    rnd = random.Random(1)
    picks = [rnd.randrange(pages) for _ in range(20)]
    ds = []
    for i in picks:
        t = time.perf_counter()
        doc[i].get_pixmap(matrix=fitz.Matrix(2200 / W, 2200 / W))
        ds.append(time.perf_counter() - t)
    rows.append(("page preview (2200 px), median", statistics.median(ds)))
    print(f"  {'page preview (2200 px), median':<46} "
          f"{statistics.median(ds) * 1000:9.1f} ms  (max "
          f"{max(ds) * 1000:.0f})")
    pg = doc[picks[0]]
    dl = timed("display list for a sheet", lambda: pg.get_displaylist(),
               rows, "ms")
    z = 6.0
    ts = []
    for k in range(24):
        cx, cy = rnd.uniform(0, W - 90), rnd.uniform(0, H - 90)
        t = time.perf_counter()
        dl.get_pixmap(matrix=fitz.Matrix(z, z), clip=fitz.Rect(
            cx, cy, cx + 512 / z, cy + 512 / z))
        ts.append(time.perf_counter() - t)
    rows.append(("512 px tile at 600 %, median", statistics.median(ts)))
    print(f"  {'512 px tile at 600 %, median':<46} "
          f"{statistics.median(ts) * 1000:9.1f} ms")
    old = timed("whole page at 600 % (old renderer)",
                lambda: pg.get_pixmap(matrix=fitz.Matrix(3, 3)), rows)
    print("     (shown at 300 %; 600 % would need "
          f"{W * 6 * H * 6 * 3 / 1e9:.1f} GB)")
    del old
    timed(f"search one word on all {pages} sheets",
          lambda: sum(len(p.search_for("PROJECT")) for p in doc), rows)
    from app import sets
    timed(f"read sheet numbers of all {pages} sheets",
          lambda: sets.index_file(path), rows)
    print("\nApp")
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
    timed("open in QuantiSheet (window ready)",
          lambda: (win.open_path(path), app.processEvents()), rows)
    v = win._view

    def flip():
        for i in picks:
            v.go_to(i)
            v.repaint()
        app.processEvents()
    timed("go to a sheet and paint it, average", flip, rows, "ms",
          len(picks))

    def zoom_pan():
        v.set_zoom(6.0)
        sc = win._scroll
        for k in range(12):
            sc.horizontalScrollBar().setValue(k * 400)
            sc.verticalScrollBar().setValue(k * 250)
            v.repaint()
        app.processEvents()
    timed("zoom to 600 % and pan 12 screens, per screen", zoom_pan, rows,
          "ms", 12)
    win._view.dirty = False
    win.close()
    if "--json" in argv:                 # for tools/perf_gate.py
        import json as _json
        with open(argv[argv.index("--json") + 1].strip('"'), "w",
                  encoding="utf-8") as _f:
            _json.dump({r[0]: r[1] for r in rows}, _f, indent=1)
    print("\nDone.")
    if "--keep" not in argv and "--pdf" not in argv:
        try:
            doc.close()
            os.remove(path)
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
