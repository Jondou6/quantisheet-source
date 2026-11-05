"""Debug: print the punch list PDF text (test steps)."""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tests"))
import fitz
from app import qa, doccontrol
from test_project import _set
d = _set()
doccontrol.scan_register(d)
pid = qa.add_punch(d, "Patch drywall at outlet", "Room 204", "Drywall", "Acme Drywall", "2026-01-10")
ref = qa.pin(d, pid, 2, (500, 400))
qa.set_status(d, pid, "ready", "fixed")
qa.set_status(d, pid, "open", "x")
qa.set_status(d, pid, "closed")
qa.add_punch(d, "Missing cover plate", trade="Electrical", due="2020-01-01")
print(qa._sheet_names(d)); print([(p["id"], p["page"]) for p in qa.punch(d)])
path = os.path.join(tempfile.gettempdir(), "dbg_punch.pdf")
qa.punch_pdf(d, path)
print(repr(fitz.open(path)[0].get_text()))
