"""Auto Takeoff Rooms on made-up plans drawn with what real sheets have.

    python tools/accuracy_hard.py [PLANS] [--seed N] [--out DIR] [--only K]

tools/accuracy.py and accuracy_real.py draw rectangles of walls with a
door each. Real plans (HMB A101, Nov 2026) miss for other reasons, so
these plans have them, with the right answer known exactly:

* walls cleaned up at their joints the way CAD draws them, of mixed
  thickness, hollow, solid or with hatched exterior walls
* L-shaped rooms (a closet or a shaft boxed out of a corner), a wall
  across a building corner at 45 degrees
* doors: single and double swings, cased openings with a dashed head
  line, pocket doors, bifolds, a threshold line across some openings
* things that are not walls: toilet partitions, tile hatching, casework
  and upper cabinets, shelving, benches, stair treads, equipment,
  furniture, grid lines through the plan, dimension strings and leaders
  across rooms
* tags: one or two name lines over a number (boxed on some plans), with
  the area printed on some plans, a tag sample in a legend, a key plan
  and a title block
* scales 1/8", 3/16" and 1/4"

The truth is not taken from the program: walls are painted into a mask
at 72 px per foot, doors shut at the wall line, and each room is the
open floor around its tag. Scores: rooms found, within 1 / 2 / 5 %,
rooms that are not rooms, and the total area.
"""
import math
import os
import random
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import cv2                                                    # noqa: E402
import fitz                                                   # noqa: E402
import numpy as np                                            # noqa: E402

SHOW = 2.0                     # rooms off by more than this are listed
PXF = 72                       # truth mask: pixels per foot
PAD = 3 * PXF                  # mask margin around the building, px
OX, OY = 190.0, 210.0          # building corner on the sheet, points
NAMES = {
    "toilet": [("MEN'S", "TOILET"), ("WOMEN'S", "TOILET"), ("TOILET",),
               ("RESTROOM",), ("STAFF", "TOILET")],
    "office": [("OFFICE",), ("MANAGER",), ("OPEN", "OFFICE"),
               ("RECEPTION",)],
    "conf": [("CONFERENCE",), ("MEETING", "ROOM"), ("TRAINING",)],
    "break": [("BREAK", "ROOM"), ("KITCHEN",), ("STAFF", "LOUNGE")],
    "storage": [("STORAGE",), ("SUPPLY",), ("FILE", "ROOM")],
    "shower": [("SHOWER",), ("LOCKER", "ROOM")],
    "mech": [("MECH.",), ("ELEC.",), ("MECH.", "ROOM")],
    "stair": [("STAIR",)],
    "exam": [("EXAM",), ("LAB",), ("PREP",)],
    "corridor": [("CORRIDOR",), ("HALL",), ("LOBBY",)],
    "closet": [("CLO.",), ("JAN.",)],
}


class Ink:
    """A pen that writes every stroke as its own path, the way CAD
    exports do (one path per object) - a page of a dozen big paths is
    taken for a scan by the program."""

    def __init__(self, page):
        self.page, self.ops = page, []

    def __getattr__(self, name):
        if not name.startswith("draw_"):
            raise AttributeError(name)

        def rec(*a, **k):
            self.ops.append((name, a, k))
        return rec

    def finish(self, **style):
        sh = self.page.new_shape()
        for name, a, k in self.ops:
            getattr(sh, name)(*a, **k)
            sh.finish(**style)
        sh.commit()
        self.ops = []

    def commit(self):
        pass


