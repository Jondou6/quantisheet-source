"""Aerial Photo Page: free USGS photo by address, or a photo file with a
world file, as a new page scaled to real feet."""
import math
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import aerial, aerial_ui, annotate, settings         # noqa: E402


@pytest.fixture(autouse=True)
def _cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Test"})
    monkeypatch.setattr(aerial_ui, "_GEOCODED", {})    # no lookups kept


def _png(w, h, rgb=(100, 110, 120)):
    import io
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (w, h), rgb).save(out, "PNG")
    return out.getvalue()


def test_bbox_covers_the_ground_asked_for():
    x0, y0, x1, y1 = aerial.naip_bbox(33.66, -79.10, 1000, 750)
    k = math.cos(math.radians(33.66)) / 0.3048
    assert (x1 - x0) * k == pytest.approx(1000)
    assert (y1 - y0) * k == pytest.approx(750)


def test_lat_lon_typed_directly_needs_no_lookup():
    lat, lon, _ = aerial.geocode("33.6577, -79.1037")
    assert (lat, lon) == (33.6577, -79.1037)


def test_census_geocoder_answer_is_read(monkeypatch):
    body = (b'{"result": {"addressMatches": [{"matchedAddress": '
            b'"1 MAIN ST, CONWAY, SC, 29526", "coordinates": '
            b'{"x": -79.05, "y": 33.83}}]}}')
    monkeypatch.setattr(aerial, "_get", lambda *a, **k: (body, "json"))
    lat, lon, m = aerial.geocode("1 Main St, Conway SC")
    assert (lat, lon) == (33.83, -79.05) and "CONWAY" in m
    monkeypatch.setattr(aerial, "_get", lambda *a, **k: (
        b'{"result": {"addressMatches": []}}', "json"))
    with pytest.raises(LookupError):
        aerial.geocode("nowhere at all")


def test_usgs_photo_page_measures_real_feet(monkeypatch):
    seen = {}

    def fake_get(url, params, timeout=60):
        seen.update(params)
        w, h = (int(v) for v in params["size"].split(","))
        return _png(w, h), "image/png"
    monkeypatch.setattr(aerial, "_get", fake_get)
    doc = aerial.aerial_document(aerial.NAIPSource(width_ft=1000), 33.66,
                                 -79.10)
    sc = annotate.read_scales(doc)[0]
    w_px = int(seen["size"].split(",")[0])
    # the photo spans 1,000 ft across
    assert doc[0].rect.width / sc["ppu"] == pytest.approx(1000, rel=1e-3)
    # stored at 1 ft per pixel, smoothly enlarged, and labeled as such
    assert w_px == 1000 and "NAIP" in doc[0].get_text()
    assert seen["interpolation"] == "RSP_BilinearInterpolation"
    assert "about 2 ft/px" in doc[0].get_text()


def test_service_error_is_reported(monkeypatch):
    monkeypatch.setattr(aerial, "_get", lambda *a, **k: (
        b'{"error": {"message": "Invalid bbox"}}', "text/plain"))
    with pytest.raises(RuntimeError, match="Invalid bbox"):
        aerial.NAIPSource().fetch(33.6, -79.1, 0, 0, 0)


def test_photo_file_with_world_file(tmp_path):
    p = tmp_path / "site.png"
    p.write_bytes(_png(400, 300))
    (tmp_path / "site.pgw").write_text("0.25\n0\n0\n-0.25\n2700000\n800000\n")
    assert aerial.world_file_pixel(str(p)) == 0.25
    data, title, _ = aerial_ui._work("file", (str(p), 0.25))
    doc = fitz.open("pdf", data)
    sc = annotate.read_scales(doc)[0]
    assert (doc[0].rect.width / sc["ppu"]) == pytest.approx(100, rel=1e-3)
    assert title == "Aerial - site.png"


