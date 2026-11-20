"""File > Save As > Reduced Size PDF (Nov 19): a smaller copy straight
from Save As at three levels; the open document is left as it is.
Made-up image data."""
import os
import sys

import fitz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from test_gui import win, qapp  # noqa: F401,E402
except Exception:                                         # noqa: BLE001
    pass


def _photo_pdf(path):
    d = fitz.open()
    pg = d.new_page(width=612, height=792)
    n = 1800
    pix = fitz.Pixmap(fitz.csRGB, n, n, os.urandom(n * n * 3), False)
    pg.insert_image(fitz.Rect(36, 36, 576, 576), pixmap=pix)
    d.save(path)
    d.close()


def test_save_as_reduced_keeps_the_document(win, tmp_path):
    src = tmp_path / "photos.pdf"
    _photo_pdf(str(src))
    assert win.open_path(str(src))
    before = os.path.getsize(src)
    out_b = tmp_path / "balanced.pdf"
    out_s = tmp_path / "smallest"
    assert win.save_as(str(out_b), kind="balanced", show=False)
    assert win.save_as(str(out_s), kind="smallest", show=False)
    small = tmp_path / "smallest.pdf"           # .pdf added
    assert os.path.getsize(small) < os.path.getsize(out_b) < before
    assert "KB" in win._last_reduced
    # still the original, still open from where it was
    assert os.path.abspath(win._path) == os.path.abspath(str(src))
    assert os.path.getsize(src) == before
    assert fitz.open(str(small)).page_count == 1


def test_reduced_copy_never_over_its_own_file(win, tmp_path):
    src = tmp_path / "photos.pdf"
    _photo_pdf(str(src))
    assert win.open_path(str(src))
    before = os.path.getsize(src)
    assert win.save_as(str(src), kind="smallest", show=False) is False
    assert os.path.getsize(src) == before


def test_dialog_lists_the_reduced_choices(win):
    kinds = [k for k, _ in win.REDUCED_KINDS]
    assert kinds == ["high quality", "balanced", "smallest"]
    assert win._reduced_filter("smallest") == \
        "Reduced Size PDF - smallest (*.pdf)"
