"""Things other programs can read: the PDF-standard scale (Acrobat,
Bluebeam), aerial-page markups for Google Earth / GIS, and the clean-up
proof's script checks. Ideas from Venice's Oct 19 review."""
import io
import json
import math
import os

import fitz
import pytest

from app import acrobat2, aerial, annotate, geoexport, pdfmeasure


def test_scale_is_written_the_standard_way_too():
    d = fitz.open()
    d.new_page(width=1224, height=792)
    annotate.apply_op(d, annotate.new_op("set_scale", 0, ppu=18.0,
                                         unit="ft"))     # 1/4" = 1'-0"
    vps = pdfmeasure.read_page(d, 0)
    assert vps and vps[-1][1] == "1/4 in = 1 ft"
    assert vps[-1][2] == pytest.approx(18.0)
    annotate.apply_op(d, annotate.new_op(
        "set_scale", 0, viewport={"name": "Detail 3", "rect": [100, 100, 400,
                                                                400],
                                  "ppu": 36.0, "unit": "ft"}))
    vps = pdfmeasure.read_page(d, 0)
    assert [v[0] for v in vps] == ["Detail 3", "Sheet scale"]
    # the viewport box is in PDF space (y up): fitz y 100..400 -> 392..692
    kind, val = d.xref_get_key(d[0].xref, "VP")
    assert "[100 392 400 692]" in val
    # survives save and reopen
    d2 = fitz.open("pdf", d.tobytes())
    assert pdfmeasure.read_page(d2, 0)[0][2] == pytest.approx(36.0)
    assert pdfmeasure.ratio_text(72 / 20, "ft") == "1 in = 20 ft"


def _photo(w, h):
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (w, h), (90, 110, 90)).save(out, "JPEG")
    return out.getvalue()


def test_aerial_markups_go_to_google_earth_in_the_right_place(tmp_path):
    lat, lon = 33.6577, -79.1037
    d = aerial.aerial_document_from(_photo(1000, 750), 0.3048, lat, lon,
                                    "USGS NAIP Plus", "")
    assert geoexport.geo_of(d, 0)
    pg = d[0]
    ppu = annotate.read_scales(d)[0]["ppu"]          # 0.75 pt per ft
    cx, cy = 1000 * 0.75 / 2, 750 * 0.75 / 2
    # a 100 x 100 ft square, its SW corner at the photo centre
    sq = [(cx, cy), (cx + 100 * ppu, cy), (cx + 100 * ppu, cy - 100 * ppu),
          (cx, cy - 100 * ppu)]
    a = pg.add_polygon_annot(sq)
    a.set_info(subject="Paving")
    a.update()
    path = str(tmp_path / "site.geojson")
    assert geoexport.to_geojson(d, 0, path) == 1
    f = json.load(open(path))["features"][0]
    ring = f["geometry"]["coordinates"][0]
    assert f["properties"]["name"] == "Paving"
    assert ring[0] == pytest.approx([lon, lat], abs=1e-6)
    # 100 ft north and east of the centre
    dn = (ring[2][1] - lat) * geoexport.FT_PER_DEG_LAT
    de = (ring[2][0] - lon) * geoexport.FT_PER_DEG_LAT * math.cos(
        math.radians(lat))
    assert dn == pytest.approx(100, abs=0.5) and de == pytest.approx(100,
                                                                    abs=0.5)
    kml = str(tmp_path / "site.kml")
    assert geoexport.to_kml(d, 0, kml) == 1
    assert "<Polygon>" in open(kml).read()
    plain = fitz.open()
    plain.new_page()
    with pytest.raises(ValueError):
        geoexport.features(plain, 0)


def test_clean_up_proof_checks_page_scripts_and_xfa():
    d = fitz.open()
    p = d.new_page()
    p.insert_text((72, 72), "SHEET A-101")
    d.xref_set_key(p.xref, "AA", "<</O<</S/JavaScript/JS(app.alert(1))>>>>")
    rows = {i: st for st, i, _d in acrobat2.verify_clean(d)}
    assert rows["Scripts (JavaScript, open/close actions)"] == "FAIL"
    acrobat2.sanitize(d)              # page scripts go in the normal pass
    rows = {i: st for st, i, _d in acrobat2.verify_clean(d)}
    assert rows["Scripts (JavaScript, open/close actions)"] == "PASS"
    assert rows["XFA form data (can hold scripts)"] == "PASS"


def test_job_data_is_not_reported_as_an_attachment():
    d = fitz.open()
    d.new_page()
    annotate.apply_op(d, annotate.new_op("set_scale", 0, ppu=18.0))
    acrobat2.sanitize(d)
    rows = {i: st for st, i, _d in acrobat2.verify_clean(d)}
    assert rows["Attached files"] == "PASS"
    assert annotate.read_scales(d)[0]["ppu"] == 18.0     # scale kept
