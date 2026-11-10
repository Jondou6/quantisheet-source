"""More Acrobat-style tools: Create PDF (Office, text, HTML, images),
split / replace / duplicate pages, visual compare, PowerPoint & HTML
export, sanitize & properties, and batch processing (Action Wizard)."""
import html as html_mod
import os
import subprocess
import sys
import tempfile

import fitz
import logging

log = logging.getLogger(__name__)

from . import acrobat, jobdata, page_ops
from . import safeio

OFFICE_WORD = (".doc", ".docx", ".rtf", ".odt")
OFFICE_EXCEL = (".xls", ".xlsx", ".xlsm", ".csv", ".ods")
OFFICE_PPT = (".ppt", ".pptx", ".odp")
TEXT_EXT = (".txt", ".log", ".md", ".py", ".json", ".xml", ".ini")
HTML_EXT = (".html", ".htm")
CREATE_FILTER = ("All supported (*.doc *.docx *.rtf *.odt *.xls *.xlsx *.xlsm "
                 "*.csv *.ods *.ppt *.pptx *.odp *.txt *.md *.html *.htm "
                 "*.png *.jpg *.jpeg *.tif *.tiff *.bmp *.gif *.pdf)")

# ---- running PowerShell / Office ------------------------------------------------

# AutomationSecurity = 3 (msoAutomationSecurityForceDisable): Office opens
# the file with every macro off, auto-open ones included - a file sent to
# "Create PDF" can't run code (threat model T-002). Excel events off too.
_PS = {
    "word": r"""
$w = New-Object -ComObject Word.Application; $w.Visible = $false
$w.AutomationSecurity = 3
try { $d = $w.Documents.Open($env:PS_IN, $false, $true)
      $d.ExportAsFixedFormat($env:PS_OUT, 17); $d.Close(0) }
finally { $w.Quit() }""",
    "excel": r"""
$x = New-Object -ComObject Excel.Application; $x.DisplayAlerts = $false
$x.AutomationSecurity = 3; $x.EnableEvents = $false
try { $b = $x.Workbooks.Open($env:PS_IN, 0, $true)
      $b.ExportAsFixedFormat(0, $env:PS_OUT); $b.Close($false) }
finally { $x.Quit() }""",
    "ppt": r"""
$p = New-Object -ComObject PowerPoint.Application
$p.AutomationSecurity = 3
try { $pr = $p.Presentations.Open($env:PS_IN, $true, $false, $false)
      $pr.SaveAs($env:PS_OUT, 32); $pr.Close() }
finally { $p.Quit() }""",
}


def _powershell(script, env, timeout=300):
    if not sys.platform.startswith("win"):
        raise RuntimeError("Microsoft Office conversion needs Windows.")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    from .syspaths import powershell       # full path (threat model T-017)
    ps = powershell()
    r = subprocess.run([ps, "-NoProfile", "-NonInteractive",
                        "-ExecutionPolicy", "Bypass", "-Command", script],
                       env={**os.environ, **env}, capture_output=True,
                       text=True, timeout=timeout, creationflags=flags)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip()[:400] or
                           "PowerShell failed")
    return r.stdout


def _soffice():
    for cand in (r"C:\Program Files\LibreOffice\program\soffice.exe",
                 r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
                 "/usr/bin/soffice", "/usr/bin/libreoffice",
                 "/Applications/LibreOffice.app/Contents/MacOS/soffice"):
        if os.path.exists(cand):
            return cand
    return None


def office_to_pdf(path, out):
    """Convert a Word/Excel/PowerPoint file with Microsoft Office (or
    LibreOffice if Office isn't installed)."""
    ext = os.path.splitext(path)[1].lower()
    kind = ("word" if ext in OFFICE_WORD else "excel" if ext in OFFICE_EXCEL
            else "ppt" if ext in OFFICE_PPT else None)
    if kind is None:
        raise ValueError(f"Not an Office file: {path}")
    errors = []
    if sys.platform.startswith("win"):
        try:
            _powershell(_PS[kind], {"PS_IN": os.path.abspath(path),
                                    "PS_OUT": os.path.abspath(out)})
            if os.path.exists(out):
                return out
        except Exception as e:
            msg = str(e)
            if "No printers are installed" in msg:
                msg = ("Excel needs a printer installed to save as PDF. "
                       "Turn on \"Microsoft Print to PDF\" (Settings > "
                       "Bluetooth & devices > Printers & scanners > Add "
                       "device, or Windows Features), then try again")
            errors.append(f"Microsoft Office: {msg.splitlines()[0]}")
    so = _soffice()
    if so:
        outdir = tempfile.mkdtemp(prefix="quantisheet-lo-")
        subprocess.run([so, "--headless", "--convert-to", "pdf", "--outdir",
                        outdir, path], capture_output=True, timeout=300)
        made = os.path.join(outdir, os.path.splitext(
            os.path.basename(path))[0] + ".pdf")
        if os.path.exists(made):
            os.replace(made, out)
            return out
        errors.append("LibreOffice could not convert it")
    raise RuntimeError("Could not convert this file. " + (
        "; ".join(errors) if errors else
        "Install Microsoft Office or LibreOffice to convert Office files."))


