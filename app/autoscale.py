"""Auto Scale: the scale of every sheet in a set, ready to confirm.

For each page:
1. Text layer: the scale written in the title block / under the plan
   title (sheets.scan + takeoff.main_scale; standard scales only).
2. Scanned sheet (no text layer): the same, read from Tesseract OCR
   words rebuilt into lines (needs tesseract; skipped quietly if absent).
3. Cross-check against the drawing itself: every dimension string
   (24'-0") next to a straight line gives points-per-foot = line length /
   feet. If the median of those disagrees with the written scale by more
   than 3%, the sheet is flagged "check" (wrong scale, or the sheet was
   printed/scaled to fit).
4. No scale written: the dimension strings alone give a scale, snapped to
   the nearest standard one when within 2% - always "check", never
   trusted on its own.

Nothing is applied here: detect() returns rows for the review dialog;
apply() sets only the rows the estimator confirmed (default: rows that
are "ok" and have no scale yet).
"""
import logging
import re
import statistics

from . import annotate, takeoff
from .dmoney import c2 as _c2

log = logging.getLogger(__name__)

AGREE_TOL = 0.03          # written scale vs dimensions
SNAP_TOL = 0.02           # dimensions-only scale snapped to a standard one
MIN_DIM_FT = 1.0
NTS = re.compile(r"\b(N\.?T\.?S\.?|NOT\s+TO\s+SCALE)\b", re.I)


def _ocr_text(page):
    """OCR'd page text as lines (top to bottom, left to right, as the
    sheet is shown - Nov 19: rotated sheets were read sideways), or ''."""
    from . import acrobat
    try:
        words = [{"rect": r, "text": t}
                 for r, t in acrobat.ocr_page_words(page)]
    except Exception as e:                    # no tesseract, timeout...
        log.info("autoscale OCR skipped: %s", e)
        return ""
    words.sort(key=lambda w: ((w["rect"].y0 + w["rect"].y1) / 2, w["rect"].x0))
    lines, cur, cy, ch = [], [], None, 0
    for w in words:
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
    return "\n".join(" ".join(w["text"] for w in sorted(ln, key=lambda w: w["rect"].x0))
                     for ln in lines)


def _segments(page):
    """Straight lines longer than 20 pt, as ((x0, y0), (x1, y1))."""
    segs = []
    try:
        drawings = page.get_cdrawings()        # C-level: much faster
    except Exception:
        try:
            drawings = page.get_drawings()
        except Exception:
            return segs
    for d in drawings:
        for it in d.get("items", ()):
            if it[0] == "l":
                a, b = it[1], it[2]
                ax, ay = (a[0], a[1]) if isinstance(a, (tuple, list)) \
                    else (a.x, a.y)
                bx, by = (b[0], b[1]) if isinstance(b, (tuple, list)) \
                    else (b.x, b.y)
                if ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5 > 20:
                    segs.append(((ax, ay), (bx, by)))
    return segs


def _dimension_words(words):
    """(feet, cx, cy) of every dimension string (24'-0") on the page."""
    out = []
    for w in words:
        got = takeoff.parse_length(w[4])
        if not got or got[1] != "ft" or got[0] < MIN_DIM_FT:
            continue
        if "'" not in w[4].translate(takeoff._QUOTES):
            continue
        out.append((got[0], (w[0] + w[2]) / 2, (w[1] + w[3]) / 2))
    return out


def _sparse(page):
    from . import acrobat
    return acrobat.sparse_text(page)


# an engineering scale as OCR leaves it: SCALE: 1"=20', SCALE 1 = 20,
# 1 20' HORIZ. (the quote marks and = are often lost or misread)
_CIVIL = re.compile(r"SCALE\W{0,6}1\W{0,4}=?\W{0,4}(5|\d{1,3}0)\b"
                    r"(?=\W{0,4}(?:'|FT|FEET|HORIZ|\W|$))", re.I)
CIVIL_FEET = (5, 10, 20, 30, 40, 50, 60, 80, 100, 200, 300, 400, 500)


