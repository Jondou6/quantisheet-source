"""How sure the AI is of a sheet's scale, and where on the sheet it read it
(AI Takeoff v3, Oct 31 2026).

    evidence(page, scale, source="text", dpi=None) -> {
        "score": 0-100, "reasons": [str], "rect": [x0, y0, x1, y1] | None,
        "text": the printed words it came from, "review": bool}
    crop_png(page, rect, zoom=3.0) -> PNG bytes of the scale text, padded

Inputs: the sheet's scale as plan_set() chose it (label, points per unit,
unit), the sheet's text lines with their boxes, its dimension strings next
to drawn lines (autoscale.dimension_scale), and how the sheet was read
(vector text, OCR, a scan's DPI).

Steps:
1. Find the printed words: every text line (and line + next line, for a
   scale split over two lines) that reads as the same scale. The one on or
   just under a line saying SCALE wins; else the first. Its box is the
   evidence crop.
2. Score it from what is on the sheet (each step is a reason line):
   start 60; written next to the word SCALE +15; printed more than once
   +5; dimension strings measure at this scale (3 or more agree within
   3%) +25; they measure at another scale written on this sheet -15 (an
   enlarged view, or a print at another size); they measure at no written
   scale -35; other scales on this sheet -10; the words can't be found -15;
   read by OCR x0.6; scanned under 150 DPI x0.5. A scale a person set on
   the sheet is 100.
3. Under REVIEW_BELOW (60) the scale goes to review: the sheet's lengths
   and areas wait in the review queue (counts don't depend on scale).

Failure points: a sheet with no text layer and no OCR (no evidence, score
0); several plan views at different scales (the smallest is used and
the score drops); dimension strings that pick up stray lines (needs 3
agreeing before it adds confidence).

DESIGN RULE (patent review): the scale comes from printed scale text and
is checked against printed dimension strings only - never by counting
raster pixels along something of known length.
"""
import re

REVIEW_BELOW = 60
_SCALE_WORD = re.compile(r"\bSCALE\b", re.I)


def _chars(page):
    """The page's text exactly as sheets.page_lines() joins it (one printed
    line per string, spans joined by a space), and each character's box
    (None for the joining spaces / line breaks)."""
    import fitz
    try:
        d = page.get_text("rawdict")
    except Exception:                                    # noqa: BLE001
        return "", []
    text, boxes = [], []
    for b in d.get("blocks", []):
        for ln in b.get("lines", []):
            chars = []
            for k, sp in enumerate(ln.get("spans", [])):
                if k:
                    chars.append((" ", None))
                for ch in sp.get("chars", []):
                    chars.append((ch.get("c", ""), fitz.Rect(ch["bbox"])))
            t = "".join(c for c, _b in chars)
            lead = len(t) - len(t.lstrip())
            t = t.strip()
            if not t:
                continue
            if text:
                text.append("\n")
                boxes.append(None)
            text.append(t)
            boxes += [bx for _c, bx in chars[lead:lead + len(t)]]
    return "".join(text), boxes


def _same(f, scale):
    return f[1] == scale[2] and abs(f[0] - scale[1]) <= 0.005 * scale[1]


def _scale_word_beside(text, boxes, r):
    """A title block often prints SCALE as a label in its own box, beside
    or just above the value: the word SCALE within three text heights of
    the printed scale counts as next to it."""
    import fitz
    h = max(4.0, min(r.width, r.height))
    for m in _SCALE_WORD.finditer(text):
        rs = [b for b in boxes[m.start():m.end()] if b is not None]
        if not rs:
            continue
        w = fitz.Rect(rs[0])
        for b in rs[1:]:
            w |= b
        dx = max(w.x0 - r.x1, r.x0 - w.x1, 0)
        dy = max(w.y0 - r.y1, r.y0 - w.y1, 0)
        if (dx * dx + dy * dy) ** 0.5 <= 3 * h:
            return True
    return False


def locate(page, scale, chars=None):
    """(rect, text, hits, near_word, others): where `scale` is printed -
    the box round the printed words (with a SCALE: word just before it on
    the same line), the words, how many times it is printed, whether the
    word SCALE is on its line or the line above, and how many other
    scales the sheet prints."""
    import fitz
    from . import takeoff
    text, boxes = _chars(page) if chars is None else chars
    hits, others = [], set()
    for st, en, label, ppu, unit, near in takeoff.scale_spans(text):
        if not _same((ppu, unit), scale):
            others.add((round(ppu, 3), unit))
            continue
        line0 = text.rfind("\n", 0, st) + 1
        pre = text[line0:st]
        k = pre.upper().rfind("SCALE")
        if k >= 0 and len(pre) - k <= 14:
            st = line0 + k
        rs = [b for b in boxes[st:en] if b is not None]
        if not rs:
            continue
        r = fitz.Rect(rs[0])
        for b in rs[1:]:
            r |= b
        if not near:
            near = _scale_word_beside(text, boxes, r)
        words = " ".join(text[st:en].split())
        hits.append((not near, len(hits), r, words, near))
    if not hits:
        return None, "", 0, False, len(others)
    best = min(hits, key=lambda h: (h[0], h[1]))
    return best[2], best[3], len(hits), best[4], len(others)


