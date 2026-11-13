"""The door swings auto takeoff reads in a box of a truth set's sheet.

    python tools/truth_doors.py SET X0 Y0 X1 Y1

One line per swing whose hinge is in the box: the hinge, the two ends of
its arc and its radius in feet. The drawings stay on this computer.
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def run(name, box):
    import fitz
    import truth_rooms as tr
    from app import aitakeoff as ait, autotakeoff as at
    src = os.path.join(tr.PLANS, tr.FILES[name])
    tmp = tempfile.mkdtemp(prefix="qs-truth-")
    doc = fitz.open(shutil.copy(src, os.path.join(tmp, "set.pdf")))
    want = tr.SHEET[name]
    row = next(r for r in ait.plan_set(doc)
               if (r["number"] or "").upper().replace("-", "") == want and
               r["kind"] != "superseded")
    page = at.cached_page(doc[row["page"]])
    ppu = row["scale"][1]
    b = fitz.Rect(box)
    n = 0
    for c, ends in at.door_swings(page, ppu):
        n += 1
        if not b.contains(c):
            continue
        r = abs(ends[0] - c)
        print(f"hinge ({c.x:.1f},{c.y:.1f}) r={r / ppu:.2f} ft ends " +
              " ".join(f"({e.x:.1f},{e.y:.1f})" for e in ends))
    print(n, "swings on the sheet")
    doc.close()
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    run(sys.argv[1], [float(v) for v in sys.argv[2:6]])
