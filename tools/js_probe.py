"""Diagnose the page-script clean-up check."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import fitz  # noqa: E402

from app import acrobat2  # noqa: E402

d = fitz.open()
p = d.new_page()
p.insert_text((72, 72), "SHEET A-101")
d.xref_set_key(p.xref, "AA", "<</O<</S/JavaScript/JS(app.alert(1))>>>>")
print("page AA before:", d.xref_get_key(p.xref, "AA"))
acrobat2.sanitize(d)
print("page AA after sanitize:", d.xref_get_key(d[0].xref, "AA"))
acrobat2._remove_directly(d, "javascript")
print("page AA after direct:", d.xref_get_key(d[0].xref, "AA"))
c = fitz.open("pdf", d.tobytes(garbage=3))
for x in range(1, c.xref_length()):
    o = c.xref_object(x, compressed=False)
    if "JavaScript" in o or "/JS" in o or "/AA" in o:
        print("xref", x, o[:300])
print("catalog:", c.xref_object(c.pdf_catalog())[:300])
for row in acrobat2.verify_clean(d):
    print(row)
