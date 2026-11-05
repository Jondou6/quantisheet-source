"""Why does the civil takeoff count what it counts? Per civil sheet: its
number, title and scale, whether it is treated as a pipe plan, and the
pipe found on it (length, labels, runs).

    python tools/civil_probe.py PLANS.pdf
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import fitz                                                   # noqa: E402

from app import civiltakeoff, heavy, sheets                   # noqa: E402


def main(argv):
    doc = fitz.open(argv[0].strip('"'))
    pages = heavy.civil_pages(doc)
    plan = set(heavy.pipe_plan_pages(doc, pages))
    rows = {r["page"]: r for r in sheets.scan(doc, pages)}
    print(f"civil pages: {[p + 1 for p in pages]}")
    print(f"pipe-plan pages: {sorted(p + 1 for p in plan)}\n", flush=True)
    for p in pages:
        r = rows.get(p, {})
        sc = r.get("scale")
        print(f"p{p + 1:>3} {r.get('number') or '?':8} "
              f"{(r.get('title') or '')[:70]!r:72} "
              f"{sc[0] if sc else 'NO SCALE'}  "
              f"{'PLAN' if p in plan else '-'}", flush=True)
        page = doc[p]
        labs = civiltakeoff.pipe_labels(page)
        print(f"      {len(labs)} pipe labels: " + "; ".join(
            l.get("text", "")[:40] for l in labs[:6]), flush=True)
        if not sc:
            continue
        try:
            got = civiltakeoff.pipe_systems(page, sc[1], sc[2])
        except Exception as e:
            print(f"      pipe_systems failed: {e}")
            continue
        for g in got:
            print(f"      {g['name']:34} {g['length']:8.1f} ft  labels "
                  f"{g['label_length']:7.1f}  runs {len(g['runs']):3}  "
                  f"style {g.get('style_name', '')}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
