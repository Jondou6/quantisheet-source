"""Everyday Acrobat-style document tools (no Qt here, so easy to test):
OCR to a searchable PDF, export to Word / Excel / text / images, combine
files, password protection, headers & footers, search-and-redact patterns,
form field detection, flattening and file-size reduction."""
from . import safeio
import datetime
import io
import os
import re
import zipfile
from xml.sax.saxutils import escape

import fitz

from . import annotate, ocr as ocr_mod


# ---- OCR ---------------------------------------------------------------------

def tessdata_dir():
    """Tesseract's language folder, or None if Tesseract isn't installed."""
    if os.getenv("TESSDATA_PREFIX"):
        return os.environ["TESSDATA_PREFIX"]
    exe = ocr_mod.find_tesseract()
    if not exe:
        return None
    for cand in (os.path.join(os.path.dirname(exe), "tessdata"),
                 os.path.join(os.path.dirname(os.path.dirname(exe)), "share",
                              "tessdata"),
                 "/usr/share/tesseract-ocr/5/tessdata",
                 "/usr/share/tesseract-ocr/4.00/tessdata",
                 "/opt/homebrew/share/tessdata", "/usr/local/share/tessdata"):
        if os.path.isdir(cand):
            return cand
    try:
        return fitz.get_tessdata()
    except Exception:
        return None


def page_has_text(page, min_chars=10):
    """True if the page has a real text layer. A page that uses no fonts
    can't have one, and finding that out only reads its resource list; the
    text itself is read only for pages that do use fonts and are light.
    Reading every word of a big vector sheet took ~25 ms a page - 8 s
    on a 309-sheet plant set, with the window frozen (Jon, Oct 19)."""
    try:
        if not page.get_fonts(full=False):
            return False
    except Exception:                                  # noqa: BLE001
        pass
    # fonts in use: a drawing or a typed page. Only a page with a tiny
    # content stream (a scan with a stamp, say) is worth reading.
    size = 0
    try:
        doc = page.parent
        for x in page.get_contents():      # stored bytes, not decompressed
            size += len(doc.xref_stream_raw(x) or b"")
    except Exception:                                  # noqa: BLE001
        size = 0
    if size > 20_000:
        return True
    return len(page.get_text().strip()) >= min_chars


def pages_needing_ocr(doc):
    """Pages with no real text layer (scans)."""
    return [i for i, p in enumerate(doc) if not page_has_text(p)]


OCR_MIN_CONF = 60          # Tesseract word confidence (0-100) to keep
TILE_PX = 2000             # tiles this many pixels square, so a 36x24 sheet
TILE_OVERLAP = 60          # never needs one ~1 GB image


def ocr_dpi(page):
    """300 dpi up to 11x17; 200 dpi for bigger sheets (text on a 24x36
    sheet is big enough, and it's half the pixels)."""
    w, h = page.rect.width / 72, page.rect.height / 72
    return 300 if max(w, h) <= 17.5 else 200


def is_photo(page):
    """A photo or rendering (lots of mid-grey), which OCR only turns into
    junk text - not a scanned drawing or document (mostly paper and ink)."""
    try:
        import numpy as np
        pix = page.get_pixmap(dpi=40, colorspace=fitz.csGRAY, alpha=False,
                              annots=False)
        g = np.frombuffer(pix.samples, dtype=np.uint8)
        if g.size == 0:
            return False
        mid = np.count_nonzero((g > 60) & (g < 200)) / g.size
        return mid > 0.45
    except Exception:
        return False


