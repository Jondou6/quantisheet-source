"""PM review NW-17: Auto Doors found 43 doors on A-102 against the door
schedule's 31 - swings drawn twice, the two leaves of a pair and half
circles (two quarter arcs on one centre) were each counted."""
import math

import fitz

from app import autowalls

PPF = 18.0                                      # 1/4" = 1'-0"


def swing(pg, hx, hy, a0, a1, r_ft=3.0):
    """A swing as a run of short lines from angle a0 to a1 (degrees) plus
    the leaf, the way Revit exports draw it."""
    r = r_ft * PPF
    step = 6 if a1 > a0 else -6
    pts = [fitz.Point(hx + r * math.cos(math.radians(a)),
                      hy + r * math.sin(math.radians(a)))
           for a in range(a0, a1 + step, step)]
    s = pg.new_shape()
    s.draw_polyline(pts)
    s.draw_line(fitz.Point(hx, hy), pts[-1])
    s.finish(color=(0, 0, 0), width=0.25)
    s.commit()


def test_one_lone_door_is_one():
    d = fitz.open()
    pg = d.new_page(width=1200, height=800)
    swing(pg, 100, 100, 0, 90)
    ds = autowalls.doors(pg, PPF, "ft")
    assert len(ds) == 1 and ds[0]["leaves"] == 1


def test_swing_drawn_twice_counts_once():
    d = fitz.open()
    pg = d.new_page(width=1200, height=800)
    swing(pg, 100, 100, 0, 90)
    swing(pg, 101, 100.5, 0, 90)                    # a second layer
    assert len(autowalls.doors(pg, PPF, "ft")) == 1


def test_back_to_back_doors_stay_two():
    d = fitz.open()
    pg = d.new_page(width=1200, height=800)
    swing(pg, 300, 300, 0, 90)                       # swings down
    swing(pg, 300, 290, 0, -90)                      # swings up
    assert len(autowalls.doors(pg, PPF, "ft")) == 2


def test_pair_of_leaves_is_one_door():
    d = fitz.open()
    pg = d.new_page(width=1200, height=800)
    swing(pg, 400, 200, 0, 90)                       # left leaf
    swing(pg, 400 + 6 * PPF, 200, 180, 90)           # right leaf, meets it
    ds = autowalls.doors(pg, PPF, "ft")
    assert len(ds) == 1
    assert ds[0]["leaves"] == 2 and abs(ds[0]["width"] - 6.0) < 0.2


def test_two_doors_side_by_side_are_two():
    d = fitz.open()
    pg = d.new_page(width=1200, height=800)
    swing(pg, 400, 500, 0, 90)                       # same hand,
    swing(pg, 400 + 6 * PPF, 500, 0, 90)             # 6 ft apart
    assert len(autowalls.doors(pg, PPF, "ft")) == 2


def test_half_circle_is_not_a_door():
    d = fitz.open()
    pg = d.new_page(width=1200, height=800)
    swing(pg, 700, 400, 0, 90)
    swing(pg, 700.5, 400, 90, 180)                   # same centre
    assert autowalls.doors(pg, PPF, "ft") == []


def test_arc_with_no_leaf_is_not_a_door():
    """Toilet bowls and fixtures are door-sized arcs with no leaf line."""
    d = fitz.open()
    pg = d.new_page(width=1200, height=800)
    r = 2.2 * PPF
    s = pg.new_shape()
    s.draw_polyline([fitz.Point(600 + r * math.cos(math.radians(a)),
                                300 + r * math.sin(math.radians(a)))
                     for a in range(0, 91, 6)])
    s.finish(color=(0, 0, 0), width=0.25)
    s.commit()
    assert autowalls.doors(pg, PPF, "ft") == []


def test_narrow_partition_door_is_left_out_but_reviewable():
    d = fitz.open()
    pg = d.new_page(width=1200, height=800)
    swing(pg, 100, 100, 0, 90)                       # 3'-0" door
    swing(pg, 600, 500, 0, 90, r_ft=2.17)            # toilet stall door
    assert len(autowalls.doors(pg, PPF, "ft")) == 1
    both = autowalls.doors(pg, PPF, "ft", include_narrow=True)
    assert sorted(x["narrow"] for x in both) == [False, True]
