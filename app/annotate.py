"""One place that turns an edit ("op") into changes to the PDF.

The desktop view, auto-markup rules, macros, AI review, takeoff and live
collaboration all go through apply_op(), so an edit looks the same whether
it was made locally or arrived from a collaborator.

Coordinates in ops are *unrotated* page coordinates (what PyMuPDF's
add_*_annot functions expect). Use to_page()/from_page() to convert from
and to what is shown on screen for rotated pages.

Every annotation is tagged with its op id (in the annotation's /NM entry),
which makes apply_op() idempotent: re-applying an op that is already on the
page does nothing. Marks are real annotations, so they can be selected,
edited and deleted in any PDF viewer.
"""
import base64
import json as _json
import logging
import uuid
import weakref as _weakref

import fitz
from . import embfiles
from .dmoney import c2 as _c2

log = logging.getLogger(__name__)

TAG = "quantisheet-op:"
from .oldnames import TAG_OLD as _TAG_OLD      # markups saved before
TAKEOFF = "Takeoff"          # /Subj prefix for measurement annotations
SCALE_FILE = "quantisheet_scale.json"

RECT_KINDS = {"add_highlight", "add_underline", "add_strike", "add_rect",
              "add_ellipse", "add_cloud", "add_stamp", "add_redact",
              "replace_span", "replace_block", "add_textbox", "add_image",
              "add_field",
              "add_callout", "move_image", "delete_image", "replace_image"}
POINT_KINDS = {"add_count", "add_text", "add_note"}
POINTS_KINDS = {"add_line", "add_polyline", "add_polygon"}
OTHER_KINDS = {"add_ink", "delete_annot", "set_annot", "set_vertices",
               "set_measure", "set_captions", "set_field",
               "set_scale", "add_legend", "import_annots", "set_jobdata"}
KINDS = RECT_KINDS | POINT_KINDS | POINTS_KINDS | OTHER_KINDS
# ops that change the page itself rather than adding an annotation
CONTENT_KINDS = {"add_redact", "replace_span", "replace_block", "add_image",
                 "move_image", "delete_image", "replace_image"}
# ops that undo must snapshot the whole document for
FULL_UNDO_KINDS = CONTENT_KINDS | {"add_field", "set_scale", "set_jobdata"}

# job data files an op may write (name -> (description, most bytes)).
# A peer in live collaboration can only send these (outside review, Nov 7
# - H4: the ADA checker's data went around the op log).
JOBDATA_FILES = {"quantisheet_ada.json": ("QuantiSheet ADA check",
                                          1_000_000)}

DEFAULT_COLORS = {
    "add_highlight": (1, 1, 0), "add_underline": (1, 0, 0),
    "add_strike": (1, 0, 0), "add_rect": (0, 0, 1), "add_ellipse": (0, 0, 1),
    "add_cloud": (1, 0, 0), "add_count": (1, 0, 0), "add_text": (0, 0, 0),
    "add_note": (1, 0.8, 0), "add_line": (1, 0, 0), "add_polyline": (1, 0, 0),
    "add_polygon": (1, 0, 0), "add_ink": (0, 0, 1), "add_textbox": (0, 0, 0),
    "replace_span": (0, 0, 0),
    "replace_block": (0, 0, 0),
}


def new_op(kind, page, **payload):
    """An op for direct, non-collaborative use (CLI, tests)."""
    return {"id": uuid.uuid4().hex, "kind": kind, "page": page,
            "payload": payload}


# ---- coordinates -------------------------------------------------------------

def to_page(page, obj):
    """Screen (rotated) coordinates -> op (unrotated) coordinates."""
    m = page.derotation_matrix
    if isinstance(obj, fitz.Rect):
        return (obj * m).normalize()
    return obj * m


def from_page(page, obj):
    """Op (unrotated) coordinates -> screen (rotated) coordinates."""
    m = page.rotation_matrix
    if isinstance(obj, fitz.Rect):
        return (obj * m).normalize()
    return obj * m


# ---- payload parsing -----------------------------------------------------------

def _rect(p):
    try:
        r = fitz.Rect(p["rect"]).normalize()
    except (KeyError, TypeError, ValueError):
        return None
    return None if (r.is_empty or r.is_infinite) else r


def _point(p, key="pt"):
    try:
        x, y = p[key]
        return fitz.Point(float(x), float(y))
    except (KeyError, TypeError, ValueError):
        return None


def _points(seq, minimum):
    try:
        pts = [fitz.Point(float(x), float(y)) for x, y in seq]
    except (TypeError, ValueError):
        return None
    return pts if len(pts) >= minimum else None


def _color(p, kind, key="color"):
    default = DEFAULT_COLORS.get(kind, (0, 0, 0))
    try:
        c = tuple(float(x) for x in p.get(key, default))
    except (TypeError, ValueError):
        return default
    return c if len(c) == 3 and all(0 <= x <= 1 for x in c) else default


def _size(p, default=10):
    s = p.get("size", default)
    return s if isinstance(s, (int, float)) and 2 <= s <= 200 else default


def _width(p, default=1.5):
    w = p.get("width", default)
    return w if isinstance(w, (int, float)) and 0.1 <= w <= 50 else default


# ---- tags ----------------------------------------------------------------------

def iter_annots(page):
    """The page's annotations (not form fields), walking the list once.
    PyMuPDF's page.annots() looks each one up again from the start of the
    list, which is quadratic: 80 ms for every pass over a sheet with 150
    markups, and many actions make several passes. (Annot.next would be
    linear but leaves the page referenced until garbage collection, which
    breaks reload_page; these are wrapped the way load_annot does.)"""
    import weakref
    mu = fitz.mupdf
    try:
        pdfpage = page._pdf_page()
        annot = mu.pdf_first_annot(pdfpage)
    except Exception:                       # not a PDF page / old PyMuPDF
        yield from page.annots()
        return
    proxy = weakref.proxy(page)
    while annot.m_internal:
        nxt = mu.pdf_next_annot(annot)
        val = fitz.Annot(annot)
        val.thisown = True
        val.parent = proxy
        page._annot_refs[id(val)] = val
        yield val
        annot = nxt


def tag_of(annot):
    """The op id an annotation was created by, or None."""
    nm = (annot.info or {}).get("id", "")
    for t in (TAG, _TAG_OLD):
        if nm.startswith(t):
            return nm[len(t):]
    return None


def is_applied(page, op_id):
    t = str(op_id)
    return any(tag_of(a) == t for a in iter_annots(page))


def _tag(doc, annot, op_id):
    doc.xref_set_key(annot.xref, "NM", fitz.get_pdf_str(TAG + str(op_id)))


def ref(annot):
    """How to point at an annotation in a later op (delete/set_annot)."""
    t = tag_of(annot)
    return {"target": t} if t else {"xref": annot.xref}


def find_annots(page, p):
    """Annotations an op refers to, by op id, xref, or exact rect."""
    target, xref = p.get("target"), p.get("xref")
    if isinstance(target, str):
        return [a for a in iter_annots(page) if tag_of(a) == target]
    if isinstance(xref, int):
        return [a for a in iter_annots(page) if a.xref == xref]
    r = _rect(p)
    if r is None:
        return []
    return [a for a in iter_annots(page)
            if all(abs(x - y) <= 1 for x, y in zip(a.rect, r))]


# ---- paragraph editing --------------------------------------------------------

_SERIF = ("times", "serif", "georgia", "garamond", "cambria", "book",
          "minion", "palatino")
_MONO = ("courier", "mono", "consol")


def _base14(font, bold=False, italic=False):
    f = (font or "").lower()
    bold = bold or "bold" in f or "black" in f or "heavy" in f
    italic = italic or "italic" in f or "oblique" in f
    if any(k in f for k in _MONO):
        return {(0, 0): "cour", (1, 0): "cobo", (0, 1): "coit",
                (1, 1): "cobi"}[(int(bold), int(italic))]
    if any(k in f for k in _SERIF):
        return {(0, 0): "tiro", (1, 0): "tibo", (0, 1): "tiit",
                (1, 1): "tibi"}[(int(bold), int(italic))]
    return {(0, 0): "helv", (1, 0): "hebo", (0, 1): "heit",
            (1, 1): "hebi"}[(int(bold), int(italic))]


def _embedded_font(doc, page, name, text):
    """The paragraph's own font, if it's embedded in full: a subset font
    is missing the letters the new text may need."""
    want = (name or "").split("+")[-1].lower()
    for f in page.get_fonts(full=True):
        base = (f[3] or "").split("+")[-1].lower()
        if not want or base != want:
            continue
        try:
            fname, ext, _t, buf = doc.extract_font(f[0])
        except Exception:
            continue
        if not buf or ext not in ("ttf", "otf", "cff", "pfa", "pfb"):
            continue
        try:
            font = fitz.Font(fontbuffer=buf)
        except Exception:
            continue
        if all(font.has_glyph(ord(ch)) for ch in set(text) if ch.strip()):
            return buf
    return None


def _redact_text(page, r):
    page.add_redact_annot(r, fill=None, cross_out=False)
    try:
        page.apply_redactions(
            images=getattr(fitz, "PDF_REDACT_IMAGE_NONE", 0),
            graphics=getattr(fitz, "PDF_REDACT_LINE_ART_NONE", 0),
            text=getattr(fitz, "PDF_REDACT_TEXT_REMOVE", 0))
    except TypeError:                       # older PyMuPDF
        page.apply_redactions(
            images=getattr(fitz, "PDF_REDACT_IMAGE_NONE", 0),
            graphics=getattr(fitz, "PDF_REDACT_LINE_ART_NONE", 0))


class _RichParser:
    """The small HTML the in-place editor writes (app/textedit.to_html):
    <p style="text-align:..."><span style="font-size:..pt;font-family:..;
    font-weight:bold;font-style:italic;color:#rrggbb">text<br></span></p>
    -> [{"align", "runs": [(text, style)]}]; "\n" in text is a line
    break."""

    def __init__(self, html_text):
        from html.parser import HTMLParser
        out = self.paras = []
        stack = [{}]

        def css(attrs):
            d = {}
            for part in (dict(attrs).get("style") or "").split(";"):
                if ":" in part:
                    k, v = part.split(":", 1)
                    d[k.strip().lower()] = v.strip()
            return d

        class P(HTMLParser):
            def handle_starttag(self, tag, attrs):
                st = css(attrs)
                if tag == "p":
                    out.append({"align": st.get("text-align", "left"),
                                "runs": []})
                    stack.append({})
                elif tag == "span":
                    stack.append(st)
                elif tag == "br":
                    self._text("\n")

            def handle_endtag(self, tag):
                if tag in ("p", "span") and len(stack) > 1:
                    stack.pop()

            def _text(self, t):
                if not out:
                    out.append({"align": "left", "runs": []})
                merged = {}
                for st in stack:
                    merged.update(st)
                out[-1]["runs"].append((t, merged))

            def handle_data(self, data):
                if data:
                    self._text(data.replace("\u2028", "\n"))
        P(convert_charrefs=True).feed(html_text or "")


def _rich_fonts(doc, page, p, text):
    """style -> (fitz.Font, size, rgb)."""
    cache = {}
    buf = _embedded_font(doc, page, p.get("font"), text)
    orig_b, orig_i = bool(p.get("bold")), bool(p.get("italic"))
    base = p.get("font") or ""

    def get(st):
        try:
            size = float(str(st.get("font-size", "")).replace("pt", "")
                         .replace("px", ""))
        except ValueError:
            size = _size(p, 10)
        size = max(2.0, min(200.0, size))
        fam = st.get("font-family", "sans-serif").strip("'\" ").lower()
        b = st.get("font-weight", "") in ("bold", "600", "700", "800", "900")
        i = st.get("font-style", "") in ("italic", "oblique")
        col = st.get("color", "")
        try:
            rgb = tuple(int(col[k:k + 2], 16) / 255 for k in (1, 3, 5)) \
                if col.startswith("#") and len(col) == 7 else None
        except ValueError:
            rgb = None
        rgb = rgb or tuple(p.get("color") or (0, 0, 0))
        key = (fam, b, i)
        if key not in cache:
            font = None
            if fam == "psorig" and buf and (b, i) == (orig_b, orig_i):
                try:
                    font = fitz.Font(fontbuffer=buf)
                except Exception:
                    font = None
            if font is None:
                like = {"serif": "times", "monospace": "courier"}.get(
                    fam, base if fam == "psorig" else "helvetica")
                font = fitz.Font(_base14(like, b, i))
            cache[key] = font
        return cache[key], size, rgb
    return get


def _layout_rich(paras, fonts, width, lh_ratio, scale=1.0):
    """Greedy word wrap of styled runs. Returns (lines, height); a line
    is {"items": [(x, text, font, size, rgb)], "asc", "h"}."""
    lines = []
    for para in paras:
        toks = []                          # (text, font, size, rgb) words
        for text, st in para["runs"]:
            font, size, rgb = fonts(st)
            size *= scale
            for piece in re_split_keep(text):
                toks.append((piece, font, size, rgb))
        cur, x = [], 0.0

        def flush(last):
            h = max((t[3] for t in cur), default=None)
            if h is None:
                f0 = toks[0] if toks else None
                h = f0[2] if f0 else 10 * scale
                asc = h * 0.8
            else:
                asc = max(t[2].ascender * t[3] for t in cur)
            lines.append({"items": list(cur), "h": h * lh_ratio, "asc": asc,
                          "align": para["align"], "last": last})
        for text, font, size, rgb in toks:
            if text == "\n":
                flush(True)
                cur, x = [], 0.0
                continue
            w = font.text_length(text, fontsize=size)
            if text.isspace():
                if cur:
                    cur.append((x, text, font, size, rgb, w))
                    x += w
                continue
            if cur and x + w > width + 0.01:
                while cur and cur[-1][1].isspace():
                    cur.pop()
                flush(False)
                cur, x = [], 0.0
            while w > width and len(text) > 1:      # a word wider than
                k = len(text)                       # the box: break it
                while k > 1 and font.text_length(text[:k], fontsize=size) \
                        > width:
                    k -= 1
                cur.append((x, text[:k], font, size, rgb,
                            font.text_length(text[:k], fontsize=size)))
                flush(False)
                cur, x = [], 0.0
                text = text[k:]
                w = font.text_length(text, fontsize=size)
            cur.append((x, text, font, size, rgb, w))
            x += w
        while cur and cur[-1][1].isspace():
            cur.pop()
        flush(True)
    return lines, sum(ln["h"] for ln in lines)


def re_split_keep(text):
    import re
    return [t for t in re.split(r"(\n| +)", text) if t]


