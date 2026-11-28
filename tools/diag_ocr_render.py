"""Where the whole-sheet OCR's time goes on one sheet, read-only:
python tools/diag_ocr_render.py <glob> [page number]

Times drawing the tiles (page.get_pixmap per tile, a display list, or the
whole sheet at once), saving them (PNG or PGM) and tesseract."""
import glob
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main(a):
    import fitz
    from app import acrobat, aitakeoff as ait, ocr as ocr_mod
    doc = fitz.open(sorted(glob.glob(os.path.join(ROOT, a[0])))[0])
    pno = int(a[1]) - 1 if len(a) > 1 else sorted(ait.ocr_needed(doc))[0]
    page = doc[pno]
    dpi = acrobat.ocr_dpi(page)
    zoom = dpi / 72.0
    tile = acrobat.TILE_PX / zoom
    ov = acrobat.TILE_OVERLAP / zoom
    R = page.rect
    clips = []
    y = R.y0
    while y < R.y1 - 1:
        x = R.x0
        while x < R.x1 - 1:
            core = fitz.Rect(x, y, min(x + tile, R.x1), min(y + tile, R.y1))
            clips.append(fitz.Rect(core.x0 - ov, core.y0 - ov, core.x1 + ov,
                                   core.y1 + ov) & R)
            x += tile
        y += tile
    m = fitz.Matrix(zoom, zoom)
    print(f"page {pno + 1}: {R.width / 72:.0f}x{R.height / 72:.0f} in, "
          f"{dpi} dpi, {len(clips)} tiles")
    t = time.time()
    pixes = [page.get_pixmap(matrix=m, clip=c, colorspace=fitz.csGRAY,
                             alpha=False, annots=False) for c in clips]
    print(f"get_pixmap per tile: {time.time() - t:.2f}s")
    t = time.time()
    dl = page.get_displaylist(annots=False)
    print(f"  display list made: {time.time() - t:.2f}s")
    t = time.time()
    for c in clips:
        dl.get_pixmap(matrix=m, clip=c, colorspace=fitz.csGRAY, alpha=False)
    print(f"display list per tile: {time.time() - t:.2f}s")
    t = time.time()
    whole = page.get_pixmap(matrix=m, colorspace=fitz.csGRAY, alpha=False,
                            annots=False)
    print(f"whole sheet once: {time.time() - t:.2f}s "
          f"({whole.width}x{whole.height}, {len(whole.samples) >> 20} MB)")
    d = tempfile.mkdtemp(prefix="qs_diag_")
    for ext in ("png", "pgm"):
        t = time.time()
        for i, p in enumerate(pixes):
            p.save(os.path.join(d, f"t{i}.{ext}"))
        print(f"save {ext}: {time.time() - t:.2f}s")
    blank = 0
    for p in pixes:
        s = p.samples
        dark = len(s) - len(s.translate(None, bytes(range(128))))
        blank += dark < 50
    print(f"blank tiles (under 50 dark pixels): {blank} of {len(pixes)}")
    exe = ocr_mod.find_tesseract()
    for ext in ("png", "pgm"):
        t = time.time()
        n = 0
        for i in range(min(4, len(pixes))):
            n += len(acrobat._tess_tile(exe, os.path.join(d, f"t{i}.{ext}"),
                                        "eng", acrobat.tessdata_dir()))
        print(f"tesseract on 4 {ext} tiles, one at a time: "
              f"{time.time() - t:.2f}s ({n} words)")
    print("pixmap resolution:", pixes[0].xres, pixes[0].yres)
    import subprocess
    same = 0
    for i in range(min(6, len(pixes))):
        outs = []
        for ext, extra in (("png", []), ("pgm", ["--dpi",
                                                 str(pixes[0].xres)])):
            r = subprocess.run([exe, os.path.join(d, f"t{i}.{ext}"),
                                "stdout", "-l", "eng", "--psm", "11"] +
                               extra + ["tsv"], capture_output=True,
                               env=dict(os.environ, OMP_THREAD_LIMIT="1",
                                        TESSDATA_PREFIX=acrobat.tessdata_dir()
                                        or ""))
            outs.append(r.stdout)
        same += outs[0] == outs[1]
    print(f"pgm with --dpi gives the same tesseract output as png: "
          f"{same} of {min(6, len(pixes))} tiles")
    import shutil
    shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    main(sys.argv[1:])
