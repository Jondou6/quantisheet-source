"""Diagnostic (read-only): LF per wall type on Aiken plan sheets as AI
Takeoff reads them - tagged, run on, inferred - and the flags (work
copy).  python tools/diag_aiken_walltypes.py A-101 A-103"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
import app  # noqa: E402,F401
import fitz  # noqa: E402
import aiken_eval  # noqa: E402
from app import aitakeoff as ait, autowalls  # noqa: E402

doc = fitz.open(os.path.join(aiken_eval.work_dir(), aiken_eval.DRAWINGS))
rows = ait.plan_set(doc, None)
leg, _p = ait.wall_legend(doc, rows)
for num in sys.argv[1:]:
    r = next(r for r in rows if (r.get("number") or "").upper() == num.upper())
    _l, ppu, unit = r["scale"]
    out = autowalls.wall_types(doc[r["page"]], ppu, unit, legend=leg)
    print("==", num, r.get("title"))
    for code, b in sorted(out["by_type"].items()):
        print(f"   {code}: {b['lf']:7.1f} LF tagged/run + "
              f"{b['lf_inferred']:6.1f} inferred, tags {b['tags']}")
    src = {}
    for w in out["walls"]:
        k = (w.get("type"), w.get("type_source"))
        src[k] = src.get(k, 0.0) + w["length"]
    for k, v in sorted(src.items(), key=lambda kv: str(kv[0])):
        print("     ", k, round(v, 1))
    for f in out["flags"]:
        print("   flag:", f[:600])
    if os.environ.get("QS_DIAG_PIC", "1") == "1":
        print("   legend:", {k: (str(v)[:80]) for k, v in (leg or {}).items()})
        page = doc[r["page"]]
        z = 1.0
        pix = page.get_pixmap(matrix=fitz.Matrix(z, z))
        pic = fitz.open()
        pp = pic.new_page(width=pix.width, height=pix.height)
        pp.insert_image(pp.rect, pixmap=pix)
        cols = {"1A": (1, 0, 0), "1B": (1, 0.5, 0), "2A": (0, 0, 1),
                "2B": (0, 0.6, 1), "3A": (0, 0.6, 0), "3B": (0.5, 0.8, 0)}
        m = page.rotation_matrix
        for w in out["walls"]:
            c = cols.get(w.get("type"), (1, 0, 1))
            a = fitz.Point(w["p0"]) * m * z
            b = fitz.Point(w["p1"]) * m * z
            dash = "[3 3] 0" if w.get("type_source") == "thickness" else None
            pp.draw_line(a, b, color=c, width=3, dashes=dash)
            if w.get("type") is None:
                mid = (a + b) / 2
                pp.insert_text(mid, f"{w.get('thickness', 0):.1f}",
                               fontsize=6, color=(1, 0, 1))
        outp = os.path.join(ROOT, ".work", "diag", f"{num}_walltypes.png")
        os.makedirs(os.path.dirname(outp), exist_ok=True)
        pp.get_pixmap(dpi=110).save(outp)
        print("   picture:", outp)
