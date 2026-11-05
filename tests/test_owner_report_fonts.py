"""Weekly Owner Report: fonts of copied PDF pages (outside review). A PDF
logo, a forecast PDF attachment and the key-plan / work-area plan sheets
bring their own fonts; a page using a non-embedded (base-14) font goes in
as an image, a page whose fonts are embedded stays vector
(show_pdf_page). The built report has no non-embedded font.
Made-up data only."""
import os
from datetime import date

import fitz
import pytest
from PIL import Image

from app import settings
from app.pm import owner_report as orp
from app.pm import owner_report_logs as orl
from app.pm.store import ProjectStore

WE = date(2026, 10, 20)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Pat Morgan"})
    s = ProjectStore(str(tmp_path / "Job"))
    s.data["name"] = "Harbor Point Clubhouse (example)"
    s.set_setting("number", "26-101")
    s.set_setting("project_start", "2026-09-01")
    return s


def _unembedded(doc):
    """Every (page index, base font) whose font program isn't in the PDF -
    checked here straight from get_page_fonts, not through the code under
    test."""
    out = []
    for pno in range(doc.page_count):
        for xref, ext, typ, base, *_ in doc.get_page_fonts(pno, full=True):
            if typ != "Type3" and (ext == "n/a" or not xref):
                out.append((pno, base))
    return out


def _pdf(tmp_path, name, text, embedded, size=(612, 792), lines=1):
    """A made-up one-page source PDF: a frame and text, either in the
    base-14 Helvetica (insert_text's default: not embedded) or in an
    embedded TrueType font."""
    path = str(tmp_path / name)
    w, h = size
    d = fitz.open()
    p = d.new_page(width=w, height=h)
    p.draw_rect(fitz.Rect(4, 4, w - 4, h - 4), color=(0.2, 0.4, 0.7),
                width=2)
    kw = {}
    if embedded:
        p.insert_font(fontname="SrcF", fontfile=os.path.join(
            orl.font_dir(), "LiberationSans-Regular.ttf"))
        kw["fontname"] = "SrcF"
    fs = 14 if h > 150 else 18
    for i in range(lines):
        p.insert_text((14, min(h - 10, 30 + i * (fs + 4))), text,
                      fontsize=fs, **kw)
    d.save(path)
    d.close()
    return path


def _photo(tmp_path, name, seed=0):
    p = str(tmp_path / name)
    Image.effect_noise((400, 300), 40 + seed).convert("RGB").save(p, "JPEG")
    return p


def _report(store, **opts):
    rep = orp.new_report(store, WE, online=False)
    rep["options"].update(opts)
    return rep


def _build(store, rep, tmp_path, name="r.pdf", **kw):
    path = str(tmp_path / name)
    res = orp.build_pdf(store, rep, path, **kw)
    return res, fitz.open(path)


def _pages(res, name):
    m = next(m for m in res["page_map"] if m[0] == name)
    return list(range(m[1] - 1, (m[2] if len(m) > 2 else m[1])))


def _text(doc, pnos=None):
    return "\n".join(doc[i].get_text() for i in
                     (pnos if pnos is not None else range(doc.page_count)))


def _spy_show(monkeypatch):
    """Record show_pdf_page calls (the vector path)."""
    calls = []
    real = fitz.Page.show_pdf_page

    def spy(self, *a, **k):
        calls.append(a)
        return real(self, *a, **k)
    monkeypatch.setattr(fitz.Page, "show_pdf_page", spy)
    return calls


