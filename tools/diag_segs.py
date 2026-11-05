"""Diagnostic (read-only): the linework crossing a probe line on one sheet
of the Aiken work copy, to see how a wall is drawn.

    python tools/diag_segs.py A-101 h 1200 300 450
        -> lines running horizontally (within 2 deg) that cross x=1200,
           between y=300 and y=450 (page points, unrotated)
    python tools/diag_segs.py A-101 v 900 400 700
        -> vertical lines crossing y=900 between x=400 and x=700
Also writes a 4x zoom picture of the probed strip to .work\\diag\\."""
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import app  # noqa: E402,F401
import fitz  # noqa: E402
import aiken_eval  # noqa: E402
from app import aitakeoff as ait  # noqa: E402

num, orient = sys.argv[1].upper(), sys.argv[2]
at, lo, hi = (float(x) for x in sys.argv[3:6])
doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))
rows = ait.plan_set(doc, None)
pno = next(r["page"] for r in rows if (r.get("number") or "").upper() == num)
page = doc[pno]
print(num, "page", pno + 1, "rotation", page.rotation, "rect", page.rect)
found = []
for d in page.get_drawings():
    for it in d.get("items", ()):
        segs = []
        if it[0] == "l":
            segs = [(it[1], it[2])]
        elif it[0] == "re":
            r = fitz.Rect(it[1])
            q = [r.tl, r.tr, r.br, r.bl]
            segs = [(q[i], q[(i + 1) % 4]) for i in range(4)]
        elif it[0] == "qu":
            q = it[1]
            pts = [q.ul, q.ur, q.lr, q.ll]
            segs = [(pts[i], pts[(i + 1) % 4]) for i in range(4)]
        for a, b in segs:
            dx, dy = b.x - a.x, b.y - a.y
            L = math.hypot(dx, dy)
            if L < 0.5:
                continue
            ang = math.degrees(math.atan2(dy, dx)) % 180
            if orient == "h":
                if min(ang, 180 - ang) > 2:
                    continue
                if not (min(a.x, b.x) <= at <= max(a.x, b.x)):
                    continue
                off = (a.y + b.y) / 2
                ext = (min(a.x, b.x), max(a.x, b.x))
            else:
                if abs(ang - 90) > 2:
                    continue
                if not (min(a.y, b.y) <= at <= max(a.y, b.y)):
                    continue
                off = (a.x + b.x) / 2
                ext = (min(a.y, b.y), max(a.y, b.y))
            if lo <= off <= hi:
                found.append((off, ext, L, d.get("type"), d.get("width"),
                              d.get("color"), d.get("fill"), it[0],
                              d.get("dashes")))
found.sort()
ppu = 18.0
print(f"{len(found)} lines; offset (pt) / (in at 1/4\") / extent / len / "
      "type width color fill item dashes")
prev = None
for f in found:
    gap = "" if prev is None else f"  +{(f[0] - prev) / ppu * 12:5.2f} in"
    prev = f[0]
    print(f"  {f[0]:9.2f}{gap:>12}  ext {f[1][0]:8.1f}-{f[1][1]:8.1f} "
          f"L={f[2]:7.1f} {f[3]} w={f[4]} c={f[5]} f={f[6]} {f[7]} "
          f"{f[8] or ''}")
clip = fitz.Rect(at - 60, lo, at + 60, hi) if orient == "h" else \
    fitz.Rect(lo, at - 60, hi, at + 60)
if page.rotation:
    clip = clip * page.rotation_matrix
pix = page.get_pixmap(matrix=fitz.Matrix(4, 4), clip=clip.normalize())
out = os.path.join(ROOT, ".work", "diag", f"{num}_{orient}_{int(at)}.png")
os.makedirs(os.path.dirname(out), exist_ok=True)
pix.save(out)
print("picture:", out)
