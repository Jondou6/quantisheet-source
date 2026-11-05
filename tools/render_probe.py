"""How long the sheets of a set take to draw, and whether drawing on a
background thread leaves the window's thread free.

    python tools/render_probe.py [PDF] [PAGES]
"""
import os
import statistics
import sys
import threading
import time

import fitz

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop",
                       "32410-004-IFC-Plant Drawings.pdf")
PREVIEW_PX = 2200


def preview_zoom(pg):
    side = max(pg.rect.width, pg.rect.height) or 1
    return PREVIEW_PX * 1.5 / side            # 150 % display scaling


def main(argv):
    path = (argv[0].strip('"') if argv else DEFAULT)
    limit = int(argv[1]) if len(argv) > 1 else 10**9
    doc = fitz.open(path)
    n = min(doc.page_count, limit)
    print(f"{os.path.basename(path)}: {doc.page_count} pages, timing {n}",
          flush=True)
    rows = []
    t_all = time.perf_counter()
    for i in range(n):
        pg = doc[i]
        z = preview_zoom(pg)
        t = time.perf_counter()
        dl = pg.get_displaylist()
        t_dl = time.perf_counter() - t
        t = time.perf_counter()
        pix = dl.get_pixmap(matrix=fitz.Matrix(z, z), alpha=False)
        t_px = time.perf_counter() - t
        size = 0
        for x in pg.get_contents():
            size += len(doc.xref_stream_raw(x) or b"")
        rows.append((t_dl + t_px, t_dl, t_px, i + 1, size, pix.width))
        del pix, dl
    total = time.perf_counter() - t_all
    times = [r[0] for r in rows]
    print(f"total {total:.1f}s  median {statistics.median(times)*1000:.0f} ms"
          f"  mean {statistics.mean(times)*1000:.0f} ms  max "
          f"{max(times)*1000:.0f} ms", flush=True)
    for cut in (0.25, 0.5, 1, 2, 4):
        print(f"  pages over {cut:>4}s: {sum(1 for x in times if x > cut)}",
              flush=True)
    print("slowest pages (total = parse + draw):", flush=True)
    for tot, dl, px, p, size, w in sorted(rows, reverse=True)[:12]:
        print(f"  p{p:<4} {tot*1000:7.0f} ms  (parse {dl*1000:6.0f}, draw "
              f"{px*1000:6.0f})  content {size/1e6:5.2f} MB  {w}px",
              flush=True)

    # does a render on another thread leave this thread free?
    slow = sorted(rows, reverse=True)[0][3] - 1
    pg = doc[slow]
    z = preview_zoom(pg)
    ticks = []
    done = threading.Event()

    def work():
        d2 = fitz.open(path)
        p2 = d2[slow]
        p2.get_pixmap(matrix=fitz.Matrix(z, z), alpha=False)
        d2.close()
        done.set()

    th = threading.Thread(target=work)
    t0 = time.perf_counter()
    th.start()
    last = t0
    worst = 0.0
    while not done.is_set():
        time.sleep(0.005)
        now = time.perf_counter()
        worst = max(worst, now - last)
        ticks.append(now)
        last = now
    th.join()
    span = time.perf_counter() - t0
    print(f"thread test on p{slow+1}: render took {span*1000:.0f} ms; this "
          f"thread ran {len(ticks)} times, longest wait {worst*1000:.0f} ms "
          f"({'FREE - library lets go of the lock' if worst < 0.1 else 'BLOCKED - library holds the lock'})",
          flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
