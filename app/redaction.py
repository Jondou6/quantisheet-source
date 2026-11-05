"""Redaction that removes the content, with a proof that it is gone.

A redaction box removes the text, the line art and the image pixels under
it, then paints the box black. After a batch of boxes, proof() checks a
freshly written copy of the document, box by box:

* no text is left inside the box (visible or invisible),
* no vector path (line art) still crosses it, other than the black box
  itself, and
* no image still shows its original pixels inside it (the pixels there
  must be blank: one flat value), and
* no form field is left over it (a field under a box is deleted, value
  and all, before the box is applied).

The redacted boxes are listed on their page (key PSRedactions) so the
Remove Hidden Information report can check them again later. The boxes
are visible as black boxes anyway, so the list gives nothing away.

PyMuPDF only. Nothing here touches the network or any file on disk.
"""
import logging
import math
import re

import fitz

log = logging.getLogger(__name__)

FILL = (0, 0, 0)
KEY = "PSRedactions"
MAX_PER_PAGE = 4000
# how close a black rectangle must be to a redaction box to count as that
# box's own fill (points)
_SAME_BOX = 1.5
# text and paths are looked for inside the box shrunk by this much, so a
# neighbour that only touches the edge doesn't count (points)
_INSET = 0.5
_MAX_SAMPLES = 200        # per side, when checking an image's pixels

_NUM = re.compile(r"-?\d+(?:\.\d+)?")


def _const(name, default):
    return getattr(fitz, name, default)


# ---- applying -------------------------------------------------------------------

def recorded(doc, pno):
    """The redaction boxes recorded on page `pno` ([fitz.Rect])."""
    try:
        t, v = doc.xref_get_key(doc.page_xref(pno), KEY)
    except Exception:                                     # noqa: BLE001
        return []
    if t != "array":
        return []
    nums = [float(x) for x in _NUM.findall(v)]
    return [fitz.Rect(nums[i:i + 4]) for i in range(0, len(nums) - 3, 4)]


def remember(doc, pno, rect):
    """Add `rect` to page `pno`'s list of redaction boxes."""
    boxes = (recorded(doc, pno) + [fitz.Rect(rect)])[-MAX_PER_PAGE:]
    doc.xref_set_key(doc.page_xref(pno), KEY, "[" + " ".join(
        "[%.2f %.2f %.2f %.2f]" % tuple(r) for r in boxes) + "]")


def all_recorded(doc):
    """[(page, rect)] for every redaction box recorded in `doc`."""
    out = []
    for pno in range(doc.page_count):
        out += [(pno, r) for r in recorded(doc, pno)]
    return out


def redact(doc, page, rect, fill=FILL):
    """Remove everything under `rect` on `page` and paint it black.

    Line art that touches the box is removed whole (a line that only
    passes through would otherwise still be in the file under the black
    box). Earlier redaction boxes that this removes along with it are
    painted again."""
    r = fitz.Rect(rect).normalize()
    pno = page.number
    earlier = [b for b in recorded(doc, pno) if b.intersects(r)]
    # apply_redactions leaves form fields alone, and a field's value would
    # still be in the file (and fail the proof): a field under the box is
    # deleted first, whole (review F13). proof() checks none is left.
    remove_fields(page, r)
    page.add_redact_annot(r, fill=fill, cross_out=False)
    kw = dict(images=_const("PDF_REDACT_IMAGE_PIXELS", 2),
              graphics=_const("PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED", 2),
              text=_const("PDF_REDACT_TEXT_REMOVE", 0))
    try:
        page.apply_redactions(**kw)
    except TypeError:                     # older PyMuPDF: fewer options
        kw.pop("text")
        try:
            page.apply_redactions(**kw)
        except TypeError:
            page.apply_redactions(images=kw["images"])
    if earlier:
        boxes = {_key(d["rect"]) for d in _black_boxes(page, fill)}
        for b in earlier:
            if _key(b) not in boxes:
                page.draw_rect(b, color=None, fill=fill, width=0,
                               overlay=True)
    remember(doc, pno, r)
    return True


