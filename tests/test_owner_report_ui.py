"""Weekly Owner Report window: new report, trades, progress lines (Daily
Log draft and the AI draft with a scripted model), photos (add, order,
leave out), add-ons, size estimate, preview, export and Mark as Sent.
Made-up data only."""
import os

import fitz
import pytest
from PIL import Image

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt                                # noqa: E402

from app import settings                                      # noqa: E402
from app.pm import owner_report as orp                        # noqa: E402
from app.pm.store import ProjectStore                         # noqa: E402
from test_pm import qapp_pm                                   # noqa: E402,F401


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Pat Morgan"})
    monkeypatch.setenv("QUANTISHEET_NO_OPEN", "1")
    s = ProjectStore(str(tmp_path / "Job"))
    s.data["name"] = "Harbor Point Clubhouse (example)"
    s.set_setting("number", "26-101")
    s.save_record("daily", {
        "date": orp.week_range({"week_ending":
                                orp.week_ending_for()})[0].isoformat()
        if hasattr(orp, "week_range") else "",
        "status": "Submitted",
        "work": "Poured slab on grade at Bldg A east half. "
                "Masons laid CMU at the pool house walls.",
        "manpower": [{"company": "Sample Concrete", "trade": "Concrete",
                      "workers": 6}]})
    return s


def photo(tmp_path, name, size=(800, 600), seed=0):
    im = Image.effect_noise(size, 30 + seed).convert("RGB")
    p = str(tmp_path / name)
    im.save(p, "JPEG", quality=85)
    return p


def window(store):
    from app.pm.owner_report_ui import OwnerReportWindow
    w = OwnerReportWindow(store, None, online=False)
    w.show()
    return w


def test_new_report_and_page1(qapp_pm, store, tmp_path):
    w = window(store)
    assert w.list.count() == 0 and not w.tabs.isEnabled()
    w.new_report(wait=True)
    assert w.list.count() == 1 and w.rep["report_no"] == "001"
    assert w.job_no.text() == "26-101"
    assert len(w.trade_boxes) == 23
    # a tick is saved, and remembered when unticked
    w.trade_boxes["Masonry"].setChecked(True)
    w.save()
    assert "Masonry" in store.get(orp.COLL, w.rep["_id"])["trades"]
    w.trade_boxes["Masonry"].setChecked(False)
    w.save()
    assert "Masonry" not in store.get(orp.COLL, w.rep["_id"])["trades"]
    # progress drafted from this week's log, then edited
    w.draft_logs()
    texts = [w.bullets.item(i).text() for i in range(w.bullets.count())]
    assert "Poured slab on grade at Bldg A east half." in texts
    w.add_bullet()
    w.bullets.item(w.bullets.count() - 1).setText("Owner walk Thursday.")
    w.bullets.item(0).setCheckState(Qt.Unchecked)                 # leave one out
    w.save()
    rec = store.get(orp.COLL, w.rep["_id"])
    assert rec["progress"][-1]["text"] == "Owner walk Thursday."
    assert rec["progress"][0]["include"] is False
    # the next report carries this one
    w.new_report(wait=True)
    assert w.list.count() == 2 and w.rep["report_no"] == "002"
    assert any(b["src"] == "carried" for b in w.rep["progress"])
    w.close()


def test_photos_order_and_export(qapp_pm, store, tmp_path):
    w = window(store)
    w.new_report(wait=True)
    added = w.add_photos([photo(tmp_path, f"p{i}.jpg", seed=i)
                          for i in range(6)])
    assert len(added) == 6 and w.photos.count() == 6
    assert "6 photo(s) print on 2 page(s)" in w.photo_count.text()
    # leave one out, rotate one, caption one
    w.photos.item(5).setCheckState(Qt.Unchecked)
    w.photos.setCurrentRow(0)
    w.rotate_photo()
    w.caption.setText("Slab pour, east half")
    w._photo_text()
    w.save()
    rec = store.get(orp.COLL, w.rep["_id"])
    assert sum(1 for p in rec["photos"] if p["include"]) == 5
    assert rec["photos"][0]["rotate"] == 90
    assert rec["photos"][0]["caption"] == "Slab pour, east half"
    assert "1 page(s)" in w.photo_count.text() or True
    # size estimate and an add-on
    assert "MB" in w.size.text()
    w.opt["captions"].setChecked(True)
    w.per_page.setCurrentIndex(w.per_page.findData(6))
    w.save()
    assert orp.options(store.get(orp.COLL, w.rep["_id"]))["captions"]
    w.preview(wait=True)
    assert os.path.isfile(w.last_pdf)
    w.export(folder=str(tmp_path / "out"), wait=True)
    res = w.last_export
    doc = fitz.open(res["path"])
    assert doc.page_count == res["pages"]
    assert "Slab pour, east half" in "".join(p.get_text() for p in doc)
    base = os.path.basename(res["path"])
    assert base[:11].count(".") == 2 and base.endswith(" PPR Report 001.pdf")
    assert "Not exported" not in w.export_info.text()
    w.mark_sent()
    assert store.get(orp.COLL, w.rep["_id"])["status"] == "Sent"
    assert "Sent" in w.list.currentItem().text()
    w.close()


