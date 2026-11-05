"""Probe: does walking annotations with first_annot/next keep the page
alive (and so break doc.reload_page)?"""
import gc
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import fitz                                                   # noqa: E402
from app import annotate                                       # noqa: E402


def make():
    d = fitz.open()
    p = d.new_page()
    for i in range(40):
        a = p.add_rect_annot(fitz.Rect(10 + i, 10, 20 + i, 20))
        a.update()
    return d


for label, walk in (("page.annots()", lambda pg: list(pg.annots())),
                    ("iter_annots", lambda pg: list(annotate.iter_annots(pg))),
                    ("iter_annots, dropped",
                     lambda pg: sum(1 for _ in annotate.iter_annots(pg))),
                    ):
    d = make()
    pg = d[0]

    def _manual(pg):
        n, a = 0, pg.first_annot
        while a:
            n += 1
            a = a.next
        return n
    r = walk(pg)
    n = len(r) if isinstance(r, list) else r
    del r
    if "--gc" in sys.argv:
        gc.collect()
    refs = pg.this.m_internal.refs
    try:
        d.reload_page(pg)
        ok = "reload ok"
    except AssertionError as e:
        ok = f"reload FAILED"
    print(f"{label:28} n={n:3} page refs={refs:3}  {ok}")
