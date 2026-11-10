"""Log pages for the Weekly Owner Report (0.12.31): the RFI log, the
Submittal Detail Report, the optional Change Order log, the inclement
weather log (rainfall records) and the 10-day forecast page.

Each ``add_*`` function appends pages to an open ``fitz.Document`` and
returns ``{"pages": n, "totals": {...}}``. The layouts follow the GC's
current form (measured: see the owner-report brief, sections 1.3-1.6):
same columns, boxes, footers and totals. Every log numbers its own pages
("Page i of n"), written after the log is laid out.

No Qt here: the report builder and the tests use it headless. Fonts:
Liberation Sans Regular / Bold (SIL OFL, app/data/fonts), embedded and
subset when the report is saved - metric-compatible with Helvetica/Arial,
so the layouts measured for Helvetica hold. Code names them by the old
built-in names "helv" / "hebo" (see put_text / text_width); if the font
files are missing the built-ins are used. Dates print MM/DD/YYYY and the
long date goes in the log footers. Copied PDF pages (a PDF logo, a
forecast PDF) stay vector only when their own fonts are embedded, else
they go in as an image (place_pdf_page / place_logo), so the report has
no non-embedded font.

Record fields come from app/pm/schema.py as they are. Fields the schema
may not have yet are read when present and derived otherwise:
  RFI "sent"            -> else the created date (not for a Draft)
  RFI "closed_on"       -> else the last update when the status is Closed
  submittal "returned_to_sub" -> else the last review step's returned date
                           once every review step is back
"""
import calendar
import math
import os
import sys
from datetime import date, datetime

import fitz

from . import schema
from .store import spec_number
from ..dmoney import c2 as _c2

# page sizes (points)
PW, PH = 612, 792            # portrait
LW, LH = 792, 612            # landscape


