"""Split a spec book and a drawing set before anyone asks a model.

Specs are cut on CSI section headers (``SECTION 01 32 00`` and the
six-digit form). Drawings are grouped by the sheet prefix (A-, S-, M-,
E-, P-, C-, and the two-letter fire and alarm prefixes). Running headers
and footers that repeat across pages are dropped.

A page with almost no letters is a text-quality failure. When the caller
passes the program's existing OCR function (or a page object and OCR is
installed), the page is read that way. OCR is never required, and this
module does not install anything.
"""
import re

MIN_LETTERS = 40

_CSI = re.compile(
    r"(?im)^[ \t]*(?:section[ \t]+)?"
    r"(\d{2})[ \t]+(\d{2})[ \t]+(\d{2})"
    r"(?:[ \t]*[-–—:.][ \t]*|[ \t]{2,}|[ \t]+)"
    r"([A-Za-z][^\n]{2,90})?"
)
_CSI6 = re.compile(
    r"(?im)^[ \t]*section[ \t]+(\d{2})(\d{2})(\d{2})"
    r"[ \t]*[-–—:.]?[ \t]*([A-Za-z][^\n]{2,90})?"
)
_SHEET = re.compile(
    r"\b(?:SHEET|DWG|DRAWING)\s+"
    r"([A-Z]{1,3})\s*[-.]?\s*(\d{1,4}(?:\.\d+)?)\b"
    r"(?:\s*[-–—:]\s*([^\n]{0,80}))?",
    re.I,
)
_PAGE_NO = re.compile(
    r"(?i)\bpage\s+\d+\s+of\s+\d+\b|\b\d+\s*/\s*\d+\b"
)

# Sheet prefix -> discipline name. Two-letter prefixes are tested first.
PREFIX = (
    ("FP", "fire protection"),
    ("FA", "fire alarm"),
    ("C", "civil"),
    ("L", "landscape"),
    ("S", "structural"),
    ("A", "architectural"),
    ("M", "mechanical"),
    ("P", "plumbing"),
    ("E", "electrical"),
    ("D", "demolition"),
    ("T", "technology"),
)


def letters(text):
    return len(re.sub(r"[^A-Za-z0-9]", "", text or ""))


def _pages(pages):
    """Normalize [(n, text)] or [{page, text, ...}] to dicts."""
    out = []
    for i, item in enumerate(pages or ()):
        if isinstance(item, dict):
            out.append({
                "page": int(item.get("page") or i + 1),
                "text": str(item.get("text") or ""),
                "number": str(item.get("number") or item.get("sheet") or ""),
                "title": str(item.get("title") or ""),
            })
        else:
            n, text = item
            out.append({"page": int(n), "text": str(text or ""),
                        "number": "", "title": ""})
    return out


def strip_running(pages):
    """Drop a short line that shows up on more than half the pages."""
    if len(pages) < 3:
        return pages
    counts = {}
    for p in pages:
        seen = set()
        for line in (p["text"] or "").splitlines():
            key = " ".join(line.split())
            if not key or len(key) > 80 or key in seen:
                continue
            seen.add(key)
            counts[key] = counts.get(key, 0) + 1
    ban = {k for k, n in counts.items()
           if n >= max(3, int(len(pages) * 0.5))}
    if not ban:
        return pages
    for p in pages:
        kept = []
        for line in (p["text"] or "").splitlines():
            key = " ".join(line.split())
            if key in ban or _PAGE_NO.search(key or ""):
                continue
            kept.append(line)
        p["text"] = "\n".join(kept)
    return pages


def _quality(page, ocr):
    """Fill text from OCR when the page has almost no letters.

    ``ocr`` is ``callable(page_dict) -> text`` or None. The program's OCR
    raises when the engine is not installed; the caller wraps that.
    """
    raw = page["text"] or ""
    info = {"page": page["page"], "letters": letters(raw),
            "blank": letters(raw) < MIN_LETTERS, "ocr": ""}
    if info["blank"] and ocr is not None:
        try:
            got = ocr(page) or ""
        except Exception as exc:                       # noqa: BLE001
            info["ocr"] = "failed"
            info["ocr_error"] = str(exc)[:200]
            got = ""
        if letters(got) >= MIN_LETTERS:
            page["text"] = got
            info["ocr"] = "used"
            info["blank"] = False
            info["letters"] = letters(got)
        elif info["ocr"] != "failed":
            info["ocr"] = "empty"
    return info