def _replace_html(doc, page, r, p):
    """In-place editing (app/textedit.py) sends the paragraph as simple
    HTML with per-run font, size, weight, slant and colour. It is laid
    out here word by word - in the paragraph's own font when that's
    embedded in full - so the text stays real, searchable text (no
    ligature glyphs), and the box grows downward if it's longer."""
    text = str(p.get("text", ""))
    if not p.get("new"):
        _redact_text(page, r)
    if not text.strip():
        return True
    paras = _RichParser(str(p.get("html") or "")).paras
    if not any(t.strip() for para in paras for t, _s in para["runs"]):
        return True
    fonts = _rich_fonts(doc, page, p, text)
    size = _size(p, 10)
    lh = p.get("line_height")
    ratio = max(0.9, min(3.0, lh / size)) if lh and size else 1.18
    box = fitz.Rect(r)
    width = max(12.0, box.width)
    room = page.rect.y1 - 2 - box.y0
    scale = 1.0
    for _ in range(12):
        lines, height = _layout_rich(paras, fonts, width, ratio, scale)
        if height <= room or scale < 0.5:
            break
        scale *= 0.92
    writers = {}
    y = box.y0
    for ln in lines:
        items = ln["items"]
        used = (items[-1][0] + items[-1][5]) if items else 0.0
        extra = width - used
        shift, gap = 0.0, 0.0
        if ln["align"] == "center":
            shift = extra / 2
        elif ln["align"] == "right":
            shift = extra
        elif ln["align"] == "justify" and not ln["last"]:
            spaces = sum(1 for it in items if it[1].isspace())
            gap = extra / spaces if spaces else 0.0
        base = y + ln["asc"]
        n_sp = 0
        for x, t, font, fs, rgb, _w in items:
            if t.isspace():
                n_sp += 1
                continue
            tw = writers.get(rgb)
            if tw is None:
                tw = writers[rgb] = fitz.TextWriter(page.rect)
            # a trailing space keeps the words apart when text is copied
            tw.append((box.x0 + x + shift + gap * n_sp, base), t + " ",
                      font=font, fontsize=fs)
        y += ln["h"]
    for rgb, tw in writers.items():
        tw.write_text(page, color=rgb)
    return True


def _image_bytes(doc, xref):
    """The picture as an image file, with its transparency."""
    info = doc.extract_image(xref)
    if info and info.get("smask"):
        try:
            pix = fitz.Pixmap(fitz.Pixmap(doc, xref),
                              fitz.Pixmap(doc, info["smask"]))
            return pix.tobytes("png")
        except Exception:
            logging.getLogger(__name__).debug("ignored error", exc_info=True)
    if info and info.get("image"):
        return info["image"]
    return fitz.Pixmap(doc, xref).tobytes("png")


def _remove_image(page, r):
    """Take the picture in `r` off this page only (other pages that use
    the same image keep it). Text and lines there stay."""
    inner = fitz.Rect(r)
    dx, dy = inner.width * 0.25, inner.height * 0.25
    inner = fitz.Rect(inner.x0 + dx, inner.y0 + dy, inner.x1 - dx,
                      inner.y1 - dy)
    page.add_redact_annot(inner, fill=None, cross_out=False)
    kw = {"images": getattr(fitz, "PDF_REDACT_IMAGE_REMOVE", 1),
          "graphics": getattr(fitz, "PDF_REDACT_LINE_ART_NONE", 0)}
    if hasattr(fitz, "PDF_REDACT_TEXT_NONE"):
        kw["text"] = fitz.PDF_REDACT_TEXT_NONE
    try:
        page.apply_redactions(**kw)
    except TypeError:                     # older PyMuPDF
        kw.pop("text", None)
        page.apply_redactions(**kw)


def _image_op(doc, page, kind, r, p):
    xref = int(p.get("xref") or 0)
    old = _rect({"rect": p["from"]}) if p.get("from") else r
    if kind == "replace_image":
        data = base64.b64decode(p.get("data", ""))
        if not data:
            return False
        if xref:
            _remove_image(page, old)
        page.insert_image(r, stream=data, keep_proportion=True)
        return True
    if not xref:
        return False
    data = _image_bytes(doc, xref) if kind == "move_image" else None
    _remove_image(page, old)
    if kind == "move_image":
        page.insert_image(r, stream=data, keep_proportion=False)
    return True


def _replace_block(doc, page, r, p, color):
    """Edit a paragraph: the old text in the block's box goes (graphics
    under it stay) and the new text is set in its place, wrapped to the
    box's width in the paragraph's own font when it's fully embedded, else
    the nearest standard one. If it doesn't fit, the size steps down a
    little, then the box grows downward."""
    if p.get("html"):
        return _replace_html(doc, page, r, p)
    text = str(p.get("text", ""))
    size = _size(p, 10)
    if not p.get("new"):
        _redact_text(page, r)
    if not text.strip():
        return True
    fontname = _base14(p.get("font"), p.get("bold"), p.get("italic"))
    buf = _embedded_font(doc, page, p.get("font"), text)
    if buf:
        fontname = "PSEdit" + str(abs(hash(p.get("font"))) % 10000)
        try:
            page.insert_font(fontname=fontname, fontbuffer=buf)
        except Exception:
            fontname = _base14(p.get("font"), p.get("bold"), p.get("italic"))
    align = {"left": 0, "center": 1, "right": 2, "justify": 3}.get(
        p.get("align"), 0)
    lh = p.get("line_height")
    box = fitz.Rect(r)
    tries = [size * k for k in (1.0, 0.95, 0.9, 0.85)]
    for fs in tries + [tries[-1]] * 8:
        trial = fitz.open()
        tp = trial.new_page(width=page.rect.width, height=page.rect.height)
        kw = {"lineheight": lh / fs} if lh else {}
        try:
            left = tp.insert_textbox(box, text, fontsize=fs,
                                     fontname=fontname if not buf else "helv",
                                     align=align, **kw)
        except Exception:
            left = -1
        trial.close()
        if left >= 0:
            break
        if fs == tries[-1]:
            box.y1 = min(page.rect.height - 2, box.y1 + fs * 1.3)
    kw = {"lineheight": lh / fs} if lh else {}
    page.insert_textbox(box, text, fontsize=fs, fontname=fontname,
                        color=color, align=align, **kw)
    return True


# ---- drawing helpers ---------------------------------------------------------

def _label(page, pt, text, size, color, boxed):
    width = max(size + 6, fitz.get_text_length(text, fontsize=size) + 8)
    r = fitz.Rect(pt.x, pt.y - size - 3, pt.x + width, pt.y + 3)
    # Appearance is generated here; FreeText annots don't get a later
    # update() call, which could reset their colours. (PyMuPDF only allows
    # border_color on rich-text FreeText, so boxed labels get a light fill.)
    return page.add_freetext_annot(r, text, fontsize=size, text_color=color,
                                   fill_color=(1, 1, 0.85) if boxed else None,
                                   border_width=1 if boxed else 0)


def _measure_label(page, pts, text, color):
    """A small label beside a measurement (centre of its points)."""
    cx = sum(p.x for p in pts) / len(pts)
    cy = sum(p.y for p in pts) / len(pts)
    return _label(page, fitz.Point(cx + 4, cy - 4), text, 8, color, True)


# How takeoff markups look. "takeoff" (0.12.29, the default): counts are
# colored dots with the number on them, lengths are thick see-through lines
# and areas are see-through fills, the way PlanSwift-style takeoff sheets
# read. "classic": the 0.12.28 look (numbers in a cream box, thin lines).
LOOK = "takeoff"


def _takeoff_look(p):
    m = p.get("measure")
    return isinstance(m, dict) and m.get("type") not in (CUTOUT, "count") \
        and p.get("look", LOOK) == "takeoff"


COUNT_RING_W = 1.5      # width of a not-yet-checked count's dashed ring


def _count_marker(page, pt, text, color, r=7.0, dashes=None):
    """(number, dot): a see-through dot in the count's color with its
    number in black on top. The count's color is kept on the number as
    PSColor, for legends and lists. `dashes`: an automatic count not yet
    checked gets a dashed ring, so it never looks like a hand count."""
    dot = page.add_circle_annot(fitz.Rect(pt.x - r, pt.y - r, pt.x + r,
                                          pt.y + r))
    dot.set_colors(stroke=color, fill=color)
    if dashes:
        dot.set_border(width=COUNT_RING_W, dashes=list(dashes))
    else:
        dot.set_border(width=0)
    dot.set_opacity(0.6)
    dot.update()
    w = max(2 * r, fitz.get_text_length(text, fontsize=8) + 4)
    a = page.add_freetext_annot(
        fitz.Rect(pt.x - w / 2, pt.y - 5.5, pt.x + w / 2, pt.y + 5.5), text,
        fontsize=8, text_color=(0, 0, 0), align=fitz.TEXT_ALIGN_CENTER,
        border_width=0)
    page.parent.xref_set_key(a.xref, "PSColor", "[" + " ".join(
        f"{c:g}" for c in color) + "]")
    return a, dot


def _ring(dot, dashes):
    """A count dot's ring: dashed while not checked, none once it is."""
    if dashes:
        dot.set_border(width=COUNT_RING_W, dashes=list(dashes))
    else:
        dot.set_border(width=0)
    dot.update()


def _count_dots(page, a):
    """The colored dot(s) under a takeoff-look count's number."""
    doc = page.parent
    if doc.xref_get_key(a.xref, "PSColor")[0] != "array":
        return []
    tag = tag_of(a)
    return [d for d in iter_annots(page) if tag and tag_of(d) == tag and
            d.type[0] == fitz.PDF_ANNOT_CIRCLE and is_label(doc, d)]


def _move_count_dot(page, a, r):
    for d in _count_dots(page, a):
        half = d.rect.width / 2
        c = fitz.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
        d.set_rect(fitz.Rect(c.x - half, c.y - half, c.x + half, c.y + half))
        d.update()


def markup_color(doc, a):
    """The color a markup stands for: a count's own color (PSColor, or its
    text color), else the stroke, else the fill."""
    import re
    t, v = doc.xref_get_key(a.xref, "PSColor")
    if t == "array":
        try:
            c = [float(x) for x in v.strip("[]").split()][:3]
            if len(c) == 3:
                return c
        except ValueError:
            pass
    colors = a.colors or {}
    c = colors.get("stroke") or colors.get("fill")
    if a.type[0] == fitz.PDF_ANNOT_FREE_TEXT:
        t, da = doc.xref_get_key(a.xref, "DA")
        m = re.search(r"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+rg", da or "")
        if m:
            return [float(x) for x in m.groups()]
    return list(c) if c else None


def _dashes(p):
    """The payload's dash pattern: True (cutouts) = 4 on 3 off, or a list."""
    d = p.get("dashes")
    if d is True:
        return [4, 3]
    if isinstance(d, (list, tuple)):
        try:
            # PyMuPDF only takes whole numbers in a dash pattern
            d = [max(1, int(round(float(x)))) for x in d
                 if 0 < float(x) <= 100][:8]
        except (TypeError, ValueError):
            return None
        return d or None
    return None


def _border(a, p, default=1.5):
    d = _dashes(p)
    if d:
        a.set_border(width=_width(p, default), dashes=d)
    else:
        a.set_border(width=_width(p, default))


def _style_shape(a, color, p, kind):
    a.set_colors(stroke=color)
    _border(a, p, 1.5)
    fill = p.get("fill")
    if fill is not None and kind in ("add_rect", "add_ellipse", "add_polygon"):
        a.set_colors(stroke=color, fill=_color(p, kind, "fill"))
        a.set_opacity(0.35)


def _set_takeoff_info(a, p):
    m = p.get("measure")
    if isinstance(m, dict):
        parent = f":{m['parent']}" if m.get("parent") else ""
        a.set_info(subject=f"{TAKEOFF}:{m.get('type', '')}:"
                           f"{m.get('value', '')}:{m.get('unit', '')}:"
                           f"{m.get('group', '')}{parent}",
                   content=str(p["label"]) if p.get("label") else None)
        if isinstance(p.get("roof"), dict):
            _set_roof(a.parent.parent, a, p["roof"])
        if isinstance(p.get("extra"), dict) and p["extra"]:
            from . import measure_extra
            measure_extra.write(a.parent.parent, a, p["extra"])
        if isinstance(p.get("fields"), dict) and p["fields"]:
            set_fields(a.parent.parent, a, p["fields"])
        try:
            _write_audit(a, p, m)
        except Exception:
            log.debug("audit trail not written", exc_info=True)


def _extra_of(doc, a):
    from . import measure_extra
    return measure_extra.read(doc, a)


FIELDS_KEY = "PSFields"


def set_fields(doc, a, fields):
    """Markups List column values a markup was made with (a Tool Chest
    tool's unit cost, product...), kept on the markup itself."""
    import json as _json
    clean = {}
    for k, v in list((fields or {}).items())[:30]:
        k = str(k).strip()[:40]
        if k and isinstance(v, (int, float, str)) and not isinstance(v, bool):
            clean[k] = v[:120] if isinstance(v, str) else v
    doc.xref_set_key(a.xref, FIELDS_KEY, get_pdf_str(_json.dumps(clean))
                     if clean else "null")


def fields_of(doc, a):
    import json as _json
    t, v = doc.xref_get_key(a.xref, FIELDS_KEY)
    if t != "string" or not v:
        return {}
    try:
        d = _json.loads(v)
    except ValueError:
        return {}
    return d if isinstance(d, dict) else {}


AUDIT_KEY = "PSAudit"
# a markup's pre-bid scope (see prebid.py): open / priced / excluded / rfi,
# why, the cost line it's priced in, and who decided and checked it
SCOPE_FIELDS = ("status", "reason", "cost_code", "line_id", "rfi", "by",
                "at", "checked", "was", "revised")


def _write_audit(a, p, m):
    """Who took this off, when, how, and at what scale - kept on the
    measurement itself (see audit.py)."""
    import datetime
    import json
    from . import settings
    page = a.parent
    doc = page.parent
    pts = p.get("pts") or ([p["pt"]] if p.get("pt") else None)
    sc = None
    try:
        sc = scale_at(doc, page.number, pts)
    except Exception:
        logging.getLogger(__name__).debug("ignored error", exc_info=True)
    rec = {"by": p.get("author") or settings.author(),
           "at": datetime.datetime.now().isoformat(timespec="seconds"),
           "method": m.get("method") or "manual"}
    if m.get("confidence") is not None:
        rec["conf"] = round(float(m["confidence"]), 3)
    if sc:
        rec["scale"] = sc.get("name") or f"{sc['ppu']:g} pt/{sc['unit']}"
        rec["ppu"] = sc["ppu"]
    try:
        # the drawing revision in force now, so the audit trail doesn't
        # have to guess it from dates later
        from . import revisions
        revs = revisions.read(doc)["revisions"]
        rec["rev"] = revs[-1]["label"] if revs else "Original"
    except Exception:
        logging.getLogger(__name__).debug("no revision label", exc_info=True)
    doc.xref_set_key(a.xref, AUDIT_KEY, get_pdf_str(json.dumps(rec)))


