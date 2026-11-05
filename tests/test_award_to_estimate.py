"""Scope Sheets > Use Award in Estimate (app/award_estimate.py): one
Subcontract line per awarded trade in the drawing's estimate, the trade's
allowance line marked replaced (kept, quantity 0, with a note), exact to
the cent, idempotent, and on to the proposal rollup like any added line.
Made-up companies and numbers only."""
import os
from decimal import Decimal

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import assemblies, award_estimate as AE                 # noqa: E402
from app import estimate_lines as EL, settings                   # noqa: E402
from app.pm import scope_sheet as ss                             # noqa: E402
from estimate_helpers import blank_doc                           # noqa: E402
from test_gui import ANSWERS, win, qapp                          # noqa: E402,F401

TODAY = "2026-10-22"


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


def _sheet(code="09 29 00", trade="Drywall & framing", rid="rec-drywall"):
    sh = ss.new_sheet(code, trade, bidders=2)
    a, b = sh["bidders"]
    a["company"], b["company"] = "Example Drywall LLC", "Sample Interiors Inc"
    a["price"] = ss.parse_money("123,456.78")
    b["price"] = ss.parse_money("130,000")
    sh["award"]["bidder"] = a["id"]
    sh["_id"] = rid
    return sh


def _allowance(code, amount, desc="Allowance - test"):
    return EL.new_line(desc, 1, "ls", code=code, cost_type="Allowance",
                       sub=amount)


def _award_lines(lines):
    return [x for x in lines if x["source"].startswith(AE.MARK)]


# ---- plan (pure) -------------------------------------------------------------

def test_adds_one_sub_line_exact_cents():
    lines, rep = AE.plan([], [_sheet()], TODAY)
    assert len(lines) == 1 and rep[0]["action"] == "added"
    ln = lines[0]
    assert ln["code"] == "09 29 00" and ln["cost_type"] == "Subcontract"
    assert "Drywall & framing" in ln["desc"] and \
        "Example Drywall LLC" in ln["desc"]
    p = EL.price(ln)
    assert p["total"] == Decimal("123456.78")
    assert p["ext"]["sub"] == Decimal("123456.78")
    assert TODAY in ln["note"]


def test_rerun_updates_never_duplicates():
    sh = _sheet()
    lines, _r = AE.plan([], [sh], TODAY)
    lines, rep = AE.plan(lines, [sh], "2026-10-23")
    assert rep[0]["action"] == "unchanged" and len(lines) == 1
    assert TODAY in lines[0]["note"]                  # untouched
    # award moves to the other bidder at a typed amount
    sh["award"]["bidder"] = sh["bidders"][1]["id"]
    sh["award"]["amount"] = ss.parse_money("129,999.99")
    lines, rep = AE.plan(lines, [sh], "2026-10-24")
    assert rep[0]["action"] == "updated" and len(lines) == 1
    assert "Sample Interiors Inc" in lines[0]["desc"]
    assert EL.price(lines[0])["total"] == Decimal("129999.99")
    assert lines[0]["id"] == rep[0]["line_id"]


def test_replaces_the_trades_allowance_and_keeps_it():
    keep = EL.new_line("Test permit", 1, "ls", sub="1250")
    exact = _allowance("09 29 00", "150000", "Allowance - drywall")
    div = _allowance("09 00 00", "400000", "Allowance - Division 09")
    lines, rep = AE.plan([keep, exact, div], [_sheet()], TODAY)
    assert rep[0]["replaced"] == [exact["id"]]       # the section wins
    by = {x["id"]: x for x in lines}
    gone = by[exact["id"]]
    assert gone["note"].startswith(AE.REPLACED + " Example Drywall LLC on "
                                   + TODAY)
    assert "$150,000.00" in gone["note"]
    assert Decimal(gone["qty"]) == 0 and Decimal(gone["sub"]) == 150000
    assert EL.price(gone)["total"] == 0
    assert Decimal(by[div["id"]]["qty"]) == 1         # untouched
    assert EL.price(by[keep["id"]])["total"] == Decimal("1250.00")
    assert len(lines) == 4                             # nothing deleted
    # again: the replaced allowance is not replaced twice
    lines2, rep2 = AE.plan(lines, [_sheet()], "2026-10-30")
    assert rep2[0]["replaced"] == [] and rep2[0]["action"] == "unchanged"
    assert {x["id"]: x["note"] for x in lines2}[exact["id"]] == gone["note"]


