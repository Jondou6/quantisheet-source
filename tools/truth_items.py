"""What is drawn in a box of a truth set's sheet: pen, layer, size.

    python tools/truth_items.py SET X0 Y0 X1 Y1 [--wall]

For working out why a traced room stops where it does. Coordinates are
PDF points on the set's sheet (truth_rooms.py --dump prints corners).
Prints one line per drawing path that lies inside the box (not the big
ones that merely cross it), and which layers the plan treats as walls.
The drawings stay on this computer; nothing from them is written into
the repository.
"""
import os
import shutil
import sys
import tempfile
from collections import Counter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def run(name, box, wall_only=False):
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
    page = doc[row["page"]]
    sc = row["scale"]
    plan = at.Plan(at.cached_page(page), {"ppu": sc[1], "unit": sc[2]},
                   claimed=False)
    print("layers of the plan picture:", len(plan.layers), "wall layer "
          "picture:", plan.wl is not None, "fine pen:",
          at.fine_pen(at.cached_page(page)))
    try:
        print("wall layers:", sorted(at.wall_layers(at.cached_page(page))))
    except Exception as e:                                # noqa: BLE001
        print("wall layers: n/a", e)
    b = fitz.Rect(box)
    seen = Counter()
    for d in page.get_drawings():
        r = fitz.Rect(d["rect"])
        if not r.intersects(b):
            continue
        if r.width > 2.5 * b.width or r.height > 2.5 * b.height:
            seen[("(big path crossing)", d.get("layer"),
                  round(d.get("width") or 0, 2))] += 1
            # its pieces that lie in the box
            for it in d["items"]:
                pts = [q for q in it[1:] if hasattr(q, "x")]
                if it[0] == "re":
                    rr = fitz.Rect(it[1])
                    pts = [rr.tl, rr.br]
                if pts and all(b.contains(q) for q in pts):
                    print(f"   piece {it[0]:2s} "
                          f"{d.get('type')} w={round(d.get('width') or 0, 2)}"
                          f" layer={str(d.get('layer'))[:22]} fill="
                          f"{'y' if d.get('fill') else '-'} " + " ".join(
                              f"({q.x:.1f},{q.y:.1f})" for q in pts[:4]))
            continue
        kinds = Counter(it[0] for it in d["items"])
        print(f"{d.get('type'):2s} w={round(d.get('width') or 0, 2):5} "
              f"layer={str(d.get('layer'))[:28]:28s} "
              f"fill={'y' if d.get('fill') else '-'} "
              f"dash={'y' if d.get('dashes') not in (None, '', '[] 0') else '-'} "
              f"rect=({r.x0:.1f},{r.y0:.1f},{r.x1:.1f},{r.y1:.1f}) "
              f"{dict(kinds)}")
    for k, n in sorted(seen.items(), key=str):
        print(n, "x", k)
    doc.close()
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    run(a[0], [float(v) for v in a[1:5]], "--wall" in sys.argv)
