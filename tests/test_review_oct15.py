"""Fixes from the Oct 15 code review: Auto Scale on real title-block text,
the name-only room crash, formula limits, cost-book regions and sheet
numbers across a set."""
import os
import time

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import assemblies, autotakeoff, costbook, sheets, takeoff  # noqa


# ---- R1 Auto Scale ---------------------------------------------------------------
@pytest.mark.parametrize("text, want", [
    ('P1.02 SCALE: 1/2" = 1\'', 36.0),
    ('02\n1/2" = 1\'-0"', 36.0),             # sheet number tail, new line
    ('02 1/2" = 1\'-0"', 36.0),              # leading zero isn't 2-1/2"
    ('09\n1/2" = 1\'-0"', 36.0),
    ('1 1/2" = 1\'-0"', 108.0),
    ('1-1/2" = 1\'-0"', 108.0),
    ('SCALE: 3/4"=1\'-0"', 54.0),
    ('SCALE: 1" = 40\'', 1.8),
])
def test_scale_from_real_title_block_text(text, want):
    sc = takeoff.main_scale(text)
    assert sc is not None and sc[1] == pytest.approx(want)


def test_frac_never_raises():
    assert takeoff._frac("02\n1/2") == pytest.approx(2.5)
    assert takeoff._frac("1-1/2") == pytest.approx(1.5)
    assert takeoff._frac("x/2") == 0.0


def test_scale_next_to_the_word_scale_wins():
    t = 'NOTE: 6" = 1\'-0" BOX\nPLAN\nSCALE: 1/4" = 1\'-0"'
    assert takeoff.main_scale(t)[1] == 18.0


def test_standard_scales():
    for fam in takeoff.PRESETS.values():
        for _, (ppu, unit) in fam:
            assert takeoff.is_standard(ppu, unit)
    assert not takeoff.is_standard(9.5 * 72, "ft")       # 9-1/2" = 1'
    assert not takeoff.is_standard(2.5 * 72, "ft")


def _sheet(doc, number, scale_lines, project="ACC778"):
    pg = doc.new_page(width=2592, height=1728)
    pg.insert_text((300, 400), "PROCESS MECHANICAL PLAN", fontsize=20)
    for i, ln in enumerate(scale_lines):
        pg.insert_text((300, 440 + 14 * i), ln, fontsize=10)
    # title block: big project number and the real sheet number
    pg.insert_text((2250, 1560), project, fontsize=26)
    pg.insert_text((2250, 1610), "SHEET", fontsize=8)
    pg.insert_text((2250, 1660), number, fontsize=30)
    return pg


def test_scan_never_applies_an_odd_scale_and_fixes_repeated_numbers():
    doc = fitz.open()
    for k in range(10):
        _sheet(doc, f"P1.{k + 1:02d}", ["02", '1/2" = 1\'-0"'])
    _sheet(doc, "P2.01", ['SCALE: 9 1/2" = 1\'-0"'])   # odd: not applied
    rows = sheets.scan(doc)
    for r in rows[:10]:
        assert r["scale"] and r["scale"][1] == 36.0
        assert r["number"].startswith("P1."), r
    assert rows[10]["scale"] is None and rows[10]["odd"][1] == 9.5 * 72
    nums = [r["number"] for r in rows]
    assert "ACC778" not in nums and len(set(nums)) == len(nums)


def test_title_drops_drafter_initials():
    assert sheets._strip_initials("COVER LRK CJB") == "COVER"
    assert sheets._strip_initials("BLOWER MCC") == "BLOWER MCC"
    assert sheets._strip_initials("SITE PLAN") == "SITE PLAN"


def test_discipline_codes():
    for good in ("A-101", "P1.02", "FP-2", "M-501A", "C3.1", "E101"):
        assert sheets.DISCIPLINE.match(good), good
    assert not sheets.DISCIPLINE.match("ACC778")


# ---- R2 name-only room ------------------------------------------------------------
def test_name_only_room_with_an_implausible_first_pass(monkeypatch):
    doc = fitz.open()
    pg = doc.new_page(width=1728, height=1152)
    pg.insert_text((400, 400), "STORAGE 104", fontsize=10)

    class FakePlan:
        unit = "ft"
        pts_per_ft = 18.0

        def __init__(self, page, scale, **kw):
            self.calls = 0

        def detect(self, pt, others, expected=None, max_sf=None):
            self.calls += 1
            sq = 9000.0 if self.calls == 1 else 12000.0
            return {"sqft": sq, "pts": [fitz.Point(0, 0), fitz.Point(10, 0),
                                        fitz.Point(10, 10)]}

        def claim(self, polys, grow=1):
            pass

        def to_units(self, sf):
            return sf
    monkeypatch.setattr(autotakeoff, "Plan", FakePlan)
    found, missed = autotakeoff.all_rooms(pg, {"ppu": 18.0, "unit": "ft"})
    assert not found and any(t["name"] == "STORAGE 104" for t in missed)


# ---- R3 formulas -----------------------------------------------------------------
def test_formula_limits():
    t = time.time()
    with pytest.raises(assemblies.FormulaError):
        assemblies.evaluate("9**9**9", {})
    assert time.time() - t < 0.1
    with pytest.raises(assemblies.FormulaError):
        assemblies.evaluate("10**20", {})
    with pytest.raises(assemblies.FormulaError):
        assemblies.evaluate("1+" * 300 + "1", {})
    with pytest.raises(assemblies.FormulaError):
        assemblies.evaluate("abs(" * 60 + "1" + ")" * 60, {})
    assert assemblies.evaluate("2**10", {}) == 1024
    assert assemblies.evaluate("ceil(length/8)*1.1", {"length": 80}) == \
        pytest.approx(11.0)