def _tess_tile(exe, png, language, tessdata):
    """[(x0, y0, x1, y1, text, conf)] in the tile's pixels."""
    import subprocess
    env = dict(os.environ, OMP_THREAD_LIMIT="1")
    if tessdata:
        env["TESSDATA_PREFIX"] = tessdata
    out = subprocess.run([exe, png, "stdout", "-l", language, "--psm", "11",
                          "tsv"], capture_output=True, timeout=600, env=env,
                         creationflags=getattr(subprocess,
                                               "CREATE_NO_WINDOW", 0))
    if out.returncode != 0:
        raise RuntimeError("tesseract failed: " +
                           out.stderr.decode("utf-8", "ignore")[:300])
    words = []
    for line in out.stdout.decode("utf-8", "ignore").splitlines()[1:]:
        cols = line.split("\t")
        if len(cols) < 12 or not cols[11].strip():
            continue
        try:
            left, top, w, h = (int(c) for c in cols[6:10])
            conf = float(cols[10])
        except ValueError:
            continue
        words.append((left, top, left + w, top + h, cols[11].strip(), conf))
    return words


def _plausible(text):
    """Drop OCR noise: a word needs mostly letters/digits."""
    t = text.strip()
    if not t:
        return False
    good = sum(ch.isalnum() for ch in t)
    if len(t) == 1:
        return t.isalnum()
    return good / len(t) >= 0.6


def ocr_page_words(page, dpi=None, language="eng", workers=None,
                   min_conf=OCR_MIN_CONF):
    """Words on an (unrotated) page, OCR'd in tiles on several cores:
    [(Rect in page points, text)] with confidence >= min_conf."""
    import tempfile
    from concurrent.futures import ThreadPoolExecutor
    exe = ocr_mod.find_tesseract()
    if not exe:
        raise ocr_mod.OCRUnavailable("Tesseract is not installed.")
    tess = tessdata_dir()
    dpi = dpi or ocr_dpi(page)
    zoom = dpi / 72.0
    tile = TILE_PX / zoom                       # tile size in page points
    ov = TILE_OVERLAP / zoom
    R = page.rect
    jobs = []
    tmpdir = tempfile.mkdtemp(prefix="pdfs_ocr_")
    y = R.y0
    k = 0
    while y < R.y1 - 1:
        x = R.x0
        while x < R.x1 - 1:
            core = fitz.Rect(x, y, min(x + tile, R.x1), min(y + tile, R.y1))
            clip = fitz.Rect(core.x0 - ov, core.y0 - ov, core.x1 + ov,
                             core.y1 + ov) & R
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip,
                                  colorspace=fitz.csGRAY, alpha=False,
                                  annots=False)
            png = os.path.join(tmpdir, f"t{k}.png")
            pix.save(png)
            del pix
            jobs.append((png, clip, core))
            k += 1
            x += tile
        y += tile
    workers = workers or max(1, min(4, (os.cpu_count() or 2)))
    out = []
    try:
        with ThreadPoolExecutor(workers) as ex:
            results = list(ex.map(lambda j: _tess_tile(exe, j[0], language,
                                                       tess), jobs))
        for (png, clip, core), words in zip(jobs, results):
            for x0, y0, x1, y1, text, conf in words:
                if conf < min_conf or not _plausible(text):
                    continue
                r = fitz.Rect(clip.x0 + x0 / zoom, clip.y0 + y0 / zoom,
                              clip.x0 + x1 / zoom, clip.y0 + y1 / zoom)
                c = fitz.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
                if core.contains(c):            # overlap: keep once
                    out.append((r, text))
    finally:
        for png, _, _ in jobs:
            try:
                os.remove(png)
            except OSError:
                pass
        try:
            os.rmdir(tmpdir)
        except OSError:
            pass
    return out


