"""Scope Sheets clarifications (app/pm/scope_sheet.py, scope_sheet_ui.py):
per bidder, qualifications / exclusions / clarifications with an optional
$ adjustment and Accept / Reject / Pending. Accepted amounts change the
bidder's leveled total (add or deduct, to the cent); rejected rows are
kept but not counted; schema 2 with migration from 1; the Excel and PDF
exports carry a Clarifications section per trade; Import from Proposal
prefills rows. Made-up companies and numbers only."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import settings                                         # noqa: E402
from app.pm import scope_sheet as ss                             # noqa: E402

M = ss.parse_money


def _sheet():
    sh = ss.new_sheet("09 29 00", "Drywall & framing", bidders=2)
    a, b = sh["bidders"]
    a["company"], b["company"] = "Example Drywall LLC", "Sample Interiors Inc"
    a["price"], b["price"] = M("240,000.00"), M("236,500.00")
    sh["budget"]["price"] = M("250,000")
    return sh, a, b


# ---- the model ---------------------------------------------------------------

def test_accepted_adds_rejected_and_pending_do_not():
    sh, a, b = _sheet()
    assert ss.low_bidder(sh) == b["id"]
    ss.add_clarification(sh, b, "Excludes fire caulking", "Exclusion",
                         M("4,500.01"), "accepted")
    ss.add_clarification(sh, b, "Price good 30 days", "Qualification")
    ss.add_clarification(sh, b, "Excludes cleanup", "Exclusion", M("900"),
                         "rejected")
    ss.add_clarification(sh, b, "Excludes bond", "Exclusion", M("2,000"))
    lv = ss.leveled(sh)
    assert lv[b["id"]]["adjusted"] == 450001
    assert lv[b["id"]]["total"] == 23650000 + 450001       # exact cents
    assert lv[a["id"]]["total"] == 24000000
    # the accepted add makes the other bidder low once leveled ...
    assert ss.low_bidder(sh) == a["id"]
    # ... but "as bid" is still as bid
    assert ss.low_bidder(sh, "none", adjust=False) == b["id"]
    s = ss.summary(sh)
    assert s["low_bidder"] == "Sample Interiors Inc"
    assert s["low_bid"] == 23650000
    assert s["leveled_low_bidder"] == "Example Drywall LLC"
    # the rejected row is kept as the award record
    kinds = [(c["text"], c["status"]) for c in ss.clarifications(sh, b)]
    assert ("Excludes cleanup", "rejected") in kinds
    assert ss.clarification_counts(sh, b) == {"pending": 2, "accepted": 1,
                                              "rejected": 1}


def test_credit_deducts_and_status_changes_count():
    sh, a, _b = _sheet()
    c = ss.add_clarification(sh, a, "Credit: owner-furnished doors",
                             "Clarification", M("(3,500.50)"), "pending")
    assert ss.leveled(sh)[a["id"]]["total"] == 24000000
    assert not ss.has_adjustments(sh)
    ss.set_clarification(sh, a, c["id"], status="Accept")
    assert ss.has_adjustments(sh)
    assert ss.leveled(sh)[a["id"]]["total"] == 24000000 - 350050
    ss.set_clarification(sh, a, c["id"], status="Reject")
    assert ss.leveled(sh)[a["id"]]["total"] == 24000000
    ss.set_clarification(sh, a, c["id"], status="accepted", clear_amount=True)
    assert ss.leveled(sh)[a["id"]]["total"] == 24000000     # no $: nothing
    assert ss.remove_clarification(sh, a, c["id"])
    assert ss.clarifications(sh, a) == []


def test_adjustments_stack_with_plugs():
    sh, a, b = _sheet()
    ln = ss.add_line(sh, "Metal studs")
    ln["lump"] = M("10,000")
    ln2 = ss.add_line(sh, "Board")
    ln2["lump"] = M("5,000")
    ss.set_bid(sh, ln["id"], a["id"], amount=M("9,000"))
    ss.set_bid(sh, ln2["id"], a["id"], flag="N")
    ss.add_clarification(sh, a, "Adds deflection track", "Clarification",
                         M("250"), "accepted")
    d = ss.leveled(sh, "budget")[a["id"]]
    assert (d["base"], d["plugged"], d["adjusted"]) == (900000, 500000,
                                                         25000)
    assert d["total"] == 1425000


def test_parse_kind_and_status():
    assert ss.parse_kind("excl") == "Exclusion"
    assert ss.parse_kind("Q") == "Qualification"
    assert ss.parse_kind("") == "Clarification"
    assert ss.parse_status("A") == "accepted"
    assert ss.parse_status("reject") == "rejected"
    assert ss.parse_status("?") == "pending"


def test_schema_2_and_migration_from_1():
    sh, a, b = _sheet()
    ss.add_clarification(sh, b, "Excludes permits", "Exclusion", M("1,200"),
                         "accepted")
    d = ss.to_dict(sh)
    assert d["schema"] == ss.SCHEMA_VERSION == 2
    back = ss.from_dict(d)
    c = back["bidders"][1]["clar"][0]
    assert (c["kind"], c["text"], c["amount"], c["status"]) == \
        ("Exclusion", "Excludes permits", 120000, "accepted")
    assert ss.content(back) == ss.content(sh)
    # a version 1 record (no "clar" anywhere) opens with empty lists
    old = ss.to_dict(sh)
    old["schema"] = 1
    for x in old["bidders"]:
        x.pop("clar")
    m = ss.from_dict(old)
    assert all(x["clar"] == [] for x in m["bidders"])
    assert ss.to_dict(m)["schema"] == 2
    assert ss.leveled(m)[b["id"]]["total"] == 23650000
    # junk rows are dropped, bad values cleaned
    old["bidders"][0]["clar"] = [{"text": "Bad amount", "amount": "abc",
                                  "status": "maybe", "kind": "x"},
                                 "not a row", {"text": "", "amount": None}]
    m = ss.from_dict(dict(old, schema=2))
    assert [(c["text"], c["amount"], c["status"], c["kind"])
            for c in m["bidders"][0]["clar"]] == \
        [("Bad amount", None, "pending", "Exclusion")]
    with pytest.raises(ss.ScopeError):
        ss.from_dict(dict(d, schema=ss.SCHEMA_VERSION + 1))


def test_duplicate_for_another_trade_clears_them():
    sh, a, _b = _sheet()
    ss.add_clarification(sh, a, "Excludes permits")
    dup = ss.duplicate(sh, "Painting")
    assert all(x["clar"] == [] for x in dup["bidders"])
    assert ss.clarifications(sh, a)                    # original kept


def test_rows_from_proposal():
    p = {"exclusions": ["Permits and fees", "permits  and fees", "Bonds"],
         "qualifications": ["Price valid 30 days"]}
    rows = ss.rows_from_proposal(p, have=["bonds"])
    assert [(r["kind"], r["text"], r["status"], r["amount"]) for r in rows] \
        == [("Exclusion", "Permits and fees", "pending", None),
            ("Qualification", "Price valid 30 days", "pending", None)]


# ---- exports -------------------------------------------------------------------

def test_excel_has_clarifications_and_reads_back(tmp_path):
    pytest.importorskip("openpyxl")
    from openpyxl import load_workbook
    sh, a, b = _sheet()
    for i in range(6):                                   # 8 bidders: 2 tabs
        ss.add_bidder(sh, f"Test Bidder {i + 3}")
    ss.add_clarification(sh, a, "Excludes permits", "Exclusion", M("1,200"),
                         "accepted")
    ss.add_clarification(sh, a, "Credit: doors by owner", "Clarification",
                         M("(500.25)"), "rejected")
    ss.add_clarification(sh, sh["bidders"][7], "Price valid 30 days",
                         "Qualification")
    path = ss.export_xlsx([sh], str(tmp_path / "scope.xlsx"),
                          company="Example Builders")
    wb = load_workbook(path)
    ws = wb[ss.tab_names([sh])[0][0]]
    vals = [str(c.value) for row in ws.iter_rows() for c in row
            if c.value is not None]
    assert any(v.startswith(ss.CLAR_HEAD) for v in vals)
    assert "Excludes permits" in vals and "REJECTED" in vals
    got, _skipped = ss.import_xlsx(path)
    assert len(got) == 1
    assert ss.content(got[0]) == ss.content(sh)
    assert ss.leveled(got[0])[got[0]["bidders"][0]["id"]]["adjusted"] == \
        120000


def test_pdf_has_a_clarifications_page(tmp_path):
    fitz = pytest.importorskip("fitz")
    sh, a, b = _sheet()
    ss.add_clarification(sh, b, "Excludes fire caulking", "Exclusion",
                         M("4,500"), "accepted")
    path = ss.export_pdf([sh], str(tmp_path / "scope.pdf"),
                         company="Example Builders")
    with fitz.open(path) as d:
        text = "\n".join(p.get_text() for p in d)
        assert d.page_count == 2
    assert "CLARIFICATIONS" in text and "Excludes fire caulking" in text
    assert "ACCEPTED" in text and "$241,000.00" in text     # leveled
    assert "LEVELED TOTAL" in text


# ---- the window ----------------------------------------------------------------

@pytest.fixture
def editor(qtbot, tmp_path, monkeypatch):
    pytest.importorskip("pytestqt")
    from PySide6.QtWidgets import QMessageBox
    from app.pm import scope_sheet_ui as ui
    from app.pm.store import ProjectStore
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache",
                        {"company": {"name": "Example Builders"}})
    for n in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, n, staticmethod(lambda *a, **k: 0))
    st = ProjectStore(str(tmp_path / "Job"))
    dlg = ui.ScopeSheetsDialog(st)
    qtbot.addWidget(dlg)
    dlg.show()
    p = dlg.panel
    sh = p.new_sheet("09 29 00", "Drywall & framing")
    ed = p.editor
    h, _i = ui._bidder_col(0)
    h2, _i2 = ui._bidder_col(1)
    ed.commit_text(ui.R_COMPANY, h, "Example Drywall LLC")
    ed.commit_text(ui.R_PRICE, h, "240,000")
    ed.commit_text(ui.R_COMPANY, h2, "Sample Interiors Inc")
    ed.commit_text(ui.R_PRICE, h2, "236,500")
    ed.commit_text(ui.R_PRICE, ui.C_QTY, "250,000")
    # keep the dialog alive for the whole test (the editor and the
    # clarifications box are its children)
    yield ed, sh, st
    dlg.close()


def _text(grid, r, c):
    it = grid.item(r, c)
    return it.text() if it is not None else ""


def test_grid_add_accept_and_leveled_total(editor):
    from app.pm import scope_sheet_ui as ui
    ed, sh, st = editor
    box = ed.clar
    b = sh["bidders"][1]
    # clicking in a bidder's column shows that bidder's list
    _h2, i2 = ui._bidder_col(1)
    ed.grid.setCurrentCell(ui.R_PRICE, i2)
    assert box.current_bidder() is b
    assert ed.row_level() is None                      # nothing accepted
    c = box.add_row("Excludes fire caulking", "Exclusion")
    assert box.table.rowCount() == 1
    # type the $ in the Adjustment cell, then Accept
    box.table.item(0, box.C_AMT).setText("4,500")
    assert c["amount"] == 450000
    assert box.table.item(0, box.C_AMT).text() == "$4,500.00"
    assert ed.row_level() is None                      # still pending
    box.table.cellWidget(0, box.C_STATUS).setCurrentIndex(
        ss.CLAR_STATUS.index("accepted"))
    assert c["status"] == "accepted"
    assert ed.row_level() is not None
    assert _text(ed.grid, ed.row_level(), i2) == "$241,000.00"
    assert "Leveled total" in box.budget.text()
    assert "$241,000.00" in box.budget.text()
    assert "$250,000.00" in box.budget.text()          # the budget column
    # saved with the sheet
    stored = ss.list_sheets(st)[0]
    assert stored["bidders"][1]["clar"][0]["status"] == "accepted"
    # Reject: kept, not counted
    box.table.cellWidget(0, box.C_STATUS).setCurrentIndex(
        ss.CLAR_STATUS.index("rejected"))
    assert ed.row_level() is None
    assert box.table.rowCount() == 1
    assert box.remove_rows([0]) == 1 and box.table.rowCount() == 0


def test_bad_amount_is_refused(editor):
    ed, sh, _st = editor
    box = ed.clar
    box.select_bidder(sh["bidders"][0])
    c = box.add_row("Credit for doors", "Clarification", M("(100)"),
                    "accepted")
    box.table.item(0, box.C_AMT).setText("lots")
    assert c["amount"] == -10000
    assert "Can't read" in ed.msg.text()


def test_import_from_proposal(editor, tmp_path, monkeypatch):
    from app import proposal_level
    ed, sh, _st = editor
    box = ed.clar
    box.select_bidder(sh["bidders"][0])
    monkeypatch.setattr(proposal_level, "parse", lambda path: {
        "bidder": "Example Drywall LLC", "exclusions": ["Permits", "Bonds"],
        "inclusions": [], "lines": []})
    pdf = str(tmp_path / "quote.pdf")
    assert box.import_from_proposal(pdf) == 2
    assert box.import_from_proposal(pdf) == 0           # no duplicates
    rows = ss.clarifications(sh, sh["bidders"][0])
    assert [(r["kind"], r["text"], r["status"]) for r in rows] == \
        [("Exclusion", "Permits", "pending"), ("Exclusion", "Bonds",
                                               "pending")]
    assert box.table.rowCount() == 2
