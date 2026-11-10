"""The outside code review of 6ca6adb, as checked by Chief (message
1SEGN76Z, Nov 7): one test per confirmed fix. Made-up data only."""
import io
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz                                                    # noqa: E402
import pytest                                                  # noqa: E402

from test_gui import qapp                                      # noqa: E402,F401


def _image_pdf(path, side=1600):
    from PIL import Image
    buf = io.BytesIO()
    Image.effect_noise((side, side), 64).convert("RGB").save(buf, "JPEG",
                                                             quality=95)
    d = fitz.open()
    p = d.new_page(width=200, height=200)        # ~576 dpi: downsampled
    p.insert_image(p.rect, stream=buf.getvalue())
    d.save(path)
    d.close()
    return path


def _image_size(doc):
    xref = doc[0].get_images()[0][0]
    return doc.extract_image(xref)["width"]


# ---- H2: the title fix keeps the other viewer settings ----------------------

def test_title_fix_keeps_viewer_preferences():
    from app import accessibility
    d = fitz.open()
    d.new_page()
    cat = d.pdf_catalog()
    d.xref_set_key(cat, "ViewerPreferences",
                   "<</PrintScaling/None/HideToolbar true/Duplex/Simplex>>")
    accessibility.fix(d, rules=["title"], title="Example")
    vp = d.xref_get_key(cat, "ViewerPreferences")[1]
    for key in ("/PrintScaling", "/HideToolbar", "/Duplex",
                "/DisplayDocTitle"):
        assert key in vp, vp
    e = fitz.open()
    e.new_page()
    accessibility.fix(e, rules=["title"], title="Example")
    assert "/DisplayDocTitle true" in e.xref_get_key(
        e.pdf_catalog(), "ViewerPreferences")[1]


# ---- H5: downloads have a size limit ----------------------------------------

class _Big:
    def __init__(self, n_chunks, length=None):
        self.left = n_chunks
        self.headers = {"Content-Type": "application/json"}
        if length is not None:
            self.headers["Content-Length"] = str(length)
        self.reads = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        self.reads += 1
        if self.left <= 0:
            return b""
        self.left -= 1
        return b"x" * n


def test_oversize_answers_are_refused(monkeypatch):
    import urllib.request
    from app import aerial
    big = _Big(2000)                                   # 125 MB in 64 KB
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: big)
    with pytest.raises(aerial.TooLarge):
        aerial._get("https://x.test/a", {}, max_bytes=aerial.MAX_JSON_BYTES)
    assert big.reads <= aerial.MAX_JSON_BYTES // aerial.CHUNK + 2  # stopped
    said = _Big(1, length=120 * 1024 * 1024)
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: said)
    with pytest.raises(aerial.TooLarge):
        aerial._get("https://x.test/a", {})
    assert said.reads == 0                             # never read
    assert aerial.MAX_IMAGE_BYTES == 40 * 1024 * 1024


def test_query_joins_with_ampersand(monkeypatch):
    import urllib.request
    from app import aerial
    seen = []

    class R(_Big):
        pass

    def opener(req, timeout=None):
        seen.append(req.full_url)
        return R(0)
    monkeypatch.setattr(urllib.request, "urlopen", opener)
    aerial._get("https://x.test/a?k=1", {"q": 2})
    assert seen[0] == "https://x.test/a?k=1&q=2"


# ---- H7: the AI review talks only to this PC ---------------------------------

def test_ai_review_refuses_another_host(monkeypatch):
    from app import policy
    from app.ai import review
    monkeypatch.setattr(policy, "get", lambda k, d=None: d)
    monkeypatch.setattr(policy, "check", lambda what: None)
    for bad in ("http://evil.example.com:11434", "http://10.0.0.5:11434"):
        with pytest.raises(review.AIError, match="on this PC"):
            review._allowed_host(bad)
    assert review._allowed_host("http://localhost:11434") == \
        "http://localhost:11434"
    assert review._allowed_host("http://127.0.0.1:11434/") == \
        "http://127.0.0.1:11434"
    # IT naming a server still works
    monkeypatch.setattr(policy, "get", lambda k, d=None:
                        "http://ai-server:11434" if k == "AIHost" else d)
    assert review._allowed_host("http://localhost:11434") == \
        "http://ai-server:11434"


