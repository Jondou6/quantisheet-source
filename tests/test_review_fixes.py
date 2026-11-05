"""Fixes from the code review: job data survives page operations and
scrubbing, OCR keeps markups, content ops are idempotent, rotated pages use
one coordinate convention, and op ids match the web client."""
import os

import fitz
import pytest

from app import (acrobat, acrobat2, annotate, autocount, autotakeoff,
                 jobdata, page_ops, pagetools, rules, sheets)
from app.collab import oplog

_KEEP = []


def _c(r):
    return fitz.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)


def _doc(n=3, scales=(10, 20, 30)):
    d = fitz.open()
    for i in range(n):
        d.new_page(width=600, height=400).insert_text((50, 50 + i),
                                                      f"sheet {i}")
    for i, ppu in enumerate(scales[:n]):
        annotate.apply_op(d, annotate.new_op("set_scale", i, ppu=ppu,
                                             unit="ft"))
    return d


def _ppu(d):
    s = annotate.read_scales(d)
    return [s.get(i, {}).get("ppu") for i in range(d.page_count)]


# ---- scales stay with their sheets ----------------------------------------------

def test_scales_follow_moved_deleted_and_inserted_pages(tmp_path):
    d = _doc()
    pagetools.move(d, 0, 2)
    assert _ppu(d) == [20, 30, 10]
    pagetools.delete(d, [0])
    assert _ppu(d) == [30, 10]
    pagetools.insert_blank(d, 0)
    assert _ppu(d) == [30, None, 10]
    src = _doc(2, scales=(36, 72))
    path = str(tmp_path / "details.pdf")
    src.save(path)
    pagetools.insert_pdf(d, path, 0)              # after the first page
    assert _ppu(d) == [30, 36, 72, None, 10]
    acrobat2.duplicate_page(d, 4)
    assert _ppu(d) == [30, 36, 72, None, 10, 10]
    page_ops.delete_pages(d, [1, 2])
    assert _ppu(d) == [30, None, 10, 10]


def test_replaced_sheet_keeps_its_scale(tmp_path):
    d = _doc()
    new = fitz.open()
    new.new_page(width=600, height=400).insert_text((50, 50), "rev B")
    path = str(tmp_path / "revb.pdf")
    new.save(path)
    acrobat2.replace_pages(d, 1, 1, path)
    assert _ppu(d) == [10, 20, 30]
    assert "rev B" in d[1].get_text()


def test_viewports_move_with_their_page():
    d = _doc()
    annotate.apply_op(d, annotate.new_op("set_scale", 2, viewport={
        "name": "D1", "rect": [0, 0, 100, 100], "ppu": 72, "unit": "ft"}))
    pagetools.move(d, 2, 0)
    assert [v["name"] for v in annotate.read_viewports(d, 0)] == ["D1"]
    assert not annotate.read_viewports(d, 2)


# ---- job data goes where the pages go ---------------------------------------------

def test_split_extract_combine_carry_job_data(tmp_path):
    d = _doc()
    from app import estimate
    estimate.set_price(d, "Wall", "length", "ft", unit_cost=12.5)
    parts = acrobat2.split(d, str(tmp_path / "parts"), every=2)
    p2 = fitz.open(parts[1])
    assert _ppu(p2) == [30]
    assert "quantisheet_estimate.json" in p2.embfile_names()
    out = str(tmp_path / "x.pdf")
    pagetools.extract(d, [2, 0], out)
    assert _ppu(fitz.open(out)) == [10, 30]
    a, b = str(tmp_path / "a.pdf"), str(tmp_path / "b.pdf")
    _doc(1, scales=(18,)).save(a)
    _doc(2, scales=(36, 9)).save(b)
    combined = acrobat.combine([a, b])
    assert _ppu(combined) == [18, 36, 9]
    merged = page_ops.merge([b, a], str(tmp_path / "m.pdf"))
    assert _ppu(fitz.open(merged)) == [36, 9, 18]


def test_remove_hidden_information_keeps_takeoff_data():
    d = _doc()
    d.embfile_add("secret.txt", b"secret")
    acrobat2.sanitize(d)
    assert "secret.txt" not in d.embfile_names()
    assert _ppu(d) == [10, 20, 30]
    acrobat2.sanitize(d, keep_job=False)
    assert d.embfile_count() == 0


