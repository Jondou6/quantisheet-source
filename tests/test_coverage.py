"""Coverage map and second-person check (upgrade spec 1b, 1g)."""
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import annotate, coverage, prebid, settings          # noqa: E402


@pytest.fixture(autouse=True)
def _cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Pat Morgan"})


def _doc(pages=3):
    d = fitz.open()
    for i in range(pages):
        p = d.new_page(width=1224, height=792)
        p.insert_text((1100, 760), f"C-10{i + 1}", fontsize=14)
    annotate.apply_op(d, annotate.new_op("set_scale", 0, ppu=18.0,
                                         unit="ft", pages=list(range(pages))))
    return d


def _area(d, pno, rect):
    x0, y0, x1, y1 = rect
    annotate.apply_op(d, annotate.new_op(
        "add_polygon", pno, pts=[[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
        measure={"type": "area", "value": 100, "unit": "sf",
                 "group": "Paving"}))


def test_no_takeoff_is_red_and_zero():
    d = _doc(1)
    s = coverage.status(d)[0]
    assert s["color"] == "red" and s["coverage"] == 0


def test_coverage_of_a_known_area_within_one_percent():
    d = _doc(1)
    area = coverage.drawing_area(d[0])
    _area(d, 0, (area.x0, area.y0, area.x0 + area.width / 2, area.y1))
    assert coverage.coverage(d, 0) == pytest.approx(0.5, abs=0.01)
    # the title block (right 20%) doesn't count
    d2 = _doc(1)
    _area(d2, 0, (area.x1 + 5, 10, d2[0].rect.x1 - 5, 700))
    assert coverage.coverage(d2, 0) == 0


def test_colors_follow_review_and_takeoff():
    d = _doc(3)
    _area(d, 1, (100, 100, 300, 300))
    _area(d, 2, (100, 100, 300, 300))
    prebid.set_reviewed(d, 2)
    colors = [s["color"] for s in coverage.status(d)]
    assert colors == ["red", "amber", "green"]


def test_second_check_must_be_someone_else():
    d = _doc(1)
    with pytest.raises(coverage.CheckError, match="reviewed"):
        coverage.set_checked(d, 0)                   # not reviewed yet
    prebid.set_reviewed(d, 0)
    with pytest.raises(coverage.CheckError, match="someone else"):
        coverage.set_checked(d, 0)                   # same person
    coverage.set_checked(d, 0, by="Pat Smith")
    s = coverage.status(d)[0]
    assert s["checked"] and s["checked_by"] == "Pat Smith"
    assert prebid.read(d)["log"][-1]["action"] == "checked"


def test_lock_waits_for_the_second_check_when_required():
    d = _doc(2)
    for p in range(2):
        prebid.set_reviewed(d, p)
    settings.set("second_check_required", True)
    settings.set("second_check_over", 0)
    assert coverage.status(d)[0]["color"] == "amber"
    with pytest.raises(prebid.PrebidError, match="second-checked"):
        prebid.lock(d, 250000)
    # only required over $500,000: a $250,000 bid locks
    settings.set("second_check_over", 500000)
    assert prebid.lock(d, 250000)
    prebid.unlock(d, reason="test")
    settings.set("second_check_over", 0)
    for p in range(2):
        coverage.set_checked(d, p, by="Pat Smith")
    assert prebid.lock(d, 250000)
    assert all(s["color"] == "green" for s in coverage.status(d))


def test_not_required_by_default():
    d = _doc(1)
    prebid.set_reviewed(d, 0)
    assert coverage.unchecked(d) == []
    assert prebid.lock(d, 1000)


def test_coverage_map_window(qapp, win, tmp_path):
    from app import coverage_ui
    d = _doc(3)
    _area(d, 0, (100, 100, 400, 400))
    path = str(tmp_path / "set.pdf")
    d.save(path)
    win.open_path(path)
    acts = [a.text() for a in win.findChildren(type(win.menuBar().actions()
                                                     [0]))]
    assert "Coverage Map and Second Check…" in acts
    dlg = coverage_ui.show(win, show=False)
    assert dlg.grid.count() == 3
    for _ in range(5):
        dlg._draw_some()
    assert not dlg.grid.item(0).icon().isNull()
    assert dlg.mark_reviewed([0, 1]) == 2
    assert dlg.mark_checked([0]) == 0                 # own review
    assert dlg.mark_checked([0, 1], by="Pat Smith") == 2
    assert "✓✓" in dlg.grid.item(0).text()
    win._view.dirty = False


from test_gui import win, qapp                        # noqa: E402,F401
