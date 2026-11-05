import os, sys, time, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tools"))
import fitz
import perf
from app import autowalls as aw
p = os.path.join(tempfile.mkdtemp(), "job.pdf")
perf.make(p, 1)
d = fitz.open(p)
pg = d[0]
print("page", pg.rect)
t = time.perf_counter(); segs = aw.segments(pg, 18); print("segments", len(segs), round(time.perf_counter() - t, 2))
t = time.perf_counter(); ws = aw.walls(pg, 18, "ft"); print("vector walls", len(ws), round(time.perf_counter() - t, 2))
t = time.perf_counter(); ds = aw.doors(pg, 18, "ft"); print("doors", len(ds), round(time.perf_counter() - t, 2))
t = time.perf_counter(); rs = aw.raster_segments(pg, 18, "ft"); print("raster segs", len(rs), round(time.perf_counter() - t, 2))
t = time.perf_counter(); ws2 = aw.walls(pg, 18, "ft", segs=rs); print("raster walls", len(ws2), round(time.perf_counter() - t, 2))
print(aw.summary(ws, ds))
