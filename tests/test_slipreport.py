"""v16: slip-sheet report, unmatched sheets first."""
import csv
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import fitz                                                   # noqa: E402
from app import sets, slipreport                              # noqa: E402
from test_sets import _files                                  # noqa: E402
from test_gui import qapp                                     # noqa: E402,F401


def _with_unnumbered(pr):
    d = fitz.open(pr)
    pg = d.new_page(width=1224, height=792)
    pg.insert_text((100, 100), "SKETCH", fontsize=12)
    d.saveIncr()


def test_plan_rows_unmatched_first(tmp_path):
    pa, pm, pr = _files(tmp_path)
    _with_unnumbered(pr)
    s = sets.new(str(tmp_path / "Job.pdfset"), [pa, pm])
    rows = slipreport.rows(sets.plan(s, [pr]))
    kinds = [r["kind"] for r in rows]
    assert kinds[0] == "unmatched"
    assert rows[0]["sheet"] == "(no number)" and "p.4" in rows[0]["new"]
    order = ["unmatched", "duplicate", "new", "slip", "no revision"]
    assert [k for k in order if k in kinds] == sorted(
        set(kinds), key=order.index)
    assert kinds.index("new") < kinds.index("slip") < kinds.index(
        "no revision")
    s_ = slipreport.summary(rows)
    assert s_.startswith("1 revised page(s) NOT matched")


def test_after_run_changed_sheets_come_before_unchanged(tmp_path):
    pa, pm, pr = _files(tmp_path)
    _with_unnumbered(pr)
    s = sets.new(str(tmp_path / "Job.pdfset"), [pa, pm])
    p = sets.plan(s, [pr])
    rep = sets.batch_slip(s, [pr], "Add 1", allow_unmatched=True)
    rows = slipreport.rows(p, rep)
    kinds = [r["kind"] for r in rows]
    assert kinds[0] == "unmatched"
    assert kinds.index("changed") < kinds.index("slip")
    a101 = next(r for r in rows if r["sheet"] == "A-101")
    assert a101["kind"] == "changed" and "flagged" in a101["action"]


def test_exports(tmp_path):
    pa, pm, pr = _files(tmp_path)
    _with_unnumbered(pr)
    s = sets.new(str(tmp_path / "Job.pdfset"), [pa, pm])
    rows = slipreport.rows(sets.plan(s, [pr]))
    c = slipreport.to_csv(rows, str(tmp_path / "r.csv"))
    got = list(csv.reader(open(c, encoding="utf-8")))
    assert got[0][:2] == ["Status", "Sheet"] and got[1][0] == "NOT MATCHED"
    p = slipreport.to_pdf(rows, str(tmp_path / "r.pdf"), "Add 1")
    txt = fitz.open(p)[0].get_text()
    assert txt.index("NOT MATCHED") < txt.index("A-101")


def test_dialog(qapp, tmp_path):
    pa, pm, pr = _files(tmp_path)
    s = sets.new(str(tmp_path / "Job.pdfset"), [pa, pm])
    dlg = slipreport.SlipReportDialog(None, slipreport.rows(
        sets.plan(s, [pr])))
    assert dlg.table.rowCount() == 4