# ---- OCR keeps the page and its markups ----------------------------------------------

def test_text_layer_keeps_markups_fields_and_links():
    d = fitz.open()
    page = d.new_page(width=612, height=300)
    _KEEP.append(page)
    annotate.apply_op(d, annotate.new_op("set_scale", 0, ppu=10, unit="ft"))
    annotate.apply_op(d, annotate.new_op(
        "add_polygon", 0, pts=[[20, 20], [120, 20], [120, 80]],
        label="Slab", measure={"type": "area", "value": 50,
                               "unit": "sq ft", "group": "Slab"}))
    annotate.apply_op(d, annotate.new_op("add_field", 0,
                                         rect=[300, 20, 400, 40],
                                         ftype="text", name="Notes"))
    page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(450, 20, 500, 40),
                      "uri": "https://example.com"})
    before = sorted(a.type[1] for a in page.annots())
    links = [dict(x) for x in page.get_links()]
    ocr = fitz.open()
    op = ocr.new_page(width=612, height=300)
    op.insert_text((72, 150), "QUANTITY TAKEOFF", fontsize=36)
    assert acrobat.add_text_layer(page, op) == 2
    page = d[0]
    _KEEP.append(page)
    assert "TAKEOFF" in page.get_text()
    hit = page.search_for("TAKEOFF")[0]
    want = op.search_for("TAKEOFF")[0]
    assert abs(hit.x0 - want.x0) < 3 and abs(hit.x1 - want.x1) < 12
    assert sorted(a.type[1] for a in page.annots()) == before
    assert [w.field_name for w in page.widgets()] == ["Notes"]
    assert [x.get("uri") for x in page.get_links()] == \
        [x.get("uri") for x in links]
    assert annotate.takeoff_items(d)[0]["value"] == pytest.approx(50)


# ---- content ops only apply once ----------------------------------------------------

def test_content_ops_are_idempotent():
    d = fitz.open()
    d.new_page()
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 4, 4), False)
    pix.clear_with(200)
    import base64
    op = annotate.new_op("add_image", 0, rect=[10, 10, 60, 60],
                         data=base64.b64encode(pix.tobytes("png")).decode())
    assert annotate.apply_op(d, op)
    assert not annotate.apply_op(d, op)               # replayed: no-op
    assert len(d[0].get_images()) == 1
    d[0].insert_text((100, 100), "CONFIDENTIAL")
    red = annotate.new_op("add_redact", 0, rect=[95, 85, 220, 105])
    assert annotate.apply_op(d, red)
    assert not annotate.apply_op(d, red)
    span = annotate.new_op("replace_span", 0, rect=[10, 200, 100, 220],
                           text="NEW")
    assert annotate.apply_op(d, span)
    assert not annotate.apply_op(d, span)
    assert d[0].get_text().count("NEW") == 1


# ---- rotated pages: one coordinate convention ---------------------------------------

def _rotated():
    d = fitz.open()
    p = d.new_page(width=600, height=400)
    p.insert_text((100, 200), "HELLO", fontsize=20)
    p.set_rotation(90)
    return d


def test_rotated_text_coordinates():
    d = _rotated()
    page = d[0]
    _KEEP.append(page)
    word = fitz.Rect(page.get_text("words")[0][:4])      # unrotated
    screen = annotate.from_page(page, word)
    # text_rects takes and returns screen rects
    got = annotate.text_rects(page, screen + (-5, -5, 5, 5))
    assert len(got) == 1 and got[0].contains(_c(screen))
    # label counts and rule marks are op (unrotated) coordinates
    hits = autocount.find_by_label(d, "HELLO", use_ocr=False)
    r = fitz.Rect(hits[0]["rect"] if isinstance(hits[0], dict) else hits[0])
    assert r.contains(_c(word))
    marks = rules.find_marks(d, [{"pattern": "HELLO", "mark": "highlight"}])
    assert fitz.Rect(marks[0][2]["rect"]).contains(_c(word))
    # sheet words are in displayed coordinates
    w = sheets.page_words(page)[0]
    assert fitz.Rect(w[:4]).contains(_c(screen))