def get_pdf_str(text):
    return fitz.get_pdf_str(text)


ZONE_KINDS = ("include", "exclude")


def zone_of(doc, annot):
    """"include" / "exclude" for an AI Takeoff zone box, else None."""
    try:
        t, v = doc.xref_get_key(annot.xref, "PSZone")
    except Exception:                                     # noqa: BLE001
        return None
    v = (v or "").strip("()")
    return v if t == "string" and v in ZONE_KINDS else None


def audit_of(doc, annot):
    import json
    t, v = doc.xref_get_key(annot.xref, AUDIT_KEY)
    if t != "string" or not v:
        return {}
    try:
        return json.loads(v)
    except ValueError:
        return {}


# ---- apply -------------------------------------------------------------------

def apply_op(doc, op, fresh=False):
    """Apply one op to `doc`. Returns True if the document changed.
    `fresh`: the op was just made here, so it can't have been applied
    before (skips the already-applied scan, which is slow on pages with
    thousands of markups).
    When it changed, the edit counter moves too, whoever sent the op
    (Venice, Nov 9 - F10: a peer's change didn't refresh the ADA
    checker)."""
    changed = _apply_op(doc, op, fresh)
    if changed:
        try:
            bump_edits(doc)
        except Exception:                                 # noqa: BLE001
            log.warning("edit counter not moved", exc_info=True)  # N5
    return changed


def _apply_op(doc, op, fresh=False):
    """apply_op() without the edit counter."""
    kind = op.get("kind")
    p = op.get("payload") or {}
    pno = op.get("page")
    oid = str(op.get("id", ""))
    if kind not in KINDS:
        log.warning("unknown op kind %r", kind)
        return False
    if not isinstance(pno, int) or not 0 <= pno < doc.page_count:
        log.warning("op %s targets missing page %r", oid, pno)
        return False
    page = doc[pno]
    try:
        if kind == "delete_annot":
            return _delete(page, p)
        if kind == "set_annot":
            return _set_annot(page, p)
        if kind == "set_vertices":
            return _set_vertices(page, p)
        if kind == "set_measure":
            return _set_measure(page, p)
        if kind == "set_captions":
            return _set_captions(page, p)
        if kind == "set_field":
            return _set_field(page, p)
        if kind == "set_scale":
            return _set_scale(doc, pno, p)
        if kind == "set_jobdata":
            return _set_jobdata(doc, p)
        if not fresh and is_applied(page, oid):
            return False
        if kind in CONTENT_KINDS:
            # these change the page itself and leave no tagged annotation,
            # so the page remembers which ops it has had (a replayed or
            # merged op must not redact, insert or retype twice)
            if oid and not fresh and oid in _content_ops(doc, page):
                return False
            done = _add(doc, page, kind, p, oid)
            if done and oid:
                _remember_content_op(doc, page, oid)
            return done
        return _add(doc, page, kind, p, oid)
    except Exception:
        log.exception("failed to apply op %s (%s)", oid, kind)
        return False


_OPS_KEY = "PSOps"


def _content_ops(doc, page):
    t, v = doc.xref_get_key(page.xref, _OPS_KEY)
    if t != "array":
        return set()
    import re
    return set(re.findall(r"\(([0-9A-Za-z_-]+)\)", v))


def _remember_content_op(doc, page, oid):
    import re
    if not re.fullmatch(r"[0-9A-Za-z_-]+", oid):
        return
    t, v = doc.xref_get_key(page.xref, _OPS_KEY)
    ids = re.findall(r"\(([0-9A-Za-z_-]+)\)", v) if t == "array" else []
    ids = (ids + [oid])[-2000:]
    doc.xref_set_key(page.xref, _OPS_KEY,
                     "[" + " ".join(f"({i})" for i in ids) + "]")


def _add(doc, page, kind, p, oid):
    color = _color(p, kind)
    r = pt = pts = None
    if kind in RECT_KINDS:
        r = _rect(p)
        if r is None:
            log.warning("op %s (%s) has no usable rect", oid, kind)
            return False
    elif kind in POINT_KINDS:
        pt = _point(p)
        if pt is None:
            log.warning("op %s (%s) has no usable point", oid, kind)
            return False
    elif kind in POINTS_KINDS:
        pts = _points(p.get("pts"), 2 if kind == "add_line" else
                      (2 if kind == "add_polyline" else 3))
        if pts is None:
            log.warning("op %s (%s) has too few points", oid, kind)
            return False

    # --- changes to the page content (not annotations) ---
    if kind == "add_redact":
        # Remove the text, line art and image pixels underneath, not just
        # cover them (the viewer then proves it: app/redaction.proof)
        from . import redaction
        return redaction.redact(doc, page, r)
    if kind == "replace_span":
        # Edit text: remove what's there, write the new text in its place.
        # Graphics under the text are kept.
        text = str(p.get("text", ""))
        page.add_redact_annot(r, text=text or None, fill=(1, 1, 1),
                              fontsize=_size(p), text_color=color,
                              cross_out=False)
        page.apply_redactions(
            images=getattr(fitz, "PDF_REDACT_IMAGE_NONE", 0),
            graphics=getattr(fitz, "PDF_REDACT_LINE_ART_NONE", 0))
        return True
    if kind == "replace_block":
        return _replace_block(doc, page, r, p, color)
    if kind in ("move_image", "delete_image", "replace_image"):
        return _image_op(doc, page, kind, r, p)
    if kind == "add_image":
        data = base64.b64decode(p.get("data", ""))
        page.insert_image(r, stream=data, keep_proportion=True)
        return True
    if kind == "add_field":
        return _add_field(doc, page, r, p, oid)
    if kind == "add_legend":
        return _add_legend(doc, page, p, oid)
    if kind == "import_annots":
        return _add_imported(doc, page, p, oid)

    # --- annotations ---
    extra = []
    if kind == "add_highlight":
        a = page.add_highlight_annot(_quads(p, r))
        a.set_colors(stroke=color)
    elif kind == "add_underline":
        a = page.add_underline_annot(_quads(p, r))
        a.set_colors(stroke=color)
    elif kind == "add_strike":
        a = page.add_strikeout_annot(_quads(p, r))
        a.set_colors(stroke=color)
    elif kind in ("add_rect", "add_cloud"):
        a = page.add_rect_annot(r)
        _style_shape(a, color, p, kind)
        if kind == "add_cloud":
            a.set_border(width=_width(p, 1.5), clouds=1)
    elif kind == "add_ellipse":
        a = page.add_circle_annot(r)
        _style_shape(a, color, p, kind)
    elif kind == "add_stamp":
        s = p.get("stamp", 0)
        a = page.add_stamp_annot(r, stamp=s if isinstance(s, int) else 0)
    elif kind == "add_textbox":
        a = page.add_freetext_annot(
            r, str(p.get("text", "")), fontsize=_size(p, 12),
            text_color=color, border_width=_width(p, 1.5)
            if p.get("border") else 0)
    elif kind == "add_callout":
        tip = _point(p, "tip") or fitz.Point(r.x0 - 40, r.y1 + 30)
        knee = fitz.Point(r.x0 if tip.x < r.x0 else r.x1,
                          min(max(tip.y, r.y0), r.y1))
        a = page.add_freetext_annot(
            r, str(p.get("text", "")), fontsize=_size(p, 11),
            text_color=color, border_width=1, callout=[tip, knee],
            line_end=fitz.PDF_ANNOT_LE_OPEN_ARROW)
    elif kind == "add_count":
        if p.get("look", LOOK) == "takeoff":
            a, dot = _count_marker(page, pt, str(p.get("n", "")), color,
                                   dashes=_dashes(p))
            extra.append(dot)
        else:
            a = _label(page, pt, str(p.get("n", "")), 9, color, boxed=True)
        _set_takeoff_info(a, p)
    elif kind == "add_text":
        a = _label(page, pt, str(p.get("text", "")), _size(p), color,
                   boxed=False)
    elif kind == "add_note":
        a = page.add_text_annot(pt, str(p.get("text", "")))
        a.set_colors(stroke=color)
    elif kind == "add_line":
        a = page.add_line_annot(pts[0], pts[1])
        a.set_colors(stroke=color)
        _border(a, p, 3.5 if _takeoff_look(p) else 1.5)
        if _takeoff_look(p) and not p.get("arrow"):
            a.set_opacity(0.7)
        if p.get("arrow"):
            a.set_line_ends(getattr(fitz, "PDF_ANNOT_LE_NONE", 0),
                            fitz.PDF_ANNOT_LE_OPEN_ARROW)
    elif kind == "add_polyline":
        a = page.add_polyline_annot(pts)
        a.set_colors(stroke=color)
        _border(a, p, 3.5 if _takeoff_look(p) else 1.5)
        if _takeoff_look(p):
            a.set_opacity(0.7)
    elif kind == "add_polygon":
        a = page.add_polygon_annot(pts)
        _style_shape(a, color, p, kind)
        if _takeoff_look(p):              # a see-through fill, as PlanSwift
            fill = _color(p, kind, "fill") if p.get("fill") is not None \
                else color
            a.set_colors(stroke=color, fill=fill)
            a.set_opacity(0.45)
    elif kind == "add_ink":
        strokes = [s for s in (_points(s, 2) for s in p.get("strokes") or [])
                   if s]
        if not strokes:
            return False
        a = page.add_ink_annot([[(q.x, q.y) for q in s] for s in strokes])
        a.set_colors(stroke=color)
        _border(a, p, 2)

    if kind in POINTS_KINDS:
        _set_takeoff_info(a, p)
        if p.get("label"):
            extra.append(_measure_label(page, pts, str(p["label"]), color))
    elif kind in ("add_ellipse", "add_rect") and \
            isinstance(p.get("measure"), dict):
        _set_takeoff_info(a, p)                    # radius, diameter
        if p.get("label"):
            rr = fitz.Rect(a.rect)
            extra.append(_measure_label(page, [rr.tl, rr.br],
                                        str(p["label"]), color))
    hatch = []
    fams = _hatch_families(p)
    if fams and kind in ("add_rect", "add_cloud", "add_ellipse",
                         "add_polygon"):
        h = _hatch_annot(page, a, kind, fams, color, pts)
        if h is not None:
            hatch.append(h)

    note = p.get("note")
    if isinstance(note, str) and note and kind not in ("add_note",):
        a.set_info(content=note)
    _apply_common(a, p, kind)
    if a.type[0] != fitz.PDF_ANNOT_FREE_TEXT:
        a.update()
    _tag(doc, a, oid)
    doc.xref_set_key(a.xref, "PSKind", fitz.get_pdf_str(
        "arrow" if kind == "add_line" and p.get("arrow") else kind))
    if kind == "add_rect" and p.get("zone") in ZONE_KINDS:
        # an AI Takeoff zone (Nov 1, zones.py): "include" / "exclude"
        doc.xref_set_key(a.xref, "PSZone", fitz.get_pdf_str(p["zone"]))
    for e in extra:                      # labels share the op's tag, so
        _tag(doc, e, oid)                # deleting one deletes both
        doc.xref_set_key(e.xref, "PSLabel", "true")
    if p.get("badge") and isinstance(p.get("measure"), dict):
        _add_badge(doc, page, pts if kind in POINTS_KINDS else None,
                   fitz.Rect(a.rect), oid)
    for h in hatch:
        _tag(doc, h, oid)
        doc.xref_set_key(h.xref, "PSHatch", fitz.get_pdf_str(
            _json.dumps(fams)))
    _set_layer(doc, [a] + extra + hatch, p.get("layer"))
    return True


# ---- hatch, layers ------------------------------------------------------------

def _hatch_families(p):
    from . import styles
    h = p.get("hatch")
    if isinstance(h, str):
        h = styles.hatches().get(h)
    return styles._clean_hatch(h) if h else None


def _shape_outline(a, kind=None, pts=None):
    from . import styles
    t = a.type[0]
    if pts:
        return [(q.x, q.y) for q in pts]
    if t == fitz.PDF_ANNOT_POLYGON:
        return [tuple(v) for v in (a.vertices or [])]
    if t == fitz.PDF_ANNOT_CIRCLE:
        return styles.ellipse_points(tuple(a.rect))
    return styles.rect_points(tuple(a.rect))


def _hatch_annot(page, a, kind, fams, color, pts=None):
    from . import styles
    outline = _shape_outline(a, kind, pts)
    segs = styles.hatch_segments(outline, fams)
    if not segs:
        return None
    h = page.add_ink_annot([[p0, p1] for p0, p1 in segs])
    h.set_colors(stroke=color)
    h.set_border(width=0.5)
    h.set_info(subject="Hatch")
    h.update()
    return h


def is_hatch(doc, annot):
    return doc.xref_get_key(annot.xref, "PSHatch")[0] == "string"


def rehatch(doc, page, shape, fams=None):
    """Redraw the hatch of `shape` (after it moved or its hatch changed).
    `fams` None = keep its current pattern; [] = remove the hatch."""
    tag = tag_of(shape)
    old = [x for x in iter_annots(page) if tag and tag_of(x) == tag
           and is_hatch(doc, x)]
    if fams is None:
        if not old:
            return False
        t, v = doc.xref_get_key(old[0].xref, "PSHatch")
        try:
            fams = [tuple(f) for f in _json.loads(v)]
        except ValueError:
            return False
    color = (shape.colors or {}).get("stroke") or (0, 0, 0)
    layer = shape.get_oc() if hasattr(shape, "get_oc") else 0
    for x in old:
        page.delete_annot(x)
    if not fams:
        return bool(old)
    h = _hatch_annot(page, shape, None, fams, color)
    if h is None:
        return bool(old)
    _tag(doc, h, tag)
    doc.xref_set_key(h.xref, "PSHatch", fitz.get_pdf_str(_json.dumps(
        [list(f) for f in fams])))
    if layer:
        h.set_oc(layer)
    return True


def ocg_xref(doc, name, create=True):
    """The layer (optional content group) called `name`."""
    for xref, info in (doc.get_ocgs() or {}).items():
        if info.get("name") == name:
            return xref
    return doc.add_ocg(name, on=True) if create else 0


def _set_layer(doc, annots, name):
    if not isinstance(name, str) or not name.strip():
        return
    x = ocg_xref(doc, name.strip()[:60])
    for a in annots:
        a.set_oc(x)