# ---- R4 regions ------------------------------------------------------------------
def test_region_aliases():
    b = costbook.Book({"name": "T", "index": {"national": 1.0,
                                              "South Carolina": 0.9},
                       "rates": {"national": {"Laborer": 40.0},
                                 "South Carolina": {"Laborer": 30.0}}})
    assert b.resolve_region("SC") == "South Carolina"
    assert b.resolve_region("south carolina") == "South Carolina"
    assert b.resolve_region("Charleston, South Carolina") == "South Carolina"
    assert b.resolve_region("XX") is None
    assert b.factor("SC") == b.factor("South Carolina")
    assert b.labor_rates("SC")["Laborer"] == b.labor_rates(
        "South Carolina")["Laborer"]


def test_unknown_region_is_reported(monkeypatch):
    b = costbook.Book({"name": "T", "index": {"national": 1.0,
                                              "South Carolina": 0.9}})
    doc = fitz.open()
    doc.new_page()
    with pytest.raises(ValueError):
        assemblies.set_costbook(doc, b, region="XX")
    assemblies.set_costbook(doc, b, region="SC")
    assert assemblies.read_job(doc)["costbook"]["region"] == "South Carolina"
    rows, totals, errors = assemblies.rollup(doc, book=b, region="XX")
    assert any("no region 'XX'" in e for e in errors)


# ---- review 2: R13 OCR, R14 sanitize, R15 PowerPoint, R16 DocuSign --------------
def _raster_page(doc, w, h, text_pts=None, noise=False):
    import numpy as np
    pg = doc.new_page(width=w, height=h)
    if noise:
        rng = np.random.default_rng(1)
        arr = rng.integers(40, 220, size=(300, 450, 3), dtype=np.uint8)
        pix = fitz.Pixmap(fitz.csRGB, 450, 300, arr.tobytes(), False)
    else:
        src = fitz.open()
        p = src.new_page(width=w, height=h)
        for (x, y), t in (text_pts or []):
            p.insert_text((x, y), t, fontsize=14)
        pix = p.get_pixmap(dpi=150)
    pg.insert_image(pg.rect, pixmap=pix)
    return pg


def test_photo_pages_are_not_ocrd():
    from app import acrobat
    d = fitz.open()
    _raster_page(d, 612, 400, noise=True)
    _raster_page(d, 612, 400, [((72, 150), "QUANTITY TAKEOFF")])
    assert acrobat.is_photo(d[0]) and not acrobat.is_photo(d[1])
    assert acrobat._plausible("TAKEOFF") and acrobat._plausible("A-101")
    assert not acrobat._plausible("«.") and not acrobat._plausible("~")
    assert acrobat.ocr_dpi(d[0]) == 300
    big = d.new_page(width=36 * 72, height=24 * 72)
    assert acrobat.ocr_dpi(big) == 200


@pytest.mark.skipif(__import__("app.ocr", fromlist=["x"]).find_tesseract()
                    is None, reason="Tesseract is not installed")
def test_ocr_in_tiles_on_a_big_sheet():
    from app import acrobat
    d = fitz.open()
    words = [((200 + 600 * i, 300 + 400 * j), f"SHEET{i}{j} DIGESTER")
             for i in range(4) for j in range(4)]
    _raster_page(d, 36 * 72, 24 * 72, words)
    _raster_page(d, 612, 400, noise=True)
    skipped = []
    t = time.time()
    assert acrobat.make_searchable(d, [0, 1], skipped=skipped) == 1
    took = time.time() - t
    assert skipped == [1] and not d[1].get_text().strip()
    text = d[0].get_text().upper()
    assert text.count("DIGESTER") >= 13, text[:400]
    assert took < 60


def _damaged(tmp_path):
    d = fitz.open()
    for i in range(3):
        d.new_page().insert_text((72, 72), f"Sheet {i}")
    d.set_metadata({"author": "Secret"})
    d.embfile_add("x.txt", b"hidden")
    p = tmp_path / "ok.pdf"
    d.save(str(p))
    data = bytearray(p.read_bytes())
    i = data.rfind(b"startxref")
    data[i:i + 20] = b"startxref\n99999999\n"[:20].ljust(20, b" ")
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(bytes(data))
    return str(bad)


def test_sanitize_damaged_file(tmp_path):
    from app import acrobat2
    d = fitz.open(_damaged(tmp_path))
    assert d.is_repaired
    t = time.time()
    acrobat2.sanitize(d)
    assert time.time() - t < 15
    assert d.page_count == 3 and "Sheet 1" in d[1].get_text()
    assert d.embfile_count() == 0 and not d.metadata.get("author")


def test_powerpoint_without_office(tmp_path):
    pytest.importorskip("pptx")
    from app import acrobat2
    d = fitz.open()
    for i in range(2):
        d.new_page(width=1224, height=792).insert_text((72, 72), f"S{i}")
    out = acrobat2.export_powerpoint(d, str(tmp_path / "deck.pptx"))
    from pptx import Presentation
    prs = Presentation(out)
    assert len(prs.slides) == 2


def test_docusign_checks_setup_first(monkeypatch):
    from app import esign_docusign as ds, settings
    monkeypatch.setattr(settings, "get", lambda k, d=None: None)
    with pytest.raises(ds.DocuSignError, match="Set up DocuSign"):
        ds.status({})
    monkeypatch.setattr(ds, "configured", lambda: True)
    with pytest.raises(ds.DocuSignError, match="envelope id"):
        ds.status({"no": "id"})
