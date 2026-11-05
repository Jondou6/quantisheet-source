"""Auto Takeoff Rooms on drawings drawn the way CAD really draws them.

    python tools/accuracy_real.py [PLANS] [--seed N]

tools/accuracy.py draws walls as solid filled bands, which is the easy
case. These plans draw every wall as two thin face lines (hollow), with
partitions 3-1/2" to 6" and 8" exterior walls, door gaps with jambs and
swings, wall-type tags and dimension text sitting on walls, a hatched
floor, and some rooms tagged only by name and number (no SF). Scores:
rooms found within 5% / 12% of their true net area, and misses.
"""
import os
import random
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import fitz                                                   # noqa: E402

PPF = 18.0
NAMES = ["OFFICE", "EXAM", "STORAGE", "KENNEL", "LAB", "BREAK", "CONF",
         "TOILET", "JANITOR", "LOBBY", "PREP", "SURGERY"]


def split(rect, rnd, depth, rooms, segs):
    if depth == 0 or (rect.width < 16 * PPF and rect.height < 16 * PPF):
        rooms.append(rect)
        return
    horiz = rect.height > rect.width if rnd.random() < 0.8 else \
        rnd.random() < 0.5
    if horiz and rect.height >= 16 * PPF:
        y = rect.y0 + PPF * round(rnd.uniform(0.35, 0.65) * rect.height /
                                  PPF)
        segs.append(("h", y, rect.x0, rect.x1))
        split(fitz.Rect(rect.x0, rect.y0, rect.x1, y), rnd, depth - 1, rooms,
              segs)
        split(fitz.Rect(rect.x0, y, rect.x1, rect.y1), rnd, depth - 1, rooms,
              segs)
    elif rect.width >= 16 * PPF:
        x = rect.x0 + PPF * round(rnd.uniform(0.35, 0.65) * rect.width / PPF)
        segs.append(("v", x, rect.y0, rect.y1))
        split(fitz.Rect(rect.x0, rect.y0, x, rect.y1), rnd, depth - 1, rooms,
              segs)
        split(fitz.Rect(x, rect.y0, rect.x1, rect.y1), rnd, depth - 1, rooms,
              segs)
    else:
        rooms.append(rect)