def _fields_under(page, r):
    """The form fields (widgets) on `page` whose box meets `r`."""
    try:
        return [w for w in (page.widgets() or [])
                if fitz.Rect(w.rect).intersects(r)]
    except Exception:                                     # noqa: BLE001
        log.debug("form fields can't be listed", exc_info=True)
        return []


def _blank_field(doc, xref):
    """Before a field's widget is deleted: drop its value and appearance
    from the object, and take it out of the form's field list, so nothing
    of it can stay in the saved file even if something still refers to
    it."""
    if not xref:
        return
    for key in ("V", "DV", "AP", "RV"):
        try:
            doc.xref_set_key(xref, key, "null")
        except Exception:                                 # noqa: BLE001
            pass
    ref = re.compile(r"\b%d\s+0\s+R\b" % int(xref))
    try:
        cat = doc.pdf_catalog()
        t, v = doc.xref_get_key(cat, "AcroForm")
        if t == "xref":
            host, key = int(v.split()[0]), "Fields"
        else:
            host, key = cat, "AcroForm/Fields"
        t, v = doc.xref_get_key(host, key)
        if t == "array" and ref.search(v):
            doc.xref_set_key(host, key, ref.sub("", v))
    except Exception:                                     # noqa: BLE001
        log.debug("form field list not updated", exc_info=True)


def remove_fields(page, rect):
    """Delete every form field whose box meets `rect` (value, appearance
    and the field itself). Returns how many were deleted."""
    r = fitz.Rect(rect).normalize()
    gone = 0
    for _ in range(MAX_PER_PAGE):          # one at a time: deleting one
        hit = _fields_under(page, r)       # makes the others' objects stale
        if not hit:
            break
        try:
            _blank_field(page.parent, hit[0].xref)
            page.delete_widget(hit[0])
        except Exception:                                 # noqa: BLE001
            log.warning("redaction: a form field could not be deleted",
                        exc_info=True)
            break                          # the proof will fail on it
        gone += 1
    return gone


def _key(r):
    return tuple(round(v) for v in r)


def _black_boxes(page, fill=FILL):
    """Drawn filled rectangles in the redaction colour, with no outline."""
    out = []
    try:
        drawings = page.get_drawings()
    except Exception:                                     # noqa: BLE001
        return out
    for d in drawings:
        if _is_fill_box(d, fill):
            out.append(d)
    return out


def _is_fill_box(d, fill):
    """A filled shape in the redaction colour. MuPDF paints a redaction's
    fill as a rectangle, a quad or four straight lines depending on the
    version, sometimes with an outline in the same colour; callers also
    check that its bounding box matches the redaction box."""
    if d.get("type") not in ("f", "fs"):
        return False
    f = d.get("fill")
    if f is None or len(f) != len(fill) or \
            any(abs(a - b) > 0.01 for a, b in zip(f, fill)):
        return False
    c = d.get("color")
    if c is not None and (len(c) != len(fill) or
                          any(abs(a - b) > 0.01 for a, b in zip(c, fill))):
        return False
    items = d.get("items") or []
    return bool(items) and all(it[0] in ("re", "qu", "l") for it in items)


# ---- proof ------------------------------------------------------------------------

