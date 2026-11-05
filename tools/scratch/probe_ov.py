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
old, new = fitz.open(po), fitz.open(pn)
res = overlay.compare(old, new)
print([(r["sheet"], r["old"], r["new"], r["align"]) for r in res])
doc = overlay.overlay_document(old, new, res, "Rev 1", "Rev 2", clouds=False)
p = doc[[r["sheet"] for r in res].index("A-101")]
for c in p.get_contents(): print("content", doc.xref_stream(c))
print("res", doc.xref_object(int(doc.xref_get_key(p.xref, "Resources")[1].split()[0])))
for x in range(1, doc.xref_length()):
    try:
        o = doc.xref_object(x)
        if "Transparency" in o or "OCG" in o or "/Form" in o:
            print(x, o.replace("\n", " ")[:300]); print("   stream", (doc.xref_stream(x) or b"")[:200])
    except Exception as e: pass
print("ocgs", doc.get_ocgs())
for pt in [(215, 109), (165, 309), (265, 249), (300, 30)]:
    print(pt, T._rgb(p, *pt))
