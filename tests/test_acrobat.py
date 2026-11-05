"""Tests for the Acrobat-style tools."""
import os
import re
import zipfile

import fitz
import pytest

from app import acrobat, annotate


def _doc(text="Hello world", pages=1):
    d = fitz.open()
    for i in range(pages):
        d.new_page(width=612, height=792).insert_text((72, 100),
                                                      f"{text} {i + 1}")
    return d


def _table_doc():
    d = fitz.open()
    p = d.new_page(width=612, height=792)
    rows = [["Item", "Qty", "Cost"], ["Door", "4", "1200"],
            ["Window", "6", "900"]]
    x0, y0, cw, rh = 72, 100, 120, 24
    for r in range(len(rows) + 1):
        p.draw_line((x0, y0 + r * rh), (x0 + 3 * cw, y0 + r * rh))
    for c in range(4):
        p.draw_line((x0 + c * cw, y0), (x0 + c * cw, y0 + len(rows) * rh))
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            p.insert_text((x0 + c * cw + 6, y0 + r * rh + 16), val,
                          fontsize=11)
    return d


def test_export_text_and_images(tmp_path):
    d = _doc(pages=2)
    t = acrobat.export_text(d, str(tmp_path / "a.txt"))
    assert "Hello world 2" in open(t, encoding="utf-8").read()
    imgs = acrobat.export_images(d, str(tmp_path / "img"), "jpg", dpi=50)
    assert len(imgs) == 2 and all(os.path.getsize(i) > 0 for i in imgs)


def test_export_word(tmp_path):
    d = _table_doc()
    d[0].insert_text((72, 400), "Bold heading", fontname="hebo", fontsize=16)
    path = acrobat.export_word(d, str(tmp_path / "a.docx"))
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode()
        assert "[Content_Types].xml" in z.namelist()
    assert "Bold heading" in xml and "<w:b/>" in xml
    assert "<w:tbl>" in xml and "Window" in xml


def test_export_excel_tables(tmp_path):
    d = _table_doc()
    n = acrobat.export_excel(d, str(tmp_path / "t.xlsx"))
    assert n >= 1
    with zipfile.ZipFile(tmp_path / "t.xlsx") as z:
        sheet = z.read("xl/worksheets/sheet1.xml").decode()
    assert "Window" in sheet and "<v>1200</v>" in sheet


def test_export_excel_text_fallback(tmp_path):
    n = acrobat.export_excel(_doc(), str(tmp_path / "t.xlsx"))
    assert n == 1
    with zipfile.ZipFile(tmp_path / "t.xlsx") as z:
        assert "Hello world 1" in z.read("xl/worksheets/sheet1.xml").decode()


def test_combine_pdfs_and_images(tmp_path):
    a, b = str(tmp_path / "a.pdf"), str(tmp_path / "b.pdf")
    _doc("A", 2).save(a)
    _doc("B", 1).save(b)
    png = str(tmp_path / "c.png")
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 50, 40), False)
    pix.clear_with(255)
    pix.save(png)
    out = acrobat.combine([a, b, png])
    assert out.page_count == 4
    assert [t[1] for t in out.get_toc()] == ["a", "b", "c"]
    assert out[3].get_images()


def test_password_protect(tmp_path):
    path = str(tmp_path / "p.pdf")
    acrobat.save_protected(_doc(), path, open_password="s3cret",
                           owner_password="owner", allow_copy=False)
    d = fitz.open(path)
    assert d.needs_pass
    assert not d.authenticate("wrong")
    assert d.authenticate("s3cret")
    assert "Hello world 1" in d[0].get_text()
    out = str(tmp_path / "u.pdf")
    acrobat.save_unprotected(d, out)
    assert not fitz.open(out).needs_pass
    with pytest.raises(ValueError):
        acrobat.save_protected(_doc(), path)


def test_header_footer_page_numbers():
    d = _doc(pages=3)
    d[1].set_rotation(90)
    acrobat.header_footer(d, {"bottom_center": "Page {page} of {pages}",
                              "top_right": "PROJECT X"})
    assert "Page 1 of 3" in d[0].get_text()
    assert "Page 2 of 3" in d[1].get_text()
    assert "PROJECT X" in d[2].get_text()
    hit = d[0].search_for("Page 1 of 3")[0]
    assert hit.y0 > 700                                 # bottom of the page
    top = d[0].search_for("PROJECT X")[0]
    assert top.y1 < 60 and top.x1 > 500                 # top right


