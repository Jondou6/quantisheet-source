"""Project Analysis (Nov 20, Jon): one button on the specs answers his
nine bid questions, each with its page. Made-up project and text."""
import os
import sys

import fitz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import bidterms  # noqa: E402

try:
    from test_gui import win, qapp  # noqa: F401,E402
except Exception:                                         # noqa: BLE001
    pass

PAGES = [
    "PROJECT MANUAL\nProject Name: Example Park Restroom Building\n"
    "Project Location: 123 Sample Road, Exampleville, SC 29000",
    "INVITATION TO BID\nSealed bids will be received by the Owner until "
    "2:00 PM local time on December 8, 2026 at the Town Hall.\nA MANDATORY "
    "pre-bid conference will be held on November 30, 2026 at 10:00 AM at "
    "the site.\nThe estimated construction cost is between 2 and 3 million "
    "dollars.",
    "SECTION 01 10 00 - SUMMARY\n1.2 SUMMARY OF WORK\nA. The Work consists "
    "of a new single-story restroom building with site utilities, paving "
    "and landscaping.",
    "The Contractor shall achieve Substantial Completion within 180 "
    "calendar days and Final Completion within 210 calendar days. "
    "Liquidated damages will be assessed in the sum of 750 dollars for "
    "each calendar day. The Owner will retain 5% of each progress payment.",
]


def _spec(path, pages=PAGES):
    d = fitz.open()
    for t in pages:
        pg = d.new_page()
        pg.insert_textbox(fitz.Rect(54, 54, 558, 738), t, fontsize=10)
    d.save(path)
    d.close()


def test_all_nine_answered_with_pages(tmp_path):
    p = tmp_path / "spec.pdf"
    _spec(str(p))
    rows = bidterms.analysis(fitz.open(str(p)))
    got = {r["key"]: (r["value"], r["page"]) for r in rows}
    assert [r["key"] for r in rows[:10]] == [k for k, _ in bidterms.ANALYSIS]
    assert got["project_name"] == ("Example Park Restroom Building", 0)
    assert got["address"][0] == "123 Sample Road, Exampleville, SC 29000"
    assert got["budget"] == ("2 million to 3 million dollars", 1)
    assert got["substantial"] == ("180 calendar days", 3)
    assert got["final"] == ("210 calendar days", 3)
    assert got["ld_value"] == ("750 dollars per day", 3)
    assert got["summary"][0].startswith("The Work consists of a new")
    assert got["bid_date"] == ("December 8, 2026, 2:00 PM", 1)
    assert got["prebid"][0] == "mandatory, November 30, 2026 at 10:00 AM"
    assert got["retainage"] == ("5%", 3)


def test_not_found_rows_say_so(tmp_path):
    p = tmp_path / "thin.pdf"
    _spec(str(p), ["SECTION 09 91 23 - PAINTING\nPART 1 - GENERAL"])
    rows = bidterms.analysis(fitz.open(str(p)))
    assert len(rows) == 10 and all(r["page"] is None for r in rows)
    assert rows[2]["value"] == "not listed"         # budget usually isn't
    assert rows[0]["value"] == "not found"


def test_the_button_and_window(win, tmp_path):
    p = tmp_path / "spec.pdf"
    _spec(str(p))
    assert win.open_path(str(p))
    act = win.command("Project Analysis…")
    assert act is not None
    dlg = win.project_analysis(show=False)
    assert dlg.windowTitle() == "Project Analysis"
    assert dlg.table.item(0, 1).text() == "Example Park Restroom Building"
    assert dlg.go(9) == 3 and win._view.page == 3
    text = dlg.copy()
    assert "7. Bid date: December 8, 2026, 2:00 PM (p. 2)" in text
    g = win.ribbon.page("Home").group("Specs")
    assert any(b.defaultAction() is act for b in g.buttons)
    # its own ribbon tab after Tools, and its own menu after Tools
    pg = win.ribbon.page("Project Analysis").group("Project Analysis")
    have = {b.defaultAction().text() for b in pg.buttons
            if b.defaultAction() is not None}
    for name in ("Project Analysis…", "Find Bid Terms…",
                 "Manufacturers in Specs…", "Bid Submittal Checklist…"):
        assert name in have
    from app import quickaccess as qa
    i = qa.TAB_ORDER.index("Tools")
    assert qa.TAB_ORDER[i + 1] == "Project Analysis"
    titles = [a.text().replace("&", "") for a in win.menuBar().actions()]
    assert titles[titles.index("Tools") + 1] == "Project Analysis"
    pam = win.menuBar().actions()[titles.index("Project Analysis")].menu()
    assert [a.text() for a in pam.actions()] == [
        "Project Analysis…", "Find Bid Terms…", "Manufacturers in Specs…",
        "Bid Submittal Checklist…"]