SUBJECTS = {
    "add_highlight": "Highlight", "add_underline": "Underline",
    "add_strike": "Strikeout", "add_rect": "Rectangle",
    "add_ellipse": "Ellipse", "add_cloud": "Cloud", "add_stamp": "Stamp",
    "add_textbox": "Text Box", "add_text": "Text", "add_note": "Note",
    "add_callout": "Callout",
    "add_line": "Line", "add_polyline": "Polyline", "add_polygon": "Polygon",
    "add_ink": "Pen",
}
STATUSES = ["", "Accepted", "Rejected", "Completed", "Cancelled", "Pending"]


def statuses():
    """Built-in statuses plus the ones you've added."""
    from . import styles
    out = list(styles.statuses(STATUSES))
    if REVISED not in out:
        out.append(REVISED)        # set by Compare Revisions > Slip Sheet
    return out


REVISED = "Check - drawing revised"


def _apply_common(a, p, kind):
    """Author, subject and opacity, shared by every markup type."""
    now = fitz.get_pdf_now()
    a.set_info(creationDate=now, modDate=now)
    author = p.get("author")
    if isinstance(author, str) and author:
        a.set_info(title=author[:100])
    if not isinstance(p.get("measure"), dict):
        subject = p.get("subject") or SUBJECTS.get(kind)
        if subject:
            a.set_info(subject=str(subject)[:100])
    op = p.get("opacity")
    if isinstance(op, (int, float)) and 0.05 <= op < 1:
        a.set_opacity(float(op))


def is_label(doc, annot):
    """True for the text label that belongs to a measurement (its "AI"
    badge too: part of the measurement, never a markup of its own)."""
    return doc.xref_get_key(annot.xref, "PSLabel")[0] == "bool" or \
        is_badge(doc, annot)


# ---- AI vs a person's markups (AI Takeoff v3, Oct 31 2026) ---------------
# An AI markup not yet accepted carries a small "AI" badge (its own text
# annotation, tagged with the measurement, PSBadge true) beside its dashed
# outline / ring. Accepting it (Check Takeoff / the review queue) takes the
# badge off and makes it solid; deleting it deletes the badge with it.
BADGE_TEXT = "AI"
BADGE_RGB = (0.5, 0.0, 0.7)          # violet: no takeoff item uses it
BADGE_FILL = (0.94, 0.9, 1.0)
BADGE_SIZE = 6

EXPORT_RULE = (
    "Drawing exports (Save, Save As, a flattened PDF, printing, XFDF) show "
    "the drawing as it is on screen: an AI markup not yet accepted keeps "
    "its dashed outline or ring and its AI badge; an accepted one is solid "
    "with no badge. Quantity exports (takeoff CSV) total only accepted AI "
    "measurements and a person's own; each detail line says where it came "
    "from (AI, accepted / manual), and AI items still in review are listed "
    "apart as pending - not in any total.")


def is_badge(doc, annot):
    """True for the "AI" badge of an AI markup not yet accepted."""
    return doc.xref_get_key(annot.xref, "PSBadge")[0] == "bool"


def _is_ai_method(method):
    return str(method or "").startswith(("AI takeoff", "auto"))


def origin(doc, annot):
    """'ai-pending' (made by AI, not accepted yet), 'ai-accepted',
    'ai-edited' (made by AI, then reshaped by a person - Nov 1) or
    'manual' (a person's own measurement)."""
    rec = audit_of(doc, annot)
    m = str(rec.get("method") or "")
    if not _is_ai_method(m):
        return "manual"
    if rec.get("edited"):
        return "ai-edited"
    if status_of(doc, annot) == "Accepted" or "(reviewed)" in m:
        return "ai-accepted"
    return "ai-pending"


ORIGIN_TEXT = {"ai-pending": "AI, not checked", "ai-accepted": "AI, accepted",
               "ai-edited": "AI, edited", "manual": "manual"}


def _badge_at(page, pts, rect=None):
    """Where a badge goes: just above the top-left of the measurement."""
    if pts:
        x = min(p.x for p in pts)
        y = min(p.y for p in pts)
    elif rect is not None:
        x, y = rect.x0, rect.y0
    else:
        return None
    w = fitz.get_text_length(BADGE_TEXT, fontsize=BADGE_SIZE) + 5
    h = BADGE_SIZE + 4
    r = fitz.Rect(x - 2, y - h - 1, x - 2 + w, y - 1)
    pr = page.rect * page.derotation_matrix if page.rotation else page.rect
    if r.y0 < pr.y0:
        r += (0, pr.y0 - r.y0, 0, pr.y0 - r.y0)
    if r.x0 < pr.x0:
        r += (pr.x0 - r.x0, 0, pr.x0 - r.x0, 0)
    return r


def _add_badge(doc, page, pts, rect, oid):
    r = _badge_at(page, pts, rect)
    if r is None:
        return None
    b = page.add_freetext_annot(r, BADGE_TEXT, fontsize=BADGE_SIZE,
                                text_color=BADGE_RGB, fill_color=BADGE_FILL,
                                border_width=0.6, align=1)
    _tag(doc, b, oid)
    doc.xref_set_key(b.xref, "PSBadge", "true")
    return b


def _drop_badges(page, tags):
    doc = page.parent
    n = 0
    for a in [x for x in iter_annots(page) if is_badge(doc, x) and
              tag_of(x) in tags]:
        page.delete_annot(a)
        n += 1
    return n


def status_of(doc, annot):
    t, v = doc.xref_get_key(annot.xref, "PSStatus")
    return v if t == "string" else ""


# An AI measurement the AI was not sure of carries this on its method
# ('AI takeoff: rooms (review)'). Until a person accepts it (Check Takeoff
# sets status Accepted) it is not in any total: it is shown as a separate
# pending-review subtotal (Jon, Oct 31).
REVIEW_SUFFIX = " (review)"


def is_pending(doc, annot):
    """True for an AI measurement flagged for review and not accepted."""
    m = str(audit_of(doc, annot).get("method") or "")
    return m.endswith(REVIEW_SUFFIX) and status_of(doc, annot) != "Accepted"


def _quads(p, r):
    """Text-markup area: the exact text-line rects if given, else the box."""
    rects = []
    for q in p.get("rects") or []:
        try:
            rr = fitz.Rect(q)
        except (TypeError, ValueError):
            continue
        if not rr.is_empty:
            rects.append(rr)
    return rects or r


def _delete(page, p):
    victims = find_annots(page, p)
    for a in victims:
        page.delete_annot(a)
    return bool(victims)


MOVABLE = {fitz.PDF_ANNOT_SQUARE, fitz.PDF_ANNOT_CIRCLE,
           fitz.PDF_ANNOT_FREE_TEXT, fitz.PDF_ANNOT_STAMP, fitz.PDF_ANNOT_TEXT}


def _set_annot(page, p):
    """Change an existing annotation: color, comment, text, position,
    line style, hatch, layer."""
    changed = False
    relabel = []
    badge_tags = set()
    for a in find_annots(page, p):
        if is_hatch(page.parent, a):
            continue                       # redrawn with its shape
        if is_badge(page.parent, a):
            badge_tags.add(tag_of(a))
            continue                       # taken off / put on below
        if ("badge" in p or p.get("status") == "Accepted") and (
                a.info or {}).get("subject", "").startswith(TAKEOFF + ":"):
            badge_tags.add(tag_of(a))      # accepted: the AI badge goes
        rehatch_later = []
        atype = a.type[0]
        if "note" in p:
            a.set_info(content=str(p["note"]))
            changed = True
        if "text" in p and atype == fitz.PDF_ANNOT_FREE_TEXT:
            a.set_info(content=str(p["text"]))
            changed = True
        if "rect" in p and atype in MOVABLE and _rect(p) is not None:
            a.set_rect(_rect(p))
            changed = True
            if atype == fitz.PDF_ANNOT_FREE_TEXT:
                _move_count_dot(page, a, _rect(p))
            if atype in (fitz.PDF_ANNOT_SQUARE, fitz.PDF_ANNOT_CIRCLE):
                rehatch_later.append(None)
        if "multiplier" in p and (a.info or {}).get("subject", "") \
                .startswith(TAKEOFF + ":"):
            try:
                if _set_multiplier(page, a, p["multiplier"]):
                    changed = True
                    relabel.append((tag_of(a), float(p["multiplier"]),
                                    (a.colors or {}).get("stroke")
                                    or (1, 0, 0)))
            except (TypeError, ValueError):
                pass
        if "roof" in p and (a.info or {}).get("subject", "") \
                .startswith(TAKEOFF + ":"):
            _set_roof(page.parent, a, p["roof"])
            changed = True
        if "dashes" in p and atype == fitz.PDF_ANNOT_FREE_TEXT and \
                (a.info or {}).get("subject", "").startswith(TAKEOFF +
                                                             ":count:"):
            for dot in _count_dots(page, a):   # found by the number's xref
                _ring(dot, _dashes(p))
            changed = True
        if "dashes" in p and atype == fitz.PDF_ANNOT_CIRCLE and \
                is_label(page.parent, a):
            _ring(a, _dashes(p))               # a count's dot: ring or none
            changed = True
        elif "dashes" in p and atype in BORDERED:
            w = (a.border or {}).get("width", 1.5)
            d = _dashes(p)
            if d:
                a.set_border(width=w if w and w > 0 else 1.5, dashes=d)
            else:                          # back to a solid line
                page.parent.xref_set_key(
                    a.xref, "BS", f"<</W {w if w and w > 0 else 1.5:g}/S/S>>")
            changed = True
        if "hatch" in p and atype in FILLABLE:
            fams = _hatch_families(p) or []
            rehatch_later.append(fams)
            changed = True
        if "layer" in p and isinstance(p["layer"], str):
            name = p["layer"].strip()
            x = ocg_xref(page.parent, name[:60]) if name else 0
            tag = tag_of(a)
            group = [x2 for x2 in iter_annots(page) if tag and tag_of(x2) == tag] \
                if tag else [a]
            for g in group:
                g.set_oc(x)
            changed = True
        if "status" in p:
            st = str(p["status"])[:40]
            page.parent.xref_set_key(a.xref, "PSStatus",
                                         fitz.get_pdf_str(st))
            changed = True
        if isinstance(p.get("scope"), dict):     # pre-bid scope decision
            import json as _json
            sc = {k: str(v)[:200] if isinstance(v, str) else v
                  for k, v in p["scope"].items()
                  if k in SCOPE_FIELDS}
            page.parent.xref_set_key(a.xref, "PSScope",
                                     fitz.get_pdf_str(_json.dumps(sc)))
            changed = True
        subj = (a.info or {}).get("subject", "")
        if "group" in p and subj.startswith(TAKEOFF + ":"):
            parts = (subj.split(":", 5) + [""] * 6)[:6]
            parts[4] = str(p["group"])[:60]
            a.set_info(subject=":".join(parts[:5]))
            changed = True
        elif "subject" in p and not subj.startswith(TAKEOFF + ":") \
                and p["subject"]:
            a.set_info(subject=str(p["subject"])[:100])
            changed = True
        if "width" in p and atype in BORDERED:
            a.set_border(width=_width(p))
            changed = True
        if "fill" in p and atype in FILLABLE:
            a.set_colors(fill=[] if p["fill"] is None else _color(p, "", "fill"))
            changed = True
        if "opacity" in p:
            op = p["opacity"]
            if isinstance(op, (int, float)) and 0.05 <= op <= 1:
                a.set_opacity(float(op))
                changed = True
        if "color" in p:
            c = _color(p, "")
            if atype == fitz.PDF_ANNOT_FREE_TEXT:
                if _count_dots(page, a):  # a takeoff-look count: the dot
                    page.parent.xref_set_key(a.xref, "PSColor", "[" + " ".join(
                        f"{x:g}" for x in c) + "]")
                    for d in _count_dots(page, a):
                        d.set_colors(stroke=c, fill=c)
                        d.update()
                else:
                    a.update(text_color=c)
                a.set_info(modDate=fitz.get_pdf_now())
                changed = True
                continue
            a.set_colors(stroke=c)
            changed = True
        if changed:
            a.set_info(modDate=fitz.get_pdf_now())
        a.update()
        for fams in rehatch_later:
            rehatch(page.parent, page, a, fams)
        if "color" in p and atype in FILLABLE and not rehatch_later:
            rehatch(page.parent, page, a)        # hatch follows the color
    for tag, m, color in relabel:
        if tag:
            _relabel_multiplier(page, tag, m, color)
    if ("badge" in p or p.get("status") == "Accepted") and \
            badge_tags - {""}:
        changed = _set_badge(page, badge_tags - {""},
                             bool(p.get("badge", False))) or changed
    return changed


RESHAPE_TYPES = (fitz.PDF_ANNOT_POLYGON, fitz.PDF_ANNOT_POLY_LINE,
                 fitz.PDF_ANNOT_LINE)


def reshapable(doc, annot):
    """A polygon, polyline or line a person can reshape by its corners."""
    return annot.type[0] in RESHAPE_TYPES and not is_label(doc, annot) \
        and not is_hatch(doc, annot) and not is_badge(doc, annot) \
        and not is_legend(doc, annot)


def _reshaped_value(mtype, old_value, old_pts, pts, ppu, extra=None,
                    base=None):
    """A measurement's value after its points moved: length (plus any
    rise/drop), wall area (length x height less openings), area, cutout
    or volume (the depth kept: old value / old area). `base` is the
    sheet's unit, for a measurement kept in another unit (extra "to")."""
    from . import measure_extra, takeoff
    if mtype == "length" or (mtype == "area" and
                             measure_extra.is_wall(extra)):
        t, v = measure_extra.run_value(takeoff.path_length(pts) / ppu, extra)
        return measure_extra.to_units(t, v, base, extra)[0] if base else v
    area = takeoff.polygon_area(pts) / ppu ** 2
    if mtype in ("area", CUTOUT):
        return measure_extra.to_units("area", area, base, extra)[0] \
            if base else area
    if mtype == "volume":
        old_area = takeoff.polygon_area(old_pts) / ppu ** 2
        return area * (old_value / old_area) if old_area > 0 else None
    return None