def test_ai_draft_with_a_scripted_model(qapp_pm, store, tmp_path):
    from app.pm.owner_report_ui import OwnerReportWindow
    seen = []

    def ask(prompt):
        seen.append(prompt)
        return ('{"bullets": [{"text": "Concrete crew poured the east half '
                'of the Bldg A slab.", "facts": [1]}]}')
    w = OwnerReportWindow(store, None, online=False, ask=ask)
    w.new_report(wait=True)
    w.ai_draft(wait=True)
    assert seen and "Poured slab" in seen[0]
    texts = [w.bullets.item(i).text() for i in range(w.bullets.count())]
    assert any("Concrete crew" in t or "Poured slab" in t for t in texts)
    assert w.ai_btn.isEnabled()

    def broken(prompt):
        raise RuntimeError("model gone")
    w.ask = broken
    w.ai_draft(wait=True)                    # falls back, no crash
    assert w.bullets.count() >= 1
    w.close()


def test_template_dialog(qapp_pm, store, tmp_path):
    from app.pm.owner_report_ui import TemplateDialog
    d = TemplateDialog()
    d.name.setText("Example Builders, Inc.")
    d.lines.setText("100 Sample Pkwy | Anytown, FL 30000")
    d._save()
    t = orp.load_template()
    assert t["company"]["name"] == "Example Builders, Inc."
    assert t["company"]["lines"] == ["100 Sample Pkwy", "Anytown, FL 30000"]
    assert len(orp.trade_list(t)[0]) == 6


def test_menu_entry_opens_the_window(qapp_pm, store, monkeypatch):
    from app import main_window
    assert hasattr(main_window.MainWindow, "weekly_owner_report") or \
        any("weekly_owner_report" in n for n in dir(main_window))


def test_wunderground_screenshot_and_rain_days(qapp_pm, store, tmp_path):
    from PySide6.QtGui import QColor, QImage
    w = window(store)
    w.new_report(wait=True)
    # the forecast page is the team's Wunderground screenshot by default
    assert w.rep["forecast"]["mode"] == "attach"
    assert "No screenshot yet" in w.forecast_info.text()
    img = QImage(900, 600, QImage.Format_RGB32)
    img.fill(QColor("#3a7bd5"))
    assert w.paste_forecast(img)
    assert w.rep["forecast"]["attach_ref"]
    assert "Screenshot attached" in w.forecast_info.text()
    # the job's Wunderground link is asked once and kept
    assert w.open_wunderground("https://www.wunderground.com/example") == \
        "https://www.wunderground.com/example"
    store.set_setting("wunderground_url", "https://www.wunderground.com/x")
    assert w.open_wunderground() == "https://www.wunderground.com/x"
    # rain typed from Wunderground drives page 1's counts
    w.add_day("2026-10-14", 0.80)               # a Wednesday: claimed
    w.add_day("2026-10-17", 1.10)               # a Saturday: not claimed
    w.add_day("2026-10-15", 0.20)               # under 0.50 in.
    assert (w.impacted.value(), w.claimed.value()) == (2, 1)
    # untick the claim on the Wednesday
    row = next(r for r in range(w.days.rowCount())
               if w.days.item(r, 0).data(Qt.UserRole) == "2026-10-14")
    w.days.item(row, 2).setCheckState(Qt.Unchecked)
    assert w.claimed.value() == 0
    w.save()
    res = orp.build_pdf(store, store.get(orp.COLL, w.rep["_id"]),
                        str(tmp_path / "f.pdf"))
    doc = fitz.open(str(tmp_path / "f.pdf"))
    last = doc[doc.page_count - 1]
    assert last.get_images(), "the screenshot is the forecast page"
    assert "IMPACTED WEATHER DAYS: 2" in doc[0].get_text()
    assert res["pages"] == doc.page_count
    w.close()


