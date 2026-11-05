"""Use the real app (offscreen) on a real DXF: import sheets, trace a
line, measure, export back to DXF; save screenshots."""
import os, sys, json
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import fitz
from PySide6.QtWidgets import QApplication, QMessageBox
from app import annotate, settings
from app.main_window import MainWindow
OUT = os.path.join(ROOT, ".run", "dxf_trial")
settings.DIR = os.path.join(OUT, "cfg"); settings.PATH = os.path.join(OUT, "cfg", "s.json"); settings._cache = None
for n in ("information", "warning"):
    setattr(QMessageBox, n, staticmethod(lambda *a, **k: 0))
app = QApplication.instance() or QApplication([])
w = MainWindow(); w.resize(1600, 1000); w.show()
src = os.path.join(OUT, "src", "gdsestimating__api-cw750-details.dxf")
pdf = os.path.join(OUT, "app_sheets.pdf")
info = w.import_dxf(src, pdf, what="layouts")
print("import:", json.dumps(info))
print("status:", w.statusBar().currentMessage())
v = w._view
res = []
for page in range(v.doc.page_count):
    v.go_to(page)
    app.processEvents()
    vps = annotate.read_viewports(v.doc, page)
    idx = v.snap_index()
    for vp in vps:
        r = fitz.Rect(vp["rect"])
        segs = [s for s in idx.segs if r.contains(fitz.Point(s[0])) and r.contains(fitz.Point(s[1]))]
        if not segs:
            continue
        a, b = max(segs, key=lambda s: (s[0][0]-s[1][0])**2 + (s[0][1]-s[1][1])**2)
        v.set_zoom(1.0); v.set_tool("trace_length")
        n = v.commit_click("trace_length", fitz.Point((a[0]+b[0])/2, (a[1]+b[1])/2))
        items = [i for i in annotate.takeoff_items(v.doc) if i["page"] == page and i["type"] == "length"]
        res.append({"page": page + 1, "viewport": vp["name"], "label": vp["label"], "traced": n,
                    "value": items[-1]["value"] if items else None, "unit": items[-1]["unit"] if items else None,
                    "seg_pts": round(((a[0]-b[0])**2+(a[1]-b[1])**2)**0.5, 1)})
    w.fit_page(); app.processEvents()
    w.grab().save(os.path.join(OUT, f"APP_page{page + 1}.png"))
print("traces:", json.dumps(res, indent=0))
out = w.export_dxf(os.path.join(OUT, "app_back.dxf"))
print("export:", out, w.statusBar().currentMessage())
v.dirty = False
w.close()