def civil_scale(text):
    """(label, pt per ft, 'ft') for the main engineering scale in OCR'd
    text, or None. Horizontal scales win (a profile's 1"=20' HORIZ.,
    1"=10' VERT. - the plan above it is at the horizontal one); then the
    smallest feet value (the plan, not a detail)."""
    found = []
    for m in _CIVIL.finditer(text or ""):
        ft = int(m.group(1))
        if ft in CIVIL_FEET:
            tail = text[m.end():m.end() + 12].upper()
            found.append((0 if "HORIZ" in tail else 1, ft))
    if not found:
        return None
    _h, ft = min(found)
    return (f'1" = {ft}\'', 72.0 / ft, "ft")


# a civil graphic scale as text: SCALE: 20' 0 20' 40' GRAPHIC SCALE (the
# bar itself is outlines; only its labels are read - never its length)
_GRAPHIC = re.compile(r"SCALE\W{0,3}:(.{0,60}?)GRAPHIC\W{0,3}SCALE",
                      re.I | re.S)


def graphic_scale(text):
    """(label, pt per ft, 'ft') from a graphic scale's printed labels -
    the first division N when N and 2N (or N twice) are printed, on the
    civil convention that the first division is one inch - or None."""
    best = None
    for m in _GRAPHIC.finditer(text or ""):
        nums = [int(x) for x in re.findall(r"(?<!\d)(\d{1,3})(?!\d)",
                                            m.group(1))]
        nums = [n for n in nums if n in CIVIL_FEET]
        for n in sorted(set(nums)):
            if 2 * n in nums or nums.count(n) > 1:
                best = n if best is None else min(best, n)
                break
    if best is None:
        return None
    return (f'1" = {best}\'', 72.0 / best, "ft")