class Sheet:
    """One made-up plan: geometry in feet, a wall mask in pixels, a PDF
    page in points."""

    def __init__(self, doc, rnd, ppf):
        self.rnd, self.ppf = rnd, ppf
        self.page = doc.new_page(width=2592, height=1728)
        k = 18.0 / ppf
        self.W = 0.5 * round(rnd.uniform(66, 88) * k / 0.5)
        self.H = 0.5 * round(rnd.uniform(46, 58) * k / 0.5)
        self.depth = 4 if ppf >= 18 else 5
        self.t_ext = rnd.choice([8, 8, 12]) / 12.0
        self.style = rnd.choice(["hollow", "hollow", "solid", "hatch"])
        self.boxed = rnd.random() < 0.4
        self.sf_mode = rnd.choice(["all", "none", "mixed"])
        self.walls = []            # {o, c, a, b, t, ext}
        self.gaps = []             # {w, g0, g1, kind, side, hinge}
        self.cells = []            # [x0, y0, x1, y1] ft
        self.rooms = []            # truth rows
        self.shafts = []
        self.chamfer = None
        self.font = 8.0 if ppf >= 13 else 6.5

    # ---- units ------------------------------------------------------
    def px(self, ft):
        return int(round(ft * PXF)) + PAD

    def pt(self, x, y):
        return fitz.Point(OX + x * self.ppf, OY + y * self.ppf)

    def px2pt(self, x, y):
        return fitz.Point(OX + (x - PAD) * self.ppf / PXF,
                          OY + (y - PAD) * self.ppf / PXF)

    def pt2px(self, p):
        return ((p.x - OX) * PXF / self.ppf + PAD,
                (p.y - OY) * PXF / self.ppf + PAD)

    # ---- layout -----------------------------------------------------
    def split(self, r, depth):
        x0, y0, x1, y1 = r
        w, h = x1 - x0, y1 - y0
        rnd = self.rnd
        if depth == 0 or (w < 17 and h < 17) or \
                (depth < self.depth - 1 and rnd.random() < 0.12):
            self.cells.append(r)
            return
        t = rnd.choice([3.5, 4.875, 4.875, 6.0, 8.0]) / 12.0
        if (w >= h and w >= 17) or h < 17:
            x = 0.5 * round((x0 + rnd.uniform(0.35, 0.65) * w) / 0.5)
            self.walls.append({"o": "v", "c": x, "a": y0, "b": y1, "t": t,
                               "ext": False})
            self.split([x0, y0, x, y1], depth - 1)
            self.split([x, y0, x1, y1], depth - 1)
        else:
            y = 0.5 * round((y0 + rnd.uniform(0.35, 0.65) * h) / 0.5)
            self.walls.append({"o": "h", "c": y, "a": x0, "b": x1, "t": t,
                               "ext": False})
            self.split([x0, y0, x1, y], depth - 1)
            self.split([x0, y, x1, y1], depth - 1)

    def layout(self):
        W, H, te, rnd = self.W, self.H, self.t_ext, self.rnd
        for o, c, a, b in (("h", 0, 0, W), ("h", H, 0, W), ("v", 0, 0, H),
                           ("v", W, 0, H)):
            self.walls.append({"o": o, "c": c, "a": a, "b": b, "t": te,
                               "ext": True})
        self.split([0, 0, W, H], self.depth)
        # a wall across one corner at 45 degrees
        if rnd.random() < 0.6:
            corner = rnd.choice(["tl", "tr", "bl", "br"])
            cell = next(c for c in self.cells if
                        (c[0] == 0 if corner[1] == "l" else c[2] == W) and
                        (c[1] == 0 if corner[0] == "t" else c[3] == H))
            d = min(rnd.uniform(5, 9), cell[2] - cell[0] - 7,
                    cell[3] - cell[1] - 7)
            if d >= 4:
                self.chamfer = (corner, round(d * 2) / 2, cell)
        # closets and shafts boxed out of room corners
        for cell in list(self.cells):
            x0, y0, x1, y1 = cell
            if min(x1 - x0, y1 - y0) < 12 or rnd.random() > 0.4:
                continue
            if self.chamfer and self.chamfer[2] is cell:
                continue
            cw = round(rnd.uniform(3, 6) * 2) / 2
            ch = round(rnd.uniform(2.5, 5) * 2) / 2
            cx = rnd.choice(["l", "r"])
            cy = rnd.choice(["t", "b"])
            bx0 = x0 if cx == "l" else x1 - cw
            by0 = y0 if cy == "t" else y1 - ch
            t = rnd.choice([3.5, 4.875]) / 12.0
            vx = bx0 + cw if cx == "l" else bx0
            hy = by0 + ch if cy == "t" else by0
            shaft = rnd.random() < 0.3
            wv = {"o": "v", "c": vx, "a": by0, "b": by0 + ch, "t": t,
                  "ext": False, "own": True}
            wh = {"o": "h", "c": hy, "a": bx0, "b": bx0 + cw, "t": t,
                  "ext": False, "own": True}
            self.walls += [wv, wh]
            box = [bx0, by0, bx0 + cw, by0 + ch]
            cell.append({"box": box, "cx": cx, "cy": cy})
            if shaft:
                self.shafts.append(box)
            else:
                self.cells.append(box + [{"closet": True, "door": wh
                                          if cw >= 3.5 else wv}])

    # ---- doors ------------------------------------------------------
    def meets(self, w):
        out = []
        for o in self.walls:
            if o is w or o["o"] == w["o"]:
                continue
            if o["a"] - 0.01 <= w["c"] <= o["b"] + 0.01 and \
                    w["a"] - 0.01 <= o["c"] <= w["b"] + 0.01:
                out.append(o["c"])
        return out

    def place(self, w, lo, hi, width, kind, side):
        """A gap of `width` on wall w between lo and hi, or None."""
        rnd = self.rnd
        ms = self.meets(w)
        used = [(g["g0"], g["g1"]) for g in self.gaps if g["w"] is w]
        for _ in range(40):
            if hi - lo < width + 1.6:
                return None
            g0 = round(rnd.uniform(lo + 0.8, hi - width - 0.8) * 4) / 4
            g1 = g0 + width
            if any(g0 - 1.2 < m < g1 + 1.2 for m in ms):
                continue
            if any(g0 < u1 + 1.5 and u0 - 1.5 < g1 for u0, u1 in used):
                continue
            if self.chamfer and w["ext"]:
                continue
            g = {"w": w, "g0": g0, "g1": g1, "kind": kind, "side": side,
                 "hinge": rnd.choice([0, 1]),
                 "sill": rnd.random() < 0.25}
            self.gaps.append(g)
            return g
        return None

    def doors(self):
        rnd = self.rnd
        for cell in self.cells:
            x0, y0, x1, y1 = cell[:4]
            info = cell[4] if len(cell) > 4 else {}
            if info.get("closet"):
                w = info["door"]
                lo, hi = (x0, x1) if w["o"] == "h" else (y0, y1)
                width = min(hi - lo - 1.7, rnd.choice([2.5, 3.0, 4.0]))
                if width >= 2.0:
                    kind = "bifold" if width >= 3 else "swing"
                    self.place(w, lo, hi, width, kind, rnd.choice([-1, 1]))
                continue
            n = 1 if (x1 - x0) * (y1 - y0) < 260 else rnd.choice([1, 2, 2])
            sides = []
            for w in self.walls:
                if w.get("own"):
                    continue
                if w["o"] == "h" and w["c"] in (y0, y1) and \
                        w["a"] <= x0 and w["b"] >= x1:
                    sides.append((w, x0, x1, 1 if w["c"] == y0 else -1))
                if w["o"] == "v" and w["c"] in (x0, x1) and \
                        w["a"] <= y0 and w["b"] >= y1:
                    sides.append((w, y0, y1, 1 if w["c"] == x0 else -1))
            rnd.shuffle(sides)
            sides.sort(key=lambda s: s[0]["ext"])       # interior first
            box = info.get("box")
            done = 0
            for w, lo, hi, side in sides:
                if done >= n:
                    break
                if box:                 # not behind the closet
                    blo, bhi = (box[0], box[2]) if w["o"] == "h" else \
                        (box[1], box[3])
                    on = (w["c"] in (box[1], box[3])) if w["o"] == "h" \
                        else (w["c"] in (box[0], box[2]))
                    if on:
                        if blo == lo:
                            lo = bhi
                        else:
                            hi = blo
                kind = rnd.choice(["swing"] * 5 + ["double", "cased",
                                                    "pocket"])
                width = {"swing": rnd.choice([2.67, 3.0, 3.0]),
                         "double": 6.0, "cased": rnd.choice([3.5, 4.0, 5.0]),
                         "pocket": 3.0}[kind]
                if self.place(w, lo, hi, width, kind, side):
                    done += 1

    # ---- the wall mask ----------------------------------------------
    def wall_rect(self, w, a=None, b=None, grow=True):
        a = w["a"] if a is None else a
        b = w["b"] if b is None else b
        e = 0.0
        if grow:                        # into the joints at both ends
            e = max([o["t"] for o in self.walls if o["o"] != w["o"]] +
                    [0]) / 2
            ea = e if any(abs(o["c"] - w["a"]) < 0.01 for o in self.walls
                          if o["o"] != w["o"]) else 0
            eb = e if any(abs(o["c"] - w["b"]) < 0.01 for o in self.walls
                          if o["o"] != w["o"]) else 0
            # only as far as the wall it joins is thick
            ja = max([o["t"] for o in self.walls if o["o"] != w["o"] and
                      abs(o["c"] - w["a"]) < 0.01] + [0]) / 2
            jb = max([o["t"] for o in self.walls if o["o"] != w["o"] and
                      abs(o["c"] - w["b"]) < 0.01] + [0]) / 2
            a, b = a - (ja if ea else 0), b + (jb if eb else 0)
        h = w["t"] / 2
        if w["o"] == "h":
            return (self.px(a), self.px(w["c"] - h), self.px(b),
                    self.px(w["c"] + h))
        return (self.px(w["c"] - h), self.px(a), self.px(w["c"] + h),
                self.px(b))

    def build_mask(self):
        shape = (self.px(self.H) + PAD, self.px(self.W) + PAD)
        closed = np.zeros(shape, np.uint8)
        for w in self.walls:
            x0, y0, x1, y1 = self.wall_rect(w)
            closed[y0:y1, x0:x1] = 1
        outside = np.zeros(shape, np.uint8)
        if self.chamfer:
            corner, d, _cell = self.chamfer
            W, H, te = self.W, self.H, self.t_ext
            cx = 0 if corner[1] == "l" else W
            cy = 0 if corner[0] == "t" else H
            sx = 1 if corner[1] == "l" else -1
            sy = 1 if corner[0] == "t" else -1
            a = (cx + sx * d, cy)
            b = (cx, cy + sy * d)
            # everything on the corner side of the diagonal is outside
            far = te + 1
            tri = np.array([[self.px(a[0] + sx * 0.0), self.px(cy - sy * far)],
                            [self.px(cx - sx * far), self.px(cy - sy * far)],
                            [self.px(cx - sx * far), self.px(b[1])],
                            [self.px(b[0]), self.px(b[1])],
                            [self.px(a[0]), self.px(a[1])]], np.int32)
            cv2.fillPoly(outside, [tri], 1)
            closed[outside > 0] = 0
            n = math.hypot(1, 1)
            ox, oy = sx * te / 2 / n, sy * te / 2 / n   # into the room
            ext = te / 2                   # run past the ends into joints
            ux, uy = (b[0] - a[0]) / (d * n), (b[1] - a[1]) / (d * n)
            a2 = (a[0] - ux * ext, a[1] - uy * ext)
            b2 = (b[0] + ux * ext, b[1] + uy * ext)
            quad = np.array([[self.px(a2[0] - ox), self.px(a2[1] - oy)],
                             [self.px(b2[0] - ox), self.px(b2[1] - oy)],
                             [self.px(b2[0] + ox), self.px(b2[1] + oy)],
                             [self.px(a2[0] + ox), self.px(a2[1] + oy)]],
                            np.int32)
            cv2.fillPoly(closed, [quad], 1)
            self.diag = (a, b)
        opened = closed.copy()
        for g in self.gaps:
            w = g["w"]
            x0, y0, x1, y1 = self.wall_rect(w, g["g0"], g["g1"], grow=False)
            if w["o"] == "h":
                opened[y0 - 2:y1 + 2, x0:x1] = 0
            else:
                opened[y0:y1, x0 - 2:x1 + 2] = 0
        self.closed, self.opened, self.outside = closed, opened, outside

    # ---- drawing ----------------------------------------------------
    def draw_walls(self):
        pg = self.page
        cnts, _h = cv2.findContours(self.opened, cv2.RETR_CCOMP,
                                    cv2.CHAIN_APPROX_SIMPLE)
        polys = []
        for c in cnts:
            q = [[int(p[0][0]), int(p[0][1])] for p in c]
            # an inside corner comes back cut off by one pixel ((3, 4),
            # (4, 3) for the corner at (3, 3)): put the corner back, so
            # every line is square as CAD draws it and the drawn room is
            # exactly the mask's
            out = []
            n = len(q)
            for i in range(n):
                a_, b_ = q[i], q[(i + 1) % n]
                out.append(a_)
                if abs(a_[0] - b_[0]) == 1 and abs(a_[1] - b_[1]) == 1:
                    for cx, cy in ((a_[0], b_[1]), (b_[0], a_[1])):
                        if self.opened[cy, cx]:
                            out.append([cx, cy])
                            break
            steps = sum(1 for i in range(len(out)) if max(
                abs(out[i][0] - out[i - 1][0]),
                abs(out[i][1] - out[i - 1][1])) == 1)
            if self.chamfer and steps > 12:
                # the wall across the corner: its pixel steps made one line
                c2 = cv2.approxPolyDP(np.array(out, np.int32).reshape(
                    -1, 1, 2), 1.3, True)
                q = [[float(p[0][0]), float(p[0][1])] for p in c2]
            else:
                q = [p_ for i, p_ in enumerate(out) if not (
                    (out[i - 1][0] == p_[0] == out[(i + 1) % len(out)][0]) or
                    (out[i - 1][1] == p_[1] == out[(i + 1) % len(out)][1]))]
            if len(q) >= 3:
                polys.append([self.px2pt(float(x), float(y)) for x, y in q])
        sh = pg.new_shape() if self.style == "solid" else Ink(pg)
        for p in polys:
            sh.draw_polyline(p + [p[0]])
        if self.style == "solid":
            sh.finish(color=(0, 0, 0), fill=(0.45, 0.45, 0.45), width=0.5,
                      even_odd=True, closePath=False)
        else:
            sh.finish(color=(0, 0, 0), width=0.7 if self.ppf >= 13 else 0.5,
                      closePath=False)
        sh.commit()
        if self.style == "hatch":
            hs = Ink(pg)
            step = 0.5 * self.ppf
            for w in self.walls:
                if not w["ext"]:
                    continue
                pieces, cur = [], w["a"]
                for g in sorted((g for g in self.gaps if g["w"] is w),
                                key=lambda g: g["g0"]):
                    pieces.append((cur, g["g0"]))
                    cur = g["g1"]
                pieces.append((cur, w["b"]))
                h = w["t"] / 2
                for s, e in pieces:
                    if w["o"] == "h":
                        r = fitz.Rect(self.pt(s, w["c"] - h),
                                      self.pt(e, w["c"] + h))
                    else:
                        r = fitz.Rect(self.pt(w["c"] - h, s),
                                      self.pt(w["c"] + h, e))
                    if self.chamfer and self._outside_pt(r.tl) and \
                            self._outside_pt(r.br):
                        continue
                    x = r.x0 - r.height
                    while x < r.x1:
                        a = fitz.Point(max(x, r.x0), r.y1 - max(0, r.x0 - x))
                        b = fitz.Point(min(x + r.height, r.x1),
                                       r.y0 + max(0, x + r.height - r.x1))
                        if not (self.chamfer and (self._outside_pt(a) or
                                                  self._outside_pt(b))):
                            hs.draw_line(a, b)
                        x += step
            hs.finish(color=(0.3, 0.3, 0.3), width=0.2, closePath=False)
            hs.commit()

    def _outside_pt(self, p):
        x, y = self.pt2px(p)
        x, y = int(round(x)), int(round(y))
        h, w = self.outside.shape
        return 0 <= y < h and 0 <= x < w and self.outside[y, x] > 0

    def draw_doors(self):
        pg, ppf = self.page, self.ppf
        thin = Ink(pg)
        dash = Ink(pg)
        for g in self.gaps:
            w = g["w"]
            h = w["t"] / 2
            side = g["side"]
            wd = g["g1"] - g["g0"]

            def P(along, across):
                return self.pt(along, w["c"] + across) if w["o"] == "h" \
                    else self.pt(w["c"] + across, along)
            face = side * h
            if g["kind"] in ("swing", "double"):
                leaves = [(g["g0"], 1, wd)] if g["kind"] == "swing" else \
                    [(g["g0"], 1, wd / 2), (g["g1"], -1, wd / 2)]
                if g["kind"] == "swing" and g["hinge"]:
                    leaves = [(g["g1"], -1, wd)]
                for hinge, d, lw in leaves:
                    tip = P(hinge, face + side * lw)
                    thin.draw_line(P(hinge, face), tip)
                    k = 0.5523
                    c1 = P(hinge + d * lw * k, face + side * lw)
                    c2 = P(hinge + d * lw, face + side * lw * k)
                    thin.draw_bezier(tip, c1, c2, P(hinge + d * lw, face))
            elif g["kind"] == "cased":
                dash.draw_line(P(g["g0"], -h), P(g["g1"], -h))
                dash.draw_line(P(g["g0"], h), P(g["g1"], h))
            elif g["kind"] == "pocket":
                t = 0.12
                a0 = g["g0"] - wd * 0.9 if g["hinge"] == 0 else g["g0"] + \
                    wd * 0.35
                thin.draw_rect(fitz.Rect(P(a0, -t / 2), P(a0 + wd * 0.95,
                                                          t / 2)).normalize())
            elif g["kind"] == "bifold":
                q = wd / 4
                for k in range(4):
                    a = g["g0"] + k * q
                    up = face + side * (q * 1.5 if k % 2 == 0 else 0)
                    dn = face + side * (0 if k % 2 == 0 else q * 1.5)
                    thin.draw_line(P(a, dn), P(a + q, up))
            if g["sill"] and g["kind"] != "cased":
                thin.draw_line(P(g["g0"], -face), P(g["g1"], -face))
        thin.finish(color=(0.25, 0.25, 0.25), width=0.35, closePath=False)
        thin.commit()
        dash.finish(color=(0.3, 0.3, 0.3), width=0.3, dashes="[3 3] 0",
                    closePath=False)
        dash.commit()
        _ = ppf

    # ---- rooms: truth, tags, what is in them ------------------------
    def kinds(self):
        rnd = self.rnd
        n, lab = cv2.connectedComponents((1 - self.closed).astype(np.uint8),
                                         connectivity=4)
        self.lab = lab
        k = 100 + 100 * rnd.randint(0, 2)
        for cell in self.cells:
            x0, y0, x1, y1 = cell[:4]
            info = cell[4] if len(cell) > 4 else {}
            box = info.get("box")
            ux0, uy0, ux1, uy1 = x0 + 0.8, y0 + 0.8, x1 - 0.8, y1 - 0.8
            if box:                      # the part clear of the closet
                if (x1 - x0) - (box[2] - box[0]) >= (y1 - y0) - \
                        (box[3] - box[1]):
                    if info["cx"] == "l":
                        ux0 = box[2] + 0.8
                    else:
                        ux1 = box[0] - 0.8
                else:
                    if info["cy"] == "t":
                        uy0 = box[3] + 0.8
                    else:
                        uy1 = box[1] - 0.8
            if self.chamfer and self.chamfer[2] is cell:
                corner, d, _c = self.chamfer
                if corner[1] == "l":
                    ux0 = x0 + d * 0.75 + 0.8
                else:
                    ux1 = x1 - d * 0.75 - 0.8
            w, h = ux1 - ux0, uy1 - uy0
            area = (x1 - x0) * (y1 - y0)
            if info.get("closet"):
                kind = "closet"
            elif max(w, h) > 3.2 * min(w, h):
                kind = "corridor"
            elif area < 110:
                kind = rnd.choice(["storage", "mech", "toilet", "stair"])
            elif area < 260:
                kind = rnd.choice(["toilet", "office", "exam", "shower",
                                   "storage", "break", "mech", "office"])
            else:
                kind = rnd.choice(["conf", "office", "break", "office",
                                   "storage", "exam"])
            name = rnd.choice(NAMES[kind])
            cx, cy = (ux0 + ux1) / 2, (uy0 + uy1) / 2
            L = int(lab[self.px(cy), self.px(cx)])
            if L == 0:
                continue
            m = lab == L
            # the walls are drawn through the centres of their edge
            # pixels: the drawn room is half a pixel bigger all round
            # than the open pixels inside it
            edge = int((m[:, 1:] != m[:, :-1]).sum() +
                       (m[1:] != m[:-1]).sum())
            sf = (float(m.sum()) + edge / 2.0 + 1.0) / PXF ** 2
            feats = [kind]
            if box:
                feats.append("L-shape")
            if self.chamfer and self.chamfer[2] is cell:
                feats.append("angled")
            self.rooms.append({"name": name, "no": str(k), "kind": kind,
                               "use": [ux0, uy0, ux1, uy1], "c": (cx, cy),
                               "sf": sf, "label": L, "feats": feats,
                               "cell": cell[:4]})
            k += 1

    def furnish(self):
        pg, rnd, ppf = self.page, self.rnd, self.ppf
        thin = Ink(pg)
        faint = Ink(pg)
        dash = Ink(pg)

        def R(x0, y0, x1, y1):
            return fitz.Rect(self.pt(x0, y0), self.pt(x1, y1))
        for r in self.rooms:
            x0, y0, x1, y1 = r["use"]
            # back to the wall faces (use is 0.8 ft inside the wall lines)
            fx0, fy0, fx1, fy1 = x0 - 0.45, y0 - 0.45, x1 + 0.45, y1 + 0.45
            w, h = fx1 - fx0, fy1 - fy0
            kind = r["kind"]
            cx, cy = r["c"]
            if kind == "toilet" and w >= 7 and h >= 7:
                step = rnd.choice([1.0, 2.0])
                gx = fx0 + step
                while gx < fx1 - 0.2:
                    faint.draw_line(self.pt(gx, fy0), self.pt(gx, fy1))
                    gx += step
                gy = fy0 + step
                while gy < fy1 - 0.2:
                    faint.draw_line(self.pt(fx0, gy), self.pt(fx1, gy))
                    gy += step
                r["feats"].append("tile")
                if w >= 9:
                    n = int((w - 4) // 3)
                    for i in range(n):
                        sx = fx0 + 3 * (i + 1)
                        thin.draw_line(self.pt(sx, fy0), self.pt(sx, fy0 + 5))
                        thin.draw_line(self.pt(sx - 3, fy0 + 5),
                                       self.pt(sx - 2.2, fy0 + 5))
                        thin.draw_line(self.pt(sx - 0.2, fy0 + 5),
                                       self.pt(sx, fy0 + 5))
                        thin.draw_oval(R(sx - 2.2, fy0 + 0.4, sx - 0.8,
                                         fy0 + 2.4))
                    if n:
                        r["feats"].append("stalls")
                    thin.draw_rect(R(fx0, fy1 - 2, fx0 + min(w, 6), fy1))
                    thin.draw_oval(R(fx0 + 1, fy1 - 1.6, fx0 + 2.4,
                                     fy1 - 0.4))
            elif kind == "office":
                thin.draw_rect(R(fx1 - 6, fy1 - 3.2, fx1 - 1, fy1 - 0.7))
                thin.draw_circle(self.pt(fx1 - 3.5, fy1 - 4.4), 0.8 * ppf)
            elif kind == "conf" and w >= 10 and h >= 8:
                thin.draw_oval(R(cx - w * 0.3, cy + 1.5, cx + w * 0.3,
                                 cy + 1.5 + min(4, h * 0.25)))
                for i in range(4):
                    thin.draw_circle(self.pt(cx - w * 0.22 + i * w * 0.15,
                                             cy + 0.8), 0.6 * ppf)
            elif kind == "break" and w >= 8 and h >= 8:
                thin.draw_rect(R(fx0, fy0, fx1, fy0 + 2))        # base
                thin.draw_rect(R(fx0, fy0 + 2, fx0 + 2, fy0 + min(h, 9)))
                dash.draw_line(self.pt(fx0, fy0 + 1), self.pt(fx1, fy0 + 1))
                thin.draw_rect(R(fx1 - 3, fy0 + 0.1, fx1 - 0.2, fy0 + 2.6))
                thin.draw_line(self.pt(fx1 - 3, fy0 + 0.1),
                               self.pt(fx1 - 0.2, fy0 + 2.6))
                thin.draw_oval(R(fx0 + 3, fy0 + 0.4, fx0 + 5, fy0 + 1.7))
                r["feats"].append("casework")
            elif kind == "storage" and w >= 6 and h >= 6:
                # shelving: long narrow boxes that look like hollow walls
                thin.draw_rect(R(fx0 + 0.1, fy0 + 0.1, fx0 + 1.6, fy1 - 0.1))
                if w >= 10:
                    thin.draw_rect(R(fx1 - 1.6, fy0 + 0.1, fx1 - 0.1,
                                     fy1 - 3.5))
                r["feats"].append("shelving")
            elif kind == "shower" and w >= 8 and h >= 8:
                thin.draw_rect(R(fx0, fy0 + 2, fx0 + 1.25, fy0 + 4.6))
                thin.draw_rect(R(fx0 + 0.15, fy0 + 2.15, fx0 + 1.1,
                                 fy0 + 4.45))
                thin.draw_circle(self.pt(cx, cy + 2), 0.25 * ppf)
                for ex, ey in ((fx0, fy0), (fx1, fy0), (fx0, fy1),
                               (fx1, fy1)):
                    faint.draw_line(self.pt(ex, ey), self.pt(cx, cy + 2))
                thin.draw_line(self.pt(fx0 + 4, fy0), self.pt(fx0 + 4,
                                                             fy0 + 4))
                r["feats"].append("bench")
            elif kind == "mech" and w >= 6 and h >= 6:
                e = R(fx1 - 4.5, fy1 - 4, fx1 - 1, fy1 - 1)
                thin.draw_rect(e)
                thin.draw_line(e.tl, e.br)
                thin.draw_line(e.tr, e.bl)
                dash.draw_rect(R(fx1 - 5, fy1 - 4.5, fx1 - 0.5, fy1 - 0.5))
            elif kind == "stair" and h >= 7:
                ty = fy0 + 0.2
                while ty < fy1 - 3.5:
                    thin.draw_line(self.pt(fx0, ty), self.pt(fx1, ty))
                    ty += 11 / 12.0
                thin.draw_line(self.pt((fx0 + fx1) / 2, fy1 - 1),
                               self.pt((fx0 + fx1) / 2, fy0 + 1))
                r["feats"].append("treads")
            elif kind == "exam" and w >= 8 and h >= 8:
                thin.draw_rect(R(fx0, fy1 - 2, fx0 + 5, fy1))
                thin.draw_rect(R(fx1 - 6.5, fy0 + 2, fx1 - 0.5, fy0 + 4.2))
                r["feats"].append("casework")
        for b in self.shafts:
            thin.draw_line(self.pt(b[0] + 0.3, b[1] + 0.3),
                           self.pt(b[2] - 0.3, b[3] - 0.3))
            thin.draw_line(self.pt(b[2] - 0.3, b[1] + 0.3),
                           self.pt(b[0] + 0.3, b[3] - 0.3))
        thin.finish(color=(0.3, 0.3, 0.3), width=0.3, closePath=False)
        thin.commit()
        faint.finish(color=(0.6, 0.6, 0.6), width=0.15, closePath=False)
        faint.commit()
        dash.finish(color=(0.4, 0.4, 0.4), width=0.25, dashes="[4 3] 0",
                    closePath=False)
        dash.commit()

    def annotate(self):
        """Grid lines, dimensions, leaders, tags, legend, title block."""
        pg, rnd, ppf = self.page, self.rnd, self.ppf
        W, H = self.W, self.H
        gs = Ink(pg)
        vs = sorted({w["c"] for w in self.walls if w["o"] == "v" and
                     not w.get("own")})
        hs_ = sorted({w["c"] for w in self.walls if w["o"] == "h" and
                      not w.get("own")})
        gv = rnd.sample(vs, min(len(vs), 4)) + [rnd.uniform(4, W - 4)]
        gh = rnd.sample(hs_, min(len(hs_), 3)) + [rnd.uniform(4, H - 4)]
        bub = []
        for x in gv:
            a, b = self.pt(x, -5), self.pt(x, H + 2)
            gs.draw_line(a, b)
            bub.append(fitz.Point(a.x, a.y - 9))
        for y in gh:
            a, b = self.pt(-5, y), self.pt(W + 2, y)
            gs.draw_line(a, b)
            bub.append(fitz.Point(a.x - 9, a.y))
        gs.finish(color=(0.45, 0.45, 0.45), width=0.2,
                  dashes="[14 3 2 3] 0", closePath=False)
        gs.commit()
        cs = Ink(pg)
        for i, c in enumerate(bub):
            cs.draw_circle(c, 9)
        cs.finish(color=(0.2, 0.2, 0.2), width=0.4)
        cs.commit()
        for i, c in enumerate(bub):
            pg.insert_text((c.x - 3, c.y + 3), "ABCDEFGHJK"[i % 10]
                           if i >= len(gv) else str(i + 1), fontsize=8)
        # dimension strings: outside, and two through the rooms
        ds = Ink(pg)

        def dim(a, b, text):
            ds.draw_line(a, b)
            for p in (a, b):
                ds.draw_line(fitz.Point(p.x - 3, p.y + 3),
                             fitz.Point(p.x + 3, p.y - 3))
            m = fitz.Point((a.x + b.x) / 2, (a.y + b.y) / 2)
            if abs(a.y - b.y) < 1:
                pg.insert_text((m.x - 12, m.y - 2), text, fontsize=6.5)
            else:
                pg.insert_text((m.x + 2, m.y), text, fontsize=6.5)
        dim(self.pt(0, -3), self.pt(W, -3), f"{int(W)}'-{int(W % 1 * 12)}\"")
        dim(self.pt(-3, 0), self.pt(-3, H), f"{int(H)}'-{int(H % 1 * 12)}\"")
        for r in rnd.sample(self.rooms, min(3, len(self.rooms))):
            x0, y0, x1, y1 = r["cell"]
            if r["kind"] == "closet":
                continue
            if rnd.random() < 0.5:
                y = y0 + (y1 - y0) * rnd.uniform(0.7, 0.85)
                dim(self.pt(x0 + 0.3, y), self.pt(x1 - 0.3, y),
                    f"{int(x1 - x0 - 0.5)}'-6\"")
            else:
                x = x0 + (x1 - x0) * rnd.uniform(0.12, 0.25)
                dim(self.pt(x, y0 + 0.3), self.pt(x, y1 - 0.3),
                    f"{int(y1 - y0 - 0.5)}'-6\"")
            r["feats"].append("dim across")
        # leaders from notes outside into two rooms
        for i, r in enumerate(rnd.sample(self.rooms, min(2,
                                                         len(self.rooms)))):
            cx, cy = r["c"]
            tip = self.pt(cx + 1.5, cy - 1.5)
            tail = self.pt(W + 6, 4 + i * 6)
            ds.draw_line(tip, fitz.Point(tail.x - 20, tail.y))
            ds.draw_line(fitz.Point(tail.x - 20, tail.y), tail)
            pg.insert_text((tail.x + 2, tail.y + 2),
                           ["PROVIDE BLOCKING", "SEE DETAIL 4/A501"][i],
                           fontsize=6.5)
            r["feats"].append("leader")
        ds.finish(color=(0.3, 0.3, 0.3), width=0.25, closePath=False)
        ds.commit()
        # room tags
        bx = Ink(pg)
        fs = self.font
        for r in self.rooms:
            want_sf = self.sf_mode == "all" or (self.sf_mode == "mixed" and
                                                rnd.random() < 0.6)
            cx, cy = r["c"]
            if r["kind"] == "closet":
                fs2 = fs * 0.8
                p = self.pt(cx, cy)
                pg.insert_text((p.x - fs2 * 1.2, p.y - 1), r["name"][0],
                               fontsize=fs2)
                pg.insert_text((p.x - fs2 * 0.9, p.y + fs2), r["no"],
                               fontsize=fs2)
                r["tag_sf"] = None
                r["tagpt"] = p
                continue
            p = self.pt(cx, cy)
            lines = list(r["name"])
            y = p.y - fs * (len(lines) + 1) / 2
            for ln in lines:
                wd = fitz.get_text_length(ln, fontsize=fs)
                pg.insert_text((p.x - wd / 2, y), ln, fontsize=fs)
                y += fs * 1.15
            wd = fitz.get_text_length(r["no"], fontsize=fs)
            pg.insert_text((p.x - wd / 2, y + (2 if self.boxed else 0)),
                           r["no"], fontsize=fs)
            if self.boxed:
                bx.draw_rect(fitz.Rect(p.x - wd / 2 - 3, y - fs + 1,
                                       p.x + wd / 2 + 3, y + 4))
            if want_sf:
                y += fs * 1.25 + (4 if self.boxed else 0)
                s = f"{round(r['sf'])} SF"
                wd = fitz.get_text_length(s, fontsize=fs)
                pg.insert_text((p.x - wd / 2, y), s, fontsize=fs)
            r["tag_sf"] = round(r["sf"]) if want_sf else None
            r["tagpt"] = p
        bx.finish(color=(0.2, 0.2, 0.2), width=0.3)
        bx.commit()
        # legend with a sample tag, a key plan, notes and the title block
        tb = Ink(pg)
        tb.draw_rect(fitz.Rect(30, 30, 2562, 1698))
        tb.draw_line((2220, 30), (2220, 1698))
        for y in (300, 760, 1180, 1500, 1580):
            tb.draw_line((2220, y), (2562, y))
        tb.finish(color=(0, 0, 0), width=1.4, closePath=False)
        tb.commit()
        pg.insert_text((2240, 330), "LEGEND", fontsize=11)
        pg.insert_text((2260, 370), "ROOM NAME", fontsize=fs)
        pg.insert_text((2272, 370 + fs * 1.2), "101", fontsize=fs)
        pg.insert_text((2264, 370 + fs * 2.4), "150 SF", fontsize=fs)
        pg.insert_text((2330, 380), "ROOM TAG", fontsize=7)
        pg.insert_text((2240, 800), "GENERAL NOTES", fontsize=11)
        for i, s in enumerate([
                "1. ALL DIMENSIONS ARE TO FACE OF STUD U.N.O.",
                "2. VERIFY ALL CONDITIONS IN THE FIELD.",
                "3. SEE A601 FOR DOOR SCHEDULE AND HARDWARE.",
                "4. PROVIDE BLOCKING AT ALL WALL MOUNTED ITEMS.",
                "5. STORAGE ROOM SHELVING BY OWNER."]):
            pg.insert_text((2240, 822 + i * 12), s, fontsize=6.5)
        kp = Ink(pg)                 # key plan: a thick small box
        kp.draw_rect(fitz.Rect(2260, 1220, 2400, 1320))
        kp.draw_line((2330, 1220), (2330, 1320))
        kp.finish(color=(0, 0, 0), width=1.2)
        kp.commit()
        pg.insert_text((2260, 1340), "KEY PLAN", fontsize=8)
        label = {18.0: "1/4\" = 1'-0\"", 13.5: "3/16\" = 1'-0\"",
                 9.0: "1/8\" = 1'-0\""}[ppf]
        pg.insert_text((OX, OY + (H + 7) * ppf), "FLOOR PLAN", fontsize=14)
        pg.insert_text((OX, OY + (H + 7) * ppf + 16), f"SCALE: {label}",
                       fontsize=9)
        pg.insert_text((2240, 1540), "FIRST FLOOR PLAN", fontsize=12)
        pg.insert_text((2400, 1660), f"A-{101 + pg.number}", fontsize=26)

    def build(self):
        self.layout()
        self.doors()
        self.build_mask()
        self.draw_walls()
        self.draw_doors()
        self.kinds()
        self.furnish()
        self.annotate()
        return self


def _poly_px(sheet, pts):
    return np.array([[*sheet.pt2px(p)] for p in pts], np.float32)


def _inside(poly, xy):
    return cv2.pointPolygonTest(poly, (float(xy[0]), float(xy[1])),
                                False) >= 0


def score(n=6, seed=21, verbose=True, out=None, only=None, debug=False):
    from app import autotakeoff
    rnd = random.Random(seed)
    doc = fitz.open()
    sheets = []
    for i in range(n):
        ppf = [18.0, 18.0, 13.5, 9.0, 18.0, 9.0, 13.5][i % 7]
        sheets.append(Sheet(doc, rnd, ppf).build())
    if out:
        os.makedirs(out, exist_ok=True)
        doc.save(os.path.join(out, "hard.pdf"))
    rows, extra, missed_tags = [], 0, 0
    took = 0.0
    for i, s in enumerate(sheets):
        if only is not None and i != only:
            continue
        sc = {"ppu": s.ppf, "unit": "ft"}
        info = {}
        t = time.perf_counter()
        found, missed = autotakeoff.all_rooms(doc[i], sc, info=info)
        took += time.perf_counter() - t
        if debug:
            pg = autotakeoff.cached_page(doc[i])
            tg = autotakeoff.room_tags(pg, {})
            tg2 = autotakeoff.room_labels(pg, skip=[t_["pt"] for t_ in tg],
                                          info={})
            print(f"--- plan {i}: app tags {len(tg)} with SF, {len(tg2)} "
                  f"by name; truth rooms {len(s.rooms)}; info "
                  f"{ {k: v for k, v in info.items() if k != 'partial'} }")
            for t_ in tg + tg2:
                print(f"   tag {str(t_.get('name'))[:28]:28s} sf "
                      f"{t_.get('sf')}  at ({t_['pt'].x:.0f}, "
                      f"{t_['pt'].y:.0f})")
            for r_ in found:
                print(f"   found {str(r_.get('name'))[:26]:26s} "
                      f"{r_['sqft']:8.1f} door {r_.get('door')} "
                      f"flags {r_.get('flags')}")
            for m_ in missed:
                print(f"   missed {str(m_.get('name'))[:26]:26s} "
                      f"sf {m_.get('sf')} why {m_.get('why')}")
            pl = autotakeoff.Plan(pg, sc, claimed=False)
            print(f"   plan: layers {len(pl.layers)}, fine pen "
                  f"{autotakeoff.fine_pen(pg)}, vector walls "
                  f"{pl.vector_walls}, doors closed {pl.doors_closed}, "
                  f"wall layers {pl.wall_layers}, inset {pl.inset_px}")
            fp = autotakeoff.fine_pen(pg)
            if fp:
                hv = autotakeoff.vector_ink(pg, pl.zoom, pl.shape,
                                            min_width=fp * 1.15)
                print("   heavy ink:", None if hv is None else int(hv.sum()))
            if out:
                for li, m_ in enumerate(pl.layers):
                    cv2.imwrite(os.path.join(out, f"walls{i}_{li}.png"),
                                (1 - m_) * 255)
        polys = [(_poly_px(s, r["pts"]), r) for r in found]
        used = set()
        for r in s.rooms:
            tp = s.pt2px(r["tagpt"])
            best = None
            for k, (poly, res) in enumerate(polys):
                if _inside(poly, tp):
                    e = (res["sqft"] - r["sf"]) / r["sf"] * 100
                    if best is None or abs(e) < abs(best[0]):
                        best = (e, k, res)
            row = {"plan": i, "ppf": s.ppf, "style": s.style, "name":
                   " ".join(r["name"]) + " " + r["no"], "sf": r["sf"],
                   "feats": r["feats"], "tag_sf": r["tag_sf"]}
            if best is None:
                row.update(err=None, got=None, flags=[])
            else:
                used.add(best[1])
                row.update(err=best[0], got=best[2]["sqft"],
                           flags=best[2].get("flags") or [],
                           review=best[2].get("review"),
                           conf=best[2].get("trace_confidence"))
            rows.append(row)
        extra += sum(1 for k in range(len(polys)) if k not in used)
        missed_tags += len(missed)
        if out:
            _picture(doc[i], s, found, os.path.join(out, f"plan{i}.png"))
    errs = [abs(r["err"]) for r in rows if r["err"] is not None]
    nrooms = len(rows)
    res = {"rooms": nrooms, "found": len(errs),
           "within1": sum(e <= 1 for e in errs),
           "within2": sum(e <= 2 for e in errs),
           "within5": sum(e <= 5 for e in errs),
           "median": statistics.median(errs) if errs else None,
           "extra": extra,
           "total_err_pct": 100 * (sum(r["got"] for r in rows if r["got"])
                                   - sum(r["sf"] for r in rows)) /
           max(1.0, sum(r["sf"] for r in rows)),
           "seconds": round(took, 1)}
    # a wrong number nobody is warned about is the worst case
    res["silent_wrong"] = sum(1 for r in rows if r["err"] is not None and
                              abs(r["err"]) > 2 and not r.get("review")
                              and not r["flags"])
    if verbose:
        bad = [r for r in rows if r["err"] is None or abs(r["err"]) > SHOW]
        for r in sorted(bad, key=lambda r: (r["plan"], r["name"])):
            e = "MISSED " if r["err"] is None else f"{r['err']:+6.1f}%"
            print(f"plan {r['plan']} ({r['ppf']:g} {r['style']:6s}) "
                  f"{r['name'][:24]:24s} {r['sf']:7.1f} SF {e}  "
                  f"[{', '.join(r['feats'])}]"
                  f"{' tagSF' if r['tag_sf'] else ''}  "
                  f"{'; '.join(r['flags'])[:60]}")
        by = {}
        for r in rows:
            for f in r["feats"] + [f"scale {r['ppf']:g}", r["style"],
                                   "sf tag" if r["tag_sf"] else "no sf tag"]:
                b = by.setdefault(f, [0, 0])
                b[1] += 1
                b[0] += r["err"] is not None and abs(r["err"]) <= 2
        print()
        for f, (g, t) in sorted(by.items(), key=lambda kv: kv[1][0] /
                                kv[1][1]):
            print(f"  {f:14s} {g:3d}/{t:3d} within 2% "
                  f"({100 * g / t:.0f}%)")
        print()
        print(f"rooms {res['rooms']}: found {res['found']} "
              f"({100 * res['found'] / nrooms:.1f}%), within 1% "
              f"{res['within1']} ({100 * res['within1'] / nrooms:.1f}%), "
              f"within 2% {res['within2']} "
              f"({100 * res['within2'] / nrooms:.1f}%), within 5% "
              f"{res['within5']} ({100 * res['within5'] / nrooms:.1f}%)")
        print(f"median error {res['median']:.2f}%; results that match no "
              f"room: {extra}; tags not traced: {missed_tags}; wrong by "
              f"over 2% with no flag: {res['silent_wrong']}; total area "
              f"{res['total_err_pct']:+.2f}%; {res['seconds']} s")
    return res


def walls_score(n=7, seed=21, verbose=True):
    """Auto Walls on the same plans: wall length found against what is
    drawn, in all and by thickness. Openings are not wall: a wall's
    length is its run less its door gaps."""
    from app import autowalls
    rnd = random.Random(seed)
    doc = fitz.open()
    tot_t = tot_g = 0.0
    tot_alt = [0.0]
    rows = []
    for i in range(n):
        ppf = [18.0, 18.0, 13.5, 9.0, 18.0, 9.0, 13.5][i % 7]
        s = Sheet(doc, rnd, ppf).build()
        truth = {}
        for w in s.walls:
            run = w["b"] - w["a"] - sum(g["g1"] - g["g0"] for g in s.gaps
                                        if g["w"] is w)
            if s.chamfer and w["ext"]:
                run -= s.chamfer[1] / 2          # each cut wall, roughly
            k = round(w["t"] * 12, 1)
            truth[k] = truth.get(k, 0.0) + run
        if s.chamfer:
            k = round(s.t_ext * 12, 1)
            truth[k] = truth.get(k, 0.0) + s.chamfer[1] * math.sqrt(2)
        try:
            ws = autowalls.walls(doc[i], ppf, "ft")
        except autowalls.AutoWallsError as e:
            print("plan", i, "no walls:", e)
            continue
        got = {}
        for w in ws:
            k = round(w["thickness"], 1)
            got[k] = got.get(k, 0.0) + w["length"]
        if hasattr(autowalls, "walls_by_pen"):
            alt = {}
            for w in autowalls.walls_by_pen(doc[i], ppf, "ft"):
                k = round(w["thickness"], 1)
                alt[k] = alt.get(k, 0.0) + w["length"]
            if verbose:
                ta = sum(truth.values())
                print(f"plan {i}: by pen {sum(alt.values()):8.1f} LF "
                      f"({100 * (sum(alt.values()) - ta) / ta:+.1f}%)  ",
                      {k: round(v, 1) for k, v in sorted(alt.items())})
            tot_alt[0] += sum(alt.values())
        t, g = sum(truth.values()), sum(got.values())
        tot_t += t
        tot_g += g
        rows.append((i, ppf, s.style, t, g))
        if verbose:
            print(f"plan {i} ({ppf:g} {s.style:6s}) walls drawn {t:8.1f} LF"
                  f", found {g:8.1f} LF ({100 * (g - t) / t:+.1f}%)")
            print("     drawn:", {k: round(v, 1) for k, v in
                                  sorted(truth.items())})
            print("     found:", {k: round(v, 1) for k, v in
                                  sorted(got.items())})
    if verbose and tot_t:
        print(f"all plans: drawn {tot_t:.1f} LF, found {tot_g:.1f} LF "
              f"({100 * (tot_g - tot_t) / tot_t:+.2f}%); by pen "
              f"{tot_alt[0]:.1f} LF "
              f"({100 * (tot_alt[0] - tot_t) / tot_t:+.2f}%)")
    return rows


def _picture(page, s, found, path):
    """The plan with the truth (green) and the traces (red)."""
    z = 1.6
    pm = page.get_pixmap(matrix=fitz.Matrix(z, z), clip=fitz.Rect(
        OX - 120, OY - 120, OX + s.W * s.ppf + 160, OY + s.H * s.ppf + 160))
    img = np.frombuffer(pm.samples, np.uint8).reshape(pm.h, pm.w, pm.n)
    img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR if pm.n == 3 else
                       cv2.COLOR_RGBA2BGR).copy()

    def P(p):
        return [int((p.x - OX + 120) * z), int((p.y - OY + 120) * z)]
    for r in s.rooms:
        m = (s.lab == r["label"]).astype(np.uint8)
        cs, _h = cv2.findContours(m, cv2.RETR_EXTERNAL,
                                  cv2.CHAIN_APPROX_SIMPLE)
        for c in cs:
            pts = np.array([P(s.px2pt(float(q[0][0]), float(q[0][1])))
                            for q in c], np.int32)
            cv2.polylines(img, [pts], True, (0, 170, 0), 3)
    for r in found:
        pts = np.array([P(p) for p in r["pts"]], np.int32)
        cv2.polylines(img, [pts], True, (0, 0, 230), 1)
    cv2.imwrite(path, img)


if __name__ == "__main__":
    a = sys.argv[1:]
    seed = int(a[a.index("--seed") + 1]) if "--seed" in a else 21
    out = a[a.index("--out") + 1] if "--out" in a else None
    only = int(a[a.index("--only") + 1]) if "--only" in a else None
    n = int(a[0]) if a and a[0].isdigit() else 6
    if "--show" in a:
        SHOW = float(a[a.index("--show") + 1])
    if "--walls" in a:
        walls_score(n, seed)
    else:
        score(n, seed, out=out, only=only, debug="--debug" in a)
