"""Gross floor area (Oct 31, round 2). On the Harbor Springs plan the
building outline traced from all the linework took in the site, porch and
dumpster linework: 3,764 SF against about 2,320 SF from the printed
dimensions. When the PDF keeps its walls on CAD wall layers, the outline
is traced from that ink only; porch-like labels are outside; and a gross
area the room cross-check disagrees with goes to review, not the totals."""
import fitz
import pytest

from app import wall_roles, crosscheck

PPU = 18.0                      # 1/4" = 1'-0"


def _plan(wall_layer="A-WALL-EXTR", porch=True):
    doc = fitz.open()
    page = doc.new_page(width=1728, height=1296)
    oc = doc.add_ocg(wall_layer)
    other = doc.add_ocg("A-FLOR-OTLN")
    x0, y0, w, h = 300.0, 300.0, 40 * PPU, 30 * PPU      # 40' x 30'
    t = 0.5 * PPU                                          # 6" walls
    sh = page.new_shape()

    def wall(a, b, n=4):
        # CAD exports a wall face as several paths on its layer
        for i in range(n):
            p = a + (b - a) * (i / n)
            q = a + (b - a) * ((i + 1) / n)
            sh.draw_line(p, q)
            sh.finish(color=(0, 0, 0), width=1, oc=oc)
    # outer and inner faces, a 3' door gap in the south wall
    gap0, gap1 = x0 + 10 * PPU, x0 + 13 * PPU
    for r in (fitz.Rect(x0, y0, x0 + w, y0 + h),
              fitz.Rect(x0 + t, y0 + t, x0 + w - t, y0 + h - t)):
        wall(r.tl, r.tr)
        wall(r.tr, r.br)
        wall(r.br, fitz.Point(gap1, r.y1))
        wall(fitz.Point(gap0, r.y1), r.bl)
        wall(r.bl, r.tl)
    if porch:
        # a 10' deep porch: posts and beam lines on another layer
        sh.draw_rect(fitz.Rect(x0, y0 + h, x0 + w, y0 + h + 10 * PPU))
        sh.finish(color=(0, 0, 0), width=1, oc=other)
        page.insert_text((x0 + 15 * PPU, y0 + h + 5 * PPU), "PORCH",
                         fontsize=9)
    sh.commit()
    return doc, page


def test_outline_from_wall_layers_leaves_the_porch_out():
    doc, page = _plan()
    out = wall_roles.layer_outline(page, PPU, "ft")
    assert out is not None
    assert out["gross_area"] == pytest.approx(1200, rel=0.02)
    assert out["outer_face_lf"] == pytest.approx(140, rel=0.03)
    assert out["loops"] == 1


def test_no_wall_layers_no_layer_outline():
    doc, page = _plan(wall_layer="A-FLOR-OTLN")
    assert wall_roles.layer_outline(page, PPU, "ft") is None


@pytest.mark.parametrize("text,kind", [
    ("COVERED ENTRY", "outside"), ("DUMPSTER", "outside"),
    ("SCREENED PORCH", "outside"), ("UNCONDITIONED STORAGE", "outside"),
    ("RECYCLING", "outside"), ("RECYCLING ROOM", None),
    ("OFFICE", None)])
def test_unconditioned_labels_are_outside(text, kind):
    assert wall_roles.classify_label(text)[0] == kind


def _res(floor, gsf):
    return {"finishes": {"rooms": [{"floor_sf": floor}]},
            "quantities": [{"engine": "walls", "name": "Gross floor area",
                            "qty": gsf, "unit": "SF",
                            "status": "taken off", "page": 4,
                            "sheet": "A101"}],
            "sheets": {}, "walls": {}, "review": [], "problems": []}


def test_gross_area_the_cross_check_rejects_goes_to_review():
    res = _res(1000.0, 3764.0)
    crosscheck.run(res)
    q = res["quantities"][0]
    assert q["status"] == "review"
    gross = [x for x in res["review"] if x["name"] == "Gross floor area"]
    assert gross and gross[0]["qty"] == 3764.0
    assert "cross-check" in gross[0]["why"]


def test_gross_area_the_cross_check_agrees_with_stays():
    res = _res(2000.0, 2320.0)
    crosscheck.run(res)
    assert res["quantities"][0]["status"] == "taken off"
    assert not [x for x in res["review"] if x["name"] == "Gross floor area"]
