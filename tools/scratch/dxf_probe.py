"""Probe a DXF's extents, text sizes and layers; look for floor plan samples."""
import collections, json, os, sys, urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import ezdxf
from ezdxf import bbox
SRC = os.path.join(ROOT, ".run", "dxf_trial", "src")
p = os.path.join(SRC, "gdsestimating__api-cw750-details.dxf")
d = ezdxf.readfile(p)
print("units", d.header.get("$INSUNITS"), "ext", d.header.get("$EXTMIN"), d.header.get("$EXTMAX"))
msp = d.modelspace()
types = collections.Counter(e.dxftype() for e in msp)
print(types)
far = []
for e in msp:
    try:
        b = bbox.extents([e])
        if b.has_data:
            far.append((round(b.extmin.x), round(b.extmin.y), round(b.extmax.x), round(b.extmax.y), e.dxftype(), e.dxf.layer))
    except Exception as ex:
        pass
xs = sorted(f[0] for f in far); ys = sorted(f[1] for f in far)
print("n", len(far), "x range", xs[:3], xs[-3:], "y range", ys[:3], ys[-3:])
for f in sorted(far, key=lambda f: -abs(f[1]))[:6]:
    print("outlier?", f)
hs = []
for e in msp.query("TEXT MTEXT"):
    hs.append(e.dxf.get("height", e.dxf.get("char_height", 0)))
for e in msp.query("INSERT"):
    blk = d.blocks.get(e.dxf.name)
    print("insert", e.dxf.name, e.dxf.insert, "scale", e.dxf.xscale, "layer", e.dxf.layer, collections.Counter(x.dxftype() for x in blk)) if blk else None
print("text heights", sorted(hs)[:5], sorted(hs)[-5:], len(hs))
print("layers", [(l.dxf.name, l.is_on(), l.is_frozen()) for l in d.layers][:20])
# search floor plans
def get(url):
    r = urllib.request.Request(url, headers={"User-Agent": "pdfstudio"})
    return urllib.request.urlopen(r, timeout=60).read()
try:
    res = json.loads(get("https://api.github.com/search/repositories?q=floor+plan+dxf&per_page=15"))
    for it in res.get("items", []):
        print("repo", it["full_name"], it["size"])
except Exception as e:
    print("search failed", e)
