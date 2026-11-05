"""Diagnostic (read-only): pipe size tags and Trade Takeoff pipe systems
on one Aiken sheet (work copy).  python tools/diag_aiken_pipes.py P-101"""
import os
import sys
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import app  # noqa: E402,F401
import fitz  # noqa: E402
import aiken_eval  # noqa: E402
from app import aitakeoff as ait, tradetakeoff as tt  # noqa: E402

num = sys.argv[1].upper()
doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))
rows = ait.plan_set(doc, None)
r = next(r for r in rows if (r.get("number") or "").upper() == num)
pno, (_l, ppu, unit) = r["page"], r["scale"]
page = doc[pno]
print(num, "page", pno + 1, r.get("title"), "scale", r["scale"])
tags = [l for l in tt.labels(page) if l["kind"] == "pipe"]
print(len(tags), "pipe tags:", Counter(t["name"] for t in tags).most_common())
# the raw words around each "1/2" tag, to see how sizes are split
for t in tags:
    if t["name"].startswith(("1/2", "1-1/2")):
        rc = t["rect"] + (-30, -4, 4, 4)
        ws = [w[4] for w in page.get_text("words") if fitz.Rect(w[:4])
              .intersects(rc)]
        print("   1/2 tag at", [round(v) for v in t["rect"]], "words:",
              [(w[4], [round(v) for v in w[:4]]) for w in page.get_text(
                  "words") if fitz.Rect(w[:4]).intersects(rc)])
for g in tt.mep_runs(page, ppu, unit):
    if not g.get("labelled"):
        if g["length"] > 20:
            print(f"  (unlabelled) {g['name']:<26} {g['length']:8.1f} "
                  f"{unit} runs={len(g['runs'])}")
        continue
    print(f"  {g['name']:<16} {g['length']:8.1f} {unit}  runs={len(g['runs'])}"
          f"  style={g.get('style_name')}  flag={g.get('flag')[:60]}")
# a picture: each labelled size in its own colour, its name at each run's
# middle, the size tags boxed - .work\diag\<sheet>_pipes.png
want = [w.replace("_", " ").replace("in", "\"") for w in sys.argv[2].split(",")] if len(sys.argv) > 2 else None
z = 0.6
pix = page.get_pixmap(matrix=fitz.Matrix(z, z))
pic = fitz.open()
pp = pic.new_page(width=pix.width, height=pix.height)
pp.insert_image(pp.rect, pixmap=pix)
cols = [(1, 0, 0), (0, 0, 1), (0, 0.6, 0), (0.8, 0, 0.8), (1, 0.5, 0),
        (0, 0.7, 0.7), (0.5, 0.3, 0), (0.4, 0.4, 0.4)]
m = page.rotation_matrix
k = 0
for g in tt.mep_runs(page, ppu, unit):
    if not g.get("labelled") or (want and g["name"] not in want):
        continue
    col = cols[k % len(cols)]
    k += 1
    for rn in g["runs"]:
        pts = [fitz.Point(p) * m for p in rn["pts"]]
        if not any(fitz.Point(q.x, q.y) in page.rect for q in pts):
            pts = [fitz.Point(p) for p in rn["pts"]]
        for a, b in zip(pts, pts[1:]):
            pp.draw_line((a.x * z, a.y * z), (b.x * z, b.y * z), color=col,
                         width=2.5)
        mid = pts[len(pts) // 2]
        pp.insert_text((mid.x * z + 2, mid.y * z - 2), g["name"],
                       fontsize=7, color=col)
for t in tags:
    rc = t["rect"] * m
    pp.draw_rect(fitz.Rect(rc.x0 * z, rc.y0 * z, rc.x1 * z, rc.y1 * z),
                 color=(0, 0.8, 0), width=1)
out = os.path.join(ROOT, ".work", "diag", f"{num}_pipes.png")
os.makedirs(os.path.dirname(out), exist_ok=True)
pp.get_pixmap(dpi=110).save(out)
print("picture:", out)
g0 = next((g for g in tt.mep_runs(page, ppu, unit) if g.get("labelled")), None)
if g0:
    print("sample run pts", g0["runs"][0]["pts"][:3], "page.rect", page.rect)

# unlabelled runs of the pipe pens, 3 ft and up: where they are and their
# dash kind (d dashed, s solid, '' short)
for g in tt.mep_runs(page, ppu, unit):
    if g.get("labelled") or g.get("style_name") not in ("black, 1.5 pt",):
        continue
    for rn in g["runs"]:
        if rn["length"] >= 3:
            p0 = fitz.Point(rn["pts"][0]) * m
            p1 = fitz.Point(rn["pts"][-1]) * m
            print(f"   unlabelled {rn['length']:5.1f} ft kind={rn.get('kind')!r}"
                  f" from ({p0.x * z * 1.53:.0f},{p0.y * z * 1.53:.0f}) to "
                  f"({p1.x * z * 1.53:.0f},{p1.y * z * 1.53:.0f}) px")