def make_searchable(doc, pages=None, dpi=None, language="eng", progress=None,
                    skipped=None):
    """Give scanned pages an invisible text layer so they can be searched,
    selected and copied. Returns the number of pages processed.

    The page itself is left as it is - its markups, measurements, form
    fields and links stay exactly where they were - and the recognised
    words are written over it as invisible text. Sheets are read in tiles
    on several cores (a 36x24 sheet needs ~100 MB, not ~1 GB); words below
    confidence 60 and non-words are dropped; photo pages are skipped (OCR
    turns them into junk) and listed in `skipped` if given."""
    if not ocr_mod.find_tesseract():
        raise ocr_mod.OCRUnavailable(
            "Tesseract is not installed, so OCR isn't available. Install it "
            "from https://github.com/UB-Mannheim/tesseract/wiki (Windows) and "
            "restart QuantiSheet.")
    pages = pages_needing_ocr(doc) if pages is None else list(pages)
    done = 0
    for n, i in enumerate(pages):
        if progress and progress(n, len(pages)) is False:
            break
        page = doc[i]
        if is_photo(page):
            if skipped is not None:
                skipped.append(i)
            continue
        rot = page.rotation
        page.set_rotation(0)
        try:
            words = ocr_page_words(page, dpi, language)
            add_words(page, words)
        finally:
            page.set_rotation(rot)
        done += 1
    return done


def add_words(page, words):
    """Write [(Rect, text)] onto `page` as invisible text, each word sized
    to cover its box."""
    font = fitz.Font("helv")
    tw = fitz.TextWriter(page.rect)
    n = 0
    for r, text in words:
        text = "".join(ch if ord(ch) < 256 else "?" for ch in text)
        if not text.strip() or r.height <= 0:
            continue
        size = r.height * 0.85
        width = font.text_length(text, fontsize=size)
        if width > 0:
            size = max(r.height * 0.5, min(r.height * 1.2,
                                           size * r.width / width))
        try:
            tw.append((r.x0, r.y1 - r.height * 0.2), text, font=font,
                      fontsize=size)
            n += 1
        except Exception:
            continue
    if n:
        tw.write_text(page, render_mode=3)
    return n


def add_text_layer(page, ocr_page):
    """Write the words of `ocr_page` (an OCR'd image of `page`, unrotated)
    onto `page` as invisible text, each sized to cover its word."""
    words = ocr_page.get_text("words")
    if not words:
        return 0
    sx = page.rect.width / ocr_page.rect.width
    sy = page.rect.height / ocr_page.rect.height
    font = fitz.Font("helv")
    tw = fitz.TextWriter(page.rect)
    n = 0
    for x0, y0, x1, y1, text, *_ in words:
        r = fitz.Rect(x0 * sx, y0 * sy, x1 * sx, y1 * sy)
        text = "".join(ch if ord(ch) < 256 else "?" for ch in text)
        if not text.strip() or r.height <= 0:
            continue
        size = r.height * 0.85
        width = font.text_length(text, fontsize=size)
        if width > 0:
            # match the word's width so selections and highlights line up
            size = max(r.height * 0.5, min(r.height * 1.2,
                                           size * r.width / width))
        try:
            tw.append((r.x0, r.y1 - r.height * 0.2), text, font=font,
                      fontsize=size)
            n += 1
        except Exception:
            continue
    if n:
        tw.write_text(page, render_mode=3)
    return n


# ---- export ------------------------------------------------------------------

def export_text(doc, path):
    with open(path, "w", encoding="utf-8") as f:
        for i, page in enumerate(doc):
            f.write(f"--- Page {i + 1} ---\n")
            f.write(page.get_text())
            f.write("\n")
    return path


def export_images(doc, folder, fmt="png", dpi=150, pages=None):
    os.makedirs(folder, exist_ok=True)
    base = os.path.splitext(os.path.basename(doc.name or "document"))[0]
    out = []
    for i in (range(doc.page_count) if pages is None else pages):
        pix = doc[i].get_pixmap(dpi=dpi, alpha=False)
        p = os.path.join(folder, f"{base}_page{i + 1:03d}.{fmt}")
        if fmt in ("jpg", "jpeg"):
            pix.save(p, jpg_quality=90)
        else:
            pix.save(p)
        out.append(p)
    return out