def test_room_tags_on_rotated_sheet_are_screen_points():
    d = fitz.open()
    p = d.new_page(width=600, height=400)
    p.insert_text((100, 200), "OFFICE\n300 SF", fontsize=10)
    p.set_rotation(90)
    page = d[0]
    _KEEP.append(page)
    tag = autotakeoff.room_tags(page)[0]
    sf = page.search_for("SF")[0]                       # unrotated
    assert annotate.from_page(page, sf).contains(tag["pt"])


# ---- op ids match the web client ------------------------------------------------------

def test_op_ids_use_javascript_number_format():
    assert oplog.js_number(1.0) == "1"
    assert oplog.js_number(-3.0) == "-3"
    assert oplog.js_number(1e-7) == "1e-7"
    assert oplog.js_number(1e21) == "1e+21"
    assert oplog.js_number(1e20) == "100000000000000000000"
    assert oplog.js_number(2.5e-6) == "0.0000025"
    assert oplog.js_number(123456789.125) == "123456789.125"
    assert oplog.canonical({"b": [1.0, 2], "a": "é", "c": None,
                            "d": True}) == '{"a":"é","b":[1,2],' \
                                           '"c":null,"d":true}'
    a = oplog.op_id("add_rect", 0, "c1", 1, 1, {"rect": [10.0, 20.0, 30.5, 40]})
    b = oplog.op_id("add_rect", 0, "c1", 1, 1, {"rect": [10, 20, 30.5, 40.0]})
    assert a == b


def test_scan_cache_shares_results():
    d = _doc(1)
    annotate.apply_op(d, annotate.new_op(
        "add_line", 0, pts=[[0, 0], [100, 0]], label="10'",
        measure={"type": "length", "value": 10, "unit": "ft", "group": "W"}))
    with annotate.scan_cache():
        a = annotate.takeoff_items(d)
        b = annotate.takeoff_items(d)
        a[0]["value"] = -1                       # callers get copies
        assert b[0]["value"] == 10
        assert annotate.takeoff_items(d)[0]["value"] == 10
    assert annotate.takeoff_items(d)[0]["value"] == 10


def test_sanitize_rebuilds_once_when_scrub_trips(monkeypatch):
    """Review 0.12.12 M3: a broken reference MuPDF didn't flag as repaired
    sent sanitize step by step (the whole set ~10 times, 100 s). Now it
    rebuilds once and cleans in one pass."""
    import fitz
    from app import acrobat2
    d = fitz.open()
    d.new_page().insert_text((72, 72), "SHEET A-101")
    d.set_metadata({"author": "Someone", "title": "Secret job"})
    calls = {"scrub": 0, "rebuild": 0}
    real_scrub, real_rebuild = fitz.Document.scrub, acrobat2._rebuild

    def scrub(self, **kw):
        calls["scrub"] += 1
        if calls["rebuild"] == 0:
            raise RuntimeError("missing xref 6702 0 R")
        return real_scrub(self, **kw)

    def rebuild(doc):
        calls["rebuild"] += 1
        return real_rebuild(doc)
    monkeypatch.setattr(fitz.Document, "scrub", scrub)
    monkeypatch.setattr(acrobat2, "_rebuild", rebuild)
    acrobat2.sanitize(d)
    assert calls["rebuild"] == 1
    assert calls["scrub"] == 2              # failed once, then one pass
    assert not (d.metadata or {}).get("author")
    assert "A-101" in d[0].get_text()


def test_remove_hidden_information_proves_what_it_removed():
    """Venice, Oct 19: check the cleaned file item by item."""
    import fitz
    from app import acrobat2
    d = fitz.open()
    p = d.new_page()
    p.insert_text((72, 72), "SHEET A-101")
    d.set_metadata({"author": "Someone", "title": "Secret job"})
    d.embfile_add("notes.txt", b"private")
    p.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(10, 10, 50, 50),
                   "uri": "https://example.com"})
    before = {i: st for st, i, _d in acrobat2.verify_clean(d)}
    assert before["Attached files"] == "FAIL"
    assert before["Document properties (author, title, software...)"] == \
        "FAIL"
    acrobat2.sanitize(d)
    after = acrobat2.verify_clean(d)
    assert all(st == "PASS" for st, _i, _d in after), after
    assert "A-101" in d[0].get_text()
