"""How long each legend symbol takes to count (Nov 1: the fire
extinguisher on Aiken was left over at AI Takeoff's 180 s device limit).

    python tools/legend_timing.py PLANS.pdf [LIMIT_S]

Works on a temp copy. Runs the same legend count AI Takeoff runs (same
pages, disciplines, titles), with no time limit unless LIMIT_S is given,
and writes .run/legend_timing.txt: each symbol, seconds, hits, pages."""
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, ".run", "legend_timing.txt")


def main(argv):
    argv = [a.strip('"') for a in argv]
    if not argv:
        raise SystemExit(__doc__)
    limit = float(argv[1]) if len(argv) > 1 else None
    import fitz
    from app import aitakeoff as ait, tradetakeoff as tt
    tmp = tempfile.mkdtemp(prefix="qs_leg_t_")
    pdf = os.path.join(tmp, "plans.pdf")
    shutil.copy2(argv[0], pdf)
    doc = fitz.open(pdf)
    rows = ait.plan_set(doc, lambda i, n: True)
    pages = [r["page"] for r in rows if "devices" in (r.get("engines") or [])]
    plan_pages = [r["page"] for r in rows
                  if "rooms" in (r.get("engines") or []) or
                  tt._LIFE_SAFETY_PLAN.search(r.get("title") or "")]
    marks = []
    last = [None, time.perf_counter()]

    def prog(k, n, name):
        now = time.perf_counter()
        if last[0] is not None:
            marks.append((last[0], now - last[1]))
        last[0], last[1] = name, now
        return True
    rep = {}
    t0 = time.perf_counter()
    found = tt.legend_counts(
        doc, pages, progress=prog, time_limit=limit, report=rep,
        disciplines={r["page"]: r.get("discipline", "") for r in rows},
        titles={r["page"]: r.get("title") or "" for r in rows},
        pictures=ait.picture_count_on(), plan_pages=plan_pages)
    total = time.perf_counter() - t0
    if last[0] is not None:
        marks.append((last[0], time.perf_counter() - last[1]))
    hits = {f["name"]: f["hits"] for f in found}
    lines = [f"{os.path.basename(argv[0])}: {len(pages)} device page(s), "
             f"{len(marks)} symbol(s), {total:.1f} s total", ""]
    for name, s in sorted(marks, key=lambda m: -m[1]):
        h = hits.get(name) or []
        lines.append(f"{s:7.1f} s  {len(h):4d} hits  pages "
                     f"{sorted({x['page'] + 1 for x in h})[:12]}  {name}")
    lines.append("")
    lines += [f"not counted: {n} - {w}" for n, w in rep.get("not_counted")
              or []]
    txt = "\n".join(lines)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(txt)
    print(txt)


if __name__ == "__main__":
    main(sys.argv[1:])