def test_division_allowance_when_no_section_one():
    div = _allowance("09 00 00", "400000")
    lines, rep = AE.plan([div], [_sheet()], TODAY)
    assert rep[0]["replaced"] == [div["id"]]
    # a second trade in the same division doesn't find it again
    paint = _sheet("09 91 23", "Painting", "rec-paint")
    lines, rep = AE.plan(lines, [paint], TODAY)
    assert rep[0]["replaced"] == [] and rep[0]["action"] == "added"
    assert len(_award_lines(lines)) == 2


def test_sheets_without_award_are_skipped():
    sh = _sheet()
    sh["award"]["bidder"] = ""
    lines, rep = AE.plan([], [sh], TODAY)
    assert lines == [] and rep == []


def test_unsaved_sheet_keyed_by_code_and_trade():
    sh = _sheet(rid="")
    sh.pop("_id")
    assert AE.sheet_key(sh) == "09 29 00 Drywall & framing"
    lines, _r = AE.plan([], [sh], TODAY)
    lines, rep = AE.plan(lines, [sh], TODAY)
    assert len(lines) == 1 and rep[0]["action"] == "unchanged"


# ---- in the drawing ----------------------------------------------------------

def test_apply_saves_in_pdf_and_flows_to_the_rollup(tmp_path):
    import fitz
    d = blank_doc()
    EL.add(d, [_allowance("09 29 00", "150000", "Allowance - drywall")])
    rep = AE.apply(d, [_sheet()], TODAY)
    assert rep[0]["action"] == "added"
    path = str(tmp_path / "job.pdf")
    d.save(path)
    d.close()
    d = fitz.open(path)
    assert len(_award_lines(EL.read(d))) == 1
    rows, totals, _e = assemblies.rollup(d)
    names = [r["name"] for r in rows]
    assert any("Example Drywall LLC" in n for n in names)
    assert not any(n.startswith("Allowance - drywall") for n in names)
    assert Decimal(str(round(totals["total"], 2))) == Decimal("123456.78")
    assert AE.apply(d, [_sheet()], TODAY)[0]["action"] == "unchanged"
    assert len(EL.read(d)) == 2


def test_panel_button_uses_the_open_drawing(win, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from app.pm import scope_sheet_ui as ui
    from app.pm.store import ProjectStore
    said = []
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: said.append(a[2]) or 0))
    st = ProjectStore(str(tmp_path / "Job"))
    st.data["name"] = "Harbor Example"
    dlg = ui.ScopeSheetsDialog(st, win)
    p = dlg.panel
    sh = p.new_sheet("09 29 00", "Drywall & framing")
    a = sh["bidders"][0]
    a["company"] = "Example Drywall LLC"
    a["price"] = ss.parse_money("98,765.43")
    sh["award"]["bidder"] = a["id"]
    p._edited(sh)
    rep = p.use_award_in_estimate(confirm=False, today=TODAY)
    assert rep and rep[0]["action"] == "added"
    lines = _award_lines(EL.read(win._view.doc))
    assert len(lines) == 1
    assert EL.price(lines[0])["total"] == Decimal("98765.43")
    win.estimate.refresh()
    assert any(k == "added" and g["id"] == lines[0]["id"]
               for k, g in win.estimate.kinds)
    assert win._view.dirty
    assert "Drywall" in said[-1]
    # again: updated in place, never a second line
    p.use_award_in_estimate(confirm=False, today=TODAY)
    assert len(_award_lines(EL.read(win._view.doc))) == 1
    dlg.close()


def test_panel_without_drawing_or_award_says_so(qtbot, tmp_path,
                                                monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from app.pm import scope_sheet_ui as ui
    from app.pm.store import ProjectStore
    said = []
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: said.append(a[2]) or 0))
    monkeypatch.setattr(ui, "_main_window", lambda w: None)
    st = ProjectStore(str(tmp_path / "Job"))
    p = ui.ScopeSheetsPanel(st)
    qtbot.addWidget(p)
    assert p.use_award_in_estimate(confirm=False) is None
    assert "Open the drawing" in said[-1]
    assert p.use_award_in_estimate(doc=blank_doc(), confirm=False) is None
    assert "No trade has a recommended award" in said[-1]

