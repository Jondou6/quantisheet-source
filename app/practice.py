"""A small practice set for the tutorials: a floor plan, a plumbing and
electrical plan with a legend, a detail sheet and a spec page - drawn the
way CAD exports them, so every tool has something real to work on
(Help > Open Practice Drawings)."""
import os

import fitz

PPU = 18.0                                   # 1/4" = 1'-0"
W, H = 1728, 1152                            # 24 x 16 sheet


def _title_block(page, number, title):
    sh = page.new_shape()
    sh.draw_rect(fitz.Rect(36, 36, W - 36, H - 36))
    sh.draw_rect(fitz.Rect(W - 300, 36, W - 36, H - 36))
    sh.finish(color=(0, 0, 0), width=1.5)
    sh.commit()
    page.insert_text((W - 285, H - 160), "PRACTICE CLINIC", fontsize=13)
    page.insert_text((W - 285, H - 135), title, fontsize=11)
    page.insert_text((W - 285, H - 110), "SCALE: 1/4\" = 1'-0\"",
                     fontsize=10)
    page.insert_text((W - 285, H - 60), number, fontsize=28)


def _p(x, y, ox=120, oy=120):
    return (ox + x * PPU, oy + y * PPU)


def _walls(page):
    """A 60 x 40 ft building, 8" exterior walls, 5" partitions."""
    t8, t5 = 8 / 12, 5 / 12
    sh = page.new_shape()

    def wall(x0, y0, x1, y1, t):
        # two faces of a wall, as CAD draws them
        if y0 == y1:
            sh.draw_line(_p(x0, y0), _p(x1, y1))
            sh.draw_line(_p(x0, y0 + t), _p(x1, y1 + t))
        else:
            sh.draw_line(_p(x0, y0), _p(x1, y1))
            sh.draw_line(_p(x0 + t, y0), _p(x1 + t, y1))
    wall(0, 0, 60, 0, t8)
    wall(0, 40 - t8, 60, 40 - t8, t8)
    wall(0, 0, 0, 40, t8)
    wall(60 - t8, 0, 60 - t8, 40, t8)
    wall(24, t8, 24, 16, t5)             # partitions, with door gaps
    wall(24, 19, 24, 40 - t8, t5)
    wall(t8, 20, 20, 20, t5)
    wall(23, 20, 60 - t8, 20, t5)
    wall(42, 20 + t5, 42, 40 - t8, t5)
    sh.finish(color=(0, 0, 0), width=0.9, closePath=False)
    # door swings (3'-0")
    for hx, hy in ((24 + t5, 16), (20, 20 + t5), (42 + t5, 23)):
        c = fitz.Point(*_p(hx, hy))
        r = 3 * PPU
        sh.draw_line(c, c + (r, 0))
        sh.draw_curve(c + (r, 0), c + (r, r), c + (0, r))
    sh.finish(color=(0, 0, 0), width=0.5, closePath=False)
    sh.commit()


def floor_plan(doc):
    page = doc.new_page(width=W, height=H)
    _title_block(page, "A-101", "FLOOR PLAN")
    _walls(page)
    for x, y, name, sf in ((8, 9, "LOBBY", 451), (38, 9, "EXAM 101", 675),
                           (8, 29, "OFFICE 102", 441),
                           (30, 29, "KENNEL 103", 333),
                           (48, 29, "STORAGE 104", 320)):
        page.insert_text(_p(x, y), name, fontsize=12)
        page.insert_text(_p(x, y + 1.3), f"{sf} SF", fontsize=10)
    page.insert_text(_p(2, 44), "SEE 3/A-501 FOR WALL SECTIONS. "
                     "PLUMBING ON P-101.", fontsize=11)
    return page


