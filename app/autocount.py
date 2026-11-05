import logging

import fitz

try:
    import numpy as np
except ImportError:
    np = None
try:
    import cv2
except ImportError:
    cv2 = None

from . import annotate
from . import ocr as ocr_mod

log = logging.getLogger(__name__)


def _norm(s):
    return "".join(ch for ch in (s or "").lower() if ch.isalnum())


def _ocr_hits(page, label):
    """Exact boxes for `label` on a scanned page (multi-word labels too)."""
    words = ocr_mod.ocr_words(page)
    target = [_norm(w) for w in label.split()]
    hits = []
    for i in range(len(words) - len(target) + 1):
        group = words[i:i + len(target)]
        if [_norm(w["text"]) for w in group] == target:
            r = fitz.Rect(group[0]["rect"])
            for w in group[1:]:
                r |= w["rect"]
            hits.append(r)
    return hits


def _text_hits(page, label):
    """Whole-word matches of `label` in the page's text: "D1" finds D1, not
    D10 or D12 (a plain text search would count those too)."""
    words = page.get_text("words")
    target = [_norm(w) for w in label.split()]
    target = [t for t in target if t]
    if not target:
        return []
    hits = []
    n = len(target)
    for i in range(len(words) - n + 1):
        group = words[i:i + n]
        if n > 1 and len({(w[5], w[6]) for w in group}) > 1:
            continue                     # not on one line
        if [_norm(w[4]) for w in group] == target:
            r = fitz.Rect(group[0][:4])
            for w in group[1:]:
                r |= fitz.Rect(w[:4])
            hits.append(r)
    return hits


def find_by_label(doc, label, use_ocr=True, plan_area_only=True, info=None):
    """Find every occurrence of `label`.

    Pages with a text layer are searched directly. Scanned pages (no text)
    are OCR'd, and the real word positions are used; the original marked a
    fixed spot in the corner and counted at most one hit per page.

    With `plan_area_only` (the default) a tag counts once per instance on
    the plan, as AI Takeoff counts it: hits in the title block, schedules,
    legends and notes blocks are left out, and on a sheet with several
    titled views only the main plan view(s) count (an enlarged plan or a
    detail showing the same tag again doesn't). `info` (a dict) gets
    "left_out": the number of hits not counted.
    """
    hits, ocr_error = [], None
    left_out = 0
    for pno, page in enumerate(doc):
        if page.get_text().strip():
            # words come in unrotated (op) coordinates
            found = _text_hits(page, label)
            if plan_area_only and found:
                kept = _in_plan_area(page, found)
                left_out += len(found) - len(kept)
                found = kept
        elif use_ocr and ocr_error is None:
            try:
                found = _ocr_hits(page, label)
            except ocr_mod.OCRUnavailable as e:
                ocr_error = e
                found = []
        else:
            found = []
        hits.extend({"page": pno, "rect": list(r)} for r in found)
    if info is not None:
        info["left_out"] = left_out
    if ocr_error and not hits:
        raise ocr_error
    return hits


def _same_spot(a, b):
    """Two hits of one label are the same tag: their boxes overlap by
    more than half of the smaller one."""
    ra, rb = fitz.Rect(a["rect"]), fitz.Rect(b["rect"])
    inter = ra & rb
    if inter.is_empty:
        return False
    small = min(ra.get_area(), rb.get_area()) or 1.0
    return inter.get_area() > 0.5 * small


