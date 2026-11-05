"""PDF/A (archival PDF) export - File > Export To > PDF/A.

PDF/A-3b is the target: it allows the embedded files QuantiSheet keeps its
job data in. With Ghostscript installed the conversion is Ghostscript's
(fonts embedded, colours converted). Without it, QuantiSheet does what it
can itself: archival metadata (XMP with the PDF/A id), an sRGB output
intent, no JavaScript or encryption, printable annotations with
appearances - and reports what it couldn't fix (fonts that aren't
embedded need Ghostscript or the authoring program).

check(doc) lists the problems a validator would raise for the rules we
can see; validate the result with veraPDF for a formal check.
"""
import datetime
import glob
import logging
import os
import shutil
import subprocess
import tempfile

import fitz

from . import annotate

log = logging.getLogger(__name__)

PART, CONF = 3, "B"


def ghostscript():
    """Ghostscript: the installed copy under Program Files first; else
    one on PATH - never one in the current folder (Windows' which()
    looks there first; threat model T-017)."""
    for base in (os.environ.get("ProgramW6432") or r"C:\Program Files",
                 os.environ.get("ProgramFiles(x86)") or
                 r"C:\Program Files (x86)"):
        for p in sorted(glob.glob(os.path.join(base, "gs", "gs*", "bin",
                                               "gswin64c.exe")) +
                        glob.glob(os.path.join(base, "gs", "gs*", "bin",
                                               "gswin32c.exe")),
                        reverse=True):
            return p
    here = os.path.normcase(os.path.abspath(os.getcwd()))
    for name in ("gswin64c", "gswin32c", "gs"):
        p = shutil.which(name)
        if p and os.path.normcase(os.path.dirname(os.path.abspath(p))) \
                != here:
            return p
    return None


def _srgb_icc():
    for p in (r"C:\Windows\System32\spool\drivers\color\sRGB Color Space "
              r"Profile.icm",
              "/usr/share/color/icc/colord/sRGB.icc",
              "/usr/share/color/icc/sRGB.icc",
              "/System/Library/ColorSync/Profiles/sRGB Profile.icc"):
        if os.path.exists(p):
            with open(p, "rb") as f:
                return f.read()
    return None


def check(doc):
    """[(problem, can fix)] for PDF/A-3b rules we can check."""
    out = []
    if doc.is_encrypted:
        out.append(("The file is encrypted", True))
    names = doc.xref_get_key(doc.pdf_catalog(), "Names")[1] or ""
    if "JavaScript" in names or any(
            "JavaScript" in (doc.xref_object(x) or "")
            for x in range(1, min(doc.xref_length(), 5000))
            if doc.xref_get_key(x, "S")[1] == "/JavaScript"):
        out.append(("JavaScript actions", True))
    if doc.xref_get_key(doc.pdf_catalog(), "OutputIntents")[0] == "null":
        out.append(("No output intent (colour profile)", True))
    md = doc.get_xml_metadata() or ""
    if "pdfaid" not in md:
        out.append(("No PDF/A identification in the metadata", True))
    noap = 0
    for p in doc:
        for a in annotate.iter_annots(p) or []:
            if a.type[0] in (fitz.PDF_ANNOT_POPUP, fitz.PDF_ANNOT_LINK):
                continue
            if doc.xref_get_key(a.xref, "AP")[0] == "null" or \
                    not (a.flags & fitz.PDF_ANNOT_IS_PRINT):
                noap += 1
    if noap:
        out.append((f"{noap} markup(s) without a printable appearance", True))
    fonts = set()
    for i in range(doc.page_count):
        for f in doc.get_page_fonts(i):
            try:
                if not doc.extract_font(f[0])[3]:
                    fonts.add(f[3])
            except Exception:
                logging.getLogger(__name__).debug("ignored error", exc_info=True)
    if fonts:
        out.append((f"Fonts not embedded: {', '.join(sorted(fonts)[:6])}",
                    False))
    return out


def _xmp(doc, now):
    md = doc.metadata or {}
    esc = (lambda s: (s or "").replace("&", "&amp;").replace("<", "&lt;")
           .replace(">", "&gt;"))
    return f"""<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:pdfaid="http://www.aiim.org/pdfa/ns/id/"
    xmlns:dc="http://purl.org/dc/elements/1.1/"
    xmlns:xmp="http://ns.adobe.com/xap/1.0/"
    xmlns:pdf="http://ns.adobe.com/pdf/1.3/">
   <pdfaid:part>{PART}</pdfaid:part>
   <pdfaid:conformance>{CONF}</pdfaid:conformance>
   <dc:title><rdf:Alt><rdf:li xml:lang="x-default">{esc(md.get('title'))}</rdf:li></rdf:Alt></dc:title>
   <dc:creator><rdf:Seq><rdf:li>{esc(md.get('author'))}</rdf:li></rdf:Seq></dc:creator>
   <xmp:CreatorTool>QuantiSheet</xmp:CreatorTool>
   <xmp:ModifyDate>{now}</xmp:ModifyDate>
   <xmp:CreateDate>{now}</xmp:CreateDate>
   <xmp:MetadataDate>{now}</xmp:MetadataDate>
   <pdf:Producer>QuantiSheet</pdf:Producer>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>"""


