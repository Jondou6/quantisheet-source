"""Look at the TYP marks on a drawing page (read-only; drawings stay on
this PC): python tools/diag_typ.py PDF PAGE(1-based)
Prints each TYP block, the drawn shapes near it with their signature and
how often each signature appears on the page, and writes a crop around
each TYP mark to .run/typ_crop_N.png for checking."""
import collections
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def sig(d):
    kinds = [it[0] for it in d["items"]]
    r = d["rect"]
    return (kinds.count("l"), kinds.count("c"), kinds.count("re"),
            int(round(r.width)), int(round(r.height)), bool(d.get("fill")))


def main(path, pno):
    import fitz
    from app import callouts as co
    import glob
    path = sorted(glob.glob(os.path.join(ROOT, path)))[0]
    doc = fitz.open(path)
    if pno == "auto":
        for i, pg in enumerate(doc):
            t = pg.get_text().upper()
            if "GROUND ROD" in t and "TYP" in t and "SYMBOL" in t:
                print("candidate page", i + 1)
                pno = str(i + 1)
    page = doc[int(pno) - 1]
    blocks = co.page_blocks(page)
    rot = page.rotation_matrix
    drs = []
    for d in page.get_drawings():
        r = d["rect"] * rot
        r.normalize()
        if max(r.width, r.height) <= 80:
            d["rect"] = r
            drs.append(d)
    allsig = collections.Counter(sig(d) for d in drs)
    print("page", pno, "size", page.rect, "rotation", page.rotation,
          "small drawings", len(drs))
    k = 0
    for lines, rect in blocks:
        if any(ln.strip().upper().rstrip(".") in ("TYP", "TYPICAL")
               for ln in lines) and len(lines) <= 5:
            k += 1
            R = fitz.Rect(rect)
            print("\nTYP block", k, lines, [round(v) for v in rect])
            near = [d for d in drs if d["rect"].intersects(R + (-60, -60, 60, 60))]
            c = collections.Counter(sig(d) for d in near)
            for s, n in c.most_common(12):
                print("   near", n, "sig", s, "on page", allsig[s])
            clip = (R + (-150, -150, 150, 150)) & page.rect
            pix = page.get_pixmap(clip=clip, dpi=150)
            pix.save(os.path.join(ROOT, ".run", f"typ_crop_{k}.png"))
    print("\nkeyed rows:")
    from app import callout_scope as cs
    syms = cs.page_symbols(page)
    dbg = []
    tc = cs.typical_counter(page, syms, dbg)
    for n in range(1, 30):
        got = tc(n)
        if dbg or got:
            print("TYP note", n, got)
            for x in dbg:
                print("    ", x)
        dbg.clear()
    for r in cs.keyed(blocks, "", None, syms, cs.typical_counter(page, syms)):
        print("  ", r["qty"], r["unit"], r["what"][:60], r["check"][-1][:90])


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
