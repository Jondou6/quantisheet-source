"""Auto Scale: every sheet's scale, from text, OCR on scans, checked
against the drawing's own dimension strings, confirmed before use."""
import shutil

import fitz
import pytest

from app import annotate, autoscale


def _plan(scale_text='SCALE: 1/4" = 1\'-0"', ppf=18.0, dim_ft=24, wrong=False):
    d = fitz.open()
    pg = d.new_page(width=1728, height=1152)
    pg.insert_text((1350, 1080), "A-101  FIRST FLOOR PLAN", fontsize=14)
    if scale_text:
        pg.insert_text((1350, 1110), scale_text, fontsize=14)
    for i, ft in enumerate((dim_ft, 12, 30)):
        y = 200 + i * 150
        length = ft * ppf * (1.25 if wrong else 1.0)
        pg.draw_line((100, y), (100 + length, y), width=0.5)
        pg.insert_text((100 + length / 2 - 15, y - 4), f"{ft}'-0\"", fontsize=9)
    return d


def _scanned(d, dpi=200):
    s = fitz.open()
    for p in d:
        q = s.new_page(width=p.rect.width, height=p.rect.height)
        q.insert_image(q.rect, pixmap=p.get_pixmap(dpi=dpi))
    return s


def test_vector_sheet_scale_and_dimension_check():
    rows = autoscale.detect(_plan())
    r = rows[0]
    assert r["ppu"] == pytest.approx(18.0) and r["unit"] == "ft"
    assert r["source"] == "text"
    assert r["dims"]["n"] >= 2 and r["dims"]["agree"] is True
    assert r["status"] == "ok"


def test_dimension_mismatch_is_flagged_for_review():
    r = autoscale.detect(_plan(wrong=True))[0]
    assert r["dims"]["agree"] is False
    assert r["status"] == "check"
    assert "dimension" in r["note"].lower()


def test_no_scale_text_falls_back_to_dimensions():
    r = autoscale.detect(_plan(scale_text=None))[0]
    assert r["source"] == "dimensions"
    assert r["ppu"] == pytest.approx(18.0, rel=0.03)
    assert r["status"] == "check"          # never auto-trusted


def test_nts_sheet_has_no_scale():
    r = autoscale.detect(_plan(scale_text="SCALE: NTS", dim_ft=0))[0]
    assert r["ppu"] is None and r["status"] == "none"


@pytest.mark.skipif(not shutil.which("tesseract"), reason="needs tesseract")
def test_scanned_sheet_read_with_ocr():
    r = autoscale.detect(_scanned(_plan()))[0]
    assert r["source"] == "ocr"
    assert r["ppu"] == pytest.approx(18.0)
    assert r["status"] == "check"            # OCR is never pre-trusted


def test_apply_only_confirmed_rows():
    d = _plan()
    d.new_page(width=1728, height=1152)
    rows = autoscale.detect(d)
    assert rows[1]["status"] == "none"
    n = autoscale.apply(d, rows, confirmed={0})
    assert n == 1
    sc = annotate.read_scales(d)
    assert sc[0]["ppu"] == pytest.approx(18.0) and 1 not in sc


def test_existing_scale_not_overwritten_without_asking():
    d = _plan()
    annotate.apply_op(d, annotate.new_op("set_scale", 0, ppu=36.0, unit="ft"))
    rows = autoscale.detect(d)
    assert rows[0]["existing"] == pytest.approx(36.0)
    assert autoscale.apply(d, rows) == 0          # default: ok rows w/o existing
    assert annotate.read_scales(d)[0]["ppu"] == pytest.approx(36.0)


def test_real_set_written_scales_agree_with_dimensions():
    """The demo set: every plan's written scale matches its dimensions."""
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "trial", "autotakeoff_demo.pdf")
    if not os.path.exists(path):
        pytest.skip("trial/autotakeoff_demo.pdf not here")
    rows = autoscale.detect(fitz.open(path))
    assert all(r["ppu"] for r in rows)
    assert not any(r["dims"]["agree"] is False for r in rows)
    assert sum(1 for r in rows if r["dims"]["agree"]) >= 4


def test_review_dialog_prechecks_only_ok_rows():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    d = _plan()
    d.insert_pdf(_plan(wrong=True))
    d.new_page(width=1728, height=1152)
    rows = autoscale.detect(d)
    assert [r["status"] for r in rows] == ["ok", "check", "none"]
    dlg = autoscale.ScaleReviewDialog(rows)
    assert dlg.confirmed() == {0}


def test_enlarged_views_at_another_written_scale_go_to_review():
    """PM review NW-19 / Chief Q2: dimensions that match another scale
    written on the sheet could be enlarged views OR a print at another
    size, so the sheet goes to review with a note naming the other scale -
    never 'ok'."""
    d = _plan('SCALE: 1/8" = 1\'-0"', ppf=27.0)
    d[0].insert_text((1350, 1135), 'ENLARGED PLAN  SCALE: 3/8" = 1\'-0"',
                     fontsize=12)
    r = autoscale.detect(d)[0]
    assert r["ppu"] == pytest.approx(9.0) and r["status"] == "check"
    assert "3/8" in r["note"]


def test_dimensions_matching_no_written_scale_still_check():
    d = _plan('SCALE: 1/8" = 1\'-0"', ppf=13.5)        # printed at 1.5x
    d[0].insert_text((1350, 1135), 'DETAIL  SCALE: 3/8" = 1\'-0"',
                     fontsize=12)
    assert autoscale.detect(d)[0]["status"] == "check"


def test_review_queue_sets_a_sheet_by_hand():
    """P1 'auto-scale review queue': every sheet listed with its scale,
    source and status; a 'check' or 'none' sheet is set with one pick and
    then applied (made-up two-sheet set)."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    d = _plan()
    d2 = _plan(scale_text=None, dim_ft=0)
    d.insert_pdf(d2)
    rows = autoscale.detect(d)
    assert rows[0]["status"] == "ok" and rows[1]["status"] != "ok"
    dlg = autoscale.ScaleReviewDialog(rows)
    assert dlg.table.rowCount() == 2
    assert dlg.confirmed() == {0}
    dlg.set_scale(1, '1/8" = 1\'-0"')
    assert dlg.confirmed() == {0, 1}
    assert autoscale.apply(d, rows, dlg.confirmed()) == 2
    sc = annotate.read_scales(d)
    assert sc[1]["ppu"] == pytest.approx(9.0)
    with pytest.raises(ValueError):
        autoscale.set_row(dict(rows[0]), "1:7 odd")