def test_menu_entry_and_dialog(qapp, win):
    acts = [a.text() for a in win.findChildren(type(win.menuBar().actions()
                                                     [0]))]
    assert "Aerial Photo Page…" in acts
    dlg = aerial_ui.AerialDialog(win)
    dlg.address.setText("33.6577, -79.1037")
    for cb in dlg.layer_boxes.values():
        cb.setChecked(False)
    assert dlg.source() == ("naip", ("33.6577, -79.1037", 1000, []))
    dlg.tabs.setCurrentIndex(1)
    dlg.path.setText("x.png")
    dlg.size.setValue(0.3048)
    dlg.unit.setCurrentIndex(1)                       # meters
    assert dlg.source()[1][1] == pytest.approx(1.0)


from test_gui import win, qapp                        # noqa: E402,F401


def _cover(doc, lines, at=(60, 80)):
    p = doc.new_page(width=1224, height=792)
    y = at[1]
    for s in lines:
        p.insert_text((at[0], y), s, fontsize=10)
        y += 14
    return p


def _title_block(page):
    page.insert_text((1000, 700), "HAZEN AND SAWYER", fontsize=8)
    page.insert_text((1000, 712), "4287 SPRUILL AVENUE, SUITE 101", fontsize=8)
    page.insert_text((1000, 724), "NORTH CHARLESTON, SC 29405", fontsize=8)


def test_site_address_from_the_cover_not_the_title_block():
    d = fitz.open()
    p = _cover(d, ["PROJECT LOCATION", "8051 TREATMENT PLANT RD",
                   "BUCKSPORT, SC 29527"])
    _title_block(p)
    for _ in range(4):
        _title_block(d.new_page(width=1224, height=792))
    site = aerial.find_site(d)
    assert site["query"] == "8051 TREATMENT PLANT RD, BUCKSPORT, SC 29527"
    assert site["page"] == 0 and site["kind"] == "address"


def test_printed_latitude_longitude_wins():
    d = fitz.open()
    p = _cover(d, ["PROJECT LOCATION", "8051 TREATMENT PLANT RD",
                   "BUCKSPORT, SC 29527",
                   "LAT 33.657712, LONG -79.103650"])
    site = aerial.find_site(d)
    assert site["kind"] == "latlon" and site["query"] == \
        "33.657712, -79.103650"
    assert aerial._lat_lon_in("N 33°39'27.8\" W 79°06'13.1\"") \
        == pytest.approx((33.65772, -79.10364), abs=1e-4)
    assert aerial._lat_lon_in("ELEV 23.250 / 17.500") is None


def test_nothing_found_on_a_set_without_a_site():
    d = fitz.open()
    for _ in range(3):
        _title_block(d.new_page(width=1224, height=792))
    assert aerial.find_site(d) is None


def test_dialog_fills_the_site_from_the_open_set(qapp, win, tmp_path):
    d = fitz.open()
    _cover(d, ["PROJECT LOCATION", "8051 TREATMENT PLANT RD",
               "BUCKSPORT, SC 29527"])
    path = str(tmp_path / "plans.pdf")
    d.save(path)
    win.open_path(path)
    dlg = aerial_ui.AerialDialog(win)
    assert dlg.address.text() == \
        "8051 TREATMENT PLANT RD, BUCKSPORT, SC 29527"
    assert "From the plans" in dlg.site_note.text()


def test_shift_moves_the_right_distance():
    lat, lon = aerial_ui.shifted(33.65, -79.12, east_ft=1000, north_ft=500)
    # back to feet
    assert (lat - 33.65) * aerial_ui.FT_PER_DEG_LAT == pytest.approx(500)
    assert (lon + 79.12) * aerial_ui.FT_PER_DEG_LAT * math.cos(
        math.radians(33.65)) == pytest.approx(1000)


GEO = (b'{"result": {"addressMatches": [{"matchedAddress": '
       b'"8051 TREATMENT RD, BUCKSPORT, SC", "coordinates": '
       b'{"x": -79.1192, "y": 33.6504}}]}}')


def _fake(calls, delay=0.0, tiles=False):
    import time

    def fake_get(url, params, timeout=60):
        if "geocod" in url:
            return GEO, "json"
        if url.endswith("/export"):               # a site layer
            calls.append("layer")
            w, h = (int(v) for v in params["size"].split(","))
            return _png(w, h, (200, 0, 0)), "image/png"
        if "/tile/" in url:
            calls.append("tile")
            if not tiles:
                raise OSError("no tiles in tests")
            return _png(256, 256), "image/png"
        calls.append(dict(params))
        time.sleep(delay)
        w, h = (int(v) for v in params["size"].split(","))
        return _png(w, h), "image/png"
    return fake_get


