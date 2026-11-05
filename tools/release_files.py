"""The files that go beside the installers (review 0.13.9 #1, #2, #10):

    refresh(root, version) -> {"sums": [...], "notes": path, "readme": path}

- release/github/SHA256SUMS.txt, made again from the installers actually in
  release/github ('<sha256>  <name>' per *.exe / *.msi), replacing the old
  file - so it can never list an old version or miss a new one;
- release/github/RELEASE_NOTES.md, a copy of docs/GITHUB_RELEASE_<v>.md
  (a stale notes file is removed when this version has none);
- release/READ ME FIRST.txt, the hash-check steps the What's New PDF
  points to, with this version's installer hash.

Run at the end of every build (tools/build_installer.py) and by
tools/zip_release.py:  python tools/release_files.py"""
import glob
import hashlib
import os
import shutil
import sys

NAME = "QuantiSheet"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def readme_text(version, sha, claims=None):
    t = (f"{NAME} {version} (in-house beta)\r\n\r\n"
         "1. Check the installer is the one Jon sent. In the folder with the\r\n"
         "   installer, open PowerShell and run:\r\n"
         f"      Get-FileHash .\\{NAME}-Beta-Setup-{version}.exe\r\n"
         "   The Hash it prints must match this one exactly:\r\n"
         f"      {sha}\r\n"
         "   If it doesn't match, don't run it - tell Jon.\r\n"
         f"2. Run {NAME}-Beta-Setup-{version}.exe. The installer isn't signed "
         "yet,\r\n"
         "   so Windows warns about an unknown publisher. Only after the hash\r\n"
         "   matches: click More info, then Run anyway.\r\n"
         "3. Read the What's New PDF for what changed.\r\n"
         "4. Send problems and ideas to Jon: the drawing, the sheet and what\r\n"
         "   you clicked.\r\n\r\n"
         "The setup installs over an earlier version and keeps your\r\n"
         "settings, price database and jobs.\r\n\r\n"
         "For in-house testers only - please don't pass it on.\r\n")
    if claims:
        name, csha = claims
        t += ("\r\nOptional: ClaimIT (insurance claim estimates).\r\n"
              f"Install it after {NAME}: {name}\r\n"
              f"   SHA256 {csha}\r\n")
    return t


def refresh(root, version):
    rel = os.path.join(root, "release")
    gh = os.path.join(rel, "github")
    out = {"sums": [], "notes": None, "readme": None}
    if os.path.isdir(gh):
        pub = sorted(p for p in glob.glob(os.path.join(gh, "*"))
                     if p.lower().endswith((".exe", ".msi")))
        lines = [f"{sha256(p).lower()}  {os.path.basename(p)}" for p in pub]
        sums = os.path.join(gh, "SHA256SUMS.txt")
        if lines:
            with open(sums, "w", newline="\n") as f:
                f.write("\n".join(lines) + "\n")
        elif os.path.exists(sums):
            os.remove(sums)                       # nothing to vouch for
        out["sums"] = lines
        src = os.path.join(root, "docs", f"GITHUB_RELEASE_{version}.md")
        dst = os.path.join(gh, "RELEASE_NOTES.md")
        if os.path.isfile(src):
            shutil.copyfile(src, dst)
            out["notes"] = dst
        elif os.path.exists(dst):
            os.remove(dst)                        # an old version's notes
    setup = os.path.join(rel, f"{NAME}-Beta-Setup-{version}.exe")
    if os.path.isfile(setup):
        claims = sorted(glob.glob(os.path.join(rel, "ClaimIT-Setup-*.exe")),
                        key=os.path.getmtime)
        c = (os.path.basename(claims[-1]), sha256(claims[-1])) \
            if claims else None
        rd = os.path.join(rel, "READ ME FIRST.txt")
        with open(rd, "w", newline="") as f:
            f.write(readme_text(version, sha256(setup), c))
        out["readme"] = rd
    return out


if __name__ == "__main__":
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, ROOT)
    from app import __version__ as V                 # noqa: E402
    r = refresh(ROOT, V)
    for ln in r["sums"]:
        print("  github:", ln)
    print("notes:", r["notes"])
    print("readme:", r["readme"])
