"""Where AI Takeoff spends its time on one set (read-only, works on the
file as it is): python tools/profile_ai.py <glob> [ENGINE ...] [--n N]"""
import cProfile
import glob
import os
import pstats
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main(a):
    import fitz
    from app import aitakeoff as ait
    n = 30
    if "--n" in a:
        i = a.index("--n")
        n = int(a[i + 1])
        a = a[:i] + a[i + 2:]
    path = sorted(glob.glob(os.path.join(ROOT, a[0])))[0]
    engines = a[1:] or None
    doc = fitz.open(path)
    rows = ait.plan_set(doc)
    t = time.perf_counter()
    pr = cProfile.Profile()
    pr.enable()
    res = ait.run(doc, rows, engines=engines)
    pr.disable()
    print(f"ran {engines or 'all'} in {time.perf_counter() - t:.1f} s; "
          f"timing {res.get('timing')}")
    st = pstats.Stats(pr)
    st.sort_stats("cumulative").print_stats(n)
    st.sort_stats("tottime").print_stats(15)


if __name__ == "__main__":
    main(sys.argv[1:])