def test_search_and_redact_patterns():
    d = fitz.open()
    p = d.new_page()
    p.insert_text((72, 100), "Call 555-123-4567 or mail bob@example.com")
    p.insert_text((72, 130), "SSN 123-45-6789. Secret word: banana")
    phone = acrobat.find_for_redaction(d, pattern=acrobat.PATTERNS[
        "Phone numbers"])
    email = acrobat.find_for_redaction(d, pattern=acrobat.PATTERNS[
        "Email addresses"])
    ssn = acrobat.find_for_redaction(d, pattern=acrobat.PATTERNS["SSNs"])
    word = acrobat.find_for_redaction(d, text="BANANA", whole_word=True)
    assert len(phone) == 1 and len(email) == 1 and len(ssn) == 1
    assert len(word) == 1
    assert acrobat.find_for_redaction(d, text="BANANA", case=True) == []
    for pno, r in phone + email + ssn + word:
        annotate.apply_op(d, annotate.new_op("add_redact", pno, rect=list(r)))
    t = d[0].get_text()
    assert "555-123-4567" not in t and "bob@example.com" not in t
    assert "123-45-6789" not in t and "banana" not in t
    assert "Call" in t and "Secret word" in t


def test_detect_form_fields():
    d = fitz.open()
    p = d.new_page()
    p.insert_text((72, 100), "Name: ____________________")
    p.insert_text((72, 140), "Date:")
    p.draw_line((110, 142), (300, 142))
    marks = acrobat.detect_fields(d)
    names = [m[2]["name"] for m in marks]
    assert len(marks) == 2
    assert any("Name" in n for n in names) and any("Date" in n for n in names)
    for m in marks:
        annotate.apply_op(d, annotate.new_op(m[1], m[0], **m[2]))
    assert len(list(d[0].widgets())) == 2
    assert acrobat.detect_fields(d) == []               # not added twice


def test_flatten_and_crop_and_reduce(tmp_path):
    d = _doc()
    annotate.apply_op(d, annotate.new_op("add_rect", 0, rect=[100, 100, 200,
                                                              200]))
    acrobat.flatten(d)
    assert d[0].first_annot is None
    acrobat.crop(d, [0], [50, 50, 400, 400])
    assert d[0].cropbox == fitz.Rect(50, 50, 400, 400)
    size = acrobat.reduce_size(d, str(tmp_path / "small.pdf"))
    assert size > 0


def test_stamp():
    d = _doc()
    annotate.apply_op(d, annotate.new_op("add_stamp", 0, rect=[100, 100, 300,
                                                               160],
                                         stamp=0, subject="Approved"))
    page = d[0]
    a = page.first_annot
    assert a.type[1] == "Stamp" and a.info["subject"] == "Approved"


@pytest.mark.skipif(acrobat.tessdata_dir() is None,
                    reason="Tesseract is not installed")
def test_ocr_makes_scans_searchable():
    src = fitz.open()
    src.new_page(width=612, height=300).insert_text(
        (72, 150), "QUANTITY TAKEOFF", fontsize=36)
    pix = src[0].get_pixmap(dpi=150)
    scan = fitz.open()
    page = scan.new_page(width=612, height=300)
    page.insert_image(page.rect, pixmap=pix)            # image only
    assert acrobat.pages_needing_ocr(scan) == [0]
    assert acrobat.make_searchable(scan) == 1
    assert "TAKEOFF" in scan[0].get_text().upper()
    assert acrobat.pages_needing_ocr(scan) == []


def test_text_check_is_quick_and_right():
    """OCR and Accessibility Check no longer read every word of every sheet
    to see whether pages have text (8 s frozen on the plant set)."""
    d = fitz.open()
    d.new_page()                                           # no fonts
    d.new_page().insert_text((72, 72), "GENERAL NOTES AND LEGEND",
                             fontsize=12)
    d.new_page().insert_text((72, 72), "A1", fontsize=12)  # fonts, 2 chars
    heavy = d.new_page()
    heavy.insert_text((72, 72), "SITE PLAN", fontsize=12)
    import random
    rnd = random.Random(7)
    shape = heavy.new_shape()
    for _ in range(6000):                    # a busy drawing: varied lines
        shape.draw_line((rnd.uniform(10, 600), rnd.uniform(90, 780)),
                        (rnd.uniform(10, 600), rnd.uniform(90, 780)))
    shape.finish(width=0.2)
    shape.commit()
    blank, typed, stamp, heavy = d[0], d[1], d[2], d[3]
    assert not acrobat.page_has_text(blank)
    assert acrobat.page_has_text(typed)
    assert not acrobat.page_has_text(stamp)                # under 10 chars
    assert acrobat.page_has_text(stamp, min_chars=1)
    assert acrobat.page_has_text(heavy)
    assert acrobat.pages_needing_ocr(d) == [0, 2]
