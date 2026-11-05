"""Upgrade spec Phase 1 (missed-scope protection): markups linked to
estimate lines, uncovered revision changes flagged, RFI status tied to the
RFI log, the missed-item report, and scope carried to the next revision."""
import json
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import (annotate, assemblies, overlay, prebid, revisions,  # noqa
                 rfilog, settings)


@pytest.fixture(autouse=True)
def _cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Pat Morgan"})


def _sheet(extra=False, pages=1):
    d = fitz.open()
    for _ in range(pages):
        p = d.new_page(width=1224, height=792)
        for x in range(100, 1000, 150):          # some linework to align on
            p.draw_rect(fitz.Rect(x, 100, x + 120, 300), width=2)
        p.draw_line((100, 500), (1000, 500), width=2)
        if extra:
            p.draw_rect(fitz.Rect(700, 560, 820, 680), width=3)
    return d


def _op(d, kind, page, **kw):
    annotate.apply_op(d, annotate.new_op(kind, page, **kw))


_PAGES = []                        # annots need their page kept alive


def _marks(d, pno=0):
    page = d[pno]
    _PAGES.append(page)
    return [a for a in annotate.iter_annots(page)
            if not annotate.is_label(d, a)]


def _review(d):
    for p in range(d.page_count):
        prebid.set_reviewed(d, p)


def test_markup_linked_to_estimate_line():
    d = _sheet()
    _review(d)
    _op(d, "add_rect", 0, rect=[100, 600, 200, 700], note="Add bollards")
    a = _marks(d)[0]
    assemblies.set_job_assembly(d, {"name": "Bollards", "measure": "count",
                                    "parts": [{"name": "Bollard",
                                               "code": "05 50 00",
                                               "unit": "EA", "qty": "Count",
                                               "cost": 450}]})
    est = prebid.estimate_lines(d)
    assert "Bollards" in est["lines"] and "05 50 00" in est["codes"]
    prebid.link(d, a, line_id="Bollards")
    assert prebid.check(d).ok
    # survives save + reopen
    d = fitz.open("pdf", d.tobytes())
    assert prebid.scope_of(d, _marks(d)[0])["line_id"] == "Bollards"
    assert prebid.check(d).ok
    # the line leaves the estimate -> the markup is unpriced again
    job = assemblies.read_job(d)
    job["assemblies"].pop("Bollards")
    assemblies.write_job(d, job)
    rep = prebid.check(d)
    assert len(rep.open_markups) == 1 and "isn't in the estimate" in \
        rep.open_markups[0]["label"]
    # a scope set through the edit path (undo / live collaboration)
    mark = prebid.scope_mark(d, 0, _marks(d)[0], "excluded",
                             reason="By owner")
    _op(d, mark[1], mark[0], **mark[2])
    sc = prebid.scope_of(d, _marks(d)[0])
    assert sc["status"] == "excluded" and sc["line_id"] == "Bollards"
    assert prebid.check(d).ok


def test_rfi_status_creates_one_logged_rfi():
    d = _sheet()
    _review(d)
    _op(d, "add_rect", 0, rect=[100, 600, 200, 700],
        note="Footing depth at grid C?")
    a = _marks(d)[0]
    num = prebid.send_to_rfi(d, 0, a)
    items = rfilog.items(d)
    assert len(items) == 1 and items[0]["number"] == num
    assert items[0]["title"].startswith("Footing depth")
    assert prebid.send_to_rfi(d, 0, _marks(d)[0]) == num
    assert len(rfilog.items(d)) == 1
    assert prebid.check(d).ok
    # the RFI is answered: the markup stays "RFI" until it's repriced
    rfilog.update(d, items[0]["id"], status="Answered")
    assert prebid.scope_of(d, _marks(d)[0])["status"] == "rfi"
    assert prebid.check(d).ok


def test_uncovered_changes_are_flagged():
    old, new = _sheet(), _sheet(extra=True)
    res = overlay.compare(old, new, by_number=False)
    assert res[0]["changes"]
    marks = prebid.uncovered_change_marks(new, res)
    assert len(marks) == 1
    # a takeoff already over the change: nothing to flag
    _op(new, "add_polygon", 0, pts=[[690, 550], [830, 550], [830, 690],
                                    [690, 690]],
        measure={"type": "area", "value": 60, "unit": "sq ft",
                 "group": "New pad"})
    assert prebid.uncovered_change_marks(new, res) == []
    same = overlay.compare(_sheet(), _sheet(), by_number=False)
    assert prebid.uncovered_change_marks(_sheet(), same) == []


def test_missed_item_report(tmp_path):
    d = _sheet(pages=2)
    prebid.set_reviewed(d, 0)
    _op(d, "add_rect", 0, rect=[100, 600, 200, 700])
    _op(d, "add_cloud", 1, rect=[500, 600, 600, 700],
        subject=prebid.CHANGE_SUBJECT)
    rep = prebid.check(d)
    items = rep.items()
    assert [i["section"] for i in items] == [
        "Sheet not reviewed", "Markup open", "Revision cloud"]
    assert rep.to_dict()["spec_gaps"] == "not run"
    x = prebid.export_report(d, str(tmp_path / "m.xlsx"), rep)
    import openpyxl
    ws = openpyxl.load_workbook(x)["Missed items"]
    assert ws.max_row == 1 + len(items)
    p = prebid.export_report(d, str(tmp_path / "m.pdf"), rep)
    txt = fitz.open(p)[0].get_text()
    assert "MISSED-ITEM REPORT" in txt and "NOT READY" in txt


def test_scope_carries_to_the_next_revision():
    old, new = _sheet(), _sheet(extra=True)
    # one priced markup away from the change, one excluded on it
    _op(old, "add_rect", 0, rect=[150, 350, 250, 450], note="far")
    _op(old, "add_rect", 0, rect=[700, 560, 820, 680], note="on change")
    far, near = sorted(_marks(old), key=lambda a: a.rect.x0)
    prebid.set_scope(old, far, "priced", line_id="Bollards")
    prebid.set_scope(old, near, "excluded", "By owner", cost_code="03 30 00")
    prebid.set_reviewed(old, 0)
    res = overlay.compare(old, new, by_number=False)
    marks, _summary = revisions.carry_ops(old, new, res, flag=True)
    for pno, kind, payload in marks:
        _op(new, kind, pno, **payload)
    revisions.copy_job_data(old, new)
    got = {(a.info or {}).get("content"): prebid.scope_of(new, a)
           for a in _marks(new)}
    assert got["far"]["status"] == "priced" and \
        got["far"]["line_id"] == "Bollards"
    assert got["on change"]["status"] == "open" and \
        got["on change"]["cost_code"] == "03 30 00"
    near_new = next(a for a in _marks(new)
                    if (a.info or {}).get("content") == "on change")
    assert annotate.status_of(new, near_new) == annotate.REVISED
    # the new set's sheets have to be reviewed again
    assert prebid.check(new).unreviewed_sheets
