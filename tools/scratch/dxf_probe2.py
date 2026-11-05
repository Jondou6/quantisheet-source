import collections, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import ezdxf
p = os.path.join(ROOT, ".run", "dxf_trial", "src", "gdsestimating__api-cw750-details.dxf")
d = ezdxf.readfile(p)
msp = d.modelspace()
per = collections.Counter(e.dxf.layer for e in msp)
for l in d.layers:
    print(f"{l.dxf.name:30s} on={l.is_on()} frozen={l.is_frozen()} color={l.dxf.color} n={per.get(l.dxf.name, 0)}")
print("layouts", [ (lay.name, len(lay)) for lay in d.layouts])
for e in msp.query("MTEXT")[:5]:
    print("mtext", e.dxf.char_height, repr(e.plain_text()[:40]), e.dxf.layer)
ins = collections.Counter((e.dxf.name, e.dxf.layer) for e in msp.query("INSERT"))
print(ins.most_common(8))
