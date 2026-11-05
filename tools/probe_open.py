"""Nov 3: a 67 MB drawing set that Acrobat opens but QuantiSheet freezes
on. Work on a temp copy and time each step of opening it, page by page,
so the step (and page) that hangs shows up. Read only: the original is
never opened for writing.

    python tools/probe_open.py PLAN.pdf [STEP]
STEP: basic (default) | window
"""
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def t(label, fn):
    t0 = time.perf_counter()
    try:
        out = fn()
        print(f"{time.perf_counter() - t0:8.2f}s  {label}", flush=True)
        return out
    except Exception as e:                                   # noqa: BLE001
        print(f"{time.perf_counter() - t0:8.2f}s  {label}: FAILED {e!r}",
              flush=True)
        return None


def basic(pdf):
    import fitz
    doc = t("open", lambda: fitz.open(pdf))
    print("pages", doc.page_count, "encrypted", doc.is_encrypted,
          "pdf version", doc.metadata.get("format"), flush=True)
    t("page labels / outline", lambda: (doc.get_page_labels(), doc.get_toc()))
    t("embedded files", lambda: doc.embfile_names())
    for i, page in enumerate(doc):
        r = page.rect
        info = f"p{i + 1} {r.width / 72:.1f}x{r.height / 72:.1f}in rot " \
               f"{page.rotation}"
        t(info + " xrefs/contents", lambda: len(page.get_contents()))
        t(info + " annots", lambda: len(list(page.annots())))
        t(info + " text", lambda: len(page.get_text("text")))
        t(info + " images", lambda: len(page.get_images()))
        t(info + " drawings count", lambda: len(page.get_cdrawings()))
        t(info + " render 0.25", lambda: page.get_pixmap(
            matrix=fitz.Matrix(0.25, 0.25), annots=False).width)
        if i >= 60:
            print("(stopping at 60 pages)")
            break


def window(pdf):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import threading
    import traceback
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from app.main_window import MainWindow

    def dump():
        time.sleep(40)
        print("\n--- still opening after 40 s; main thread is in:")
        frame = sys._current_frames()[threading.main_thread().ident]
        traceback.print_stack(frame)
        sys.stdout.flush()
        os._exit(3)
    threading.Thread(target=dump, daemon=True).start()
    w = MainWindow()
    t("open_path", lambda: w.open_path(pdf))
    t("events", lambda: [app.processEvents() for _ in range(50)])
    print("opened OK")
    os._exit(0)


def profile(pdf):
    """Open it in the window under the profiler; also time the unpriced
    count and the Markups List, then print the slowest calls."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import cProfile
    import pstats
    import threading
    import traceback
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from app.main_window import MainWindow

    def dump():
        time.sleep(400)
        print("\n--- still busy after 150 s; main thread is in:")
        traceback.print_stack(sys._current_frames()[
            threading.main_thread().ident])
        sys.stdout.flush()
        os._exit(3)
    threading.Thread(target=dump, daemon=True).start()
    w = MainWindow()
    prof = cProfile.Profile()
    prof.enable()
    t("open_path", lambda: w.open_path(pdf))
    prof.disable()
    pstats.Stats(prof).sort_stats("cumulative").print_stats(45)
    sys.stdout.flush()
    import fitz
    d = fitz.open(pdf)
    n = [sum(1 for _ in pg.annots()) for pg in d]
    print("annotations:", sum(n), "max on a page:", max(n), flush=True)
    os._exit(0)
    t("events (first paint, deferred work)", lambda: [
        (app.processEvents(), time.sleep(0.02)) for _ in range(60)])
    b = getattr(w, "workflow_boost", None)
    if b is not None:
        t("unpriced count", lambda: b._count_unpriced())
        print("unpriced:", getattr(b, "unpriced_count", None))
    from app import annotate
    t("markup items", lambda: len(annotate.markup_items(w._view.doc)))
    print("markups:", len(annotate.markup_items(w._view.doc)))
    prof.disable()
    pstats.Stats(prof).sort_stats("cumulative").print_stats(35)
    os._exit(0)


def render(pdf, pages=6):
    """Open it in the window, go to each of the first pages, wait for the
    drawing process, and say how much of the page area was drawn (a blank
    page is all white)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from app.main_window import MainWindow
    w = MainWindow()
    w.resize(1600, 1000)
    w.show()
    t("open_path", lambda: w.open_path(pdf))
    v = w._view
    for _ in range(40):
        app.processEvents()
        time.sleep(0.05)
    count = v.doc.page_count if pages is None else min(pages,
                                                       v.doc.page_count)
    blank = []
    for pno in range(count):
        v.go_to(pno)
        w.fit_page()
        t0 = time.perf_counter()
        ink = 0
        while time.perf_counter() - t0 < 15:
            app.processEvents()
            time.sleep(0.1)
            img = v.grab().toImage()
            W, H = img.width(), img.height()
            ink = sum(1 for x in range(0, W, 8) for y in range(0, H, 8)
                      if img.pixelColor(x, y).lightness() < 200)
            if ink > 50:
                break
        print(f"page {pno + 1}: rot {v.doc[pno].rotation}, zoom "
              f"{v.zoom:.2f}, dark samples {ink} after "
              f"{time.perf_counter() - t0:.1f}s, view {W}x{H}, drawer ok "
              f"{getattr(getattr(v, 'drawer', None), 'ok', '?')}",
              flush=True)
        if ink <= 50:
            blank.append(pno + 1)
    print("BLANK PAGES:", blank or "none", flush=True)
    os._exit(0)


def marked(pdf, n=1257):
    """Nov 3: the tester's copy of the set had about 1,250 markups. Add that
    many made-up markups to the temp copy (spread over the pages, the kinds
    a takeoff makes), then check every page draws, as render() does."""
    import random
    import fitz
    rnd = random.Random(3)
    doc = fitz.open(pdf)
    kinds = ("rect", "poly", "line", "text", "cloud")
    for i in range(n):
        pg = doc[i % doc.page_count]
        r = pg.rect
        x, y = rnd.uniform(0.05, 0.85) * r.width, rnd.uniform(0.05, 0.85) * \
            r.height
        k = kinds[i % len(kinds)]
        if k == "rect":
            a = pg.add_rect_annot(fitz.Rect(x, y, x + 40, y + 30))
        elif k == "poly":
            a = pg.add_polygon_annot([(x, y), (x + 60, y), (x + 60, y + 40),
                                      (x, y + 40)])
        elif k == "line":
            a = pg.add_line_annot((x, y), (x + 80, y + 10))
        elif k == "text":
            a = pg.add_freetext_annot(fitz.Rect(x, y, x + 90, y + 20),
                                      f"Item {i}", fontsize=8)
        else:
            a = pg.add_circle_annot(fitz.Rect(x, y, x + 30, y + 30))
        a.set_info(subject=f"Takeoff:area:Probe {i % 7}")
        a.update()
    out = pdf.replace(".pdf", "_marked.pdf")
    doc.save(out)
    doc.close()
    print("markups added", n, flush=True)
    render(out, pages=None)


def main(argv):
    src = argv[0].strip('"')
    step = argv[1] if len(argv) > 1 else "basic"
    tmp = tempfile.mkdtemp(prefix="qs_probe_")
    pdf = os.path.join(tmp, "plans.pdf")
    shutil.copy2(src, pdf)
    print("copy", os.path.getsize(pdf), "bytes", flush=True)
    try:
        {"window": window, "profile": profile, "render": render,
         "marked": marked}.get(step, basic)(pdf)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main(sys.argv[1:])
