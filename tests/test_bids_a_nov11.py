"""Nov 11, bidding phase A: the Exclusions table (who excludes what) and
the qualification badges with the award warning. Made-up companies and
numbers only."""
import datetime as dt
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import exclusions as ex, qualify, settings, subdir      # noqa: E402
from app.pm import scope_sheet as ss                             # noqa: E402

BIDS = [
    {"bidder": "Example Mechanical", "exclusions": [
        "Permits", "Bonds", "Winter protection"], "inclusions": [
        "Dewatering"]},
    {"bidder": "Sample Piping", "exclusions": ["Permit fees", "Dewatering"],
     "inclusions": ["bonds"]},
    {"bidder": "Demo Plumbing", "exclusions": [
        "All permits by others", "Soils testing", "Testing"],
     "inclusions": []}]
TODAY = dt.date(2026, 11, 11)


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Pat Morgan"})


def _row(rows, label):
    return next(r for r in rows if r["label"] == label)


# ---- the table ---------------------------------------------------------------

def test_similar_wordings_share_a_row_and_keep_their_words():
    rows = ex.matrix(BIDS)
    p = _row(rows, "Permits")
    assert p["wordings"] == ["Permits", "Permit fees",
                             "All permits by others"]
    assert all(c["state"] == ex.EXCLUDED for c in p["cells"].values())
    assert p["cells"]["Demo Plumbing"]["texts"] == ["All permits by others"]
    assert p["only"] == ""
    assert rows[0] is p                         # most excluded first
    # nothing is lost or rewritten
    seen = {t for r in rows for c in r["cells"].values()
            if c["state"] == ex.EXCLUDED for t in c["texts"]}
    assert seen == {t for b in BIDS for t in b["exclusions"]}


def test_only_one_bidder_and_included_and_not_stated():
    rows = ex.matrix(BIDS)
    b = _row(rows, "Bonds")
    assert b["only"] == "Example Mechanical"
    assert b["cells"]["Sample Piping"] == {"state": ex.INCLUDED,
                                           "texts": ["bonds"]}
    assert b["cells"]["Demo Plumbing"]["state"] == ex.NOT_STATED
    d = _row(rows, "Dewatering")
    assert d["only"] == "Sample Piping"
    assert d["cells"]["Example Mechanical"]["state"] == ex.INCLUDED
    # one bidder alone is never "only this bidder"
    assert all(r["only"] == "" for r in ex.matrix(BIDS[:1]))


def test_split_merge_and_back():
    rows = ex.matrix(BIDS)
    assert _row(rows, "Testing")["wordings"] == ["Soils testing", "Testing"]
    moves = ex.split({}, "Soils testing")
    rows = ex.matrix(BIDS, moves)
    assert _row(rows, "Soils testing")["wordings"] == ["Soils testing"]
    assert _row(rows, "Testing")["wordings"] == ["Testing"]
    moves = ex.merge(moves, _row(rows, "Bonds"),
                     _row(rows, "Winter protection"))
    rows = ex.matrix(BIDS, moves)
    assert _row(rows, "Winter protection")["wordings"] == [
        "Bonds", "Winter protection"]
    assert not any(r["label"] == "Bonds" for r in rows)
    moves = ex.unmove(moves, "Soils testing")
    assert _row(ex.matrix(BIDS, moves), "Testing")["wordings"] == [
        "Soils testing", "Testing"]


def test_report_table():
    t = ex.table(BIDS)
    assert t[0] == ["Exclusion", "Example Mechanical", "Sample Piping",
                    "Demo Plumbing", "Only one bidder excludes it"]
    bonds = next(r for r in t if r[0] == "Bonds")
    assert bonds[1:] == ["Excluded: Bonds", "Included: bonds", "Not stated",
                         "Example Mechanical"]


