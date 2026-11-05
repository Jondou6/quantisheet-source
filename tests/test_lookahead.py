"""Submittal look-ahead (Project Center): open submittals due in the next
few weeks plus the late ones, soonest first, as PDF or Excel."""
from datetime import date

import pytest

from app import settings
from app.pm import lookahead
from app.pm.store import ProjectStore

TODAY = date(2026, 10, 20)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Pat Morgan"})
    return ProjectStore(str(tmp_path / "Job"))


def add(store, title, spec="03 30 00", **kw):
    rec = {"title": title, "spec": spec, "type": "Product Data",
           "status": "Not Submitted", "responsible": "Acme Concrete"}
    rec.update(kw)
    return store.save_record("submittal", rec)


def titles(rows):
    return [r["title"] for r in rows]


def test_due_in_the_window(store):
    add(store, "Mix designs", submit_by="2026-10-30")
    add(store, "Rebar shops", submit_by="2026-11-20")     # past 4 weeks
    rows = lookahead.lookahead(store, 4, TODAY)
    assert titles(rows) == ["Mix designs"]
    r = rows[0]
    assert r["days_left"] == 10
    assert r["no"] == "03 30 00-001"
    assert r["ball"] == "Acme Concrete"
    assert r["for"] == "Submit"
    assert titles(lookahead.lookahead(store, 2, TODAY)) == ["Mix designs"]
    assert titles(lookahead.lookahead(store, 1, TODAY)) == []


def test_submit_by_worked_out_from_the_on_site_date(store):
    # needed Nov 30, 20 days lead, 10 review -> submit by Oct 31
    add(store, "Door hardware", "08 71 00", required_on_site="2026-11-30",
        lead_days=20, review_days=10)
    rows = lookahead.lookahead(store, 2, TODAY)
    assert rows[0]["submit_by"] == "2026-10-31"
    assert rows[0]["days_left"] == 11


def test_overdue_is_listed_with_negative_days(store):
    add(store, "Waterproofing", "07 13 00", submit_by="2026-10-01")
    rows = lookahead.lookahead(store, 2, TODAY)
    assert titles(rows) == ["Waterproofing"]
    assert rows[0]["days_left"] == -19


def test_review_step_due_date_counts_once_submitted(store):
    add(store, "Storefront shops", "08 41 13", status="In Review",
        submit_by="2026-09-01",
        workflow=[{"reviewer": "Architect", "due": "2026-10-27"}])
    add(store, "Returned step", "08 41 13", status="In Review",
        submit_by="2026-09-01",
        workflow=[{"reviewer": "Architect", "due": "2026-10-22",
                   "returned": "2026-10-15"}])
    rows = lookahead.lookahead(store, 2, TODAY)
    assert titles(rows) == ["Storefront shops"]
    assert rows[0]["days_left"] == 7
    assert rows[0]["for"] == "Review by Architect"
    assert rows[0]["ball"] == "Architect"


def test_closed_ones_are_left_out(store):
    for st in ("Approved", "Approved as Noted", "Rejected", "Closed"):
        add(store, st, submit_by="2026-10-01", status=st)
    add(store, "No dates at all")
    assert lookahead.lookahead(store, 4, TODAY) == []


def test_sorted_soonest_first(store):
    add(store, "C", submit_by="2026-11-05")
    add(store, "A", submit_by="2026-09-15")
    add(store, "B2", "09 21 16", submit_by="2026-10-20")
    add(store, "B1", "05 12 00", submit_by="2026-10-20")
    rows = lookahead.lookahead(store, 4, "2026-10-20")
    assert titles(rows) == ["A", "B1", "B2", "C"]
    assert [r["days_left"] for r in rows] == [-35, 0, 0, 16]


def test_export_xlsx_reads_back(store, tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    add(store, "Mix designs", submit_by="2026-10-30")
    add(store, "Waterproofing", "07 13 00", submit_by="2026-10-01")
    path = str(tmp_path / "look.xlsx")
    assert lookahead.export_xlsx(store, path, 3, TODAY) == path
    ws = openpyxl.load_workbook(path).active
    got = [list(r) for r in ws.iter_rows(values_only=True)]
    assert got[0] == lookahead.HEADERS
    assert [r[2] for r in got[1:]] == ["Waterproofing", "Mix designs"]
    assert got[1][10] == -19
    assert got[2][8].date() == date(2026, 10, 30)


def test_export_pdf(store, tmp_path):
    fitz = pytest.importorskip("fitz")
    pytest.importorskip("PySide6")
    add(store, "Mix designs", submit_by="2026-10-30")
    path = str(tmp_path / "look.pdf")
    lookahead.export(store, path, 4, TODAY)
    with fitz.open(path) as doc:
        text = doc[0].get_text()
    assert "Submittal look-ahead - 4 weeks" in text
    assert "Mix designs" in text
