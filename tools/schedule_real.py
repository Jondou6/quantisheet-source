"""Build Schedule From Plans on real files, printed:
python tools/schedule_real.py PLANS.pdf SPEC.pdf [NTP MM/DD/YY]"""
import datetime as dt
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import fitz                                                   # noqa: E402

from app import settings                                      # noqa: E402

TMP = tempfile.mkdtemp(prefix="sched-real-")
settings.DIR = os.path.join(TMP, "cfg")
settings.PATH = os.path.join(settings.DIR, "s.json")
settings._cache = None
from app.pm import autoschedule as au, schedule               # noqa: E402
from app.pm.store import ProjectStore                         # noqa: E402


def main(argv):
    plans = fitz.open(argv[0].strip('"')) if argv[0] != "-" else None
    spec = fitz.open(argv[1].strip('"')) if len(argv) > 1 else None
    ntp = dt.datetime.strptime(argv[2], "%m/%d/%y").date() \
        if len(argv) > 2 else dt.date(2026, 11, 2)
    t = time.time()
    info = au.read_job(plans, spec, progress=lambda s: print("  ..", s))
    print(f"read in {time.time() - t:.1f}s: {info['sheets']} sheets, "
          f"divisions {info['divisions']}, area found "
          f"{info['area_found']}")
    for f in info["ct"]["found"]:
        print(f"   p{f['page']}: {f['kind']} {f.get('days') or f.get('date')}"
              f" {f.get('basis', '')} | {f['text'][:110]}")
    st = ProjectStore(os.path.join(TMP, "job"))
    res = au.build(st, info["scope"], ntp, info["ct"])
    for line in au.summary_text(info["ct"], info["scope"], res):
        print("  ", line)
    cpm = schedule.compute(st, au.ntp_or_today(st))
    print("problems:", cpm["problems"])
    for a, lvl, _s in schedule.outline(st.list("activity")):
        r = next(x for x in cpm["rows"] if x["_id"] == a["_id"])
        print("   " + "  " * lvl + f"{a['name'][:44]:44} {r['dur']:>3}d "
              f"{r['es']:%m/%d/%y} - {r['ef']:%m/%d/%y}"
              + ("  crit" if r["critical"] else ""))


if __name__ == "__main__":
    main(sys.argv[1:])
