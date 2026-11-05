"""Reading vendor invoices and receipts (P1-08). Local only: the PDF text
layer first, then local Tesseract for scans and photos. No cloud OCR.

extract(path, engine) -> {field: (value, confidence)} where confidence is
'high' (green), 'medium' (yellow) or 'low' (red: must be confirmed).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile

from . import cents, fileguard

HIGH, MEDIUM, LOW = "high", "medium", "low"
COLOUR = {HIGH: "green", MEDIUM: "yellow", LOW: "red"}
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp")

_NUM = r"\$?\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{2})|[0-9]+\.[0-9]{2})"
_DATE = r"(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})"
PATTERNS = {
    "invoice_no": r"invoice\s*(?:no\.?|number|#)\s*[:#]?\s*([A-Z0-9][A-Z0-9-]{2,})",
    "invoice_date": r"(?:invoice\s+)?date\s*[:]?\s*" + _DATE,
    "due_date": r"due\s*(?:date)?\s*[:]?\s*" + _DATE,
    "tax": r"(?:sales\s+)?tax\s*[:]?\s*" + _NUM,
    "total": r"(?:invoice\s+|amount\s+due|grand\s+)?total(?:\s+due)?\s*[:]?\s*" + _NUM,
}


KNOWN_DIRS = (r"C:\Program Files\Tesseract-OCR",
              r"C:\Program Files (x86)\Tesseract-OCR") \
    if sys.platform == "win32" else ()


def find_tesseract():
    """The Tesseract program from absolute PATH folders (and its usual
    Windows install folders) only: never the current folder or a relative
    PATH entry, so a tesseract.exe dropped next to a document can't run."""
    name = "tesseract.exe" if sys.platform == "win32" else "tesseract"
    dirs = [d for d in os.environ.get("PATH", "").split(os.pathsep)
            if d and os.path.isabs(d)] + list(KNOWN_DIRS)
    for d in dirs:
        p = os.path.join(d, name)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None


class TesseractOCR:
    """Local Tesseract (installed separately, like QuantiSheet's OCR)."""

    def __init__(self, exe=None):
        self.exe = exe or find_tesseract()

    def available(self) -> bool:
        return bool(self.exe)

    def read(self, image_path) -> list[tuple[str, int]]:
        """[(word, confidence 0-100)] from Tesseract's TSV output."""
        if not self.available():
            raise RuntimeError("Tesseract OCR is not installed")
        out = subprocess.run([self.exe, image_path, "stdout", "tsv"],
                             capture_output=True, text=True, check=True,
                             timeout=120).stdout
        words = []
        for row in out.splitlines()[1:]:
            parts = row.split("\t")
            if len(parts) >= 12 and parts[11].strip():
                try:
                    conf = int(float(parts[10]))
                except ValueError:
                    conf = 0
                words.append((parts[11], conf))
        return words


def _norm_date(s: str) -> str:
    if re.match(r"\d{4}-\d{2}-\d{2}$", s):
        return s
    m, d, y = s.split("/")
    y = int(y)
    y = y + 2000 if y < 100 else y
    return f"{y:04d}-{int(m):02d}-{int(d):02d}"


def _conf_for(span_words, word_conf):
    if word_conf is None:
        return HIGH
    confs = [c for w, c in word_conf if w and any(w in s for s in span_words)]
    if not confs:
        return LOW
    m = min(confs)
    return HIGH if m >= 85 else MEDIUM if m >= 60 else LOW


def parse(text: str, vendors=(), word_conf=None) -> dict:
    """Suggest fields from invoice text. word_conf: [(word, conf)] from OCR
    (None for a digital text layer, which reads exactly)."""
    out = {}
    low = text.lower()
    vend = None
    for v in sorted(vendors, key=len, reverse=True):
        if v and v.lower() in low:
            vend = v
            break
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    if vend:
        out["vendor"] = (vend, _conf_for(vend.split(), word_conf)
                         if word_conf else HIGH)
    elif first:
        out["vendor"] = (first, MEDIUM if word_conf is None else
                         min(_conf_for(first.split(), word_conf), MEDIUM,
                             key=[HIGH, MEDIUM, LOW].index))
    for k, pat in PATTERNS.items():
        hits = list(re.finditer(pat, text, re.I))
        if k == "total":
            hits = [h for h in hits if not re.search(
                r"sub\s*$", text[max(0, h.start() - 4):h.start()], re.I)]
        if k == "invoice_date":
            hits = [h for h in hits if not re.search(
                r"due\s*$", text[max(0, h.start() - 5):h.start()], re.I)]
        if not hits:
            continue
        h = hits[-1] if k == "total" else hits[0]
        raw = h.group(1)
        try:
            val = _norm_date(raw) if "date" in k else \
                cents.text(cents.parse_amount(raw)) if k in ("total", "tax") \
                else raw
        except (ValueError, cents.MoneyError):
            continue
        out[k] = (val, _conf_for([raw], word_conf))
    return out


def page_text(path) -> str:
    import fitz
    with fitz.open(path) as doc:
        return "\n".join(p.get_text() for p in doc)


def extract(path, vendors=(), engine=None) -> dict:
    """Text layer first; scans and photos go through local OCR."""
    fileguard.refuse_company_file(path)
    ext = os.path.splitext(path)[1].lower()
    text = ""
    if ext == ".pdf":
        text = page_text(path)
        if text.strip():
            return {"text": text, "source": "text layer",
                    "fields": parse(text, vendors)}
        # Render the scan in a private temp folder (never next to the
        # user's file) and always remove it.
        import fitz
        tmp = tempfile.mkdtemp(prefix="qsbo-ocr-")
        try:
            img = os.path.join(tmp, "page1.png")
            with fitz.open(path) as doc:
                doc[0].get_pixmap(dpi=300).save(img)
            words = (engine or TesseractOCR()).read(img)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        text = " ".join(w for w, _ in words)
        return {"text": text, "source": "ocr",
                "fields": parse(text, vendors, word_conf=words)}
    elif ext not in IMAGE_EXTS:
        raise ValueError(f"{ext or 'this file'} is not a PDF or image")
    engine = engine or TesseractOCR()
    words = engine.read(path)
    text = " ".join(w for w, _ in words)
    return {"text": text, "source": "ocr",
            "fields": parse(text, vendors, word_conf=words)}
