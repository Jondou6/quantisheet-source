"""Proposals from the assembly estimate."""
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import assemblies, proposal                       # noqa: E402
from test_gui import win, qapp                              # noqa: E402,F401
from test_planswift import _job, WALL                       # noqa: E402


@pytest.fixture(autouse=True)
def _own_settings(tmp_path, monkeypatch):
    from app import settings
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


def _data(doc, **kw):
    d = proposal.defaults(doc)
    d.update(client="Aiken County", project="Spay & Neuter Clinic",
             tax=7, overhead=10, profit=10, **kw)
    return d


COMP = {"name": "Acme Builders", "address": "1 Main St\nAiken, SC",
        "phone": "803-555-0100", "email": "bids@acme.test", "website": "",
        "license": "G-12345", "logo": "", "signer": "Jon D.",
        "title": "Estimator"}


@pytest.mark.parametrize("detail", ["trade", "assembly", "parts"])
def test_pricing_adds_up(detail):
    d = _job()
    rows, totals, _ = assemblies.rollup(d)
    p = proposal.price(d, _data(d, detail=detail))
    want = (totals["material"] * 1.07 + totals["labor_cost"]) * 1.1 * 1.1
    assert p["total"] == pytest.approx(want, abs=0.01)
    assert round(sum(ln["price"] for ln in p["lines"]), 2) == p["total"]
    if detail == "trade":
        assert len(p["lines"]) == len({r["trade"] for r in rows})
    if detail == "assembly":
        assert len(p["lines"]) == len(rows)


def test_proposal_pdf(tmp_path):
    d = _job()
    logo = tmp_path / "logo.png"
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 30), False)
    pix.clear_with(90)
    pix.save(str(logo))
    comp = dict(COMP, logo=str(logo))
    data = _data(d, inclusions="Cleanup daily\nDumpster")
    out = proposal.make_pdf(d, data, comp)
    text = "".join(pg.get_text() for pg in out)
    total = proposal.price(d, data)["total"]
    for want in ("PROPOSAL", "Aiken County", "Spay & Neuter Clinic",
                 "Acme Builders", "License G-12345", f"${total:,.2f}",
                 "Cleanup daily", "Permits, fees and bonds", "Acceptance",
                 "Page 1 of"):
        assert want in text, want
    assert out[0].get_images(), "logo missing"
    assert out.metadata["title"].startswith("Proposal")


def test_details_saved_with_the_job_and_company_in_settings():
    d = _job()
    data = _data(d, number="P-77")
    proposal.write(d, data)
    again = fitz.open(stream=d.tobytes(), filetype="pdf")
    assert proposal.read(again)["number"] == "P-77"
    proposal.save_company(COMP)
    assert proposal.company()["license"] == "G-12345"


def test_dialog_and_create_in_app(win):
    from app.proposal_ui import ProposalDialog
    from app import annotate
    v = win._view
    annotate.apply_op(v.doc, annotate.new_op("set_scale", 0, ppu=18,
                                             unit="ft"))
    annotate.apply_op(v.doc, annotate.new_op(
        "add_polyline", 0, pts=[[100, 100], [550, 100]],
        measure={"type": "length", "value": 25, "unit": "ft",
                 "group": WALL}))
    dlg = ProposalDialog(v.doc, win)
    dlg.d["client"].setText("Aiken County")
    dlg.pct["profit"].setValue(12)
    assert "Proposal total" in dlg.summary.text()
    data = dlg.values()
    assert data["client"] == "Aiken County" and data["profit"] == 12
    tabs = win.tabs.count()
    out = win.create_proposal(data=data, comp=COMP)
    assert out is not None and win.tabs.count() == tabs + 1
    assert "Aiken County" in out[0].get_text()
    assert proposal.read(v.doc)["profit"] == 12        # kept with the job
    for i in range(win.tabs.count()):              # nothing to save
        win.tabs.widget(i).view.dirty = False


def test_parts_view_groups_under_each_assembly():
    d = _job()
    data = _data(d, detail="parts", show_breakdown=True)
    out = proposal.make_pdf(d, data, COMP)
    text = "".join(pg.get_text() for pg in out)
    assert WALL in text and "Studs" in text
    assert f"{WALL} - Studs" not in text           # not repeated per part
    # the total is never alone at the top of a page
    for pg in out:
        words = pg.get_text("words")
        tot = [w for w in words if w[4] == "TOTAL"]
        if tot:
            above = [w for w in words if w[3] < tot[0][1] - 1
                     and w[1] > 40]
            assert above, "TOTAL separated from its breakdown"


def test_unlocked_bid_warns_inside_the_dialog_not_in_a_modal_box(
        win, monkeypatch):
    """Review 0.12.35 #20: the 'bid isn't locked' note no longer opens a
    modal box of its own before the proposal dialog (a stacked modal
    could leave a scripted run waiting); it is shown in the dialog and the
    status bar."""
    from PySide6.QtWidgets import QMessageBox
    from app import main_window, prebid, proposal_ui
    monkeypatch.setattr(prebid, "lock_state", lambda doc: None)

    def no_box(*a, **k):
        raise AssertionError("modal box opened")
    for name in ("warning", "information", "question", "critical"):
        monkeypatch.setattr(QMessageBox, name, no_box)
    seen = {}

    def fake_exec(self):
        seen["warning"] = self.warning_label.text() \
            if self.warning_label is not None else None
        seen["parent"] = self.parentWidget()
        return 0                                   # Cancel
    monkeypatch.setattr(proposal_ui.ProposalDialog, "exec", fake_exec)
    assert win.create_proposal() is None
    assert seen["warning"] == main_window.UNLOCKED_BID_WARNING
    assert seen["parent"] is win
