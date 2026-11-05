"""Old vs new Auto Scale on a plan set: same answers? how much faster?

    python tools/autoscale_compare.py [PDF]
"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app  # noqa: E402,F401
import fitz  # noqa: E402
from app import autoscale  # noqa: E402
import _autoscale_old as old  # noqa: E402

SRC = os.path.join(os.path.expanduser("~"), "OneDrive", "Desktop",
                   "32410-004-IFC-Plant Drawings.pdf")


def run(mod, path):
    doc = fitz.open(path)
    t = time.perf_counter()
    rows = mod.detect(doc, use_ocr=False)
    return rows, time.perf_counter() - t


def main(argv):
    path = argv[0].strip('"') if argv else SRC
    new_rows, t_new = run(autoscale, path)
    print(f"new: {t_new:.1f}s", flush=True)
    old_rows, t_old = run(old, path)
    print(f"old: {t_old:.1f}s", flush=True)
    diffs = 0
    for a, b in zip(old_rows, new_rows):
        da, db = dict(a), dict(b)
        va, vb = da["dims"].get("ppu"), db["dims"].get("ppu")
        same_dims = (va is None and vb is None) or (
            va is not None and vb is not None and abs(va - vb) < 1e-9)
        da["dims"] = {k: v for k, v in da["dims"].items() if k != "ppu"}
        db["dims"] = {k: v for k, v in db["dims"].items() if k != "ppu"}
        if da != db or not same_dims:
            diffs += 1
            if diffs <= 8:
                print(f"  DIFF p{a['page']+1}: old {a} | new {b}",
                      flush=True)
    print(f"{len(new_rows)} sheets, {diffs} differences; "
          f"{t_old / max(t_new, 1e-9):.1f}x faster", flush=True)
    ok = sum(1 for r in new_rows if r["status"] == "ok")
    chk = sum(1 for r in new_rows if r["status"] == "check")
    print(f"result: {ok} ok, {chk} to check, "
          f"{len(new_rows) - ok - chk} with no scale", flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
