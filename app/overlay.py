"""Revision overlay: compare an older and a newer set of drawings.

* Sheets are paired by sheet number (A-101 with A-101, wherever they sit
  in the set), else by page order.
* The older sheet is lined up with the newer one automatically (the plot
  often moves or rescales between issues): feature matching finds the
  shift and scale, checked against how well the linework then overlaps.
* Overlay: a vector page with the older drawing tinted red and the newer
  tinted green, multiplied together - unchanged linework stays dark,
  removed is red, added is green. Each revision is its own layer, so
  either can be turned off; zoom stays sharp.
* Changes: the areas that differ are found and can be clouded.
* Slip sheet: the newer drawing replaces an older sheet in your takeoff
  document, lined up with it, so your markups and takeoffs stay where
  they were; the older drawing is kept as a hidden, tinted layer and
  takeoffs that sit on changed areas are flagged for review.
"""
import logging
import math
import re

import fitz

log = logging.getLogger(__name__)

OLD_COLOR = (0.86, 0.12, 0.12)
NEW_COLOR = (0.08, 0.62, 0.16)
CHANGE_SUBJECT = "Revision change"
CHANGE_LAYER = "Revision changes"
REVIEW_STATUS = "Check - drawing revised"   # annotate.REVISED


# ---- pairing sheets --------------------------------------------------------------

def sheet_number(page):
    from . import sheets
    try:
        words = [w[:5] for w in page.get_text("words")]
        return sheets.sheet_info(words, page.rect.width,
                                 page.rect.height)[0]
    except Exception:
        return ""


def pair_pages(old, new, by_number=True):
    """[(old index or None, new index or None, sheet number)] - every page
    of both documents once."""
    pairs = []
    if by_number:
        on = {i: sheet_number(old[i]) for i in range(old.page_count)}
        nn = {j: sheet_number(new[j]) for j in range(new.page_count)}
        found_o = {}
        for i, s in on.items():
            if s and s not in found_o:
                found_o[s] = i
        hits = sum(1 for s in nn.values() if s and s in found_o)
        if hits >= max(1, min(old.page_count, new.page_count) // 2):
            used = set()
            for j in range(new.page_count):
                s = nn[j]
                i = found_o.get(s) if s else None
                if i is not None and i not in used:
                    used.add(i)
                    pairs.append((i, j, s))
                else:
                    pairs.append((None, j, s))
            for i in range(old.page_count):
                if i not in used:
                    pairs.append((i, None, on[i]))
            return pairs
    for k in range(max(old.page_count, new.page_count)):
        pairs.append((k if k < old.page_count else None,
                      k if k < new.page_count else None,
                      sheet_number(new[k]) if k < new.page_count else
                      sheet_number(old[k])))
    return pairs


# ---- alignment ---------------------------------------------------------------------

def _gray(page, dpi):
    import numpy as np
    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY, alpha=False,
                          annots=False)
    return np.frombuffer(pix.samples, np.uint8).reshape(
        pix.height, pix.stride)[:, :pix.width].copy()


def _overlap(a, b):
    """How well two ink masks agree (dilated IoU)."""
    import cv2
    import numpy as np
    k = np.ones((3, 3), np.uint8)
    da, db = cv2.dilate(a, k), cv2.dilate(b, k)
    inter = np.logical_and(a > 0, db > 0).sum() + \
        np.logical_and(b > 0, da > 0).sum()
    total = (a > 0).sum() + (b > 0).sum()
    return inter / total if total else 1.0


def affine(m):
    """(a, b, tx, ty) of an alignment (scale, tx, ty, score[, rotation
    degrees]): new = [[a, -b], [b, a]] . old + (tx, ty), in points with the
    origin at the top left."""
    s, tx, ty = float(m[0]), float(m[1]), float(m[2])
    rot = math.radians(float(m[4])) if len(m) > 4 else 0.0
    return s * math.cos(rot), s * math.sin(rot), tx, ty