def _photo_calls(calls):
    return [c for c in calls if c not in ("tile", "layer")]


def test_preview_then_move_onto_the_site(qapp, win, monkeypatch):
    calls = []
    monkeypatch.setattr(aerial, "_get", _fake(calls))
    dlg = aerial_ui.AerialDialog(win)
    dlg.address.setText("8051 Treatment Plant Rd, Bucksport SC")
    dlg.do_preview(wait=True)
    assert dlg.center[:2] == (33.6504, -79.1192)
    assert len(_photo_calls(calls)) == 1
    # one photo 3x the chosen width, at 1 ft per pixel
    assert int(_photo_calls(calls)[0]["size"].split(",")[0]) == 3000
    assert dlg.preview.has_image()
    dlg.move(1, 0, wait=True)                       # a third of 1,000 ft east
    assert dlg.center[1] > -79.1192
    assert dlg.center[0] == pytest.approx(33.6504, abs=1e-9)
    dlg.zoom(2.0, wait=True)                        # 2,000 ft: leaves it
    kind, args = dlg.source()
    assert kind == "naip_crop" and args[3] == 2000
    data, title, _ = aerial_ui._work(kind, args)
    doc = fitz.open("pdf", data)
    sc = annotate.read_scales(doc)[0]
    assert doc[0].rect.width / sc["ppu"] == pytest.approx(2000, rel=2e-3)
    dlg.address.textEdited.emit("somewhere else")   # typing starts over
    assert dlg.center is None


def test_arrows_wider_closer_and_ok_download_nothing_more(qapp, win,
                                                          monkeypatch):
    """Venice A1/A2: one Preview, then moving, zooming and OK make no new
    USGS photo requests while the box stays in the photo."""
    import time
    calls = []
    monkeypatch.setattr(aerial, "_get", _fake(calls))
    dlg = aerial_ui.AerialDialog(win)
    dlg.address.setText("33.6504, -79.1192")
    dlg.do_preview(wait=True)
    assert len(_photo_calls(calls)) == 1
    for dx, dy in ((0, 1), (1, 0), (0, -1), (-1, 0)):
        t = time.perf_counter()
        dlg.move(dx, dy, wait=True)
        assert time.perf_counter() - t < 0.5
    dlg.zoom(0.5, wait=True)                        # Closer
    dlg.zoom(2.0, wait=True)                        # back to Wider
    kind, args = dlg.source()
    assert kind == "naip_crop"
    data, _t, _m = aerial_ui._work(kind, args)
    assert len(_photo_calls(calls)) == 1            # still just the one
    doc = fitz.open("pdf", data)
    sc = annotate.read_scales(doc)[0]
    assert doc[0].rect.width / sc["ppu"] == pytest.approx(1000, rel=2e-3)
    # walking off the photo fetches exactly one more
    for _ in range(4):
        dlg.move(1, 0, wait=True)
    assert len(_photo_calls(calls)) == 2


def test_a_late_answer_never_replaces_a_newer_one(qapp, win, monkeypatch):
    """Venice A3: two downloads out at once, answering in the wrong
    order - only the newest one's photo is kept."""
    from app import bg
    calls = []
    monkeypatch.setattr(aerial, "_get", _fake(calls))
    dlg = aerial_ui.AerialDialog(win)
    dlg.address.setText("33.6504, -79.1192")
    dlg.do_preview(wait=True)
    jobs = []
    monkeypatch.setattr(bg, "run", lambda fn, done, failed, owner,
                        pool=None: jobs.append((fn, done)))
    dlg.move(1, 0)                         # east (inside the photo)
    dlg._fetch(force=True)                 # request 1
    dlg.move(0, 1)                         # north
    dlg._fetch(force=True)                 # request 2
    assert len(jobs) == 2 and dlg.cancel_btn.isVisibleTo(dlg)
    second = jobs[1][0]()
    first = jobs[0][0]()
    jobs[1][1](second)                     # the newer answer lands first
    jobs[0][1](first)                      # then the old one, late
    assert dlg.photo is second
    e, n = dlg.preview.center_ft()
    assert e == pytest.approx(1000 / 3) and n == pytest.approx(1000 / 3)
    dlg._fetch(force=True)
    dlg.cancel_fetch()                     # Cancel: its answer is ignored
    jobs[2][1](jobs[2][0]())
    assert dlg.photo is second and dlg.status.text() == ""


