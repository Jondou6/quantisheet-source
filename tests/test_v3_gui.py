"""AI Takeoff v3 (Oct 31 2026) in the window (offscreen): the run-again
choice (new matches ticked, what's there locked, nothing counted twice),
the one review queue (accept / deny / undo through the window's Undo,
pending out of the totals until accepted) and the scale evidence panel."""
import os

import pytest

fitz = pytest.importorskip("fitz")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import aitakeoff as ait, annotate, rerun  # noqa: E402
from test_gui import win, qapp  # noqa: E402,F401
from test_v3_rerun import SQ, _poly, _count, _shift  # noqa: E402


def _res(marks, review=None):
    return {"scales": [], "marks": [(p, k, dict(pl, measure=dict(
        pl["measure"]))) for p, k, pl in marks], "assemblies": {},
        "review": list(review or []), "problems": [], "sheets": {},
        "quantities": []}


@pytest.fixture
def dlg(win, monkeypatch):
    monkeypatch.setattr(ait, "summary_text", lambda *a, **k: "summary")
    d = win.ai_takeoff(show=False)
    return d


def _ai_marks():
    return [_poly(SQ, "OFFICE 101", 100.0, review=False),
            _poly(_shift(SQ, 200, 0), "OFFICE 102", 100.0, review=True),
            _count([400, 300], "Doors"), _count([450, 300], "Doors")]


def test_second_run_adds_only_the_ticked_new_matches(dlg, win):
    doc = win._view.doc
    dlg._apply([], _res(_ai_marks()))
    before = rerun.drawing_totals(doc)
    shown = {}

    def confirm(d):
        shown["new"] = d.new_list.count()
        shown["prev"] = d.prev_list.count()
        return True
    dlg.confirm_rerun = confirm
    again = _ai_marks() + [_count([600, 300], "Doors")]
    dlg._apply([], _res(again))
    assert shown == {"new": 1, "prev": 4}
    assert "already on the drawing" in dlg.status.text()
    after = rerun.drawing_totals(doc)
    assert after[("Doors", "count", "ea")][0] == \
        before[("Doors", "count", "ea")][0] + 1
    for k, v in before.items():
        if k[0] != "Doors":
            assert after[k] == v
    # third run, the person unticks the new one: nothing changes at all
    def untick(d):
        from PySide6.QtCore import Qt
        d._all(Qt.Unchecked)
        return True
    dlg.confirm_rerun = untick
    dlg._apply([], _res(again + [_count([700, 300], "Doors")]))
    assert rerun.drawing_totals(doc) == after
    # cancel: nothing added
    dlg.confirm_rerun = lambda d: False
    assert dlg._apply([], _res(again + [_count([700, 350], "Doors")])) \
        is None
    assert rerun.drawing_totals(doc) == after


