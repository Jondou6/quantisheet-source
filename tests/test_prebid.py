"""Pre-bid checklist (upgrade spec Phase 0): sheets reviewed, every markup
priced / excluded with a reason / RFI, every revision cloud accounted for,
a one-page printout and the bid lock."""
import json
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import annotate, assemblies, prebid, settings          # noqa: E402
from app.dmoney import D, cents, fmt                             # noqa: E402


@pytest.fixture(autouse=True)
def _cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Pat Morgan"})


def _doc(pages=3):
    d = fitz.open()
    for i in range(pages):
        p = d.new_page(width=1224, height=792)
        p.insert_text((1100, 760), f"A-10{i + 1}", fontsize=14)
    annotate.apply_op(d, annotate.new_op("set_scale", 0, ppu=18.0,
                                         unit="ft"))
    return d


_PAGES = []                        # annots need their page kept alive


def _annots(doc, pno):
    page = doc[pno]
    _PAGES.append(page)
    return [a for a in annotate.iter_annots(page)
            if not annotate.is_label(doc, a)]


def _review_all(d):
    for p in range(d.page_count):
        prebid.set_reviewed(d, p)


def test_money_helper_is_exact():
    assert D(0.1) + D(0.2) == D("0.3")
    assert cents("1,234.565") == D("1234.57") and fmt(-5) == "-$5.00"
    assert D("(12.50)") == D("-12.50") and D("x") == 0


def test_sheets_must_be_reviewed():
    d = _doc()
    rep = prebid.check(d)
    assert len(rep.unreviewed_sheets) == 3 and not rep.ok
    _review_all(d)
    rep = prebid.check(d)
    assert rep.unreviewed_sheets == [] and rep.ok
    assert rep.sheets[0]["by"] == "Pat Morgan"


def test_markups_need_a_decision():
    d = _doc(1)
    _review_all(d)
    annotate.apply_op(d, annotate.new_op("add_rect", 0,
                                         rect=[100, 100, 200, 160]))
    rep = prebid.check(d)
    assert len(rep.open_markups) == 1 and not rep.ok
    a = _annots(d, 0)[0]
    prebid.set_scope(d, a, "priced")
    assert prebid.check(d).ok
    # excluded needs a reason
    with pytest.raises(prebid.PrebidError):
        prebid.set_scope(d, a, "excluded", "")
    d.xref_set_key(a.xref, prebid.SCOPE_KEY, fitz.get_pdf_str(json.dumps(
        {"status": "excluded", "reason": ""})))
    assert len(prebid.check(d).open_markups) == 1
    prebid.set_scope(d, a, "excluded", "By owner")
    assert prebid.check(d).ok


def test_takeoff_in_the_estimate_is_priced_automatically():
    d = _doc(1)
    _review_all(d)
    annotate.apply_op(d, annotate.new_op(
        "add_polygon", 0, pts=[[300, 300], [480, 300], [480, 480],
                               [300, 480]],
        measure={"type": "area", "value": 100, "unit": "sq ft",
                 "group": "Mystery Floor"}))
    rep = prebid.check(d)
    assert len(rep.open_markups) == 1 and "Mystery Floor" in \
        rep.open_markups[0]["label"]
    assemblies.set_job_assembly(d, {
        "name": "Mystery Floor", "measure": "area", "trade": "Flooring",
        "parts": [{"name": "Tile", "unit": "SF", "qty": "Area",
                   "cost": 4.0}]})
    assert prebid.check(d).ok


def test_revision_clouds_must_be_accounted_for():
    d = _doc(1)
    _review_all(d)
    annotate.apply_op(d, annotate.new_op(
        "add_cloud", 0, rect=[500, 200, 700, 300],
        subject=prebid.CHANGE_SUBJECT, note="Changed in the revision"))
    rep = prebid.check(d)
    assert len(rep.unaccounted_clouds) == 1 and not rep.ok
    # a takeoff over it accounts for it (and is itself priced)
    annotate.apply_op(d, annotate.new_op(
        "add_line", 0, pts=[[520, 250], [680, 250]],
        measure={"type": "length", "value": 8.9, "unit": "ft",
                 "group": "Wall X"}))
    rep = prebid.check(d)
    assert rep.unaccounted_clouds == [] and len(rep.open_markups) == 1
    # without the takeoff, an RFI accounts for it
    page = d[0]
    for a in list(page.annots()):
        if (a.info or {}).get("subject", "") != prebid.CHANGE_SUBJECT:
            page.delete_annot(a)
    assert len(prebid.check(d).unaccounted_clouds) == 1
    cloud = next(a for a in _annots(d, 0)
                 if (a.info or {}).get("subject") == prebid.CHANGE_SUBJECT)
    prebid.set_scope(d, cloud, "rfi", rfi="RFI-012")
    assert prebid.check(d).ok