def _near(words, box):
    """The words whose centre is in `box`, read in lines, left to right."""
    got = [w for w in words if box[0] <= (w[0] + w[2]) / 2 <= box[2] and
           box[1] <= (w[1] + w[3]) / 2 <= box[3]]
    if not got:
        return ""
    h = max(1.0, sorted(w[3] - w[1] for w in got)[len(got) // 2])
    got.sort(key=lambda w: (round(w[3] / (0.8 * h)), w[0]))
    return " ".join(w[4] for w in got)


def scale_words(page, words=None):
    """Scale text read by where the words sit, not by text order (an OCR
    layer's lines come out in any order): (civil, graphic) - the words
    just right of each SCALE word, and the words around each GRAPHIC
    word."""
    if words is None:
        words = page.get_text("words")
    civil, graphic = [], []
    for w in words:
        t = str(w[4]).upper()
        h = max(1.0, w[3] - w[1])
        if t.startswith("SCALE"):
            civil.append(_near(words, (w[0] - 0.5 * h, w[1] - 0.6 * h,
                                       w[2] + 22 * h, w[3] + 0.6 * h)))
        elif t.startswith("GRAPHIC"):
            graphic.append(_near(words, (w[0] - 9 * h, w[1] - 4.5 * h,
                                         w[2] + 14 * h, w[3] + 3 * h)))
    return civil, graphic


def graphic_labels(text):
    """1" = N' from a graphic scale's labels in `text` (words around the
    GRAPHIC SCALE title, any order): the first division N when N and 2N
    (or N twice) are printed - else None."""
    nums = [int(x) for x in re.findall(r"(?<![\d.+])(\d{1,3})(?![\d.+])",
                                        text or "")]
    nums = [n for n in nums if n in CIVIL_FEET]
    for n in sorted(set(nums)):
        if 2 * n in nums or nums.count(n) > 1:
            return (f'1" = {n}\'', 72.0 / n, "ft")
    return None


def dimension_scale(page, words=None):
    """{"ppu": median points per foot or None, "n": dims used, "values"}

    Same answers as before, much faster on dense sheets: lines are read
    only when the sheet has dimension strings, and each string looks only
    at lines within 25 pt of it (the old way compared every string with
    every line - 70 s for Auto Scale on the 309-sheet plant set)."""
    import bisect
    if words is None:
        words = page.get_text("words")
    dims = _dimension_words(words)
    vals = []
    if dims:
        segs = _segments(page)
        # horizontal lines by height, vertical lines by x; keep each line's
        # place in the drawing so ties go to the same line as before
        hz, vt = [], []
        for i, (a, b) in enumerate(segs):
            if abs(a[1] - b[1]) < 1:
                hz.append(((a[1] + b[1]) / 2, i, a, b))
            elif abs(a[0] - b[0]) < 1:
                vt.append(((a[0] + b[0]) / 2, i, a, b))
        hz.sort()
        vt.sort()
        hk = [h[0] for h in hz]
        vk = [v[0] for v in vt]
        for ft, cx, cy in dims:
            best = None                      # (dist, index, length)
            lo, hi = bisect.bisect_left(hk, cy - 25), bisect.bisect_right(
                hk, cy + 25)
            for my, i, a, b in hz[lo:hi]:
                if not (min(a[0], b[0]) - 5 <= cx <= max(a[0], b[0]) + 5):
                    continue
                dist = abs(my - cy)
                if dist < 25 and (best is None or (dist, i) < best[:2]):
                    best = (dist, i, ((a[0] - b[0]) ** 2 +
                                      (a[1] - b[1]) ** 2) ** 0.5)
            lo, hi = bisect.bisect_left(vk, cx - 25), bisect.bisect_right(
                vk, cx + 25)
            for mx, i, a, b in vt[lo:hi]:
                if not (min(a[1], b[1]) - 5 <= cy <= max(a[1], b[1]) + 5):
                    continue
                dist = abs(mx - cx)
                if dist < 25 and (best is None or (dist, i) < best[:2]):
                    best = (dist, i, ((a[0] - b[0]) ** 2 +
                                      (a[1] - b[1]) ** 2) ** 0.5)
            if best and best[2]:
                vals.append(best[2] / ft)
    if len(vals) < 2:
        return {"ppu": None, "n": len(vals), "values": vals}
    # densest cluster (dimension strings pick up stray lines; the real
    # scale is the value most of them agree on)
    best = []
    for v in vals:
        close = [x for x in vals if abs(x / v - 1) <= AGREE_TOL]
        if len(close) > len(best):
            best = close
    need = 2 if len(vals) <= 3 else max(3, int(0.2 * len(vals)))
    if len(best) < need:
        return {"ppu": None, "n": len(best), "values": vals}
    return {"ppu": statistics.median(best), "n": len(best), "values": vals}


def _snap(ppu, unit="ft"):
    best = None
    for fam in takeoff.PRESETS.values():
        for label, (p, u) in fam:
            if u == unit and abs(p / ppu - 1) <= SNAP_TOL:
                if best is None or abs(p - ppu) < abs(best[1] - ppu):
                    best = (label, p)
    return best


ZOOM_DPI = 400


def _ocr_clip_text(page, clip, dpi=ZOOM_DPI, psm=11):
    """One small area of a sheet OCR'd closely, as the sheet is shown,
    read in lines. `clip` is in the page's text coordinates. psm 6 reads
    the area as one block (Nov 23: it keeps SCALE: 1" = 5' together where
    the sparse-text reading, psm 11, lost the "= 5'")."""
    import os
    import tempfile
    import fitz
    from . import acrobat, ocr as ocr_mod
    exe = ocr_mod.find_tesseract()
    if not exe:
        return ""
    # the OCR layer's words sit where the sheet shows them; the sheet's
    # own text on a turned page is in its unturned frame - try both
    tries = [fitz.Rect(clip) & page.rect]
    if page.rotation:
        tries.append((fitz.Rect(clip) * page.rotation_matrix) & page.rect)
    zoom = dpi / 72.0
    out = []
    for shown in tries:
        if shown.is_empty:
            continue
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=shown,
                              colorspace=fitz.csGRAY, alpha=False,
                              annots=False)
        fd, png = tempfile.mkstemp(suffix=".png", prefix="qs_scale_")
        os.close(fd)
        try:
            pix.save(png)
            words = acrobat._tess_tile(exe, png, "eng",
                                       acrobat.tessdata_dir(), psm=psm)
        except Exception as e:                            # noqa: BLE001
            log.info("close-up OCR skipped: %s", e)
            continue
        finally:
            try:
                os.remove(png)
            except OSError:
                pass
        out.append(_lines_text([w for w in words if w[5] >= 40]))
        if re.search(r"GRAPHIC|SCALE", out[-1], re.I):
            break
    return "\n".join(out)


def _lines_text(words):
    """[(x0, y0, x1, y1, text, conf)] -> text in lines, top to bottom."""
    words = sorted(words, key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    lines, cur, cy, ch = [], [], None, 0
    for w in words:
        y, h = (w[1] + w[3]) / 2, max(1, w[3] - w[1])
        if cy is not None and abs(y - cy) > 0.6 * max(h, ch):
            lines.append(cur)
            cur = []
        if not cur:
            cy, ch = y, h
        cur.append(w)
    if cur:
        lines.append(cur)
    return "\n".join(" ".join(w[4] for w in sorted(ln, key=lambda w: w[0]))
                     for ln in lines)


def zoom_scale(page, words=None, ocr=None):
    """Nov 23 (a civil sheet whose SCALE: 1" = 5' and graphic scale labels
    were too small for the whole-sheet OCR): read the area around each
    SCALE / GRAPHIC SCALE word again, close up. (label, ppu, unit) or
    None. `ocr(page, clip) -> text` for tests."""
    import fitz
    if words is None:
        words = page.get_text("words")
    ocr = ocr or _ocr_clip_text
    # only where a graphic scale is drawn (a detail sheet's many SCALE
    # words aren't worth a close look each)
    if not any(str(w[4]).upper().startswith("GRAPHIC") for w in words):
        return None
    words = [w for w in words if str(w[4]).upper().startswith("GRAPHIC")]
    boxes = []
    for w in words:
        t = str(w[4]).upper()
        if not (t.startswith("SCALE") or t.startswith("GRAPHIC")):
            continue
        h = max(4.0, w[3] - w[1])
        b = fitz.Rect(w[0] - 12 * h, w[1] - 6 * h, w[2] + 24 * h,
                      w[3] + 6 * h)
        for i, o in enumerate(boxes):
            if b.intersects(o):
                boxes[i] = o | b
                break
        else:
            boxes.append(b)
    if ocr is _ocr_clip_text:
        tries = [lambda b: _ocr_clip_text(page, b, ZOOM_DPI, psm=6),
                 lambda b: _ocr_clip_text(page, b, ZOOM_DPI),
                 lambda b: _ocr_clip_text(page, b, 600),
                 lambda b: _ocr_clip_text(page, b, 600, psm=6)]
    else:
        tries = [lambda b: ocr(page, b), lambda b: ocr(page, b, 600)]
    arch, part = [], []       # architectural scales read close up
    for b in boxes[:6]:
        for read in tries:
            text = read(b) or ""
            full = [f[:3] for f in takeoff._find(text)
                    if f[3] and f[2] == "ft" and "'-0" in f[0]
                    and takeoff.is_standard(f[1], f[2])]
            arch += full
            if not full:
                # 'SCALE: 1/2" =' with the 1'-0" lost backs up a full read
                part += _ZOOM_PART.findall(text.translate(takeoff._QUOTES))
            # close up, a scale needs its "=" ('SCALE: 1" 10' with the
            # "= 5'" lost is not 1" = 10'), and the graphic labels, when
            # read, must agree with it
            m = _ZOOM_CIVIL.search(text)
            civ = (f'1" = {m.group(1)}\'', 72.0 / int(m.group(1)), "ft") \
                if m and int(m.group(1)) in CIVIL_FEET else None
            gl = graphic_labels(text.split("GRAPHIC")[0]
                                if "GRAPHIC" in text.upper() else text)
            if civ and gl and abs(gl[1] - civ[1]) > 1e-9:
                break                 # they disagree: no scale from here
            if civ or gl:
                return civ or gl
    # Nov 23 (D01.10: 1/2" = 1'-0" over a bar labelled 0 2 4 in feet): an
    # architectural scale needs two readings of it and none of another
    # (or one, and its inches again where the rest was lost)
    labels = {a[0] for a in arch}
    if len(labels) == 1:
        inch = arch[0][0].split('"')[0]
        if all(p == inch for p in part) and \
                len(arch) + (len(part) if "/" in inch else 0) >= 2:
            return arch[0]
    return None


_ZOOM_PART = re.compile(r"SCALE\W{0,3}(\d{1,2}/\d{1,2})\s*\"\s*=?\s*$", re.M)


_ZOOM_CIVIL = re.compile(r"SCALE\W{0,4}1\W{0,3}=\W{0,3}(5|\d{1,3}0)\b",
                         re.I)


def detect(doc, pages=None, use_ocr=True, progress=None):
    """One row per page: {page, label, ppu, unit, source ('text', 'ocr',
    'civil', 'graphic', 'close-up', 'dimensions' or ''), existing (ppu already set or None), dims {ppu, n,
    agree}, status ('ok', 'check', 'none'), note}."""
    from . import sheets
    have = annotate.read_scales(doc)
    pages = list(pages if pages is not None else range(doc.page_count))
    rows = []
    for k, pno in enumerate(pages):
        if progress and progress(k, len(pages)) is False:
            break
        page = doc[pno]
        # the sheet's text is read once and shared: it used to be pulled
        # out four times per sheet (57 % of Auto Scale's time)
        try:
            import fitz
            tp = page.get_textpage(flags=fitz.TEXTFLAGS_TEXT)
        except Exception:
            tp = None
        info = sheets.scan(doc, [pno], numbers=False,
                           textpages={pno: tp} if tp is not None else None)[0]
        sc, src, note = info["scale"], "text" if info["scale"] else "", ""
        text = page.get_text(textpage=tp)
        has_text = bool(text.strip())
        if sc is None and use_ocr and (not has_text or _sparse(page)):
            # a scan - or (Nov 19) a sheet whose scales are drawn as
            # outlines, not typed (a civil set: only its title block has
            # text)
            otext = _ocr_text(page)
            main = takeoff.main_scale(otext)
            if main and takeoff.is_standard(main[1], main[2]):
                sc, src = main, "ocr"
            else:
                civ = civil_scale(otext)
                if civ:
                    sc, src = civ, "ocr"
        if sc is None and has_text:
            # an engineering scale in the sheet's text as OCR left it
            # (Nov 19: SCALE: 1 20' HORIZ. under a profile)
            civ = civil_scale(text)
            if civ:
                sc, src = civ, "civil"
            else:
                civ = graphic_scale(text)
                if civ:
                    sc, src = civ, "graphic"
        if sc is None and has_text:
            near_civil, near_graphic = scale_words(page)
            civ = civil_scale(" ; ".join(near_civil))
            if civ:
                sc, src = civ, "civil"
            else:
                found = [c for c in map(graphic_labels, near_graphic) if c]
                if found:
                    sc, src = min(found, key=lambda c: -c[1]), "graphic"
        if sc is None and has_text and use_ocr:
            civ = zoom_scale(page)
            if civ:
                sc, src = civ, "close-up"
        if sc is None and info.get("odd"):
            note = f"odd scale written: {info['odd'][0]} - pick it if right"
        nts = sc is None and bool(NTS.search(text))
        dims = dimension_scale(page, page.get_text("words", textpage=tp)) \
            if has_text and not nts else {"ppu": None, "n": 0}
        if nts:
            note = "sheet says NTS (not to scale) - don't measure from it"
        agree = None
        if sc and dims["ppu"] and sc[2] == "ft":
            agree = abs(dims["ppu"] / sc[1] - 1) <= AGREE_TOL
        row = {"page": pno, "sheet": info.get("label", ""), "label": None,
               "ppu": None, "unit": "ft", "source": src,
               "existing": (have.get(pno) or {}).get("ppu"),
               "dims": {"ppu": dims["ppu"], "n": dims["n"], "agree": agree},
               "status": "none", "note": note}
        other = None
        if sc and agree is False and src == "text":
            # the dimension strings match ANOTHER scale written on this
            # sheet: its enlarged views, not a print-to-fit (PM review
            # NW-19: A-101 1/8" plan with 3/8" enlarged plans was 'check')
            for lab, ppu_, unit_ in takeoff.find_scales(text):
                if unit_ == "ft" and abs(ppu_ - sc[1]) > 1e-6 and \
                        abs(dims["ppu"] / ppu_ - 1) <= AGREE_TOL:
                    other = lab
                    break
        if sc:
            row.update(label=sc[0], ppu=sc[1], unit=sc[2])
            if other:
                # can't be told from a half/double-size print of a sheet
                # that also has a key plan at the other scale (Chief Q2):
                # review it, never 'ok'
                row["status"] = "check"
                row["note"] = (f"dimensions match the {other} views on "
                               f"this sheet - check the {sc[0]} main view "
                               "with a known dimension (a print at another "
                               "size looks the same)")
            elif agree is False:
                row["status"] = "check"
                row["note"] = (f"dimension strings say {_c2(dims['ppu']):.2f} pt/ft, "
                               f"not {_c2(sc[1]):.2f} - sheet may be printed to fit")
            elif src == "civil" and not agree:
                row["status"] = "check"
                row["note"] = ("engineering scale read from the sheet's text "
                               "(often OCR) - check it with a known "
                               "dimension or the graphic scale")
            elif src == "graphic" and not agree:
                row["status"] = "check"
                row["note"] = ("read from the graphic scale's labels (first "
                               "division taken as 1\") - check it against "
                               "the bar or a known dimension")
            elif src == "close-up" and not agree:
                row["status"] = "check"
                row["note"] = ("read close up beside the graphic scale (OCR)"
                               " - check it against the bar or a known "
                               "dimension")
            elif src == "ocr" and not agree:
                row["status"] = "check"
                row["note"] = ("read by OCR - spot-check it (OCR can misread "
                               "1/4 vs 1/2, or 1\"=20' vs 1\"=200')")
            else:
                row["status"] = "ok"
        elif dims["ppu"]:
            snap = _snap(dims["ppu"])
            label, ppu = snap if snap else (takeoff.scale_text(dims["ppu"], "ft"),
                                            dims["ppu"])
            row.update(label=label, ppu=ppu, source="dimensions", status="check",
                       note=f"no scale written; {dims['n']} dimension strings agree")
        elif not row["note"]:
            row["note"] = "no scale found - set it by hand (Calibrate)"
        rows.append(row)
    return rows


def apply(doc, rows, confirmed=None):
    """Set the scale on confirmed pages (set of page indexes). Default:
    rows with status 'ok' and no existing scale. Returns pages set."""
    n = 0
    for r in rows:
        if not r.get("ppu"):
            continue
        ok = (r["page"] in confirmed) if confirmed is not None else \
            (r["status"] == "ok" and not r.get("existing"))
        if ok:
            if annotate.apply_op(doc, annotate.new_op(
                    "set_scale", r["page"], ppu=r["ppu"], unit=r["unit"],
                    name=r.get("label") or "")):
                n += 1
    return n


def preset_labels():
    """[(label, ppu, unit)] of every standard scale, for setting a sheet's
    scale from the review list."""
    out = []
    for fam in takeoff.PRESETS.values():
        for label, (ppu, unit) in fam:
            out.append((label, ppu, unit))
    return out


def set_row(row, label):
    """Set a review row to a standard scale picked by hand (P1 'auto-scale
    review queue': one click per sheet). Returns the row."""
    for lab, ppu, unit in preset_labels():
        if lab == label:
            row.update(label=lab, ppu=ppu, unit=unit, source="set by hand",
                       status="ok", note="set by hand in the review list")
            return row
    raise ValueError(f"not a standard scale: {label}")


# ---------------------------------------------------------------- review UI
try:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                                   QTableWidget, QTableWidgetItem,
                                   QVBoxLayout, QLabel)
except ImportError:
    QDialog = None

if QDialog is not None:
    class ScaleReviewDialog(QDialog):
        """Every sheet's found scale with a checkbox. 'ok' rows start
        checked (unless the page already has a scale), 'check' rows start
        unchecked and amber, 'none' rows can't be checked."""
        COLS = ["Use", "Page", "Sheet", "Scale", "From", "Dims check", "Note",
                "Set to"]

        def __init__(self, rows, parent=None):
            super().__init__(parent)
            self.setWindowTitle("Auto Scale - confirm before use")
            self.rows = rows
            lay = QVBoxLayout(self)
            lay.addWidget(QLabel("Spot-check a page with a known dimension "
                                 "before taking off."))
            t = self.table = QTableWidget(len(rows), len(self.COLS))
            t.setHorizontalHeaderLabels(self.COLS)
            for i, r in enumerate(rows):
                use = QTableWidgetItem()
                if r.get("ppu"):
                    use.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                    use.setCheckState(Qt.Checked if r["status"] == "ok" and
                                      not r.get("existing") else Qt.Unchecked)
                else:
                    use.setFlags(Qt.ItemIsEnabled)
                d = r["dims"]
                dims = ("agrees" if d.get("agree") else "DISAGREES"
                        if d.get("agree") is False else f"{d.get('n', 0)} dims")
                vals = [str(r["page"] + 1), r.get("sheet", ""), r.get("label") or "-",
                        r.get("source") or "-", dims,
                        (f"(page already {_c2(r['existing']):.2f} pt/ft) " if r.get("existing") else "")
                        + r.get("note", "")]
                t.setItem(i, 0, use)
                for c, v in enumerate(vals, 1):
                    t.setItem(i, c, QTableWidgetItem(v))
                if r["status"] != "ok":
                    for c in range(len(self.COLS) - 1):
                        t.item(i, c).setBackground(QColor("#fff3cd") if r["status"] == "check"
                                                   else QColor("#f8d7da"))
                # one click to set a sheet's scale by hand (P1 review queue)
                box = QComboBox()
                box.addItem("—")
                for lab, _p, _u in preset_labels():
                    box.addItem(lab)
                box.currentTextChanged.connect(
                    lambda text, row=i: self.set_scale(row, text))
                t.setCellWidget(i, len(self.COLS) - 1, box)
            lay.addWidget(t)
            bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            bb.accepted.connect(self.accept)
            bb.rejected.connect(self.reject)
            lay.addWidget(bb)
            self.resize(900, 500)

        def set_scale(self, i, label):
            if label == "—":
                return
            r = set_row(self.rows[i], label)
            self.table.item(i, 3).setText(r["label"])
            self.table.item(i, 4).setText(r["source"])
            self.table.item(i, 6).setText(r["note"])
            use = self.table.item(i, 0)
            use.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            use.setCheckState(Qt.Checked)
            for c in range(len(self.COLS) - 1):
                self.table.item(i, c).setBackground(QColor("#d4edda"))

        def confirmed(self):
            return {self.rows[i]["page"] for i in range(self.table.rowCount())
                    if self.table.item(i, 0).checkState() == Qt.Checked}

    def run_dialog(parent, doc, pages=None):
        """Detect, show the review table, apply what was confirmed."""
        rows = detect(doc, pages)
        dlg = ScaleReviewDialog(rows, parent)
        if dlg.exec() != QDialog.Accepted:
            return 0
        return apply(doc, rows, dlg.confirmed())
