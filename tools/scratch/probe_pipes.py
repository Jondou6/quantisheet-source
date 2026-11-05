import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tests"))
import test_tradetakeoff as T
from app import tradetakeoff as tt
d = T.plumbing()
for p in d[0].get_drawings():
    print(p.get("type"), p.get("color"), p.get("width"), p.get("dashes"), [it[0] for it in p["items"]])
for k, v in tt.styled_segments(d[0]).items():
    print(k, len(v), [round(sum(((s[2]-s[0])**2+(s[3]-s[1])**2)**.5 for s in v)/18, 1)], [len(r) for r in tt.runs(v)])
