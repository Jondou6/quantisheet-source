"""Automatic tagging keeps the page looking and reading the same, and
builds headings, paragraphs, figures, links and fields in reading order;
preflight finds print problems and PDF/X export fixes what it can."""
import fitz
import pytest

from app import accessibility, autotag, preflight

BODY = ("The contractor shall furnish all labor, materials and equipment "
        "required to complete the work shown on the drawings. ") * 3


def _doc(rotate=0):
    d = fitz.open()
    p = d.new_page()
    p.insert_text((72, 80), "ANIMAL SERVICES CLINIC", fontsize=24,
                  fontname="hebo")
    p.insert_text((72, 130), "Section 1 - General", fontsize=14,
                  fontname="hebo")
    p.insert_textbox(fitz.Rect(72, 150, 540, 260), BODY, fontsize=10)
    p.insert_textbox(fitz.Rect(72, 280, 540, 380), BODY, fontsize=10)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 40), 0)
    pix.clear_with(120)
    p.insert_image(fitz.Rect(72, 420, 252, 540), pixmap=pix)
    sh = p.new_shape()
    sh.draw_rect(fitz.Rect(300, 420, 500, 540))
    sh.draw_line((300, 480), (500, 480))
    sh.finish(color=(0, 0, 0), width=1)
    sh.commit()
    p.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(72, 600, 200,
                                                            615),
                   "uri": "https://example.com"})
    p.insert_text((72, 612), "example.com", fontsize=10)
    w = fitz.Widget()
    w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    w.field_name = "owner"
    w.rect = fitz.Rect(72, 650, 300, 670)
    p.add_widget(w)
    p2 = d.new_page()
    p2.insert_text((72, 80), "Page two text", fontsize=10)
    if rotate:
        p2.set_rotation(rotate)
    return fitz.open("pdf", d.tobytes())


def _px(doc):
    return [p.get_pixmap(dpi=60, alpha=False).samples for p in doc]


def test_tagging_keeps_pages_identical_and_builds_structure(tmp_path):
    d = _doc(rotate=90)
    before_px, before_txt = _px(d), [p.get_text() for p in d]
    rep = autotag.tag(d)
    assert _px(d) == before_px                      # looks the same
    assert [p.get_text() for p in d] == before_txt  # reads the same
    assert rep["H1"] == 1 and rep["H2"] >= 1 and rep["P"] >= 2
    assert rep["Figure"] == 1 and rep["Link"] == 1 and rep["Form"] == 1
    out = tmp_path / "t.pdf"
    d.save(str(out), garbage=3)
    t = fitz.open(str(out))
    roles = [r for r, _alt in autotag.structure(t)]
    assert roles[0] == "H1" and "Figure" in roles and "Link" in roles
    assert roles.index("H2") < roles.index("P")
    res = {r["rule"]: r for r in accessibility.check(t)}
    assert res["tagged"]["ok"]
    content = t[0].read_contents()
    assert content.count(b"BDC") == content.count(b"EMC") - \
        content.count(b"BMC")
    assert b"/Artifact BMC" in content              # the box and line
    assert _px(t) == before_px
    with pytest.raises(autotag.TagError):
        autotag.tag(t)


def test_tokenizer_handles_strings_and_inline_images():
    data = (b"q 1 0 0 1 0 0 cm BT /F1 12 Tf 72 700 Td (a \\) b (c)) Tj ET "
            b"BI /W 1 /H 1 /CS /G /BPC 8 ID \x00 EI Q "
            b"0 0 m 10 10 l S")
    ops = [op for _s, _e, op, _a in autotag.operations(data)]
    assert ops == [b"q", b"cm", b"BT", b"Tf", b"Td", b"Tj", b"ET", b"BI",
                   b"Q", b"m", b"l", b"S"]


def test_preflight_and_pdfx(tmp_path):
    d = _doc()
    p = d[0]
    a = p.add_rect_annot(fitz.Rect(400, 600, 500, 650))
    a.update()
    issues = preflight.preflight(d, "PDF/X-4")
    rules = {i["rule"] for i in issues}
    assert {"fonts", "resolution", "boxes", "annotations",
            "intent"} <= rules
    x1a = {i["rule"]: i for i in preflight.preflight(d, "PDF/X-1a")}
    assert x1a["color"]["severity"] == "error"
    out = tmp_path / "x.pdf"
    res = preflight.export_pdfx(d, str(out), use_ghostscript=False)
    o = fitz.open(str(out))
    assert "PDF/X-4" in o.get_xml_metadata()
    assert o.xref_get_key(o.pdf_catalog(), "OutputIntents")[0] != "null"
    assert o.xref_get_key(o[0].xref, "TrimBox")[0] != "null"
    assert not list(o[0].annots())                  # flattened
    left = {i["rule"] for i in res["remaining"]}
    assert "boxes" not in left and "intent" not in left
    assert "fonts" in left                          # needs Ghostscript
