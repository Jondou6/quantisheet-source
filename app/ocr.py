"""OCR through the Tesseract command-line program."""
import os
import shutil
import subprocess
import sys
import tempfile

import fitz

SCALE = 2          # render at 2x (144 dpi) for better recognition


class OCRUnavailable(RuntimeError):
    pass


def find_tesseract():
    """Installed Tesseract first (Program Files), then PATH - never a copy
    in the current folder (threat model T-017)."""
    if sys.platform.startswith("win"):
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                     os.path.expandvars(r"%LOCALAPPDATA%\Programs")):
            cand = os.path.join(base, "Tesseract-OCR", "tesseract.exe")
            if os.path.exists(cand):
                return cand
    elif sys.platform == "darwin":
        for cand in ("/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract"):
            if os.path.exists(cand):
                return cand
    exe = shutil.which("tesseract")
    here = os.path.normcase(os.path.abspath(os.getcwd()))
    if exe and os.path.normcase(os.path.dirname(os.path.abspath(exe))) \
            != here:
        return exe
    return None


def _run(page, *mode):
    exe = find_tesseract()
    if not exe:
        raise OCRUnavailable(
            "Tesseract is not installed (or not on PATH). Install it to use "
            "OCR: https://tesseract-ocr.github.io/tessdoc/Installation.html")
    pix = page.get_pixmap(matrix=fitz.Matrix(SCALE, SCALE), alpha=False)
    fd, tmp = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        pix.save(tmp)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # no console flash
        out = subprocess.run([exe, tmp, "stdout", *mode], capture_output=True,
                             timeout=300, creationflags=flags)
        if out.returncode != 0:
            raise RuntimeError("tesseract failed: "
                               + out.stderr.decode("utf-8", "ignore")[:300])
        return out.stdout.decode("utf-8", "ignore")
    finally:
        os.unlink(tmp)


def ocr_page(page):
    return _run(page)


def ocr_words(page):
    """Words found on the page, each as {"text", "rect"} in PDF coordinates."""
    words = []
    lines = _run(page, "tsv").splitlines()
    for line in lines[1:]:
        cols = line.split("\t")
        if len(cols) < 12 or not cols[11].strip():
            continue
        try:
            left, top, w, h = (int(c) for c in cols[6:10])
        except ValueError:
            continue
        r = fitz.Rect(left, top, left + w, top + h) / SCALE
        # the pixmap shows the page as displayed; map back to page space
        words.append({"text": cols[11].strip(),
                      "rect": r * page.derotation_matrix})
    return words


def ocr_document(path):
    doc = fitz.open(path)
    try:
        return "\n".join(ocr_page(p) for p in doc)
    finally:
        doc.close()
