"""Diagnostic (read-only): walls and the exterior outline on chosen Aiken
sheets, from the work copy in %LOCALAPPDATA%\\QuantiSheetWork\\aiken
(made by aiken_eval; the Aiken folder itself is never opened here).

    python tools/diag_aiken_walls.py A-101 A-102 A-103

Prints, per sheet: scale, title, wall count and LF by thickness class,
the wall roles summary, the exterior loop (LF, loops, flags), and saves
a picture of the sheet with the walls (red), the exterior loop (blue) and
walls left outside the loop (green) to quantisheet\\.work\\diag\\."""
import math
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import app  # noqa: E402,F401
import fitz  # noqa: E402
import aiken_eval  # noqa: E402
from app import aitakeoff as ait, autowalls, wall_roles  # noqa: E402

args = sys.argv[1:]
if args and args[0].startswith("maxt="):
    autowalls.MAX_T_IN = float(args.pop(0)[5:])
if args and args[0] == "oldhatch":
    args.pop(0)
    autowalls.HATCH_EVEN_ONLY = False
print("MAX_T_IN", autowalls.MAX_T_IN, "HATCH_EVEN_ONLY",
      autowalls.HATCH_EVEN_ONLY)
want = [a.upper() for a in args] or ["A-101", "A-102", "A-103"]
pdf = os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS)
doc = fitz.open(pdf)
rows = ait.plan_set(doc, None)
out_dir = os.path.join(ROOT, ".work", "diag")
os.makedirs(out_dir, exist_ok=True)
print("walls pages:", ait.walls_pages(rows))
for r in rows:
    num = (r.get("number") or "").upper()
    if num not in want:
        continue
    pno = r["page"]
    page = doc[pno]
    print("=" * 70)
    print(num, "page", pno + 1, "|", r.get("title"), "| kind", r.get("kind"),
          "| engines", r.get("engines"), "| scale", r.get("scale"))
    if not r.get("scale"):
        print("  no scale")
        continue
    _l, ppu, unit = r["scale"]
    info = {}
    try:
        ws = autowalls.walls(page, ppu, unit, info=info)
    except Exception as e:                               # noqa: BLE001
        print("  walls failed:", e)
        ws = []
    print("  vector segs:", len(autowalls.segments(page)),
          "walls:", len(ws), "source:", info.get("source"))
    for c in info.get("classes") or []:
        print(f"   class {c['label']:<40} {c['lf']:8.1f} LF n={c['count']}"
              f" conf={c['confident']} {c.get('flags')}")
    roles = wall_roles.find_ex(page, ppu, unit)
    from app import schedules as _sc
    _inf = _sc.sheet_info(page)
    _vs = _sc.views(_inf["cells"])
    print("  views:", [(v["title"], v["secondary"]) for v in _vs])
    for _c in _inf["cells"]:
        if re.search(r"MEZZ|LADDER|FINISHED|SCALE", _c["text"]):
            print("   cell:", repr(_c["text"]), round(_c["x0"]), round(_c["y0"]),
                  round(_c["x1"]), round(_c["y1"]), round(_c["h"], 1))
    _vs = _sc.view_regions(_vs, _inf["segs"], _inf["w"], _inf["h"])
    print("  regions:", [(v["title"], v.get("region")) for v in _vs])
    print("  other views:", wall_roles._other_views(page))
    print("  roles summary:", {k: round(v, 1) for k, v in
                               roles["summary"].items()})
    ext = roles["exterior"]
    print("  exterior:", {k: (round(v, 1) if isinstance(v, float) else v)
                          for k, v in ext.items() if k != "pts"})
    print("  loops pts:", [len(p) for p in ext.get("pts") or []])
    print("  flags:", roles["flags"])
    # picture, in unrotated page coordinates scaled down
    z = 0.35
    pix = page.get_pixmap(matrix=fitz.Matrix(z, z) * page.derotation_matrix
                          if page.rotation else fitz.Matrix(z, z))
    pic = fitz.open()
    W, H = pix.width, pix.height
    pp = pic.new_page(width=W, height=H)
    pp.insert_image(pp.rect, pixmap=pix)
    for w in roles["walls"]:
        a, b = w["p0"], w["p1"]
        pp.draw_line((a[0] * z, a[1] * z), (b[0] * z, b[1] * z),
                     color=(1, 0, 0), width=1.2)
    for loop in ext.get("pts") or []:
        n = len(loop)
        for i in range(n):
            a, b = loop[i], loop[(i + 1) % n]
            pp.draw_line((a[0] * z, a[1] * z), (b[0] * z, b[1] * z),
                         color=(0, 0, 1), width=2.5)
    for pc in roles["pieces"]:
        if pc.get("role") == "Freestanding":
            a, b = pc["p0"], pc["p1"]
            pp.draw_line((a[0] * z, a[1] * z), (b[0] * z, b[1] * z),
                         color=(0, 0.7, 0), width=2)
    outp = os.path.join(out_dir, f"{num}_t{autowalls.MAX_T_IN:g}"
                        f"{'' if autowalls.HATCH_EVEN_ONLY else '_old'}.png")
    pp.get_pixmap(dpi=72).save(outp)
    print("  picture:", outp, f"({W}x{H})")