def _story_pdf(html, base_dir=None, paper=fitz.paper_rect("letter")):
    archive = fitz.Archive(base_dir) if base_dir else None
    story = fitz.Story(html, archive=archive,
                       user_css="body{font-family:sans-serif;font-size:11pt}")
    where = paper + (54, 54, -54, -54)
    return story.write_with_links(lambda n, filled: (paper, where, None))


def text_to_pdf(text):
    return _story_pdf("<pre style='white-space:pre-wrap;font-family:"
                      "monospace;font-size:9.5pt'>" + html_mod.escape(text) +
                      "</pre>")


def create_pdf(path):
    """A new document from any supported file. The caller closes it (on
    Windows an open document keeps its file locked)."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return fitz.open(path)
    if ext in acrobat.IMAGE_EXT:
        return acrobat.combine([path], bookmarks=False)
    if ext in TEXT_EXT:
        with open(path, encoding="utf-8", errors="replace") as f:
            return text_to_pdf(f.read())
    if ext in HTML_EXT:
        with open(path, encoding="utf-8", errors="replace") as f:
            return _story_pdf(f.read(), os.path.dirname(os.path.abspath(path)))
    if ext in OFFICE_WORD + OFFICE_EXCEL + OFFICE_PPT:
        out = os.path.join(tempfile.mkdtemp(prefix="quantisheet-"),
                           os.path.splitext(os.path.basename(path))[0] +
                           ".pdf")
        office_to_pdf(path, out)
        return fitz.open(out)
    raise ValueError(f"QuantiSheet can't convert {ext} files.")


# ---- organize pages --------------------------------------------------------------

def split(doc, out_dir, every=None, by_bookmarks=False, base=None):
    """Split into several PDFs: every N pages, or at each top-level
    bookmark. Returns the paths written."""
    os.makedirs(out_dir, exist_ok=True)
    base = base or os.path.splitext(os.path.basename(doc.name or "document"))[0]
    n = doc.page_count
    ranges = []
    if by_bookmarks:
        marks = [(t, p - 1) for lvl, t, p, *_ in doc.get_toc() if lvl == 1
                 and p >= 1]
        if not marks:
            raise ValueError("This document has no bookmarks to split at.")
        if marks[0][1] > 0:
            marks.insert(0, ("Start", 0))
        for i, (title, start) in enumerate(marks):
            end = marks[i + 1][1] - 1 if i + 1 < len(marks) else n - 1
            if end >= start:
                ranges.append((title, start, end))
    else:
        every = max(1, int(every or 1))
        for start in range(0, n, every):
            end = min(n, start + every) - 1
            ranges.append((f"pages {start + 1}-{end + 1}", start, end))
    out = []
    for i, (title, start, end) in enumerate(ranges, 1):
        safe = "".join(c if c.isalnum() or c in " -_" else "_"
                       for c in title).strip()[:50]
        path = os.path.join(out_dir, f"{base} - {i:02d} {safe}.pdf")
        part = fitz.open()
        part.insert_pdf(doc, from_page=start, to_page=end)
        jobdata.copy_job(doc, part, {start + k: k
                                     for k in range(end - start + 1)})
        part.save(path, garbage=safeio.gc_level(part), deflate=True)
        part.close()
        out.append(path)
    return out


def replace_pages(doc, first, count, src_path, src_first=0):
    """Replace `count` pages starting at `first` with pages from another
    PDF (starting at its page `src_first`)."""
    src = fitz.open(src_path)
    try:
        count = min(count, src.page_count - src_first,
                    doc.page_count - first)
        if count <= 0:
            raise ValueError("Nothing to replace with.")
        # a replaced sheet keeps the scale of the one it replaces
        with jobdata.keep_scales(doc):
            doc.insert_pdf(src, from_page=src_first,
                           to_page=src_first + count - 1, start_at=first)
            doc.delete_pages(list(range(first + count, first + 2 * count)))
    finally:
        src.close()
    return count


def duplicate_page(doc, i):
    with jobdata.keep_scales(doc):
        doc.fullcopy_page(i, i + 1 if i + 1 < doc.page_count else -1)
    jobdata.copy_job(doc, doc, {i: i + 1}, scales_only=True)
    return i + 1


# ---- visual compare --------------------------------------------------------------

def visual_compare(old_path, new_path, dpi=100, threshold=60):
    """A PDF showing, page by page, what changed between two drawings:
    removed in red, added in green, unchanged in light grey. Returns
    (document, [changed pixel % per page])."""
    import numpy as np
    a, b = fitz.open(old_path), fitz.open(new_path)
    out = fitz.open()
    stats = []
    try:
        for i in range(max(a.page_count, b.page_count)):
            ref = b[i] if i < b.page_count else a[i]
            w, h = ref.rect.width, ref.rect.height

            def gray(doc):
                if i >= doc.page_count:
                    return np.full((int(h * dpi / 72), int(w * dpi / 72)),
                                   255, np.uint8)
                p = doc[i]
                m = fitz.Matrix(dpi / 72 * w / p.rect.width,
                                dpi / 72 * h / p.rect.height)
                pix = p.get_pixmap(matrix=m, colorspace=fitz.csGRAY,
                                   alpha=False)
                arr = np.frombuffer(pix.samples, np.uint8).reshape(
                    pix.height, pix.stride)[:, :pix.width]
                return arr

            g1, g2 = gray(a), gray(b)
            hh, ww = min(g1.shape[0], g2.shape[0]), min(g1.shape[1],
                                                         g2.shape[1])
            g1, g2 = g1[:hh, :ww], g2[:hh, :ww]
            ink1, ink2 = g1 < 255 - threshold, g2 < 255 - threshold
            removed, added = ink1 & ~ink2, ink2 & ~ink1
            rgb = np.full((hh, ww, 3), 255, np.uint8)
            same = ink1 & ink2
            rgb[same] = (190, 190, 190)
            rgb[removed] = (220, 30, 30)
            rgb[added] = (20, 160, 40)
            pix = fitz.Pixmap(fitz.csRGB, ww, hh, rgb.tobytes(), False)
            page = out.new_page(width=w, height=h)
            page.insert_image(page.rect, pixmap=pix)
            changed = (removed | added).sum() / max(1, (ink1 | ink2).sum())
            stats.append(round(100 * changed, 1))
            page.insert_text((18, 20), f"Page {i + 1}: red = removed, "
                             f"green = added ({stats[-1]}% of linework "
                             "changed)", fontsize=9, color=(0.2, 0.2, 0.2))
    finally:
        a.close()
        b.close()
    return out, stats


# ---- export ------------------------------------------------------------------------

def export_html(doc, path):
    parts = ["<!doctype html><meta charset='utf-8'><title>" +
             html_mod.escape(os.path.basename(doc.name or "Document")) +
             "</title><style>body{background:#888;margin:0}"
             ".page{background:#fff;margin:16px auto;position:relative;"
             "box-shadow:0 2px 8px #0005;overflow:hidden}</style>"]
    for page in doc:
        parts.append(f"<div class='page' style='width:{page.rect.width}pt;"
                     f"height:{page.rect.height}pt'>" + page.get_text("html")
                     .replace('<div id="page0"', "<div") + "</div>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))
    return path


_PPT_SCRIPT = r"""
$p = New-Object -ComObject PowerPoint.Application
$p.AutomationSecurity = 3
try {
  $pres = $p.Presentations.Add($false)
  $pres.PageSetup.SlideWidth = [single]$env:PS_W
  $pres.PageSetup.SlideHeight = [single]$env:PS_H
  $i = 1
  Get-ChildItem -Path $env:PS_DIR -Filter *.png | Sort-Object Name | ForEach-Object {
    $s = $pres.Slides.Add($i, 12)
    $null = $s.Shapes.AddPicture($_.FullName, 0, -1, 0, 0,
                                 $pres.PageSetup.SlideWidth,
                                 $pres.PageSetup.SlideHeight)
    $i++
  }
  $pres.SaveAs($env:PS_OUT, 24); $pres.Close()
} finally { $p.Quit() }"""


def export_powerpoint(doc, path, dpi=150):
    """PowerPoint deck, one slide per page (pages as pictures). Written
    directly (python-pptx) - no Office needed, on any system; falls back
    to the PowerPoint installed on this computer."""
    try:
        import pptx                                    # noqa: F401
    except ImportError:
        return _export_powerpoint_office(doc, path, dpi)
    return _export_powerpoint_pptx(doc, path, dpi)


def _export_powerpoint_pptx(doc, path, dpi=150):
    import io
    from pptx import Presentation
    from pptx.util import Emu
    r = doc[0].rect
    scale = min(1.0, 4032 / max(r.width, r.height))   # PowerPoint max 56in
    emu = 12700                                        # per point
    prs = Presentation()
    prs.slide_width = Emu(int(r.width * scale * emu))
    prs.slide_height = Emu(int(r.height * scale * emu))
    blank = prs.slide_layouts[6]
    for page in doc:
        slide = prs.slides.add_slide(blank)
        png = page.get_pixmap(dpi=dpi, alpha=False).tobytes("png")
        pr = page.rect
        f = min(r.width / pr.width, r.height / pr.height) * scale
        w, h = pr.width * f * emu, pr.height * f * emu
        left = (prs.slide_width - w) / 2
        top = (prs.slide_height - h) / 2
        slide.shapes.add_picture(io.BytesIO(png), Emu(int(left)),
                                 Emu(int(top)), Emu(int(w)), Emu(int(h)))
    prs.save(path)
    return path


def _export_powerpoint_office(doc, path, dpi=150):
    folder = tempfile.mkdtemp(prefix="quantisheet-ppt-")
    for i, page in enumerate(doc):
        page.get_pixmap(dpi=dpi, alpha=False).save(
            os.path.join(folder, f"slide{i:04d}.png"))
    r = doc[0].rect
    scale = min(1.0, 4032 / max(r.width, r.height))    # PowerPoint max 56in
    _powershell(_PPT_SCRIPT, {"PS_DIR": folder, "PS_OUT": os.path.abspath(path),
                              "PS_W": str(r.width * scale),
                              "PS_H": str(r.height * scale)})
    return path


# ---- protect -------------------------------------------------------------------------

def _has_hidden_text(doc):
    """Any invisible (render mode 3) text in the file - e.g. an OCR layer
    or text hidden on purpose."""
    for page in doc:
        try:
            if any(sp.get("type") == 3 for sp in page.get_texttrace()):
                return True
        except Exception:
            return True
    return False


def _clean_copy(doc, **kw):
    """A freshly written copy of `doc`, opened from memory: rewriting a
    file MuPDF had to repair gives it a sound structure (xref table, page
    tree)."""
    data = doc.tobytes(garbage=safeio.gc_level(doc), **kw)
    return fitz.open("pdf", data)


def _rebuild(doc):
    """Replace a damaged (repaired) file's pages with a clean copy of
    itself, in place."""
    clean = _clean_copy(doc)
    n = doc.page_count
    doc.insert_pdf(clean)
    doc.delete_pages(0, n - 1)
    clean.close()


# ---- Check / Repair PDF ---------------------------------------------------------------

class RepairReport:
    """What check_and_repair() found and did."""

    def __init__(self, path):
        self.path = path
        self.error = ""              # the file could not be checked at all
        self.repaired_on_open = False
        self.page_count = 0          # pages found
        self.declared = 0            # pages the file says it has
        self.bad_pages = []          # [(page index, reason)]
        self.notes = []              # [(page index, MuPDF warning)]
        self.out = None              # the repaired copy written, if any
        self.out_pages = 0
        self.out_repaired = False    # the copy itself still needed repair
        self.unprotected_skip = False  # protected file: copy couldn't keep it

    @property
    def problems(self):
        out = []
        if self.error:
            out.append(self.error)
        if self.repaired_on_open:
            out.append("The file's structure (cross-reference table) is "
                       "damaged; it had to be repaired to open.")
        if self.declared > self.page_count:
            out.append(f"The file says it has {self.declared} pages, but "
                       f"only {self.page_count} could be found.")
        for i, why in self.bad_pages:
            out.append(f"Page {i + 1}: {why}.")
        return out

    @property
    def ok(self):
        return not self.problems

    def text(self):
        name = os.path.basename(self.path)
        if self.ok:
            lines = [f"No problems found in {name}. No file was written."]
            if self.notes:
                lines.append("")
                lines.append("Notes while reading (usually harmless):")
                lines += [f"  Page {i + 1}: {w}" for i, w in self.notes[:10]]
            return "\n".join(lines)
        lines = [f"Problems found in {name}:", ""]
        lines += ["  • " + p for p in self.problems[:30]]
        if len(self.problems) > 30:
            lines.append(f"  … and {len(self.problems) - 30} more")
        if self.notes:
            lines += ["", "Other warnings while reading:"]
            lines += [f"  Page {i + 1}: {w}" for i, w in self.notes[:10]]
        lines.append("")
        if self.out:
            lines.append(f"Saved a repaired copy: {os.path.basename(self.out)}"
                         f" ({self.out_pages} page(s)), next to the "
                         "original. The original was not changed.")
            if self.out_repaired:
                lines.append("The copy still needed repair when it was "
                             "re-opened: ask for a new copy of the file.")
            else:
                lines.append("The copy re-opens cleanly. Check it "
                             "before relying on it.")
        elif self.unprotected_skip:
            lines.append("No repaired copy was saved: the file is "
                         "password-protected and a repaired copy could not "
                         "keep that protection.")
        elif not self.error:
            lines.append("No repaired copy could be saved: nothing in the "
                         "file could be read.")
        return "\n".join(lines)


def repaired_path(path):
    """'<name> (repaired).pdf' next to `path`, never an existing file."""
    base = os.path.splitext(path)[0]
    out = f"{base} (repaired).pdf"
    n = 2
    while os.path.exists(out):
        out = f"{base} (repaired {n}).pdf"
        n += 1
    return out


def _mupdf_warnings():
    try:
        return (fitz.TOOLS.mupdf_warnings(reset=True) or "").strip()
    except Exception:                                     # noqa: BLE001
        return ""


def _declared_pages(doc):
    try:
        t, v = doc.xref_get_key(doc.pdf_catalog(), "Pages/Count")
        return int(v) if t == "int" else 0
    except Exception:                                     # noqa: BLE001
        return 0


def _missing_content(doc, page):
    """Content streams the page refers to that aren't in the file."""
    gone = 0
    try:
        xrefs = page.get_contents()
    except Exception:                                     # noqa: BLE001
        return 1
    n = doc.xref_length()
    for x in xrefs:
        try:
            if x <= 0 or x >= n or \
                    doc.xref_object(x, compressed=True).strip() == "null" \
                    or doc.xref_stream_raw(x) is None:
                gone += 1
        except Exception:                                 # noqa: BLE001
            gone += 1
    return gone


