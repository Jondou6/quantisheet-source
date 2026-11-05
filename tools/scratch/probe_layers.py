"""Probe: can MuPDF draw a page's markups on top of a cached render of its
drawing (contents and annotations separately)?"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import fitz                                                   # noqa: E402

mu = fitz.mupdf
print("pymupdf", fitz.VersionBind, "has:", {n: hasattr(mu, n) for n in (
    "fz_run_page_contents", "fz_run_page_annots", "fz_run_page_widgets",
    "fz_new_draw_device", "fz_new_list_device")})
import perf                                                    # noqa: E402
import tempfile                                                # noqa: E402
tmp = tempfile.mkdtemp()
path = os.path.join(tmp, "p.pdf")
perf.make(path, 2)
doc = fitz.open(path)
page = doc[0]
print("page.this type:", type(page.this).__name__)
z = 0.8
m = fitz.Matrix(z, z)
t = time.perf_counter()
full = page.get_pixmap(matrix=m, alpha=False)
print(f"full render {1000 * (time.perf_counter() - t):.1f} ms")
t = time.perf_counter()
base = page.get_pixmap(matrix=m, alpha=False, annots=False)
print(f"contents only {1000 * (time.perf_counter() - t):.1f} ms")
try:
    fzpage = page.this if isinstance(page.this, mu.FzPage) else \
        mu.FzPage(page.this)
    t = time.perf_counter()
    pix = fitz.Pixmap(base)                        # copy
    dev = mu.fz_new_draw_device(mu.FzMatrix(), pix.this)
    ctm = mu.FzMatrix(z, 0, 0, z, 0, 0)
    mu.fz_run_page_annots(fzpage, dev, ctm, mu.FzCookie())
    mu.fz_run_page_widgets(fzpage, dev, ctm, mu.FzCookie())
    mu.fz_close_device(dev)
    dt = 1000 * (time.perf_counter() - t)
    out = os.path.join(ROOT, ".run", "probe")
    os.makedirs(out, exist_ok=True)
    for name, px in (("full", full), ("base", base), ("overlay", pix)):
        px.save(os.path.join(out, name + ".png"))
    print("pix sizes", full.irect, base.irect, pix.irect, pix.n, full.n)
    diff = sum(abs(a - b) for a, b in zip(full.samples, pix.samples))
    print(f"overlay annots on cached contents {dt:.1f} ms, total abs diff "
          f"{diff} over {len(full.samples)} bytes")
    page.set_rotation(90)
    full = page.get_pixmap(matrix=m, alpha=False)
    base = page.get_pixmap(matrix=m, alpha=False, annots=False)
    pix = fitz.Pixmap(base)
    dev = mu.fz_new_draw_device(mu.FzMatrix(), pix.this)
    ctm2 = mu.FzMatrix(*(page.rotation_matrix * m))
    fzpage = page.this if isinstance(page.this, mu.FzPage) else \
        mu.FzPage(page.this)
    mu.fz_run_page_annots(fzpage, dev, ctm2, mu.FzCookie())
    mu.fz_close_device(dev)
    diff = sum(abs(a - b) for a, b in zip(full.samples, pix.samples))
    print(f"rotated page: diff {diff}")
except Exception as e:
    import traceback
    traceback.print_exc()
