"""Preflight and PDF/X export (Document > Preflight / PDF/X), for print
shops and plan rooms.

preflight(doc, profile) checks what a printer cares about:
  fonts embedded, images sharp enough at their printed size, page boxes
  (trim and bleed), colour (RGB in a CMYK workflow), transparency
  (not allowed in PDF/X-1a), annotations that would print, encryption,
  JavaScript, hairlines too thin to print, and page sizes.

export_pdfx(doc, path, profile) writes PDF/X-4 (or X-1a with
Ghostscript): output intent, X identification in Info and XMP, TrimBox
on every page, annotations flattened, and lists anything left.
"""
import datetime
import logging
import os
import subprocess
import tempfile

import fitz

from . import annotate, pdfa

log = logging.getLogger(__name__)
PROFILES = {"PDF/X-4": {"rgb_ok": True, "transparency_ok": True},
            "PDF/X-1a": {"rgb_ok": False, "transparency_ok": False},
            "Plan room (print)": {"rgb_ok": True, "transparency_ok": True}}
MIN_DPI = {"color": 150, "gray": 150, "bitonal": 300}
HAIRLINE = 0.25            # points


def _issue(sev, rule, text, pages=None, fix=False):
    return {"severity": sev, "rule": rule, "text": text,
            "pages": sorted(set(pages or []))[:50], "fix": fix}


def preflight(doc, profile="PDF/X-4"):
    """[{severity: error|warning|info, rule, text, pages, fix}]"""
    prof = PROFILES.get(profile, PROFILES["PDF/X-4"])
    out = []
    if doc.is_encrypted:
        out.append(_issue("error", "encryption", "The file is encrypted",
                          fix=True))
    # fonts
    missing = {}
    for i in range(doc.page_count):
        for f in doc.get_page_fonts(i):
            try:
                if not doc.extract_font(f[0])[3]:
                    missing.setdefault(f[3], []).append(i + 1)
            except Exception:
                logging.getLogger(__name__).debug("ignored error", exc_info=True)
    for name, pages in missing.items():
        out.append(_issue("error", "fonts", f"Font not embedded: {name}",
                          pages))
    # images: resolution at placed size, colour
    low, rgb_img = [], []
    for pno, page in enumerate(doc):
        for info in page.get_image_info(xrefs=True):
            bbox = fitz.Rect(info["bbox"])
            if bbox.is_empty or bbox.width < 4:
                continue
            dpi = min(info["width"] / (bbox.width / 72),
                      info["height"] / (bbox.height / 72))
            cs = info.get("colorspace", 3)
            kind = "bitonal" if info.get("bpc") == 1 else \
                ("gray" if cs == 1 else "color")
            if dpi < MIN_DPI[kind] * 0.98:
                low.append((pno + 1, round(dpi)))
            if cs == 3 and not prof["rgb_ok"]:
                rgb_img.append(pno + 1)
    if low:
        worst = min(d for _p, d in low)
        out.append(_issue("warning", "resolution",
                          f"{len(low)} image(s) below print resolution "
                          f"(lowest {worst} dpi)", [p for p, _d in low]))
    if rgb_img:
        out.append(_issue("error", "color", f"{len(rgb_img)} RGB image(s) "
                          f"- {profile} needs CMYK or gray (Ghostscript "
                          "converts)", rgb_img))
    # vector colour, transparency, hairlines
    rgb_vec, trans, hair = [], [], []
    for pno, page in enumerate(doc):
        try:
            draws = page.get_drawings()
        except Exception:
            continue
        for d in draws[:4000]:
            for c in (d.get("color"), d.get("fill")):
                if c and len(c) == 3 and not (c[0] == c[1] == c[2]):
                    rgb_vec.append(pno + 1)
                    break
            if (d.get("fill_opacity") or 1) < 0.999 or \
                    (d.get("stroke_opacity") or 1) < 0.999:
                trans.append(pno + 1)
            w = d.get("width")
            if d.get("color") and w is not None and 0 < w < HAIRLINE:
                hair.append(pno + 1)
    if rgb_vec and not prof["rgb_ok"]:
        out.append(_issue("error", "color", "RGB colours in drawings",
                          rgb_vec))
    elif rgb_vec:
        out.append(_issue("info", "color", "RGB colours (fine for PDF/X-4 "
                          "with an output intent)", rgb_vec))
    if trans and not prof["transparency_ok"]:
        out.append(_issue("error", "transparency", "Transparency - not "
                          f"allowed in {profile}", trans))
    if hair:
        out.append(_issue("warning", "hairlines", f"Lines thinner than "
                          f"{HAIRLINE} pt may not print", hair))
    # boxes
    no_trim = [i + 1 for i, p in enumerate(doc)
               if doc.xref_get_key(p.xref, "TrimBox")[0] == "null" and
               doc.xref_get_key(p.xref, "ArtBox")[0] == "null"]
    if no_trim:
        out.append(_issue("error", "boxes", "No TrimBox (finished page "
                          "size)", no_trim, fix=True))
    sizes = {}
    for i, p in enumerate(doc):
        r = p.rect
        sizes.setdefault((round(r.width), round(r.height)), []).append(i + 1)
    if len(sizes) > 1:
        desc = ", ".join(f"{w / 72:g}x{h / 72:g} in ({len(v)})"
                         for (w, h), v in sorted(sizes.items(),
                                                 key=lambda kv:
                                                 -len(kv[1]))[:4])
        out.append(_issue("info", "sizes", f"Mixed page sizes: {desc}"))
    # annotations that would print over the artwork
    ann = [pno + 1 for pno, p in enumerate(doc)
           for a in annotate.iter_annots(p) or []
           if a.type[0] not in (fitz.PDF_ANNOT_LINK, fitz.PDF_ANNOT_POPUP)]
    if ann:
        out.append(_issue("warning", "annotations", f"{len(ann)} markup(s) "
                          "- flattened into the page on export", ann,
                          fix=True))
    if doc.xref_get_key(doc.pdf_catalog(), "OutputIntents")[0] == "null":
        out.append(_issue("error", "intent", "No output intent", fix=True))
    js = any(doc.xref_get_key(x, "S")[1] == "/JavaScript"
             for x in range(1, min(doc.xref_length(), 5000)))
    if js:
        out.append(_issue("error", "javascript", "JavaScript actions",
                          fix=True))
    return out


