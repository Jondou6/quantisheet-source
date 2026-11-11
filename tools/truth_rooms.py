"""Auto Takeoff Rooms against the checked room areas in a truth file.

    python tools/truth_rooms.py [SET] [--sheet A101] [--dump]

Reads _incoming/plans/truth.csv (rows of kind "area" whose match is
"room:NAME NUMBER"), opens a temp copy of that set's drawing read-only,
takes the rooms off the sheet and prints each room's traced area against
the truth: error %, the tolerance in the file, flags. The drawings and
the truth file stay on this computer; nothing from them is written into
the repository.
"""
import csv
import glob
import os
import re
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PLANS = os.path.join(ROOT, "_incoming", "plans")
FILES = {"hmb": "harbor_springs_hmb_bid_drawings.pdf"}
SHEET = {"hmb": "A101"}


def truth(name):
    rows = []
    with open(os.path.join(PLANS, "truth.csv"), encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["set"] == name and r["kind"] == "area" and \
                    r["match"].startswith("room:"):
                m = re.search(r"(\d{2,4}[A-Z]?)\s*$", r["match"])
                rows.append({"no": m.group(1) if m else "",
                             "name": r["match"][5:],
                             "sf": float(r["truth"]),
                             "tol": float(r["tolerance_pct"] or 5)})
    return rows


def run(name="hmb", sheet=None, dump=False, pic=()):
    import fitz
    from app import aitakeoff as ait, autotakeoff as at
    src = os.path.join(PLANS, FILES.get(name) or "")
    if not os.path.isfile(src):
        cands = glob.glob(os.path.join(PLANS, f"*{name}*.pdf"))
        if not cands:
            raise SystemExit(f"no drawing for set {name!r} in {PLANS}")
        src = cands[0]
    tmp = tempfile.mkdtemp(prefix="qs-truth-")
    pdf = shutil.copy(src, os.path.join(tmp, "set.pdf"))
    doc = fitz.open(pdf)
    want = (sheet or SHEET.get(name) or "").upper()
    rows = ait.plan_set(doc)
    row = next((r for r in rows if (r["number"] or "").upper().replace(
        "-", "") == want.replace("-", "") and r["kind"] != "superseded"),
        None)
    if row is None:
        raise SystemExit(f"sheet {want} not found; have " + ", ".join(
            str(r["number"]) for r in rows))
    sc = row["scale"]
    print(f"sheet {row['number']} (page {row['page'] + 1}) "
          f"{row['title']!r}; scale {sc and sc[0]!r} from "
          f"{row['scale_from']!r}; engines {row['engines']}")
    if not sc:
        raise SystemExit("no scale on that sheet")
    scale = {"ppu": sc[1], "unit": sc[2]}
    info = {}
    t = time.perf_counter()
    found, missed = at.all_rooms(doc[row["page"]], scale, info=info,
                                 skip_measured=False)
    took = time.perf_counter() - t
    by_no = {}
    for r in found:
        by_no.setdefault(str(r.get("number") or at.room_number(
            r.get("name") or "") or ""), []).append(r)
    tr = truth(name)
    errs, ok = [], 0
    print(f"{'room':34s} {'truth':>8s} {'traced':>8s} {'err':>7s} "
          f"{'tol':>4s}  conf  flags")
    for t_ in sorted(tr, key=lambda x: x["no"]):
        got = by_no.get(t_["no"]) or []
        if not got:
            print(f"{t_['name'][:34]:34s} {t_['sf']:8.1f} {'MISSED':>8s}")
            errs.append(100.0)
            continue
        r = got[0]
        sf = r.get("net_sf") or r.get("sqft")
        e = 100 * (sf - t_["sf"]) / t_["sf"]
        errs.append(abs(e))
        ok += abs(e) <= t_["tol"]
        print(f"{t_['name'][:34]:34s} {t_['sf']:8.1f} {sf:8.1f} {e:+6.1f}% "
              f"{t_['tol']:4.0f}  {r.get('trace_confidence') or 0:4.2f}  "
              f"{'; '.join(r.get('flags') or [])[:70]}")
        if pic and t_["no"] in pic:
            import numpy as np
            import cv2
            pts = r["pts"]
            box = fitz.Rect(min(q.x for q in pts) - 30,
                            min(q.y for q in pts) - 30,
                            max(q.x for q in pts) + 30,
                            max(q.y for q in pts) + 30)
            z = 5.0
            pm = doc[row["page"]].get_pixmap(matrix=fitz.Matrix(z, z),
                                             clip=box)
            im = np.frombuffer(pm.samples, np.uint8).reshape(
                pm.h, pm.w, pm.n)[:, :, :3].copy()
            im = cv2.cvtColor(im, cv2.COLOR_RGB2BGR)
            cv2.polylines(im, [np.array([[(q.x - box.x0) * z,
                                          (q.y - box.y0) * z] for q in pts],
                                        np.int32)], True, (0, 0, 255), 1)
            os.makedirs(os.path.join(ROOT, ".run", "hard"), exist_ok=True)
            cv2.imwrite(os.path.join(ROOT, ".run", "hard",
                                     f"truth_{t_['no']}.png"), im)
        if dump:
            pts = r.get("pts") or []
            print("     on lines:", r.get("on_lines"), " corners (pt):",
                  [[round(q.x, 2), round(q.y, 2)] for q in pts][:40])
    extra = [r for no, rs in by_no.items() for r in rs
             if no not in {t_["no"] for t_ in tr}]
    for r in extra:
        print(f"  (not in truth) {str(r.get('name'))[:30]:30s} "
              f"{r.get('net_sf') or r.get('sqft'):8.1f}")
    for m in missed:
        print(f"  (tag not traced) {str(m.get('name'))[:40]}")
    n = len(tr)
    errs.sort()
    print(f"\n{ok}/{n} within the file's tolerance; "
          f"{sum(e <= 2 for e in errs)}/{n} within 2%, "
          f"{sum(e <= 5 for e in errs)}/{n} within 5%; median error "
          f"{errs[n // 2] if n else 0:.1f}%, worst {errs[-1] if n else 0:.1f}"
          f"%; {took:.1f}s; total traced "
          f"{sum((r.get('net_sf') or r.get('sqft') or 0) for no in by_no for r in by_no[no][:1] if no in {t_['no'] for t_ in tr}):.1f}"
          f" vs truth {sum(t_['sf'] for t_ in tr):.1f}")
    doc.close()
    shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    sh = None
    if "--sheet" in sys.argv:
        sh = sys.argv[sys.argv.index("--sheet") + 1]
        a = [x for x in a if x != sh]
    pic = ()
    if "--pic" in sys.argv:
        pic = sys.argv[sys.argv.index("--pic") + 1].split(",")
        a = [x for x in a if x != sys.argv[sys.argv.index("--pic") + 1]]
    run(a[0] if a else "hmb", sh, "--dump" in sys.argv, pic)
