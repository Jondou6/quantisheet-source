"""Zip the newest installer and its What's New PDF for the team, onto the
Desktop:  python tools/zip_release.py"""
import glob
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app import __version__ as V                     # noqa: E402
sys.path.insert(0, os.path.join(ROOT, "tools"))
import ship_check                                    # noqa: E402

REL = os.path.join(ROOT, "release")
NAME = "QuantiSheet"
setup = os.path.join(REL, f"{NAME}-Beta-Setup-{V}.exe")
notes = os.path.join(REL, f"{NAME} {V} - Whats New.pdf")
missing = [p for p in (setup, notes) if not os.path.isfile(p)]
if missing:
    raise SystemExit("missing: " + ", ".join(missing))
desk = os.path.dirname(ROOT) if os.path.basename(os.path.dirname(ROOT)) \
    .lower() == "desktop" else os.path.join(os.path.expanduser("~"), "Desktop")
out = os.path.join(desk, f"{NAME} {V} for the team.zip")
import hashlib
with open(setup, "rb") as f:
    sha = hashlib.sha256(f.read()).hexdigest().upper()
import release_files                                  # noqa: E402
claims = sorted(glob.glob(os.path.join(REL, "ClaimIT-Setup-*.exe")),
                key=os.path.getmtime)
claims = claims[-1] if claims else None
csha = None
if claims:
    with open(claims, "rb") as f:
        csha = hashlib.sha256(f.read()).hexdigest().upper()
readme = release_files.readme_text(
    V, sha, (os.path.basename(claims), csha) if claims else None)
print("SHA256", sha)
# the hash also goes out on its own (a text or email from Jon), so a
# swapped zip can't carry a matching hash with it
with open(os.path.join(desk, f"{NAME} {V} SHA256.txt"), "w") as f:
    f.write(f"{NAME}-Beta-Setup-{V}.exe\nSHA256 {sha}\n")
    if claims:
        f.write(f"{os.path.basename(claims)}\nSHA256 {csha}\n")
# nothing that must never ship goes in the zip (review 0.12.35 #21)
ship_check.require_clean([os.path.basename(p) for p in
                          (setup, notes, claims) if p] +
                         ["READ ME FIRST.txt"], "the team zip")
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    z.write(setup, os.path.basename(setup))
    z.write(notes, os.path.basename(notes))
    if claims:
        z.write(claims, os.path.basename(claims))
    z.writestr("READ ME FIRST.txt", readme)
print(out, f"{os.path.getsize(out) / 1e6:.1f} MB")
for p in glob.glob(os.path.join(REL, "*")):
    print("  release:", os.path.basename(p))

# the server setup and the public (GitHub) copies: their hashes, for the
# release page and for IT (SHA256SUMS.txt beside them)
GH = os.path.join(REL, "github")


def _sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


server = os.path.join(REL, f"{NAME}-Beta-Server-Setup-{V}.exe")
if os.path.isfile(server):
    print("SHA256 server", _sha(server))
msi = os.path.join(REL, f"{NAME}-Beta-{V}.msi")
if os.path.isfile(msi):
    print("SHA256 msi", _sha(msi))
import release_files                                  # noqa: E402
rf = release_files.refresh(ROOT, V)
for ln in rf["sums"]:
    print("  github:", ln)