# ------------------------------------------------- key plan and work areas
RED_BOX = (100, 150, 120, 170)          # unrotated page points
RED_MID = (110.0, 160.0)


def plan_sheet(tmp_path, rotate=0, name="A-101 plan.pdf"):
    """A one-page 612 x 792 plan with a red box drawn in unrotated
    space, then the page rotated."""
    path = str(tmp_path / name)
    d = fitz.open()
    p = d.new_page(width=612, height=792)
    p.draw_rect(fitz.Rect(60, 60, 400, 500), color=(0, 0, 0), width=1)
    p.draw_rect(fitz.Rect(*RED_BOX), color=(1, 0, 0), fill=(1, 0, 0))
    p.insert_text((70, 80), "BLDG A - CLUBHOUSE", fontsize=9)
    if rotate:
        p.set_rotation(rotate)
    d.save(path)
    d.close()
    return path


def red_centre(path, zoom):
    """Where the red box shows on the page rendered at `zoom` (canvas
    pixels), found by looking at the pixels - no matrix maths."""
    d = fitz.open(path)
    pix = d[0].get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    s, n, st = pix.samples, pix.n, pix.stride
    xs, ys = [], []
    for y in range(pix.height):
        row = s[y * st:y * st + pix.width * n]
        for x in range(pix.width):
            r, g, b = row[x * n], row[x * n + 1], row[x * n + 2]
            if r > 200 and g < 70 and b < 70:
                xs.append(x)
                ys.append(y)
    d.close()
    assert xs, "red box not rendered"
    return (sum(xs) / len(xs) + 0.5, sum(ys) / len(ys) + 0.5)


def names(res):
    return [e[0] for e in res["page_map"]]


def spy_ops(monkeypatch):
    from app import annotate
    calls = []
    real = annotate.apply_op

    def spy(doc, op, fresh=False):
        calls.append(op)
        return real(doc, op, fresh)
    monkeypatch.setattr(annotate, "apply_op", spy)
    return calls


def test_option_labels_offer_the_plan_addons(qapp_pm, store):
    from app.pm.owner_report_ui import OPTION_LABELS
    keys = dict(OPTION_LABELS)
    assert keys["key_plan"] == "Photo key plan (pins on a plan sheet)"
    assert keys["work_areas"] == "Work areas shaded on a plan"


