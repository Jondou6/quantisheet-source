"""A sample Weekly Owner Report (made-up job) to look at:
python tools/owner_report_sample.py out_default.pdf [out_all_options.pdf]"""
import os
import sys
import tempfile
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
from app import settings                                     # noqa: E402

tmp = tempfile.mkdtemp()
settings.DIR = os.path.join(tmp, "cfg")
settings.PATH = os.path.join(tmp, "cfg", "s.json")
settings._cache = {"author": "Pat Example"}
from app.pm import owner_report as orp                         # noqa: E402
from app.pm import owner_report_logs as L                      # noqa: E402
from app.pm.store import ProjectStore                          # noqa: E402
import test_owner_report as T                                  # noqa: E402
import test_owner_report_logs as TL                            # noqa: E402
import test_photofit as TP                                     # noqa: E402

s = ProjectStore(os.path.join(tmp, "Job"))
s.data["name"] = "Harbor Point Clubhouse (example)"
s.set_setting("number", "26-101")
s.set_setting("location", "1 Example Way, Anytown, FL")
s.set_setting("project_start", "2026-05-01")
TL.add_rfis(s)
TL.add_submittals(s)
TL.add_change_events(s)
T._logs(s)
T._schedule(s)
paths = []
for i in range(16):
    w, h = (1600, 1200) if i % 5 else (1200, 1600)
    p = os.path.join(tmp, f"site{i:02d}.jpg")
    TP.site_photo(w, h, seed=i).save(p, "JPEG", quality=90)
    paths.append(p)
rep = orp.new_report(s, T.WE, online=False)
orp.add_photos(s, rep, paths)
orp.draft_from_daily_logs(s, rep)
rep["weather"].update({"threshold_in": 0.5,
                       "days": L.weather_days(TL.rain_rows(), 0.5)})
tot = L.weather_totals(rep["weather"])
rows = []
from datetime import timedelta                                 # noqa: E402
for i, rain in enumerate([0.78, 0.01, 0.06, 0.17, 0.49, 0.0, 0.6, 0.04,
                          0.11, 0.07]):
    d = date(2026, 10, 21) + timedelta(days=i)
    rows.append({"date": d.isoformat(), "sky": "Showers", "high": 85,
                 "low": 71, "rain_chance": 40, "rain_in": rain, "wind": 12})
rep["forecast"].update({"mode": "table", "rows": rows,
                        "as_of": "2026-10-20"})
res = orp.build_pdf(s, rep, sys.argv[1])
print("default:", res["pages"], "pages", res["bytes"], "bytes",
      [m[0] for m in res["page_map"]], res.get("warnings"))
if len(sys.argv) > 2:
    for k in list(rep["options"]):
        if isinstance(rep["options"][k], bool):
            rep["options"][k] = True
    rep["options"]["key_plan"] = rep["options"]["work_areas"] = False
    rep.setdefault("decisions", []).append(
        {"text": "Approve the pool tile color", "due": "2026-10-22",
         "impact": "Tile order (6-week lead)", "ref": "RFI 004",
         "done": False})
    res = orp.build_pdf(s, rep, sys.argv[2])
    print("all:", res["pages"], "pages", res["bytes"], "bytes",
          [m[0] for m in res["page_map"]], res.get("warnings"))
