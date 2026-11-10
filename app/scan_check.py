"""Check Scan Quality (Document menu, Nov 5): before trusting OCR text,
say which scanned pages are too coarse, tilted, blank or solid black, and
whether the OCR language pack is installed - using app/ocr_quality.

A page counts as a scan when one picture covers most of it. Its DPI is
the picture's pixels over the inches it is drawn at (the lower of the
two directions). Tilt and ink are measured on a 150 DPI grey render of
the page, so a huge scan is never decoded at full size. Nothing is
changed in the PDF and no OCR is run.
"""
import fitz

from . import ocr_quality

RENDER_DPI = 150
SCAN_COVER = 0.5            # a picture over half the page: a scanned page
LIMIT = 30                  # pages per check (a plan set can be hundreds)


def _scan_image(page):
    """(dpi, picture rect) of the picture that makes this page a scan, or
    None."""
    area = abs(page.rect)
    best = None
    for info in page.get_image_info(xrefs=True):
        r = fitz.Rect(info["bbox"]) & page.rect
        if r.is_empty or not info.get("width"):
            continue
        if best is None or abs(r) > abs(best[1]):
            best = (info, r)
    if best is None or abs(best[1]) < SCAN_COVER * area:
        return None
    info, _r = best
    full = fitz.Rect(info["bbox"])
    # the picture may be drawn turned (a landscape scan on a portrait
    # page): compare long side to long side
    px = sorted((info["width"], info["height"]))
    inch = sorted((full.width / 72.0, full.height / 72.0))
    if inch[0] <= 0:
        return None
    dpi = min(px[0] / inch[0], px[1] / inch[1])
    return round(dpi), best[1]


def _gray(page):
    import numpy as np
    pix = page.get_pixmap(dpi=RENDER_DPI, colorspace=fitz.csGRAY,
                          alpha=False)
    arr = np.frombuffer(pix.samples, dtype=np.uint8)
    return arr.reshape(pix.height, pix.stride)[:, :pix.width].copy()


def check_page(page):
    """{"page", "scan", "dpi", "skew", "reasons"} for one page."""
    out = {"page": page.number + 1, "scan": False, "dpi": None,
           "skew": None, "reasons": []}
    found = _scan_image(page)
    if found is None:
        return out
    out["scan"] = True
    dpi, _rect = found
    try:
        chk = ocr_quality.check_image(_gray(page), dpi=dpi)
    except (ocr_quality.ScanError, ValueError) as e:
        out["dpi"] = dpi
        out["reasons"] = [str(e)]
        return out
    out["dpi"], out["skew"] = chk.dpi, chk.skew_degrees
    out["reasons"] = [f.reason for f in chk.flags]
    return out


def check(doc, pages=None, limit=LIMIT, languages=None, needed="eng"):
    """Check the pages (0-based numbers, default all, at most `limit`).
    `languages` is passed through to ocr_quality.language_flags (None:
    ask the installed Tesseract)."""
    pages = list(range(doc.page_count) if pages is None else pages)
    todo, skipped = pages[:limit], max(len(pages) - limit, 0)
    rows = [check_page(doc[i]) for i in todo]
    if languages is None:
        languages = ocr_quality.installed_languages()
    lang = [f.reason for f in ocr_quality.language_flags(languages, needed)]
    scans = [r for r in rows if r["scan"]]
    poor = [r for r in scans if r["reasons"]]
    return {"pages": rows, "languages": lang, "skipped": skipped,
            "scans": len(scans), "poor": len(poor)}


def summary(res):
    if not res["scans"]:
        head = ("No scanned pages here - the text is already in the PDF, "
                "so there is nothing for OCR to misread.")
    elif not res["poor"]:
        head = (f"{res['scans']} scanned page(s), all good enough to read.")
    else:
        head = (f"{res['poor']} of {res['scans']} scanned page(s) may read "
                "badly - see the reasons below. Rescanning them at 300 DPI "
                "gives the best text.")
    out = [head]
    if res["skipped"]:
        out.append(f"Only the first {LIMIT} pages were checked "
                   f"({res['skipped']} more not checked).")
    out += res["languages"]
    return out
