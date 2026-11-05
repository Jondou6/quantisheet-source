"""Diagnostic: does apply_redactions remove line art here? (made-up page)"""
import fitz

print("PyMuPDF", fitz.VersionBind, "MuPDF", fitz.VersionFitz)
for name in ("PDF_REDACT_LINE_ART_NONE", "PDF_REDACT_LINE_ART_REMOVE_IF_COVERED",
             "PDF_REDACT_LINE_ART_REMOVE_IF_TOUCHED", "PDF_REDACT_IMAGE_PIXELS",
             "PDF_REDACT_TEXT_REMOVE"):
    print(name, getattr(fitz, name, "missing"))
box = fitz.Rect(150, 320, 330, 410)
for g in (0, 1, 2):
    d = fitz.open()
    p = d.new_page()
    p.draw_line((170, 330), (310, 400), color=(1, 0, 0), width=1)
    p.draw_line((60, 380), (550, 380), color=(0, 0, 1), width=1.5)
    p.draw_rect((200, 340, 250, 380), color=(0, 1, 0), width=1)
    p.add_redact_annot(box, fill=(0, 0, 0))
    try:
        p.apply_redactions(images=2, graphics=g)
        how = "graphics=%d" % g
    except TypeError as e:
        how = "TypeError %s" % e
    left = [(x["type"], x.get("color"), tuple(round(v) for v in x["rect"]))
            for x in p.get_drawings()]
    print(how, "->", left)

d = fitz.open()
p = d.new_page()
p.draw_line((170, 330), (310, 400), color=(1, 0, 0), width=1)
p.add_redact_annot(box, fill=(0, 0, 0))
try:
    p.apply_redactions(images=2, graphics=2, text=0)
    print("with text=0 ok ->", [x["type"] for x in p.get_drawings()])
except Exception as e:
    print("with text=0 raised", type(e).__name__, e)
import inspect
print(inspect.signature(fitz.Page.apply_redactions))
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import redaction
d = fitz.open()
p = d.new_page()
p.draw_line((170, 330), (310, 400), color=(1, 0, 0), width=1)
redaction.redact(d, p, box)
print("app redact ->", [(x["type"], x.get("color")) for x in p.get_drawings()])