def summary(issues):
    e = sum(1 for i in issues if i["severity"] == "error")
    w = sum(1 for i in issues if i["severity"] == "warning")
    return "Passed" if not e and not w else \
        f"{e} error(s), {w} warning(s)"


def _xmp_x(doc, now, version):
    md = doc.metadata or {}
    esc = (lambda s: (s or "").replace("&", "&amp;").replace("<", "&lt;")
           .replace(">", "&gt;"))
    return f"""<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:pdfxid="http://www.npes.org/pdfx/ns/id/"
    xmlns:pdfx="http://ns.adobe.com/pdfx/1.3/"
    xmlns:dc="http://purl.org/dc/elements/1.1/"
    xmlns:xmp="http://ns.adobe.com/xap/1.0/"
    xmlns:xmpMM="http://ns.adobe.com/xap/1.0/mm/"
    xmlns:pdf="http://ns.adobe.com/pdf/1.3/">
   <pdfxid:GTS_PDFXVersion>{version}</pdfxid:GTS_PDFXVersion>
   <pdfx:GTS_PDFXVersion>{version}</pdfx:GTS_PDFXVersion>
   <pdf:Trapped>False</pdf:Trapped>
   <dc:title><rdf:Alt><rdf:li xml:lang="x-default">{esc(md.get('title'))}</rdf:li></rdf:Alt></dc:title>
   <xmp:CreatorTool>QuantiSheet</xmp:CreatorTool>
   <xmp:CreateDate>{now}</xmp:CreateDate>
   <xmp:ModifyDate>{now}</xmp:ModifyDate>
   <xmp:MetadataDate>{now}</xmp:MetadataDate>
   <xmpMM:DocumentID>uuid:{os.urandom(16).hex()}</xmpMM:DocumentID>
   <xmpMM:VersionID>1</xmpMM:VersionID>
   <pdf:Producer>QuantiSheet</pdf:Producer>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>"""