def _in_plan_area(page, rects):
    """The hits (unrotated rects) that count on the plan: outside the
    title block, schedules, legends and notes; in a main plan view when
    the sheet has titled views; one per position. On any trouble reading
    the sheet, all of them (never fewer by accident)."""
    try:
        from . import schedules as sch
        info = sch.sheet_info(page)
        try:
            tables = sch.read_cells(info["cells"], info["segs"] or [],
                                    info["w"], info["h"], "")
        except Exception:                                 # noqa: BLE001
            tables = []
        ex = sch.plan_exclusions(info, tables)
        vs = sch.views(info["cells"], ex)
        m, _back = sch._disp(page)
        cells = []
        for r in rects:
            d = (fitz.Rect(r) * m).normalize() if m is not None else \
                fitz.Rect(r)
            cells.append({"cx": (d.x0 + d.x1) / 2, "cy": (d.y0 + d.y1) / 2,
                          "h": max(1.0, d.y1 - d.y0), "rect": r})
        cells = [c for c in cells if not any(sch._inside(c, e) for e in ex)]
        # one per position: the same text printed on top of itself (a
        # bold or shadow copy) - hits that overlap, not merely near (H2:
        # two tags a text height apart are two fixtures)
        uniq = []
        for c in cells:
            if not any(_same_spot(c, d) for d in uniq):
                uniq.append(c)
        if any(v["plan"] for v in vs):
            from collections import Counter
            owner = {id(c): sch.view_of(c, vs, info["w"]) for c in uniq}
            counts = Counter(id(v) for v in owner.values() if v is not None)
            main = {id(v) for v in sch.main_views(vs, counts)}
            uniq = [c for c in uniq if owner[id(c)] is not None and
                    id(owner[id(c)]) in main]
        return [c["rect"] for c in uniq]
    except Exception:                                     # noqa: BLE001
        log.debug("plan area not worked out; counting every hit",
                  exc_info=True)
        return list(rects)


def symbol_template(page, rect):
    """PNG of the area `rect` (screen coordinates), at the scale
    find_symbols() searches with."""
    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=rect,
                          colorspace=fitz.csGRAY, alpha=False)
    return pix.tobytes("png")


def _ink_check(gray, x, y, t, level=170):
    """(template strokes found, candidate strokes explained): how much of
    the sample's ink is present in the candidate and vice versa, within a
    pixel. A plain circle passes for a duplex outlet on correlation alone;
    it fails here because the outlet's prongs aren't there."""
    th, tw = t.shape
    c = gray[y:y + th, x:x + tw]
    if c.shape != t.shape:
        return 0.0, 0.0
    ti = t < level
    ci = c < level
    if not ti.any() or not ci.any():
        return 0.0, 0.0
    k = np.ones((3, 3), np.uint8)
    td = cv2.dilate(ti.astype(np.uint8), k).astype(bool)
    cd = cv2.dilate(ci.astype(np.uint8), k).astype(bool)
    found = float((ti & cd).sum()) / float(ti.sum())
    explained = float((ci & td).sum()) / float(ci.sum())
    return found, explained


MAX_CANDIDATES = 4000      # per page and orientation
MAX_HITS = 1500            # per page: more means the symbol is too plain


