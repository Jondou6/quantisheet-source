"""Auto Walls on a real set's sheet, the old way (every line paired with
every other) and pen by pen: total length and the thickness classes.

    python tools/truth_walls.py [SET] [--sheet A101]

Reads a temp copy of the drawing in _incoming/plans; nothing from it is
written into the repository."""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def run(name="hmb", sheet=None):
    import fitz
    import truth_rooms as tr
    from app import aitakeoff as ait, autowalls
    src = os.path.join(tr.PLANS, tr.FILES[name])
    tmp = tempfile.mkdtemp(prefix="qs-truth-")
    doc = fitz.open(shutil.copy(src, os.path.join(tmp, "set.pdf")))
    want = (sheet or tr.SHEET[name]).upper()
    row = next(r for r in ait.plan_set(doc) if (r["number"] or "").upper()
               == want and r["kind"] != "superseded")
    ppu, unit = row["scale"][1], row["scale"][2]
    page = doc[row["page"]]
    for label, kw in (("every line", {"by_pen": False}), ("pen by pen", {})):
        info = {}
        try:
            ws = autowalls.walls(page, ppu, unit, info=info, **kw)
        except TypeError:
            continue
        cls = {}
        for w in ws:
            k = round(w["thickness"], 1)
            cls[k] = cls.get(k, 0.0) + w["length"]
        print(f"{label}: {len(ws)} walls, {sum(cls.values()):.1f} LF; "
              f"{ {k: round(v, 1) for k, v in sorted(cls.items())} }")
    doc.close()
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    sh = sys.argv[sys.argv.index("--sheet") + 1] if "--sheet" in sys.argv \
        else None
    run(a[0] if a and a[0] != sh else "hmb", sh)
