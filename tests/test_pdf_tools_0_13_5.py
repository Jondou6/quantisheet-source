"""0.13.5 PDF tools (made-up data only, Example names):

1. Redaction proof, fail closed: after redacting, every box is checked on
   a freshly written copy (no text, no line art, no original image
   pixels); a batch that fails is rolled back whole and nothing is saved;
   the Remove Hidden Information report has a Redaction proof section.
2. Reduce File Size keeps only a smaller result.
3. Check / Repair PDF, and the notice when a file was repaired on open.
4. Booklet / N-up (layout math in app/booklet.py, no Qt needed).
"""
import os
import random

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

fitz = pytest.importorskip("fitz")

from app import acrobat, acrobat2, annotate, booklet, redaction  # noqa: E402

SECRET = "Examplename Claimant 000-12-3456"
TOKEN = "Examplename"
BOX = fitz.Rect(150, 320, 330, 410)        # the redaction box (page coords)
IMG = fitz.Rect(100, 300, 400, 560)        # an image under the box's area


def _noise(w, h, seed=7, n=3):
    rnd = random.Random(seed)
    data = bytes(rnd.getrandbits(8) for _ in range(w * h * n))
    cs = fitz.csRGB if n == 3 else fitz.csGRAY
    return fitz.Pixmap(cs, w, h, data, False)


def _secret_page(doc):
    """A page with text, a vector line and an image all under BOX."""
    page = doc.new_page(width=612, height=792)
    page.insert_image(IMG, pixmap=_noise(120, 104))
    page.insert_text((160, 360), SECRET, fontsize=9, fontname="helv")
    page.draw_line((60, 380), (550, 380), color=(0, 0, 1), width=1.5)
    # a diagonal stroke (like a signature) that must be removed; a plain
    # straight rule may stay under the black box
    page.draw_line((170, 330), (310, 400), color=(1, 0, 0), width=1)
    page.insert_text((72, 720), "Example title block - kept", fontsize=10)
    return page


def _forms(s):
    """How `s` can look in a decompressed content stream."""
    b = s.encode("latin-1")
    hx = b.hex()
    two = "".join("00" + c for c in (hx[i:i + 2]
                                      for i in range(0, len(hx), 2)))
    return [b, hx.encode(), hx.upper().encode(), two.encode(),
            two.upper().encode()]


def _all_streams(doc):
    out = []
    for x in range(1, doc.xref_length()):
        try:
            if doc.xref_is_stream(x):
                out.append(doc.xref_stream(x) or b"")
        except Exception:                                 # noqa: BLE001
            pass
    return out


# ================================================= 1. redaction proof

def test_redaction_removes_text_line_and_pixels_and_proof_passes():
    doc = fitz.open()
    _secret_page(doc)
    # the checker sees everything before redacting (it is not blind)
    before = redaction.proof(doc, [(0, BOX)])
    assert len(before) == 1 and not before[0].ok
    assert before[0].words >= 1 and before[0].paths >= 1
    assert before[0].images == 1
    assert annotate.apply_op(doc, annotate.new_op("add_redact", 0,
                                                  rect=list(BOX)))
    res = redaction.proof(doc, [(0, BOX)])
    assert len(res) == 1
    r = res[0]
    assert (r.words, r.chars, r.paths, r.images, r.error) == \
        (0, 0, 0, 0, ""), r.describe()
    assert r.ok
    st, item, _det = redaction.summary(res)
    assert st == "PASS" and item.startswith("Redaction proof")
    # the same, by hand, on a cleanly written copy
    copy = redaction.fresh_copy(doc)
    pg = copy[0]
    assert pg.get_text("words", clip=BOX + (1, 1, -1, -1)) == []
    inner = BOX + (1, 1, -1, -1)
    crossing = [d for d in pg.get_drawings()
                if fitz.Rect(d["rect"]).intersects(inner)]
    # only the black box itself is left
    # (MuPDF paints it filled, sometimes with an outline in the same colour)
    assert all(d.get("fill") and d.get("color") in (None, d.get("fill"))
               for d in crossing)
    # the image is still there outside the box (only its pixels under the
    # box were blanked)
    assert any(fitz.Rect(i["bbox"]).intersects(IMG)
               for i in pg.get_image_info())
    # text outside the box is kept
    assert "Example title block" in pg.get_text()
    # the box is recorded for the Remove Hidden Information report
    boxes = redaction.recorded(copy, 0)
    assert len(boxes) == 1 and redaction._near(boxes[0], BOX)
    copy.close()


