"""Revision-aware takeoff: the revision log and carrying takeoff onto a
newer set."""
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import annotate, assemblies, overlay, revisions     # noqa: E402
from test_gui import win, qapp                               # noqa: E402,F401
from test_planswift import _job, WALL, SLAB                  # noqa: E402


@pytest.fixture(autouse=True)
def _own_settings(tmp_path, monkeypatch):
    from app import settings
    monkeypatch.setattr(assemblies, "LIBRARY_PATH",
                        str(tmp_path / "assemblies.json"))
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


def _apply(doc, marks):
    for pno, kind, payload in marks:
        annotate.apply_op(doc, annotate.new_op(kind, pno, **payload))


def _delete_group(doc, group):
    page = doc[0]
    for a in list(page.annots()):
        if (a.info or {}).get("subject", "").split(":")[4:5] == [group]:
            page.delete_annot(a)


def test_revision_log_tracks_the_bid(tmp_path):
    d = _job()
    s0 = revisions.snapshot(d)
    assert s0["measurements"] == 4 and s0["total"] > 0
    assert any(k.startswith(WALL) for k in s0["quantities"])
    e = revisions.record(d, "Addendum 1", ["A-101"], flagged=[])
    assert e["no"] == 1 and e["before"]["total"] == s0["total"]
    rows = revisions.log_rows(d)
    assert rows[0]["change"] == 0 and rows[0]["latest"]
    # the slab is redrawn smaller in the addendum
    _delete_group(d, SLAB)
    side = 18 * 600 ** 0.5
    annotate.apply_op(d, annotate.new_op(
        "add_polygon", 0, pts=[[800, 200], [800 + side, 200],
                               [800 + side, 200 + side], [800, 200 + side]],
        measure={"type": "area", "value": 600, "unit": "sq ft",
                 "group": SLAB}))
    rows = revisions.log_rows(d)
    assert rows[0]["change"] < 0
    ch = revisions.revision_changes(d, 1)
    slab = [i for i in ch["items"] if i["name"] == SLAB]
    assert slab and slab[0]["qty_before"] == pytest.approx(1000) and \
        slab[0]["qty_after"] == pytest.approx(600)
    assert any(q["group"] == SLAB and q["change"] == pytest.approx(-400)
               for q in ch["quantities"])
    revisions.record(d, "Addendum 2")
    rows = revisions.log_rows(d)
    assert len(rows) == 2 and rows[0]["after"] == rows[1]["before"]
    out = revisions.export_xlsx(d, str(tmp_path / "rev.xlsx"))
    assert os.path.getsize(out) > 2000
    # the log travels inside the PDF
    d2 = fitz.open("pdf", d.tobytes())
    assert len(revisions.read(d2)["revisions"]) == 2


def test_carry_takeoff_onto_a_rescaled_newer_set():
    old = _job()
    w, h = old[0].rect.width, old[0].rect.height
    new = fitz.open()
    new.new_page(width=w, height=h)
    m = (0.8, 20.0, 10.0, 1.0, 0.0)               # replotted at 80 %
    change = fitz.Rect(780, 150, 1500, 900)        # around the slab (new)
    res = [{"old": 0, "new": 0, "sheet": "A-101", "align": m,
            "changes": [change], "changed_pct": 3.0}]
    revisions.copy_job_data(old, new)
    marks, summary = revisions.carry_ops(old, new, res)
    _apply(new, marks)
    assert summary["carried"] == 4 and summary["sheets"] == 1
    # scale follows the plot size, so real lengths stay the same
    assert annotate.read_scales(new)[0]["ppu"] == pytest.approx(18 * 0.8)
    items = {i["group"]: i for i in annotate.takeoff_items(new)}
    assert items[WALL]["value"] == pytest.approx(40)
    page = new[0]
    wall = [a for a in page.annots()
            if (a.info or {}).get("subject", "").startswith(
                annotate.TAKEOFF) and WALL in a.info["subject"]][0]
    assert wall.vertices[0][0] == pytest.approx(100 * 0.8 + 20, abs=0.5)
    # the slab sits on the changed area: flagged for re-measure, the wall
    # isn't
    flagged = revisions.flagged_refs(new)
    assert summary["flagged"] >= 1 and len(flagged) >= 1
    assert annotate.status_of(new, wall) != annotate.REVISED
    # the job's assemblies came across, so the carried takeoff is priced
    assert revisions.snapshot(new)["total"] == pytest.approx(
        revisions.snapshot(old)["total"], rel=0.001)
    assert revisions.value_of(new, flagged) > 0


def test_revision_log_window(qapp, win, tmp_path):
    d = _job()
    p = tmp_path / "job.pdf"
    d.save(str(p))
    win.open_path(str(p))
    dlg = win.revision_log(show=False)
    assert dlg.refresh() == [] and "No revisions" in dlg.head.text()
    dlg.record("Rev B")
    assert dlg.table.rowCount() == 1
    assert dlg.show_detail() is not None
    assert revisions.export_xlsx(dlg.doc, str(tmp_path / "log0.xlsx"))
    assert dlg.export(str(tmp_path / "log.xlsx"))
    assert win.command("Revision Log") is not None
