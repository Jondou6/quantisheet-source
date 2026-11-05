import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bls
cands = ["PCU23811X23811X", "PCU23816X23816X", "PCU23821X23821X", "PCU23822X23822X",
         "WPU1017", "WPU107405", "WPU102502", "WPUSI004011", "WPU1333", "WPU1331",
         "WPU1392", "WPU13710102", "WPU062101", "WPU1311", "WPU1394", "WPU1321",
         "WPU1332", "WPU0721", "WPU1073", "WPU801", "WPUIP231200", "WPU1322", "WPU101706", "WPU112"]
data = bls.fetch_series(cands, 2023, 2026, None)
for s in cands:
    pts = data.get(s) or {}
    ks = sorted(pts)
    print(f"{s:<18} n={len(pts):>3}  {ks[0] if ks else '-'} .. {ks[-1] if ks else '-'}  last={pts[ks[-1]] if ks else '-'}")
