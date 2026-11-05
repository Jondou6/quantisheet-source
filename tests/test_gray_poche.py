"""Existing walls drawn as mid-grey solid poche (round 2, held-out
courthouse set: the offices inside grey existing walls were never found,
recall 7 of 11). Grey fills that are wall-thin at the sheet's scale are
walls; a big grey area (a key plan, site shading) and coloured or pale
fills are not."""
import fitz
import numpy as np

from app import autotakeoff as at

PPF = 9.0                                  # 1/8" = 1'-0": 9 points a foot


def _page(fill=(0.76, 0.76, 0.76)):
    doc = fitz.open()
    pg = doc.new_page(width=600, height=600)
    sh = pg.new_shape()
    t = 0.5 * PPF                          # 6 in walls
    for r in ((100, 100, 300, 100 + t), (100, 300 - t, 300, 300),
              (100, 100, 100 + t, 300), (300 - t, 100, 300, 300)):
        sh.draw_rect(fitz.Rect(*r))
    sh.finish(fill=fill, color=None, width=0)
    sh.draw_rect(fitz.Rect(400, 400, 560, 560))     # a 17' grey block
    sh.finish(fill=fill, color=None, width=0)
    # enough other linework to be read as a vector sheet
    for i in range(70):
        sh.draw_line((10, 10 + i), (40, 10 + i))
    sh.finish(color=(0, 0, 0), width=0.5)
    sh.commit()
    return doc, pg


def _ink(pg, gray=True):
    return at.vector_ink(pg, 1.0, (600, 600), fitz.Identity, min_paths=1,
                         gray_walls=(at.GRAY_WALL_FT[0] * PPF,
                                     at.GRAY_WALL_FT[1] * PPF)
                         if gray else None)


def test_thickness_of_a_long_wall_is_its_width():
    q = np.array([(0, 0), (100, 0), (100, 4), (0, 4), (0, 0)], float)
    assert 3.6 <= at._thickness_pts([q]) <= 4.0


def test_grey_wall_poche_is_wall_ink_but_not_a_grey_block():
    _doc, pg = _page()
    ink = _ink(pg)
    assert ink is not None
    assert ink[200, 102] == 1 and ink[102, 200] == 1   # the grey walls
    assert ink[480, 480] == 0                          # the grey block
    assert ink[200, 200] == 0                          # the room's floor
    off = _ink(pg, gray=False)
    assert off is None or off[200, 102] == 0           # old behaviour


def test_coloured_or_pale_fills_are_not_walls():
    for fill in ((0.9, 0.9, 0.9), (0.8, 0.5, 0.5)):
        _doc, pg = _page(fill)
        ink = _ink(pg)
        assert ink is None or ink[200, 102] == 0
