import os, sys, traceback
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tests"))
from app import qa, doccontrol
from test_project import _set
d = _set()
print(doccontrol.scan_register(d), d.embfile_names())
print(len(doccontrol.read(d)["sheets"]))
pid = qa.add_punch(d, "Patch", "Room 204")
print(d.embfile_names(), len(doccontrol.read(d)["sheets"]))
try:
    print(doccontrol.register(d))
except Exception:
    traceback.print_exc()
