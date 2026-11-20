"""How invisible text lands on a rotated page (made-up page, read-only)."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main():
    import fitz
    for rot in (0, 90, 270):
        d = fitz.open()
        p = d.new_page(width=2448, height=1584)
        p.set_rotation(rot)
        target = fitz.Rect(100, 200, 300, 230)          # display coords
        font = fitz.Font("helv")
        # A: TextWriter in display coords + morph to unrotated
        tw = fitz.TextWriter(p.rect)
        tw.append((target.x0, target.y1 - 6), "ALPHA", font=font,
                  fontsize=24)
        tw.write_text(p, render_mode=3,
                      morph=(fitz.Point(0, 0), p.derotation_matrix))
        # B: plain TextWriter, display coords as given
        tw2 = fitz.TextWriter(p.rect)
        tw2.append((target.x0, target.y1 + 94), "BRAVO", font=font,
                   fontsize=24)
        tw2.write_text(p, render_mode=3)
        for w in p.get_text("words"):
            print(rot, w[4], [round(v) for v in w[:4]],
                  "dir", [ (round(l["dir"][0]), round(l["dir"][1]))
                           for b in p.get_text("dict")["blocks"]
                           for l in b.get("lines", [])
                           if any(s["text"].strip() == w[4]
                                  for s in l["spans"])][:1])


if __name__ == "__main__":
    main()
