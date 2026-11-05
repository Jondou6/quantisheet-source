"""Nov 3: a 99-sheet set with 31,580 markups froze QuantiSheet on open
(Acrobat opened it at once). Opening runs each panel once, sharing one
scan; a set with that many markups lists one page at a time and counts
unpriced markups only when asked; measurement scans skip markups that
can't be measurements without building their .info."""
import os

import pytest

fitz = pytest.importorskip("fitz")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import annotate, prebid  # noqa: E402
from test_gui import win, qapp  # noqa: E402,F401


def _big(path, n_per_page=1400, pages=3):
    d = fitz.open()
    for p in range(pages):
        pg = d.new_page(width=1224, height=792)
        for i in range(n_per_page):
            x, y = 20 + (i % 70) * 16, 20 + (i // 70) * 30
            a = pg.add_rect_annot(fitz.Rect(x, y, x + 10, y + 10))
            a.set_info(subject="Cloud+", content=f"note {i}")
            a.update()
    annotate.apply_op(d, annotate.new_op(
        "add_polygon", 1, pts=[[100, 600], [200, 600], [200, 700]],
        label="Fläche: 1 sq ft",
        measure={"type": "area", "value": 1.0, "unit": "sq ft",
                 "group": "Fläche m²"}))
    d.save(path)
    d.close()


def test_scan_skips_plain_markups_but_finds_encoded_ones(tmp_path):
    p = str(tmp_path / "big.pdf")
    _big(p, n_per_page=50, pages=2)
    d = fitz.open(p)
    plain = next(iter(annotate.iter_annots(d[0])))
    assert annotate.maybe_takeoff(d, plain) is False
    items = annotate.takeoff_items(d)
    assert [it["group"] for it in items] == ["Fläche m²"]
    assert annotate.annot_count(d) == 102          # 100 + area + its label


def test_big_set_opens_without_reading_everything(win, tmp_path,
                                                  monkeypatch):
    p = str(tmp_path / "big.pdf")
    _big(p)
    calls = []
    orig = win.markups.set_doc
    monkeypatch.setattr(win.markups, "set_doc",
                        lambda d: calls.append(1) or orig(d))
    read = []
    from app import overlay
    monkeypatch.setattr(overlay, "sheet_number",
                        lambda pg: read.append(pg.number) or "")
    assert win.open_path(p)
    assert len(calls) <= 1                       # not twice
    assert read == []                            # no sheet text read
    m = win.markups
    assert m.big() and m.page_only.isChecked()
    assert {it["page"] for it in m.items} <= {win._view.page}
    assert "untick This page" in m.count.text()
    m.page_only.setChecked(False)                # every markup on request
    assert len(m.items) >= 4200
    b = getattr(win, "workflow_boost", None)
    if b is not None:
        b.refresh_unpriced()
        assert b.unpriced_chip.text() == "Unpriced: click to count"
        b._chip_clicked()
        assert b.unpriced_count >= 4200


def test_unpriced_check_reads_no_sheet_text(tmp_path, monkeypatch):
    p = str(tmp_path / "big.pdf")
    _big(p, n_per_page=20, pages=3)
    d = fitz.open(p)
    from app import overlay
    monkeypatch.setattr(overlay, "sheet_number",
                        lambda pg: pytest.fail("sheet text read"))
    rep = prebid.check(d, sheets=False)
    assert rep.open_markups and rep.open_markups[0]["sheet"] == "Page 1"
