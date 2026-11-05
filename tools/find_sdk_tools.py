"""Read-only: which Windows packaging tools are on this PC (makeappx,
signtool, the App Certification Kit) and whether Developer Mode is on.
    python tools/find_sdk_tools.py"""
import glob
import os
import shutil
import winreg

for name in ("makeappx.exe", "signtool.exe", "appcert.exe"):
    hits = [shutil.which(name)] if shutil.which(name) else []
    for base in (r"C:\Program Files (x86)\Windows Kits\10\bin",
                 r"C:\Program Files\Windows Kits\10\bin",
                 r"C:\Program Files (x86)\Windows Kits\10\App Certification Kit"):
        hits += glob.glob(os.path.join(base, "**", name), recursive=True)
    print(name, "->", hits[:4] or "not found")
try:
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows"
                        r"\CurrentVersion\AppModelUnlock") as k:
        v = winreg.QueryValueEx(k, "AllowDevelopmentWithoutDevLicense")[0]
    print("Developer Mode:", "on" if v == 1 else "off")
except OSError:
    print("Developer Mode: off (not set)")
import platform
print("Windows:", platform.version(), platform.release())