def _hex(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


BLACK = (0, 0, 0)
WHITE = (1, 1, 1)
MUTED = (0.35, 0.35, 0.35)
RED = (0.78, 0.0, 0.0)
ROW_GREY = _hex("DCDCDC")            # log rows / package rules
BAR_GREY = _hex("D9D9D9")            # forecast header
STRIPE = _hex("F1F1F1")
DAY_YELLOW = _hex("FFD966")          # weather log day cells
TRACKED_BLUE = _hex("00B0F0")
CLAIMED_GREEN = _hex("00B050")
TITLE_BLUE = _hex("336699")

WORKDAYS = (0, 1, 2, 3, 4)           # Monday .. Friday
LOGO = (24.4, 28.5, 127.3, 80.3)


# ------------------------------------------------------------------ helpers
def _day(v):
    """date / datetime / 'YYYY-MM-DD...' / 'MM/DD/YYYY' -> date or None."""
    if v is None or v == "":
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        pass
    try:
        return datetime.strptime(s[:10], "%m/%d/%Y").date()
    except ValueError:
        return None


def _real(v):
    """A usable date: placeholder years before 1901 (01/01/1900) don't count
    as a date for totals, overdue or day counts."""
    d = _day(v)
    return d if d and d.year >= 1901 else None


def _mdy(v, blank=False):
    """Date as MM/DD/YYYY. blank=True (option g) prints placeholder dates
    (any year before 1901) as blank; otherwise the stored value prints as
    is."""
    if v in (None, ""):
        return ""
    d = _day(v)
    if d is None:
        return str(v)
    if blank and d.year < 1901:
        return ""
    return f"{d.month:02d}/{d.day:02d}/{d.year:04d}"


def _long(d):
    return f"{d:%B} {d.day}, {d.year}"


def _report_date(head):
    return _day((head or {}).get("date")) or date.today()


def _long_date(head):
    return (head or {}).get("long_date") or _long(_report_date(head))


def _num(v):
    if v in (None, ""):
        return None
    try:
        return float(str(v).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        return None


def _person(v):
    if isinstance(v, dict):
        return str(v.get("name") or v.get("email") or "")
    if isinstance(v, (list, tuple)):
        return "; ".join(_person(x) for x in v if x)
    return str(v or "")


# ------------------------------------------------------------------ fonts
FONT_FILES = {"helv": ("LiberationSans-Regular.ttf", "LibSans"),
              "hebo": ("LiberationSans-Bold.ttf", "LibSansBd")}
_fonts = {}


def font_dir():
    """app/data/fonts (from the source tree or the PyInstaller bundle)."""
    base = getattr(sys, "_MEIPASS", None)
    if base and os.path.isdir(os.path.join(base, "app", "data", "fonts")):
        return os.path.join(base, "app", "data", "fonts")
    return os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "data", "fonts")


def _font(font):
    """(alias, font bytes, fitz.Font) for "helv" / "hebo"; None when the
    font file is missing (then the PDF built-in is used)."""
    key = "hebo" if font in ("hebo", "bold") else "helv"
    if key not in _fonts:
        name, alias = FONT_FILES[key]
        try:
            with open(os.path.join(font_dir(), name), "rb") as f:
                buf = f.read()
            _fonts[key] = (alias, buf, fitz.Font(fontbuffer=buf))
        except Exception:                          # noqa: BLE001
            import logging
            logging.getLogger(__name__).warning(
                "report font %s not found - using the PDF built-in", name)
            _fonts[key] = None
    return _fonts[key]


def text_width(text, size, font="helv"):
    """Width in points of text in the report font."""
    f = _font(font)
    if f is None:
        return fitz.get_text_length(str(text), fontname=font, fontsize=size)
    return f[2].text_length(str(text), fontsize=size)


def put_text(page, point, text, size, font="helv", color=BLACK, **kw):
    """page.insert_text in the embedded report font (inserted once a
    page; doc.subset_fonts() before saving keeps only the glyphs used)."""
    f = _font(font)
    if f is None:
        return page.insert_text(point, text, fontsize=size, fontname=font,
                                color=color, **kw)
    alias, buf, _ = f
    done = getattr(page, "_report_fonts", None)
    if done is None:
        done = set()
        try:
            page._report_fonts = done
        except AttributeError:
            pass
    if alias not in done:
        page.insert_font(fontname=alias, fontbuffer=buf)
        done.add(alias)
    return page.insert_text(point, text, fontsize=size, fontname=alias,
                            color=color, **kw)


def _w(text, size, font="helv"):
    return text_width(text, size, font)


def _clip(text, size, font, width):
    t = str(text)
    while t and _w(t, size, font) > width:
        t = t[:-1]
    return t


def _wrap(text, size, font, width):
    """Words onto lines no wider than width; over-long words are split."""
    out = []
    for para in str(text or "").split("\n"):
        line = ""
        for word in para.split(" "):
            cand = (line + " " + word).strip() if line else word
            if _w(cand, size, font) <= width:
                line = cand
                continue
            if line:
                out.append(line)
            while len(word) > 1 and _w(word, size, font) > width:
                k = len(word)
                while k > 1 and _w(word[:k], size, font) > width:
                    k -= 1
                out.append(word[:k])
                word = word[k:]
            line = word
        out.append(line)
    return out or [""]


def _put(page, x, y, text, size=7.0, font="helv", color=BLACK,
         align="left"):
    """Text with its baseline at y; x is the left edge, the centre or the
    right edge depending on align."""
    text = str(text)
    if not text:
        return
    if align == "center":
        x -= _w(text, size, font) / 2
    elif align == "right":
        x -= _w(text, size, font)
    put_text(page, (x, y), text, size, font, color)


def _box(page, r, fill=None, color=BLACK, width=0.5):
    page.draw_rect(fitz.Rect(*r), color=color, fill=fill,
                   width=width if color is not None else 0)


def _shadow_box(page, r, width=0.8):
    """White box with a 3 pt black drop shadow (the form's title and filter
    boxes)."""
    x0, y0, x1, y1 = r
    page.draw_rect(fitz.Rect(x0 + 3, y0 + 3, x1 + 3, y1 + 3), color=None,
                   fill=BLACK)
    page.draw_rect(fitz.Rect(x0, y0, x1, y1), color=BLACK, fill=WHITE,
                   width=width)


# ------------------------------------------------- copied PDF pages
# A PDF logo, a forecast PDF attachment and the plan sheets bring their own
# fonts. show_pdf_page copies them as they are, so a source using a
# non-embedded (base-14) font prints with whatever the reader substitutes.
# Such a page goes in as an image instead; a page whose fonts are all
# embedded (or that has no text) stays vector.
RASTER_DPI = 200             # forecast attachments, plan sheets
LOGO_DPI = 300
LOGO_FIT = (160.0, 81.0)     # the largest logo box (page 1), points
MAX_PIXELS = 12_000_000      # a cap for a huge page at a big placed size
LOSSLESS_MAX = 1_500_000     # bytes: a busier raster goes in as JPEG
JPEG_QUALITY = 85


def font_embedded(entry):
    """One Document.get_page_fonts() entry (xref, ext, type, basefont,
    name, encoding[, referencer]): True when the font program is in the
    PDF. ext is "n/a" when there is no font file; a Type3 font draws its
    glyphs itself (no file, nothing to substitute)."""
    xref, ext, typ = entry[0], entry[1], entry[2]
    if str(typ or "").lower() == "type3":
        return True
    return bool(xref) and str(ext or "").strip().lower() not in ("", "n/a")


def missing_fonts(doc, pno=0):
    """Base names of the fonts page pno uses (directly or through a form
    XObject) that are not embedded. A page that can't be read counts as
    ["?"] so the caller takes the safe (image) path."""
    try:
        fonts = doc.get_page_fonts(pno, full=True)
    except Exception:                              # noqa: BLE001
        return ["?"]
    return sorted({str(f[3]) for f in fonts if not font_embedded(f)})


def fonts_embedded(doc, pno=0):
    return not missing_fonts(doc, pno)


def _content_of(doc, pno, referencer, cache):
    """The content stream a font entry's referencer draws with: the page's
    (referencer 0) or the form XObject's. None when it can't be read."""
    if referencer not in cache:
        try:
            data = doc[pno].read_contents() if not referencer \
                else doc.xref_stream(referencer)
        except Exception:                          # noqa: BLE001
            data = None
        cache[referencer] = data
    return cache[referencer]


def font_used(doc, pno, entry, cache=None):
    """True when the font's resource name is used in its referencer's
    content stream (/Name ... Tf, or the name anywhere: conservative).
    True too when that can't be told."""
    cache = {} if cache is None else cache
    name = str(entry[4] or "")
    ref = entry[6] if len(entry) > 6 and entry[6] else 0
    data = _content_of(doc, pno, ref, cache)
    if data is None or not name:
        return True
    import re
    pat = rb"/" + re.escape(name.encode("latin-1", "replace")) + \
        rb"(?![^\s/\[\]<>(){}%])"
    return re.search(pat, bytes(data)) is not None


def font_report(doc, pno=0):
    """[(xref, ext, type, basefont, name, referencer, embedded, used)]
    for page pno - the diagnosis behind fonts_embedded()."""
    out, cache = [], {}
    try:
        fonts = doc.get_page_fonts(pno, full=True)
    except Exception:                              # noqa: BLE001
        return out
    for f in fonts:
        ref = f[6] if len(f) > 6 else 0
        out.append((f[0], f[1], f[2], f[3], f[4], ref, font_embedded(f),
                    font_used(doc, pno, f, cache)))
    return out


def drop_unused_fonts(doc, pno=0):
    """Remove font resources that are not embedded and not used by the
    content that lists them (e.g. a /Helv left behind by a deleted
    annotation), so they don't travel into the report. Only for a working
    copy the report owns (a marked plan sheet). Returns the names
    dropped."""
    dropped = []
    page = doc[pno]
    for xref, _e, _t, base, name, ref, emb, used in font_report(doc, pno):
        if emb or used or not name:
            continue
        holder = ref or page.xref
        if "/" in name or " " in name:
            continue
        try:
            # only where the holder has its own Resources (never create
            # one that would hide inherited resources)
            if doc.xref_get_key(holder, "Resources")[0] == "null" or \
                    doc.xref_get_key(holder, "Resources/Font/" + name)[0] \
                    == "null":
                continue
            doc.xref_set_key(holder, "Resources/Font/" + name, "null")
            dropped.append(base or name)
        except Exception:                          # noqa: BLE001
            pass
    return dropped


def unembedded_fonts(doc):
    """[(page number from 1, base font)] for every non-embedded font."""
    return [(pno + 1, name) for pno in range(doc.page_count)
            for name in missing_fonts(doc, pno)]


def fit_rect(rect, w, h, keep=True):
    """The part of rect a w x h source fills, centred (as show_pdf_page
    and insert_image place it with keep_proportion)."""
    rect = fitz.Rect(rect)
    if not keep or w <= 0 or h <= 0:
        return rect
    s = min(rect.width / w, rect.height / h)
    cw, ch = w * s, h * s
    x0 = rect.x0 + (rect.width - cw) / 2
    y0 = rect.y0 + (rect.height - ch) / 2
    return fitz.Rect(x0, y0, x0 + cw, y0 + ch)


def source_rect(src, pno=0, clip=None):
    """The shown part of the source page (show_pdf_page's clip semantics:
    the clip intersected with the page rect)."""
    r = src[pno].rect
    if clip:
        r = fitz.Rect(clip) & r
    if r.is_empty or r.is_infinite:
        raise ValueError("nothing to show - empty clip")
    return r


def raster_page(src, pno, size, clip=None, dpi=RASTER_DPI, annots=False):
    """Page pno of src (the clip of it) rendered for a placed size (w, h)
    in points at dpi. Returns (insert_image keyword arguments, bytes the
    image adds): a lossless pixmap (stored deflated, ~ zlib of its
    samples), or a JPEG when that comes out over LOSSLESS_MAX and the
    JPEG is smaller. The size estimate calls this too."""
    import zlib
    srect = source_rect(src, pno, clip)
    w, h = size
    z = max(w / srect.width, h / srect.height) * dpi / 72.0
    px = srect.width * z * srect.height * z
    if px > MAX_PIXELS:
        z *= math.sqrt(MAX_PIXELS / px)
    pix = src[pno].get_pixmap(matrix=fitz.Matrix(z, z), clip=srect,
                              alpha=False, annots=annots)
    n = len(zlib.compress(pix.samples, 6))
    if n > LOSSLESS_MAX:
        try:
            jpg = pix.tobytes("jpg", jpg_quality=JPEG_QUALITY)
            if len(jpg) < n:
                return {"stream": jpg}, len(jpg)
        except Exception:                          # noqa: BLE001
            pass                                   # an engine without JPEG
    return {"pixmap": pix}, n


def place_pdf_page(page, rect, src, pno=0, clip=None, keep_proportion=True,
                   dpi=RASTER_DPI, annots=False):
    """Put page pno of src into rect: vectors (show_pdf_page) when every
    font it uses is embedded, else an image at dpi of its placed size.
    Returns ("vector" | "image", bytes the image adds or 0)."""
    rect = fitz.Rect(rect)
    if fonts_embedded(src, pno):
        page.show_pdf_page(rect, src, pno, keep_proportion=keep_proportion,
                           clip=fitz.Rect(clip) if clip else None)
        return "vector", 0
    srect = source_rect(src, pno, clip)
    tr = fit_rect(rect, srect.width, srect.height, keep_proportion)
    kw, n = raster_page(src, pno, (tr.width, tr.height), srect, dpi,
                        annots=annots)
    page.insert_image(tr, keep_proportion=False, **kw)
    return "image", n


def logo_raster(src):
    """A PDF logo's page 1 as an image sized for the largest logo box at
    LOGO_DPI (one image, reused on every page)."""
    sr = src[0].rect
    s = min(LOGO_FIT[0] / sr.width, LOGO_FIT[1] / sr.height)
    return raster_page(src, 0, (sr.width * s, sr.height * s), dpi=LOGO_DPI)


def place_logo(page, rect, path):
    """A PDF logo into rect: vectors when its fonts are embedded, else one
    image rendered once a document and reused by xref."""
    doc = page.parent
    cache = getattr(doc, "_report_logos", None)
    if cache is None:
        cache = {}
        try:
            doc._report_logos = cache
        except AttributeError:
            pass
    key = os.path.abspath(str(path))
    xref = cache.get(key)
    if xref:
        page.insert_image(fitz.Rect(rect), xref=xref, keep_proportion=True)
        return "image"
    with fitz.open(path) as src:
        if xref == 0 or fonts_embedded(src, 0):
            cache[key] = 0
            page.show_pdf_page(fitz.Rect(rect), src, 0, keep_proportion=True)
            return "vector"
        kw, _n = logo_raster(src)
    cache[key] = page.insert_image(fitz.Rect(rect), keep_proportion=True,
                                   **kw)
    return "image"


def _logo(page, head, rect=LOGO):
    path = (head or {}).get("logo")
    if not path or not os.path.isfile(str(path)):
        return
    try:
        if str(path).lower().endswith(".pdf"):
            place_logo(page, rect, path)
        else:
            page.insert_image(fitz.Rect(*rect), filename=str(path),
                              keep_proportion=True)
    except Exception:           # a bad logo file never stops the report
        pass


def _log_header(page, head, title, landscape):
    """Logo, title box with shadow, company block and project block - the
    top of every RFI / submittal / CO log page."""
    head = head or {}
    _logo(page, head)
    if landscape:
        box, py, cy = (462, 26, 745, 51), 93.0, 120.0
        lx, vx = 462, 552
    else:
        box, py, cy = (316, 26, 562, 51), 108.0, 115.5
        lx, vx = 318, 408
    _shadow_box(page, box)
    _put(page, (box[0] + box[2]) / 2, 43, title, 13, "hebo", align="center")
    comp = head.get("company") or {}
    _put(page, 24, cy, comp.get("name") or "", 10.5, "hebo")
    y = cy + 16.5
    for ln in (comp.get("lines") or [])[:3]:
        _put(page, 24, y, _clip(ln, 7.5, "helv", 270), 7.5)
        y += 12
    pj = head.get("project") or {}
    rows = [("Project Name:", pj.get("name")),
            ("Project No.:", pj.get("number")),
            ("Project No. Arch:", pj.get("number_arch")),
            ("Project No. Owner:", pj.get("number_owner")),
            ("Project Location:", pj.get("location"))]
    for i, (label, val) in enumerate(rows):
        yy = py + 11.5 * i
        _put(page, lx, yy, label, 7.5)
        _put(page, vx, yy, _clip(val or "", 7.5, "helv",
                                 page.rect.width - vx - 24), 7.5)


# "  |  Report #007" while an auto-pack owner report is drawn (G23: the
# report number on the log pages too); "" otherwise
FOOTER_SUFFIX = ""


def _footers(doc, pnos, label, long_date):
    """'<log name> | long date | Page i of n' on each page of one log."""
    if FOOTER_SUFFIX and FOOTER_SUFFIX not in long_date:
        long_date = f"{long_date}{FOOTER_SUFFIX}"
    n = len(pnos)
    for i, pno in enumerate(pnos):
        page = doc[pno]
        W, H = page.rect.width, page.rect.height
        y = H - 24
        _put(page, 48, y, label, 7.5)
        _put(page, W / 2, y, long_date, 7.5, align="center")
        _put(page, W - 36, y, f"Page {i + 1} of {n}", 7.5, align="right")


class _Pages:
    """Pages of one log: start(page, first) draws the header and filter
    box (first page only) and the column headings, and returns the first
    row's y."""

    def __init__(self, doc, landscape, start, bottom):
        self.doc, self.landscape = doc, landscape
        self.start, self.bottom = start, bottom
        self.pnos = []
        self.page = None
        self.y = 0

    def new(self):
        W, H = (LW, LH) if self.landscape else (PW, PH)
        self.page = self.doc.new_page(width=W, height=H)
        first = not self.pnos
        self.pnos.append(self.doc.page_count - 1)
        # like the GC's form: the logo, title, company and filter blocks on
        # a log's first page; later pages carry only the column headings
        self.y = self.start(self.page, first)
        return self.page

    def need(self, h, limit=None):
        """True when a new page was started to fit h points."""
        if self.page is None:
            self.new()
            return True
        if self.y + h > (limit or self.bottom):
            self.new()
            return True
        return False


# ------------------------------------------------------------ as-of views
def _after(v, as_of):
    d = _real(v)
    return bool(d and as_of and d > as_of)


def as_of_view(kind, recs, as_of, rfis=()):
    """Option as_of_logs: the records as they stood on the report date.
    A log printed for a past week must not show what happened later
    (review: RFI-001 printed "Closed 10/29" - the record's last edit - on
    a report dated 11/20, and a change event approved in December showed
    as an approved CO). Copies are returned; the store is not touched.
    rfi:       not sent yet -> left out; answered later -> open, no answer.
    submittal: review steps sent later dropped, returns after the date
               blanked; "closed" with no return on or before -> open.
    event:     no date on or before (and no linked RFI sent on or before)
               -> left out; approved later -> pending or open, no CO no."""
    as_of = _day(as_of)
    if not as_of:
        return list(recs)
    sent_rfis = {r.get("_id") for r in rfis
                 if _real(_rfi_sent(r)) and _real(_rfi_sent(r)) <= as_of}
    out = []
    for r in recs:
        r = dict(r)
        if kind == "rfi":
            sent = _real(_rfi_sent(r))
            if sent and sent > as_of:
                continue
            if _after(r.get("answered"), as_of):
                for k in ("answered", "answered_by", "answer", "closed_on"):
                    r.pop(k, None)
            if _after(r.get("closed_on"), as_of):
                r.pop("closed_on", None)
            if _rfi_closed(r):
                if not _real(r.get("answered")) and \
                        not _real(r.get("closed_on")):
                    r["status"] = "Open"
                elif not r.get("closed_on"):
                    # the answer date, not the record's last edit (_updated)
                    r["closed_on"] = r.get("answered")
        elif kind == "submittal":
            if r.get("workflow"):
                steps = []
                for st in _steps(r):
                    if _after(st.get("sent"), as_of):
                        continue
                    st = dict(st)
                    if _after(st.get("returned"), as_of):
                        st.pop("returned", None)
                    steps.append(st)
                r["workflow"] = steps
            if _after(r.get("returned_to_sub"), as_of):
                r.pop("returned_to_sub", None)
            if schema.is_closed("submittal", r) and \
                    not _real(_sub_returned_to_sub(r)):
                r["status"] = "Open"
        elif kind == "event":
            dates = [_real(r.get(k)) for k in ("submitted", "approved")]
            dates = [d for d in dates if d]
            linked = r.get("rfi") in sent_rfis if r.get("rfi") else False
            if dates and min(dates) > as_of and not linked:
                continue
            if _after(r.get("approved"), as_of):
                r.pop("approved", None)
                r.pop("co_no", None)
                r["status"] = "Open"
            if _after(r.get("submitted"), as_of):
                r.pop("submitted", None)
                r["status"] = "Open"
            elif r.get("submitted") and r.get("status") == "Open" \
                    and not r.get("approved"):
                r["status"] = "Pending"
        out.append(r)
    return out


def log_records(store, kind, opts=None, today=None):
    """The records a log prints: as they stood on the report date when
    option as_of_logs is on, else as stored."""
    recs = store.list(kind)
    if (opts or {}).get("as_of_logs"):
        rfis = store.list("rfi") if kind == "event" else ()
        recs = as_of_view(kind, recs, today, rfis)
    return recs


# ------------------------------------------------------------------- RFIs
def _rfi_no(rec):
    no = str(rec.get("_no") or "")
    pre = schema.TOOLS["rfi"].get("prefix") or ""
    return no[len(pre):] if pre and no.startswith(pre) else no


def _rfi_closed(rec):
    return rec.get("status") == "Closed"


def _rfi_sent(rec):
    if rec.get("sent"):
        return rec["sent"]
    if rec.get("status") == "Draft":
        return ""
    return (rec.get("_created") or "")[:10]


def _rfi_closed_on(rec):
    if rec.get("closed_on"):
        return rec["closed_on"]
    if _rfi_closed(rec):
        return (rec.get("_updated") or "")[:10]
    return ""


def _rfi_overdue(rec, today):
    due = _real(rec.get("due"))
    return bool(due and due < today and not _rfi_closed(rec)
                and not _real(rec.get("answered")))


def _rfi_totals(store, today, recs=None):
    recs = store.list("rfi") if recs is None else recs
    closed = sum(1 for r in recs if _rfi_closed(r))
    return {"total": len(recs), "closed": closed,
            "open": len(recs) - closed,
            "responded": sum(1 for r in recs if _real(r.get("answered"))),
            "overdue": sum(1 for r in recs if _rfi_overdue(r, today))}


# column x positions (portrait), measured from the form
RFI_COLS = [  # key, x, wrap width
    ("num", 52, 95), ("orig", 172, 60), ("bic", 237, 56), ("sent", 295, 44),
    ("due", 341, 38), ("resp", 381, 44), ("closed", 428, 44),
    ("status", 542, 32)]
RFI_ROW = 6.0           # body font size
RFI_LEAD = 7.2          # line pitch inside a row
RFI_GAP = 2.5           # white gap between grey rows


def add_rfi_log(doc, store, head, opts=None):
    """Request for Information Log (portrait, spec 1.3)."""
    opts = opts or {}
    blank = bool(opts.get("blank_dates"))
    open_only = bool(opts.get("open_only"))
    today = _report_date(head)
    every = log_records(store, "rfi", opts, today)
    recs = every
    if open_only:
        recs = [r for r in recs if not _rfi_closed(r)]

    def start(page, first=True):
        hy = 260.0 if first else 48.0
        if not first:
            return rfi_heads(page, hy)
        _log_header(page, head, "Request for Information Log", False)
        _shadow_box(page, (23, 180, 587, 230))
        _put(page, 26, 190.5, "This Report Was Created Using The Following "
             "Filters:", 7.7, "hebo")
        _put(page, 26, 202.8, "Days With Reviewer  [ ]", 7.2)
        _put(page, 115.4, 202.8, "Days Overdue  [ ]", 7.2)
        _put(page, 189.2, 202.8, "Include Question and Answer  [ ]", 7.2)
        _put(page, 317.9, 202.8, "Include Posted Replies  [ ]", 7.2)
        _put(page, 26, 214.8, "Initial Folder:", 7.2)
        _put(page, 82.1, 214.8, "All", 7.2)
        if open_only:
            _put(page, 103, 214.8, "Status: Open only", 7.2)
        _put(page, 200, 214.8, "Responsible Party:", 7.2)
        _put(page, 26, 225.8, "Date Filter:", 7.2)
        _put(page, 200, 225.8, "Duration:", 7.2)
        return rfi_heads(page, hy)

    def rfi_heads(page, hy):
        _put(page, 37, hy, "Number Subject", 6.4, "hebo")
        _put(page, 172, hy, "Originator", 6.4, "hebo")
        _put(page, 237, hy, "BIC", 6.4, "hebo")
        for cx, top, bottom in ((311, "Date", "Submitted"),
                                (397, "Date", "Responded"),
                                (444, "Date", "Closed")):
            _put(page, cx, hy - 8, top, 5.6, "hebo", align="center")
            _put(page, cx, hy, bottom, 5.6, "hebo", align="center")
        _put(page, 341, hy, "Date Due", 6.4, "hebo")
        _put(page, 542, hy, "Status", 6.4, "hebo")
        # "Posted Replies", rotated 90 (reads bottom to top) over the boxes
        label = "Posted Replies"
        size = min(5.0, 29.0 / max(_w(label, 1.0), 0.01))
        put_text(page, (585.5, hy + 4), label, size, "helv", BLACK,
                 rotate=90)
        return hy + 5

    pages = _Pages(doc, False, start, PH - 42)
    pages.new()
    if not recs:
        _put(pages.page, 52, pages.y + 12, "No RFIs", 7.5)
        pages.y += 18
    for r in recs:
        vals = {"num": f"{_rfi_no(r)} {r.get('subject') or ''}".strip(),
                "orig": _person(r.get("from")) or r.get("_by") or "",
                "bic": schema.ball_in_court("rfi", r),
                "sent": _mdy(_rfi_sent(r), blank),
                "due": _mdy(r.get("due"), blank),
                "resp": _mdy(r.get("answered"), blank),
                "closed": _mdy(_rfi_closed_on(r), blank),
                "status": r.get("status") or ""}
        cells = [(x, _wrap(vals[k], RFI_ROW, "helv", w)[:8])
                 for k, x, w in RFI_COLS]
        nl = max(len(c[1]) for c in cells)
        h = RFI_LEAD * nl + 4.8
        pages.need(h + RFI_GAP)
        p, y = pages.page, pages.y
        _box(p, (26, y, 590, y + h), fill=ROW_GREY, color=None)
        for x, lines in cells:
            for k, ln in enumerate(lines):
                _put(p, x, y + 8.4 + RFI_LEAD * k, ln, RFI_ROW)
        # posted replies box (marked when the RFI has a discussion)
        _box(p, (576, y + 2, 584, y + 10), fill=WHITE, width=0.7)
        if r.get("thread"):
            p.draw_line((577.5, y + 3.5), (582.5, y + 8.5), color=BLACK,
                        width=0.7)
            p.draw_line((577.5, y + 8.5), (582.5, y + 3.5), color=BLACK,
                        width=0.7)
        pages.y = y + h + RFI_GAP

    tot = _rfi_totals(store, today, every)
    tot["listed"] = len(recs)
    pages.need(46)
    p, y = pages.page, pages.y + 6
    _put(p, 26, y + 8, "RFI LOG TOTALS:", 7.5, "hebo")
    _put(p, 60, y + 21, f"Total RFIs   {tot['total']}", 7.5)
    _put(p, 129, y + 21, f"Total Closed RFIs   {tot['closed']}", 7.5)
    _put(p, 229, y + 21, f"Total Open RFIs   {tot['open']}", 7.5)
    _put(p, 60, y + 33, f"Qty. Responded   {tot['responded']}", 7.5)
    _footers(doc, pages.pnos, "Request for Information Log",
             _long_date(head))
    return {"pages": len(pages.pnos), "totals": tot}


# -------------------------------------------------------------- submittals
def _steps(rec):
    return [s for s in rec.get("workflow") or [] if isinstance(s, dict)]


def _sub_review(rec):
    """(sent to reviewer, due from review, received from review) from the
    review steps: sent = the first step's; while a step is out, its due
    date and no return; once all are back, the last step's due/returned."""
    steps = _steps(rec)
    if not steps:
        return "", "", ""
    sent = steps[0].get("sent") or ""
    out = [s for s in steps if not s.get("returned")]
    if out:
        return sent, out[0].get("due") or "", ""
    return sent, steps[-1].get("due") or "", steps[-1].get("returned") or ""


def _sub_returned_to_sub(rec):
    if rec.get("returned_to_sub"):
        return rec["returned_to_sub"]
    steps = _steps(rec)
    if steps and all(s.get("returned") for s in steps):
        return steps[-1].get("returned") or ""
    return ""


def _sub_open(rec):
    """Option (f): open = not returned to the sub (and not closed)."""
    return not _real(_sub_returned_to_sub(rec)) and \
        not schema.is_closed("submittal", rec)


def _sub_due(rec):
    """The date it is waiting on: the review due date once sent to the
    reviewer, else the submit-by date."""
    sent, due, _ret = _sub_review(rec)
    if _real(sent):
        return _real(due)
    return _real(rec.get("submit_by") or schema.submit_by(rec))


def _sub_overdue(rec, today):
    due = _sub_due(rec)
    sent, _due, ret = _sub_review(rec)
    return bool(_sub_open(rec) and not _real(ret) and due and due < today)


def _sub_days(rec, today):
    """(days in review, days overdue) or None where it doesn't apply."""
    sent, due, ret = _sub_review(rec)
    end = _real(ret) or today
    s = _real(sent)
    in_review = (end - s).days if s else None
    d = _sub_due(rec)
    overdue = max(0, (end - d).days) if d else None
    return in_review, overdue


def _sub_totals(store, today, recs=None):
    recs = store.list("submittal") if recs is None else recs
    yet = open_over = recv_over = 0
    review_days = []
    for r in recs:
        sent, due, ret = _sub_review(r)
        if not _real(sent) and not schema.is_closed("submittal", r):
            yet += 1
        if _sub_overdue(r, today):
            open_over += 1
        if _real(ret) and _real(due) and _real(ret) > _real(due):
            recv_over += 1
        dr = _sub_days(r, today)[0]
        if dr is not None:
            review_days.append(dr)
    avg = round(sum(review_days) / len(review_days)) if review_days else 0
    return {"total": len(recs), "yet_to_submit": yet,
            "open_overdue": open_over, "received_overdue": recv_over,
            "avg_days_in_review": avg,
            "open": sum(1 for r in recs if _sub_open(r)),
            "overdue": open_over}


def _pkg_label(pkg, items):
    if pkg is None:
        return "(no package)"
    spec = spec_number(pkg.get("spec") or "") or \
        next((spec_number(i.get("spec") or "") for i in items
              if spec_number(i.get("spec") or "")), "")
    code = spec.replace(" ", "")
    return "-".join(x for x in (code, pkg.get("title") or "",
                                str(pkg.get("_no") or "")) if x)


def _sub_groups(store, recs):
    """[(package label, [items])] by spec code, items by number/revision;
    items with no (or a deleted) package come last."""
    pkgs = {p["_id"]: p for p in store.list("subpkg")}
    groups = {}
    for r in recs:
        pid = r.get("package") if r.get("package") in pkgs else None
        groups.setdefault(pid, []).append(r)

    def item_key(r):
        try:
            rev = int(float(r.get("revision") or 0))
        except (TypeError, ValueError):
            rev = 0
        return (str(r.get("_no") or ""), rev, r.get("_n") or 0)

    out = []
    for pid, items in groups.items():
        items.sort(key=item_key)
        pkg = pkgs.get(pid)
        label = _pkg_label(pkg, items)
        code = spec_number((pkg or {}).get("spec") or "") or \
            spec_number(items[0].get("spec") or "")
        out.append(((pid is None, code or "~", (pkg or {}).get("_n") or 0),
                    label, items))
    out.sort(key=lambda g: g[0])
    return [(label, items) for _k, label, items in out]


SUB_SIZE = 6.8
SUB_LEAD = 8.5
SUB_BOTTOM = LH - 40         # rows stop here (footer at H - 24)
SUB_TOTALS_Y = LH - 45       # totals block baseline on the last page


def add_submittal_log(doc, store, head, opts=None):
    """Submittal Detail Report (landscape, spec 1.4), grouped by package."""
    opts = opts or {}
    blank = bool(opts.get("blank_dates"))
    open_only = bool(opts.get("open_only"))
    today = _report_date(head)
    every = log_records(store, "submittal", opts, today)
    recs = every
    if open_only:
        recs = [r for r in recs if _sub_open(r)]

    def start(page, first=True):
        if not first:
            return sub_heads(page, 52.0)
        _log_header(page, head, "Submittal Detail Report", True)
        _shadow_box(page, (23, 166, 769, 196))
        _put(page, 28, 177.6, "This report is detailed by:", 8.2, "hebo")
        _put(page, 260, 176, "Only Overdue: [ ]", 7.5)
        _put(page, 331.9, 176, "Most Current: [ ]", 7.5)
        _put(page, 409.3, 176, "Only Open: [X]" if open_only
             else "Only Open: [ ]", 7.5)
        _put(page, 28, 191.5, "Status:" + ("  Open only" if open_only
                                            else ""), 7.5)
        _put(page, 248, 191.5, "BIC:", 7.5)
        _put(page, 502, 191.5, "Submitting Company:", 7.5)
        return sub_heads(page, 235.5)

    def sub_heads(page, b):      # b: the bottom heading line
        heads = [(51, ("Item", "No:"), "left"), (93, ("Rev", "No:"), "left"),
                 (120, ("Description",), "left"),
                 (227, ("Submitting Company",), "left"),
                 (352, ("Received", "From Sub"), "center"),
                 (393, ("Submit", "to", "Reviewer"), "center"),
                 (433, ("Due", "from", "Review"), "center"),
                 (475, ("Received", "From", "Review"), "center"),
                 (515, ("Returned", "to", "Sub"), "center"),
                 (563, ("Status",), "center"), (655, ("BIC",), "center"),
                 (718, ("Days In", "Review"), "center"),
                 (750, ("Days", "Overdue"), "center")]
        for x, lines, al in heads:
            for k, t in enumerate(reversed(lines)):
                _put(page, x, b - 8 * k, t, 5.8, "hebo", align=al)
        page.draw_line((23, b + 4), (769, b + 4), color=BLACK, width=2)
        return b + 7

    pages = _Pages(doc, True, start, SUB_BOTTOM)
    pages.new()

    def pkg_row(label, cont=False):
        p, y = pages.page, pages.y
        p.draw_line((23, y + 1), (769, y + 1), color=ROW_GREY, width=2)
        _put(p, 23, y + 9.5, "Package:", 7, "hebo")
        _put(p, 66, y + 9.5, _clip(label + (" (continued)" if cont else ""),
                                   7, "hebo", 690), 7, "hebo")
        pages.y = y + 11

    def item_cells(r):
        sent, due, ret = _sub_review(r)
        din, dover = _sub_days(r, today)
        try:
            rev = f"{int(float(r.get('revision') or 0)):04d}"
        except (TypeError, ValueError):
            rev = str(r.get("revision") or "")
        company = _person(r.get("responsible"))
        cells = [  # x, text, wrap width, align
            (41, str(r.get("_no") or ""), 50, "left"),
            (93, rev, 25, "left"),
            (120, r.get("title") or "", 104, "left"),
            (227, company, 104, "left"),
            (352, _mdy(r.get("received"), blank), 41, "center"),
            (393, _mdy(sent, blank), 41, "center"),
            (433, _mdy(due, blank), 41, "center"),
            (475, _mdy(ret, blank), 41, "center"),
            (515, _mdy(_sub_returned_to_sub(r), blank), 41, "center"),
            (563, r.get("status") or "", 60, "center"),
            (655, schema.ball_in_court("submittal", r), 78, "center"),
            (718, "" if din is None else str(din), 30, "center"),
            (750, "" if dover is None else str(dover), 30, "center")]
        return [(x, _wrap(t, SUB_SIZE, "helv", w)[:6], al)
                for x, t, w, al in cells]

    groups = _sub_groups(store, recs)
    if not groups:
        _put(pages.page, 41, pages.y + 12, "No submittals", 7.5)
        pages.y += 18
    for label, items in groups:
        first = item_cells(items[0])
        h0 = SUB_LEAD * max(len(c[1]) for c in first) + 9
        pages.need(11 + h0)
        pkg_row(label)
        for r in items:
            cells = item_cells(r)
            h = SUB_LEAD * max(len(c[1]) for c in cells) + 9
            if pages.need(h):
                pkg_row(label, cont=True)
            p, y = pages.page, pages.y
            for x, lines, al in cells:
                for k, ln in enumerate(lines):
                    _put(p, x, y + 8.5 + SUB_LEAD * k, ln, SUB_SIZE,
                         align=al)
            p.draw_line((23, y + h), (769, y + h), color=ROW_GREY,
                        width=0.5)
            pages.y = y + h

    tot = _sub_totals(store, today, every)
    tot["listed"] = len(recs)
    if pages.y > SUB_TOTALS_Y - 12:
        pages.new()
    p, y = pages.page, SUB_TOTALS_Y
    _put(p, 60, y, "Total Submittal Items Yet to Submit: "
         f"{tot['yet_to_submit']}", 7.5)
    _put(p, 210, y, f"# Submittal Items Open Overdue: {tot['open_overdue']}",
         7.5)
    _put(p, 365, y, "# Submittal Items Received Overdue: "
         f"{tot['received_overdue']}", 7.5)
    _put(p, 110, y + 11, "Avg Days in Review (Days) "
         f"{tot['avg_days_in_review']}", 7.5)
    _footers(doc, pages.pnos, "Submittal Detail Report", _long_date(head))
    return {"pages": len(pages.pnos), "totals": tot}


# ------------------------------------------------------- change order log
CO_OPEN = ("Open", "Pending")


def _event_price(e):
    from .cost import event_price
    return event_price(e)


def _int(v):
    n = _num(v)
    return int(round(n)) if n is not None else 0


def _co_totals(store, evs=None):
    evs = store.list("event") if evs is None else evs
    orig = sum(_num(c.get("scheduled")) or 0 for c in store.list("contract"))
    by = {s: [e for e in evs if e.get("status") == s]
          for s in ("Open", "Pending", "Approved")}
    appr = sum(_event_price(e) for e in by["Approved"])
    return {"total": len(evs),
            "original": _c2(orig), "approved": _c2(appr),
            "revised": _c2(orig + appr),
            "pending": _c2(sum(_event_price(e) for e in by["Pending"])),
            "open_amount": _c2(sum(_event_price(e) for e in by["Open"])),
            "approved_days": sum(_int(e.get("days")) for e in by["Approved"]),
            "pending_days": sum(_int(e.get("days")) for e in by["Pending"]),
            "open": len(by["Open"]) + len(by["Pending"]), "overdue": 0}


def _money(v):
    v = _c2(float(v or 0))
    s = f"${abs(v):,.0f}" if v == int(v) else f"${_c2(abs(v)):,.2f}"
    return f"({s})" if v < 0 else s


CO_COLS = [  # key, x, wrap width, align
    ("no", 30, 40, "left"), ("title", 72, 222, "left"),
    ("reason", 300, 66, "left"), ("status", 370, 58, "left"),
    ("sent", 430, 70, "left"), ("approved", 505, 70, "left"),
    ("amount", 620, 60, "right"), ("days", 653, 20, "center"),
    ("co", 680, 80, "left")]


def add_co_log(doc, store, head, opts=None):
    """Change Order Log (option m, landscape): change events with the
    prime contract totals."""
    opts = opts or {}
    blank = bool(opts.get("blank_dates"))
    every = log_records(store, "event", opts, _report_date(head))
    evs = every
    if opts.get("open_only"):
        evs = [e for e in evs if e.get("status") in CO_OPEN]

    def start(page, first=True):
        if first:
            _log_header(page, head, "Change Order Log", True)
        y = 200 if first else 40
        _box(page, (23, y, 769, y + 16), fill=ROW_GREY, color=None)
        labels = {"no": "No.", "title": "Title", "reason": "Reason",
                  "status": "Status", "sent": "Sent to Owner",
                  "approved": "Approved", "amount": "Amount",
                  "days": "Days", "co": "CO No."}
        for k, x, _w_, al in CO_COLS:
            _put(page, x, y + 11, labels[k], 7.5, "hebo", align=al)
        return y + 18

    pages = _Pages(doc, True, start, SUB_BOTTOM)
    pages.new()
    if not evs:
        _put(pages.page, 30, pages.y + 12, "No change events", 7.5)
        pages.y += 18
    for e in evs:
        st = e.get("status") or ""
        vals = {"no": str(e.get("_no") or ""), "title": e.get("title") or "",
                "reason": e.get("reason") or "", "status": st,
                "sent": _mdy(e.get("submitted"), blank),
                "approved": _mdy(e.get("approved"), blank),
                "amount": _money(_event_price(e)),
                "days": str(_int(e.get("days"))),
                "co": str(e.get("co_no") or "")}
        cells = [(x, _wrap(vals[k], 7, "helv", w)[:5], al,
                  "hebo" if k == "status" and st == "Pending" else "helv")
                 for k, x, w, al in CO_COLS]
        h = 9 * max(len(c[1]) for c in cells) + 5
        pages.need(h)
        p, y = pages.page, pages.y
        for x, lines, al, font in cells:
            for k, ln in enumerate(lines):
                _put(p, x, y + 9.5 + 9 * k, ln, 7, font, align=al)
        p.draw_line((23, y + h), (769, y + h), color=ROW_GREY, width=0.5)
        pages.y = y + h

    tot = _co_totals(store, every)
    tot["listed"] = len(evs)
    pages.need(80)
    p, y = pages.page, pages.y + 6
    _put(p, 30, y + 9, "CHANGE ORDER TOTALS:", 7.5, "hebo")
    rows = [("Original contract sum", tot["original"], "helv"),
            ("Approved change orders", tot["approved"], "helv"),
            ("Revised contract sum", tot["revised"], "hebo"),
            ("Pending (sent to Owner, not approved)", tot["pending"], "helv"),
            ("Open (not yet priced/sent)", tot["open_amount"], "helv")]
    for i, (label, v, font) in enumerate(rows):
        yy = y + 22 + 12 * i
        _put(p, 60, yy, label, 7.5)
        _put(p, 330, yy, _money(v), 7.5, font, align="right")
    _put(p, 380, y + 22, f"Approved days added: {tot['approved_days']}", 7.5)
    _put(p, 475, y + 22, f"Pending days: {tot['pending_days']}", 7.5)
    _footers(doc, pages.pnos, "Change Order Log", _long_date(head))
    return {"pages": len(pages.pnos), "totals": tot}


# ------------------------------------------------------------ page-1 counts
def counts(store, today=None, opts=None):
    """Option (f): open / overdue / total per log for the page-1 LOGS
    table. Overdue = due before the report date and not returned/closed.
    With option as_of_logs the counts are of the records as they stood on
    the report date (as_of_view), the same rows the logs print."""
    today = _day(today) or date.today()
    rt = _rfi_totals(store, today, log_records(store, "rfi", opts, today))
    st = _sub_totals(store, today,
                     log_records(store, "submittal", opts, today))
    ct = _co_totals(store, log_records(store, "event", opts, today))
    return {"rfi": {"open": rt["open"], "overdue": rt["overdue"],
                    "total": rt["total"]},
            "submittal": {"open": st["open"], "overdue": st["overdue"],
                          "total": st["total"]},
            "co": {"open": ct["open"], "overdue": 0, "total": ct["total"],
                   "pending": ct["pending"]}}


# ---------------------------------------------------------------- weather
def _flags(rain, d, threshold_in, workdays):
    """Default (tracked, claimed) for a day: tracked = rain >= threshold;
    claimed = tracked on a workday."""
    tracked = rain is not None and _c2(rain) >= _c2(threshold_in)
    return tracked, bool(tracked and d.weekday() in workdays)


def weather_days(rows, threshold_in=0.5, workdays=WORKDAYS):
    """History rows ({"date", "rain_in"} dicts or (date, rain) pairs) ->
    rep["weather"]["days"]: one dict per date, sorted, with tracked
    (rain >= threshold) and claimed (tracked and a workday) defaults."""
    out = {}
    thr = float(threshold_in if threshold_in is not None else 0.5)
    for r in rows or []:
        if isinstance(r, dict):
            d, rain = r.get("date"), r.get("rain_in")
        else:
            d, rain = r[0], r[1]
        d = _day(d)
        if d is None:
            continue
        rain = _num(rain)
        tracked, claimed = _flags(rain, d, thr, workdays)
        out[d.isoformat()] = {"date": d.isoformat(),
                              "rain_in": None if rain is None
                              else _c2(rain),
                              "tracked": tracked, "claimed": claimed,
                              "note": ""}
    return [out[k] for k in sorted(out)]


def merge_weather(old_days, new_rows, threshold_in=0.5, workdays=WORKDAYS,
                  old_threshold=None):
    """Re-pulled history merged into the stored days: rain comes from the
    new rows, the user's choices stay. A day counts as edited when it has
    "edited": True (the editor sets it) or its tracked/claimed differ from
    the default for its stored rain (at old_threshold, default the same
    threshold); its notes always stay. Stored days the new pull doesn't
    cover are kept.

    A rain amount the PM typed ("source": "typed") is never replaced: the
    day keeps its rain_in and source, the downloaded amount is kept next
    to it as "download_in" (shown in the weather log), and its default
    tracked / claimed follow the typed amount."""
    thr_old = threshold_in if old_threshold is None else old_threshold
    new = {d["date"]: d for d in weather_days(new_rows, threshold_in,
                                              workdays)}
    for o in old_days or []:
        d = _day(o.get("date"))
        if d is None:
            continue
        k = d.isoformat()
        n = new.get(k)
        if n is None:
            new[k] = dict(o, date=k)
            continue
        if o.get("source") == "typed":
            typed = _num(o.get("rain_in"))
            n["download_in"] = n.get("rain_in")
            n["rain_in"] = None if typed is None else _c2(typed)
            n["source"] = "typed"
            n["tracked"], n["claimed"] = _flags(typed, d,
                                                float(threshold_in),
                                                workdays)
        default = _flags(_num(o.get("rain_in")), d, float(thr_old),
                         workdays)
        mine = (bool(o.get("tracked")), bool(o.get("claimed")))
        if o.get("edited") or mine != default:
            n["tracked"], n["claimed"] = mine
            n["edited"] = True
        if o.get("note"):
            n["note"] = o["note"]
        lost = _lost_claim(o, n, mine, d, float(thr_old), workdays)
        if lost:
            n["tracked"], n["claimed"] = mine
            n["edited"] = True
            n["note"] = (f"{n['note']} - {lost}" if n.get("note") and
                         lost not in n["note"] else n.get("note") or lost)
    return [new[k] for k in sorted(new)]


def _lost_claim(o, n, mine, d, thr_old, workdays):
    """A day claimed before that a re-pull with LESS rain would un-claim
    (a revised download - at the old threshold it wouldn't be claimed
    either - not a threshold change or the PM's untick): the claim stays
    and this note says why, so it never drops out silently. "" when
    nothing would be lost."""
    if o.get("source") == "typed" or not mine[1] or n.get("claimed"):
        return ""
    was, now = _num(o.get("rain_in")), _num(n.get("rain_in"))
    if was is None or (now is not None and _c2(now) >= _c2(was)):
        return ""
    if _flags(now, d, thr_old, workdays)[1]:
        return ""                           # the threshold moved, not rain
    now_s = "no data" if now is None else f"{_c2(now):.2f} in"
    return (f"Kept as claimed: re-pulled rain {now_s} (was {_c2(was):.2f} in) - "
            "check and untick if not a weather day")


def typed_rain_notes(weather):
    """One line per day whose rain the PM typed over a different downloaded
    amount: "10/06/2026: typed 1.25 in (download 0.10 in)"."""
    out = []
    for d in sorted(_wdays(weather), key=lambda d: str(d.get("date"))):
        if d.get("source") != "typed":
            continue
        typed, dl = _num(d.get("rain_in")), _num(d.get("download_in"))
        if typed is None or dl is None or _c2(typed) == _c2(dl):
            continue
        out.append(f"{_mdy(d.get('date'))}: typed {_c2(typed):.2f} in "
                   f"(download {_c2(dl):.2f} in)")
    return out


def weather_counts(weather):
    """(impacted, claimed) - the one pair page 1, the weather log, the gap
    line and the schedule block all print. With a per-day list they are
    its totals (a stale stored or typed total never wins); without one
    (no history, the PM keeps the count elsewhere) the stored totals."""
    if isinstance(weather, list):
        weather = {"days": weather}
    weather = weather or {}
    if _wdays(weather):
        tot = weather_totals(weather)
        return tot["impacted"], tot["claimed"]
    return _int(weather.get("impacted")), _int(weather.get("claimed"))


def _wdays(weather):
    if isinstance(weather, list):
        return weather
    return (weather or {}).get("days") or []


MONTH_HEAD = {9: "Sept"}


def _month_iter(first, last):
    y, m = first.year, first.month
    while (y, m) <= (last.year, last.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def weather_totals(weather):
    """{"impacted", "claimed", "tracked", "rain_in", "project_days",
    "first", "last", "months": [{"month": "2026-05", "label", "year",
    "tracked", "claimed", "actual", "rain_in"}]}.
    Tracked = tracked but not claimed (blue); Claimed (green); Actual =
    tracked or claimed. Page 1: IMPACTED = Actual total, CLAIMED = Claimed
    total."""
    days = [d for d in _wdays(weather) if _day(d.get("date"))]
    days.sort(key=lambda d: _day(d["date"]))
    if not days:
        return {"impacted": 0, "claimed": 0, "tracked": 0, "rain_in": 0.0,
                "project_days": 0, "first": None, "last": None,
                "months": []}
    first, last = _day(days[0]["date"]), _day(days[-1]["date"])
    months = {}
    for y, m in _month_iter(first, last):
        months[(y, m)] = {"month": f"{y:04d}-{m:02d}", "year": y,
                          "label": MONTH_HEAD.get(m, calendar.month_name[m]),
                          "tracked": 0, "claimed": 0, "actual": 0,
                          "rain_in": 0.0}
    for d in days:
        dd = _day(d["date"])
        mo = months[(dd.year, dd.month)]
        mo["rain_in"] = _c2(mo["rain_in"] + (_num(d.get("rain_in")) or 0))
        t, c = bool(d.get("tracked")), bool(d.get("claimed"))
        mo["claimed"] += c
        mo["tracked"] += t and not c
        mo["actual"] += t or c
    ms = list(months.values())
    return {"impacted": sum(m["actual"] for m in ms),
            "claimed": sum(m["claimed"] for m in ms),
            "tracked": sum(m["tracked"] for m in ms),
            "rain_in": _c2(sum(m["rain_in"] for m in ms)),
            "project_days": (last - first).days + 1,
            "first": first.isoformat(), "last": last.isoformat(),
            "months": ms}


def weather_gap_line(weather):
    """Option (e): when impacted != claimed, one line explaining the gap:
    "<I> impacted vs <C> claimed: <n1> fell on non-work days, <n2> were
    under the <t> in. threshold[, <n3> other: <notes>]." with
    n1 + n2 + n3 == I - C. None when they are equal. A typed
    weather["gap_note"] replaces the line (it is editable before export)."""
    if isinstance(weather, list):
        weather = {"days": weather}
    weather = weather or {}
    days = _wdays(weather)
    thr = _num(weather.get("threshold_in"))
    thr = 0.5 if thr is None else thr
    workdays = weather.get("workdays") or WORKDAYS
    imp, cl = weather_counts(weather)
    if imp == cl:
        return None
    note = (weather.get("gap_note") or "").strip()
    if note:
        return note
    if imp < cl:
        return f"{imp} impacted vs {cl} claimed: see the attached log."
    n1 = n2 = n3 = 0
    notes = []
    for d in days:
        dd = _day(d.get("date"))
        if not dd or not d.get("tracked") or d.get("claimed"):
            continue
        rain = _num(d.get("rain_in"))
        if dd.weekday() not in workdays:
            n1 += 1
        elif rain is None or _c2(rain) < _c2(thr):
            n2 += 1
        else:
            n3 += 1
            t = (d.get("note") or "").strip()
            if t and t not in notes:
                notes.append(t)
    if not days:
        n3 = imp - cl
    line = (f"{imp} impacted vs {cl} claimed: {n1} fell on non-work days, "
            f"{n2} were under the {_c2(thr):.2f} in. threshold")
    if n3:
        line += f", {n3} other: {'; '.join(notes) or 'see log'}"
    return line + "."


# weather log geometry (portrait), measured from the form
WX0 = 17.8
W_DAY, W_RAIN = 55.0, 37.7
W_MONTH = W_DAY + W_RAIN
W_TITLE = (41.5, 53.8)
W_HEAD = (53.8, 66.5)
W_ROW0, W_ROWH = 66.5, 12.6
W_SUM_X = [229.8, 309.8, 389.8, 469.8, 549.8]
W_SUM_Y0, W_SUM_H = 494.8, 11.0


def add_weather_log(doc, head, weather, opts=None):
    """Inclement weather log / rainfall records (portrait, spec 1.5): up to
    six month columns a page (more months -> another page), day cells
    yellow, tracked days blue, claimed days green, a TOTAL row, the legend
    and the Tracked / Claimed / Actual summary."""
    weather = weather or {}
    days = {}
    for d in _wdays(weather):
        dd = _day(d.get("date"))
        if dd:
            days[dd] = d
    tot = weather_totals(weather)
    if tot["months"]:
        months = [(m["year"], int(m["month"][5:])) for m in tot["months"]]
        first, last = _day(tot["first"]), _day(tot["last"])
    else:
        rd = _report_date(head)
        months, first, last = [(rd.year, rd.month)], None, None
    by_month = {(m["year"], int(m["month"][5:])): m for m in tot["months"]}
    typed = typed_rain_notes(weather)
    typed_days = {d.get("date") for d in _wdays(weather)
                  if d.get("source") == "typed" and
                  _num(d.get("download_in")) is not None and
                  _num(d.get("rain_in")) is not None and
                  _c2(_num(d["rain_in"])) !=
                  _c2(_num(d["download_in"]))}
    chunks = [months[i:i + 6] for i in range(0, len(months), 6)]
    for ci, chunk in enumerate(chunks):
        page = doc.new_page(width=PW, height=PH)
        is_last = ci == len(chunks) - 1
        gw = W_MONTH * len(chunk)
        x1 = WX0 + gw
        # title bar (at least three months wide so the title fits)
        bw = max(gw, W_MONTH * 3)
        _box(page, (WX0, W_TITLE[0], WX0 + bw, W_TITLE[1]), fill=TITLE_BLUE,
             color=None)
        names = [calendar.month_name[m] for _y, m in chunk]
        title = "Rainfall Records" + (
            f" ({names[0]} to {names[-1]})" if len(names) > 1
            else f" ({names[0]})")
        years = sorted({y for y, _m in chunk})
        year = f"Year: {years[0]}" + (f"-{years[-1]}" if len(years) > 1
                                       else "")
        _put(page, WX0 + bw * 0.345, 50.6, title, 7.5, "hebo", WHITE,
             "center")
        _put(page, WX0 + bw * 0.757, 50.6, year, 7.5, "hebo", WHITE,
             "center")
        for i, (y, m) in enumerate(chunk):
            x = WX0 + W_MONTH * i
            _box(page, (x, W_HEAD[0], x + W_DAY, W_HEAD[1]), fill=DAY_YELLOW)
            _box(page, (x + W_DAY, W_HEAD[0], x + W_MONTH, W_HEAD[1]),
                 fill=DAY_YELLOW)
            _put(page, x + W_DAY / 2, 62.6, MONTH_HEAD.get(
                m, calendar.month_name[m]), 7, "hebo", align="center")
            _put(page, x + W_DAY + W_RAIN / 2, 62.6, "Rainfall", 6.5, "hebo",
                 align="center")
            for dn in range(1, calendar.monthrange(y, m)[1] + 1):
                d = date(y, m, dn)
                rec = days.get(d)
                if rec is None and not (first and first <= d <= last):
                    continue        # before the job's first / after its last
                ry = W_ROW0 + W_ROWH * (dn - 1)
                _box(page, (x, ry, x + W_DAY, ry + W_ROWH), fill=DAY_YELLOW)
                _put(page, x + 2.2, ry + 9, f"{d:%a}, {dn:02d}", 6.5, "hebo")
                fill = WHITE
                if rec and rec.get("claimed"):
                    fill = CLAIMED_GREEN
                elif rec and rec.get("tracked"):
                    fill = TRACKED_BLUE
                _box(page, (x + W_DAY, ry, x + W_MONTH, ry + W_ROWH),
                     fill=fill)
                rain = _num(rec.get("rain_in")) if rec else None
                if rain is not None:
                    _put(page, x + W_MONTH - 2.2, ry + 9, f"{_c2(rain):.2f}", 6.5,
                         align="right")
                if rec and rec.get("date") in typed_days:
                    _put(page, x + W_DAY + 2.0, ry + 9, "*", 6.5)
            mo = by_month.get((y, m))
            _put(page, x + W_MONTH - 2.2, 466.5,
                 f"{_c2(mo['rain_in']):.2f}" if mo else "", 6.5, align="right")
        _box(page, (WX0, W_HEAD[0], x1, W_ROW0 + 31 * W_ROWH), fill=None,
             width=0.75)
        _put(page, WX0 + 4, 466.5, "TOTAL", 6.5, "hebo")
        # legend
        _box(page, (28, 495.5, 58, 502.5), fill=TRACKED_BLUE, color=None)
        _put(page, 64, 501.8, "Tracked", 6.5)
        _box(page, (28, 507.5, 58, 514.5), fill=CLAIMED_GREEN, color=None)
        _put(page, 64, 513.8, "Claimed Rain Days", 6.5)
        # summary
        sx, sy, sh = W_SUM_X, W_SUM_Y0, W_SUM_H

        def srow(r, label, vals, label_fill=DAY_YELLOW, val_fill=WHITE,
                 bold_vals=False):
            y0 = sy + sh * r
            _box(page, (sx[0], y0, sx[1], y0 + sh), fill=label_fill)
            _put(page, sx[0] + 3, y0 + 8, label, 6.5, "hebo")
            for k, v in enumerate(vals):
                _box(page, (sx[k + 1], y0, sx[k + 2], y0 + sh), fill=val_fill)
                if bold_vals:
                    _put(page, (sx[k + 1] + sx[k + 2]) / 2, y0 + 8, v, 6.5,
                         "hebo", align="center")
                else:
                    _put(page, sx[k + 2] - 3, y0 + 8, v, 6.5, align="right")

        srow(0, "", ["Tracked", "Claimed", "Actual"], WHITE, CLAIMED_GREEN,
             True)
        r = 1
        for y, m in chunk:
            mo = by_month.get((y, m)) or {"tracked": 0, "claimed": 0,
                                          "actual": 0}
            srow(r, MONTH_HEAD.get(m, calendar.month_name[m]),
                 [f"{_c2(mo['tracked']):.2f}", f"{_c2(mo['claimed']):.2f}",
                  f"{_c2(mo['actual']):.2f}"])
            r += 1
        if is_last:
            label = "Total" if len(chunks) == 1 else "Total (all months)"
            srow(r, label, [f"{_c2(tot['tracked']):.2f}", f"{_c2(tot['claimed']):.2f}",
                            f"{_c2(tot['impacted']):.2f}"])
            srow(r + 1, "TOTAL PROJECT DAYS",
                 ["", "", str(tot["project_days"])])
        else:
            sub = [by_month.get(k) for k in chunk if by_month.get(k)]
            srow(r, "Subtotal",
                 [f"{_c2(sum(s['tracked'] for s in sub)):.2f}",
                  f"{_c2(sum(s['claimed'] for s in sub)):.2f}",
                  f"{_c2(sum(s['actual'] for s in sub)):.2f}"])
        if not tot["months"]:
            _put(page, WX0, 485, "No rainfall records yet.", 7)
        if is_last and typed:
            _typed_notes(page, typed)
    return {"pages": len(chunks), "totals": tot}


TYPED_Y0, TYPED_PITCH = 622.0, 8.6


def _typed_notes(page, lines):
    """Under the summary: the days whose rainfall the PM typed over the
    downloaded amount, both values (* in the day's rainfall cell)."""
    _put(page, 28, TYPED_Y0, "* Rainfall typed by the PM (the typed amount "
         "is used; the downloaded amount is shown for reference):", 6.5,
         "hebo")
    cols = 3
    room = int((PH - 40 - TYPED_Y0) // TYPED_PITCH) - 1      # rows
    shown = lines if len(lines) <= cols * room else \
        lines[:cols * (room - 1)]
    per = math.ceil(len(shown) / cols) if shown else 0
    colw = (PW - 56) / cols
    for i, ln in enumerate(shown):
        c, r = divmod(i, max(per, 1))
        _put(page, 28 + c * colw, TYPED_Y0 + TYPED_PITCH * (r + 1),
             _clip(ln, 6.5, "helv", colw - 6), 6.5)
    if len(shown) < len(lines):
        _put(page, 28, TYPED_Y0 + TYPED_PITCH * (per + 1),
             f"... and {len(lines) - len(shown)} more typed days.", 6.5)


# --------------------------------------------------------------- forecast
FC_COLS = [("Day", 60), ("Date", 110), ("Sky", 175), ("High / Low (F)", 270),
           ("Rain chance", 345), ("Rain (in.)", 410), ("Wind (mph)", 470),
           ("Work day?", 530)]


FC_BOX = (36, 36, PW - 36, PH - 36)      # an attached forecast, fitted


def _fc_attached(forecast):
    path = forecast.get("attach_path") or forecast.get("attach_ref")
    if isinstance(path, dict):
        path = path.get("path")
    return path if isinstance(path, str) and os.path.isfile(path) else None


def add_forecast_page(doc, head, forecast, opts=None):
    """10-day forecast page (portrait, spec 1.6): a table (Day, Date, Sky,
    High/Low, Rain chance, Rain, Wind, Work day? -> Weekend / At risk /
    Yes), or, in "attach" mode, the attached screenshot or PDF page placed
    fit-to-page (forecast["attach_path"], resolved by the caller)."""
    forecast = forecast or {}
    opts = opts or {}
    page = doc.new_page(width=PW, height=PH)
    box = fitz.Rect(*FC_BOX)
    if forecast.get("mode") == "attach":
        path = _fc_attached(forecast)
        if path:
            try:
                if path.lower().endswith(".pdf"):
                    with fitz.open(path) as src:
                        # vectors, or an image when its fonts aren't
                        # embedded (see place_pdf_page)
                        place_pdf_page(page, box, src,
                                       int(forecast.get("attach_page")
                                           or 0), keep_proportion=True)
                else:
                    page.insert_image(box, filename=path,
                                      keep_proportion=True)
                return {"pages": 1, "totals": {"mode": "attach", "days": 0,
                                               "at_risk": 0}}
            except Exception:
                pass            # unreadable attachment: print the table
    thr = _num(forecast.get("threshold_in"))
    if thr is None:
        thr = _num(opts.get("threshold_in"))
    thr = 0.5 if thr is None else thr
    rows = forecast.get("rows") or []
    _put(page, PW / 2, 60, "10-Day Weather Forecast", 16, "hebo",
         align="center")
    place = forecast.get("place") or ((head or {}).get("project") or {}).get(
        "location") or ""
    as_of = forecast.get("as_of") or _report_date(head).isoformat()
    src = forecast.get("source") or "Open-Meteo"
    sub = " - ".join(x for x in (place, f"as of {_mdy(as_of)}",
                                 f"source: {src}") if x)
    _put(page, PW / 2, 75.5, _clip(sub, 8, "helv", PW - 80), 8, color=MUTED,
         align="center")
    y = 98
    _box(page, (40, y, PW - 40, y + 18), fill=BAR_GREY, color=None)
    for label, x in FC_COLS:
        _put(page, x, y + 12, label, 7.5, "hebo")
    y += 18
    at_risk = 0
    if not rows:
        # G22: offline with nothing typed or attached - say so plainly
        _put(page, 60, y + 16, "Not available offline - type the forecast "
             "rows or attach a screenshot (online: check the job "
             "location).", 8)
    for i, r in enumerate(rows):
        d = _day(r.get("date"))
        if i % 2:
            _box(page, (40, y, PW - 40, y + 22), fill=STRIPE, color=None)
        hi, lo = _num(r.get("high")), _num(r.get("low"))
        hl = f"{round(hi)} / {round(lo)}" if hi is not None and \
            lo is not None else (f"{round(hi)}" if hi is not None else "")
        chance = _num(r.get("rain_chance"))
        rain = _num(r.get("rain_in"))
        wind = _num(r.get("wind"))
        holidays = {str(h)[:10] for h in forecast.get("holidays") or ()}
        if d and d.isoformat() in holidays:
            work, color = "Holiday", BLACK
        elif d and d.weekday() >= 5:
            work, color = "Weekend", BLACK
        elif rain is not None and _c2(rain) >= _c2(thr):
            work, color = "At risk", RED
            at_risk += 1
        else:
            work, color = "Yes", BLACK
        vals = [f"{d:%a}" if d else "", _mdy(r.get("date")),
                _clip(r.get("sky") or "", 7.5, "helv", 90), hl,
                f"{round(chance)}%" if chance is not None else "",
                f"{_c2(rain):.2f}" if rain is not None else "",
                f"{round(wind)}" if wind is not None else ""]
        for (label, x), v in zip(FC_COLS, vals):
            _put(page, x, y + 13.5, v, 7.5)
        _put(page, FC_COLS[-1][1], y + 13.5, work, 7.5, color=color)
        y += 22
        if y > PH - 60:
            break
    return {"pages": 1, "totals": {"mode": "table", "days": len(rows),
                                   "at_risk": at_risk}}
