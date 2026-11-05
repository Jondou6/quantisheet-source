"""Print md5 of every source file (to check a copy is complete)."""
import hashlib
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for base in ("app", "tests", "tools"):
    for dp, dn, fn in os.walk(os.path.join(ROOT, base)):
        dn[:] = [d for d in dn if d != "__pycache__"]
        for f in sorted(fn):
            if f.endswith((".py", ".ps1", ".js", ".html", ".json")):
                p = os.path.join(dp, f)
                rel = os.path.relpath(p, ROOT).replace("\\", "/")
                with open(p, "rb") as fh:
                    print(hashlib.md5(fh.read()).hexdigest(), rel)
