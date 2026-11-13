"""Where Auto Takeoff Rooms spends its time.

    python tools/profile_rooms.py [hard N | hmb] [--click]

Profiles all_rooms() (or one click, room_at) on a made-up hard plan or
the truth set's sheet and prints the top functions by cumulative and by
own time.
"""
import cProfile
import os
import pstats
import random
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main(a):
    import fitz
    from app import autotakeoff as at
    click = "--click" in a
    a = [x for x in a if not x.startswith("--")]
    if a and a[0] == "hmb":
        import truth_rooms as tr
        from app import aitakeoff as ait
        tmp = tempfile.mkdtemp(prefix="qs-truth-")
        doc = fitz.open(shutil.copy(os.path.join(tr.PLANS, tr.FILES["hmb"]),
                                    os.path.join(tmp, "set.pdf")))
        row = next(r for r in ait.plan_set(doc)
                   if (r["number"] or "").upper().replace("-", "") == "A101"
                   and r["kind"] != "superseded")
        page, sc = doc[row["page"]], {"ppu": row["scale"][1],
                                      "unit": row["scale"][2]}
        pt = None
    else:
        import accuracy_hard as ah
        k = int(a[1]) if len(a) > 1 else 0
        rnd = random.Random(21)
        doc = fitz.open()
        ss = [ah.Sheet(doc, rnd, [18.0, 18.0, 13.5, 9.0, 18.0, 9.0,
                                  13.5][i % 7]).build() for i in range(k + 1)]
        page, sc = doc[k], {"ppu": ss[k].ppf, "unit": "ft"}
        r = ss[k].rooms[3]
        pt = ss[k].pt(r["c"][0], r["c"][1] + 1.5)
    pr = cProfile.Profile()
    t = time.perf_counter()
    pr.enable()
    if click and pt is not None:
        res = at.room_at(page, sc, pt)
        n = 1
    else:
        found, missed = at.all_rooms(page, sc, skip_measured=False)
        n = len(found)
    pr.disable()
    print(f"{'click' if click else 'all rooms'}: {n} result(s) in "
          f"{time.perf_counter() - t:.2f} s")
    for key in ("cumulative", "tottime"):
        print("== by", key)
        st = pstats.Stats(pr)
        st.sort_stats(key).print_stats(22)


if __name__ == "__main__":
    main(sys.argv[1:])