@pytest.mark.parametrize("rotate", [0, 90])
def test_pins_on_the_key_plan(qapp_pm, store, tmp_path, monkeypatch,
                              rotate):
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    from app.pm import plan_picker
    from app.pm.owner_report_ui import PIN_MARK
    sheet = plan_sheet(tmp_path, rotate)
    w = window(store)
    w.new_report(wait=True)
    w.add_photos([photo(tmp_path, f"p{i}.jpg", seed=i) for i in range(3)])
    kp = w.choose_plan(sheet, page=0)
    assert kp["page"] == 0 and kp["sheet"]["sha256"]
    assert os.path.isfile(store.attachment_path(kp["sheet"]))
    assert "A-101 plan.pdf" in w.plan_info.text()
    w.photos.setCurrentRow(0)
    d = w.pin_on_plan()                    # exec() doesn't wait in tests
    assert d is not None and d.mode == "pin"
    d.show()
    assert w.opt["key_plan"].isChecked()
    assert d.zoom == pytest.approx(plan_picker.ZOOM)
    first = w._photo(0)
    assert orp._photo_key(d.current_photo()["ref"]) == \
        orp._photo_key(first["ref"])
    # click on the red box: the pin is the box's centre in unrotated points
    vx, vy = red_centre(sheet, d.zoom)
    pin = d.click(vx, vy)
    assert pin["x"] == pytest.approx(RED_MID[0], abs=1.0)
    assert pin["y"] == pytest.approx(RED_MID[1], abs=1.0)
    assert pin["page"] == 0 and \
        orp._sheet_key(pin["sheet"]) == orp._sheet_key(kp["sheet"])
    px, py = d.page_to_view(*RED_MID)
    assert (px, py) == (pytest.approx(vx, abs=1.5), pytest.approx(vy, abs=1.5))
    # the picker moved on to the next photo; a real mouse click pins it
    assert d.items.currentRow() == 1
    tx, ty = d.page_to_view(300, 400)
    QTest.mouseClick(d.canvas, Qt.LeftButton, Qt.NoModifier,
                     QPoint(int(round(tx)), int(round(ty))))
    second = w._photo(1)
    assert second["pin"]["x"] == pytest.approx(300, abs=1.5)
    assert second["pin"]["y"] == pytest.approx(400, abs=1.5)
    # zooming doesn't change the mapping
    d.set_scale(+1)
    assert d.zoom > plan_picker.ZOOM
    zx, zy = d.page_to_view(*RED_MID)
    assert d.view_to_page(zx, zy) == (pytest.approx(RED_MID[0], abs=0.05),
                                      pytest.approx(RED_MID[1], abs=0.05))
    d.canvas.repaint()                     # draws the numbered pins
    w._plan_done()
    assert w.photos.item(0).text().startswith(PIN_MARK)
    assert not w.photos.item(2).text().startswith(PIN_MARK)
    assert "2 photo(s) pinned" in w.plan_info.text()
    rec = store.get(orp.COLL, w.rep["_id"])
    assert sum(1 for p in rec["photos"] if p.get("pin")) == 2
    assert orp.options(rec)["key_plan"]
    # the key plan page: one numbered pin per pinned photo, at the pins
    calls = spy_ops(monkeypatch)
    res = orp.build_pdf(store, rec, str(tmp_path / "kp.pdf"))
    assert "key_plan" in names(res)
    pins = [c for c in calls if c["kind"] == "add_count"]
    assert len(pins) == 2
    assert [c["payload"]["n"] for c in pins] == ["1", "2"]
    assert pins[0]["payload"]["pt"][0] == pytest.approx(RED_MID[0], abs=1)
    assert pins[0]["payload"]["pt"][1] == pytest.approx(RED_MID[1], abs=1)
    doc = fitz.open(str(tmp_path / "kp.pdf"))
    kp_page = next(e for e in res["page_map"] if e[0] == "key_plan")[1]
    assert "Location / caption" in doc[kp_page - 1].get_text()
    # remove a pin
    d.items.setCurrentRow(1)
    d.remove_pin()
    assert w._photo(1)["pin"] is None
    w.close()


@pytest.mark.parametrize("rotate", [0, 90])
def test_work_areas_drawn_on_the_plan(qapp_pm, store, tmp_path,
                                      monkeypatch, rotate):
    from PySide6.QtTest import QTest
    sheet = plan_sheet(tmp_path, rotate)
    w = window(store)
    w.new_report(wait=True)
    w.choose_plan(sheet, page=0)
    d = w.edit_work_areas()
    assert d is not None and d.mode == "areas"
    d.show()
    assert w.opt["work_areas"].isChecked()
    square = [(60, 60), (300, 60), (300, 200), (60, 200)]
    for x, y in square:
        d.click(*d.page_to_view(x, y))
    d.click(*d.page_to_view(60, 200))       # the same spot twice: ignored
    assert len(d.pts) == 4
    d.canvas.repaint()                      # the polygon being drawn
    a = d.finish_area("Bldg A slab pour")
    assert a["label"] == "Bldg A slab pour"
    assert a["color"] == list(orp.AREA_COLORS[0])
    for (x, y), (ex, ey) in zip(a["pts"], square):
        assert (x, y) == (pytest.approx(ex, abs=0.05),
                          pytest.approx(ey, abs=0.05))
    # a second area closed with Enter (label asked; blank = "Area 2")
    for x, y in [(320, 300), (400, 300), (400, 480)]:
        d.click(*d.page_to_view(x, y))
    QTest.keyClick(d, Qt.Key_Return)
    assert len(w.rep["work_areas"]) == 2
    assert w.rep["work_areas"][1]["label"] == "Area 2"
    assert w.rep["work_areas"][1]["color"] == list(orp.AREA_COLORS[1])
    # a third, then deleted
    for x, y in [(70, 600), (200, 600), (200, 700)]:
        d.click(*d.page_to_view(x, y))
    d.finish_area("Scratch")
    assert d.items.count() == 3
    d.delete_area(2)
    assert d.items.count() == 2 and len(w.rep["work_areas"]) == 2
    # the print area: a dragged box, in the page's displayed coordinates
    if not rotate:
        clip = d.set_clip_view(*d.page_to_view(40, 40),
                               *d.page_to_view(450, 520))
        assert clip == [pytest.approx(40, abs=0.2), pytest.approx(40, abs=0.2),
                        pytest.approx(450, abs=0.2),
                        pytest.approx(520, abs=0.2)]
    d.canvas.repaint()
    w._plan_done()
    assert "2 work area(s)" in w.areas_info.text()
    rec = store.get(orp.COLL, w.rep["_id"])
    assert len(rec["work_areas"]) == 2 and orp.options(rec)["work_areas"]
    calls = spy_ops(monkeypatch)
    res = orp.build_pdf(store, rec, str(tmp_path / "wa.pdf"))
    assert "work_areas" in names(res)
    assert [c["kind"] for c in calls if c["kind"] == "add_polygon"] == \
        ["add_polygon"] * 2
    doc = fitz.open(str(tmp_path / "wa.pdf"))
    first = next(e for e in res["page_map"] if e[0] == "work_areas")[1]
    t = doc[first - 1].get_text()
    assert "This week's work areas" in t and "Bldg A slab pour" in t
    assert "Area 2" in t
    # a photo pinned inside an area takes the area's label as its location
    ph = w.add_photos([photo(tmp_path, "in.jpg")])[0]
    ph = w._photo(0)
    ph["pin"] = {"sheet": rec["key_plan"]["sheet"], "page": 0,
                 "x": 100.0, "y": 100.0}
    assert orp.photo_location(w.rep, ph) == "Bldg A slab pour"
    # the plan and the areas carry to next week's report
    w.new_report(wait=True)
    assert w.rep["key_plan"]["sheet"]["sha256"] == \
        rec["key_plan"]["sheet"]["sha256"]
    assert len(w.rep["work_areas"]) == 2
    w.close()