def from_affine(a, b, tx, ty, score=0.0):
    rot = math.degrees(math.atan2(b, a))
    if abs(rot) < 0.01:
        rot = 0.0
    return (math.hypot(a, b), float(tx), float(ty), float(score), rot)


IDENTITY = (1.0, 0.0, 0.0, 0.0, 0.0)


def is_identity(m):
    a, b, tx, ty = affine(m)
    return abs(a - 1) < 1e-9 and abs(b) < 1e-9 and abs(tx) < 1e-9 and \
        abs(ty) < 1e-9


def invert(m):
    a, b, tx, ty = affine(m)
    d = a * a + b * b
    ia, ib = a / d, -b / d
    return from_affine(ia, ib, -(ia * tx - ib * ty), -(ib * tx + ia * ty),
                       m[3] if len(m) > 3 else 0.0)


def map_point(pt, m, inverse=False):
    a, b, tx, ty = affine(invert(m) if inverse else m)
    x, y = pt
    return fitz.Point(a * x - b * y + tx, b * x + a * y + ty)


def map_rect(r, m, inverse=False):
    r = fitz.Rect(r)
    pts = [map_point(p, m, inverse) for p in (r.tl, r.tr, r.bl, r.br)]
    return fitz.Rect(min(p.x for p in pts), min(p.y for p in pts),
                     max(p.x for p in pts), max(p.y for p in pts))


def _warp(img, m_px, shape):
    """Warp `img` by (a, b, tx, ty) in pixels."""
    import cv2
    import numpy as np
    a, b, tx, ty = m_px
    m = np.float32([[a, -b, tx], [b, a, ty]])
    return cv2.warpAffine(img, m, (shape[1], shape[0]),
                          flags=cv2.INTER_NEAREST, borderValue=0)


def _px(m, f):
    a, b, tx, ty = affine(m)
    return a, b, tx * f, ty * f


def score(old_page, new_page, m, dpi=40):
    """How well the linework overlaps (0-1) with alignment `m`."""
    import numpy as np
    a = (_gray(old_page, dpi) < 200).astype(np.uint8) * 255
    b = (_gray(new_page, dpi) < 200).astype(np.uint8) * 255
    return float(_overlap(_warp(a, _px(m, dpi / 72.0), b.shape), b))


def align(old_page, new_page, dpi=40, fine=100):
    """(scale, tx, ty, score, rotation) mapping the older page's
    coordinates (points) onto the newer page's - see affine(). Score is how
    well the linework overlaps afterwards (0-1)."""
    import cv2
    import numpy as np
    a = (_gray(old_page, dpi) < 200).astype(np.uint8) * 255
    b = (_gray(new_page, dpi) < 200).astype(np.uint8) * 255
    base = _overlap(_warp(a, (1.0, 0.0, 0.0, 0.0), b.shape), b)
    best = ((1.0, 0.0, 0.0, 0.0), base)
    cands = []
    # features: shift, scale and rotation
    try:
        orb = cv2.ORB_create(5000)
        ka, da = orb.detectAndCompute(a, None)
        kb, db = orb.detectAndCompute(b, None)
        if da is not None and db is not None and len(ka) > 10 and \
                len(kb) > 10:
            bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
            m = sorted(bf.match(da, db), key=lambda x: x.distance)[:1500]
            if len(m) >= 12:
                pa = np.float32([ka[x.queryIdx].pt for x in m])
                pb = np.float32([kb[x.trainIdx].pt for x in m])
                mat, inl = cv2.estimateAffinePartial2D(
                    pa, pb, method=cv2.RANSAC, ransacReprojThreshold=2.0)
                if mat is not None and inl is not None and inl.sum() >= 12:
                    sc = float(np.hypot(mat[0, 0], mat[1, 0]))
                    if 0.5 < sc < 2.0:
                        cands.append((float(mat[0, 0]), float(mat[1, 0]),
                                      float(mat[0, 2]), float(mat[1, 2])))
    except cv2.error:
        log.warning("feature alignment failed", exc_info=True)
    # pure shift by phase correlation
    try:
        h = max(a.shape[0], b.shape[0])
        w = max(a.shape[1], b.shape[1])
        fa = np.zeros((h, w), np.float32)
        fb = np.zeros((h, w), np.float32)
        fa[:a.shape[0], :a.shape[1]] = a
        fb[:b.shape[0], :b.shape[1]] = b
        (dx, dy), _ = cv2.phaseCorrelate(fa, fb)
        cands += [(1.0, 0.0, float(dx), float(dy)),
                  (1.0, 0.0, -float(dx), -float(dy))]
    except cv2.error:
        pass
    for c in cands:
        sc = _overlap(_warp(a, c, b.shape), b)
        if sc > best[1] + 0.02:
            best = (c, sc)
    (ca, cb, tx, ty), sc = best
    f = 72.0 / dpi
    m = from_affine(ca, cb, tx * f, ty * f, sc)
    try:
        m = _refine(old_page, new_page, m, fine)
    except Exception:
        log.warning("alignment refinement failed", exc_info=True)
    # snap a tiny correction to none (scan noise)
    s_, tx_, ty_, sc_, rot_ = m
    if abs(s_ - 1) < 0.002 and abs(tx_) < 0.75 and abs(ty_) < 0.75 and \
            abs(rot_) < 0.02:
        return (1.0, 0.0, 0.0, max(base, sc_), 0.0)
    return m


