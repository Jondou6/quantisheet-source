"""Nov 4: scanned quotes (OCR), unit prices from the estimate on the bid
form, estimating hours in the dashboard, code signing set-up and Count
From a Picture. Made-up data only."""
import json
import os
from decimal import Decimal

import fitz
import pytest


# ---- 1. scanned sub quotes --------------------------------------------------

def test_scanned_quote_is_read_with_ocr(tmp_path, monkeypatch):
    from app import ocr, proposal_level
    d = fitz.open()
    d.new_page()                                     # no text: a "scan"
    p = str(tmp_path / "scan.pdf")
    d.save(p)
    monkeypatch.setattr(ocr, "ocr_page", lambda page: (
        "Acme Drywall\nGypsum board walls 1,000 SF $2.20 $2,200.00\n"
        "Total $2,200.00\n"))
    q = proposal_level.parse(p)
    assert q["bidder"] == "Acme Drywall" and q["ocr"] == "used"
    assert q["lines"][0]["amount"] == 2200.0
    assert q["check"].startswith("Read from a scan")


def test_scan_without_tesseract_says_so(tmp_path, monkeypatch):
    from app import ocr, proposal_level

    def no(page):
        raise ocr.OCRUnavailable("none")
    monkeypatch.setattr(ocr, "ocr_page", no)
    d = fitz.open()
    d.new_page()
    p = str(tmp_path / "s.pdf")
    d.save(p)
    q = proposal_level.parse(p)
    assert q["ocr"] == "unavailable" and "OCR" in q["check"]


def test_picture_of_a_quote(tmp_path, monkeypatch):
    from app import ocr, proposal_level
    d = fitz.open()
    pg = d.new_page(width=200, height=100)
    img = str(tmp_path / "q.png")
    pg.get_pixmap().save(img)
    monkeypatch.setattr(ocr, "ocr_page", lambda page: "Bravo\nPaint LS "
                        "$900.00\n")
    q = proposal_level.parse(img)
    assert q["ocr"] == "used" and q["lines"]


# ---- 2. unit prices from the estimate -------------------------------------------

def test_bid_form_unit_prices_from_the_estimate(tmp_path, monkeypatch):
    from app import bidform_auto as BA, estimate_lines as EL
    monkeypatch.setattr(BA, "base_bid", lambda d: Decimal("1000"))
    doc = fitz.open()
    doc.new_page()
    EL.add(doc, [EL.new_line("Rock excavation", 50, "cy", sub="85"),
                 EL.new_line("Concrete sidewalk", 200, "sf", mat="7.50")])
    f = fitz.open()
    pg = f.new_page()
    for i, (label, y) in enumerate((("1. Rock excavation, per CY", 100),
                                    ("2. Concrete sidewalk, per SF", 140),
                                    ("3. Unsuitable soil removal", 180)), 1):
        pg.insert_text((40, y + 12), label, fontsize=10)
        w = fitz.Widget()
        w.field_name = f"Unit Price {i}"
        w.rect = fitz.Rect(320, y, 450, y + 16)
        w.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        pg.add_widget(w)
    src = str(tmp_path / "form.pdf")
    f.save(src)
    got = BA.run(doc, src, str(tmp_path / "out.pdf"))
    vals = {w.field_name: w.field_value
            for p in fitz.open(str(tmp_path / "out.pdf")) for w in p.widgets()}
    assert vals["Unit Price 1"] == "$85.00"
    assert vals["Unit Price 2"] == "$7.50"
    assert vals["Unit Price 3"] in (None, "")          # not in the estimate
    assert any("from the estimate" in m for _ok, m in got["check"])
    # a typed price wins
    got2 = BA.run(doc, src, str(tmp_path / "o2.pdf"), unit_prices={1: 90})
    v2 = {w.field_name: w.field_value
          for p in fitz.open(str(tmp_path / "o2.pdf")) for w in p.widgets()}
    assert v2["Unit Price 1"] == "$90.00"


# ---- 3. estimating hours in the dashboard -------------------------------------------

def test_dashboard_jobs_get_their_time(tmp_path):
    from app import dashboard as db, timelog
    folder = str(tmp_path / "Job A")
    os.makedirs(folder)
    data = timelog.add({}, os.path.join(folder, "Plans.pdf"), "A-1",
                       "takeoff", 3600)
    timelog.add(data, os.path.join(folder, "Plans.pdf"), "A-2", "review",
                1800)
    timelog.add(data, str(tmp_path / "Other.pdf"), "A-1", "takeoff", 600)
    jobs = [db._new_job("a", name="Job A", folder=folder,
                        bid=Decimal("150000")),
            db._new_job("b", name="Nothing logged")]
    assert db.attach_time(jobs, data) == 1
    assert jobs[0]["hours"] == {"takeoff": 1.0, "review": 0.5,
                                "total": 1.5}
    assert jobs[1]["hours"] is None
    assert db.bid_cost_per_hour(jobs[0]) == Decimal("100000.00")
    r = db.bid_results(jobs)[0]
    assert r["hours"] == 1.5 and r["bid_per_hour"] == Decimal("100000.00")