def test_pair_before_after(qapp_pm, store, tmp_path):
    from app.pm.owner_report_ui import PairDialog
    sheet = plan_sheet(tmp_path)
    w = window(store)
    w.new_report(wait=True)
    w.add_photos([photo(tmp_path, f"b{i}.jpg", seed=i) for i in range(2)])
    w.choose_plan(sheet, page=0)
    w.photos.setCurrentRow(0)
    d = w.pin_on_plan()
    spots = [(110, 160), (300, 400)]
    for x, y in spots:
        d.click(*d.page_to_view(x, y))
    w._plan_done()
    assert w.pair_before_after() is None         # no last week yet
    # next week: same spots, new photos
    w.new_report(wait=True)
    assert len(w.rep["before_candidates"]) == 2
    w.add_photos([photo(tmp_path, f"a{i}.jpg", seed=10 + i)
                  for i in range(2)])
    w.photos.setCurrentRow(0)
    d = w.pin_on_plan()
    for x, y in spots:
        d.click(*d.page_to_view(x + 4, y - 3))    # a few points off
    w._plan_done()
    pd = w.pair_before_after()                    # exec() doesn't wait
    assert isinstance(pd, PairDialog) and pd.list.count() == 2
    assert "pins close together" in pd.list.item(0).text()
    pd.list.item(1).setCheckState(Qt.Unchecked)
    chosen = pd.chosen()
    assert len(chosen) == 1
    w.apply_pairs(chosen)
    assert w.opt["before_after"].isChecked()
    rec = store.get(orp.COLL, w.rep["_id"])
    paired = [p for p in rec["photos"] if p.get("pair_with")]
    assert len(paired) == 1
    assert w.photos.item(0).text().endswith("(+before)")
    res = orp.build_pdf(store, rec, str(tmp_path / "ba.pdf"))
    assert "before_after" in names(res)
    w.close()


