"""Civil takeoff on a sewer plan-and-profile drawn the way civil CAD draws
it, against a hand takeoff.

    python tools/civil_real.py [--seed N] [--save out.pdf]

The plan: a sanitary main through manholes (circles, tags and RIM / INV
callouts), two pipe sizes labelled along the pipe ('312 LF 8" PVC SDR-35
@ 0.40%'), an existing water main (dashed, 'EX. 6" DIP W'), street edges,
property lines, contours and a building - and below it a profile view of
the same main, with elevation scales both sides, which must not be
counted again. Scores pipe LF per size (manhole centre to centre, as an
estimator measures it) and the manhole count.
"""
import math
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import fitz                                                   # noqa: E402

PPU = 72 / 40.0          # 1" = 40'
MH_R = 7.0               # manhole symbol radius on paper (pt)


def make(seed=3):
    rnd = random.Random(seed)
    doc = fitz.open()
    pg = doc.new_page(width=2592, height=1728)
    # manholes along a bending main in the top half
    pts = []
    x, y = 260.0, 420.0
    for i in range(7):
        pts.append((x, y))
        ang = rnd.uniform(-0.25, 0.25)
        if y > 490:
            ang = -abs(ang)
        elif y < 420:
            ang = abs(ang)
        L = rnd.uniform(120, 300) * PPU            # 120-300 ft runs
        x += L * math.cos(ang)
        y += L * math.sin(ang)
        if x > 2150:
            break
    truth = {"8": 0.0, "10": 0.0, "4": 0.0}
    sizes = []
    for i in range(len(pts) - 1):
        sizes.append("8" if i < (len(pts) - 1) // 2 + 1 else "10")
    rim0 = 104.0
    inv = 96.0
    structs = []
    for i, (px, py) in enumerate(pts):
        rim = round(rim0 + rnd.uniform(-1.5, 2.5), 2)
        structs.append({"id": f"MH-{i + 1}", "pt": (px, py), "rim": rim,
                        "inv": round(inv, 2)})
        if i < len(pts) - 1:
            L = math.dist(pts[i], pts[i + 1]) / PPU
            inv -= L * 0.004 + 0.1
    sh = pg.new_shape()
    lab = []
    for i in range(len(pts) - 1):
        a, b = fitz.Point(pts[i]), fitz.Point(pts[i + 1])
        d = (b - a) / abs(b - a)
        sh.draw_line(a + d * MH_R, b - d * MH_R)
        L = abs(b - a) / PPU
        truth[sizes[i]] += L
        lab.append((a, b, L, sizes[i]))
    # a branch main off MH-2, up the side street, ending at its own manhole
    bx, by = pts[1]
    blen = rnd.uniform(90, 140) * PPU
    b_end = (bx + 10, by - blen)
    a_, b_ = fitz.Point(bx, by), fitz.Point(b_end)
    d_ = (b_ - a_) / abs(b_ - a_)
    sh.draw_line(a_ + d_ * MH_R, b_ - d_ * MH_R)
    truth["8"] += abs(b_ - a_) / PPU
    lab.append((a_, b_, abs(b_ - a_) / PPU, "8"))
    structs.append({"id": f"MH-{len(structs) + 1}", "pt": b_end,
                    "rim": round(structs[1]["rim"] + 1.2, 2),
                    "inv": round(structs[1]["inv"] + 0.8, 2)})
    sh.finish(color=(0, 0, 0), width=1.6, closePath=False)
    sh.commit()
    # service laterals: thinner, from mid-run down to the lots
    sh = pg.new_shape()
    services = []
    for i in range(len(pts) - 1):
        a, b = fitz.Point(pts[i]), fitz.Point(pts[i + 1])
        m = a + (b - a) * rnd.uniform(0.3, 0.7)
        L = rnd.uniform(35, 70)
        sh.draw_line(m, m + (0, L * PPU))
        truth["4"] += L
        services.append(m + (-3, L * PPU * 0.5))
    sh.finish(color=(0, 0, 0), width=0.8, closePath=False)
    sh.commit()
    for q in services:                  # written along the lateral
        pg.insert_text(q + (-20, 0), '4" PVC SERVICE', fontsize=5.5,
                       morph=(q, fitz.Matrix(90)))
    sh = pg.new_shape()
    for s in structs:
        sh.draw_circle(s["pt"], MH_R)
    sh.finish(color=(0, 0, 0), width=1.0)
    sh.commit()
    # labels along each pipe, rotated with it
    for a, b, L, size in lab:
        m = (a + b) / 2
        ang = math.degrees(math.atan2(b.y - a.y, b.x - a.x))
        text = f'{round(L)} LF {size}" PVC SDR-35 @ 0.40%'
        pg.insert_text(m + (-55, -4), text, fontsize=7,
                       morph=(m, fitz.Matrix(ang)))
    # manhole callouts
    for s in structs:
        x0, y0 = s["pt"][0] + 12, s["pt"][1] + 16
        pg.insert_text((x0, y0), s["id"], fontsize=8)
        pg.insert_text((x0, y0 + 10), f"RIM={s['rim']:.2f}", fontsize=6.5)
        pg.insert_text((x0, y0 + 19), f'INV IN (W) 8"={s["inv"] + 0.1:.2f}',
                       fontsize=6.5)
        pg.insert_text((x0, y0 + 28), f'INV OUT (E) 8"={s["inv"]:.2f}',
                       fontsize=6.5)
    # existing water main, dashed, parallel to the street
    sh = pg.new_shape()
    sh.draw_line((200, 300), (2300, 300))
    sh.finish(color=(0, 0, 0.8), width=1.0, dashes="[6 3] 0")
    sh.commit()
    pg.insert_text((900, 294), 'EX. 6" DIP W', fontsize=7)
    # street edges, property lines, contours, a building
    sh = pg.new_shape()
    for yy in (250, 600):
        sh.draw_line((150, yy), (2350, yy))
    for xx in range(300, 2300, 260):
        sh.draw_line((xx, 600), (xx, 760))
    sh.finish(color=(0.3, 0.3, 0.3), width=0.5)
    sh.commit()
    sh = pg.new_shape()
    for k in range(4):
        pts_c = [(150 + j * 110, 680 + k * 18 + 10 * math.sin(j / 2))
                 for j in range(20)]
        sh.draw_polyline(pts_c)
    sh.finish(color=(0.6, 0.4, 0.2), width=0.35, closePath=False)
    sh.commit()
    for k in range(4):
        pg.insert_text((160, 676 + k * 18), f"{102 - k}", fontsize=5)
    sh = pg.new_shape()
    sh.draw_rect(fitz.Rect(1500, 640, 1700, 740))
    sh.finish(color=(0, 0, 0), width=1.6)
    sh.commit()
    pg.insert_text((1520, 690), "EX. BUILDING", fontsize=8)
    # the profile: elevation scales both sides, same main again
    top, bot = 1000.0, 1480.0
    elevs = list(range(110, 80, -5))
    step = (bot - top) / (len(elevs) - 1)
    for k, e in enumerate(elevs):
        yy = top + k * step
        pg.insert_text((170, yy + 3), f"{e}", fontsize=7)
        pg.insert_text((2330, yy + 3), f"{e}", fontsize=7)
    sh = pg.new_shape()
    sh.draw_rect(fitz.Rect(200, top, 2320, bot))
    sh.finish(color=(0.5, 0.5, 0.5), width=0.4)
    sh.commit()

    def py_(el):
        return top + (110 - el) / 5 * step
    main = structs[:len(pts)]                     # the profile runs MH-1..n
    sh = pg.new_shape()
    xs = [260 + (2000) * i / (len(main) - 1) for i in range(len(main))]
    for i in range(len(main) - 1):
        sh.draw_line((xs[i], py_(structs[i]["inv"])),
                     (xs[i + 1], py_(structs[i + 1]["inv"] + 0.1)))
    sh.finish(color=(0, 0, 0), width=1.6, closePath=False)
    sh.commit()
    for i, s in enumerate(main):
        pg.insert_text((xs[i] + 4, py_(s["rim"]) - 30), s["id"], fontsize=7)
        pg.insert_text((xs[i] + 4, py_(s["rim"]) - 21),
                       f"RIM={s['rim']:.2f}", fontsize=6)
    for i in range(len(main) - 1):
        m = ((xs[i] + xs[i + 1]) / 2 - 40,
             (py_(structs[i]["inv"]) + py_(structs[i + 1]["inv"])) / 2 + 14)
        pg.insert_text(m, f'{sizes[i]}" PVC @ 0.40%', fontsize=6)
    pg.insert_text((1100, 1530), "PROFILE", fontsize=14)
    pg.insert_text((1100, 200), "PLAN", fontsize=14)
    pg.insert_text((2380, 1640), "C-201", fontsize=24)
    pg.insert_text((2380, 1600), "SCALE: 1\" = 40'", fontsize=9)
    depths = {s["id"]: round(s["rim"] - s["inv"], 2) for s in structs}
    return doc, {"lf": truth, "manholes": len(structs), "depths": depths}


def score(seed=3, verbose=True):
    from app import civiltakeoff as ct
    doc, truth = make(seed)
    res = ct.takeoff(doc, scales={0: (PPU, "ft")})
    got = {}
    for p in res["pipes"]:
        if not p["existing"]:
            got[f"{p['size']:g}"] = got.get(f"{p['size']:g}", 0) + \
                p["length"]
    errs = {k: abs(got.get(k, 0) - v) / v for k, v in truth["lf"].items()
            if v}
    mhs = [s for s in res["structures"] if s["kind"] == "manhole"
           and not s["existing"]]
    depth_ok = sum(1 for s in mhs if s["depth"] is not None and abs(
        s["depth"] - truth["depths"].get(s["id"], -99)) < 0.02)
    out = {"lf_truth": {k: round(v, 1) for k, v in truth["lf"].items()},
           "lf_found": {k: round(v, 1) for k, v in got.items()},
           "lf_err": {k: round(v, 4) for k, v in errs.items()},
           "manholes_truth": truth["manholes"], "manholes_found": len(mhs),
           "depths_right": depth_ok,
           "existing": [p["name"] for p in res["pipes"] if p["existing"]]}
    if verbose:
        print(out)
    return out, doc, res


if __name__ == "__main__":
    a = sys.argv[1:]
    seed = int(a[a.index("--seed") + 1]) if "--seed" in a else 3
    out, doc, res = score(seed)
    if "--save" in a:
        doc.save(a[a.index("--save") + 1])
