"""Chief's round-4 re-test of b781b44 (Nov 7): one test per problem he
found. Made-up data only."""
import os
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz                                                    # noqa: E402
import pytest                                                  # noqa: E402

from app import annotate                                       # noqa: E402
from test_gui import qapp, win                                 # noqa: E402,F401
from test_review_fixes_nov7 import _image_pdf, _image_size     # noqa: E402


# ---- 1: the summary's "X for Y" meanings ---------------------------------------

def test_quoted_for_meanings_are_taken_out():
    from app.ai import review
    src = ("SHEET A-201 ROOF PLAN. DS DS DS. OH. CB. NEW ROOF DRAIN. "
           "DOOR 101. CEILING HEIGHT 9'-0\". RCP REFLECTED CEILING PLAN")
    reply = ('- The sheets use abbreviations like "CB" for ceiling, "DS" '
             'for door, and "OH" for overhead.\n'
             "- Use RCP for reference.\n"
             "- RCP (Reflected Ceiling Plan).")
    out, removed = review.check_expansions(reply, src)
    assert "for ceiling" not in out and "for door" not in out
    assert "for overhead" not in out
    assert {"CB = ceiling", "DS = door", "OH = overhead"} <= set(removed)
    assert "Use RCP for reference" in out             # not a meaning
    assert "Reflected Ceiling Plan" in out


def test_nearby_words_dont_define_an_abbreviation():
    from app.ai import review
    # DOOR and CEILING are printed right by DS and CB - not a legend
    src = "DS DOOR HARDWARE SET 3. CB 2X4 ACT CEILING. DS = DOWNSPOUT"
    out, removed = review.check_expansions(
        "- DS (door) hardware.\n- the ceiling (CB) grid.\n"
        "- DS (downspout) at each corner.", src)
    assert "DS (downspout)" in out
    assert "(door)" not in out and "ceiling (CB)" not in out
    assert review._defined_near("ET/FOLD DOWN EXAM TABLE", "ET",
                                "exam table")
    assert review._defined_near("AHU-1 AIR HANDLING UNIT", "AHU",
                                "air handling unit")
    assert not review._defined_near("et al. exam table", "ET", "exam table")


# ---- 2: Translate keeps what it translated ----------------------------------------

def _seed(v):
    v.apply_marks([(0, "add_note", {"pt": [60, 60],
                                    "text": "Install new door hardware"}),
                   (0, "add_textbox", {"rect": [100, 300, 300, 330],
                                       "text": "Verify ceiling height"})])


def test_translate_result_is_kept(win, monkeypatch):
    from app import bg
    runs = []
    monkeypatch.setattr(bg, "run", lambda fn, ok, bad, parent=None, **k:
                        runs.append((fn, ok, bad)))
    v = win._view
    _seed(v)
    busy = win.translate_markups("Spanish")
    assert busy is not None and runs
    _fn, ok, _bad = runs.pop()
    ok(["Instalar herrajes nuevos", "Verificar altura del techo"])
    comments = {m["comment"] for m in annotate.markup_items(v.doc)}
    assert "Instalar herrajes nuevos" in comments
    assert "cancelled" not in win.statusBar().currentMessage()


def test_translate_cancel_still_throws_it_away(win, monkeypatch):
    from app import bg
    runs = []
    monkeypatch.setattr(bg, "run", lambda fn, ok, bad, parent=None, **k:
                        runs.append((fn, ok, bad)))
    v = win._view
    _seed(v)
    busy = win.translate_markups("Spanish")
    from PySide6.QtWidgets import QPushButton
    busy.findChild(QPushButton).click()               # the Cancel button
    _fn, ok, _bad = runs.pop()
    ok(["Instalar herrajes nuevos", "Verificar altura del techo"])
    comments = {m["comment"] for m in annotate.markup_items(v.doc)}
    assert "Install new door hardware" in comments