def _builtin(doc):
    """Fix what can be fixed in place. Returns what was done."""
    done = []
    now = datetime.datetime.now().astimezone().replace(microsecond=0)
    iso = now.isoformat()
    md = dict(doc.metadata or {})
    md["producer"] = "QuantiSheet"
    md["creator"] = md.get("creator") or "QuantiSheet"
    pdfdate = "D:" + now.strftime("%Y%m%d%H%M%S")
    md["modDate"] = md["creationDate"] = pdfdate
    doc.set_metadata(md)
    doc.set_xml_metadata(_xmp(doc, iso))
    done.append(f"PDF/A-{PART}{CONF.lower()} metadata")
    cat = doc.pdf_catalog()
    if doc.xref_get_key(cat, "OutputIntents")[0] == "null":
        icc = _srgb_icc()
        if icc:
            x = doc.get_new_xref()
            doc.update_object(x, "<</N 3>>")
            doc.update_stream(x, icc, compress=True)
            oi = doc.get_new_xref()
            doc.update_object(oi, f"<</Type/OutputIntent/S/GTS_PDFA1"
                                  f"/OutputConditionIdentifier(sRGB)"
                                  f"/Info(sRGB IEC61966-2.1)"
                                  f"/DestOutputProfile {x} 0 R>>")
            doc.xref_set_key(cat, "OutputIntents", f"[{oi} 0 R]")
            done.append("sRGB output intent")
    for key in ("OpenAction", "AA"):
        if "JavaScript" in (doc.xref_get_key(cat, key)[1] or ""):
            doc.xref_set_key(cat, key, "null")
            done.append("JavaScript removed")
    names = doc.xref_get_key(cat, "Names")
    if names[0] == "xref":
        nx = int(names[1].split()[0])
        if doc.xref_get_key(nx, "JavaScript")[0] != "null":
            doc.xref_set_key(nx, "JavaScript", "null")
            done.append("Document JavaScript removed")
    n = 0
    for p in doc:
        for a in annotate.iter_annots(p) or []:
            if a.type[0] in (fitz.PDF_ANNOT_POPUP, fitz.PDF_ANNOT_LINK):
                continue
            if not a.flags & fitz.PDF_ANNOT_IS_PRINT:
                a.set_flags(a.flags | fitz.PDF_ANNOT_IS_PRINT)
                n += 1
            if doc.xref_get_key(a.xref, "AP")[0] == "null":
                try:
                    a.update()
                except Exception:
                    logging.getLogger(__name__).debug("ignored error", exc_info=True)
    if n:
        done.append(f"{n} markup(s) set to print")
    return done


def export(doc, path, use_ghostscript=True):
    """Write `doc` as PDF/A-3b to `path`. Returns {method, done, remaining}
    (remaining = problems a validator would still raise)."""
    gs = ghostscript() if use_ghostscript else None
    if gs:
        tmp = tempfile.mkdtemp(prefix="quantisheet-pdfa-")
        src = os.path.join(tmp, "in.pdf")
        doc.save(src, garbage=1)
        cmd = [gs, "-dPDFA=3", "-dBATCH", "-dNOPAUSE", "-dSAFER",
               "-sColorConversionStrategy=RGB",
               "-dPDFACompatibilityPolicy=1", "-sDEVICE=pdfwrite",
               f"-sOutputFile={path}", src]
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=1800, creationflags=getattr(
                               subprocess, "CREATE_NO_WINDOW", 0))
        if p.returncode == 0 and os.path.exists(path):
            out = fitz.open(path)
            try:
                # Ghostscript drops embedded files; put the job data back
                from . import jobdata
                jobdata.restore(out, jobdata.snapshot(doc))
                done = ["Converted with Ghostscript"] + _builtin(out)
                out.save(path + ".tmp", garbage=1, deflate=True)
                rem = check(out)
            finally:
                out.close()
            os.replace(path + ".tmp", path)
            return {"method": "ghostscript", "done": done,
                    "remaining": [m for m, _f in rem]}
        log.warning("ghostscript PDF/A failed: %s", p.stderr[-2000:])
    work = fitz.open("pdf", doc.tobytes())
    try:
        done = _builtin(work)
        work.save(path, garbage=1, deflate=True)
    finally:
        work.close()
    out = fitz.open(path)
    rem = check(out)
    out.close()
    return {"method": "built-in", "done": done,
            "remaining": [m for m, _f in rem]}