def check_and_repair(path, save=True):
    """Check the PDF at `path` and, when it has problems, save a rebuilt
    copy as '<name> (repaired).pdf' next to it (never over the original or
    any other file). Every page is loaded and read; the copy is rewritten
    from scratch (tobytes(garbage=3) and re-opened), keeps every page
    that loads and is checked again. A clean file: no file written.
    Returns a RepairReport."""
    rep = RepairReport(path)
    shown = None
    try:
        shown = bool(fitz.TOOLS.mupdf_display_errors())
        fitz.TOOLS.mupdf_display_errors(False)
    except Exception:                                     # noqa: BLE001
        shown = None
    _mupdf_warnings()                                     # start clean
    try:
        try:
            doc = fitz.open(path)
        except Exception as e:                            # noqa: BLE001
            rep.error = f"The file can't be opened at all ({e})."
            return rep
        try:
            _check_doc(doc, rep)
            if save and not rep.error and not rep.ok:
                _save_repaired(doc, rep)
        finally:
            doc.close()
    finally:
        _mupdf_warnings()
        if shown is not None:
            try:
                fitz.TOOLS.mupdf_display_errors(shown)
            except Exception:                             # noqa: BLE001
                pass
    return rep


def _check_doc(doc, rep):
    if not doc.is_pdf:
        rep.error = "That file isn't a PDF."
        return
    if doc.needs_pass:
        rep.error = ("The file is password-protected, so it can't be "
                     "checked or repaired here (a repaired copy would "
                     "lose its protection).")
        return
    rep.repaired_on_open = bool(getattr(doc, "is_repaired", False))
    _mupdf_warnings()
    rep.page_count = doc.page_count
    rep.declared = _declared_pages(doc)
    for i in range(doc.page_count):
        try:
            page = doc.load_page(i)
            gone = _missing_content(doc, page)
            page.get_text("text")
            page.get_drawings()
        except Exception as e:                            # noqa: BLE001
            rep.bad_pages.append((i, f"can't be read ({e})"))
            _mupdf_warnings()
            continue
        if gone:
            rep.bad_pages.append((i, "its drawing content is missing "
                                  "(the page will be blank)"))
        w = _mupdf_warnings()
        if w:
            rep.notes.append((i, w.splitlines()[0][:160]))


