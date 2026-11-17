"""Time doc.tobytes() against saving to a temp file and reading it back
(read-only on the input): python tools/diag_tobytes.py PDF-GLOB"""
import glob
import os
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
import fitz  # noqa: E402

path = sorted(glob.glob(os.path.join(ROOT, sys.argv[1])))[0]
doc = fitz.open(path)
for _ in range(2):
    t = time.perf_counter()
    a = doc.tobytes()
    t1 = time.perf_counter() - t
    t = time.perf_counter()
    fd, tmp = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    doc.save(tmp)
    with open(tmp, "rb") as f:
        b = f.read()
    os.unlink(tmp)
    t2 = time.perf_counter() - t
    t = time.perf_counter()
    import io
    bio = io.BytesIO()
    doc.save(bio)
    c = bio.getvalue()
    t3 = time.perf_counter() - t
    print(f"{len(a) / 1e6:.0f} MB  tobytes {t1:.2f}s  temp file {t2:.2f}s  "
          f"BytesIO {t3:.2f}s  same {a == b == c}")
fd, tmp = tempfile.mkstemp(suffix=".pdf")
os.close(fd)
doc.save(tmp)
b1 = open(tmp, "rb").read()
doc.save(tmp)
b2 = open(tmp, "rb").read()
os.unlink(tmp)
a1, a2 = doc.tobytes(), doc.tobytes()
print("tobytes stable", a1 == a2, " temp stable", b1 == b2,
      " tobytes == temp", a1 == b1)
if a1 != b1:
    i = next(k for k in range(min(len(a1), len(b1))) if a1[k] != b1[k])
    print("first difference at", i, "of", len(a1), len(b1),
          a1[i - 40:i + 40], b1[i - 40:i + 40])