def test_translate_failure_is_shown(win, monkeypatch):
    from app import bg, main_window
    runs = []
    warned = []
    monkeypatch.setattr(bg, "run", lambda fn, ok, bad, parent=None, **k:
                        runs.append((fn, ok, bad)))
    monkeypatch.setattr(main_window.QMessageBox, "warning",
                        lambda *a, **k: warned.append(a))
    _seed(win._view)
    win.translate_markups("Spanish")
    _fn, _ok, bad = runs.pop()
    bad("The local AI isn't answering")
    assert warned


# ---- 3: an encrypted file's images are never changed in place ---------------------

def _locked(tmp_path, attach=0):                  # owner password only
    src = _image_pdf(str(tmp_path / "plain.pdf"))
    d = fitz.open(src)
    if attach:
        d.embfile_add("example.bin", os.urandom(attach))
    p = str(tmp_path / "locked.pdf")
    d.save(p, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner-x",
           permissions=fitz.PDF_PERM_PRINT | fitz.PDF_PERM_ACCESSIBILITY)
    d.close()
    return p


def test_encrypted_reduce_leaves_the_document_alone(tmp_path):
    from app import acrobat
    p = _locked(tmp_path)
    d = fitz.open(p)
    assert d.metadata.get("encryption")
    before = _image_size(d)
    with pytest.raises(acrobat.NotSmaller):           # (forced: original=10)
        acrobat.reduce_size(d, str(tmp_path / "out.pdf"), original=10)
    assert not d.is_dirty and _image_size(d) == before
    d.close()


def test_encrypted_batch_keeps_the_original_images(tmp_path, monkeypatch):
    from app import acrobat, acrobat2
    p = _locked(tmp_path)
    with fitz.open(p) as d:
        before = _image_size(d)
    real = acrobat.reduce_size                         # never smaller enough
    monkeypatch.setattr(acrobat, "reduce_size",
                        lambda doc, path, **k: real(doc, path, original=10))
    res = acrobat2.run_batch([p], ["watermark", "reduce"],
                             str(tmp_path / "o"), {"watermark": "DRAFT"})
    assert not str(res[0][1]).startswith("ERROR"), res
    with fitz.open(res[0][1]) as d:
        if d.needs_pass:
            d.authenticate("owner-x")
        assert _image_size(d) == before


def test_encrypted_reduce_still_shrinks_when_it_can(tmp_path):
    from app import acrobat
    p = _locked(tmp_path)
    d = fitz.open(p)
    before = _image_size(d)
    out = str(tmp_path / "small.pdf")
    acrobat.reduce_size(d, out, original=os.path.getsize(p))
    assert _image_size(d) == before and not d.is_dirty
    with fitz.open(out) as r:
        assert r.metadata.get("encryption")          # still protected
        if r.needs_pass:
            r.authenticate("owner-x")
        assert _image_size(r) < before


# ---- 4: no temp file is left when the copy can't be made ---------------------------

def _temps():
    d = tempfile.gettempdir()
    return {n for n in os.listdir(d) if n.startswith("qs-reduce-")}


def test_reduce_temp_removed_when_the_save_fails(tmp_path, monkeypatch):
    from app import acrobat
    d = fitz.open(_image_pdf(str(tmp_path / "photo.pdf")))
    before = _temps()

    def boom(*a, **k):
        raise RuntimeError("example disk full")
    monkeypatch.setattr(type(d), "save", boom)
    with pytest.raises(RuntimeError):
        acrobat.reduce_size(d, str(tmp_path / "out.pdf"), original=10)
    monkeypatch.undo()
    assert _temps() <= before
    d.close()


def test_reduce_temp_removed_when_the_reopen_fails(tmp_path, monkeypatch):
    from app import acrobat
    d = fitz.open(_image_pdf(str(tmp_path / "photo.pdf")))
    before = _temps()
    real = fitz.open

    def picky(*a, **k):
        if a and "qs-reduce-" in str(a[0]):
            raise RuntimeError("example unreadable copy")
        return real(*a, **k)
    monkeypatch.setattr(fitz, "open", picky)
    with pytest.raises(RuntimeError):
        acrobat.reduce_size(d, str(tmp_path / "out.pdf"), original=10)
    monkeypatch.undo()
    assert _temps() <= before
    d.close()
