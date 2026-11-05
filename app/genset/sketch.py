"""A sketch gives the footprint's proportions (and room names, if they are
typed text on a PDF). Nothing else is traced in v1."""
import logging
import os

log = logging.getLogger(__name__)


def _image(path, page=0):
    """The sketch as a grey numpy image (PNG/JPG, or a PDF page at 150
    dpi), plus the fitz page when it was a PDF."""
    import cv2
    import numpy as np
    if path.lower().endswith(".pdf"):
        import fitz
        doc = fitz.open(path)
        pg = doc[max(0, min(page, doc.page_count - 1))]
        pix = pg.get_pixmap(dpi=150, colorspace=fitz.csGRAY, alpha=False)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
            pix.height, pix.width).copy()
        return img, pg, doc
    data = np.fromfile(path, dtype=np.uint8)            # unicode paths
    img = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
    return img, None, None


def footprint_from(path, page=0):
    """(ratio >= 1, room names, warning or None). ratio is None when no
    footprint could be read."""
    try:
        import cv2
        img, pg, doc = _image(path, page)
    except Exception as e:                                # noqa: BLE001
        return None, [], f"Sketch not readable — footprint from SF. ({e})"
    try:
        return _read(img, pg)
    finally:
        if doc is not None:
            doc.close()


def _read(img, pg):
    import cv2
    if img is None or img.size == 0:
        return None, [], "Sketch not readable — footprint from SF."
    names = []
    if pg is not None:
        try:
            from .. import autotakeoff
            names = [r["name"] for r in autotakeoff.room_labels(pg)][:20]
        except Exception:                                 # noqa: BLE001
            log.debug("room names from the sketch failed", exc_info=True)
    h, w = img.shape[:2]
    blur = cv2.GaussianBlur(img, (5, 5), 0)
    edges = cv2.Canny(blur, 40, 120)
    edges = cv2.dilate(edges, None, iterations=2)
    cs, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL,
                             cv2.CHAIN_APPROX_SIMPLE)
    best = None
    for c in cs:
        peri = cv2.arcLength(c, True)
        ap = cv2.approxPolyDP(c, 0.03 * peri, True)
        area = cv2.contourArea(ap)
        if len(ap) == 4 and area >= 0.15 * w * h and \
                (best is None or area > best[0]):
            best = (area, ap)
    if best is None:
        return None, names, ("Sketch not readable — footprint from "
                             "SF.")
    (cx, cy), (rw, rh), _ = cv2.minAreaRect(best[1])
    a, b = max(rw, rh), max(1.0, min(rw, rh))
    return round(a / b, 3), names, None


def describe(path):
    return os.path.basename(path) if path else None