def _section_marks(text):
    found = []
    for rx in (_CSI, _CSI6):
        for m in rx.finditer(text or ""):
            num = f"{m.group(1)} {m.group(2)} {m.group(3)}"
            title = " ".join((m.group(4) or "").split())
            found.append((m.start(), num, title))
    found.sort(key=lambda x: x[0])
    # The six-digit form and the spaced form can hit the same header.
    kept, last = [], -1
    for pos, num, title in found:
        if last >= 0 and pos - last < 8 and kept and kept[-1][1] == num:
            if title and not kept[-1][2]:
                kept[-1] = (kept[-1][0], num, title)
            continue
        kept.append((pos, num, title))
        last = pos
    return kept


def segment_spec(pages, ocr=None):
    pages = strip_running(_pages(pages))
    quality = [_quality(p, ocr) for p in pages]
    sections = []
    current = None
    for page in pages:
        marks = _section_marks(page["text"])
        if not marks:
            if current is not None:
                current["text"] += "\n" + page["text"]
                if page["page"] not in current["pages"]:
                    current["pages"].append(page["page"])
            continue
        # Text before the first header on this page stays with the previous
        # section (a sentence that crossed the page break).
        if current is not None and marks[0][0] > 0:
            current["text"] += "\n" + page["text"][:marks[0][0]]
            if page["page"] not in current["pages"]:
                current["pages"].append(page["page"])
        for i, (pos, num, title) in enumerate(marks):
            end = marks[i + 1][0] if i + 1 < len(marks) else len(page["text"])
            current = {
                "number": num,
                "title": title,
                "division": num[:2],
                "pages": [page["page"]],
                "text": page["text"][pos:end],
            }
            sections.append(current)
    # Merge consecutive pieces of the same section (the header repeats).
    merged = []
    for sec in sections:
        if merged and merged[-1]["number"] == sec["number"]:
            merged[-1]["text"] += "\n" + sec["text"]
            for p in sec["pages"]:
                if p not in merged[-1]["pages"]:
                    merged[-1]["pages"].append(p)
            if sec["title"] and not merged[-1]["title"]:
                merged[-1]["title"] = sec["title"]
        else:
            merged.append(sec)
    return merged, quality


def discipline(prefix):
    p = (prefix or "").upper()
    for pre, name in PREFIX:
        if p == pre:
            return name
    return ""


def segment_drawings(pages, ocr=None):
    pages = strip_running(_pages(pages))
    quality = [_quality(p, ocr) for p in pages]
    sheets = []
    for page in pages:
        number = page.get("number") or ""
        title = page.get("title") or ""
        if not number:
            m = _SHEET.search(page["text"] or "")
            if m:
                number = f"{m.group(1).upper()}-{m.group(2)}"
                title = title or " ".join((m.group(3) or "").split())
        prefix = ""
        m2 = re.match(r"([A-Za-z]{1,3})", number or "")
        if m2:
            prefix = m2.group(1).upper()
        sheets.append({
            "sheet": number,
            "prefix": prefix,
            "discipline": discipline(prefix),
            "title": title,
            "page": page["page"],
            "text": page["text"],
        })
    return sheets, quality


def blank_report(quality, source):
    return [{"page": q["page"], "source": source,
             "reason": "no extractable text",
             "ocr": q.get("ocr") or ""}
            for q in quality if q.get("blank")]


def ingest(spec_pages=None, drawings=None, ocr=None):
    sections, spec_q = segment_spec(spec_pages or [], ocr=ocr)
    sheets, draw_q = segment_drawings(drawings or [], ocr=ocr)
    blanks = blank_report(spec_q, "spec") + blank_report(draw_q, "drawings")
    return {
        "spec_sections": sections,
        "drawings": sheets,
        "blank_pages": blanks,
        "spec_quality": spec_q,
        "drawing_quality": draw_q,
        "divisions": sorted({s["division"] for s in sections if s["division"]}),
    }


def ingest_pdf(path, kind="spec", ocr=True):
    """Read a PDF with the program's PDF library. OCR uses ``app.ocr``
    when ``ocr`` is true and a page has no text layer. A missing OCR
    engine is reported on the page; it is not an error.
    """
    import fitz

    doc = fitz.open(path)
    try:
        pages = []
        for i, page in enumerate(doc):
            try:
                text = page.get_text() or ""
            except Exception:                           # noqa: BLE001
                text = ""
            pages.append({"page": i + 1, "text": text, "_page": page})
        def _ocr(info):
            if not ocr:
                return ""
            src = info.get("_page")
            if src is None:
                return ""
            from ... import ocr as ocr_mod
            return ocr_mod.ocr_page(src)
        if kind == "drawings":
            sheets, quality = segment_drawings(pages, ocr=_ocr if ocr else None)
            return sheets, quality
        sections, quality = segment_spec(pages, ocr=_ocr if ocr else None)
        return sections, quality
    finally:
        doc.close()
