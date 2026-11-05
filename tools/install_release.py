"""Install the newest built installer on this PC, silently (per-user
install, no admin). Closes QuantiSheet first. It installs to
...\\Programs\\QuantiSheet (an upgrade stays where the earlier one is).

    python tools/install_release.py
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from app import __version__ as V                     # noqa: E402
from app import branding                             # noqa: E402

ONLY_CLAIMS = len(sys.argv) > 1 and sys.argv[1] == "claims"
STATUS = os.path.join(ROOT, ".run", "build_installer.status")


def wait_for_build(limit_s=780, stale_s=5400):
    """Nov 1: `build_installer start/claims` runs in the background, so an
    install queued right behind it ran first and put the old setup back.
    Wait while a build says starting/running (a status untouched for 90
    minutes is a dead build, not a running one); refuse after a failed
    build."""
    import time
    t0 = time.time()
    while True:
        try:
            with open(STATUS) as fh:
                st = fh.read().strip()
            age = time.time() - os.path.getmtime(STATUS)
        except OSError:
            return
        if st.startswith("failed"):
            raise SystemExit("the last build failed - not installing: " +
                             st[:200])
        if not st.startswith(("starting", "running")) or age > stale_s:
            return
        if time.time() - t0 > limit_s:
            # under the runner's 15-minute limit: stop cleanly and say so
            raise SystemExit("a build is still running - not installing "
                             "yet; run install_release again when it's done")
        time.sleep(10)


wait_for_build()
setup = os.path.join(ROOT, "release", f"QuantiSheet-Beta-Setup-{V}.exe")
if not ONLY_CLAIMS and not os.path.isfile(setup):   # claims-only needs none
    raise SystemExit(f"missing: {setup}")
log = os.path.join(ROOT, ".run", "install_release.log")


class _Done:
    returncode = 0


r = _Done() if ONLY_CLAIMS else subprocess.run([setup, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART",
                    "/CLOSEAPPLICATIONS", "/FORCECLOSEAPPLICATIONS",
                    f"/LOG={log}"], timeout=600)
print(f"installer exit code {r.returncode}")
exe = branding.installed_exe()        # the registered folder
print("installed:", exe, os.path.isfile(exe))
try:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"(Get-Item '{exe}').VersionInfo.ProductVersion"],
        capture_output=True, text=True, timeout=60).stdout.strip()
    print("installed version:", out)
except Exception as e:
    print("version check failed:", e)
# ClaimIT (0.12.29): its own setup, beside QuantiSheet, per user
import glob                                           # noqa: E402
try:                                  # this source's ClaimIT version first
    from quantisheet_claims import __version__ as CV
    want = os.path.join(ROOT, "release", f"ClaimIT-Setup-{CV}.exe")
except Exception:                                     # noqa: BLE001
    want = ""
claims = [want] if want and os.path.isfile(want) else sorted(
    glob.glob(os.path.join(ROOT, "release", "ClaimIT-Setup-*.exe")),
    key=os.path.getmtime)
if claims:
    rc = subprocess.run([claims[-1], "/VERYSILENT", "/SUPPRESSMSGBOXES",
                         "/NORESTART", "/CURRENTUSER",
                         "/LOG=" + os.path.join(ROOT, ".run",
                                                "install_claims.log")],
                        timeout=600).returncode
    cexe = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs",
                        "ClaimIT", "ClaimIT.exe")
    print(f"claims installer exit code {rc}; installed:",
          os.path.isfile(cexe))
sys.exit(r.returncode)