def test_from_proposals_and_the_leveling_export(tmp_path):
    from app import leveling
    props = [{"bidder": b["bidder"], "exclusions": b["exclusions"],
              "inclusions": b["inclusions"],
              "lines": [{"desc": "8 in PVC", "unit": "LF", "qty": 100.0,
                         "price": 40.0 + i, "amount": 100 * (40.0 + i)}]}
             for i, b in enumerate(BIDS)]
    bids = ex.from_proposals(props)
    assert bids == BIDS
    from app import proposal_level
    res = leveling.run(proposal_level.to_bids(props), 25, 25, 2.0, 2)
    p = leveling.export_xlsx(res, str(tmp_path / "l.xlsx"),
                             [("Exclusions", ex.table(bids))])
    import openpyxl
    wb = openpyxl.load_workbook(p)
    assert "Exclusions" in wb.sheetnames
    vals = [c.value for row in wb["Exclusions"].iter_rows() for c in row]
    assert "Excluded: All permits by others" in vals


# ---- qualification -----------------------------------------------------------

def _contact(**kw):
    c = {"company": "Example Mechanical", "license": "M-10442",
         "insurance_exp": "2027-06-30", "bond_limit": "500,000",
         "prequal": "Approved", "prequal_limit": "750000"}
    c.update(kw)
    return c


def _by(bs):
    return {b["key"]: b for b in bs}


def test_badges_all_good():
    bs = qualify.badges(_contact(), 400000, TODAY)
    assert [b["state"] for b in bs] == [qualify.OK] * 4
    assert qualify.short(bs) == "Qualified"
    assert qualify.award_warnings(_contact(), 400000, TODAY) == []


def test_badges_expired_expiring_and_over_the_bond():
    c = _contact(insurance_exp="2026-11-01", license_exp="2026-11-30")
    b = _by(qualify.badges(c, 600000, TODAY))
    assert b["insurance"]["state"] == qualify.BAD
    assert b["license"]["state"] == qualify.WARN        # within 30 days
    assert b["bond"]["state"] == qualify.BAD
    assert "single job" in b["bond"]["text"]
    w = qualify.award_warnings(c, 600000, TODAY)
    assert len(w) == 2 and "Insurance expired 2026-11-01" in w[0]
    # an expired license stops the award too; an expiring one doesn't
    c["license_exp"] = "2026-10-01"
    assert any("License expired" in x
               for x in qualify.award_warnings(c, 100, TODAY))
    # over the prequalified limit
    assert any("prequalified limit" in x for x in qualify.award_warnings(
        _contact(bond_limit=""), 800000, TODAY))


def test_no_bid_amount_is_not_over_anything_and_unknown_bidder_is_grey():
    assert _by(qualify.badges(_contact(), None, TODAY))["bond"][
        "state"] == qualify.OK
    bs = qualify.badges(None, 1000, TODAY)
    assert len(bs) == 1 and bs[0]["state"] == qualify.NONE
    assert qualify.award_warnings(None, 1000, TODAY) == []


def test_override_needs_a_reason():
    with pytest.raises(ValueError):
        qualify.override("Example Mechanical", ["x"], "  ")
    o = qualify.override("Example Mechanical", ["Insurance expired"],
                         "New certificate promised by Friday", "Pat Morgan",
                         dt.datetime(2026, 11, 11, 9, 30))
    assert o["reason"].startswith("New certificate") and \
        o["by"] == "Pat Morgan" and o["at"] == "2026-11-11T09:30:00"


def test_directory_keeps_a_license_expiry(cfg):
    subdir.upsert({"company": "Example Mechanical", "license": "M-10442",
                   "license_exp": "2026-10-01",
                   "insurance_exp": "2027-01-01"})
    c = qualify.find("example mechanical")
    assert c["license_exp"] == "2026-10-01"
    al = subdir.alerts(today=TODAY)
    assert [(what, d, ex_) for _c, what, d, ex_ in al] == [
        ("License", "2026-10-01", True)]
    assert "license_exp" in subdir._COLS


# ---- Scope Sheets ------------------------------------------------------------

def _sheet():
    sh = ss.new_sheet("22 00 00", "Plumbing", bidders=2)
    a, b = sh["bidders"]
    a["company"], b["company"] = "Example Mechanical", "Sample Piping"
    a["price"], b["price"] = ss.parse_money("240,000"), \
        ss.parse_money("236,500")
    ss.add_clarification(sh, a, "Permits", "Exclusion")
    ss.add_clarification(sh, b, "Permit fees", "Exclusion")
    ss.add_clarification(sh, b, "Winter protection", "Exclusion")
    ss.add_clarification(sh, b, "Price good 30 days", "Qualification")
    return sh, a, b