# DESIGN RULE (Oct 31 2026, patent review - enforced by
# tests/test_patent_design_rules.py): symbol counting scores each candidate
# with whole-symbol measures only. Never add a second pass that splits the
# sample or the candidates into separate ink pieces (connected components)
# and compares them piece by piece, and never put a colour or size
# pre-filter in front of the match. New counting work should prefer vector
# path matching or a detector that needs no user-picked sample.
def find_symbols(doc, template_bytes, threshold=0.8, pages=None,
                 turns=True, mirrors=False, verify=True, cache=None):
    """Template matching. One hit per symbol (overlapping matches merged),
    each with its match score. With `turns` the symbol is also looked for
    turned 90, 180 and 270 degrees (outlets and doors face every way on a
    plan); `mirrors` adds mirror images (left- and right-hand doors)."""
    if cv2 is None or np is None:
        raise RuntimeError("Symbol search needs numpy and opencv installed.")
    tpl = cv2.imdecode(np.frombuffer(template_bytes, np.uint8),
                       cv2.IMREAD_GRAYSCALE)
    if tpl is None:
        raise ValueError("template is not a readable image")
    tpls = [tpl]
    if turns:
        tpls += [cv2.rotate(tpl, k) for k in (cv2.ROTATE_90_CLOCKWISE,
                                              cv2.ROTATE_180,
                                              cv2.ROTATE_90_COUNTERCLOCKWISE)]
    if mirrors:
        tpls += [cv2.flip(t, 1) for t in list(tpls)]
    # drop orientations that look the same (a round symbol turned is itself)
    uniq = []
    for t in tpls:
        if not any(u.shape == t.shape and
                   float(np.mean(np.abs(u.astype(int) - t.astype(int)))) < 2
                   for u in uniq):
            uniq.append(t)
    out = []
    for pno, page in enumerate(doc):
        if pages is not None and pno not in pages:
            continue
        gray = cache.get(pno) if cache is not None else None
        if gray is None:
            if max(page.rect.width, page.rect.height) * 2 > 12000:
                continue                 # absurd page size: skip, don't die
            try:
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2),
                                      colorspace=fitz.csGRAY, alpha=False)
            except Exception:
                continue
            gray = np.frombuffer(pix.samples, np.uint8).reshape(
                pix.height, pix.stride)[:, :pix.width].copy()
            if cache is not None:            # many symbols, one render
                cache[pno] = gray
        cands = []
        for t in uniq:
            th, tw = t.shape
            if gray.shape[0] < th or gray.shape[1] < tw:
                continue
            res = cv2.matchTemplate(gray, t, cv2.TM_CCOEFF_NORMED)
            # with the stroke check behind it, correlation can cast a
            # wider net (rotated and slightly different copies)
            lo = threshold - 0.08 if verify else threshold
            ys, xs = np.where(res >= lo)
            if len(ys) > MAX_CANDIDATES:
                # a very plain symbol (a short line, a dot) matches
                # everywhere: keep only the best, so it can't flood memory
                vals = res[ys, xs]
                top = np.argpartition(-vals, MAX_CANDIDATES)[:MAX_CANDIDATES]
                ys, xs = ys[top], xs[top]
            for x, y in zip(xs.tolist(), ys.tolist()):
                cands.append((float(res[y, x]), x, y, tw, th, id(t)))
        cands.sort(reverse=True)
        by_id = {id(t): t for t in uniq}
        kept = []
        for sc, x, y, tw, th, tid in cands:     # non-maximum suppression
            cx, cy = x + tw / 2, y + th / 2
            if not all(abs(cx - k[0]) >= max(tw, k[2]) / 2 or
                       abs(cy - k[1]) >= max(th, k[3]) / 2 for k in kept):
                continue
            if verify:
                found, explained = _ink_check(gray, x, y, by_id[tid])
                if found < 0.9 or explained < 0.55:
                    continue
                sc = round(min(1.0, (sc + found) / 2), 3)
            kept.append((cx, cy, tw, th, sc, x, y))
        if len(kept) > MAX_HITS:
            continue                   # too plain to count reliably
        for cx, cy, tw, th, sc, x, y in kept:
            r = fitz.Rect(x, y, x + tw, y + th) / 2 * page.derotation_matrix
            out.append({"page": pno, "rect": list(r),
                        "score": round(sc, 3)})
    return out


def count_marks(hits, group="Count", doc=None, color=(1, 0, 0)):
    """Marks numbering each hit (1, 2, 3… per page, continuing after any
    counts of the same group already on the page): (page, kind, payload)."""
    counters, marks = {}, []
    if doc is not None:
        for item in annotate.takeoff_items(doc):
            if item["type"] == "count" and item["group"] == group:
                counters[item["page"]] = counters.get(item["page"], 0) + 1
    for h in hits:
        p = h["page"]
        counters[p] = counters.get(p, 0) + 1
        x0, y0 = h["rect"][0], h["rect"][1]
        marks.append((p, "add_count", {
            "pt": [x0, max(12, y0 - 2)], "n": counters[p],
            "color": list(color),
            "measure": {"type": "count", "value": 1, "unit": "ea",
                        "group": group,
                        "method": h.get("method") or "auto count",
                        **({"confidence": h["score"]}
                           if isinstance(h.get("score"), (int, float))
                           else {})}}))
    return marks


def apply_counts(doc, hits, group="Count"):
    """Apply count marks directly (CLI). Returns the number of hits."""
    for p, kind, payload in count_marks(hits, group, doc):
        annotate.apply_op(doc, annotate.new_op(kind, p, **payload))
    return len(hits)


# ======================================================================
# Auto Count with review (was autocount_boost.py; folded Nov 4, 1.1.1)
#
# Auto Count boost: click one example, find every copy, review, accept.
#
# Builds on autocount.find_symbols (template match + stroke check) and adds
# what real plan sets need:
# - any angle: the sample is also searched turned every ANGLE_STEP degrees
#   (and mirrored), not just 90/180/270 - diffusers and fixtures on angled
#   wings were missed (measured: 2% recall at 30 and 45 degrees);
# - size drift: 90/100/110% copies (blocks scaled in CAD, rasterized at a
#   different DPI - measured: 58% recall at +/-10% size);
# - text tag: count only symbols tagged e.g. "C" and not "CE" (the tag must
#   be a whole word right beside the symbol);
# - confidence bands: "high" (pre-accepted) and "review" (shown, not
#   accepted); nothing is added to the takeoff until the estimator accepts
#   it in CountReviewDialog.

