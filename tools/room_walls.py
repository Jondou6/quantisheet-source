"""Independent check of a room's floor area from the drawing itself (Nov
5, HMB 108/112): the wall-layer lines round a room tag, in feet from the
tag, and the dimension strings near it - for a person to read, not the
takeoff's own fill. Read-only.

    python tools/room_walls.py FILE.pdf PAGE(1-based) TAG[,TAG] [RADIUS_FT]
Writes .run/room_walls/<tag>.txt and a 4x crop PNG with a 1 ft grid."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import fitz                                                   # noqa: E402

PPF = 18.0                                   # 1/4" = 1'-0": 18 pt a foot
OUT = os.path.join(ROOT, ".run", "room_walls")


def main():
    path, p = sys.argv[1].strip('"'), int(sys.argv[2])
    tags = [t.strip() for t in sys.argv[3].split(",")]
    rad = float(sys.argv[4]) if len(sys.argv) > 4 else 16.0
    os.makedirs(OUT, exist_ok=True)
    fitz.TOOLS.set_small_glyph_heights(False)
    doc = fitz.open(path)
    page = doc[p - 1]
    words = page.get_text("words")
    from app import autotakeoff as at
    layers = set(at.wall_layers(page) or [])
    draws = page.get_drawings()
    for tag in tags:
        hits = [w for w in words if w[4] == tag]
        lines = [f"tag {tag}: {len(hits)} hit(s); wall layers {sorted(layers)}"]
        for w in hits:
            cx, cy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
            lines.append(f"  at pt ({cx:.1f}, {cy:.1f})")
            box = fitz.Rect(cx - rad * PPF, cy - rad * PPF, cx + rad * PPF,
                            cy + rad * PPF)
            for ww in words:
                r = fitz.Rect(ww[:4])
                if r.intersects(box) and any(ch in ww[4] for ch in "'\""):
                    lines.append(f"  text {ww[4]!r} at "
                                 f"({(r.x0 - cx) / PPF:+.2f}, "
                                 f"{(r.y0 - cy) / PPF:+.2f}) ft")
            segs = []
            for d in draws:
                if (d.get("layer") or "") not in layers:
                    continue
                if not fitz.Rect(d["rect"]).intersects(box):
                    continue
                for it in d["items"]:
                    if it[0] == "l":
                        a, b = it[1], it[2]
                        segs.append((d.get("layer"), (a.x - cx) / PPF,
                                     (a.y - cy) / PPF, (b.x - cx) / PPF,
                                     (b.y - cy) / PPF, d.get("fill")
                                     is not None))
                    elif it[0] == "re":
                        r = it[1]
                        segs.append((d.get("layer"), (r.x0 - cx) / PPF,
                                     (r.y0 - cy) / PPF, (r.x1 - cx) / PPF,
                                     (r.y1 - cy) / PPF, "rect"))
            lines.append(f"  {len(segs)} wall-layer segments within "
                         f"{rad} ft (x right, y down, feet from the tag):")
            for s in sorted(segs, key=lambda s: (round(s[2], 1),
                                                 round(s[1], 1))):
                if abs(s[1] - s[3]) < 0.02 or abs(s[2] - s[4]) < 0.02:
                    kind = "V" if abs(s[1] - s[3]) < 0.02 else "H"
                else:
                    kind = "D"
                lines.append(f"    {kind} {s[0]:<12} ({s[1]:+7.2f},{s[2]:+7.2f})"
                             f" -> ({s[3]:+7.2f},{s[4]:+7.2f})"
                             f"{'  fill' if s[5] is True else ''}"
                             f"{'  rect' if s[5] == 'rect' else ''}")
            pix = page.get_pixmap(clip=box, dpi=288)
            pix.save(os.path.join(OUT, f"{tag}.png"))
        with open(os.path.join(OUT, f"{tag}.txt"), "w",
                  encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print("\n".join(lines[:4]), f"... -> {tag}.txt")


if __name__ == "__main__":
    main()
