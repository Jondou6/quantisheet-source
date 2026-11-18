"""Where Work Notes Takeoff's reading spends its time (read-only):
python tools/profile_notes.py <glob relative to the folder> [N]"""
import cProfile
import glob
import os
import pstats
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def main(a):
    from app import callout_scope as cs
    path = sorted(glob.glob(os.path.join(ROOT, a[0])))[0]
    n = int(a[1]) if len(a) > 1 else 25
    t = time.perf_counter()
    pr = cProfile.Profile()
    pr.enable()
    rows, _f = cs.read_set(path, "")
    pr.disable()
    print(f"{len(rows)} rows in {time.perf_counter() - t:.1f} s")
    pstats.Stats(pr).sort_stats("cumulative").print_stats(n)


if __name__ == "__main__":
    main(sys.argv[1:])
