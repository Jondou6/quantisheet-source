"""Why a pipe measures short: run the civil pipe finder on one sheet with
its debug notes on.

    python tools/civil_debug.py PLANS.pdf PAGE(1-based) [TEXT to filter]
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import fitz                                                   # noqa: E402

from app import civiltakeoff as ct, sheets                    # noqa: E402


def main(argv):
    doc = fitz.open(argv[0].strip('"'))
    pno = int(argv[1]) - 1
    want = (argv[2] if len(argv) > 2 else "").strip('"').upper()
    rows = sheets.scan(doc, [pno])
    sc = rows[0]["scale"]
    print(rows[0]["label"], sc[0] if sc else "NO SCALE", flush=True)
    page = doc[pno]
    for lab in ct.pipe_labels(page):
        if want in lab["text"].upper():
            print(f"  label {lab['text']!r} length={lab.get('length')} "
                  f"at {tuple(round(v) for v in lab['center'])} "
                  f"dir={lab.get('dir')}")
    ct.DEBUG = []
    got = ct.pipe_systems(page, sc[1], sc[2])
    for d in ct.DEBUG:
        if not want or any(want in str(x).upper() for x in d) or \
                d[0] in ("style", "kept connected"):
            print("  ", d)
    print()
    for g in got:
        if want in g["name"].upper():
            print(f"{g['name']}: {g['length']:.1f} ft, labels "
                  f"{g['label_length']:.1f}")
            for r in g["runs"]:
                p = r["pts"]
                print(f"   run {r['length']:7.1f} ft  "
                      f"{tuple(round(v) for v in p[0])} -> "
                      f"{tuple(round(v) for v in p[-1])}  "
                      f"{'grey' if r.get('screened') else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
