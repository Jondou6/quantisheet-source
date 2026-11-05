"""Cutting a big rectangular building into its parts, by rule.

    office_and_bay(W, D, office_sf, side="W") -> (office, bay, annex)
        the office block in a front corner, the warehouse / plant bay
        east (or west) of it the full depth, and the strip behind the
        office - open to the bay (an open wall, model.py schema 2)
    split_bays(W, n, min_w=...) -> x breaks for n tenant bays (strip
        retail, a later phase)

Rectangles are inner (x0, y0, x1, y1) in plan feet: the exterior walls'
inside faces at EXT_T / 2, partitions on their centrelines, whole feet."""
import math

from .layout import EXT_T

OFFICE_MIN_D, OFFICE_MAX_D = 26.0, 60.0
OFFICE_MIN_W = 24.0


def office_size(W, D, office_sf):
    """(width, depth) of the office block for about `office_sf`: about
    1.5 times as wide as deep, 26-60 ft deep, never more than half the
    building's width or 45% of its depth."""
    d = math.sqrt(office_sf / 1.5)
    d = max(OFFICE_MIN_D, min(OFFICE_MAX_D, D * 0.45, d))
    w = office_sf / d
    if w > W * 0.5:                     # too long: deeper instead
        w = W * 0.5
        d = min(D * 0.45, office_sf / w)
    w = max(OFFICE_MIN_W, w)
    return float(round(w)), float(round(d))


def office_and_bay(W, D, office_sf, side="W"):
    """(office rect, bay rect, annex rect or None). The office is in the
    south-west corner (side "W") or south-east ("E")."""
    t = EXT_T / 2
    ow, od = office_size(W, D, office_sf)
    if side == "W":
        xo = t + ow if t + ow < W - t - 10 else round(W / 2)
        xo = float(round(xo))
        office = (t, t, xo, od)
        bay = (xo, t, W - t, D - t)
        annex = (t, od, xo, D - t) if D - t - od >= 3 else None
    else:
        xo = float(round(W - t - ow))
        office = (xo, t, W - t, od)
        bay = (t, t, xo, D - t)
        annex = (xo, od, W - t, D - t) if D - t - od >= 3 else None
    return office, bay, annex


def split_bays(W, n, min_w=20.0):
    """x positions of the demising walls for n equal tenant bays across a
    W ft building (centrelines; whole feet). Fewer bays when they would
    come out narrower than min_w."""
    n = max(1, int(n))
    while n > 1 and W / n < min_w:
        n -= 1
    return [float(round(W * i / n)) for i in range(1, n)]
