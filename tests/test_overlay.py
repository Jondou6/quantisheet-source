"""Compare Revisions: pairing by sheet number, lining up, changes,
the vector overlay and slip sheeting with takeoffs kept."""
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import annotate, overlay  # noqa: E402
from test_gui import ANSWERS, win, qapp                    # noqa: E402,F401

W, H = 600, 400
SHIFT = (15, 9)


def _sheet(doc, number, lines, shift=(0, 0)):
    p = doc.new_page(width=W, height=H)
    dx, dy = shift
    p.draw_rect(fitz.Rect(20 + dx, 20 + dy, 480 + dx, 360 + dy), width=3)
    for (x0, y0, x1, y1) in lines:
        p.draw_line((x0 + dx, y0 + dy), (x1 + dx, y1 + dy), width=3)
    p.insert_text((W - 90 + dx, H - 18 + dy), number, fontsize=16)
    return p


def _sets(tmp_path):
    old = fitz.open()
    _sheet(old, "A-101", [(50, 100, 450, 100), (50, 300, 300, 300)])
    _sheet(old, "A-102", [(100, 50, 100, 340)])
    new = fitz.open()
    _sheet(new, "A-102", [(100, 50, 100, 340)])           # unchanged, moved
    _sheet(new, "A-101", [(50, 100, 450, 100),            # kept
                          (250, 150, 250, 330)],          # added; 300 removed
           shift=SHIFT)
    _sheet(new, "A-103", [(60, 60, 400, 60)])             # a new sheet
    po, pn = str(tmp_path / "old.pdf"), str(tmp_path / "new.pdf")
    old.save(po)
    new.save(pn)
    return po, pn


def _rgb(page, x, y, dpi=72):
    pix = page.get_pixmap(dpi=dpi, annots=False)
    return pix.pixel(int(x * dpi / 72), int(y * dpi / 72))[:3]


def test_pair_align_and_changes(tmp_path):
    po, pn = _sets(tmp_path)
    old, new = fitz.open(po), fitz.open(pn)
    assert overlay.sheet_number(old[0]) == "A-101"
    pairs = overlay.pair_pages(old, new)
    assert (0, 1, "A-101") in pairs and (1, 0, "A-102") in pairs
    assert (None, 2, "A-103") in pairs
    m = overlay.align(old[0], new[1])
    s, tx, ty, score, rot = m
    assert rot == pytest.approx(0, abs=0.05)
    assert s == pytest.approx(1.0, abs=0.01)
    assert tx == pytest.approx(SHIFT[0], abs=1.0)
    assert ty == pytest.approx(SHIFT[1], abs=1.0)
    assert score > 0.8
    rects, pct = overlay.changes(old[0], new[1], m)
    assert 1 <= len(rects) <= 4 and pct > 0
    added = fitz.Rect(250 + SHIFT[0], 150 + SHIFT[1], 251 + SHIFT[0],
                      330 + SHIFT[1])
    removed = fitz.Rect(50 + SHIFT[0], 299 + SHIFT[1], 300 + SHIFT[0],
                        301 + SHIFT[1])
    assert any(r.intersects(added) for r in rects)
    assert any(r.intersects(removed) for r in rects)
    # the unchanged, re-ordered sheet has no changes
    rects2, pct2 = overlay.changes(old[1], new[0],
                                   overlay.align(old[1], new[0]))
    assert rects2 == [] and pct2 == 0


def test_overlay_document_layers_and_colors(tmp_path):
    po, pn = _sets(tmp_path)
    old, new = fitz.open(po), fitz.open(pn)
    res = overlay.compare(old, new)
    doc = overlay.overlay_document(old, new, res, "Rev 1", "Rev 2")
    assert doc.page_count == 3
    names = sorted(i["name"] for i in doc.get_ocgs().values())
    assert names == ["Rev 1 (red)", "Rev 2 (green)"]
    toc = [t[1] for t in doc.get_toc()]
    assert any(t.startswith("A-101 - ") and "change" in t for t in toc)
    assert any(t.startswith("A-103 - added") for t in toc)
    p = doc[[r["sheet"] for r in res].index("A-101")]
    # unchanged line: dark; removed (older only): red; added: green
    kept = _rgb(p, 200 + SHIFT[0], 100 + SHIFT[1])
    gone = _rgb(p, 150 + SHIFT[0], 300 + SHIFT[1])
    new_ = _rgb(p, 250 + SHIFT[0], 240 + SHIFT[1])
    assert max(kept) < 90
    assert gone[0] > 150 and gone[1] < 90
    assert new_[1] > 100 and new_[0] < 90
    assert any((a.info or {}).get("subject") == overlay.CHANGE_SUBJECT
               for a in p.annots())
    out = str(tmp_path / "overlay.pdf")
    doc.save(out)
    assert fitz.open(out).page_count == 3


