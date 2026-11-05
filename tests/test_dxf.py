"""Step 5: DXF import/export and Trace Length."""
import os

import fitz
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ezdxf = pytest.importorskip("ezdxf")

from app import annotate, dxf, snap, vector                 # noqa: E402
from test_gui import ANSWERS, win, qapp                    # noqa: E402,F401


def _cad(path):
    """A 40' x 20' room in inches, with a door block, text and a circle."""
    d = ezdxf.new("R2010")
    d.header["$INSUNITS"] = 1
    d.layers.add("WALLS", color=1)
    d.layers.add("NOTES", color=5)
    d.layers.add("HIDDEN", color=2).off()
    msp = d.modelspace()
    msp.add_lwpolyline([(0, 0), (480, 0), (480, 240), (0, 240)], close=True,
                       dxfattribs={"layer": "WALLS"})
    msp.add_line((0, 120), (200, 120), dxfattribs={"layer": "WALLS"})
    msp.add_circle((300, 120), 24, dxfattribs={"layer": "WALLS"})
    msp.add_text("ROOM 101", height=12,
                 dxfattribs={"layer": "NOTES"}).set_placement((40, 60))
    msp.add_line((10, 10), (50, 50), dxfattribs={"layer": "HIDDEN"})
    blk = d.blocks.new("DOOR")
    blk.add_line((0, 0), (36, 0))
    blk.add_arc((0, 0), 36, 0, 90)
    msp.add_blockref("DOOR", (100, 0), dxfattribs={"layer": "WALLS"})
    d.saveas(path)


def test_import_dxf_to_scaled_pdf(tmp_path):
    src = str(tmp_path / "room.dxf")
    _cad(src)
    out = str(tmp_path / "room.pdf")
    info = dxf.to_pdf(src, out)
    assert info["scale"] == "3/4\" = 1'-0\"" and info["layers"] == 3
    assert info["layers_off"] == 1
    d = fitz.open(out)
    sc = annotate.read_scales(d)[0]
    assert sc["ppu"] == 54 and sc["unit"] == "ft"
    states = {v["name"]: v["on"] for v in d.get_ocgs().values()}
    assert states == {"WALLS": True, "NOTES": True, "HIDDEN": False}
    assert "ROOM 101" in d[0].get_text()
    # the outer wall measures exactly 40' along its long side
    idx = snap.SnapIndex(snap.page_segments(d[0]))
    segs = [s for s in idx.segs if abs(s[0][1] - s[1][1]) < 0.01 and
            abs(abs(s[0][0] - s[1][0]) - 40 * 54) < 0.5]
    assert segs, "outer wall line not found"
    a, b = segs[0]
    mid = ((a[0] + b[0]) / 2, a[1] + 1)
    pts, closed = vector.trace(idx, mid)
    assert closed and vector.length(pts) / 54 == pytest.approx(120, abs=0.1)
    # the interior partition is a 200" = 16'-8" open run
    part = [s for s in idx.segs if abs(abs(s[0][0] - s[1][0]) -
                                       200 / 12 * 54) < 0.5]
    a, b = part[0]
    pts, closed = vector.trace(idx, ((a[0] + b[0]) / 2, a[1]))
    assert not closed
    assert vector.length(pts) / 54 == pytest.approx(200 / 12, abs=0.05)
    with pytest.raises(dxf.DXFError):
        dxf.to_pdf(str(tmp_path / "missing.dxf"), out)