def _docx_run(text, size=None, bold=False):
    props = ""
    if bold or size:
        props = "<w:rPr>" + ("<w:b/>" if bold else "") + \
            (f'<w:sz w:val="{int(size * 2)}"/>' if size else "") + "</w:rPr>"
    return (f'<w:r>{props}<w:t xml:space="preserve">{escape(text)}</w:t>'
            "</w:r>")


TABLE_MAX_AREA = 17 * 11 * 72 * 72 * 1.05     # up to tabloid (11 x 17 in)


def export_word(doc, path):
    """Word (.docx) with the document's text: one paragraph per text block,
    keeping font size and bold, a page break between pages. Layout,
    columns and pictures are not reproduced."""
    body = []
    for pno, page in enumerate(doc):
        if pno:
            body.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            runs = []
            for line in block["lines"]:
                for s in line["spans"]:
                    if s["text"].strip():
                        runs.append(_docx_run(
                            s["text"], round(s["size"]),
                            bool(s["flags"] & 16) or "Bold" in s["font"]))
                runs.append(_docx_run(" "))
            if runs:
                body.append("<w:p>" + "".join(runs) + "</w:p>")
        # full-size drawing sheets: table detection crawls on CAD linework
        # (minutes per set) and the Word copy is text only anyway
        if page.rect.width * page.rect.height <= TABLE_MAX_AREA:
            for t in _tables(page):
                body.append(_docx_table(t))
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/'
        'wordprocessingml/2006/main"><w:body>' + "".join(body) +
        "<w:sectPr/></w:body></w:document>")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://'
                   'schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.'
                   'openxmlformats-package.relationships+xml"/><Default '
                   'Extension="xml" ContentType="application/xml"/><Override '
                   'PartName="/word/document.xml" ContentType="application/'
                   'vnd.openxmlformats-officedocument.wordprocessingml.'
                   'document.main+xml"/></Types>')
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8"?><Relationships '
                   'xmlns="http://schemas.openxmlformats.org/package/2006/'
                   'relationships"><Relationship Id="rId1" Type="http://'
                   'schemas.openxmlformats.org/officeDocument/2006/'
                   'relationships/officeDocument" Target="word/document.xml"/>'
                   '</Relationships>')
        z.writestr("word/document.xml", document)
    return path


def _docx_table(rows):
    out = ['<w:tbl><w:tblPr><w:tblBorders>' +
           "".join(f'<w:{s} w:val="single" w:sz="4"/>' for s in
                   ("top", "left", "bottom", "right", "insideH", "insideV")) +
           "</w:tblBorders></w:tblPr>"]
    for row in rows:
        out.append("<w:tr>")
        for cell in row:
            out.append("<w:tc><w:p>" + _docx_run(str(cell or "")) +
                       "</w:p></w:tc>")
        out.append("</w:tr>")
    out.append("</w:tbl><w:p/>")
    return "".join(out)


def _has_rules(page, need=3):
    """Cheap check for a ruled grid. find_tables() finds tables from
    vector lines, so a page without lines both across and down has none to
    find. Text underlines and a single border are not enough. Skipping
    those pages makes exporting long text documents (spec books) many
    times faster."""
    def xy(p):
        return (p[0], p[1]) if isinstance(p, (tuple, list)) else (p.x, p.y)
    try:
        h = v = 0
        for d in page.get_cdrawings():
            for it in d.get("items", ()):
                op = it[0]
                if op == "l":
                    (x0, y0), (x1, y1) = xy(it[1]), xy(it[2])
                    if abs(y1 - y0) < 1 and abs(x1 - x0) > 5:
                        h += 1
                    elif abs(x1 - x0) < 1 and abs(y1 - y0) > 5:
                        v += 1
                elif op in ("re", "qu"):
                    h += 2
                    v += 2
                if h > need and v > need:
                    return True
        return False
    except Exception:
        return True


def _tables(page):
    if not _has_rules(page):
        return []
    try:
        found = page.find_tables()
    except Exception:
        return []
    out = []
    for t in found.tables:
        rows = [[("" if c is None else str(c).replace("\n", " ")) for c in r]
                for r in t.extract()]
        if rows and any(any(c for c in r) for r in rows):
            out.append(rows)
    return out