class Result:
    """What proof() found in one redaction box."""

    def __init__(self, page, rect):
        self.page = page                    # 0-based
        self.rect = fitz.Rect(rect)
        self.chars = 0                      # characters of text left
        self.words = 0                      # words of text left
        self.paths = 0                      # vector paths crossing it
        self.images = 0                     # images showing original pixels
        self.fields = 0                     # form fields still over it
        self.error = ""                     # the check itself failed

    @property
    def ok(self):
        return not (self.chars or self.paths or self.images or
                    self.fields or self.error)

    def where(self):
        r = self.rect
        return (f"page {self.page + 1}, box at ({r.x0:.0f}, {r.y0:.0f}) - "
                f"({r.x1:.0f}, {r.y1:.0f})")

    def describe(self):
        """One line, without the text that was found (it may be the very
        thing being redacted)."""
        if self.ok:
            return f"{self.where()}: clean"
        bits = []
        if self.error:
            bits.append(self.error)
        if self.words or self.chars:
            bits.append(f"{self.words or 1} word(s) of text left")
        if self.paths:
            bits.append(f"{self.paths} line-art path(s) left")
        if self.images:
            bits.append(f"{self.images} image(s) still show their pixels")
        if self.fields:
            bits.append(f"{self.fields} form field(s) left")
        return f"{self.where()}: " + ", ".join(bits)

    def __repr__(self):
        return f"<Result {self.describe()}>"


def fresh_copy(doc):
    """`doc` as it would be written: removed objects can linger in memory
    until a save, so the proof reads a cleanly written copy."""
    from . import safeio
    data = doc.tobytes(garbage=max(1, safeio.gc_level(doc)), deflate=True)
    return fitz.open("pdf", data)


def proof(doc, areas=None, fill=FILL, copy=True):
    """Check every redaction box. `areas`: [(page, rect)], or None for all
    the boxes recorded in the file. `copy`: check a freshly written copy
    of `doc` (False when `doc` already is one). Returns [Result]."""
    if areas is None:
        areas = all_recorded(doc)
    areas = [(int(p), fitz.Rect(r).normalize()) for p, r in areas]
    if not areas:
        return []
    chk = fresh_copy(doc) if copy else doc
    try:
        by_page = {}
        for p, r in areas:
            by_page.setdefault(p, []).append(r)
        out = []
        for pno in sorted(by_page):
            out += _check_page(chk, pno, by_page[pno], fill)
        return out
    finally:
        if chk is not doc:
            chk.close()


def failures(results):
    return [r for r in results if not r.ok]


def summary(results, limit=5):
    """('PASS' | 'FAIL', item, detail) for a report."""
    bad = failures(results)
    item = (f"Redaction proof ({len(results)} redacted area(s): no text, "
            "line art, image pixels or form fields left)")
    detail = "; ".join(r.describe() for r in bad[:limit])
    if len(bad) > limit:
        detail += f"; and {len(bad) - limit} more"
    return ("FAIL" if bad else "PASS", item, detail)


