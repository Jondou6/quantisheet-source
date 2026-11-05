"""Picture of the Back Office Time Off page on made-up data (a throwaway
company in a temp folder; never the real Back Office data).
    python tools/shot_timeoff.py [week]  ->  .work/diag/timeoff_<mode>.png"""
import os
import sys
import tempfile
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):             # real text offscreen
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
tmp = tempfile.mkdtemp(prefix="bo_shot_")
os.environ["QS_BACKOFFICE_HOME"] = os.path.join(tmp, "home")

from quantisheet_backoffice import clock, hr, pto, security, settings, timeoff  # noqa: E402,E501
from quantisheet_backoffice.tests.helpers import make_office  # noqa: E402
from quantisheet_backoffice.tests.m3_helpers import add_hr  # noqa: E402

security.PBKDF2_ROUNDS = 2000
settings.reload()
clock.set_now(datetime(2026, 11, 4, 10, 0, 0))
mode = sys.argv[1] if len(sys.argv) > 1 else "month"
from PySide6.QtWidgets import QApplication  # noqa: E402
app = QApplication.instance() or QApplication([])
from PySide6.QtGui import QFont  # noqa: E402
app.setFont(QFont("Segoe UI", 9))
o = make_office(os.path.join(tmp, "data"))
add_hr(o)
o.act_as("hr@bo.test")
people = [("R. Diaz", "E401"), ("M. Chen", "E402"), ("L. Park", "E403"),
          ("T. Okafor", "E404"), ("S. Novak", "E405")]
ids = []
for name, no in people:
    eid = hr.add_employee(o, name, no, "2025-01-06", labor_class="LAB")
    pol = pto.add_policy(o, f"PTO {no}", per_hours="30", cap="120")
    pto.assign(o, eid, pol)
    pto.adjust(o, eid, "2026-10-01", "80", "opening balance")
    ids.append(eid)
timeoff.add_holiday(o, "2026-11-11", "Veterans Day")
timeoff.add_holiday(o, "2026-11-26", "Thanksgiving")
timeoff.add_holiday(o, "2026-11-27", "Day after Thanksgiving")
for i, (a, b) in zip(ids, [("2026-11-09", "2026-11-13"),
                           ("2026-11-02", "2026-11-03"),
                           ("2026-11-16", "2026-11-20"),
                           ("2026-11-23", "2026-11-25"),
                           ("2026-11-04", "2026-11-04")]):
    rid = pto.request(o, i, a, b, "8", note="family" if i == ids[0] else "")
    if i in (ids[0], ids[1], ids[4]):
        pto.decide(o, rid, "approve")
pto.request(o, ids[1], "2026-11-30", "2026-12-01", "8", note="appointment")
r = pto.request(o, ids[3], "2026-12-07", "2026-12-07", "8")
pto.decide(o, r, "reject")
from quantisheet_backoffice.ui.timeoff_page import TimeOffPage  # noqa: E402
pg = TimeOffPage(o, today="2026-11-04")
if mode == "week":
    pg.cal.set_mode("week")
pg.resize(1280, 940)
pg.show()
app.processEvents()
out = os.path.join(ROOT, ".work", "diag", f"timeoff_{mode}.png")
os.makedirs(os.path.dirname(out), exist_ok=True)
pg.grab().save(out)
print("picture:", out)
o.close()
