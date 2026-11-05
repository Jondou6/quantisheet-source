"""P1 'photo albums, tags, location pins on a sheet, timeline': photos
already on the job's records, grouped by date / area / tag, filtered by
tag, pinned on A-102; no GPS read or sent (made-up photos)."""
import pytest

from app import settings
from app.pm import photo_library as pl
from app.pm.store import ProjectStore


@pytest.fixture
def s(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DIR", str(tmp_path / "cfg"))
    monkeypatch.setattr(settings, "PATH", str(tmp_path / "cfg" / "s.json"))
    monkeypatch.setattr(settings, "_cache", {"author": "Test PM"})
    st = ProjectStore(str(tmp_path / "job"))
    refs = []
    for i in range(6):
        p = tmp_path / f"ph{i}.jpg"
        p.write_bytes(b"\xff\xd8\xff example photo %d" % i)
        refs.append(st.attach(str(p)))
    st.save_record("daily", {"date": "2026-11-16", "photos": refs[:3],
                             "location": "Bldg A"})
    st.save_record("daily", {"date": "2026-11-17", "photos": refs[3:5]})
    st.save_record("punch", {"title": "Example scuff", "photos": refs[5:],
                             "location": "Lobby",
                             "date": "2026-11-18"})
    return st


def test_albums_by_date_and_area_and_timeline(s):
    assert len(pl.photos(s)) == 6
    by_date = pl.albums(s, "date")
    assert [len(v) for v in by_date.values()] == [3, 2, 1]
    by_area = pl.albums(s, "area")
    assert len(by_area["Bldg A"]) == 3 and len(by_area["No area"]) == 2
    assert pl.timeline(s)[0] == ("2026-11-16", 3)


def test_tags_filter_and_pin_on_a_sheet(s):
    ph = pl.photos(s)
    pl.set_tags(s, ph[0]["key"], ["Slab", "slab", " pour "])
    pl.set_tags(s, ph[4]["key"], ["Slab"])
    assert pl.photos(s)[0]["tags"] == ["Slab", "pour"]
    assert len(pl.with_tag(s, "slab")) == 2
    assert set(pl.albums(s, "tag")) == {"Slab", "pour", "No tag"}
    pl.pin(s, ph[1]["key"], "a-102", 0, 120, 340, looking="NE")
    on = pl.on_sheet(s, "A-102")
    assert len(on) == 1 and on[0]["pin"]["looking"] == "NE"
    pl.unpin(s, ph[1]["key"])
    assert pl.on_sheet(s, "A-102") == []


def test_no_location_data_is_read():
    src = open(pl.__file__, encoding="utf-8").read()
    assert "GPSInfo" not in src and "34853" not in src


def test_pin_by_clicking_the_drawing(s, tmp_path):
    """Known-broken fix: a pin goes where the PM clicks on the sheet, not
    always the middle."""
    import fitz
    pytest.importorskip("PySide6.QtWidgets")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app.pm.photo_library_ui import PhotoLibraryDialog, PinPickDialog
    sheet = str(tmp_path / "A-102.pdf")
    d = fitz.open()
    d.new_page(width=1224, height=792)
    d.save(sheet)
    dlg = PinPickDialog(sheet, 0)
    assert dlg.scale > 0
    x, y = dlg.pick_at(450 * dlg.scale, 300 * dlg.scale)
    assert (x, y) == (450.0, 300.0)
    lib = PhotoLibraryDialog(s)
    key = pl.photos(s)[0]["key"]
    lib.edit_pin(key, "a-102", x=x, y=y)
    pin = pl.photos(s)[0]["pin"]
    assert pin["sheet"] == "A-102" and (pin["x"], pin["y"]) == (450.0,
                                                                300.0)