def _col(n):
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def _xlsx_sheet(rows):
    xml = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<worksheet xmlns="http://schemas.openxmlformats.org/'
           'spreadsheetml/2006/main"><sheetData>']
    for r, row in enumerate(rows, 1):
        xml.append(f'<row r="{r}">')
        for c, value in enumerate(row):
            ref = f"{_col(c)}{r}"
            v = str(value or "").strip()
            num = v.replace(",", "").replace("$", "")
            if re.fullmatch(r"-?\d+(\.\d+)?", num):
                xml.append(f'<c r="{ref}"><v>{num}</v></c>')
            elif v:
                xml.append(f'<c r="{ref}" t="inlineStr"><is><t xml:space='
                           f'"preserve">{escape(v)}</t></is></c>')
        xml.append("</row>")
    xml.append("</sheetData></worksheet>")
    return "".join(xml)


def write_xlsx(path, sheets):
    """sheets: [(name, rows)] -> a basic .xlsx Excel can open."""
    sheets = sheets or [("Sheet1", [["(no data)"]])]
    names = []
    for name, _ in sheets:
        n = re.sub(r"[\[\]:*?/\\]", "", name)[:31] or "Sheet"
        while n in names:
            n = n[:28] + f"_{len(names)}"
        names.append(n)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http:'
                   '//schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.'
                   'openxmlformats-package.relationships+xml"/><Default '
                   'Extension="xml" ContentType="application/xml"/><Override '
                   'PartName="/xl/workbook.xml" ContentType="application/vnd.'
                   'openxmlformats-officedocument.spreadsheetml.sheet.main+xml'
                   '"/>' + "".join(
                       f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" '
                       'ContentType="application/vnd.openxmlformats-'
                       'officedocument.spreadsheetml.worksheet+xml"/>'
                       for i in range(len(sheets))) + "</Types>")
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8"?><Relationships '
                   'xmlns="http://schemas.openxmlformats.org/package/2006/'
                   'relationships"><Relationship Id="rId1" Type="http://'
                   'schemas.openxmlformats.org/officeDocument/2006/'
                   'relationships/officeDocument" Target="xl/workbook.xml"/>'
                   '</Relationships>')
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="'
                   'http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/'
                   '2006/relationships"><sheets>' + "".join(
                       f'<sheet name="{escape(n)}" sheetId="{i + 1}" '
                       f'r:id="rId{i + 1}"/>' for i, n in enumerate(names)) +
                   "</sheets></workbook>")
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8"?><Relationships '
                   'xmlns="http://schemas.openxmlformats.org/package/2006/'
                   'relationships">' + "".join(
                       f'<Relationship Id="rId{i + 1}" Type="http://schemas.'
                       'openxmlformats.org/officeDocument/2006/relationships/'
                       f'worksheet" Target="worksheets/sheet{i + 1}.xml"/>'
                       for i in range(len(sheets))) + "</Relationships>")
        for i, (_, rows) in enumerate(sheets):
            z.writestr(f"xl/worksheets/sheet{i + 1}.xml", _xlsx_sheet(rows))
    return path


def export_excel(doc, path):
    """Excel (.xlsx): every table found in the PDF on its own sheet. If no
    tables are found, one sheet with the text, line by line."""
    sheets = []
    for pno, page in enumerate(doc):
        for n, rows in enumerate(_tables(page), 1):
            sheets.append((f"Page {pno + 1} Table {n}", rows))
    if not sheets:
        rows = []
        for pno, page in enumerate(doc):
            for line in page.get_text().splitlines():
                if line.strip():
                    rows.append([pno + 1, line])
        sheets = [("Text", [["Page", "Text"]] + rows)]
    write_xlsx(path, sheets)
    return len(sheets)


