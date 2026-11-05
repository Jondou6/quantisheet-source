import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fitz
from app import annotate
print("pymupdf", fitz.VersionBind)
d = fitz.open(); pg = d.new_page()
op = annotate.new_op("add_rect", 0, rect=[100, 100, 200, 160], dashes=[6, 2, 1, 2])
annotate.apply_op(d, op)
pg = d[0]
for a in pg.annots():
    print("border", a.border, d.xref_object(a.xref)[:400])
a = pg.add_rect_annot(fitz.Rect(10, 10, 50, 50))
a.set_border(width=2, dashes=[5, 3]); print("direct before update", a.border)
a.update(); print("direct after update", a.border)
x = d.add_ocg("L1", on=True)
print("ocgs", d.get_ocgs())
d.set_layer(-1, on=[], off=[x])
print("after set_layer off", d.get_ocgs(), d.get_layer(-1))
d.set_layer(-1, off=[x])
print("after 2", d.get_ocgs())
print("layer ui", d.layer_ui_configs())
d.set_layer_ui_config(0, fitz.PDF_OC_OFF) if hasattr(fitz, "PDF_OC_OFF") else None
print("after ui", d.get_ocgs())
