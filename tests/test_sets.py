"""Sets (many PDFs as one drawing set) and batch slip sheet."""
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import annotate, assemblies, revisions, sets        # noqa: E402
from test_gui import win, qapp                               # noqa: E402,F401


@pytest.fixture(autouse=True)
def _own_settings(tmp_path, monkeypatch):
    from app import settings
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


def _sheet(doc, number, title, extra=0, shift=(0, 0)):
    pg = doc.new_page(width=1224, height=792)
    sx, sy = shift
    sh = pg.new_shape()
    for k in range(6):
        y = 120 + k * 90 + sy
        sh.draw_line((100 + sx, y), (900 + sx, y))
        sh.draw_line((100 + k * 150 + sx, 100 + sy),
                     (100 + k * 150 + sx, 600 + sy))
    if extra:
        sh.draw_rect(fitz.Rect(600 + sx, 300 + sy, 800 + sx, 420 + sy))
    sh.finish(color=(0, 0, 0), width=2)
    sh.commit()
    pg.insert_text((1040, 700), title, fontsize=9)
    pg.insert_text((1040, 750), number, fontsize=22)
    return pg


def _files(tmp_path):
    a = fitz.open()
    _sheet(a, "A-101", "FLOOR PLAN")
    _sheet(a, "A-201", "ELEVATIONS")
    m = fitz.open()
    _sheet(m, "M-101", "HVAC PLAN")
    pa, pm = str(tmp_path / "Arch.pdf"), str(tmp_path / "Mech.pdf")
    # a takeoff on A-101 (on the area that will change) and on A-201
    annotate.apply_op(a, annotate.new_op("set_scale", 0, ppu=18, unit="ft"))
    annotate.apply_op(a, annotate.new_op(
        "add_polyline", 0, pts=[[620, 320], [780, 320], [780, 400]],
        measure={"type": "length", "value": 13.3, "unit": "ft",
                 "group": "Wall"}))
    annotate.apply_op(a, annotate.new_op(
        "add_polyline", 1, pts=[[120, 140], [300, 140]],
        measure={"type": "length", "value": 10, "unit": "ft",
                 "group": "Wall"}))
    a.save(pa)
    m.save(pm)
    rev = fitz.open()
    _sheet(rev, "M-101", "HVAC PLAN")                # same
    _sheet(rev, "A-101", "FLOOR PLAN", extra=1, shift=(6, -4))   # changed
    _sheet(rev, "A-301", "SECTIONS")                 # new sheet
    pr = str(tmp_path / "Addendum 1.pdf")
    rev.save(pr)
    return pa, pm, pr


def test_set_index_order_and_navigation(tmp_path):
    pa, pm, _ = _files(tmp_path)
    s = sets.new(str(tmp_path / "Job.pdfset"), [pm, pa])
    nums = [r["number"] for r in sets.sheets(s)]
    assert nums == ["A-101", "A-201", "M-101"]          # discipline order
    assert sets.find(s, "m-101")["file"] == pm
    nxt = sets.neighbor(s, pa, 1)
    assert nxt["number"] == "M-101"
    s2 = sets.load(s["path"])
    assert len(s2["index"]) == 3 and s2["files"] == ["Mech.pdf", "Arch.pdf"]


def test_batch_slip_sheet_across_files(tmp_path):
    pa, pm, pr = _files(tmp_path)
    s = sets.new(str(tmp_path / "Job.pdfset"), [pa, pm])
    p = sets.plan(s, [pr])
    assert [m["number"] for m in p["matches"]] == ["A-101", "M-101"]
    assert [r["number"] for r in p["new_only"]] == ["A-301"]
    assert p["unchanged"] == ["A-201"]
    rep = sets.batch_slip(s, [pr], "Addendum 1")
    assert os.path.exists(os.path.join(rep["backup"], "Arch.pdf"))
    arch = next(f for f in rep["files"] if f["file"] == pa)
    assert arch["changed"] == 1 and arch["flagged"] == 1
    d = fitz.open(pa)
    # the takeoffs are still there; the changed one is flagged
    st = [annotate.status_of(d, a) for pg in d for a in pg.annots()
          if (a.info or {}).get("subject", "").startswith(annotate.TAKEOFF)]
    assert annotate.REVISED in st
    assert revisions.read(d)["revisions"][0]["label"] == "Addendum 1"
    assert any("Previous drawing" in str(v) for v in
               (d.layer_ui_configs() or []))
    # the new sheet joined the set
    assert sets.find(s, "A-301") is not None
    mech = next(f for f in rep["files"] if f["file"] == pm)
    assert mech["changed"] == 0


