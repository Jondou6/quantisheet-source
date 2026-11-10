"""PR 8 wired (Nov 4): Build Schedule From Plans > Detailed draft. The
completeness gate stops "built" until the gaps are accepted; the old build
stays the default."""
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication                       # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dlg(qapp, tmp_path, monkeypatch):
    from app import settings
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {})
    from app.pm import scheduler as sch
    spec = fitz.open()
    pg = spec.new_page()
    pg.insert_text((72, 72), "SECTION 00 41 00 - BID FORM", fontsize=10)
    pg.insert_text((72, 100), "The Contractor shall fully complete all "
                   "Work within 200 calendar days.", fontsize=9)
    for div, title in (("03 30 00", "CAST-IN-PLACE CONCRETE"),
                       ("09 91 00", "PAINTING"), ("22 10 00", "PLUMBING"),
                       ("26 05 00", "ELECTRICAL"),
                       ("26 32 13", "ENGINE GENERATORS")):
        p = spec.new_page()
        p.insert_text((72, 72), f"SECTION {div} - {title}", fontsize=10)
    sp = str(tmp_path / "spec.pdf")
    spec.save(sp)
    st = sch.create_schedule("Clinic", folder=str(tmp_path / "job"))
    w = sch.Scheduler(st)
    w._quiet = True
    d = w.build_from_plans(spec=sp, show=False)
    d.ntp.setText("11/02/26")
    d.read()
    d.area.setText("4000")
    yield d, w, st
    w.close()


def test_detailed_is_off_by_default(dlg):
    d, _w, _st = dlg
    assert not d.detailed.isChecked()


def test_detailed_draft_gate_and_apply(dlg):
    d, w, st = dlg
    d.detailed.setChecked(True)
    i = d.ptype.findData("new_building")
    d.ptype.setCurrentIndex(i)
    sc, _ct, ntp = d.inputs()
    asked = []
    res = d._build_detailed(st, sc, ntp,
                            ask=lambda t: asked.append(t) or False)
    if d.draft.get("status") != "finished":
        assert res is None and asked and "NOT a finished" in asked[0]
        assert not st.list("activity")                # nothing put in
        res = d._build_detailed(st, sc, ntp, ask=lambda t: True)
    assert res and res["detailed"]["activities"]
    assert len(st.list("activity")) >= 10
    assert w.undo() and not st.list("activity")       # undo brings it back


def test_addenda_make_a_bid_set_draft(dlg, tmp_path):
    """Nov 5: addenda / Q&A picked in the dialog are applied before the
    detailed draft is built; removed items stay off (made-up text)."""
    d, _w, st = dlg
    bid = fitz.open()
    pg = bid.new_page()
    pg.insert_text((72, 72), "SCOPE OF WORK", fontsize=10)
    pg.insert_text((72, 90), "1. Interior demolition (about 1,200 SF).",
                   fontsize=9)
    pg.insert_text((72, 104), "2. Power wash the building exterior.",
                   fontsize=9)
    pg.insert_text((72, 118), "3. New flooring and base (about 800 SF).",
                   fontsize=9)
    bp = str(tmp_path / "bid.pdf")
    bid.save(bp)
    bid.close()
    ad = tmp_path / "Addendum 1.txt"
    ad.write_text("ADDENDUM 1\n1. Delete item 2.\n", encoding="utf-8")
    d.spec.setText(bp)
    d.add_addenda([str(ad)])
    assert d.detailed.isChecked()
    assert "1. Addendum 1.txt" in d.addenda_lbl.text()
    sc, _ct, ntp = d.inputs()
    res = d._build_detailed(st, sc, ntp, ask=lambda t: True)
    doc = res["detailed"]
    names = " ".join(a["name"].lower() for a in doc["activities"])
    assert "demolition" in names and "flooring" in names
    assert "power wash" not in names
    assert doc["scope"]["removed"][0]["removed_by"] == "Addendum 1 item 1"
    assert doc["caveat"] in d.last_message