def test_slip_sheet_keeps_takeoffs_and_flags_changed_ones(tmp_path):
    po, pn = _sets(tmp_path)
    doc, new = fitz.open(po), fitz.open(pn)
    annotate.apply_op(doc, annotate.new_op("set_scale", 0, ppu=18,
                                           unit="ft"))
    near = annotate.new_op("add_polyline", 0, pts=[[60, 300], [290, 300]],
                           measure={"type": "length", "value": 12.8,
                                    "unit": "ft", "group": "Wall"})
    far = annotate.new_op("add_polyline", 0, pts=[[60, 100], [440, 100]],
                          measure={"type": "length", "value": 21.1,
                                   "unit": "ft", "group": "Wall"})
    annotate.apply_op(doc, near)
    annotate.apply_op(doc, far)
    res = overlay.compare(doc, new)
    out = overlay.slip_sheet(doc, new, res, "Rev 1")
    assert out["replaced"] == 2 and out["added"] == 1
    doc = overlay.reopen(doc)
    assert doc.page_count == 3
    page = doc[0]
    # the newer drawing, lined up with the old sheet: the added line shows
    # where it belongs in the old frame, the removed one is gone
    assert max(_rgb(page, 250, 240)) < 90
    assert min(_rgb(page, 150, 300)) > 200
    assert min(_rgb(page, 150, 200)) > 200
    # still hidden after saving and reopening
    tmp = str(tmp_path / "slip0.pdf")
    doc.save(tmp)
    assert min(_rgb(fitz.open(tmp)[0], 150, 300)) > 200
    ocgs = {i["name"]: i for i in doc.get_ocgs().values()}
    assert "Previous drawing (Rev 1)" in ocgs
    assert ocgs["Previous drawing (Rev 1)"]["on"] is False
    # takeoffs are still there, and the one on the changed area is flagged
    subs = [a for a in page.annots()
            if (a.info or {}).get("subject", "").startswith(
                annotate.TAKEOFF)]
    assert len(subs) == 2
    marks = overlay.flag_ops(doc, res, "old")
    assert len(marks) == 1 and marks[0][1] == "set_annot"
    for pno, kind, payload in marks:
        annotate.apply_op(doc, annotate.new_op(kind, pno, **payload))
    flagged = [a for a in doc[0].annots()
               if annotate.status_of(doc, a) == overlay.REVIEW_STATUS]
    assert len(flagged) == 1
    assert annotate.REVISED in annotate.statuses()
    path = str(tmp_path / "slip.pdf")
    doc.save(path)
    d2 = fitz.open(path)
    assert d2.page_count == 3 and len(list(d2[0].annots())) >= 2


def test_compare_revisions_window(qapp, win, tmp_path):
    from app.overlay_ui import CompareRevisionsDialog
    po, pn = _sets(tmp_path)
    win.open_path(po)
    dlg = win.compare_revisions(pn)
    assert isinstance(dlg, CompareRevisionsDialog)
    assert dlg.is_newer.isChecked()
    res = dlg.run()
    assert len(res) == 3 and dlg.table.rowCount() == 3
    assert dlg.b_slip.isEnabled() and dlg.b_overlay.isEnabled()
    v = dlg.make_overlay()
    assert v is not None
    win.tabs.setCurrentIndex(win.tabs.count() - 2)
    dlg.view = win._view
    out = dlg.slip()
    assert out and out["replaced"] == 2 and out["added"] == 1
    assert win._view.doc.page_count == 3
    clouds = [a for a in win._view.doc[0].annots()
              if (a.info or {}).get("subject") == overlay.CHANGE_SUBJECT]
    assert clouds
    win.undo()


# ---- rotated revisions and manual alignment -------------------------------------

import math  # noqa: E402

ROT, TR = 1.5, (10, -6)