ANGLE_STEP = 15
SIZES = (0.9, 1.0, 1.1)
HIGH = 0.9                 # score at or above: pre-accepted
THRESHOLD = 0.8


def _variants(tpl, angles, sizes, mirrors):
    """Template images (white background) for every angle/size, with
    near-duplicates dropped (a square turned 90 degrees is itself)."""
    out = []
    h, w = tpl.shape
    base = [tpl, cv2.flip(tpl, 1)] if mirrors else [tpl]
    for b in base:
        for s in sizes:
            t = b if s == 1.0 else cv2.resize(
                b, (max(4, int(round(w * s))), max(4, int(round(h * s)))),
                interpolation=cv2.INTER_AREA)
            th, tw = t.shape
            for a in angles:
                if a % 360 == 0:
                    r = t
                elif a % 90 == 0:
                    r = np.rot90(t, k=(a // 90) % 4).copy()
                else:
                    side = int(np.ceil(np.hypot(th, tw)))
                    pad = np.full((side, side), 255, np.uint8)
                    y0, x0 = (side - th) // 2, (side - tw) // 2
                    pad[y0:y0 + th, x0:x0 + tw] = t
                    m = cv2.getRotationMatrix2D((side / 2, side / 2), a, 1.0)
                    r = cv2.warpAffine(pad, m, (side, side), flags=cv2.INTER_LINEAR,
                                       borderValue=255)
                    ys, xs = np.where(r < 200)       # crop to ink + 1px
                    if len(ys):
                        r = r[max(0, ys.min() - 1):ys.max() + 2,
                              max(0, xs.min() - 1):xs.max() + 2]
                if not any(u.shape == r.shape and
                           float(np.mean(np.abs(u.astype(int) - r.astype(int)))) < 3
                           for u in out):
                    out.append(r)
    return out


def _tag_ok(page, rect, tag, words_cache):
    words = words_cache.get(page.number)
    if words is None:
        words = words_cache[page.number] = page.get_text("words")
    r = fitz.Rect(rect)
    reach = max(r.width, r.height) * 1.6
    zone = fitz.Rect(r.x0 - reach, r.y0 - reach, r.x1 + reach, r.y1 + reach)
    want = _norm(tag)
    return any(_norm(w[4]) == want and fitz.Rect(w[:4]).intersects(zone) for w in words)


def find(doc, template_bytes, pages=None, threshold=THRESHOLD, any_angle=True,
         sizes=SIZES, mirrors=False, tag=None, cache=None):
    """Hits {page, rect, score, band, angle_hint} with duplicates across
    variants merged (best score kept)."""
    if cv2 is None:
        raise RuntimeError("Auto Count needs numpy and opencv installed.")
    tpl = cv2.imdecode(np.frombuffer(template_bytes, np.uint8), cv2.IMREAD_GRAYSCALE)
    if tpl is None:
        raise ValueError("template is not a readable image")
    angles = range(0, 360, ANGLE_STEP) if any_angle else (0, 90, 180, 270)
    cache = {} if cache is None else cache
    variants = [cv2.imencode(".png", v)[1].tobytes()
                for v in _variants(tpl, angles, sizes, mirrors)]

    def one(b):
        return find_symbols(doc, b, threshold=threshold, pages=pages,
                                      turns=False, mirrors=False, cache=cache)
    raw = one(variants[0])                 # renders the pages into `cache`
    import concurrent.futures as cf
    import os
    with cf.ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 2)) as ex:
        for got in ex.map(one, variants[1:]):     # OpenCV releases the GIL
            raw += got
    raw.sort(key=lambda h: -h["score"])
    kept = []
    for h in raw:                                       # merge across variants
        r = fitz.Rect(h["rect"])
        c = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
        dup = False
        for k in kept:
            if k["page"] != h["page"]:
                continue
            kr = fitz.Rect(k["rect"])
            kc = (kr.x0 + kr.x1) / 2, (kr.y0 + kr.y1) / 2
            lim = 0.5 * min(max(r.width, r.height), max(kr.width, kr.height))
            if abs(c[0] - kc[0]) < lim and abs(c[1] - kc[1]) < lim:
                dup = True
                break
        if not dup:
            kept.append(h)
    if tag:
        words = {}
        kept = [h for h in kept if _tag_ok(doc[h["page"]], h["rect"], tag, words)]
    for h in kept:
        h["band"] = "high" if h["score"] >= HIGH else "review"
        h["method"] = "auto count (reviewed)"
    kept.sort(key=lambda h: (h["page"], h["rect"][1], h["rect"][0]))
    return kept