def _save_repaired(doc, rep):
    unreadable = {i for i, why in rep.bad_pages if why.startswith("can't")}
    # a protected file (permissions only: one that needs a password to open
    # is refused by _check_doc) gets a copy with its own encryption, or none
    protected = safeio.is_encrypted(doc)
    copy = None
    try:
        if protected:
            copy = safeio.protected_copy(doc, garbage=safeio.gc_level(doc),
                                         deflate=True)
        else:
            copy = _clean_copy(doc, deflate=True)
        drop = [i for i in range(copy.page_count) if i in unreadable or
                not _loads(copy, i)]
        if drop and len(drop) < copy.page_count:
            copy.delete_pages(drop)
        elif drop:
            copy.close()
            copy = None
    except Exception:                                     # noqa: BLE001
        log.info("check/repair: whole-file rebuild failed; copying page "
                 "by page", exc_info=True)
        if copy is not None:
            copy.close()
        copy = None
    if copy is None and protected:
        # a page-by-page copy is a new, unprotected PDF: don't write one
        rep.unprotected_skip = True
        return
    if copy is None:
        # page by page: whatever loads
        copy = fitz.open()
        for i in range(doc.page_count):
            if i in unreadable:
                continue
            try:
                copy.insert_pdf(doc, from_page=i, to_page=i)
            except Exception:                             # noqa: BLE001
                log.info("check/repair: page %d not copied", i + 1)
        if copy.page_count == 0:
            copy.close()
            return
    try:
        out = repaired_path(rep.path)
        safeio.atomic_save_keeping_encryption(
            copy, out, garbage=safeio.gc_level(copy), deflate=True)
    except safeio.UnprotectedCopyError:
        rep.unprotected_skip = True
        return
    finally:
        copy.close()
    rep.out = out
    try:
        chk = fitz.open(out)
        rep.out_pages = chk.page_count
        rep.out_repaired = bool(getattr(chk, "is_repaired", False))
        chk.close()
    except Exception:                                     # noqa: BLE001
        rep.out_repaired = True


