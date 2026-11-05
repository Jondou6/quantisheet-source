"""Which filled paths are big on a page: python tools/fills_probe.py FILE PAGE"""
import sys
import fitz
from collections import Counter
doc = fitz.open(sys.argv[1].strip('"'))
pg = doc[int(sys.argv[2]) - 1]
c = Counter()
big = []
for p in pg.get_drawings():
    if p.get("fill") is not None:
        r = fitz.Rect(p["rect"])
        key = (p.get("type"), tuple(round(x, 2) for x in p["fill"]),
               p.get("fill_opacity"))
        c[key] += 1
        if r.width * r.height > 2000:
            big.append((round(r.width * r.height), key, len(p["items"])))
print(c.most_common(15))
big.sort(reverse=True)
print(big[:20])
