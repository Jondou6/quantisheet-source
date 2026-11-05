"""Debug: print the punch list PDF text."""
import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import fitz
from app import qa, forms
d = fitz.open(); d.new_page()
pid = qa.add_punch(d, "Patch drywall at outlet", "Room 204", "Drywall", "Acme Drywall", "2026-01-10")
qa.set_status(d, pid, "closed")
qa.add_punch(d, "Missing cover plate", trade="Electrical", due="2020-01-01")
path = os.path.join(tempfile.gettempdir(), "dbg_punch.pdf")
qa.punch_pdf(d, path)
t = fitz.open(path)[0].get_text()
print(repr(t))
print(forms.wrap("Patch drywall at outlet", 200, 8))