def test_lock_unlock_print_and_reopen(tmp_path):
    d = _doc(2)
    annotate.apply_op(d, annotate.new_op("add_rect", 1,
                                         rect=[10, 10, 50, 50]))
    with pytest.raises(prebid.PrebidError, match="Not ready"):
        prebid.lock(d, 1000)
    out = prebid.print_pdf(d, str(tmp_path / "check.pdf"))
    pdf = fitz.open(out)
    txt = pdf[0].get_text()
    assert pdf.page_count == 1 and "NOT READY" in txt and \
        "Sheets reviewed: 0 of 2" in txt
    _review_all(d)
    prebid.set_scope(d, _annots(d, 1)[0], "excluded", "NIC")
    lk = prebid.lock(d, 1234567.5)
    assert lk["total"] == "1234567.50" and lk["by"] == "Pat Morgan"
    assert lk["at"] and prebid.lock_state(d)["stale"] is False
    out = prebid.print_pdf(d, str(tmp_path / "check2.pdf"))
    txt = fitz.open(out)[0].get_text()
    assert "PASS" in txt and "$1,234,567.50" in txt
    # saved and reopened, everything is still there
    p = tmp_path / "bid.pdf"
    d.save(str(p))
    d2 = fitz.open(str(p))
    assert prebid.check(d2).ok and prebid.lock_state(d2)["total"] == \
        "1234567.50"
    # a takeoff change makes the lock stale
    annotate.apply_op(d2, annotate.new_op(
        "add_line", 0, pts=[[100, 100], [280, 100]],
        measure={"type": "length", "value": 10, "unit": "ft",
                 "group": "Late Add"}))
    assert prebid.lock_state(d2)["stale"] is True
    with pytest.raises(prebid.PrebidError):
        prebid.unlock(d2, reason="")
    assert prebid.unlock(d2, reason="Addendum 2")
    assert prebid.lock_state(d2) is None
    assert prebid.read(d2)["log"][-1]["reason"] == "Addendum 2"


def test_cli_exit_codes(tmp_path, capsys):
    from app import cli
    d = _doc(1)
    p = tmp_path / "a.pdf"
    d.save(str(p))
    assert cli.main(["prebid", str(p)]) == 3
    assert "NOT READY" in capsys.readouterr().out
    _review_all(d)
    p2 = tmp_path / "b.pdf"
    d.save(str(p2))
    assert cli.main(["prebid", str(p2), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["ok"] is True and data["counts"]["sheets"] == 1


def test_dialog_lock_button(qtbot=None):
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication, QMainWindow
    from app.prebid_ui import PrebidDialog
    app = QApplication.instance() or QApplication([])

    class View:
        def __init__(self, doc):
            self.doc, self.page = doc, 0

        def mark_dirty(self):
            pass

    class Win(QMainWindow):
        def _go_page(self, i):
            self.went = i

        def _go_annot(self, i, ref):
            self.went_annot = ref
    w = Win()
    w._view = View(_doc(2))
    dlg = PrebidDialog(w)
    assert not dlg.lock_btn.isEnabled() and "Not ready" in \
        dlg.verdict.text()
    dlg.mark_page_reviewed()
    w._view.page = 1
    dlg.mark_page_reviewed()
    assert dlg.lock_btn.isEnabled()
    lk = dlg.lock(500)
    assert lk["total"] == "500.00" and dlg.unlock_btn.isEnabled()
    assert dlg.unlock("re-bid")
    app.processEvents()


def test_unpriced_count_reads_no_sheet_numbers(monkeypatch):
    """The unpriced chip and highlights read no sheet numbers at all (17 s
    when opening a 309-sheet set; Nov 3: a 99-sheet set with markups on
    every page froze on open reading the pages that have markups)."""
    d = _doc(5)
    annotate.apply_op(d, annotate.new_op("add_rect", 3,
                                         rect=[100, 100, 200, 160]))
    full = prebid.check(d)
    from app import overlay
    read = []
    orig = overlay.sheet_number
    monkeypatch.setattr(overlay, "sheet_number",
                        lambda pg: read.append(pg.number) or orig(pg))
    quick = prebid.check(d, sheets=False)
    assert read == []
    assert len(quick.open_markups) == len(full.open_markups) == 1
    assert full.open_markups[0]["sheet"] == "A-104"
    assert quick.open_markups[0]["sheet"] == "Page 4"
    assert quick.open_markups[0]["rect"] == full.open_markups[0]["rect"]