def _loads(doc, i):
    try:
        doc.load_page(i).get_text("text")
        return True
    except Exception:                                     # noqa: BLE001
        return False


def sanitize(doc, keep_job=True, hidden_text=None):
    """Remove hidden information: metadata, scripts, attachments, hidden
    text, thumbnails, links. Markups and form values are kept, and so is
    QuantiSheet's own job data (scales, prices, assemblies) unless
    keep_job is False.

    hidden_text None: removed only when the file has some (the slow part,
    so files without it take seconds). A damaged file that MuPDF had to
    repair is rebuilt first, and any step that still fails is done on its
    own, so the rest is always cleaned."""
    job = jobdata.snapshot(doc) if keep_job else {}
    if hidden_text is None:
        hidden_text = _has_hidden_text(doc)
    failed = []
    rebuilt = False
    if getattr(doc, "is_repaired", False):
        try:
            _rebuild(doc)
            rebuilt = True
        except Exception:
            log.warning("could not rebuild repaired file", exc_info=True)
    # everything except hidden text first: it's quick. The hidden-text
    # redaction is the slow part (9,410 redactions on a 66-sheet set) and
    # now runs once, last, on its own (Grok M9: it used to run 3 times)
    opts = dict(attached_files=True, clean_pages=False,
                embedded_files=True, hidden_text=False,
                javascript=True, metadata=True, redactions=True,
                remove_links=True, reset_fields=False,
                reset_responses=False, thumbnails=True, xml_metadata=True)
    try:
        doc.scrub(**opts)
    except Exception as first:
        done = False
        if not rebuilt:
            try:
                _rebuild(doc)
                rebuilt = True
                doc.scrub(**opts)
                done = True
                log.info("hidden information: file rebuilt after %s", first)
            except Exception as e:
                log.info("hidden information: rebuild did not help (%s)", e)
        if not done:
            for k in [k for k, v in opts.items() if v]:
                one = {kk: False for kk in opts}
                one[k] = True
                try:
                    doc.scrub(**one)
                except Exception as e:
                    if not _remove_directly(doc, k):
                        failed.append(k)
                        log.info("hidden information: %s failed (%s)", k, e)
    # open/close scripts on the document and on each page: MuPDF's scrub
    # leaves page /AA alone (found Oct 19), so always remove them here
    try:
        cat = doc.pdf_catalog()
        if doc.xref_get_key(cat, "AA")[0] != "null":
            doc.xref_set_key(cat, "AA", "null")
        for pno in range(doc.page_count):
            if doc.xref_get_key(doc[pno].xref, "AA")[0] != "null":
                doc.xref_set_key(doc[pno].xref, "AA", "null")
    except Exception:                                     # noqa: BLE001
        failed.append("javascript")
    # XFA form data can carry scripts and isn't touched by scrub; the
    # ordinary form fields stay
    try:
        cat = doc.pdf_catalog()
        if doc.xref_get_key(cat, "AcroForm/XFA")[0] != "null":
            doc.xref_set_key(cat, "AcroForm/XFA", "null")
    except Exception:                                     # noqa: BLE001
        failed.append("xfa")
    if hidden_text:
        try:
            doc.scrub(**{k: k == "hidden_text" for k in opts})
        except Exception as e:
            failed.append("hidden_text")
            log.info("hidden information: hidden text failed (%s)", e)
    if failed:
        log.warning("hidden information: could not clean %s",
                    ", ".join(failed))
    # (no set_metadata({}) here any more: scrub already removed /Info, and
    # calling it re-created an empty one - Venice N4)
    if job:
        jobdata.restore(doc, job)
    return [STEP_NAMES.get(k, k) for k in failed]


