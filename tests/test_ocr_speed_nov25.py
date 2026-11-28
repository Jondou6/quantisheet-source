"""Faster whole-sheet OCR (Nov 25 optimization list): the typed-word check
uses a grid, tiles are drawn from one display list and go to tesseract as
they are drawn, on every core but one. Made-up pages, no tesseract."""
import os

import fitz

from app import acrobat


def _page_with_words():
    d = fitz.open()
    p = d.new_page(width=1800, height=1200)
    for i in range(40):
        p.insert_text((40 + 40 * i, 100 + 25 * (i % 30)), f"W{i}",
                      fontsize=9)
    return d, p


def test_new_words_drops_only_words_on_typed_ones():
    d, p = _page_with_words()
    typed = p.get_text("words")
    ocr = []
    for w in typed:                                  # same place: dropped
        ocr.append((fitz.Rect(w[:4]), w[4]))
    ocr += [(fitz.Rect(1500, 1100, 1530, 1110), "NEW"),
            (fitz.Rect(5, 5, 20, 12), "CORNER")]
    # a word whose middle is just inside a typed box's 1 pt margin
    b = typed[0]
    ocr.append((fitz.Rect(b[2], b[1], b[2] + 1.0, b[3]), "EDGE"))
    new = [t for _r, t in acrobat._new_words(p, ocr)]
    assert new == ["NEW", "CORNER"]


def test_new_words_matches_the_plain_check():
    import random
    d, p = _page_with_words()
    have = [fitz.Rect(w[:4]) + (-1, -1, 1, 1) for w in p.get_text("words")]
    rnd = random.Random(7)
    ocr = []
    for _ in range(400):
        x, y = rnd.uniform(0, 1800), rnd.uniform(0, 1200)
        ocr.append((fitz.Rect(x, y, x + rnd.uniform(2, 60),
                              y + rnd.uniform(2, 14)), "w"))
    plain = [r for r, _t in ocr
             if not any(h.contains(fitz.Point((r.x0 + r.x1) / 2,
                                              (r.y0 + r.y1) / 2))
                        for h in have)]
    assert [r for r, _t in acrobat._new_words(p, ocr)] == plain


def test_tiles_go_to_tesseract_as_drawn(monkeypatch):
    from app import ocr as ocr_mod
    monkeypatch.setattr(ocr_mod, "find_tesseract", lambda: "tesseract")
    seen = []

    def tess(exe, png, language, tessdata, psm=11, dpi=None):
        import os
        seen.append(os.path.getsize(png) > 0 and png.endswith(".pgm") and
                    dpi == 96)
        return [(300, 300, 360, 330, "HELLO", 95.0)]
    monkeypatch.setattr(acrobat, "_tess_tile", tess)
    d = fitz.open()
    d.new_page(width=2592, height=1728)              # 36 x 24 in
    words = acrobat.ocr_page_words(d[0], dpi=200, workers=3)
    assert seen and all(seen)
    assert len(words) == len(seen)                   # one per tile, kept once
    assert all(isinstance(r, fitz.Rect) and t == "HELLO" for r, t in words)


def test_ocr_workers_leave_a_core_free(monkeypatch):
    import os
    for cores, want in ((1, 1), (2, 1), (4, 3), (8, 7), (16, 8)):
        monkeypatch.setattr(os, "cpu_count", lambda c=cores: c)
        assert acrobat.ocr_workers() == want


def test_a_set_is_read_sheet_after_sheet_on_one_pool(monkeypatch, tmp_path):
    """make_searchable draws the next sheet while the last is read; every
    sheet still gets its words (both readings of a civil sheet), each
    sheet keeps its rotation, and no tile is left in TEMP."""
    import tempfile
    from app import ocr as ocr_mod
    monkeypatch.setattr(ocr_mod, "find_tesseract", lambda: "tesseract")
    real = tempfile.mkdtemp
    made = []

    def mk(*a, **k):
        k["dir"] = str(tmp_path)
        made.append(real(*a, **k))
        return made[-1]
    monkeypatch.setattr(tempfile, "mkdtemp", mk)
    calls = []

    def tess(exe, img, language, tessdata, psm=11, dpi=None):
        calls.append(img)
        return [(300, 300, 420, 330, "MADEUP", 95.0)]
    monkeypatch.setattr(acrobat, "_tess_tile", tess)
    monkeypatch.setattr(acrobat, "is_photo", lambda page: False)
    d = fitz.open()
    for rot in (0, 90, 0):
        p = d.new_page(width=1224, height=792)          # 17 x 11 in
        p.set_rotation(rot)
    assert acrobat.make_searchable(d, [0, 1, 2], vertical=True) == 3
    assert [p.rotation for p in d] == [0, 90, 0]
    for p in d:
        assert "MADEUP" in p.get_text()
    flat = [c for c in calls if "a_" in os.path.basename(c)]
    turned = [c for c in calls if "b_" in os.path.basename(c)]
    assert flat and turned and len(flat) == len(turned)
    assert made and not any(os.path.exists(m) for m in made)


def test_auto_scale_reads_every_sheet_needing_ocr_at_once(monkeypatch):
    """Auto Scale OCRs all the sheets that need it in one call (one pool,
    sheets overlapped), then reads each sheet's scale from its words."""
    from app import autoscale
    d = fitz.open()
    for _ in range(3):
        d.new_page(width=1728, height=1152)        # no text: a "scan"
    calls = []

    def many(doc, pages, *a, **k):
        calls.append(list(pages))
        return {p: [(fitz.Rect(1350, 1100, 1600, 1114),
                     'SCALE: 1/4" = 1\'-0"')] for p in pages}
    monkeypatch.setattr(acrobat, "ocr_pages_words", many)
    monkeypatch.setattr(acrobat, "ocr_page_words",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("one sheet at a time")))
    rows = autoscale.detect(d, use_ocr=True)
    assert calls == [[0, 1, 2]]
    assert [r["source"] for r in rows] == ["ocr"] * 3
    assert all(abs(r["ppu"] - 18.0) < 1e-6 for r in rows)
    assert autoscale.detect(d, use_ocr=False)[0]["source"] == ""
    assert calls == [[0, 1, 2]]                    # no OCR when it's off