def test_scope_sheet_exclusions_and_what_is_kept():
    sh, a, b = _sheet()
    bids = ss.exclusion_bids(sh)
    assert [x["exclusions"] for x in bids] == [
        ["Permits"], ["Permit fees", "Winter protection"]]
    rows = ex.matrix(bids)
    assert _row(rows, "Winter protection")["only"] == "Sample Piping"
    sh["ex_moves"] = ex.split({}, "Permit fees")
    sh["award"]["bidder"] = b["id"]
    sh["award"]["override"] = qualify.override(
        "Sample Piping", ["Insurance expired 2026-11-01"], "COI on the way")
    back = ss.from_dict(ss.to_dict(sh))
    assert back["ex_moves"] == {"permit fees": "Permit fees"}
    assert back["award"]["override"]["reason"] == "COI on the way"
    # neither is in the workbook, so neither is compared with an import
    c = ss.content(sh)
    assert "ex_moves" not in c and "override" not in c["award"]
    # an old sheet opens as before
    plain = ss.from_dict(ss.to_dict(ss.new_sheet("09", "Paint")))
    assert "ex_moves" not in plain and "override" not in plain["award"]


@pytest.fixture
def editor(cfg, tmp_path):
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app.pm import scope_sheet_ui as ui
    subdir.upsert({"company": "Sample Piping", "license": "P-2201",
                   "insurance_exp": "2020-01-01", "bond_limit": "100000"})
    subdir.upsert({"company": "Example Mechanical", "license": "M-10442",
                   "insurance_exp": "2099-01-01", "bond_limit": "900000"})
    ed = ui.ScopeSheetEditor(None)
    sh, a, b = _sheet()
    ed.set_sheet(sh)
    return ed, sh, a, b


def test_scope_sheet_badges_and_award_warning(editor):
    ed, sh, a, b = editor
    html = ed.qualification_html()
    assert "Insurance expired" in html and "Over bond limit" in html
    assert "Example Mechanical: " in html and "Qualified" in html
    assert ed.award_warnings(a) == []
    assert len(ed.award_warnings(b)) == 2
    assert ed.confirm_award(a) and "override" not in sh["award"]
    assert not ed.confirm_award(b, reason="")
    assert ed.confirm_award(b, reason="Certificate due Friday")
    ov = sh["award"]["override"]
    assert ov["by"] == "Pat Morgan" and len(ov["warnings"]) == 2
    assert ed.confirm_award(a) and "override" not in sh["award"]


def test_scope_sheet_exclusions_window_and_one_click_adjustment(editor):
    ed, sh, a, b = editor
    dlg = ed.clar.compare_exclusions(show=False)
    p = dlg.panel
    assert p.table.columnCount() == 3 and p.table.rowCount() == 2
    texts = [p.table.item(r, c).text() for r in range(2) for c in range(3)]
    assert "ONLY ONE - Excluded: Winter protection" in texts
    assert "Excluded: Permit fees" in texts
    p.split("Permit fees")
    assert sh["ex_moves"] == {"permit fees": "Permit fees"}
    assert p.table.rowCount() == 3
    c = ed.clar.price_exclusion("Sample Piping", "Winter protection",
                                ss.parse_money("3,250.00"))
    assert c["amount"] == 325000 and c["status"] == "pending"
    assert ss.leveled(sh)[b["id"]]["adjusted"] == 0   # not until accepted
    ss.set_clarification(sh, b, c["id"], status="accepted")
    assert ss.leveled(sh)[b["id"]]["adjusted"] == 325000
    assert p.export(str(os.path.join(settings.DIR, "ex.xlsx")))


# ---- Leveling Board / bid-day sheets ----------------------------------------