STEP_NAMES = {"javascript": "scripts", "xml_metadata": "XML metadata",
              "metadata": "document properties", "attached_files":
              "attached files", "embedded_files": "embedded files",
              "thumbnails": "thumbnails", "remove_links": "links",
              "redactions": "redactions", "hidden_text": "hidden text",
              "xfa": "XFA form data"}


import re as _re
_JS_RE = _re.compile(r"/S\s*/JavaScript|/JS\s*[(<]|/JS\s+\d+\s+\d+\s+R|"
                     r"/JavaScript\s*(?:<<|\d+\s+\d+\s+R)")


def verify_clean(doc, hidden_text=None):
    """Proof, not hope: check the cleaned file item by item. Returns
    [(status, item, detail)] with status PASS or FAIL (Venice, Oct 19).
    hidden_text: also check that no invisible text is left (True), or skip
    that line (False / None)."""
    out = []

    def add(ok, item, detail=""):
        out.append(("PASS" if ok else "FAIL", item, detail))

    # check what will be saved: removed objects linger in memory until the
    # file is written, so look at a cleanly written copy
    copied = False
    try:
        doc = fitz.open("pdf", doc.tobytes(garbage=3))
        copied = True
    except Exception:                                     # noqa: BLE001
        pass
    js, aa, xmp, thumbs = [], [], [], 0
    try:
        cat = doc.pdf_catalog()
    except Exception:                                     # noqa: BLE001
        cat = 0
    for x in range(1, doc.xref_length()):
        try:
            obj = doc.xref_object(x, compressed=False)
        except Exception:                                 # noqa: BLE001
            continue
        # a real script: an action of type JavaScript, a /JS string or
        # stream, or a JavaScript name tree - not a key set to null
        if _JS_RE.search(obj):
            js.append(x)
        if "/Type/Metadata" in obj.replace(" ", ""):
            xmp.append(x)
    try:
        if cat and doc.xref_get_key(cat, "AA")[0] not in ("null", ""):
            aa.append(cat)
    except Exception:                                     # noqa: BLE001
        pass
    page_aa = 0
    for pg in doc:
        try:
            if doc.xref_get_key(pg.xref, "Thumb")[0] != "null":
                thumbs += 1
            if doc.xref_get_key(pg.xref, "AA")[0] != "null":
                page_aa += 1                      # page open/close scripts
        except Exception:                                 # noqa: BLE001
            pass
    aa += [0] * page_aa
    try:
        xfa = cat and doc.xref_get_key(cat, "AcroForm/XFA")[0] != "null"
    except Exception:                                     # noqa: BLE001
        xfa = False
    add(not js and not aa, "Scripts (JavaScript, open/close actions)",
        f"{len(js) + len(aa)} found" if js or aa else "")
    add(not xfa, "XFA form data (can hold scripts)", "found" if xfa else "")
    info = {k: v for k, v in (doc.metadata or {}).items()
            if v and k not in ("format", "encryption")}
    add(not info, "Document properties (author, title, software...)",
        ", ".join(sorted(info)) if info else "")
    add(not xmp, "XML metadata (document and pages)",
        f"{len(xmp)} found" if xmp else "")
    try:
        # QuantiSheet's own job data (scales, takeoff) is kept on purpose
        n_att = doc.embfile_count() - len(jobdata.names(doc))
    except Exception:                                     # noqa: BLE001
        n_att = 0
    n_att += sum(1 for pg in doc for a in (pg.annots() or [])
                 if a.type[1] == "FileAttachment")
    add(n_att == 0, "Attached files", f"{n_att} found" if n_att else "")
    add(thumbs == 0, "Page thumbnails", f"{thumbs} found" if thumbs else "")
    links = sum(len(pg.get_links()) for pg in doc)
    add(links == 0, "Links", f"{links} found" if links else "")
    if hidden_text:
        hid = _has_hidden_text(doc)
        add(not hid, "Hidden (invisible) text", "some left" if hid else "")
    # Redaction proof: every box redacted in QuantiSheet, checked again
    # for text, line art and image pixels left under it (item 1, 0.13.5)
    try:
        from . import redaction
        res = redaction.proof(doc, copy=not copied)
        if res:
            out.append(redaction.summary(res))
    except Exception as e:                                # noqa: BLE001
        log.warning("redaction proof failed", exc_info=True)
        add(False, "Redaction proof", f"the check could not be run ({e})")
    return out