def _refine(old_page, new_page, m, dpi, rounds=2):
    """Fine-tune the shift of alignment `m` by phase correlation between
    the newer sheet and the older one redrawn through `m`."""
    import cv2
    import numpy as np
    f = dpi / 72.0
    b = (_gray(new_page, dpi) < 200).astype(np.uint8) * 255

    def moved(mm):
        g = _gray(old_page, dpi) if is_identity(mm) else \
            _gray(_moved(old_page, new_page, mm), dpi)
        a = (g < 200).astype(np.uint8) * 255
        return _warp(a, (1.0, 0.0, 0.0, 0.0), b.shape)

    wa = moved(m)
    best = (m, _overlap(wa, b))
    for _ in range(rounds):
        (dx, dy), _r = cv2.phaseCorrelate(wa.astype(np.float32),
                                          b.astype(np.float32))
        if abs(dx) < 0.05 and abs(dy) < 0.05:
            break
        ca, cb, tx, ty = affine(best[0])
        improved = False
        for sx in (1, -1):
            cand = from_affine(ca, cb, tx + sx * dx / f, ty + sx * dy / f)
            wc = moved(cand)
            sc = _overlap(wc, b)
            if sc > best[1] + 1e-4:
                best, wa, improved = (cand, sc), wc, True
        if not improved:
            break
    mm, sc = best
    return (mm[0], mm[1], mm[2], float(sc), mm[4])


def align_points(old_pts, new_pts, old_page=None, new_page=None):
    """The alignment that takes the points you picked on the older sheet
    onto the same points on the newer one (2 or more pairs; with more, the
    best fit). Includes rotation. Score filled in when the pages are
    given."""
    import numpy as np
    n = min(len(old_pts), len(new_pts))
    if n < 2:
        raise ValueError("Pick at least 2 matching points on each sheet.")
    rows, rhs = [], []
    for (x, y), (u, v) in zip(old_pts[:n], new_pts[:n]):
        rows += [[x, -y, 1, 0], [y, x, 0, 1]]
        rhs += [u, v]
    sol, *_ = np.linalg.lstsq(np.float64(rows), np.float64(rhs), rcond=None)
    a, b, tx, ty = (float(v) for v in sol)
    if not 0.2 < math.hypot(a, b) < 5:
        raise ValueError("Those points give an unlikely scale - check that "
                         "point 1 and point 2 are the same places on both "
                         "sheets.")
    m = from_affine(a, b, tx, ty)
    if old_page is not None and new_page is not None:
        m = m[:3] + (score(old_page, new_page, m),) + m[4:]
    return m