def _with_all(store, tmp_path, embedded):
    """A report with a PDF logo, a forecast PDF attachment, a key plan
    and work areas, all from made-up source PDFs."""
    tag = "emb" if embedded else "b14"
    logo = _pdf(tmp_path, f"logo_{tag}.pdf", "ACME LOGO", embedded,
                (200, 100))
    fc = _pdf(tmp_path, f"fc_{tag}.pdf", "FORECAST TEN DAY", embedded,
              lines=20)
    sheet = _pdf(tmp_path, f"plan_{tag}.pdf", "BLDG A - CLUBHOUSE", embedded,
                 (792, 612))
    t = orp.load_template()
    t["logo"] = logo
    rep = _report(store, key_plan=True, work_areas=True)
    orp.add_photos(store, rep, [_photo(tmp_path, f"p{tag}{i}.jpg", i)
                                for i in range(2)])
    for i, ph in enumerate(rep["photos"]):
        ph["pin"] = {"sheet": sheet, "page": 0, "x": 120 + 80 * i, "y": 150}
    rep["work_areas"] = [{"sheet": sheet, "page": 0,
                          "pts": [[60, 60], [300, 60], [300, 200]],
                          "label": "Bldg A", "note": "Example."}]
    rep["forecast"] = {"mode": "attach", "attach_ref": store.attach(fc)}
    return rep, t


# ------------------------------------------------------------ the checks
def test_font_embedded_reads_get_page_fonts_entries():
    assert not orl.font_embedded((12, "n/a", "Type1", "Helvetica", "F1",
                                  "WinAnsiEncoding", 0))
    assert orl.font_embedded((12, "ttf", "TrueType", "ABCDEF+Arial", "F2",
                              "WinAnsiEncoding", 0))
    assert orl.font_embedded((14, "cff", "Type0", "X", "F3", "Identity-H"))
    assert orl.font_embedded((9, "n/a", "Type3", "", "T3", ""))   # glyph procs
    assert not orl.font_embedded((0, "n/a", "Type1", "Helvetica", "F1", ""))


def test_made_up_sources_are_what_they_say(tmp_path):
    with fitz.open(_pdf(tmp_path, "a.pdf", "Hello", False)) as d:
        assert any(f[1] == "n/a" for f in d.get_page_fonts(0, full=True))
        assert not orl.fonts_embedded(d, 0)
        assert orl.missing_fonts(d, 0)
    with fitz.open(_pdf(tmp_path, "b.pdf", "Hello", True)) as d:
        assert d.get_page_fonts(0, full=True)
        assert orl.fonts_embedded(d, 0)
        assert orl.missing_fonts(d, 0) == []


def test_place_pdf_page_image_for_base14_vector_for_embedded(tmp_path,
                                                             monkeypatch):
    calls = _spy_show(monkeypatch)
    b14 = _pdf(tmp_path, "a.pdf", "PLAN TEXT", False, (792, 612))
    emb = _pdf(tmp_path, "b.pdf", "PLAN TEXT", True, (792, 612))
    box = fitz.Rect(36, 36, 576, 756)
    doc = fitz.open()
    p = doc.new_page(width=612, height=792)
    with fitz.open(b14) as src:
        mode, n = orl.place_pdf_page(p, box, src, 0)
    assert mode == "image" and n > 0 and not calls
    assert "PLAN TEXT" not in p.get_text()
    assert _unembedded(doc) == []
    # fitted and centred as show_pdf_page would place it
    bbox = fitz.Rect(p.get_image_info()[0]["bbox"])
    want_h = 540 * 612 / 792
    assert abs(bbox.width - 540) < 1 and abs(bbox.height - want_h) < 1
    assert abs(bbox.y0 - (36 + (720 - want_h) / 2)) < 1
    p2 = doc.new_page(width=612, height=792)
    with fitz.open(emb) as src:
        mode, n = orl.place_pdf_page(p2, box, src, 0)
    assert mode == "vector" and n == 0 and len(calls) == 1
    assert "PLAN TEXT" in p2.get_text() and not p2.get_images()


