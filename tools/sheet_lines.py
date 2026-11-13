"""What linework a sheet has, by pen: for finding the pen a run is drawn in.

    python tools/sheet_lines.py PDF-GLOB PAGE [--ppf 7.2] [--min 20]

Prints one line per pen (colour, width, dash pattern, layer): how many
pieces and the total length in feet at --ppf points per foot. Also the
small closed shapes (post or valve symbols) by size. The drawings stay
on this computer.
"""
import glob
import math
import os
import shutil
import sys
import tempfile
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def by_layer(args, layer, ppf):
    """Straight-line length per pen on layers whose name has `layer`,
    for pages A-B: the run itself, without its post circles."""
    import fitz
    hits = sorted(glob.glob(os.path.join(ROOT, args[0])))
    a, _, b = args[1].partition("-")
    tmp = tempfile.mkdtemp(prefix="qs-lines-")
    with fitz.open(shutil.copy(hits[0], os.path.join(tmp, "s.pdf"))) as doc:
        for n in range(int(a) - 1, int(b or a)):
            pens = defaultdict(lambda: [0.0, 0, 0])
            for d in doc[n].get_drawings():
                name = d.get("layer") or ""
                if layer.upper() not in name.upper():
                    continue
                key = (name, round(d.get("width") or 0, 2),
                       str(d.get("dashes") or ""))
                for it in d["items"]:
                    if it[0] == "l":
                        pens[key][0] += math.hypot(it[2].x - it[1].x,
                                                   it[2].y - it[1].y)
                        pens[key][1] += 1
                    elif it[0] == "c":
                        pens[key][2] += 1
            print(f"p{n + 1}:", "; ".join(
                f"{k[0]} w{k[1]} {k[2]}: {v[0] / ppf:.1f} ft "
                f"({v[1]} lines, {v[2] // 4} circles)"
                for k, v in sorted(pens.items())) or "-")
    return 0


def around(args):
    """For each short number printed on the page: the smallest drawn
    shape around it (how many straight and curved pieces, its size)."""
    import fitz
    from collections import Counter
    hits = sorted(glob.glob(os.path.join(ROOT, args[0])))
    tmp = tempfile.mkdtemp(prefix="qs-lines-")
    with fitz.open(shutil.copy(hits[0], os.path.join(tmp, "s.pdf"))) as doc:
        page = doc[int(args[1]) - 1]
        small = [d for d in page.get_drawings()
                 if 4 <= max(d["rect"].width, d["rect"].height) <= 40]
        seen = Counter()
        for w in page.get_text("words"):
            if not w[4].strip().isdigit() or len(w[4].strip()) > 2:
                continue
            c = fitz.Point((w[0] + w[2]) / 2, (w[1] + w[3]) / 2)
            best = None
            for d in small:
                r = d["rect"]
                if r.contains(c) and (best is None or
                                      r.get_area() < best["rect"].get_area()):
                    best = d
            if best is None:
                seen[(w[4], "no shape")] += 1
                continue
            kinds = Counter(it[0] for it in best["items"])
            seen[(w[4], f"l{kinds.get('l', 0)} c{kinds.get('c', 0)} "
                        f"re{kinds.get('re', 0)} "
                        f"{best['rect'].width:.0f}x{best['rect'].height:.0f}"
                        f" w{best.get('width') or 0:.2f} "
                        f"{'closed' if best.get('closePath') else 'open'}")] += 1
        for (num, shape), n in sorted(seen.items(),
                                      key=lambda kv: (int(kv[0][0]), kv[0][1])):
            print(f"{num:>3} x{n}  {shape}")
    return 0


def main(argv):
    import fitz
    args = list(argv)

    def opt(name, default):
        if name in args:
            i = args.index(name)
            v = args[i + 1]
            del args[i:i + 2]
            return v
        return default
    ppf = float(opt("--ppf", "7.2"))
    layer = opt("--layer", "")
    if layer:
        return by_layer(args, layer, ppf)
    if "--around" in args:
        args.remove("--around")
        return around(args)
    least = float(opt("--min", "20"))
    hits = sorted(glob.glob(os.path.join(ROOT, args[0])))
    if not hits:
        print("no file matches", args[0])
        return 1
    tmp = tempfile.mkdtemp(prefix="qs-lines-")
    with fitz.open(shutil.copy(hits[0], os.path.join(tmp, "s.pdf"))) as doc:
        page = doc[int(args[1]) - 1]
        pens = defaultdict(lambda: [0, 0.0, 0])
        small = defaultdict(int)
        for d in page.get_drawings():
            key = (tuple(round(c, 2) for c in (d.get("color") or ())),
                   round(d.get("width") or 0, 2), d.get("dashes") or "",
                   d.get("layer") or "")
            n = 0.0
            curves = 0
            for it in d["items"]:
                if it[0] == "l":
                    n += math.hypot(it[2].x - it[1].x, it[2].y - it[1].y)
                elif it[0] == "c":
                    n += math.hypot(it[4].x - it[1].x, it[4].y - it[1].y)
                    curves += 1
                elif it[0] in ("re", "qu"):
                    r = it[1] if it[0] == "re" else it[1].rect
                    n += 2 * (r.width + r.height)
            pens[key][0] += 1
            pens[key][1] += n
            pens[key][2] += curves
            r = d["rect"]
            if curves >= 2 and max(r.width, r.height) <= 12:
                small[(key[0], round(max(r.width, r.height), 1))] += 1
        print(f"page {args[1]}: {page.rect.width:.0f} x {page.rect.height:.0f}"
              f" pt, rotation {page.rotation}")
        for key, (cnt, n, cv) in sorted(pens.items(), key=lambda kv: -kv[1][1]):
            if n / ppf >= least:
                print(f"{n / ppf:9.1f} ft {cnt:6d} pcs {cv:6d} curves  "
                      f"col {key[0]} w {key[1]} dash '{key[2]}' "
                      f"layer '{key[3]}'")
        print("small round shapes:", sorted(small.items(),
                                            key=lambda kv: -kv[1])[:12])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