def _remove_directly(doc, step):
    """Do a step by hand through the file's catalog when scrub trips on a
    broken reference elsewhere (Grok M9: scripts and XML metadata on the
    kenai set). True when it worked."""
    try:
        cat = doc.pdf_catalog()
        if step == "javascript":
            # "null" removes the key in PyMuPDF; /AA holds document-level
            # open/close scripts (Venice N3)
            doc.xref_set_key(cat, "Names/JavaScript", "null")
            doc.xref_set_key(cat, "OpenAction", "null")
            doc.xref_set_key(cat, "AA", "null")
            for pno in range(doc.page_count):      # page open/close scripts
                doc.xref_set_key(doc[pno].xref, "AA", "null")
            return True
        if step == "xml_metadata":
            doc.xref_set_key(cat, "Metadata", "null")
            for pno in range(doc.page_count):      # page-level XMP too
                doc.xref_set_key(doc[pno].xref, "Metadata", "null")
            return True
        if step == "metadata":
            doc.set_metadata({})
            return True
    except Exception:
        log.debug("direct removal of %s failed", step, exc_info=True)
    return False


def external_issue(doc, path, password=None, allow_unprotected=False):
    """Save a copy of `doc` to `path` for people outside the company:
    QuantiSheet's job data (estimate, prices, margins, audit, scales,
    assemblies) is removed along with hidden information. Markups and form
    entries stay. The open document is not changed. Returns the list of
    job files that were left out.
    A password-protected document's copy keeps its encryption, passwords
    and permissions (`password`: the one it was unlocked with);
    safeio.UnprotectedCopyError when that can't be done and
    `allow_unprotected` is False (nothing is written)."""
    removed = jobdata.names(doc)
    if allow_unprotected:
        copy = fitz.open("pdf", doc.tobytes(garbage=1))
    else:
        copy = safeio.protected_copy(doc, password, garbage=1)
    try:
        sanitize(copy, keep_job=False)
        jobdata.strip(copy)      # in case scrub missed a /Kids name tree
        left = jobdata.names(copy)
        if left:
            raise RuntimeError("job data could not be removed: "
                               + ", ".join(left))
        safeio.save_keeping_encryption(
            copy, path, garbage=safeio.gc_level(copy), deflate=True)
    finally:
        copy.close()
    return removed