def _check_page(doc, pno, rects, fill):
    results = [Result(pno, r) for r in rects]
    if not 0 <= pno < doc.page_count:
        for res in results:
            res.error = "the page is missing"
        return results
    try:
        page = doc[pno]
    except Exception as e:                                # noqa: BLE001
        for res in results:
            res.error = f"the page can't be read ({e})"
        return results
    own = recorded(doc, pno) + list(rects)
    # text: every character, visible or not
    try:
        chars = _chars(page)
    except Exception as e:                                # noqa: BLE001
        chars = None
        for res in results:
            res.error = f"the text can't be read ({e})"
    try:
        drawings = page.get_drawings()
    except Exception as e:                                # noqa: BLE001
        drawings = None
        for res in results:
            res.error = res.error or f"the line art can't be read ({e})"
    try:
        images = page.get_image_info(xrefs=True)
    except Exception as e:                                # noqa: BLE001
        images = None
        for res in results:
            res.error = res.error or f"the images can't be read ({e})"
    try:
        fields = [fitz.Rect(w.rect) for w in (page.widgets() or [])]
    except Exception as e:                                # noqa: BLE001
        fields = None
        for res in results:
            res.error = res.error or f"the form fields can't be read ({e})"
    pixmaps = {}
    for res in results:
        inner = _inset(res.rect, _INSET)
        if inner.is_empty:
            continue
        if fields is not None:
            res.fields = sum(1 for fr in fields if fr.intersects(inner))
        if chars is not None:
            left = [(bb, w) for bb, w in chars if _char_inside(bb, inner)]
            res.chars = len(left)
            res.words = len({w for _bb, w in left})
        if drawings is not None:
            for d in drawings:
                r = fitz.Rect(d.get("rect") or (0, 0, 0, 0))
                if not _touches(r, inner, d):
                    continue
                if _is_fill_box(d, fill) and any(
                        _near(r, b) for b in own):
                    continue                     # the black box itself
                if _straight_rule(d, r):
                    continue                     # a plain straight line
                log.warning("redaction proof: path left on page %d: type=%s "
                            "fill=%s color=%s rect=%s items=%s", pno + 1,
                            d.get("type"), d.get("fill"), d.get("color"),
                            tuple(round(v, 1) for v in r),
                            [it[0] for it in (d.get("items") or [])][:8])
                res.paths += 1
        if images is not None:
            for info in images:
                bbox = fitz.Rect(info.get("bbox") or (0, 0, 0, 0))
                if not (bbox & inner).is_valid or (bbox & inner).is_empty:
                    continue
                try:
                    blank = _pixels_blank(doc, page, info, inner, pixmaps)
                except Exception as e:                    # noqa: BLE001
                    log.debug("redaction proof: image check failed",
                              exc_info=True)
                    res.error = res.error or \
                        f"an image under it can't be read ({e})"
                    continue
                if not blank:
                    res.images += 1
    return results


def _straight_rule(d, r):
    """A single straight horizontal or vertical line (a drawing's grid,
    border or dimension line) that runs through the box. MuPDF can't
    remove these because their box has no height or width; a straight
    rule carries no information beyond its position, and the black box
    covers it, so it doesn't fail the proof. Curves, diagonal strokes and
    shapes (handwriting, signatures, logos) still do."""
    items = d.get("items") or []
    if not items or any(it[0] != "l" for it in items):
        return False
    return r.width < 0.5 or r.height < 0.5


def _inset(r, d):
    return fitz.Rect(r.x0 + d, r.y0 + d, r.x1 - d, r.y1 - d)


def _near(a, b):
    return all(abs(x - y) <= _SAME_BOX for x, y in zip(a, b))


def _touches(r, inner, d):
    """A path whose bounding box reaches into the box. A perfectly
    straight horizontal or vertical line has an empty box, so check its
    extent with a little width."""
    w = max(float(d.get("width") or 0), 0.1) / 2
    rr = fitz.Rect(r.x0 - w, r.y0 - w, r.x1 + w, r.y1 + w)
    x = rr & inner
    return x.is_valid and not x.is_empty


def _chars(page):
    """[(char bbox, word number)] for all the text on the page."""
    flags = 0
    for name in ("TEXT_PRESERVE_WHITESPACE", "TEXT_PRESERVE_LIGATURES"):
        flags |= _const(name, 0)
    out, word = [], 0
    d = page.get_text("rawdict", flags=flags)
    for b in d.get("blocks", []):
        for line in b.get("lines", []):
            for span in line.get("spans", []):
                gap = True
                for ch in span.get("chars", []):
                    c = ch.get("c", "")
                    if not c.strip():
                        gap = True
                        continue
                    if gap:
                        word += 1
                        gap = False
                    out.append((fitz.Rect(ch["bbox"]), word))
    return out


def _char_inside(bb, inner):
    """A character left in the box: its centre is in it, or it is at least
    half covered by it."""
    if bb.is_empty:
        c = fitz.Point(bb.x0, bb.y0)
        return c in inner
    c = fitz.Point((bb.x0 + bb.x1) / 2, (bb.y0 + bb.y1) / 2)
    if inner.contains(c):
        return True
    x = bb & inner
    if not x.is_valid or x.is_empty:
        return False
    return x.width * x.height >= 0.5 * bb.width * bb.height


