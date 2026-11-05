"""Unpack a zip from _incoming into _incoming\\plans (Nov 2: the HMB plan
set handed over by Chief). Only .pdf / .csv / .txt members are written,
never into the program folders; existing files are left alone.

    python tools/unpack_incoming.py NAME.zip
"""
import hashlib
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INC = os.path.join(ROOT, "_incoming")
OUT = os.path.join(INC, "plans")


def main(argv):
    name = os.path.basename(argv[0].strip('"'))
    src = os.path.join(INC, name)
    os.makedirs(OUT, exist_ok=True)
    with zipfile.ZipFile(src) as z:
        for m in z.namelist():
            base = os.path.basename(m)
            if not base or not base.lower().endswith((".pdf", ".csv",
                                                      ".txt")):
                print("skipped", m)
                continue
            dst = os.path.join(OUT, base)
            if os.path.exists(dst):
                print("exists, left alone:", dst)
            else:
                with z.open(m) as f, open(dst, "wb") as g:
                    g.write(f.read())
                print("wrote", dst)
            with open(dst, "rb") as f:
                print("   sha256", hashlib.sha256(f.read()).hexdigest())


if __name__ == "__main__":
    main(sys.argv[1:])