def test_base14_sources_leave_no_non_embedded_font(store, tmp_path,
                                                   monkeypatch):
    """Logo, forecast PDF and plan sheet in base-14 Helvetica: the built
    report has no non-embedded font; each went in as an image."""
    calls = _spy_show(monkeypatch)
    rep, t = _with_all(store, tmp_path, embedded=False)
    res, doc = _build(store, rep, tmp_path, template=t)
    for n in ("key_plan", "work_areas", "forecast"):
        assert n in [m[0] for m in res["page_map"]], n
    assert _unembedded(doc) == []
    assert res["unembedded_fonts"] == []
    assert not any("not embedded" in w for w in res["warnings"])
    assert not calls                              # nothing copied as vectors
    all_text = _text(doc)
    for s in ("ACME LOGO", "FORECAST TEN DAY", "BLDG A - CLUBHOUSE"):
        assert s not in all_text, s               # pictures of text now
    # the logo is one image, reused on page 1 and the log pages
    assert doc[0].get_images()
    fc = _pages(res, "forecast")[0]
    assert len(doc[fc].get_images()) == 1
    for name in ("key_plan", "work_areas"):
        pg = doc[_pages(res, name)[0]]
        assert pg.get_images(), name
        assert pg.first_annot is None
    assert res["raster_bytes"] > 0
    # the key plan's table and legend are still the report's own text
    assert "Location / caption" in _text(doc, _pages(res, "key_plan"))
    assert "Bldg A" in _text(doc, _pages(res, "work_areas"))


def test_embedded_sources_stay_vector(store, tmp_path, monkeypatch):
    calls = _spy_show(monkeypatch)
    rep, t = _with_all(store, tmp_path, embedded=True)
    res, doc = _build(store, rep, tmp_path, template=t)
    assert _unembedded(doc) == []
    assert res["raster_bytes"] == 0
    # logo (page 1 + log pages), forecast, key plan, work areas
    assert len(calls) >= 4
    assert "ACME LOGO" in doc[0].get_text()
    fc = _pages(res, "forecast")[0]
    assert "FORECAST TEN DAY" in doc[fc].get_text()
    assert not doc[fc].get_images()
    for name in ("key_plan", "work_areas"):
        pg = doc[_pages(res, name)[0]]
        assert "BLDG A - CLUBHOUSE" in pg.get_text(), name
        assert not pg.get_images(), name
    # the pin dots are vectors, the pin numbers the report's font
    pins = [d for d in doc[_pages(res, "key_plan")[0]].get_drawings()
            if d.get("fill") and all(abs(a - b) <= 0.05 for a, b in
                                     zip(d["fill"], orp.PIN_COLOR))]
    assert len(pins) >= 2


def test_forecast_attachment_alone(tmp_path):
    for emb in (False, True):
        src = _pdf(tmp_path, f"f{emb}.pdf", "TEN DAY OUTLOOK", emb)
        doc = fitz.open()
        res = orl.add_forecast_page(doc, {}, {"mode": "attach",
                                              "attach_path": src}, {})
        assert res["totals"]["mode"] == "attach"
        assert _unembedded(doc) == []
        assert ("TEN DAY OUTLOOK" in doc[0].get_text()) is emb
        assert bool(doc[0].get_images()) is not emb


def test_estimate_counts_the_rasterised_forecast(store, tmp_path):
    """The size estimate adds what a base-14 forecast PDF costs as an
    image (rendered as the build renders it)."""
    rep = _report(store)
    rep["forecast"] = {"mode": "table", "rows": [], "as_of": "2026-10-20"}
    e0 = orp.estimate_size(store, rep)
    r0 = orp.build_pdf(store, rep)["bytes"]
    src = _pdf(tmp_path, "fc.pdf", "FORECAST TEN DAY RAIN 60%", False,
               lines=30)
    rep["forecast"] = {"mode": "attach", "attach_ref": store.attach(src)}
    e1 = orp.estimate_size(store, rep)
    r1 = orp.build_pdf(store, rep)["bytes"]
    de, dr = e1 - e0, r1 - r0
    assert de > 0 and dr > 0
    assert abs(de - dr) <= 0.25 * dr + 15000, (de, dr)
    # an embedded-font forecast stays vector: no image allowance
    src2 = _pdf(tmp_path, "fc2.pdf", "FORECAST", True)
    rep["forecast"] = {"mode": "attach", "attach_ref": store.attach(src2)}
    assert orp.estimate_size(store, rep) == e0
