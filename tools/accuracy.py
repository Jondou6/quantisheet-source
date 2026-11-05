"""Accuracy of the automatic takeoff tools, against drawings whose right
answers are known.

    python tools/accuracy.py [PLANS] [--seed N]

Generates floor plans at 1/4" = 1'-0" with rooms of known size (thick
walls, door openings and swings, room tags with square footage,
dimension strings, furniture, hatching), outlet symbols in four
orientations with look-alike distractors, and door tags (D1, D10, D11 ...),
then scores:

* Auto Takeoff Rooms: rooms found, and area error against the true size
* Auto Area (click in each room, tagged or not)
* Count Symbol: recall and precision (and per orientation)
* Count by Label: exact tag matches only (D1 must not count D10)
* Auto Scale: the sheet's scale read from its title block
"""
import math
import os
import random
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import fitz                                                   # noqa: E402

PPF = 18.0                     # 1/4" = 1'-0": 18 points per foot
WALL = 0.5 * PPF               # 6" walls


def _split(rect, rnd, depth, out):
    w, h = rect.width / PPF, rect.height / PPF
    if depth == 0 or (w < 16 and h < 16):
        out.append(rect)
        return
    if w >= h:
        x = rect.x0 + rnd.uniform(0.35, 0.65) * rect.width
        x = round(x / (PPF / 2)) * (PPF / 2)
        _split(fitz.Rect(rect.x0, rect.y0, x, rect.y1), rnd, depth - 1, out)
        _split(fitz.Rect(x, rect.y0, rect.x1, rect.y1), rnd, depth - 1, out)
    else:
        y = rect.y0 + rnd.uniform(0.35, 0.65) * rect.height
        y = round(y / (PPF / 2)) * (PPF / 2)
        _split(fitz.Rect(rect.x0, rect.y0, rect.x1, y), rnd, depth - 1, out)
        _split(fitz.Rect(rect.x0, y, rect.x1, rect.y1), rnd, depth - 1, out)


def outlet(sh, c, rot):
    """Duplex outlet: circle with two prongs, pointing `rot` degrees."""
    r = 5
    sh.draw_circle(c, r)
    a = math.radians(rot)
    ux, uy = math.cos(a), math.sin(a)
    px, py = -uy, ux
    for s in (-2.2, 2.2):
        p0 = fitz.Point(c.x + px * s + ux * r, c.y + py * s + uy * r)
        p1 = fitz.Point(p0.x + ux * 6, p0.y + uy * 6)
        sh.draw_line(p0, p1)


