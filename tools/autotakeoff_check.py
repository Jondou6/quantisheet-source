"""Check auto takeoff against the room tags of a real sheet.

    python tools/autotakeoff_check.py plans.pdf [page] [scale points/ft]

Prints each tagged room's traced area against the area on its tag."""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(
    __file__))))

import fitz                                    # noqa: E402

from app import annotate, autotakeoff          # noqa: E402


def main():
    path = sys.argv[1]
    pno = int(sys.argv[2]) - 1 if len(sys.argv) > 2 else 0
    doc = fitz.open(path)
    sc = annotate.read_scales(doc).get(pno)
    if len(sys.argv) > 3 or not sc:
        sc = {"ppu": float(sys.argv[3]) if len(sys.argv) > 3 else 18.0,
              "unit": "ft"}
    t = time.time()
    found, missed = autotakeoff.all_rooms(doc[pno], sc)
    took = time.time() - t
    errs = []
    for r in sorted(found, key=lambda r: r["name"]):
        e = 100 * (r["sqft"] - r["tag_sf"]) / r["tag_sf"]
        errs.append(abs(e))
        print(f"{r['name'][:30]:30s} tag {r['tag_sf']:7,.0f}  traced "
              f"{r['sqft']:8,.1f}  {e:+6.1f}%")
    for m in missed:
        print(f"{m['name'][:30]:30s} tag {m['sf']:7,.0f}  NOT FOUND")
    n = len(found) + len(missed)
    print(f"\n{len(found)}/{n} rooms found in {took:.1f}s; "
          f"{sum(e <= 5 for e in errs)} within 5%, "
          f"{sum(e <= 10 for e in errs)} within 10%")


if __name__ == "__main__":
    main()
