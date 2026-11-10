"""QuantiSheet 1.2 phase 4 (Nov 5): the water district's own form filled
in as an overlay, mapped once; tester certificate and gauge checks; the
submission record. Uses a MADE-UP stand-in page drawn here (a scanned
image, no fields) - never the real district form."""
import hashlib
import io

import fitz
import pytest
from PIL import Image, ImageDraw

from app import settings
from app.service import backflow, district_form as DF, testers
from r111_support import isolate, qapp, use_company  # noqa: F401


@pytest.fixture(autouse=True)
def svc_home(tmp_path, monkeypatch):
    use_company(monkeypatch)
    return isolate(tmp_path, monkeypatch)


def stand_in(path, rotate=0, scale=1.0):
    """A made-up scanned form: boxes drawn on an image, no fields."""
    w, h = int(850 * scale), int(1100 * scale)
    im = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(im)
    d.text((40 * scale, 30 * scale), "MADE-UP DISTRICT - TEST FORM", fill=0)
    for i in range(12):
        y = (100 + i * 60) * scale
        d.rectangle([60 * scale, y, 790 * scale, y + 30 * scale], outline=0)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    doc = fitz.open()
    page = doc.new_page(width=612 * scale, height=792 * scale)
    page.insert_image(page.rect, stream=buf.getvalue())
    if rotate:
        page.set_rotation(rotate)
    del page                    # nothing of a document outlives it
    doc.save(path)
    doc.close()
    return path


def _report(**kw):
    r = backflow.empty_report()
    r.update(acct_name="Test Smith", acct_address="1 Test Lane",
             dev_name="TestCo RPZ", dev_serial="BF-SN-1", dev_size="1",
             dev_application="Irrigation", test_date="2026-11-03",
             tester="A Tester", cert_no="SC-T-100", gauge_serial="G-1",
             c1_before_tight=True, c1_before_psi="5.2", so1_type="Gate")
    r.update(kw)
    return r


def _map(t, path):
    DF.set_form(t, path)
    DF.place(t, "acct_name", 72, 90)
    DF.place(t, "c1_before_tight", 300, 140)
    DF.place(t, "app_irrigation", 300, 240, 60, 20)
    DF.place(t, "so1_gate", 100, 500, 30, 20)
    DF.place(t, "so1_ball", 150, 500, 30, 20)
    DF.place(t, "c1_before_psi", 400, 200)
    DF.place(t, "repairs", 72, 300, 200, 24)
    return t


def _ink(path, rect, page=0):
    with fitz.open(path) as d:
        pix = d[page].get_pixmap(clip=rect, dpi=72, colorspace=fitz.csGRAY)
        return sum(1 for b in pix.samples if b < 160)


def _text(path, page=0):
    with fitz.open(path) as d:
        return d[page].get_text()


def _words(path, page=0):
    with fitz.open(path) as d:
        return {w[4]: w for w in d[page].get_text("words")}


def test_overlay_fills_a_copy_and_never_the_blank(tmp_path):
    blank = stand_in(str(tmp_path / "form.pdf"))
    before = hashlib.md5(open(blank, "rb").read()).hexdigest()
    t = DF.load_template()
    with pytest.raises(DF.FormError):
        DF.fill(_report(), str(tmp_path / "x.pdf"), t)        # not mapped
    _map(t, blank)
    DF.save_template(t)
    out = DF.fill(_report(), str(tmp_path / "filled.pdf"))
    assert hashlib.md5(open(blank, "rb").read()).hexdigest() == before
    words = _words(out["file"])
    assert abs(words["Smith"][1] - 90) < 12 and words["Test"][0] < 110
    assert "X" in words and abs(words["X"][0] - 300) < 8
    # gate or ball: a ring round the matching word only
    gate = fitz.Rect(98, 498, 132, 522)
    ball = fitz.Rect(148, 498, 182, 522)
    assert _ink(out["file"], gate) > _ink(blank, gate) + 10
    assert _ink(out["file"], ball) <= _ink(blank, ball) + 2
    # "circle one": a ring round the word, not an X
    ring = fitz.Rect(298, 238, 362, 262)
    assert _ink(out["file"], ring) > _ink(blank, ring) + 10
    assert "5.2" in words
    assert "Domestic" not in _text(out["file"])               # not ticked
    assert "Account no." in out["not_mapped"]
    with pytest.raises(DF.FormError):
        DF.fill(_report(), blank)                             # over the blank


