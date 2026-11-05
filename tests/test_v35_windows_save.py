"""3b B8: saving over a PDF that PyMuPDF has open, twice. On Windows an open
file can't be replaced; that must fail cleanly (original untouched, no temp
file left, a plain message) and the Save Copy commands refuse the open
file up front. Runs everywhere; the Windows run is the one that counts."""
import os
import sys

import fitz
import pytest

from app import acrobat, safeio


def _pdf(path, text):
    d = fitz.open()
    d.new_page().insert_text((72, 72), text)
    d.save(path)
    d.close()


def _save_twice(doc, p, fn):
    errs = []
    for k in (1, 2):
        doc[0].insert_text((72, 100 + 40 * k), f"edit {k}")
        try:
            fn(doc, p)
        except safeio.FileInUseError as e:
            errs.append(str(e))
    return errs


@pytest.mark.parametrize("fn", [
    lambda d, p: safeio.atomic_save(d, p, garbage=1, deflate=True),
    acrobat.save_unprotected])
def test_save_twice_over_the_open_file(tmp_path, fn):
    p = str(tmp_path / "plan.pdf")
    _pdf(p, "first")
    before = open(p, "rb").read()
    doc = fitz.open(p)                    # held open, like a viewer tab
    errs = _save_twice(doc, p, fn)
    doc.close()
    assert not [f for f in os.listdir(tmp_path) if f.endswith(".tmp")]
    if sys.platform == "win32":
        assert len(errs) == 2 and "is open" in errs[0]
        assert open(p, "rb").read() == before          # untouched
    else:
        text = fitz.open(p)[0].get_text()
        assert errs == [] and "edit 2" in text


def test_save_twice_to_another_file_while_open(tmp_path):
    p, q = str(tmp_path / "a.pdf"), str(tmp_path / "a_copy.pdf")
    _pdf(p, "a")
    doc = fitz.open(p)
    assert _save_twice(doc, q, acrobat.save_unprotected) == []
    doc.close()
    assert "edit 2" in fitz.open(q)[0].get_text()


def test_same_file():
    class D:
        name = os.path.join("x", "Plan.pdf")
    assert safeio.same_file(D, os.path.join("x", "Plan.pdf"))
    assert not safeio.same_file(D, os.path.join("x", "Other.pdf"))
