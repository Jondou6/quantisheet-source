"""Try several close-up OCR settings on the scale area of one sheet
(read-only, in memory; prints text only):
python tools/diag_zoom_variants.py <glob> <page or sheet number>"""
import glob
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def tess(exe, png, psm, tessdata):
    env = dict(os.environ, OMP_THREAD_LIMIT="1")
    if tessdata:
        env["TESSDATA_PREFIX"] = tessdata
    out = subprocess.run([exe, png, "stdout", "-l", "eng", "--psm", str(psm)],
                         capture_output=True, timeout=300, env=env,
                         creationflags=getattr(subprocess,
                                               "CREATE_NO_WINDOW", 0))
    return out.stdout.decode("utf-8", "ignore")


def threshold(pix, cut):
    import fitz
    table = bytes(0 if v < cut else 255 for v in range(256))
    s = bytes(pix.samples).translate(table)
    return fitz.Pixmap(fitz.csGRAY, pix.width, pix.height, s, False)


def main(a):
    import fitz
    from app import acrobat, aitakeoff as ait, ocr as ocr_mod
    doc = fitz.open(sorted(glob.glob(os.path.join(ROOT, a[0])))[0])
    if a[1].isdigit():
        p = int(a[1]) - 1
    else:
        hits = [i for i in range(doc.page_count)
                if a[1] in doc[i].get_text()]
        print("pages with", a[1], [h + 1 for h in hits])
        p = hits[-1] if hits else 0
    if p in ait.ocr_needed(doc):
        acrobat.make_searchable(doc, [p], vertical=True)
    page = doc[p]
    print("page", p + 1, "rotation", page.rotation)
    exe, td = ocr_mod.find_tesseract(), acrobat.tessdata_dir()
    words = [w for w in page.get_text("words")
             if str(w[4]).upper().startswith("GRAPHIC")]
    for w in words[:2]:
        h = max(4.0, w[3] - w[1])
        b = fitz.Rect(w[0] - 12 * h, w[1] - 6 * h, w[2] + 24 * h,
                      w[3] + 6 * h)
        for clip in (b, (b * page.rotation_matrix) & page.rect):
            clip = clip & page.rect
            if clip.is_empty:
                continue
            for dpi in (400, 600, 800):
                z = dpi / 72.0
                pix = page.get_pixmap(matrix=fitz.Matrix(z, z), clip=clip,
                                      colorspace=fitz.csGRAY, alpha=False,
                                      annots=False)
                for name, px in (("gray", pix), ("bw160", threshold(pix, 160)),
                                 ("bw210", threshold(pix, 210))):
                    fd, png = tempfile.mkstemp(suffix=".png")
                    os.close(fd)
                    try:
                        px.save(png)
                        for psm in (6, 11, 12):
                            t = " | ".join(x.strip() for x in
                                           tess(exe, png, psm, td).splitlines()
                                           if x.strip())
                            print(f"{[round(c) for c in clip]} {dpi} {name} "
                                  f"psm{psm}: {t[:240]}")
                    finally:
                        os.remove(png)


if __name__ == "__main__":
    main(sys.argv[1:])