PROPERTY_KEYS = ("title", "author", "subject", "keywords", "creator",
                 "producer")


def set_properties(doc, **values):
    meta = dict(doc.metadata or {})
    for k in PROPERTY_KEYS:
        if k in values:
            meta[k] = values[k]
    doc.set_metadata({k: meta.get(k) or "" for k in PROPERTY_KEYS})


# ---- Action Wizard (batch) ----------------------------------------------------------

BATCH_ACTIONS = [
    ("ocr", "Make searchable (OCR)"),
    ("page_numbers", "Add page numbers"),
    ("watermark", "Add watermark"),
    ("flatten", "Flatten markups & fields"),
    ("sanitize", "Remove hidden information"),
    ("reduce", "Reduce file size"),
    ("protect", "Password protect"),
]


def run_batch(paths, actions, out_dir, options=None, progress=None):
    """Apply `actions` (keys of BATCH_ACTIONS, in that order) to each file
    and save the results in out_dir. Returns [(path, result or error)]."""
    options = options or {}
    os.makedirs(out_dir, exist_ok=True)
    results = []
    for n, src in enumerate(paths):
        if progress and progress(n, len(paths), src) is False:
            break
        out = os.path.join(out_dir, os.path.basename(src))
        if os.path.abspath(out) == os.path.abspath(src):
            out = os.path.splitext(out)[0] + "_processed.pdf"
        doc = None
        try:
            doc = create_pdf(src)
            if "ocr" in actions and acrobat.pages_needing_ocr(doc):
                acrobat.make_searchable(doc)
            if "page_numbers" in actions:
                acrobat.header_footer(doc, {"bottom_center": options.get(
                    "page_format", "Page {page} of {pages}")})
            if "watermark" in actions:
                page_ops.add_watermark(doc, options.get("watermark", "DRAFT"),
                                       options.get("opacity", 0.25))
            if "flatten" in actions:
                acrobat.flatten(doc)
            if "sanitize" in actions:
                sanitize(doc)
            if "protect" in actions and options.get("password"):
                acrobat.save_protected(doc, out, options["password"])
            elif "reduce" in actions:
                # kept only when smaller than the file it came from; with
                # other steps (or a converted file) there is still a new
                # file to write, just not a "reduced" one
                other = bool(set(actions) - {"reduce"}) or \
                    not src.lower().endswith(".pdf")
                try:
                    acrobat.reduce_size(doc, out,
                                        original=os.path.getsize(src))
                except acrobat.NotSmaller as e:
                    if not other:
                        results.append((src, f"SKIPPED: {e}"))
                        continue
                    # a protected file stays protected: same passwords
                    # and permissions (Chief's round 5, Nov 9: Watermark +
                    # Reduce on a protected PDF wrote it unprotected)
                    safeio.atomic_save_keeping_encryption(
                        doc, out, garbage=safeio.gc_level(doc), deflate=True)
            else:
                safeio.atomic_save_keeping_encryption(
                    doc, out, garbage=safeio.gc_level(doc), deflate=True)
            results.append((src, out))
        except Exception as e:
            results.append((src, f"ERROR: {e}"))
        finally:
            # a file that failed is let go of too, so Windows doesn't keep
            # it locked (outside review via Chief, Nov 7 - H6)
            if doc is not None:
                doc.close()
    return results