def plan(doc, rnd):
    pg = doc.new_page(width=2592, height=1728)
    bld = fitz.Rect(180, 180, 180 + PPF * rnd.randint(70, 95),
                    180 + PPF * rnd.randint(48, 62))
    rooms, segs = [], []
    split(bld, rnd, 4, rooms, segs)
    t_ext = 8 / 12 * PPF
    t_int = rnd.choice([3.5, 4.875, 6.0]) / 12 * PPF
    walls = [("h", bld.y0, bld.x0, bld.x1, t_ext),
             ("h", bld.y1, bld.x0, bld.x1, t_ext),
             ("v", bld.x0, bld.y0, bld.y1, t_ext),
             ("v", bld.x1, bld.y0, bld.y1, t_ext)]
    walls += [(o, c, a, b, t_int) for o, c, a, b in segs]
    # door gaps on interior walls, away from the walls that meet them
    sh = pg.new_shape()
    arcs = pg.new_shape()
    for o, c, a, b, t in walls:
        gaps = []
        if t == t_int and (b - a) > 10 * PPF:
            meets = []                   # where other walls meet this one
            for oo, cc, aa, bb, tt in walls:
                if oo != o and aa - 1 <= c <= bb + 1 and a < cc < b:
                    meets.append(cc)
            for _ in range(20):
                g = rnd.uniform(a + 2 * PPF, b - 5 * PPF)
                if all(abs(g - m) > 3 * PPF and abs(g + 3 * PPF - m) > 1.5 *
                       PPF for m in meets):
                    gaps.append((g, g + 3 * PPF))
                    break
        pieces, cur = [], a
        for g0, g1 in gaps:
            pieces.append((cur, g0))
            cur = g1
        pieces.append((cur, b))
        for s, e in pieces:
            for off in (-t / 2, t / 2):
                if o == "h":
                    sh.draw_line((s, c + off), (e, c + off))
                else:
                    sh.draw_line((c + off, s), (c + off, e))
        for g0, g1 in gaps:                       # jambs and a swing
            for g in (g0, g1):
                if o == "h":
                    sh.draw_line((g, c - t / 2), (g, c + t / 2))
                else:
                    sh.draw_line((c - t / 2, g), (c + t / 2, g))
            if o == "h":
                arcs.draw_line((g0, c + t / 2), (g0, c + t / 2 + 3 * PPF))
                arcs.draw_curve((g0, c + t / 2 + 3 * PPF),
                                (g1, c + t / 2 + 3 * PPF), (g1, c + t / 2))
            else:
                arcs.draw_line((c + t / 2, g0), (c + t / 2 + 3 * PPF, g0))
                arcs.draw_curve((c + t / 2 + 3 * PPF, g0),
                                (c + t / 2 + 3 * PPF, g1), (c + t / 2, g1))
    sh.finish(color=(0, 0, 0), width=0.7, closePath=False)
    sh.commit()
    arcs.finish(color=(0.35, 0.35, 0.35), width=0.35, closePath=False)
    arcs.commit()
    truth = []
    for k, r in enumerate(rooms):
        def face(side):
            # wall thickness on each side of this room
            x0 = r.x0 + (t_ext if abs(r.x0 - bld.x0) < 1 else t_int) / 2
            x1 = r.x1 - (t_ext if abs(r.x1 - bld.x1) < 1 else t_int) / 2
            y0 = r.y0 + (t_ext if abs(r.y0 - bld.y0) < 1 else t_int) / 2
            y1 = r.y1 - (t_ext if abs(r.y1 - bld.y1) < 1 else t_int) / 2
            return fitz.Rect(x0, y0, x1, y1)
        inner = face(None)
        sf = inner.width * inner.height / PPF ** 2
        truth.append({"rect": inner, "sf": sf, "name":
                      f"{rnd.choice(NAMES)} {100 + k}",
                      "sf_tag": rnd.random() < 0.7})
    # hatch one floor, furniture in some rooms (thin lines)
    hs = pg.new_shape()
    hr = rnd.choice(truth)["rect"]
    x = hr.x0 + 6
    while x < hr.x1 + hr.height:
        a = fitz.Point(x, hr.y0 + 4)
        b = fitz.Point(x - hr.height + 8, hr.y1 - 4)
        hs.draw_line(a, b)
        x += PPF
    for t in truth:
        r = t["rect"]
        if r.width > 10 * PPF and r.height > 10 * PPF:
            hs.draw_rect(fitz.Rect(r.x1 - 6 * PPF, r.y1 - 3 * PPF,
                                   r.x1 - PPF, r.y1 - PPF))
    hs.finish(color=(0.5, 0.5, 0.5), width=0.25, closePath=False)
    hs.commit()
    for t in truth:
        c = t["rect"]
        cx, cy = (c.x0 + c.x1) / 2 - 30, (c.y0 + c.y1) / 2
        pg.insert_text((cx, cy), t["name"], fontsize=8)
        if t["sf_tag"]:
            pg.insert_text((cx, cy + 11), f"{round(t['sf'])} SF", fontsize=8)
    # wall-type tags and dimension text sitting right on interior walls
    for o, c, a, b, t in walls[4:]:
        m = (a + b) / 2 + PPF
        if o == "h":
            pg.insert_text((m, c + 3), "W2", fontsize=7)
        else:
            pg.insert_text((c - 5, m), "W2", fontsize=7)
    pg.insert_text(((bld.x0 + bld.x1) / 2, bld.y0 - 30), "62'-4\"",
                   fontsize=9)
    sh = pg.new_shape()
    sh.draw_line((bld.x0, bld.y0 - 36), (bld.x1, bld.y0 - 36))
    sh.finish(color=(0.4, 0.4, 0.4), width=0.3)
    sh.commit()
    pg.insert_text((2300, 1600), "SCALE: 1/4\" = 1'-0\"", fontsize=10)
    pg.insert_text((2300, 1650), f"A-{101 + doc.page_count}", fontsize=24)
    return truth


def score(n=4, seed=7, verbose=True):
    from app import autotakeoff
    rnd = random.Random(seed)
    doc = fitz.open()
    truths = [plan(doc, rnd) for _ in range(n)]
    sc = {"ppu": PPF, "unit": "ft"}
    tot = found5 = found12 = 0
    errs = []
    t_sf = t_name = f_sf = f_name = 0
    for pno, truth in enumerate(truths):
        found, missed = autotakeoff.all_rooms(doc[pno], sc)
        for t in truth:
            tot += 1
            if t["sf_tag"]:
                t_sf += 1
            else:
                t_name += 1
            c = fitz.Point((t["rect"].x0 + t["rect"].x1) / 2,
                           (t["rect"].y0 + t["rect"].y1) / 2)
            best = None
            for r in found:
                xs = [p.x for p in r["pts"]]
                ys = [p.y for p in r["pts"]]
                if min(xs) <= c.x <= max(xs) and min(ys) <= c.y <= max(ys):
                    e = abs(r["sqft"] - t["sf"]) / t["sf"]
                    if best is None or e < best:
                        best = e
            if best is not None:
                errs.append(best)
                if best <= 0.05:
                    found5 += 1
                    if t["sf_tag"]:
                        f_sf += 1
                    else:
                        f_name += 1
                if best <= 0.12:
                    found12 += 1
    out = {"rooms": tot, "within5": found5, "within12": found12,
           "median_err": statistics.median(errs) if errs else None,
           "sf_tagged": f"{f_sf}/{t_sf}", "name_only": f"{f_name}/{t_name}"}
    if verbose:
        print(out)
    return out


if __name__ == "__main__":
    args = sys.argv[1:]
    seed = int(args[args.index("--seed") + 1]) if "--seed" in args else 7
    n = int(args[0]) if args and args[0].isdigit() else 4
    score(n, seed)
