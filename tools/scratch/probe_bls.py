import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bls
cands = ["WPU1017", "WPU1025", "WPU102502", "WPU0811", "WPU081", "WPU1321", "WPU1322",
         "WPU133", "WPU1333", "WPU107", "WPU1074", "WPU1073", "PCU23811X", "PCU23816X",
         "PCU23821X", "PCU23822X", "PCU238110238110", "PCU238160238160", "PCU238210238210",
         "PCU238220238220", "WPUIP2312301", "WPU0581", "WPU057303", "WPU1392"]
try:
    data = bls.fetch_series(cands, 2023, 2026, None)
except Exception as e:
    print("FETCH FAILED", repr(e)); raise
for s in cands:
    pts = data.get(s) or {}
    ks = sorted(pts)
    print(f"{s:<18} n={len(pts):>3}  {ks[0] if ks else '-'} .. {ks[-1] if ks else '-'}  last={pts[ks[-1]] if ks else '-'}")
json.dump(data, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "trial_output", "ppi_probe.json"), "w"))