def _set_vertices(page, p):
    """Reshape a polygon, polyline or line (Nov 1): new points `pts` (page,
    unrotated). Everything else about the markup stays - style, layer,
    status, scope, audit trail, multiplier, roof, its tag (so its label,
    hatch, badge and cutouts stay with it). A measurement's value follows
    at the page's scale and its label is rewritten; an AI measurement is
    marked edited by a person (origin "ai-edited")."""
    import datetime
    import json
    from . import settings, takeoff
    doc = page.parent
    pts = _points(p.get("pts"), 2)
    if not pts:
        return False
    done = False
    for a in [x for x in find_annots(page, p) if reshapable(doc, x)]:
        t = a.type[0]
        if (t == fitz.PDF_ANNOT_POLYGON and len(pts) < 3) or \
                (t == fitz.PDF_ANNOT_LINE and len(pts) != 2):
            continue
        old_pts = [fitz.Point(v) for v in (a.vertices or [])]
        tag = tag_of(a)
        info = dict(a.info or {})
        colors = dict(a.colors or {})
        border = dict(a.border or {})
        opacity = a.opacity
        ends = a.line_ends if t != fitz.PDF_ANNOT_POLYGON else None
        oc = a.get_oc() if hasattr(a, "get_oc") else 0
        keys = {}
        for k in doc.xref_get_keys(a.xref):
            if k.startswith("PS"):
                keys[k] = doc.xref_get_key(a.xref, k)
        badged = any(is_badge(doc, x) and tag_of(x) == tag
                     for x in iter_annots(page)) if tag else False
        page.delete_annot(a)
        if t == fitz.PDF_ANNOT_POLYGON:
            new = page.add_polygon_annot(pts)
        elif t == fitz.PDF_ANNOT_POLY_LINE:
            new = page.add_polyline_annot(pts)
        else:
            new = page.add_line_annot(pts[0], pts[1])
        new.set_colors(stroke=colors.get("stroke"),
                       fill=colors.get("fill")
                       if t == fitz.PDF_ANNOT_POLYGON else None)
        w = border.get("width", 1.5)
        if border.get("dashes"):
            new.set_border(width=w if w and w > 0 else 1.5,
                           dashes=border["dashes"])
        else:
            new.set_border(width=w if w and w > 0 else 1.5)
        if ends and any(ends):
            new.set_line_ends(*ends)
        if opacity is not None and 0 <= opacity < 1:
            new.set_opacity(opacity)
        new.set_info(info)
        new.update()
        if tag:
            _tag(doc, new, tag)                     # same op id (NM)
        if oc:
            new.set_oc(oc)
        for k, (kt, v) in keys.items():
            doc.xref_set_key(new.xref, k, fitz.get_pdf_str(v)
                             if kt == "string" else v)
        subj = info.get("subject", "")
        if subj.startswith(TAKEOFF + ":"):
            parts = (subj.split(":", 5) + [""] * 6)[:6]
            mtype, unit = parts[1], parts[3]
            try:
                old_value = float(parts[2])
            except ValueError:
                old_value = 0.0
            ppu = p.get("ppu")
            sc = scale_at(doc, page.number, [(q.x, q.y) for q in pts])
            if not ppu:
                ppu = sc["ppu"] if sc else None
            from . import measure_extra
            extra = measure_extra.read(doc, new)
            value = _reshaped_value(mtype, old_value, old_pts, pts, ppu,
                                    extra, sc["unit"] if sc and
                                    extra.get("to") else None) \
                if ppu else None
            if value is not None:
                parts[2] = f"{round(value, 4)}"
                sub = ":".join(parts[:5]) + (f":{parts[5]}" if parts[5]
                                             else "")
                new.set_info(subject=sub)
                _relabel_shape(page, new, mtype, value, unit, parts[4])
            # the audit trail says a person changed it (an AI one is then
            # "AI, edited"); method and confidence stay as they were
            rec = audit_of(doc, new)
            rec["edited"] = {"by": p.get("author") or settings.author(),
                             "at": datetime.datetime.now().isoformat(
                                 timespec="seconds")}
            doc.xref_set_key(new.xref, AUDIT_KEY,
                             get_pdf_str(json.dumps(rec)))
        new.update()
        try:
            rehatch(doc, page, new)                 # the hatch follows
        except Exception:
            log.debug("hatch not redrawn", exc_info=True)
        if badged:
            _drop_badges(page, {tag})
            _add_badge(doc, page, pts, None, tag)
        done = True
    return done


def _set_measure(page, p):
    """Change how a measurement is worked out, in place (Nov 2): "rise"
    (vertical length added to a run), "height" and "openings" (a run as a
    wall area; height 0 turns it back into a length), "show" (the cubic
    unit a volume is shown in). The value and label are worked out again
    from the markup's own points at its scale."""
    from . import measure_extra, takeoff
    doc = page.parent
    keys = [k for k in ("rise", "height", "openings", "show") if k in p]
    if not keys:
        return False
    done = False
    for a in find_annots(page, p):
        subj = (a.info or {}).get("subject", "")
        if not subj.startswith(TAKEOFF + ":") or is_label(doc, a) or \
                is_hatch(doc, a) or is_badge(doc, a) or is_legend(doc, a):
            continue
        parts = (subj.split(":", 5) + [""] * 6)[:6]
        mtype, unit, group = parts[1], parts[3], parts[4]
        try:
            value = float(parts[2])
        except ValueError:
            continue
        extra = measure_extra.read(doc, a)
        for k in keys:
            extra[k] = p[k]
        extra = measure_extra.clean(extra)
        pts = [fitz.Point(v) for v in (a.vertices or [])]
        run = a.type[0] in (fitz.PDF_ANNOT_POLY_LINE, fitz.PDF_ANNOT_LINE)
        if run and mtype in ("length", "area"):
            sc = scale_at(doc, page.number, [(q.x, q.y) for q in pts])
            if not sc or len(pts) < 2:
                continue
            extra.pop("show", None)
            base = sc["unit"]
            plan = takeoff.path_length(pts) / sc["ppu"]
            mtype, value = measure_extra.run_value(plan, extra)
            value, unit = measure_extra.to_units(mtype, value, base, extra)
        elif mtype == "volume" and extra.get("show"):
            got = measure_extra.volume_in(value, unit, extra["show"])
            if got is None:
                continue
            value, unit = got, extra["show"]
            extra = {"show": extra["show"]}
        else:
            continue
        measure_extra.write(doc, a, extra)
        parts[1], parts[2], parts[3] = mtype, f"{round(value, 4)}", unit
        a.set_info(subject=":".join(parts[:5]) +
                   (f":{parts[5]}" if parts[5] else ""),
                   content=measure_extra.label_text(
                       mtype, value, unit, group, extra, takeoff.fmt))
        a.update()
        _relabel_shape(page, a, mtype, value, unit, group)
        done = True
    return done


def _set_captions(page, p):
    """Rewrite the captions of the measurements on the page as
    "Name: quantity", the quantity only or the name only (p["mode"]:
    both / value / name). The full caption is kept on the label (PSFull),
    so going back to "both" restores it as it was."""
    from . import measure_extra
    mode = p.get("mode")
    if mode not in measure_extra.CAPTIONS:
        return False
    doc = page.parent
    annots = list(iter_annots(page))
    groups = {}
    for a in annots:
        subj = (a.info or {}).get("subject", "")
        if subj.startswith(TAKEOFF + ":") and tag_of(a) and \
                not is_label(doc, a):
            parts = (subj.split(":", 5) + [""] * 6)
            if parts[1] not in ("count", CUTOUT):
                try:
                    from . import takeoff
                    qty = measure_extra.label_text(
                        parts[1], float(parts[2]), parts[3], "",
                        measure_extra.read(doc, a), takeoff.fmt)
                except ValueError:
                    qty = None
                groups[tag_of(a)] = (parts[4], (a.colors or {}).get(
                    "stroke") or (1, 0, 0), qty)
    changed = 0
    for lab in annots:
        t = tag_of(lab)
        if t not in groups or lab.type[0] != fitz.PDF_ANNOT_FREE_TEXT or \
                doc.xref_get_key(lab.xref, "PSLabel")[1] != "true":
            continue
        group, color, qty = groups[t]
        have = (lab.info or {}).get("content", "")
        kt, kv = doc.xref_get_key(lab.xref, "PSFull")
        full = kv if kt == "string" and kv else have
        want = measure_extra.recaption(full, group, mode, qty)
        if want == have:
            continue
        r = fitz.Rect(lab.rect)
        page.delete_annot(lab)
        new = _label(page, fitz.Point(r.x0, r.y1 - 3), want, 8, color, True)
        _tag(doc, new, t)
        doc.xref_set_key(new.xref, "PSLabel", "true")
        if mode != "both":
            doc.xref_set_key(new.xref, "PSFull", get_pdf_str(full))
        changed += 1
    return changed > 0


def _relabel_shape(page, shape, mtype, value, unit, group):
    """A reshaped measurement's label says its new value (an area's net
    label is rewritten again by refresh_area_labels)."""
    from . import takeoff
    doc = page.parent
    tag = tag_of(shape)
    if not tag:
        return
    from . import measure_extra
    extra = measure_extra.read(doc, shape)
    if mtype == CUTOUT:
        text = f"Cutout -{_c2(value):,.2f} {unit}"
    else:
        text = measure_extra.label_text(mtype, value, unit, group, extra,
                                        takeoff.fmt)
    if (shape.info or {}).get("content", "") != text:
        shape.set_info(content=text)      # the Markups List comment too
        shape.update()
    m = multiplier_of(doc, shape)
    color = (shape.colors or {}).get("stroke") or (1, 0, 0)
    for lab in [x for x in iter_annots(page) if tag_of(x) == tag
                and x.type[0] == fitz.PDF_ANNOT_FREE_TEXT
                and doc.xref_get_key(x.xref, "PSLabel")[1] == "true"]:
        r = fitz.Rect(lab.rect)
        page.delete_annot(lab)
        new = _label(page, fitz.Point(r.x0, r.y1 - 3), text, 8, color, True)
        _tag(doc, new, tag)
        doc.xref_set_key(new.xref, "PSLabel", "true")
    if m and m != 1:
        _relabel_multiplier(page, tag, m, color)


def _set_badge(page, tags, on):
    """Take the AI badge off the measurements tagged `tags` (accepted), or
    put it back (on=True: back to an AI proposal)."""
    if not on:
        return _drop_badges(page, tags) > 0
    doc = page.parent
    have = {tag_of(a) for a in iter_annots(page) if is_badge(doc, a)}
    n = 0
    for a in list(iter_annots(page)):
        t = tag_of(a)
        if t in tags and t not in have and (a.info or {}).get(
                "subject", "").startswith(TAKEOFF + ":"):
            pts = [fitz.Point(v) for v in (a.vertices or [])] \
                if a.type[0] in BORDERED else None
            if _add_badge(doc, page, pts, fitz.Rect(a.rect), t) is not None:
                have.add(t)
                n += 1
    return n > 0


def kind_of(doc, annot):
    """The QuantiSheet tool that made an annotation ("add_cloud", "arrow"…),
    or "" for annotations from other programs."""
    t, v = doc.xref_get_key(annot.xref, "PSKind")
    return v if t == "string" else ""


def friendly_type(a, subj="", doc=None):
    """What Bluebeam-style lists call the markup."""
    t = a.type[1]
    if subj.startswith(TAKEOFF + ":"):
        return {"length": "Length", "area": "Area", "count": "Count",
                CUTOUT: "Cutout", "volume": "Volume", "angle": "Angle",
                "radius": "Radius", "diameter": "Diameter"}.get(
            subj.split(":")[1], "Measurement")
    kind = kind_of(doc, a) if doc is not None else ""
    if kind == "add_cloud" or (t == "Square" and (a.border or {}).get(
            "clouds", -1) > 0):
        return "Cloud"
    if kind == "arrow" or (t == "Line" and (a.line_ends or (0, 0))[1]):
        return "Arrow"
    if kind == "add_stamp":
        return "Stamp"
    if kind == "add_legend":
        return "Legend"
    return {"Square": "Rectangle", "Circle": "Ellipse", "Text": "Note",
            "FreeText": "Text Box", "Ink": "Pen", "StrikeOut": "Strikeout",
            "PolyLine": "Polyline"}.get(t, t)


BORDERED = {fitz.PDF_ANNOT_SQUARE, fitz.PDF_ANNOT_CIRCLE, fitz.PDF_ANNOT_LINE,
            fitz.PDF_ANNOT_POLY_LINE, fitz.PDF_ANNOT_POLYGON,
            fitz.PDF_ANNOT_INK}
FILLABLE = {fitz.PDF_ANNOT_SQUARE, fitz.PDF_ANNOT_CIRCLE,
            fitz.PDF_ANNOT_POLYGON}


# ---- forms -------------------------------------------------------------------

FIELD_TYPES = {
    "text": "PDF_WIDGET_TYPE_TEXT", "checkbox": "PDF_WIDGET_TYPE_CHECKBOX",
    "combo": "PDF_WIDGET_TYPE_COMBOBOX", "list": "PDF_WIDGET_TYPE_LISTBOX",
}


def _add_field(doc, page, r, p, oid):
    ftype = getattr(fitz, FIELD_TYPES.get(p.get("ftype"), ""), None)
    name = str(p.get("name") or "").strip()
    if ftype is None or not name:
        return False
    if any(w.field_name == name for pg in doc for w in pg.widgets()):
        log.warning("a field named %r already exists", name)
        return False
    w = fitz.Widget()
    w.rect = r
    w.field_type = ftype
    w.field_name = name
    w.text_fontsize = 0
    w.border_color = (0, 0, 0)
    w.border_width = 1
    w.fill_color = (0.93, 0.95, 1)
    choices = [str(c) for c in p.get("choices") or [] if str(c)]
    if ftype in (fitz.PDF_WIDGET_TYPE_COMBOBOX, fitz.PDF_WIDGET_TYPE_LISTBOX):
        w.choice_values = choices or ["Option 1"]
        w.field_value = w.choice_values[0]
    elif ftype == fitz.PDF_WIDGET_TYPE_TEXT:
        w.field_value = str(p.get("value", ""))
    a = page.add_widget(w)
    if a is not None:
        _tag(doc, a, oid)
    return True


def _set_field(page, p):
    """Fill in a form field by name (searched on this page)."""
    name = p.get("name")
    for w in page.widgets():
        if w.field_name != name:
            continue
        v = p.get("value")
        if w.field_type in (fitz.PDF_WIDGET_TYPE_CHECKBOX,
                            fitz.PDF_WIDGET_TYPE_RADIOBUTTON):
            w.field_value = w.on_state() if v else "Off"
        else:
            w.field_value = "" if v is None else str(v)
            if w.field_value == "":
                # PyMuPDF skips empty values, so clear /V ourselves
                page.parent.xref_set_key(w.xref, "V", "()")
        w.update()
        return True
    return False


# ---- takeoff scale (stored inside the PDF) -----------------------------------------

SCALE_RESET_NOTICE = ("The saved scales in this PDF were damaged and "
                      "have been reset.")
