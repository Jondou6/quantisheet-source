"""Tests for Create PDF, organize pages, visual compare, export, protect
extras and the Action Wizard."""
import os
import sys

import fitz
import pytest

from app import acrobat, acrobat2, annotate


def _doc(texts):
    d = fitz.open()
    for t in texts:
        d.new_page(width=612, height=792).insert_text((72, 100), t)
    return d


def _save(d, path):
    d.save(str(path))
    return str(path)


def test_create_from_text_html_image(tmp_path):
    t = tmp_path / "notes.txt"
    t.write_text("Line one\nLine two <not html>\n" * 3, encoding="utf-8")
    d = acrobat2.create_pdf(str(t))
    assert "Line two <not html>" in d[0].get_text()
    h = tmp_path / "page.html"
    h.write_text("<h1>Site Report</h1><p>All <b>good</b>.</p>",
                 encoding="utf-8")
    d = acrobat2.create_pdf(str(h))
    assert "Site Report" in d[0].get_text()
    png = str(tmp_path / "pic.png")
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 30), False)
    pix.clear_with(128)
    pix.save(png)
    assert acrobat2.create_pdf(png)[0].get_images()
    with pytest.raises(ValueError):
        acrobat2.create_pdf(str(tmp_path / "x.unknown"))


def _office_or_skip(fn):
    try:
        return fn()
    except RuntimeError as e:
        pytest.skip(f"Office not available: {e}")


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows only")
def test_create_from_word(tmp_path):
    src = _doc(["Hello from Word conversion"])
    docx = acrobat.export_word(src, str(tmp_path / "w.docx"))
    d = _office_or_skip(lambda: acrobat2.create_pdf(docx))
    assert "Hello from Word conversion" in d[0].get_text()


@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows only")
def test_export_powerpoint(tmp_path):
    out = str(tmp_path / "deck.pptx")
    _office_or_skip(lambda: acrobat2.export_powerpoint(
        _doc(["Slide A", "Slide B"]), out))
    import zipfile
    with zipfile.ZipFile(out) as z:
        slides = [n for n in z.namelist()
                  if n.startswith("ppt/slides/slide") and n.endswith(".xml")]
    assert len(slides) == 2


def test_split(tmp_path):
    d = _doc(["A1", "A2", "B1", "B2", "B3"])
    out = acrobat2.split(d, str(tmp_path / "every2"), every=2, base="set")
    assert [fitz.open(p).page_count for p in out] == [2, 2, 1]
    d.set_toc([[1, "Arch", 1], [1, "Struct", 3]])
    out = acrobat2.split(d, str(tmp_path / "bm"), by_bookmarks=True)
    assert [fitz.open(p).page_count for p in out] == [2, 3]
    assert "Struct" in os.path.basename(out[1])
    with pytest.raises(ValueError):
        acrobat2.split(_doc(["x"]), str(tmp_path / "n"), by_bookmarks=True)


def test_replace_and_duplicate(tmp_path):
    d = _doc(["one", "two", "three"])
    new = _save(_doc(["TWO-rev1", "THREE-rev1"]), tmp_path / "rev.pdf")
    assert acrobat2.replace_pages(d, 1, 2, new) == 2
    assert [p.get_text().strip() for p in d] == ["one", "TWO-rev1",
                                                 "THREE-rev1"]
    acrobat2.duplicate_page(d, 0)
    assert [p.get_text().strip() for p in d][:2] == ["one", "one"]


def test_visual_compare(tmp_path):
    a = fitz.open()
    for _ in range(2):
        p = a.new_page()
        p.draw_rect(fitz.Rect(100, 100, 300, 300), width=2)
    b = fitz.open(stream=a.tobytes(), filetype="pdf")
    b[1].draw_line((100, 400), (400, 400), width=3)       # added on page 2
    pa, pb = _save(a, tmp_path / "a.pdf"), _save(b, tmp_path / "b.pdf")
    out, stats = acrobat2.visual_compare(pa, pb)
    assert out.page_count == 2
    assert stats[0] == 0 and stats[1] > 0
    pix = out[1].get_pixmap(dpi=72)
    green = pix.pixel(250, 400)
    assert green[1] > 120 and green[0] < 80                # drawn in green


def test_export_html(tmp_path):
    out = acrobat2.export_html(_doc(["Hello web"]), str(tmp_path / "a.html"))
    assert "Hello web" in open(out, encoding="utf-8").read()


def test_sanitize_and_properties():
    d = _doc(["body"])
    d.set_metadata({"author": "Secret Person", "title": "T"})
    d.embfile_add("hidden.txt", b"secret")
    annotate.apply_op(d, annotate.new_op("add_rect", 0,
                                         rect=[100, 100, 200, 200]))
    acrobat2.sanitize(d)
    assert not (d.metadata.get("author") or "")
    assert d.embfile_count() == 0
    assert d[0].first_annot is not None                    # markups kept
    acrobat2.set_properties(d, title="Floor Plan", author="Jon")
    assert d.metadata["title"] == "Floor Plan"


def test_action_wizard(tmp_path):
    a = _save(_doc(["first file"]), tmp_path / "a.pdf")
    b = _save(_doc(["second file", "page two"]), tmp_path / "b.pdf")
    txt = tmp_path / "c.txt"
    txt.write_text("plain text file", encoding="utf-8")
    res = acrobat2.run_batch([a, b, str(txt)],
                             ["page_numbers", "watermark", "reduce"],
                             str(tmp_path / "out"), {"watermark": "COPY"})
    assert all(not str(r).startswith("ERROR") for _, r in res), res
    out_b = fitz.open(res[1][1])
    assert "Page 2 of 2" in out_b[1].get_text()
    assert "COPY" in out_b[0].get_text()
    res = acrobat2.run_batch([a], ["protect"], str(tmp_path / "locked"),
                             {"password": "pw"})
    assert fitz.open(res[0][1]).needs_pass


def test_callout_and_bordered_textbox():
    d = _doc(["x"])
    annotate.apply_op(d, annotate.new_op("add_callout", 0,
                                         rect=[300, 100, 450, 130],
                                         tip=[150, 300], text="Check this"))
    annotate.apply_op(d, annotate.new_op("add_textbox", 0,
                                         rect=[100, 500, 250, 550],
                                         text="RECEIVED", border=True))
    page = d[0]
    types = [a.type[1] for a in page.annots()]
    assert types == ["FreeText", "FreeText"]
    items = {i["type"] for i in annotate.markup_items(d)}
    assert "Text Box" in items