def residuals(old_pts, new_pts, m):
    """How far (points) each picked old point lands from its new point."""
    return [map_point(p, m).distance_to(fitz.Point(q))
            for p, q in zip(old_pts, new_pts)]


# ---- changes ----------------------------------------------------------------------

def changes(old_page, new_page, m=IDENTITY, dpi=90, tolerance=2.0,
            group=0.18, min_ink=12):
    """Areas (rects in the newer page's points) where the drawings differ,
    and the % of linework that changed. `tolerance` is in points.

    A line counts as removed only where the older sheet has clear ink and
    the newer has none at all nearby (and the other way round for added),
    so faint hairlines that render a shade lighter or darker after a small
    shift don't show up as changes."""
    import cv2
    import numpy as np
    f = dpi / 72.0
    gb = _gray(new_page, dpi)
    if is_identity(m):
        ga = _gray(old_page, dpi)
    else:
        # redraw the older sheet moved/turned onto the newer one's page, so
        # both are rendered the same way
        ga = _gray(_moved(old_page, new_page, m), dpi)
    h, w = min(ga.shape[0], gb.shape[0]), min(ga.shape[1], gb.shape[1])
    ga, gb = ga[:h, :w], gb[:h, :w]
    strong_a, strong_b = ga < 160, gb < 160
    any_a = (ga < 240).astype(np.uint8)
    any_b = (gb < 240).astype(np.uint8)
    t = max(1, int(round(tolerance * f)))
    k = np.ones((2 * t + 1, 2 * t + 1), np.uint8)
    removed = strong_a & (cv2.dilate(any_b, k) == 0)
    added = strong_b & (cv2.dilate(any_a, k) == 0)
    diff = (removed | added).astype(np.uint8)
    ink = int((strong_a | strong_b).sum())
    pct = round(100.0 * diff.sum() / ink, 1) if ink else 0.0
    if not diff.any():
        return [], 0.0
    gap = max(3, int(group * dpi))
    blob = cv2.dilate(diff, np.ones((gap, gap), np.uint8))
    n, labels, st, _ = cv2.connectedComponentsWithStats(blob, connectivity=8)
    rects = []
    for i in range(1, n):
        x, y, w_, h_, _area = st[i]
        real = int(diff[y:y + h_, x:x + w_].sum())
        if real < min_ink * f:
            continue
        pad = 4
        rects.append(fitz.Rect((x - pad) / f, (y - pad) / f,
                               (x + w_ + pad) / f, (y + h_ + pad) / f)
                     & new_page.rect)
    rects = _merge(rects)
    return rects, pct


def _moved(old_page, new_page, m):
    """A temporary page the size of `new_page` with `old_page` drawn on it
    through alignment `m`."""
    tmp = fitz.open()
    p = tmp.new_page(width=new_page.rect.width, height=new_page.rect.height)
    ops, _n, _x = _place(p, old_page.parent, old_page.number, m)
    _write(tmp, p, [ops])
    return p


def _merge(rects, gap=6):
    rects = [fitz.Rect(r) for r in rects if not r.is_empty]
    changed = True
    while changed:
        changed = False
        out = []
        while rects:
            r = rects.pop()
            grow = fitz.Rect(r.x0 - gap, r.y0 - gap, r.x1 + gap, r.y1 + gap)
            for o in rects[:]:
                if grow.intersects(o):
                    r |= o
                    rects.remove(o)
                    changed = True
            out.append(r)
        rects = out
    return sorted(rects, key=lambda r: (round(r.y0 / 50), r.x0))


# ---- drawing pages into pages ----------------------------------------------------