def test_import_paper_space_sheets_with_viewport_scales(tmp_path):
    src = str(tmp_path / "sheets.dxf")
    _cad(src)
    d = ezdxf.readfile(src)
    lay = d.layouts.new("A-101")
    lay.page_setup(size=(36, 24), margins=(0, 0, 0, 0), units="inch")
    lay.add_lwpolyline([(0.5, 0.5), (35.5, 0.5), (35.5, 23.5), (0.5, 23.5)],
                       close=True)
    lay.add_text("A-101", height=0.5).set_placement((30, 1.5))
    # 1/4" = 1'-0": 20" of paper shows 960" of model
    lay.add_viewport(center=(15, 12), size=(24, 20),
                     view_center_point=(240, 120), view_height=960)
    d.saveas(src)
    assert dxf.layouts(src) == [("A-101", 1)]
    out = str(tmp_path / "sheets.pdf")
    info = dxf.to_pdf(src, out, what="layouts")
    assert info["pages"] == 1 and info["viewports"] == 1
    assert info["scale"] == "1/4\" = 1'-0\""
    p = fitz.open(out)
    assert "A-101" in p[0].get_text()
    vps = annotate.read_viewports(p, 0)
    assert len(vps) == 1 and vps[0]["ppu"] == pytest.approx(18)
    assert annotate.read_scales(p)[0]["ppu"] == pytest.approx(18)
    # the 40' wall is 10" long on the sheet
    idx = snap.SnapIndex(snap.page_segments(p[0]))
    assert any(abs(abs(a[0] - b[0]) - 720) < 1 and abs(a[1] - b[1]) < 0.1
               for a, b in idx.segs)
    assert p.get_toc() == [[1, "A-101", 1]]


def test_export_page_to_dxf_in_real_units(tmp_path):
    d = fitz.open()
    p = d.new_page(width=1224, height=792)
    p.draw_line((100, 700), (100 + 48 * 10, 700))            # 10' at 1/4"
    p.insert_text((100, 650), "LOBBY", fontsize=18)
    annotate.apply_op(d, annotate.new_op("set_scale", 0, ppu=18, unit="ft"))
    annotate.apply_op(d, annotate.new_op(
        "add_polyline", 0, pts=[[100, 500], [100 + 18 * 25, 500]],
        measure={"type": "length", "value": 25, "unit": "ft",
                 "group": "Wall A"}))
    out = str(tmp_path / "p.dxf")
    info = dxf.from_page(d, 0, out)
    assert info["units"] == "ft" and info["entities"] >= 3
    x = ezdxf.readfile(out)
    assert x.header["$INSUNITS"] == 2
    msp = x.modelspace()
    lines = msp.query("LINE[layer=='PDF-Drawing']")
    assert any(abs(e.dxf.end.x - e.dxf.start.x - 480 / 18) < 1e-6
               for e in lines)
    texts = [e.dxf.text for e in msp.query("TEXT")]
    assert "LOBBY" in texts
    wall = msp.query("LWPOLYLINE[layer=='Takeoff-Wall A']")
    assert len(wall) == 1
    pts = list(wall[0].get_points("xy"))
    assert pts[1][0] - pts[0][0] == pytest.approx(25)


def test_dxf_and_trace_in_the_app(qapp, win, tmp_path):
    src = str(tmp_path / "room.dxf")
    _cad(src)
    info = win.import_dxf(src, str(tmp_path / "room_from_dxf.pdf"))
    assert info and win._view.scale()["ppu"] == 54
    v = win._view
    idx = v.snap_index()
    seg = next(s for s in idx.segs if abs(abs(s[0][0] - s[1][0]) -
                                          200 / 12 * 54) < 0.5)
    v.set_zoom(1.0)
    v.set_tool("trace_length")
    n = v.commit_click("trace_length", fitz.Point(
        (seg[0][0] + seg[1][0]) / 2, seg[0][1] + 2))
    assert n
    it = [i for i in annotate.takeoff_items(v.doc) if i["type"] == "length"]
    assert it and it[-1]["value"] == pytest.approx(200 / 12, abs=0.05)
    out = win.export_dxf(str(tmp_path / "back.dxf"))
    assert out
    # DXF export runs on a worker thread now (review 0.12.29 step 9)
    import time
    from PySide6.QtWidgets import QApplication
    end = time.monotonic() + 60
    while not os.path.exists(str(tmp_path / "back.dxf")) and \
            time.monotonic() < end:
        QApplication.processEvents()
        time.sleep(0.05)
    assert os.path.exists(str(tmp_path / "back.dxf"))
