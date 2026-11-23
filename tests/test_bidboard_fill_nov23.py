"""Project Analysis to the Bid Board (Nov 23, Jon: both places): "Send to
Bid Board" in the Project Analysis window and "Fill From Specs" in the Bid
Board's edit window. Only empty fields are filled. Made-up project."""
import os
import sys

import fitz
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import bidboard as B, projanalysis as pa, settings  # noqa: E402

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
    "the site.\nQuestions must be submitted in writing no later than "
    "December 1, 2026 at 5:00 PM.",
    "SECTION 01 10 00 - SUMMARY\n1.2 SUMMARY OF WORK\nA. The Work consists "
    "of a new single-story restroom building with site utilities, paving "
    "and landscaping.",
]


@pytest.fixture(autouse=True)
def cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Pat Morgan"})


def _spec(path, pages=PAGES):
    d = fitz.open()
    for t in pages:
        pg = d.new_page()
        pg.insert_textbox(fitz.Rect(54, 54, 558, 738), t, fontsize=10)
    d.save(path)
    d.close()


def _rows(tmp_path):
    p = tmp_path / "Example Specs.pdf"
    _spec(str(p))
    return pa.run(fitz.open(str(p)))


def test_fields_from_the_answers(tmp_path):
    f = pa.bidboard_fields(_rows(tmp_path), "Example Specs.pdf")
    assert f["project"] == "Example Park Restroom Building"
    assert f["address"].startswith("123 Sample Road")
    assert f["location"] == "Exampleville, SC"
    assert f["due"] == "2026-12-08"
    assert f["due_time"] == "2:00 PM"
    assert f["job_walk"] == "2026-11-30 10:00 AM"
    assert f["prebid_mandatory"] == "Yes"
    assert f["rfi_due"] == "2026-12-01"
    assert f["notes"].startswith("From the specs: ")
    assert f["source"] == "Example Specs.pdf"
    # and the Bid Board keeps them as they are
    o = B.clean(dict(f, status="Undecided"))
    assert o["due"] == "2026-12-08" and o["job_walk"].startswith("2026-11-30")
    assert o["prebid_mandatory"] == "Yes"


def test_not_found_fills_nothing():
    rows = [{"key": "project_name", "label": "1", "value": "not found",
             "page": None}, {"key": "bid_date", "label": "7",
                             "value": "not found", "page": None}]
    assert pa.bidboard_fields(rows) == {}


def test_optional_prebid_and_city_after_the_street():
    rows = [{"key": "prebid", "value": "non-mandatory, January 5, 2027",
             "page": 1, "text": ""},
            {"key": "address", "value": "400 Oak Avenue Sampletown, NC 27000",
             "page": 0, "text": ""}]
    f = pa.bidboard_fields(rows)
    assert f["prebid_mandatory"] == "No"
    assert f["job_walk"] == "2027-01-05"
    assert f["location"] == "Sampletown, NC"


def test_only_empty_fields_are_filled():
    o, filled = pa.fill_empty({"project": "Our Name", "due": ""},
                              {"project": "Theirs", "due": "2026-12-08"})
    assert o["project"] == "Our Name" and o["due"] == "2026-12-08"
    assert filled == ["due"]


def test_send_to_bid_board_from_project_analysis(win, tmp_path):
    p = tmp_path / "Example Specs.pdf"
    _spec(str(p))
    assert win.open_path(str(p))
    dlg = win.project_analysis(show=False)
    names = [b.text() for b in dlg.findChildren(type(dlg.board_btn))]
    assert "Send to Bid Board" in names
    od = dlg.send_to_board(show=False)
    assert od.w["project"].text() == "Example Park Restroom Building"
    assert od.w["due"].text() == "2026-12-08"
    assert od.w["rfi_due"].text() == "2026-12-01"
    from PySide6.QtWidgets import QLabel
    assert any("Read from the specifications" in x.text()
               for x in od.findChildren(QLabel))
    assert B.load() == []                     # nothing saved yet
    saved = od.save()
    assert saved["project"] == "Example Park Restroom Building"
    assert saved["source"] == "Example Specs.pdf"
    assert [x["id"] for x in B.load()] == [saved["id"]]


def test_fill_from_specs_in_the_bid_board_edit_window(win, tmp_path):
    from app import bidboard_ui
    p = tmp_path / "Example Specs.pdf"
    _spec(str(p))
    assert win.open_path(str(p))
    board = bidboard_ui.show(win)
    try:
        od = bidboard_ui.OpportunityDialog(board, {"project": "Typed Name",
                                                   "gc": "Example Builders"})
        assert od.specs_btn.text() == "Fill From Specs"
        filled = od.fill_from_specs()
        assert "project" not in filled and "due" in filled
        assert od.w["project"].text() == "Typed Name"       # kept
        assert od.w["gc"].text() == "Example Builders"
        assert od.w["due"].text() == "2026-12-08"
        assert od.w["job_walk"].text() == "2026-11-30 10:00 AM"
        assert "Filled from the specs" in od.warn.text()
        assert od.fill_from_specs() == []                   # all full now
        assert "Nothing new" in od.warn.text()
        od.close()
    finally:
        board.close()


def test_fill_from_specs_with_nothing_open(qapp):
    from app import bidboard_ui
    od = bidboard_ui.OpportunityDialog(None, {"project": "Typed Name"})
    assert od.fill_from_specs() == []
    assert "Open the specifications first" in od.warn.text()