def _place(page, src, pno, m=IDENTITY):
    """Put src[pno] into `page` as an XObject drawn 1:1 from the top left
    and then moved by alignment `m`. Returns (drawing operators, resource
    name, xref)."""
    doc = page.parent
    sp = src[pno]
    before = b"".join(doc.xref_stream(c) or b"" for c in page.get_contents())
    xref = page.show_pdf_page(fitz.Rect(0, 0, sp.rect.width, sp.rect.height),
                              src, pno, keep_proportion=False)
    after = b"".join(doc.xref_stream(c) or b"" for c in page.get_contents())
    snippet = after[len(before):] if after.startswith(before) else after
    found = re.search(rb"/(\S+)\s+Do", snippet)
    name = found.group(1).decode() if found else ""
    # the placed XObject (with the placement matrix) is the one the page's
    # resources name, not the bare page copy show_pdf_page returns
    t, v = doc.xref_get_key(_resources_xref(doc, page), f"XObject/{name}")
    if t == "xref":
        xref = int(v.split()[0])
    # alignment (top-left points) as a PDF matrix (bottom-left origin)
    a, b, tx, ty = affine(m)
    h = page.rect.height
    cm = (f"{a:.6f} {-b:.6f} {b:.6f} {a:.6f} {tx - b * h:.4f} "
          f"{h - a * h - ty:.4f} cm ")
    ops = (cm if not is_identity(m) else "") + f"/{name} Do"
    return ops, name, xref


def _resources_xref(doc, page):
    t, v = doc.xref_get_key(page.xref, "Resources")
    if t == "xref":
        return int(v.split()[0])
    x = doc.get_new_xref()
    doc.update_object(x, v if t == "dict" else "<<>>")
    doc.xref_set_key(page.xref, "Resources", f"{x} 0 R")
    return x


def _box(doc, page):
    t, v = doc.xref_get_key(page.xref, "MediaBox")
    nums = [float(n) for n in re.findall(r"-?[\d.]+", v)] if t == "array" \
        else [0, 0, page.rect.width, page.rect.height]
    return nums[:4]


def _tinted(doc, page, ops, name, xref, rgb, oc=0):
    """A transparency group drawing XObject `xref` (with the drawing
    operators `ops`) with its dark linework turned `rgb` (white stays
    white); drawn with Multiply it tints."""
    x0, y0, x1, y1 = _box(doc, page)
    g = doc.get_new_xref()
    doc.update_object(
        g, f"<</Type/XObject/Subtype/Form/BBox[{x0:g} {y0:g} {x1:g} {y1:g}]"
        "/Group<</S/Transparency/CS/DeviceRGB/I true/K false>>"
        f"/Resources<</XObject<</{name} {xref} 0 R>>"
        "/ExtGState<</Lt<</Type/ExtGState/BM/Lighten>>>>>>>>")
    r, gg, b = rgb
    w, h = x1 - x0, y1 - y0
    doc.update_stream(g, (
        f"q 1 1 1 rg {x0:g} {y0:g} {w:g} {h:g} re f Q q {ops} Q "
        f"q /Lt gs {r:.3f} {gg:.3f} {b:.3f} rg {x0:g} {y0:g} {w:g} {h:g} re "
        "f Q").encode())
    return (g, oc)


def _write(doc, page, layers):
    """Replace the page's content with `layers`: [drawing operators (str)
    or ("tint", (group xref, layer))] in drawing order."""
    res = _resources_xref(doc, page)
    if "Mul" not in (doc.xref_get_key(res, "ExtGState")[1] or ""):
        doc.xref_set_key(res, "ExtGState/Mul",
                         "<</Type/ExtGState/BM/Multiply>>")
    out = []
    for i, lay in enumerate(layers):
        if isinstance(lay, tuple) and lay[0] == "tint":
            g, oc = lay[1]
            nm = f"PSTint{g}"
            doc.xref_set_key(res, f"XObject/{nm}", f"{g} 0 R")
            draw = f" q /Mul gs /{nm} Do Q "
            if oc:
                prop = f"PSoc{oc}"
                doc.xref_set_key(res, f"Properties/{prop}", f"{oc} 0 R")
                draw = f" /OC /{prop} BDC{draw}EMC "
            out.append(draw.encode())
        else:
            out.append(f" q {lay} Q ".encode())
    conts = page.get_contents()
    doc.update_stream(conts[0], b"".join(out))
    for c in conts[1:]:
        doc.update_stream(c, b" ")