def review_marks(accepted, group="Count", doc=None, color=(1, 0, 0)):
    """Count marks for the hits the estimator accepted."""
    for h in accepted:
        h["method"] = "auto count (reviewed)"
    return count_marks(accepted, group=group, doc=doc, color=color)


# ---------------------------------------------------------------- review UI
try:
    from PySide6.QtCore import Qt, Signal
    from PySide6.QtGui import QColor, QIcon, QImage, QPixmap
    from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                                   QListWidget, QListWidgetItem, QPushButton,
                                   QVBoxLayout)
except ImportError:
    QDialog = None

if QDialog is not None:
    class CountReviewDialog(QDialog):
        """Every hit as a thumbnail with a checkbox, lowest confidence
        first so the doubtful ones get looked at. High-confidence hits
        start checked, review-band hits unchecked. Double-click jumps to
        it on the plan (go_to)."""
        go_to = Signal(int, object)

        def __init__(self, doc, hits, group="Count", parent=None):
            super().__init__(parent)
            self.doc, self.hits = doc, sorted(hits, key=lambda h: h["score"])
            self.setWindowTitle(f"Auto Count - review {group}")
            lay = QVBoxLayout(self)
            self.info = QLabel("")
            lay.addWidget(self.info)
            self.list = QListWidget()
            self.list.setViewMode(QListWidget.IconMode)
            self.list.setIconSize(pixsize := self.list.iconSize() * 3)
            self.list.setResizeMode(QListWidget.Adjust)
            for h in self.hits:
                it = QListWidgetItem(self._thumb(h), f"p{h['page'] + 1} {h['score']:.2f}")
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(Qt.Checked if h["band"] == "high" else Qt.Unchecked)
                if h["band"] != "high":
                    it.setBackground(QColor("#fff3cd"))
                self.list.addItem(it)
            self.list.itemDoubleClicked.connect(
                lambda it: self.go_to.emit(self.hits[self.list.row(it)]["page"],
                                           self.hits[self.list.row(it)]["rect"]))
            self.list.itemChanged.connect(lambda _: self._count())
            lay.addWidget(self.list)
            row = QHBoxLayout()
            for text, val in (("Accept all", True), ("Reject all", False)):
                b = QPushButton(text)
                b.clicked.connect(lambda _=False, v=val: self.set_all(v))
                row.addWidget(b)
            row.addStretch()
            lay.addLayout(row)
            bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            bb.accepted.connect(self.accept)
            bb.rejected.connect(self.reject)
            lay.addWidget(bb)
            self.resize(820, 560)
            self._count()

        def _thumb(self, h):
            try:
                r = fitz.Rect(h["rect"])
                r = fitz.Rect(r.x0 - r.width, r.y0 - r.height, r.x1 + r.width, r.y1 + r.height)
                pix = self.doc[h["page"]].get_pixmap(matrix=fitz.Matrix(3, 3), clip=r, alpha=False)
                img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                             QImage.Format_RGB888).copy()
                return QIcon(QPixmap.fromImage(img))
            except Exception:
                return QIcon()

        def _count(self):
            n = len(self.accepted())
            rv = sum(1 for h in self.hits if h["band"] != "high")
            self.info.setText(f"{n} of {len(self.hits)} accepted - {rv} need a look "
                              "(amber). Only accepted ones are counted.")

        def set_all(self, on):
            for i in range(self.list.count()):
                self.list.item(i).setCheckState(Qt.Checked if on else Qt.Unchecked)

        def toggle(self, i):
            it = self.list.item(i)
            it.setCheckState(Qt.Unchecked if it.checkState() == Qt.Checked else Qt.Checked)

        def accepted(self):
            return [self.hits[i] for i in range(self.list.count())
                    if self.list.item(i).checkState() == Qt.Checked]