_scale_notices = {}          # id(doc) -> notice waiting to be shown


def _read_all_scales(doc):
    """(scales, damaged): damaged is True when the PDF has a scale
    attachment that can't be read (e.g. 'object is not a stream') - the
    scales are then treated as empty."""
    import json
    try:
        if SCALE_FILE not in doc.embfile_names():
            return {}, False
    except Exception:
        log.warning("could not list embedded files", exc_info=True)
        return {}, False
    try:
        data = json.loads(doc.embfile_get(SCALE_FILE).decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("scale data is not an object")
        return ({int(k): v for k, v in data.items() if isinstance(v, dict)},
                False)
    except Exception:
        log.warning("could not read takeoff scales", exc_info=True)
        return {}, True


def _all_scales(doc):
    return _read_all_scales(doc)[0]


def take_scale_notice(doc):
    """The one-time note for the user after Set Scale replaced a damaged
    scale attachment, or None. Cleared once read."""
    return _scale_notices.pop(id(doc), None)


def _rewrite_damaged(doc, data):
    """Drop the unreadable scale attachment and write a fresh one."""
    try:
        embfiles.delete(doc, SCALE_FILE)
    except Exception:
        # no raw embfile_del here: with several attachments it can swap
        # their data (embfiles.py); the safe writer below overwrites it
        log.warning("could not remove the damaged scale file", exc_info=True)
    if SCALE_FILE in doc.embfile_names():
        # still listed: overwrite through the safe writer as a last try
        embfiles.put(doc, SCALE_FILE, data, "QuantiSheet takeoff scales")
    else:
        doc.embfile_add(SCALE_FILE, data, filename=SCALE_FILE,
                        desc="QuantiSheet takeoff scales")


def read_scales(doc):
    """{page_index: {"ppu": points per unit, "unit": "ft"}} - the scale of
    each page as a whole. Viewports (regions with their own scale) are in
    read_viewports()."""
    return {k: v for k, v in _all_scales(doc).items()
            if v.get("ppu", 0) > 0}


def read_viewports(doc, pno=None):
    """{page: [{"name", "rect" (op coords), "ppu", "unit"}]}, or one page's
    list when `pno` is given."""
    out = {}
    for k, v in _all_scales(doc).items():
        vps = [vp for vp in v.get("viewports") or []
               if isinstance(vp, dict) and vp.get("ppu", 0) > 0
               and isinstance(vp.get("rect"), list)]
        if vps:
            out[k] = vps
    return out.get(pno, []) if pno is not None else out


def scale_at(doc, pno, pts=None, scales=None, viewports=None):
    """The scale that applies to points `pts` (op coordinates) on page
    `pno`: the viewport they fall in, else the page's scale, else None."""
    if pts:
        vps = viewports.get(pno, []) if viewports is not None \
            else read_viewports(doc, pno)
        if vps:
            cx = sum(q[0] for q in pts) / len(pts)
            cy = sum(q[1] for q in pts) / len(pts)
            for vp in reversed(vps):            # the last drawn wins
                if fitz.Rect(vp["rect"]).contains(fitz.Point(cx, cy)):
                    return {"ppu": vp["ppu"], "unit": vp.get("unit", "ft"),
                            "name": vp.get("name", ""), "viewport": True}
    scales = read_scales(doc) if scales is None else scales
    return scales.get(pno)


def _set_jobdata(doc, p):
    """Write one listed job data file (JSON text). False when it is not on
    the list, too big, not JSON, or already the same."""
    import json
    name = str(p.get("file") or "")
    if name not in JOBDATA_FILES:
        log.warning("job data %r is not one an op may write", name)
        return False
    desc, most = JOBDATA_FILES[name]
    data = p.get("data")
    if not isinstance(data, str) or len(data.encode("utf-8")) > most:
        return False
    try:
        parsed = json.loads(data)
    except ValueError:
        return False
    if not isinstance(parsed, dict):       # never "5", [] or null (Venice F)
        return False
    raw = data.encode("utf-8")
    try:
        if name in embfiles.names(doc) and \
                bytes(embfiles.get(doc, name)) == raw:
            return False
    except Exception:                                     # noqa: BLE001
        pass
    embfiles.put(doc, name, raw, desc)
    return True


def _set_scale(doc, pno, p):
    import json
    scales, damaged = _read_all_scales(doc)
    if "viewport" in p or "delete_viewport" in p:
        entry = scales.setdefault(pno, {})
        vps = [v for v in entry.get("viewports") or [] if isinstance(v, dict)]
        if "delete_viewport" in p:
            name = str(p["delete_viewport"])
            keep = [v for v in vps if v.get("name") != name]
            if len(keep) == len(vps):
                return False
            vps = keep
        else:
            vp = p["viewport"]
            try:
                r = fitz.Rect(vp["rect"]).normalize()
                ppu = float(vp["ppu"])
            except (KeyError, TypeError, ValueError):
                return False
            if ppu <= 0 or r.is_empty:
                return False
            name = str(vp.get("name") or f"Viewport {len(vps) + 1}")[:40]
            vps = [v for v in vps if v.get("name") != name]
            vps.append({"name": name, "rect": [_c2(x) for x in r],
                        "ppu": ppu, "unit": str(vp.get("unit", "ft"))[:12],
                        "label": str(vp.get("label", ""))[:40]})
        entry["viewports"] = vps
    else:
        try:
            ppu = float(p.get("ppu"))
        except (TypeError, ValueError):
            return False
        if ppu <= 0:
            return False
        pages = p.get("pages")
        targets = [int(i) for i in pages] if isinstance(pages, list) \
            else [pno]
        for i in targets:
            if 0 <= i < doc.page_count:
                keep = scales.get(i, {}).get("viewports")
                scales[i] = {"ppu": ppu,
                             "unit": str(p.get("unit", "ft"))[:12]}
                if p.get("name"):
                    scales[i]["name"] = str(p["name"])[:40]
                geo = p.get("geo")              # an aerial page's location
                if isinstance(geo, dict) and i == pno:
                    try:
                        scales[i]["geo"] = {k: float(geo[k]) for k in
                                            ("lat", "lon", "cx", "cy")}
                    except (KeyError, TypeError, ValueError):
                        pass
                if keep:
                    scales[i]["viewports"] = keep
    data = json.dumps({str(k): v for k, v in scales.items()}).encode()
    if damaged:
        _rewrite_damaged(doc, data)
        _scale_notices[id(doc)] = SCALE_RESET_NOTICE
    else:
        embfiles.put(doc, SCALE_FILE, data, "QuantiSheet takeoff scales")
    # the standard PDF copy, so other programs measure in real units too
    from . import pdfmeasure
    if "viewport" in p or "delete_viewport" in p:
        touched = [pno]
    else:
        touched = [i for i in targets if 0 <= i < doc.page_count]
    for i in touched:
        pdfmeasure.sync_page(doc, i, scales.get(i))
    return True


# ---- misc ------------------------------------------------------------------------

def has_similar(page, kind, rect, tol=1.0):
    """True if the page already has an annotation of this kind at this rect.

    Used to stop auto-markup from stacking duplicates when run twice.
    """
    types = {"add_highlight": fitz.PDF_ANNOT_HIGHLIGHT,
             "add_underline": fitz.PDF_ANNOT_UNDERLINE,
             "add_strike": fitz.PDF_ANNOT_STRIKE_OUT,
             "add_rect": fitz.PDF_ANNOT_SQUARE,
             "add_cloud": fitz.PDF_ANNOT_SQUARE,
             "add_ellipse": fitz.PDF_ANNOT_CIRCLE}
    t = types.get(kind)
    if t is None:
        return False
    r = fitz.Rect(rect)
    for a in page.annots(types=[t]):
        if all(abs(x - y) <= tol + 3 for x, y in zip(a.rect, r)):
            return True
    return False


def text_rects(page, rect):
    """Line-by-line rects of the words inside `rect` (screen coordinates),
    so highlights hug the text instead of covering the whole drag box.
    Returns screen rects. (Text extraction itself gives unrotated
    coordinates, so words are turned to screen ones before comparing.)"""
    rect = fitz.Rect(rect)
    lines = {}
    for x0, y0, x1, y1, _w, block, line, _n in page.get_text("words"):
        wr = from_page(page, fitz.Rect(x0, y0, x1, y1))
        if wr.intersects(rect) and (wr & rect).get_area() >= 0.3 * wr.get_area():
            key = (block, line)
            lines[key] = lines[key] | wr if key in lines else wr
    return list(lines.values())


CUTOUT = "cutout"

# While panels refresh together they each asked for the same full-document
# scans; inside scan_cache() each scan runs once and is shared.
_CACHE = None


class scan_cache:
    def __enter__(self):
        global _CACHE
        self._outer = _CACHE
        if _CACHE is None:
            _CACHE = {}
        return self

    def __exit__(self, *exc):
        global _CACHE
        if self._outer is None:
            _CACHE = None
        return False


def _cached(key, fn):
    if _CACHE is None:
        return fn()
    if key not in _CACHE:
        _CACHE[key] = fn()
    return [dict(x) for x in _CACHE[key]]


def maybe_takeoff(doc, a):
    """False when annotation `a` is surely not a measurement: its /Subj
    is read straight from the PDF, much faster than a.info (Nov 3: a set
    with 31,580 markups spent seconds per scan building .info for every
    one). Anything not plain - a missing or odd /Subj - says True and is
    checked the usual way."""
    try:
        t, v = doc.xref_get_key(a.xref, "Subj")
    except Exception:
        return True
    if t == "null":
        return False
    if t != "string":
        return True
    return v.startswith(TAKEOFF) or not v.isascii() or \
        v.startswith(("<", "\\", "\ufeff", "\xfe"))   # (encoded text)


def takeoff_items(doc, include_cutouts=False):
    return _cached(("takeoff", id(doc), bool(include_cutouts)),
                   lambda: _takeoff_items(doc, include_cutouts))


def totals_items(doc, include_cutouts=False):
    """takeoff_items() less the AI measurements flagged for review and not
    accepted yet: what quantities, estimates, exports and links total.
    (Jon, Oct 31: an item in review is not in any total until a person
    accepts it; the Takeoff panel shows it as a pending subtotal.)"""
    return [it for it in takeoff_items(doc, include_cutouts)
            if not it.get("pending")]


def _takeoff_items(doc, include_cutouts=False):
    """All measurements in the document, for the quantities panel.

    Cutouts (openings drawn inside an area) are taken off the area they
    belong to: its "value" is the net area, "gross" the area as drawn,
    "cutouts" how many, and "hole_perimeter" the openings' edge length
    (for forms, trim and the like). Cutouts themselves are left out unless
    include_cutouts is set."""
    scales = vports = None
    out, cutouts, roofs = [], [], {}
    verts = {}                       # id(item) -> outline (for cutouts)
    for pno, page in enumerate(doc):
        for a in iter_annots(page):
            if not maybe_takeoff(doc, a):
                continue                 # (most markups: no .info needed)
            subj = (a.info or {}).get("subject", "")
            if not subj.startswith(TAKEOFF + ":"):
                continue
            parts = subj.split(":", 5)
            parts += [""] * (6 - len(parts))
            _, mtype, value, unit, group, parent = parts[:6]
            try:
                value = float(value)
            except ValueError:
                continue
            item = {"page": pno, "type": mtype, "value": value,
                    "unit": unit, "group": group,
                    "label": (a.info or {}).get("content", ""),
                    "ref": ref(a), "rect": list(a.rect), "tag": tag_of(a),
                    "multiplier": multiplier_of(doc, a),
                    "pending": is_pending(doc, a),
                    "origin": origin(doc, a)}
            from . import measure_extra
            ex = measure_extra.read(doc, a)
            if ex:
                item["extra"] = ex
            r = roof_of(doc, a)
            if r is not None and mtype != CUTOUT:
                roofs[id(item)] = r
            if mtype == CUTOUT:
                if scales is None:
                    scales, vports = read_scales(doc), read_viewports(doc)
                item["parent"] = parent
                verts[id(item)] = [tuple(v) for v in (a.vertices or [])]
                item["perimeter"] = _perimeter(a, scale_at(
                    doc, pno, [tuple(v) for v in (a.vertices or [])],
                    scales, vports))
                cutouts.append(item)
                if include_cutouts:
                    out.append(item)
                continue
            if mtype == "area":
                item.update(gross=value, cutouts=0, hole_perimeter=0.0)
                verts[id(item)] = [tuple(v) for v in (a.vertices or [])]
            elif mtype == "length":
                # corners and segments of a run (Nov 4 takeoff list #11):
                # elbows, bends, posts
                n = len(a.vertices or [])
                item.update(segments=max(0, n - 1), corners=max(0, n - 2))
            out.append(item)
    by_tag = {(it["page"], it["tag"]): it for it in out
              if it["type"] == "area" and it["tag"]}
    kids = {}
    for c in cutouts:
        parent = by_tag.get((c["page"], c["parent"]))
        if parent is None:
            continue                        # its area was deleted
        parent["cutouts"] += 1
        parent["hole_perimeter"] += c["perimeter"]
        kids.setdefault(id(parent), (parent, []))[1].append(c)
    for parent, cs in kids.values():
        # cutouts that overlap each other, or reach outside the area, are
        # taken off once and only inside it (review QS-015, Nov 4)
        took = sum(c["value"] for c in cs)
        got = _net_cutout(verts.get(id(parent)),
                          [verts.get(id(c)) for c in cs],
                          parent["gross"])
        # the grid is used only when it shows a real overlap (more than
        # 1 %); otherwise the exact cutout sizes stand
        if got is not None and got < took * 0.99:
            took = got
        parent["value"] = max(0.0, parent["value"] - took)
    # typical sheets: everything on a page counted N times (a typical
    # floor plan used for floors 2-6: x5) - Nov 4 takeoff list #3
    pmult = {}
    for it in out:
        pno = it["page"]
        if pno not in pmult:
            pmult[pno] = page_multiplier(doc, pno)
        if pmult[pno] != 1:
            it["page_multiplier"] = pmult[pno]
            it["multiplier"] = (it.get("multiplier") or 1) * pmult[pno]
    # typical areas: one takeoff standing for N identical units
    for it in out:
        m = it.get("multiplier") or 1
        if m != 1 and it["type"] != CUTOUT:
            it["unit_value"] = it["value"]
            it["value"] *= m
            if it["type"] == "area":
                it["gross"] *= m
                it["hole_perimeter"] *= m
    if roofs:                       # true (sloped) quantities, roof.py
        from . import roof
        out = [roof.apply(it, roofs[id(it)]) if id(it) in roofs else it
               for it in out]
    return out


def _poly_area(pts):
    n = len(pts)
    return abs(sum(pts[i][0] * pts[(i + 1) % n][1] -
                   pts[(i + 1) % n][0] * pts[i][1] for i in range(n))) / 2


def _net_cutout(parent_pts, cut_pts, parent_value, cells=900):
    """How much of the area the cutouts really take away, in the area's
    units: the union of the cutouts, inside the area - worked out on a
    fine grid (about 0.1 % of the area). None when it can't be (no
    outline, or no OpenCV): then the cutouts are simply added up."""
    if not parent_pts or len(parent_pts) < 3 or not cut_pts or \
            any(not c or len(c) < 3 for c in cut_pts):
        return None
    try:
        import cv2
        import numpy as np
    except Exception:                                     # noqa: BLE001
        return None
    xs = [p[0] for p in parent_pts]
    ys = [p[1] for p in parent_pts]
    x0, y0 = min(xs), min(ys)
    span = max(max(xs) - x0, max(ys) - y0)
    if span <= 0:
        return None
    k = cells / span
    w = int((max(xs) - x0) * k) + 3
    h = int((max(ys) - y0) * k) + 3

    def px(pts):
        return np.array([[(x - x0) * k + 1, (y - y0) * k + 1]
                         for x, y in pts], dtype=np.float64)
    shift = 4                                  # sub-pixel accuracy
    m = 1 << shift
    area = np.zeros((h, w), np.uint8)
    cv2.fillPoly(area, [np.round(px(parent_pts) * m).astype(np.int32)], 1,
                 lineType=cv2.LINE_8, shift=shift)
    holes = np.zeros((h, w), np.uint8)
    for c in cut_pts:
        cv2.fillPoly(holes, [np.round(px(c) * m).astype(np.int32)], 1,
                     lineType=cv2.LINE_8, shift=shift)
    inside = float(np.count_nonzero(area))
    if not inside:
        return None
    frac = float(np.count_nonzero(area & holes)) / inside
    return parent_value * frac


MULT_KEY = "PSMult"
PAGE_MULT_KEY = "PSPageMult"         # on the page itself: moves with it


def page_multiplier(doc, pno):
    """How many times this sheet counts (a typical floor); 1 unless set."""
    try:
        t, v = doc.xref_get_key(doc[pno].xref, PAGE_MULT_KEY)
    except Exception:                                     # noqa: BLE001
        return 1
    if t in ("int", "real"):
        try:
            m = float(v)
            return int(m) if m == int(m) and m >= 1 else (m if m > 0 else 1)
        except ValueError:
            pass
    return 1


def set_page_multiplier(doc, pno, m):
    """Set (m > 1) or clear (m == 1) the sheet's multiplier."""
    x = doc[pno].xref
    if not m or float(m) == 1:
        doc.xref_set_key(x, PAGE_MULT_KEY, "null")
    else:
        doc.xref_set_key(x, PAGE_MULT_KEY, f"{float(m):g}")
    return page_multiplier(doc, pno)


def multiplier_of(doc, annot):
    """How many identical units this measurement stands for (a typical
    hotel room x 200). 1 unless set."""
    t, v = doc.xref_get_key(annot.xref, MULT_KEY)
    if t in ("real", "int"):
        try:
            m = float(v)
            return m if m > 0 else 1.0
        except ValueError:
            pass
    return 1.0


def _set_multiplier(page, a, m):
    """Set the typical count on measurement `a` (its label is redrawn by
    _relabel_multiplier once the caller is done with its annotations)."""
    doc = page.parent
    m = float(m)
    if m <= 0:
        return False
    if m == 1:
        doc.xref_set_key(a.xref, MULT_KEY, "null")
    else:
        doc.xref_set_key(a.xref, MULT_KEY, f"{m:g}")
    return True


# roof plan takeoff (roof.py): what a measurement is on the roof and its
# pitch, kept on the markup so the true (sloped) quantity can be redone
ROOF_KEYS = {"type": "PSRoof", "pitch": "PSPitch", "run": "PSRun",
             "sheet": "PSSheet", "parapet_in": "PSParapetIn",
             "curb": "PSCurb", "membrane": "PSMembrane"}


def roof_of(doc, annot):
    """The roof data on a measurement, or None when it has none."""
    t, v = doc.xref_get_key(annot.xref, "PSRoof")
    if t != "string" or not v:
        return None
    out = {}
    for field, key in ROOF_KEYS.items():
        t, v = doc.xref_get_key(annot.xref, key)
        if t == "string" and v != "":
            out[field] = v
        elif t in ("real", "int"):
            out[field] = v
    if "parapet_in" in out:
        try:
            out["parapet_in"] = float(out["parapet_in"])
        except ValueError:
            out.pop("parapet_in")
    return out


def _set_roof(doc, a, data):
    """Write (or with an empty value, clear) the roof keys on `a`."""
    if not isinstance(data, dict) or not data.get("type"):
        for key in ROOF_KEYS.values():
            doc.xref_set_key(a.xref, key, "null")
        return True
    for field, key in ROOF_KEYS.items():
        v = data.get(field)
        if v is None or v == "":
            doc.xref_set_key(a.xref, key, "null")
        else:
            doc.xref_set_key(a.xref, key, fitz.get_pdf_str(str(v)[:40]))
    return True


def _relabel_multiplier(page, tag, m, color):
    import re
    doc = page.parent
    for lab in [x for x in iter_annots(page) if tag_of(x) == tag
                and x.type[0] == fitz.PDF_ANNOT_FREE_TEXT
                and doc.xref_get_key(x.xref, "PSLabel")[1] == "true"]:
        have = (lab.info or {}).get("content", "")
        base = re.sub(r"\s+x\s*[\d.,]+ typical(?: = [\d.,]+)?$", "",
                      have)
        want = base if m == 1 else f"{base}  x {m:g} typical"
        if want == have:
            continue
        r = fitz.Rect(lab.rect)
        page.delete_annot(lab)
        new = _label(page, fitz.Point(r.x0, r.y1 - 3), want, 8, color, True)
        _tag(doc, new, tag)
        doc.xref_set_key(new.xref, "PSLabel", "true")


def _perimeter(annot, scale):
    """Closed outline length of a polygon annotation, in drawing units."""
    try:
        v = [fitz.Point(p) for p in (annot.vertices or [])]
        if len(v) < 3 or not scale or not scale.get("ppu"):
            return 0.0
        return sum(abs(b - a) for a, b in zip(v, v[1:] + v[:1])) \
            / scale["ppu"]
    except Exception:
        return 0.0


def area_label_text(item):
    """What an area's label on the drawing says, net of cutouts (and,
    for a typical area, per unit times the count)."""
    m = item.get("multiplier") or 1
    per = item.get("unit_value", item["value"])
    if item.get("extra", {}).get("height"):
        from . import measure_extra, takeoff
        text = measure_extra.label_text("area", per, item["unit"], "",
                                        item["extra"], takeoff.fmt)
        if m != 1:
            text += f" x {m:g} typical = {_c2(item['value']):,.2f}"
        return measure_extra.join(item.get("group"), text)
    text = f"{_c2(per):,.2f} {item['unit']}"
    if item.get("cutouts"):
        n = item["cutouts"]
        text += f" net ({n} cutout{'s' if n > 1 else ''})"
    if m != 1:
        text += f" x {m:g} typical = {_c2(item['value']):,.2f}"
    from . import measure_extra
    return measure_extra.join(item.get("group"), text)


def refresh_area_labels(doc, pno):
    """Rewrite the labels of areas on page `pno` so they show the net area
    after cutouts are added or removed. Returns how many changed."""
    page = doc[pno]
    if page.rotation:
        return 0
    items = [it for it in takeoff_items(doc)
             if it["page"] == pno and it["type"] == "area" and it["tag"]]
    changed = 0
    annots = list(iter_annots(page))
    for it in items:
        want = area_label_text(it)
        labels = [a for a in annots if tag_of(a) == it["tag"]
                  and a.type[0] == fitz.PDF_ANNOT_FREE_TEXT
                  and doc.xref_get_key(a.xref, "PSLabel")[1] == "true"]
        shape = [a for a in annots if tag_of(a) == it["tag"]
                 and a.type[0] in (fitz.PDF_ANNOT_POLYGON,
                                   fitz.PDF_ANNOT_POLY_LINE,
                                   fitz.PDF_ANNOT_LINE)]
        for lab in labels:
            have = (lab.info or {}).get("content", "")
            if have == want:
                continue
            r = fitz.Rect(lab.rect)
            color = (shape[0].colors.get("stroke") if shape else None) \
                or (1, 0, 0)
            page.delete_annot(lab)
            new = _label(page, fitz.Point(r.x0, r.y1 - 3), want, 8,
                         color, True)
            _tag(doc, new, it["tag"])
            doc.xref_set_key(new.xref, "PSLabel", "true")
            changed += 1
    return changed


def pdf_date(s):
    """'D:20261013125500-04'00'' -> '2026-10-13 12:55'"""
    s = (s or "").replace("D:", "")
    if len(s) >= 12 and s[:12].isdigit():
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]} {s[8:10]}:{s[10:12]}"
    return s