def test_long_text_shrinks_wraps_then_goes_on_an_extra_page(tmp_path):
    blank = stand_in(str(tmp_path / "form.pdf"))
    t = _map(DF.load_template(), blank)
    short = DF.fill(_report(repair_materials="Replaced check 1 spring"),
                    str(tmp_path / "a.pdf"), t)
    assert short["overflow"] == []
    long = "Replaced the check 1 spring and seat, rubber kit, relief " \
           "valve diaphragm, cleaned the body, flushed the line. " * 6
    out = DF.fill(_report(repair_materials=long), str(tmp_path / "b.pdf"), t)
    assert out["overflow"] == ["Repairs and materials (all)"]
    with fitz.open(out["file"]) as doc:
        assert doc.page_count == 2
    assert "see attached" in _text(out["file"])
    assert "flushed the line" in _text(out["file"], 1)


def test_rotated_and_rescaled_pages_land_where_mapped(tmp_path):
    rot = stand_in(str(tmp_path / "rot.pdf"), rotate=90)
    t = DF.set_form(DF.load_template(), rot)
    assert t["page_size"] == [792, 612]                       # as it looks
    DF.place(t, "acct_name", 300, 200, 150, 20)
    out = DF.fill(_report(), str(tmp_path / "rf.pdf"), t)
    box = fitz.Rect(300, 200, 450, 220)
    assert _ink(out["file"], box) > _ink(rot, box) + 10
    # mapped on a letter page, filled on a page twice the size
    big = stand_in(str(tmp_path / "big.pdf"), scale=2.0)
    t2 = _map(DF.load_template(), stand_in(str(tmp_path / "f.pdf")))
    out2 = DF.fill(_report(), str(tmp_path / "bf.pdf"), t2, form_path=big)
    assert out2["scaled"]
    box2 = fitz.Rect(144, 180, 144 + 440, 180 + 28)
    assert _ink(out2["file"], box2) > _ink(big, box2) + 10


def test_repairs_go_in_comments_and_the_map_travels_with_the_form(
        tmp_path):
    blank = stand_in(str(tmp_path / "form.pdf"))
    t = DF.set_form(DF.load_template(), blank)
    DF.place(t, "comments", 72, 400, 400, 40)
    out = DF.fill(_report(repair_materials="New check 2 kit",
                          comments="All good."), str(tmp_path / "c.pdf"), t)
    assert "Repairs / materials: New check 2 kit. All good." in \
        " ".join(_text(out["file"]).split())
    DF.save_beside(t)                       # FORM.pdf.qsmap.json
    again = DF.set_form({"fields": {}, "nudge": [0, 0]}, blank)
    assert again["fields"]["comments"]["x"] == 72


def test_calibration_print_names_every_box(tmp_path):
    blank = stand_in(str(tmp_path / "form.pdf"))
    t = _map(DF.load_template(), blank)
    text = _text(DF.calibration(str(tmp_path / "cal.pdf"), t))
    assert "CALIBRATION" in text and "Account name" in text


def test_gate_or_ball_is_kept_on_the_report():
    st = backflow.blank()
    rid = backflow.add(st, _report(so2_type="Ball"))
    r = backflow.get(st, rid)
    assert (r["so1_type"], r["so2_type"]) == ("Gate", "Ball")
    with pytest.raises(backflow.BackflowError):
        backflow.add(st, _report(so1_type="Butterfly"))


