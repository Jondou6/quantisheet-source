"""Check the live team update on R2 the way a tester's QuantiSheet does
(Nov 2): fetch version.json from the public link, check its Ed25519
signature with the public key the program ships, then download the
installer from the link it names and check its size and SHA-256. Also
compares both with the local upload folder. Downloads go to a temp
folder; nothing is installed.

    python tools/verify_update.py
"""
import hashlib
import json
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main():
    from app import updatecheck as uc
    print("manifest:", uc.MANIFEST_URL)
    raw = uc.fetch_manifest()
    m = uc.parse_manifest(raw)                     # raises if bad signature
    print("signature: OK (public key shipped in the program)")
    print("version:", m["version"], "| installer:", m.get("url"))
    print("size:", m.get("size"), "| sha256:", m.get("sha256"))
    print("newer than 1.0.1 (what testers have):",
          uc.is_newer(m["version"], "1.0.1"))
    print("newer than itself (no loop on 1.0.2):",
          uc.is_newer(m["version"], m["version"]))
    up = os.path.join(ROOT, "release", "r2_upload")
    local = next((os.path.join(up, d, "team") for d in os.listdir(up)
                  if os.path.isdir(os.path.join(up, d, "team"))), None)
    if local:
        with open(os.path.join(local, "version.json"), "rb") as f:
            print("version.json same as the local upload copy:",
                  f.read() == raw)
    tmp = tempfile.mkdtemp(prefix="qs_verify_upd_")
    try:
        p = uc.download(m, folder=tmp)             # checks size and SHA-256
        print("installer download: OK -", os.path.getsize(p), "bytes,",
              "SHA-256 matches the signed manifest")
        exe = os.path.join(local or "", os.path.basename(p)) if local \
            else None
        rel = os.path.join(ROOT, "release", "QuantiSheet-Beta-Setup-"
                           f"{m['version']}.exe")
        for name, q in (("upload folder", exe), ("release folder", rel)):
            if q and os.path.isfile(q):
                print(f"same as the {name} installer:", sha(q) == sha(p))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print(json.dumps({"ok": True}))


if __name__ == "__main__":
    main()