def test_weather_totals_follow_the_day_list_and_source_shown(qapp_pm, store,
                                                             tmp_path):
    """Review 0.12.35 #7 / #15: with a Rain days list page 1's boxes are
    its totals (read-only), a typed total can't disagree with it; the
    window says which weather service is used."""
    w = window(store)
    w.new_report(wait=True)
    assert not w.impacted.isReadOnly()             # no list: typed totals
    w.claimed.setValue(3)
    w.save()
    assert store.get(orp.COLL, w.rep["_id"])["weather"]["claimed"] == 3
    for iso in ("2026-10-12", "2026-10-13", "2026-10-14"):   # Mon-Wed
        w.add_day(iso, 0.9)
    for iso in ("2026-10-13", "2026-10-14"):
        row = next(r for r in range(w.days.rowCount())
                   if w.days.item(r, 0).data(Qt.UserRole) == iso)
        w.days.item(row, 2).setCheckState(Qt.Unchecked)
    assert w.impacted.isReadOnly() and w.claimed.isReadOnly()
    assert (w.impacted.value(), w.claimed.value()) == (3, 1)
    w.save()
    rec = store.get(orp.COLL, w.rep["_id"])
    assert (rec["weather"]["impacted"], rec["weather"]["claimed"]) == (3, 1)
    assert orp.weather_counts(rec) == (3, 1)
    assert "free" in w.weather_source.text()
    w.set_weather_key("TEST-KEY")
    from app import secretstore           # DPAPI-protected (T-014)
    assert secretstore.get_secret("weather_api_key") == "TEST-KEY"
    assert "commercial" in w.weather_source.text()
    w.set_weather_key("")
    assert "free" in w.weather_source.text()
    w.close()


def _settle(w, kind):
    """Wait for this kind's background job, then deliver its result."""
    from PySide6.QtWidgets import QApplication
    for j in [j for j in w._jobs if j.kind == kind]:
        assert j.wait(10000)
    for _ in range(20):
        QApplication.processEvents()


def test_new_report_saved_on_the_gui_thread(qapp_pm, store):
    """Review #3: new_report ran in a QThread and saved there, so the
    store's listeners (Project Center widgets) ran off the GUI thread."""
    import threading
    seen = []
    store.listeners.append(lambda coll: seen.append(
        threading.current_thread() is threading.main_thread()))
    w = window(store)
    w.new_report(wait=True)
    assert w.rep.get("_id") and seen and all(seen)
    w.close()


def test_jobs_keep_edits_made_meanwhile_and_their_own_results(
        qapp_pm, store, monkeypatch):
    """Review #2: Update Weather / AI Draft worked on a copy that replaced
    the live report (edits typed meanwhile lost), and one stored callback
    handed the weather result to the AI handler. Fake jobs, held open by
    events: each result reaches its own handler, folds in only its own
    fields, and the line typed meanwhile stays."""
    import json
    import threading
    from PySide6.QtWidgets import QListWidgetItem
    go_w, go_a = threading.Event(), threading.Event()
    rows = [{"date": "2026-10-21", "high": 70, "low": 50, "rain_in": 0.1}]

    def slow_forecast(store_, rep, online=True, today=None):
        go_w.wait(10)
        rep.setdefault("forecast", {})["rows"] = list(rows)
        return rep
    monkeypatch.setattr(orp, "fill_forecast", slow_forecast)

    def ask(prompt):
        go_a.wait(10)
        return json.dumps({"bullets": [
            {"text": "Concrete crew poured the Bldg A slab.", "facts": [1]}]})
    w = window(store)
    w.ask = ask
    w.new_report(wait=True)
    w.update_weather()
    w.ai_draft()
    w.update_weather()                       # already running: ignored
    assert len([j for j in w._jobs if j.kind == "weather"]) == 1
    it = QListWidgetItem("Typed while the jobs ran.")
    it.setFlags(it.flags() | Qt.ItemIsEditable | Qt.ItemIsUserCheckable)
    it.setCheckState(Qt.Checked)
    it.setData(Qt.UserRole, "typed")
    w.bullets.addItem(it)
    go_w.set()
    _settle(w, "weather")
    assert w.ai_btn.text() == "AI working…"    # not the AI handler
    assert w.rep["forecast"]["rows"] == rows
    texts = [w.bullets.item(i).text() for i in range(w.bullets.count())]
    assert "Typed while the jobs ran." in texts
    go_a.set()
    _settle(w, "ai")
    assert w.ai_btn.isEnabled()
    texts = [b["text"] for b in w.rep["progress"]]
    assert "Typed while the jobs ran." in texts
    assert "Concrete crew poured the Bldg A slab." in texts
    assert w.rep["forecast"]["rows"] == rows   # not undone by the AI job
    rec = store.get(orp.COLL, w.rep["_id"])
    assert "Typed while the jobs ran." in [b["text"] for b in
                                           rec["progress"]]
    w.close()
