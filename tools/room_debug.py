"""Trace the rooms on one sheet and draw them, to see why a room comes out
wrong (Nov 1: Collenton toilet rooms overlapping the corridor; HMB room
109 short under its benches).

    python tools/room_debug.py PLANS.pdf SHEET [ROOM ROOM ...]

SHEET is the sheet number (A-101) or a page number. ROOM: numbers to
report and crop to (113 114 117); none = every room. Works on a temp copy
of the PDF. Writes .run/room_debug.txt (each room: tag, trace, fill,
flags, overlaps) and .run/room_debug.png (the sheet near those rooms,
each outline in its own colour, labelled)."""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, ".run", "room_debug")

COLOURS = [(1, 0, 0), (0, 0.6, 0), (0, 0, 1), (1, 0.5, 0), (0.6, 0, 0.8),
           (0, 0.6, 0.7), (0.8, 0.6, 0), (0.9, 0, 0.5)]


def main(argv):
    argv = [a.strip('"') for a in argv]
    if len(argv) < 2:
        raise SystemExit(__doc__)
    src, sheet, want = argv[0], argv[1], {a.upper() for a in argv[2:]}
    import fitz
    from app import aitakeoff as ait, autotakeoff
    tmp = tempfile.mkdtemp(prefix="qs_room_dbg_")
    pdf = os.path.join(tmp, "plans.pdf")
    shutil.copy2(src, pdf)
    doc = fitz.open(pdf)
    rows = ait.plan_set(doc, lambda i, n: True)
    row = next((r for r in rows if str(r.get("number") or "").upper()
                == sheet.upper()), None)
    if row is None and sheet.isdigit():
        row = next((r for r in rows if r["page"] + 1 == int(sheet)), None)
    if row is None or not row.get("scale"):
        raise SystemExit(f"sheet {sheet}: not found or no scale")
    label, ppu, unit = row["scale"]
    pno = row["page"]
    info = {}
    found, missed = ait._full_glyph_boxes(lambda: autotakeoff.all_rooms(
        doc[pno], {"ppu": ppu, "unit": unit}, info=info))()

    def num(r):
        return str(r.get("number") or "").upper()

    pick = [r for r in found if not want or num(r) in want or
            any(w in str(r.get("name") or "").upper() for w in want)]
    lines = [f"{os.path.basename(src)} sheet {row['number']} (page "
             f"{pno + 1}) scale {label} - {len(found)} rooms, "
             f"{len(missed)} missed, overlaps {info.get('overlaps')}", ""]
    keys = ("name", "number", "sqft", "net_sf", "tag_sf", "tag_diff_sf",
            "tag_diff_pct", "face_fill_sf", "door", "perimeter_lf",
            "trace_confidence", "review", "overlaps", "flags", "via")
    for r in pick:
        lines.append(" | ".join(f"{k}={r.get(k)!r}" for k in keys
                                if r.get(k) not in (None, "", [])))
        lines.append("   pts=" + repr([(round(p[0], 1), round(p[1], 1))
                                       for p in r.get("pts") or []]))
    for t in missed:
        if not want or str(t.get("number") or "").upper() in want:
            lines.append(f"MISSED: {t.get('name')!r} {t.get('number')!r} "
                         f"tag {t.get('sf')!r}")
    txt = "\n".join(lines)
    with open(OUT + ".txt", "w", encoding="utf-8") as f:
        f.write(txt)
    print(txt)
    # picture: the sheet around the picked rooms, outlines drawn
    page = doc[pno]
    pts = [p for r in pick for p in r.get("pts") or []]
    if pts:
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        pad = 40
        clip = fitz.Rect(min(xs) - pad, min(ys) - pad, max(xs) + pad,
                         max(ys) + pad) & page.rect
    else:
        clip = page.rect
    for i, r in enumerate(pick):
        c = COLOURS[i % len(COLOURS)]
        p = [fitz.Point(*q) for q in r.get("pts") or []]
        if len(p) >= 3:
            sh = page.new_shape()
            sh.draw_polyline(p + [p[0]])
            sh.finish(color=c, width=1.2, fill=c, fill_opacity=0.12)
            sh.commit()
            page.insert_text(p[0] + (2, 8), f"{num(r) or r.get('name')} "
                             f"{r.get('sqft', 0):.0f}sf", fontsize=6,
                             color=c)
    zoom = min(4.0, 2400 / max(clip.width, clip.height, 1))
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip)
    pix.save(OUT + ".png")
    doc.close()
    shutil.rmtree(tmp, ignore_errors=True)
    print("wrote", OUT + ".txt", OUT + ".png")


if __name__ == "__main__":
    main(sys.argv[1:])