# ---- combine ------------------------------------------------------------------

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff")


def combine(paths, bookmarks=True):
    """A new document made of the given PDFs and images, in order, with a
    bookmark for each file."""
    out = fitz.open()
    toc = []
    for path in paths:
        start = out.page_count
        if path.lower().endswith(IMAGE_EXT):
            img = fitz.open(path)
            rect = img[0].rect
            img.close()
            page = out.new_page(width=rect.width, height=rect.height)
            page.insert_image(page.rect, filename=path)
        else:
            src = fitz.open(path)
            if src.needs_pass:
                src.close()
                raise ValueError(f"{os.path.basename(path)} is "
                                 "password-protected.")
            out.insert_pdf(src)
            from . import jobdata             # scales, prices, assemblies
            jobdata.copy_job(src, out, {k: start + k
                                        for k in range(src.page_count)})
            src.close()
        if bookmarks and out.page_count > start:
            toc.append([1, os.path.splitext(os.path.basename(path))[0],
                        start + 1])
    if bookmarks and toc:
        out.set_toc(toc)
    return out


# ---- security -----------------------------------------------------------------

def save_protected(doc, path, open_password="", owner_password="",
                   allow_print=True, allow_copy=True, allow_edit=True):
    """Save an AES-256 encrypted copy. `open_password` is needed to open
    it; `owner_password` controls the permissions."""
    if not open_password and not owner_password:
        raise ValueError("Enter at least one password.")
    def P(name, bit):
        return getattr(fitz, "PDF_PERM_" + name, 1 << bit)

    perm = P("ACCESSIBILITY", 9)
    if allow_print:
        perm |= P("PRINT", 2) | P("PRINT_HQ", 11)
    if allow_copy:
        perm |= P("COPY", 4)
    if allow_edit:
        perm |= P("MODIFY", 3) | P("ANNOTATE", 5) | P("FORM", 8) | \
            P("ASSEMBLE", 10)
    safeio.atomic_save(doc, path, garbage=1, deflate=True,
             encryption=fitz.PDF_ENCRYPT_AES_256,
             user_pw=open_password or None,
             owner_pw=owner_password or open_password, permissions=perm)
    return path


def save_unprotected(doc, path):
    safeio.atomic_save(doc, path, garbage=1, deflate=True, encryption=fitz.PDF_ENCRYPT_NONE)
    return path


# ---- headers, footers, page numbers ---------------------------------------------

POSITIONS = ("top_left", "top_center", "top_right",
             "bottom_left", "bottom_center", "bottom_right")


def _expand(text, n, total, start, filename):
    return (text.replace("{page}", str(n + start))
                .replace("{pages}", str(total + start - 1))
                .replace("{date}", datetime.date.today().isoformat())
                .replace("{file}", filename))


def header_footer(doc, texts, size=9, margin=24, color=(0, 0, 0),
                  pages=None, start=1):
    """Stamp text in page corners/centres.

    texts: {position: template}, positions as in POSITIONS. Templates may use
    {page}, {pages}, {date}, {file}. Text is drawn upright on rotated pages.
    """
    filename = os.path.basename(doc.name or "")
    pages = list(range(doc.page_count)) if pages is None else list(pages)
    total = len(pages)
    for n, i in enumerate(pages):
        page = doc[i]
        r = page.rect                                # as displayed
        for pos, tmpl in texts.items():
            if not tmpl or pos not in POSITIONS:
                continue
            text = _expand(tmpl, n, total, start, filename)
            w = fitz.get_text_length(text, fontsize=size)
            vert, horiz = pos.split("_")
            y = margin + size if vert == "top" else r.height - margin
            x = {"left": margin, "center": (r.width - w) / 2,
                 "right": r.width - margin - w}[horiz]
            pt = fitz.Point(x, y) * page.derotation_matrix
            page.insert_text(pt, text, fontsize=size, color=color,
                             rotate=page.rotation)
    return total