def _ocg(doc, name, on=True):
    for x, info in (doc.get_ocgs() or {}).items():
        if info.get("name") == name:
            return x
    x = doc.add_ocg(name, on=on)
    if not on:
        # make the open document honour it now, not only after reopening
        try:
            cur = doc.get_layer(-1) or {}
            off = list(cur.get("off") or [])
            if x not in off:
                off.append(x)
            doc.set_layer(-1, on=[o for o in (cur.get("on") or [])
                                  if o != x], off=off)
            for ui in doc.layer_ui_configs() or []:      # the live state
                if ui.get("text") == name and ui.get("on"):
                    doc.set_layer_ui_config(ui["number"],
                                            getattr(fitz, "PDF_OC_OFF", 2))
        except Exception:
            log.warning("couldn't switch the layer off", exc_info=True)
    return x


# ---- outputs -------------------------------------------------------------------------

def compare(old, new, by_number=True, auto_align=True, find_changes=True,
            progress=None):
    """Pair and compare two documents (fitz docs). Returns [{old, new,
    sheet, align: (scale, tx, ty, score, rotation), changes: [rects in
    the new page], changed_pct}].
    """
    out = []
    pairs = pair_pages(old, new, by_number)
    for k, (i, j, sheet) in enumerate(pairs):
        if progress and progress(k, len(pairs), sheet):
            break
        r = {"old": i, "new": j, "sheet": sheet, "align": IDENTITY,
             "changes": [], "changed_pct": 0.0}
        if i is not None and j is not None:
            try:
                r["align"] = align(old[i], new[j]) if auto_align else \
                    IDENTITY
                if find_changes:
                    r["changes"], r["changed_pct"] = changes(
                        old[i], new[j], r["align"])
            except Exception:
                log.exception("comparing %s", sheet)
        out.append(r)
    return out


def overlay_document(old, new, results, old_label="Older",
                     new_label="Newer", old_color=OLD_COLOR,
                     new_color=NEW_COLOR, clouds=True):
    """A new document: one overlay page per compared sheet (older tinted
    red, newer green, each on its own layer), changes clouded, and a
    bookmark per sheet."""
    out = fitz.open()
    oc_old = _ocg(out, f"{old_label} (red)")
    oc_new = _ocg(out, f"{new_label} (green)")
    toc = []
    for r in results:
        i, j = r["old"], r["new"]
        ref = new[j] if j is not None else old[i]
        page = out.new_page(width=ref.rect.width, height=ref.rect.height)
        layers = []
        if i is not None:
            ops, name, x = _place(page, old, i, r["align"] if j is not None
                                  else IDENTITY)
            layers.append(("tint", _tinted(out, page, ops, name, x,
                                           old_color, oc_old)))
        if j is not None:
            ops, name, x = _place(page, new, j)
            layers.append(("tint", _tinted(out, page, ops, name, x,
                                           new_color, oc_new)))
        _write(out, page, layers)
        what = ("added sheet" if i is None else "removed sheet" if j is None
                else f"{len(r['changes'])} change(s)")
        label = f"{r['sheet'] or f'Page {(j if j is not None else i) + 1}'}"
        toc.append([1, f"{label} - {what}", page.number + 1])
        if clouds and r["changes"]:
            for n, c in enumerate(r["changes"], 1):
                a = page.add_rect_annot(c)
                a.set_border(width=1.5, clouds=1)
                a.set_colors(stroke=(0.85, 0.1, 0.6))
                a.set_info(subject=CHANGE_SUBJECT,
                           content=f"Change {n} on {label}")
                a.update()
        if i is None or j is None:
            a = page.add_freetext_annot(
                fitz.Rect(18, 12, 400, 34), f"{label}: {what}", fontsize=12,
                text_color=(0.85, 0.1, 0.1))
            a.update()
    out.set_toc(toc)
    return out


