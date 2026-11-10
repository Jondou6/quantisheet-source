"""Draw what AI Takeoff found for some rooms over the sheet (Nov 5, HMB
109): the room outline in green on a crop round its tag, to see which
floor it leaves out. Read-only; writes .run/room_overlay/<name>.png.

    python tools/room_overlay.py FILE.pdf PAGE(1-based) NUM[,NUM] [RADIUS_FT]"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import fitz                                                   # noqa: E402

OUT = os.path.join(ROOT, ".run", "room_overlay")


def main():
    path, p = sys.argv[1].strip('"'), int(sys.argv[2])
    want = [n.strip() for n in sys.argv[3].split(",")]
    rad = float(sys.argv[4]) if len(sys.argv) > 4 else 12.0
    os.makedirs(OUT, exist_ok=True)
    from app import autotakeoff as at
    prev = fitz.TOOLS.set_small_glyph_heights()
    fitz.TOOLS.set_small_glyph_heights(False)
    doc = fitz.open(path)
    page = doc[p - 1]
    found, missed = at.all_rooms(at.cached_page(page),
                                 {"ppu": 18.0, "unit": "ft"})
    fitz.TOOLS.set_small_glyph_heights(prev)
    info = {}
    for f in found:
        num = str(f.get("number") or f.get("name", "")[-3:])
        if num not in want:
            continue
        pts = [fitz.Point(x, y) for x, y in f["pts"]]
        xs, ys = [q.x for q in pts], [q.y for q in pts]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        box = fitz.Rect(cx - rad * 18, cy - rad * 18, cx + rad * 18,
                        cy + rad * 18)
        shape = page.new_shape()
        shape.draw_polyline(pts + [pts[0]])
        shape.finish(color=(0, 0.7, 0), fill=(0, 0.8, 0), fill_opacity=0.35,
                     width=1.5)
        shape.commit()
        page.get_pixmap(clip=box, dpi=200).save(
            os.path.join(OUT, f"{num}.png"))
        info[num] = {"sqft": round(f["sqft"], 1), "points": len(pts),
                     "via": f.get("via"), "face_fill_sf": f.get("face_fill_sf"),
                     "net_sf": f.get("net_sf"), "flags": f.get("flags"),
                     "review": f.get("review"),
                     "trace_confidence": f.get("trace_confidence"),
                     "box_pt": [round(v, 1) for v in box]}
    with open(os.path.join(OUT, "rooms.json"), "w", encoding="utf-8") as fh:
        json.dump(info, fh, indent=1)
    print(json.dumps(info, indent=1))


if __name__ == "__main__":
    main()