def mep_plan(doc):
    page = doc.new_page(width=W, height=H)
    _title_block(page, "P-101", "PLUMBING & POWER PLAN")
    # the building in light grey, as MEP sheets show it
    sh = page.new_shape()
    for a, b in (((0, 0), (60, 0)), ((60, 0), (60, 40)), ((60, 40), (0, 40)),
                 ((0, 40), (0, 0)), ((24, 0), (24, 40)), ((0, 20), (60, 20))):
        sh.draw_line(_p(*a), _p(*b))
    sh.finish(color=(0.65, 0.65, 0.65), width=0.4, closePath=False)
    sh.commit()

    def run(pts, color, width=1.4, dashes=None):
        s = page.new_shape()
        for a, b in zip(pts, pts[1:]):
            s.draw_line(_p(*a), _p(*b))
        s.finish(color=color, width=width, dashes=dashes, closePath=False)
        s.commit()
    run([(2, 6), (56, 6)], (0, 0, 0.9))                        # 2" CW
    run([(30, 6), (30, 30)], (0, 0, 0.9))
    page.insert_text(_p(12, 5.4), '2" CW', fontsize=8)
    run([(2, 9), (40, 9), (40, 30)], (0.9, 0, 0), 1.0, "[4 2] 0")  # HW
    page.insert_text(_p(14, 8.4), '1" HW', fontsize=8)
    run([(4, 36), (56, 36)], (0.2, 0.6, 0.2), 1.8)             # sanitary
    page.insert_text(_p(20, 35.4), '4" SAN', fontsize=8)
    # legend and devices
    lx, ly = W - 560, 120
    page.insert_text((lx, ly), "LEGEND", fontsize=12)

    def recept(c):
        s = page.new_shape()
        s.draw_circle(c, 5)
        s.draw_line(c + (-7, -2), c + (-5, -2))
        s.draw_line(c + (-7, 2), c + (-5, 2))
        s.finish(color=(0, 0, 0), width=0.8)
        s.commit()

    def jbox(c):
        s = page.new_shape()
        s.draw_rect(fitz.Rect(c.x - 5, c.y - 5, c.x + 5, c.y + 5))
        s.draw_line(c + (-5, -5), c + (5, 5))
        s.draw_line(c + (-5, 5), c + (5, -5))
        s.finish(color=(0, 0, 0), width=0.8)
        s.commit()
    recept(fitz.Point(lx + 10, ly + 24))
    page.insert_text((lx + 30, ly + 27), "DUPLEX RECEPTACLE", fontsize=8)
    jbox(fitz.Point(lx + 10, ly + 46))
    page.insert_text((lx + 30, ly + 49), "JUNCTION BOX", fontsize=8)
    for x, y in ((3, 2), (14, 2), (35, 2), (50, 2), (3, 24), (20, 38),
                 (45, 24), (57, 30)):
        recept(fitz.Point(*_p(x, y)))
    for x, y in ((10, 15), (36, 15), (52, 34)):
        jbox(fitz.Point(*_p(x, y)))
    return page


def detail_sheet(doc):
    page = doc.new_page(width=W, height=H)
    _title_block(page, "A-501", "DETAILS")
    page.insert_text((140, 160), "3  WALL SECTION", fontsize=14)
    sh = page.new_shape()
    sh.draw_rect(fitz.Rect(160, 200, 400, 700))
    sh.finish(color=(0, 0, 0), width=1)
    sh.commit()
    page.insert_text((140, 760), "SEE A-101 FOR LOCATIONS.", fontsize=11)
    return page


def spec_page(doc):
    page = doc.new_page()                                   # letter
    page.insert_text((72, 72), "SECTION 03 30 00 - CAST-IN-PLACE CONCRETE",
                     fontsize=13, fontname="hebo")
    page.insert_textbox(
        fitz.Rect(72, 100, 540, 260),
        "1.1 SUMMARY\nThe contractor shall furnish all labor, materials and "
        "equipment required to complete the concrete work shown on the "
        "drawings and specified herein, including formwork, reinforcement "
        "and curing.", fontsize=10.5, fontname="tiro")
    return page


def make(path):
    """Write the practice set to `path` (scale set on the drawing sheets)."""
    from . import annotate
    doc = fitz.open()
    floor_plan(doc)
    mep_plan(doc)
    detail_sheet(doc)
    spec_page(doc)
    annotate.apply_op(doc, annotate.new_op(
        "set_scale", 0, ppu=PPU, unit="ft", name='1/4" = 1\'-0"',
        pages=[0, 1, 2]))
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    doc.save(path, garbage=3, deflate=True)
    return path
