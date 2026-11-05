"""Print the SHA-256 of each installer in release\\ and release\\github\\
for the current version:  python tools/release_hashes.py"""
import glob
import hashlib
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app import __version__ as V                     # noqa: E402

for d in ("release", os.path.join("release", "github")):
    for p in sorted(glob.glob(os.path.join(ROOT, d, f"*{V}*"))):
        if not p.lower().endswith((".exe", ".msi")):
            continue
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for b in iter(lambda: f.read(1 << 20), b""):
                h.update(b)
        print(h.hexdigest().upper(), os.path.relpath(p, ROOT))
