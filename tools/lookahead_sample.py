"""A sample 2-week look-ahead (made-up job) to look at:
python tools/lookahead_sample.py out.pdf [today YYYY-MM-DD]"""
import datetime as dt
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app import settings                                     # noqa: E402
from app.pm import activity_lookahead as la                  # noqa: E402
from app.pm.store import ProjectStore                         # noqa: E402

tmp = tempfile.mkdtemp()
settings.DIR = os.path.join(tmp, "cfg")
settings.PATH = os.path.join(tmp, "cfg", "s.json")
s = ProjectStore(os.path.join(tmp, "Station 9 Repairs"))
today = dt.date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else \
    dt.date.today()
s.set_setting("data_date", today.isoformat())
mon = today - dt.timedelta(days=today.weekday())
add = lambda **r: s.save_record("activity", r)                # noqa: E731
add(name="Mobilize & protection", duration=2,
    start=(mon - dt.timedelta(days=3)).isoformat(), responsible="GC")
add(name="Power wash exterior", duration=2, preds=[{"id": "A0001"}],
    responsible="Clean Co.", area="Exterior")
add(name="Repair stucco at front steps", duration=4,
    preds=[{"id": "A0002"}], responsible="Stucco sub", area="Exterior")
add(name="Remove & replace window caulking", duration=4,
    preds=[{"id": "A0002"}], responsible="Sealant sub", area="Exterior",
    baseline_start=mon.isoformat(),
    baseline_finish=(mon + dt.timedelta(days=3)).isoformat())
add(name="Paint window frames", duration=4, preds=[{"id": "A0004"}],
    responsible="Paint sub", area="Exterior")
add(name="Repair nail pops, Bldgs A-D", duration=3,
    preds=[{"id": "A0001"}], responsible="Drywall sub", area="Interior")
add(name="Water softener - deliver & install", duration=2,
    start=(mon + dt.timedelta(days=8)).isoformat(), responsible="Plumber")
add(name="Exterior work complete", duration=0, preds=[{"id": "A0005"},
                                                      {"id": "A0003"}])
add(name="Punch list", duration=5, preds=[{"id": "A0008"}])
out = la.export(s, sys.argv[1], 2, today)
print("wrote", out)