def _hex(c):
    if not c:
        return ""
    c = list(c)[:3]
    if len(c) == 1:
        c = c * 3
    return "#" + "".join(f"{int(round(x * 255)):02x}" for x in c)


def markup_items(doc, pages=None):
    """Every markup in the document, for the Markups List (only those on
    `pages`, a list of page numbers, when given)."""
    if pages is not None:
        return _cached(("markups", id(doc), tuple(pages)),
                       lambda: _markup_items(doc, pages))
    return _cached(("markups", id(doc)), lambda: _markup_items(doc))


def annot_count(doc):
    """How many annotations the document has (fast: no annotation is
    loaded)."""
    n = 0
    for page in doc:
        try:
            n += len(page.annot_xrefs())
        except Exception:
            pass
    return n


def _markup_items(doc, pages=None):
    out = []
    nets = {(it["page"], it["tag"]): it for it in takeoff_items(doc)
            if it["type"] == "area" and it.get("cutouts")}
    for pno in (range(doc.page_count) if pages is None else pages):
        if not 0 <= pno < doc.page_count:
            continue
        page = doc[pno]
        for a in iter_annots(page):
            if is_label(doc, a) or is_hatch(doc, a):
                continue
            info = a.info or {}
            subj = info.get("subject", "")
            measure = ""
            mtype, mvalue = "", None
            if subj.startswith(TAKEOFF + ":"):
                parts = (subj.split(":", 5) + [""] * 6)
                mtype, value, unit, group = parts[1:5]
                subj = group or mtype.title()
                try:
                    mvalue = float(value)
                    measure = (f"{_c2(float(value)):,.2f} {unit}"
                               if mtype != "count" else "1 ea")
                    if mtype == CUTOUT:
                        measure = "-" + measure
                        mvalue = -mvalue
                    net = nets.get((pno, tag_of(a)))
                    if net:
                        measure = f"{_c2(net['value']):,.2f} {unit} net"
                        mvalue = net["value"]
                except ValueError:
                    measure = ""
            colors = a.colors or {}
            out.append({
                "page": pno,
                "type": friendly_type(a, info.get("subject", ""), doc),
                "subject": subj,
                "comment": info.get("content", ""),
                "author": info.get("title", ""),
                "date": pdf_date(info.get("modDate") or
                                 info.get("creationDate")),
                "status": status_of(doc, a), "measure": measure,
                "origin": ORIGIN_TEXT.get(origin(doc, a), "manual")
                if mtype else "",
                "mtype": mtype, "mvalue": mvalue,
                "fields": fields_of(doc, a) if mtype else {},
                "extra": _extra_of(doc, a) if mtype else {},
                "color": _hex(markup_color(doc, a)),
                "ref": ref(a), "rect": list(a.rect)})
    return out


# ---- legends ---------------------------------------------------------------------

LEGEND_ROW = 14


def _fit_cols(rows, label_fs, qty_fs, qty_font, room):
    """Widths for the label and quantity columns, and the font scale that
    keeps every label on one line within `room` points."""
    lw = max([fitz.get_text_length(r[0], fontsize=label_fs) for r in rows]
             or [0])
    qw = max([fitz.get_text_length(r[1], fontname=qty_font,
                                   fontsize=qty_fs) for r in rows] or [0])
    scale = 1.0
    if lw + qw > room > 0:
        scale = max(6.0 / label_fs, room / (lw + qw))
    return lw * scale, qw * scale, scale


def _legend_icon(page, kind, box):
    """The takeoff legend's small type glyph (fixed colors)."""
    x0, y0, x1, y1 = box
    out = []
    if kind == "length":
        pts = [fitz.Point(x0, y1 - 1), fitz.Point(x0 + 3.5, y0 + 2),
               fitz.Point(x1 - 3, y1 - 2), fitz.Point(x1, y0 + 1)]
        ln = page.add_polyline_annot(pts)
        ln.set_colors(stroke=(0, 0, 1))
        ln.set_border(width=0.8)
        ln.update()
        out.append(ln)
        for q in pts:
            h = page.add_rect_annot(fitz.Rect(q.x - 0.9, q.y - 0.9,
                                              q.x + 0.9, q.y + 0.9))
            h.set_colors(stroke=(0, 0, 1), fill=(1, 1, 1))
            h.set_border(width=0.4)
            h.update()
            out.append(h)
    elif kind == "area":
        pts = [fitz.Point(x0, y0 + 3), fitz.Point(x0 + 5, y0),
               fitz.Point(x1, y0 + 4), fitz.Point(x1 - 2, y1),
               fitz.Point(x0 + 1, y1)]
        pg = page.add_polygon_annot(pts)
        pg.set_colors(stroke=(0.2, 0.6, 0.2), fill=(0.6, 0.9, 0.6))
        pg.set_border(width=0.5)
        pg.update()
        out.append(pg)
    elif kind == "count":
        for dx, dy in ((1.5, 6.5), (4.5, 2.5), (7.5, 6.5)):
            c = fitz.Point(x0 + dx, y0 + dy)
            d = page.add_circle_annot(fitz.Rect(c.x - 1.4, c.y - 1.4,
                                                c.x + 1.4, c.y + 1.4))
            d.set_colors(stroke=(1, 0, 0), fill=(1, 0, 0))
            d.set_border(width=0)
            d.update()
            out.append(d)
    return out


