"""Count from a picture (Nov 4, Jon: go ahead with the photo item).

Takeoff > Count From a Picture: instead of boxing a sample on the sheet,
give a picture of the symbol - a snip from a legend, a cut sheet, another
plan set, or a phone photo of a printed sheet. The picture is cleaned up
(ink only, cropped, black on white like a drawing), tried at several
sizes on the current sheet to find the size the drawing uses, then
searched for with the same whole-symbol matching as Count Symbol, and
every hit goes to the usual review list before anything is counted.

A photo of the physical product itself (a light fixture, a valve) looks
nothing like its plan symbol; matching those would need a trained model,
which this doesn't use. Whole-symbol matching only - no piece matching,
no colour or size pre-filter (patent design rules); honours the
picture_count switch.
"""
import logging

try:
    import cv2
    import numpy as np
except ImportError:                                       # pragma: no cover
    cv2 = np = None

log = logging.getLogger(__name__)

# the symbol's longest side, in pixels of the 2x render the search uses
# (about 6 to 45 points on the sheet): a coarse sweep finds the size
# region, then every pixel size around the best ones is tried
COARSE_PX = tuple(sorted({int(round(12 * 1.06 ** k)) for k in range(36)}))
FINE_SPAN = 3
TOP_SIZES = 3
MIN_SCORE = 0.82


def clean(image_bytes):
    """The picture as a drawing-like template: grey, ink black on white,
    cropped to the ink with a small margin. Raises ValueError."""
    if cv2 is None:
        raise RuntimeError("Counting from a picture needs numpy and opencv.")
    img = cv2.imdecode(np.frombuffer(image_bytes, np.uint8),
                       cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError("That file isn't a picture QuantiSheet can read.")
    h, w = img.shape
    if max(h, w) > 1600:                 # a phone photo: work smaller
        f = 1600.0 / max(h, w)
        img = cv2.resize(img, (int(w * f), int(h * f)),
                         interpolation=cv2.INTER_AREA)
    # even out lighting (photos of paper), then black ink on white
    bg = cv2.medianBlur(img, 31) if min(img.shape) > 40 else img
    norm = cv2.divide(img, bg, scale=255) if bg is not img else img
    _t, ink = cv2.threshold(norm, 0, 255,
                            cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    ys, xs = np.nonzero(ink)
    if len(xs) < 10:
        raise ValueError("No symbol found in the picture - crop it to the "
                         "symbol on a light background.")
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    pad = max(2, int(0.06 * max(x1 - x0, y1 - y0)))
    crop = 255 - ink[max(0, y0 - pad):y1 + pad + 1,
                     max(0, x0 - pad):x1 + pad + 1]
    return crop


def _skeleton(b):
    b = b.copy()
    out = np.zeros_like(b)
    el = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    while cv2.countNonZero(b):
        e = cv2.erode(b, el)
        out |= cv2.subtract(b, cv2.dilate(e, el))
        b = e
    return out


def at_size(tpl, longest_px):
    """The template at a size, its lines redrawn about as thick as a
    drawing's (a picture's strokes are rarely the drawing's weight)."""
    ink = (tpl < 128).astype(np.uint8) * 255
    h, w = ink.shape
    f = float(longest_px) / max(h, w)
    small = cv2.resize(ink, (max(4, int(round(w * f))),
                             max(4, int(round(h * f)))),
                       interpolation=cv2.INTER_AREA)
    small = (small > 60).astype(np.uint8) * 255
    line = cv2.dilate(_skeleton(small), np.ones((2, 2), np.uint8))
    return 255 - line


def png(tpl):
    return cv2.imencode(".png", tpl)[1].tobytes()


def _page_gray(doc, page):
    import fitz
    pix = doc[page].get_pixmap(matrix=fitz.Matrix(2, 2),
                               colorspace=fitz.csGRAY, alpha=False)
    return np.frombuffer(pix.samples, np.uint8).reshape(
        pix.height, pix.stride)[:, :pix.width].copy()


def coarse_sizes(gray, tpl, sizes=COARSE_PX, top=TOP_SIZES):
    """The sizes whose best raw match on the sheet (at half resolution,
    upright and turned 90) is highest - where to look closely."""
    half = cv2.resize(gray, (gray.shape[1] // 2, gray.shape[0] // 2),
                      interpolation=cv2.INTER_AREA)
    scored = []
    for px in sizes:
        t = at_size(tpl, px)
        t2 = cv2.resize(t, (max(4, t.shape[1] // 2), max(4, t.shape[0] // 2)),
                        interpolation=cv2.INTER_AREA)
        best = 0.0
        for v in (t2, cv2.rotate(t2, cv2.ROTATE_90_CLOCKWISE)):
            if v.shape[0] >= half.shape[0] or v.shape[1] >= half.shape[1]:
                continue
            best = max(best, float(cv2.matchTemplate(
                half, v, cv2.TM_CCOEFF_NORMED).max()))
        scored.append((best, px))
    scored.sort(reverse=True)
    return [px for _s, px in scored[:top]]


def best_size(doc, tpl, page, find=None, gray=None):
    """The size (longest side, px) that matches best on `page`: most
    good hits, then the best mean score. (size, hits) or (None, [])."""
    from . import autocount
    gray = _page_gray(doc, page) if gray is None else gray
    cache = {page: gray}
    find = find or (lambda b: autocount.find_symbols(
        doc, b, threshold=MIN_SCORE, pages={page}, turns=True, cache=cache))
    tried = set()
    best, best_key, best_hits = None, (0, 0.0), []
    for c in coarse_sizes(gray, tpl):
        for px in range(max(8, c - FINE_SPAN), c + FINE_SPAN + 1):
            if px in tried:
                continue
            tried.add(px)
            try:
                hits = find(png(at_size(tpl, px)))
            except Exception:                             # noqa: BLE001
                log.debug("size %s not searched", px, exc_info=True)
                continue
            good = [h for h in hits if h.get("score", 0) >= MIN_SCORE]
            if not good:
                continue
            key = (len(good), sum(h["score"] for h in good) / len(good))
            if key > best_key:
                best, best_key, best_hits = px, key, good
    return best, best_hits


def template_for(doc, image_bytes, page):
    """(PNG template at the drawing's size, size px, hits on `page`)."""
    tpl = clean(image_bytes)
    px, hits = best_size(doc, tpl, page)
    if px is None:
        raise ValueError("The picture wasn't found on this sheet at any "
                         "size. Go to a sheet that shows the symbol, or "
                         "crop the picture closer to it.")
    return png(at_size(tpl, px)), px, hits
