import os, sys, traceback
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tests"))
from app import qa, doccontrol
from test_project import _set
d = _set()
doccontrol.scan_register(d)
pid = qa.add_punch(d, "Patch", "Room 204")
qa.pin(d, pid, 2, (500, 400))
print("after pin", d.embfile_names(), len(doccontrol.read(d)["sheets"]))
qa.set_status(d, pid, "ready")
print("after status", d.embfile_names(), len(doccontrol.read(d)["sheets"]))
try:
    raw = d.embfile_get("pdfstudio_doccontrol.json")
    print(raw[:80])
except Exception:
    traceback.print_exc()