def test_preview_zooms_with_the_wheel_and_drags(qapp, win, monkeypatch):
    """Venice A4: the preview zooms and pans without downloading."""
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    calls = []
    monkeypatch.setattr(aerial, "_get", _fake(calls))
    dlg = aerial_ui.AerialDialog(win)
    dlg.show()
    dlg.address.setText("33.6504, -79.1192")
    dlg.do_preview(wait=True)
    v = dlg.preview
    z0 = v.zoom_factor()
    pos = QPointF(v.viewport().rect().center())
    ev = QWheelEvent(pos, v.mapToGlobal(pos.toPoint()), QPoint(0, 0),
                     QPoint(0, 240), Qt.NoButton, Qt.NoModifier,
                     Qt.NoScrollPhase, False)
    v.wheelEvent(ev)
    assert v.zoom_factor() == pytest.approx(z0 * 1.5625, rel=1e-3)
    e0, n0 = v.center_ft()
    from PySide6.QtTest import QTest
    c = v.viewport().rect().center()
    QTest.mousePress(v.viewport(), Qt.LeftButton, Qt.NoModifier, c)
    QTest.mouseMove(v.viewport(), c + QPoint(-60, 0))
    QTest.mouseMove(v.viewport(), c + QPoint(-120, 0))
    QTest.mouseRelease(v.viewport(), Qt.LeftButton, Qt.NoModifier,
                       c + QPoint(-120, 0))
    e1, n1 = v.center_ft()
    assert e1 > e0 + 1                  # dragged left: the box moved east
    assert dlg.center[1] > -79.1192
    assert len(_photo_calls(calls)) == 1
    dlg.close()


def test_ok_puts_the_page_after_the_current_sheet(qapp, win, monkeypatch,
                                                  tmp_path):
    """Jon, Oct 19: the aerial page goes into the open set."""
    d = fitz.open()
    for _ in range(3):
        d.new_page(width=1224, height=792)
    path = str(tmp_path / "plans.pdf")
    d.save(path)
    win.open_path(path)
    win._view.go_to(1)
    calls = []
    monkeypatch.setattr(aerial, "_get", _fake(calls))
    dlg = aerial_ui.AerialDialog(win)
    dlg.address.setText("33.6504, -79.1192")
    dlg.do_preview(wait=True)
    data, title, _ = aerial_ui._work(*dlg.source())
    assert aerial_ui.add_to_set(win, data, title) == "set"
    doc = win._view.doc
    assert doc.page_count == 4 and win._view.page == 2
    sc = annotate.read_scales(doc)
    assert 2 in sc and doc[2].rect.width / sc[2]["ppu"] == \
        pytest.approx(1000, rel=2e-3)


def test_photo_cache_on_disk(monkeypatch):
    """Venice A7: the same view again comes from the disk cache."""
    calls = []
    monkeypatch.setattr(aerial, "_get", _fake(calls))
    src = aerial.NAIPSource(width_ft=1000)
    a, _ = src.fetch(33.65, -79.12, 0, 0, 0)
    b, _ = src.fetch(33.65, -79.12, 0, 0, 0)
    assert a == b and len(_photo_calls(calls)) == 1
    assert os.path.isdir(aerial._cache_dir())


def test_quick_overview_from_tiles(monkeypatch):
    calls = []
    monkeypatch.setattr(aerial, "_get", _fake(calls, tiles=True))
    data, top_lat, left_lon, fpp = aerial.overview(33.65, -79.12, 3000)
    assert calls.count("tile") == 35 and data[:2] == b"\xff\xd8"
    assert top_lat > 33.65 and left_lon < -79.12 and 1 < fpp < 20
    monkeypatch.setattr(aerial, "_get", _fake([], tiles=False))
    assert aerial.overview(33.65, -79.12, 3000) is None   # quietly none