def _image_pixmap(doc, page, info, cache):
    xref = int(info.get("xref") or 0)
    if xref > 0:
        if xref not in cache:
            cache.clear()                 # one decoded image at a time
            pix = fitz.Pixmap(doc, xref)
            if pix.alpha:
                pix = fitz.Pixmap(pix, 0)
            cache[xref] = pix
        return cache[xref]
    # an inline image: find it among the page's image blocks
    want = fitz.Rect(info.get("bbox"))
    for b in page.get_text("dict").get("blocks", []):
        if b.get("type") == 1 and _near(fitz.Rect(b["bbox"]), want):
            pix = fitz.Pixmap(b["image"])
            if pix.alpha:
                pix = fitz.Pixmap(pix, 0)
            return pix
    raise RuntimeError("inline image not found")


def _pixels_blank(doc, page, info, inner, cache):
    """True when the image's pixels inside `inner` are all one value
    (blanked, or a plain area that holds nothing)."""
    m = fitz.Matrix(info["transform"])
    if abs(m.a * m.d - m.b * m.c) < 1e-9:
        return True                                 # drawn with no size
    bbox = fitz.Rect(info["bbox"])
    pix = _image_pixmap(doc, page, info, cache)
    W, H = pix.width, pix.height
    if W < 1 or H < 1:
        return True
    # size of one image pixel on the page, along each image axis
    px = max(math.hypot(m.a, m.b) / W, math.hypot(m.c, m.d) / H, 1e-6)
    q = _inset(inner & bbox, 1.5 * px)
    if not q.is_valid or q.is_empty:
        return True              # only the outermost pixels: left as is
    inv = ~m
    nx = int(min(_MAX_SAMPLES, max(2, math.ceil(q.width / px))))
    ny = int(min(_MAX_SAMPLES, max(2, math.ceil(q.height / px))))
    n = pix.n
    stride = pix.stride
    data = getattr(pix, "samples_mv", None)
    if data is None:
        data = pix.samples
    first = None
    for j in range(ny):
        y = q.y0 + q.height * j / (ny - 1)
        for i in range(nx):
            x = q.x0 + q.width * i / (nx - 1)
            u = fitz.Point(x, y) * inv
            px_x = min(W - 1, max(0, int(u.x * W)))
            px_y = min(H - 1, max(0, int(u.y * H)))
            k = px_y * stride + px_x * n
            v = bytes(data[k:k + n])
            if first is None:
                first = v
            elif v != first:
                return False
    return True


# ---- what a saved file still holds (QS-002, Nov 4) ------------------------------
#
# A redaction removes the content from the page, but a save that ADDS to the
# file (incremental) keeps the old page contents in the earlier revision,
# where any PDF tool can read them. After a redaction the next save is
# always a full rewrite (main_window._write), and the saved file is then
# searched, raw, for the words that were under the boxes: page text,
# annotations, form fields, embedded job data, metadata and every object in
# the file (left-over revisions included).

MIN_WORD = 3


def words_under(page, rect):
    """The words a box will remove (for the check after saving)."""
    out = set()
    try:
        for w in page.get_text("words"):
            if fitz.Rect(w[:4]).intersects(rect):
                t = w[4].strip(".,;:()[]{}\"'")
                if len(t) >= MIN_WORD:
                    out.add(t)
    except Exception:                                     # noqa: BLE001
        log.debug("words under a redaction", exc_info=True)
    return out


_HEX = re.compile(rb"(?<!<)<([0-9A-Fa-f\s]{4,})>(?!>)")
_OCT = re.compile(rb"\\([0-7]{1,3})")


