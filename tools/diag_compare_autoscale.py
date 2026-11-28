"""Auto Scale as the program runs it (no OCR layer made first), the
current code against an older copy of app/autoscale.py, on one set,
read-only: python tools/diag_compare_autoscale.py <glob> <old autoscale.py>
Prints both times and any sheet whose result differs."""
import glob
import importlib.util
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main(a):
    import fitz
    from app import autoscale
    spec = importlib.util.spec_from_file_location(
        "app._autoscale_old", os.path.join(ROOT, a[1]))
    old = importlib.util.module_from_spec(spec)
    sys.modules["app._autoscale_old"] = old
    spec.loader.exec_module(old)
    path = sorted(glob.glob(os.path.join(ROOT, a[0])))[0]
    out = {}
    for name, mod in (("new", autoscale), ("old", old)):
        doc = fitz.open(path)
        t = time.time()
        rows = mod.detect(doc, use_ocr=True)
        out[name] = (time.time() - t, rows)
        doc.close()
        print(f"{name}: {out[name][0]:.0f}s")
    diff = 0
    for r1, r2 in zip(out["new"][1], out["old"][1]):
        k1 = (r1["status"], r1.get("label"), r1.get("source"))
        k2 = (r2["status"], r2.get("label"), r2.get("source"))
        if k1 != k2:
            diff += 1
            print("  sheet", r1["page"] + 1, "new", k1, "old", k2)
    print("same results on every sheet" if not diff else f"{diff} differ")


if __name__ == "__main__":
    main(sys.argv[1:])