def test_sets_panel_and_batch_dialog(qapp, win, tmp_path):
    from app.sets_ui import BatchSlipDialog
    pa, pm, pr = _files(tmp_path)
    s = win.sets.new_set([pa, pm], str(tmp_path / "Job.pdfset"))
    assert win.sets.fill() == 3
    win.sets.filter.setText("m-1")
    assert win.sets.fill() == 1
    win.sets.filter.setText("")
    v = win.open_sheet(pa, 1)
    assert v is not None and v.page == 1
    dlg = win.batch_slip_sheet(show=False)
    assert isinstance(dlg, BatchSlipDialog)
    p = dlg.pick([pr])
    assert dlg.table.rowCount() == 3 and dlg.go.isEnabled()
    rep = dlg.run()
    assert rep and len(rep["files"]) == 2
    assert win.command("Batch Slip Sheet") is not None


def test_unnumbered_revised_sheet_is_never_dropped_silently(tmp_path):
    """Review R12: a revised page with no readable number is reported and
    batch_slip refuses until told to go ahead."""
    pa, pm, pr = _files(tmp_path)
    d = fitz.open(pr)
    pg = d.new_page(width=1224, height=792)
    pg.insert_text((300, 300), "REVISED DETAIL - NO TITLE BLOCK",
                   fontsize=12)
    d.saveIncr()
    d.close()
    s = sets.new(str(tmp_path / "Job.pdfset"), [pa, pm])
    p = sets.plan(s, [pr])
    assert p["unmatched"] == [{"file": pr, "page": 3}]
    with pytest.raises(sets.SlipError):
        sets.batch_slip(s, [pr], "Addendum 1")
    rep = sets.batch_slip(s, [pr], "Addendum 1", allow_unmatched=True)
    assert rep["unmatched"] and len(rep["files"]) == 2


def test_p1_drawing_log_current_and_superseded(tmp_path):
    """P1 #7: the drawing log lists every sheet at its current revision,
    with the revisions it replaced, and exports as CSV."""
    import csv
    pa, pm, pr = _files(tmp_path)
    s = sets.new(str(tmp_path / "Job.pdfset"), [pa, pm])
    log0 = {r["number"]: r for r in sets.drawing_log(s)}
    assert log0["A-101"]["current"] == "Original"
    assert log0["A-101"]["history"] == []
    sets.batch_slip(s, [pr], "Addendum 1")
    d = fitz.open(pa)
    revisions.record(d, "Bulletin 2", ["A-101"], flagged=[])
    d.saveIncr()
    d.close()
    s = sets.load(s["path"])
    log1 = {r["number"]: r for r in sets.drawing_log(s)}
    a101 = log1["A-101"]
    assert a101["current"] == "Bulletin 2"
    assert [h["label"] for h in a101["history"]] == ["Bulletin 2",
                                                     "Addendum 1"]
    assert log1["A-201"]["current"] == "Original"       # untouched sheet
    assert "A-301" in log1                             # new sheet joined
    out = tmp_path / "log.csv"
    assert sets.drawing_log_csv(s, str(out)) == len(log1)
    rows = list(csv.reader(open(out, encoding="utf-8-sig")))
    assert rows[0][:4] == ["Sheet", "Title", "Discipline",
                           "Current revision"]
    r = next(x for x in rows if x[0] == "A-101")
    assert r[3] == "Bulletin 2" and r[5].startswith("Addendum 1")


def test_p1_drawing_log_button(qapp, win, tmp_path):
    pa, pm, _pr = _files(tmp_path)
    win.sets.new_set([pa, pm], str(tmp_path / "Job.pdfset"))
    out = tmp_path / "log.csv"
    assert win.sets.export_log(str(out)) == 3
    assert out.exists()
