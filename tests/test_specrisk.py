"""Nov 3 (#9): Spec Book Risk Scanner. Made-up spec text."""
import os

import fitz
import pytest

from app import specrisk as S

PAGES = ["SECTION 00 21 13 - INSTRUCTIONS TO BIDDERS. A bid bond in the "
         "amount of 5 percent of the bid is required. Performance and "
         "payment bonds 100% of the contract sum.",
         "Liquidated damages of $1,500.00 per calendar day will be assessed."
         " Davis-Bacon wage determination applies.",
         "Commercial general liability $1,000,000 each occurrence. Umbrella "
         "liability of $5,000,000.",
         "Provide manufacturer one year warranty. Provide a 20-year "
         "manufacturer warranty for the roof. Special warranty: five (5) "
         "years.",
         "The Contractor shall engage a qualified testing agency."]


def test_terms_found():
    got = {(r["kind"], r["value"]) for r in S.scan_pages(PAGES)}
    assert ("bond", "Bid bond 5%") in got
    assert ("bond", "Performance and payment bond 100%") in got
    assert ("ld", "$1,500.00 per day") in got
    assert ("wage", "Prevailing wage / wage determination") in got
    assert ("insurance", "$1,000,000 each occurrence") in got
    assert ("warranty", "20-year warranty") in got
    assert ("warranty", "5-year warranty") in got
    assert not any(v == "1-year warranty" for _k, v in got)
    assert any(k == "testing" for k, _v in got)


def test_sections_and_pdf(tmp_path):
    secs = [{"number": "00 21 13", "title": "Instructions", "start": 0,
             "end": 1}]
    got = S.scan_pages(PAGES, secs)
    assert got[0]["section"].startswith("00 21 13")
    p = S.summary_pdf(got, str(tmp_path / "r.pdf"), "Test Job")
    t = fitz.open(p)[0].get_text()
    assert "SPEC BOOK RISK SUMMARY" in t and "Liquidated damages" in t


def test_window(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app import specrisk_ui
    d = fitz.open()
    for t in PAGES:
        d.new_page().insert_textbox(fitz.Rect(40, 40, 560, 760), t,
                                    fontsize=9)
    opened = []
    w = specrisk_ui.SpecRiskDialog(doc=d, open_result=opened.append)
    assert w.table.rowCount() >= 8
    assert w.summary(str(tmp_path / "s.pdf")) and opened


# ---- Nov 4: Bid Form & Insurance Review PDF ----------------------------------

GC_PAGES = ["SECTION 00 21 13 INSTRUCTIONS TO BIDDERS\nBids are due.",
            "SECTION 00 72 00 GENERAL CONDITIONS\nARTICLE 10 PROTECTION\nx",
            "ARTICLE 11\nINSURANCE AND BONDS\nCommercial general liability "
            "$1,000,000 each occurrence.",
            "More insurance text. Umbrella liability of $5,000,000.",
            "ARTICLE 12 CHANGES IN THE WORK\nChanges.",
            "SECTION 00 73 16 INSURANCE REQUIREMENTS\nBuilder's Risk "
            "insurance on a completed value form. Deductible not to exceed "
            "$5,000 per occurrence.",
            "SECTION 01 10 00 SUMMARY\nNothing here."]
GC_SECS = [{"number": "00 21 13", "title": "Instructions", "start": 0,
            "end": 0},
           {"number": "00 72 00", "title": "General Conditions", "start": 1,
            "end": 4},
           {"number": "00 73 16", "title": "Insurance Requirements",
            "start": 5, "end": 5},
           {"number": "01 10 00", "title": "Summary", "start": 6, "end": 6}]


def test_review_items_find_insurance_and_builders_risk():
    items = S.review_items(GC_PAGES, GC_SECS)
    ins = [i for i in items if i["kind"] == "insurance"]
    assert [i["pages"] for i in ins] == [[2, 3], [5]]   # stops at Article 12
    assert "$1,000,000 each occurrence" in ins[0]["terms"]
    br = [i for i in items if i["kind"] == "builders_risk"][0]
    assert br["pages"] == [5] and "Deductible $5,000" in br["terms"]
    none = S.review_items(["SECTION 01 10 00 SUMMARY"], GC_SECS[3:4])
    assert all(i.get("missing") for i in none) and len(none) == 3


def test_review_pdf_has_the_pages_and_a_cover(tmp_path):
    d = fitz.open()
    for t in GC_PAGES:
        d.new_page().insert_textbox(fitz.Rect(40, 40, 560, 760), t,
                                    fontsize=9)
    items = S.review_items(GC_PAGES, GC_SECS)
    p = S.review_pdf(d, items, str(tmp_path / "r.pdf"), "Job X")
    r = fitz.open(p)
    assert r.page_count == 1 + 2 + 1 + 1                 # cover + pages
    cover = r[0].get_text()
    assert "BID FORM & INSURANCE REVIEW" in cover and "Job X" in cover
    assert "Builder's risk requirements" in cover
    assert "ARTICLE 11" in r[1].get_text()
    assert [t[1] for t in r.get_toc()][0] == "What was found"


def test_scanner_window_makes_the_review(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app import specrisk_ui
    d = fitz.open()
    for t in GC_PAGES:
        d.new_page().insert_textbox(fitz.Rect(40, 40, 560, 760), t,
                                    fontsize=9)
    src = str(tmp_path / "Fire Station Specs.pdf")
    d.save(src)
    opened = []
    w = specrisk_ui.SpecRiskDialog(open_result=opened.append)
    w.pick(src)
    assert w.review_path == str(tmp_path / ("Fire Station Specs - Bid Form "
                                            "& Insurance Review.pdf"))
    assert os.path.isfile(w.review_path)
    assert "Bid Form & Insurance Review" in w.note.text()
    assert w.open_review() == w.review_path and opened


def test_review_items_find_the_bid_form():
    pages = ["SECTION 00 41 13\nBID FORM\n1. Mobilization LS $____\n"
             "2. Sidewalk 1,250 SF $____\nAlternate No. 1: Canopy $____",
             "SECTION 01 10 00 SUMMARY"]
    secs = [{"number": "00 41 13", "title": "Bid Form - Stipulated Sum",
             "start": 0, "end": 0},
            {"number": "01 10 00", "title": "Summary", "start": 1, "end": 1}]
    bf = [i for i in S.review_items(pages, secs) if i["kind"] == "bid_form"]
    assert bf[0]["pages"] == [0] and "2 bid item(s)" in bf[0]["terms"]
    # no sections read: a page headed like a bid form still counts
    bf = [i for i in S.review_items(pages) if i["kind"] == "bid_form"]
    assert bf[0]["pages"] == [0]
