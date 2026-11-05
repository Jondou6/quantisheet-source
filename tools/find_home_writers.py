"""Which test file touches Jon's REAL QuantiSheet files? (GUI test r42:
~/.quantisheet/prices.db and settings.json changed at 09:10, while a test
run was finishing.) Runs each given test file on its own and compares the
real data folder before and after: size, modified time and SHA-256 of each
file (contents are never printed).

    python tools/find_home_writers.py tests/test_a.py tests/test_b.py ..."""
import hashlib
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOMES = [os.path.join(os.path.expanduser("~"), d)
         for d in (".quantisheet",)]


def snap():
    out = {}
    for h in HOMES:
        if not os.path.isdir(h):
            continue
        for name in os.listdir(h):
            p = os.path.join(h, name)
            if not os.path.isfile(p):
                continue
            st = os.stat(p)
            if st.st_size > 200 * 1024 * 1024:
                dig = "big"
            else:
                d = hashlib.sha256()
                with open(p, "rb") as f:
                    for b in iter(lambda: f.read(1 << 20), b""):
                        d.update(b)
                dig = d.hexdigest()[:16]
            out[p] = (st.st_size, st.st_mtime_ns, dig)
    return out


def diff(a, b):
    lines = []
    for p in sorted(set(a) | set(b)):
        if a.get(p) == b.get(p):
            continue
        if p not in a:
            lines.append(f"    NEW      {p}")
        elif p not in b:
            lines.append(f"    REMOVED  {p}")
        else:
            what = "CONTENT" if a[p][2] != b[p][2] else "time only"
            lines.append(f"    CHANGED ({what}) {p}")
    return lines


hits = 0
for t in sys.argv[1:]:
    before = snap()
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x",
                        "-p", "no:cacheprovider", t], cwd=ROOT,
                       capture_output=True, text=True, timeout=1500)
    after = snap()
    d = diff(before, after)
    tail = (r.stdout.strip().splitlines() or ["?"])[-1]
    print(f"{t}: {tail}")
    if d:
        hits += 1
        print("  TOUCHED THE REAL DATA FOLDER:", *d, sep="\n")
print(f"\n{hits} test file(s) touched the real data folder")
