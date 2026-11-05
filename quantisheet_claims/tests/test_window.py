"""The window constructs under QT_QPA_PLATFORM=offscreen and drives the
same engine (settlement text, takeoff, revisions, export)."""
import os

import pytest

from quantisheet_claims import model as m
from quantisheet_claims.interface import load_snapshot
from quantisheet_claims.__main__ import build_window, parse_args
from .helpers import c8_claim, t1_claim

DATA = os.path.join(os.path.dirname(__file__), "data", "sample_snapshot.json")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_window_constructs_offscreen(qapp):
    """0.2: no claim given -> the start page; a claim opens the tabs."""
    from quantisheet_claims.ui.workspace import new_claim
    win = build_window(parse_args([]))
    assert win.claim is None and win.stack.currentIndex() == 0
    win.add_claim(new_claim("residential"))
    assert win.stack.currentIndex() == 1
    assert win.windowTitle() == "ClaimIT – NEW-CLAIM"
    assert win.tabs.count() == 10
    assert [win.tabs.tabText(i).replace("&&", "&") for i in range(10)] == [
        "Claim", "Coverage & deductibles", "Rooms & line items", "Groups (WBS)",
        "O&P", "Settlement summary", "Revisions & supplements",
        "Diary & payments", "Contents", "Export"]
    win.close()


def test_settlement_tab_and_commercial_fields(qapp):
    from quantisheet_claims.ui.workspace import ClaimsWindow
    win = ClaimsWindow()
    win.add_claim(c8_claim())
    assert "Paid now" in win.settlement_view.toPlainText()
    assert "$139,722.22" in win.settlement_view.toPlainText()
    assert win.com_box.isEnabled() and not win.res_box.isEnabled()
    win.add_claim(t1_claim())
    assert "$6,168.00" in win.settlement_view.toPlainText()
    assert win.res_box.isEnabled()


def test_bad_money_is_an_error_not_zero(qapp):
    from quantisheet_claims.ui.workspace import ClaimsWindow
    win = ClaimsWindow()
    win.add_claim(t1_claim())
    win.ded_amount.setText("12,5OO")
    assert win.apply_coverage_tab() is False
    assert "12,5OO" in win.last_error
    assert win.claim.deductible.amount_cents == 100_000
    win.ded_amount.setText("2,500.00")
    assert win.apply_coverage_tab() is True
    assert win.claim.deductible.amount_cents == 250_000
    assert win.claim.audit[-1].action == "edit coverage"


def test_takeoff_revision_and_export(qapp, tmp_path):
    from quantisheet_claims.ui.workspace import new_claim
    win = build_window(parse_args(["--takeoff", DATA]))
    assert win.snapshot is not None and len(win.snapshot.items) == 3
    assert win.start.buttons["takeoff"].isVisibleTo(win.start)
    win.add_claim(new_claim("residential"))
    win.f["claim_number"].setText("R-1")
    assert win.apply_claim_tab()
    assert win.new_revision()
    assert win.add_from_takeoff(list(win.snapshot.items))
    assert len(win.claim.lines) == 3
    assert all(ln.item_code == "REVIEW" for ln in win.claim.lines)
    assert win.new_revision()
    assert len(win.revisions) == 2 and len(win.revisions[1].changes) == 3
    assert win.approve_revision() is False                    # reasons missing
    for r in range(3):
        win.change_table.item(r, 3).setText("from takeoff")
    assert win.save_reasons() and win.approve_revision()
    assert win.revisions[1].status == "approved"
    for kind in ("csv", "xlsx", "pdf"):
        assert win.export_to(kind, str(tmp_path / f"r1.{kind}"))
    p = win.save()
    assert p and p.startswith(os.environ["QUANTISHEET_CLAIMS_HOME"])
    win2 = build_window(parse_args([p]))
    assert win2.claim.claim_number == "R-1" and len(win2.revisions) == 2


def test_frozen_claim_refuses_edits(qapp):
    from quantisheet_claims.ui.workspace import ClaimsWindow
    win = ClaimsWindow()
    win.add_claim(m.edit(t1_claim(), "Jon", "submit", status="submitted"))
    assert win.add_line() is False and "revision" in win.last_error


def test_main_version(capsys):
    from quantisheet_claims.__main__ import main
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == "0.2.2"


def test_frozen_entry_script_uses_absolute_imports():
    """The exe's entry script can't be __main__.py (relative imports fail
    in a frozen top-level script - Jon, Oct 20)."""
    import os
    root = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    spec = open(os.path.join(root, "quantisheet_claims.spec"),
                encoding="utf-8").read()
    assert '"claimit_launch.py"' in spec and '"__main__.py")' not in spec
    src = open(os.path.join(root, "claimit_launch.py"),
               encoding="utf-8").read()
    assert "from quantisheet_claims.__main__ import main" in src
    assert "from ." not in src


def test_selftest_flag_loads_the_window_modules():
    from quantisheet_claims.__main__ import main
    assert main(["--selftest"]) == 0
