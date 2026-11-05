"""Compile installer/<name>.iss with Inno Setup and print its messages
(a quick check of the [Code] section; the setup it makes goes to a temp
folder and is thrown away)."""
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import build_installer                                   # noqa: E402

name = sys.argv[1] if len(sys.argv) > 1 else "quantisheet"
iscc = build_installer.find_iscc()
src = os.path.join(os.environ.get("LOCALAPPDATA", ""), "QuantiSheetBuild",
                   "dist", "QuantiSheet")
out = tempfile.mkdtemp(prefix="iscc-")
r = subprocess.run([iscc, "/DAppVersion=1.0.0", "/DAppPublisher=QuantiSheet",
                    f"/DSourceDir={src}", f"/DOutputDir={out}",
                    "/DOutputBase=check",
                    os.path.join(ROOT, "installer", name + ".iss")],
                   capture_output=True, text=True)
text = (r.stdout + r.stderr).splitlines()
print("\n".join([ln for ln in text if "Compiling" not in ln][-40:]))
print("exit", r.returncode)