def test_one_queue_accept_deny_undo_in_the_window(dlg, win):
    doc = win._view.doc
    sched = {"engine": "schedules", "name": "DOOR 101 (schedule row)",
             "qty": 1, "unit": "EA", "page": 0, "sheet": "A601",
             "confidence": 0.5, "why": "row read with a gap"}
    dlg._apply([], _res(_ai_marks(), [sched]))
    q = dlg.review(show=False)
    kinds = {e["kind"] for e in q.entries}
    assert {"area", "count", "schedule row"} <= kinds
    scores = [(e["repeat"], e["score"]) for e in q.entries]
    assert scores == sorted(scores)
    tot = rerun.drawing_totals(doc)
    assert tot[("OFFICE 102", "area", "sq ft")] == (0.0, 100.0)  # pending
    # accept the pending room: it joins the totals, solid, no badge
    q.i = next(i for i, e in enumerate(q.entries)
               if e["name"] == "OFFICE 102")
    assert q.accept_one()
    tot = rerun.drawing_totals(doc)
    assert tot[("OFFICE 102", "area", "sq ft")] == (100.0, 0.0)
    assert not [e for e in q.entries if e["name"] == "OFFICE 102"]
    pg = doc[0]
    badged = any(annotate.is_badge(doc, a) and a.rect.intersects(
        fitz.Rect(250, 50, 350, 150)) for a in pg.annots())
    del pg                  # no page object held across the window's undo
    assert not badged
    # undo (through the window's Edit > Undo): pending again
    assert q.undo_one()
    tot = rerun.drawing_totals(doc)
    assert tot[("OFFICE 102", "area", "sq ft")] == (0.0, 100.0)
    # deny a count: gone from the drawing; undo brings it back
    n0 = tot[("Doors", "count", "ea")][0]
    q.i = next(i for i, e in enumerate(q.entries) if e["kind"] == "count")
    assert q.deny_one()
    assert rerun.drawing_totals(doc)[("Doors", "count", "ea")][0] == n0 - 1
    assert q.undo_one()
    assert rerun.drawing_totals(doc)[("Doors", "count", "ea")][0] == n0
    # the schedule row: typed quantity, accepted into the result
    q.i = next(i for i, e in enumerate(q.entries)
               if e["kind"] == "schedule row")
    q.qty.setText("2")
    line = q.accept_one()
    assert line["qty"] == 2 and line["status"] == "taken off"
    assert q.undo_one()
    assert sched in dlg.result["review"]
    rec = q.report_missed("DOOR 105 (missed)")
    assert rec["action"] == "missed"
    assert not [x for x in dlg.result["quantities"] if x.get("reviewed")]


def test_scale_item_shows_its_crop_and_confirming_releases(dlg, win):
    doc = win._view.doc
    page = doc[0]
    page.insert_text((60, 500), 'SCALE: 1/4" = 1\'-0"', fontsize=10)
    from app import scale_evidence as se
    ev = se.evidence(page, ('1/4" = 1\'-0"', 18.0, "ft"))
    assert ev["rect"] is not None
    item = {"engine": "scale", "kind": "scale", "name": "Scale on A101",
            "qty": None, "unit": "", "page": 0, "sheet": "A101",
            "confidence": 0.45, "why": "dimensions disagree",
            "rect": list(ev["rect"])}
    res = _res([], [item])
    res["sheets"] = {0: {"scale_review": True}}
    res["quantities"] = [{"name": "Wall 8in", "qty": 20, "unit": "LF",
                          "page": 0, "status": "pending review",
                          "scale_hold": True}]
    dlg._apply([], res)
    q = dlg.review(show=False)
    e = q.current()
    assert e["kind"] == "scale" and e["score"] == 45
    assert q.crop.pixmap() is not None and not q.crop.pixmap().isNull()
    assert q.acc_btn.text().startswith("Confirm Scale")
    assert q.accept_one()
    assert res["sheets"][0]["scale_review"] is False
    assert res["quantities"][0]["status"] == "taken off"
    assert q.undo_one()
    assert res["sheets"][0]["scale_review"] is True
    assert res["quantities"][0]["status"] == "pending review"


def test_ai_dialog_shows_scale_score_and_crop(dlg, win):
    doc = win._view.doc
    page = doc[0]
    page.insert_text((60, 520), 'SCALE: 1/8" = 1\'-0"', fontsize=10)
    from app import scale_evidence as se
    ev = se.evidence(page, ('1/8" = 1\'-0"', 9.0, "ft"), dims={})
    dlg.rows = [{"page": 0, "number": "A101", "title": "Plan",
                 "discipline": "Architectural", "scale": ['1/8" = 1\'-0"',
                                                         9.0, "ft"],
                 "scale_from": "sheet", "engines": ["rooms"], "note": "",
                 "scale_conf": ev["score"], "scale_why": ev["reasons"],
                 "scale_rect": list(ev["rect"]), "scale_review": False}]
    dlg._fill()
    assert f"{ev['score']}/100" in dlg.table.item(0, 4).text()
    assert dlg.table.item(0, 4).toolTip().startswith("Scale confidence")
    dlg.show_scale(0)
    assert not dlg.scale_crop.pixmap().isNull()
    assert "confidence" in dlg.scale_why.text()