def test_tester_and_gauge_checks():
    st = testers.blank()
    testers.set_tester(st, "A Tester", "SC-T-100", "2026-12-01")
    testers.set_gauge(st, "G-1", "2025-12-20")
    w = testers.check(_report(), st, today="2026-11-20")
    assert ("warn", "A Tester's tester certificate expires on 2026-12-01.") \
        in w
    assert any("due for calibration on 2026-12-20" in x for _k, x in w)
    w = testers.check(_report(), st, today="2027-01-05")
    assert [k for k, _x in w] == ["stop", "stop"]
    testers.set_tester(st, "A Tester", "SC-T-100", "2029-11-01")
    testers.set_gauge(st, "G-1", "2026-11-01")
    assert testers.check(_report(), st, today="2026-11-20") == []
    rep = _report(repair_materials="New check 1 spring")
    assert any("retest" in x for _k, x in
               testers.check(rep, st, today="2026-11-20"))
    rep["c1_after_tight"] = True
    assert testers.check(rep, st, today="2026-11-20") == []
    assert any("isn't on file" in x for _k, x in testers.check(
        _report(tester="B Nobody", gauge_serial=""), st, "2026-11-20"))
    settings.set("service_gauge_calibration_months", 6)
    assert any("calibration" in x for _k, x in testers.check(
        _report(), st, today="2027-06-01"))


def test_backflow_rules_say_not_yet_reviewed():
    assert "NOT YET REVIEWED" in testers.rule_note()
    assert "12 months" in testers.rule_note()


def test_submission_is_a_setting_with_no_default_deadline():
    rep = _report()
    assert "set the method" in testers.submit_line(rep)
    assert testers.submit_by(rep) == ""
    settings.set("service_backflow_submit_method", "email")
    settings.set("service_backflow_submit_to", "district@example.test")
    assert testers.submit_line(rep) == \
        "Submit by email to district@example.test."
    settings.set("service_backflow_submit_days", 10)
    assert testers.submit_by(rep) == "2026-11-13"
    rep["number"] = "BF-0001"
    assert testers.unsubmitted([rep]) == [("BF-0001", "Test Smith",
                                           "2026-11-13")]
    testers.mark_submitted(rep, when="2026-11-05")
    assert rep["submitted"] == {"how": "email", "on": "2026-11-05"}
    assert testers.unsubmitted([rep]) == []
    with pytest.raises(testers.TesterError):
        testers.mark_submitted(rep, how="pigeon")


def test_windows(qapp, tmp_path):
    from app.service import backflow_ui, district_form_ui
    blank = stand_in(str(tmp_path / "form.pdf"))
    m = district_form_ui.MapFormWindow()
    m.pick_clicked(path=blank)
    m.list.setCurrentRow(1)                                   # Account name
    box = m.click_at(72 * m.zoom, 90 * m.zoom)
    assert box["x"] == 72 and box["y"] == 90
    assert m.save_clicked() and m.calib_clicked(path=str(tmp_path / "c.pdf"))
    m.close()
    st = testers.blank()
    testers.set_tester(st, "A Tester", "SC-T-100", "2025-01-01")  # expired
    testers.save(st)
    w = backflow_ui.BackflowWindow()
    w.acct.setText("Test Smith")
    w.dev_name.setText("TestCo RPZ")
    w.tester.setText("A Tester")
    asked = []
    assert w.overlay_clicked(path=str(tmp_path / "o.pdf"),
                             ask=lambda t: asked.append(t) or False) is None
    assert "STOP" in asked[0] and "Not printed" in w.msg.text()
    out = w.overlay_clicked(path=str(tmp_path / "o.pdf"), ask=lambda t: True)
    assert "Smith" in _text(out["file"])
    w.save_clicked()
    assert w.submitted_clicked(how="mail", when="2026-11-05")["how"] == "mail"
    tw = w.testers_clicked()
    tw.g_serial.setText("G-9")
    tw.g_cal.setText("2026-10-01")
    tw.gauge_clicked()
    assert tw.table.rowCount() == 2
    tw.close()
    w.close()
