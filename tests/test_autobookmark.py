"""Auto Bookmark: detail callouts linked to the detail itself."""
import fitz
import pytest

from app import autobookmark


def _bubble(pg, x, y, num, sheet):
    pg.draw_circle((x, y), 16, width=1)
    pg.draw_line((x - 16, y), (x + 16, y), width=0.7)
    pg.insert_text((x - 3, y - 4), num, fontsize=9)
    pg.insert_text((x - 13, y + 11), sheet, fontsize=7)


def _set():
    d = fitz.open()
    a = d.new_page(width=1728, height=1152)
    a.insert_text((1500, 1100), "A-101", fontsize=20)
    a.insert_text((1500, 1060), "FIRST FLOOR PLAN", fontsize=12)
    _bubble(a, 300, 300, "3", "A-501")
    _bubble(a, 600, 500, "5", "A-501")
    _bubble(a, 900, 500, "7", "A-999")          # no such sheet
    a.insert_text((100, 900), "SEE A-501 FOR TYPICAL DETAILS", fontsize=9)
    b = d.new_page(width=1728, height=1152)
    b.insert_text((1500, 1100), "A-501", fontsize=20)
    b.insert_text((1500, 1060), "DETAILS", fontsize=12)
    _bubble(b, 200, 700, "3", "A-501")
    b.insert_text((230, 705), "WALL SECTION", fontsize=10)
    _bubble(b, 900, 300, "5", "A-501")
    b.insert_text((930, 305), "DOOR HEAD", fontsize=10)
    return d


def test_callouts_found_and_targets_located():
    d = _set()
    links = autobookmark.find_links(d)
    det = [l for l in links if l["kind"] == "detail"]
    assert {(l["detail"], l["sheet"]) for l in det} == {("3", "A-501"), ("5", "A-501")}
    for l in det:
        assert l["src_page"] == 0 and l["dst_page"] == 1
        assert l["dst_found"] is True
    three = [l for l in det if l["detail"] == "3"][0]
    assert abs(three["dst_point"][0] - 200) < 40 and abs(three["dst_point"][1] - 700) < 40
    # plain "SEE A-501" text -> sheet-level link, lower confidence
    sheet = [l for l in links if l["kind"] == "sheet"]
    assert len(sheet) == 1 and sheet[0]["confidence"] < three["confidence"]
    # a sheet's own detail titles are not callouts back to itself
    assert not any(l["src_page"] == 1 and l["dst_page"] == 1 for l in links)


def test_apply_makes_clickable_links_and_bookmarks():
    d = _set()
    links = autobookmark.find_links(d)
    n = autobookmark.apply(d, links)
    assert n == len(links)
    got = [l for l in d[0].get_links() if l["kind"] == fitz.LINK_GOTO]
    assert len(got) == len(links) and all(g["page"] == 1 for g in got)
    toc = d.get_toc()
    titles = [t[1] for t in toc]
    assert "Details" in titles[0] or any("3/A-501" in t for t in titles)
    # re-running doesn't duplicate
    autobookmark.apply(d, autobookmark.find_links(d))
    assert len([l for l in d[0].get_links() if l["kind"] == fitz.LINK_GOTO]) == len(links)


def test_embedded_links_reported():
    d = _set()
    d[0].insert_link({"kind": fitz.LINK_GOTO, "from": fitz.Rect(10, 10, 50, 30), "page": 1})
    assert autobookmark.embedded_links(d) == 1


def test_review_dialog_only_checked_applied():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    d = _set()
    links = autobookmark.find_links(d)
    dlg = autobookmark.LinkReviewDialog(links)
    assert len(dlg.accepted()) == sum(1 for l in links if l["confidence"] >= autobookmark.PRECHECK)
