"""Sign the team copy's version.json for this version and lay out the two
files to upload to R2, at the same paths the program will ask for:

    python tools/sign_team_update.py

    -> release/r2_upload/<folder>/team/version.json
       release/r2_upload/<folder>/team/QuantiSheet-Beta-Setup-<v>.exe

The private key is read from ~/QuantiSheet Keys/update_signing_key.pem and
stays there (never copied, printed or put in the repo). Uploading the two
files is a separate step."""
import os
import shutil
import subprocess
import sys
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app import __version__ as V                     # noqa: E402
from app import updatecheck                          # noqa: E402

KEY = os.path.join(os.path.expanduser("~"), "QuantiSheet Keys",
                   "update_signing_key.pem")
SETUP = f"QuantiSheet-Beta-Setup-{V}.exe"


def main():
    if ".invalid" in updatecheck.UPDATE_HOST:
        sys.exit("UPDATE_BASE is still the placeholder")
    if not os.path.isfile(KEY):
        sys.exit(f"no signing key at {KEY}")
    src = os.path.join(ROOT, "release", SETUP)
    if not os.path.isfile(src):
        sys.exit(f"missing {src}")
    folder = urlparse(updatecheck.UPDATE_BASE).path.strip("/")
    out = os.path.join(ROOT, "release", "r2_upload", folder, "team")
    os.makedirs(out, exist_ok=True)
    notes = os.path.join(ROOT, "docs", f"TEAM_NOTES_{V}.txt")
    url = updatecheck.UPDATE_BASE.rstrip("/") + "/team/" + SETUP
    cmd = [sys.executable, os.path.join(ROOT, "tools",
                                        "make_update_manifest.py"),
           "sign", "--key", KEY, "--installer", src, "--url", url,
           "--out", os.path.join(out, "version.json")]
    if os.path.isfile(notes):
        cmd += ["--notes-file", notes]
    r = subprocess.run(cmd)
    if r.returncode:
        sys.exit(r.returncode)
    shutil.copy2(src, os.path.join(out, SETUP))
    print("manifest URL:", updatecheck.MANIFEST_URL)
    print("installer URL:", url)
    print("upload folder:", out)
    for n in sorted(os.listdir(out)):
        print("  ", n, os.path.getsize(os.path.join(out, n)), "bytes")


if __name__ == "__main__":
    main()