# ---- 4. code signing, ready for the certificate ---------------------------------------

def _codesign():
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location(
        "codesign", os.path.join(here, "..", "tools", "codesign.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_code_signing_off_until_set_up(tmp_path, monkeypatch):
    cs = _codesign()
    monkeypatch.setattr(cs, "CONFIG", str(tmp_path / "codesign.json"))
    exe = tmp_path / "a.exe"
    exe.write_bytes(b"MZ")
    assert cs.config() is None and cs.sign([str(exe)]) == 0
    assert "not set up" in cs.status()
    (tmp_path / "codesign.json").write_text(json.dumps(
        {"thumbprint": "ab " * 13 + "c"}))            # not 40 characters
    assert cs.config() is None


def test_code_signing_when_set_up(tmp_path, monkeypatch):
    cs = _codesign()
    monkeypatch.setattr(cs, "CONFIG", str(tmp_path / "codesign.json"))
    (tmp_path / "codesign.json").write_text(json.dumps(
        {"thumbprint": "a1" * 20}))
    monkeypatch.setattr(cs, "find_signtool", lambda: "signtool.exe")
    exe = tmp_path / "a.exe"
    exe.write_bytes(b"MZ")
    ran = []

    class R:
        returncode = 0
        stdout = stderr = ""
    assert cs.sign([str(exe), str(tmp_path / "missing.exe")],
                   log=lambda *a: None,
                   run=lambda c, **k: (ran.append(c), R())[1]) == 1
    c = ran[0]
    assert c[:4] == ["signtool.exe", "sign", "/sha1", "A1" * 20]
    assert "/tr" in c and c[-1] == str(exe)

    class Bad(R):
        returncode = 1
        stderr = "token not present"
    with pytest.raises(RuntimeError):
        cs.sign([str(exe)], log=lambda *a: None, run=lambda c, **k: Bad())


def test_build_signs_when_set_up():
    here = os.path.dirname(os.path.abspath(__file__))
    src = open(os.path.join(here, "..", "tools", "build_installer.py"),
               encoding="utf-8").read()
    assert "codesign.sign([exe], log)" in src
    assert "codesign.sign(made, log)" in src


# ---- 5. Count From a Picture ---------------------------------------------------------

def _symbol_page():
    d = fitz.open()
    pg = d.new_page(width=600, height=400)
    for x, y in ((100, 100), (300, 120), (450, 300)):
        pg.draw_circle((x, y), 9, width=1.2)
        pg.draw_line((x - 9, y), (x + 9, y), width=1.2)
        pg.draw_line((x, y - 9), (x, y + 9), width=1.2)
    pg.draw_rect(fitz.Rect(200, 250, 260, 290), width=1.2)   # not it
    return d


def test_picture_found_at_the_drawings_size(tmp_path):
    pytest.importorskip("cv2")
    from app import picsearch
    import cv2
    import numpy as np
    # the "picture": the same symbol drawn much bigger, grey on off-white
    img = np.full((300, 300), 235, np.uint8)
    cv2.circle(img, (150, 150), 100, 60, 10)
    cv2.line(img, (50, 150), (250, 150), 60, 10)
    cv2.line(img, (150, 50), (150, 250), 60, 10)
    data = cv2.imencode(".png", img)[1].tobytes()
    doc = _symbol_page()
    tpl, px, hits = picsearch.template_for(doc, data, 0)
    assert px and len(hits) >= 3
    assert all(h["page"] == 0 for h in hits)


def test_picture_with_nothing_in_it():
    pytest.importorskip("cv2")
    from app import picsearch
    import cv2
    import numpy as np
    blank = cv2.imencode(".png", np.full((50, 50), 255, np.uint8))[1]
    with pytest.raises(ValueError):
        picsearch.clean(blank.tobytes())
    with pytest.raises(ValueError):
        picsearch.clean(b"not a picture")


def test_count_from_picture_in_window(tmp_path, monkeypatch):
    pytest.importorskip("cv2")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication, QMessageBox
    QApplication.instance() or QApplication([])
    from app import settings
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", None)
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: 0))
    import cv2
    import numpy as np
    img = np.full((120, 120), 250, np.uint8)
    cv2.circle(img, (60, 60), 40, 0, 4)
    cv2.line(img, (20, 60), (100, 60), 0, 4)
    cv2.line(img, (60, 20), (60, 100), 0, 4)
    pic = tmp_path / "sym.png"
    pic.write_bytes(cv2.imencode(".png", img)[1].tobytes())
    plan = str(tmp_path / "plan.pdf")
    _symbol_page().save(plan)
    from app.main_window import MainWindow
    w = MainWindow()
    assert w.open_path(plan)
    assert w.command("Count From a Picture") is not None
    dlg = w._view.count_from_picture(pic.read_bytes(), "Outlet", False,
                                     exec_review=False)
    assert dlg is not None and dlg is not 0
    w._view.dirty = False
    w.close()
    w.deleteLater()