def _builtin(doc, profile):
    done = []
    version = "PDF/X-4" if profile != "PDF/X-1a" else "PDF/X-1a:2003"
    # flatten markups so nothing prints differently than it shows
    n = sum(1 for p in doc for a in annotate.iter_annots(p) or []
            if a.type[0] not in (fitz.PDF_ANNOT_LINK,
                                 fitz.PDF_ANNOT_POPUP))
    if n:
        doc.bake(annots=True, widgets=True)
        done.append(f"{n} markup(s) flattened into the page")
    t = 0
    for p in doc:
        if doc.xref_get_key(p.xref, "TrimBox")[0] == "null":
            p.set_trimbox(p.cropbox)
            t += 1
    if t:
        done.append(f"TrimBox set on {t} page(s) (= crop box)")
    now = datetime.datetime.now().astimezone().replace(microsecond=0)
    md = dict(doc.metadata or {})
    md["producer"] = "QuantiSheet"
    md["title"] = md.get("title") or "Document"
    md["modDate"] = md["creationDate"] = "D:" + now.strftime(
        "%Y%m%d%H%M%S")
    doc.set_metadata(md)
    info = doc.xref_get_key(-1, "Info")
    if info[0] == "xref":
        ix = int(info[1].split()[0])
        doc.xref_set_key(ix, "GTS_PDFXVersion", fitz.get_pdf_str(version))
        doc.xref_set_key(ix, "Trapped", "/False")
    doc.set_xml_metadata(_xmp_x(doc, now.isoformat(), version))
    done.append(f"{version} identification (Info and XMP)")
    cat = doc.pdf_catalog()
    if doc.xref_get_key(cat, "OutputIntents")[0] == "null":
        icc = pdfa._srgb_icc()
        x = None
        if icc:
            x = doc.get_new_xref()
            doc.update_object(x, "<</N 3>>")
            doc.update_stream(x, icc, compress=True)
        oi = doc.get_new_xref()
        prof = f"/DestOutputProfile {x} 0 R" if x else ""
        doc.update_object(oi, "<</Type/OutputIntent/S/GTS_PDFX"
                              "/OutputConditionIdentifier(sRGB)"
                              "/RegistryName(http://www.color.org)"
                              f"/Info(sRGB IEC61966-2.1){prof}>>")
        doc.xref_set_key(cat, "OutputIntents", f"[{oi} 0 R]")
        done.append("Output intent (sRGB)")
    for key in ("OpenAction", "AA"):
        if "JavaScript" in (doc.xref_get_key(cat, key)[1] or ""):
            doc.xref_set_key(cat, key, "null")
            done.append("JavaScript removed")
    return done


def export_pdfx(doc, path, profile="PDF/X-4", use_ghostscript=True):
    """Returns {method, done, remaining}."""
    gs = pdfa.ghostscript() if use_ghostscript else None
    if gs and profile == "PDF/X-1a":
        tmp = tempfile.mkdtemp(prefix="quantisheet-pdfx-")
        src = os.path.join(tmp, "in.pdf")
        doc.save(src, garbage=1)
        cmd = [gs, "-dPDFX", "-dBATCH", "-dNOPAUSE", "-dSAFER",
               "-sColorConversionStrategy=CMYK", "-sDEVICE=pdfwrite",
               "-dHaveTransparency=false", f"-sOutputFile={path}", src]
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=1800, creationflags=getattr(
                               subprocess, "CREATE_NO_WINDOW", 0))
        if p.returncode == 0 and os.path.exists(path):
            out = fitz.open(path)
            done = ["Converted to CMYK with Ghostscript"] + \
                _builtin(out, profile)
            out.save(path + ".tmp", garbage=1, deflate=True)
            rem = preflight(out, profile)
            out.close()
            os.replace(path + ".tmp", path)
            return {"method": "ghostscript", "done": done,
                    "remaining": [i for i in rem
                                  if i["severity"] == "error"]}
        log.warning("ghostscript PDF/X failed: %s", p.stderr[-2000:])
    work = fitz.open("pdf", doc.tobytes())
    try:
        done = _builtin(work, profile)
        work.save(path, garbage=1, deflate=True)
    finally:
        work.close()
    out = fitz.open(path)
    rem = preflight(out, profile)
    out.close()
    return {"method": "built-in", "done": done,
            "remaining": [i for i in rem if i["severity"] == "error"]}
