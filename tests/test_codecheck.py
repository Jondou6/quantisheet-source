"""Step 4 of the Venice modules: code check from the takeoff."""
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import annotate, codecheck as cc, settings         # noqa: E402
from test_gui import ANSWERS, win, qapp                    # noqa: E402,F401


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)


def _area(d, name, sf, x, y):
    side = 18 * sf ** 0.5 / 4
    annotate.apply_op(d, annotate.new_op(
        "add_polygon", 0, pts=[[x, y], [x + side, y], [x + side, y + side],
                               [x, y + side]],
        measure={"type": "area", "value": sf, "unit": "sq ft",
                 "group": name}))


def _len(d, name, ft, y):
    annotate.apply_op(d, annotate.new_op(
        "add_polyline", 0, pts=[[100, y], [100 + 4.5 * ft, y]],
        measure={"type": "length", "value": ft, "unit": "ft",
                 "group": name}))


def _count(d, name, n):
    for i in range(n):
        annotate.apply_op(d, annotate.new_op(
            "add_count", 0, pt=[1500 + 30 * i, 1500], n=1,
            measure={"type": "count", "value": 1, "unit": "ea",
                     "group": name}))


def _plan(path=None):
    d = fitz.open()
    d.new_page(width=2592, height=1728)
    annotate.apply_op(d, annotate.new_op("set_scale", 0, ppu=4.5,
                                         unit="ft"))
    _area(d, "OPEN OFFICE", 6000, 100, 100)
    _area(d, "CONFERENCE", 900, 900, 100)
    _area(d, "STORAGE", 600, 1300, 100)
    _area(d, "CORRIDOR", 1000, 1600, 100)
    _len(d, "Exit Door", 3, 1000)
    _len(d, "Exit Door", 3, 1020)
    _len(d, "Door", 2.5, 1040)
    _len(d, "Corridor", 3.5, 1060)
    _len(d, "Travel Distance", 320, 1080)
    _len(d, "Dead End", 30, 1100)
    _count(d, "Exit", 1)
    _count(d, "WC", 4)
    if path:
        d.save(path)
    return d


def _rules(findings):
    return {f["rule"]: f for f in findings}


def test_tables():
    assert [cc.accessible_parking(n) for n in (25, 26, 100, 101, 300, 500,
                                               600, 1000, 1200)] == \
        [1, 2, 4, 5, 7, 9, 12, 20, 22]
    assert [cc.van_parking(n) for n in (1, 6, 7)] == [1, 1, 2]
    fx = cc.fixtures(120, "B")
    assert (fx["wc_each"], fx["lav_each"], fx["df"]) == (3, 2, 2)
    assert cc.fixtures(50, "A-3") is None
    assert cc.occupant_load(1500, "business") == 10
    assert cc.occupant_load(301, "assembly_unconcentrated") == 21
    assert cc.occupant_load(1000, "support", "business") == 7
    assert cc.occupant_load(1000, "support", "classroom") == 0
    assert cc.guess_use("CONFERENCE 104") == "assembly_unconcentrated"
    assert cc.guess_use("WOMEN") == "support"
    assert cc.guess_use("Mystery", "M") == "mercantile"


def test_check_from_the_takeoff(tmp_path):
    d = _plan()
    cc.update(d, parking={"total": 120, "accessible": 4, "van": 1})
    findings, s = cc.check(d)
    assert s["occupants"] == 40 + 60 + 2 + 7
    r = _rules(findings)
    assert r["two-exits"]["severity"] == "warn"            # not entered
    assert r["two-exits"]["where"] == "CONFERENCE"
    assert r["door-width"]["actual"] == 30
    assert r["corridor-width"]["required"] == 44
    assert r["travel-distance"]["required"] == 300           # B, sprinklered
    assert "dead-end" not in r                               # 50 ft allowed
    assert r["exits-per-story"]["severity"] == "warn"        # 1 of 2
    assert "egress-capacity" not in r                        # 72 in >= 22
    assert r["accessible-parking"]["required"] == 5
    assert "van-parking" not in r
    assert r["plumbing-wc"]["required"] == 6 and \
        r["plumbing-wc"]["actual"] == 4
    assert findings[0]["severity"] == "error"

    cc.update(d, sprinklered=False, exits={"CONFERENCE": 1})
    r = _rules(cc.check(d)[0])
    assert r["dead-end"]["required"] == 20
    assert r["travel-distance"]["required"] == 200
    assert r["two-exits"]["severity"] == "error"
    cc.update(d, exits={"CONFERENCE": 2}, uses={"CONFERENCE":
                                                "assembly_concentrated"})
    findings, s = cc.check(d)
    assert "two-exits" not in _rules(findings)
    assert s["occupants"] == 40 + 129 + 2 + 7
    assert "egress-capacity" not in _rules(findings)

    # metric drawings are converted
    m = fitz.open()
    m.new_page()
    annotate.apply_op(m, annotate.new_op(
        "add_polyline", 0, pts=[[10, 10], [100, 10]],
        measure={"type": "length", "value": 0.8, "unit": "m",
                 "group": "Door"}))
    r = _rules(cc.check(m)[0])
    assert r["door-width"]["actual"] == pytest.approx(31.5, abs=0.1)

    n = cc.markup(d, findings)
    assert n >= 3
    clouds = [a for a in d[0].annots()
              if (a.info or {}).get("subject") == "Code Check"]
    assert len(clouds) == n and "1010.1.1" in " ".join(
        a.info["content"] for a in clouds)
    out = cc.report_pdf(d, str(tmp_path / "cc.pdf"), "Clinic")
    with fitz.open(out) as rep:
        text = "".join(p.get_text() for p in rep)
    assert "Code Check" in text and "1010.1.1" in text and \
        "CONFERENCE" in text and "Screening only" in text


def test_code_check_window(qapp, win, tmp_path, monkeypatch):
    path = str(tmp_path / "cc_plan.pdf")
    _plan(path)
    win.open_path(path)
    v = win._view
    dlg = win.code_check()
    assert dlg.spaces.rowCount() == 4
    names = [dlg.spaces.item(r, 1).text() for r in range(4)]
    row = names.index("STORAGE")
    cb = dlg.spaces.cellWidget(row, 3)
    cb.setCurrentIndex(cb.findData("business"))
    qapp.processEvents()
    assert cc.read(v.doc)["uses"]["STORAGE"] == "business"
    assert dlg.found.rowCount() >= 5
    got = []
    dlg.go_to.connect(lambda p, r: got.append(p))
    first = next(r for r in range(dlg.found.rowCount())
                 if dlg.findings[r].get("page") is not None)
    dlg._finding_go(dlg.found.item(first, 0))
    assert got == [0]
    from PySide6.QtGui import QDesktopServices
    monkeypatch.setattr(QDesktopServices, "openUrl",
                        staticmethod(lambda *a: True))
    out = dlg.report(str(tmp_path / "r.pdf"))
    assert os.path.exists(out)
    assert dlg.mark_up() >= 3
    dlg.close()
