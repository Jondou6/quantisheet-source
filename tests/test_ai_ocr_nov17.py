"""AI Takeoff makes scanned sheets searchable first (Nov 17), made-up scans.

A scanned sheet with no text layer can't give its sheet number, scale or
room names. AI Takeoff's read step now runs OCR on those sheets first (one
Undo step), then reads the set; without Tesseract it says why the sheets
can't be read. OCR itself is stood in for here (no Tesseract needed)."""
import os

import pytest

fitz = pytest.importorskip("fitz")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import acrobat, aitakeoff as ait, ocr  # noqa: E402
from test_gui import win, qapp  # noqa: E402,F401

W, H = 1728, 1152


def scan(doc, text=False):
    page = doc.new_page(width=W, height=H)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 64, 48), False)
    pix.clear_with(235)
    page.insert_image(page.rect, pixmap=pix)
    if text:
        fake_ocr(page)
    return page


def fake_ocr(page):
    for (x, y), s in [((W - 285, H - 182), "FLOOR PLAN"),
                      ((W - 285, H - 110), "SCALE: 1/4\" = 1'-0\""),
                      ((W - 285, H - 60), "A-101")]:
        page.insert_text((x, y), s, fontsize=12, render_mode=3)


def made_up(tmp_path, n=2, text_on=()):
    d = fitz.open()
    for i in range(n):
        scan(d, text=i in text_on)
    v = d.new_page(width=W, height=H)               # a vector sheet
    v.insert_text((100, 100), "GENERAL NOTES", fontsize=12)
    p = tmp_path / "scans.pdf"
    d.save(p)
    return str(p)


def test_ocr_needed_lists_scans_without_text(tmp_path):
    with fitz.open(made_up(tmp_path, 2, text_on=(1,))) as d:
        assert ait.ocr_needed(d) == [0]


def test_read_makes_scans_searchable_then_reads_them(win, tmp_path,
                                                     monkeypatch):
    calls = []

    def fake_make(doc, pages=None, progress=None, skipped=None, **k):
        for n, i in enumerate(pages):
            if progress:
                progress(n, len(pages))
            fake_ocr(doc[i])
        calls.append(list(pages))
        return len(pages)
    monkeypatch.setattr(ocr, "find_tesseract", lambda: "tesseract")
    monkeypatch.setattr(acrobat, "make_searchable", fake_make)
    assert win.open_path(made_up(tmp_path, 1))
    dlg = win.ai_takeoff(show=False)
    rows = dlg.read()
    assert calls == [[0]]
    assert "made searchable first" in dlg.status.text()
    r = rows[0]
    assert r["number"] == "A-101" and r["engines"] == ["rooms"]
    # nothing left to do on a second read
    dlg.read()
    assert calls == [[0]]
    dlg.close()


def test_without_tesseract_it_says_why(win, tmp_path, monkeypatch):
    monkeypatch.setattr(ocr, "find_tesseract", lambda: None)
    assert win.open_path(made_up(tmp_path, 2))
    dlg = win.ai_takeoff(show=False)
    dlg.read()
    assert "2 scanned sheet(s) have no text" in dlg.status.text()
    assert "isn't installed" in dlg.status.text()
    dlg.close()