def test_dialog_fits_on_the_screen(qapp, win):
    """Jon, Oct 19: the dialog grew taller than the screen."""
    dlg = aerial_ui.AerialDialog(win)
    dlg.show()
    qapp.processEvents()
    av = dlg.screen().availableGeometry()
    assert dlg.frameGeometry().height() <= av.height()
    assert av.contains(dlg.frameGeometry().topLeft())
    assert dlg.preview.sizeHint().height() < 600
    dlg.close()


def test_site_layers_go_on_as_switchable_pdf_layers(qapp, win, monkeypatch):
    """Venice, Oct 19: flood zones, wetlands and contours over the photo,
    each its own PDF layer, lined up with the photo."""
    calls = []
    monkeypatch.setattr(aerial, "_get", _fake(calls))
    dlg = aerial_ui.AerialDialog(win)
    dlg.address.setText("33.6504, -79.1192")
    dlg.do_preview(wait=True)
    for key, cb in dlg.layer_boxes.items():
        cb.setChecked(key in ("flood", "contours"))
    kind, args = dlg.source()
    assert args[-1] == ["flood", "contours"]
    data, _t, _m = aerial_ui._work(kind, args)
    assert calls.count("layer") == 2
    doc = fitz.open("pdf", data)
    names = {v["name"] for v in doc.get_ocgs().values()}
    assert names == {"Flood zones", "Contours"}
    assert "Site layers" in doc[0].get_text()
    sc = annotate.read_scales(doc)[0]           # the scale is unchanged
    assert doc[0].rect.width / sc["ppu"] == pytest.approx(1000, rel=2e-3)
    # a service that doesn't answer: the page is still made, and says so
    monkeypatch.setattr(aerial, "site_layer", lambda *a, **k: None)
    data, _t, _m = aerial_ui._work(kind, args)
    doc = fitz.open("pdf", data)
    assert not doc.get_ocgs() and "not available" in doc[0].get_text()


def test_ok_puts_the_photo_in(qapp, win, monkeypatch):
    """Jon, Oct 20: preview worked, OK closed the box and nothing came in.
    Closing the progress box emits canceled(), which made every finished
    photo look cancelled."""
    from PySide6.QtWidgets import QDialog
    from app import bg

    class Dlg:
        def __init__(self, mw):
            pass

        def exec(self):
            return QDialog.Accepted

        def source(self):
            return "file", ("x.png", 1.0)

    added = []
    monkeypatch.setattr(aerial_ui, "AerialDialog", Dlg)
    monkeypatch.setattr(aerial_ui, "_work",
                        lambda kind, args: (b"%PDF", "Aerial - test", "Site"))
    monkeypatch.setattr(aerial_ui, "add_to_set",
                        lambda mw, data, title, **k: added.append(title))

    def run(work, done, failed, parent=None, pool=None):
        from PySide6.QtWidgets import QApplication, QProgressDialog
        for w in QApplication.topLevelWidgets():   # the box is up by now
            if isinstance(w, QProgressDialog):
                w.show()
        done(work())
    monkeypatch.setattr(bg, "run", run)
    aerial_ui.new_aerial_page(win)
    assert added == ["Aerial - test"]


def test_progress_box_does_not_come_back_after_a_quick_photo(qapp, win,
                                                             monkeypatch):
    """A crop finished before the box's 400 ms delay; the box then showed
    itself anyway and spun forever (Jon, Oct 20)."""
    import time
    from PySide6.QtWidgets import QApplication, QDialog, QProgressDialog
    from app import bg

    class Dlg:
        def __init__(self, mw):
            pass

        def exec(self):
            return QDialog.Accepted

        def source(self):
            return "naip_crop", ({}, (0, 0), (0, 0, "x"), 100, [])

    monkeypatch.setattr(aerial_ui, "AerialDialog", Dlg)
    monkeypatch.setattr(aerial_ui, "_work",
                        lambda kind, args: (b"%PDF", "Aerial - t", ""))
    monkeypatch.setattr(aerial_ui, "add_to_set", lambda mw, d, t, **k: "set")
    monkeypatch.setattr(bg, "run", lambda work, done, failed, parent=None,
                        pool=None: done(work()))
    aerial_ui.new_aerial_page(win)
    end = time.monotonic() + 1.0             # past the 400 ms delay
    while time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.02)
    assert not [w for w in QApplication.topLevelWidgets()
                if isinstance(w, QProgressDialog) and w.isVisible()]