def _rot(pt):
    c = (W / 2, H / 2)
    t = math.radians(ROT)
    x, y = pt[0] - c[0], pt[1] - c[1]
    return (math.cos(t) * x - math.sin(t) * y + c[0] + TR[0],
            math.sin(t) * x + math.cos(t) * y + c[1] + TR[1])


def _rotated_sets(tmp_path):
    old = fitz.open()
    p = old.new_page(width=W, height=H)
    p.draw_rect(fitz.Rect(40, 40, 520, 340), width=3)
    p.draw_line((80, 120), (480, 120), width=3)
    new = fitz.open()
    q = new.new_page(width=W, height=H)
    q.draw_polyline([_rot(c) for c in ((40, 40), (520, 40), (520, 340),
                                       (40, 340), (40, 40))], width=3)
    q.draw_line(_rot((80, 120)), _rot((480, 120)), width=3)
    q.draw_line(_rot((300, 180)), _rot((300, 320)), width=3)     # added
    po, pn = str(tmp_path / "rold.pdf"), str(tmp_path / "rnew.pdf")
    old.save(po)
    new.save(pn)
    return po, pn


def test_manual_alignment_with_rotation(tmp_path):
    po, pn = _rotated_sets(tmp_path)
    old, new = fitz.open(po), fitz.open(pn)
    pts_old = [(40, 40), (520, 340)]
    m = overlay.align_points(pts_old, [_rot(p) for p in pts_old],
                             old[0], new[0])
    assert m[0] == pytest.approx(1.0, abs=1e-6)
    assert m[4] == pytest.approx(ROT, abs=1e-6)
    assert m[3] > 0.8                                     # it overlaps
    assert max(overlay.residuals(pts_old, [_rot(p) for p in pts_old],
                                 m)) < 1e-6
    back = overlay.map_point(overlay.map_point((123, 45), m), m, True)
    assert back.x == pytest.approx(123) and back.y == pytest.approx(45)
    rects, pct = overlay.changes(old[0], new[0], m)
    added = fitz.Rect(_rot((300, 250)), _rot((300, 250))) + (-1, -1, 1, 1)
    assert 1 <= len(rects) <= 2 and any(r.intersects(added) for r in rects)
    with pytest.raises(ValueError):
        overlay.align_points([(0, 0)], [(1, 1)])
    res = [{"old": 0, "new": 0, "sheet": "", "align": m, "changes": rects,
            "changed_pct": pct}]
    doc = overlay.overlay_document(old, new, res, clouds=False)
    kept = _rot((300, 120))
    assert max(_rgb(doc[0], *kept)) < 90                  # lined up: dark
    # slip sheet: the rotated new drawing lands on the old frame
    od = fitz.open(po)
    overlay.slip_sheet(od, new, res, "R0")
    od = overlay.reopen(od)
    assert max(_rgb(od[0], 300, 250)) < 90                # the added line
    assert max(_rgb(od[0], 200, 120)) < 90                # the kept line


def test_align_manually_in_the_window(qapp, win, tmp_path):
    from app.overlay_ui import PointAlignDialog
    po, pn = _rotated_sets(tmp_path)
    win.open_path(po)
    dlg = win.compare_revisions(pn)
    dlg.run()
    old, new = fitz.open(po), fitz.open(pn)
    pick = PointAlignDialog(old[0], new[0], "R-1", dlg)
    assert not pick.ok.isEnabled()
    pick.add_point("old", (40, 40))
    pick.add_point("new", _rot((40, 40)))
    pick.add_point("old", (520, 340))
    pick.undo()
    assert pick.points["old"] == [(40, 40)]
    pick.add_point("old", (520, 340))
    pick.add_point("new", _rot((520, 340)))
    assert pick.ok.isEnabled() and "turned" in pick.status.text()
    assert pick.result()[4] == pytest.approx(ROT, abs=1e-6)
    # snapping finds the drawn corner from a near miss
    near = pick.views["old"].snap(fitz.Point(41.5, 39))
    assert (round(near.x), round(near.y)) == (40, 40)
    m = dlg.align_manually(0, (pick.points["old"], pick.points["new"]),
                           apply_all=False)
    assert m[4] == pytest.approx(ROT, abs=1e-6)
    assert dlg.results[0]["manual"] and dlg.results[0]["changes"]
    assert "turned" in dlg.table.item(0, 3).text()