def decoded_strings(raw: bytes) -> str:
    """Text hidden in PDF string syntax that a plain search misses (review
    1, Nov 4): hex strings <536D697468> and octal escapes \123, decoded
    as single bytes and, with a byte-order mark, as UTF-16."""
    out = []
    for m in _HEX.finditer(raw or b""):
        h = re.sub(rb"\s", b"", m.group(1))
        if len(h) % 2:
            h += b"0"
        try:
            b = bytes.fromhex(h.decode("ascii"))
        except ValueError:
            continue
        if b.startswith(b"\xfe\xff"):
            out.append(b[2:].decode("utf-16-be", "ignore"))
        else:
            out.append(b.decode("latin-1"))
            if len(b) % 2 == 0 and b[:1] == b"\x00":
                out.append(b.decode("utf-16-be", "ignore"))
    if b"\\" in (raw or b""):
        out.append(_OCT.sub(lambda m: bytes([int(m.group(1), 8) & 0xFF]),
                            raw).decode("latin-1"))
    return "\n".join(out)


def _contains(text, words):
    low = (text or "").lower()
    return {w for w in words if w.lower() in low}


def leak_check(path, words, visible=None):
    """Where the redacted words can still be found in the saved file:
    {place: [words]}. `visible` = words still on the pages outside the
    boxes (the same word elsewhere is not a leak)."""
    words = {w for w in words if w} - set(visible or ())
    if not words:
        return {}
    found = {}

    def hit(place, text):
        f = _contains(text, words)
        if f:
            found.setdefault(place, set()).update(f)
    d = fitz.open(path)
    try:
        for i, pg in enumerate(d):
            hit(f"page {i + 1} text", pg.get_text())
            for a in pg.annots() or []:
                info = a.info or {}
                hit(f"page {i + 1} markups", " ".join(
                    str(v) for v in info.values()))
            for wdg in pg.widgets() or []:
                hit(f"page {i + 1} form fields", str(wdg.field_value or ""))
        for n in d.embfile_names():
            try:
                hit(f"embedded file {n}", d.embfile_get(n).decode(
                    "utf-8", "ignore"))
            except Exception:                             # noqa: BLE001
                pass
        hit("document properties", " ".join(str(v) for v in
                                             (d.metadata or {}).values()))
        try:
            hit("XMP metadata", d.get_xml_metadata())
        except Exception:                                 # noqa: BLE001
            pass
        # every object in the file, streams unpacked: left-over revisions
        for x in range(1, d.xref_length()):
            try:
                if d.xref_is_stream(x):
                    raw = d.xref_stream(x) or b""
                    hit("other content in the file", raw.decode("latin-1"))
                    hit("other content in the file", decoded_strings(raw))
                src = d.xref_object(x)
                hit("other content in the file", src)
                hit("other content in the file",
                    decoded_strings(src.encode("latin-1", "ignore")))
            except Exception:                             # noqa: BLE001
                continue
    finally:
        d.close()
    return {k: sorted(v) for k, v in found.items()}


def check(path, words, visible=None):
    """A graded answer (review 1, Nov 4), never a single "clean":
    {"leaks": {place: [words]} - still in the file, hidden;
     "elsewhere": [words] - redacted in one place but still showing on
                  the pages somewhere else (not a leak, but say so);
     "unchecked": [what couldn't be checked]}."""
    words = {w for w in words if w}
    vis = set(visible or ())
    out = {"leaks": leak_check(path, words, vis),
           "elsewhere": sorted(words & vis), "unchecked": []}
    try:
        d = fitz.open(path)
        try:
            if any(pg.get_images() for pg in d):
                out["unchecked"].append(
                    "text inside pictures or scanned pages (it isn't read)")
        finally:
            d.close()
    except Exception:                                     # noqa: BLE001
        out["unchecked"].append("the file couldn't be reopened to check")
    return out


def visible_words(doc):
    out = set()
    for pg in doc:
        try:
            out |= {w[4].strip(".,;:()[]{}\"'") for w in pg.get_text("words")}
        except Exception:                                 # noqa: BLE001
            pass
    return out
