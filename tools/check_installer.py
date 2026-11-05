"""Install the built setup into a scratch folder, check the installed
program starts and opens drawings, then uninstall it again.

    python tools/check_installer.py [path\\to\\QuantiSheet-Beta-Setup-x.exe]
"""
import glob
import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def main():
    setup = sys.argv[1] if len(sys.argv) > 1 else sorted(
        glob.glob(os.path.join(ROOT, "release", "QuantiSheet-Beta-Setup-*.exe")),
        key=os.path.getmtime)[-1]
    target = os.path.join(tempfile.gettempdir(), "QuantiSheetInstallCheck")
    print("setup:", setup, f"({os.path.getsize(setup) / 1e6:.0f} MB)")
    t = time.time()
    p = subprocess.run([setup, "/VERYSILENT", "/SUPPRESSMSGBOXES",
                        "/NORESTART", "/CURRENTUSER", f"/DIR={target}",
                        "/TASKS=", "/NOICONS", "/LOG=" + os.path.join(
                            tempfile.gettempdir(), "quantisheet-setup.log")],
                       timeout=600, creationflags=NOWIN)
    print(f"install exit {p.returncode} in {time.time() - t:.0f}s")
    exe = os.path.join(target, "QuantiSheet.exe")
    print("installed exe:", os.path.exists(exe))
    print("no agreement (1.0.0):", not os.path.exists(os.path.join(
        target, "BETA-AGREEMENT.txt")))
    print("extras script:", os.path.exists(os.path.join(
        target, "extras", "install_deps.ps1")))
    out = os.path.join(tempfile.gettempdir(), "quantisheet-installed-smoke.json")
    if os.path.exists(out):
        os.remove(out)
    env = dict(os.environ, QUANTISHEET_SMOKE=out, QT_QPA_PLATFORM="offscreen")
    subprocess.run([exe], env=env, timeout=300, creationflags=NOWIN)
    res = {"ok": False}
    if os.path.exists(out):
        with open(out) as fh:
            res = json.load(fh)
    for name, c in res.get("checks", {}).items():
        print(f"  {'ok ' if c['ok'] else 'BAD'} {name}")
    print("installed program works:", res["ok"])
    un = sorted(glob.glob(os.path.join(target, "unins*.exe")))
    if un:
        p = subprocess.run([un[-1], "/VERYSILENT", "/SUPPRESSMSGBOXES",
                            "/NORESTART"], timeout=300, creationflags=NOWIN)
        time.sleep(3)
        print(f"uninstall exit {p.returncode}; exe left behind:",
              os.path.exists(exe))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
