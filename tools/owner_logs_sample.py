"""Sample log pages (made-up data) to look at: python tools/owner_logs_sample.py out.pdf"""
import os
import sys
import tempfile
import types
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import fitz                                                   # noqa: E402

from app import settings                                     # noqa: E402
from app.pm.store import ProjectStore                         # noqa: E402

tmp = tempfile.mkdtemp()
settings.DIR = os.path.join(tmp, "cfg")
settings.PATH = os.path.join(tmp, "cfg", "s.json")
settings._cache = {"author": "Pat Example"}
import test_owner_report_logs as T                            # noqa: E402
L = T.L
s = ProjectStore(os.path.join(tmp, "Job"))
T.add_rfis(s)
T.add_submittals(s)
T.add_change_events(s)
doc = fitz.open()
L.add_rfi_log(doc, s, T.HEAD, {})
L.add_submittal_log(doc, s, T.HEAD, {})
L.add_co_log(doc, s, T.HEAD, {})
w = {"threshold_in": 0.5, "days": L.weather_days(T.rain_rows(), 0.5)}
L.add_weather_log(doc, T.HEAD, w, {})
T.test_forecast_table.__code__  # noqa: B018
rows = []
from datetime import timedelta                                # noqa: E402
for i, rain in enumerate([0.78, 0.01, 0.06, 0.17, 0.49, 0.0, 0.6, 0.04,
                          0.11, 0.07]):
    d = date(2026, 10, 21) + timedelta(days=i)
    rows.append({"date": d.isoformat(), "sky": "Showers", "high": 85,
                 "low": 71, "rain_chance": 40, "rain_in": rain, "wind": 12})
L.add_forecast_page(doc, T.HEAD, {"mode": "table", "rows": rows,
                                  "as_of": "2026-10-20"}, {})
doc.save(sys.argv[1])
print("pages", doc.page_count)