# ---- search & redact -------------------------------------------------------------

PATTERNS = {
    "Phone numbers": r"\(?\b\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
    "Email addresses": r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b",
    "SSNs": r"\b\d{3}-\d{2}-\d{4}\b",
    "Credit card numbers": r"\b(?:\d[ -]?){13,16}\b",
    "Dates": r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
}


def find_for_redaction(doc, text=None, pattern=None, whole_word=False,
                       case=False):
    """[(page, op rect)] for every match of plain text or a regex."""
    from . import rules
    hits = []
    if pattern is None and text:
        pattern = re.escape(text)
        if whole_word:
            pattern = rf"\b{pattern}\b"
    if not pattern:
        return hits
    flags = 0 if case else re.IGNORECASE
    rx = re.compile(pattern, flags)
    for pno, page in enumerate(doc):
        for r in rules.search_regex(page, rx):
            hits.append((pno, annotate.to_page(page, r)))
    return hits


# ---- forms ---------------------------------------------------------------------

def detect_fields(doc, pages=None, max_lines=400):
    """Guess form fields: runs of underscores and drawn blank lines become
    text fields; empty box characters become checkboxes. Returns marks
    (page, "add_field", payload) for apply_marks().

    Text is read once per page (it used to be read again for every line:
    minutes on a drawing), and pages with more than `max_lines` drawn lines
    are drawings, not forms - their walls aren't blanks to fill in."""
    marks, used = [], {w.field_name for p in doc for w in p.widgets()}

    def text_in(words, r):
        return " ".join(w[4] for w in words if fitz.Rect(w[:4]).intersects(r))

    def name_for(words, rect, fallback):
        left = fitz.Rect(max(0, rect.x0 - 220), rect.y0 - 4, rect.x0 - 1,
                         rect.y1 + 2)
        label = re.sub(r"[^\w ]", "", " ".join(
            w[4] for w in words if fitz.Rect(w[:4]).intersects(left)
            and w[2] <= rect.x0 + 1)).strip()
        label = " ".join(label.split()[-4:]) or fallback
        n, base = 1, label
        while label in used:
            n += 1
            label = f"{base} {n}"
        used.add(label)
        return label

    for pno, page in enumerate(doc):
        if pages is not None and pno not in pages:
            continue
        taken = [w.rect for w in page.widgets()]

        def free(r):
            return not any(r.intersects(t) for t in taken)

        words = page.get_text("words")
        found = []
        for x0, y0, x1, y1, word, *_ in words:
            if re.fullmatch(r"_{3,}", word):
                found.append(("text", fitz.Rect(x0, y1 - 14, x1, y1 + 1)))
            elif word in ("☐", "□", "▢", "❑"):
                found.append(("checkbox", fitz.Rect(x0, y0, x1, y1)))
        lines = []
        drawings = page.get_drawings()
        n_items = sum(len(d.get("items", [])) for d in drawings)
        if n_items <= max_lines:
            for d in drawings:
                if (d.get("width") or 1) > 2:
                    continue
                for item in d.get("items", []):
                    if item[0] != "l":
                        continue
                    a, b = item[1], item[2]
                    if abs(a.y - b.y) < 0.5 and abs(b.x - a.x) > 60:
                        lines.append((a, b))
        for a, b in lines:
            x0, x1 = sorted((a.x, b.x))
            r = fitz.Rect(x0, a.y - 14, x1, a.y - 0.5)
            if not text_in(words, r).strip():
                found.append(("text", r))
        for ftype, r in found:
            pr = annotate.to_page(page, r)
            if not free(pr):
                continue
            taken.append(pr)
            name = name_for(words, r, f"Field {len(marks) + 1}")
            marks.append((pno, "add_field",
                          {"rect": list(pr), "ftype": ftype, "name": name}))
    return marks


# ---- misc ------------------------------------------------------------------------

def flatten(doc, annots=True, fields=True):
    """Burn markups and/or form fields into the page so they can't change."""
    doc.bake(annots=annots, widgets=fields)


