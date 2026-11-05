"""Review CHECK Items: each flagged AI Takeoff line accepted, fixed or
deleted by a person, and the totals / workbook following."""
import pytest


def _res():
    return {"quantities": [],
            "review": [
                {"engine": "envelope", "name": "Exterior wall - 8\" CMU "
                 "back-up", "qty": 4164.9, "unit": "SF", "page": None,
                 "sheet": "set", "csi": "04 22 00",
                 "why": "AI-derived, confidence 0.55 - top wall mark"},
                {"engine": "devices", "name": "EXAMPLE PANEL", "qty": 1,
                 "unit": "ea", "page": 2, "sheet": "E-201",
                 "why": "the same symbol is drawn on another plan of the "
                        "same floor - counted once"},
                {"engine": "fittings", "name": "2\" 90 elbow - vent",
                 "qty": 7, "unit": "EA", "page": None, "sheet": "P-101",
                 "csi": "22 13 16", "why": "counted from the layout"},
                {"name": "legend line", "qty": None, "unit": "ea",
                 "page": 0, "sheet": "E-001", "why": "not a device name"}]}


def test_queue_puts_quantities_first_and_repeats_last():
    from app import review
    q = review.queue(_res())
    assert q[0]["name"].startswith("Exterior wall")
    assert q[1]["name"].startswith("2\" 90 elbow")
    assert q[-1]["name"] == "EXAMPLE PANEL"          # a repeat: last


def test_accept_fix_and_delete():
    from app import review
    res = _res()
    cmu, panel, elbow, note = res["review"]
    line = review.accept(res, cmu, who="Example Estimator")
    assert line["qty"] == 4164.9 and line["status"] == "taken off"
    assert "accepted as found by Example Estimator" in line["basis"]
    fixed = review.accept(res, elbow, qty=11, who="Example Estimator")
    assert fixed["qty"] == 11 and "AI found 7" in fixed["basis"]
    assert review.accept(res, note) is None          # no quantity: stays
    review.delete(res, panel)
    assert res["review"] == [note]
    c = review.counts(res)
    assert c == {"left": 1, "accepted": 1, "fixed": 1, "deleted": 1}
    assert [d["action"] for d in review.decisions(res)] == \
        ["accepted", "fixed", "deleted"]


def test_the_workbook_follows_the_decisions():
    from app import estimate_book, review
    res = _res()
    cmu, panel, elbow, _note = res["review"]
    review.accept(res, cmu)
    review.delete(res, panel)
    review.accept(res, elbow, qty=11)
    by = {l["description"]: l for l in estimate_book.collect([], res)}
    assert by["Exterior wall - 8\" CMU back-up"]["status"] == "taken off"
    assert by["Exterior wall - 8\" CMU back-up"]["qty"] == 4164.9
    assert by["2\" 90 elbow - vent"]["qty"] == 11
    assert "EXAMPLE PANEL" not in by


def test_review_dialog_steps_through(qtbot):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QWidget
    from app.review_ui import ReviewDialog
    res = _res()
    host = QWidget()
    qtbot.addWidget(host)
    seen = []
    dlg = ReviewDialog(host, res, who="Example Estimator",
                       on_change=lambda: seen.append(1))
    qtbot.addWidget(dlg)
    # least sure first (Oct 31): the note with no quantity, the elbows
    # (no score given), the CMU (confidence 0.55), the repeat last
    assert "legend line" in dlg.title.text()
    assert "score 20/100" in dlg.where.text()
    dlg.skip()                                        # the note
    assert "2\" 90 elbow" in dlg.title.text()
    dlg.qty.setText("11")
    dlg.accept_one()                                  # elbows fixed
    assert any(q["qty"] == 11 for q in res["quantities"])
    assert "Exterior wall" in dlg.title.text()
    dlg.accept_one()                                  # CMU as found
    assert "EXAMPLE PANEL" in dlg.title.text()
    assert "already counted" in dlg.where.text()
    dlg.delete_one()
    assert dlg.current() is None and len(seen) == 3
    assert "still to check" not in dlg.progress.text()
    assert "1 to check" in dlg.progress.text()


def test_ai_marks_are_pencil_until_accepted():
    from app import aitakeoff_ui, tradetakeoff_ui
    marks = [(0, "add_polyline", {"pts": [[0, 0], [1, 1]],
                                  "measure": {"method": "AI takeoff: pipe "
                                              "runs"}}),
             (0, "add_count", {"pt": [0, 0]})]
    out = aitakeoff_ui._pencil(marks)
    assert out[0][2]["dashes"] == aitakeoff_ui.PENCIL
    # Oct 31: AI count dots are pencil too (a dashed ring until accepted)
    assert out[1][2]["dashes"] == aitakeoff_ui.PENCIL
    assert "dashes" not in marks[0][2]                # input untouched
    assert tradetakeoff_ui._solid({"method": "AI takeoff: pipe runs"}) == \
        {"dashes": []}
    assert tradetakeoff_ui._solid({"method": "manual"}) == {}


def test_accepting_an_ai_line_makes_it_solid():
    fitz = pytest.importorskip("fitz")
    from app import annotate
    d = fitz.open()
    d.new_page()
    annotate.apply_op(d, {"kind": "add_polyline", "page": 0, "id": "t1",
                          "payload": {
                              "pts": [[50, 50], [150, 50], [150, 120]],
                              "dashes": [6, 4],
                              "measure": {"type": "length", "value": 10,
                                          "unit": "ft", "group": '2" W',
                                          "method": "AI takeoff: pipe runs"}}},
                      fresh=True)
    pg = d[0]
    a = [x for x in pg.annots() if x.type[1] == "PolyLine"][0]
    assert (a.border or {}).get("dashes")
    xref = a.xref
    annotate.apply_op(d, {"kind": "set_annot", "page": 0, "id": "t2",
                          "payload": {"xref": xref, "dashes": []}},
                      fresh=True)
    pg = d[0]
    a = [x for x in pg.annots() if x.type[1] == "PolyLine"][0]
    assert not (a.border or {}).get("dashes")