def cloud_ops(results, doc_side="new", note=""):
    """(page, kind, payload) marks that cloud every change on this
    document (`doc_side` = which side of the comparison it is)."""
    marks = []
    for r in results:
        pno = r[doc_side]
        if pno is None:
            continue
        for n, c in enumerate(r["changes"], 1):
            rect = c if doc_side == "new" else map_rect(c, r["align"], True)
            marks.append((pno, "add_cloud", {
                "rect": list(rect), "color": [0.85, 0.1, 0.6],
                "subject": CHANGE_SUBJECT, "layer": CHANGE_LAYER,
                "note": (note or "Changed in the revision") +
                f" ({r['sheet'] or 'page ' + str(pno + 1)}, change {n})"}))
    return marks


def flag_ops(doc, results, doc_side="old"):
    """set_annot marks giving takeoffs on changed areas the status
    "Check - drawing revised"."""
    from . import annotate
    marks = []
    for r in results:
        pno = r[doc_side]
        if pno is None or not r["changes"]:
            continue
        zones = [c if doc_side == "new" else map_rect(c, r["align"], True)
                 for c in r["changes"]]
        page = doc[pno]
        seen = set()
        for a in annotate.iter_annots(page) or []:
            subj = (a.info or {}).get("subject", "")
            if not subj.startswith(annotate.TAKEOFF + ":"):
                continue
            ref = annotate.ref(a)
            key = tuple(sorted(ref.items()))
            if key in seen:
                continue
            if any(a.rect.intersects(z) for z in zones):
                seen.add(key)
                marks.append((pno, "set_annot", dict(
                    ref, status=REVIEW_STATUS)))
    return marks


def reopen(doc):
    """The document reopened from its bytes - MuPDF only picks up layers
    added to an open document (the hidden previous drawing) that way."""
    return fitz.open("pdf", doc.tobytes())


def slip_sheet(doc, new, results, label="Revision", keep_old=True,
               add_new_sheets=True):
    """Put the newer drawings into `doc` (the older set with your markups
    and takeoffs): each paired page gets the newer drawing, lined up with
    the old one so markups stay in place; the old drawing becomes the
    hidden layer "Previous drawing (<label>)". Sheets only in the newer
    set are added at the end. Returns {replaced, added, pages: {new index:
    doc page}}."""
    oc_prev = _ocg(doc, f"Previous drawing ({label})", on=False) \
        if keep_old else 0
    replaced, mapping = 0, {}
    for r in results:
        i, j = r["old"], r["new"]
        if i is None or j is None:
            continue
        page = doc[i]
        snap = fitz.open()
        snap.insert_pdf(doc, from_page=i, to_page=i, annots=False,
                        widgets=False)
        for c in page.get_contents():
            doc.update_stream(c, b" ")
        if not page.get_contents():
            x = doc.get_new_xref()
            doc.update_object(x, "<<>>")
            doc.update_stream(x, b" ")
            doc.xref_set_key(page.xref, "Contents", f"{x} 0 R")
        layers = []
        ops, name, x = _place(page, new, j, invert(r["align"]))
        layers.append(ops)
        if keep_old:
            ops2, name2, x2 = _place(page, snap, 0)
            layers.append(("tint", _tinted(doc, page, ops2, name2, x2,
                                           OLD_COLOR, oc_prev)))
        _write(doc, page, layers)
        snap.close()
        mapping[j] = i
        replaced += 1
    added = 0
    if add_new_sheets:
        for r in results:
            if r["old"] is None and r["new"] is not None:
                doc.insert_pdf(new, from_page=r["new"], to_page=r["new"])
                mapping[r["new"]] = doc.page_count - 1
                added += 1
    return {"replaced": replaced, "added": added, "pages": mapping}
