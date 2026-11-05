"""Render trial PDFs with every layer switched on."""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import fitz
OUT = os.path.join(ROOT, ".run", "dxf_trial")
for name in ("gdsestimating__api-cw750-details_sheets.pdf", "gdsestimating__api-cw750-details.pdf", "mozman__VP4_sheets.pdf"):
    d = fitz.open(os.path.join(OUT, name))
    d.set_layer(-1, basestate="ON", on=list(d.get_ocgs().keys()))
    for i, pg in enumerate(d):
        if i < 4:
            pg.get_pixmap(dpi=55).save(os.path.join(OUT, f"ON_{name[:-4]}_{i + 1}.png"))
    print(name, d.page_count, len(d.get_ocgs()))