# ---- real threads, real progress box (Oct 20 review, measured on 0.12.29)
# These use the real bg.run, the aerial pools and QProgressDialog, with a
# slow fake USGS (offline) - nothing is mocked between OK and the page.
import threading                                       # noqa: E402
import time                                            # noqa: E402


def _wait_for(cond, timeout=5.0):
    """Run the event loop until cond() or the timeout (no pytest-qt here)."""
    from PySide6.QtWidgets import QApplication
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QApplication.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    QApplication.processEvents()
    return bool(cond())


def _nap(s):
    """A slow server that still hears Cancel / the deadline."""
    end = time.monotonic() + s
    while time.monotonic() < end:
        aerial.check()
        time.sleep(0.01)


def _slow_fake(log, photo_s=0.3, geo_s=0.0, tile_s=None):
    def fake_get(url, params, timeout=60):
        if "geocod" in url:
            log.append("geocode")
            _nap(geo_s)
            return GEO, "json"
        if "/tile/" in url:
            if tile_s is None:
                raise OSError("no tiles in tests")
            _nap(tile_s)
            return _png(256, 256), "image/png"
        if url.endswith("/export"):
            raise OSError("no layers in tests")
        assert url == aerial.NAIP_URL
        log.append("exportImage")
        _nap(photo_s)
        w, h = (int(v) for v in params["size"].split(","))
        return _png(w, h), "image/png"
    return fake_get


def _silent_usgs(monkeypatch):
    """The real aerial._get against a server that never answers."""
    import urllib.request
    gate = threading.Event()

    def urlopen(req, timeout=None):
        gate.wait(10)
        raise OSError("let go")
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    return gate


def _warnings(monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    got = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(
        lambda *a, **k: got.append(a[2] if len(a) > 2 else "") or 0))
    return got


def _ok_on(monkeypatch, dlg):
    """new_aerial_page uses this dialog, and its OK is clicked at once."""
    from PySide6.QtWidgets import QDialog
    for cb in dlg.layer_boxes.values():
        cb.setChecked(False)
    monkeypatch.setattr(dlg, "exec", lambda: QDialog.Accepted)
    monkeypatch.setattr(aerial_ui, "AerialDialog", lambda mw: dlg)


def _progress_boxes():
    from PySide6.QtWidgets import QApplication, QProgressDialog
    return [w for w in QApplication.topLevelWidgets()
            if isinstance(w, QProgressDialog) and w.isVisible()]


def _measures(doc, pno):
    sc = annotate.read_scales(doc)
    return doc[pno].rect.width / sc[pno]["ppu"]


def _second_set(win, tmp_path):
    d = fitz.open()
    for _ in range(3):
        d.new_page(width=1224, height=792)
    path = str(tmp_path / "plans.pdf")
    d.save(path)
    win.open_path(path)
    win._view.go_to(1)
    return win._view


def test_real_preview_then_ok_adds_the_page(qapp, win, monkeypatch):
    log = []
    monkeypatch.setattr(aerial, "_get", _slow_fake(log, photo_s=0.2))
    warned = _warnings(monkeypatch)
    view = win._view
    n0, at = view.doc.page_count, view.page
    dlg = aerial_ui.AerialDialog(win)
    dlg.address.setText("8051 Treatment Plant Rd, Bucksport SC")
    dlg.do_preview()
    assert _wait_for(lambda: dlg.photo is not None)
    _ok_on(monkeypatch, dlg)
    aerial_ui.new_aerial_page(win)
    assert _wait_for(lambda: view.doc.page_count == n0 + 1), warned
    assert log.count("exportImage") == 1 and log.count("geocode") == 1
    assert _measures(view.doc, at + 1) == pytest.approx(1000, rel=2e-3)
    assert not warned
    assert _wait_for(lambda: not _progress_boxes(), 1.5)