MORE = PAGES + [
    "SECTION 00 21 13 - INSTRUCTIONS TO BIDDERS\nOwner: Town of Example\n"
    "Architect: Sample Design Group\nQuestions must be submitted in writing "
    "no later than December 1, 2026 at 5:00 PM. Bids shall be submitted "
    "electronically. The successful bidder shall furnish a performance bond "
    "and payment bond each in the amount of 100% of the contract sum. "
    "UNIT PRICE NO. 1 - rock excavation. UNIT PRICE NO. 2 - unsuitable "
    "soil.",
    "ADDENDUM NO. 1\nThe bid date is changed. Sealed bids will be received "
    "until 2:00 PM on December 15, 2026.",
]


def test_addendum_wins_and_extras(tmp_path):
    from app import projanalysis as pa
    p = tmp_path / "spec.pdf"
    _spec(str(p), MORE)
    rows = pa.run(fitz.open(str(p)))
    by = {r["key"]: r for r in rows}
    assert by["bid_date"]["value"] == "December 15, 2026, 2:00 PM"
    assert by["bid_date"]["page"] == 5
    assert ("December 8, 2026, 2:00 PM", 1) in by["bid_date"]["also"]
    assert by["questions_due"]["value"] == "December 1, 2026, 5:00 PM"
    assert by["perf_bond"]["value"] == "100% of the contract"
    assert by["pay_bond"]["value"] == "100% of the contract"
    assert "electronic" in by["delivery"]["value"]
    assert by["unit_prices"]["value"] == "2 (No. 1, 2)"
    assert by["addenda"]["value"] == "1 (No. 1)"
    assert by["owner"]["value"] == "Town of Example"
    assert by["architect"]["value"] == "Sample Design Group"
    assert by["owner"]["section"] == "00 21 13 Instructions To Bidders"
    assert by["insurance"]["value"] == "not found"
    assert by["summary"]["section"].startswith("01 10 00")


def test_dates_exposure_cache_and_pdf(tmp_path):
    import datetime
    from decimal import Decimal
    from app import projanalysis as pa
    p = tmp_path / "spec.pdf"
    _spec(str(p))
    doc = fitz.open(str(p))
    rows = pa.run(doc)
    d = pa.completion_dates(rows, datetime.date(2027, 1, 4))
    assert d["substantial"] == datetime.date(2027, 7, 3)     # +180 days
    assert d["final"] == datetime.date(2027, 8, 2)           # +210 days
    assert pa.add_days(datetime.date(2026, 11, 20), 5, "working") == \
        datetime.date(2026, 11, 27)                           # Fri + 5 wd
    rate = pa.ld_rate(rows)
    assert rate == Decimal(750)
    assert pa.ld_exposure(rows, 30) == rate * 30
    assert pa.cached(doc) is None
    pa.save(doc, rows)
    assert pa.cached(doc) == rows
    doc.new_page()                                  # an addendum added
    assert pa.cached(doc) is None
    out = pa.export_pdf(rows, str(tmp_path / "a.pdf"),
                        ntp=datetime.date(2027, 1, 4), days_late=30)
    txt = fitz.open(out)[0].get_text()
    assert "1. Project name: Example Park Restroom Building" in txt
    assert "from NTP 2027-01-04: 2027-07-03" in txt


def test_window_ntp_and_run_again(win, tmp_path):
    p = tmp_path / "spec.pdf"
    _spec(str(p), MORE)
    assert win.open_path(str(p))
    dlg = win.project_analysis(show=False)
    assert not dlg.from_cache
    dlg.use_ntp.setChecked(True)
    texts = [dlg.table.item(r, 0).text() for r in range(dlg.table.rowCount())]
    assert any("also stated" in t for t in texts)
    assert any(t.endswith("from NTP") for t in texts)
    assert "LD exposure" in texts
    again = win.project_analysis(show=False)
    assert again.from_cache
    assert again.run_again()
    assert os.path.exists(dlg.export_pdf(str(tmp_path / "pa.pdf")))
