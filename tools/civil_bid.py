"""Run the Civil estimate end to end on a real drawing set, the way an
estimator would: read sheet scales, civil takeoff on the utility/site
sheets, activities from the takeoff, crews and rates from the library,
schedule, resources, cash flow and a priced owner's schedule built from
the takeoff groups. Prints every step and what looked wrong.

    python tools/civil_bid.py FILE.pdf [PAGES 1-based, comma list]

Uses a throwaway settings folder, so your price database isn't touched.
Writes .run/civil_bid.pdf and .run/civil_bid_*.xlsx.
"""
import os
import re
import sys
import tempfile
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
RUN = os.path.join(ROOT, ".run")

import fitz                                                   # noqa: E402

from app import settings                                      # noqa: E402

tmp = tempfile.mkdtemp(prefix="civilbid-")
settings.DIR = tmp
settings.PATH = os.path.join(tmp, "s.json")
settings._cache = {"author": "Civil bid test"}

from app import annotate, civiltakeoff, heavy, sheets         # noqa: E402

CIVIL = re.compile(r"\b(UTILIT|SEWER|SANITARY|WATER|STORM|DRAIN|GRADING|"
                   r"SITE|PAVING|EROSION|CIVIL)", re.I)
problems = []


def step(name, fn):
    t = time.time()
    try:
        out = fn()
        print(f"  ok   {name} ({time.time() - t:.1f}s)")
        return out
    except Exception as e:
        problems.append(f"{name}: {e}")
        print(f"  FAIL {name}: {e}")
        traceback.print_exc(limit=4, file=sys.stdout)
        return None


def main(argv):
    path = argv[0].strip("\"")
    doc = fitz.open(path)
    print(f"{os.path.basename(path)}: {doc.page_count} pages")
    pages = [int(p) - 1 for p in argv[1].split(",")] if len(argv) > 1 \
        else None
    rows = step("read sheet numbers and scales",
                lambda: sheets.scan(doc, pages))
    rows = rows or []
    if pages is None:
        pages = [r["page"] for r in rows if
                 (r["number"] or "").upper().startswith("C") or
                 (not r["number"] and CIVIL.search(r["title"] or ""))]
    pick = [r for r in rows if r["page"] in pages]
    for r in pick:
        print(f"    p{r['page'] + 1:>3} {r['label'][:60]:60} scale "
              f"{r['scale'][0] if r['scale'] else '-'}")
    if not pick:
        problems.append("no civil sheets found")
    scales = {r["page"]: (r["scale"][1], r["scale"][2]) for r in pick
              if r["scale"]}
    no_scale = [r["page"] + 1 for r in pick if not r["scale"]]
    if no_scale:
        problems.append(f"no scale read on page(s) {no_scale} - pipe "
                        "lengths skipped there")
    pipe_pages = heavy.pipe_plan_pages(doc, pages, loose=True)
    print(f"    pipe taken off from page(s) {[p + 1 for p in pipe_pages]}")
    res = step("civil takeoff (pipes and structures)",
               lambda: civiltakeoff.takeoff(doc, pipe_pages, scales))
    if res:
        for p in res["pipes"]:
            print(f"    pipe  {p['name'][:50]:50} {p['length']:8.1f} ft "
                  f"(labels say {p['label_length']:.0f})"
                  f"{' EXISTING' if p['existing'] else ''}")
        for c in res.get("checks", []):
            problems.append("takeoff: " + c)
        print(f"    {len(res['structures'])} structures: " + ", ".join(
            s["key"] for s in res["structures"][:15]))
        n = step("put the takeoff in the PDF",
                 lambda: civiltakeoff.apply(doc, res))
        print(f"    {n} marks")
    lib = step("company library (starter rates)", heavy.library)
    job = heavy.read(doc)
    acts = step("activities from every takeoff group",
                lambda: heavy.activities_from_takeoff(doc, job, lib,
                                                       pages)) or []
    for a in acts:
        print(f"    {a['name'][:46]:46} {float(a['qty']):9.1f} {a['unit']:3}"
              f" crew {a['crew'] or '-':5} @ {a['rate']}/hr")
    if not acts:
        problems.append("the takeoff made no activities")
    # an owner's schedule built from the same groups (item per activity)
    job["pay_items"] = [{"no": str(i + 1), "desc": a["name"],
                         "unit": a["unit"], "owner_qty": a["qty"],
                         "weight": "1"} for i, a in enumerate(acts)]
    for i, a in enumerate(acts):
        a["pay_item"] = str(i + 1)
    job["indirects"] = [{"desc": "Superintendent", "rate": "2800",
                         "per": "week", "qty": "1", "duration": ""},
                        {"desc": "Mobilization", "rate": "15000",
                         "per": "LS", "qty": "1", "duration": ""}]
    sch = step("crew schedule", lambda: heavy.schedule(job, lib))
    if sch:
        job["settings"]["duration_weeks"] = str(sch["weeks"])
        print(f"    {sch['days']} work days, {sch['weeks']} weeks (all "
              "activities in parallel unless chained)")
    t = step("totals", lambda: heavy.totals(job, lib))
    if t:
        print(f"    direct {t['direct']}  indirect {t['indirect']}  markup "
              f"{t['markup']}  total {t['total']}")
        for p in t["problems"]:
            problems.append("estimate: " + p)
        for a, c in t["activities"]:
            print(f"    {a['name'][:40]:40} {c['hours']:>8} crew hr  "
                  f"{c['total']:>12}  {c['unit_cost']:>8}/{a['unit']}")
    s = step("spread over the owner's schedule",
             lambda: heavy.spread(job, lib))
    if s:
        print(f"    bid {s['bid']} (rounding {s['rounding']})")
    r = step("resources", lambda: heavy.resources(job, lib))
    if r:
        for k, v in r["labor"].items():
            print(f"    {k:6} {v['hours']:>9} hr  {v['cost']:>12}")
    step("cash flow", lambda: heavy.cashflow(job, lib))
    for name, fn in [("schedule", heavy.export_schedule),
                     ("resources", heavy.export_resources),
                     ("cashflow", heavy.export_cashflow)]:
        step(f"export {name}", lambda fn=fn, name=name: fn(
            job, lib, os.path.join(RUN, f"civil_bid_{name}.xlsx")))
    step("save version", lambda: heavy.save_version(job, "test", lib))
    heavy.write(doc, job)
    out = os.path.join(RUN, "civil_bid.pdf")
    step("save PDF", lambda: doc.save(out, garbage=3, deflate=True))
    back = step("read it back", lambda: heavy.read(fitz.open(out)))
    if back and len(back["activities"]) != len(job["activities"]):
        problems.append("activities lost on save")
    print("\nPROBLEMS:" if problems else "\nno problems")
    for p in problems:
        print("  - " + p)


if __name__ == "__main__":
    main(sys.argv[1:])