def plan(doc, rnd, n):
    """One sheet. Returns its ground truth."""
    pg = doc.new_page(width=2592, height=1728)
    sh = pg.new_shape()
    bld = fitz.Rect(144, 144, 144 + PPF * rnd.randint(70, 95),
                    144 + PPF * rnd.randint(48, 62))
    rooms = []
    _split(bld, rnd, 4, rooms)
    # walls: every room edge as a 6" band (shared walls overlap)
    for r in rooms + [bld]:
        for a, b in ((r.tl, r.tr), (r.tr, r.br), (r.br, r.bl), (r.bl, r.tl)):
            if a.y == b.y:
                sh.draw_rect(fitz.Rect(min(a.x, b.x) - WALL / 2, a.y - WALL / 2,
                                       max(a.x, b.x) + WALL / 2, a.y + WALL / 2))
            else:
                sh.draw_rect(fitz.Rect(a.x - WALL / 2, min(a.y, b.y) - WALL / 2,
                                       a.x + WALL / 2, max(a.y, b.y) + WALL / 2))
    sh.finish(color=(0, 0, 0), fill=(0.15, 0.15, 0.15), width=0.5)
    truth_rooms = []
    for k, r in enumerate(rooms):
        inner = fitz.Rect(r.x0 + WALL / 2, r.y0 + WALL / 2, r.x1 - WALL / 2,
                          r.y1 - WALL / 2)
        sf = inner.width * inner.height / PPF ** 2
        truth_rooms.append({"rect": inner, "sf": sf,
                            "tagged": rnd.random() < 0.85,
                            "name": f"ROOM {100 + k}"})
    sh.commit()
    # door openings (white gap through one wall of each room) + swings
    sh = pg.new_shape()
    for t in truth_rooms:
        r = t["rect"]
        if r.width > 4 * PPF:
            x = r.x0 + PPF * 1.5
            sh.draw_rect(fitz.Rect(x, r.y0 - WALL - 1, x + 3 * PPF,
                                   r.y0 + 1))
    sh.finish(color=(1, 1, 1), fill=(1, 1, 1), width=0)
    sh.commit()
    sh = pg.new_shape()
    for t in truth_rooms:
        r = t["rect"]
        if r.width > 4 * PPF:
            x = r.x0 + PPF * 1.5
            sh.draw_line((x, r.y0), (x, r.y0 + 3 * PPF))
            sh.draw_curve((x, r.y0 + 3 * PPF), (x + 2 * PPF, r.y0 + 3 * PPF),
                          (x + 3 * PPF, r.y0))
    sh.finish(color=(0.3, 0.3, 0.3), width=0.4)
    # furniture and dimension strings (thin lines that must not count)
    for t in truth_rooms:
        r = t["rect"]
        if r.width > 8 * PPF and r.height > 8 * PPF:
            sh.draw_rect(fitz.Rect(r.x1 - 5 * PPF, r.y1 - 3 * PPF,
                                   r.x1 - PPF, r.y1 - PPF))
    sh.draw_line((bld.x0, bld.y1 + 40), (bld.x1, bld.y1 + 40))
    sh.finish(color=(0.4, 0.4, 0.4), width=0.3)
    sh.commit()
    for t in truth_rooms:
        c = t["rect"]
        cx, cy = (c.x0 + c.x1) / 2 - 28, (c.y0 + c.y1) / 2
        pg.insert_text((cx, cy), t["name"], fontsize=8)
        if t["tagged"]:
            pg.insert_text((cx, cy + 11), f"{round(t['sf'])} SF", fontsize=8)
    # outlets in four orientations + look-alikes (plain circles, J-boxes)
    sh = pg.new_shape()
    outs = []
    for k in range(n):
        t = rnd.choice(truth_rooms)
        r = t["rect"]
        if r.width < 5 * PPF or r.height < 5 * PPF:
            continue
        c = fitz.Point(rnd.uniform(r.x0 + 20, r.x1 - 20),
                       rnd.uniform(r.y0 + 40, r.y1 - 20))
        if any(abs(c.x - o["c"].x) < 30 and abs(c.y - o["c"].y) < 30
               for o in outs):
            continue
        rot = rnd.choice((0, 90, 180, 270))
        outlet(sh, c, rot)
        outs.append({"c": c, "rot": rot})
    decoys = 0
    for k in range(n // 2):
        t = rnd.choice(truth_rooms)
        r = t["rect"]
        c = fitz.Point(rnd.uniform(r.x0 + 15, r.x1 - 15),
                       rnd.uniform(r.y0 + 15, r.y1 - 15))
        if any(abs(c.x - o["c"].x) < 30 and abs(c.y - o["c"].y) < 30
               for o in outs):
            continue
        sh.draw_circle(c, 5)                     # a plain circle: not one
        decoys += 1
    sh.finish(color=(0, 0, 0), width=0.6)
    sh.commit()
    # door tags: D1 x a, D10/D11 x b
    labels = {"D1": 0, "D10": 0, "D11": 0}
    for t in truth_rooms:
        tag = rnd.choice(("D1", "D1", "D10", "D11"))
        r = t["rect"]
        pg.insert_text((r.x0 + 6, r.y0 + 14), tag, fontsize=7)
        labels[tag] += 1
    pg.insert_text((2300, 1600), "SCALE: 1/4\" = 1'-0\"", fontsize=10)
    pg.insert_text((2300, 1650), f"A-{101 + doc.page_count}", fontsize=24)
    return {"rooms": truth_rooms, "outlets": outs, "decoys": decoys,
            "labels": labels}


def main(argv):
    from app import autocount, autotakeoff, takeoff
    n_plans = int(argv[0]) if argv and argv[0].isdigit() else 6
    seed = int(argv[argv.index("--seed") + 1]) if "--seed" in argv else 11
    rnd = random.Random(seed)
    doc = fitz.open()
    truths = [plan(doc, rnd, 40) for _ in range(n_plans)]
    scale = {"ppu": PPF, "unit": "ft"}
    print(f"{n_plans} plans, "
          f"{sum(len(t['rooms']) for t in truths)} rooms, "
          f"{sum(len(t['outlets']) for t in truths)} outlets\n")

    # ---- auto takeoff rooms ----
    found = errs = tagged = 0
    abs_err = []
    wrong = 0
    for i, t in enumerate(truths):
        res, _missed = autotakeoff.all_rooms(doc[i], scale)
        want = [r for r in t["rooms"] if r["tagged"]]
        tagged += len(want)
        for r in res:
            match = next((w for w in want if w["name"] == r["name"]), None)
            if match is None:
                wrong += 1
                continue
            found += 1
            abs_err.append(abs(r["sqft"] - match["sf"]) / match["sf"] * 100)
    print("Auto Takeoff Rooms")
    print(f"  tagged rooms found     {found}/{tagged} "
          f"({found / max(tagged, 1) * 100:.0f}%)")
    if abs_err:
        print(f"  area error             median {statistics.median(abs_err):.1f}%"
              f", worst {max(abs_err):.1f}%, within 2%: "
              f"{sum(e <= 2 for e in abs_err) / len(abs_err) * 100:.0f}%")
    print(f"  unmatched results      {wrong}")

    # ---- auto area by click ----
    ok = tried = 0
    click_err = []
    for i, t in enumerate(truths):
        for r in t["rooms"]:
            c = r["rect"]
            pt = fitz.Point(c.x0 + c.width * 0.7, c.y0 + c.height * 0.3)
            tried += 1
            try:
                res = autotakeoff.room_at(doc[i], scale, pt)
            except Exception:
                continue
            e = abs(res["sqft"] - r["sf"]) / r["sf"] * 100
            click_err.append(e)
            ok += e <= 5
    print("\nAuto Area (click in each room, tagged or not)")
    print(f"  within 5% of true area {ok}/{tried} "
          f"({ok / max(tried, 1) * 100:.0f}%)")
    if click_err:
        print(f"  median error           {statistics.median(click_err):.1f}%")

    # ---- count symbol ----
    first = next(o for o in truths[0]["outlets"] if o["rot"] == 0)
    tpl_rect = fitz.Rect(first["c"].x - 9, first["c"].y - 9,
                         first["c"].x + 14, first["c"].y + 9)
    tpl = autocount.symbol_template(doc[0], tpl_rect)
    hits = autocount.find_symbols(doc, tpl, 0.8)
    tp = fp = 0
    per_rot = {0: [0, 0], 90: [0, 0], 180: [0, 0], 270: [0, 0]}
    for o in [o for t in truths for o in t["outlets"]]:
        per_rot[o["rot"]][1] += 1
    used = set()
    for h in hits:
        r = fitz.Rect(h["rect"])
        pi = h["page"]
        m = next((k for k, o in enumerate(truths[pi]["outlets"])
                  if (pi, k) not in used and r.contains(o["c"])), None)
        if m is None:
            fp += 1
        else:
            used.add((pi, m))
            tp += 1
            per_rot[truths[pi]["outlets"][m]["rot"]][0] += 1
    total = sum(len(t["outlets"]) for t in truths)
    print("\nCount Symbol (template: one outlet)")
    print(f"  recall                 {tp}/{total} ({tp / max(total, 1) * 100:.0f}%)")
    print(f"  precision              {tp}/{tp + fp} "
          f"({tp / max(tp + fp, 1) * 100:.0f}%)")
    print("  by orientation         " + ", ".join(
        f"{k}°: {v[0]}/{v[1]}" for k, v in per_rot.items()))

    print("  threshold sweep        (recall / precision)")
    for th in (0.75, 0.8, 0.85, 0.88, 0.9, 0.93):
        hs = autocount.find_symbols(doc, tpl, th)
        tp2 = fp2 = 0
        used2 = set()
        for h in hs:
            r = fitz.Rect(h["rect"])
            pi = h["page"]
            m = next((k for k, o in enumerate(truths[pi]["outlets"])
                      if (pi, k) not in used2 and r.contains(o["c"])), None)
            if m is None:
                fp2 += 1
            else:
                used2.add((pi, m))
                tp2 += 1
        print(f"    {th:.2f}               {tp2 / max(total, 1) * 100:4.0f}% / "
              f"{tp2 / max(tp2 + fp2, 1) * 100:4.0f}%")
    scores = sorted(h.get("score", 0) for h in hits)
    if scores:
        print(f"  hit scores             min {scores[0]:.2f}, median "
              f"{scores[len(scores) // 2]:.2f}")

    # ---- count by label ----
    want = sum(t["labels"]["D1"] for t in truths)
    got = len(autocount.find_by_label(doc, "D1", use_ocr=False))
    print("\nCount by Label \"D1\" (with D10 and D11 on the sheets)")
    print(f"  counted {got}, right answer {want}"
          + ("  OK" if got == want else "  WRONG"))

    # ---- auto scale ----
    good = 0
    for pg in doc:
        sc = takeoff.main_scale(pg.get_text())
        ppu = sc[1] if isinstance(sc, (tuple, list)) and len(sc) > 1 else \
            (sc or {}).get("ppu") if isinstance(sc, dict) else None
        good += bool(ppu) and abs(float(ppu) - PPF) < 0.01
    print(f"\nAuto Scale\n  read right on {good}/{doc.page_count} sheets")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
