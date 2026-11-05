import sys, os, tempfile
R = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, R); sys.path.insert(0, os.path.join(R, "tests"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import fitz
from app import overlay
import test_overlay as T
from pathlib import Path
d = Path(tempfile.mkdtemp())
po, pn = T._sets(d)
doc, new = fitz.open(po), fitz.open(pn)
res = overlay.compare(doc, new)
overlay.slip_sheet(doc, new, res, "Rev 1")
p = doc[0]
for c in p.get_contents(): print("content", c, doc.xref_stream(c))
rx = doc.xref_get_key(p.xref, "Resources"); print("resref", rx)
if rx[0] == "xref": print(doc.xref_object(int(rx[1].split()[0])))
print("ocgs", doc.get_ocgs()); print("layer", doc.get_layer(-1)); print("cat OCP", doc.xref_get_key(doc.pdf_catalog(), "OCProperties"))
print("live", T._rgb(p, 150, 300))
out = str(d / "s.pdf"); doc.save(out)
d2 = fitz.open(out); print("reopen", T._rgb(d2[0], 150, 300), d2.get_layer(-1))
for x in range(1, doc.xref_length()):
    o = doc.xref_object(x)
    if "Transparency" in o: print(x, o.replace("\n"," ")[:400], doc.xref_stream(x))