def chars_from_words(words):
    """OCR words ({"text", "rect"}) as _chars() text and boxes: rebuilt
    into lines top to bottom, each character boxed by its word."""
    import fitz
    ws = sorted(words, key=lambda w: ((w["rect"].y0 + w["rect"].y1) / 2,
                                      w["rect"].x0))
    lines, cur, cy, ch = [], [], None, 0
    for w in ws:
        y = (w["rect"].y0 + w["rect"].y1) / 2
        h = max(1.0, w["rect"].height)
        if cy is not None and abs(y - cy) > 0.6 * max(h, ch):
            lines.append(cur)
            cur = []
        if not cur:
            cy, ch = y, h
        cur.append(w)
    if cur:
        lines.append(cur)
    text, boxes = [], []
    for ln in lines:
        if text:
            text.append("\n")
            boxes.append(None)
        for k, w in enumerate(sorted(ln, key=lambda w: w["rect"].x0)):
            if k:
                text.append(" ")
                boxes.append(None)
            text.append(w["text"])
            boxes += [fitz.Rect(w["rect"])] * len(w["text"])
    return "".join(text), boxes


def evidence(page, scale, source="text", dpi=None, dims=None, user=False,
             ocr_words=None):
    """How sure (0-100) and where: see the module notes. `source`: "text"
    (the sheet's text layer), "ocr" (read from a scan: pass the OCR words)
    or "scan" (a scan with nothing read)."""
    if not scale:
        why = ["no scale read on this sheet"]
        if source in ("scan", "ocr"):
            why = ["scanned sheet - no text layer to read the scale from; "
                   "set it by hand (Calibrate) before measuring"]
            if dpi:
                why.append(f"scanned at about {dpi:.0f} DPI" +
                           (" - under 150 DPI" if dpi < 150 else ""))
        return {"score": 0, "reasons": why, "rect": None, "text": "",
                "review": True}
    if user:
        return {"score": 100, "reasons": ["set on the sheet by a person"],
                "rect": None, "text": scale[0], "review": False}
    reasons = []
    chars = chars_from_words(ocr_words or []) if source == "ocr" else \
        _chars(page)
    rect, text, hits, near, others = locate(page, scale, chars) \
        if chars[0] else (None, "", 0, False, 0)
    s = 60
    reasons.append(f"read '{scale[0]}' from the sheet's text" if source !=
                   "ocr" else f"read '{scale[0]}' by OCR")
    if near:
        s += 15
        reasons.append("printed next to the word SCALE (+15)")
    if hits > 1:
        s += 5
        reasons.append(f"printed {hits} times on the sheet (+5)")
    if rect is None:
        s -= 15
        reasons.append("the printed words couldn't be found on the sheet "
                       "(-15)")
    if dims is None and source != "ocr":
        try:
            from . import autoscale
            dims = autoscale.dimension_scale(page)
        except Exception:                                # noqa: BLE001
            dims = None
    agree = None
    ratio = dims["ppu"] / scale[1] if dims and dims.get("ppu") and \
        scale[2] == "ft" else None
    if ratio is not None and not 0.4 <= ratio <= 2.5:
        # strings matched to lines that aren't their dimension lines (an
        # elevation's or a detail's): no evidence either way
        reasons.append("the printed dimensions found don't measure at any "
                       "drawing scale - no check either way")
    elif ratio is not None:
        off = abs(ratio - 1)
        agree = off <= 0.03
        if agree and dims.get("n", 0) >= 3:
            s += 25
            reasons.append(f"{dims['n']} printed dimensions measure at this "
                           "scale (+25)")
        elif agree:
            s += 10
            reasons.append(f"{dims['n']} printed dimensions measure at this "
                           "scale (+10)")
        elif off <= 0.08:
            s -= 5
            reasons.append(f"printed dimensions measure {off:.0%} off this "
                           "scale (-5)")
        else:
            from . import takeoff
            other = next((f[0] for f in takeoff.find_scales(chars[0])
                          if f[2] == "ft" and not _same(f[1:], scale)
                          and abs(dims["ppu"] / f[1] - 1) <= 0.03), None)
            if other:
                s -= 15
                reasons.append(f"printed dimensions measure at {other}, "
                               "another scale on this sheet (-15)")
            else:
                s -= 35
                reasons.append(f"printed dimensions measure "
                               f"{dims['ppu']:.2f} pt/ft, not "
                               f"{scale[1]:.2f} - wrong scale or printed "
                               "to fit? (-35)")
    elif ratio is None and source != "ocr":
        reasons.append("no printed dimensions to check it against")
    if others:
        s -= 10
        reasons.append(f"{others} other scale(s) printed on this sheet - "
                       "the plan's was picked (-10)")
    if source == "ocr":
        s *= 0.6
        reasons.append("read by OCR from a scan (x0.6)")
    if dpi and dpi < 150:
        s *= 0.5
        reasons.append(f"scanned at about {dpi:.0f} DPI (x0.5)")
    s = int(round(max(0, min(100, s))))
    return {"score": s, "reasons": reasons,
            "rect": [round(v, 1) for v in rect] if rect is not None else None,
            "text": text, "review": s < REVIEW_BELOW, "dims_agree": agree}


def crop_png(page, rect, zoom=3.0, pad=6.0):
    """The printed scale text as a PNG (bytes), padded a little; None when
    there's nothing to show. Rendered from the page itself (vector text
    stays sharp)."""
    import fitz
    if not rect:
        return None
    # text boxes are in the unrotated page's space; the picture is drawn
    # in the turned page's (a sideways sheet's scale reads level)
    r = (fitz.Rect(rect) + (-pad, -pad, pad, pad)) * page.rotation_matrix
    r = r & page.rect
    if r.is_empty:
        return None
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=r,
                          annots=False)
    return pix.tobytes("png")
