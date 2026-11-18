"""Bid Package (Nov 17): proposal, estimate summary, detail, takeoff sheets
and contents in one folder and one zip. Made-up drawings and quantities;
no prices are typed anywhere in this test."""
import os
import sys
import zipfile

import fitz
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import ai_quantities as aq, bidpackage as bp  # noqa: E402
from estimate_helpers import area  # noqa: E402

WHEN = "2026-11-17"


def job(tmp_path, pages=3):
    d = fitz.open()
    for _ in range(pages):
        d.new_page(width=1224, height=792)
    area(d, "Slab on grade", 20, 30, page=1)
    aq.store(d, {"quantities": [{
        "engine": "steel", "name": "W8x10 beams", "qty": 1520.0,
        "unit": "LB", "status": "taken off", "page": 2,
        "sheet": "S-101"}]})
    f = tmp_path / "Made Up Clinic.pdf"
    d.save(f)
    d.close()
    return fitz.open(f)


def test_package_folder_and_zip(tmp_path):
    d = job(tmp_path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    out = bp.make(d, str(out_dir), when=WHEN, comp={})
    assert os.path.basename(out["folder"]) == \
        "2026.11.17 Made Up Clinic Bid Package"
    parts = [k for k, _p in out["files"]]
    for k in ("proposal", "summary_pdf", "summary_xlsx", "detail_csv",
              "sheets_pdf", "contents"):
        assert k in parts, (k, out["skipped"])
    assert ("workbook", "run AI Takeoff first (made from its result)") in \
        out["skipped"]
    names = [os.path.basename(p) for _k, p in out["files"]]
    assert "2026.11.17 Made Up Clinic Proposal.pdf" in names
    assert "2026.11.17 Made Up Clinic Takeoff Sheets.pdf" in names
    with zipfile.ZipFile(out["zip"]) as z:
        got = sorted(os.path.basename(n) for n in z.namelist())
    assert got == sorted(names)


def test_takeoff_sheets_are_the_pages_with_takeoff(tmp_path):
    d = job(tmp_path, pages=4)
    assert bp.takeoff_pages(d) == [1, 2]
    p = tmp_path / "sheets.pdf"
    assert bp.sheets_pdf(d, str(p)) == 2
    with fitz.open(p) as s:
        assert s.page_count == 2
        assert len(list(s[0].annots())) >= 1       # the measurement kept


def test_contents_lists_what_needs_a_look(tmp_path):
    d = job(tmp_path)
    out = bp.make(d, str(tmp_path), when=WHEN, comp={})
    text = open(dict(out["files"])["contents"], encoding="utf-8").read()
    assert "Bid package - Made Up Clinic" in text
    assert "Takeoff Sheets.pdf" in text
    assert "Not included:" in text and "Estimate Workbook" in text
    assert "isn't locked" in text                  # nothing locked here
    assert "no price" in text                      # unpriced lines named
    assert "$" not in text


def test_second_package_same_day_gets_its_own_folder(tmp_path):
    d = job(tmp_path)
    a = bp.make(d, str(tmp_path), when=WHEN, parts=("contents",), comp={})
    b = bp.make(d, str(tmp_path), when=WHEN, parts=("contents",), comp={})
    assert a["folder"] != b["folder"] and b["folder"].endswith("(2)")


def test_with_ai_result_the_workbook_is_made(tmp_path):
    d = job(tmp_path)
    rows = [{"page": 2, "number": "S-101", "title": "FRAMING PLAN",
             "discipline": "structural", "kind": "plan"}]
    res = {"quantities": [{"engine": "steel", "name": "W8x10 beams",
                           "qty": 1520.0, "unit": "LB",
                           "status": "taken off", "page": 2,
                           "sheet": "S-101", "csi": "05 12 00",
                           "basis": "made up"}],
           "review": [], "marks": [], "sheets": {}}
    out = bp.make(d, str(tmp_path), when=WHEN, comp={}, ai_rows=rows,
                  ai_result=res, parts=("workbook", "contents"))
    assert "workbook" in dict(out["files"]), out["skipped"]


def test_a_part_that_fails_is_listed_and_the_rest_made(tmp_path,
                                                       monkeypatch):
    from app import estimate_export

    def boom(*a, **k):
        raise RuntimeError("made-up failure")
    monkeypatch.setattr(estimate_export, "save_pdf", boom)
    d = job(tmp_path)
    out = bp.make(d, str(tmp_path), when=WHEN, comp={})
    why = dict(out["skipped"])["summary_pdf"]
    assert "made-up failure" in why
    assert "summary_xlsx" in dict(out["files"])


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def win(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from app import settings
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    for name in ("information", "warning"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: 0))
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)   # never block
    monkeypatch.setenv("QUANTISHEET_SMOKE", "1")       # no background jobs
    from app.main_window import MainWindow
    w = MainWindow()
    yield w
    for v in w._all_views():
        v.dirty = False
    w.close()
    w.deleteLater()
    qapp.processEvents()


def test_window_command(win, tmp_path):
    d = job(tmp_path)
    path = d.name
    d.close()
    assert win.open_path(path)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    seen = []
    out = win.export_bid_package(folder=str(out_dir),
                                 ask=lambda t: seen.append(t) or False)
    assert out and os.path.isfile(out["zip"])
    assert "to send" in seen[0] and "Before you send it" in seen[0]
    names = [a.text() for a in win.findChildren(type(win.menuBar().actions()[0]))]
    assert "Export Bid Package…" in names


def test_board_match_and_mark_submitted(tmp_path, monkeypatch):
    from app import bidboard, settings
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    os.makedirs(tmp_path / "cfg", exist_ok=True)
    a = bidboard.save({"project": "Made Up Clinic Renovation",
                       "gc": "Made Up Builders", "status": "Accepted"})
    bidboard.save({"project": "Other Made Up School", "gc": "X",
                   "status": "Undecided"})
    bidboard.save({"project": "Made Up Clinic", "gc": "Y",
                   "status": "Lost"})                 # decided: not offered
    o = bp.board_match("Made Up Clinic Renovation")
    assert o and o["id"] == a["id"]
    assert bp.board_match("Something Else Entirely") is None
    done = bp.mark_submitted(o, {"folder": str(tmp_path /
                                               "2026.11.17 X Bid Package")})
    assert done["status"] == "Submitted"
    assert "Bid package: 2026.11.17 X Bid Package" in done["notes"]


def test_window_offers_the_bid_board(win, tmp_path):
    from app import bidboard
    bidboard.save({"project": "Made Up Clinic", "gc": "Made Up Builders",
                   "status": "Accepted"})
    d = job(tmp_path)
    path = d.name
    d.close()
    assert win.open_path(path)
    out_dir = tmp_path / "out2"
    out_dir.mkdir()
    seen = []
    out = win.export_bid_package(folder=str(out_dir),
                                 ask=lambda t: seen.append(t) or
                                 "Bid Board" in t)
    assert "Made Up Builders" in seen[0]
    assert out["board"]["status"] == "Submitted"
    assert seen[-1].endswith("Open the folder?")