def test_redacted_text_is_gone_after_save_and_reopen(tmp_path):
    doc = fitz.open()
    _secret_page(doc)
    raw = b"".join(doc.xref_stream(x) or b"" for x in doc[0].get_contents())
    assert any(f in raw for f in _forms(TOKEN))      # the check can see it
    assert annotate.apply_op(doc, annotate.new_op("add_redact", 0,
                                                  rect=list(BOX)))
    out = tmp_path / "redacted.pdf"
    doc.save(str(out), garbage=3, deflate=True)
    doc.close()
    r = fitz.open(str(out))
    assert r[0].search_for(TOKEN) == []
    assert r[0].search_for("000-12-3456") == []
    assert TOKEN not in r[0].get_text()
    # nowhere in any decompressed stream of the file either
    for data in _all_streams(r):
        assert not any(f in data for f in _forms(TOKEN))
    r.close()


FIELD_VALUE = "Examplefield 555-0199"


def _text_field(page, name, rect, value):
    w = fitz.Widget()
    w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
    w.field_name = name
    w.rect = fitz.Rect(rect)
    w.field_value = value
    page.add_widget(w)


def test_redaction_over_a_form_field_deletes_it_and_proof_passes(tmp_path):
    """Review F13: a form field under the box used to make the proof fail
    every time; it is now deleted (value and all) and the proof checks
    that no field is left."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    _text_field(page, "example_claim_no", (160, 340, 320, 362), FIELD_VALUE)
    _text_field(page, "example_kept", (72, 700, 300, 722), "Example kept")
    before = redaction.proof(doc, [(0, BOX)])
    assert before[0].fields == 1 and not before[0].ok
    assert "form field" in before[0].describe()
    assert annotate.apply_op(doc, annotate.new_op("add_redact", 0,
                                                  rect=list(BOX)))
    res = redaction.proof(doc, [(0, BOX)])
    assert res[0].ok, res[0].describe()
    assert res[0].fields == 0
    out = tmp_path / "redacted form.pdf"
    doc.save(str(out), garbage=3, deflate=True)
    doc.close()
    r = fitz.open(str(out))
    names = [w.field_name for w in r[0].widgets()]
    assert names == ["example_kept"]          # only the one outside the box
    assert "Examplefield" not in r[0].get_text()
    for data in _all_streams(r):
        assert not any(f in data for f in _forms("Examplefield"))
    assert b"Examplefield" not in open(out, "rb").read()
    assert redaction.proof(r)[0].ok
    r.close()


def test_overlapping_boxes_keep_both_black_boxes():
    doc = fitz.open()
    _secret_page(doc)
    a = fitz.Rect(150, 320, 260, 410)
    b = fitz.Rect(240, 320, 330, 410)
    for r in (a, b):
        assert annotate.apply_op(doc, annotate.new_op("add_redact", 0,
                                                      rect=list(r)))
    res = redaction.proof(doc)            # every recorded box
    assert len(res) == 2 and all(x.ok for x in res), res
    boxes = [d["rect"] for d in doc[0].get_drawings()
             if redaction._is_fill_box(d, redaction.FILL)]
    for r in (a, b):
        assert any(redaction._near(fitz.Rect(x), r) for x in boxes)


def test_proof_names_page_and_box_when_something_is_left():
    doc = fitz.open()
    doc.new_page()
    _secret_page(doc)                                    # page 2
    res = redaction.proof(doc, [(1, BOX)])
    bad = redaction.failures(res)
    assert bad
    msg = bad[0].describe()
    assert "page 2" in msg and "box at (150, 320)" in msg
    assert TOKEN not in msg          # never repeats the secret itself
    st, _item, det = redaction.summary(res)
    assert st == "FAIL" and "page 2" in det


def test_remove_hidden_information_report_has_redaction_proof():
    doc = fitz.open()
    _secret_page(doc)
    rows = acrobat2.verify_clean(doc)
    assert not [r for r in rows if r[1].startswith("Redaction proof")]
    annotate.apply_op(doc, annotate.new_op("add_redact", 0, rect=list(BOX)))
    acrobat2.sanitize(doc)
    rows = acrobat2.verify_clean(doc)
    proof = [r for r in rows if r[1].startswith("Redaction proof")]
    assert proof and proof[0][0] == "PASS", proof
    # something written into the box afterwards is caught
    doc[0].insert_text((170, 370), "Example later text", fontsize=9)
    rows = acrobat2.verify_clean(doc)
    proof = [r for r in rows if r[1].startswith("Redaction proof")]
    assert proof[0][0] == "FAIL" and "page 1" in proof[0][2]


# ---- fail closed, in the viewer -----------------------------------------------

@pytest.fixture
def qapp(tmp_path, monkeypatch):
    QtWidgets = pytest.importorskip("PySide6.QtWidgets")
    from app import settings, toolchest
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    monkeypatch.setattr(toolchest, "PATH", str(tmp_path / "cfg" / "tc.json"))
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _two_page_file(tmp_path):
    doc = fitz.open()
    for i in range(2):
        p = doc.new_page(width=612, height=792)
        p.insert_text((160, 360), f"{SECRET} page {i + 1}", fontsize=9)
    path = str(tmp_path / "Example claim.pdf")
    doc.save(path)
    doc.close()
    return path


def test_failed_redaction_rolls_back_whole_batch(qapp, tmp_path,
                                                 monkeypatch):
    from app.viewer import PdfView
    path = _two_page_file(tmp_path)
    on_disk = open(path, "rb").read()
    v = PdfView(fitz.open(path), path)
    real = fitz.Page.apply_redactions
    calls = []

    def flaky(self, *a, **k):
        calls.append(self.number)
        if self.number == 1:
            raise RuntimeError("simulated redaction failure")
        return real(self, *a, **k)
    monkeypatch.setattr(fitz.Page, "apply_redactions", flaky)
    shown = []
    v.redaction_failed.connect(shown.append)
    marks = [(0, "add_redact", {"rect": list(BOX)}),
             (1, "add_redact", {"rect": list(BOX)})]
    assert v.apply_marks(marks) == 0
    assert calls == [0, 1]
    msg = v.last_redaction_error
    assert msg and "page 2" in msg and "rolled back" in msg
    assert shown == [msg]
    # page 1 was redacted first, and is back as it was: whole batch undone
    assert TOKEN in v.doc[0].get_text() and TOKEN in v.doc[1].get_text()
    assert redaction.recorded(v.doc, 0) == []
    assert not v.dirty
    assert not v.history.can_undo()           # no step was recorded
    assert v.save_blocked is None             # the rollback worked
    assert open(path, "rb").read() == on_disk     # nothing was saved
    monkeypatch.setattr(fitz.Page, "apply_redactions", real)
    # the same batch works once nothing fails
    assert v.apply_marks(marks) == 2
    assert v.last_redaction_error is None
    assert TOKEN not in v.doc[0].get_text() + v.doc[1].get_text()
    assert v.dirty and v.history.can_undo()
    v.dirty = False
    v.deleteLater()


def test_redaction_that_fails_its_proof_is_rolled_back(qapp, tmp_path,
                                                       monkeypatch):
    from app.viewer import PdfView
    path = _two_page_file(tmp_path)
    v = PdfView(fitz.open(path), path)

    def leaky(doc, areas=None, **k):
        res = redaction.Result(1, BOX)
        res.chars = res.words = 1
        return [res]
    monkeypatch.setattr(redaction, "proof", leaky)
    n = v.apply_marks([(0, "add_redact", {"rect": list(BOX)}),
                       (1, "add_redact", {"rect": list(BOX)})])
    assert n == 0
    assert "page 2" in v.last_redaction_error
    assert TOKEN in v.doc[0].get_text()
    assert not v.dirty
    v.deleteLater()


def test_blocked_save_is_refused(tmp_path):
    pytest.importorskip("PySide6")
    from types import SimpleNamespace
    from app import main_window as mw
    doc = fitz.open()
    doc.new_page()
    view = SimpleNamespace(doc=doc, page=0, protection=None,
                           save_blocked="a redaction could not be proven")
    out = tmp_path / "out.pdf"
    with pytest.raises(RuntimeError, match="blocked"):
        mw.MainWindow._write(SimpleNamespace(_view=None), str(out), view)
    assert not out.exists()


# ================================================= 2. reduce file size

def _compressed_pdf(path):
    doc = fitz.open()
    for i in range(3):
        doc.new_page().insert_text((72, 72), f"Example sheet {i + 1}")
    doc.save(str(path), garbage=4, deflate=True, use_objstms=1, clean=True)
    doc.close()
    return str(path)


def _hi_res_pdf(path):
    """A sheet with a 600-dpi scan (2 x 2 inch, 1200 x 1200 gray)."""
    doc = fitz.open()
    page = doc.new_page()
    page.insert_image(fitz.Rect(72, 72, 216, 216),
                      pixmap=_noise(1200, 1200, seed=3, n=1))
    page.insert_text((72, 300), "Example scanned detail")
    doc.save(str(path), garbage=3, deflate=True)
    doc.close()
    return str(path)


def test_not_smaller_message():
    e = acrobat.NotSmaller(100 * 1024, 120 * 1024)
    assert str(e).startswith("Already as small as it gets; no file written.")
    assert "would have grown" in str(e)
    assert "would only have gone" in str(acrobat.NotSmaller(1000, 995))


def test_reduce_already_compressed_writes_nothing(tmp_path):
    src = _compressed_pdf(tmp_path / "small.pdf")
    out = tmp_path / "small_reduced.pdf"
    with pytest.raises(acrobat.NotSmaller) as ei:
        acrobat.reduce_size(fitz.open(src), str(out),
                            original=os.path.getsize(src))
    assert "no file written" in str(ei.value)
    if ei.value.after > ei.value.before:
        assert "would have grown" in str(ei.value)
    assert not out.exists()
    assert sorted(os.listdir(tmp_path)) == ["small.pdf"]   # no temp left
    # with no file to compare with (opened from the file: its size)
    with pytest.raises(acrobat.NotSmaller):
        acrobat.reduce_size(fitz.open(src), str(out))
    assert not out.exists()


def test_reduce_never_replaces_an_existing_file_when_not_smaller(tmp_path):
    src = _compressed_pdf(tmp_path / "small.pdf")
    out = tmp_path / "older copy.pdf"
    out.write_bytes(b"%PDF-1.4 example older copy")
    with pytest.raises(acrobat.NotSmaller):
        acrobat.reduce_size(fitz.open(src), str(out),
                            original=os.path.getsize(src))
    assert out.read_bytes() == b"%PDF-1.4 example older copy"


def test_reduce_600_dpi_scan_is_smaller(tmp_path):
    if not hasattr(fitz.Document, "rewrite_images"):
        pytest.skip("this PyMuPDF can't downsample images")
    src = _hi_res_pdf(tmp_path / "scan.pdf")
    out = tmp_path / "scan_reduced.pdf"
    size = acrobat.reduce_size(fitz.open(src), str(out),
                               original=os.path.getsize(src))
    assert out.exists() and size == os.path.getsize(out)
    assert size < os.path.getsize(src)
    r = fitz.open(str(out))
    assert r.page_count == 1 and "Example scanned detail" in r[0].get_text()
    r.close()


def test_batch_reduce_skips_one_writes_one(tmp_path):
    if not hasattr(fitz.Document, "rewrite_images"):
        pytest.skip("this PyMuPDF can't downsample images")
    small = _compressed_pdf(tmp_path / "small.pdf")
    scan = _hi_res_pdf(tmp_path / "scan.pdf")
    out_dir = tmp_path / "out"
    res = dict(acrobat2.run_batch([small, scan], ["reduce"], str(out_dir)))
    assert res[small].startswith("SKIPPED: Already as small as it gets")
    assert os.path.isfile(res[scan])
    assert os.listdir(out_dir) == ["scan.pdf"]


def test_batch_reduce_with_other_steps_still_writes(tmp_path):
    small = _compressed_pdf(tmp_path / "small.pdf")
    res = acrobat2.run_batch([small], ["page_numbers", "reduce"],
                             str(tmp_path / "out"))
    out = res[0][1]
    assert os.path.isfile(out), res
    assert "Page 1 of 3" in fitz.open(out)[0].get_text()


# ================================================= 3. check / repair

def _plain_pdf(path, pages=3, text_lines=1):
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page()
    for i, page in enumerate(doc):
        for k in range(text_lines):
            page.insert_text((72, 72 + 12 * k),
                             f"Example sheet {i + 1} line {k + 1} " + "x" * 40,
                             fontsize=8)
    doc.save(str(path), garbage=0, deflate=False)
    doc.close()
    return str(path)


def _broken_xref(path):
    _plain_pdf(path)
    data = bytearray(open(path, "rb").read())
    i = data.rfind(b"startxref")
    assert i > 0
    j = i + len(b"startxref")
    while data[j:j + 1] in (b"\r", b"\n", b" "):
        j += 1
    k = j
    while data[k:k + 1].isdigit():
        k += 1
    data[j:k] = b"17".rjust(k - j, b"0")           # points at nothing
    open(path, "wb").write(bytes(data))
    return str(path)


def test_broken_xref_is_reported_and_repaired_copy_is_clean(tmp_path):
    src = _broken_xref(tmp_path / "Example plans.pdf")
    original = open(src, "rb").read()
    d = fitz.open(src)
    assert d.is_repaired and d.page_count == 3
    d.close()
    rep = acrobat2.check_and_repair(src)
    assert rep.repaired_on_open and not rep.ok
    assert rep.out == str(tmp_path / "Example plans (repaired).pdf")
    r = fitz.open(rep.out)
    assert not r.is_repaired and r.page_count == 3
    assert "Example sheet 3" in r[2].get_text()
    r.close()
    assert not rep.out_repaired and rep.out_pages == 3
    assert "repaired copy" in rep.text()
    assert open(src, "rb").read() == original      # never overwritten
    # a second run never replaces the first copy
    rep2 = acrobat2.check_and_repair(src)
    assert rep2.out == str(tmp_path / "Example plans (repaired 2).pdf")


def test_truncated_file_lists_bad_pages_and_saves_what_loads(tmp_path):
    src = str(tmp_path / "Example truncated.pdf")
    _plain_pdf(src, pages=6, text_lines=40)
    data = open(src, "rb").read()
    open(src, "wb").write(data[:int(len(data) * 0.7)])
    rep = acrobat2.check_and_repair(src)
    assert not rep.error, rep.error
    assert not rep.ok
    assert rep.bad_pages or rep.declared > rep.page_count, rep.text()
    assert "Page " in rep.text() or "could be found" in rep.text()
    assert rep.out and os.path.isfile(rep.out)
    r = fitz.open(rep.out)
    assert 1 <= r.page_count <= 6 and not r.is_repaired
    assert "Example sheet 1" in r[0].get_text()
    r.close()


def test_clean_file_no_problems_no_file(tmp_path):
    src = _plain_pdf(tmp_path / "Example clean.pdf")
    rep = acrobat2.check_and_repair(src)
    assert rep.ok and rep.out is None
    assert rep.text().startswith("No problems found")
    assert os.listdir(tmp_path) == ["Example clean.pdf"]


def test_repaired_path_never_overwrites(tmp_path):
    p = tmp_path / "x.pdf"
    assert acrobat2.repaired_path(str(p)) == str(tmp_path / "x (repaired).pdf")
    (tmp_path / "x (repaired).pdf").write_bytes(b"older")
    assert acrobat2.repaired_path(str(p)) == \
        str(tmp_path / "x (repaired 2).pdf")


def test_repaired_notice_wording():
    pytest.importorskip("PySide6")
    from app import main_window as mw
    note = mw.repaired_notice(os.path.join("C:", "Example plans.pdf"))
    assert "Example plans.pdf" in note and "repaired" in note
    assert "Check / Repair PDF" in note


# ================================================= 4. booklet / n-up

def test_booklet_order_six_pages():
    assert booklet.padded(6) == 8
    assert booklet.booklet_order(6) == [(8, 1), (2, 7), (6, 3), (4, 5)]
    # pages 7 and 8 are blank
    assert booklet.booklet_sides(6) == [(None, 1), (2, None), (6, 3), (4, 5)]
    assert booklet.padded(8) == 8 and booklet.padded(9) == 12
    sides = booklet.plan([(612, 792)] * 6, "booklet")
    assert len(sides) == 4                          # 2 sheets, 4 sides
    assert [[p + 1 for p, _r, _a in s["items"]] for s in sides] == \
        [[1], [2], [6, 3], [4, 5]]


def test_four_up_ten_pages_keeps_aspect():
    sides = booklet.plan([(612, 792)] * 10, "4up")
    assert len(sides) == 3
    assert [len(s["items"]) for s in sides] == [4, 4, 2]
    for s in sides:
        w, h = s["size"]
        for _p, (x0, y0, x1, y1), _rot in s["items"]:
            assert x0 >= 0 and y0 >= 0 and x1 <= w and y1 <= h
            assert abs((x1 - x0) / (y1 - y0) - 612 / 792) < 1e-6
            assert (x1 - x0) < 612                  # scaled to fit


def test_two_up_and_mixed_sizes_keep_aspect():
    sizes = [(612, 792), (1224, 792), (612, 792)]   # a fold-out sheet
    for s in booklet.plan(sizes, "2up"):
        assert s["size"][0] > s["size"][1]          # landscape sheet
        for p, (x0, y0, x1, y1), _rot in s["items"]:
            sw, sh = sizes[p]
            assert abs((x1 - x0) / (y1 - y0) - sw / sh) < 1e-6


def test_flip_back_and_creep():
    plain = booklet.plan([(612, 792)] * 8, "booklet")
    flip = booklet.plan([(612, 792)] * 8, "booklet", flip_back=True)
    assert all(rot == 0 for _p, _r, rot in flip[0]["items"])
    assert all(rot == 180 for _p, _r, rot in flip[1]["items"])
    creep = booklet.plan([(612, 792)] * 8, "booklet", creep=2)
    assert creep[0]["items"] == plain[0]["items"]   # outer sheet unchanged
    (_p, l1, _), (_q, r1, _) = creep[2]["items"]
    assert l1[2] == pytest.approx(612) and r1[0] == pytest.approx(612)
    assert (l1[2] - l1[0]) / (l1[3] - l1[1]) == pytest.approx(612 / 792)
    assert l1[0] > plain[2]["items"][0][1][0]


def _vector_doc(n):
    doc = fitz.open()
    for i in range(n):
        p = doc.new_page(width=612, height=792)
        p.insert_text((100, 100), f"Example page {i + 1}", fontsize=24)
        p.draw_rect(fitz.Rect(50, 150, 560, 700), color=(0, 0, 0), width=2)
        p.draw_line((50, 150), (560, 700), color=(1, 0, 0))
    return doc


def test_booklet_pdf_order_and_vector(tmp_path):
    doc = _vector_doc(6)
    out = str(tmp_path / "Example_booklet.pdf")
    assert booklet.write(doc, out, mode="booklet") == 4
    assert doc.page_count == 6                      # open document unchanged
    r = fitz.open(out)
    assert r.page_count == 4
    expect = [(None, 1), (2, None), (6, 3), (4, 5)]
    for i, (left, right) in enumerate(expect):
        pg = r[i]
        w, h = pg.rect.width, pg.rect.height
        halves = (pg.get_text(clip=fitz.Rect(0, 0, w / 2, h)),
                  pg.get_text(clip=fitz.Rect(w / 2, 0, w, h)))
        for want, got in zip((left, right), halves):
            if want is None:
                assert "Example page" not in got
            else:
                assert f"Example page {want}" in got
        assert pg.get_images() == []                # vector stays vector
        assert pg.get_drawings()
    r.close()


def test_four_up_pdf_ten_pages(tmp_path):
    doc = _vector_doc(10)
    out = str(tmp_path / "Example_4up.pdf")
    assert booklet.write(doc, out, mode="4up") == 3
    r = fitz.open(out)
    assert r.page_count == 3
    assert "Example page 10" in r[2].get_text()
    assert all(pg.get_images() == [] for pg in r)
    r.close()


# ================================================= menus

def test_new_commands_are_in_the_menus_and_run(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox
    from app.main_window import MainWindow
    from app.ribbon import all_actions, clean
    monkeypatch.setattr(QDialog, "exec", lambda self, *a: 0)
    for n in ("information", "warning"):
        monkeypatch.setattr(QMessageBox, n, staticmethod(lambda *a, **k: 0))
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.No))
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: ("", "")))
    src = _broken_xref(tmp_path / "Example damaged.pdf")
    w = MainWindow()
    try:
        assert w.open_path(src)
        # the non-blocking notice: the file opened, the tab says why
        assert "repaired" in w.tabs.tabToolTip(w.tabs.currentIndex())
        acts = {(p, clean(a.text())): a for p, a in all_actions(w.menuBar())}
        names = {n for _p, n in acts}
        assert "Check / Repair PDF…" in names or "Check / Repair PDF" in names
        assert "Booklet / N-up…" in names or "Booklet / N-up" in names
        for (_p, n), a in acts.items():
            if n.startswith(("Check / Repair PDF", "Booklet / N-up")):
                a.trigger()
                qapp.processEvents()
        assert os.path.isfile(tmp_path / "Example damaged (repaired).pdf")
        rep = w.check_repair()
        assert rep is not None and rep.repaired_on_open
    finally:
        if w._view is not None:
            w._view.dirty = False
        w.close()
        w.deleteLater()
        qapp.processEvents()
