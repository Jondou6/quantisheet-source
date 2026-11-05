"""Code signing for the build (Nov 4, Jon: get it ready for the
certificate). Off until a certificate is set up; then every program and
installer the build makes is signed, so Windows shows the publisher
instead of "Unknown publisher".

Set up (once, by Jon, after buying the certificate):
  1. Install the certificate the way the seller says. Code signing
     certificates now live on a USB token or in a cloud signing service,
     so it shows in Windows' certificate store.
  2. Put its thumbprint in ~/QuantiSheet Keys/codesign.json:
        {"thumbprint": "AB12...", "timestamp": "http://timestamp.digicert.com"}
     (the folder that already holds the update signing key - never the
     repository). No password is stored anywhere; the token asks for its
     own PIN when signing.

The build then signs QuantiSheet.exe and ClaimIT.exe before packaging,
and every setup .exe and .msi after. A signing failure stops the build
(an unsigned release is never mixed into a signed one).
"""
import glob
import json
import os
import shutil
import subprocess

KEYS = os.path.join(os.path.expanduser("~"), "QuantiSheet Keys")
CONFIG = os.path.join(KEYS, "codesign.json")
DEFAULT_TS = "http://timestamp.digicert.com"


def config():
    """The signing settings, or None when signing isn't set up."""
    try:
        with open(CONFIG, encoding="utf-8") as f:
            c = json.load(f)
    except (OSError, ValueError):
        return None
    tp = "".join(ch for ch in str(c.get("thumbprint", "")) if ch.isalnum())
    if len(tp) != 40:
        return None
    return {"thumbprint": tp.upper(),
            "timestamp": c.get("timestamp") or DEFAULT_TS}


def find_signtool():
    exe = shutil.which("signtool")
    if exe:
        return exe
    for base in (r"C:\Program Files (x86)\Windows Kits\10\bin",
                 r"C:\Program Files\Windows Kits\10\bin"):
        hits = sorted(glob.glob(os.path.join(base, "*", "x64",
                                             "signtool.exe")))
        if hits:
            return hits[-1]
    return None


def command(files, cfg, signtool):
    return [signtool, "sign", "/sha1", cfg["thumbprint"], "/fd", "SHA256",
            "/tr", cfg["timestamp"], "/td", "SHA256", "/d", "QuantiSheet",
            *files]


def sign(files, log=print, run=subprocess.run):
    """Sign `files` when signing is set up. Returns how many were signed
    (0 = not set up). Raises RuntimeError when signing fails."""
    cfg = config()
    files = [f for f in files if f and os.path.isfile(f)]
    if cfg is None or not files:
        return 0
    tool = find_signtool()
    if not tool:
        raise RuntimeError("code signing is set up but signtool.exe isn't "
                           "installed (Windows SDK > Signing Tools)")
    r = run(command(files, cfg, tool), capture_output=True, text=True,
            timeout=900)
    if r.returncode != 0:
        raise RuntimeError("code signing failed: " +
                           (r.stderr or r.stdout or "")[-400:])
    log(f"   signed {len(files)} file(s) with certificate "
        f"{cfg['thumbprint'][:8]}...")
    return len(files)


def status():
    cfg = config()
    if cfg is None:
        return "code signing: not set up (no certificate yet)"
    return (f"code signing: certificate {cfg['thumbprint'][:8]}..., "
            f"signtool {'found' if find_signtool() else 'MISSING'}")


if __name__ == "__main__":
    print(status())
