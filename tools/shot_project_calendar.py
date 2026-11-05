"""Picture of the Project Center Calendar page on a made-up job in a temp
folder (never a real project).
    python tools/shot_project_calendar.py [week] -> .work/diag/project_calendar_<mode>.png"""
import os
import sys
import tempfile
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
if os.path.isdir(r"C:\Windows\Fonts"):
    os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")
tmp = tempfile.mkdtemp(prefix="pc_shot_")
from app import settings  # noqa: E402
settings.DIR = os.path.join(tmp, "cfg")
settings.PATH = os.path.join(tmp, "cfg", "s.json")
settings._cache = {"author": "Pat Morgan"}
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
app = QApplication.instance() or QApplication([])
app.setFont(QFont("Segoe UI", 9))
from app.pm.store import ProjectStore  # noqa: E402
from app.pm import center  # noqa: E402

mode = sys.argv[1] if len(sys.argv) > 1 else "month"
s = ProjectStore(os.path.join(tmp, "Example Clinic"))
s.set_setting("holidays", ["2026-11-26", "2026-11-27"])
s.set_setting("data_date", "2026-10-30")
add = lambda **r: s.save_record("activity", r)        # noqa: E731
add(name="Mobilize", duration=2, start="2026-11-02")
add(name="Excavate", duration=5, preds=[{"id": "A0001"}])
add(name="Footings", duration=4, preds=[{"id": "A0002"}])
add(name="Underground plumbing", duration=3, preds=[{"id": "A0003"}])
add(name="Foundations done", duration=0, preds=[{"id": "A0003"}])
add(name="Slab on grade", duration=4, preds=[{"id": "A0004"}])
add(name="Steel erection", duration=6, preds=[{"id": "A0006"}])
s.save_record("inspection", {"title": "Footing inspection",
                             "date": "2026-11-13", "status": "Scheduled"})
s.save_record("inspection", {"title": "Under-slab plumbing",
                             "date": "2026-11-19", "status": "Scheduled"})
s.save_record("meeting", {"title": "OAC #4", "date": "2026-11-10",
                          "time": "9:00", "type": "OAC"})
s.save_record("meeting", {"title": "OAC #5", "date": "2026-11-24",
                          "time": "9:00", "type": "OAC"})
s.save_record("expedite", {"item": "Rebar", "expected": "2026-11-09"})
s.save_record("expedite", {"item": "Steel joists",
                           "expected": "2026-11-30"})
w = center.ProjectCenter(s)
w.resize(1360, 900)
w.show()
p = w.show_tool("calendar")
p.cal.today = date(2026, 11, 4)
p.cal.go_today()
if mode == "week":
    p.cal.set_mode("week")
app.processEvents()
out = os.path.join(ROOT, ".work", "diag", f"project_calendar_{mode}.png")
os.makedirs(os.path.dirname(out), exist_ok=True)
w.grab().save(out)
print("picture:", out)
w.close()