# ---- H3: reduce never changes the caller's document ---------------------------

def test_reduce_size_leaves_the_document_alone(tmp_path):
    from app import acrobat
    src = _image_pdf(str(tmp_path / "photo.pdf"))
    d = fitz.open(src)
    before = _image_size(d)
    dirty = d.is_dirty
    with pytest.raises(acrobat.NotSmaller):
        acrobat.reduce_size(d, str(tmp_path / "out.pdf"), original=10)
    assert d.is_dirty == dirty and _image_size(d) == before
    d.close()


def test_batch_keeps_the_original_images_after_not_smaller(tmp_path,
                                                          monkeypatch):
    from app import acrobat, acrobat2
    src = _image_pdf(str(tmp_path / "photo.pdf"))
    with fitz.open(src) as d:
        before = _image_size(d)

    # the real one downsamples a copy; prove the batch saves `doc` as it was
    real = acrobat.reduce_size
    monkeypatch.setattr(acrobat, "reduce_size",
                        lambda doc, path, **k: real(doc, path, original=10))
    out = tmp_path / "out"
    res = acrobat2.run_batch([src], ["watermark", "reduce"], str(out),
                             {"watermark": "DRAFT"})
    assert not str(res[0][1]).startswith("ERROR"), res
    with fitz.open(res[0][1]) as d:
        assert _image_size(d) == before


# ---- H6: files are let go of after a failure ----------------------------------

def test_batch_closes_files_that_fail(tmp_path, monkeypatch):
    from app import acrobat, acrobat2
    srcs = []
    for k in range(3):
        p = str(tmp_path / f"f{k}.pdf")
        d = fitz.open()
        d.new_page()
        d.save(p)
        d.close()
        srcs.append(p)
    opened = []
    real = acrobat2.create_pdf

    def tracking(path):
        doc = real(path)
        opened.append(doc)
        return doc
    monkeypatch.setattr(acrobat2, "create_pdf", tracking)

    def boom(doc, spec):
        raise RuntimeError("example failure")
    monkeypatch.setattr(acrobat, "header_footer", boom)
    res = acrobat2.run_batch(srcs, ["page_numbers"], str(tmp_path / "o"))
    assert all(str(r[1]).startswith("ERROR") for r in res)
    assert opened and all(d.is_closed for d in opened)
    for p in srcs:                                     # nothing holds them
        os.replace(p, p + ".moved")


def test_combine_closes_a_source_that_fails(tmp_path, monkeypatch):
    from app import acrobat, jobdata
    p = str(tmp_path / "a.pdf")
    d = fitz.open()
    d.new_page()
    d.save(p)
    d.close()
    opened = []
    real_open = fitz.open

    def tracking(*a, **k):
        doc = real_open(*a, **k)
        if a and a[0] == p:
            opened.append(doc)
        return doc
    monkeypatch.setattr(fitz, "open", tracking)
    monkeypatch.setattr(jobdata, "copy_job",
                        lambda *a, **k: (_ for _ in ()).throw(
                            RuntimeError("example failure")))
    with pytest.raises(RuntimeError):
        acrobat.combine([p], bookmarks=False)
    assert opened and all(x.is_closed for x in opened)


# ---- M8, L5: Excel keeps codes as written --------------------------------------

def test_excel_keeps_leading_zeros(tmp_path):
    from app import acrobat
    xml = acrobat._xlsx_sheet([["00101", "081113", "29401", "$1,234.50",
                                "0.5", "-0.25", "x" * 40000]])
    for code in ("00101", "081113"):
        assert f"<t xml:space=\"preserve\">{code}</t>" in xml
    assert "<v>29401</v>" in xml and "<v>1234.50</v>" in xml
    assert "<v>0.5</v>" in xml and "<v>-0.25</v>" in xml
    assert "Excel holds 32,767 characters" in xml
    assert "x" * 32768 not in xml


# ---- M10: card numbers need the check digit ------------------------------------