def _add_legend(doc, page, p, oid):
    """A markup legend: a framed table of swatch, description and quantity,
    one row per kind of markup. All its parts share the op's tag.
    style "classic" (the default when the op has none): title row, swatch,
    label (type), count | quantity. style "takeoff": no title, type icon,
    name, bold blue quantity, see-through color swatch."""
    from . import legend
    r = _rect(p)
    rows = [x for x in p.get("rows") or [] if isinstance(x, dict)][:60]
    if r is None:
        return False
    style = p.get("style") if p.get("style") in legend.STYLES else "classic"
    title = str(p.get("title") or "Legend")[:60]
    take = style == "takeoff"
    texts = [(legend.format_label(x, style)[:80],
              legend.format_qty(x, style)[:40]) for x in rows]
    pr = page.rect
    if take:
        row_h, lfs, qfs, qfont = 10.4, 9.0, 7.0, "helv"
        lead, tail, top = 4 + 9 + 4, 4 + 8 + 4, 3
    else:
        row_h, lfs, qfs, qfont = LEGEND_ROW, 8.0, 8.0, "helv"
        lead, tail, top = 26, 4, 22
    room = max(0.0, pr.width - 18 - lead - tail - 8)
    lw, qw, scale = _fit_cols(texts, lfs, qfs, qfont, room)
    lfs, qfs = lfs * scale, qfs * scale
    want = lead + lw + 10 + qw + tail + 4
    if take:
        r.x1 = r.x0 + max(want, 120)
        need = top * 2 + row_h * max(1, len(rows))
        r.y1 = r.y0 + need
    else:
        r.x1 = max(r.x1, r.x0 + 180, r.x0 + want)
        need = 24 + row_h * max(1, len(rows)) + 6
        if r.height < need:
            r.y1 = r.y0 + need
    if r.x1 > pr.x1 - 9:                 # keep it on the sheet
        w = r.width
        r.x1 = pr.x1 - 9
        r.x0 = max(pr.x0 + 9, r.x1 - w)
    frame = page.add_rect_annot(r)
    frame.set_colors(stroke=(0, 0, 0), fill=(1, 1, 1))
    frame.set_border(width=0.5 if take else 1)
    if take:
        frame.set_opacity(0.9)
    frame.set_info(subject="Legend", content=title)
    now = fitz.get_pdf_now()
    frame.set_info(creationDate=now, modDate=now)
    if isinstance(p.get("author"), str):
        frame.set_info(title=p["author"][:100])
    frame.update()
    parts = []
    if not take:
        parts.append(page.add_freetext_annot(
            fitz.Rect(r.x0 + 4, r.y0 + 3, r.x1 - 4, r.y0 + 19), title,
            fontsize=10, text_color=(0, 0, 0)))
    qty_w = qw + 6
    qw_c = max(qty_w, min(110, (r.width - 40) / 2))
    if r.width - 30 - qw_c < lw + 2:
        qw_c = max(qty_w, r.width - 32 - lw)
    for i, (row, (label, qty)) in enumerate(zip(rows, texts)):
        y = r.y0 + top + i * row_h
        c = _color(row, "add_rect")
        if take:
            kind = row.get("type") if row.get("type") in (
                "length", "area", "count") else "other"
            ib = (r.x0 + 4, y + (row_h - 9) / 2, r.x0 + 13,
                  y + (row_h + 9) / 2)
            icon = _legend_icon(page, kind, ib)
            if not icon:
                sq = page.add_rect_annot(fitz.Rect(*ib))
                sq.set_colors(stroke=c, fill=c)
                sq.set_border(width=0.5)
                sq.update()
                icon = [sq]
            parts.extend(icon)
            sx = r.x1 - 4 - 8
            sr = fitz.Rect(sx, y + (row_h - 8) / 2, sx + 8,
                           y + (row_h + 8) / 2)
            if kind == "count":
                sw = page.add_circle_annot(sr)
                sw.set_colors(stroke=c, fill=c)
                sw.set_border(width=0)
            else:
                sw = page.add_rect_annot(sr)
                sw.set_colors(stroke=(0, 0, 0), fill=c)
                sw.set_border(width=0.5)
            sw.set_opacity(0.6)
            sw.update()
            parts.append(sw)
            qx1 = sx - 3
            parts.append(page.add_freetext_annot(
                fitz.Rect(r.x0 + lead, y - 1.5, qx1 - qty_w - 2,
                          y + row_h + 1.5),
                label, fontsize=lfs, text_color=(0, 0, 0)))
            parts.append(page.add_freetext_annot(
                fitz.Rect(qx1 - qty_w, y - 1.5, qx1, y + row_h + 1.5), qty,
                fontsize=qfs, text_color=(0, 0, 1),
                align=fitz.TEXT_ALIGN_RIGHT))
            continue
        sw = page.add_rect_annot(fitz.Rect(r.x0 + 6, y + 2, r.x0 + 22,
                                           y + LEGEND_ROW - 2))
        sw.set_colors(stroke=c, fill=c)
        sw.set_border(width=0.5)
        if row.get("hatch"):
            sw.set_opacity(0.6)
        sw.update()
        parts.append(sw)
        parts.append(page.add_freetext_annot(
            fitz.Rect(r.x0 + 26, y, r.x1 - qw_c - 4, y + LEGEND_ROW),
            label, fontsize=lfs, text_color=(0, 0, 0)))
        parts.append(page.add_freetext_annot(
            fitz.Rect(r.x1 - qw_c, y, r.x1 - 4, y + LEGEND_ROW),
            qty, fontsize=qfs, text_color=(0, 0, 0),
            align=fitz.TEXT_ALIGN_RIGHT))
    _tag(doc, frame, oid)
    doc.xref_set_key(frame.xref, "PSKind", fitz.get_pdf_str("add_legend"))
    if style != "classic" or p.get("style"):
        doc.xref_set_key(frame.xref, "PSLegendStyle", fitz.get_pdf_str(style))
    opts = legend.clean_opts(p.get("opts"))
    if opts:
        doc.xref_set_key(frame.xref, legend.OPTS_KEY,
                         fitz.get_pdf_str(_json.dumps(opts)))
    for x in parts:
        _tag(doc, x, oid)
        doc.xref_set_key(x.xref, "PSLabel", "true")
    _set_layer(doc, [frame] + parts, p.get("layer"))
    return True


def is_legend(doc, annot):
    return kind_of(doc, annot) == "add_legend"


# ---- importing markups from another PDF ------------------------------------------

_IMPORT_KEYS = ("PSKind", "PSLabel", "PSBadge", "PSStatus", "PSHatch",
                "PSAudit", "PSScope", "PSColor", "PSLegendStyle", "PSMult",
                "PSRoof", "PSPitch", "PSRun", "PSSheet", "PSParapetIn",
                "PSCurb",
                "PSMembrane", "PSMeasureX", "PSLegendOpts", "PSFields")


def inner_rect(doc, a):
    """The shape's own rectangle: /Rect less the /RD margin PyMuPDF adds
    around squares and circles for the border."""
    import re
    r = fitz.Rect(a.rect)
    t, v = doc.xref_get_key(a.xref, "RD")
    if t == "array":
        n = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", v)]
        if len(n) == 4:
            # /RD is left, top, right, bottom
            r = fitz.Rect(r.x0 + n[0], r.y0 + n[1], r.x1 - n[2], r.y1 - n[3])
    return r


def serialize_annot(doc, a):
    """Everything needed to redraw annotation `a` in another document."""
    info = a.info or {}
    border = a.border or {}
    d = {"type": a.type[0], "rect": list(inner_rect(doc, a)
                                          if a.type[0] in (
                                              fitz.PDF_ANNOT_SQUARE,
                                              fitz.PDF_ANNOT_CIRCLE)
                                          else a.rect),
         "colors": {k: list(v) for k, v in (a.colors or {}).items() if v},
         "width": border.get("width", 1), "dashes": border.get("dashes") or [],
         "clouds": border.get("clouds", -1),
         "opacity": a.opacity if a.opacity is not None else -1,
         "info": {k: info.get(k, "") for k in ("title", "subject",
                                               "content")},
         "line_ends": list(a.line_ends or (0, 0)), "keys": {}}
    v = a.vertices
    if v:
        d["vertices"] = [list(x) if not isinstance(x[0], (list, tuple))
                         else [list(y) for y in x] for x in v]
    for k in _IMPORT_KEYS:
        t, val = doc.xref_get_key(a.xref, k)
        if t != "null":
            d["keys"][k] = [t, val]
    if a.type[0] == fitz.PDF_ANNOT_FREE_TEXT:
        da = doc.xref_get_key(a.xref, "DA")[1] or ""
        size = 10
        for tok_i, tok in enumerate(da.split()):
            if tok == "Tf" and tok_i > 0:
                try:
                    size = float(da.split()[tok_i - 1])
                except ValueError:
                    pass
        d["fontsize"] = size
    return d


def _add_imported(doc, page, p, oid):
    made = []
    for d in p.get("annots") or []:
        try:
            a = _draw_imported(page, d)
        except Exception:
            log.warning("could not import a markup", exc_info=True)
            continue
        if a is None:
            continue
        for k, (t, val) in (d.get("keys") or {}).items():
            if k in _IMPORT_KEYS:
                doc.xref_set_key(a.xref, k, val if t != "string"
                                 else fitz.get_pdf_str(val))
        _tag(doc, a, oid)
        made.append(a)
    _set_layer(doc, made, p.get("layer"))
    return bool(made)


def _draw_imported(page, d):
    t = d.get("type")
    r = fitz.Rect(d["rect"])
    v = d.get("vertices") or []
    c = d.get("colors") or {}
    info = d.get("info") or {}
    stroke = tuple(c.get("stroke") or (1, 0, 0))
    if t == fitz.PDF_ANNOT_SQUARE:
        a = page.add_rect_annot(r)
    elif t == fitz.PDF_ANNOT_CIRCLE:
        a = page.add_circle_annot(r)
    elif t == fitz.PDF_ANNOT_LINE and len(v) >= 2:
        a = page.add_line_annot(fitz.Point(v[0]), fitz.Point(v[1]))
    elif t == fitz.PDF_ANNOT_POLY_LINE and len(v) >= 2:
        a = page.add_polyline_annot([fitz.Point(x) for x in v])
    elif t == fitz.PDF_ANNOT_POLYGON and len(v) >= 3:
        a = page.add_polygon_annot([fitz.Point(x) for x in v])
    elif t == fitz.PDF_ANNOT_INK and v:
        a = page.add_ink_annot([[tuple(q) for q in s] for s in v])
    elif t in (fitz.PDF_ANNOT_HIGHLIGHT, fitz.PDF_ANNOT_UNDERLINE,
               fitz.PDF_ANNOT_STRIKE_OUT):
        quads = [fitz.Quad(*[fitz.Point(q) for q in v[i:i + 4]])
                 for i in range(0, len(v) - 3, 4)] or r
        fn = {fitz.PDF_ANNOT_HIGHLIGHT: page.add_highlight_annot,
              fitz.PDF_ANNOT_UNDERLINE: page.add_underline_annot,
              fitz.PDF_ANNOT_STRIKE_OUT: page.add_strikeout_annot}[t]
        a = fn(quads)
    elif t == fitz.PDF_ANNOT_FREE_TEXT:
        fill = c.get("fill")
        a = page.add_freetext_annot(
            r, info.get("content", ""), fontsize=d.get("fontsize", 10),
            text_color=stroke if c.get("stroke") else (0, 0, 0),
            fill_color=tuple(fill) if fill else None,
            border_width=1 if fill else 0)
        a.set_info(title=info.get("title", ""),
                   subject=info.get("subject", ""))
        return a
    elif t == fitz.PDF_ANNOT_TEXT:
        a = page.add_text_annot(r.tl, info.get("content", ""))
    elif t == fitz.PDF_ANNOT_STAMP:
        a = page.add_stamp_annot(r)
    else:
        return None
    if t not in (fitz.PDF_ANNOT_STAMP,):
        a.set_colors(stroke=stroke, fill=tuple(c["fill"])
                     if c.get("fill") and t in (
                         fitz.PDF_ANNOT_SQUARE, fitz.PDF_ANNOT_CIRCLE,
                         fitz.PDF_ANNOT_POLYGON) else None)
    if t in BORDERED:
        w = d.get("width") or 1
        dashes = [max(1, int(round(x))) for x in d.get("dashes") or []
                  if x > 0]
        if dashes:
            a.set_border(width=w if w > 0 else 1, dashes=dashes)
        else:
            a.set_border(width=w if w > 0 else 1)
        if d.get("clouds", -1) > 0:
            a.set_border(clouds=d["clouds"])
    if t == fitz.PDF_ANNOT_LINE and any(d.get("line_ends") or ()):
        a.set_line_ends(*d["line_ends"][:2])
    op = d.get("opacity", -1)
    if isinstance(op, (int, float)) and 0.05 <= op < 1:
        a.set_opacity(op)
    a.set_info(title=info.get("title", ""), subject=info.get("subject", ""),
               content=info.get("content", ""))
    a.update()
    return a


def import_ops(doc, src, layer=None):
    """Marks that copy every markup of `src` onto the same page numbers of
    `doc` (as many pages as both have). Markups that belonged together in
    `src` (a measurement and its label) stay together."""
    marks = []
    for pno in range(min(doc.page_count, src.page_count)):
        groups = {}
        for a in iter_annots(src[pno]):
            if a.type[0] in (fitz.PDF_ANNOT_LINK, fitz.PDF_ANNOT_WIDGET,
                             fitz.PDF_ANNOT_POPUP):
                continue
            key = tag_of(a) or f"x{a.xref}"
            groups.setdefault(key, []).append(serialize_annot(src, a))
        for items in groups.values():
            payload = {"annots": items}
            if layer:
                payload["layer"] = layer
            marks.append((pno, "import_annots", payload))
    return marks


# ---- a cheap edit counter per open document --------------------------------
# Bumped by the viewer on every change, so a cache can tell "nothing
# changed" without walking the pages (outside review, Nov 7 - N5).
# per open document, gone with it (Venice, Nov 9: a dict keyed by id()
# grew forever and a recycled id could hand a new document an old count).
# Compare only (equal or not), never arithmetic: an increment lost to two
# threads at once, or the viewer bumping after apply_op already did,
# doesn't matter, so it is not a count of edits (Venice N4).
_EDITS = _weakref.WeakKeyDictionary()
_EDITS_BY_ID = {}                     # documents that can't be weakly held


def bump_edits(doc):
    if doc is None:
        return
    try:
        _EDITS[doc] = _EDITS.get(doc, 0) + 1
    except TypeError:
        _EDITS_BY_ID[id(doc)] = _EDITS_BY_ID.get(id(doc), 0) + 1


def edit_count(doc):
    try:
        return _EDITS.get(doc, 0)
    except TypeError:
        return _EDITS_BY_ID.get(id(doc), 0)