def test_ok_during_the_download_uses_that_download(qapp, win, monkeypatch):
    """0.12.29: OK during Preview's download started a second one (60 s).
    Now OK closes the dialog, waits for the one under way and crops it."""
    log = []
    monkeypatch.setattr(aerial, "_get", _slow_fake(log, photo_s=0.8))
    warned = _warnings(monkeypatch)
    view = win._view
    n0, at = view.doc.page_count, view.page
    dlg = aerial_ui.AerialDialog(win)
    dlg.address.setText("8051 Treatment Plant Rd, Bucksport SC")
    dlg.do_preview()
    assert _wait_for(lambda: dlg._inflight is not None)
    assert dlg.photo is None
    _ok_on(monkeypatch, dlg)
    t = time.monotonic()
    aerial_ui.new_aerial_page(win)
    boxes = _progress_boxes()                    # at once, not after 4 s
    assert boxes and boxes[0].labelText().startswith(
        "Getting the USGS photo of 8051 TREATMENT RD")
    assert "USGS is often slow" in boxes[0].labelText()
    assert _wait_for(lambda: view.doc.page_count == n0 + 1), warned
    assert time.monotonic() - t < 3
    assert log.count("exportImage") == 1 and log.count("geocode") == 1
    assert _measures(view.doc, at + 1) == pytest.approx(1000, rel=2e-3)
    assert not warned


def test_ok_during_the_address_lookup_waits_for_it(qapp, win, monkeypatch):
    log = []
    monkeypatch.setattr(aerial, "_get", _slow_fake(log, photo_s=0.2,
                                                   geo_s=0.4))
    warned = _warnings(monkeypatch)
    view = win._view
    n0 = view.doc.page_count
    dlg = aerial_ui.AerialDialog(win)
    dlg.address.setText("8051 Treatment Plant Rd, Bucksport SC")
    dlg.do_preview()
    assert dlg._geo is not None and dlg.origin is None
    _ok_on(monkeypatch, dlg)
    aerial_ui.new_aerial_page(win)
    assert _wait_for(lambda: view.doc.page_count == n0 + 1), warned
    assert log.count("exportImage") == 1 and log.count("geocode") == 1
    assert not warned


def test_photo_does_not_wait_for_the_overview(qapp, win, monkeypatch):
    """The overview tiles and the photo are separate jobs: a slow tile
    server no longer holds the photo (133 s on 0.12.29)."""
    log = []
    monkeypatch.setattr(aerial, "_get", _slow_fake(log, photo_s=0.05,
                                                   tile_s=0.3))
    dlg = aerial_ui.AerialDialog(win)
    dlg.address.setText("33.6504, -79.1192")
    dlg.do_preview()
    assert _wait_for(lambda: dlg.photo is not None)
    assert "overview" not in dlg.preview.items     # still coming
    assert _wait_for(lambda: "overview" in dlg.preview.items, 5)
    dlg.stop()


def test_a_silent_usgs_is_an_error_within_the_deadline(qapp, win,
                                                       monkeypatch):
    monkeypatch.setattr(aerial_ui, "OK_DEADLINE", 1.0)
    gate = _silent_usgs(monkeypatch)
    warned = _warnings(monkeypatch)
    try:
        view = win._view
        n0 = view.doc.page_count
        dlg = aerial_ui.AerialDialog(win)
        dlg.address.setText("33.6504, -79.1192")       # no lookup needed
        _ok_on(monkeypatch, dlg)
        assert dlg.source()[0] == "naip"
        t = time.monotonic()
        aerial_ui.new_aerial_page(win)
        boxes = _progress_boxes()
        assert boxes and boxes[0].labelText().startswith(
            "Getting the USGS photo of 33.6504, -79.1192")
        assert _wait_for(lambda: warned, 4)
        assert time.monotonic() - t < 2.5
        assert "The USGS imagery service didn't answer in 1 s. It is " \
               "often slow; try again in a few minutes." in warned[0]
        assert view.doc.page_count == n0
        assert _wait_for(lambda: aerial_ui._pool("ok").activeThreadCount()
                         == 0, 1.0)
    finally:
        gate.set()