def test_card_numbers_need_the_check_digit():
    from app import acrobat
    assert acrobat.luhn_ok("4111 1111 1111 1111")
    assert not acrobat.luhn_ok("12 34 56 78 90 12 34")
    assert not acrobat.luhn_ok("1234567890123")
    d = fitz.open()
    p = d.new_page()
    p.insert_text((72, 72), "Card 4111 1111 1111 1111", fontsize=10)
    p.insert_text((72, 100), "Order 12 34 56 78 90 12 34", fontsize=10)
    p.insert_text((72, 128), "Ref 1234567890123", fontsize=10)
    hits = acrobat.find_for_redaction(
        d, pattern=acrobat.PATTERNS["Credit card numbers"])
    assert len(hits) == 1 and hits[0][1].y0 < 80


# ---- M14: world files ---------------------------------------------------------

def test_world_file_rotated_or_short_is_refused(tmp_path):
    from app import aerial
    img = tmp_path / "site.png"
    img.write_bytes(b"x")
    pgw = tmp_path / "site.pgw"
    pgw.write_text("0.25\n0\n0\n-0.25\n2700000\n800000\n")
    assert aerial.world_file_pixel(str(img)) == 0.25
    pgw.write_text("0.5\n0.3\n0.3\n-0.5\n2700000\n800000\n")
    px, why = aerial.world_file_info(str(img))
    assert px is None and "rotated" in why
    pgw.write_text("0.5\n")
    px, why = aerial.world_file_info(str(img))
    assert px is None and "incomplete" in why
    pgw.write_text("0.5\n0\n0\n-0.25\n1\n2\n")
    assert aerial.world_file_pixel(str(img)) is None


# ---- M9: OCR tiles never left in TEMP ------------------------------------------

def test_ocr_tiles_are_cleaned_up_after_a_failure(tmp_path, monkeypatch):
    import tempfile
    from app import acrobat, ocr as ocr_mod
    monkeypatch.setattr(ocr_mod, "find_tesseract", lambda: "tesseract")
    made = []
    real = tempfile.mkdtemp

    def mk(*a, **k):
        p = real(*a, dir=str(tmp_path), **{x: y for x, y in k.items()
                                          if x != "dir"})
        made.append(p)
        return p
    monkeypatch.setattr(tempfile, "mkdtemp", mk)
    calls = {"n": 0}
    real_pix = fitz.Page.get_pixmap

    def pix(self, *a, **k):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("example failure")
        return real_pix(self, *a, **k)
    monkeypatch.setattr(fitz.Page, "get_pixmap", pix)
    d = fitz.open()
    d.new_page(width=3000, height=3000)
    with pytest.raises(RuntimeError):
        acrobat.ocr_page_words(d[0], dpi=200)
    assert made and not any(os.path.exists(p) for p in made)


# ---- M11, M12, M16, H4: the ADA checker -----------------------------------------

def test_ada_checker_scans_once_and_skips_unchanged_writes(qapp,
                                                           monkeypatch):
    from app import ada_check, ada_takeoff, ada_ui
    calls = []
    real = ada_takeoff.elements
    monkeypatch.setattr(ada_takeoff, "elements",
                        lambda doc: calls.append(1) or real(doc))
    d = fitz.open()
    d.new_page()
    tab = ada_ui.CheckerTab(d)
    tab.refresh()
    tab.refresh()
    assert len(calls) == 1                             # M12
    edits = []
    tab.edited.connect(lambda: edits.append(1))
    tab.ed["stories"].setText("2")
    tab.run()
    assert len(edits) == 1
    tab.run()                                          # nothing changed
    assert len(edits) == 1                             # M16
    tab.ed["stories"].setText("3")
    tab.blocked = lambda what: True                    # live collab
    tab.run()
    assert len(edits) == 1                             # H4: not written
    assert str(ada_check.read(d).get("stories")) == "2"
    assert "counts once" in ada_ui.PARKING_RULE        # M11


# ---- M15, L2, L3, L6 ------------------------------------------------------------

def test_small_cleanups():
    import inspect
    from app import acrobat2, aerial_ui, acrobat_dialogs
    from app.ai import dialogs
    assert not hasattr(dialogs._AIDialog, "_start")
    assert not hasattr(dialogs._AIDialog, "_finish")
    assert hasattr(aerial_ui.AerialDialog, "pan_by")
    assert "move" not in aerial_ui.AerialDialog.__dict__
    assert "caller closes it" in acrobat2.create_pdf.__doc__
    assert "permissions password" in inspect.getsource(
        acrobat_dialogs.ProtectDialog).lower()
