"""Rooms engine, Oct 31 2026 (public bid set): linework that is in the
PDF but not visible on the sheet - drawn under a white mask or cut off by
a viewport clip - is not a wall. On the test set an electrical legend
table hidden under the floor plan split MECH. ROOM 110 into a 20 SF cell
(truth about 145 SF from its 12'-10" x 11'-4" dimensions). Every drawing
here is made up in the test."""
import os

import fitz

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app import autotakeoff                                  # noqa: E402

PPF = 18.0
OX, OY = 90.0, 90.0
SCALE = {"ppu": PPF, "unit": "ft"}


def _ft(x, y):
    return fitz.Point(OX + x * PPF, OY + y * PPF)


def _wall(page, x0, y0, x1, y1):
    page.draw_rect(fitz.Rect(_ft(x0, y0), _ft(x1, y1)), color=(0, 0, 0),
                   fill=(0, 0, 0), width=0)


def _room(page):
    """One 12' x 10' room (120 SF) with 6" poche walls."""
    _wall(page, 0, 0, 13, 0.5)
    _wall(page, 0, 10.5, 13, 11)
    _wall(page, 0, 0, 0.5, 11)
    _wall(page, 12.5, 0, 13, 11)
    page.insert_text(_ft(4, 3), "MECH. ROOM", fontsize=8)
    page.insert_text(_ft(5, 3.6), "110", fontsize=8)


def _table(page):
    """A legend table's grid lines across the middle of the room."""
    for y in (4.5, 5.5, 6.5, 7.5, 8.5):
        page.draw_line(_ft(1.5, y), _ft(11.5, y), color=(0, 0, 0),
                       width=0.6)
    for x in (1.5, 4.0, 11.5):
        page.draw_line(_ft(x, 4.5), _ft(x, 8.5), color=(0, 0, 0),
                       width=0.6)
    # the legend's lettering, drawn as pen strokes (CAD fonts exported as
    # linework): dense enough to close into solid blobs like a wall
    for row in (4.5, 5.5, 6.5, 7.5):
        x = 4.3
        while x < 11.2:
            page.draw_line(_ft(x, row + 0.2), _ft(x + 0.1, row + 0.8),
                           color=(0, 0, 0), width=0.5)
            x += 0.12


def _area(page):
    return autotakeoff.room_at(page, SCALE, _ft(6, 2))["sqft"]


def test_control_room_without_hidden_lines():
    d = fitz.open()
    pg = d.new_page(width=600, height=500)
    _room(pg)
    assert abs(_area(pg) - 120) < 120 * 0.05


def test_lines_under_a_white_mask_are_not_walls():
    d = fitz.open()
    pg = d.new_page(width=600, height=500)
    _room(pg)
    _table(pg)
    pg.draw_rect(fitz.Rect(_ft(1, 4), _ft(12, 9)), color=None,
                 fill=(1, 1, 1), width=0)          # the mask
    assert abs(_area(pg) - 120) < 120 * 0.05


def test_lines_clipped_out_of_a_viewport_are_not_walls():
    src = fitz.open()
    sp = src.new_page(width=600, height=500)
    _table(sp)
    # the legend lies outside the viewport window on the source, so it is
    # in the content but never shown
    d = fitz.open()
    pg = d.new_page(width=600, height=500)
    _room(pg)
    pg.show_pdf_page(pg.rect, src, 0,
                     clip=fitz.Rect(0, 0, 600, OY + 4.0 * PPF))
    assert abs(_area(pg) - 120) < 120 * 0.05


def test_visible_lines_still_split_a_room():
    """A real wall drawn across the room still counts."""
    d = fitz.open()
    pg = d.new_page(width=600, height=500)
    _room(pg)
    _wall(pg, 0.5, 5, 12.5, 5.5)
    assert _area(pg) < 70