def test_board_keeps_the_quotes_exclusions_and_the_choices(monkeypatch):
    import fitz
    from app import estimate
    from app.estimating import bidday, levelboard as LB
    monkeypatch.setattr(estimate, "lines", lambda d, page=None: [
        {"name": "Gypsum board walls", "unit": "sf", "type": "area",
         "quantity": 1000, "code": "09 21 16", "unit_cost": 2.5},
        {"name": "Acoustic ceiling", "unit": "sf", "type": "area",
         "quantity": 400, "code": "09 51 13", "unit_cost": 4.0}])
    doc = fitz.open()
    doc.new_page()
    pkg = LB.start_board(doc, LB.scope_sheet(doc, "09"))
    LB.import_quote(doc, pkg, parsed={
        "bidder": "Example Drywall", "lines": [
            {"desc": "Gypsum board walls", "amount": 2400.0}],
        "exclusions": ["Permits", "Scaffolding"], "inclusions": ["Cleanup"]})
    LB.import_quote(doc, pkg, parsed={
        "bidder": "Sample Interiors", "lines": [
            {"desc": "Gypsum board walls", "amount": 2200.0}],
        "exclusions": ["Permit fees"]})
    bids = bidday.exclusion_bids(doc, pkg)
    assert bids[0]["exclusions"] == ["Permits", "Scaffolding"]
    assert "Cleanup" in bids[0]["inclusions"] and \
        "Gypsum board walls" in bids[0]["inclusions"]
    rows = ex.matrix(bids)
    assert _row(rows, "Scaffolding")["only"] == "Example Drywall"
    bidday.set_extra(doc, pkg, "ex_moves", ex.split({}, "Permit fees"))
    LB.set_status(doc, pkg, "Example Drywall", "2", LB.RED)   # rebuilds it
    sheet = bidday.load(doc, pkg)
    assert sheet["ex_moves"] == {"permit fees": "Permit fees"}
    assert sheet["bidders"][0]["exclusions"] == ["Permits", "Scaffolding"]
    bidday.set_extra(doc, pkg, "ex_moves", None)
    assert "ex_moves" not in bidday.load(doc, pkg)
    with pytest.raises(bidday.BidDayError):
        bidday.set_extra(doc, pkg, "scope", [])


def test_board_window_warns_before_using_an_unqualified_low(cfg,
                                                            monkeypatch):
    pytest.importorskip("PySide6.QtWidgets")
    import fitz
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app import estimate
    from app.estimating import bidday, levelboard as LB, levelboard_ui
    monkeypatch.setattr(estimate, "lines", lambda d, page=None: [
        {"name": "Gypsum board walls", "unit": "sf", "type": "area",
         "quantity": 1000, "code": "09 21 16", "unit_cost": 2.5}])
    subdir.upsert({"company": "Example Drywall",
                   "insurance_exp": "2020-01-01"})
    doc = fitz.open()
    doc.new_page()
    w = levelboard_ui.LevelBoard(doc)
    w.new_from_trade("09", ask=False)
    LB.import_quote(doc, w.package(), parsed={
        "bidder": "Example Drywall", "lines": [
            {"desc": "Gypsum board walls", "amount": 2400.0}],
        "exclusions": ["Permits"]})
    w.refresh()
    assert "Insurance expired" in w.summary.text()
    assert w.use_low(reason="") is None                 # no reason: no go
    assert not bidday.load(doc, w.package()).get("applied")
    got = w.use_low(reason="Renewal certificate requested")
    assert got["bidder"] == "Example Drywall"
    ov = bidday.load(doc, w.package())["award_override"]
    assert ov["reason"] == "Renewal certificate requested"
    dlg = w.exclusions(show=False)
    assert dlg.panel.table.rowCount() == 1


def test_leveling_window_has_the_exclusions_tab(cfg):
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app import leveling_ui, proposal_level
    w = leveling_ui.LevelingDialog()
    w.proposals = [
        {"bidder": b["bidder"], "exclusions": b["exclusions"],
         "inclusions": b["inclusions"],
         "lines": [{"desc": "8 in PVC", "unit": "LF", "qty": 100.0,
                    "price": 40.0 + i, "amount": 100 * (40.0 + i)}]}
        for i, b in enumerate(BIDS)]
    w.bids = proposal_level.to_bids(w.proposals)
    w.project.addItem("Proposals", "files")
    w.project.setCurrentIndex(w.project.count() - 1)
    assert w.run()
    t = w.exclusions.table
    assert t.rowCount() == 5 and t.columnCount() == 4
    assert "Not in directory" in w.qual.text()