def test_the_page_goes_into_the_set_ok_was_clicked_in(qapp, win, monkeypatch,
                                                      tmp_path):
    """0.12.29 put the page into whatever tab was in front when the photo
    arrived."""
    log = []
    monkeypatch.setattr(aerial, "_get", _slow_fake(log, photo_s=0.5))
    warned = _warnings(monkeypatch)
    first = win._view
    n_first = first.doc.page_count
    target = _second_set(win, tmp_path)
    dlg = aerial_ui.AerialDialog(win)
    dlg.address.setText("33.6504, -79.1192")
    _ok_on(monkeypatch, dlg)
    aerial_ui.new_aerial_page(win)
    win.tabs.setCurrentIndex(aerial_ui._tab_index(win, first))  # switch
    assert win._view is first
    assert _wait_for(lambda: target.doc.page_count == 4), warned
    assert first.doc.page_count == n_first
    assert win._view is target and target.page == 2
    assert _measures(target.doc, 2) == pytest.approx(1000, rel=2e-3)


def test_a_closed_set_gets_its_page_in_a_new_tab(qapp, win, monkeypatch,
                                                 tmp_path):
    log = []
    monkeypatch.setattr(aerial, "_get", _slow_fake(log, photo_s=0.5))
    warned = _warnings(monkeypatch)
    flashes = []
    monkeypatch.setattr(win, "_flash", flashes.append)
    first = win._view
    n_first = first.doc.page_count
    target = _second_set(win, tmp_path)
    dlg = aerial_ui.AerialDialog(win)
    dlg.address.setText("33.6504, -79.1192")
    _ok_on(monkeypatch, dlg)
    aerial_ui.new_aerial_page(win)
    n_tabs = win.tabs.count()
    assert win.close_tab(aerial_ui._tab_index(win, target))
    assert _wait_for(lambda: win.tabs.count() == n_tabs), warned
    new = win._view
    assert new is not first and new.doc.page_count == 1
    assert _measures(new.doc, 0) == pytest.approx(1000, rel=2e-3)
    assert first.doc.page_count == n_first
    assert flashes and "closed" in flashes[-1] and "new tab" in flashes[-1]


def test_cancel_frees_the_worker_at_once(qapp, win, monkeypatch):
    from PySide6.QtWidgets import QPushButton
    gate = _silent_usgs(monkeypatch)
    warned = _warnings(monkeypatch)
    pool = aerial_ui._pool("ok")
    try:
        view = win._view
        n0 = view.doc.page_count
        dlg = aerial_ui.AerialDialog(win)
        dlg.address.setText("33.6504, -79.1192")
        _ok_on(monkeypatch, dlg)
        aerial_ui.new_aerial_page(win)
        boxes = _progress_boxes()
        assert boxes
        assert _wait_for(lambda: pool.activeThreadCount() == 1, 2)
        time.sleep(0.2)                            # well into the request
        t = time.monotonic()
        [b for b in boxes[0].findChildren(QPushButton)
         if b.text() == "Cancel"][0].click()
        assert _wait_for(lambda: pool.activeThreadCount() == 0, 2)
        assert time.monotonic() - t < 1.0
        assert _wait_for(lambda: not _progress_boxes(), 1)
        assert view.doc.page_count == n0 and not warned
    finally:
        gate.set()


def test_cancel_while_waiting_on_the_preview_download(qapp, win,
                                                      monkeypatch):
    log = []
    monkeypatch.setattr(aerial, "_get", _slow_fake(log, photo_s=5))
    warned = _warnings(monkeypatch)
    pool = aerial_ui._pool("preview")
    view = win._view
    n0 = view.doc.page_count
    dlg = aerial_ui.AerialDialog(win)
    dlg.address.setText("33.6504, -79.1192")
    dlg.do_preview()
    assert _wait_for(lambda: dlg._inflight is not None)
    _ok_on(monkeypatch, dlg)
    aerial_ui.new_aerial_page(win)
    boxes = _progress_boxes()
    assert boxes
    boxes[0].canceled.emit()                       # the Cancel button
    assert _wait_for(lambda: pool.activeThreadCount() == 0, 1.5)
    assert view.doc.page_count == n0 and not warned
    assert log.count("exportImage") == 1