class NotSmaller(Exception):
    """Reduce File Size made nothing smaller: no file was written."""

    def __init__(self, before, after):
        self.before, self.after = before, after
        if after > before:
            how = (f"it would have grown from {before / 1024:,.0f} KB to "
                   f"{after / 1024:,.0f} KB")
        else:
            how = (f"it would only have gone from {before / 1024:,.0f} KB "
                   f"to {after / 1024:,.0f} KB")
        super().__init__("Already as small as it gets; no file written. "
                         f"({how}.)")


# a reduced copy is kept only when it is at least this much smaller
MIN_GAIN = 0.02


def baseline_size(doc, path=None, edited=False):
    """What a reduced copy has to beat: the file on disk, or (unsaved
    changes, or no file) the size a normal save would write."""
    path = path or getattr(doc, "name", "") or ""
    if path and not edited and os.path.isfile(path):
        return os.path.getsize(path)
    return len(doc.tobytes(garbage=1, deflate=True))


def reduce_size(doc, path, image_dpi=150, original=None, min_gain=MIN_GAIN):
    """Save a smaller copy: downsample big images, compress, clean up.

    The copy is written to a temporary file first and kept only when it
    is smaller than `original` bytes (by `min_gain`); otherwise the
    temporary file is deleted, nothing is written at `path` and NotSmaller
    is raised. `original` None: the size of the file `doc` was opened from
    (no check for a document that has no file). Returns the new size."""
    if original is None:
        name = getattr(doc, "name", "") or ""
        if name and os.path.isfile(name) and not doc.is_dirty:
            original = os.path.getsize(name)
    try:
        doc.rewrite_images(dpi_threshold=image_dpi + 50, dpi_target=image_dpi,
                           quality=80, lossy=True, lossless=True, bitonal=True,
                           color=True, gray=True)
    except Exception:
        pass                                  # older PyMuPDF: just compress
    # Merging duplicate objects (garbage 3/4) and rewriting every content
    # stream (clean) are slow on big files: minutes for a 687-page book.
    # Only do them for smaller documents, where they are quick.
    big = doc.xref_length() > 20000 or doc.page_count > 300
    opts = dict(garbage=2 if big else 4, deflate=True, deflate_images=True,
                deflate_fonts=True, clean=not big, use_objstms=1)
    # a password-protected document's copy keeps its encryption, both
    # passwords and permissions (PDF_ENCRYPT_KEEP; checked after saving).
    # safeio.UnprotectedCopyError when it can't: nothing is written.
    if original is None:
        safeio.atomic_save_keeping_encryption(doc, path, **opts)
        return os.path.getsize(path)
    tmp = os.fspath(path) + f".{os.getpid()}.reduce-tmp"
    try:
        safeio.save_keeping_encryption(doc, tmp, **opts)
        after = os.path.getsize(tmp)
        if after > original * (1 - min_gain):
            raise NotSmaller(original, after)
        try:
            os.replace(tmp, path)
        except PermissionError as e:
            raise safeio.FileInUseError(
                f"{os.path.basename(path)} is open (in QuantiSheet or "
                "another program), so it can't be replaced. Save under a "
                "different name, or close it first.") from e
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
    return after


def crop(doc, pages, rect):
    """Crop pages to `rect` (op coordinates of the first page)."""
    for i in pages:
        page = doc[i]
        r = fitz.Rect(rect) & page.mediabox
        if not r.is_empty:
            page.set_cropbox(r)


STAMPS = [("Approved", 0), ("Not Approved", 9), ("Draft", 13), ("Final", 6),
          ("For Comment", 7), ("Confidential", 2), ("As Is", 1),
          ("Expired", 5), ("Experimental", 4), ("Departmental", 3),
          ("For Public Release", 8), ("Not For Public Release", 10),
          ("Sold", 11), ("Top Secret", 12)]
